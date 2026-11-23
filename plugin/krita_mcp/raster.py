"""
Raster engine for the Krita MCP bridge.

Renders things Krita's scripting API can't paint directly (variable-width ink, grain,
gradients, SVG with gradients, soft edges) into a QImage with QPainter, then commits the
image onto a layer the undoable way: through a temporary layer that is merged down.
Raw Node.setPixelData is not recorded in Krita's undo history; a merge is.
"""
import math
import random

from PyQt5.QtCore import QByteArray, QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QConicalGradient, QGradient, QImage, QLinearGradient,
                         QPainter, QPainterPath, QPolygonF, QRadialGradient)
from PyQt5.QtSvg import QSvgRenderer


class RasterError(Exception):
    pass


# ----------------------------------------------------------------------------- images

def new_image(w, h):
    img = QImage(max(1, int(w)), max(1, int(h)), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    return img


def image_bytes(img):
    """Non-premultiplied BGRA bytes (Krita RGBA/U8 layout), no row padding."""
    img = img.convertToFormat(QImage.Format_ARGB32)
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    return bytes(ptr)


def image_from_bytes(data, w, h):
    return QImage(bytes(data), w, h, w * 4, QImage.Format_ARGB32).copy()


def alpha8_bytes(img):
    """Alpha channel of img as w*h bytes (row padding removed)."""
    a = img.convertToFormat(QImage.Format_Alpha8)
    ptr = a.constBits()
    ptr.setsize(a.byteCount())
    raw = bytes(ptr)
    w, h, bpl = a.width(), a.height(), a.bytesPerLine()
    if bpl == w:
        return raw
    return b"".join(raw[y * bpl:y * bpl + w] for y in range(h))


def alpha8_image(data, w, h):
    return QImage(bytes(data), w, h, w, QImage.Format_Alpha8).copy()


def mask_with(img, mask, mx=0, my=0):
    """Keep img only where mask (any image with alpha, placed at mx,my relative to img) is opaque."""
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    p.drawImage(mx, my, mask)
    p.end()
    return img


def bbox_of(img):
    """Tight bounding box of non-transparent pixels (x, y, w, h) or None. Coarse scan, then refine."""
    a = alpha8_bytes(img)
    w, h = img.width(), img.height()
    rows = [y for y in range(h) if any(a[y * w:(y + 1) * w])]
    if not rows:
        return None
    y0, y1 = rows[0], rows[-1]
    cols_any = bytearray(w)
    for y in range(y0, y1 + 1):
        row = a[y * w:(y + 1) * w]
        for x in range(w):
            if row[x]:
                cols_any[x] = 1
    xs = [x for x in range(w) if cols_any[x]]
    return xs[0], y0, xs[-1] - xs[0] + 1, y1 - y0 + 1


def blur_image(img, radius):
    """Gaussian-ish blur with Qt's blur effect; the image grows by `pad` on each side.
    Returns (blurred, pad)."""
    from PyQt5.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene
    from PyQt5.QtGui import QPixmap
    radius = float(radius)
    pad = int(math.ceil(radius * 2)) + 2
    src = new_image(img.width() + 2 * pad, img.height() + 2 * pad)
    p = QPainter(src)
    p.drawImage(pad, pad, img)
    p.end()
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(src))
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(radius * 2)          # Qt's radius is roughly 2x a Gaussian sigma
    eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    out = new_image(src.width(), src.height())
    p = QPainter(out)
    scene.render(p, QRectF(0, 0, src.width(), src.height()), QRectF(0, 0, src.width(), src.height()))
    p.end()
    return out, pad


# ----------------------------------------------------------------------------- colors & paint

def qcolor(value):
    if value is None:
        return None
    if isinstance(value, QColor):
        return value
    if isinstance(value, (list, tuple)):
        return QColor(*[int(v) for v in value])
    s = str(value).strip()
    if s.startswith("#") and len(s) == 9:
        c = QColor(s[:7])
        c.setAlpha(int(s[7:9], 16))
    else:
        c = QColor(s)
    if not c.isValid():
        raise RasterError(f"Not a color: {value!r}")
    return c


_SPREAD = {"pad": QGradient.PadSpread, "reflect": QGradient.ReflectSpread, "repeat": QGradient.RepeatSpread}


def gradient(spec):
    """{type: linear|radial|conical, stops: [[pos, color], ...] or [color, color...], ...}
    linear: x1,y1,x2,y2   radial: cx,cy,r (+ fx,fy focal)   conical: cx,cy,angle."""
    t = spec.get("type", "linear")
    if t == "linear":
        g = QLinearGradient(spec["x1"], spec["y1"], spec["x2"], spec["y2"])
    elif t == "radial":
        g = QRadialGradient(QPointF(spec["cx"], spec["cy"]), spec["r"],
                            QPointF(spec.get("fx", spec["cx"]), spec.get("fy", spec["cy"])))
    elif t == "conical":
        g = QConicalGradient(spec["cx"], spec["cy"], spec.get("angle", 0))
    else:
        raise RasterError(f"Unknown gradient type {t!r}")
    stops = spec.get("stops") or ["#000000", "#ffffff"]
    if not isinstance(stops[0], (list, tuple)) or isinstance(stops[0][0], str):
        n = len(stops)
        stops = [[i / max(1, n - 1), c] for i, c in enumerate(stops)]
    for pos, c in stops:
        g.setColorAt(float(pos), qcolor(c))
    g.setSpread(_SPREAD.get(spec.get("spread", "pad"), QGradient.PadSpread))
    return g


def brush_for(fill):
    """A color string or a gradient dict -> QBrush."""
    if isinstance(fill, dict):
        return QBrush(gradient(fill))
    return QBrush(qcolor(fill))


# ----------------------------------------------------------------------------- grain

_GRAIN = {}


def grain_tile(strength, scale=1, seed=7):
    """A tiling image whose alpha is 255 minus noise; DestinationIn with it adds paper grain."""
    key = (round(strength, 2), int(scale), seed)
    if key in _GRAIN:
        return _GRAIN[key]
    rnd = random.Random(seed)
    n = 96
    small = QImage(n, n, QImage.Format_ARGB32)
    for y in range(n):
        for x in range(n):
            v = rnd.random()
            v = v * v                    # mostly light, some deep pits - like paper tooth
            a = int(255 * (1 - strength * v))
            small.setPixel(x, y, (a << 24) | 0xFFFFFF)
    tile = small if scale <= 1 else small.scaled(n * scale, n * scale, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    _GRAIN[key] = tile
    return tile


def apply_grain(img, strength, scale=1, ox=0, oy=0):
    if strength <= 0:
        return img
    tile = grain_tile(min(1.0, strength), scale)
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    br = QBrush(tile)
    # anchor the texture to the canvas so neighbouring strokes share the same paper
    from PyQt5.QtGui import QTransform
    br.setTransform(QTransform.fromTranslate(-ox, -oy))
    p.fillRect(img.rect(), br)
    p.end()
    return img


# ----------------------------------------------------------------------------- geometry

def catmull(points, per_seg=10):
    """Smooth a list of tuples (any length) with Catmull-Rom."""
    if len(points) < 3:
        return list(points)
    out = []
    n = len(points)
    k = len(points[0])
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1, p2 = points[i], points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        for s in range(per_seg):
            t = s / per_seg
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t +
                                    (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2 +
                                    (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in range(k)))
    out.append(tuple(points[-1]))
    return out


def resample(points, step):
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        k = max(1, int(math.ceil(d / step)))
        for i in range(1, k + 1):
            t = i / k
            out.append(tuple(a[j] + (b[j] - a[j]) * t for j in range(len(a))))
    return out


def path_from_points(points, closed=False, smooth=True):
    pts = [(p[0], p[1]) for p in points]
    path = QPainterPath(QPointF(*pts[0]))
    if smooth and len(pts) >= 3:
        ring = pts + [pts[0]] if closed else pts
        n = len(ring)
        for i in range(n - 1):
            p0 = ring[i - 1] if i > 0 else (ring[-2] if closed else ring[i])
            p1, p2 = ring[i], ring[i + 1]
            p3 = ring[i + 2] if i + 2 < n else (ring[1] if closed else p2)
            path.cubicTo(QPointF(p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6),
                         QPointF(p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6),
                         QPointF(*p2))
    else:
        for p in pts[1:]:
            path.lineTo(QPointF(*p))
        if closed:
            path.closeSubpath()
    return path


def shape_path(s):
    """A shape dict -> QPainterPath (doc pixels).
    rect: x,y,w,h (+ radius)  ellipse: x,y,w,h  circle: cx,cy,r  polygon/path: points (+smooth, closed)."""
    t = s.get("type", "rect")
    path = QPainterPath()
    if t in ("rect", "rectangle"):
        r = float(s.get("radius", 0))
        if r:
            path.addRoundedRect(QRectF(s["x"], s["y"], s["w"], s["h"]), r, r)
        else:
            path.addRect(QRectF(s["x"], s["y"], s["w"], s["h"]))
    elif t == "ellipse":
        path.addEllipse(QRectF(s["x"], s["y"], s["w"], s["h"]))
    elif t == "circle":
        r = float(s["r"])
        path.addEllipse(QPointF(s["cx"], s["cy"]), r, r)
    elif t == "polygon":
        path.addPolygon(QPolygonF([QPointF(p[0], p[1]) for p in s["points"]]))
        path.closeSubpath()
    elif t == "path":
        path = path_from_points(s["points"], closed=s.get("closed", True), smooth=s.get("smooth", True))
    else:
        raise RasterError(f"Unknown shape type {t!r}")
    path.setFillRule(Qt.WindingFill)
    return path


# ----------------------------------------------------------------------------- ink ribbons

def ink_samples(points, size, smooth=True, taper=None, min_width=0.0):
    """points [(x, y, pressure)] -> dense [(x, y, half_width)]."""
    pts = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 1.0) for p in points]
    if smooth:
        pts = catmull(pts, per_seg=8)
    step = max(0.4, size * 0.12)
    pts = resample(pts, step) if len(pts) > 1 else pts
    n = len(pts)
    out = []
    # optional automatic taper (fraction of length at each end)
    if taper:
        t0, t1 = (taper, taper) if not isinstance(taper, (list, tuple)) else taper
        total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])) or 1
        acc = 0.0
        prev = pts[0]
    for i, (x, y, pr) in enumerate(pts):
        if taper:
            acc += math.hypot(x - prev[0], y - prev[1])
            prev = (x, y)
            f = min(1.0, max(0.0, acc / total))
            if t0 and f < t0:
                pr *= max(0.0, math.sin(0.5 * math.pi * f / t0)) ** 0.8
            if t1 and f > 1 - t1:
                pr *= max(0.0, math.sin(0.5 * math.pi * (1 - f) / t1)) ** 0.8
        hw = max(min_width, size * max(0.0, pr)) / 2
        out.append((x, y, hw))
    return out


def paint_ink(painter, samples):
    """Fill the union of circles + connecting quads (opaque white on a mask painter)."""
    painter.setPen(Qt.NoPen)
    for (x, y, r) in samples:
        if r > 0.05:
            painter.drawEllipse(QPointF(x, y), r, r)
    for (x0, y0, r0), (x1, y1, r1) in zip(samples, samples[1:]):
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 1e-6 or (r0 < 0.05 and r1 < 0.05):
            continue
        nx, ny = -dy / d, dx / d
        painter.drawPolygon(QPolygonF([QPointF(x0 + nx * r0, y0 + ny * r0), QPointF(x1 + nx * r1, y1 + ny * r1),
                                       QPointF(x1 - nx * r1, y1 - ny * r1), QPointF(x0 - nx * r0, y0 - ny * r0)]))


def render_ink_strokes(strokes, doc_w, doc_h, defaults):
    """Render ink strokes into one image (cropped to their bounds). Returns (img, x, y) or None.
    Each stroke: points, size, color (or gradient dict), opacity, grain, taper, min_width, smooth."""
    pieces = []
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for s in strokes:
        st = dict(defaults)
        st.update({k: v for k, v in s.items() if v is not None})
        size = float(st.get("size") or 8)
        samples = ink_samples(st["points"], size, smooth=st.get("smooth", True), taper=st.get("taper"),
                              min_width=float(st.get("min_width", 0)))
        for (x, y, r) in samples:
            x0, y0, x1, y1 = min(x0, x - r), min(y0, y - r), max(x1, x + r), max(y1, y + r)
        pieces.append((st, samples))
    if not pieces:
        return None
    pad = 3
    bx, by = max(0, int(math.floor(x0)) - pad), max(0, int(math.floor(y0)) - pad)
    bx1, by1 = min(doc_w, int(math.ceil(x1)) + pad), min(doc_h, int(math.ceil(y1)) + pad)
    if bx1 <= bx or by1 <= by:
        return None
    out = new_image(bx1 - bx, by1 - by)
    for st, samples in pieces:
        mask = new_image(out.width(), out.height())
        p = QPainter(mask)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(-bx, -by)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        paint_ink(p, samples)
        p.end()
        if st.get("grain"):
            apply_grain(mask, float(st["grain"]), int(st.get("grain_scale", 1)), bx, by)
        # color the mask
        layer = new_image(out.width(), out.height())
        p = QPainter(layer)
        p.translate(-bx, -by)
        p.fillRect(QRectF(bx, by, out.width(), out.height()), brush_for(st.get("color", "#000000")))
        p.end()
        mask_with(layer, mask)
        p = QPainter(out)
        p.setOpacity(float(st.get("opacity", 1.0)))
        mode = st.get("mode", "normal")
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut if mode == "erase"
                             else QPainter.CompositionMode_SourceOver)
        p.drawImage(0, 0, layer)
        p.end()
    return out, bx, by


# ----------------------------------------------------------------------------- fills

def render_fills(shapes, doc_w, doc_h):
    """Antialiased filled/outlined shapes with colors or gradients. Returns (img, 0, 0) full-doc."""
    out = new_image(doc_w, doc_h)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    for s in shapes:
        path = shape_path(s)
        p.setOpacity(float(s.get("opacity", 1.0)))
        if s.get("erase"):                      # cut this shape out of what the call drew so far
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            p.fillPath(path, QBrush(QColor(0, 0, 0)))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            continue
        if s.get("fill") not in (None, "none"):
            p.fillPath(path, brush_for(s["fill"]))
        if s.get("stroke") not in (None, "none"):
            from PyQt5.QtGui import QPen
            pen = QPen(brush_for(s["stroke"]), float(s.get("stroke_width", 2)))
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            p.strokePath(path, pen)
    p.end()
    return out, 0, 0


def render_svg(svg, doc_w, doc_h):
    """Render SVG markup in document pixels. Bare elements are wrapped in a doc-sized <svg>."""
    if "<svg" not in svg:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
               f'width="{doc_w}" height="{doc_h}" viewBox="0 0 {doc_w} {doc_h}">{svg}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not r.isValid():
        raise RasterError("The SVG could not be parsed (Qt supports SVG Tiny 1.2: shapes, paths, "
                          "gradients, opacity, transforms, text - no filters or masks).")
    out = new_image(doc_w, doc_h)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    r.render(p, QRectF(0, 0, doc_w, doc_h))
    p.end()
    return out, 0, 0


def shapes_mask(shapes, doc_w, doc_h):
    """Full-doc white-on-transparent image of the union of shapes (for selections)."""
    out = new_image(doc_w, doc_h)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    for s in shapes:
        if s.get("type") == "svg":
            img, _, _ = render_svg(s["svg"], doc_w, doc_h)
            p.drawImage(0, 0, img)
        else:
            p.fillPath(shape_path(s), QBrush(QColor(255, 255, 255)))
    p.end()
    return out
