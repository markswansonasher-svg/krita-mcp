"""
Example: the sci-fi soldier DRAWN as line art, in one pass.

Every part is an ink contour drawn back to front with draw_strokes:
  - limbs are "tube" outlines (a spine with a radius per point) - natural tapering contours
  - armor plates are rounded-corner polygons or smooth closed paths
  - each outline carries its "fill" color and parts in front "occlude" (erase the lines behind them)
  - seams and panel lines are "joins" lines whose ends snap onto the contours they meet
Then fill_line_art colors it (no seed coordinates), render_form lights it, edge_light adds the rim
and kicker, and the glow goes on top. Same camera and hallway as scifi_soldier.py.

    uv run --with "mcp>=1.2,<2" --with numpy --with scipy --with pillow \
        python examples/scifi_soldier_drawn.py [out_dir]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import server as k  # noqa: E402
import scifi_soldier as S  # noqa: E402  (camera, hallway, finishing passes)

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "soldier-out")
body, rifle_pt = S.body, S.rifle_pt

INK = "#0c1017"
HEAVY, MID, FINE = 6.0, 3.2, 1.8
SUIT, ARMOR, ARMOR2, ARMOR_DK, ARMOR_DK2 = "#2f353f", "#6f7c8e", "#64717f", "#4a5361", "#525c6a"
BELT, POUCH, PACK = "#2a2e35", "#3b4048", "#262b33"
VISOR, ACCENT = "#ffb43a", "#ff7b1c"
GUN, GUN2, GUN3, HAND = "#2a3039", "#3a434f", "#323a45", "#3c424c"


def _px():
    a, b = rifle_pt(0.5, 0.0), rifle_pt(0.5, 0.1)
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 / 0.1


PX = None   # pixels per metre near the soldier, set in main()


# --- drawing vocabulary: soldier space (metres) -> line-art strokes ---------------------

def pts(points, dz=0.0, mirror=False):
    return [body(-x if mirror else x, y, dz) for x, y in points]


def outline(shape, fill, size=HEAVY, occlude=True):
    return {"outline": shape, "fill": fill, "size": size, "occlude": occlude}


def part(points, fill, dz=0.0, mirror=False, corner=0.012, size=HEAVY, smooth=False, occlude=True):
    """A plate: closed contour through soldier-space points, rounded corners (corner in metres)."""
    if smooth:
        shape = {"type": "path", "points": pts(points, dz, mirror), "smooth": True}
    else:
        shape = {"type": "polygon", "points": pts(points, dz, mirror), "corner_radius": corner * PX}
    return outline(shape, fill, size, occlude)


def limb(spine, fill, mirror=False, size=HEAVY, occlude=True):
    """A limb contour along a spine of (x, y, radius, dz) in metres."""
    sp = [body(-x if mirror else x, y, dz) + [r * PX] for x, y, r, dz in spine]
    return outline({"type": "tube", "spine": sp}, fill, size, occlude)


def seam(points, dz=0.0, mirror=False, size=MID):
    return {"points": pts(points, dz, mirror), "size": size, "joins": True}


def detail(points, dz=0.0, mirror=False, size=FINE):
    return {"points": pts(points, dz, mirror), "size": size, "taper": 0.35}


def both(fn, *a, **kw):
    return [fn(*a, **kw), fn(*a, mirror=True, **kw)]


def rpts(points):
    return [rifle_pt(u, v) for u, v in points]


# --- the figure, back to front ------------------------------------------------------------

def figure():
    s = []
    # backpack and antenna (furthest back)
    s.append(part([(-0.25, 1.34), (0.25, 1.34), (0.245, 1.69), (0.15, 1.735), (-0.15, 1.735), (-0.245, 1.69)],
                  PACK, dz=0.16, corner=0.03, size=MID))
    s.append({"points": [body(0.2, 1.66, 0.14) + [1.0], body(0.212, 1.85, 0.14) + [0.7],
                         body(0.232, 2.12, 0.14) + [0.15]], "size": 3.4, "taper": 0.1})

    # legs: undersuit limbs, then thigh plates, shin guards, knee caps in front
    s += both(limb, [(0.11, 0.98, 0.088, 0.0), (0.15, 0.8, 0.082, 0.0), (0.17, 0.6, 0.064, 0.0),
                     (0.19, 0.42, 0.068, 0.0), (0.215, 0.2, 0.056, 0.0), (0.235, -0.16, 0.05, 0.0)], SUIT)
    s += both(part, [(0.085, 0.962), (0.2, 0.966), (0.226, 0.82), (0.21, 0.69), (0.15, 0.662), (0.1, 0.68),
                     (0.084, 0.8)], ARMOR, dz=-0.06, corner=0.02, size=MID)
    s += both(detail, [(0.11, 0.9), (0.15, 0.905), (0.195, 0.9)], dz=-0.065)
    s += both(part, [(0.123, 0.452), (0.238, 0.452), (0.264, 0.3), (0.27, -0.16), (0.15, -0.16), (0.127, 0.3)],
              ARMOR, dz=-0.07, corner=0.018, size=MID)
    s += both(seam, [(0.181, 0.452), (0.193, 0.3), (0.2, 0.12), (0.207, -0.16)], dz=-0.075)
    for m in (False, True):
        c = body(-0.17 if m else 0.17, 0.552, -0.09)
        s.append(outline({"type": "blob", "cx": c[0], "cy": c[1], "rx": 0.072 * PX, "ry": 0.06 * PX,
                          "wobble": 0.08, "lumps": 3, "seed": 2}, ARMOR2, MID))
    s += both(detail, [(0.14, 0.6), (0.17, 0.607), (0.205, 0.6)], dz=-0.1)

    # hips and torso undersuit, then belt, fauld, abs, chest, gorget
    s.append(part([(-0.205, 1.1), (0.205, 1.1), (0.222, 0.985), (0.1, 0.905), (0.0, 0.875), (-0.1, 0.905),
                   (-0.222, 0.985)], SUIT, corner=0.03))
    s.append(part([(-0.272, 1.45), (-0.2, 1.585), (0.2, 1.585), (0.272, 1.45), (0.205, 1.2), (0.19, 1.07),
                   (-0.19, 1.07), (-0.205, 1.2)], SUIT, dz=-0.02, corner=0.04))
    s.append(part([(-0.21, 0.998), (0.21, 0.998), (0.205, 1.088), (-0.205, 1.088)], BELT, dz=-0.1, corner=0.01,
                  size=MID))
    for x in (-0.135, 0.0, 0.135):
        s.append(part([(x - 0.035, 0.992), (x + 0.035, 0.992), (x + 0.032, 1.082), (x - 0.032, 1.082)], POUCH,
                      dz=-0.115, corner=0.01, size=MID))
    s.append(part([(-0.09, 0.995), (0.09, 0.995), (0.075, 0.88), (0.0, 0.83), (-0.075, 0.88)], ARMOR2,
                  dz=-0.08, smooth=True, size=MID))
    s.append(part([(-0.17, 1.095), (0.17, 1.095), (0.165, 1.148), (-0.165, 1.148)], ARMOR_DK2, dz=-0.09,
                  corner=0.012, size=MID))
    s.append(part([(-0.165, 1.152), (0.165, 1.152), (0.16, 1.205), (-0.16, 1.205)], ARMOR_DK, dz=-0.09,
                  corner=0.012, size=MID))
    s.append(part([(-0.123, 1.557), (-0.2, 1.535), (-0.255, 1.43), (-0.237, 1.32), (-0.19, 1.245), (0.0, 1.216),
                   (0.19, 1.245), (0.237, 1.32), (0.255, 1.43), (0.2, 1.535), (0.123, 1.557), (0.0, 1.565)],
                  ARMOR, dz=-0.11, smooth=True))
    s.append(seam([(0.0, 1.565), (0.004, 1.48), (0.002, 1.38), (0.0, 1.216)], dz=-0.12))
    s += both(seam, [(0.252, 1.43), (0.17, 1.405), (0.09, 1.392), (0.0, 1.398)], dz=-0.12)
    for i in range(3):
        y = 1.36 - i * 0.035
        s += both(detail, [(0.06, y), (0.1, y - 0.004), (0.14, y - 0.012)], dz=-0.12)
    s.append(part([(-0.125, 1.548), (0.125, 1.548), (0.1, 1.628), (-0.1, 1.628)], ARMOR_DK, dz=-0.07,
                  corner=0.015, size=MID))

    # helmet: shell, brow, visor, jaw vents
    helm = [(0.0, 1.888), (0.08, 1.865), (0.123, 1.8), (0.131, 1.72), (0.116, 1.655), (0.066, 1.625), (0.0, 1.618)]
    helm = helm + [(-x, y) for x, y in reversed(helm[1:-1])]
    s.append(part(helm, ARMOR, smooth=True))
    s.append(seam([(-0.126, 1.772), (-0.06, 1.786), (0.0, 1.79), (0.06, 1.786), (0.126, 1.772)], size=MID))
    s.append(part([(-0.11, 1.732), (0.0, 1.747), (0.11, 1.732), (0.104, 1.696), (0.0, 1.677), (-0.104, 1.696)],
                  VISOR, dz=-0.04, smooth=True, size=MID))
    s.append(seam([(-0.12, 1.66), (-0.05, 1.643), (0.0, 1.64), (0.05, 1.643), (0.12, 1.66)], dz=-0.03, size=FINE))
    for x in (-0.03, 0.0, 0.03):
        s.append(detail([(x - 0.006, 1.67), (x, 1.655)], dz=-0.05))
    s.append(detail([(0.0, 1.885), (0.003, 1.84), (0.0, 1.795)]))

    # upper arms, then pauldrons (lower plate, shell, stripe) over them
    s += both(limb, [(0.335, 1.48, 0.066, -0.02), (0.36, 1.33, 0.062, -0.04), (0.382, 1.2, 0.054, -0.07)], SUIT)
    s += both(part, [(0.3, 1.4), (0.4, 1.35), (0.455, 1.3), (0.43, 1.255), (0.37, 1.25), (0.31, 1.29)], ARMOR2,
              dz=-0.04, smooth=True, size=MID)
    s += both(part, [(0.19, 1.555), (0.25, 1.605), (0.33, 1.635), (0.41, 1.6), (0.458, 1.53), (0.462, 1.45),
                     (0.44, 1.385), (0.39, 1.35), (0.32, 1.385), (0.24, 1.45)], ARMOR, dz=-0.03, smooth=True)
    s += both(part, [(0.31, 1.628), (0.352, 1.64), (0.466, 1.515), (0.462, 1.472)], ACCENT, dz=-0.032,
              corner=0.006, size=MID)
    return s


FIST = [(0.255, -0.045), (0.31, -0.038), (0.38, -0.04), (0.396, -0.07), (0.392, -0.13), (0.37, -0.157),
        (0.3, -0.162), (0.262, -0.14), (0.25, -0.09)]
PALM = [(0.62, -0.046), (0.7, -0.05), (0.758, -0.048), (0.766, -0.085), (0.738, -0.128), (0.67, -0.137),
        (0.628, -0.11)]


def rifle_and_arms():
    s = []
    # rifle: body with softened corners, then its sub-parts in front
    body_pts = [(0.0, -0.044), (0.07, -0.074), (0.24, -0.066), (0.276, -0.13), (0.34, -0.13), (0.355, -0.062),
                (0.74, -0.05), (0.79, -0.031), (1.08, -0.027), (1.086, -0.004), (1.08, 0.018), (0.8, 0.022),
                (0.72, 0.062), (0.36, 0.075), (0.33, 0.1), (0.16, 0.07), (0.12, 0.056), (0.02, 0.046)]
    s.append(outline({"type": "polygon", "points": rpts(body_pts), "corner_radius": 0.006 * PX}, GUN))
    s.append(outline({"type": "polygon", "points": rpts([(0.45, -0.055), (0.49, -0.168), (0.56, -0.162),
                                                          (0.54, -0.052)]), "corner_radius": 0.008 * PX}, GUN2, MID))
    s.append(outline({"type": "polygon", "points": rpts([(0.36, 0.075), (0.6, 0.068), (0.6, 0.12), (0.37, 0.126)]),
                      "corner_radius": 0.01 * PX}, GUN2, MID))
    s.append(outline({"type": "polygon", "points": rpts([(0.6, -0.048), (0.79, -0.034), (0.795, 0.024),
                                                          (0.6, 0.066)]), "corner_radius": 0.008 * PX}, GUN3, MID))
    s.append(outline({"type": "polygon", "points": rpts([(0.42, -0.014), (0.59, -0.014), (0.59, 0.014),
                                                          (0.42, 0.014)]), "corner_radius": 0.01 * PX}, "#0b1418", FINE))
    s.append({"points": rpts([(0.14, -0.071), (0.14, 0.063)]), "size": MID, "joins": True, "smooth": False})
    for u in (0.64, 0.68, 0.72, 0.76):
        s.append({"points": rpts([(u, -0.032), (u + 0.008, 0.035)]), "size": FINE, "taper": 0.3, "smooth": False})

    # forearms (elbow on the body -> wrist at the hand on the rifle), elbow pads, gauntlet cuffs
    for elbow, wrist, r in (((-0.385, 1.195, -0.09), (0.255, -0.1), 0.046),
                            ((0.385, 1.2, -0.09), (0.69, -0.13), 0.048)):
        e, w = body(*elbow), rifle_pt(*wrist)
        mid = [(e[0] + w[0]) / 2, (e[1] + w[1]) / 2]
        s.append(outline({"type": "tube", "spine": [e + [r * PX], mid + [(r + 0.006) * PX], w + [r * 0.8 * PX]]},
                         ARMOR_DK, HEAVY))
        s.append(outline({"type": "blob", "cx": e[0], "cy": e[1], "rx": r * 1.15 * PX, "ry": r * 1.05 * PX,
                          "wobble": 0.06, "lumps": 3, "seed": 5}, ARMOR2, MID))
        dx, dy = w[0] - e[0], w[1] - e[1]
        ln = (dx * dx + dy * dy) ** 0.5
        nx, ny = -dy / ln, dx / ln
        for t in (0.42, 0.85):
            c = [e[0] + dx * t, e[1] + dy * t]
            rr = r * 1.3 * PX
            s.append({"points": [[c[0] + nx * rr, c[1] + ny * rr], [c[0] + dx / ln * 6, c[1] + dy / ln * 6],
                                 [c[0] - nx * rr, c[1] - ny * rr]], "size": MID, "joins": True})

    # right fist on the pistol grip: fist, knuckle ridge, fingers, thumb over the receiver
    s.append(outline({"type": "polygon", "points": rpts(FIST), "corner_radius": 0.018 * PX}, HAND))
    s.append({"points": rpts([(0.312, -0.038), (0.318, -0.08), (0.312, -0.125), (0.3, -0.162)]), "size": MID,
              "joins": True})
    for v in (-0.068, -0.096, -0.124):
        s.append({"points": rpts([(0.316, v), (0.355, v - 0.004), (0.396, v + 0.002)]), "size": MID, "joins": True})
    s.append(outline({"type": "tube", "spine": [rifle_pt(0.3, -0.04) + [0.016 * PX], rifle_pt(0.35, -0.02) + [0.015 * PX],
                                                rifle_pt(0.395, -0.022) + [0.012 * PX]]}, HAND, MID))
    # left hand under the shroud: palm, four fingertips curling over the top, thumb along the side
    s.append(outline({"type": "polygon", "points": rpts(PALM), "corner_radius": 0.02 * PX}, HAND))
    for u in (0.632, 0.66, 0.688, 0.716):
        s.append(outline({"type": "tube", "spine": [rifle_pt(u + 0.013, 0.03) + [0.012 * PX],
                                                    rifle_pt(u + 0.013, 0.068) + [0.011 * PX]]}, HAND, MID))
    s.append(outline({"type": "tube", "spine": [rifle_pt(0.63, -0.05) + [0.016 * PX], rifle_pt(0.6, -0.01) + [0.014 * PX],
                                                rifle_pt(0.61, 0.016) + [0.011 * PX]]}, HAND, MID))
    return s


def stage_drawn():
    top = k.list_layers()["layers"][0]["name"]
    k.select_layer(layer=top)
    k.add_layer(name="Soldier", type="group")
    k.add_layer(name="Lines", parent="Soldier")
    k.draw_strokes(layer="Lines", engine="ink", color=INK, strokes=figure(), natural=0.25, seed=3)
    k.draw_strokes(layer="Lines", engine="ink", color=INK, strokes=rifle_and_arms(), natural=0.2, seed=9)

    r = k.fill_line_art(line_layer="Lines", background_seeds=[body(0.0, 0.55, 0.0), body(0.0, 0.2, 0.0)], gap=3,
                        default_color=SUIT, new_layer="Flats")
    for prob in r.get("seed_problems", []):
        print("fill:", prob)
    k.render_form(layer="Flats", material="painted_metal", profile="round", radius=10, depth=1.1,
                  key_angle=215, key_elevation=24, key_color="#ffbb88", key_intensity=1.9,
                  fill_color="#3f8fa3", fill_intensity=0.6, sky_color="#8fe6f4", ground_color="#5a4030",
                  ambient=0.75, rim_angle=75, rim_color="#b8f8ff", rim_intensity=1.6, ao=0.6,
                  env_sky="#d4fbff", env_ground="#6a5040", bump=0.1, bump_scale=4,
                  material_overrides={"metalness": 0.35})
    k.texture(layer="Flats", kind="grime", scale=70, dark="#2a1e14", light="#ffffff", mode="multiply", opacity=0.3)
    k.texture(layer="Flats", kind="scratches", scale=30, dark="#000000", light="#9fb3c2", mode="screen",
              opacity=0.1, seed=5)
    k.edge_light(layer="Flats", angle=70, color="#aef6ff", width=5, opacity=0.9, by_color=True, inner=0.35,
                 new_layer="Rim")
    k.edge_light(layer="Flats", angle=215, color="#ffa860", width=4, opacity=0.55, new_layer="Kicker")
    k.set_layer(layer="Lines", position="top")

    # glow: visor and energy cell, with bloom
    vis = [body(x, y, -0.05) for x, y in ((-0.095, 1.712), (-0.04, 1.718), (0.04, 1.718), (0.095, 1.712))]
    cell = [rifle_pt(0.43, 0.0), rifle_pt(0.58, 0.0)]
    k.draw_strokes(new_layer="Glow", engine="ink", snap=False, strokes=[
        {"points": vis, "size": 16, "color": "#ffd27a", "opacity": 0.55, "taper": 0.3},
        {"points": [body(-0.07, 1.724, -0.05), body(0.03, 1.714, -0.05)], "size": 3, "color": "#fff8e0", "taper": 0.4},
        {"points": cell, "size": 7, "color": "#9ff8ff", "taper": 0.1}])
    k.draw_strokes(new_layer="Glow bloom", engine="ink", blur=16, snap=False, strokes=[
        {"points": vis, "size": 40, "color": "#ff9a2e", "opacity": 0.8},
        {"points": cell, "size": 26, "color": "#2fd8ff"}])
    k.set_layer(layer="Glow bloom", blend_mode="add")


def main():
    global PX
    os.makedirs(OUT, exist_ok=True)
    PX = _px()
    S.REAL = True
    S.stage_hall()
    stage_drawn()
    S.REAL = False          # keep the drawn lines crisp: no painterly pass over them
    S.stage_finish()
    k.save(path=os.path.join(OUT, "scifi-soldier-drawn.kra"))
    k.export_image(path=os.path.join(OUT, "soldier-drawn.png"))
    print("exported", os.path.join(OUT, "soldier-drawn.png"))


if __name__ == "__main__":
    main()
