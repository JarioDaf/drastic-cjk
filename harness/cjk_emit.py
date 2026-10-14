"""cjk_emit.py -- log exactly what the CJK layer hands to the host renderer.

Hooks the pristine body (0x87F04) and fill_rect body (0x88434) *without*
touching PC, so the real page is drawn and every emitted primitive is
recorded.  With base == 0 the LR-4 of the outermost call is the dispatcher
site, which is what the hook itself sees.

Usage: cjk_emit.py [main|firm|keys|opt|video|all]
       CJK=build/drastic.cjk cjk_emit.py all
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
import page_preview as PV

BODY_TEXT = 0x87F04
BODY_FILL = 0x88434

def install(mu, log):
    def dt(u, a, sz, ud):
        fp = PV.u64(u, P.FONT_SLOT)
        fw = fh = 0
        if fp:
            try: fw, fh = struct.unpack("<II", P.rd(u, fp, 8))
            except Exception: pass
        log.append(("T", u.reg_read(UC_ARM64_REG_W1), u.reg_read(UC_ARM64_REG_W2),
                    u.reg_read(UC_ARM64_REG_W3), u.reg_read(UC_ARM64_REG_W4),
                    P.cstr(u, u.reg_read(UC_ARM64_REG_X0), 40), (fw, fh)))
    def fl(u, a, sz, ud):
        log.append(("F", u.reg_read(UC_ARM64_REG_W0), u.reg_read(UC_ARM64_REG_W1),
                    u.reg_read(UC_ARM64_REG_W2), u.reg_read(UC_ARM64_REG_W3),
                    u.reg_read(UC_ARM64_REG_W4), None, None))
    mu.hook_add(UC_HOOK_CODE, dt, None, BODY_TEXT, BODY_TEXT + 3)
    mu.hook_add(UC_HOOK_CODE, fl, None, BODY_FILL, BODY_FILL + 3)

def main(which):
    pm = P.load_pltmap()
    mu, d = P.setup(PV.BIN, pm)
    mu.mem_map(PV.CTXROOT, PV.CTXROOT_N, UC_PROT_ALL)
    mu.mem_write(PV.CTXROOT, b"\0" * PV.CTXROOT_N)
    mu.mem_write(PV.CTXSZ, b"\0" * 0x400)
    mu.mem_write(PV.CTXSZ, struct.pack("<Q", PV.CTXROOT))
    PV.install_help(mu)
    log = []
    install(mu, log)
    found = PV.build_tree(mu)
    lp = found["/".join(PV.PAGES[which])]
    disp = PV.DISP_MAIN if which == "main" else PV.DISP_SUB
    arr = PV.u64(mu, lp + 0x20); cnt = PV.u32(mu, lp + 0x14)
    sel = PV.u32(mu, lp + 0x18); tail = PV.u64(mu, lp)
    print("# %s count=%d sel=%d" % (which, cnt, sel))
    def call(addr, a0, a1, a2, lr):
        mu.reg_write(UC_ARM64_REG_SP, P.STACK); mu.reg_write(UC_ARM64_REG_X0, a0)
        mu.reg_write(UC_ARM64_REG_X1, a1); mu.reg_write(UC_ARM64_REG_X2, a2)
        mu.reg_write(UC_ARM64_REG_X30, lr)
        try: mu.emu_start(addr, lr, count=60_000_000)
        except UcError as e: print("   ! %s pc=0x%x" % (e, mu.reg_read(UC_ARM64_REG_PC)))
    if tail:
        del log[:]; call(tail, PV.CTXSZ, lp, 0, P.SENT)
        print(" -- tail 0x%x" % tail); show(log, "   ")
    for i in range(cnt):
        np = PV.u64(mu, arr + 8 * i)
        if np == 0: continue
        rend = PV.u64(mu, np + 0x10)
        lab = P.cstr(mu, PV.u64(mu, np), 32)
        del log[:]
        call(rend, PV.CTXSZ, np, 1 if i == sel else 0, disp + 4)
        print(" -- [%d] %r rend=0x%x" % (i, lab, rend))
        show(log, "   ")

def show(log, ind):
    for e in log:
        if e[0] == "T":
            print("%sT fg=0x%04x bg=0x%04x x=%-5d y=%-5d cell=%s %r" %
                  (ind, e[1], e[2], e[3], e[4], e[6], e[5][:32]))
        elif e[0] == "F":
            print("%sF color=0x%08x x=%-5d y=%-5d w=%-5d h=%-5d" %
                  (ind, e[1], e[2], e[3], e[4], e[5]))

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "firm"
    for k in (["main", "firm", "keys", "opt", "video"] if which == "all" else [which]):
        main(k)
