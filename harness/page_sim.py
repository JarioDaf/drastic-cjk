"""page_sim.py -- run DraStic's real menu page builders under Unicorn.

Rebuilds the node lists exactly as the vendor does (so the label pointers,
row ids, renderers and per-row extra data are authentic), then feeds each
node through its own renderer with the patched cjk hook active and dumps
the resulting framebuffer.  This makes any layout claim checkable instead
of guessed.

PLT stubs are intercepted: each one is hooked and emulated in Python, so
string/printf/new helpers behave like the C library.
"""
import struct, sys, os
from unicorn import *
from unicorn.arm64_const import *
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "tools"), os.path.join(ROOT, "assets")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as C

ORIG = C.require_src()                       # the pristine binary
PATCHED = os.environ.get("CJK") or C.build("drastic.cjk")

MOD_SIZE = 0x200000
BIG      = 0x2000000        # fabricated "app state" struct
SCRATCH  = 0x2010000
HEAP     = 0x2030000
HEAP_END = 0x2040000
FB       = 0x3000000
FB_SIZE  = 0x400000
STACK    = 0x400F000
SENT     = 0x400FF00
PITCH_PX = 800

DRAW_TEXT = 0x87F00
FONT_SLOT = 0x167668
FONT_OFF  = 0x170000
FONT_LEN  = 265118 + 176748 + 141400 + 29780

# ---------------------------------------------------------------- PLT table
def load_pltmap():
    import subprocess
    out = subprocess.run([sys.executable, os.path.join(HERE, "pltmap.py")],
                         capture_output=True, text=True, cwd=HERE).stdout
    m = {}
    for ln in out.splitlines():
        if ln.startswith("0x") and "->" in ln:
            parts = ln.split()
            br = int(parts[0], 16)
            got = int(parts[2], 16)
            name = parts[3]
            m[br - 0xC] = (got, name)
    return m

# ---------------------------------------------------------------- setup
def setup(path, pltmap):
    d = bytearray(open(path, "rb").read())
    (eid, et, em, ev, ent, ephoff, eshoff, efl, eeh, epe, ephn, eshe, echn, esh) = \
        struct.unpack_from("<16sHHIQQQIHHHHHH", d, 0)
    mu = Uc(UC_ARCH_ARM64, UC_MODE_LITTLE_ENDIAN)
    if os.environ.get("STRICT"):
        # exactly what the kernel maps for the patched image:
        #   [0, 0x14d000)        R-X  vendor code + rodata  (p_filesz 0x14c7ef)
        #   [0x14d000,0x150000)  --   HOLE, not mapped
        #   [0x150000,0x153000)  R-X  injected payload + menu strings
        #   [0x153000,0x15d000)  --   HOLE, not mapped
        #   [0x15d000,0x169000)  RW   vendor .data  (file part + zeroed tail)
        #   [0x169000,0x200000)  RW   vendor .bss (the kernel's anon mapping)
        mu.mem_map(0x000000, 0x14d000, UC_PROT_READ | UC_PROT_EXEC)
        mu.mem_map(0x150000, 0x003000, UC_PROT_READ | UC_PROT_EXEC)
        mu.mem_map(0x15d000, 0x00c000, UC_PROT_READ | UC_PROT_WRITE)
        mu.mem_map(0x169000, 0x097000, UC_PROT_READ | UC_PROT_WRITE)
    else:
        mu.mem_map(0, MOD_SIZE, UC_PROT_ALL)
    mu.mem_map(BIG, 0x40000, UC_PROT_ALL)
    mu.mem_map(FB, FB_SIZE, UC_PROT_ALL)
    mu.mem_map(0x4000000, 0x10000, UC_PROT_ALL)
    for i in range(ephn):
        t, fl, off, va, pa, fsz, msz, al = struct.unpack_from("<IIQQQQQQ", d, ephoff + i * 56)
        if t != 1 or fsz == 0:
            continue
        mu.mem_write(va, bytes(d[off:off + fsz]))
        if msz > fsz:
            mu.mem_write(va + fsz, b"\0" * min(msz - fsz, MOD_SIZE - (va + fsz)))
    # the kernel's loader applies the R_AARCH64_RELATIVE relocations; without
    # this every relocated pointer in .data.rel.ro would still hold its
    # pre-link value, so the patched string table would never be seen
    apply_rela(mu, d, ephoff, ephn)
    # video state used by the renderer: 16bpp into FB
    mu.mem_write(BIG + 0xb8, struct.pack("<I", 1))
    mu.mem_write(BIG + 0x78, struct.pack("<Q", FB))
    mu.mem_write(0x15fef8, struct.pack("<Q", BIG))
    mu.mem_write(0x15fdc0, struct.pack("<Q", 0x4008000))     # stack guard global
    add_syscall_emu(mu, d)
    install_plt(mu, pltmap)
    return mu, d

def apply_rela(mu, d, ephoff, ephn):
    """write base(0) + addend for every R_AARCH64_RELATIVE, like ld.so does"""
    dyn = None
    for i in range(ephn):
        t, fl, off, va, pa, fsz, msz, al = struct.unpack_from("<IIQQQQQQ", d, ephoff + i * 56)
        if t == 2:
            dyn = off
    if dyn is None:
        return 0
    tags, o = {}, dyn
    while True:
        tag, val = struct.unpack_from("<QQ", d, o); o += 16
        if tag == 0:
            break
        tags.setdefault(tag, []).append(val)
    rela, sz = tags.get(7, [0])[0], tags.get(8, [0])[0]
    n = 0
    for i in range(sz // 24):
        ro, ri, ad = struct.unpack_from("<QQQ", d, rela + i * 24)
        if (ri & 0xFFFFFFFF) != 1027 or ro + 8 > MOD_SIZE:
            continue
        mu.mem_write(ro, struct.pack("<Q", ad))
        n += 1
    return n

SYSCALLS = []

def rd(mu, a, n):
    return bytes(mu.mem_read(a, n))

def cstr(mu, p, n=256):
    if p == 0:
        return b""
    out = b""
    for k in range(n):
        c = rd(mu, p + k, 1)
        if c == b"\0":
            break
        out += c
    return out

def add_syscall_emu(mu, d):
    (eid, et, em, ev, ent, ephoff, eshoff, efl, eeh, epe, ephn, eshe, echn, esh) = \
        struct.unpack_from("<16sHHIQQQIHHHHHH", d, 0)
    seg = None
    for i in range(ephn):
        t, fl, off, va, pa, fsz, msz, al = struct.unpack_from("<IIQQQQQQ", d, ephoff + i * 56)
        if t == 1 and 0x140000 <= va < MOD_SIZE:
            seg = (off, va, fsz)
    if seg is None:
        return
    off, va, fsz = seg
    sites = [va + (k - off) for k in range(off, off + fsz, 4) if d[k:k + 4] == b"\x01\x00\x00\xd4"]
    base = [0x5000000]

    def cb(u, addr, size, ud):
        nr = u.reg_read(UC_ARM64_REG_X8)
        x0 = u.reg_read(UC_ARM64_REG_X0)
        x1 = u.reg_read(UC_ARM64_REG_X1)
        if nr == 56:                                        # openat
            p = cstr(u, x1, 128)
            u.reg_write(UC_ARM64_REG_X0, 3 if p == b"/proc/self/exe" else -2)
        elif nr == 222:                                     # mmap
            ln = u.reg_read(UC_ARM64_REG_X1)
            of = u.reg_read(UC_ARM64_REG_X5)
            rnd = (ln + 0xFFF) & ~0xFFF
            a = base[0]
            base[0] += rnd + 0x1000
            u.mem_map(a, rnd, UC_PROT_ALL)
            u.mem_write(a, bytes(d[of:of + ln]))
            u.reg_write(UC_ARM64_REG_X0, a)
        elif nr == 57:
            u.reg_write(UC_ARM64_REG_X0, 0)
        else:
            u.reg_write(UC_ARM64_REG_X0, -38)

    for a in sites:
        mu.mem_write(a, b"\x1f\x20\x03\xd5")
        mu.hook_add(UC_HOOK_CODE, cb, None, a, a + 3)

# ---------------------------------------------------------------- PLT emu
def install_plt(mu, pltmap):
    def ret(u, addr, size, ud):
        lr = u.reg_read(UC_ARM64_REG_X30)
        u.reg_write(UC_ARM64_REG_PC, lr)

    def cb(u, addr, size, ud):
        got, name = pltmap.get(addr, (0, "?"))
        a0 = u.reg_read(UC_ARM64_REG_X0)
        a1 = u.reg_read(UC_ARM64_REG_X1)
        a2 = u.reg_read(UC_ARM64_REG_X2)
        a3 = u.reg_read(UC_ARM64_REG_X3)
        a4 = u.reg_read(UC_ARM64_REG_X4)
        a5 = u.reg_read(UC_ARM64_REG_X5)
        a6 = u.reg_read(UC_ARM64_REG_X6)
        if name == "strlen":
            r = len(cstr(u, a0, 4096))
        elif name == "strcpy":
            s = cstr(u, a1, 4096) + b"\0"
            u.mem_write(a0, s)
            r = a0
        elif name == "strncpy":
            s = cstr(u, a1, a2) + b"\0"
            u.mem_write(a0, s)
            r = a0
        elif name == "strcat":
            s = cstr(u, a0, 4096)
            t = cstr(u, a1, 4096) + b"\0"
            u.mem_write(a0 + len(s), t)
            r = a0
        elif name in ("strncat", "__strncat_chk"):
            s = cstr(u, a0, 4096)
            t = cstr(u, a1, a2) + b"\0"
            u.mem_write(a0 + len(s), t)
            r = a0
        elif name == "memset":
            u.mem_write(a0, bytes([a1 & 0xFF]) * a2)
            r = a0
        elif name in ("memcpy", "memmove"):
            u.mem_write(a0, rd(u, a1, a2))
            r = a0
        elif name in ("memcmp",):
            r = 0
        elif name in ("__sprintf_chk", "sprintf", "snprintf", "__snprintf_chk"):
            # __sprintf_chk(dst, flag, dstlen, fmt, ...)  /  sprintf(dst, fmt, ...)
            if name in ("__sprintf_chk", "__snprintf_chk"):
                dst, ln, fmt = a0, a2, a3
                args = [a4, a5, a6, rd(u, u.reg_read(UC_ARM64_REG_SP), 32)]
            else:
                dst, ln, fmt = a0, 1 << 20, a1
                args = [a2, a3, a4, rd(u, u.reg_read(UC_ARM64_REG_SP), 32)]
            s = do_format(u, cstr(u, fmt), args)
            u.mem_write(dst, s + b"\0")
            r = len(s)
        elif name in ("_Znam", "_Znwm", "malloc", "calloc", "_Znaj"):
            n = a0 if name != "calloc" else a0 * a1
            r = HEAP + (ud["hp"] if isinstance(ud, dict) else 0)
            hp = _bump[0]
            _bump[0] = (hp + n + 15) & ~15
            r = HEAP + hp
        elif name in ("_ZdlPv", "_ZdaPv", "free", "operator delete"):
            r = 0
        elif name == "__stack_chk_fail":
            raise RuntimeError("stack chk fail")
        else:
            r = 0
        u.reg_write(UC_ARM64_REG_X0, r & 0xFFFFFFFFFFFFFFFF)
        u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30))

    _bump[0] = 0x1000
    for start in pltmap:
        mu.hook_add(UC_HOOK_CODE, cb, None, start, start + 3)

_bump = [0x1000]

def do_format(u, fmt, args):
    """minimal printf: %s %d %u %c %x %*d %0*d %-Nd %.*s"""
    out = bytearray()
    ai = 0
    i = 0
    while i < len(fmt):
        c = fmt[i]
        if c != 0x25:
            out.append(c)
            i += 1
            continue
        i += 1
        if i < len(fmt) and fmt[i] == 0x25:
            out.append(0x25)
            i += 1
            continue
        width = 0
        star = False
        while i < len(fmt) and fmt[i] in b"*0123456789-+ ":
            if fmt[i] == 0x2A:
                width = args[ai]
                if width > 0x80000000:
                    width -= 1 << 32
                ai += 1
                star = True
            elif 0x30 <= fmt[i] <= 0x39:
                width = width * 10 + (fmt[i] - 0x30)
            i += 1
        conv = chr(fmt[i]) if i < len(fmt) else "?"
        i += 1
        if conv in ("z", "l", "h"):
            conv = chr(fmt[i]); i += 1
        if conv == "s":
            s = cstr(u, args[ai], 512); ai += 1
            if width > len(s):
                s = b" " * (width - len(s)) + s
            out += s
        elif conv in ("d", "i", "u", "x", "X"):
            v = args[ai] & 0xFFFFFFFF
            ai += 1
            if conv in ("d", "i") and v >= 0x80000000:
                v -= 1 << 32
            if conv in ("x", "X"):
                t = ("%x" % (v & 0xFFFFFFFF)) if conv == "x" else ("%X" % (v & 0xFFFFFFFF))
            else:
                t = "%d" % v
            if width > len(t):
                t = " " * (width - len(t)) + t
            out += t.encode()
        elif conv == "c":
            out.append(args[ai] & 0xFF); ai += 1
        else:
            pass
    return bytes(out)

# ---------------------------------------------------------------- helpers
def alloc(mu, n):
    p = HEAP + _bump[0]
    _bump[0] = (_bump[0] + n + 15) & ~15
    return p

def run(mu, addr, args, count=50_000_000):
    mu.reg_write(UC_ARM64_REG_SP, STACK)
    mu.reg_write(UC_ARM64_REG_X30, SENT)
    for i, a in enumerate(args):
        if i < 4:
            mu.reg_write(UC_ARM64_REG_X0 + i, a & 0xFFFFFFFFFFFFFFFF)
        else:
            mu.mem_write(STACK + 8 * (i - 4), struct.pack("<Q", a))
    mu.emu_start(addr, SENT, count=count)
    return mu.reg_read(UC_ARM64_REG_X0)

def dump_list(mu, lp, depth=0, seen=None):
    if seen is None:
        seen = set()
    if lp == 0 or lp in seen:
        return
    seen.add(lp)
    tail = struct.unpack("<Q", rd(mu, lp, 8))[0]
    f8 = struct.unpack("<Q", rd(mu, lp + 8, 8))[0]
    f10 = struct.unpack("<I", rd(mu, lp + 0x10, 4))[0]
    cnt = struct.unpack("<I", rd(mu, lp + 0x14, 4))[0]
    sel = struct.unpack("<I", rd(mu, lp + 0x18, 4))[0]
    arr = struct.unpack("<Q", rd(mu, lp + 0x20, 8))[0]
    f28 = struct.unpack("<Q", rd(mu, lp + 0x28, 8))[0]
    print("%sLIST@0x%x tail=0x%x f8=0x%x x=0x%x count=%d sel=%d arr=0x%x f28=0x%x" %
          ("  " * depth, lp, tail, f8, f10, cnt, sel, arr, f28))
    if arr and 0 < cnt < 200:
        for i in range(cnt):
            np = struct.unpack("<Q", rd(mu, arr + 8 * i, 8))[0]
            if np == 0:
                print("%s  [%d] null" % ("  " * depth, i))
                continue
            lab = struct.unpack("<Q", rd(mu, np, 8))[0]
            nid = struct.unpack("<I", rd(mu, np + 8, 4))[0]
            rend = struct.unpack("<Q", rd(mu, np + 0x10, 8))[0]
            f30 = struct.unpack("<Q", rd(mu, np + 0x30, 8))[0]
            f38 = struct.unpack("<I", rd(mu, np + 0x38, 4))[0]
            f3c = struct.unpack("<I", rd(mu, np + 0x3c, 4))[0]
            f40 = struct.unpack("<Q", rd(mu, np + 0x40, 8))[0]
            extra = ""
            if f30:
                try:
                    extra = " val=%d" % struct.unpack("<I", rd(mu, f30, 4))[0]
                except Exception:
                    pass
            print("%s  [%d] id=%-3d rend=0x%-6x label=0x%-7x %-30r [30]=0x%x%s [38]=%d [3c]=%d [40]=0x%x" %
                  ("  " * depth, i, nid, rend, lab, cstr(mu, lab, 48), f30, extra, f38, f3c, f40))
            dump_user(mu, lab, rend, np, "  " * depth + "     ")
    if tail:
        print("%s  -> tail fn 0x%x" % ("  " * depth, tail))

def dump_user(mu, lab, rend, np, ind):
    s = cstr(mu, lab, 48)
    try:
        print("%s  raw=%r" % (ind, s))
    except Exception:
        pass

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "patched"
    path = PATCHED if which == "patched" else ORIG
    pm = load_pltmap()
    print("# PLT stubs known:", len(pm))
    mu, d = setup(path, pm)
    # fabricated app state
    _bump[0] = 0x1000
    mu.mem_write(BIG, b"\0" * 0x400)
    # big [8] -> scratch region (used as `add x24, x24, #0x458`)
    sp = SCRATCH
    mu.mem_write(BIG + 8, struct.pack("<Q", sp))
    mu.mem_write(BIG + 0x40, struct.pack("<I", 0))     # layout flag
    # stack-local struct the draw routine uses (sp+0x88) -- emulate by using BIG
    try:
        rv = run(mu, 0x7F3E0, [BIG])
        print("# builder returned 0x%x" % rv)
    except UcError as e:
        print("UcError", e, "pc=0x%x" % mu.reg_read(UC_ARM64_REG_PC))
    # the layout is what the builder stored into BIG[0x10]?
    for off in (0x10, 0x18, 0x20, 0x88, 0x98, 0xa0):
        v = struct.unpack("<Q", rd(mu, BIG + off, 8))[0]
        print("BIG[0x%x] = 0x%x" % (off, v))
