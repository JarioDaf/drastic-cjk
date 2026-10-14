"""unifont.py -- the 16x16 bitmap source behind the four CJK sets in assets/.

The sets come from **GNU Unifont**, which is free software: the glyphs are
dual-licensed under the SIL Open Font License 1.1 and the GNU GPL v2 or later
with the GNU font embedding exception, and carry no Reserved Font Name -- so
trimming the set down to GB2312 and shipping the derived bitmaps is fine.

    unifont-18.0.01   https://unifoundry.com/unifont/
                      https://ftp.gnu.org/gnu/unifont/  (and its mirrors)

Input
    assets/unifont.hex    the GB2312 subset, committed so that ./gen-assets.sh
                          runs offline and byte-reproducibly.  It is a trimmed
                          copy of the upstream file, not a derived font; build
                          it with tools/unifont_subset.py.
    $UNIFONT_HEX          point this at a full upstream file instead
                          (unifont_all-<ver>.hex, ~126 000 glyphs).

Format
    One line per glyph, `<codepoint>:<scanlines>`, MOST significant bit =
    left-most pixel.  Unifont is a *dual-width* font: a 16-pixel-wide glyph
    has 4 hex digits per scanline, an 8-pixel-wide one has 2 (see section
    2.3 of doc/unifont.txt).  Both are 16 scanlines tall here.

    That is already the u16 layout the injected renderer reads out of the blob
    (see src/cjk.c), so wide glyphs are copied as-is -- no anti-aliasing, no
    scaling.  Narrow glyphs are centred in the 16-pixel cell (`v << 4`), which
    is where a CJK font puts the GB2312 symbol zones they belong to.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C

CELL = 16               # the upstream glyph grid, and the "big" cell
NUM_SLOTS = 8837        # 94*94 GB2312 slots + 1 fallback box
LAST_SLOT = 8836        # index of the fallback box

DEFAULT_HEX = C.asset("unifont.hex")


def hex_path():
    """resolve the bitmap source, explaining what to do when it is missing."""
    p = os.path.abspath(os.environ.get("UNIFONT_HEX") or DEFAULT_HEX)
    if not os.path.isfile(p):
        raise SystemExit(
            "unifont bitmap source not found: %s\n"
            "assets/unifont.hex is committed, so a plain ./build.sh needs no\n"
            "font at all.  Only ./gen-assets.sh reads one -- point it at the\n"
            "upstream file if you removed the subset:\n"
            "    UNIFONT_HEX=/path/to/unifont_all-18.0.01.hex ./gen-assets.sh\n"
            "See NOTICE.md." % p)
    return p


def rows_of(bits):
    """one glyph's scanlines -> 16 u16 rows with bit15 = left-most pixel.

    Returns None for the quadruple-width historic ideographs, which GB2312
    cannot reach anyway.
    """
    if len(bits) == CELL * 4:                   # 16 px wide
        return [int(bits[i:i + 4], 16) for i in range(0, len(bits), 4)]
    if len(bits) == (CELL // 2) * 4:            # 8 px wide, centred
        return [int(bits[i:i + 2], 16) << 4 for i in range(0, len(bits), 2)]
    return None


def load(path=None):
    """{codepoint: [16 u16 rows]} for every glyph of the BMP in the file."""
    p = os.path.abspath(path) if path else hex_path()
    g = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cp_s, _, bits = line.partition(":")
            if not bits or len(cp_s) > 4:       # planes 1+ are not needed here
                continue
            rows = rows_of(bits)
            if rows is not None:
                g[int(cp_s, 16)] = rows
    return g


def box_rows(n=CELL):
    """the fallback "missing glyph" box: hollow, n pixels on a side."""
    rows = []
    for y in range(n):
        v = 0
        for x in range(n):
            if (y in (0, n - 1) or x in (0, n - 1)) and not (
                    y in (0, n - 1) and x in (0, n - 1)):
                v |= 1 << (15 - x)
        rows.append(v)
    return rows


def vshift(rows, k):
    """move a glyph k pixels down inside its cell (k < 0 moves it up)."""
    if k == 0:
        return list(rows)
    if k > 0:
        return [0] * k + list(rows[:CELL - k])
    k = -k
    return list(rows[k:]) + [0] * k


def gb2312_rows(src, shift=0):
    """the 8837-slot source grid the font generators consume.

    Index = (zone-1)*94 + (pos-1) for the GB2312 byte pair (0xA0+zone,
    0xA0+pos), i.e. the same slot order as assets/uni_tab.bin.  A slot is
    None when the byte pair is unassigned -- the generators turn that into
    blank rows, exactly as before.
    """
    out = [None] * NUM_SLOTS
    for zone in range(1, 95):
        for pos in range(1, 95):
            idx = (zone - 1) * 94 + (pos - 1)
            try:
                cp = ord(bytes([0xA0 + zone, 0xA0 + pos]).decode("gb2312"))
            except Exception:
                continue
            r = src.get(cp)
            if r is not None:
                out[idx] = vshift(r, shift)
    out[LAST_SLOT] = box_rows()
    return out
