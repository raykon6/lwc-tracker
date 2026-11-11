"""crop.py SRC ASPECT OUT [anchor]: crop SRC to width/height = ASPECT, anchored top (or center)."""
import sys
from PIL import Image
src, aspect, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
anchor = sys.argv[4] if len(sys.argv) > 4 else "top"
im = Image.open(src).convert("RGB")
w, h = im.size
if w / h > aspect:          # too wide: trim sides
    nw = round(h * aspect); x = (w - nw) // 2 if anchor != "left" else 0
    im = im.crop((x, 0, x + nw, h))
else:                       # too tall: trim bottom (top anchor) or both
    nh = round(w / aspect); y = 0 if anchor in ("top", "left") else (h - nh) // 2
    im = im.crop((0, y, w, y + nh))
im.save(out, optimize=True)
