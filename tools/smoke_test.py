"""Smoke test: draws a small scene in Krita through the bridge and exports it.
Krita must be open with the plugin enabled.
    uv run --with "mcp>=1.2,<2" python tools/smoke_test.py [out_dir]
"""
import base64
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server  # noqa: E402

c = server.call
out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "smoke-out")
os.makedirs(out, exist_ok=True)

print(c("status")["krita"])
c("new_document", width=800, height=600, name="smoke-test", background="#f3efe6")

# sky gradient-ish bands with shapes, on their own layer
c("add_layer", name="Sky")
c("draw_shapes", shapes=[
    {"type": "rect", "x": 0, "y": 0, "w": 800, "h": 380, "stroke": None, "fill": "#bfe3f5"},
    {"type": "circle", "cx": 640, "cy": 110, "r": 60, "stroke": None, "fill": "#ffd34d"},
])

# hills as filled polygons
c("add_layer", name="Hills")
c("draw_shapes", shapes=[
    {"type": "path", "points": [[0, 420], [150, 330], [330, 400], [520, 300], [800, 390], [800, 600], [0, 600]],
     "closed": True, "stroke": None, "fill": "#6fb36a"},
])

# vector house from SVG, rasterized so brushes can work on it later
c("add_svg", layer="House", rasterize=True, svg=(
    '<rect x="300" y="360" width="160" height="120" fill="#d9734e" stroke="#3a2a20" stroke-width="4"/>'
    '<polygon points="285,365 380,290 475,365" fill="#8a3b2e" stroke="#3a2a20" stroke-width="4"/>'
    '<rect x="362" y="410" width="36" height="70" fill="#3a2a20"/>'))

# brush strokes with pressure: grass and a tapered signature curve
c("add_layer", name="Ink")
grass = []
for i in range(40):
    x = 20 + i * 19
    grass.append({"points": [[x, 590, 1.0], [x + 4, 565, 0.6], [x + 10, 545, 0.1]]})
c("draw_strokes", strokes=grass, preset="Ink-2 Fineliner", size=6, color="#2f6b2b")
wave = [[60 + t * 6, 120 + 25 * math.sin(t / 6), 0.15 + 0.85 * math.sin(math.pi * t / 60)] for t in range(61)]
c("draw_strokes", strokes=[{"points": wave}], preset="Ink-3 Gpen", size=14, color="#24323f")
# birds as smooth no-pressure strokes
c("draw_strokes", strokes=[
    {"points": [[200, 160], [215, 150], [230, 160], [245, 150], [260, 160]]},
    {"points": [[270, 200], [282, 192], [294, 200], [306, 192], [318, 200]]},
], size=4, color="#24323f")

# pixel art sprite
c("add_layer", name="Sprite")
c("set_pixels", x=40, y=420, scale=6, palette={"k": "#1b1b1b", "y": "#ffd800", "w": "#ffffff"}, rows=[
    "..kkkk..",
    ".kyyyyk.",
    "kywkywyk",
    "kyyyyyyk",
    "kykyykyk",
    "kyykkyyk",
    ".kyyyyk.",
    "..kkkk..",
])

print(c("list_layers")["layers"][0]["name"], "is on top")
print(c("export_image", path=os.path.join(out, "smoke.png")))
print(c("export_image", path=os.path.join(out, "sprite.png"), layer="Sprite", crop_to_content=True))
print(c("save", path=os.path.join(out, "smoke.kra")))
img = c("look", max_size=800)
with open(os.path.join(out, "look.png"), "wb") as f:
    f.write(base64.b64decode(img["png_base64"]))
print("look:", img["width"], "x", img["height"])
