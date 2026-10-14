"""page_preview.py -- render the PATCHED binary's real menu pages to PNG.

The pages are no longer guessed: the vendor's own main-menu builder (0x7F3E0)
constructs the whole tree, and every page object is picked out of it by its
label path.  That is what makes the 配置按键 page -- which an earlier version mistook for its
额外按键 sub-page -- impossible to mix up again.

Reproduced draw path (exactly what the vendor does):

    page = <object from the tree>
    page.tail(ctx, page)                       -- title / header / notes
    for i in 0..page.count-1:                  -- one node per row
        page.node[i].rend(ctx, node, sel == i) -- LR-4 == dispatcher blr

    0x7d7a8   shared list drawer   (every settings/key list)
    0x7fdc0   main-menu drawer

Usage: page_preview.py [name|all] [out.png]
       CJK=build/drastic.cjk SEL=-1 page_preview.py firm
"""
import struct, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "tools"), os.path.join(ROOT, "assets")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import page_sim as P
from unicorn import *
from unicorn.arm64_const import *
from PIL import Image

import config as C

BIN      = os.environ.get("CJK") or C.build("drastic.cjk")
CTXSZ    = 0x201C000
CTXBK    = 0x201C400
NAMES    = 0x201C800
CTXROOT  = 0x2100000
CTXROOT_N = 0x100000
KEYNAME  = 0x8b410          # (dst, idx) -> "KB %s"

FONT_8    = 0x162e58        # 8x8   -- the font every menu list runs with
FONT_15   = 0x160a50        # 9x15
FONT_10   = 0x165260        # 6x10

MAINB     = 0x7F3E0         # the vendor's main-menu builder: builds the tree
DISP_SUB  = 0x7d7a8         # shared list drawer (blr x3)
DISP_MAIN = 0x7fdc0         # main-menu drawer

# name -> label path from the root
PAGES = {
    "main":  [],
    "video": ["更改选项"],
    "opt":   ["更改选项", "视频选项"],
    "keys":  ["配置按键"],
    "keysx": ["配置按键", "额外按键"],
    "firm":  ["配置固件"],
}

def u32(mu, a): return struct.unpack("<I", P.rd(mu, a, 4))[0]
def u64(mu, a): return struct.unpack("<Q", P.rd(mu, a, 8))[0]

def s_at(mu, a, n=48):
    try: b = bytes(mu.mem_read(a, n))
    except Exception: return "?"
    b = b.split(b"\0")[0]
    try: return b.decode("gbk")
    except Exception: return b.decode("latin1")

def install_help(mu):
    """emulate the vendor's key-name formatter."""
    def cb(u, addr, size, ud):
        if addr == KEYNAME:
            dst = u.reg_read(UC_ARM64_REG_X0)
            idx = u.reg_read(UC_ARM64_REG_X1) & 0xFFFF
            n = KB[idx % len(KB)]
            u.mem_write(dst, n + b"\0")
            u.reg_write(UC_ARM64_REG_X0, dst)
        u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_X30))
    mu.hook_add(UC_HOOK_CODE, cb, None, KEYNAME, KEYNAME + 3)

KB = [b"Unmapped", b"KB Up", b"KB Down", b"KB Left", b"KB Right",
      b"KB Enter", b"KB Shift", b"KB Space", b"KB Tab", b"JS3 Hat 14",
      b"JS2 Hat 2a", b"JS1 Btn A", b"KB Esc", b"KB Ctrl", b"KB Alt",
      b"JS3 Hat 2", b"JS2 Btn B", b"KB F1", b"KB F2", b"KB Backspace"]

def build_tree(mu):
    """run the vendor's main-menu builder and index every page by path."""
    P._bump[0] = 0x1000
    mu.mem_write(P.BIG, b"\0" * 0x800)
    mu.mem_write(P.BIG + 8, struct.pack("<Q", P.SCRATCH))
    mu.mem_write(P.BIG + 0x40, struct.pack("<I", 0))
    mu.mem_write(P.BIG + 0xb8, struct.pack("<I", 1))
    mu.mem_write(P.BIG + 0x78, struct.pack("<Q", P.FB))
    mu.mem_write(0x15fef8, struct.pack("<Q", P.BIG))
    mu.mem_write(0x15fdc0, struct.pack("<Q", 0x4008000))
    mu.mem_write(P.FONT_SLOT, struct.pack("<Q", FONT_8))
    mu.mem_write(P.SCRATCH, b"\0" * 0x1000)
    mu.mem_write(NAMES, b"\0" * 0x200)

    top = P.run(mu, MAINB, [P.BIG])

    found = {}
    def walk(p, path, depth):
        if depth > 3: return
        try: tail = u64(mu, p)
        except Exception: return
        if not (0x79000 <= tail < 0x7b000): return
        found["/".join(path)] = p
        cnt = u32(mu, p + 0x14); arr = u64(mu, p + 0x20)
        for i in range(min(cnt, 40)):
            try: np = u64(mu, arr + 8 * i)
            except Exception: return
            if np == 0: continue
            sub = u64(mu, np + 0x30)
            if sub and 0x2000020 <= sub < 0x3000000:
                walk(sub, path + [s_at(mu, u64(mu, np)).strip()], depth + 1)
    walk(top, [], 0)

    nm = os.environ.get("NAME")                 # pretend the user typed a name
    if nm:
        p = found["配置固件"]
        np = u64(mu, u64(mu, p + 0x20) + 0)
        mu.mem_write(u64(mu, np + 0x30), nm.encode("gbk") + b"\0")
    return found

def draw_page(mu, found, key, sel=-9):
    p = found["/".join(PAGES[key])]
    # XO emulates the device: the page field the tail reads as its x base does
    # NOT hold the builder's value on hardware (measured 88, not 256).
    if os.environ.get("XO"):
        mu.mem_write(p + 0x10, struct.pack("<I", int(os.environ["XO"])))
    cnt = u32(mu, p + 0x14); arr = u64(mu, p + 0x20)
    tail = u64(mu, p); xo = u32(mu, p + 0x10)
    disp = DISP_MAIN if key == "main" else DISP_SUB
    print("# %-6s page=0x%-8x tail=0x%-6x x_origin=%-4d count=%d disp=0x%x"
          % (key, p, tail, xo, cnt, disp))

    mu.mem_write(P.FB, b"\0" * (800 * 480 * 2))

    def call(addr, a0, a1, a2, lr):
        mu.reg_write(UC_ARM64_REG_SP, P.STACK)
        mu.reg_write(UC_ARM64_REG_X0, a0)
        mu.reg_write(UC_ARM64_REG_X1, a1)
        mu.reg_write(UC_ARM64_REG_X2, a2)
        mu.reg_write(UC_ARM64_REG_X30, lr)
        try:
            mu.emu_start(addr, lr, count=60_000_000)
        except UcError as e:
            print("   ! UcError %s pc=0x%x row %s" %
                  (e, mu.reg_read(UC_ARM64_REG_PC), getattr(call, "i", "?")))

    if tail:
        call(tail, CTXSZ, p, 0, P.SENT)
    for i in range(cnt):
        np = u64(mu, arr + 8 * i)
        if np == 0: continue
        s = (i == u32(mu, p + 0x18)) if sel == -9 else (i == sel)
        call.i = i
        call(u64(mu, np + 0x10), CTXSZ, np, 1 if s else 0, disp + 4)
    return p

def fb_image(mu, scale=1):
    fb = bytes(mu.mem_read(P.FB, 800 * 480 * 2))
    u16 = memoryview(fb).cast("H")
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    px = img.load()
    for y in range(480):
        row = y * 800
        for x in range(800):
            v = u16[row + x]
            px[x, y] = ((v >> 11) & 31) * 8, ((v >> 5) & 63) * 4, (v & 31) * 8
    if scale != 1:
        img = img.resize((800 * scale, 480 * scale), Image.NEAREST)
    return img

def dump_rows(mu, found, key):
    p = found["/".join(PAGES[key])]
    cnt = u32(mu, p + 0x14); arr = u64(mu, p + 0x20)
    for i in range(cnt):
        np = u64(mu, arr + 8 * i)
        if np == 0: continue
        print("    row %-2d %r rend=0x%x" % (i, s_at(mu, u64(mu, np)), u64(mu, np + 0x10)))

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    out = sys.argv[2] if len(sys.argv) > 2 else None
    sel = int(os.environ.get("SEL", "-9"))
    pm = P.load_pltmap()
    mu, d = P.setup(BIN, pm)
    mu.mem_map(CTXROOT, CTXROOT_N, UC_PROT_ALL)
    mu.mem_write(CTXROOT, b"\0" * CTXROOT_N)
    mu.mem_write(CTXSZ, b"\0" * 0x400)
    mu.mem_write(CTXSZ + 0x00, struct.pack("<Q", CTXROOT))
    install_help(mu)
    found = build_tree(mu)
    print("pages found:", " | ".join(sorted(found)))
    todo = list(PAGES) if which == "all" else [which]
    for k in todo:
        draw_page(mu, found, k, sel)
        if which == "all" and k in ("keys", "firm"):
            dump_rows(mu, found, k)
        fn = out or ("pv_%s.png" % k)
        fb_image(mu).save(fn)
        print("   -> %s" % fn)
