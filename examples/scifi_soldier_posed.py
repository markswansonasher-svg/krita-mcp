"""
Example: the sci-fi soldier in a dynamic pose, drawn with draw_figure.

The pose is a few numbers (stance, twist, lean, head, where the hands are); the figure engine
solves elbows and knees, draws continuous anatomical contours, and the armor is attached to bones
in bone-local coordinates - so it follows the pose with no re-measuring. The rifle is placed by
the two hands that hold it. Same camera and hallway as scifi_soldier.py.

    uv run --with "mcp>=1.2,<2" --with numpy --with scipy --with pillow \
        python examples/scifi_soldier_posed.py [out_dir]
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import server as k  # noqa: E402
import scifi_soldier as S  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "soldier-out")

SUIT, ARMOR, ARMOR2, ARMOR_DK = "#2f353f", "#6f7c8e", "#64717f", "#4a5361"
BELT, PACK, VISOR, ACCENT = "#2a2e35", "#262b33", "#ffb43a", "#ff7b1c"
GUN, GUN2, GUN3, HAND = "#2a3039", "#3a434f", "#323a45", "#3c424c"

CAMERA = {"eye": [0, S.CAM_H, 0], "pitch": math.degrees(S.PITCH), "focal": S.F, "center": [S.CX, S.CY]}

POSE = {
    "root": [0.0, S.Z_SOLDIER], "facing": 8,
    "feet": {"l": [0.25, 0.08, 0.1], "r": [-0.21, 0.08, -0.08]},     # wide stance, weight on its left leg
    "side_bend": -3, "twist": 14, "lean": -4,                       # chest turned, leaning back a touch
    "head": {"yaw": -10, "pitch": 14},                              # looking down at the viewer
    "hands": {"r": [-0.1, 1.0, 0.3], "l": [0.27, 1.22, 0.36]},      # rifle diagonally across the body
}


def armor():
    a = []
    for s in ("l", "r"):
        a += [
            # legs
            {"bone": "thigh_" + s, "points": [(0.1, -0.92), (0.08, 0.92), (0.82, 0.88), (0.9, 0.0), (0.82, -0.88)],
             "smooth": False, "corner_radius": 9, "fill": ARMOR, "lines": [[(0.25, -0.7), (0.27, 0.0), (0.25, 0.7)]],
             "joins": False},
            {"bone": "shin_" + s, "points": [(0.18, -0.95), (0.18, 0.95), (0.97, 0.82), (1.0, -0.82)], "smooth": False,
             "corner_radius": 10, "fill": ARMOR, "lines": [[(0.18, 0.0), (1.0, 0.0)]]},
            {"bone": "shin_" + s, "points": [(-0.14, -1.05), (-0.14, 1.05), (0.12, 1.0), (0.18, 0.0), (0.12, -1.0)],
             "fill": ARMOR2, "layer": 1},
            # arms: pauldrons, elbow pads, gauntlets
            {"bone": "upper_arm_" + s, "points": [(-0.28, -1.6), (-0.38, 0.0), (-0.28, 1.6), (0.38, 1.45), (0.5, 0.0),
                                                  (0.38, -1.45)], "fill": ARMOR, "thickness": 1.15,
             "lines": [[(-0.3, 0.9), (0.42, 0.6)], [(-0.3, 1.25), (0.4, 0.95)]], "joins": True},
            {"bone": "forearm_" + s, "points": [(0.3, -1.08), (0.3, 1.08), (0.97, 1.0), (0.97, -1.0)], "smooth": False,
             "corner_radius": 8, "fill": ARMOR_DK, "lines": [[(0.55, -1.0), (0.58, 0.0), (0.55, 1.0)]]},
            {"bone": "forearm_" + s, "points": [(-0.16, -1.1), (-0.16, 1.1), (0.14, 1.0), (0.2, 0.0), (0.14, -1.0)],
             "fill": ARMOR2, "layer": 1},
        ]
    a += [
        # torso: backpack (behind), belt, fauld, abdominal plates, chest plate, gorget
        {"bone": "torso", "points": [(0.45, -1.15), (0.45, 1.15), (1.02, 1.1), (1.06, -1.1)], "smooth": False,
         "corner_radius": 14, "fill": PACK, "behind": True},
        {"bone": "torso", "points": [(0.06, -1.06), (0.06, 1.06), (0.2, 1.0), (0.2, -1.0)], "smooth": False,
         "corner_radius": 5, "fill": BELT, "lines": [[(0.06, -0.35), (0.2, -0.35)], [(0.06, 0.35), (0.2, 0.35)]]},
        {"bone": "torso", "points": [(0.08, -0.45), (0.08, 0.45), (-0.12, 0.3), (-0.2, 0.0), (-0.12, -0.3)],
         "fill": ARMOR2},
        {"bone": "torso", "points": [(0.22, -0.95), (0.22, 0.95), (0.42, 0.9), (0.42, -0.9)], "smooth": False,
         "corner_radius": 8, "fill": ARMOR_DK, "lines": [[(0.32, -0.9), (0.32, 0.9)]]},
        {"bone": "torso", "points": [(0.44, -0.98), (0.44, 0.98), (0.75, 1.08), (0.93, 0.8), (0.97, 0.0), (0.93, -0.8),
                                     (0.75, -1.08)], "fill": ARMOR, "thickness": 1.08,
         "lines": [[(0.44, 0.0), (0.96, 0.0)], [(0.74, -1.0), (0.68, -0.45), (0.7, 0.0)],
                   [(0.74, 1.0), (0.68, 0.45), (0.7, 0.0)]]},
        {"bone": "torso", "points": [(0.92, -0.55), (0.92, 0.55), (1.06, 0.42), (1.06, -0.42)], "smooth": False,
         "corner_radius": 6, "fill": ARMOR_DK},
        # helmet with brow line and visor (head bone: neck -> head centre)
        {"bone": "head", "points": [(1.78, 0.0), (1.62, 0.72), (1.25, 1.08), (0.86, 1.02), (0.56, 0.66), (0.46, 0.0),
                                    (0.56, -0.66), (0.86, -1.02), (1.25, -1.08), (1.62, -0.72)], "fill": ARMOR,
         "thickness": 1.18, "lines": [[(1.4, -1.0), (1.47, 0.0), (1.4, 1.0)]]},
        {"bone": "head", "points": [(1.3, -0.92), (1.35, 0.0), (1.3, 0.92), (1.05, 0.85), (1.0, 0.0), (1.05, -0.85)],
         "fill": VISOR, "thickness": 1.18, "layer": 1},
    ]
    return a


def rifle_frame(info):
    """The rifle sits in the hands: grip in the right hand, foregrip in the left."""
    g, f = info["joints"]["hand_r"], info["joints"]["hand_l"]
    dx, dy = f[0] - g[0], f[1] - g[1]
    span = math.hypot(dx, dy)
    L = span / (0.69 - 0.31)                     # rifle length in px (grip at u=.31, foregrip at u=.69)
    ux, uy = dx / span, dy / span
    nx, ny = -uy, ux
    if ny > 0:                                   # 'up' across the rifle = toward the top of the screen
        nx, ny = -nx, -ny
    ox, oy = g[0] - ux * 0.31 * L, g[1] - uy * 0.31 * L

    def rp(u, v):
        vv = v / 1.17 * L                        # v was designed in metres for a 1.17 m rifle
        return [round(ox + ux * u * L + nx * vv, 2), round(oy + uy * u * L + ny * vv, 2)]
    return rp, L


def rifle_strokes(rp, L):
    def poly(pts, fill, size, corner):
        return {"outline": {"type": "polygon", "points": [rp(u, v) for u, v in pts], "corner_radius": corner},
                "fill": fill, "size": size, "occlude": True}
    hv, md, fn = 6.0, 3.2, 1.8
    s = [
        poly([(0.0, -0.044), (0.07, -0.074), (0.24, -0.066), (0.276, -0.13), (0.34, -0.13), (0.355, -0.062),
              (0.74, -0.05), (0.79, -0.031), (1.08, -0.027), (1.086, -0.004), (1.08, 0.018), (0.8, 0.022),
              (0.72, 0.062), (0.36, 0.075), (0.33, 0.1), (0.16, 0.07), (0.12, 0.056), (0.02, 0.046)], GUN, hv, 4),
        poly([(0.45, -0.055), (0.49, -0.168), (0.56, -0.162), (0.54, -0.052)], GUN2, md, 5),
        poly([(0.36, 0.075), (0.6, 0.068), (0.6, 0.12), (0.37, 0.126)], GUN2, md, 6),
        poly([(0.6, -0.048), (0.79, -0.034), (0.795, 0.024), (0.6, 0.066)], GUN3, md, 5),
        poly([(0.42, -0.014), (0.59, -0.014), (0.59, 0.014), (0.42, 0.014)], "#0b1418", fn, 6),
        {"points": [rp(0.14, -0.071), rp(0.14, 0.063)], "size": md, "joins": True, "smooth": False},
    ]
    s += [{"points": [rp(u, -0.032), rp(u + 0.008, 0.035)], "size": fn, "taper": 0.3, "smooth": False}
          for u in (0.64, 0.68, 0.72, 0.76)]
    # hands on top: fist around the grip with finger bands, support hand under the shroud with fingertips
    fist = [(0.255, -0.045), (0.31, -0.038), (0.38, -0.04), (0.396, -0.07), (0.392, -0.13), (0.37, -0.157),
            (0.3, -0.162), (0.262, -0.14), (0.25, -0.09)]
    s.append(poly(fist, HAND, hv, 10))
    for v in (-0.068, -0.096, -0.124):
        s.append({"points": [rp(0.316, v), rp(0.355, v - 0.004), rp(0.396, v + 0.002)], "size": md, "joins": True})
    s.append({"points": [rp(0.312, -0.038), rp(0.318, -0.08), rp(0.3, -0.162)], "size": md, "joins": True})
    palm = [(0.62, -0.046), (0.7, -0.05), (0.758, -0.048), (0.766, -0.085), (0.738, -0.128), (0.67, -0.137),
            (0.628, -0.11)]
    s.append(poly(palm, HAND, hv, 10))
    r_tip = 0.012 / 1.17 * L
    for u in (0.632, 0.66, 0.688, 0.716):
        s.append({"outline": {"type": "tube", "spine": [rp(u + 0.013, 0.03) + [r_tip], rp(u + 0.013, 0.068) + [r_tip]]},
                  "fill": HAND, "size": md, "occlude": True})
    return s



# ----------------------------------------------------------------------------- depth and scene lighting

ZS = [2.0 + 2.0 * i for i in range(19)]       # hallway segment positions (as in scifi_soldier.stage_hall)


def W(x, y, z):
    """Hallway coordinates (y relative to the camera) -> world (y up from the floor)."""
    return [x, y + S.CAM_H, z]


def hall_depth():
    polys = []
    far = 40.0
    for i, z0 in enumerate(ZS):
        z1 = ZS[i + 1] if i + 1 < len(ZS) else far
        for f in range(8):
            a, b = S.SECTION[f], S.SECTION[(f + 1) % 8]
            polys.append([W(a[0], a[1], z0), W(b[0], b[1], z0), W(b[0], b[1], z1), W(a[0], a[1], z1)])
    polys.append([W(x, y, far) for x, y in S.SECTION])
    k.add_depth(polygons=polys, camera=CAMERA, reset=True)


def hall_lights():
    """The lamps that are actually in the hallway: ceiling strips, warm floor lamps, the bright far end."""
    lights = []
    for z0 in ZS[:6]:
        lights.append({"pos": [0.0, S.CEIL + S.CAM_H - 0.05, z0 + 1.0], "color": "#cff8ff", "intensity": 0.55,
                       "range": 1.6})
    for z0 in ZS[:4]:
        for side in (-1, 1):
            lights.append({"pos": [1.36 * side, S.FLOOR + S.CAM_H + 0.3, z0 + 0.6], "color": "#ffaa55",
                           "intensity": 0.45, "range": 1.1})
    lights.append({"pos": [0.0, 1.4, 12.0], "color": "#9fefff", "intensity": 0.3, "range": 9.0})
    return lights


def stage_figure():
    top = k.list_layers()["layers"][0]["name"]
    k.select_layer(layer=top)
    k.add_layer(name="Soldier", type="group")
    k.add_layer(name="Lines", parent="Soldier")
    colors = {"skin": SUIT, "torso": SUIT, "head": ARMOR_DK, "hand": HAND}
    # first pass only to learn where the hands land, then draw figure + rifle in one go
    import figure as fig
    cam = fig.Camera(CAMERA["eye"], CAMERA["pitch"], 0, CAMERA["focal"], tuple(CAMERA["center"]))
    _, info0, _, _ = fig.figure_strokes(POSE, cam, attachments=[])
    rp, L = rifle_frame(info0)
    info = k.draw_figure(POSE, camera=CAMERA, layer="Lines", new_layer=None, colors=colors, attachments=armor(),
                         line_sizes=[6.0, 3.2, 1.8], extra_strokes=rifle_strokes(rp, L))
    r = k.fill_line_art(line_layer="Lines", background_seeds=[S.body(0.0, 0.5, 0.0)], gap=3, default_color=SUIT,
                        new_layer="Flats")
    for prob in r.get("seed_problems", []):
        print("fill:", prob)
    k.render_form(layer="Flats", material="painted_metal", profile="round", radius=10, depth=1.1,
                  key_angle=215, key_elevation=24, key_color="#ffbb88", key_intensity=1.2,
                  fill_color="#3f8fa3", fill_intensity=0.6, sky_color="#8fe6f4", ground_color="#5a4030",
                  ambient=0.75, rim_angle=75, rim_color="#b8f8ff", rim_intensity=1.6, ao=0.6,
                  env_sky="#d4fbff", env_ground="#6a5040", bump=0.1, bump_scale=4,
                  material_overrides={"metalness": 0.35})
    k.texture(layer="Flats", kind="grime", scale=70, dark="#2a1e14", light="#ffffff", mode="multiply", opacity=0.3)
    # the hallway's own lamps light the soldier (positions from the 3D scene + the depth buffer)
    k.scene_light(layer="Flats", lights=hall_lights(), camera=CAMERA, opacity=0.8, new_layer="Hall lamps")
    k.edge_light(layer="Flats", angle=70, color="#aef6ff", width=5, opacity=0.9, by_color=True, inner=0.35,
                 new_layer="Rim")
    k.edge_light(layer="Flats", angle=215, color="#ffa860", width=4, opacity=0.55, new_layer="Kicker")
    k.set_layer(layer="Lines", position="top")
    # visor and energy-cell glow
    import figure as fig2  # noqa: F401
    hf = info["bones"]["head"]
    hc = info["joints"]["head"]
    n = hf["normal"]
    d = hf["dir"]
    w = 0.085 * fig.build_skeleton(POSE)["_scale"] * cam.scale(fig.build_skeleton(POSE)["head"])
    vis = [[hc[0] + d[0] * w * 0.22 + n[0] * w * t, hc[1] + d[1] * w * 0.22 + n[1] * w * t] for t in (-0.85, -0.3, 0.3, 0.85)]
    cell = [rp(0.43, 0.0), rp(0.58, 0.0)]
    k.draw_strokes(new_layer="Glow", engine="ink", snap=False, strokes=[
        {"points": vis, "size": 14, "color": "#ffd27a", "opacity": 0.55, "taper": 0.3},
        {"points": cell, "size": 7, "color": "#9ff8ff", "taper": 0.1}])
    k.draw_strokes(new_layer="Glow bloom", engine="ink", blur=16, snap=False, strokes=[
        {"points": vis, "size": 36, "color": "#ff9a2e", "opacity": 0.8},
        {"points": cell, "size": 26, "color": "#2fd8ff"}])
    k.set_layer(layer="Glow bloom", blend_mode="add")


def main():
    os.makedirs(OUT, exist_ok=True)
    S.REAL = True
    S.stage_hall()
    hall_depth()                      # the hallway's 3D faces -> depth buffer
    stage_figure()                    # the figure writes its own depth
    # real cast shadow from the ceiling strip just behind him, and contact occlusion around him
    k.figure_shadow(POSE, light=[0.0, S.CEIL + S.CAM_H - 0.05, 5.0], camera=CAMERA, opacity=0.7, above="Hall")
    k.ambient_occlusion(radius=22, strength=0.9, above="Figure shadow")
    S.REAL = False
    S.stage_finish()
    # aerial perspective and focus: the far hall fades and softens, the soldier stays sharp
    k.atmosphere(color="#8cc7d6", density=0.045, start=2.0, max_opacity=0.7, above="Soldier")
    focus_at = S.body(0.0, 1.4, -0.1)
    k.depth_of_field(focus_point=focus_at, focus_range=0.6, max_blur=7)
    k.save(path=os.path.join(OUT, "scifi-soldier-posed.kra"))
    k.export_image(path=os.path.join(OUT, "soldier-posed.png"))
    print("exported", os.path.join(OUT, "soldier-posed.png"))


if __name__ == "__main__":
    main()
