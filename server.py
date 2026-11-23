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
        "Coordinates are document pixels, origin top-left. Paint on paint layers with draw_strokes "
        "(real brush strokes, optional pressure) and draw_shapes (outlined/filled shapes); use add_svg "
        "for crisp vector art and set_pixels for pixel art. Use look often to see the result. "
        "Work on separate layers so mistakes are easy to undo or delete. "
        "export_image writes PNG/JPG; save keeps layers (.kra)."
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
         document: str | None = None) -> Image:
    """See the canvas as an image. layer: show only that layer. region: [x, y, w, h] to zoom in.
    Transparent areas show as a checkerboard."""
    return _image(call("look", max_size=max_size, layer=layer, region=region, document=document))


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
              alpha_locked: bool | None = None, active: bool | None = None,
              position: str | int | None = None, document: str | None = None) -> dict:
    """Change a layer (default: the active one): rename, opacity 0-1, blend mode, visibility, lock,
    alpha lock (paint only where there is already paint), make active, or move it:
    position = "top", "bottom", "up", "down" or an index within its group (0 = bottom)."""
    return call("set_layer", layer=layer, new_name=new_name, opacity=opacity, blend_mode=blend_mode,
                visible=visible, locked=locked, alpha_locked=alpha_locked, active=active,
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
    """Erase everything on a paint layer."""
    return call("clear_layer", layer=layer, document=document)


@mcp.tool()
def fill_layer(color: str, layer: str | None = None, rect: list[int] | None = None,
               document: str | None = None) -> dict:
    """Fill a paint layer (or rect [x, y, w, h] of it) with a flat color, replacing what was there."""
    return call("fill_layer", color=color, layer=layer, rect=rect, document=document)


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
def draw_strokes(strokes: list[dict], layer: str | None = None, preset: str | None = None,
                 size: float | None = None, color: str | None = None, opacity: float | None = None,
                 smooth: bool = True, document: str | None = None) -> dict:
    """Paint real brush strokes on a paint layer (default: the active layer) with Krita's brush engine.

    strokes: list of {"points": [[x, y], ...] or [[x, y, pressure], ...], plus optional "color",
    "size", "preset", "opacity", "flow", "eraser", "smooth", "closed"}. Pressure 0-1 changes width
    and/or opacity depending on the preset (e.g. taper a line with pressures 0.2 -> 1 -> 0.2).
    smooth=true draws curves through the points; false draws straight segments.
    The top-level preset/size/color/opacity apply before all strokes; per-stroke values override.
    Send many strokes in one call."""
    return call("draw_strokes", strokes=strokes, layer=layer, preset=preset, size=size, color=color,
                opacity=opacity, smooth=smooth, document=document)


@mcp.tool()
def draw_shapes(shapes: list[dict], layer: str | None = None, preset: str | None = None,
                size: float | None = None, document: str | None = None) -> dict:
    """Paint shapes with the brush on a paint layer.

    shapes: list of {"type": "rect" | "ellipse" | "circle" | "polygon" | "line" | "path", ...}
      rect/ellipse: "x", "y", "w", "h";  circle: "cx", "cy", "r";
      polygon/line/path: "points" [[x, y], ...] (path: "smooth", "closed")
      "stroke": outline color, or null for no outline (default: current color)
      "fill": fill color (default: no fill)
      optional "size", "preset", "opacity" for the outline brush."""
    return call("draw_shapes", shapes=shapes, layer=layer, preset=preset, size=size, document=document)


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
               replace: bool = False, layer: str | None = None, document: str | None = None) -> dict:
    """Exact pixels, for pixel art.
    rows + palette: rows of characters, each mapped to a color by palette, e.g.
      rows=["..kk..", ".kyyk."], palette={"k": "#000000", "y": "#ffd800"}; characters not in the palette
      are transparent (kept as-is unless replace=true). Placed at x, y; scale enlarges each pixel.
    pixels: [[x, y, color], ...] for individual pixels."""
    return call("set_pixels", rows=rows, palette=palette, pixels=pixels, x=x, y=y, scale=scale,
                replace=replace, layer=layer, document=document)


@mcp.tool()
def get_pixels(rect: list[int], layer: str | None = None, document: str | None = None) -> dict:
    """Read pixel colors in a small area (up to 64x64): rect = [x, y, w, h]. Default: the whole image."""
    return call("get_pixels", rect=rect, layer=layer, document=document)


# ----------------------------------------------------------------------------- selection, filters, actions

@mcp.tool()
def select(mode: str = "rect", rect: list[int] | None = None, document: str | None = None) -> dict:
    """Selection: mode "rect" with rect [x, y, w, h], "all", or "none". Painting and filters stay inside it."""
    return call("select", mode=mode, rect=rect, document=document)


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
def undo(times: int = 1) -> dict:
    """Undo the last change(s)."""
    return call("undo", times=times)


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


if __name__ == "__main__":
    mcp.run()
