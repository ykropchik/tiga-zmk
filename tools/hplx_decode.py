#!/usr/bin/env python3
"""
Decode HPLX resource containers from the Zoom75 TIGA display module into PNG.

Handles both span encodings (plain RGB565 and RGB565 + alpha) and both run types
(animation runs, which are delta-coded, and sprite runs, which are independent).
Output is RGBA so transparency survives.

Requires:  pip install pillow

Usage:
    python hplx_decode.py images                 decode ./images into ./images_png
    python hplx_decode.py images --out png       choose the output directory
    python hplx_decode.py images --sheet         also build a contact sheet
    python hplx_decode.py images --report        print the run analysis and exit

Input files are expected to be named hplx_<index>_<w>x<h>.bin, as produced by
hplx_grab.py — the index determines chain order, which matters for delta frames.
"""

import argparse
import os
import re
import struct
import sys

from PIL import Image

MAGIC = b"HPLX"
ANIM_COVERAGE = 0.9      # a run whose first container covers this much is an animation


def parse(data: bytes):
    """Return (width, height, rows, coverage).

    rows is a list per scanline of (x_start, byte_len_signed, payload).
    coverage is the fraction of the container's area touched by its spans.
    """
    if data[:4] != MAGIC:
        raise ValueError("not an HPLX container")

    w = struct.unpack_from("<I", data, 0x08)[0]
    h = struct.unpack_from("<I", data, 0x0C)[0]
    tbl = struct.unpack_from("<I", data, 0x20)[0]
    dat = struct.unpack_from("<I", data, 0x24)[0]

    rows = []
    covered = 0

    for y in range(h):
        off, size = struct.unpack_from("<II", data, tbl + y * 8)
        p = dat + off
        end = min(p + size, len(data))
        spans = []
        while p + 8 <= end:
            x = struct.unpack_from("<I", data, p)[0]
            blen = struct.unpack_from("<i", data, p + 4)[0]   # signed
            p += 8
            n = (blen & 0x7FFFFFFF) if blen < 0 else blen
            if n == 0 or p + n > len(data):
                break
            covered += n // 3 if blen < 0 else n // 2
            spans.append((x, blen, data[p:p + n]))
            p += n
        rows.append(spans)

    return w, h, rows, covered / (w * h) if w and h else 0.0


def rgb565(v: int):
    return (((v >> 11) & 0x1F) * 255 // 31,
            ((v >> 5) & 0x3F) * 255 // 63,
            (v & 0x1F) * 255 // 31)


def paint(canvas: Image.Image, w: int, h: int, rows) -> None:
    px = canvas.load()
    for y, spans in enumerate(rows):
        if y >= h:
            break
        for x0, blen, blob in spans:
            if blen < 0:
                # 3 bytes per pixel: RGB565 little-endian plus an 8-bit alpha
                for i in range(len(blob) // 3):
                    v = struct.unpack_from("<H", blob, i * 3)[0]
                    a = blob[i * 3 + 2]
                    x = x0 + i
                    if 0 <= x < w:
                        r, g, b = rgb565(v)
                        px[x, y] = (r, g, b, a)
            else:
                # 2 bytes per pixel, fully opaque
                for i in range(len(blob) // 2):
                    v = struct.unpack_from("<H", blob, i * 2)[0]
                    x = x0 + i
                    if 0 <= x < w:
                        r, g, b = rgb565(v)
                        px[x, y] = (r, g, b, 255)


def collect(src: str):
    """Return [(index, filename)] ordered by chain index."""
    out = []
    for f in os.listdir(src):
        m = re.match(r"hplx_(\d+)_\d+x\d+\.bin$", f)
        if m:
            out.append((int(m.group(1)), f))
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="directory of .bin containers")
    ap.add_argument("--out", help="output directory (default: <src>_png)")
    ap.add_argument("--sheet", action="store_true",
                    help="also write overview.png with one tile per run")
    ap.add_argument("--report", action="store_true",
                    help="print the run analysis and exit without writing PNGs")
    args = ap.parse_args()

    files = collect(args.src)
    if not files:
        sys.exit(f"no hplx_*.bin files in {args.src}")

    dst = args.out or (args.src.rstrip("/\\") + "_png")
    if not args.report:
        os.makedirs(dst, exist_ok=True)

    # pass 1 — parse everything, group into runs by size
    parsed = {}
    for idx, f in files:
        parsed[idx] = parse(open(os.path.join(args.src, f), "rb").read())

    runs = []
    prev = None
    for idx, _ in files:
        w, h, _, _ = parsed[idx]
        if prev != (w, h):
            runs.append({"start": idx, "size": (w, h), "members": [idx]})
            prev = (w, h)
        else:
            runs[-1]["members"].append(idx)

    for run in runs:
        run["animation"] = parsed[run["start"]][3] > ANIM_COVERAGE

    mode = {}
    for run in runs:
        for m in run["members"]:
            mode[m] = run["animation"]

    anim_frames = sum(1 for v in mode.values() if v)
    print(f"{len(files)} containers, {len(runs)} runs: "
          f"{anim_frames} animation frames, {len(mode) - anim_frames} standalone sprites")

    if args.report:
        print(f"\n{'start':>6} {'n':>4}  {'size':<10} {'cover':>6}  type")
        for run in runs:
            w, h = run["size"]
            print(f"{run['start']:>6} {len(run['members']):>4}  {w}x{h:<7} "
                  f"{parsed[run['start']][3]:>6.3f}  "
                  f"{'animation' if run['animation'] else 'sprites'}")
        return

    # pass 2 — render
    canvas = None
    prev = None
    for idx, f in files:
        w, h, rows, cov = parsed[idx]
        fresh = (not mode[idx]) or prev != (w, h) or cov > ANIM_COVERAGE
        if fresh:
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            prev = (w, h)
        paint(canvas, w, h, rows)
        canvas.save(os.path.join(dst, f[:-4] + ".png"))

    print(f"wrote {len(files)} PNGs to {dst}")

    if args.sheet:
        cols, cw, ch = 8, 180, 110
        tiles = [Image.open(os.path.join(dst, dict(files)[r["start"]][:-4] + ".png"))
                 .convert("RGBA") for r in runs]
        nrows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGBA", (cols * cw, nrows * ch), (235, 235, 235, 255))
        for n, im in enumerate(tiles):
            k = min((cw - 10) / im.width, (ch - 10) / im.height)
            small = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                              Image.NEAREST)
            x = (n % cols) * cw + (cw - small.width) // 2
            y = (n // cols) * ch + (ch - small.height) // 2
            sheet.alpha_composite(small, (x, y))
        path = os.path.join(dst, "overview.png")
        sheet.convert("RGB").save(path)
        print(f"contact sheet: {path}")


if __name__ == "__main__":
    main()
