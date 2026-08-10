"""Still A for the POV exam-screen video: the real hero plate, super disc-blurred,
with a soft dark vignette (dim exam room at the edges of vision).
Reuses compose_frames.py's linear-light disc blur.
Usage: tools/.venv/bin/python tools/make_still_a.py [blur_radius]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from compose_frames import disc_blur, to_f01, to_u8

ROOT = Path(__file__).resolve().parent.parent
RADIUS = float(sys.argv[1]) if len(sys.argv) > 1 else 42.0

plate = Image.open(ROOT / "shots/hero_1024x1536.png").convert("RGB")
rgb = to_f01(np.asarray(plate))

blurred = disc_blur(rgb, RADIUS)

# soft vignette: elliptical falloff toward the frame edges (dim room at the
# periphery of a patient's view), gentle enough that the cream still reads
h, w = blurred.shape[:2]
yy, xx = np.mgrid[0:h, 0:w]
nx = (xx - w / 2) / (w / 2)
ny = (yy - h / 2) / (h / 2)
d = np.sqrt(nx**2 + ny**2)
vig = 1.0 - 0.38 * np.clip((d - 0.62) / 0.75, 0, 1) ** 1.8
out = blurred * vig[..., None]

img = Image.fromarray(to_u8(out))
img.save(ROOT / "shots/still_a_blur.png", optimize=True)
img.save(ROOT / "shots/still_a_blur.webp", quality=92, method=6)
print(f"radius={RADIUS} -> shots/still_a_blur.png / .webp ({w}x{h})")
