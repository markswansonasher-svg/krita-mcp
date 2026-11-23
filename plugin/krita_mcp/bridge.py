"""
Krita MCP bridge - runs inside Krita.

Opens a small JSON socket server on 127.0.0.1 (port 9877, or KRITA_MCP_PORT) so the
Krita MCP server can drive Krita: make documents and layers, pick brushes and colors,
paint real brush strokes, add SVG vector art, apply filters and export images.

Protocol: one JSON object per line.
    request  {"id": 1, "cmd": "draw_strokes", "params": {...}}
    response {"id": 1, "ok": true, "result": ...}   or   {"id": 1, "ok": false, "error": "..."}

Everything runs on Krita's main (GUI) thread through Qt signals, so the Krita API is
always called safely. Only connections from this computer are accepted.
"""
import base64
import contextlib
import io
import json
import math
import os
import time
import traceback

from krita import Extension, InfoObject, Krita, ManagedColor
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainterPath
from PyQt5.QtNetwork import QHostAddress, QTcpServer
from PyQt5.QtWidgets import QApplication, QMessageBox

PORT = int(os.environ.get("KRITA_MCP_PORT", "9877"))
VERSION = "0.1.0"


class McpError(Exception):
    """An error meant for the caller (shown without a traceback)."""


# ----------------------------------------------------------------------------- helpers

def app():
    return Krita.instance()


def color(value):
    """'#rrggbb', '#rrggbbaa', 'red', [r,g,b] or [r,g,b,a] (0-255) -> QColor."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        c = QColor(*[int(v) for v in value])
    else:
        s = str(value).strip()
        if s.startswith("#") and len(s) == 9:      # CSS-style #rrggbbaa
            c = QColor(s[:7])
            c.setAlpha(int(s[7:9], 16))
        else:
            c = QColor(s)
    if not c.isValid():
        raise McpError(f"Not a color: {value!r}. Use '#rrggbb', '#rrggbbaa', a name like 'red' or [r,g,b].")
    return c


def hexof(qc):
    return qc.name(QColor.HexRgb) + ("" if qc.alpha() == 255 else f"{qc.alpha():02x}")


def managed(qc, view):
    return ManagedColor.fromQColor(qc, view.canvas() if view else None)


def doc_required(params=None):
    params = params or {}
    name = params.get("document")
    if name:
        for d in app().documents():
            if d.name() == name or os.path.basename(d.fileName() or "") == name or d.fileName() == name:
                return d
        raise McpError(f"No open document called {name!r}. Open ones: {[d.name() for d in app().documents()]}")
    d = app().activeDocument()
    if d is None:
        docs = app().documents()
        if docs:
            return docs[-1]
        raise McpError("No document is open. Use new_document or open_document first.")
    return d


def same_doc(a, b):
    try:
        return a == b
    except Exception:
        return a.rootNode().uniqueId() == b.rootNode().uniqueId()


def view_for(doc, activate=True):
    """The view showing doc (made active, since Krita paints with the active view's brush)."""
    win = app().activeWindow() or (app().windows() or [None])[0]
    if win is None:
        raise McpError("Krita has no main window open.")
    for w in app().windows():
        for v in w.views():
            if v.document() is not None and same_doc(v.document(), doc):
                if activate:
                    w.activate()
                    w.showView(v)
                    v.setVisible()
                return v
    v = win.addView(doc)
    return v


def walk(node):
    for c in node.childNodes():
        yield c
        yield from walk(c)


def find_node(doc, ref, required=True):
    """Layer by name, by 'Group/Layer' path, or by unique id. None/'' -> the active layer."""
    if not ref:
        n = doc.activeNode()
        if n is None and required:
            raise McpError("No active layer.")
        return n
    ref = str(ref)
    for n in walk(doc.rootNode()):
        if n.uniqueId().toString().strip("{}") == ref.strip("{}"):
            return n
    if "/" in ref:
        node = doc.rootNode()
        for part in ref.split("/"):
            node = next((c for c in node.childNodes() if c.name() == part), None)
            if node is None:
                break
        if node is not None:
            return node
    for n in walk(doc.rootNode()):
        if n.name() == ref:
            return n
    if required:
        raise McpError(f"No layer called {ref!r}. Layers: {[n.name() for n in walk(doc.rootNode())]}")
    return None


def node_info(n, active=None):
    info = {
        "name": n.name(),
        "id": n.uniqueId().toString().strip("{}"),
        "type": n.type(),
        "visible": n.visible(),
        "opacity": round(n.opacity() / 255, 3),
        "blend_mode": n.blendingMode(),
        "locked": n.locked(),
        "alpha_locked": n.alphaLocked(),
    }
    b = n.bounds()
    if b.width() > 0:
        info["bounds"] = [b.x(), b.y(), b.width(), b.height()]
    if active is not None and n.uniqueId() == active.uniqueId():
        info["active"] = True
    kids = n.childNodes()
    if kids and n.type() == "grouplayer":
        info["children"] = [node_info(c, active) for c in reversed(kids)]   # top first
    return info


def finish(doc):
    doc.waitForDone()
    doc.refreshProjection()


def png_b64(img, max_size=None):
    if max_size and max(img.width(), img.height()) > max_size:
        img = img.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return {"png_base64": base64.b64encode(bytes(ba)).decode("ascii"),
            "width": img.width(), "height": img.height()}


def qimage_bytes(img):
    img = img.convertToFormat(QImage.Format_ARGB32)     # = BGRA in memory = Krita RGBA/U8 layout
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    return img, bytes(ptr)


def require_rgba8(doc):
    if doc.colorModel() != "RGBA" or doc.colorDepth() != "U8":
        raise McpError(f"This needs an 8-bit RGBA document (this one is {doc.colorModel()}/{doc.colorDepth()}).")


# ----------------------------------------------------------------------------- brush state

def apply_brush(view, p):
    """Apply any brush settings given in p to the view. Returns the previous background color."""
    if p.get("preset"):
        presets = app().resources("preset")
        res = presets.get(p["preset"])
        if res is None:
            low = p["preset"].lower()
            matches = [k for k in presets if low in k.lower()]
            if not matches:
                raise McpError(f"No brush preset matching {p['preset']!r}. Try list_brushes.")
            res = presets[sorted(matches, key=len)[0]]
        view.activateResource(res) if hasattr(view, "activateResource") else view.setCurrentBrushPreset(res)
    if p.get("color") is not None:
        view.setForeGroundColor(managed(color(p["color"]), view))
    if p.get("size") is not None:
        view.setBrushSize(float(p["size"]))
    if p.get("opacity") is not None:
        view.setPaintingOpacity(float(p["opacity"]))
    if p.get("flow") is not None:
        view.setPaintingFlow(float(p["flow"]))
    if p.get("blend_mode"):
        view.setCurrentBlendingMode(p["blend_mode"])
    if p.get("eraser") is not None:
        view.setEraserMode(bool(p["eraser"]))


def brush_state(view):
    out = {}
    with contextlib.suppress(Exception):
        out["preset"] = view.currentBrushPreset().name()
    with contextlib.suppress(Exception):
        out["size"] = view.brushSize()
    with contextlib.suppress(Exception):
        out["opacity"] = round(view.paintingOpacity(), 3)
    with contextlib.suppress(Exception):
        out["flow"] = round(view.paintingFlow(), 3)
    with contextlib.suppress(Exception):
        out["blend_mode"] = view.currentBlendingMode()
    with contextlib.suppress(Exception):
        out["eraser"] = view.eraserMode()
    with contextlib.suppress(Exception):
        out["color"] = hexof(view.foregroundColor().colorForCanvas(view.canvas()))
    with contextlib.suppress(Exception):
        out["background_color"] = hexof(view.backgroundColor().colorForCanvas(view.canvas()))
    return out


# ----------------------------------------------------------------------------- geometry

def pts(points):
    out = []
    for p in points:
        if isinstance(p, dict):
            out.append((float(p["x"]), float(p["y"]), float(p.get("pressure", 1.0))))
        else:
            out.append((float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 1.0))
    if not out:
        raise McpError("A stroke needs at least one point.")
    return out


def smooth_path(points, closed=False, smooth=True):
    """QPainterPath through the points; smooth=True uses Catmull-Rom curves."""
    path = QPainterPath(QPointF(points[0][0], points[0][1]))
    if len(points) == 1:
        path.lineTo(QPointF(points[0][0] + 0.01, points[0][1]))     # a dot
        return path
    p = [(x, y) for x, y, _ in points]
    if closed:
        p = p + [p[0]]
    if not smooth or len(p) < 3:
        for x, y in p[1:]:
            path.lineTo(QPointF(x, y))
        return path
    n = len(p)
    for i in range(n - 1):
        p0 = p[i - 1] if i > 0 else (p[-2] if closed else p[i])
        p1, p2 = p[i], p[i + 1]
        p3 = p[i + 2] if i + 2 < n else (p[1] if closed else p2)
        c1 = QPointF(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = QPointF(p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        path.cubicTo(c1, c2, QPointF(*p2))
    return path


def resample(points, step=2.0):
    """Densify a polyline (with pressure) so pressure changes smoothly along it."""
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        k = max(1, int(d / step))
        for i in range(1, k + 1):
            t = i / k
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t))
    return out


def catmull_points(points, per_seg=8):
    """Smooth a point list (keeping pressure) for pressure strokes."""
    if len(points) < 3:
        return points
    out = []
    n = len(points)
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        for s in range(per_seg):
            t = s / per_seg
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t +
                                    (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 +
                                    (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in range(3)))
    out.append(points[-1])
    return out


_LINE_PRESSURE = None


def paint_line(node, a, b):
    """node.paintLine with pressure when this Krita supports it."""
    global _LINE_PRESSURE
    from PyQt5.QtCore import QPoint
    pa, pb = QPoint(round(a[0]), round(a[1])), QPoint(round(b[0]), round(b[1]))
    if _LINE_PRESSURE is not False:
        try:
            node.paintLine(pa, pb, max(a[2], 0.0), max(b[2], 0.0), "ForegroundColor")
            _LINE_PRESSURE = True
            return
        except TypeError:
            _LINE_PRESSURE = False
    node.paintLine(pa, pb)


# ----------------------------------------------------------------------------- commands

class Commands:
    # --- general ---------------------------------------------------------------
    def ping(self, p):
        return {"pong": True, "krita": app().version(), "bridge": VERSION}

    def status(self, p):
        a = app()
        out = {"krita": a.version(), "bridge": VERSION, "port": PORT,
               "documents": [d.name() or os.path.basename(d.fileName() or "") for d in a.documents()]}
        d = a.activeDocument()
        if d is not None:
            out["active_document"] = {
                "name": d.name(), "file": d.fileName(), "width": d.width(), "height": d.height(),
                "resolution": d.resolution(), "color_model": d.colorModel(), "color_depth": d.colorDepth(),
                "modified": d.modified(),
                "active_layer": d.activeNode().name() if d.activeNode() else None,
            }
            with contextlib.suppress(McpError):
                out["brush"] = brush_state(view_for(d, activate=False))
        return out

    # --- documents -------------------------------------------------------------
    def new_document(self, p):
        w, h = int(p.get("width", 1920)), int(p.get("height", 1080))
        name = p.get("name") or "Untitled"
        d = app().createDocument(w, h, name, p.get("color_model", "RGBA"), p.get("color_depth", "U8"),
                                 "", float(p.get("resolution", 300)))
        win = app().activeWindow() or (app().windows() or [None])[0]
        if win is None:
            raise McpError("Krita has no main window open.")
        win.addView(d)
        app().setActiveDocument(d) if hasattr(app(), "setActiveDocument") else None
        bg = p.get("background", "#ffffff")
        layers = [n for n in d.rootNode().childNodes() if n.type() == "paintlayer"]
        if bg not in (None, "", "transparent") and layers and d.colorModel() == "RGBA" and d.colorDepth() == "U8":
            img = QImage(w, h, QImage.Format_ARGB32)
            img.fill(color(bg))
            img, data = qimage_bytes(img)
            layers[0].setPixelData(data, 0, 0, w, h)
            layers[0].setName("Background")
        # a fresh layer to paint on, above the background
        paint = d.createNode("Paint", "paintlayer")
        d.rootNode().addChildNode(paint, None)
        d.setActiveNode(paint)
        finish(d)
        return {"name": d.name(), "width": w, "height": h, "active_layer": "Paint"}

    def open_document(self, p):
        path = os.path.abspath(os.path.expanduser(p["path"]))
        if not os.path.exists(path):
            raise McpError(f"File not found: {path}")
        d = app().openDocument(path)
        if d is None:
            raise McpError(f"Krita could not open {path}")
        (app().activeWindow() or app().windows()[0]).addView(d)
        finish(d)
        return {"name": d.name(), "file": d.fileName(), "width": d.width(), "height": d.height()}

    def list_documents(self, p):
        act = app().activeDocument()
        return [{"name": d.name(), "file": d.fileName(), "width": d.width(), "height": d.height(),
                 "modified": d.modified(), "active": act is not None and same_doc(d, act)}
                for d in app().documents()]

    def switch_document(self, p):
        d = doc_required({"document": p["document"]})
        view_for(d)
        return {"active": d.name()}

    def resize_canvas(self, p):
        d = doc_required(p)
        d.resizeImage(int(p.get("x", 0)), int(p.get("y", 0)), int(p["width"]), int(p["height"]))
        finish(d)
        return {"width": d.width(), "height": d.height()}

    def scale_image(self, p):
        d = doc_required(p)
        d.scaleImage(int(p["width"]), int(p["height"]), d.xRes(), d.yRes(), p.get("filter", "Bicubic"))
        finish(d)
        return {"width": d.width(), "height": d.height()}

    def save(self, p):
        """Save as .kra (or .psd/.ora...) - keeps layers."""
        d = doc_required(p)
        path = p.get("path")
        d.setBatchmode(True)
        try:
            if path:
                path = os.path.abspath(os.path.expanduser(path))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                ok = d.saveAs(path)
            else:
                if not d.fileName():
                    raise McpError("This document has never been saved; give a path (for example C:/art/picture.kra).")
                ok = d.save()
        finally:
            d.setBatchmode(False)
        if not ok:
            raise McpError("Krita could not save the file.")
        return {"file": d.fileName()}

    def export_image(self, p):
        """Flattened image (png/jpg/webp/bmp/tif) - or any Krita export format via exportImage."""
        d = doc_required(p)
        finish(d)
        path = os.path.abspath(os.path.expanduser(p["path"]))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ext = os.path.splitext(path)[1].lower()
        layer = p.get("layer")
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff") and d.colorDepth() == "U8":
            if layer:
                n = find_node(d, layer)
                img = n.thumbnail(d.width(), d.height())
            else:
                img = d.projection(0, 0, d.width(), d.height())
            if p.get("crop_to_content"):
                b = (find_node(d, layer).bounds() if layer else None)
                if b is None:
                    b = rect_union([n.bounds() for n in d.rootNode().childNodes() if n.visible()])
                if b and b.width() > 0:
                    img = img.copy(b)
            if p.get("width") or p.get("height"):
                w = int(p.get("width") or 0)
                h = int(p.get("height") or 0)
                if w and h:
                    img = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation if not p.get("pixel_art") else Qt.FastTransformation)
                elif w:
                    img = img.scaledToWidth(w, Qt.FastTransformation if p.get("pixel_art") else Qt.SmoothTransformation)
                else:
                    img = img.scaledToHeight(h, Qt.FastTransformation if p.get("pixel_art") else Qt.SmoothTransformation)
            if ext in (".jpg", ".jpeg", ".bmp"):
                flat = QImage(img.size(), QImage.Format_RGB32)
                flat.fill(color(p.get("matte", "#ffffff")))
                from PyQt5.QtGui import QPainter
                painter = QPainter(flat)
                painter.drawImage(0, 0, img)
                painter.end()
                img = flat
            if not img.save(path, None, int(p.get("quality", 92))):
                raise McpError(f"Could not write {path}")
            return {"file": path, "width": img.width(), "height": img.height()}
        d.setBatchmode(True)
        try:
            ok = d.exportImage(path, InfoObject())
        finally:
            d.setBatchmode(False)
        if not ok:
            raise McpError(f"Krita could not export {path}")
        return {"file": path}

    def close_document(self, p):
        d = doc_required(p)
        name = d.name()
        if d.modified() and not p.get("discard_changes"):
            raise McpError("The document has unsaved changes. Save it first, or pass discard_changes=true.")
        d.setModified(False)
        d.close()
        return {"closed": name}

    def look(self, p):
        """A PNG of the canvas (or one layer, or a region) for Claude to see."""
        d = doc_required(p)
        finish(d)
        max_size = int(p.get("max_size", 1024))
        if p.get("layer"):
            n = find_node(d, p["layer"])
            img = n.thumbnail(d.width(), d.height())
        else:
            img = d.projection(0, 0, d.width(), d.height())
        r = p.get("region")
        if r:
            img = img.copy(int(r[0]), int(r[1]), int(r[2]), int(r[3]))
        if p.get("checker", True) and img.hasAlphaChannel():
            from PyQt5.QtGui import QPainter
            bg = QImage(img.size(), QImage.Format_RGB32)
            bg.fill(QColor("#ffffff"))
            painter = QPainter(bg)
            s = max(8, max(img.width(), img.height()) // 64)
            for yy in range(0, img.height(), s):
                for xx in range(0, img.width(), s):
                    if (xx // s + yy // s) % 2:
                        painter.fillRect(xx, yy, s, s, QColor("#d8d8d8"))
            painter.drawImage(0, 0, img)
            painter.end()
            img = bg
        out = png_b64(img, max_size)
        out["document_size"] = [d.width(), d.height()]
        return out

    # --- layers ----------------------------------------------------------------
    def list_layers(self, p):
        d = doc_required(p)
        act = d.activeNode()
        return {"document": d.name(), "size": [d.width(), d.height()],
                "layers": [node_info(c, act) for c in reversed(d.rootNode().childNodes())]}

    def add_layer(self, p):
        d = doc_required(p)
        kind = {"paint": "paintlayer", "group": "grouplayer", "vector": "vectorlayer",
                "paintlayer": "paintlayer", "grouplayer": "grouplayer", "vectorlayer": "vectorlayer"}.get(
            p.get("type", "paint"))
        if kind is None:
            raise McpError("type must be paint, group or vector.")
        n = d.createNode(p.get("name") or "Layer", kind)
        parent, above = self._placement(d, p)
        parent.addChildNode(n, above)
        self._layer_props(n, p)
        d.setActiveNode(n)
        finish(d)
        return node_info(n)

    def _placement(self, d, p):
        if p.get("parent"):
            parent = find_node(d, p["parent"])
            if parent.type() != "grouplayer":
                raise McpError(f"{parent.name()!r} is not a group layer.")
            kids = parent.childNodes()
            return parent, (kids[-1] if kids else None)
        act = d.activeNode()
        if act is None or act.parentNode() is None:
            kids = d.rootNode().childNodes()
            return d.rootNode(), (kids[-1] if kids else None)
        return act.parentNode(), act

    def _layer_props(self, n, p):
        if p.get("opacity") is not None:
            n.setOpacity(int(round(float(p["opacity"]) * 255)))
        if p.get("blend_mode"):
            n.setBlendingMode(p["blend_mode"])
        if p.get("visible") is not None:
            n.setVisible(bool(p["visible"]))
        if p.get("locked") is not None:
            n.setLocked(bool(p["locked"]))
        if p.get("alpha_locked") is not None:
            n.setAlphaLocked(bool(p["alpha_locked"]))
        if p.get("new_name"):
            n.setName(p["new_name"])

    def set_layer(self, p):
        d = doc_required(p)
        n = find_node(d, p.get("layer"))
        self._layer_props(n, p)
        if p.get("active"):
            d.setActiveNode(n)
        if p.get("position") is not None:
            parent = n.parentNode()
            kids = [k for k in parent.childNodes() if k.uniqueId() != n.uniqueId()]
            pos = p["position"]                     # "top", "bottom", "up", "down" or an index (0 = bottom)
            cur = [k.uniqueId() for k in parent.childNodes()].index(n.uniqueId())
            idx = {"top": len(kids), "bottom": 0, "up": min(cur + 1, len(kids)),
                   "down": max(cur - 1, 0)}.get(pos, pos)
            kids.insert(max(0, min(int(idx), len(kids))), n)
            parent.setChildNodes(kids)
        finish(d)
        return node_info(n)

    def select_layer(self, p):
        d = doc_required(p)
        n = find_node(d, p["layer"])
        d.setActiveNode(n)
        return {"active": n.name()}

    def delete_layer(self, p):
        d = doc_required(p)
        n = find_node(d, p["layer"])
        name = n.name()
        n.remove()
        finish(d)
        return {"deleted": name}

    def duplicate_layer(self, p):
        d = doc_required(p)
        n = find_node(d, p.get("layer"))
        dup = n.duplicate()
        dup.setName(p.get("name") or n.name() + " copy")
        n.parentNode().addChildNode(dup, n)
        d.setActiveNode(dup)
        finish(d)
        return node_info(dup)

    def merge_down(self, p):
        d = doc_required(p)
        n = find_node(d, p.get("layer"))
        merged = n.mergeDown()
        finish(d)
        return node_info(merged) if merged else {"merged": True}

    def flatten(self, p):
        d = doc_required(p)
        d.flatten()
        finish(d)
        return {"layers": [c.name() for c in d.rootNode().childNodes()]}

    def clear_layer(self, p):
        d = doc_required(p)
        require_rgba8(d)
        n = find_node(d, p.get("layer"))
        b = n.bounds()
        if b.width() > 0:
            n.setPixelData(bytes(b.width() * b.height() * 4), b.x(), b.y(), b.width(), b.height())
        finish(d)
        return {"cleared": n.name()}

    def fill_layer(self, p):
        d = doc_required(p)
        require_rgba8(d)
        n = find_node(d, p.get("layer"))
        x, y, w, h = [int(v) for v in (p.get("rect") or [0, 0, d.width(), d.height()])]
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(color(p.get("color", "#ffffff")))
        img, data = qimage_bytes(img)
        n.setPixelData(data, x, y, w, h)
        finish(d)
        return {"filled": n.name(), "rect": [x, y, w, h]}

    def place_image(self, p):
        """Put an image file onto a new paint layer (references, textures, photos)."""
        d = doc_required(p)
        require_rgba8(d)
        path = os.path.abspath(os.path.expanduser(p["path"]))
        img = QImage(path)
        if img.isNull():
            raise McpError(f"Could not read image {path}")
        if p.get("width") or p.get("height"):
            w = int(p.get("width") or img.width() * int(p["height"]) / img.height())
            h = int(p.get("height") or img.height() * w / img.width())
            img = img.scaled(w, h, Qt.IgnoreAspectRatio,
                             Qt.FastTransformation if p.get("pixel_art") else Qt.SmoothTransformation)
        img, data = qimage_bytes(img)
        n = d.createNode(p.get("name") or os.path.splitext(os.path.basename(path))[0], "paintlayer")
        parent, above = self._placement(d, p)
        parent.addChildNode(n, above)
        n.setPixelData(data, int(p.get("x", 0)), int(p.get("y", 0)), img.width(), img.height())
        self._layer_props(n, p)
        d.setActiveNode(n)
        finish(d)
        return node_info(n)

    def add_svg(self, p):
        """Vector shapes from SVG markup onto a vector layer (crisp, editable in Krita)."""
        d = doc_required(p)
        svg = p["svg"]
        n = find_node(d, p.get("layer"), required=False) if p.get("layer") else None
        if n is None or n.type() != "vectorlayer":
            n = d.createNode(p.get("layer") or p.get("name") or "Vector", "vectorlayer")
            parent, above = self._placement(d, p)
            parent.addChildNode(n, above)
            # createNode hands back a plain Node; the tree gives the typed VectorLayer
            uid = n.uniqueId()
            n = next(c for c in parent.childNodes() if c.uniqueId() == uid)
        if "<svg" not in svg:
            # bare shapes in document pixels -> wrap them so 1 SVG unit = 1 pixel
            w_in, h_in = d.width() / d.xRes(), d.height() / d.yRes()
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_in}in" height="{h_in}in" '
                   f'viewBox="0 0 {d.width()} {d.height()}">{svg}</svg>')
        shapes = n.addShapesFromSvg(svg)
        d.setActiveNode(n)
        if p.get("rasterize"):
            n = self._rasterize(d, n)
        finish(d)
        info = node_info(n)
        info["shapes_added"] = len(shapes) if shapes is not None else None
        return info

    def _rasterize(self, d, n):
        raster = d.createNode(n.name(), "paintlayer")
        n.parentNode().addChildNode(raster, n)
        finish(d)
        for _ in range(50):                 # vector shapes render asynchronously
            data = bytes(n.projectionPixelData(0, 0, d.width(), d.height()))
            if any(data[3::4]):
                break
            QApplication.processEvents()
            time.sleep(0.02)
            d.waitForDone()
        raster.setPixelData(data, 0, 0, d.width(), d.height())
        raster.setOpacity(n.opacity())
        raster.setBlendingMode(n.blendingMode())
        n.remove()
        d.setActiveNode(raster)
        return raster

    # --- brushes & colors ------------------------------------------------------
    def list_brushes(self, p):
        q = (p.get("query") or "").lower()
        names = sorted(k for k in app().resources("preset") if q in k.lower())
        limit = int(p.get("limit", 200))
        return {"count": len(names), "presets": names[:limit]}

    def set_brush(self, p):
        d = doc_required(p)
        v = view_for(d)
        apply_brush(v, p)
        if p.get("background_color") is not None:
            v.setBackGroundColor(managed(color(p["background_color"]), v))
        return brush_state(v)

    def get_brush(self, p):
        return brush_state(view_for(doc_required(p)))

    # --- painting --------------------------------------------------------------
    def draw_strokes(self, p):
        """Real brush strokes with the current (or given) brush. Each stroke:
        {points: [[x,y] or [x,y,pressure]...], color, size, preset, opacity, flow,
         blend_mode, eraser, smooth (default true), closed}"""
        d = doc_required(p)
        n = find_node(d, p.get("layer"))
        if n.type() != "paintlayer":
            raise McpError(f"{n.name()!r} is a {n.type()}; brush strokes need a paint layer.")
        v = view_for(d)
        apply_brush(v, p)
        count = 0
        for s in p.get("strokes", []):
            apply_brush(v, s)
            ps = pts(s["points"])
            smooth = s.get("smooth", p.get("smooth", True))
            if s.get("closed"):
                ps = ps + [ps[0]]
            pressures = {round(q[2], 3) for q in ps}
            if len(pressures) > 1:
                # varying pressure: lots of short segments, each with its own pressures
                dense = resample(catmull_points(ps) if smooth else ps, step=max(1.0, float(s.get("size") or 4) / 6))
                for a, b in zip(dense, dense[1:]):
                    paint_line(n, a, b)
            else:
                pr = ps[0][2]
                if pr != 1.0 and len(ps) >= 2:
                    dense = resample(catmull_points(ps) if smooth else ps, step=4.0)
                    for a, b in zip(dense, dense[1:]):
                        paint_line(n, a, b)
                else:
                    n.paintPath(smooth_path(ps, closed=False, smooth=smooth), "ForegroundColor", "None")
            count += 1
            d.waitForDone()
        finish(d)
        return {"strokes": count, "layer": n.name(), "brush": brush_state(v)}

    def draw_shapes(self, p):
        """Brush-outlined and/or filled shapes. Each shape:
        {type: rect|ellipse|circle|polygon|line|path, x,y,w,h | cx,cy,r | points,
         stroke: color|null, fill: color|null, size, preset, opacity, smooth, closed}"""
        d = doc_required(p)
        n = find_node(d, p.get("layer"))
        if n.type() != "paintlayer":
            raise McpError(f"{n.name()!r} is a {n.type()}; painting needs a paint layer.")
        v = view_for(d)
        apply_brush(v, p)
        old_bg = v.backgroundColor()
        old_fg = v.foregroundColor()
        try:
            for s in p.get("shapes", []):
                brush = {k: s[k] for k in ("preset", "size", "opacity", "flow", "blend_mode", "eraser") if k in s}
                apply_brush(v, brush)
                stroke = s.get("stroke", "current")
                fill = s.get("fill")
                if stroke not in (None, "none", "current"):
                    v.setForeGroundColor(managed(color(stroke), v))
                if fill not in (None, "none"):
                    v.setBackGroundColor(managed(color(fill), v))
                ss = "None" if stroke in (None, "none") else "ForegroundColor"
                fs = "None" if fill in (None, "none") else "BackgroundColor"
                t = s.get("type", "rect")
                if t in ("rect", "rectangle"):
                    n.paintRectangle(QRectF(s["x"], s["y"], s["w"], s["h"]), ss, fs)
                elif t in ("ellipse", "circle"):
                    if "r" in s:
                        r = float(s["r"])
                        rect = QRectF(s["cx"] - r, s["cy"] - r, 2 * r, 2 * r)
                    else:
                        rect = QRectF(s["x"], s["y"], s["w"], s["h"])
                    n.paintEllipse(rect, ss, fs)
                elif t == "polygon":
                    n.paintPolygon([QPointF(q[0], q[1]) for q in pts(s["points"])], ss, fs)
                elif t == "line":
                    q = pts(s["points"])
                    paint_line(n, q[0], q[1])
                elif t == "path":
                    n.paintPath(smooth_path(pts(s["points"]), closed=s.get("closed", False),
                                            smooth=s.get("smooth", True)), ss, fs)
                else:
                    raise McpError(f"Unknown shape type {t!r}.")
                d.waitForDone()
        finally:
            v.setBackGroundColor(old_bg)
            if p.get("keep_stroke_color") is False:
                v.setForeGroundColor(old_fg)
        finish(d)
        return {"shapes": len(p.get("shapes", [])), "layer": n.name()}

    def set_pixels(self, p):
        """Exact pixels (pixel art): {pixels: [[x,y,color], ...]} or {rows: ["..",".."], palette: {"a": "#f00"}, x, y, scale}"""
        d = doc_required(p)
        require_rgba8(d)
        n = find_node(d, p.get("layer"))
        scale = max(1, int(p.get("scale", 1)))
        if p.get("rows"):
            rows = p["rows"]
            pal = {k: color(v) for k, v in (p.get("palette") or {}).items()}
            w, h = max(len(r) for r in rows), len(rows)
            img = QImage(w, h, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            for yy, row in enumerate(rows):
                for xx, ch in enumerate(row):
                    if ch in pal:
                        img.setPixelColor(xx, yy, pal[ch])
            if scale > 1:
                img = img.scaled(w * scale, h * scale, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            x0, y0 = int(p.get("x", 0)), int(p.get("y", 0))
            if p.get("replace", False):
                img, data = qimage_bytes(img)
                n.setPixelData(data, x0, y0, img.width(), img.height())
            else:  # composite over what is there (transparent cells keep the old pixels)
                raw = bytes(n.pixelData(x0, y0, img.width(), img.height()))
                old = QImage(raw, img.width(), img.height(), img.width() * 4, QImage.Format_ARGB32).copy()
                from PyQt5.QtGui import QPainter
                painter = QPainter(old)
                painter.drawImage(0, 0, img)
                painter.end()
                old, data = qimage_bytes(old)
                n.setPixelData(data, x0, y0, old.width(), old.height())
            finish(d)
            return {"layer": n.name(), "rect": [x0, y0, img.width(), img.height()]}
        count = 0
        for x, y, c in p.get("pixels", []):
            qc = color(c)
            px = bytes([qc.blue(), qc.green(), qc.red(), qc.alpha()]) * (scale * scale)
            n.setPixelData(px, int(x) * scale, int(y) * scale, scale, scale)
            count += 1
        finish(d)
        return {"layer": n.name(), "pixels": count}

    def get_pixels(self, p):
        d = doc_required(p)
        require_rgba8(d)
        x, y, w, h = [int(v) for v in p["rect"]]
        if w * h > 64 * 64:
            raise McpError("get_pixels is for small areas (up to 64x64). Use look for bigger ones.")
        if p.get("layer"):
            data = find_node(d, p["layer"]).pixelData(x, y, w, h)
        else:
            img = d.projection(x, y, w, h).convertToFormat(QImage.Format_ARGB32)
            _, data = qimage_bytes(img)
        data = bytes(data)
        rows = []
        for yy in range(h):
            row = []
            for xx in range(w):
                i = (yy * w + xx) * 4
                b, g, r, a = data[i:i + 4]
                row.append(f"#{r:02x}{g:02x}{b:02x}" + ("" if a == 255 else f"{a:02x}"))
            rows.append(row)
        return {"rect": [x, y, w, h], "rows": rows}

    # --- selection, filters, actions ----------------------------------------
    def select(self, p):
        """Rectangular selection ({rect:[x,y,w,h]}), 'all', or 'none'."""
        d = doc_required(p)
        mode = p.get("mode", "rect")
        if mode == "none":
            d.setSelection(None)
            app().action("deselect").trigger()
            return {"selection": None}
        from krita import Selection
        s = Selection()
        if mode == "all":
            s.select(0, 0, d.width(), d.height(), 255)
        else:
            x, y, w, h = [int(v) for v in p["rect"]]
            s.select(x, y, w, h, 255)
        d.setSelection(s)
        return {"selection": [s.x(), s.y(), s.width(), s.height()]}

    def list_filters(self, p):
        return sorted(app().filters())

    def apply_filter(self, p):
        d = doc_required(p)
        n = find_node(d, p.get("layer"))
        f = app().filter(p["filter"])
        if f is None:
            raise McpError(f"No filter {p['filter']!r}. Use list_filters.")
        cfg = f.configuration()
        for k, val in (p.get("settings") or {}).items():
            cfg.setProperty(k, val)
        f.setConfiguration(cfg)
        x, y, w, h = [int(v) for v in (p.get("rect") or [0, 0, d.width(), d.height()])]
        ok = f.apply(n, x, y, w, h)
        ok = True if ok is None else ok
        finish(d)
        if p.get("show_settings"):
            return {"applied": ok, "settings": cfg.properties()}
        return {"applied": ok}

    def filter_settings(self, p):
        f = app().filter(p["filter"])
        if f is None:
            raise McpError(f"No filter {p['filter']!r}.")
        return {k: (v if isinstance(v, (int, float, str, bool)) else str(v))
                for k, v in f.configuration().properties().items()}

    def run_action(self, p):
        d = app().activeDocument()
        if d is not None:
            view_for(d)
        a = app().action(p["action"])
        if a is None:
            raise McpError(f"No Krita action {p['action']!r}. Use list_actions to search.")
        for _ in range(int(p.get("times", 1))):
            a.trigger()
        if d is not None:
            finish(d)
        return {"triggered": p["action"]}

    def list_actions(self, p):
        q = (p.get("query") or "").lower()
        out = []
        for a in app().actions():
            text = a.text().replace("&", "")
            if q in a.objectName().lower() or q in text.lower():
                out.append(f"{a.objectName()}  ({text})")
        return sorted(out)[: int(p.get("limit", 100))]

    def undo(self, p):
        return self.run_action({"action": "edit_undo", "times": p.get("times", 1)})

    def redo(self, p):
        return self.run_action({"action": "edit_redo", "times": p.get("times", 1)})

    # --- escape hatch ------------------------------------------------------
    def execute_python(self, p):
        """Run Python inside Krita. Set `result` to return a value; print() output is returned too."""
        g = {"Krita": Krita, "app": app(), "Application": app(), "doc": app().activeDocument(),
             "QColor": QColor, "QPointF": QPointF, "QRectF": QRectF, "QImage": QImage,
             "QPainterPath": QPainterPath, "ManagedColor": ManagedColor, "InfoObject": InfoObject}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(compile(p["code"], "<claude>", "exec"), g)
        if g.get("doc") is not None:
            with contextlib.suppress(Exception):
                finish(g["doc"])
        res = g.get("result")
        try:
            json.dumps(res)
        except TypeError:
            res = repr(res)
        return {"stdout": out.getvalue()[-20000:], "result": res}


def rect_union(rects):
    rects = [r for r in rects if r.width() > 0]
    if not rects:
        return None
    u = rects[0]
    for r in rects[1:]:
        u = u.united(r)
    return u


# ----------------------------------------------------------------------------- server

class Bridge:
    def __init__(self):
        self.server = QTcpServer()
        self.server.newConnection.connect(self._on_conn)
        self.cmds = Commands()
        self.buffers = {}
        self.error = None

    def start(self):
        if self.server.isListening():
            return True
        if not self.server.listen(QHostAddress.LocalHost, PORT):
            self.error = self.server.errorString()
            return False
        self.error = None
        return True

    def stop(self):
        self.server.close()

    def _on_conn(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self.buffers[id(sock)] = b""
            sock.readyRead.connect(lambda s=sock: self._on_read(s))
            sock.disconnected.connect(lambda s=sock: self._on_gone(s))

    def _on_gone(self, sock):
        self.buffers.pop(id(sock), None)
        sock.deleteLater()

    def _on_read(self, sock):
        self.buffers[id(sock)] = self.buffers.get(id(sock), b"") + bytes(sock.readAll())
        while b"\n" in self.buffers[id(sock)]:
            line, rest = self.buffers[id(sock)].split(b"\n", 1)
            self.buffers[id(sock)] = rest
            if line.strip():
                sock.write((json.dumps(self.handle(line)) + "\n").encode("utf-8"))
                sock.flush()

    def handle(self, line):
        rid = None
        try:
            req = json.loads(line.decode("utf-8"))
            rid = req.get("id")
            name = req.get("cmd", "")
            fn = getattr(self.cmds, name, None)
            if name.startswith("_") or fn is None:
                raise McpError(f"Unknown command {name!r}.")
            return {"id": rid, "ok": True, "result": fn(req.get("params") or {})}
        except McpError as e:
            return {"id": rid, "ok": False, "error": str(e)}
        except KeyError as e:
            return {"id": rid, "ok": False, "error": f"Missing parameter {e}"}
        except Exception as e:
            return {"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}",
                    "traceback": traceback.format_exc()[-4000:]}


class KritaMcpExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self.bridge = Bridge()

    def setup(self):
        self.bridge.start()

    def createActions(self, window):
        a = window.createAction("krita_mcp_status", "Krita MCP (Claude): status", "tools/scripts")
        a.triggered.connect(self._show_status)

    def _show_status(self):
        ok = self.bridge.start()
        if ok:
            msg = f"Krita MCP bridge {VERSION} is listening on 127.0.0.1:{PORT}.\nClaude can draw in Krita."
        else:
            msg = f"Krita MCP could not listen on port {PORT}: {self.bridge.error}"
        QMessageBox.information(None, "Krita MCP", msg)
