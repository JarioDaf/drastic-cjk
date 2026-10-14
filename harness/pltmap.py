"""pltmap.py -- map every PLT stub in the vendor binary to its GOT slot and
dynamic symbol name, so the Unicorn tracers can install their own stubs.

AArch64 PLT stub (with BTI off, -z now off) is 16 bytes:
    adrp x16, <got page>
    ldr  x17, [x16, #lo]
    add  x16, x16, #lo
    br   x17
"""
import struct, sys, os
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import config as C

d = open(C.require_src(), "rb").read()

eh = struct.unpack_from("<16sHHIQQQIHHHHHH", d, 0)
ephnum, ephoff = eh[10], eh[5]
ph = [struct.unpack_from("<IIQQQQQQ", d, ephoff + i * 56) for i in range(ephnum)]
dyn = [p for p in ph if p[0] == 2][0]

tags = {}
for i in range(dyn[5] // 16):
    t, v = struct.unpack_from("<qQ", d, dyn[2] + i * 16)
    if t == 0:
        break
    tags.setdefault(t, v)

DT_SYMTAB, DT_STRTAB, DT_JMPREL = 6, 5, 23
DT_PLTRELSZ, DT_PLTREL, DT_SYMENT = 2, 20, 11
DT_RELASZ, DT_RELA, DT_RELAENT = 8, 7, 9

def load_va(va, n):
    for t, fl, off, v, pa, fsz, msz, al in ph:
        if t == 1 and v <= va < v + fsz and va + n <= v + fsz:
            return d[off + (va - v): off + (va - v) + n]
    raise KeyError(hex(va))

symtab = tags[DT_SYMTAB]
strtab = tags[DT_STRTAB]
jmp = tags.get(DT_JMPREL)
pltrelsz = tags.get(DT_PLTRELSZ, 0)

def sym_name(idx):
    so = symtab + idx * 24
    st_name = struct.unpack_from("<I", load_va(so, 4))[0]
    e = d.find(b"\0", strtab + st_name)
    return d[strtab + st_name:e].decode("latin1")

relocs = []   # (got_va, sym_idx, type)
if jmp:
    for i in range(pltrelsz // 24):
        fo = jmp + i * 24
        off, info, add = struct.unpack_from("<QQq", load_va(fo, 24))
        relocs.append((off, info >> 32, info & 0xFFFFFFFF))

# RELA (non-PLT) may also hold GLOB_DAT
for i in range(tags.get(DT_RELASZ, 0) // 24):
    fo = tags[DT_RELA] + i * 24
    off, info, add = struct.unpack_from("<QQq", load_va(fo, 24))
    relocs.append((off, info >> 32, info & 0xFFFFFFFF))

md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
md.detail = True

def dec_adrp(w, pc):
    immhi = (w >> 5) & 0x7FFFF
    immlo = (w >> 29) & 3
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= (1 << 21)
    return (pc & ~0xFFF) + (imm << 12)

# find all `br x17` and walk back the 3 preceding insns
# scan the whole first PT_LOAD
tseg = [p for p in ph if p[0] == 1 and p[1] & 1][0]
off, va, fsz = tseg[2], tseg[3], tseg[5]
words = struct.unpack_from("<%dI" % (fsz // 4), d, off)
stubs = {}
for i, w in enumerate(words):
    if w == 0xD61F0220:                       # br x17
        pc = va + i * 4
        # adrp x16 at i-3, ldr x17,[x16,#lo] at i-2, add x16,x16,#lo at i-1
        wa = words[i - 3]
        if (wa & 0x9F000000) != 0x90000000:
            continue
        page = dec_adrp(wa, pc - 12)
        wl = words[i - 2]                     # ldr x17, [x16, #imm]
        if (wl & 0xFFC00000) != 0xF9400000:
            continue
        imm = ((wl >> 10) & 0xFFF) * 8
        got = page + imm
        stubs[pc] = got
        # sanity: the add must target the same slot
        wnd = words[i - 1]
        if (wnd & 0xFFC00000) == 0x91000000:
            ai = (wnd >> 10) & 0xFFF
            assert page + ai == got, (hex(pc), hex(page + ai), hex(got))

by_got = {}
for off_v, si, ty in relocs:
    by_got[off_v] = (sym_name(si), ty)

print("# PLT stub  ->  GOT slot  ->  symbol")
for pc in sorted(stubs):
    got = stubs[pc]
    nm, ty = by_got.get(got, ("<none>", -1))
    print("0x%06x -> 0x%06x  %-28s (type %d)" % (pc, got, nm, ty))

if len(sys.argv) > 1:
    want = set(sys.argv[1:])
    print("\n# filter:")
    for pc in sorted(stubs):
        got = stubs[pc]
        nm, ty = by_got.get(got, ("<none>", -1))
        if nm in want:
            print("0x%06x got=0x%06x %s" % (pc, got, nm))
