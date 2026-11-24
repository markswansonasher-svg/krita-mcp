"""
Depth for the Krita MCP: a per-document depth buffer (view-space distance in metres per pixel)
written by 3D-aware drawing (3D polygons, posed figures), and the effects that need it:
atmospheric perspective, depth of field, screen-space ambient occlusion, cast shadows from 3D
geometry, and point lights placed in the scene.
"""
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

import realism

INF = np.float32(1e9)


class DepthBuffer:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.z = np.full((h, w), INF, np.float32)

    def write_triangle(self, s0, s1, s2, z0, z1, z2):
        """Screen triangle with view-space depths at its corners; 1/z interpolated (perspective
        correct); nearer wins."""
        xs = [s0[0], s1[0], s2[0]]
        ys = [s0[1], s1[1], s2[1]]
        x0, x1 = max(0, int(math.floor(min(xs)))), min(self.w - 1, int(math.ceil(max(xs))))
        y0, y1 = max(0, int(math.floor(min(ys)))), min(self.h - 1, int(math.ceil(max(ys))))
        if x1 < x0 or y1 < y0:
            return
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
        xx += 0.5
        yy += 0.5
        d = (s1[1] - s2[1]) * (s0[0] - s2[0]) + (s2[0] - s1[0]) * (s0[1] - s2[1])
        if abs(d) < 1e-9:
            return
        a = ((s1[1] - s2[1]) * (xx - s2[0]) + (s2[0] - s1[0]) * (yy - s2[1])) / d
        b = ((s2[1] - s0[1]) * (xx - s2[0]) + (s0[0] - s2[0]) * (yy - s2[1])) / d
        c = 1 - a - b
        inside = (a >= -1e-4) & (b >= -1e-4) & (c >= -1e-4)
        if not inside.any():
            return
        iz = a / z0 + b / z1 + c / z2
        z = 1.0 / np.maximum(iz, 1e-6)
        region = self.z[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (z < region)
        region[upd] = z[upd]

    def write_polygon3d(self, cam, pts3d):
        """Convex-ish 3D polygon (fan triangulated)."""
        sp = [cam.project(p) for p in pts3d]
        zs = [cam.depth(p) for p in pts3d]
        for i in range(1, len(pts3d) - 1):
            self.write_triangle(sp[0], sp[i], sp[i + 1], zs[0], zs[i], zs[i + 1])

    def write_mask(self, mask, z):
        """A flat-depth silhouette (alpha mask or polygon raster) at depth z (scalar or array)."""
        zz = np.broadcast_to(np.asarray(z, np.float32), self.z.shape)
        upd = mask & (zz < self.z)
        self.z[upd] = zz[upd]

    def write_polygon2d(self, pts, z):
        im = Image.new("L", (self.w, self.h), 0)
        ImageDraw.Draw(im).polygon([(float(x), float(y)) for x, y in pts], fill=1)
        self.write_mask(np.asarray(im) > 0, z)

    def filled(self, far=None):
        z = self.z.copy()
        if far is None:
            finite = z[z < INF]
            far = float(finite.max()) * 1.5 if finite.size else 100.0
        z[z >= INF] = far
        return z


# ----------------------------------------------------------------------------- effects

def atmosphere(z, color, density=0.06, start=0.0, max_opacity=0.85, height_falloff=None, ys=None):
    """Fog opacity per pixel: 1 - exp(-density * (z - start)), capped. Returns RGBA."""
    a = 1.0 - np.exp(-density * np.maximum(z - start, 0.0))
    a = np.clip(a, 0, max_opacity).astype(np.float32)
    return realism.colorize(np.zeros(z.shape, np.float32), color, color, alpha=a)


def depth_of_field(img, z, focus, focus_range=0.5, max_blur=10.0, bands=7):
    """Blur that grows with distance from the focus plane. img RGBA (straight alpha)."""
    coc = np.clip((np.abs(z - focus) - focus_range) / max(focus, 1e-3) * 4.0, 0, 1) * max_blur
    levels = np.linspace(0, max_blur, bands)
    pre = img.copy()
    pre[..., :3] *= pre[..., 3:4]                          # premultiply for clean blurs
    blurred = [pre] + [realism.gblur(pre, max(0.5, s * 0.5)) for s in levels[1:]]
    idx = np.clip(coc / max(max_blur, 1e-6) * (bands - 1), 0, bands - 1)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, bands - 1)
    f = (idx - lo)[..., None]
    stack = np.stack(blurred, 0)
    H, W = z.shape
    yy, xx = np.mgrid[0:H, 0:W]
    out = stack[lo, yy, xx] * (1 - f) + stack[hi, yy, xx] * f
    a = np.clip(out[..., 3:4], 1e-6, 1)
    res = out.copy()
    res[..., :3] = np.where(a > 1e-5, out[..., :3] / a, 0)
    return res


def ambient_occlusion(z, radius=12, strength=1.0, bias=0.03):
    """Screen-space ambient occlusion: darker where nearby pixels are in front (creases, where a
    figure meets a wall or floor). Returns an occlusion map 0..1 (1 = fully occluded)."""
    occ = np.zeros_like(z)
    n = 0
    for r in (radius * 0.35, radius * 0.7, radius):
        for k in range(8):
            a = 2 * math.pi * k / 8 + r
            dx, dy = int(round(math.cos(a) * r)), int(round(math.sin(a) * r))
            sh = np.roll(np.roll(z, dy, 0), dx, 1)
            diff = z - sh                                    # >0 when the neighbour is nearer
            rel = diff / np.maximum(z, 1e-3)
            occ += np.clip((rel - bias) * 8.0, 0, 1) * (rel < 0.5)
            n += 1
    occ = realism.gblur(occ / n, max(1.0, radius * 0.25)) * strength
    return np.clip(occ, 0, 1).astype(np.float32)


def view_positions(z, cam):
    """View-space x, y (metres) for every pixel."""
    H, W = z.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vx = (xx - cam.cx) * z / cam.f
    vy = -(yy - cam.cy) * z / cam.f
    return vx, vy


def point_lights(img, z, cam, lights, normal_from="layer", profile_radius=10.0, wrap=0.15):
    """Light every pixel of `img` (a layer, RGBA) from point lights placed in the 3D scene.
    Normals come from the layer's own silhouette/colour regions (render_form's height field) for
    shape, combined with the depth buffer for position. lights: [{pos: [x, y, z] world, color,
    intensity, range (m), radius}] Returns an RGB light map (H x W x 3) to add."""
    vx, vy = view_positions(z, cam)
    h, inside = realism.height_field(img, "round", profile_radius, True, smooth=1.5)
    gy, gx = np.gradient(h)
    nx, ny, nz = -gx, -gy, np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    # screen normal (x right, y down, z toward viewer) -> view space (x right, y up, z away)
    n = np.stack([nx / ln, -ny / ln, -nz / ln], -1)
    out = np.zeros(z.shape + (3,), np.float32)
    for L in lights:
        lp = cam.view(L["pos"])
        lx, ly, lz = lp[0] - vx, lp[1] - vy, lp[2] - z
        d = np.sqrt(lx * lx + ly * ly + lz * lz) + 1e-6
        ndl = (n[..., 0] * lx + n[..., 1] * ly + n[..., 2] * lz) / d
        diff = np.clip((ndl + wrap) / (1 + wrap), 0, 1)
        rng = float(L.get("range", 4.0))
        att = 1.0 / (1.0 + (d / rng) ** 2)
        out += (diff * att * float(L.get("intensity", 1.0)))[..., None] * realism.rgb(L.get("color", "#ffffff"))
    out *= inside[..., None]
    return out


def floor_shadow(spheres, light, cam, w, h, floor_y=0.0, softness=1.0):
    """Shadow on the floor plane (y = floor_y) cast by spheres [(center3d, radius)] from a point
    light. Returns a 0..1 map (screen). Each sphere projects to an ellipse on the floor; softness
    grows with the distance between the sphere and the floor (penumbra)."""
    im = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(im)
    lx, ly, lz = light
    shadows = []
    for (cx, cy, cz), r in spheres:
        if cy >= ly:
            continue
        t = (ly - floor_y) / max(ly - cy, 1e-3)              # light -> sphere -> floor
        px, pz = lx + (cx - lx) * t, lz + (cz - lz) * t
        rr = r * t
        # sample the floor disc, project to screen
        pts = [cam.project([px + math.cos(a) * rr, floor_y, pz + math.sin(a) * rr])
               for a in np.linspace(0, 2 * math.pi, 24, endpoint=False)]
        shadows.append((pts, cy - floor_y))
    for pts, height in sorted(shadows, key=lambda s: -s[1]):
        dr.polygon([tuple(p) for p in pts], fill=255)
    m = realism.gblur(np.asarray(im, np.float32) / 255.0, 2.0 + 6.0 * softness)
    # contact shadows: tight, dark patches straight under whatever nearly touches the floor
    cim = Image.new("L", (w, h), 0)
    cdr = ImageDraw.Draw(cim)
    for (cx, cy, cz), r in spheres:
        gap = cy - r - floor_y
        if gap > 0.12:
            continue
        k = 1.0 - max(gap, 0.0) / 0.12
        rr = r * 1.25
        pts = [cam.project([cx + math.cos(a) * rr, floor_y, cz + math.sin(a) * rr * 0.9])
               for a in np.linspace(0, 2 * math.pi, 24, endpoint=False)]
        cdr.polygon([tuple(p) for p in pts], fill=int(255 * k))
    contact = realism.gblur(np.asarray(cim, np.float32) / 255.0, 2.5)
    return np.clip(np.maximum(m * 0.8, contact), 0, 1)


def light_wrap(subject, background, radius=10.0, strength=0.6):
    """Background light bleeding over a subject's edges (how real optics and paint blend a figure
    into its surroundings). subject/background RGBA. Returns RGBA to put over the subject."""
    a = subject[..., 3]
    bg = realism.gblur(background[..., :3], radius)
    inner = realism.gblur(a, radius * 0.6)
    band = np.clip(a * (1.0 - inner) * 2.2, 0, 1)                 # just inside the silhouette edge
    lum = realism.lum(bg)
    wrap = band * np.clip(lum * 1.3, 0, 1) * strength              # bright background wraps more
    out = np.zeros_like(subject)
    out[..., :3] = bg
    out[..., 3] = wrap
    return out


def harmonize(subject, background, strength=0.35, ring=40):
    """Pull a subject's colours toward its surroundings (mean/contrast transfer in each channel from
    a ring of background around it) - so it shares the scene's light and palette."""
    a = subject[..., 3] > 0.5
    if not a.any():
        return subject.copy()
    near = ndimage.binary_dilation(a, iterations=int(ring)) & ~a
    out = subject.copy()
    for c in range(3):
        s_ = subject[..., c][a]
        b_ = background[..., c][near] if near.any() else background[..., c].ravel()
        ms, ss = s_.mean(), s_.std() + 1e-4
        mb, sb = b_.mean(), b_.std() + 1e-4
        moved = (subject[..., c] - ms) / ss * (ss * 0.6 + sb * 0.4) + (ms * 0.5 + mb * 0.5)
        out[..., c] = np.clip(subject[..., c] * (1 - strength) + moved * strength, 0, 1)
    out[..., 3] = subject[..., 3]
    return out
