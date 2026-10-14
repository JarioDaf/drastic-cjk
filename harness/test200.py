"""test200.py -- menu regression.

Everything is measured against the *patched* binary, never against our own
intent, and the pages are taken from the vendor's own menu tree (an earlier
mistake was to believe a hand written list of builders).

  1. drift guard   the ROWTAB compiled into cjk.c is exactly what the tree
                   walk produces -- including the 配置按键 page an earlier
                   attempt missed, plus the four OFF_ANY rows whose label is
                   the vendor's own "A", "B", "X", "Y".
  2. one font size every glyph the CJK layer emits is a single 16x16 cell.
                   This is what makes a *missing* interception visible: an
                   unhandled site falls back to the host font and emits 8x8.
  3. on screen     no cell is emitted off the 800x480 canvas.
  4. no clipping   the leading run of cells at the page's label column is as
                   long as the row's own label.
  5. value columns values are right aligned to the page's vr1 / vr2.
  6. the layout    row y strictly increases, rows never overlap, the trailing
                   action group gap is applied.
  7. key pages     both the 配置按键 page (19 rows + 5 actions) and its
                   额外按键 sub-page (20 + 4) carry two value columns.
  8. vendor labels the OFF_ANY rows land on their page's grid.
  9. editor row    the firmware username row is laid out in the value column
                   in BOTH states -- the "small name on the left" ghost
                   left behind came from the not-selected branch.
 10. page title    the firmware title is 固件设置, still at table offset 0x94.
 11. colour swatch the vendor paints it at the hard-coded vendor y=296; it
                   must end up on 喜爱颜色's row (page 1 row 2), just right of
                   the value column -- not between the two "exit and save"
                   rows, which is exactly where vendor y 296 falls.
 12. device x base  the same swatch check with the page field the vendor's
                   tail reads frozen to the value measured on hardware (88,
                   not the harness's 256).  Earlier revisions keyed on
                   x == 536, so on the device neither ever fired.

Usage: CJK=build/drastic.cjk test200.py
"""
import re, struct, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, os.path.join(ROOT, "tools"), os.path.join(ROOT, "assets")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("NAME", "Drastic")        # give the editor row something to show
import page_sim as P
from unicorn import *
from unicorn.arm64_const import *
import page_preview as PV
import cjk_emit as CE
import gen_rowtab as GR

import config as C

BIN   = os.environ.get("CJK") or C.build("drastic.cjk")
DEVICE_XO = 88                 # the page field the tail reads, as measured on hardware
MENU  = open(C.MENU_BIN, "rb").read()
CELL  = 16
OFF_ANY = 0xFFFF
RECT_BODY = 0x88434      # fill_rect's pristine body: args are post-rewrite here
RECTS = []

SRC = open(os.path.join(ROOT, "src", "cjk.c"), encoding="utf-8", errors="replace").read()

def c_pages():
    """PAGES[] as cjk.c has it: page id -> (name, top,pitch,lx,lmax,vr1,vr2,edt,grp,gap)"""
    blk = SRC.split("static const page_t PAGES[] = {", 1)[1].split("};", 1)[0]
    out = {}
    for m in re.finditer(r"/\*\s*(\d+)\s+(\w+)\s*\*/\s*\{([^}]*)\}", blk):
        f = [t.strip() for t in m.group(3).split(",")]
        out[int(m.group(1))] = (m.group(2).lower(), tuple(int(t, 0) for t in f if t))
    return out

def c_rowtab():
    blk = SRC.split("static const rowdef_t ROWTAB[] = {", 1)[1].split("};", 1)[0]
    return [(OFF_ANY if a == "OFF_ANY" else int(a, 16), int(y), int(p), int(r))
            for a, y, p, r in re.findall(
                r"\{\s*(OFF_ANY|0x[0-9a-fA-F]+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}", blk)]

PAGES = c_pages()
ROWS  = c_rowtab()

def geom(pid):
    return PAGES[pid][1]

def row_y(pid, ri):
    top, pitch, lx, lmax, vr1, vr2, edt, grp, gap = geom(pid)
    return top + pitch * ri + (gap if ri >= grp else 0)

def label_cells(off):
    s = MENU[off:MENU.find(b"\0", off)]
    i, cnt = 0, 0
    while i < len(s):
        i += 2 if s[i] >= 0x80 else 1
        cnt += 1
    return cnt

# ---------------------------------------------------------------- emulator
LOG = []

def render(mu, found, key, sel):
    """draw `key`, return [(row, [(x, y, (fw, fh)), ...]), ...]"""
    p   = found["/".join(PV.PAGES[key])]
    cnt = PV.u32(mu, p + 0x14)
    arr = PV.u64(mu, p + 0x20)
    tail = PV.u64(mu, p)
    disp = PV.DISP_MAIN if key == "main" else PV.DISP_SUB
    del RECTS[:]                      # the swatch is painted by the page tail

    def call(addr, a0, a1, a2, lr):
        mu.reg_write(UC_ARM64_REG_SP, P.STACK)
        mu.reg_write(UC_ARM64_REG_X0, a0)
        mu.reg_write(UC_ARM64_REG_X1, a1)
        mu.reg_write(UC_ARM64_REG_X2, a2)
        mu.reg_write(UC_ARM64_REG_X30, lr)
        mu.emu_start(addr, lr, count=60_000_000)

    if tail:
        call(tail, PV.CTXSZ, p, 0, P.SENT)
    rows = []
    for i in range(cnt):
        np = PV.u64(mu, arr + 8 * i)
        if np == 0: continue
        del LOG[:]
        call(PV.u64(mu, np + 0x10), PV.CTXSZ, np, 1 if i == sel else 0, disp + 4)
        rows.append((i, [(e[3], e[4], e[6]) for e in LOG if e[0] == "T"]))
    return rows

def main():
    fails = []

    def bad(msg):
        fails.append(msg); print("FAIL " + msg)

    # 1 ------------------------------------------------------ drift guard
    pm = P.load_pltmap()
    mu, d = P.setup(BIN, pm)
    vendor = GR.collect(mu)
    if vendor != ROWS:
        bad("ROWTAB in cjk.c differs from the vendor menu tree (%d vs %d)"
            % (len(vendor), len(ROWS)))
    else:
        print("OK   ROWTAB matches the vendor tree (%d rows, %d pages)"
              % (len(ROWS), len({r[2] for r in ROWS})))

    for need in ("S_EDT_0L", "S_EDT_0V", "OFF_ANY", "sticky",
                 "0x7d7a8", "0x7fdc0"):
        if need not in SRC:
            bad("%s not wired into cjk.c" % need)

    # 2..9 ---------------------------------------------------- live render
    mu, d = P.setup(BIN, pm)
    mu.mem_map(PV.CTXROOT, PV.CTXROOT_N, UC_PROT_ALL)
    mu.mem_write(PV.CTXROOT, b"\0" * PV.CTXROOT_N)
    mu.mem_write(PV.CTXSZ, b"\0" * 0x400)
    mu.mem_write(PV.CTXSZ, struct.pack("<Q", PV.CTXROOT))
    PV.install_help(mu)
    CE.install(mu, LOG)

    def on_rect(mu, addr, size, ud):
        RECTS.append((mu.reg_read(UC_ARM64_REG_X0) & 0xFFFFFFFF,
                      mu.reg_read(UC_ARM64_REG_X1) & 0xFFFFFFFF,
                      mu.reg_read(UC_ARM64_REG_X2) & 0xFFFFFFFF,
                      mu.reg_read(UC_ARM64_REG_X3) & 0xFFFFFFFF,
                      mu.reg_read(UC_ARM64_REG_X4) & 0xFFFFFFFF))
    mu.hook_add(UC_HOOK_CODE, on_rect, None, RECT_BODY, RECT_BODY)

    found = PV.build_tree(mu)

    # every page in PAGES[] must be reachable in the tree
    for pid, (name, g) in sorted(PAGES.items()):
        if name not in PV.PAGES:
            bad("page %d (%s) has no path in page_preview.PAGES" % (pid, name))

    for pid, (name, _) in sorted(PAGES.items()):
        top, pitch, lx, lmax, vr1, vr2, edt, grp, gap = geom(pid)
        want = [(off, y, r) for off, y, p, r in ROWS if p == pid]
        for sel in ((0, -1) if name == "firm" else (-9,)):
            rows = render(mu, found, name, sel)
            if len(rows) != len(want):
                bad("%s sel=%d row count %d != %d" % (name, sel, len(rows), len(want)))
                continue
            prev_y, n1, n2, nany = None, 0, 0, 0
            for (ri, cells), (off, sy, rr) in zip(rows, want):
                oy = row_y(pid, rr)
                for x, y, cell in cells:                       # 2. font size
                    if cell != (CELL, CELL):
                        bad("%s sel=%d row %d: glyph cell %s != (16,16)"
                            % (name, sel, ri, cell)); break
                for x, y, cell in cells:                       # 3. on canvas
                    if not (0 <= x <= 800 - CELL and 0 <= y <= 480 - CELL):
                        bad("%s sel=%d row %d: glyph at (%d,%d) off canvas"
                            % (name, sel, ri, x, y)); break
                ys = sorted({c[1] for c in cells})             # 4. row y
                if ys and ys != [oy]:
                    bad("%s sel=%d row %d: emitted at y=%s, expected %d"
                        % (name, sel, ri, ys, oy))
                if prev_y is not None and oy < prev_y + CELL:
                    bad("%s sel=%d row %d: y=%d overlaps previous" % (name, sel, ri, oy))
                prev_y = oy
                xs = {c[0] for c in cells}
                if off == OFF_ANY:                             # 8. vendor label
                    if lx not in xs:
                        bad("%s row %d: vendor label not at lx=%d" % (name, ri, lx))
                    else:
                        nany += 1
                else:                                          # 5. label intact
                    run, cx, exp = 0, lx, label_cells(off)
                    while cx in xs:
                        run += 1; cx += CELL
                    if run != exp:
                        bad("%s sel=%d row %d: label run %d cells, needs %d (clipped)"
                            % (name, sel, ri, run, exp))
                # value columns: split the row into maximal runs of adjacent
                # cells.  The run that starts at lx is the label -- and on an
                # action row ("exit and save", "delete config") that label is
                # 8 or 9 cells long, so a naive "x >= lx + 6*CELL" cut would
                # mistake the label's own tail for a value.  Everything after
                # the label run is a value run.
                runs, cur = [], []
                for x in sorted(xs):
                    if cur and x - cur[-1] <= CELL:
                        cur.append(x)
                    else:
                        if cur: runs.append(cur)
                        cur = [x]
                if cur: runs.append(cur)
                grp_e = [r[-1] + CELL for r in runs if r[0] != lx]
                if vr1:
                    ok = {vr1} | ({vr2} if vr2 else set())
                    for e in grp_e:
                        if e not in ok:
                            bad("%s sel=%d row %d: value right edge %d not in %s"
                                % (name, sel, ri, e, sorted(ok)))
                        elif e == vr1: n1 += 1
                        else:          n2 += 1
                elif grp_e:
                    pass
            print("OK   %-5s sel=%-2d %2d rows, %d labels by vendor text, "
                  "%d values col1%s" % (name, sel, len(rows), nany, n1,
                                        (", %d col2" % n2) if n2 else ""))
            if name == "firm" and sel == -1:
                if n1 == 0:
                    bad("firm: the deselected username is not in the value column")
            if name in ("keys", "keysx"):
                if n2 == 0:
                    bad("%s page has no second value column" % name)
                if grp < 0xFFFF and gap:
                    a_, b_ = row_y(pid, grp - 1), row_y(pid, grp)
                    if b_ - a_ != pitch + gap:
                        bad("%s group gap not applied (%d)" % (name, b_ - a_))

    # 10 ------------------------------------------------- firmware page title
    # "固件用户设置" was shortened to "固件设置"; the offset is unchanged, so
    # title_page() must still map it to the firmware page.
    t_end = MENU.find(b"\0", 0x94)
    title = MENU[0x94:t_end].decode("gb2312", "replace")
    if title != "固件设置":
        bad("firmware title is %r, expected '固件设置'" % title)
    elif "OFF_T_FW    0x94u" not in SRC:
        bad("cjk.c no longer defines the firmware title offset as 0x94")
    else:
        print("OK   firmware title is 固件设置 (%d B at table offset 0x94)" % len(MENU[0x94:t_end]))

    # 11 ------------------------------------------- the favourite-colour swatch
    # The vendor paints it in the page tail at the hard-coded vendor y=296,
    # which lands between our rows 6 and 7 once the list is spread to the
    # 16 px grid.  cjk_rect must re-anchor it to 喜爱颜色's row (page 1 row 2)
    # and park it just right of the value column.
    render(mu, found, "firm", -9)
    top, pitch, lx, lmax, vr1, vr2, edt, grp, gap = geom(1)
    wx, wy = vr1 + 8, row_y(1, 2) + (CELL - 8) // 2
    want = {(16, 8, wx, wy), (14, 6, wx + 1, wy + 1)}
    got  = {(w, h, x, y) for (_c, x, y, w, h) in RECTS}
    if got != want:
        bad("colour swatch at %s, expected %s (vendor y 296 must not be used)"
            % (sorted(got), sorted(want)))
    else:
        print("OK   colour swatch on the 喜爱颜色 row: frame (%d,%d) 16x8 + core 14x6"
              % (wx, wy))

    # 12 ------------------------- the same, under the DEVICE x base (88)
    # The tail computes x = page_field + 0x118.  The harness builds that page
    # itself, so it sees 256 and gets 536; the device held 88 and painted the
    # swatch at 368.  The pair was dropped / relocated only when
    # x == 536 -- so on hardware the swatch never moved.  Freeze the field to
    # the measured device value and require the swatch on 喜爱颜色's row.
    fwnode = found["配置固件"]
    mu.mem_write(fwnode + 0x10, struct.pack("<I", DEVICE_XO))
    render(mu, found, "firm", -9)
    got2 = {(w, h, x, y) for (_c, x, y, w, h) in RECTS}
    if got2 != want:
        bad("device x base %d: swatch at %s, expected %s"
            % (DEVICE_XO, sorted(got2), sorted(want)))
    else:
        print("OK   colour swatch still on 喜爱颜色's row with the device x base (%d)"
              % DEVICE_XO)
    mu.mem_write(fwnode + 0x10, struct.pack("<I", 256))

    print()
    if fails:
        print("menu regression: FAIL (%d)" % len(fails)); sys.exit(1)
    print("menu regression: PASS")

if __name__ == "__main__":
    main()
