"""Walk the vendor's real menu tree; print every row as (label_off, y, rend)."""
import struct, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "tools"), os.path.join(ROOT, "assets")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import page_sim as P
from unicorn import *
from unicorn.arm64_const import *

import config as C

BIN = os.environ.get("CJK") or C.build("drastic.cjk")
STRTAB = 0x152000
CTXROOT = 0x2100000; CTXROOT_N = 0x100000

def u32(mu, a): return struct.unpack("<I", P.rd(mu, a, 4))[0]
def u64(mu, a): return struct.unpack("<Q", P.rd(mu, a, 8))[0]

def s_at(mu, a, n=48):
    try: b = bytes(mu.mem_read(a, n))
    except Exception: return "?"
    b = b.split(b"\0")[0]
    try: return b.decode("gbk")
    except Exception: return b.decode("latin1")

def off_of(mu, a, base):
    if base + STRTAB <= a < base + STRTAB + 1559:
        return a - (base + STRTAB)
    return None

seen = set()
def dump(mu, p, base, depth, tag=""):
    if p < 0x2000020 or p in seen or depth > 3: return
    if p & 7: return
    seen.add(p)
    try:
        tail = u64(mu, p)
    except Exception:
        return
    if not (0x79000 <= tail < 0x7b000): return      # not a page object
    xo = u32(mu, p + 0x10); cnt = u32(mu, p + 0x14); arr = u64(mu, p + 0x20)
    print("%sPAGE 0x%-8x tail=0x%-6x x_origin=%-4d count=%-2d %s"
          % ("  " * depth, p, tail, xo, cnt, tag))
    for i in range(min(cnt, 40)):
        try: np = u64(mu, arr + 8 * i)
        except Exception: break
        if np == 0: continue
        labp = u64(mu, np); key = u32(mu, np + 8)
        rend = u64(mu, np + 0x10); fn18 = u64(mu, np + 0x18)
        sub = u64(mu, np + 0x30)
        o = off_of(mu, labp, base)
        print("%s  row %-2d key=%-3d y=%-4d rend=0x%-6x f18=0x%-6x | off=%-6s | %r"
              % ("  " * depth, i, key, key * 8, rend, fn18,
                 ("0x%03x" % o) if o is not None else "-", s_at(mu, labp)))
        if sub and 0x2000020 <= sub < 0x3000000:
            dump(mu, sub, base, depth + 1, "sub of %r" % s_at(mu, labp))

pm = P.load_pltmap()
mu, d = P.setup(BIN, pm)
base = P.getbase(mu) if hasattr(P, "getbase") else 0
mu.mem_map(CTXROOT, CTXROOT_N, UC_PROT_ALL)
mu.mem_write(P.BIG + 0xb8, struct.pack("<I", 1))
mu.mem_write(P.BIG + 0x78, struct.pack("<Q", P.FB))
mu.mem_write(0x15fef8, struct.pack("<Q", P.BIG))
mu.mem_write(0x15fdc0, struct.pack("<Q", 0x4008000))
mu.mem_write(P.BIG + 8, struct.pack("<Q", P.SCRATCH))
P._bump[0] = 0x1000
top = P.run(mu, 0x7F3E0, [P.BIG])
print("base = 0x%x" % base)
dump(mu, top, base, 0, "MAIN")
