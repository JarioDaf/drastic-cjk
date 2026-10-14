"""genfont5.py -- the 15x15 / 10x10 / 8x8 CJK bitmap sets.

Single crisp source: GNU Unifont's native 16x16 glyph grid (1 px strokes, no
anti-aliasing), box-filtered down into each cell:
  15x15 : 16 -> 15  (nearly 1:1)          raw
  10x10 : 16 -> 10  box filter, th 0.30   raw
  8x8   : 16 -> 8   box filter, th 0.30, shifted down one row so the
                    baseline lands on row 7 like the host's own 8x8 font

At 16 -> 8 a one-pixel stroke covers only a quarter of an output pixel, so a
raw downsample drops the thin horizontals of characters like 称 or 戏 and the
row goes illegible.  Unifont's strokes are all exactly one pixel wide, so for
the 8x8 set the source is thickened by one pixel (4-neighbour dilation, which
turns a 1 px stroke into a 2 px one -- exactly 1 px after the halving) before
the box filter.  The 15 and 10 sets do not need it.

See tools/unifont.py for the source format and NOTICE.md for the licence.
"""
import struct, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import unifont as U

OUT      = C.ASSETS
NUM      = U.NUM_SLOTS   # 94*94 GB2312 slots + 1 fallback box
SRC_N    = U.CELL        # 16
SRC_SHIFT = 0            # move the source glyphs down inside the cell

# cell, threshold, output shift-down, source dilation
SETS = ((15, 0.5, 0, 0), (10, 0.30, 0, 0), (8, 0.30, 1, 1))


def dilate(rows, k):
    """thicken every stroke by k pixels (4-neighbour, 16-bit rows)."""
    cur = list(rows)
    for _ in range(k):
        nxt = []
        for y in range(SRC_N):
            r = cur[y]
            m = r | ((r << 1) & 0xFFFF) | (r >> 1)
            if y:
                m |= cur[y - 1]
            if y + 1 < SRC_N:
                m |= cur[y + 1]
            nxt.append(m)
        cur = nxt
    return cur


def downscale(rows, N, th):
    step = SRC_N / N
    out = [0] * N
    for ty in range(N):
        v = 0
        for tx in range(N):
            x0, x1 = tx * step, (tx + 1) * step
            y0, y1 = ty * step, (ty + 1) * step
            tot = cnt = 0.0
            iy = int(y0)
            while iy < SRC_N and iy < y1:
                ix = int(x0)
                while ix < SRC_N and ix < x1:
                    w = (min(x1, ix + 1) - x0) * (min(y1, iy + 1) - y0)
                    tot += w * ((rows[iy] >> (15 - ix)) & 1)
                    cnt += w
                    ix += 1
                iy += 1
            if cnt and tot / cnt >= th:
                v |= 1 << (15 - tx)
        out[ty] = v
    return out

def shift_down(rows, k):
    if k <= 0:
        return rows
    return [0] * k + rows[:-k]

def pack(rows):
    # NOTE: `rows` here is the *list of glyphs* (8837 of them), so the 8-byte
    # header ends up holding the glyph count, not the cell size.  That is a
    # wart, but it is load-bearing for reproducibility: the injected loader
    # (src/cjk.c) compiles the geometry in via SZ15/SZ10/SZ8 and skips this
    # header entirely, and "fixing" it to (N, N) would change font_15/10/8.bin
    # and therefore the md5 of the whole build.  Leave it alone.
    b = bytearray(struct.pack("<II", len(rows), len(rows)))
    for r in rows:
        for v in r:
            b += struct.pack("<H", v)
    return bytes(b)

def main():
    src = U.load()
    print("source: GNU Unifont, %d glyphs of the BMP (%s)"
          % (len(src), U.hex_path()))
    grid = U.gb2312_rows(src, SRC_SHIFT)
    for N, th, sh, dil in SETS:
        dst = []
        for r in grid:
            if r is None:
                dst.append([0] * N)
            else:
                d = downscale(dilate(r, dil), N, th)
                dst.append(shift_down(d, sh))
        p = os.path.join(OUT, "font_%d.bin" % N)
        open(p, "wb").write(pack(dst))
        print("  font_%d.bin  %d bytes  (th %.2f, dilate %d, shift %d)"
              % (N, 8 + N * NUM * 2, th, dil, sh))

if __name__ == "__main__":
    main()
