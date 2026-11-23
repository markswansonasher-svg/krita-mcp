# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2"]   # mcp 2.x renamed FastMCP
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

PORT = int(os.environ.get("KRITA_MCP_PORT", "9877"))
HOST = "127.0.0.1"
mcp = FastMCP(
    "krita",
    instructions=(
        "Drives the user's live Krita. Start with status (or launch_krita if Krita is closed). "
        "Coordinates are document pixels, origin top-left. For a real illustration read art_guide first. "
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
    while time.time() < end:
        time.sleep(2)
        try:
            return {"started": True, **call("ping")}
        except KritaNotRunning:
            continue
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

@mcp.tool()
def draw_strokes(strokes: list[dict], engine: str = "brush", layer: str | None = None,
                 new_layer: str | None = None, preset: str | None = None, size: float | None = None,
                 color: str | dict | None = None, opacity: float | None = None, mode: str = "normal",
                 clip: bool = False, blur: float = 0, taper: float | None = None, grain: float | None = None,
                 smooth: bool = True, document: str | None = None) -> dict:
    """Paint strokes. Points are [x, y] or [x, y, pressure 0-1]. Send many strokes per call.

    engine (per call, or "engine" per stroke):
      "brush"    Krita's brush engine with a preset (list_brushes) - textured, painterly marks.
      "ink"      clean variable-width lines: width = size x pressure, crisp antialiased tapers.
      "pencil"   ink + paper grain;  "charcoal" heavier grain;  "marker" translucent flat ink.
    Per stroke: points, color, size, preset, opacity, flow, eraser, smooth (curve through points),
      closed, and for ink engines: taper (0-0.5 of the length auto-tapered at each end, or [start, end]),
      grain 0-1, min_width. Ink color may be a gradient dict (see `paint`).
    Each stroke has ONE opacity (overlapping segments don't darken). mode: blend mode for the
    whole call (normal, multiply, screen, overlay, add, color_dodge, soft_light, erase...).
    clip: only where the layer already has paint. blur: soften (px). new_layer: paint on a new layer.
    Painting respects the current selection. One call = one undo step."""
    return call("draw_strokes", strokes=strokes, engine=engine, layer=layer, new_layer=new_layer,
                preset=preset, size=size, color=color, opacity=opacity, mode=mode, clip=clip, blur=blur,
                taper=taper, grain=grain, smooth=smooth, document=document)


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
    return call("select", mode=mode, rect=rect, shapes=shapes, svg=svg, layer=layer, op=op, feather=feather,
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
            "polygon" (points) | "path" (points, "smooth": true curve through them, "closed"),
            "fill": color or gradient, "stroke": color or gradient, "stroke_width", "opacity"}
    color: "#rrggbb", "#rrggbbaa", "red" or [r,g,b,a].
    gradient: {"type": "linear", "x1","y1","x2","y2", "stops": [[0,"#000"],[1,"#fff0"]]}
              {"type": "radial", "cx","cy","r", optional focal "fx","fy", "stops": [...]}
              {"type": "conical", "cx","cy","angle", "stops": [...]}   (stops may be just a color list;
              "spread": pad | reflect | repeat)
    mode: blend mode against the layer (normal, multiply = shadows, screen/add/color_dodge = light,
          overlay, soft_light, erase = cut away). clip: only where the layer already has paint
          (shade inside a form). blur: soft edges in px (glows, soft shadows, atmosphere)."""
    return call("paint", shapes=shapes, layer=layer, new_layer=new_layer, mode=mode, opacity=opacity,
                clip=clip, blur=blur, document=document)


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
    return call("add_mask", layer=layer, shapes=shapes, feather=feather, name=name, document=document)


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

3. Light and form, in this order, each its own pass:
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
