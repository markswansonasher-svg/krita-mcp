"""Exercises the realism tools: organic shapes, render_form materials, textures, natural lines,
painterly. Krita must be open.
    uv run --with "mcp>=1.2,<2" --with numpy --with scipy --with pillow python tools/realism_test.py [out_dir]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server as k  # noqa: E402

out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "realism-out")
os.makedirs(out, exist_ok=True)
t0 = time.time()


def lap(label):
    print(f"{time.time() - t0:6.1f}s  {label}")


k.new_document(width=1000, height=720, name="realism-test", background="#20252c")
k.paint(layer="Background", shapes=[{"type": "rect", "x": 0, "y": 0, "w": 1000, "h": 720, "fill": {
    "type": "radial", "cx": 380, "cy": 260, "r": 800, "stops": ["#4a5866", "#1a1e24"]}}])
k.paint(layer="Background", shapes=[{"type": "rect", "x": 0, "y": 520, "w": 1000, "h": 200, "fill": {
    "type": "linear", "x1": 0, "y1": 520, "x2": 0, "y2": 720, "stops": ["#3b3530", "#1d1a17"]}}])

# plastic sphere
k.paint(new_layer="Sphere", shapes=[{"type": "circle", "cx": 170, "cy": 420, "r": 110, "fill": "#c8312a"}])
k.render_form(layer="Sphere", material="plastic", profile="dome", key_angle=140, key_elevation=45,
              rim_intensity=0.5, rim_color="#9fd8ff")
lap("sphere")

# metal panel block: several flat regions -> bevelled plates
k.paint(new_layer="Metal", shapes=[
    {"type": "rect", "x": 330, "y": 300, "w": 240, "h": 260, "radius": 10, "fill": "#7d8794"},
    {"type": "rect", "x": 350, "y": 320, "w": 95, "h": 110, "radius": 6, "fill": "#8a93a0"},
    {"type": "rect", "x": 455, "y": 320, "w": 95, "h": 110, "radius": 6, "fill": "#848d9a"},
    {"type": "rect", "x": 350, "y": 440, "w": 200, "h": 100, "radius": 6, "fill": "#6f7884"},
    {"type": "circle", "cx": 450, "cy": 490, "r": 26, "fill": "#c9772c"},
])
k.render_form(layer="Metal", material="metal", profile="bevel", radius=9, key_angle=135, rim_intensity=0.4)
k.texture(layer="Metal", kind="scratches", scale=28, mode="screen", opacity=0.35, dark="#000000", light="#dfe8f0")
k.texture(layer="Metal", kind="grime", scale=60, mode="multiply", opacity=0.45, dark="#3a2c20", light="#ffffff")
lap("metal")

# stone blobs
k.paint(new_layer="Rocks", shapes=[
    {"type": "blob", "cx": 760, "cy": 560, "rx": 150, "ry": 80, "wobble": 0.25, "lumps": 6, "seed": 3, "fill": "#7b7468"},
    {"type": "blob", "cx": 640, "cy": 600, "rx": 80, "ry": 50, "rotation": 15, "wobble": 0.3, "seed": 8, "fill": "#857d70"},
])
k.render_form(layer="Rocks", material="stone", profile="dome", bump=0.9, bump_scale=7, key_angle=135)
lap("rocks")

# organic tentacle from tubes (skin)
k.paint(new_layer="Tentacle", shapes=[
    {"type": "tube", "spine": [[700, 520, 34], [690, 430, 30], [740, 340, 24], [820, 290, 17], [880, 220, 10],
                               [860, 160, 5]], "fill": "#d48a7a"},
])
k.render_form(layer="Tentacle", material="skin", profile="dome", key_angle=150, rim_intensity=0.6,
              rim_color="#ffd0b0")
k.paint(layer="Tentacle", clip=True, shapes=[
    {"type": "blob", "cx": x, "cy": y, "rx": r, "ry": r * 0.8, "wobble": 0.1, "seed": i, "fill": "#e6b0a2"}
    for i, (x, y, r) in enumerate([(722, 470, 9), (712, 420, 8), (750, 370, 7), (800, 320, 6), (850, 270, 5)])])
lap("tentacle")

# leaves on tubes with natural vein lines
leaves = []
for i, (x, y, a) in enumerate([(120, 200, -30), (210, 160, 10), (280, 220, 40)]):
    import math
    dx, dy = math.cos(math.radians(a - 90)), math.sin(math.radians(a - 90))
    leaves.append({"type": "tube", "spine": [[x, y, 1], [x + dx * 40, y + dy * 40, 22], [x + dx * 95, y + dy * 95, 1]],
                   "fill": ["#4f8a3a", "#5c9a42", "#477f34"][i]})
k.paint(new_layer="Leaves", shapes=leaves)
k.render_form(layer="Leaves", material="leaf", profile="pillow", radius=14, key_angle=120)
veins = []
for (x, y, a) in [(120, 200, -30), (210, 160, 10), (280, 220, 40)]:
    dx, dy = math.cos(math.radians(a - 90)), math.sin(math.radians(a - 90))
    veins.append({"points": [[x, y], [x + dx * 50, y + dy * 50], [x + dx * 90, y + dy * 90]], "size": 2.2})
k.draw_strokes(layer="Leaves", engine="ink", color="#2b4a20", strokes=veins, natural=0.5, clip=True)
lap("leaves")

# natural sketch lines vs plain
k.draw_strokes(new_layer="Lines", engine="pencil", size=3, color="#e9e2d0", strokes=[
    {"points": [[40, 640], [300, 600], [560, 650]]}], natural=0.0)
k.draw_strokes(layer="Lines", engine="pencil", size=3, color="#e9e2d0", strokes=[
    {"points": [[40, 690], [300, 650], [560, 700]]}], natural=0.6, passes=3)
lap("lines")

k.cast_shadow(layer="Sphere", direction=[0.55, 0.22])
k.cast_shadow(layer="Metal", direction=[0.55, 0.22])
k.cast_shadow(layer="Rocks", direction=[0.55, 0.22], base_y=640)
lap("shadows")
k.export_image(path=os.path.join(out, "realism-before-paint.png"))
k.painterly(new_layer="Painterly", sizes=[16, 8, 4, 2], threshold=0.05)
lap("painterly")
k.export_image(path=os.path.join(out, "realism-painterly.png"))
k.save(path=os.path.join(out, "realism-test.kra"))
lap("done")
