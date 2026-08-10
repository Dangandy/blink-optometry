"""Knock out the modern phoropter aperture ring for the porthole overlay.

Floods near-white regions reachable from the image border (studio background)
and from the image centre (the aperture opening) to transparency, feathers the
boundary, and measures the hole circle. Also builds the clip-1 end composite
(ring over the -10 wash) for video generation.

Usage: tools/.venv/bin/python tools/make_ring.py
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).parent))
from compose_frames import (bbox_circle, feathered_alpha, fill_holes,
                            scanline_fill)

ROOT = Path(__file__).resolve().parent.parent
NEAR_WHITE_MIN = 236
NEAR_WHITE_TOL = 14

src = Image.open(ROOT / "assets/phoropter_ring_raw.png").convert("RGB")
w, h = src.size
rgb = np.asarray(src)

mn = rgb.min(axis=2).astype(np.int16)
mx = rgb.max(axis=2).astype(np.int16)
near_white = (mn >= NEAR_WHITE_MIN) & ((mx - mn) <= NEAR_WHITE_TOL)

ba = bytearray(near_white.astype(np.uint8).ravel().tobytes())
visited = bytearray(w * h)

# background: near-white reachable from the border
border = []
for x in range(w):
    border += [(x, 0), (x, h - 1)]
for y in range(h):
    border += [(0, y), (w - 1, y)]
scanline_fill(ba, visited, w, h, [s for s in border if near_white[s[1], s[0]]], 1)

# hole: near-white reachable from the centre, tracked separately
visited2 = bytearray(w * h)
ba2 = bytearray((near_white & ~(np.frombuffer(bytes(visited), dtype=np.uint8)
                                .reshape(h, w) != 0)).astype(np.uint8).ravel().tobytes())
cx0, cy0 = w // 2, h // 2
assert near_white[cy0, cx0], "image centre is not near-white — aperture not centred?"
n, hx0, hy0, hx1, hy1 = scanline_fill(ba2, visited2, w, h, [(cx0, cy0)], 1)
hole = np.frombuffer(bytes(visited2), dtype=np.uint8).reshape(h, w) != 0
hole_geom = bbox_circle(hx0, hy0, hx1, hy1)

bg = np.frombuffer(bytes(visited), dtype=np.uint8).reshape(h, w) != 0
opaque = fill_holes(~(bg | hole)) & ~hole
alpha = feathered_alpha(opaque, feather=1.0)

# premultiply hygiene: neutral grey under transparent pixels
out_rgb = rgb.copy()
out_rgb[alpha == 0] = (70, 70, 72)
ring = np.dstack([out_rgb, alpha])
Image.fromarray(ring, "RGBA").save(ROOT / "assets/opt/phoropter_ring.png", optimize=True)
Image.fromarray(ring, "RGBA").save(ROOT / "assets/opt/phoropter_ring.webp",
                                   quality=90, method=6, lossless=False)

# clip-1 end composite: ring over the -10 wash at identity position
wash = Image.open(ROOT / "shots/still_a_blur.png").convert("RGB")
comp = wash.copy()
comp.paste(Image.fromarray(out_rgb), (0, 0), Image.fromarray(alpha, "L"))
comp.save(ROOT / "shots/clip1_end.png", optimize=True)

geom = {"ring_hole": hole_geom,
        "opaque_bbox": [int(v) for v in np.argwhere(opaque)[:, ::-1].min(0).tolist() +
                        np.argwhere(opaque)[:, ::-1].max(0).tolist()]}
(ROOT / "tools/ring_geometry.json").write_text(json.dumps(geom, indent=2))
kb = lambda p: f"{p.stat().st_size / 1024:.1f} KB"
print(json.dumps(geom, indent=2))
print("ring png:", kb(ROOT / "assets/opt/phoropter_ring.png"),
      "| webp:", kb(ROOT / "assets/opt/phoropter_ring.webp"),
      "| clip1_end:", kb(ROOT / "shots/clip1_end.png"))
