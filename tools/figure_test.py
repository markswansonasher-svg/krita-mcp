"""Draws three poses with draw_figure (standing, walking 3/4, crouching aim) plus a pose sketch.
    uv run --with "mcp>=1.2,<2" --with numpy --with scipy --with pillow python tools/figure_test.py [out_dir]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server as k  # noqa: E402

out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "figure-out")
os.makedirs(out, exist_ok=True)
W, H = 1500, 900
cam = {"eye": [0, 1.0, -6.0], "pitch": 4, "focal": 1100, "center": [W / 2, H / 2]}

k.new_document(width=W, height=H, name="figure-test", background="#e9e5dc")
poses = [
    {"root": [-2.0, 0.0]},
    {"root": [0.0, 0.0], "facing": 35, "lean": 8, "twist": -15, "head": {"yaw": -20},
     "feet": {"l": [0.12, 0.08, 0.32], "r": [-0.14, 0.18, -0.3]},
     "hands": {"l": [0.24, 0.95, -0.2], "r": [-0.2, 0.92, 0.28]}},
    {"root": [2.0, 0.0], "facing": -30, "crouch": 0.32, "lean": 18, "side_bend": -5,
     "feet": {"l": [0.2, 0.08, 0.35], "r": [-0.22, 0.08, -0.25]},
     "hands": {"l": [0.05, 1.18, 0.5], "r": [-0.1, 1.08, 0.2]}, "head": {"pitch": 10}},
]
for i, pose in enumerate(poses):
    k.sketch_pose(pose, camera=cam, new_layer=f"Sketch {i}")
k.export_image(path=os.path.join(out, "poses-sketch.png"))
for i in range(len(poses)):
    k.delete_layer(layer=f"Sketch {i}")
for i, pose in enumerate(poses):
    info = k.draw_figure(pose, camera=cam, new_layer=f"Figure {i}", colors={"skin": "#d9b49a", "torso": "#7a8fa8",
                                                                             "head": "#e2c2a8", "hand": "#d9b49a"})
    k.fill_line_art(line_layer=f"Figure {i}", new_layer=f"Flats {i}")
    k.render_form(layer=f"Flats {i}", material="skin", profile="dome", key_angle=130, rim_intensity=0.4)
k.export_image(path=os.path.join(out, "poses.png"))
print("ok")
