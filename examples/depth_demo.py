"""
Depth demo: two simple characters at different distances in the hallway.

Everything that makes them sit IN the scene comes from the depth tools, not hand-tuning:
  - the hallway's 3D faces and both figures write a depth buffer
  - the hallway's own lamps light both figures (scene_light) - each gets the light that is near it
  - each casts a real shadow on the floor from the ceiling strip behind it (figure_shadow)
  - contact darkness where they meet the floor and walls (ambient_occlusion)
  - the far one fades into the air (atmosphere) and is out of focus (depth_of_field), and its lines
    are thinner and lighter (draw_figure depth_lines)

    uv run --with "mcp>=1.2,<2" --with numpy --with scipy --with pillow python examples/depth_demo.py [out_dir]
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import server as k  # noqa: E402
import scifi_soldier as S  # noqa: E402
import scifi_soldier_posed as P  # noqa: E402  (hall depth + hall lamps)

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "depth-out")
CAMERA = P.CAMERA

NEAR = {"root": [-0.55, 3.6], "facing": 25, "twist": -10, "lean": 3, "head": {"yaw": 15},
        "feet": {"l": [0.18, 0.08, 0.15], "r": [-0.16, 0.08, -0.12]},
        "hands": {"l": [0.3, 0.98, 0.12], "r": [-0.32, 1.05, 0.2]}}
FAR = {"root": [0.6, 9.5], "facing": -35, "head": {"yaw": -20},
       "feet": {"l": [0.14, 0.15, -0.25], "r": [-0.12, 0.08, 0.3]},          # walking toward us
       "hands": {"l": [0.24, 0.92, 0.25], "r": [-0.22, 0.95, -0.2]}}


def character(name, pose, body_color, suit_color):
    k.select_layer(layer=P_TOP[0])
    k.add_layer(name=name, type="group")
    k.add_layer(name=f"{name} lines", parent=name)
    k.draw_figure(pose, camera=CAMERA, layer=f"{name} lines", new_layer=None,
                  colors={"skin": suit_color, "torso": body_color, "head": "#d9dde3", "hand": suit_color},
                  attachments=[{"bone": "head", "points": [(1.3, -0.85), (1.34, 0.0), (1.3, 0.85), (1.07, 0.8),
                                                           (1.03, 0.0), (1.07, -0.8)], "fill": "#2a3440",
                                "thickness": 1.16}])
    k.fill_line_art(line_layer=f"{name} lines", new_layer=f"{name} flats", gap=3)
    k.render_form(layer=f"{name} flats", material="plastic", profile="dome", key_angle=110, key_elevation=55,
                  key_color="#dff8ff", key_intensity=0.9, ambient=0.6, sky_color="#8fe6f4", ground_color="#4a3a30",
                  rim_angle=80, rim_color="#bff8ff", rim_intensity=1.0)
    k.scene_light(layer=f"{name} flats", lights=P.hall_lights(), camera=CAMERA, opacity=0.8,
                  new_layer=f"{name} lamps")
    k.set_layer(layer=f"{name} lines", position="top")


P_TOP = []


def main():
    os.makedirs(OUT, exist_ok=True)
    S.REAL = True
    S.stage_hall()
    P.hall_depth()
    P_TOP.append(k.list_layers()["layers"][0]["name"])
    character("Far", FAR, "#c75b39", "#3d4a5a")        # far one first (behind)
    P_TOP[0] = "Far"
    character("Near", NEAR, "#e0a43a", "#3d4a5a")
    lamp = [0.0, S.CEIL + S.CAM_H - 0.05]
    k.figure_shadow(FAR, light=lamp + [11.0], camera=CAMERA, opacity=0.6, new_layer="Far shadow", above="Hall")
    k.figure_shadow(NEAR, light=lamp + [5.0], camera=CAMERA, opacity=0.7, new_layer="Near shadow", above="Far shadow")
    k.ambient_occlusion(radius=20, strength=0.9, above="Near shadow")
    # blend both figures into the hallway: its light wraps over their edges, its palette tints them
    k.integrate_subject("Far", light_wrap=0.7, wrap_radius=6, harmonize=0.35)
    k.integrate_subject("Near", light_wrap=0.6, wrap_radius=12, harmonize=0.3)
    S.REAL = False
    S.stage_finish()
    k.atmosphere(color="#8cc7d6", density=0.05, start=2.0, max_opacity=0.75, above="Near")
    j = k.call("status")  # noqa: F841
    focus = P.S.body(-0.55, 1.4, 3.6 - S.Z_SOLDIER)       # the near figure's chest
    k.depth_of_field(focus_point=focus, focus_range=0.8, max_blur=8)
    k.save(path=os.path.join(OUT, "depth-demo.kra"))
    k.export_image(path=os.path.join(OUT, "depth-demo.png"))
    print("exported", os.path.join(OUT, "depth-demo.png"))


if __name__ == "__main__":
    main()
