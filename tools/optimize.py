#!/usr/bin/env python3
"""
optimize.py -- convert the five intro frame PNGs to WebP.

quality 80, method 6, 1024x1536 preserved. Any output over 600 KB is
re-encoded at quality 72. Prints a before/after table.
"""

import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
OPT = os.path.join(ASSETS, "opt")

FRAMES = [
    ("frame1_page_blurred.png", "frame1.webp"),
    ("frame2_descend_end.png", "frame2.webp"),
    ("frame3_pushin_start.png", "frame3.webp"),
    ("frame4_lens_blurred.png", "frame4.webp"),
    ("frame5_lens_sharp.png", "frame5.webp"),
]

MAX_KB = 600
Q_HI = 80
Q_LO = 72


def kb(path):
    return os.path.getsize(path) / 1024.0


def main():
    os.makedirs(OPT, exist_ok=True)
    rows = []
    total_before = 0.0
    total_after = 0.0

    for src_name, dst_name in FRAMES:
        src = os.path.join(ASSETS, src_name)
        dst = os.path.join(OPT, dst_name)
        before = kb(src)

        im = Image.open(src).convert("RGB")
        w, h = im.size
        q = Q_HI
        im.save(dst, "WEBP", quality=q, method=6)
        after = kb(dst)
        note = ""
        if after > MAX_KB:
            q = Q_LO
            im.save(dst, "WEBP", quality=q, method=6)
            after = kb(dst)
            note = f"re-encoded @q{Q_LO}"
        rows.append((src_name, dst_name, f"{w}x{h}", before, after, q, note))
        total_before += before
        total_after += after

    hdr = (f"{'source':<26} {'output':<14} {'dims':<10} "
           f"{'before KB':>10} {'after KB':>9} {'q':>3} {'saved':>7}  note")
    print(hdr)
    print("-" * len(hdr))
    for src_name, dst_name, dims, before, after, q, note in rows:
        saved = 100.0 * (1.0 - after / before)
        print(f"{src_name:<26} {dst_name:<14} {dims:<10} "
              f"{before:>10.1f} {after:>9.1f} {q:>3} {saved:>6.1f}%  {note}")
    print("-" * len(hdr))
    print(f"{'TOTAL':<26} {'':<14} {'':<10} "
          f"{total_before:>10.1f} {total_after:>9.1f}")
    print(f"\nTotal WebP size: {total_after:.1f} KB "
          f"({total_after / 1024.0:.2f} MB) from {total_before:.1f} KB PNG "
          f"({100.0 * (1.0 - total_after / total_before):.1f}% smaller)")
    over = [r for r in rows if r[4] > MAX_KB]
    if over:
        print("WARNING: still over 600 KB after re-encode: "
              + ", ".join(r[1] for r in over))
    else:
        print("All frames under the 600 KB per-file cap.")


if __name__ == "__main__":
    main()
