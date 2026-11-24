# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2", "numpy>=1.26", "scipy>=1.11", "pillow>=10"]   # mcp 2.x renamed FastMCP
# ///
"""
Krita MCP - lets Claude (or any MCP client) draw in Krita.

Krita runs a small bridge plugin (plugin/krita_mcp) that listens on 127.0.0.1:9877.
This server turns MCP tool calls into commands for that bridge.

Run it with:
    uv run path/to/server.py

Environment:
    KRITA_MCP_PORT   port of the bridge inside Krita (default 9877)
    KRITA_PATH       krita.exe / krita binary, used by launch_krita (found automatically otherwise)
"""
import base64
import itertools
import math
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import realism  # noqa: E402  (numpy/scipy/Pillow work happens here, in the server)

PORT = int(os.environ.get("KRITA_MCP_PORT", "9877"))
HOST = "127.0.0.1"
mcp = FastMCP(
    "krita",
    instructions=(
        "Drives the user's live Krita. Start with status (or launch_krita if Krita is closed). "
        "Coordinates are document pixels, origin top-left. For a real illustration read art_guide first. "
        "For realism: paint parts flat (tube/blob/polygon shapes), then render_form lights them as 3D "
        "forms; add texture, cast_shadow and an optional painterly pass. "
        "Block in with paint / paint_svg (shapes, gradients, blend modes, clip, blur), render light and "
        "shadow as separate clipped multiply/screen passes, draw lines with draw_strokes (engine ink / "
        "pencil / brush with presets), texture with scatter_strokes and hatch, limit work with select "
        "and add_mask. Use look often (grid=100 to place things, grayscale=true to check values, region "
        "to inspect detail). Each call is one undo step. export_image writes PNG/JPG; save keeps layers."
    ),
)
_ids = itertools.count(1)


class KritaNotRunning(RuntimeError):
    pass


def call(cmd: str, timeout: float = 120.0, **params) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
    except OSError:
        raise KritaNotRunning(
            f"Krita isn't reachable on {HOST}:{PORT}. Open Krita (or call launch_krita). If Krita is open, "
            "enable 'Krita MCP (Claude)' in Settings > Configure Krita > Python Plugin Manager and restart Krita."
        ) from None
    with sock:
        sock.settimeout(timeout)
        rid = next(_ids)
        sock.sendall((json.dumps({"id": rid, "cmd": cmd, "params": params}) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(1 << 20)
            if not chunk:
                raise RuntimeError("Krita closed the connection.")
            buf += chunk
    resp = json.loads(buf.split(b"\n", 1)[0])
    if not resp.get("ok"):
        err = resp.get("error", "unknown error")
        if resp.get("traceback"):
            err += "\n" + resp["traceback"]
        raise RuntimeError(err)
    return resp.get("result")


def _image(result: dict) -> Image:
    return Image(data=base64.b64decode(result["png_base64"]), format="png")


def _find_krita() -> str | None:
    if os.environ.get("KRITA_PATH"):
        return os.environ["KRITA_PATH"]
    candidates = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if base:
                candidates.append(os.path.join(base, "Krita (x64)", "bin", "krita.exe"))
                candidates.append(os.path.join(base, "Krita", "bin", "krita.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/krita.app/Contents/MacOS/krita")
    for c in candidates:
        if os.path.exists(c):
            return c
    return shutil.which("krita")


# ----------------------------------------------------------------------------- general

@mcp.tool()
def status() -> dict:
    """Krita version, open documents, the active document (size, active layer) and the current brush."""
    return call("status")


@mcp.tool()
def launch_krita(wait_seconds: int = 90) -> dict:
    """Start Krita if it isn't running, and wait until its bridge answers."""
    try:
        return {"already_running": True, **call("ping")}
    except KritaNotRunning:
        pass
    exe = _find_krita()
    if not exe:
        raise RuntimeError("Couldn't find Krita. Set KRITA_PATH to krita.exe.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe], creationflags=flags, close_fds=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + wait_seconds
    last = None
    while time.time() < end:
        time.sleep(2)
        try:
            last = call("ping")
        except KritaNotRunning:
            continue
        if last.get("windows"):
            return {"started": True, **last}
    if last and last.get("dialogs"):
        raise RuntimeError(f"Krita is waiting on a dialog: {last['dialogs']}. Ask the user to answer it in Krita.")
    raise RuntimeError("Krita started but the bridge didn't answer. Check that the 'Krita MCP (Claude)' "
                       "plugin is enabled in Settings > Configure Krita > Python Plugin Manager.")


@mcp.tool()
def look(max_size: int = 1024, layer: str | None = None, region: list[int] | None = None,
         grid: int | None = None, grayscale: bool = False, document: str | None = None) -> Image:
    """See the canvas as an image. layer: only that layer. region: [x, y, w, h] to zoom in on detail.
    grid: overlay labelled lines every N document pixels (use it to place things precisely).
    grayscale: check values/contrast without color. Transparent areas show as a checkerboard."""
    return _image(call("look", max_size=max_size, layer=layer, region=region, grid=grid,
                       grayscale=grayscale, document=document))


# ----------------------------------------------------------------------------- documents

@mcp.tool()
def new_document(width: int = 1920, height: int = 1080, name: str = "Untitled",
                 background: str | None = "#ffffff", resolution: float = 300,
                 color_model: str = "RGBA", color_depth: str = "U8") -> dict:
    """Create a document and open it in Krita. background: a color, or "transparent".
    It gets a 'Background' layer plus an empty 'Paint' layer (active) to draw on.
    For pixel art use a small size (e.g. 32x32) and set_pixels."""
    for key in [k_ for k_ in _LINE_ART if k_[0] in ("", name)]:
        _LINE_ART.pop(key, None)
    return call("new_document", width=width, height=height, name=name, background=background,
                resolution=resolution, color_model=color_model, color_depth=color_depth)


@mcp.tool()
def open_document(path: str) -> dict:
    """Open an image or .kra file in Krita."""
    return call("open_document", path=path)


@mcp.tool()
def list_documents() -> list:
    """Documents open in Krita."""
    return call("list_documents")


@mcp.tool()
def switch_document(document: str) -> dict:
    """Make another open document the active one (by name or file path)."""
    return call("switch_document", document=document)


@mcp.tool()
def resize_canvas(width: int, height: int, x: int = 0, y: int = 0, document: str | None = None) -> dict:
    """Change the canvas size without scaling (x, y = offset of the new canvas)."""
    return call("resize_canvas", width=width, height=height, x=x, y=y, document=document)


@mcp.tool()
def scale_image(width: int, height: int, filter: str = "Bicubic", document: str | None = None) -> dict:
    """Scale the whole image. filter: Bicubic, Bilinear, Box (use Box for pixel art), Lanczos3..."""
    return call("scale_image", width=width, height=height, filter=filter, document=document)


@mcp.tool()
def save(path: str | None = None, document: str | None = None) -> dict:
    """Save with layers. path ending .kra (Krita), .psd or .ora. No path = save to the current file."""
    return call("save", path=path, document=document)


@mcp.tool()
def export_image(path: str, layer: str | None = None, width: int | None = None, height: int | None = None,
                 crop_to_content: bool = False, pixel_art: bool = False, quality: int = 92,
                 matte: str = "#ffffff", document: str | None = None) -> dict:
    """Export a flattened image: .png, .jpg, .webp, .bmp, .tif (other extensions use Krita's exporter).
    layer: export just one layer. width/height: resize on export (keeps aspect if only one is given).
    pixel_art: nearest-neighbour scaling. crop_to_content: trim empty edges. matte: background for JPG."""
    return call("export_image", path=path, layer=layer, width=width, height=height,
                crop_to_content=crop_to_content, pixel_art=pixel_art, quality=quality, matte=matte,
                document=document)


@mcp.tool()
def close_document(discard_changes: bool = False, document: str | None = None) -> dict:
    """Close a document. Refuses if it has unsaved changes unless discard_changes is true."""
    return call("close_document", discard_changes=discard_changes, document=document)


# ----------------------------------------------------------------------------- layers

@mcp.tool()
def list_layers(document: str | None = None) -> dict:
    """The layer tree, top layer first, with type, opacity, blend mode, visibility and bounds."""
    return call("list_layers", document=document)


@mcp.tool()
def add_layer(name: str, type: str = "paint", parent: str | None = None, opacity: float | None = None,
              blend_mode: str | None = None, document: str | None = None) -> dict:
    """Add a layer above the active one and make it active. type: paint, group or vector.
    parent: put it inside this group. opacity 0-1. blend_mode e.g. normal, multiply, screen, overlay, add."""
    return call("add_layer", name=name, type=type, parent=parent, opacity=opacity, blend_mode=blend_mode,
                document=document)


@mcp.tool()
def set_layer(layer: str | None = None, new_name: str | None = None, opacity: float | None = None,
              blend_mode: str | None = None, visible: bool | None = None, locked: bool | None = None,
              alpha_locked: bool | None = None, clipped: bool | None = None, active: bool | None = None,
              position: str | int | None = None, document: str | None = None) -> dict:
    """Change a layer (default: the active one): rename, opacity 0-1, blend mode, visibility, lock,
    alpha_locked (paint only lands where the layer already has paint), clipped (Krita "inherit alpha":
    the layer only shows where the layers below it in its group have paint - put a base shape and its
    shading layers together in a group for clipping-mask style rendering), make active, or move it:
    position = "top", "bottom", "up", "down" or an index within its group (0 = bottom)."""
    return call("set_layer", layer=layer, new_name=new_name, opacity=opacity, blend_mode=blend_mode,
                visible=visible, locked=locked, alpha_locked=alpha_locked, clipped=clipped, active=active,
                position=position, document=document)


@mcp.tool()
def select_layer(layer: str, document: str | None = None) -> dict:
    """Make a layer active (by name, 'Group/Layer' path or id)."""
    return call("select_layer", layer=layer, document=document)


@mcp.tool()
def delete_layer(layer: str, document: str | None = None) -> dict:
    """Delete a layer."""
    return call("delete_layer", layer=layer, document=document)


@mcp.tool()
def duplicate_layer(layer: str | None = None, name: str | None = None, document: str | None = None) -> dict:
    """Duplicate a layer (default: the active one)."""
    return call("duplicate_layer", layer=layer, name=name, document=document)


@mcp.tool()
def merge_down(layer: str | None = None, document: str | None = None) -> dict:
    """Merge a layer into the one below it."""
    return call("merge_down", layer=layer, document=document)


@mcp.tool()
def flatten(document: str | None = None) -> dict:
    """Flatten all layers into one."""
    return call("flatten", document=document)


@mcp.tool()
def clear_layer(layer: str | None = None, document: str | None = None) -> dict:
    """Erase everything on a paint layer (only inside the selection, if there is one)."""
    return call("clear_layer", layer=layer, document=document)


@mcp.tool()
def fill_layer(color: str | dict, layer: str | None = None, new_layer: str | None = None,
               rect: list[int] | None = None, mode: str = "normal", opacity: float = 1.0,
               clip: bool = False, blur: float = 0, document: str | None = None) -> dict:
    """Fill a paint layer with a color or gradient - limited to the selection (if any) and/or rect
    [x, y, w, h]. Combine with select (shapes, feather) for soft shaped fills. See `paint` for
    color/gradient formats, mode, clip and blur."""
    return call("fill_layer", color=color, layer=layer, new_layer=new_layer, rect=rect, mode=mode,
                opacity=opacity, clip=clip, blur=blur, document=document)


@mcp.tool()
def place_image(path: str, x: int = 0, y: int = 0, width: int | None = None, height: int | None = None,
                name: str | None = None, opacity: float | None = None, pixel_art: bool = False,
                document: str | None = None) -> dict:
    """Put an image file on a new paint layer at x, y (optionally resized) - references, textures, photos."""
    return call("place_image", path=path, x=x, y=y, width=width, height=height, name=name,
                opacity=opacity, pixel_art=pixel_art, document=document)


# ----------------------------------------------------------------------------- brushes

@mcp.tool()
def list_brushes(query: str = "", limit: int = 200) -> dict:
    """Brush presets installed in Krita, filtered by query (e.g. "ink", "pencil", "airbrush", "eraser")."""
    return call("list_brushes", query=query, limit=limit)


@mcp.tool()
def set_brush(preset: str | None = None, size: float | None = None, color: str | None = None,
              opacity: float | None = None, flow: float | None = None, blend_mode: str | None = None,
              eraser: bool | None = None, background_color: str | None = None,
              document: str | None = None) -> dict:
    """Set the current brush: preset name (or part of it), size in px, color, opacity 0-1, flow 0-1,
    blend mode, eraser mode, background color. Returns the brush state."""
    return call("set_brush", preset=preset, size=size, color=color, opacity=opacity, flow=flow,
                blend_mode=blend_mode, eraser=eraser, background_color=background_color, document=document)


@mcp.tool()
def get_brush(document: str | None = None) -> dict:
    """The current brush preset, size, opacity, flow, blend mode and colors."""
    return call("get_brush", document=document)


# ----------------------------------------------------------------------------- painting

_LINE_ART = {}   # (document, layer) -> {"lines": [polylines], "seeds": [(x, y, color)]} for fill_line_art


def _art_key(document, layer):
    return (document or "", layer or "")


@mcp.tool()
def draw_strokes(strokes: list[dict], engine: str = "brush", layer: str | None = None,
                 new_layer: str | None = None, preset: str | None = None, size: float | None = None,
                 color: str | dict | None = None, opacity: float | None = None, mode: str = "normal",
                 clip: bool = False, blur: float = 0, taper: float | None = None, grain: float | None = None,
                 smooth: bool = True, natural: float = 0.0, passes: int = 1, seed: int = 1, snap: bool = True,
                 document: str | None = None) -> dict:
    """Paint strokes. Points are [x, y] or [x, y, pressure 0-1]. Send many strokes per call.

    engine (per call, or "engine" per stroke):
      "brush"    Krita's brush engine with a preset (list_brushes) - textured, painterly marks.
      "ink"      clean variable-width lines: width = size x pressure, crisp antialiased tapers.
      "pencil"   ink + paper grain;  "charcoal" heavier grain;  "marker" translucent flat ink.
    Per stroke: points, color, size, preset, opacity, flow, eraser, smooth (curve through points),
      closed, and for ink engines: taper (0-0.5 of the length auto-tapered at each end, or [start, end]),
      grain 0-1, min_width. Ink color may be a gradient dict (see `paint`).

    LINE ART (draw an object line by line, then color it with fill_line_art):
      "outline": a shape dict (as in `paint`: tube {spine [[x,y,r],...]} for limbs/fingers/tentacles,
          blob, ellipse, circle, rect/polygon with "corner_radius", smooth "path") - the stroke becomes
          that shape's closed contour line. Instead of "points".
      "fill": color - remembers this closed outline's color; fill_line_art then colors its inside
          without any seeds (later strokes win where outlines overlap: draw back to front).
      "occlude": true - this outline is IN FRONT: lines already on the layer inside it are erased
          up to its contour before it is drawn (no hand-sized erasers, no stubs, no gaps).
      "joins": true - a line meeting other lines at its ends (seams, panel edges, folds that end on a
          contour): solid ends, no overshoot, and (snap=true) its ends snap onto the nearest line
          within reach so areas close for coloring. Free-ending detail lines (creases, vents, hair)
          leave it off and taper away. Outlines are joins automatically.
    natural 0-1: hand-drawn wobble, pressure that swells and lifts, overshoot on free ends.
    passes > 1: sketchy look - each stroke drawn several times, lighter.
    Each stroke has ONE opacity (overlapping segments don't darken). mode: blend mode for the
    whole call (normal, multiply, screen, overlay, add, color_dodge, soft_light, erase...).
    clip: only where the layer already has paint. blur: soften (px). new_layer: paint on a new layer.
    Painting respects the current selection."""
    target = new_layer or layer
    if target is None:
        st_ = call("status", document=document)
        target = (st_.get("active_document") or {}).get("active_layer")
    art = _LINE_ART.setdefault(_art_key(document, target), {"lines": [], "polygons": []})

    prepped = []
    for st in strokes:
        st = dict(st)
        if st.get("outline"):
            st["points"] = realism.outline_points(st.pop("outline"))
            st["closed"] = True
            st["joins"] = True
            st.setdefault("smooth", False)          # outline points are already dense and smooth
        if st.get("joins"):
            sz = float(st.get("size") or size or 6)
            st.update(overshoot=False, taper=min(float(st.get("taper", 0.06)), 0.08))
            st.setdefault("min_width", sz * 0.55)
            st.setdefault("size", sz)
        prepped.append(st)
    if snap:
        realism.snap_endpoints(prepped, art["lines"])
    # remember geometry and fills for fill_line_art (in drawing order)
    for st in prepped:
        pts = [p[:2] for p in st["points"]]
        if st.get("closed") and pts and pts[0] != pts[-1]:
            pts = pts + [pts[0]]
        if not st.get("eraser") and mode != "erase":
            art["lines"].append(pts)
        if st.get("fill") and st.get("closed"):
            art["polygons"].append((pts, st["fill"]))
    strokes = prepped
    if natural > 0 or passes > 1:
        out = []
        for i, st in enumerate(strokes):
            sz = float(st.get("size") or size or 6)
            for k in range(max(1, passes)):
                amount = max(natural, 0.35 if passes > 1 else 0.0)
                ns = realism.naturalize(st, sz, amount, seed * 1000 + i * 17 + k)
                if passes > 1:
                    base_op = float(st.get("opacity", opacity if opacity is not None else 1.0))
                    ns = dict(ns, opacity=base_op * (0.55 if k else 0.85))
                out.append(ns)
        strokes = out

    # split at occluders: draw what came before, erase inside the occluder, then continue
    common = dict(engine=engine, preset=preset, size=size, color=color, opacity=opacity, mode=mode, clip=clip,
                  blur=blur, taper=taper, grain=grain, smooth=smooth, document=document)
    batch, result, first = [], None, True

    def flush():
        nonlocal batch, result, first
        if batch:
            kw = dict(common, layer=layer, new_layer=new_layer) if first else dict(common, layer=target)
            result = call("draw_strokes", strokes=batch, **kw)
            first = False
            batch = []

    for st in strokes:
        if st.get("occlude"):
            flush()
            if first and new_layer:   # make sure the new layer exists before erasing on it
                call("add_layer", name=new_layer, document=document)
                first = False
            poly = [p[:2] for p in st["points"]]
            call("paint", layer=target, mode="erase", document=document,
                 shapes=[{"type": "polygon", "points": poly, "fill": "#000000"}])
        batch.append(st)
    flush()
    return result or {"strokes": 0}


@mcp.tool()
def draw_shapes(shapes: list[dict], layer: str | None = None, new_layer: str | None = None,
                preset: str | None = None, size: float | None = None, opacity: float = 1.0,
                mode: str = "normal", clip: bool = False, blur: float = 0, document: str | None = None) -> dict:
    """Shapes outlined with Krita's brush engine (textured outlines) and/or flat-filled.
    shapes: {"type": "rect" | "ellipse" | "circle" | "polygon" | "line" | "path", ...}
      rect/ellipse: x, y, w, h;  circle: cx, cy, r;  polygon/line/path: points [[x, y], ...]
      "stroke": outline color or null (default current color); "fill": color (default none);
      optional "size", "preset". For gradient fills and antialiased flat shapes use `paint`."""
    return call("draw_shapes", shapes=shapes, layer=layer, new_layer=new_layer, preset=preset, size=size,
                opacity=opacity, mode=mode, clip=clip, blur=blur, document=document)


@mcp.tool()
def add_svg(svg: str, layer: str | None = None, rasterize: bool = False, document: str | None = None) -> dict:
    """Add vector art from SVG to a vector layer (created if needed; layer = its name).
    You can pass just elements like '<circle cx="100" cy="100" r="50" fill="#f80"/>': they are placed in
    document pixels. A full <svg> document is used as-is. rasterize=true turns the result into a paint layer
    (so brushes and filters can work on it)."""
    return call("add_svg", svg=svg, layer=layer, rasterize=rasterize, document=document)


@mcp.tool()
def set_pixels(rows: list[str] | None = None, palette: dict[str, str] | None = None,
               pixels: list[list] | None = None, x: int = 0, y: int = 0, scale: int = 1,
               replace: bool = False, layer: str | None = None, new_layer: str | None = None,
               document: str | None = None) -> dict:
    """Exact pixels, for pixel art.
    rows + palette: rows of characters, each mapped to a color by palette, e.g.
      rows=["..kk..", ".kyyk."], palette={"k": "#000000", "y": "#ffd800"}; characters not in the palette
      are transparent (existing pixels kept unless replace=true). Placed at x, y; scale enlarges each pixel.
    pixels: [[x, y, color], ...] relative to x, y."""
    return call("set_pixels", rows=rows, palette=palette, pixels=pixels, x=x, y=y, scale=scale,
                replace=replace, layer=layer, new_layer=new_layer, document=document)


@mcp.tool()
def get_pixels(rect: list[int], layer: str | None = None, document: str | None = None) -> dict:
    """Read pixel colors in a small area (up to 64x64): rect = [x, y, w, h]. Default: the whole image."""
    return call("get_pixels", rect=rect, layer=layer, document=document)


# ----------------------------------------------------------------------------- selection, filters, actions

@mcp.tool()
def select(mode: str = "rect", rect: list[int] | None = None, shapes: list[dict] | None = None,
           svg: str | None = None, layer: str | None = None, op: str = "replace",
           feather: int | None = None, grow: int | None = None, shrink: int | None = None,
           x: float | None = None, y: float | None = None, w: float | None = None, h: float | None = None,
           cx: float | None = None, cy: float | None = None, r: float | None = None,
           points: list[list[float]] | None = None, smooth: bool | None = None,
           document: str | None = None) -> dict:
    """Make a selection; painting, fills, filters and clear_layer then stay inside it.
    mode: "rect" (rect=[x,y,w,h]) | "ellipse" (x,y,w,h) | "circle" (cx,cy,r) | "polygon" (points) |
      "path" (points, smooth curve) | "shapes" (list of shape dicts as in `paint`, or {"type":"svg","svg":..})
      | "svg" (svg markup in doc pixels) | "layer" (everything painted on a layer) | "all" | "none" |
      "invert" | "modify" (only apply feather/grow/shrink to the current selection).
    op: replace | add | subtract | intersect. feather: soft edge (px). grow/shrink in px."""
    return call("select", mode=mode, rect=rect, shapes=realism.expand_shapes(shapes), svg=svg, layer=layer, op=op, feather=feather,
                grow=grow, shrink=shrink, x=x, y=y, w=w, h=h, cx=cx, cy=cy, r=r, points=points,
                smooth=smooth, document=document)


@mcp.tool()
def list_filters() -> list:
    """Filter names (blur, gaussian blur, sharpen, unsharp, noise, oilpaint, pixelize, levels...)."""
    return call("list_filters")


@mcp.tool()
def filter_settings(filter: str) -> dict:
    """The settings a filter takes, with their default values."""
    return call("filter_settings", filter=filter)


@mcp.tool()
def apply_filter(filter: str, settings: dict | None = None, layer: str | None = None,
                 rect: list[int] | None = None, document: str | None = None) -> dict:
    """Apply a filter to a layer (default: active), optionally only in rect [x, y, w, h].
    settings: values from filter_settings, e.g. {"horizRadius": 8, "vertRadius": 8} for "gaussian blur"."""
    return call("apply_filter", filter=filter, settings=settings, layer=layer, rect=rect, document=document)


@mcp.tool()
def run_action(action: str, times: int = 1) -> dict:
    """Trigger any Krita menu action by its id, e.g. "mirror_canvas", "image_flip_horizontal"... (see list_actions)."""
    return call("run_action", action=action, times=times)


@mcp.tool()
def list_actions(query: str = "", limit: int = 100) -> list:
    """Search Krita's actions (menu commands) by id or text."""
    return call("list_actions", query=query, limit=limit)


@mcp.tool()
def undo(times: int = 1, raw: bool = False) -> dict:
    """Undo whole tool calls (everything each call did). raw=true undoes single Krita steps instead."""
    return call("undo", times=times, raw=raw)


@mcp.tool()
def redo(times: int = 1) -> dict:
    """Redo."""
    return call("redo", times=times)


@mcp.tool()
def execute_python(code: str) -> dict:
    """Run Python inside Krita with its full scripting API (Krita, app, doc = active document,
    QColor, QPointF, QRectF, QImage, QPainterPath, ManagedColor). Set `result` to return a value;
    print() output is returned too. Use it for anything the other tools don't cover."""
    return call("execute_python", code=code, timeout=300)


# ----------------------------------------------------------------------------- rendering

@mcp.tool()
def paint(shapes: list[dict], layer: str | None = None, new_layer: str | None = None, mode: str = "normal",
          opacity: float = 1.0, clip: bool = False, blur: float = 0, document: str | None = None) -> dict:
    """Antialiased shapes filled with flat colors or gradients - the workhorse for blocking in forms,
    lighting and shading. All shapes of one call are composited together (one undo step).

    shape: {"type": "rect" (x,y,w,h, radius) | "ellipse" (x,y,w,h) | "circle" (cx,cy,r) |
            "polygon" (points) | "path" (points, "smooth": true curve through them, "closed") |
            "tube" (spine [[x, y, radius], ...] - smooth organic limbs, fingers, tentacles, branches,
                    horns, hair locks; radius may vary along it) |
            "blob" (cx, cy, rx, ry, rotation, wobble 0-0.5, lumps, seed - rocks, clouds, muscles, bushes),
            "fill": color or gradient, "stroke": color or gradient, "stroke_width", "opacity",
            "erase": true (cut this shape out of what the call drew so far)}
    color: "#rrggbb", "#rrggbbaa", "red" or [r,g,b,a].
    gradient: {"type": "linear", "x1","y1","x2","y2", "stops": [[0,"#000"],[1,"#fff0"]]}
              {"type": "radial", "cx","cy","r", optional focal "fx","fy", "stops": [...]}
              {"type": "conical", "cx","cy","angle", "stops": [...]}   (stops may be just a color list;
              "spread": pad | reflect | repeat)
    mode: blend mode against the layer (normal, multiply = shadows, screen/add/color_dodge = light,
          overlay, soft_light, erase = cut away). clip: only where the layer already has paint
          (shade inside a form). blur: soft edges in px (glows, soft shadows, atmosphere)."""
    return call("paint", shapes=realism.expand_shapes(shapes), layer=layer, new_layer=new_layer, mode=mode,
                opacity=opacity, clip=clip, blur=blur, document=document)


@mcp.tool()
def paint_svg(svg: str, layer: str | None = None, new_layer: str | None = None, mode: str = "normal",
              opacity: float = 1.0, clip: bool = False, blur: float = 0, document: str | None = None) -> dict:
    """Render SVG straight onto a paint layer in document pixels: paths, curves, linear/radial
    gradients (<defs>), opacity, transforms, text. Bare elements are fine (they get a doc-sized <svg>).
    Best for complex silhouettes and precise hard-surface shapes. mode/clip/blur as in `paint`.
    (For editable Krita vector shapes use add_svg instead.)"""
    return call("paint_svg", svg=svg, layer=layer, new_layer=new_layer, mode=mode, opacity=opacity,
                clip=clip, blur=blur, document=document)


@mcp.tool()
def add_mask(layer: str | None = None, shapes: list[dict] | None = None, feather: int | None = None,
             name: str = "Mask", document: str | None = None) -> dict:
    """Add a transparency mask to a layer: from shapes (see `paint`), or from the current selection.
    Non-destructive - the layer only shows inside the mask."""
    return call("add_mask", layer=layer, shapes=realism.expand_shapes(shapes), feather=feather, name=name,
                document=document)


# ----------------------------------------------------------------------------- procedural marks

def _poly_contains(poly, x, y):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


@mcp.tool()
def scatter_strokes(region: list[list[float]] | list[float], count: int = 100,
                    length: list[float] = [10, 30], angle: float = -90, angle_jitter: float = 20,
                    curve: float = 0.2, size: list[float] = [2, 4], colors: list[str] | None = None,
                    engine: str = "ink", taper: float = 0.4, opacity: list[float] = [0.8, 1.0],
                    preset: str | None = None, seed: int = 1, layer: str | None = None,
                    new_layer: str | None = None, mode: str = "normal", clip: bool = False,
                    document: str | None = None) -> dict:
    """Many organic marks at once: grass, fur, hair strands, foliage, rain, sparks, scratches, stars.
    region: polygon [[x,y],...] or rect [x, y, w, h] where marks start. angle: direction in degrees
    (0 = right, -90 = up) +- angle_jitter. length/size/opacity: [min, max]. curve: bend amount.
    colors: picked at random. engine: ink / pencil / brush (with preset) / charcoal."""
    import random
    rnd = random.Random(seed)
    if len(region) == 4 and not isinstance(region[0], (list, tuple)):
        x, y, w, h = region
        poly = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    else:
        poly = region
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    colors = colors or [None]
    strokes, tries = [], 0
    while len(strokes) < count and tries < count * 50:
        tries += 1
        px, py = rnd.uniform(min(xs), max(xs)), rnd.uniform(min(ys), max(ys))
        if not _poly_contains(poly, px, py):
            continue
        a = math.radians(angle + rnd.uniform(-angle_jitter, angle_jitter))
        ln = rnd.uniform(*length)
        bend = rnd.uniform(-curve, curve) * ln
        mx, my = px + math.cos(a) * ln / 2 - math.sin(a) * bend, py + math.sin(a) * ln / 2 + math.cos(a) * bend
        ex, ey = px + math.cos(a) * ln, py + math.sin(a) * ln
        s = {"points": [[px, py, 1.0], [mx, my, 0.8], [ex, ey, 0.4]], "size": rnd.uniform(*size),
             "opacity": rnd.uniform(*opacity)}
        if engine != "brush":
            s["taper"] = taper
        c = rnd.choice(colors)
        if c:
            s["color"] = c
        strokes.append(s)
    return call("draw_strokes", strokes=strokes, engine=engine, preset=preset, layer=layer,
                new_layer=new_layer, mode=mode, clip=clip, document=document)


@mcp.tool()
def hatch(region: list[list[float]] | list[float], angle: float = 45, spacing: float = 8,
          size: float = 1.5, color: str = "#000000", layers: int = 1, jitter: float = 1.0,
          engine: str = "pencil", opacity: float = 0.8, seed: int = 1, layer: str | None = None,
          new_layer: str | None = None, mode: str = "normal", document: str | None = None) -> dict:
    """Hatching / cross-hatching inside a polygon [[x,y],...] or rect [x,y,w,h] - for shading
    drawings, engraving looks, comic tones. layers: 1 = hatch, 2+ = cross-hatch (rotated 90/layers deg)."""
    import random
    rnd = random.Random(seed)
    if len(region) == 4 and not isinstance(region[0], (list, tuple)):
        x, y, w, h = region
        poly = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    else:
        poly = region
    strokes = []
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    radius = max(math.hypot(p[0] - cx, p[1] - cy) for p in poly) + spacing
    for k in range(max(1, layers)):
        a = math.radians(angle) + k * (math.pi / 2 if layers == 2 else math.pi / max(1, layers))
        dx, dy = math.cos(a), math.sin(a)
        nx, ny = -dy, dx
        t = -radius
        while t <= radius:
            o = t + rnd.uniform(-jitter, jitter)
            # sample along the line, keep runs inside the polygon
            run = []
            steps = int(2 * radius / 3) + 2
            for i in range(steps + 1):
                s_ = -radius + 2 * radius * i / steps
                px, py = cx + nx * o + dx * s_, cy + ny * o + dy * s_
                if _poly_contains(poly, px, py):
                    run.append([px + rnd.uniform(-jitter, jitter) * 0.3, py + rnd.uniform(-jitter, jitter) * 0.3])
                elif run:
                    if len(run) > 1:
                        strokes.append({"points": [run[0], run[len(run) // 2], run[-1]], "taper": 0.15})
                    run = []
            if len(run) > 1:
                strokes.append({"points": [run[0], run[len(run) // 2], run[-1]], "taper": 0.15})
            t += spacing
    return call("draw_strokes", strokes=strokes, engine=engine, size=size, color=color, opacity=opacity,
                layer=layer, new_layer=new_layer, mode=mode, smooth=False, document=document)


# ----------------------------------------------------------------------------- realism (server-side)

def _get(layer=None, document=None):
    r = call("get_image", layer=layer, document=document)
    return realism.decode_png(r["png_base64"])


def _bbox(alpha, pad=4):
    ys, xs = (alpha > 0.002).nonzero()
    if len(xs) == 0:
        return None
    h, w = alpha.shape
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
            min(w, int(xs.max()) + pad + 1), min(h, int(ys.max()) + pad + 1))


def _put(arr, x, y, **kw):
    return call("put_image", png_base64=realism.encode_png(arr), x=int(x), y=int(y), timeout=300, **kw)


@mcp.tool()
def render_form(layer: str, material: str = "painted_metal", profile: str = "round", radius: float = 24,
                by_color: bool = True, depth: float = 1.0, key_angle: float = 135, key_elevation: float = 40,
                key_color: str = "#fff4e0", key_intensity: float = 1.0, fill_color: str = "#4a6080",
                fill_intensity: float = 0.35, sky_color: str = "#9fc6e8", ground_color: str = "#3a2f28",
                ambient: float = 0.35, rim_angle: float | None = None, rim_color: str = "#bff4ff",
                rim_intensity: float = 0.0, ao: float = 0.6, env_sky: str = "#cfe8ff",
                env_ground: str = "#2b2622", bump: float | None = None, bump_scale: float = 6,
                material_overrides: dict | None = None, new_layer: str | None = None,
                document: str | None = None) -> dict:
    """Turn the flat shapes on a layer into lit 3D forms - the biggest single step toward realism.

    It builds a height field from the silhouette (each flat-color region is its own form when
    by_color=true, so armor plates, fingers, petals... each get their own rounded edge), then lights
    it: key light, fill light, sky/ground ambient, ambient occlusion in creases, specular highlights,
    rim light, environment reflections (metal) and subsurface glow (skin, leaves).

    Paint parts flat first (paint with tube/blob/polygon shapes, a distinct color per part), then call
    this. profile: round (rounded edges of `radius` px) | dome (each region fully rounded, like a
    pillow or sphere) | bevel (chamfered hard-surface) | pillow (soft) | flat.
    material: matte, plastic, metal, painted_metal, skin, cloth, stone, wood, glass, leaf
      (material_overrides: diffuse, specular, shininess, metalness, wrap, subsurface, sheen).
    Lights: angles in degrees the light comes FROM (0 = right, 90 = top, 180 = left), elevation
    0-90. rim_intensity > 0 adds a rim light from rim_angle (default: opposite the key).
    bump adds surface relief (stone, worn metal, skin pores); bump_scale is its size in px.
    The layer is replaced with the rendered version (undo restores it); new_layer keeps the original."""
    img = _get(layer, document)
    bb = _bbox(img[..., 3])
    if bb is None:
        return {"error": f"Layer {layer!r} is empty."}
    x0, y0, x1, y1 = bb
    out = realism.render_form(img[y0:y1, x0:x1], material=material, profile=profile, radius=radius,
                              by_color=by_color, depth=depth, key_angle=key_angle, key_elevation=key_elevation,
                              key_color=key_color, key_intensity=key_intensity, fill_color=fill_color,
                              fill_intensity=fill_intensity, sky_color=sky_color, ground_color=ground_color,
                              ambient=ambient, rim_angle=rim_angle, rim_color=rim_color,
                              rim_intensity=rim_intensity, ao=ao, env_sky=env_sky, env_ground=env_ground,
                              bump=bump, bump_scale=bump_scale, overrides=material_overrides)
    if new_layer:
        return _put(out, x0, y0, new_layer=new_layer, above=layer, document=document)
    return _put(out, x0, y0, layer=layer, replace=True, use_selection=False, document=document)


@mcp.tool()
def painterly(layer: str | None = None, new_layer: str | None = "Painterly", sizes: list[int] = [24, 12, 6, 3],
              threshold: float = 0.06, stroke_length: int = 10, curvature: float = 0.6, bristles: bool = True,
              color_jitter: float = 0.04, opacity: float = 1.0, region: list[int] | None = None, seed: int = 7,
              document: str | None = None) -> dict:
    """Repaint an image with real-looking brushwork: long curved strokes that follow the forms
    (along edges and gradients), coarse to fine - big strokes for broad areas, small ones only where
    detail needs them - with bristle texture and slight color variation. Turns vector-clean renders
    into something that reads as painted.

    Source: a layer (layer=...) or the whole visible canvas (layer=None). The result goes to new_layer
    (default "Painterly", on top) - lower its opacity or mask it to mix with the original; or pass
    new_layer=None with a layer to replace that layer. sizes: brush radii in px, coarse -> fine.
    threshold: lower = more fine strokes (more detail). region: [x, y, w, h] to limit the work."""
    img = _get(layer, document)
    H, W = img.shape[:2]
    if region:
        x0, y0, w, h = [int(v) for v in region]
        x1, y1 = min(W, x0 + w), min(H, y0 + h)
        x0, y0 = max(0, x0), max(0, y0)
    else:
        bb = _bbox(img[..., 3], 0)
        if bb is None:
            return {"error": "Nothing to paint."}
        x0, y0, x1, y1 = bb
    out = realism.painterly(img[y0:y1, x0:x1], sizes=tuple(sizes), threshold=threshold, max_length=stroke_length,
                            curvature=curvature, bristles=bristles, color_jitter=color_jitter, seed=seed)
    if new_layer:
        above = layer or call("list_layers", document=document)["layers"][0]["name"]   # default: on top
        return _put(out, x0, y0, new_layer=new_layer, above=above, opacity=opacity, use_selection=False,
                    document=document)
    return _put(out, x0, y0, layer=layer, replace=True, use_selection=False, document=document)


@mcp.tool()
def fill_line_art(line_layer: str, seeds: list[list] | None = None, background_seeds: list[list[float]] | None = None,
                  gap: int = 2, default_color: str | None = None, new_layer: str = "Flats",
                  debug_view: bool = False, document: str | None = None):
    """Color drawn line art the way artists do (bucket fill / colorize mask): every enclosed area
    between the lines that contains a seed [x, y, color] is filled with that color. Outlines drawn
    with draw_strokes(..., "fill": color) on this layer color themselves automatically - every
    enclosed area mostly inside such an outline (even when seams or parts in front split it into
    pieces) takes its color, frontmost outline winning. Extra `seeds` override. Areas open to the
    top/left/right canvas edge (or containing a background seed [x, y]) stay empty. gap closes small
    breaks in the lines (px). default_color fills enclosed areas you didn't seed. The color extends
    under the lines so there are no halos. Result: a new layer just below the line layer - then
    render_form it, shade with strokes, etc.
    debug_view=true: nothing is painted; returns an image with every enclosed area in its own random
    color (background grey) and the seeds as numbered dots - leaks show as one color crossing a line
    that should separate it."""
    lines = _get(line_layer, document)
    polys = _LINE_ART.get(_art_key(document, line_layer), {}).get("polygons", [])
    seeds = [tuple(x) for x in (seeds or [])]
    out = realism.fill_line_art(lines, seeds, [tuple(b) for b in (background_seeds or [])], gap, default_color,
                                polygons=polys)
    if debug_view:
        from PIL import Image as PILImage, ImageDraw
        dbg, pts = realism.fill_line_art.last_debug
        bb = _bbox(lines[..., 3], 20) or (0, 0, dbg.shape[1], dbg.shape[0])
        im = PILImage.fromarray((dbg[bb[1]:bb[3], bb[0]:bb[2]] * 255).astype(np.uint8), "RGB")
        dr = ImageDraw.Draw(im)
        for i, (x, y) in enumerate(pts):
            x, y = x - bb[0], y - bb[1]
            dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 0, 0), outline=(255, 255, 255))
            dr.text((x + 5, y - 6), str(i), fill=(255, 255, 255))
        scale = min(1.0, 1100 / max(im.size))
        if scale < 1:
            im = im.resize((int(im.size[0] * scale), int(im.size[1] * scale)))
        import io as _io
        buf = _io.BytesIO()
        im.save(buf, "PNG")
        return Image(data=buf.getvalue(), format="png")
    bb = _bbox(out[..., 3], 1)
    if bb is None:
        return {"error": "No enclosed area was filled - check that the seeds are inside closed lines."}
    x0, y0, x1, y1 = bb
    r = _put(out[y0:y1, x0:x1], x0, y0, new_layer=new_layer, below=line_layer, use_selection=False,
             document=document)
    problems = getattr(realism.fill_line_art, "last_report", [])
    if problems:
        r["seed_problems"] = problems   # leaks: close the line gap near there, or raise gap
    return r


@mcp.tool()
def edge_light(layer: str, angle: float = 60, color: str = "#bff4ff", width: float = 6, power: float = 1.5,
               opacity: float = 0.9, mode: str = "add", by_color: bool = False, inner: float = 0.5,
               new_layer: str | None = None, document: str | None = None) -> dict:
    """Rim / edge light: brightens only the edges of the layer's paint that FACE a light coming from
    `angle` (degrees: 0 = right, 90 = top, 180 = left), fading inward over `width` px. Use it for
    backlight from a corridor, sky or window (cool), and a second call for a warm kicker. by_color
    also catches the edges between differently colored parts (plate edges) at `inner` strength.
    Goes on a new layer above (blend `mode`, default add)."""
    img = _get(layer, document)
    bb = _bbox(img[..., 3], 2)
    if bb is None:
        return {"error": f"Layer {layer!r} is empty."}
    x0, y0, x1, y1 = bb
    m = realism.edge_light(img[y0:y1, x0:x1], angle, width, power, by_color, inner=inner)
    out = realism.colorize(np.zeros(m.shape, np.float32), color, color, alpha=m)
    name = new_layer or f"{layer} edge light"
    r = _put(out, x0, y0, new_layer=name, above=layer, opacity=opacity, use_selection=False, document=document)
    call("set_layer", layer=name, blend_mode=mode, document=document)
    return r


@mcp.tool()
def cast_shadow(layer: str, direction: list[float] = [0.7, -0.22], base_y: float | None = None,
                base_x: float | None = None, color: str = "#0a0c12", opacity: float = 0.75,
                softness: float = 14, falloff: float = 0.6, contact: float = 0.9, contact_size: float = 6,
                target_layer: str | None = None, document: str | None = None) -> dict:
    """Ground shadow cast by the shapes on a layer - grounds objects so they stop floating.
    direction: where the shadow falls per pixel of object height, [dx, dy] on screen, e.g.
    [0.7, -0.22] = to the right and slightly back (light from the front-left), [-1.2, -0.1] = long to
    the left, [0.1, 0.35] = short, toward the viewer (light from behind). base_y / base_x: the ground
    contact point (default: bottom-center of the layer's paint). Sharp near the contact, softer and
    fainter farther away (softness px, falloff 0-1), plus a dark contact shadow right at the base.
    Goes on a new layer just below the object (or onto target_layer, multiplied)."""
    img = _get(layer, document)
    alpha = img[..., 3]
    bb = _bbox(alpha, 0)
    if bb is None:
        return {"error": f"Layer {layer!r} is empty."}
    x0, y0, x1, y1 = bb
    by = float(base_y if base_y is not None else y1 - 1)
    bx = float(base_x if base_x is not None else (x0 + x1) / 2)
    sh = realism.cast_shadow(alpha, by, bx, tuple(direction), softness, falloff, contact, contact_size)
    bb2 = _bbox(sh, 2)
    if bb2 is None:
        return {"error": "The shadow fell outside the canvas."}
    sx0, sy0, sx1, sy1 = bb2
    out = realism.colorize(np.zeros((sy1 - sy0, sx1 - sx0), np.float32), color, color, alpha=sh[sy0:sy1, sx0:sx1])
    if target_layer:
        return _put(out, sx0, sy0, layer=target_layer, mode="multiply", opacity=opacity, document=document)
    name = f"{layer} shadow"
    r = _put(out, sx0, sy0, new_layer=name, below=layer, opacity=opacity, document=document)
    call("set_layer", layer=name, blend_mode="multiply", document=document)
    return r


@mcp.tool()
def texture(layer: str, kind: str = "grime", scale: float = 32, dark: str = "#000000", light: str = "#ffffff",
            mode: str = "overlay", opacity: float = 0.5, contrast: float = 1.0, clip: bool = True,
            rect: list[int] | None = None, seed: int = 1, new_layer: str | None = None,
            document: str | None = None) -> dict:
    """Procedural surface detail blended onto a layer (clipped to its paint by default).
    kind: grain (fine noise), fbm/clouds (soft variation), grime/rust (dirty patches), scratches,
    cells (cracks, scales), stone, fabric. The pattern is mapped from `dark` to `light` and blended with
    `mode` (overlay / soft_light keep the color and add detail, multiply for dirt, screen for wear).
    scale: feature size in px."""
    img = _get(layer, document)
    H, W = img.shape[:2]
    if rect:
        x0, y0, w, h = [int(v) for v in rect]
        x1, y1 = min(W, x0 + w), min(H, y0 + h)
    else:
        bb = _bbox(img[..., 3]) if clip else (0, 0, W, H)
        if bb is None:
            return {"error": f"Layer {layer!r} is empty."}
        x0, y0, x1, y1 = bb
    t = realism.texture(y1 - y0, x1 - x0, kind=kind, scale=scale, seed=seed, contrast=contrast)
    out = realism.colorize(t, dark, light)
    if new_layer:
        return _put(out, x0, y0, new_layer=new_layer, above=layer, mode=mode, opacity=opacity, document=document)
    return _put(out, x0, y0, layer=layer, mode=mode, opacity=opacity, clip=clip, document=document)

# ----------------------------------------------------------------------------- guidance

ART_GUIDE = r"""
HOW TO MAKE A STRONG PICTURE WITH THESE TOOLS

0. Plan before painting. Decide canvas size, focal point, camera (eye level, low angle = horizon
   low and verticals converging upward), light direction and color, and a 3-5 color palette with a
   clear value plan (darks / mids / lights). Write coordinates down; use look(grid=100) to check them.

1. Separate layers, back to front: Background, Far, Mid, Subject, Subject shading, FX, Atmosphere,
   Line/details, Color grade. Name them. Group a subject's base with its shading layers and set
   the shading layers clipped=true (or use clip=true per call) so shading never leaks.

2. Block in flat silhouettes first (paint / paint_svg with flat colors). Check look(grayscale=true):
   the subject must read as a clear shape against its background before any detail.

2b. REALISM FAST PATH: paint each part flat in its own color (paint with "tube" shapes for limbs,
   fingers, tentacles, branches; "blob" for rocks, muscles, clouds; polygons for hard surface), then
   render_form(layer, material=..., profile=...) computes real light: rounded or bevelled volume,
   key/fill/sky light, ambient occlusion, specular, rim, metal reflections, skin subsurface glow.
   Match its light angles to the scene's light sources. Then texture(...) for grime/scratches/stone,
   cast_shadow(...) to ground objects, and optionally painterly(...) (opacity 0.4-0.7) at the end
   so it reads as painted. Do not paint tiny detail marks before render_form - each mark becomes its
   own little bump; add detail after it.

   NATURAL LINES: draw_strokes(..., natural=0.3-0.6) gives hand-drawn wobble, pressure and overshoot;
   passes=2-3 gives a sketchy look. Prefer few long confident strokes over many short ones.

2c. DRAWING A FIGURE OR OBJECT AS LINE ART (gets it right the first time):
   - Draw back to front on one line layer. Each part is ONE stroke with "outline": a shape - tube
     (spine with a radius per point) for limbs, fingers, cables; blob for pads, rocks, muscles;
     polygon/rect with corner_radius for hard surface; smooth path for curved shells.
   - Give each outline "fill": color, and "occlude": true when it is in front of what you drew
     before - it erases the hidden lines exactly up to its contour. No erasers to size by hand.
   - Seams, panel lines and folds that end on a contour: "joins": true (their ends snap shut).
     Free-ending details (vents, creases, hair): plain strokes that taper.
   - fill_line_art(line_layer) then colors everything from the outlines - no seed coordinates.
     If it reports seed_problems, call it with debug_view=true and look.
   - Attach things in the frame of what they touch: a hand on a grip is drawn in the grip's own
     coordinates, so it can't end up beside it.
   - Then render_form on the flats, edge_light for rim/kicker light, keep the lines on top.

3. Light and form by hand (for stylized work, or on top of render_form), each its own pass:
   - form shadow: paint(mode="multiply", clip=true, blur=6-20) with a cool dark on the side away
     from the light;  - occlusion: small dark multiply blurs where forms meet;
   - key light: paint(mode="screen" or "add", clip=true) with warm light on surfaces facing the light;
   - rim light: thin bright ink strokes (engine="ink", taper) along the edge opposite the key;
   - specular highlights: tiny bright ink dots/lines on hard materials (metal, visor, armor edges).

4. Materials: metal = high contrast, sharp highlights, reflected environment color; cloth = soft
   gradients, folds as tapered multiply strokes; skin = warm, subsurface reds in shadows; glass/visor =
   gradient + reflection streak + glow. Texture: scatter_strokes for scratches/grass/fur, hatch for
   engraving looks, engine="pencil"/"charcoal" grain, brush presets (list_brushes "texture", "chalk").

5. Depth: farther things get lower contrast and shift toward the atmosphere color (a translucent
   paint layer, mode normal/screen, opacity 0.2-0.5). Add volumetric light (long blurred screen
   polygons), bloom around emissive lights (blur 20-60, mode add), and a vignette (radial multiply).

6. Edges: vary them. Hard edges on the focal point, soft/lost edges in the background (blur).

7. Final grade: a new layer with mode "overlay"/"soft_light" gradient to unify color, slight
   chromatic accents, then look() at full size and look(region=...) at details; fix, repeat.

8. Occlusion: draw overlapping parts back to front. Put outlines on the shapes themselves
   ("stroke" in `paint`), not on a separate line layer, or lines of hidden parts show through.
   For edge light/shade passes over many parts, list them back to front as [fill part, shifted copy
   with "erase": true] - and add plain {"erase": true} copies of parts in front that shouldn't get
   the effect - all in ONE paint call, so nearer parts cover farther ones.

9. Pitfall: `mode` in paint/draw_strokes blends against the pixels already on THAT layer. On an
   empty layer, multiply/screen/add do nothing special. To light or shade what's below, make a
   layer with set_layer(blend_mode="multiply"/"add"/...) (often clipped=true) and paint normally on it.

10. Perspective: compute it. Put a tiny pinhole projection in your plan (camera height, tilt,
   focal length) and project 3D points for architecture and figures - low angle = camera low,
   tilted up, long-ish lens so the figure is heroic rather than distorted.

11. Iterate. look after every few steps. undo takes back a whole call. Save .kra (keeps layers) and
   export_image the PNG.
"""


@mcp.tool()
def art_guide() -> str:
    """Workflow advice for painting complex, high-quality images with these tools. Read it before a
    big illustration."""
    return ART_GUIDE


if __name__ == "__main__":
    mcp.run()
