"""genfont_uni.py -- generate assets/uni_tab.bin, the GB2312 -> Unicode map.

Layout: a sorted array of u32,  (unicode_codepoint << 16) | gb_slot_index,
where gb_slot_index = (zone-1)*94 + (pos-1) for the GB2312 byte pair
(0xA0+zone, 0xA0+pos).  The injected renderer binary-searches it to turn a
UTF-8/Unicode character coming from the host into the glyph slot of the
bitmap fonts in the appended blob.

This is a pure function of the GB2312 codec, so it is identical on every
Python >= 3.4 and needs no external font.

Usage:  python tools/genfont_uni.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

NUM_SLOTS = 8837          # 94*94 GB2312 slots (the extra slot holds a box)


def build_uni_table():
    """sorted u32 array: (unicode << 16) | gb_index"""
    items = []
    seen = set()
    for zone in range(1, 95):
        for pos in range(1, 95):
            hi = 0xA0 + zone
            lo = 0xA0 + pos
            try:
                ch = bytes([hi, lo]).decode("gb2312")
            except Exception:
                continue
            cp = ord(ch)
            if cp > 0xFFFF or cp in seen:
                continue
            seen.add(cp)
            gbidx = (zone - 1) * 94 + (pos - 1)
            items.append((cp << 16) | gbidx)
    items.sort()
    print("  unicode entries: %d" % len(items))
    return struct.pack("<%dI" % len(items), *items)


def main():
    os.makedirs(C.ASSETS, exist_ok=True)
    u = build_uni_table()
    p = C.asset("uni_tab.bin")
    open(p, "wb").write(u)
    print("  -> %s  %d bytes (expect 29780)" % (p, len(u)))


if __name__ == "__main__":
    main()
