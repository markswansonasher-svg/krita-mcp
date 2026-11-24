"""
Realism engine for the Krita MCP server (runs in the MCP server process, with numpy/scipy/Pillow).

- render_form: turns flat shapes into lit 3D forms (height field from the silhouette -> normals ->
  key/fill/ambient light, specular, rim, ambient occlusion, environment reflection, subsurface).
- painterly: repaints an image with brush strokes that follow its forms (multi-pass, coarse to fine,
  with bristle texture), so it reads as painted instead of vector.
- texture: procedural material detail (grain, clouds, grime, scratches, cells, fabric, stone).
- organic shapes (tube, blob) and natural hand-drawn strokes.
"""
import base64
import io
import math
import random

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, sparse
from scipy.sparse.linalg import spsolve


# ----------------------------------------------------------------------------- image I/O

def decode_png(b64):
    """PNG base64 -> float32 array H x W x 4 in 0..1 (straight alpha)."""
    im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    return np.asarray(im, dtype=np.float32) / 255.0


def encode_png(arr):
    a = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, "PNG", compress_level=1)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def rgb(c):
    if isinstance(c, (list, tuple)):
        return np.array(c[:3], dtype=np.float32) / 255.0
    s = str(c).lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


def lum(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def gblur(a, sigma):
    if sigma <= 0:
        return a
    if a.ndim == 3:
        return np.stack([ndimage.gaussian_filter(a[..., i], sigma) for i in range(a.shape[2])], axis=-1)
    return ndimage.gaussian_filter(a, sigma)


# ----------------------------------------------------------------------------- noise

def value_noise(h, w, cell, rng):
    gh, gw = max(2, int(math.ceil(h / cell)) + 2), max(2, int(math.ceil(w / cell)) + 2)
    grid = rng.random((gh, gw)).astype(np.float32)
    im = Image.fromarray(grid, "F").resize((int(gw * cell), int(gh * cell)), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32)[:h, :w]


def fbm(h, w, scale=64.0, octaves=5, persistence=0.5, seed=1):
    rng = np.random.default_rng(seed)
    total = np.zeros((h, w), np.float32)
    amp, norm, cell = 1.0, 0.0, float(scale)
    for _ in range(octaves):
        total += amp * value_noise(h, w, max(1.0, cell), rng)
        norm += amp
        amp *= persistence
        cell /= 2.0
    total /= norm
    lo, hi = np.percentile(total, 1), np.percentile(total, 99)
    return np.clip((total - lo) / max(1e-6, hi - lo), 0, 1)


def noise1d(n, freq, seed):
    """Smooth 1-D noise in [-1, 1], n samples, about `freq` bumps across."""
    rnd = random.Random(seed)
    k = max(2, int(freq) + 2)
    vals = [rnd.uniform(-1, 1) for _ in range(k + 2)]
    out = []
    for i in range(n):
        t = i / max(1, n - 1) * k
        j = int(t)
        f = t - j
        f = f * f * (3 - 2 * f)
        out.append(vals[j] * (1 - f) + vals[j + 1] * f)
    return out


# ----------------------------------------------------------------------------- form shading

MATERIALS = {
    #            diffuse spec  shin  metal  wrap  sss   bump  sheen
    "matte":     (1.0,    0.05, 8,    0.0,   0.1,  0.0,  0.0,  0.0),
    "plastic":   (1.0,    0.55, 40,   0.0,   0.1,  0.0,  0.0,  0.0),
    "metal":     (0.45,   1.0,  70,   0.8,   0.0,  0.0,  0.08, 0.0),
    "painted_metal": (0.9, 0.45, 35,  0.25,  0.05, 0.0,  0.12, 0.0),
    "skin":      (1.0,    0.18, 14,   0.0,   0.45, 0.4,  0.05, 0.0),
    "cloth":     (1.0,    0.0,  4,    0.0,   0.25, 0.0,  0.15, 0.35),
    "stone":     (1.0,    0.06, 10,   0.0,   0.1,  0.0,  0.9,  0.0),
    "wood":      (1.0,    0.12, 16,   0.0,   0.1,  0.0,  0.35, 0.0),
    "glass":     (0.3,    1.0,  140,  0.55,  0.0,  0.0,  0.0,  0.0),
    "leaf":      (1.0,    0.25, 20,   0.0,   0.35, 0.3,  0.1,  0.0),
}


def light_vec(angle, elevation):
    """Light coming FROM `angle` degrees (0 = right, 90 = up, 180 = left) at `elevation` degrees."""
    a, e = math.radians(angle), math.radians(elevation)
    v = np.array([math.cos(e) * math.cos(a), -math.cos(e) * math.sin(a), math.sin(e)], np.float32)
    return v / np.linalg.norm(v)


def inflate(mask, max_grid=220):
    """Smooth 'balloon' height over a mask: solve -laplacian(h) = 4 with h = 0 outside (on a coarse
    grid), then sqrt. A disk gives an exact hemisphere, a tube a round cross-section - no creases."""
    H, W = mask.shape
    s = max(1.0, max(H, W) / float(max_grid))
    if s > 1:
        sw, sh = max(2, int(round(W / s))), max(2, int(round(H / s)))
        small = np.asarray(Image.fromarray((mask * 255).astype(np.uint8), "L").resize((sw, sh), Image.BILINEAR)) > 127
    else:
        small = mask.copy()
        sw, sh = W, H
    small[0, :] = small[-1, :] = False
    small[:, 0] = small[:, -1] = False
    n = int(small.sum())
    if n == 0:
        return np.zeros((H, W), np.float32)
    idx = -np.ones(small.shape, np.int64)
    idx[small] = np.arange(n)
    rows, cols, vals = [np.arange(n)], [np.arange(n)], [np.full(n, 4.0)]
    ys, xs = np.nonzero(small)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nb = idx[ys + dy, xs + dx]
        ok = nb >= 0
        rows.append(idx[ys[ok], xs[ok]])
        cols.append(nb[ok])
        vals.append(np.full(int(ok.sum()), -1.0))
    A = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    sol = spsolve(A, np.full(n, 4.0))
    hs = np.zeros(small.shape, np.float32)
    hs[small] = np.sqrt(np.maximum(sol, 0)).astype(np.float32)
    if s > 1:
        hs = np.asarray(Image.fromarray(hs, "F").resize((W, H), Image.BICUBIC), np.float32) * s
    return np.where(mask, np.maximum(hs, 0), 0).astype(np.float32)


def height_field(img, profile="round", radius=24.0, by_color=True, color_tolerance=0.06, smooth=1.5,
                 bump=0.0, bump_scale=6.0, seed=3):
    alpha = img[..., 3]
    inside = alpha > 0.5
    core = inside.copy()
    labels = None
    if by_color:
        q = np.round(img[..., :3] / max(color_tolerance, 1e-3)).astype(np.int32)
        q = q.astype(np.int64)
        key = (q[..., 0] * 73856093) ^ (q[..., 1] * 19349663) ^ (q[..., 2] * 83492791)
        key = np.where(inside, key, -1)
        seam = np.zeros_like(inside)
        seam[:, 1:] |= key[:, 1:] != key[:, :-1]
        seam[1:, :] |= key[1:, :] != key[:-1, :]
        # thin outlines (darker than both neighbours) also count as seams
        core &= ~seam
        _, labels = np.unique(key, return_inverse=True)
        labels = labels.reshape(key.shape)
    if profile in ("dome", "pillow"):
        h = inflate(core)
        if profile == "pillow":          # flatter top, soft rounded sides
            m = max(1.0, float(h.max()))
            h = m * np.clip(h / m, 0, 1) ** 0.45 * 0.6
        h = gblur(h, smooth)
    else:
        d = gblur(ndimage.distance_transform_edt(core).astype(np.float32), 0.8)
        t = np.clip(d / float(radius), 0, 1)
        if profile == "round":
            h = radius * np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1))
        elif profile == "bevel":
            h = radius * t
        else:  # flat
            h = np.zeros_like(d)
        h = gblur(h.astype(np.float32), smooth)
    if bump > 0:
        n = fbm(h.shape[0], h.shape[1], bump_scale * 4, 4, 0.55, seed) - 0.5
        n2 = fbm(h.shape[0], h.shape[1], bump_scale, 3, 0.5, seed + 1) - 0.5
        h = h + (n * 0.6 + n2 * 0.4) * bump * radius * 0.35
    h[~inside] = 0
    return h, inside


def render_form(img, material="painted_metal", profile="round", radius=24.0, by_color=True, depth=1.0,
                key_angle=135.0, key_elevation=40.0, key_color="#fff4e0", key_intensity=1.0,
                fill_color="#4a6080", fill_intensity=0.35, sky_color="#9fc6e8", ground_color="#3a2f28",
                ambient=0.35, rim_angle=None, rim_color="#bff4ff", rim_intensity=0.0, rim_power=3.0,
                spec_color="#ffffff", ao=0.6, env_sky="#cfe8ff", env_ground="#2b2622", env_horizon="#ffffff",
                sss_color="#ff3818", bump=None, bump_scale=6.0, smooth=1.5, seed=3, overrides=None):
    """Return the shaded RGBA image (same alpha as the input)."""
    diff_k, spec_k, shin, metal, wrap, sss, bump_m, sheen = MATERIALS.get(material, MATERIALS["matte"])
    if overrides:
        diff_k = overrides.get("diffuse", diff_k)
        spec_k = overrides.get("specular", spec_k)
        shin = overrides.get("shininess", shin)
        metal = overrides.get("metalness", metal)
        wrap = overrides.get("wrap", wrap)
        sss = overrides.get("subsurface", sss)
        sheen = overrides.get("sheen", sheen)
    h, inside = height_field(img, profile, radius, by_color, smooth=smooth,
                             bump=bump_m if bump is None else bump, bump_scale=bump_scale, seed=seed)
    gy, gx = np.gradient(h)
    nx, ny, nz = -gx * depth, -gy * depth, np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    nx, ny, nz = nx / ln, ny / ln, nz / ln
    base = img[..., :3]

    L = light_vec(key_angle, key_elevation)
    ndl = nx * L[0] + ny * L[1] + nz * L[2]
    diffuse = np.clip((ndl + wrap) / (1 + wrap), 0, 1)
    # hemisphere ambient: surfaces facing up (ny < 0 on screen) see the sky
    up = np.clip(0.5 - 0.5 * ny, 0, 1)[..., None]
    amb = (rgb(ground_color) * (1 - up) + rgb(sky_color) * up) * ambient
    F = light_vec(key_angle + 180, 20)
    fill = np.clip(nx * F[0] + ny * F[1] + nz * F[2], 0, 1)[..., None] * rgb(fill_color) * fill_intensity

    # ambient occlusion: cavities (lower than the blurred surroundings) and near the silhouette
    cav = np.clip((gblur(h, radius * 0.6) - h) / max(radius * 0.35, 1), 0, 1)
    edge = np.clip(1 - ndimage.distance_transform_edt(inside) / max(radius * 0.5, 1), 0, 1)
    occ = 1 - ao * np.clip(cav * 0.9 + edge * 0.25, 0, 1)

    lit = base * (amb + diffuse[..., None] * rgb(key_color) * key_intensity * diff_k + fill) * occ[..., None]

    # metal: environment reflection by the reflected view vector's vertical direction
    if metal > 0:
        ry = 2 * nz * ny          # reflect V=(0,0,1): r = 2(n.V)n - V
        t = np.clip(0.5 - 0.5 * ry, 0, 1)
        horizon = np.exp(-((t - 0.5) ** 2) / 0.004)[..., None]
        env = rgb(env_ground) * (1 - t[..., None]) + rgb(env_sky) * t[..., None]
        env = env * (1 - 0.6 * horizon) + rgb(env_horizon) * 0.6 * horizon
        lit = lit * (1 - metal) + base * env * metal * 1.3 * occ[..., None]

    # specular (Blinn-Phong), tinted by the base color for metals
    H = L + np.array([0, 0, 1], np.float32)
    H = H / np.linalg.norm(H)
    ndh = np.clip(nx * H[0] + ny * H[1] + nz * H[2], 0, 1)
    spec = (ndh ** shin) * spec_k * (ndl > 0)
    spec_col = rgb(spec_color) * (1 - metal * 0.6) + base * metal * 0.6
    lit = lit + spec[..., None] * spec_col * key_intensity

    # subsurface scattering: warm glow near the light/shadow boundary
    if sss > 0:
        term = np.exp(-(ndl ** 2) / 0.06) * sss
        lit = lit + term[..., None] * rgb(sss_color) * base * 1.5

    # sheen (cloth) and rim light: brightest on edges turned toward the rim light
    if sheen > 0:
        lit = lit + ((1 - nz) ** 2)[..., None] * sheen * rgb(key_color) * base
    if rim_intensity > 0:
        ra = math.radians(key_angle + 180 if rim_angle is None else rim_angle)
        rdir = np.array([math.cos(ra), -math.sin(ra)], np.float32)
        facing = np.clip(nx * rdir[0] + ny * rdir[1], 0, 1) / np.maximum(np.sqrt(nx * nx + ny * ny), 1e-4)
        rim = ((1 - nz) ** (1.0 / max(rim_power, 0.1))) * facing
        lit = lit + (rim ** rim_power)[..., None] * rgb(rim_color) * rim_intensity

    out = img.copy()
    out[..., :3] = np.clip(lit, 0, 1)
    return out


# ----------------------------------------------------------------------------- textures

def texture(h, w, kind="fbm", scale=32.0, seed=1, contrast=1.0):
    """Grayscale 0..1 pattern."""
    rng = np.random.default_rng(seed)
    if kind == "grain":
        t = rng.random((h, w)).astype(np.float32)
        t = gblur(t, 0.6)
    elif kind in ("fbm", "clouds"):
        t = fbm(h, w, scale, 6, 0.55, seed)
    elif kind in ("grime", "rust"):
        f = fbm(h, w, scale, 6, 0.6, seed)
        t = np.clip((f - 0.45) * 3.0, 0, 1) * (0.6 + 0.4 * fbm(h, w, scale / 6, 3, 0.5, seed + 7))
    elif kind == "scratches":
        im = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(im)
        rnd = random.Random(seed)
        n = int(w * h / (scale * scale) * 3)
        for _ in range(n):
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            a = rnd.uniform(0, math.pi)
            ln = rnd.uniform(0.3, 1.5) * scale
            pts = [(x + math.cos(a) * ln * i / 4 + rnd.uniform(-1, 1), y + math.sin(a) * ln * i / 4 + rnd.uniform(-1, 1))
                   for i in range(5)]
            dr.line(pts, fill=rnd.randint(90, 255), width=1)
        t = np.asarray(im, np.float32) / 255.0
    elif kind in ("cells", "stone", "scales"):
        n = max(4, int(w * h / (scale * scale)))
        seeds = np.zeros((h, w), bool)
        ys, xs = rng.integers(0, h, n), rng.integers(0, w, n)
        seeds[ys, xs] = True
        dist, (iy, ix) = ndimage.distance_transform_edt(~seeds, return_indices=True)
        lab = iy * w + ix
        border = np.zeros((h, w), bool)
        border[:, 1:] |= lab[:, 1:] != lab[:, :-1]
        border[1:, :] |= lab[1:, :] != lab[:-1, :]
        edge = ndimage.distance_transform_edt(~border)
        t = np.clip(edge / (scale * 0.25), 0, 1)
        if kind == "stone":
            t = t * (0.7 + 0.3 * fbm(h, w, scale / 2, 4, 0.5, seed + 3))
    elif kind == "fabric":
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        s = max(2.0, scale / 8)
        t = 0.5 + 0.25 * np.sin(xx / s * math.pi) * np.sign(np.sin(yy / (2 * s) * math.pi)) \
            + 0.25 * np.sin(yy / s * math.pi) * np.sign(np.sin(xx / (2 * s) * math.pi))
        t = t * 0.85 + 0.15 * rng.random((h, w)).astype(np.float32)
    else:
        raise ValueError(f"Unknown texture kind {kind!r}")
    if contrast != 1.0:
        t = np.clip(0.5 + (t - 0.5) * contrast, 0, 1)
    return t.astype(np.float32)


def colorize(t, dark="#000000", light="#ffffff", alpha=None):
    out = np.zeros(t.shape + (4,), np.float32)
    out[..., :3] = rgb(dark) * (1 - t[..., None]) + rgb(light) * t[..., None]
    out[..., 3] = 1.0 if alpha is None else alpha
    return out


# ----------------------------------------------------------------------------- painterly

def _cells(diff, alpha, step, threshold, first):
    """Vectorized: for each step x step cell, the pixel with the largest error, if the cell needs paint."""
    H, W = diff.shape
    hc, wc = int(math.ceil(H / step)), int(math.ceil(W / step))
    pad = np.zeros((hc * step, wc * step), np.float32)
    pad[:H, :W] = diff * (alpha > 0.5)
    blocks = pad.reshape(hc, step, wc, step).transpose(0, 2, 1, 3).reshape(hc, wc, step * step)
    arg = blocks.argmax(-1)
    mean = blocks.mean(-1)
    keep = (mean > (0.0 if first else threshold)) & (blocks.max(-1) > 0)
    cy, cx = np.nonzero(keep)
    a = arg[cy, cx]
    ys, xs = cy * step + a // step, cx * step + a % step
    ok = (ys < H) & (xs < W)
    return ys[ok], xs[ok]


def painterly(img, sizes=(24, 12, 6, 3), threshold=0.06, max_length=10, curvature=0.6, bristles=True,
              color_jitter=0.04, seed=7, underpaint=True, flow_scale=180.0):
    """Hertzmann-style painterly re-render: long curved strokes that follow the image's forms,
    coarse to fine; fine strokes only where detail needs them. In flat areas strokes follow a gently
    flowing direction field instead of inventing swirls. Returns RGBA (alpha = original)."""
    rnd = random.Random(seed)
    H, W = img.shape[:2]
    alpha = img[..., 3]
    ref = img[..., :3]
    S = 2  # supersampling for smooth stroke edges
    canvas = gblur(ref, sizes[0] * 0.5) if underpaint else ref.copy()
    big = Image.fromarray(np.clip(canvas * 255, 0, 255).astype(np.uint8), "RGB").resize((W * S, H * S), Image.BILINEAR)
    draw = ImageDraw.Draw(big)
    # flow field for low-detail areas: smooth noise angles, mostly diagonal like a painter's hand
    flow = (fbm(H, W, flow_scale, 3, 0.5, seed + 99) - 0.5) * math.pi * 0.9 + math.radians(-35)
    fx, fy = np.cos(flow).astype(np.float32), np.sin(flow).astype(np.float32)
    for li, R in enumerate(sizes):
        blur = gblur(ref, max(0.5, R * 0.5))
        L = lum(blur)
        gy = ndimage.sobel(L, axis=0)
        gx = ndimage.sobel(L, axis=1)
        gmag = np.hypot(gx, gy)
        # isophote direction where there is structure, flow field where flat
        wgt = gmag / (gmag + 0.04)
        tx = (-gy / np.maximum(gmag, 1e-6)) * wgt + fx * (1 - wgt)
        ty = (gx / np.maximum(gmag, 1e-6)) * wgt + fy * (1 - wgt)
        cur = np.asarray(big.resize((W, H), Image.BILINEAR), np.float32) / 255.0
        diff = np.sqrt(((cur - blur) ** 2).sum(-1))
        step = max(2, int(R * 0.8))
        ys, xs = _cells(diff, alpha, step, threshold, li == 0)
        strokes = []
        stop = threshold * 1.6
        for y, x in zip(ys.tolist(), xs.tolist()):
            c = blur[y, x]
            pts = [(x, y)]
            dxp = dyp = 0.0
            px, py = float(x), float(y)
            for _ in range(max_length):
                iy, ix = int(py), int(px)
                dx, dy = float(tx[iy, ix]), float(ty[iy, ix])
                if dxp * dx + dyp * dy < 0:
                    dx, dy = -dx, -dy
                if dxp or dyp:
                    dx, dy = curvature * dx + (1 - curvature) * dxp, curvature * dy + (1 - curvature) * dyp
                n = math.hypot(dx, dy) or 1
                dx, dy = dx / n, dy / n
                px, py = px + R * dx, py + R * dy
                if not (0 <= px < W and 0 <= py < H) or alpha[int(py), int(px)] < 0.5:
                    break
                if np.sqrt(((blur[int(py), int(px)] - c) ** 2).sum()) > stop and len(pts) > 1:
                    break
                pts.append((px, py))
                dxp, dyp = dx, dy
            strokes.append((pts, c, R))
        rnd.shuffle(strokes)
        for pts, c, r in strokes:
            base = np.clip(c + (rnd.uniform(-1, 1) * color_jitter)
                           + np.array([rnd.uniform(-1, 1) for _ in range(3)]) * color_jitter * 0.4, 0, 1)
            spts = [(p[0] * S, p[1] * S) for p in pts]
            if len(spts) == 1:
                spts = spts + [(spts[0][0] + 0.5, spts[0][1] + 0.5)]
            width = max(1, int(r * S * 1.6))
            col = tuple(int(v * 255) for v in base)
            if bristles and r >= 3:
                nb = min(10, max(3, int(r / 1.5)))
                ax, ay = spts[-1][0] - spts[0][0], spts[-1][1] - spts[0][1]
                ln = math.hypot(ax, ay) or 1
                nx, ny = -ay / ln, ax / ln
                bw = max(1, int(width / nb * 1.7))
                for b in range(nb):
                    o = (b / (nb - 1) - 0.5) * width * 0.9 if nb > 1 else 0
                    shade = rnd.uniform(-1, 1) * color_jitter * 1.5
                    bc = tuple(int(np.clip(v + shade, 0, 1) * 255) for v in base)
                    cut = rnd.randint(0, max(0, len(spts) // 4))
                    bp = [(x + nx * o, y + ny * o) for x, y in spts[: len(spts) - cut or None]]
                    if len(bp) > 1:
                        draw.line(bp, fill=bc, width=bw, joint="curve")
            else:
                draw.line(spts, fill=col, width=width, joint="curve")
                if width > 3:
                    rr = width / 2
                    for p in (spts[0], spts[-1]):
                        draw.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], fill=col)
    small = np.asarray(big.resize((W, H), Image.LANCZOS), np.float32) / 255.0
    out = np.zeros((H, W, 4), np.float32)
    out[..., :3] = small
    out[..., 3] = alpha
    return out


# ----------------------------------------------------------------------------- shadows

def cast_shadow(alpha, base_y, base_x, direction=(0.6, -0.25), softness=12.0, falloff=0.6, contact=0.9,
                contact_size=6.0):
    """Shadow on a ground plane from a silhouette (alpha H x W). The object's 'up' axis is mapped to
    `direction` (screen dx, dy per pixel of height; e.g. (0.8, -0.2) = long shadow to the right, slightly
    back). Sharp at the contact point, softer and fainter with distance. Returns a 0..1 opacity map
    on the same canvas."""
    H, W = alpha.shape
    dx, dy = direction
    # dest = base + A (src - base), A = [[1, -dx], [0, -dy]] for src above base (src_y - base_y <= 0)
    a, b, c, d = 1.0, -dx, 0.0, -dy
    det = a * d - b * c
    if abs(det) < 1e-4:
        d = -0.01 if d <= 0 else 0.01
        det = a * d - b * c
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    # PIL AFFINE maps output (x, y) -> input (ax + by + c, dx + ey + f)
    coeffs = (ia, ib, base_x - ia * base_x - ib * base_y, ic, id_, base_y - ic * base_x - id_ * base_y)
    src = Image.fromarray((np.clip(alpha, 0, 1) * 255).astype(np.uint8), "L")
    proj = np.asarray(src.transform((W, H), Image.AFFINE, coeffs, resample=Image.BILINEAR), np.float32) / 255.0
    # only parts of the object above the base cast onto the ground
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = np.hypot(xx - base_x, yy - base_y)
    far = np.clip(dist / max(1.0, float(np.percentile(dist[proj > 0.1], 95)) if (proj > 0.1).any() else 1.0), 0, 1)
    sharp = gblur(proj, max(0.6, softness * 0.15))
    soft = gblur(proj, softness)
    sh = sharp * (1 - far) + soft * far
    sh = sh * (1 - falloff * far)
    if contact > 0:
        # dark occlusion right where the object meets the ground
        band = np.exp(-((yy - base_y) ** 2) / (2 * contact_size ** 2))
        foot = gblur((alpha > 0.5).astype(np.float32) * (np.abs(yy - base_y) < contact_size * 2), contact_size)
        sh = np.maximum(sh, np.clip(foot * band * 3, 0, 1) * contact)
    return np.clip(sh, 0, 1).astype(np.float32)


# ----------------------------------------------------------------------------- organic shapes

def _catmull(pts, per=8):
    if len(pts) < 3:
        return pts
    out = []
    n = len(pts)
    for i in range(n - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, n - 1)]
        for s in range(per):
            t = s / per
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in range(len(p1))))
    out.append(tuple(pts[-1]))
    return out


def tube_outline(spine, caps=True):
    """spine [[x, y, radius], ...] -> closed outline points of a smooth tube (limbs, fingers, tentacles,
    branches, hair locks, horns). Radius can change along the spine."""
    pts = _catmull([tuple(float(v) for v in p) for p in spine], 10)
    left, right = [], []
    n = len(pts)
    for i, (x, y, r) in enumerate(pts):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, n - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln, dx / ln
        left.append([x + nx * r, y + ny * r])
        right.append([x - nx * r, y - ny * r])
    out = left
    if caps:
        x, y, r = pts[-1]
        a0 = math.atan2(left[-1][1] - y, left[-1][0] - x)
        out = out + [[x + math.cos(a0 - math.pi * k / 8) * r, y + math.sin(a0 - math.pi * k / 8) * r] for k in range(1, 8)]
    out = out + right[::-1]
    if caps:
        x, y, r = pts[0]
        a0 = math.atan2(right[0][1] - y, right[0][0] - x)
        out = out + [[x + math.cos(a0 - math.pi * k / 8) * r, y + math.sin(a0 - math.pi * k / 8) * r] for k in range(1, 8)]
    return [[round(p[0], 2), round(p[1], 2)] for p in out]


def blob_outline(cx, cy, rx, ry, rotation=0.0, wobble=0.15, lumps=5, seed=1, points=96):
    """Irregular rounded shape: rocks, clouds, muscles, bushes, puddles, cells."""
    rnd = random.Random(seed)
    harmonics = [(k, rnd.uniform(0, 2 * math.pi), rnd.uniform(0.4, 1.0)) for k in range(2, 2 + int(lumps))]
    rot = math.radians(rotation)
    out = []
    for i in range(points):
        t = 2 * math.pi * i / points
        r = 1 + wobble * sum(a * math.sin(k * t + ph) / k for k, ph, a in harmonics)
        x, y = math.cos(t) * rx * r, math.sin(t) * ry * r
        out.append([round(cx + x * math.cos(rot) - y * math.sin(rot), 2),
                    round(cy + x * math.sin(rot) + y * math.cos(rot), 2)])
    return out


def expand_shapes(shapes):
    """Turn organic shape types into polygons understood by the Krita plugin."""
    if not shapes:
        return shapes
    out = []
    for s in shapes:
        t = s.get("type")
        if t == "tube":
            s = dict(s, type="polygon", points=tube_outline(s["spine"], s.get("caps", True)))
            s.pop("spine", None)
        elif t == "blob":
            s = dict(s, type="polygon", points=blob_outline(
                s["cx"], s["cy"], s.get("rx", s.get("r", 50)), s.get("ry", s.get("r", 50)),
                s.get("rotation", 0), s.get("wobble", 0.15), s.get("lumps", 5), s.get("seed", 1)))
        out.append(s)
    return out


# ----------------------------------------------------------------------------- natural strokes

def naturalize(stroke, size, amount=0.5, seed=1):
    """Make a stroke feel hand-drawn: gentle wobble, pressure that swells and lifts, slight overshoot."""
    pts = [list(map(float, p)) + ([1.0] if len(p) < 3 else []) for p in stroke["points"]]
    has_pressure = any(len(p) > 2 for p in stroke["points"])
    if len(pts) < 2 or amount <= 0:
        return stroke
    dense = _catmull([tuple(p) for p in pts], 8) if stroke.get("smooth", True) else [tuple(p) for p in pts]
    # resample evenly
    seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(dense, dense[1:])]
    total = sum(seg) or 1.0
    n = max(8, int(total / max(2.0, size * 0.6)))
    res, acc, j = [], 0.0, 0
    for i in range(n + 1):
        target = total * i / n
        while j < len(seg) - 1 and acc + seg[j] < target:
            acc += seg[j]
            j += 1
        f = 0 if seg[j] == 0 else (target - acc) / seg[j]
        a, b = dense[j], dense[min(j + 1, len(dense) - 1)]
        res.append([a[k] + (b[k] - a[k]) * f for k in range(3)])
    wob = noise1d(len(res), max(2, total / 120), seed)
    amp = amount * min(0.012 * total + 0.25 * size, 6 + size)
    out = []
    for i, (x, y, p) in enumerate(res):
        a = res[max(i - 1, 0)]
        b = res[min(i + 1, len(res) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy) or 1
        nx, ny = -dy / ln, dx / ln
        t = i / (len(res) - 1)
        if not has_pressure:
            swell = math.sin(math.pi * min(1, t * 1.15)) ** 0.6
            p = 0.25 + 0.75 * swell
        p = max(0.05, p * (1 + 0.15 * amount * wob[(i * 7) % len(wob)]))
        out.append([round(x + nx * wob[i] * amp, 2), round(y + ny * wob[i] * amp, 2), round(p, 3)])
    # overshoot past the ends, lifting off
    ov = amount * min(0.05 * total, 3 * size)
    if ov > 0.5:
        for end, nb, sign in ((out[-1], out[-2], 1), (out[0], out[1], -1)):
            dx, dy = end[0] - nb[0], end[1] - nb[1]
            ln = math.hypot(dx, dy) or 1
            extra = [round(end[0] + dx / ln * ov, 2), round(end[1] + dy / ln * ov, 2), 0.05]
            if sign > 0:
                out.append(extra)
            else:
                out.insert(0, extra)
    s = dict(stroke, points=out)
    return s
