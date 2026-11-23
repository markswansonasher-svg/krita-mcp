"""Exercises the v0.2 painting features and checks undo. Krita must be open.
    uv run --with "mcp>=1.2,<2" python tools/feature_test.py [out_dir]
"""
import base64
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402

c = server.call
out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "feature-out")
os.makedirs(out, exist_ok=True)


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        check.failed += 1


check.failed = 0

c("new_document", width=900, height=600, name="feature-test", background="#ffffff")

# gradient sky + radial sun glow (raster engine, undoable)
c("paint", new_layer="Sky", shapes=[{"type": "rect", "x": 0, "y": 0, "w": 900, "h": 600,
  "fill": {"type": "linear", "x1": 0, "y1": 0, "x2": 0, "y2": 600, "stops": ["#1d2b53", "#7e5c9b", "#f6a46b"]}}])
c("paint", new_layer="Glow", mode="screen", blur=25, shapes=[{"type": "circle", "cx": 650, "cy": 420, "r": 120,
  "fill": {"type": "radial", "cx": 650, "cy": 420, "r": 120, "stops": [[0, "#fff3c4"], [1, "#ffb34700"]]}}])

# layer count before / after undo of one call
n0 = len(c("list_layers")["layers"])
pix0 = c("get_pixels", rect=[100, 100, 1, 1])["rows"][0][0]
c("paint", layer="Sky", shapes=[{"type": "rect", "x": 0, "y": 0, "w": 300, "h": 300, "fill": "#ff0000"}])
check("paint changed pixels", c("get_pixels", rect=[100, 100, 1, 1])["rows"][0][0] == "#ff0000")
r = c("undo")
check(f"undo one call restores pixels ({r})", c("get_pixels", rect=[100, 100, 1, 1])["rows"][0][0] == pix0)
check("undo kept layer count", len(c("list_layers")["layers"]) == n0)

# mountains with SVG + gradient, then clipped shading
c("paint_svg", new_layer="Mountains", svg=(
    '<defs><linearGradient id="m" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#3b2f5c"/><stop offset="1" stop-color="#14112a"/></linearGradient></defs>'
    '<path d="M0 430 L140 300 L230 370 L360 240 L470 380 L560 330 L700 420 L900 350 L900 600 L0 600 Z" fill="url(#m)"/>'))
c("paint", layer="Mountains", clip=True, mode="multiply", opacity=0.6, blur=10, shapes=[
    {"type": "polygon", "points": [[360, 240], [470, 380], [420, 600], [360, 600]], "fill": "#000000"}])

# selection-limited painting: shapes selection, feathered
c("select", mode="ellipse", x=120, y=60, w=260, h=160, feather=20)
c("fill_layer", new_layer="Cloud", color="#ffffffcc")
c("select", mode="none")

# ink engine: tapered lines, pencil grain, gradient-colored ink
c("add_layer", name="Ink")
birds = []
for i in range(6):
    x, y = 420 + i * 45, 120 + (i % 3) * 25
    birds.append({"points": [[x - 16, y], [x - 6, y - 8], [x, y]], "taper": 0.35})
    birds.append({"points": [[x, y], [x + 6, y - 8], [x + 16, y]], "taper": 0.35})
c("draw_strokes", engine="ink", size=4, color="#151022", strokes=birds)
c("draw_strokes", engine="pencil", size=5, color="#20183a", strokes=[
    {"points": [[40 + t * 8, 560 - 10 * math.sin(t / 3)] for t in range(100)], "taper": 0.2}])
c("draw_strokes", engine="ink", size=18, strokes=[
    {"points": [[60, 520, 0.1], [200, 470, 1.0], [340, 520, 0.1]],
     "color": {"type": "linear", "x1": 60, "y1": 0, "x2": 340, "y2": 0, "stops": ["#ff4f8b", "#ffd23f"]}}])

# brush engine with whole-stroke opacity (no segment buildup) + pressure
c("draw_strokes", preset="Airbrush", size=60, color="#ffd7a0", opacity=0.35, new_layer="Haze", strokes=[
    {"points": [[0, 470, 0.3], [450, 440, 1.0], [900, 470, 0.3]]}])
c("draw_strokes", preset="Ink-3 Gpen", size=10, color="#0d0b18", opacity=0.5, layer="Ink", strokes=[
    {"points": [[600 + 20 * math.cos(t / 5), 200 + t * 2, 0.3 + 0.7 * math.sin(math.pi * t / 60)] for t in range(61)]}])

# mask from shapes, clipping flag
c("add_mask", layer="Haze", shapes=[{"type": "rect", "x": 0, "y": 400, "w": 900, "h": 200}], feather=30)
c("add_layer", name="Rim", type="paint")
c("set_layer", layer="Rim", clipped=False)

layers = c("list_layers")["layers"]
check("layers present", {l["name"] for l in layers} >= {"Sky", "Glow", "Mountains", "Cloud", "Ink", "Haze"})
check("scratch doc hidden", all("_mcp" not in d["name"] for d in c("list_documents")))
c("export_image", path=os.path.join(out, "features.png"))
img = c("look", max_size=900, grid=100)
open(os.path.join(out, "look-grid.png"), "wb").write(base64.b64decode(img["png_base64"]))
print("failures:", check.failed)
