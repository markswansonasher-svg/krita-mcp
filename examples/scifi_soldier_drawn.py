"""
Example: the sci-fi soldier DRAWN line by line - curved, hand-drawn ink lines (natural wobble,
pressure, tapers, weight hierarchy), then colored like line art is colored (fill_line_art), lit
(render_form), rim-lit with drawn lines and finished. No shape-building for the figure.

Uses the same camera and hallway as scifi_soldier.py.

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
body, rifle_pt, W, H = S.body, S.rifle_pt, S.W, S.H

INK = "#0c1017"
HEAVY, MID, FINE = 6.2, 3.3, 1.9

SUIT, ARMOR, ARMOR2, ARMOR_DK, ARMOR_DK2 = "#2f353f", "#6f7c8e", "#64717f", "#4a5361", "#525c6a"
BELT, POUCH, PACK = "#2a2e35", "#3b4048", "#262b33"
VISOR, ACCENT = "#ffb43a", "#ff7b1c"
GUN, GUN2, GUN3, HAND = "#2a3039", "#3a434f", "#323a45", "#3c424c"


def L(pts, dz=0.0, mirror=False, size=MID, taper=0.06, op=1.0, joins=True):
    """One drawn line through soldier-space points (x, y[, pressure]).
    joins=True: the line meets other lines at its ends, so its ends stay solid (no hairline gaps);
    joins=False: a free-ending detail line that tapers away."""
    sp = []
    for p in pts:
        x = -p[0] if mirror else p[0]
        q = body(x, p[1], p[3] if len(p) > 3 else dz)
        if len(p) > 2 and p[2] is not None:
            q = q + [p[2]]
        sp.append(q)
    st = {"points": sp, "size": size, "taper": taper if joins else max(taper, 0.35), "opacity": op}
    if joins:
        st["min_width"] = size * 0.55
    return st


def both(pts, **kw):
    return [L(pts, **kw), L(pts, mirror=True, **kw)]


def R(pts, size=MID, taper=0.04):
    """A line on the rifle, in rifle coordinates (u along, v across)."""
    return {"points": [rifle_pt(u, v) for u, v in pts], "size": size, "taper": taper, "min_width": size * 0.55}


# ----------------------------------------------------------------------------- the drawing

def back_lines():
    s = []
    # backpack edges peeking out beside the helmet, and the antenna
    s += both([(0.135, 1.722), (0.2, 1.71), (0.238, 1.66), (0.245, 1.6), (0.235, 1.56)], dz=0.16, size=MID)
    s.append(L([(0.2, 1.66, 1.0), (0.212, 1.85, 0.7), (0.232, 2.12, 0.15)], dz=0.14, size=3.4, taper=0.1))

    # helmet: dome, cheek/jaw sweep, brow, visor, ridge, vents
    s.append(L([(-0.129, 1.70), (-0.131, 1.77), (-0.108, 1.84), (-0.055, 1.879), (0.0, 1.888), (0.055, 1.879),
                (0.108, 1.84), (0.131, 1.77), (0.129, 1.70)], size=HEAVY))
    s.append(L([(-0.129, 1.70), (-0.122, 1.663), (-0.092, 1.638), (-0.048, 1.623), (0.0, 1.618), (0.048, 1.623),
                (0.092, 1.638), (0.122, 1.663), (0.129, 1.70)], dz=-0.03, size=HEAVY))
    s.append(L([(-0.125, 1.772), (-0.06, 1.786), (0.0, 1.79), (0.06, 1.786), (0.125, 1.772)], size=MID))
    s.append(L([(-0.113, 1.731), (-0.06, 1.743), (0.0, 1.746), (0.06, 1.743), (0.113, 1.731)], dz=-0.04, size=MID))
    s.append(L([(-0.107, 1.695), (-0.06, 1.681), (0.0, 1.677), (0.06, 1.681), (0.107, 1.695)], dz=-0.04, size=MID))
    s += both([(0.113, 1.731), (0.111, 1.713), (0.107, 1.695)], dz=-0.04, size=MID)
    s.append(L([(0.0, 1.888), (0.003, 1.84), (0.0, 1.79)], size=FINE, joins=False))
    for x in (-0.03, 0.0, 0.03):
        s.append(L([(x - 0.008, 1.66), (x, 1.645), (x + 0.006, 1.632)], dz=-0.05, size=FINE, joins=False))

    # neck seal and gorget
    s += both([(0.064, 1.628), (0.07, 1.6), (0.078, 1.567)], dz=-0.02, size=MID)
    s.append(L([(-0.125, 1.556), (-0.06, 1.569), (0.0, 1.573), (0.06, 1.569), (0.125, 1.556)], dz=-0.07, size=MID))
    s.append(L([(-0.06, 1.6), (0.0, 1.607), (0.06, 1.6)], dz=-0.05, size=FINE, joins=False))

    # chest plate: rounded outline, centre ridge, pec plates
    s.append(L([(-0.123, 1.557), (-0.2, 1.535), (-0.248, 1.47), (-0.257, 1.41), (-0.237, 1.32), (-0.19, 1.245),
                (-0.1, 1.222), (0.0, 1.216), (0.1, 1.222), (0.19, 1.245), (0.237, 1.32), (0.257, 1.41),
                (0.248, 1.47), (0.2, 1.535), (0.123, 1.557)], dz=-0.11, size=HEAVY))
    s.append(L([(0.0, 1.571), (0.004, 1.5), (0.002, 1.4), (0.0, 1.22)], dz=-0.12, size=MID))
    s += both([(0.245, 1.43), (0.17, 1.405), (0.09, 1.392), (0.0, 1.398)], dz=-0.12, size=MID)
    s += both([(0.2, 1.505), (0.15, 1.47), (0.12, 1.43)], dz=-0.12, size=FINE, op=0.8, joins=False)
    # chest vents
    for i in range(3):
        y = 1.36 - i * 0.035
        s += both([(0.06, y), (0.1, y - 0.004), (0.14, y - 0.012)], dz=-0.12, size=FINE, op=0.85, joins=False)

    # undersuit sides of the torso down to the waist
    s += both([(0.257, 1.41), (0.235, 1.3), (0.2, 1.2), (0.18, 1.12), (0.195, 1.085)], dz=-0.02, size=HEAVY)

    # abdominal plates
    s.append(L([(-0.165, 1.205), (-0.08, 1.193), (0.0, 1.19), (0.08, 1.193), (0.165, 1.205)], dz=-0.09, size=MID))
    s.append(L([(-0.17, 1.15), (-0.08, 1.138), (0.0, 1.135), (0.08, 1.138), (0.17, 1.15)], dz=-0.09, size=MID))
    s += both([(0.165, 1.205), (0.172, 1.15), (0.18, 1.09)], dz=-0.09, size=MID)
    s.append(L([(0.0, 1.216), (0.0, 1.09)], dz=-0.1, size=MID))

    # belt, buckle, pouches
    s.append(L([(-0.205, 1.088), (-0.1, 1.075), (0.0, 1.072), (0.1, 1.075), (0.205, 1.088)], dz=-0.1, size=MID))
    s.append(L([(-0.212, 1.0), (-0.1, 0.987), (0.0, 0.984), (0.1, 0.987), (0.212, 1.0)], dz=-0.1, size=MID))
    s += both([(0.205, 1.088), (0.212, 1.045), (0.212, 1.0)], dz=-0.1, size=MID)
    s.append(L([(-0.035, 1.07), (-0.038, 1.03), (-0.034, 0.988)], dz=-0.11, size=FINE))
    s.append(L([(0.035, 1.07), (0.038, 1.03), (0.034, 0.988)], dz=-0.11, size=FINE))
    s += both([(0.1, 1.076), (0.098, 1.03), (0.105, 0.99)], dz=-0.12, size=FINE)
    s += both([(0.165, 1.083), (0.168, 1.03), (0.17, 0.995)], dz=-0.12, size=FINE)

    # fauld (hip plate)
    s.append(L([(-0.09, 0.993), (-0.084, 0.94), (-0.065, 0.885), (-0.03, 0.845), (0.0, 0.832), (0.03, 0.845),
                (0.065, 0.885), (0.084, 0.94), (0.09, 0.993)], dz=-0.08, size=MID))

    # legs: bulging outer contours, inner contours, then plates
    s += both([(0.212, 1.0), (0.238, 0.9), (0.24, 0.8), (0.228, 0.7), (0.214, 0.6), (0.22, 0.5), (0.25, 0.4),
               (0.268, 0.28), (0.276, 0.15), (0.282, 0.02), (0.29, -0.12)], size=HEAVY)
    s += both([(0.075, 0.9), (0.085, 0.82), (0.1, 0.72), (0.112, 0.62), (0.118, 0.55), (0.122, 0.45),
               (0.132, 0.33), (0.142, 0.2), (0.148, 0.05), (0.152, -0.12)], size=HEAVY)
    # thigh plate
    s += both([(0.082, 0.965), (0.14, 0.972), (0.2, 0.966), (0.222, 0.88), (0.226, 0.8), (0.214, 0.7),
               (0.19, 0.663), (0.14, 0.657), (0.104, 0.668), (0.088, 0.75), (0.082, 0.85), (0.082, 0.965)],
              dz=-0.06, size=MID)
    s += both([(0.11, 0.9), (0.15, 0.905), (0.195, 0.9)], dz=-0.065, size=FINE, op=0.8, joins=False)
    # knee cap
    s += both([(0.113, 0.618), (0.17, 0.642), (0.232, 0.62), (0.256, 0.565), (0.25, 0.5), (0.222, 0.468),
               (0.17, 0.458), (0.118, 0.47), (0.097, 0.52), (0.1, 0.58), (0.113, 0.618)], dz=-0.09, size=MID)
    s += both([(0.14, 0.605), (0.17, 0.612), (0.21, 0.605)], dz=-0.095, size=FINE, joins=False)
    s += both([(0.14, 0.585), (0.17, 0.592), (0.21, 0.585)], dz=-0.095, size=FINE, joins=False)
    # shin guard with a centre ridge
    s += both([(0.122, 0.452), (0.18, 0.458), (0.238, 0.452), (0.258, 0.36), (0.266, 0.22), (0.268, 0.05),
               (0.27, -0.12)], dz=-0.07, size=MID)
    s += both([(0.122, 0.452), (0.128, 0.33), (0.138, 0.18), (0.145, 0.03), (0.15, -0.12)], dz=-0.07, size=MID)
    s += both([(0.18, 0.458), (0.192, 0.3), (0.2, 0.12), (0.207, -0.12)], dz=-0.075, size=MID)

    # pauldrons: domed shell, rim, lower plate, accent stripe
    s += both([(0.192, 1.552), (0.25, 1.603), (0.33, 1.632), (0.41, 1.6), (0.455, 1.53), (0.462, 1.45),
               (0.44, 1.385), (0.395, 1.352)], dz=-0.03, size=HEAVY)
    s += both([(0.192, 1.552), (0.235, 1.49), (0.3, 1.42), (0.355, 1.375), (0.395, 1.352)], dz=-0.03, size=MID)
    s += both([(0.3, 1.628), (0.36, 1.585), (0.41, 1.53), (0.465, 1.475)], dz=-0.03, size=MID)
    s += both([(0.35, 1.638), (0.395, 1.592), (0.438, 1.545), (0.465, 1.51)], dz=-0.03, size=MID)
    s += both([(0.3, 1.42), (0.345, 1.392), (0.395, 1.352), (0.44, 1.33), (0.455, 1.29), (0.43, 1.255),
               (0.37, 1.252), (0.32, 1.28)], dz=-0.04, size=MID)
    # upper arms coming out from under the pauldrons
    s += both([(0.455, 1.29), (0.445, 1.24), (0.425, 1.19)], dz=-0.02, size=HEAVY)
    s += both([(0.32, 1.28), (0.315, 1.23), (0.322, 1.18)], dz=-0.02, size=MID)
    return s


def _px_per_m():
    a, b = rifle_pt(0.5, 0.0), rifle_pt(0.5, 0.1)
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 / 0.1


def front_erasers():
    """Eraser strokes just inside the rifle and forearms (a bit narrower than them, so the lines
    behind still touch their edges), so the lines they cover disappear."""
    k_ = _px_per_m() * 0.8
    er = []
    # rifle: (u0, u1, v_low, v_high) sections of its outline
    for u0, u1, lo, hi in ((0.03, 0.24, -0.06, 0.045), (0.24, 0.6, -0.052, 0.065), (0.6, 0.79, -0.044, 0.05),
                           (0.79, 1.06, -0.024, 0.016), (0.37, 0.59, 0.07, 0.122), (0.285, 0.335, -0.125, -0.05),
                           (0.47, 0.53, -0.16, -0.05)):
        if hi - lo > u1 - u0:      # taller than long: erase across instead of along
            mid = (u0 + u1) / 2
            er.append({"points": [rifle_pt(mid, lo + 0.006), rifle_pt(mid, hi - 0.006)],
                       "size": (u1 - u0) * k_, "smooth": False})
        else:
            vm = (lo + hi) / 2
            er.append({"points": [rifle_pt(u0 + 0.01, vm), rifle_pt(u1 - 0.01, vm)],
                       "size": (hi - lo) * k_, "smooth": False})
    # forearms (centre lines between their two contours) and fists
    er.append({"points": [body(-0.425, 1.19, -0.09), body(-0.35, 1.19, -0.12), body(-0.26, 1.155, -0.15),
                          body(-0.16, 1.11, -0.19)], "size": 0.05 * k_ / 0.8 * 0.75})
    er.append({"points": [body(0.42, 1.205, -0.09), body(0.36, 1.24, -0.13), body(0.3, 1.295, -0.17),
                          body(0.24, 1.345, -0.2)], "size": 0.06 * k_ / 0.8 * 0.75})
    er.append({"points": [body(-0.11, 1.1, -0.2), body(-0.1, 1.11, -0.2)], "size": 0.07 * k_ / 0.8})
    er.append({"points": [body(0.2, 1.37, -0.23), body(0.22, 1.39, -0.23)], "size": 0.07 * k_ / 0.8})
    return er


def front_lines():
    s = []
    # rifle: drawn like a machine - one closed outline with crisp corners, straight panel lines
    def hard(pts, size):
        return dict(R(pts, size), smooth=False, overshoot=False)
    s.append(dict(hard([(0.0, -0.044), (0.07, -0.074), (0.24, -0.066), (0.276, -0.13), (0.34, -0.13),
                        (0.355, -0.062), (0.45, -0.055), (0.49, -0.168), (0.56, -0.162), (0.54, -0.052),
                        (0.74, -0.05), (0.79, -0.031), (1.08, -0.027), (1.086, -0.004), (1.08, 0.018),
                        (0.8, 0.022), (0.72, 0.062), (0.6, 0.068), (0.6, 0.12), (0.37, 0.126), (0.36, 0.075),
                        (0.33, 0.1), (0.16, 0.07), (0.12, 0.056), (0.02, 0.046), (0.0, -0.044)], HEAVY),
                  closed=True))
    s.append(hard([(0.6, -0.05), (0.6, 0.068)], MID))            # receiver | shroud
    s.append(hard([(0.79, -0.031), (0.8, 0.022)], MID))          # shroud | barrel
    s.append(hard([(0.36, 0.075), (0.6, 0.068)], MID))           # scope base
    s.append(hard([(0.45, -0.055), (0.54, -0.052)], MID))        # magazine well
    s.append(hard([(0.25, -0.066), (0.355, -0.062)], MID))       # grip top
    s.append(hard([(0.14, -0.071), (0.14, 0.063)], MID))         # stock joint
    s += [dict(hard([(u, -0.034), (u + 0.01, 0.04)], FINE), taper=0.3, min_width=0) for u in (0.64, 0.68, 0.72, 0.76)]
    s.append(dict(hard([(0.39, 0.1), (0.57, 0.098)], FINE), taper=0.3, min_width=0))
    s.append(dict(hard([(0.42, -0.014), (0.7, -0.014)], FINE), taper=0.2, min_width=0))
    s.append(dict(hard([(0.42, 0.014), (0.7, 0.014)], FINE), taper=0.2, min_width=0))

    # screen-left forearm (soldier's right) into the fist on the grip
    s.append(L([(-0.43, 1.205, None, -0.09), (-0.37, 1.245, None, -0.12), (-0.28, 1.215, None, -0.15),
                (-0.19, 1.172, None, -0.18), (-0.15, 1.158, None, -0.19)], size=HEAVY))
    s.append(L([(-0.425, 1.17, None, -0.09), (-0.35, 1.14, None, -0.12), (-0.25, 1.1, None, -0.15),
                (-0.18, 1.072, None, -0.18), (-0.15, 1.06, None, -0.19)], size=HEAVY))
    s.append(L([(-0.35, 1.235), (-0.355, 1.19), (-0.348, 1.14)], dz=-0.13, size=MID))
    s.append(L([(-0.235, 1.195), (-0.24, 1.15), (-0.235, 1.095)], dz=-0.16, size=MID))
    s.append(L([(-0.3, 1.215), (-0.305, 1.17), (-0.3, 1.125)], dz=-0.145, size=FINE, joins=False))
    # fist: knuckles wrapping the grip, thumb over the top
    s.append(L([(-0.15, 1.158), (-0.118, 1.168), (-0.085, 1.155), (-0.068, 1.12), (-0.072, 1.08),
                (-0.09, 1.048), (-0.125, 1.035), (-0.15, 1.06)], dz=-0.2, size=HEAVY))
    for y in (1.13, 1.105, 1.08):
        s.append(L([(-0.125, y + 0.01), (-0.1, y + 0.004), (-0.074, y - 0.006)], dz=-0.21, size=FINE, joins=False))
    s.append(L([(-0.15, 1.158), (-0.12, 1.185), (-0.09, 1.19), (-0.07, 1.175)], dz=-0.21, size=MID))

    # screen-right forearm (soldier's left) rising to the hand under the barrel
    s.append(L([(0.44, 1.24, None, -0.09), (0.39, 1.28, None, -0.13), (0.33, 1.33, None, -0.17),
                (0.275, 1.385, None, -0.2)], size=HEAVY))
    s.append(L([(0.4, 1.17, None, -0.09), (0.34, 1.2, None, -0.13), (0.27, 1.26, None, -0.17),
                (0.2, 1.31, None, -0.2)], size=HEAVY))
    s.append(L([(0.405, 1.265), (0.385, 1.235), (0.372, 1.19)], dz=-0.12, size=MID))
    s.append(L([(0.33, 1.32), (0.31, 1.285), (0.29, 1.24)], dz=-0.17, size=MID))
    # hand gripping the foregrip
    s.append(L([(0.2, 1.31), (0.165, 1.33), (0.15, 1.37), (0.17, 1.41), (0.21, 1.435), (0.255, 1.425),
                (0.275, 1.385)], dz=-0.23, size=HEAVY))
    for t in (0.0, 0.025, 0.05):
        s.append(L([(0.17 + t, 1.36 + t * 0.6), (0.19 + t, 1.375 + t * 0.6), (0.205 + t, 1.395 + t * 0.6)],
                   dz=-0.24, size=FINE, joins=False))
    return s


def seeds():
    """Where each color goes (one point inside each enclosed area)."""
    sd = []

    def add(x, y, dz, c, mirror=True):
        sd.append(body(x, y, dz) + [c])
        if mirror and x:
            sd.append(body(-x, y, dz) + [c])

    add(0.06, 1.84, 0, ARMOR)          # helmet dome
    add(0.06, 1.758, 0, ARMOR2)        # brow band
    add(0.0, 1.712, -0.04, VISOR, False)
    add(0.06, 1.655, -0.04, ARMOR_DK)  # jaw / cheeks
    add(0.0, 1.59, -0.05, ARMOR_DK, False)   # neck seal
    add(0.12, 1.47, -0.12, ARMOR)      # upper chest
    add(0.12, 1.3, -0.12, ARMOR2)      # lower chest
    add(0.08, 1.17, -0.09, ARMOR_DK)   # abs row 1
    add(0.08, 1.115, -0.09, ARMOR_DK2) # abs row 2
    add(0.065, 1.03, -0.1, BELT)
    add(0.135, 1.03, -0.12, POUCH)
    add(0.0, 1.03, -0.11, POUCH, False)
    add(0.0, 0.92, -0.08, ARMOR2, False)
    add(0.15, 0.82, -0.06, ARMOR)      # thigh plates
    add(0.17, 0.53, -0.09, ARMOR2)     # knees
    add(0.155, 0.2, -0.07, ARMOR)      # shins
    add(0.235, 0.2, -0.07, ARMOR2)
    add(0.3, 1.53, -0.03, ARMOR)       # pauldron shell
    add(0.392, 1.565, -0.035, ACCENT)  # stripe
    add(0.38, 1.3, -0.04, ARMOR2)      # lower pauldron plate
    add(0.19, 1.66, 0.16, PACK)        # backpack beside the helmet
    # rifle
    for u, v, c in ((0.07, 0.0, GUN3), (0.31, -0.1, GUN3), (0.5, -0.11, GUN2), (0.45, -0.03, GUN),
                    (0.48, 0.1, GUN2), (0.7, 0.0, GUN2), (0.95, -0.004, GUN)):
        sd.append(rifle_pt(u, v) + [c])
    # gauntlets and gloves
    add(-0.29, 1.165, -0.15, ARMOR_DK, False)
    add(0.35, 1.25, -0.15, ARMOR_DK, False)
    add(-0.11, 1.1, -0.2, HAND, False)
    add(0.22, 1.38, -0.23, HAND, False)
    return sd


def stage_drawn():
    top = k.list_layers()["layers"][0]["name"]
    k.select_layer(layer=top)
    k.add_layer(name="Soldier", type="group")
    k.add_layer(name="Lines", parent="Soldier")
    # 1) everything behind the rifle and forearms, drawn as natural ink lines
    k.draw_strokes(layer="Lines", engine="ink", color=INK, strokes=back_lines(), natural=0.25, seed=3)
    # 2) erase what the rifle and arms cover, 3) draw them in front
    k.draw_strokes(layer="Lines", engine="ink", color="#000000", mode="erase", strokes=front_erasers())
    k.draw_strokes(layer="Lines", engine="ink", color=INK, strokes=front_lines(), natural=0.22, seed=9)

    # color the drawing: flats between the lines, then lighting on the flats
    bg = [body(0.0, 0.55, 0.0), body(0.0, 0.2, 0.0), body(0.0, 0.7, 0.0)]
    r = k.fill_line_art(line_layer="Lines", seeds=seeds(), background_seeds=bg, gap=4, default_color=SUIT,
                        new_layer="Flats")
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

    # drawn rim light: thin bright lines just inside the silhouette on the corridor side
    rim = []
    for st in back_lines() + front_lines():
        if st["size"] >= HEAVY:
            rim.append(dict(st, points=[[p[0] - 2.5, p[1] + 2.5] + p[2:] for p in st["points"]], size=1.6,
                            opacity=0.75))
    k.draw_strokes(new_layer="Rim lines", engine="ink", color="#a8f6ff", strokes=rim, natural=0.3, seed=21,
                   clip=False)
    k.set_layer(layer="Rim lines", blend_mode="add", opacity=0.8)
    k.set_layer(layer="Lines", position="top")

    # glow: visor and energy cell painted with soft strokes, plus bloom
    vis = [body(x, y, -0.05) for x, y in ((-0.095, 1.712), (-0.04, 1.718), (0.04, 1.718), (0.095, 1.712))]
    cell = [rifle_pt(0.43, 0.0), rifle_pt(0.69, 0.0)]
    k.draw_strokes(new_layer="Glow", engine="ink", strokes=[
        {"points": vis, "size": 16, "color": "#ffd27a", "opacity": 0.55, "taper": 0.3},
        {"points": [body(-0.07, 1.724, -0.05), body(0.03, 1.714, -0.05)], "size": 3, "color": "#fff8e0",
         "taper": 0.4},
        {"points": cell, "size": 7, "color": "#9ff8ff", "taper": 0.1}])
    k.draw_strokes(new_layer="Glow bloom", engine="ink", blur=16, strokes=[
        {"points": vis, "size": 40, "color": "#ff9a2e", "opacity": 0.8},
        {"points": cell, "size": 26, "color": "#2fd8ff"}])
    k.set_layer(layer="Glow bloom", blend_mode="add")


def main():
    os.makedirs(OUT, exist_ok=True)
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
