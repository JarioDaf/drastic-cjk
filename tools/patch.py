"""patch.py -- add CJK text support to DraStic (aarch64 PIE) without touching
the kernel's view of the image.

Layout
  * the tiny injected image (code+rodata, ~1 KB) is put in ONE recycled
    program header (PT_NOTE) as a PT_LOAD **R-X** -- the same protection as
    the vendor's own code segment, so the process never gains a W+X mapping
    -- whose vaddr lives in the vendor's address-space hole between the two
    original LOADs (0x14c8000 .. 0x15d1f8).  It is therefore strictly BELOW
    the .bss, so the kernel's single anonymous bss mapping
    (set_brk(elf_bss, elf_brk)) is bit-for-bit what the vendor build asks for.
  * the injected image has NO mutable statics: the renderer's scratch font
    lives on the stack and the blob pointer/dead flag live in the vendor's
    own RW LOAD at 0x168E00 -- the zero-filled file-tail padding between
    .data (0x1681a0) and .bss (0x169000), which elf_map() maps as the last
    partial page of that segment and which no linker symbol uses.
  * the ~600 KB GB2312 bitmap blob is appended to the file and mmap()ed from
    the running executable on first CJK draw (see cjk.c).  It is not covered
    by any PT_LOAD on purpose (it cannot fit below the .bss).
  * the first instruction of draw_text() @0x87f00 becomes `b cjk_entry`.

Asserted invariants (these are what the earlier attempts got wrong)
      p_vaddr + p_filesz <= 0x1681a0   (elf_bss stays -> .bss start 0x169000)
      p_vaddr + p_memsz  <= 0x3F32240  (elf_brk stays -> .bss end   0x3F32240)
      no PT_LOAD is writable *and* executable
"""
import struct, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
sys.path.insert(0, C.ASSETS)          # menu_sites.py lives with the assets

SRC     = C.require_src()
OUT     = sys.argv[1] if len(sys.argv) > 1 else os.path.join(C.BUILD, "drastic.cjk")
PAYLOAD = C.build("payload.elf")

HOOK_VA   = 0x87f00          # draw_text()
SEG_VA    = 0x150000         # 64K-aligned slot inside the vendor hole
SEG_OFF   = 0x160000         # 64K aligned, past the end of the vendor file
SEG_ALIGN = 0x10000          # valid for 4K / 16K / 64K page kernels
FONT_OFF  = 0x170000         # 64K aligned; blob pulled in at runtime

# vendor limits that must not move
VENDOR_BSS_START = 0x169000
VENDOR_BSS_END   = 0x3F32240
HOLE_LO          = 0x14c800        # page_align(end of the R-X segment)
HOLE_HI          = 0x15d1f8        # start of the vendor RW segment

FONTS = [("font_15.bin", 265118), ("font_10.bin", 176748),
         ("font_8.bin", 141400), ("font_16.bin", 282792),
         ("uni_tab.bin", 29780)]

HOOKS = [(0x87f00, "cjk_entry"), (0x88430, "cjk_rect_entry")]

# ---------------------------------------------------------------- payload
p = open(PAYLOAD, "rb").read()
(_, _, _, _, pentry, pphoff, pshoff, _, _, _, _, pshs, pshnum, pshstr) = \
    struct.unpack_from("<16sHHIQQQIHHHHHH", p, 0)
psh = [struct.unpack_from("<IIQQQQIIQQ", p, pshoff + i * pshs) for i in range(pshnum)]
pst = psh[pshstr]; pstab = p[pst[4]:pst[4] + pst[5]]
def pname(o):
    e = pstab.find(b"\0", o); return pstab[o:e].decode()
sect = {pname(s[0]): s for s in psh}

# symbol table -> entry point of each hook stub
SYMS = {}
_symsec = next((s for s in psh if s[1] == 2), None)          # SHT_SYMTAB
if _symsec is not None:
    _strsec = psh[_symsec[6]]
    _strt = p[_strsec[4]:_strsec[4] + _strsec[5]]
    for i in range(_symsec[5] // 24):
        _o, _info, _other, _shn, _val, _sz = struct.unpack_from("<IBBHQQ", p, _symsec[4] + i * 24)
        _e = _strt.find(b"\0", _o)
        SYMS[_strt[_o:_e].decode()] = _val
for _n in ("cjk_entry", "cjk_rect_entry"):
    assert _n in SYMS, "payload is missing symbol %s" % _n
print("payload syms: cjk_entry=0x%x cjk_rect_entry=0x%x" % (SYMS["cjk_entry"], SYMS["cjk_rect_entry"]))

# one flat image: progbits at their vaddr, zero filled up to the end of the
# allocatable part, so filesz == memsz (the kernel only maps p_filesz here).
end = SEG_VA
for name in (".text", ".rodata", ".data", ".bss"):
    if name in sect and sect[name][5]:
        end = max(end, sect[name][3] + sect[name][5])
memsz = end - SEG_VA
img = bytearray(memsz)
for name in (".text", ".rodata", ".data"):
    if name in sect and sect[name][5]:
        s = sect[name]
        img[s[3] - SEG_VA: s[3] - SEG_VA + s[5]] = p[s[4]: s[4] + s[5]]
filesz = len(img)
entry_rel = pentry - SEG_VA
print("payload image: filesz=memsz=0x%x (%d B), entry +0x%x" % (filesz, filesz, entry_rel))

# nothing writable may live in the injected image (it is mapped R-X)
for name in (".data", ".bss"):
    n = sect[name][5] if name in sect else 0
    assert n == 0, "%s: %d bytes of writable state in an R-X segment" % (name, n)

# ---- the image must be position independent at the DATA level, too -----
# The vendor executable is a PIE and this image is one of its PT_LOADs, so
# the module is mapped at a loader-chosen base and NOTHING relocates the
# payload: any pointer stored in the image keeps the absolute value the
# linker gave it (0x151b78, 0x87f00, ...) and becomes a dangling address on
# the device.  Code and string literals are PC-relative and safe; a table
# of pointers is not.  (This is exactly how the first VALMAP table crashed the
# emulator the moment the menu came up -- the Unicorn harness loads the
# module at VA 0, where those stale pointers happen to be valid.)
ABSOLUTE_TRAPS = (0x87f00, 0x88434, 0x167668, 0x160a50, 0x162e58, 0x165260)
for _o in range(0, len(img) - 7, 8):
    _v = struct.unpack_from("<Q", img, _o)[0]
    _bad = (SEG_VA <= _v < SEG_VA + len(img)) or (_v in ABSOLUTE_TRAPS)
    assert not _bad, (
        "absolute address 0x%x stashed at VA 0x%x -- the injected image must be "
        "base independent (use an array, not a pointer)" % (_v, SEG_VA + _o))

# --------------------------------------------------- Chinese menu string table
# The GB2312 menu strings live in their own R-X section appended to the same
# PT_LOAD (the vendor hole has ~53 KB to spare).  Every reference site in the
# host binary is then retargeted:  adrp/add string loads become a single
# `adr` (PC-relative, +-1 MB, plenty for the 0x7xxxx..0x82xxx sites), and
# R_AARCH64_RELATIVE table entries get their addend rewritten.  The original
# English strings are left byte-for-byte intact -- other code (e.g. the
# "r2.5.2.2" substring reference) keeps working untouched.
import menu_sites as MS
OFF = {int(k, 16): v for k, v in MS.OFFSETS.items()}
MENU = open(C.MENU_BIN, "rb").read()
STRTAB_VA = SEG_VA + 0x2000          # 8 KB of payload, then the string table
assert STRTAB_VA == 0x152000, "update STRTAB_REL in cjk.c"
assert len(MENU) == 1555, "menu.bin size changed -- update MENU_SZ in cjk.c"
_pad = STRTAB_VA - (SEG_VA + filesz)
assert _pad >= 0, "payload outgrew its 8 KB slot (0x%x > 0x2000)" % filesz
img += b"\0" * _pad + MENU
filesz = len(img)
print("menu strtab: 0x%x, %d bytes, %d strings (payload 0x%x)" %
      (STRTAB_VA, len(MENU), len(MS.OFFSETS), _pad + 0 - 0))
print("  code+rodata slot used: %d / 8192 B" % _pad)

# ---------------------------------------------------------------- invariants
assert filesz <= SEG_ALIGN, "payload no longer fits a 64K page"
assert HOLE_LO <= SEG_VA and SEG_VA + filesz <= HOLE_HI, "payload leaves the vendor hole"
assert SEG_VA + filesz <= VENDOR_BSS_START, "would move elf_bss"
assert SEG_VA + filesz <= VENDOR_BSS_END,   "would move elf_brk"
assert (SEG_VA - SEG_OFF) % SEG_ALIGN == 0, "p_vaddr/p_offset must be congruent"
assert SEG_OFF % SEG_ALIGN == 0 and FONT_OFF % SEG_ALIGN == 0, "offsets must be 64K aligned"
assert FONT_OFF >= SEG_OFF + filesz, "font blob overlaps the injected segment"

# ---------------------------------------------------------------- host
d = bytearray(open(SRC, "rb").read())
(eid, etype, emach, ever, eentry, ephoff, eshoff, eflags, eehsize,
 ephent, ephnum, eshent, eshnum, eshstr) = struct.unpack_from("<16sHHIQQQIHHHHHH", d, 0)
hdr = []
for i in range(ephnum):
    hdr.append((i,) + struct.unpack_from("<IIQQQQQQ", d, ephoff + i * 56))

def loads(hs):
    return [h for h in hs if h[1] == 1]
def elf_bss(hs):
    return max(h[4] + h[6] for h in loads(hs))          # max(vaddr + p_filesz)
def elf_brk(hs):
    return max(h[4] + h[7] for h in loads(hs))          # max(vaddr + p_memsz)

print("vendor : elf_bss=0x%x elf_brk=0x%x  (.bss 0x%x..0x%x)" %
      (elf_bss(hdr), elf_brk(hdr), VENDOR_BSS_START, VENDOR_BSS_END))
assert elf_bss(hdr) == 0x1681a0 and elf_brk(hdr) == VENDOR_BSS_END, "unexpected vendor layout"

note_idx = next((h[0] for h in hdr if h[1] == 4), None)
assert note_idx is not None, "no PT_NOTE to recycle"

# ---------------------------------------------------------------- emit
out = bytearray(d)
if len(out) < SEG_OFF:
    out += b"\0" * (SEG_OFF - len(out))
out[SEG_OFF:SEG_OFF + filesz] = img

# font blob, appended (deliberately not covered by any program header)
assert len(out) <= FONT_OFF, "gap between segment and blob vanished"
out += b"\0" * (FONT_OFF - len(out))
blob_off = len(out)
for name, want in FONTS:
    b = open(C.asset(name), "rb").read()
    assert len(b) == want, "%s: %d != %d" % (name, len(b), want)
    out += b
print("font blob at file 0x%x, %d bytes (cjk15|cjk10|cjk8|cjk16|uni_tab)" % (blob_off, len(out) - blob_off))

# recycled program header -> PT_LOAD R-X (never W+X)
struct.pack_into("<IIQQQQQQ", out, ephoff + note_idx * 56,
                 1, 5, SEG_OFF, SEG_VA, SEG_VA, filesz, filesz, SEG_ALIGN)

# hooks: the first instruction of each primitive becomes `b <stub>`
for HOOK_VA, sym in HOOKS:
    target = SYMS[sym]
    delta = target - HOOK_VA
    assert -0x8000000 <= delta <= 0x7FFFFFC and delta % 4 == 0
    struct.pack_into("<I", out, HOOK_VA, 0x14000000 | ((delta >> 2) & 0x03FFFFFF))
    print("hook %-14s 0x%x: b 0x%x (payload %s)" % (sym + "()", HOOK_VA, target, sym))

# --------------------------------------------------- retarget menu references
# capstone's ARM64 register ids are NOT "X0 + n": X29/X30 are early aliases.
import capstone.arm64 as _a
REGNUM = {getattr(_a, "ARM64_REG_X%d" % i): i for i in range(31)}

def enc_adr(rd, pc, tgt):
    """ADR Rd, tgt : imm21 = immhi(19):immlo(2), (tgt - pc) signed, |.| <= 1 MB."""
    off = tgt - pc
    assert -(1 << 20) <= off < (1 << 20) and off % 4 == 0, \
        "adr out of range: 0x%x -> 0x%x (%d)" % (pc, tgt, off)
    imm = off & 0x1FFFFF
    immlo = imm & 3
    immhi = (imm >> 2) & 0x7FFFF
    return (immlo << 29) | (0b10000 << 24) | (immhi << 5) | rd

for adrp_a, add_a, reg, s_addr in MS.CODE_SITES:
    add_a = int(add_a, 16); s_addr = int(s_addr, 16)
    tgt = STRTAB_VA + OFF[s_addr]
    out[add_a:add_a + 4] = struct.pack("<I", enc_adr(REGNUM[reg], add_a, tgt))

for rela_fo, s_addr in MS.REL_SITES:
    # RELA entry layout: r_offset(8) r_info(8) r_addend(8) -- patch the addend
    struct.pack_into("<Q", out, int(rela_fo, 16) + 16, STRTAB_VA + OFF[int(s_addr, 16)])
print("menu: %d code sites -> adr, %d reloc addends rewritten" %
      (len(MS.CODE_SITES), len(MS.REL_SITES)))

# ---------------------------------------------------------------- verify
# (v9 note: the v8 instruction patches here -- pinning the value column and
#  moving the firmware cursor -- are GONE.  The hook now overrides both by
#  call-site: values land on one hard-aligned column and the cursor is
#  re-anchored inside cjk_rect, so the host code stays pristine.)
ph2 = []
for i in range(ephnum):
    ph2.append((i,) + struct.unpack_from("<IIQQQQQQ", out, ephoff + i * 56))
print("patched: elf_bss=0x%x elf_brk=0x%x" % (elf_bss(ph2), elf_brk(ph2)))
assert elf_bss(ph2) == elf_bss(hdr), "elf_bss moved -- .bss would break"
assert elf_brk(ph2) == elf_brk(hdr), "elf_brk moved -- .bss would break"
for h in ph2:
    if h[1] == 1:
        assert not (h[2] & 3 == 3), "PT_LOAD at 0x%x is writable+executable" % h[4]
        assert (h[3] - h[4]) % h[8] == 0, "p_vaddr/p_offset not p_align congruent at 0x%x" % h[4]

open(OUT, "wb").write(out)
os.chmod(OUT, 0o755)
print("written %s (%d bytes, +%d)" % (OUT, len(out), len(out) - len(d)))
