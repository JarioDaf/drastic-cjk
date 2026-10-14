"""genfont6.py -- 200% (2x) font sets for the DraStic UI.

  font_16.bin   : GB2312 CJK, 16x16, taken 1:1 from GNU Unifont's native
                  16x16 glyph grid (no scaling loss at all).
  ascii_16.bin  : 256 glyphs 16x16, produced by doubling every pixel of the
                  vendor's own built-in 8x8 UI font (exactly 200%).

Both files use the renderer's font layout:
    u32 width, u32 height, then height rows of u16 (bit15 = left-most pixel),
    with glyph g's first row at  8 + (off[g]) * 2.

See tools/unifont.py for the source and NOTICE.md for the licence.
"""
import struct, os, sys

HERE   = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C
import unifont as U

DRAS   = C.require_src()

NUM    = U.NUM_SLOTS   # 94*94 GB2312 slots + 1 fallback box

# vendor's built-in 8x8 bitmap font (see the RE notes); it lives in the RW
# segment, whose file offset is 0x10000 below its vaddr (the injected segment
# occupies exactly that hole)
F8_VA, F8_FO = 0x162e58, 0x162e58 - 0x10000


def vendor_glyph8(d, ch):
    """return the 8 rows (list of 8 bits, index 0 = left-most) of ASCII `ch`."""
    w, h = struct.unpack_from("<II", d, F8_FO)
    assert (w, h) == (8, 8), "unexpected vendor font metrics %d x %d" % (w, h)
    off = struct.unpack_from("<I", d, F8_FO + 0x2008 + ch * 4)[0]
    rows = []
    for y in range(8):
        v = struct.unpack_from("<H", d, F8_FO + 8 + (off + y) * 2)[0]
        rows.append([(v >> (15 - x)) & 1 for x in range(8)])
    return rows


def main():
    d = open(DRAS, "rb").read()

    # ------------------------------------------------ CJK 16x16 from Unifont
    # 1:1 -- the upstream grid is already 16x16, so this set is a verbatim
    # copy of the glyphs and loses nothing to scaling.
    src = U.load()
    print("source: GNU Unifont, %d glyphs of the BMP (%s)"
          % (len(src), U.hex_path()))
    out = bytearray()
    out += struct.pack("<II", 16, 16)
    for rows in U.gb2312_rows(src):          # 8836 slots + the fallback box
        for v in (rows if rows is not None else [0] * U.CELL):
            out += struct.pack("<H", v)
    assert len(out) == 8 + 16 * NUM * 2, len(out)
    open(C.asset("font_16.bin"), "wb").write(out)
    print("font_16.bin   %d bytes (%d glyphs 16x16)" % (len(out), NUM))

    # ------------------------------------------------ ASCII 16x16 = 2x of 8x8
    # Reference only: the injected renderer doubles the vendor 8x8 ASCII at
    # run time (see the scratch font in cjk.c), so this file is not consumed
    # by patch.py -- it is written to build/ as a byte-exact comparison aid.
    out = bytearray()
    out += struct.pack("<II", 16, 16)
    for ch in range(256):
        g = vendor_glyph8(d, ch)
        for y in range(16):
            v = 0
            src = g[y >> 1]
            for x in range(16):
                if src[x >> 1]:
                    v |= 1 << (15 - x)
            out += struct.pack("<H", v)
    assert len(out) == 8 + 256 * 32, len(out)
    os.makedirs(C.BUILD, exist_ok=True)
    open(C.build("ascii_16.bin"), "wb").write(out)
    print("ascii_16.bin  %d bytes (256 glyphs 16x16, 2x of the vendor 8x8)" % len(out))


if __name__ == "__main__":
    main()
