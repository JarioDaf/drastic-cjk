"""verify.py -- structural sanity check for a patched DraStic executable.

Runs without the device: it re-derives every invariant the patch promises and
compares the result against the reference build.

    python tools/verify.py build/drastic.cjk
    python tools/verify.py --md5-only build/drastic.cjk

Exit status 0 = all checks passed.
"""
import hashlib
import os
import struct
import sys

# the byte-exact output of the reference build (see docs/BUILD.md)
REFERENCE_MD5 = "373b50bfde2112438b37c968073ff853"
REFERENCE_SIZE = 2403166

HOOKS = {0x87F00: 0x150000, 0x88430: 0x150054}      # site -> payload entry
SEG_VA, SEG_OFF, FONT_OFF = 0x150000, 0x160000, 0x170000
VENDOR_BSS = 0x1681A0       # max(p_vaddr + p_filesz) -- end of .data
VENDOR_BRK = 0x3F32240      # max(p_vaddr + p_memsz)  -- end of .bss
SZ15, SZ10, SZ8, SZ16, SZUNI = 265118, 176748, 141400, 282792, 29780
BLOB = SZ15 + SZ10 + SZ8 + SZ16 + SZUNI             # 895838
NUM_SLOTS, UNI_N = 8837, 7445

ok = True


def check(cond, what, detail=""):
    global ok
    print("  %s %s%s" % ("PASS" if cond else "FAIL", what,
                         ("   [%s]" % detail) if detail else ""))
    if not cond:
        ok = False
    return cond


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    md5_only = "--md5-only" in argv
    path = [a for a in argv[1:] if not a.startswith("-")][0]
    d = open(path, "rb").read()
    md5 = hashlib.md5(d).hexdigest()

    print("%s" % path)
    print("  size %d B, md5 %s" % (len(d), md5))
    if md5 == REFERENCE_MD5:
        print("  == the reference build, byte for byte")
    else:
        print("  != the reference build (expected %s / %d B)"
              % (REFERENCE_MD5, REFERENCE_SIZE))
    if md5_only:
        return 0 if md5 == REFERENCE_MD5 else 1

    print("\nELF invariants")
    (_, etype, emach, _, eentry, ephoff, _, _, _, _, ephnum, _, _, _) = \
        struct.unpack_from("<16sHHIQQQIHHHHHH", d, 0)
    check(emach == 183, "e_machine == EM_AARCH64", "0x%x" % emach)
    check(etype == 3, "e_type == ET_DYN (PIE)", "%d" % etype)

    ph = [struct.unpack_from("<IIQQQQQQ", d, ephoff + i * 56)
          for i in range(ephnum)]
    loads = [h for h in ph if h[0] == 1]
    elf_bss = max(h[3] + h[5] for h in loads)       # vaddr + filesz
    elf_brk = max(h[3] + h[6] for h in loads)       # vaddr + memsz
    check(elf_bss == VENDOR_BSS, "elf_bss unmoved", hex(elf_bss))
    check(elf_brk == VENDOR_BRK, "elf_brk unmoved", hex(elf_brk))
    check(not any((h[1] & 3) == 3 for h in loads), "no W+X PT_LOAD")
    check(all((h[2] - h[3]) % h[7] == 0 for h in loads),
          "p_vaddr congruent to p_offset (mod p_align)")

    inj = [h for h in loads if h[3] == SEG_VA]
    if check(len(inj) == 1, "injected PT_LOAD present at 0x%x" % SEG_VA):
        h = inj[0]
        check(h[1] == 5, "injected segment is R-X (flags 5)", "flags=%d" % h[1])
        check(h[2] == SEG_OFF, "p_offset == 0x%x" % SEG_OFF, hex(h[2]))
        check(h[5] == h[6], "filesz == memsz", "%d" % h[5])
        check(SEG_VA + h[5] <= VENDOR_BSS, "injected segment stays below .bss")

    print("\nhooks")
    for site, target in HOOKS.items():
        w = struct.unpack_from("<I", d, site)[0]
        delta = ((w & 0x03FFFFFF) << 2)
        if delta & (1 << 27):
            delta -= 1 << 28
        check((w >> 26) == 0b000101 and site + delta == target,
              "b 0x%x at 0x%x -> 0x%x" % (target, site, target),
              "encodes 0x%x" % (site + delta))

    print("\nappended blob")
    check(len(d) == FONT_OFF + BLOB,
          "file length == FONT_OFF + blob", "%d" % len(d))
    blob = d[FONT_OFF:FONT_OFF + BLOB]
    # 15x15 / 10x10 / 8x8 / 16x16 bitmap sections -- each is a vestigial
    # 8-byte header followed by NUM_SLOTS glyphs of N u16 rows.  The loader
    # compiles the geometry in (SZ*), so the header is never read.
    for name, off, sz, cell in (("cjk15", 0, SZ15, 15),
                                ("cjk10", SZ15, SZ10, 10),
                                ("cjk8", SZ15 + SZ10, SZ8, 8),
                                ("cjk16", SZ15 + SZ10 + SZ8, SZ16, 16)):
        body = blob[off + 8: off + sz]
        check(len(body) == NUM_SLOTS * cell * 2 and any(body),
              "%s section present (%d glyphs %dx%d)" % (name, NUM_SLOTS, cell, cell))
    uni = blob[SZ15 + SZ10 + SZ8 + SZ16:]
    vals = struct.unpack("<%dI" % UNI_N, uni[:UNI_N * 4])
    check(len(uni) == SZUNI, "unicode map is %d bytes" % SZUNI, "%d" % len(uni))
    check(all(vals[i] <= vals[i + 1] for i in range(UNI_N - 1)),
          "unicode map is sorted ascending (binary-searchable)")
    check(0x4E00 in [v >> 16 for v in vals], "unicode map covers U+4E00")

    print("\nresult: %s" % ("ALL CHECKS PASSED" if ok else "FAILURES PRESENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
