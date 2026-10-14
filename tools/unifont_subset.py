"""unifont_subset.py -- write assets/unifont.hex, the committed GB2312 subset.

The generators only ever look up the characters GB2312 can produce (7 445 of
them, see tools/genfont_uni.py), so there is no reason to make the repository
carry all ~126 000 glyphs of unifont_all.hex.  This writes out just those
lines -- **copied verbatim** from the upstream file, in its own order, so the
result is a trimmed copy of GNU Unifont rather than a modified font.  It is
still font software, and still under the same licence (OFL 1.1 or GPLv2+ with
the font embedding exception); see NOTICE.md.

Usage:
    UNIFONT_HEX=/path/to/unifont_all-18.0.01.hex python tools/unifont_subset.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C
import unifont as U


def needed_codepoints():
    """every BMP codepoint reachable through the GB2312 codec."""
    cps = set()
    for zone in range(1, 95):
        for pos in range(1, 95):
            try:
                ch = bytes([0xA0 + zone, 0xA0 + pos]).decode("gb2312")
            except Exception:
                continue
            cp = ord(ch)
            if cp <= 0xFFFF:
                cps.add(cp)
    return cps


def main():
    src = U.hex_path()
    want = needed_codepoints()
    print("source : %s" % src)
    print("needed : %d GB2312 codepoints" % len(want))

    kept = 0
    missing = set(want)
    out = []
    with open(src, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            cp_s, _, bits = s.partition(":")
            if not bits or len(cp_s) > 4:
                continue
            if U.rows_of(bits) is None:          # quadruple-width ideographs
                continue
            cp = int(cp_s, 16)
            if cp in want:
                out.append(s + "\n")
                missing.discard(cp)
                kept += 1
    if missing:
        # GB2312 covers a handful of characters Unifont itself leaves
        # unassigned; those slots stay blank in the font.
        print("note   : %d codepoints have no glyph upstream (blank slots)"
              % len(missing))

    os.makedirs(C.ASSETS, exist_ok=True)
    p = C.asset("unifont.hex")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(out)
    print("wrote  : %s  %d glyphs, %d bytes"
          % (p, kept, sum(len(x) for x in out)))


if __name__ == "__main__":
    main()
