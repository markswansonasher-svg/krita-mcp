"""
Example: a sci-fi soldier in a spaceship hallway, seen from a low angle - painted only through
the Krita MCP tools (paint, paint_svg, draw_strokes, scatter_strokes, select...).

A tiny pinhole camera (0.45 m above the floor, tilted up 14 degrees, long lens) projects the hallway and the
soldier's body points, so the perspective is a true low-angle three-point view.

    uv run --with "mcp>=1.2,<2" python examples/scifi_soldier.py [stage] [out_dir]
stage: all (default), hall, soldier, finish
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server as k  # noqa: E402

W, H = 1200, 1600
CAM_H = 0.45                     # camera height above the floor (m)
PITCH = math.radians(14)         # looking up
F = 2100                         # focal length in px (a longer lens: heroic, not fish-eyed)
CX, CY = W / 2, 700
FLOOR, CEIL = -CAM_H, 3.2 - CAM_H
Z_SOLDIER = 3.4

STAGE = sys.argv[1] if len(sys.argv) > 1 else "all"
OUT = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "soldier-out")


def proj(x, y, z):
    """World (x right, y up from camera height, z forward) -> screen."""
    yp = y * math.cos(PITCH) - z * math.sin(PITCH)
    zp = y * math.sin(PITCH) + z * math.cos(PITCH)
    zp = max(zp, 0.05)
    return [round(CX + F * x / zp, 1), round(CY - F * yp / zp, 1)]


def body(x, y, dz=0.0):
    """Soldier space: x right, y up from the floor (m), dz toward(-)/away(+) from camera."""
    return proj(x, y - CAM_H, Z_SOLDIER + dz)


def poly(points, dz=0.0, mirror=False):
    return [body(-x if mirror else x, y, dz) for x, y in points]


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * t):02x}" for i in range(3))


FOG = "#3d8ea3"


def fogged(c, z, density=0.075):
    return mix(c, FOG, 1 - math.exp(-z * density))


# hallway cross-section (octagon), x / y relative to the camera
SECTION = [(-1.1, FLOOR), (1.1, FLOOR), (1.6, FLOOR + 0.5), (1.6, CEIL - 0.7), (1.0, CEIL),
           (-1.0, CEIL), (-1.6, CEIL - 0.7), (-1.6, FLOOR + 0.5)]
FACE_COL = ["#1b1f27", "#272d38", "#2b323e", "#323a48", "#232933", "#323a48", "#2b323e", "#272d38"]


def stage_hall():
    k.new_document(width=W, height=H, name="scifi-soldier", background="#0b1016")
    k.set_layer(layer="Paint", new_name="Hall")
    zs = [2.0 + 2.0 * i for i in range(19)]           # frame positions
    far = 40.0
    # far end: bright opening (the backlight)
    end = [proj(x, y, far) for x, y in SECTION]
    k.paint(layer="Hall", shapes=[{"type": "polygon", "points": end, "fill": "#bff6ff"}])
    # segments, far to near, each face with fog
    shapes = []
    for i in range(len(zs) - 1, -1, -1):
        z0 = zs[i]
        z1 = zs[i + 1] if i + 1 < len(zs) else far
        for f in range(8):
            a, b = SECTION[f], SECTION[(f + 1) % 8]
            q = [proj(*a, z0), proj(*b, z0), proj(*b, z1), proj(*a, z1)]
            shapes.append({"type": "polygon", "points": q, "fill": fogged(FACE_COL[f], (z0 + z1) / 2)})
    k.paint(layer="Hall", shapes=shapes)

    # wall panels: inset rectangles on the side walls and ceiling of every segment
    panels = []
    for i in range(len(zs) - 1, -1, -1):
        z0 = zs[i] + 0.25
        z1 = (zs[i + 1] if i + 1 < len(zs) else far) - 0.25
        zm = (z0 + z1) / 2
        for side in (-1, 1):
            x = 1.6 * side
            for (ya, yb) in ((FLOOR + 0.65, FLOOR + 1.35), (FLOOR + 1.5, CEIL - 0.85)):
                q = [proj(x, ya, z0), proj(x, yb, z0), proj(x, yb, z1), proj(x, ya, z1)]
                panels.append({"type": "polygon", "points": q, "fill": fogged("#1d222b", zm),
                               "stroke": fogged("#46505f", zm), "stroke_width": 1.2})
        q = [proj(-0.75, CEIL, z0), proj(0.75, CEIL, z0), proj(0.75, CEIL, z1), proj(-0.75, CEIL, z1)]
        panels.append({"type": "polygon", "points": q, "fill": fogged("#191d24", zm)})
    k.paint(layer="Hall", shapes=panels)

    # pipes along both walls (long tapered tubes with a highlight)
    pipes = []
    for side in (-1, 1):
        for yy, wdt in ((FLOOR + 1.42, 0.05), (FLOOR + 1.5, 0.035)):
            pts = [proj(1.55 * side, yy, z) for z in (2.0, 4, 8, 16, 30)]
            pipes.append({"points": pts, "size": 22 * wdt / 0.05, "color": "#141920", "taper": [0, 0.6]})
            pts = [proj(1.55 * side, yy + wdt * 0.6, z) for z in (2.0, 4, 8, 16, 30)]
            pipes.append({"points": pts, "size": 5 * wdt / 0.05, "color": "#7fa9b8", "opacity": 0.7,
                          "taper": [0, 0.7]})
    k.draw_strokes(layer="Hall", engine="ink", strokes=pipes)

    # frames (ribs): a ring at each z with an inner opening, drawn as even-odd SVG paths
    svg = []
    for i in range(len(zs) - 1, -1, -1):
        z = zs[i]
        for depth, col in ((0.18, "#14171d"), (0.0, "#3b4453")):
            zz = z + depth
            outer = [proj(x * 1.0, y, zz) for x, y in SECTION]
            inner = [proj(x * 0.9, CAM_H * 0 + (y - (FLOOR + CEIL) / 2) * 0.9 + (FLOOR + CEIL) / 2, zz)
                     for x, y in SECTION]
            d = "M" + " L".join(f"{p[0]} {p[1]}" for p in outer) + " Z M" + \
                " L".join(f"{p[0]} {p[1]}" for p in inner) + " Z"
            svg.append(f'<path fill-rule="evenodd" d="{d}" fill="{fogged(col, zz, 0.06)}"/>')
    k.paint_svg(layer="Hall", svg="".join(svg))

    # ceiling light strips (emissive) and warm accent lights on the lower bevels
    lights, warm = [], []
    for i in range(len(zs) - 1, -1, -1):
        z0 = zs[i] + 0.35
        z1 = (zs[i + 1] if i + 1 < len(zs) else far) - 0.35
        zm = (z0 + z1) / 2
        q = [proj(-0.22, CEIL - 0.01, z0), proj(0.22, CEIL - 0.01, z0), proj(0.22, CEIL - 0.01, z1),
             proj(-0.22, CEIL - 0.01, z1)]
        lights.append({"type": "polygon", "points": q, "fill": fogged("#e8fdff", zm, 0.03)})
        for side in (-1, 1):
            q = [proj(1.32 * side, FLOOR + 0.25, z0 + 0.3), proj(1.40 * side, FLOOR + 0.33, z0 + 0.3),
                 proj(1.40 * side, FLOOR + 0.33, z0 + 0.9), proj(1.32 * side, FLOOR + 0.25, z0 + 0.9)]
            warm.append({"type": "polygon", "points": q, "fill": fogged("#ffb347", zm, 0.03)})
    k.paint(new_layer="Lights", shapes=lights + warm)
    # bloom: blurred copies, added
    k.paint(new_layer="Bloom", mode="normal", blur=18, opacity=0.9, shapes=lights)
    k.set_layer(layer="Bloom", blend_mode="add")
    k.paint(layer="Bloom", blur=10, opacity=0.8, shapes=warm)
    k.paint(layer="Bloom", blur=60, opacity=0.8, shapes=[
        {"type": "polygon", "points": end, "fill": "#7fe9ff"}])

    # light falling on the walls/floor under each ceiling strip (screen, clipped to the hall)
    spill = []
    for i in range(len(zs) - 1, -1, -1):
        z0, z1 = zs[i] + 0.3, (zs[i + 1] if i + 1 < len(zs) else far) - 0.3
        zm = (z0 + z1) / 2
        q = [proj(-1.1, FLOOR, z0), proj(1.1, FLOOR, z0), proj(1.1, FLOOR, z1), proj(-1.1, FLOOR, z1)]
        spill.append({"type": "polygon", "points": q, "fill": fogged("#2f6f80", zm, 0.03)})
    k.paint(layer="Hall", mode="screen", blur=14, clip=True, opacity=0.45, shapes=spill)

    # floor grating lines
    grate = []
    for i in range(1, 60):
        z = 2.0 + i * 0.5
        a, b = proj(-1.05, FLOOR, z), proj(1.05, FLOOR, z)
        grate.append({"points": [a, b], "size": max(0.6, 5 / z), "color": fogged("#0a0c10", z), "opacity": 0.55})
    for x in (-0.9, -0.45, 0.0, 0.45, 0.9):
        grate.append({"points": [proj(x, FLOOR, 2.0), proj(x, FLOOR, 30)], "size": 1.6, "color": "#0c0f14", "opacity": 0.55})
    k.draw_strokes(layer="Hall", engine="ink", strokes=grate, smooth=False)



# ----------------------------------------------------------------------------- soldier

SUIT, SUIT_HI = "#14171d", "#2a303a"
ARMOR, ARMOR_DK = "#566275", "#343c49"
ACCENT, VISOR = "#ff7b1c", "#ffb43a"


def sym(pts):
    """Mirror a right-side outline to make it symmetric about x=0 (pts go from top-center down the right side)."""
    return pts + [(-x, y) for x, y in reversed(pts)]


# (name, outline in soldier space, dz, color, mirrored copy?)
SUIT_PARTS = [
    ("pack", [(-0.25, 1.34), (0.25, 1.34), (0.24, 1.69), (0.15, 1.73), (-0.15, 1.73), (-0.24, 1.69)], 0.16, "#1d222a", False),
    ("leg", [(0.03, 1.02), (0.21, 1.02), (0.25, 0.8), (0.23, 0.56), (0.27, 0.32), (0.31, -0.1), (0.13, -0.1),
             (0.12, 0.32), (0.1, 0.56), (0.07, 0.8)], 0.0, SUIT, True),
    ("pelvis", [(-0.17, 1.18), (0.17, 1.18), (0.21, 1.02), (0.05, 0.9), (-0.05, 0.9), (-0.21, 1.02)], 0.0, SUIT, False),
    ("torso", sym([(0.0, 1.61), (0.07, 1.61), (0.2, 1.57), (0.27, 1.44), (0.16, 1.12), (0.0, 1.12)]), 0.0, SUIT, False),
    ("neck", [(-0.065, 1.56), (0.065, 1.56), (0.06, 1.67), (-0.06, 1.67)], 0.02, SUIT, False),
    ("uparm_r", [(-0.41, 1.43), (-0.27, 1.43), (-0.3, 1.19), (-0.43, 1.19)], -0.02, SUIT, False),
    ("uparm_l", [(0.27, 1.43), (0.41, 1.43), (0.41, 1.21), (0.29, 1.19)], -0.02, SUIT, False),
]

ARMOR_PARTS = [
    ("thigh", [(0.08, 0.97), (0.22, 0.97), (0.245, 0.8), (0.22, 0.64), (0.11, 0.64), (0.085, 0.8)], -0.06, ARMOR, True),
    ("knee", [(0.1, 0.63), (0.24, 0.63), (0.265, 0.53), (0.22, 0.46), (0.12, 0.46), (0.085, 0.53)], -0.1, ARMOR, True),
    ("shin", [(0.12, 0.45), (0.245, 0.45), (0.28, 0.25), (0.295, -0.1), (0.14, -0.1), (0.13, 0.25)], -0.07, ARMOR, True),
    ("fauld", [(-0.09, 1.0), (0.09, 1.0), (0.07, 0.86), (0.0, 0.83), (-0.07, 0.86)], -0.08, ARMOR_DK, False),
    ("belt", [(-0.2, 1.08), (0.2, 1.08), (0.21, 0.99), (-0.21, 0.99)], -0.09, "#22272f", False),
    ("abs1", [(-0.15, 1.09), (0.15, 1.09), (0.16, 1.15), (-0.16, 1.15)], -0.08, ARMOR_DK, False),
    ("abs2", [(-0.165, 1.16), (0.165, 1.16), (0.18, 1.22), (-0.18, 1.22)], -0.09, ARMOR_DK, False),
    ("chest", sym([(0.0, 1.57), (0.08, 1.57), (0.2, 1.53), (0.255, 1.41), (0.2, 1.24), (0.0, 1.22)]), -0.11, ARMOR, False),
    ("gorget", [(-0.12, 1.55), (0.12, 1.55), (0.1, 1.64), (-0.1, 1.64)], -0.06, ARMOR_DK, False),
    ("pauldron", [(0.19, 1.56), (0.31, 1.62), (0.43, 1.55), (0.45, 1.43), (0.38, 1.35), (0.24, 1.39)], -0.03, ARMOR, True),
    ("pauldron2", [(0.25, 1.4), (0.39, 1.36), (0.44, 1.3), (0.43, 1.25), (0.3, 1.28)], -0.04, ARMOR_DK, True),
]

HELMET = [
    ("helmet", sym([(0.0, 1.885), (0.08, 1.865), (0.123, 1.8), (0.128, 1.72), (0.11, 1.655), (0.06, 1.63), (0.0, 1.63)]), 0.0, ARMOR, False),
    ("jaw", sym([(0.0, 1.68), (0.065, 1.675), (0.058, 1.64), (0.03, 1.622), (0.0, 1.618)]), -0.05, ARMOR_DK, False),
    ("visor", sym([(0.0, 1.735), (0.108, 1.728), (0.1, 1.695), (0.05, 1.678), (0.0, 1.676)]), -0.04, VISOR, False),
]

# forearms, hands (drawn after the rifle)
FRONT_PARTS = [
    ("forearm_r", [(-0.43, 1.22), (-0.34, 1.26), (-0.11, 1.15), (-0.14, 1.05)], -0.14, SUIT, False),
    ("bracer_r", [(-0.4, 1.215), (-0.33, 1.245), (-0.2, 1.18), (-0.23, 1.11)], -0.16, ARMOR, False),
    ("forearm_l", [(0.43, 1.24), (0.32, 1.16), (0.16, 1.31), (0.24, 1.41)], -0.17, SUIT, False),
    ("bracer_l", [(0.41, 1.24), (0.33, 1.18), (0.24, 1.27), (0.3, 1.33)], -0.19, ARMOR, False),
    ("hand_r", sym([(0.0, 0.0)]) and [(-0.18, 1.14), (-0.1, 1.16), (-0.07, 1.1), (-0.09, 1.03), (-0.16, 1.04)], -0.2, SUIT_HI, False),
    ("hand_l", [(0.15, 1.33), (0.22, 1.42), (0.28, 1.4), (0.25, 1.31), (0.19, 1.28)], -0.24, SUIT_HI, False),
]

RIFLE_A, RIFLE_B = (-0.34, 0.97), (0.58, 1.7)
RIFLE_DZ = -0.21
RIFLE = [  # (u along the gun in m, v across it in m)
    ("rifle", [(0.0, -0.045), (0.06, -0.075), (0.24, -0.065), (0.28, -0.13), (0.34, -0.13), (0.355, -0.06),
               (0.74, -0.05), (0.79, -0.03), (1.08, -0.026), (1.08, 0.018), (0.8, 0.022), (0.72, 0.062),
               (0.42, 0.072), (0.33, 0.1), (0.12, 0.055), (0.0, 0.045)], "#1e232b"),
    ("mag", [(0.45, -0.05), (0.49, -0.17), (0.56, -0.165), (0.54, -0.05)], "#2b313b"),
    ("scope", [(0.36, 0.075), (0.58, 0.075), (0.6, 0.12), (0.36, 0.125)], "#2e3540"),
    ("shroud", [(0.6, -0.045), (0.86, -0.035), (0.86, 0.03), (0.6, 0.05)], "#3c4554"),
]


def rifle_pt(u, v):
    ax, ay = RIFLE_A
    bx, by = RIFLE_B
    L = math.hypot(bx - ax, by - ay)
    dx, dy = (bx - ax) / L, (by - ay) / L
    nx, ny = -dy, dx
    return body(ax + dx * u + nx * v, ay + dy * u + ny * v, RIFLE_DZ - 0.04 * u)


def screen_parts(parts):
    out = []
    for name, pts, dz, col, mirrored in parts:
        out.append((name, poly(pts, dz), col))
        if mirrored:
            out.append((name + "_m", poly(pts, dz, mirror=True), col))
    return out


def rifle_parts():
    return [(name, [rifle_pt(u, v) for u, v in pts], col) for name, pts, col in RIFLE]


def shifted(pts, dx, dy):
    return [[x + dx, y + dy] for x, y in pts]


def fills(parts, color=None):
    return [{"type": "polygon", "points": p, "fill": color or c} for _, p, c in parts]


def depth_sequence(parts, color, dx, dy, lit=None):
    """Edge light/shade with occlusion: for each part, back to front, fill it and then cut away the
    same shape shifted - a crescent stays on the edge away from the shift. Because parts are drawn in
    order, a part in front covers (and replaces) the crescents of the parts behind it."""
    seq = []
    for name, p, _ in parts:
        if lit is not None and not name.startswith(lit):
            seq.append({"type": "polygon", "points": p, "erase": True})      # occluder only
            continue
        seq.append({"type": "polygon", "points": p, "fill": color})
        seq.append({"type": "polygon", "points": shifted(p, dx, dy), "erase": True})
    return seq


def outlined(parts, width=2.2, line="#0b0e13"):
    return [{"type": "polygon", "points": p, "fill": c, "stroke": line, "stroke_width": width} for _, p, c in parts]


def stage_soldier():
    back = screen_parts(SUIT_PARTS)
    armor = screen_parts(ARMOR_PARTS)
    helmet = screen_parts(HELMET)
    front = screen_parts(FRONT_PARTS)
    gun = rifle_parts()
    behind = back + armor + helmet            # drawn first
    infront = gun + front                     # drawn over them
    ordered = behind + infront

    # the soldier group goes on top of the whole hallway
    top = k.list_layers()["layers"][0]["name"]
    k.select_layer(layer=top)
    k.add_layer(name="Soldier", type="group")
    k.add_layer(name="Base", parent="Soldier")

    # antenna (behind the backpack's top)
    k.draw_strokes(layer="Base", engine="ink", strokes=[
        {"points": [body(0.2, 1.62, 0.14), body(0.215, 1.85, 0.14), body(0.235, 2.12, 0.14)], "size": 4,
         "color": "#3a4452", "taper": [0, 0.5]}])
    # 1) everything behind the rifle and forearms: fills + outlines in depth order
    k.paint(layer="Base", shapes=outlined(behind))
    # 2) surface detail on those parts (later covered by the rifle where it crosses)
    acc = []
    for s in (1, -1):
        acc.append({"type": "polygon", "points": poly([(0.33, 1.6), (0.37, 1.585), (0.43, 1.5), (0.395, 1.5)], -0.035,
                                                       mirror=s < 0), "fill": ACCENT})
        acc.append({"type": "polygon", "points": poly([(0.13, 0.6), (0.22, 0.6), (0.225, 0.58), (0.125, 0.58)], -0.11,
                                                       mirror=s < 0), "fill": ACCENT})
    acc.append({"type": "polygon", "points": poly([(-0.07, 1.47), (0.0, 1.43), (0.07, 1.47), (0.07, 1.44),
                                                   (0.0, 1.4), (-0.07, 1.44)], -0.12), "fill": ACCENT})
    k.paint(layer="Base", shapes=acc)
    seams = []
    for a, b in (((0.0, 1.56), (0.0, 1.25)), ((-0.21, 1.42), (-0.06, 1.38)), ((0.21, 1.42), (0.06, 1.38)),
                 ((-0.1, 1.3), (0.1, 1.3)), ((0.17, 0.4), (0.2, 0.05)), ((-0.17, 0.4), (-0.2, 0.05))):
        seams.append({"points": [body(*a, -0.12), body(*b, -0.12)], "size": 1.8, "color": "#0b0e13", "opacity": 0.8})
    k.draw_strokes(layer="Base", engine="ink", smooth=False, strokes=seams)
    k.scatter_strokes(layer="Base", region=poly([(-0.22, 1.26), (0.22, 1.26), (0.22, 1.54), (-0.22, 1.54)], -0.12),
                      count=60, length=[3, 10], angle=-20, angle_jitter=60, size=[0.7, 1.4],
                      colors=["#a5b5c8", "#0d1015"], opacity=[0.2, 0.5], seed=4, clip=True)
    for leg in (1, -1):
        k.scatter_strokes(layer="Base", region=poly([(0.14, 0.0), (0.27, 0.0), (0.24, 0.44), (0.13, 0.44)], -0.07,
                                                     mirror=leg < 0),
                          count=35, length=[3, 9], angle=-80, angle_jitter=40, size=[0.7, 1.3],
                          colors=["#a5b5c8", "#0d1015"], opacity=[0.2, 0.5], seed=5 + leg, clip=True)
    # 3) rifle, forearms and hands on top, also in depth order
    k.paint(layer="Base", shapes=outlined(infront))

    # --- form shadow: a multiply layer clipped to the soldier -------------------
    k.add_layer(name="Shade", blend_mode="multiply")
    k.set_layer(layer="Shade", clipped=True)
    k.paint(layer="Shade", shapes=[{"type": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": {
        "type": "radial", "cx": body(-0.1, 1.45)[0], "cy": body(-0.1, 1.45)[1], "r": 1050,
        "fx": body(-0.2, 1.35)[0], "fy": body(-0.2, 1.35)[1],
        "stops": [[0, "#ffffff"], [0.35, "#c3cbe0"], [0.75, "#5d6a8e"], [1, "#2f3850"]]}}])
    # bevel/occlusion shade on the lower-right edges of every part, occluded properly
    k.paint(layer="Shade", blur=3, opacity=0.75, shapes=depth_sequence(ordered, "#2a3248", -6, -7))

    # --- warm key light from the floor lights, lower left -----------------------
    k.add_layer(name="Key", blend_mode="add")
    k.set_layer(layer="Key", clipped=True)
    k.paint(layer="Key", blur=2, opacity=0.55, shapes=depth_sequence(ordered, "#ff8f3c", 8, -6))
    k.paint(layer="Key", blur=80, opacity=0.25, shapes=[{"type": "circle", "cx": 250, "cy": 1500, "r": 420,
                                                         "fill": "#ff8a3a"}])

    # --- cool rim light from the hallway behind: top and both sides --------------
    k.add_layer(name="Rim", blend_mode="add")
    k.set_layer(layer="Rim", clipped=True)
    k.paint(layer="Rim", blur=2, opacity=0.9, shapes=depth_sequence(ordered, "#7fefff", -6, 8))
    k.paint(layer="Rim", blur=2, opacity=0.7, shapes=depth_sequence(ordered, "#7fefff", 6, 8))
    k.paint(layer="Rim", blur=1, opacity=0.8, shapes=depth_sequence(ordered, "#e6ffff", 0, 3,
                                          lit=tuple(n for n, _, _ in armor + helmet[:1])))

    # --- specular glints on hard edges (not under the rifle) ---------------------
    spec = []
    for x, y, dz, sz in ((0.07, 1.86, 0, 6), (0.37, 1.6, -0.03, 7), (-0.37, 1.6, -0.03, 7),
                         (0.18, 0.62, -0.1, 5), (-0.18, 0.62, -0.1, 5), (-0.2, 1.5, -0.11, 4)):
        p = body(x, y, dz)
        spec.append({"points": [[p[0] - sz * 1.6, p[1]], [p[0] + sz * 1.6, p[1]]], "size": sz * 0.5,
                     "color": "#f0ffff", "taper": 0.5})
    k.add_layer(name="Glints")
    k.set_layer(layer="Glints", clipped=True)
    k.draw_strokes(layer="Glints", engine="ink", strokes=spec)

    # --- emissive: visor, rifle cell, chest light, with bloom ---------------------
    k.add_layer(name="Glow")
    visor = [p for n, p, _ in helmet if n == "visor"][0]
    ys = [q[1] for q in visor]
    k.paint(layer="Glow", shapes=[{"type": "polygon", "points": visor, "fill": {
        "type": "linear", "x1": 0, "y1": min(ys), "x2": 0, "y2": max(ys),
        "stops": [[0, "#fff3c8"], [0.45, VISOR], [1, "#b8500c"]]}}])
    a, b = body(-0.085, 1.726, -0.05), body(0.05, 1.7, -0.05)
    cell = [rifle_pt(0.42, 0.0), rifle_pt(0.7, 0.0)]
    k.draw_strokes(layer="Glow", engine="ink", strokes=[
        {"points": [a, b], "size": 2.5, "color": "#fffbe8", "taper": 0.4, "opacity": 0.9},
        {"points": cell, "size": 5, "color": "#9ff8ff", "taper": 0.1}])
    k.add_layer(name="Glow bloom", blend_mode="add")
    k.paint(layer="Glow bloom", blur=18, opacity=0.9, shapes=[{"type": "polygon", "points": visor, "fill": "#ff9a2e"}])
    k.draw_strokes(layer="Glow bloom", engine="ink", blur=12, strokes=[{"points": cell, "size": 22, "color": "#2fd8ff"}])
    # visor light spilling on the jaw and gorget
    k.select_layer(layer="Glints")
    k.add_layer(name="Visor spill", blend_mode="add")
    k.set_layer(layer="Visor spill", clipped=True)
    vc = body(0, 1.68, -0.06)
    k.paint(layer="Visor spill", blur=24, opacity=0.5, shapes=[
        {"type": "circle", "cx": vc[0], "cy": vc[1] + 25, "r": 60, "fill": "#ff8a2a"}])


def stage_finish():
    # floor shadow under the soldier (on the hall) and volumetric light from the ceiling strips
    feet = [body(-0.32, 0.0, 0.0), body(0.32, 0.0, 0.0)]
    k.paint(layer="Hall", mode="multiply", blur=25, opacity=0.8, shapes=[
        {"type": "polygon", "points": [body(-0.5, 0.0, -0.3), body(0.5, 0.0, -0.3), body(0.5, 0.0, 0.5),
                                       body(-0.5, 0.0, 0.5)], "fill": "#0a0d12"}])
    beams = []
    for z in (4.3, 6.3, 8.3, 10.3, 14.3):
        top = [proj(-0.22, CEIL, z), proj(0.22, CEIL, z + 1.3)]
        bot = [proj(-0.9, FLOOR, z - 0.2), proj(0.9, FLOOR, z + 1.5)]
        beams.append({"type": "polygon", "points": [top[0], [top[1][0], top[0][1]], [bot[1][0], bot[0][1]],
                                                    [bot[0][0], bot[0][1]]],
                      "fill": {"type": "linear", "x1": 0, "y1": top[0][1], "x2": 0, "y2": bot[0][1],
                               "stops": [[0, "#bff6ff"], [1, "#bff6ff00"]]}})
    k.select_layer(layer="Bloom")
    k.paint(new_layer="Beams", blur=30, opacity=0.18, shapes=beams)
    k.set_layer(layer="Beams", blend_mode="screen")
    # haze toward the far end
    vp = proj(0, (FLOOR + CEIL) / 2, 400)
    k.paint(new_layer="Haze", blur=0, opacity=0.3, shapes=[{"type": "rect", "x": 0, "y": 0, "w": W, "h": H,
        "fill": {"type": "radial", "cx": vp[0], "cy": vp[1], "r": 700, "stops": [[0, "#9be8f5"], [1, "#9be8f500"]]}}])
    k.set_layer(layer="Haze", blend_mode="screen")

    # dust in the air, some in front of the soldier (blurred = out of focus)
    top = k.list_layers()["layers"][0]["name"]
    k.select_layer(layer=top)
    k.scatter_strokes(new_layer="Dust", region=[0, 0, W, H], count=220, length=[1, 3], size=[1.2, 2.6],
                      angle=60, angle_jitter=180, colors=["#d8fbff", "#ffd9a8"], opacity=[0.25, 0.7], seed=11)
    k.set_layer(layer="Dust", blend_mode="add")
    k.scatter_strokes(layer="Dust", region=[0, 0, W, H], count=30, length=[1, 2], size=[8, 18], angle=0,
                      colors=["#bff6ff"], opacity=[0.08, 0.2], seed=12)
    # vignette and a color grade (teal shadows, warm low light)
    k.paint(new_layer="Vignette", shapes=[{"type": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": {
        "type": "radial", "cx": W / 2, "cy": H * 0.52, "r": H * 0.78,
        "stops": [[0, "#ffffff"], [0.45, "#ffffff"], [1, "#1c2230"]]}}])
    k.set_layer(layer="Vignette", blend_mode="multiply")
    k.paint(new_layer="Grade", opacity=0.35, shapes=[{"type": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": {
        "type": "linear", "x1": 0, "y1": 0, "x2": 0, "y2": H, "stops": ["#2b6f8a", "#808080", "#c4682a"]}}])
    k.set_layer(layer="Grade", blend_mode="soft_light")
    # film grain: mid-gray layer + noise filter, overlaid softly
    k.fill_layer(new_layer="Grain", color="#808080")
    k.apply_filter(filter="noise", layer="Grain", settings={"level": 60, "opacity": 100, "grayscale": True})
    k.set_layer(layer="Grain", blend_mode="overlay", opacity=0.12)


def main():
    os.makedirs(OUT, exist_ok=True)
    if STAGE in ("all", "hall"):
        stage_hall()
    if STAGE in ("all", "soldier"):
        stage_soldier()
    if STAGE in ("all", "finish"):
        stage_finish()
    k.save(path=os.path.join(OUT, "scifi-soldier.kra"))
    k.export_image(path=os.path.join(OUT, f"stage-{STAGE}.png"))
    print("exported", os.path.join(OUT, f"stage-{STAGE}.png"))


if __name__ == "__main__":
    main()
