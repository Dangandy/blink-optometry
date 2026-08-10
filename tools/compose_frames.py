#!/usr/bin/env python3
"""
compose_frames.py — build the five intro stills from REAL page screenshots.

Inputs (shot with the Playwright browser at DPR 1; see "Screenshots" below):
  shots/hero_1024x1536.png   S1 — viewport plate of /?shot=hero
  shots/fullpage_1024w.png   S2 — full-page plate of /?shot=page
  assets/frame2..5*.png      the ORIGINAL machine/lens photography (source
                             material only — every page pixel is replaced)

Outputs:
  assets/opt/frame1..5.webp        the intro sequence (q80)
  assets/opt/machine_cutout.png    the phoropter, knocked off its white wall
  assets/opt/measurements.json     + tools/measurements.json (identical)
  shots/work/*.png                 full-res masters (frame5_full.png is the
                                   lossless final frame for the Phase-3 video)

Geometry is CONSTRUCTED, never eyeballed: the lens content is a circular crop
of S1 centred on the hero lockup, so the frame5 -> live-hero handoff constants
fall out of the crop arithmetic (printed at the end, and written to
measurements.json for js/main.js to bake in).

Screenshots (rerun before this script if the page changes):
  browser.resize(1024, 1536)
  browser.navigate('http://localhost:8000/?shot=hero') -> shots/hero_1024x1536.png
  browser.navigate('http://localhost:8000/?shot=page') -> shots/fullpage_1024w.png (fullPage)
  #hero-lockup's getBoundingClientRect() in the hero plate -> S1_LOCKUP below.

Blur is a DISC (pillbox) kernel convolved in linear light — Gaussian reads as
"smudged JPEG", a disc keeps strokes as banded shapes with defined edges, which
is what "I need my glasses" actually looks like.
"""

import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

# ==========================================================================
# Constants
# ==========================================================================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OPT = os.path.join(ASSETS, "opt")
TOOLS = os.path.join(ROOT, "tools")
SHOTS = os.path.join(ROOT, "shots")
WORK = os.path.join(SHOTS, "work")

S1_PATH = os.path.join(SHOTS, "hero_1024x1536.png")
S2_PATH = os.path.join(SHOTS, "fullpage_1024w.png")
OLD_F2 = os.path.join(ASSETS, "frame2_descend_end.png")
OLD_F3 = os.path.join(ASSETS, "frame3_pushin_start.png")
OLD_F4 = os.path.join(ASSETS, "frame4_lens_blurred.png")
OLD_F5 = os.path.join(ASSETS, "frame5_lens_sharp.png")

W, H = 1024, 1536                      # every still is 1024x1536

# --- #hero-lockup and #hero-cta, measured in the browser on the S1 plate
#     (CSS px == image px at DPR 1). #hero-lockup IS the box js/main.js
#     measures at runtime, so the handoff maths below is the same box on both
#     sides of the dissolve; #hero-cta anchors frame3's background scale.
S1_LOCKUP = {"x": 343.59, "y": 628.81, "w": 336.81, "h": 278.36}
S1_CTA = {"x": 420.94, "y": 865.92, "w": 182.11, "h": 41.25}
S1_CHROME_STRIP_H = 12                 # the teal band across the top of the page

# --- frame1/2 poster: S2 printed onto a wall.
# The page is 1024x5526 (aspect 1:5.4), so a poster showing ALL of it would be
# a 200 px ribbon whose type is far too small to survive a defocus that reads
# as defocus at frame scale. The poster is therefore printed near frame width
# and bleeds off the bottom — a long sheet seen close up. Its position is
# CONSTRUCTED, not chosen: the poster is placed so the page's own lockup centre
# falls on frames 4/5's lens centre, so the whole intro dives along one fixed
# point (frame1's blurred wordmark sits exactly where the sharp one lands).
POSTER_W = 856
POSTER_SHADOW = {"dx": 7, "dy": 10, "blur": 16, "strength": 0.13}

# Disc-blur radii, px in each image's own space. All three are calibrated
# against the SOURCE photography's own defocus, measured as the 10->90 % width
# of a hard edge (a disc of radius R gives a transition of ~1.6 R):
#   old frame1 poster       13 px -> R  8    (but over 1.7x larger type)
#   old frame3 background   27 px -> R 16
#   old frame4 lens         20 px -> R 12.5
# frame1 is set blurrier than the old plate's 8 because our poster prints the
# page 1.7x smaller: R 15 reproduces the same legibility band — the wordmark
# and the button read as shapes, no text is readable.
FRAME1_BLUR_R = 15.0
FRAME3_BG_BLUR_R = 16.0
# frame4's lens interior, expressed in S1-crop space: the crop is upscaled by
# (disc diameter / crop diameter) ~ 1.82 on its way onto the disc, so this is
# divided through to land on the old frame4's measured 12.5 px... x 1.8, which
# is deliberate: the CLICK has to be felt, and the old plate's defocus is too
# mild to read at phone scale.
FRAME4_BLUR_R_S1 = 12.5
B_BLUR_SCALE = 1.02                    # blue channel blurs 2% wider (CA)

GAMMA = 2.2                            # convolve in linear light
FEATHER_PX = 2.0                       # disc paste edge
CUTOUT_FEATHER_PX = 1.0

# Machine knockout: the wall AND the old poster are near-white; the machine is
# black/brass. Everything reachable from the border at this tolerance is
# background; the machine is the largest surviving component.
NEAR_WHITE_MIN = 225
NEAR_WHITE_TOL = 14
# ...except that the old plates print the poster's edge shadow as a flat ~220
# grey rule, just under the near-white floor, and it TOUCHES the machine — so
# it survives the fill and rides along as an L-shaped ghost. Flat greys this
# bright are studio paper, never the machine (whose brights are all saturated
# brass), so they are subtracted after the fill and any hole they punch in the
# machine is closed again.
FLAT_GREY_MIN = 198
# Likewise the old brand's teal: where it brushes the machine (frame3's eye
# mark clips the arm) it would ride along as a cyan fringe on the new plate.
TEAL_MIN = 10

# Wall: the OLD frame1's wall gradient (bright top-left falling to a dimmer
# bottom-right), re-tinted warm so it sits under the cream paper instead of
# under the old pure-white page. Sampled tones are printed at run time.
WALL_TL = (241.0, 238.0, 231.0)
WALL_TR = (238.0, 235.0, 228.0)
WALL_BL = (231.0, 228.0, 221.0)
WALL_BR = (227.0, 224.0, 217.0)

WEBP_Q = 80
WEBP_METHOD = 6

anomalies = []


# ==========================================================================
# Helpers
# ==========================================================================
def kb(path):
    return os.path.getsize(path) / 1024.0


def srgb_to_lin(a):
    return np.power(np.clip(a, 0.0, 1.0), GAMMA)


def lin_to_srgb(a):
    return np.power(np.clip(a, 0.0, 1.0), 1.0 / GAMMA)


def disc_kernel(radius, ss=4):
    """Antialiased disc (pillbox), 4x4-supersampled coverage, sums to 1."""
    r = float(radius)
    n = int(np.ceil(r)) * 2 + 1
    c = n // 2
    # sub-sample offsets inside each pixel
    off = (np.arange(ss) + 0.5) / ss - 0.5
    dy = (np.arange(n) - c)[:, None, None, None] + off[None, None, :, None]
    dx = (np.arange(n) - c)[None, :, None, None] + off[None, None, None, :]
    cover = ((dx * dx + dy * dy) <= r * r).mean(axis=(2, 3))
    s = cover.sum()
    if s <= 0:
        raise ValueError("degenerate disc kernel")
    return cover / s


def disc_blur(rgb01, radius, b_scale=B_BLUR_SCALE):
    """
    Disc-blur an HxWx3 float array (sRGB 0..1) in linear light via FFT.

    The image is edge-padded by the kernel radius before the (circular) FFT
    convolution and cropped afterwards, so the wrap-around never reaches the
    visible frame — no halo bleeding in from the opposite border.
    """
    h, w = rgb01.shape[:2]
    lin = srgb_to_lin(rgb01.astype(np.float64))
    out = np.empty_like(lin)
    for ch in range(3):
        r = radius * (b_scale if ch == 2 else 1.0)
        k = disc_kernel(r)
        kh, kw = k.shape
        pad = max(kh, kw)
        p = np.pad(lin[..., ch], pad, mode="edge")
        ph, pw = p.shape
        kern = np.zeros((ph, pw), dtype=np.float64)
        kern[:kh, :kw] = k
        # roll so the kernel centre sits at (0, 0) -> convolution is centred
        kern = np.roll(kern, (-(kh // 2), -(kw // 2)), axis=(0, 1))
        conv = np.fft.irfft2(np.fft.rfft2(p) * np.fft.rfft2(kern), s=(ph, pw))
        out[..., ch] = conv[pad:pad + h, pad:pad + w]
    return lin_to_srgb(out)


def to_u8(rgb01):
    return np.clip(np.rint(rgb01 * 255.0), 0, 255).astype(np.uint8)


def to_f01(arr_u8):
    return arr_u8.astype(np.float64) / 255.0


# --- flood-fill knockout (the make_rim.py pattern) -------------------------
def scanline_fill(mask, visited, w, h, seeds, mark):
    """4-connected scanline fill over a flat bytearray mask (1 == fillable)."""
    stack = list(seeds)
    count = 0
    x0, y0, x1, y1 = w, h, -1, -1
    while stack:
        x, y = stack.pop()
        base = y * w
        if not mask[base + x] or visited[base + x]:
            continue
        xl = x
        while xl >= 0 and mask[base + xl] and not visited[base + xl]:
            xl -= 1
        xl += 1
        xr = x
        while xr < w and mask[base + xr] and not visited[base + xr]:
            xr += 1
        xr -= 1
        for i in range(base + xl, base + xr + 1):
            visited[i] = mark
        count += xr - xl + 1
        x0, x1 = min(x0, xl), max(x1, xr)
        y0, y1 = min(y0, y), max(y1, y)
        for ny in (y - 1, y + 1):
            if 0 <= ny < h:
                nbase = ny * w
                run = False
                for i in range(xl, xr + 1):
                    if mask[nbase + i] and not visited[nbase + i]:
                        if not run:
                            stack.append((i, ny))
                            run = True
                    else:
                        run = False
    if count == 0:
        return (0, 0, 0, 0, 0)
    return (count, x0, y0, x1, y1)


def largest_component(mask_bool):
    """Largest 4-connected component. -> (stats, labels HxW uint8, label)."""
    h, w = mask_bool.shape
    mask = bytearray(mask_bool.astype(np.uint8).ravel().tobytes())
    visited = bytearray(w * h)
    best = (0, 0, 0, 0, 0)
    best_label = 0
    label = 0
    for y in range(h):
        base = y * w
        if 1 not in mask[base:base + w]:
            continue
        for x in range(w):
            if mask[base + x] and not visited[base + x]:
                label = 1 if label == 0 else (label % 254) + 1
                stats = scanline_fill(mask, visited, w, h, [(x, y)], label)
                if stats[0] > best[0]:
                    best = stats
                    best_label = label
    labels = np.frombuffer(bytes(visited), dtype=np.uint8).reshape(h, w)
    return best, labels, best_label


def shift2(a, dy, dx, fill=0):
    out = np.full_like(a, fill)
    h, w = a.shape[0], a.shape[1]
    out[max(0, dy):h - max(0, -dy), max(0, dx):w - max(0, -dx)] = \
        a[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
    return out


def bleed_colour(rgb_f, known, rounds=4):
    """Grow known colour into unknown pixels so feathered edges never sample
    the background that was knocked out."""
    h, w = known.shape
    offs = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
    out = rgb_f.copy()
    kn = known.copy()
    for _ in range(rounds):
        ksum = np.zeros_like(out)
        kcnt = np.zeros((h, w), np.float64)
        kf = kn.astype(np.float64)
        masked = out * kf[..., None]
        for dy, dx in offs:
            ksum += shift2(masked, dy, dx, 0.0)
            kcnt += shift2(kf, dy, dx, 0.0)
        newly = (~kn) & (kcnt > 0)
        if not newly.any():
            break
        out[newly] = ksum[newly] / kcnt[newly][:, None]
        kn |= newly
    return out


def border_seeds(mask):
    h, w = mask.shape
    s = []
    for x in range(w):
        if mask[0, x]:
            s.append((x, 0))
        if mask[h - 1, x]:
            s.append((x, h - 1))
    for y in range(h):
        if mask[y, 0]:
            s.append((0, y))
        if mask[y, w - 1]:
            s.append((w - 1, y))
    return s


def flood_from_border(mask_bool):
    """Everything in mask_bool reachable from the image border."""
    h, w = mask_bool.shape
    ba = bytearray(mask_bool.astype(np.uint8).ravel().tobytes())
    visited = bytearray(w * h)
    seeds = border_seeds(mask_bool)
    if seeds:
        scanline_fill(ba, visited, w, h, seeds, 1)
    return np.frombuffer(bytes(visited), dtype=np.uint8).reshape(h, w) != 0, len(seeds)


def fill_holes(mask_bool):
    """Close every hole that is not connected to the image border."""
    outside, _ = flood_from_border(~mask_bool)
    return ~outside


def knockout_machine(img_u8, near_white_min=NEAR_WHITE_MIN, tol=NEAR_WHITE_TOL,
                     flat_grey_min=FLAT_GREY_MIN, teal_min=TEAL_MIN, label=""):
    """
    Isolate the phoropter from a white-studio plate.

      1. near-white, reachable from the border  -> background
      2. largest surviving component            -> the machine (page text and
                                                   other islands are dropped)
      3. minus flat studio greys and teal ink   -> the poster-edge rule that
                                                   touches the machine is cut,
                                                   and so is any old-brand ink
                                                   that brushes it (the machine
                                                   is black, brass and warm —
                                                   never cyan)
      4. largest component again, holes filled  -> a solid silhouette (teal
                                                   INSIDE the machine, i.e. the
                                                   old page seen through a lens,
                                                   is restored here and then
                                                   overwritten by the disc paste)
    """
    a = img_u8.astype(np.float64)
    mn = img_u8.min(axis=2).astype(np.int16)
    mx = img_u8.max(axis=2).astype(np.int16)
    near_white = (mn >= near_white_min) & ((mx - mn) <= tol)
    bg, n_seeds = flood_from_border(near_white)
    stats, labels, lab = largest_component(~bg)
    machine = labels == lab
    raw = int(machine.sum())

    flat_grey = (mn >= flat_grey_min) & ((mx - mn) <= tol)
    teal_ink = ((a[..., 1] + a[..., 2]) / 2.0 - a[..., 0]) > teal_min
    machine = machine & ~flat_grey & ~teal_ink
    stats, labels, lab = largest_component(machine)
    machine = fill_holes(labels == lab)

    ys, xs = np.nonzero(machine)
    print(f"  {label}near-white {100.0 * near_white.mean():.1f}%  "
          f"seeds {n_seeds}  bg {100.0 * bg.mean():.1f}%")
    print(f"  {label}machine {int(machine.sum())} px "
          f"(flat-grey ghost removed: {raw - int(machine.sum())} px)  "
          f"bbox x {xs.min()}..{xs.max()} y {ys.min()}..{ys.max()}")
    return machine


def feathered_alpha(mask_bool, feather=CUTOUT_FEATHER_PX):
    adj = (shift2(~mask_bool, 1, 0) | shift2(~mask_bool, -1, 0) |
           shift2(~mask_bool, 0, 1) | shift2(~mask_bool, 0, -1))
    a = np.where(mask_bool, 255, 0).astype(np.uint8)
    a[mask_bool & adj] = 128
    return np.asarray(Image.fromarray(a, mode="L").filter(
        ImageFilter.GaussianBlur(feather)), dtype=np.uint8)


def gauss_u8(arr_f, radius):
    """Gaussian blur of a 0..255 float plane, via Pillow."""
    u8 = np.clip(np.rint(arr_f), 0, 255).astype(np.uint8)
    return np.asarray(Image.fromarray(u8, mode="L").filter(
        ImageFilter.GaussianBlur(radius)), dtype=np.float64)


def teal_blob(img_u8, window=None, frac=0.5):
    """
    Bounding box of the strongest teal blob at half-max — the page's Book
    Appointment button. Half-max is used because these plates are defocused and
    a fixed threshold would measure the blur, not the button.
    """
    a = img_u8.astype(np.float64)
    tealness = (a[..., 1] + a[..., 2]) / 2.0 - a[..., 0]
    if window:
        x0, y0, x1, y1 = window
        m = np.full_like(tealness, -1e9)
        m[y0:y1, x0:x1] = tealness[y0:y1, x0:x1]
        tealness = m
    peak = tealness.max()
    sel = tealness >= peak * frac
    stats, labels, lab = largest_component(sel)
    ys, xs = np.nonzero(labels == lab)
    return {"x0": int(xs.min()), "x1": int(xs.max()),
            "y0": int(ys.min()), "y1": int(ys.max()),
            "w": float(xs.max() - xs.min() + 1),
            "h": float(ys.max() - ys.min() + 1),
            "cx": float((xs.min() + xs.max()) / 2.0),
            "cy": float((ys.min() + ys.max()) / 2.0)}


def place_plate(plate_u8, k, src_anchor, dst_anchor, out_w, out_h):
    """Scale a plate by k and lay it down so src_anchor lands on dst_anchor."""
    ph, pw = plate_u8.shape[:2]
    sw, sh = int(round(pw * k)), int(round(ph * k))
    scaled = np.asarray(Image.fromarray(plate_u8).resize((sw, sh), Image.LANCZOS),
                        dtype=np.uint8)
    ox = dst_anchor[0] - k * src_anchor[0]
    oy = dst_anchor[1] - k * src_anchor[1]
    xs = np.clip(np.rint(np.arange(out_w) - ox).astype(int), 0, sw - 1)
    ys = np.clip(np.rint(np.arange(out_h) - oy).astype(int), 0, sh - 1)
    return scaled[np.ix_(ys, xs)], ox, oy


def bbox_circle(x0, y0, x1, y1):
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    return {
        "cx": round(x0 + bw / 2.0, 1),
        "cy": round(y0 + bh / 2.0, 1),
        "r": round((bw / 2.0 + bh / 2.0) / 2.0, 1),
        "bbox": [int(x0), int(y0), int(x1), int(y1)],
    }


def measure_disc(arr_u8, window=None, thr=200):
    """Largest bright blob -> circle. window = (x0, y0, x1, y1) or None."""
    bright = arr_u8.min(axis=2) > thr
    if window:
        x0, y0, x1, y1 = window
        m = np.zeros_like(bright)
        m[y0:y1, x0:x1] = bright[y0:y1, x0:x1]
        bright = m
    stats, _, _ = largest_component(bright)
    if stats[0] == 0:
        return None
    return bbox_circle(*stats[1:])


def radial_shading(arr_u8, cx, cy, r, bins=64):
    """
    Multiplicative vignette V(t), t = radius/r, sampled from a disc's own
    paper: per-bin median of the brightest half of the pixels (so ink does not
    drag the curve down), normalised to the disc's flat centre.
    """
    yy, xx = np.mgrid[0:arr_u8.shape[0], 0:arr_u8.shape[1]]
    d = np.hypot(xx - cx, yy - cy) / r
    lum = arr_u8.mean(axis=2)
    prof = np.ones(bins)
    for i in range(bins):
        sel = (d >= i / bins) & (d < (i + 1) / bins)
        v = lum[sel]
        if v.size < 32:
            prof[i] = prof[i - 1] if i else 1.0
            continue
        prof[i] = np.median(v[v >= np.percentile(v, 50)])
    centre = np.median(prof[:int(bins * 0.3)])
    prof = prof / max(centre, 1e-6)
    # light smoothing, then clamp: this is a shading term, not a tone curve
    k = np.ones(5) / 5.0
    prof = np.convolve(np.pad(prof, 2, mode="edge"), k, mode="valid")
    return np.clip(prof, 0.45, 1.03)


def paste_disc(base_u8, crop_rgb01, cx, cy, r, shading, src_r,
               feather=FEATHER_PX):
    """
    Paste a circular crop into a disc at (cx, cy), with the sampled
    inner-shadow ring and a feathered edge. Linear-light multiply for the
    shading so the vignette behaves like light, not like a levels adjustment.

    src_r is the crop's radius in ITS own pixels. The output side is
    side_src x (r / src_r) — not ceil(2r), which would quietly rescale the
    content by up to a percent and put the derived handoff constants a couple
    of pixels out.
    """
    h, w = base_u8.shape[:2]
    src_side = crop_rgb01.shape[0]
    side = int(round(src_side * r / float(src_r)))
    x0 = int(round(cx - side / 2.0))
    y0 = int(round(cy - side / 2.0))
    patch = np.array(Image.fromarray(to_u8(crop_rgb01)).resize(
        (side, side), Image.LANCZOS), dtype=np.uint8)

    yy, xx = np.mgrid[0:side, 0:side]
    dx = xx + x0 - cx
    dy = yy + y0 - cy
    dist = np.hypot(dx, dy)

    t = np.clip(dist / r, 0.0, 1.0)
    idx = np.clip((t * (len(shading) - 1)).astype(int), 0, len(shading) - 1)
    vign = shading[idx]

    lin = srgb_to_lin(to_f01(patch)) * vign[..., None]
    shaded = to_u8(lin_to_srgb(lin))

    alpha = np.clip((r - dist) / feather + 0.5, 0.0, 1.0)

    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(w, x0 + side), min(h, y0 + side)
    px0, py0 = sx0 - x0, sy0 - y0
    px1, py1 = px0 + (sx1 - sx0), py0 + (sy1 - sy0)

    out = base_u8.astype(np.float64).copy()
    a = alpha[py0:py1, px0:px1][..., None]
    out[sy0:sy1, sx0:sx1] = (out[sy0:sy1, sx0:sx1] * (1 - a) +
                             shaded[py0:py1, px0:px1] * a)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def circular_crop(img_u8, cx, cy, r):
    """Square crop of side 2r centred on (cx, cy), edge-clamped. -> float 0..1"""
    side = int(round(2 * r))
    x0 = int(round(cx - r))
    y0 = int(round(cy - r))
    h, w = img_u8.shape[:2]
    xs = np.clip(np.arange(x0, x0 + side), 0, w - 1)
    ys = np.clip(np.arange(y0, y0 + side), 0, h - 1)
    return to_f01(img_u8[np.ix_(ys, xs)])


# ==========================================================================
# 0. Load the plates
# ==========================================================================
def main():
    os.makedirs(OPT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)

    for p in (S1_PATH, S2_PATH, OLD_F2, OLD_F3, OLD_F4, OLD_F5):
        if not os.path.exists(p):
            print(f"MISSING INPUT: {p}")
            sys.exit(1)

    s1 = np.asarray(Image.open(S1_PATH).convert("RGB"), dtype=np.uint8)
    s2_img = Image.open(S2_PATH).convert("RGB")
    print("=== inputs ===")
    print(f"S1 hero plate : {s1.shape[1]}x{s1.shape[0]}")
    print(f"S2 page plate : {s2_img.size[0]}x{s2_img.size[1]}")
    if (s1.shape[1], s1.shape[0]) != (W, H):
        anomalies.append(f"S1 is {s1.shape[1]}x{s1.shape[0]}, expected {W}x{H}")
    if s2_img.size[0] != W:
        anomalies.append(f"S2 is {s2_img.size[0]} px wide, expected {W}")

    # ----------------------------------------------------------------------
    # 1. The lens crop — constructed from the lockup box
    # ----------------------------------------------------------------------
    print("\n=== lens crop (constructed) ===")
    old_f5 = np.asarray(Image.open(OLD_F5).convert("RGB"), dtype=np.uint8)
    old_f4 = np.asarray(Image.open(OLD_F4).convert("RGB"), dtype=np.uint8)
    old_f3 = np.asarray(Image.open(OLD_F3).convert("RGB"), dtype=np.uint8)

    f5_lens = measure_disc(old_f5)
    f4_lens = measure_disc(old_f4)
    print(f"frame5 lens disc: {f5_lens}")
    print(f"frame4 bright blob: {f4_lens}  (NOT used — see frame4 below)")
    lens = f5_lens
    lens_d = 2 * lens["r"]

    # how much of the old disc the old lockup filled — the optical proportion
    # the new crop has to reproduce
    yy, xx = np.mgrid[0:H, 0:W]
    inside = ((xx - lens["cx"]) ** 2 + (yy - lens["cy"]) ** 2) < (lens["r"] * 0.93) ** 2
    ink = inside & (old_f5.min(axis=2) < 170)
    iy, ix = np.nonzero(ink)
    old_lockup_w = float(ix.max() - ix.min() + 1)
    old_ratio = old_lockup_w / lens_d
    print(f"old frame5 lockup ink: x {ix.min()}..{ix.max()} y {iy.min()}..{iy.max()} "
          f"w={old_lockup_w:.1f}  w/disc = {old_ratio:.4f}")

    crop_cx = S1_LOCKUP["x"] + S1_LOCKUP["w"] / 2.0
    crop_cy = S1_LOCKUP["y"] + S1_LOCKUP["h"] / 2.0
    crop_r = S1_LOCKUP["w"] / (2.0 * old_ratio)
    print(f"S1 lockup box   : x={S1_LOCKUP['x']:.2f} y={S1_LOCKUP['y']:.2f} "
          f"w={S1_LOCKUP['w']:.2f} h={S1_LOCKUP['h']:.2f}")
    print(f"S1 CROP CIRCLE  : cx={crop_cx:.2f} cy={crop_cy:.2f} r={crop_r:.2f} "
          f"(diameter {2*crop_r:.2f})")
    print(f"  -> crop covers x {crop_cx-crop_r:.1f}..{crop_cx+crop_r:.1f}, "
          f"y {crop_cy-crop_r:.1f}..{crop_cy+crop_r:.1f}")
    if (crop_cx - crop_r < 0 or crop_cx + crop_r > W or
            crop_cy - crop_r < 0 or crop_cy + crop_r > H):
        anomalies.append("S1 crop circle runs outside the plate")

    # the lockup's real ink — not its box corners, which are empty — must clear
    # the disc edge the way the old plate's did
    lx0, ly0 = int(S1_LOCKUP["x"]), int(S1_LOCKUP["y"])
    lx1 = int(S1_LOCKUP["x"] + S1_LOCKUP["w"])
    ly1 = int(S1_LOCKUP["y"] + S1_LOCKUP["h"])
    paper = np.median(s1[ly0:ly1, lx0:lx1].reshape(-1, 3), axis=0)
    box = s1[ly0:ly1, lx0:lx1].astype(np.float64)
    ink = np.abs(box - paper).max(axis=2) > 24
    iyy, ixx = np.nonzero(ink)
    worst = np.hypot(ixx + lx0 - crop_cx, iyy + ly0 - crop_cy).max()
    print(f"  lockup ink: {int(ink.sum())} px, widest point at "
          f"{worst/crop_r:.3f} of the crop radius")
    if worst > crop_r * 0.99:
        anomalies.append("lockup ink reaches the crop edge — raise crop_r")

    # The handoff transform, straight out of the crop arithmetic. The lens
    # content IS this crop scaled to the disc, so the on-frame lockup is
    # S1_LOCKUP scaled by the same factor — no calibration, no eyeballing.
    lockup_cx, lockup_cy = crop_cx, crop_cy       # (the crop is centred on it)
    scale_to_disc = lens_d / (2.0 * crop_r)
    lockup_to_lens = S1_LOCKUP["w"] * scale_to_disc / lens_d
    lockup_x_off = (lockup_cx - crop_cx) * scale_to_disc / lens_d
    lockup_y_off = (lockup_cy - crop_cy) * scale_to_disc / lens_d
    print(f"crop -> disc scale: {scale_to_disc:.4f}")
    print(f"DERIVED  LOCKUP_TO_LENS = {lockup_to_lens:.4f}")
    print(f"DERIVED  LOCKUP_X_OFFSET = {lockup_x_off:.4f}")
    print(f"DERIVED  LOCKUP_Y_OFFSET = {lockup_y_off:.4f}")

    crop = circular_crop(s1, crop_cx, crop_cy, crop_r)

    # ----------------------------------------------------------------------
    # 2. frame1 — the page, printed and defocused
    # ----------------------------------------------------------------------
    print("\n=== frame1: poster + wall ===")
    pw = POSTER_W
    pk = pw / float(s2_img.size[0])
    ph = int(round(s2_img.size[1] * pk))
    poster = np.asarray(s2_img.resize((pw, ph), Image.LANCZOS), dtype=np.uint8)
    # constructed placement: the page's lockup centre lands on the lens centre
    px = int(round(lens["cx"] - pk * (S1_LOCKUP["x"] + S1_LOCKUP["w"] / 2.0)))
    py = int(round(lens["cy"] - pk * (S1_LOCKUP["y"] + S1_LOCKUP["h"] / 2.0)))
    print(f"poster: {pw}x{ph} at ({px}, {py})  scale={pk:.4f}")
    print(f"  lockup centre on the poster: "
          f"({px + pk * (S1_LOCKUP['x'] + S1_LOCKUP['w'] / 2.0):.1f}, "
          f"{py + pk * (S1_LOCKUP['y'] + S1_LOCKUP['h'] / 2.0):.1f})"
          f"  vs lens ({lens['cx']}, {lens['cy']})")
    print(f"  page rows visible: {max(0,-py)/pk:.0f}"
          f" .. {(H-py)/pk:.0f} of {s2_img.size[1]}")

    # wall: the old frame1's gradient shape, re-tinted warm for cream paper
    gy = np.linspace(0.0, 1.0, H)[:, None]
    gx = np.linspace(0.0, 1.0, W)[None, :]
    wall = np.empty((H, W, 3), dtype=np.float64)
    for c in range(3):
        top = WALL_TL[c] + (WALL_TR[c] - WALL_TL[c]) * gx
        bot = WALL_BL[c] + (WALL_BR[c] - WALL_BL[c]) * gx
        wall[..., c] = top + (bot - top) * gy
    # a shallow corner vignette, as in the source photograph
    vy, vx = np.mgrid[0:H, 0:W]
    rad = np.hypot((vx - W / 2) / (W / 2), (vy - H / 2) / (H / 2))
    wall *= (1.0 - 0.030 * np.clip(rad - 0.55, 0, None) / 0.45)[..., None]
    canvas = wall.copy()

    # poster drop shadow (light from upper left, as in the source photograph)
    sh = np.zeros((H, W), dtype=np.float64)
    sy0 = np.clip(py + POSTER_SHADOW["dy"], 0, H)
    sy1 = np.clip(py + ph + POSTER_SHADOW["dy"], 0, H)
    sx0 = np.clip(px + POSTER_SHADOW["dx"], 0, W)
    sx1 = np.clip(px + pw + POSTER_SHADOW["dx"], 0, W)
    sh[sy0:sy1, sx0:sx1] = 1.0
    sh = np.asarray(Image.fromarray(to_u8(sh[..., None].repeat(3, 2))[..., 0])
                    .filter(ImageFilter.GaussianBlur(POSTER_SHADOW["blur"])),
                    dtype=np.float64) / 255.0
    canvas *= (1.0 - POSTER_SHADOW["strength"] * sh)[..., None]

    ty0, ty1 = max(0, py), min(H, py + ph)
    tx0, tx1 = max(0, px), min(W, px + pw)
    canvas[ty0:ty1, tx0:tx1] = poster[ty0 - py:ty1 - py, tx0 - px:tx1 - px]
    frame1_sharp = to_u8(canvas / 255.0)
    Image.fromarray(frame1_sharp).save(os.path.join(WORK, "frame1_sharp.png"))
    print(f"wall tone at the frame edge: {tuple(int(v) for v in frame1_sharp[8, 8])}"
          f" .. {tuple(int(v) for v in frame1_sharp[H-8, W-8])}")

    print(f"disc blur R={FRAME1_BLUR_R} (B channel x{B_BLUR_SCALE})")
    frame1 = to_u8(disc_blur(to_f01(frame1_sharp), FRAME1_BLUR_R))
    Image.fromarray(frame1).save(os.path.join(WORK, "frame1_full.png"))

    # ----------------------------------------------------------------------
    # 3. machine cutout — flood-fill knockout of the old frame2's white wall
    # ----------------------------------------------------------------------
    print("\n=== machine cutout (from the old frame2) ===")
    old_f2 = np.asarray(Image.open(OLD_F2).convert("RGB"), dtype=np.uint8)
    machine = knockout_machine(old_f2, label="f2 ")
    if int(machine.sum()) < 100000:
        anomalies.append("machine component looks too small — check the knockout")

    m_rgb = bleed_colour(old_f2.astype(np.float64), machine, rounds=4)
    m_alpha = feathered_alpha(machine)
    m_rgb_u8 = np.clip(m_rgb, 0, 255).astype(np.uint8)
    m_rgb_u8[m_alpha == 0] = (26, 26, 26)
    cutout = np.dstack([m_rgb_u8, m_alpha])
    cut_path = os.path.join(OPT, "machine_cutout.png")
    Image.fromarray(cutout, mode="RGBA").save(cut_path, "PNG", optimize=True)
    print(f"wrote {cut_path}  {kb(cut_path):.1f} KB")

    # ----------------------------------------------------------------------
    # 4. frame2 — the same defocused page, machine sharp in front of it
    # ----------------------------------------------------------------------
    print("\n=== frame2: machine over the defocused poster ===")
    a = (m_alpha.astype(np.float64) / 255.0)[..., None]
    # contact shadow: the machine hangs in front of the sheet
    msh = np.asarray(Image.fromarray(m_alpha, mode="L").filter(
        ImageFilter.GaussianBlur(26)), dtype=np.float64) / 255.0
    msh = np.roll(msh, 26, axis=0)
    bgf = frame1.astype(np.float64) * (1.0 - 0.16 * msh)[..., None]
    frame2 = np.clip(np.rint(bgf * (1 - a) + m_rgb_u8.astype(np.float64) * a),
                     0, 255).astype(np.uint8)
    Image.fromarray(frame2).save(os.path.join(WORK, "frame2_full.png"))

    # ----------------------------------------------------------------------
    # 5. frame3 — the page inside the far lens
    # ----------------------------------------------------------------------
    print("\n=== frame3: right-lens disc ===")

    # (a) The old plate's own background is the OLD brand — a white page in the
    #     old typeface, legible enough at this defocus to contradict everything
    #     the click resolves to. Replace it: the machine is knocked out, and
    #     behind it goes OUR hero plate, printed at the scale the old page was
    #     printed (both pages' Book Appointment buttons measured at half-max)
    #     and thrown out of focus by the same amount.
    m3 = knockout_machine(old_f3, near_white_min=210, tol=18, label="f3 ")
    bg3 = ~m3
    old_btn = teal_blob(old_f3, window=(0, 1100, W, 1450))
    k3 = old_btn["w"] / S1_CTA["w"]
    s1_btn_c = (S1_CTA["x"] + S1_CTA["w"] / 2.0, S1_CTA["y"] + S1_CTA["h"] / 2.0)
    print(f"  old page button (half-max): w={old_btn['w']:.0f} h={old_btn['h']:.0f} "
          f"centre ({old_btn['cx']:.0f}, {old_btn['cy']:.0f})")
    print(f"  our button: w={S1_CTA['w']:.1f} h={S1_CTA['h']:.1f} -> "
          f"background print scale k={k3:.3f}")
    plate3, ox3, oy3 = place_plate(s1, k3, s1_btn_c,
                                   (old_btn["cx"], old_btn["cy"]), W, H)
    print(f"  our page printed at ({ox3:.0f}, {oy3:.0f}), "
          f"{int(round(W*k3))}x{int(round(H*k3))} px — covers the frame")
    if ox3 > 0 or oy3 > 0 or ox3 + W * k3 < W or oy3 + H * k3 < H:
        anomalies.append("frame3's replacement page does not cover the frame")

    # the old plate's own lighting, as a low-frequency multiplier: a normalised
    # convolution over the background only, so the machine's hole is filled by
    # extrapolation and its cast shadow survives onto the new sheet
    lum3 = old_f3.mean(axis=2)
    kn = bg3.astype(np.float64)
    num = gauss_u8(lum3 * kn, 90)
    den = gauss_u8(kn * 255.0, 90)
    shade3 = num / np.maximum(den / 255.0, 1e-3) / 255.0
    shade3 = shade3 / np.median(shade3[bg3])
    shade3 = np.clip(shade3, 0.70, 1.10)
    print(f"  plate lighting: {shade3.min():.3f} .. {shade3.max():.3f} "
          f"(median 1.000)")

    bg_new = disc_blur(to_f01(plate3), FRAME3_BG_BLUR_R)
    bg_new = to_u8(lin_to_srgb(srgb_to_lin(bg_new) * shade3[..., None]))

    m3_rgb = np.clip(bleed_colour(old_f3.astype(np.float64), m3, rounds=4),
                     0, 255).astype(np.uint8)
    a3 = (feathered_alpha(m3).astype(np.float64) / 255.0)[..., None]
    frame3 = np.clip(np.rint(bg_new * (1 - a3) + m3_rgb * a3),
                     0, 255).astype(np.uint8)

    # (b) …then our hero goes into the right lens, sharp.
    f3_disc = measure_disc(old_f3, window=(620, 540, 1010, 960))
    print(f"frame3 right lens: {f3_disc}")
    if f3_disc is None:
        anomalies.append("frame3's right lens disc was not found")
    else:
        sh3 = radial_shading(old_f3, f3_disc["cx"], f3_disc["cy"], f3_disc["r"])
        print(f"  frame3 shading: centre {sh3[0]:.3f} .. edge {sh3[-1]:.3f}")
        frame3 = paste_disc(frame3, crop, f3_disc["cx"], f3_disc["cy"],
                            f3_disc["r"], sh3, crop_r)
    Image.fromarray(frame3).save(os.path.join(WORK, "frame3_full.png"))

    # ----------------------------------------------------------------------
    # 6. frame4 / frame5 — the page inside the near lens
    # ----------------------------------------------------------------------
    print("\n=== frame4 / frame5: main lens disc ===")
    sh5 = radial_shading(old_f5, lens["cx"], lens["cy"], lens["r"])
    print(f"  frame5 shading: centre {sh5[0]:.3f} .. 0.9R {sh5[int(len(sh5)*0.9)]:.3f}"
          f" .. edge {sh5[-1]:.3f}")
    frame5 = paste_disc(old_f5, crop, lens["cx"], lens["cy"], lens["r"], sh5,
                        crop_r)
    Image.fromarray(frame5).save(os.path.join(WORK, "frame5_full.png"))

    print(f"  frame4 crop blur R={FRAME4_BLUR_R_S1} in S1 space "
          f"(= {FRAME4_BLUR_R_S1 * scale_to_disc:.1f} px on the disc)")
    crop_blurred = disc_blur(crop, FRAME4_BLUR_R_S1)
    # frame4 is the SAME housing photograph as frame5 (verified: outside the
    # disc the two plates differ by a mean of 1.6/255). Its own bright blob
    # measures small and off-centre — the old defocused content dims the disc's
    # lower edge below the threshold — so frame4 takes frame5's disc geometry
    # and frame5's shading. The click is then a pure change of focus: nothing
    # moves, nothing re-lights, the page just snaps sharp.
    frame4 = paste_disc(old_f4, crop_blurred, lens["cx"], lens["cy"],
                        lens["r"], sh5, crop_r)
    Image.fromarray(frame4).save(os.path.join(WORK, "frame4_full.png"))

    # ----------------------------------------------------------------------
    # 7. measurements
    # ----------------------------------------------------------------------
    print("\n=== measurements ===")
    with open(os.path.join(TOOLS, "measurements.json")) as fh:
        prev = json.load(fh)

    # The page's own teal, straight off the plate's Book Appointment button.
    # Median, not mean: the button carries white type, and a mean of button +
    # type is a colour that appears nowhere on the page.
    btn = s1[int(S1_CTA["y"] + 4):int(S1_CTA["y"] + S1_CTA["h"] - 4),
             int(S1_CTA["x"] + 4):int(S1_CTA["x"] + S1_CTA["w"] - 4)]
    teal_rgb = np.median(btn.reshape(-1, 3), axis=0)
    teal_hex = "#%02x%02x%02x" % tuple(int(round(v)) for v in teal_rgb)
    print(f"teal sampled from the S1 button: {teal_hex}")

    measurements = {
        "image": {"w": W, "h": H},
        "rim_hole": prev["rim_hole"],
        "frame5_lens": lens,
        "teal_hex": teal_hex,
        "s1_crop": {"cx": round(crop_cx, 2), "cy": round(crop_cy, 2),
                    "r": round(crop_r, 2)},
        "s1_lockup": {"x": round(S1_LOCKUP["x"], 2), "y": round(S1_LOCKUP["y"], 2),
                      "w": round(S1_LOCKUP["w"], 2), "h": round(S1_LOCKUP["h"], 2)},
    }
    for p in (os.path.join(TOOLS, "measurements.json"),
              os.path.join(OPT, "measurements.json")):
        with open(p, "w") as fh:
            json.dump(measurements, fh, indent=2)
            fh.write("\n")
        print(f"wrote {p}")

    # ----------------------------------------------------------------------
    # 8. encode + size table
    # ----------------------------------------------------------------------
    print("\n=== encode ===")
    outs = [("frame1.webp", frame1), ("frame2.webp", frame2),
            ("frame3.webp", frame3), ("frame4.webp", frame4),
            ("frame5.webp", frame5)]
    total = 0.0
    rows = []
    for name, arr in outs:
        p = os.path.join(OPT, name)
        Image.fromarray(arr).save(p, "WEBP", quality=WEBP_Q, method=WEBP_METHOD)
        rows.append((name, kb(p)))
        total += kb(p)

    extra = [("rim_overlay.webp", os.path.join(OPT, "rim_overlay.webp"))]
    fonts = os.path.join(ASSETS, "fonts")
    for f in ("fraunces-var.woff2", "public-sans-var.woff2",
              "plex-mono-400.woff2", "plex-mono-500.woff2"):
        extra.append((f, os.path.join(fonts, f)))

    print(f"{'asset':<24}{'KB':>10}")
    print("-" * 34)
    for name, k in rows:
        print(f"{name:<24}{k:>10.1f}")
    for name, p in extra:
        k = kb(p) if os.path.exists(p) else 0.0
        total += k
        print(f"{name:<24}{k:>10.1f}")
    print("-" * 34)
    print(f"{'INTRO PAYLOAD':<24}{total:>10.1f} KB  ({total/1024.0:.2f} MB)")
    if total > 4096:
        anomalies.append(f"intro payload {total/1024.0:.2f} MB exceeds the 4 MB budget")

    print("\n=== ENGINE CONSTANTS (paste into js/main.js) ===")
    print(f"  LOCKUP_TO_LENS  = {lockup_to_lens:.4f}")
    print(f"  LOCKUP_X_OFFSET = {lockup_x_off:.4f}")
    print(f"  LOCKUP_Y_OFFSET = {lockup_y_off:.4f}")
    print(f"  frame5_lens     = cx {lens['cx']}, cy {lens['cy']}, r {lens['r']}")
    print(f"  s1_crop         = cx {crop_cx:.2f}, cy {crop_cy:.2f}, r {crop_r:.2f}")

    print("\nANOMALIES:", json.dumps(anomalies, indent=2) if anomalies else "none")


if __name__ == "__main__":
    main()
