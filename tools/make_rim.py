#!/usr/bin/env python3
"""
make_rim.py

1. Knocks the white background AND the white center hole out of
   assets/rim_raw.png -> a ring-shaped RGBA overlay with soft edges.
   Writes assets/opt/rim_overlay.png and assets/opt/rim_overlay.webp.

2. Measures geometry/colour and writes tools/measurements.json plus an
   identical copy at assets/opt/measurements.json.

All coordinates are in source-image pixel space (1024 x 1536).
"""

import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OPT = os.path.join(ASSETS, "opt")
TOOLS = os.path.join(ROOT, "tools")

RIM_SRC = os.path.join(ASSETS, "rim_raw.png")
FRAME5_SRC = os.path.join(ASSETS, "frame5_lens_sharp.png")

NEUTRAL_DARK = (26, 26, 26)  # premultiply hygiene for fully-transparent px

anomalies = []


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def shift2(a, dy, dx, fill=0):
    """out[y, x] = a[y - dy, x - dx], zero/False padded."""
    out = np.full_like(a, fill)
    h, w = a.shape[0], a.shape[1]
    ys_dst = slice(max(0, dy), h - max(0, -dy))
    ys_src = slice(max(0, -dy), h - max(0, dy))
    xs_dst = slice(max(0, dx), w - max(0, -dx))
    xs_src = slice(max(0, -dx), w - max(0, dx))
    out[ys_dst, xs_dst] = a[ys_src, xs_src]
    return out


def scanline_fill(mask, visited, w, h, seeds, mark):
    """
    4-connected scanline flood fill over a flat bytearray `mask`
    (1 == fillable). Marks `visited[i] = mark` for every filled pixel.
    Pixels already visited (any nonzero mark) are treated as walls, so
    separately-seeded components stay separate.

    Returns (count, x0, y0, x1, y1) -- bbox inclusive, or (0, ...) if empty.
    """
    stack = [s for s in seeds]
    count = 0
    x0, y0, x1, y1 = w, h, -1, -1
    while stack:
        x, y = stack.pop()
        base = y * w
        if not mask[base + x] or visited[base + x]:
            continue
        # walk left
        xl = x
        while xl >= 0 and mask[base + xl] and not visited[base + xl]:
            xl -= 1
        xl += 1
        # walk right
        xr = x
        while xr < w and mask[base + xr] and not visited[base + xr]:
            xr += 1
        xr -= 1
        for i in range(base + xl, base + xr + 1):
            visited[i] = mark
        count += xr - xl + 1
        if xl < x0:
            x0 = xl
        if xr > x1:
            x1 = xr
        if y < y0:
            y0 = y
        if y > y1:
            y1 = y
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
    """
    Largest 4-connected component of a 2D bool array.
    Returns (count, x0, y0, x1, y1, visited_bytearray, label_of_largest).
    """
    h, w = mask_bool.shape
    mask = bytearray(mask_bool.astype(np.uint8).ravel().tobytes())
    visited = bytearray(w * h)
    best = (0, 0, 0, 0, 0)
    best_label = 0
    label = 0
    for y in range(h):
        base = y * w
        row = mask[base:base + w]
        if 1 not in row:
            continue
        for x in range(w):
            if mask[base + x] and not visited[base + x]:
                label = 1 if label == 0 else (label % 254) + 1
                stats = scanline_fill(mask, visited, w, h, [(x, y)], label)
                if stats[0] > best[0]:
                    best = stats
                    best_label = label
    return best, visited, best_label


def bbox_circle(x0, y0, x1, y1):
    bw = x1 - x0 + 1
    bh = y1 - y0 + 1
    return {
        "cx": round(x0 + bw / 2.0, 1),
        "cy": round(y0 + bh / 2.0, 1),
        "r": round((bw / 2.0 + bh / 2.0) / 2.0, 1),
        "bbox": [int(x0), int(y0), int(x1), int(y1)],
    }


def kb(path):
    return os.path.getsize(path) / 1024.0


# --------------------------------------------------------------------------
# 1. rim knockout
# --------------------------------------------------------------------------
print("=== rim_raw.png -> rim_overlay ===")
rim_img = Image.open(RIM_SRC).convert("RGB")
W, H = rim_img.size
print(f"source: {W}x{H}")
rgb = np.asarray(rim_img, dtype=np.uint8)

mn = rgb.min(axis=2).astype(np.int16)
mx = rgb.max(axis=2).astype(np.int16)
near_white = (mn >= 240) & ((mx - mn) <= 12)
print(f"near-white pixels: {int(near_white.sum())} "
      f"({100.0 * near_white.sum() / (W * H):.1f}%)")

mask_ba = bytearray(near_white.astype(np.uint8).ravel().tobytes())
visited = bytearray(W * H)

# (a) seeds: every near-white pixel on the four image edges
edge_seeds = []
for x in range(W):
    if near_white[0, x]:
        edge_seeds.append((x, 0))
    if near_white[H - 1, x]:
        edge_seeds.append((x, H - 1))
for y in range(H):
    if near_white[y, 0]:
        edge_seeds.append((0, y))
    if near_white[y, W - 1]:
        edge_seeds.append((W - 1, y))
print(f"edge seeds: {len(edge_seeds)}")
if not edge_seeds:
    anomalies.append("no near-white pixels on image border - background may "
                     "not be white")

LABEL_EDGE, LABEL_CENTER = 1, 2
edge_stats = scanline_fill(mask_ba, visited, W, H, edge_seeds, LABEL_EDGE)
print(f"edge component: {edge_stats[0]} px  bbox={edge_stats[1:]}")

# (b) seeds: the image-centre region
CX0, CY0 = W // 2, H // 2  # (512, 768)
center_seeds = []
for dy in range(-16, 17, 4):
    for dx in range(-16, 17, 4):
        sx, sy = CX0 + dx, CY0 + dy
        if 0 <= sx < W and 0 <= sy < H and near_white[sy, sx]:
            center_seeds.append((sx, sy))
if not near_white[CY0, CX0]:
    anomalies.append(f"image centre pixel ({CX0},{CY0}) is not near-white "
                     f"(rgb={tuple(int(v) for v in rgb[CY0, CX0])})")
if visited[CY0 * W + CX0] == LABEL_EDGE:
    anomalies.append("centre hole is connected to the outer background "
                     "(rim has a gap) - rim_hole could not be isolated")
print(f"centre seeds: {len(center_seeds)}")

center_stats = scanline_fill(mask_ba, visited, W, H, center_seeds,
                             LABEL_CENTER)
print(f"centre component: {center_stats[0]} px  bbox={center_stats[1:]}")

labels = np.frombuffer(bytes(visited), dtype=np.uint8).reshape(H, W)
filled = labels != 0
opaque = ~filled
print(f"filled (transparent) px: {int(filled.sum())}  "
      f"opaque px: {int(opaque.sum())}")

# --- bleed rim colour outward so blurred edges never sample white -------
rgbf = rgb.astype(np.float32)
known = opaque.copy()
OFFS = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
for _ in range(3):
    ksum = np.zeros_like(rgbf)
    kcnt = np.zeros((H, W), np.float32)
    kf = known.astype(np.float32)
    masked = rgbf * kf[..., None]
    for dy, dx in OFFS:
        ksum += shift2(masked, dy, dx, 0.0)
        kcnt += shift2(kf, dy, dx, 0.0)
    newly = (~known) & (kcnt > 0)
    if not newly.any():
        break
    rgbf[newly] = ksum[newly] / kcnt[newly][:, None]
    known |= newly
out_rgb = np.clip(rgbf, 0, 255).astype(np.uint8)

# --- alpha: shave 1px at the boundary, then soften ----------------------
adj_trans = (shift2(filled, 1, 0) | shift2(filled, -1, 0) |
             shift2(filled, 0, 1) | shift2(filled, 0, -1))
boundary = opaque & adj_trans
alpha = np.where(opaque, 255, 0).astype(np.uint8)
alpha[boundary] = 102  # ~40%
print(f"boundary px shaved to 40%: {int(boundary.sum())}")

alpha_img = Image.fromarray(alpha, mode="L").filter(
    ImageFilter.GaussianBlur(radius=1.0))
alpha = np.asarray(alpha_img, dtype=np.uint8)

# premultiply hygiene: fully transparent pixels get a neutral dark grey
fully_clear = alpha == 0
out_rgb[fully_clear] = NEUTRAL_DARK
print(f"fully-transparent px recoloured to {NEUTRAL_DARK}: "
      f"{int(fully_clear.sum())}")

out = np.dstack([out_rgb, alpha])
overlay = Image.fromarray(out, mode="RGBA")

os.makedirs(OPT, exist_ok=True)
png_path = os.path.join(OPT, "rim_overlay.png")
webp_path = os.path.join(OPT, "rim_overlay.webp")
overlay.save(png_path, "PNG", optimize=True)
overlay.save(webp_path, "WEBP", quality=90, method=6, lossless=False)
print(f"wrote {png_path}  {kb(png_path):.1f} KB")
print(f"wrote {webp_path}  {kb(webp_path):.1f} KB")

# --------------------------------------------------------------------------
# 2. measurements
# --------------------------------------------------------------------------
print("\n=== measurements ===")
if center_stats[0] == 0:
    anomalies.append("centre flood fill produced 0 pixels - rim_hole is "
                     "degenerate")
    rim_hole = {"cx": 0, "cy": 0, "r": 0, "bbox": [0, 0, 0, 0]}
else:
    rim_hole = bbox_circle(*center_stats[1:])
print("rim_hole:", rim_hole)

# --- frame5 lens ---------------------------------------------------------
f5 = Image.open(FRAME5_SRC).convert("RGB")
f5w, f5h = f5.size
f5arr = np.asarray(f5, dtype=np.uint8)
bright = f5arr.min(axis=2) > 200
print(f"frame5 bright px: {int(bright.sum())} "
      f"({100.0 * bright.sum() / (f5w * f5h):.1f}%)")
best, _, _ = largest_component(bright)
if best[0] == 0:
    anomalies.append("no bright component found in frame5")
    frame5_lens = {"cx": 0, "cy": 0, "r": 0, "bbox": [0, 0, 0, 0]}
else:
    frame5_lens = bbox_circle(*best[1:])
print(f"frame5 largest bright component: {best[0]} px")
print("frame5_lens:", frame5_lens)

# --- teal button ---------------------------------------------------------
a = f5arr.astype(np.float32) / 255.0
r_, g_, b_ = a[..., 0], a[..., 1], a[..., 2]
cmax = a.max(axis=2)
cmin = a.min(axis=2)
delta = cmax - cmin
safe = np.where(delta == 0, 1.0, delta)
hue = np.zeros_like(cmax)
m_r = (cmax == r_) & (delta > 0)
m_g = (cmax == g_) & (delta > 0) & ~m_r
m_b = (cmax == b_) & (delta > 0) & ~m_r & ~m_g
hue[m_r] = (60.0 * (((g_ - b_) / safe)[m_r] % 6.0))
hue[m_g] = (60.0 * (((b_ - r_) / safe)[m_g] + 2.0))
hue[m_b] = (60.0 * (((r_ - g_) / safe)[m_b] + 4.0))
sat = np.where(cmax > 0, delta / np.maximum(cmax, 1e-9), 0.0)
val = cmax

teal_mask = ((hue >= 170.0) & (hue <= 200.0) & (sat > 0.35) &
             (val >= 0.25) & (val <= 0.85))
print(f"teal candidate px: {int(teal_mask.sum())}")
tbest, tvisited, tlabel = largest_component(teal_mask)
if tbest[0] == 0:
    anomalies.append("no teal component matched the HSV window in frame5")
    teal_hex = "#000000"
else:
    tlab = np.frombuffer(bytes(tvisited), dtype=np.uint8).reshape(f5h, f5w)
    sel = tlab == tlabel
    mean_rgb = f5arr[sel].mean(axis=0)
    teal_hex = "#%02x%02x%02x" % tuple(int(round(v)) for v in mean_rgb)
    print(f"teal component: {tbest[0]} px  bbox={tbest[1:]}  "
          f"mean_rgb={tuple(round(float(v), 1) for v in mean_rgb)}")
print("teal_hex:", teal_hex)

measurements = {
    "image": {"w": W, "h": H},
    "rim_hole": rim_hole,
    "frame5_lens": frame5_lens,
    "teal_hex": teal_hex,
}

for p in (os.path.join(TOOLS, "measurements.json"),
          os.path.join(OPT, "measurements.json")):
    with open(p, "w") as fh:
        json.dump(measurements, fh, indent=2)
        fh.write("\n")
    print(f"wrote {p}")

# --------------------------------------------------------------------------
# 3. sanity
# --------------------------------------------------------------------------
print("\n=== sanity ===")


def check_circle(name, c, iw, ih):
    if c["r"] < 150:
        anomalies.append(f"{name}: radius {c['r']} < 150 px (degenerate)")
    x0, y0, x1, y1 = c["bbox"]
    corners = ((0, 0), (iw - 1, 0), (0, ih - 1), (iw - 1, ih - 1))
    touching = [cn for cn in corners
                if x0 <= cn[0] <= x1 and y0 <= cn[1] <= y1]
    if touching:
        anomalies.append(f"{name}: bbox touches image corner(s) {touching}")
    off_x = abs(c["cx"] - iw / 2.0) / iw
    off_y = abs(c["cy"] - ih / 2.0) / ih
    if off_x > 0.15 or off_y > 0.15:
        anomalies.append(
            f"{name}: centre ({c['cx']},{c['cy']}) is off-centre by "
            f"{off_x * 100:.0f}%/{off_y * 100:.0f}% of image w/h")
    print(f"{name}: r={c['r']} centre=({c['cx']},{c['cy']}) bbox={c['bbox']}")


check_circle("rim_hole", rim_hole, W, H)
check_circle("frame5_lens", frame5_lens, f5w, f5h)

tr, tg, tb = (int(teal_hex[1:3], 16), int(teal_hex[3:5], 16),
              int(teal_hex[5:7], 16))
if not (tb > tr and tg > tr):
    anomalies.append(f"teal_hex {teal_hex} is not a greenish-blue "
                     f"(r={tr} g={tg} b={tb})")
if max(tr, tg, tb) - min(tr, tg, tb) < 25:
    anomalies.append(f"teal_hex {teal_hex} is near-grey (low chroma)")
print(f"teal_hex {teal_hex} -> r={tr} g={tg} b={tb}")

print("\nANOMALIES:", json.dumps(anomalies, indent=2) if anomalies else "none")
print("\nRIM SIZES: png=%.1f KB  webp=%.1f KB" % (kb(png_path), kb(webp_path)))
print(json.dumps(measurements, indent=2))
sys.exit(0)
