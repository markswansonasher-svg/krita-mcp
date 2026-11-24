"""
Posable figure engine for the Krita MCP server.

A 3D skeleton with human proportions, posed with a handful of numbers (root, facing, lean, twist,
side bend, head turn, and where the hands and feet are - elbows and knees are solved by two-bone
IK), projected through a perspective camera, and turned into line-art strokes for draw_strokes:
anatomical limb contours (muscle profiles, not uniform tubes), torso, head, hands, feet - drawn
back to front with "outline" + "fill" + "occlude" so the result colors cleanly with fill_line_art.

Armor, clothing and props attach to bones in bone-local coordinates (u along the bone 0..1, v across
it in radius units), so they follow any pose without re-measuring anything.
"""
import math

# ----------------------------------------------------------------------------- vector helpers


def v_add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def v_sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def v_mul(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def v_len(a):
    return math.sqrt(v_dot(a, a))


def v_norm(a):
    n = v_len(a) or 1.0
    return [a[0] / n, a[1] / n, a[2] / n]


def v_lerp(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]


def rot_y(p, deg):          # yaw: turn around the vertical axis
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c]


def rot_x(p, deg):          # pitch: lean forward (toward -z) for positive deg
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [p[0], p[1] * c + p[2] * s, -p[1] * s + p[2] * c]


def rot_z(p, deg):          # roll / side bend
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]]


# ----------------------------------------------------------------------------- camera

class Camera:
    """Pinhole camera. eye [x, y, z] in metres (y up, z forward into the scene), pitch (deg, up is
    positive), yaw (deg), focal length in px, image center [cx, cy]."""

    def __init__(self, eye=(0, 1.6, -4), pitch=0.0, yaw=0.0, focal=1500.0, center=(600, 800)):
        self.eye = list(eye)
        self.pitch = float(pitch)
        self.yaw = float(yaw)
        self.f = float(focal)
        self.cx, self.cy = center

    def view(self, p):
        q = v_sub(p, self.eye)
        q = rot_y(q, -self.yaw)
        a = math.radians(self.pitch)
        y = q[1] * math.cos(a) - q[2] * math.sin(a)
        z = q[1] * math.sin(a) + q[2] * math.cos(a)
        return [q[0], y, max(z, 0.05)]

    def project(self, p):
        x, y, z = self.view(p)
        return [round(self.cx + self.f * x / z, 2), round(self.cy - self.f * y / z, 2)]

    def depth(self, p):
        return self.view(p)[2]

    def scale(self, p):
        """Pixels per metre at point p."""
        return self.f / self.view(p)[2]


# ----------------------------------------------------------------------------- body

PROPORTIONS = {     # fractions of the figure's height (heroic ~8 heads)
    "hip": 0.53, "knee": 0.285, "ankle": 0.045, "waist": 0.6, "chest": 0.72, "neck": 0.815,
    "head": 0.905, "head_h": 0.125, "shoulder_w": 0.115, "hip_w": 0.053,
    "upper_arm": 0.17, "forearm": 0.145, "foot": 0.13,
}

# radius profiles along each bone: (t, radius in metres for a 1.85 m figure) - muscle shapes
PROFILES = {
    "thigh":    [(0.0, 0.088), (0.25, 0.084), (0.6, 0.07), (0.9, 0.058), (1.0, 0.056)],
    "shin":     [(0.0, 0.056), (0.22, 0.064), (0.45, 0.058), (0.75, 0.044), (1.0, 0.036)],
    "upper_arm": [(0.0, 0.062), (0.2, 0.06), (0.45, 0.054), (0.8, 0.045), (1.0, 0.042)],
    "forearm":  [(0.0, 0.044), (0.2, 0.049), (0.45, 0.044), (0.8, 0.034), (1.0, 0.029)],
    "neck":     [(0.0, 0.056), (1.0, 0.05)],
    "foot":     [(0.0, 0.04), (0.5, 0.045), (1.0, 0.034)],
}


def _profile(name, t, scale):
    prof = PROFILES[name]
    for (t0, r0), (t1, r1) in zip(prof, prof[1:]):
        if t <= t1:
            f = (t - t0) / max(t1 - t0, 1e-6)
            f = f * f * (3 - 2 * f)
            return (r0 + (r1 - r0) * f) * scale
    return prof[-1][1] * scale


def two_bone_ik(a, target, l1, l2, pole):
    """Shoulder/hip a, hand/foot target, bone lengths, pole direction -> (elbow/knee, end)."""
    d_vec = v_sub(target, a)
    d = min(v_len(d_vec), (l1 + l2) * 0.999)
    d = max(d, abs(l1 - l2) + 1e-3)
    dirn = v_norm(d_vec)
    end = v_add(a, v_mul(dirn, d))
    x = (l1 * l1 + d * d - l2 * l2) / (2 * d)
    h = math.sqrt(max(l1 * l1 - x * x, 0.0))
    p = v_sub(pole, v_mul(dirn, v_dot(pole, dirn)))
    if v_len(p) < 1e-6:
        p = [0, 0, -1] if abs(dirn[2]) < 0.9 else [1, 0, 0]
        p = v_sub(p, v_mul(dirn, v_dot(p, dirn)))
    p = v_norm(p)
    mid = v_add(v_add(a, v_mul(dirn, x)), v_mul(p, h))
    return mid, end


def build_skeleton(pose):
    """3D joint positions (metres) for a pose dict.

    pose keys (all optional):
      height (1.85), root [x, z] floor position, facing (deg; 0 = facing the camera, 90 = facing
      screen-left... i.e. turned to its right), crouch (m the hips drop), lean (deg forward),
      side_bend (deg, + = bends toward its left), twist (deg, chest turned relative to hips),
      head {yaw, pitch (+ = looks down), roll},
      feet {l: [x, y, z], r: [...]}, hands {l: [...], r: [...]} - in the figure's frame relative to
      root (x = its left, y = up, z = its forward), metres. Defaults: relaxed stance, arms down.
      elbows {l: [x, y, z] pole direction, r: ...}, knees {...} - optional pole directions.
    """
    H = float(pose.get("height", 1.85))
    P = PROPORTIONS
    sc = H / 1.85
    rx, rz = pose.get("root", [0.0, 0.0])
    facing = float(pose.get("facing", 0.0))
    crouch = float(pose.get("crouch", 0.0))
    lean = float(pose.get("lean", 0.0))
    bend = float(pose.get("side_bend", 0.0))
    twist = float(pose.get("twist", 0.0))
    head = pose.get("head", {})

    # local frame: x = figure's left, y = up, z = figure's forward. facing the camera, its forward is -z
    def to_world(p):
        q = [p[0], p[1], -p[2]]               # forward -> toward camera
        q = rot_y(q, facing)
        return [q[0] + rx, q[1], q[2] + rz]

    pelvis = [0.0, H * P["hip"] - crouch, 0.0]
    hip_w = H * P["hip_w"]

    def upper(p):                              # upper-body pose around the pelvis
        q = v_sub(p, pelvis)
        q = rot_y(q, twist)
        q = rot_z(q, -bend)
        q = rot_x(q, lean)
        return v_add(q, pelvis)

    rel = {
        "waist": [0, H * (P["waist"] - P["hip"]), 0.0],
        "chest": [0, H * (P["chest"] - P["hip"]), 0.01],
        "neck": [0, H * (P["neck"] - P["hip"]), 0.0],
        "shoulder_l": [H * P["shoulder_w"], H * (P["neck"] - P["hip"]) - 0.035 * sc, 0.0],
        "shoulder_r": [-H * P["shoulder_w"], H * (P["neck"] - P["hip"]) - 0.035 * sc, 0.0],
    }
    J = {"pelvis": pelvis, "hip_l": [hip_w, pelvis[1] - 0.03 * sc, 0.0], "hip_r": [-hip_w, pelvis[1] - 0.03 * sc, 0.0]}
    for k_, v in rel.items():
        J[k_] = upper(v_add(pelvis, v))
    # head: on the neck, turned by the torso then by its own yaw/pitch/roll
    head_off = [0, H * (P["head"] - P["neck"]), 0.012 * sc]
    ho = rot_x(rot_z(rot_y(head_off, float(head.get("yaw", 0))), -float(head.get("roll", 0))),
               float(head.get("pitch", 0)))
    ho = rot_x(rot_z(rot_y(ho, twist), -bend), lean)
    J["head"] = v_add(J["neck"], ho)

    # legs (IK from hips to feet), knees point forward
    feet = pose.get("feet", {})
    knees = pose.get("knees", {})
    for side, sx in (("l", 1), ("r", -1)):
        foot = feet.get(side, [sx * 0.14 * sc, H * P["ankle"], 0.0])
        pole = knees.get(side, [sx * 0.1, 0.0, 1.0])
        knee, ankle = two_bone_ik(J["hip_" + side], list(foot), H * (P["hip"] - P["knee"]),
                                  H * (P["knee"] - P["ankle"]), pole)
        J["knee_" + side], J["ankle_" + side] = knee, ankle
        J["toe_" + side] = v_add(ankle, [sx * 0.02 * sc, -H * P["ankle"] * 0.6, H * P["foot"]])
    # arms (IK from shoulders to hands), elbows point back and out
    hands = pose.get("hands", {})
    elbows = pose.get("elbows", {})
    for side, sx in (("l", 1), ("r", -1)):
        sh = J["shoulder_" + side]
        default_hand = [sh[0] + sx * 0.06 * sc, sh[1] - H * (P["upper_arm"] + P["forearm"]) * 0.97, 0.03 * sc]
        hand = hands.get(side, default_hand)
        pole = elbows.get(side, [sx * 0.6, -0.2, -1.0])
        elbow, wrist = two_bone_ik(sh, list(hand), H * P["upper_arm"], H * P["forearm"], pole)
        J["elbow_" + side], J["wrist_" + side] = elbow, wrist
        fdir = v_norm(v_sub(wrist, elbow))
        J["hand_" + side] = v_add(wrist, v_mul(fdir, 0.055 * sc))
    J = {k_: to_world(v) for k_, v in J.items()}
    J["_scale"] = sc
    J["_facing"] = facing + twist
    return J


BONES = [  # name, from, to, profile
    ("thigh_l", "hip_l", "knee_l", "thigh"), ("thigh_r", "hip_r", "knee_r", "thigh"),
    ("shin_l", "knee_l", "ankle_l", "shin"), ("shin_r", "knee_r", "ankle_r", "shin"),
    ("foot_l", "ankle_l", "toe_l", "foot"), ("foot_r", "ankle_r", "toe_r", "foot"),
    ("upper_arm_l", "shoulder_l", "elbow_l", "upper_arm"), ("upper_arm_r", "shoulder_r", "elbow_r", "upper_arm"),
    ("forearm_l", "elbow_l", "wrist_l", "forearm"), ("forearm_r", "elbow_r", "wrist_r", "forearm"),
    ("neck", "neck", "head", "neck"),
]


def bone_frames(J, cam):
    """Screen-space frame of every bone: start/end points, radius (px) along it, direction, normal."""
    sc = J["_scale"]
    frames = {}
    for name, a, b, prof in BONES:
        pa, pb = J[a], J[b]
        sa, sb = cam.project(pa), cam.project(pb)
        frames[name] = {"a3": pa, "b3": pb, "a": sa, "b": sb, "profile": prof,
                        "ppm_a": cam.scale(pa), "ppm_b": cam.scale(pb), "scale": sc}
    # torso as a bone from pelvis to neck, its width depends on which way it faces the camera
    frames["torso"] = {"a3": J["pelvis"], "b3": J["neck"], "a": cam.project(J["pelvis"]),
                       "b": cam.project(J["neck"]), "profile": None, "ppm_a": cam.scale(J["pelvis"]),
                       "ppm_b": cam.scale(J["neck"]), "scale": sc}
    frames["head"] = {"a3": J["neck"], "b3": J["head"], "a": cam.project(J["neck"]), "b": cam.project(J["head"]),
                      "profile": None, "ppm_a": cam.scale(J["neck"]), "ppm_b": cam.scale(J["head"]), "scale": sc}
    frames["torso"]["kind"] = "torso"
    frames["head"]["kind"] = "head"
    for f in frames.values():
        dx, dy = f["b"][0] - f["a"][0], f["b"][1] - f["a"][1]
        ln = math.hypot(dx, dy) or 1.0
        f["dir"] = [dx / ln, dy / ln]
        f["normal"] = [-dy / ln, dx / ln]
        f["length_px"] = ln
    return frames


def _torso_halfwidth(t, J):
    """Half-width (m) of the torso along pelvis(0) -> neck(1), seen from the camera direction."""
    sc = J["_scale"]
    prof_w = [(0.0, 0.165), (0.22, 0.142), (0.45, 0.16), (0.75, 0.2), (0.92, 0.18), (1.0, 0.07)]
    prof_d = [(0.0, 0.11), (0.22, 0.1), (0.45, 0.11), (0.75, 0.13), (0.92, 0.1), (1.0, 0.055)]

    def interp(prof):
        for (t0, r0), (t1, r1) in zip(prof, prof[1:]):
            if t <= t1:
                f = (t - t0) / max(t1 - t0, 1e-6)
                f = f * f * (3 - 2 * f)
                return r0 + (r1 - r0) * f
        return prof[-1][1]
    yaw = math.radians(J["_facing"])
    w, d = interp(prof_w), interp(prof_d)
    return math.hypot(w * math.cos(yaw), d * math.sin(yaw)) * sc


def radius_px(frame, t):
    p3 = v_lerp(frame["a3"], frame["b3"], t)
    ppm = frame["ppm_a"] + (frame["ppm_b"] - frame["ppm_a"]) * t
    return _profile(frame["profile"], t, frame["scale"]) * ppm, p3


def limb_spine(frame, samples=6, swell=1.0):
    pts = []
    for i in range(samples):
        t = i / (samples - 1)
        r, _ = radius_px(frame, t)
        x = frame["a"][0] + (frame["b"][0] - frame["a"][0]) * t
        y = frame["a"][1] + (frame["b"][1] - frame["a"][1]) * t
        pts.append([round(x, 2), round(y, 2), round(r * swell, 2)])
    return pts


def local_to_screen(frame, u, v, J=None, thickness=1.0):
    """Bone-local (u along 0..1, v across in radius units) -> screen point."""
    ppm = frame["ppm_a"] + (frame["ppm_b"] - frame["ppm_a"]) * min(max(u, 0.0), 1.0)
    if frame.get("profile"):
        r, _ = radius_px(frame, min(max(u, 0.0), 1.0))
    elif frame.get("kind") == "torso" and J is not None:
        r = _torso_halfwidth(min(max(u, 0.0), 1.0), J) * ppm
    else:                                     # head: a fixed radius
        r = 0.085 * frame["scale"] * ppm
    x = frame["a"][0] + (frame["b"][0] - frame["a"][0]) * u + frame["normal"][0] * v * r * thickness
    y = frame["a"][1] + (frame["b"][1] - frame["a"][1]) * u + frame["normal"][1] * v * r * thickness
    return [round(x, 2), round(y, 2)]


# ----------------------------------------------------------------------------- drawing

def figure_strokes(pose, cam, colors=None, sizes=None, head_style="helmet", attachments=(),
                   hands_style="fist"):
    """Line-art strokes for a posed figure (back to front) + joint/bone info.
    attachments: [{"bone": name, "points": [[u, v], ...], "fill": color, "smooth": bool,
                   "corner_radius": px, "thickness": 1.1, "size": px, "lines": [[[u, v], ...], ...]}]
    """
    colors = dict({"skin": "#2f353f", "head": "#6f7c8e", "hand": "#3c424c", "torso": "#2f353f"}, **(colors or {}))
    J = build_skeleton(pose)
    F = bone_frames(J, cam)
    if sizes is None:       # line weights scale with the figure's size on screen
        ppm = cam.scale(J["pelvis"])
        heavy = min(9.0, max(1.6, 0.0105 * ppm))
        sizes = (heavy, heavy * 0.55, heavy * 0.32)
    HEAVY, MID, FINE = sizes
    parts = []      # (depth, [strokes])

    def depth_of(*names):
        return sum(cam.depth(J[n]) for n in names) / len(names)

    # torso: a contour along the spine with a width profile
    tor = F["torso"]
    spine = []
    for i in range(7):
        t = i / 6
        p = local_to_screen(tor, t, 0.0)
        ppm = tor["ppm_a"] + (tor["ppm_b"] - tor["ppm_a"]) * t
        spine.append(p + [round(_torso_halfwidth(t, J) * ppm, 2)])
    part_depth = {}
    part_depth["torso"] = depth_of("pelvis", "chest", "neck") + 0.02
    parts.append((part_depth["torso"],
                  [{"outline": {"type": "tube", "spine": spine, "caps": True}, "fill": colors["torso"],
                    "size": HEAVY, "occlude": True, "_part": "torso"}]))
    # limbs: each whole arm and leg is ONE continuous contour through the elbow/knee (no mannequin
    # seams); feet and neck are separate
    for side in ("l", "r"):
        for upper, lower, joints, key in (("thigh_" + side, "shin_" + side, ("hip_", "knee_", "ankle_"), "leg"),
                                          ("upper_arm_" + side, "forearm_" + side, ("shoulder_", "elbow_", "wrist_"),
                                           "arm")):
            spine = limb_spine(F[upper], 6)[:-1] + limb_spine(F[lower], 7)
            fill = colors.get(key + "_" + side, colors.get(upper, colors["skin"]))
            st = {"outline": {"type": "tube", "spine": spine}, "fill": fill, "size": HEAVY, "occlude": True,
                  "_part": key + "_" + side}
            bias = -0.06 if key == "arm" else 0.0          # arms usually overlap the torso
            part_depth[key + "_" + side] = depth_of(*(j + side for j in joints)) + bias
            parts.append((part_depth[key + "_" + side], [st]))
    for name, a, b, prof in BONES:
        if prof not in ("foot", "neck"):
            continue
        st = {"outline": {"type": "tube", "spine": limb_spine(F[name], 4)}, "fill": colors.get(name, colors["skin"]),
              "size": MID, "occlude": True, "_part": name}
        part_depth[name] = depth_of(a, b)
        if prof == "neck":      # the neck always sits behind the head, whatever the head's tilt
            part_depth[name] = max(part_depth[name], cam.depth(J["head"]) + 0.03)
        parts.append((part_depth[name], [st]))
    # head
    hf = F["head"]
    hc = cam.project(J["head"])
    hr = 0.11 * J["_scale"] * cam.scale(J["head"])
    ang = math.degrees(math.atan2(hf["dir"][1], hf["dir"][0])) + 90
    head = [{"outline": {"type": "ellipse", "x": hc[0] - hr * 0.78, "y": hc[1] - hr, "w": hr * 1.56, "h": hr * 2.0,
                         "rotation": ang}, "fill": colors["head"], "size": HEAVY, "occlude": True, "_part": "head"}]
    part_depth["head"] = cam.depth(J["head"]) - 0.01
    parts.append((part_depth["head"], head))
    # hands: a rounded fist / mitten at the end of each forearm
    for side in ("l", "r"):
        fa = F["forearm_" + side]
        c = cam.project(J["hand_" + side])
        r = 0.045 * J["_scale"] * cam.scale(J["hand_" + side])
        ang = math.degrees(math.atan2(fa["dir"][1], fa["dir"][0]))
        parts.append((cam.depth(J["hand_" + side]) - 0.08,
                      [{"outline": {"type": "blob", "cx": c[0], "cy": c[1], "rx": r * 1.15, "ry": r * 0.95,
                                    "rotation": ang, "wobble": 0.06, "lumps": 3, "seed": 7},
                        "fill": colors["hand"], "size": MID, "occlude": True, "_part": "hand_" + side}]))
    # attachments (armor, clothing): drawn right after their bone, a hair in front of it
    for at in attachments:
        bone = at["bone"]
        fr = F[bone]
        th = float(at.get("thickness", 1.12))
        pts = [local_to_screen(fr, u, v, J, th) for u, v in at["points"]]
        strokes = []
        if len(pts) >= 3:
            shape = ({"type": "path", "points": pts, "smooth": True} if at.get("smooth", True) else
                     {"type": "polygon", "points": pts, "corner_radius": at.get("corner_radius", 6)})
            strokes.append({"outline": shape, "fill": at.get("fill", "#6f7c8e"), "size": at.get("size", MID),
                            "occlude": True, "_part": bone + ":armor"})
        for line in at.get("lines", []):
            strokes.append({"points": [local_to_screen(fr, u, v, J, th) for u, v in line],
                            "size": at.get("line_size", FINE), "joins": bool(at.get("joins", True))})
        # an attachment is drawn right after the body part it sits on (never hidden by it)
        side = bone[-1] if bone[-2:] in ("_l", "_r") else ""
        parent = ("leg_" + side if bone.startswith(("thigh", "shin")) else
                  "arm_" + side if bone.startswith(("upper_arm", "forearm")) else bone)
        d = part_depth.get(parent, depth_of("pelvis", "neck"))
        if at.get("behind"):                 # backpacks, capes: behind the body part
            d += 0.12
        parts.append((d - 0.0005 - float(at.get("layer", 0)) * 0.0002, strokes))
    parts.sort(key=lambda p: -p[0])           # far first
    for d, ss in parts:
        for st in ss:
            st["_z"] = round(d, 4)                # camera distance of the part (for depth effects)
    strokes = [s for _, ss in parts for s in ss]
    info = {"joints": {k_: cam.project(v) for k_, v in J.items() if not k_.startswith("_")},
            "joints_3d": {k_: [round(c, 4) for c in v] for k_, v in J.items() if not k_.startswith("_")},
            "bones": {k_: {"a": f["a"], "b": f["b"], "dir": [round(c, 4) for c in f["dir"]],
                           "normal": [round(c, 4) for c in f["normal"]], "length_px": round(f["length_px"], 1)}
                      for k_, f in F.items()}}
    for s in strokes:
        s.pop("_part", None)
    return strokes, info, J, F


def figure_spheres(pose):
    """The posed body as spheres [(center3d, radius)] - for 3D shadows and occlusion."""
    J = build_skeleton(pose)
    sc = J["_scale"]
    out = []
    for name, a, b, prof in BONES:
        for i in range(6):
            t = i / 5
            out.append((v_lerp(J[a], J[b], t), _profile(prof, t, sc)))
    for i in range(6):
        t = i / 5
        out.append((v_lerp(J["pelvis"], J["neck"], t), 0.15 * sc))
    out.append((J["head"], 0.11 * sc))
    for side in ("l", "r"):
        out.append((J["hand_" + side], 0.05 * sc))
    return out


def skeleton_sketch(pose, cam, size=3.0):
    """A quick gesture sketch: stick skeleton + joint dots + head circle, to check a pose."""
    J = build_skeleton(pose)
    P = lambda n: cam.project(J[n])          # noqa: E731
    chains = [["ankle_l", "knee_l", "hip_l", "pelvis", "hip_r", "knee_r", "ankle_r"],
              ["pelvis", "waist", "chest", "neck", "head"],
              ["wrist_l", "elbow_l", "shoulder_l", "neck", "shoulder_r", "elbow_r", "wrist_r"],
              ["ankle_l", "toe_l"], ["ankle_r", "toe_r"]]
    strokes = [{"points": [P(n) for n in ch], "size": size, "smooth": False} for ch in chains]
    hr = 0.11 * J["_scale"] * cam.scale(J["head"])
    hc = P("head")
    strokes.append({"outline": {"type": "circle", "cx": hc[0], "cy": hc[1], "r": hr}, "size": size})
    for n in J:
        if n.startswith("_"):
            continue
        p = P(n)
        strokes.append({"points": [p, [p[0] + 0.6, p[1]]], "size": size * 2.4})
    return strokes
