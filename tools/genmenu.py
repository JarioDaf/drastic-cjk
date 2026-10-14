"""genmenu.py -- build the Chinese menu string table for DraStic.

Reads the pristine binary, verifies every original string we intend to
replace, lays out the replacement strings (GB2312 encoded, padding chosen so
the *rendered cell count* is preserved -- the menu renderer derives highlight
boxes and value columns from it), locates every reference site and emits
    menu.bin       the flat string blob
    menu_sites.py  {OFFSETS, CODE_SITES, REL_SITES} for patch.py

Cell model (menu screens all use the built-in 8x8 font: rows advance by
`id * 8`, the only font with height 8):
    1 ASCII byte  -> 1 cell (8 px)
    1 CJK char    -> 1 cell (our injected glyphs advance exactly `cell` = 8 px)
so a string's rendered width in cells == len(chars).  Padding rules:
    'L'  label in a field   : keep left edge,  pad trailing spaces
    'R'  right-aligned value: keep right edge, pad leading spaces
    'P6' 6x10-font string   : pixel-preserving, trailing spaces rounded
    'X'  no padding (printf argument)
"""
import struct, json, os, sys
from capstone import *
from capstone.arm64 import *

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C

os.makedirs(C.BUILD, exist_ok=True)
d = open(C.require_src(), "rb").read()

def orig_str(addr):
    e = d.find(b"\0", addr)
    return d[addr:e].decode("latin1")

# ---------------------------------------------------------------- translations
# (addr, kind, expected original text (stripped), chinese)
E = [
    # ---- main menu -------------------------------------------------------
    (0x121EF8, 'L', "Change Options",            "更改选项"),
    (0x1217A8, 'L', "Configure Controls",        "配置按键"),
    (0x121F08, 'L', "Configure Firmware",        "配置固件"),
    (0x121F20, 'L', "Configure Cheats",          "配置金手指"),
    (0x121F38, 'L', "Load state",                "读取存档"),
    (0x121F48, 'L', "Save state",                "保存存档"),
    (0x121F58, 'L', "Load new game",             "载入新游戏"),
    (0x121F68, 'L', "Restart game",              "重启游戏"),
    (0x121F78, 'L', "Return to game",            "返回游戏"),
    (0x121F88, 'L', "Exit DraStic",              "退出DraStic"),
    # ---- screen titles / notes ------------------------------------------
    (0x121710, 'L', "Configure Options",             "选项设置"),
    (0x121728, 'L', "Configure Video Options",       "视频选项设置"),
    (0x121740, 'L', "Configure Firmware User Settings", "固件设置"),
    (0x121768, 'L', "(Note: changes take effect only", "（注：所有更改仅在"),
    (0x121788, 'L', "when a game is newly loaded)",    "新载入游戏后生效）"),
    (0x121F98, 'P6', "Version r2.5.2.2",         "版本 r2.5.2.2"),
    (0x121FB0, 'P6', "(No savestate)",           "（无存档）"),
    # ---- options screen ---------------------------------------------------
    (0x121BB0, 'L', "Frame skip type",           "跳帧方式"),
    (0x121BC8, 'L', "Frame skip value",          "跳帧数值"),
    (0x121BF0, 'L', "Safe frame skipping",       "安全跳帧"),
    (0x121C08, 'L', "Screen orientation",        "屏幕方向"),
    (0x121C20, 'L', "Screen swap",               "屏幕交换"),
    (0x121C38, 'L', "Mirror touchscreen",        "镜像触屏"),
    (0x121C50, 'L', "Fix main 2D screen",        "修正2D主屏"),
    (0x121C68, 'L', "Disable edge marking",      "禁用边缘标记"),
    (0x121C80, 'L', "High-resolution 3D",        "高分辨率3D"),
    (0x121C98, 'L', "Threaded 3D",               "多线程3D"),
    (0x121CB0, 'L', "Delete game-specific config", "删除游戏专属配置"),
    (0x121CD0, 'L', "Exit: save for all games",  "退出：保存所有游戏"),
    (0x121CF0, 'L', "Exit: save for this game",  "退出：保存当前游戏"),
    (0x121D10, 'L', "Exit without saving",       "退出且不保存"),
    (0x121D28, 'L', "Video options",             "视频选项"),
    (0x121D38, 'L', "Show speed",                "显示速度"),
    (0x121D50, 'L', "Enable sound",              "启用声音"),
    (0x121D68, 'L', "Fast forward",              "快进"),
    (0x121D80, 'L', "Compress savestates",       "压缩即时存档"),
    (0x121D98, 'L', "Snapshot in savestates",    "截图写入存档"),
    (0x121DB0, 'L', "Enable cheats",             "启用金手指"),
    (0x121DC8, 'L', "Uncompress ROMs",           "解压ROM"),
    (0x121DE0, 'L', "Preload ROMs",              "预载ROM"),
    (0x121DF8, 'L', "Backup in savestates",      "备份写入存档"),
    (0x121E10, 'L', "Speed override",            "速度覆盖"),
    (0x121E28, 'L', "Slot 2 Device",             "插槽2设备"),
    (0x121E40, 'L', "Restore default controls",  "恢复默认按键"),
    (0x121E60, 'L', "Extra Controls",            "额外按键"),
    # ---- firmware settings -------------------------------------------------
    (0x121E70, 'L', "Username",                  "用户名"),
    (0x121E90, 'L', "Language",                  "语言"),
    (0x121EA8, 'L', "Favorite Color",            "喜爱颜色"),
    (0x121EB8, 'L', "Birthday Month",            "生日月份"),
    (0x121ED0, 'L', "Birthday Day",              "生日日期"),
    (0x1217C0, 'L', "%s: Modify",                "%s：修改"),
    (0x1217D0, 'L', "%s: Unmap",                 "%s：取消映射"),
    # ---- file browser hints -------------------------------------------------
    (0x1218E0, 'L', "%s: select",                "%s：选择"),
    (0x1218F0, 'L', "%s: return to main menu",   "%s：返回主菜单"),
    (0x121908, 'L', "%s: go up directory",       "%s：返回上级目录"),
    (0x121920, 'L', "%s: switch display (%s)",   "%s：切换显示 (%s)"),
    # ---- cheat screen ---------------------------------------------------------
    (0x121B60, 'L', "%s: toggle cheat/folder    %s: return to main menu",
                                                 "%s：切换金手指/目录    %s：返回主菜单"),
    (0x121B98, 'X', "enabled",                   "启用"),
    (0x121BA0, 'X', "disabled",                  "禁用"),
    # ---- language values (right aligned, 19 cells) ----------------------------
    (0x122408, 'R', "Japanese", "日语"),
    (0x122420, 'R', "English",  "英语"),
    (0x122438, 'R', "French",   "法语"),
    (0x122450, 'R', "German",   "德语"),
    (0x122468, 'R', "Italian",  "意大利语"),
    (0x122480, 'R', "Spanish",  "西班牙语"),
    (0x122498, 'R', "Chinese",  "中文"),
    (0x1224B0, 'R', "Reserved", "保留"),
    # ---- months (right aligned, 19 cells) --------------------------------------
    (0x122168, 'R', "January",   "一月"),
    (0x122180, 'R', "February",  "二月"),
    (0x122198, 'R', "March",     "三月"),
    (0x1221B0, 'R', "April",     "四月"),
    (0x1221C8, 'R', "May",       "五月"),
    (0x1221E0, 'R', "June",      "六月"),
    (0x1221F8, 'R', "July",      "七月"),
    (0x122210, 'R', "August",    "八月"),
    (0x122228, 'R', "September", "九月"),
    (0x122240, 'R', "October",   "十月"),
    (0x122258, 'R', "November",  "十一月"),
    (0x122270, 'R', "December",  "十二月"),
    # ---- favorite colors (3 leading + text + 3 trailing = 22 cells) -------------
    (0x122288, 'R', "Light Slate Gray",   "浅石板灰"),
    (0x1222A0, 'R', "Redwood",            "红木色"),
    (0x1222B8, 'R', "Deep Chestnut",      "深栗色"),
    (0x1222D0, 'R', "M. Lavender Magenta","薰衣草紫"),
    (0x1222E8, 'R', "Persian Orange",     "波斯橙"),
    (0x122300, 'R', "Burlywood",          "原木色"),
    (0x122318, 'R', "Dark Khaki",         "深卡其色"),
    (0x122330, 'R', "Mantis",             "螳螂绿"),
    (0x122348, 'R', "Viridian",           "翡翠绿"),
    (0x122360, 'R', "Dark Sea Green",     "暗海绿"),
    (0x122378, 'R', "Moonstone Blue",     "月光蓝"),
    (0x122390, 'R', "Tufts Blue",         "塔夫茨蓝"),
    (0x1223A8, 'R', "Dark Cerulean",      "深蔚蓝"),
    (0x1223C0, 'R', "Toolbox",            "工具箱"),
    (0x1223D8, 'R', "Rich Lavender",      "浓薰衣草"),
    (0x1223F0, 'R', "Mulberry",           "桑葚紫"),
    # ---- slot-2 device / speed values (right aligned, 13 cells) -----------------
    (0x122858, 'R', "none",        "无"),
    (0x122868, 'R', "gba cart",    "GBA卡带"),
    (0x122878, 'R', "sram cart",   "SRAM卡带"),
    (0x122888, 'R', "rumble pack", "震动包"),
    (0x122898, 'R', "motion pack", "运动感应包"),
    (0x1228A8, 'R', "hb motion",   "自制感应包"),
    # ---- control names (left aligned, 20 cells) ----------------------------------
    (0x122678, 'L', "Enter Menu",          "进入菜单"),
    (0x122690, 'L', "Save State",          "保存状态"),
    (0x1226A8, 'L', "Load State",          "读取状态"),
    (0x1226C0, 'L', "Toggle Fast Forward", "切换快进"),
    (0x1226D8, 'L', "Swap Screens",        "交换屏幕"),
    (0x1226F0, 'L', "Swap Orientation A",  "交换方向A"),
    (0x122708, 'L', "Swap Orientation B",  "交换方向B"),
    (0x122720, 'L', "Load New Game",       "载入新游戏"),
    (0x122738, 'L', "Quit",                "退出"),
    (0x122750, 'L', "Fake Microphone",     "模拟麦克风"),
    (0x122768, 'L', "Menu Cursor Up",      "菜单光标上"),
    (0x122780, 'L', "Menu Cursor Down",    "菜单光标下"),
    (0x122798, 'L', "Menu Cursor Left",    "菜单光标左"),
    (0x1227B0, 'L', "Menu Cursor Right",   "菜单光标右"),
    (0x1227C8, 'L', "Menu Select",         "菜单确认"),
    (0x1227E0, 'L', "Menu Exit Menu",      "菜单退出"),
    (0x1227F8, 'L', "Menu Up Directory",   "菜单上级目录"),
    (0x122810, 'L', "Menu Page Up",        "菜单上翻页"),
    (0x122828, 'L', "Menu Page Down",      "菜单下翻页"),
    (0x122840, 'L', "Menu Switch View",    "切换视图"),
    (0x1224C8, 'L', "D-Pad Up",            "十字键上"),
    (0x1224E0, 'L', "D-Pad Down",          "十字键下"),
    (0x1224F8, 'L', "D-Pad Left",          "十字键左"),
    (0x122510, 'L', "D-Pad Right",         "十字键右"),
    # A/B/X/Y stay as-is (single letters)
    (0x122588, 'L', "L Trigger",           "L键"),
    (0x1225A0, 'L', "R Trigger",           "R键"),
    (0x1225B8, 'L', "Start",               "开始"),
    (0x1225D0, 'L', "Select",              "选择"),
    (0x1225E8, 'L', "Hinge Shut",          "合盖"),
    (0x122600, 'L', "Touch Cursor Up",     "触摸光标上"),
    (0x122618, 'L', "Touch Cursor Down",   "触摸光标下"),
    (0x122630, 'L', "Touch Cursor Left",   "触摸光标左"),
    (0x122648, 'L', "Touch Cursor Right",  "触摸光标右"),
    (0x122660, 'L', "Touch Cursor Press",  "触摸光标按"),
]

# ------------------------------------------------------------------ build strings
def cjk_cells(s):
    n = 0
    for ch in s:
        n += 2 if ord(ch) > 0x7F else 1      # GB2312: 2 bytes per CJK char
    return n

def disp_cells(s):                            # rendered cells (8x8 model)
    return sum(1 if ord(c) < 0x80 else 1 for c in s)

blob = bytearray()
OFFSETS = {}
report = []
for addr, kind, expect, zh in E:
    o = orig_str(addr)
    assert o.strip() == expect, "0x%x: %r != %r" % (addr, o.strip(), expect)
    try:
        enc = zh.encode("gb2312")
    except UnicodeEncodeError:
        raise SystemExit("not GB2312: %r" % zh)
    lead = len(o) - len(o.lstrip(" "))
    trail = len(o) - len(o.rstrip(" "))
    total = len(o)
    ncell = disp_cells(zh)
    if kind == 'L':
        pad = total - ncell
        assert pad >= 0, "0x%x %r: %d > %d cells" % (addr, zh, ncell, total)
        new = " " * lead + zh + " " * (total - lead - ncell)
    elif kind == 'R':
        pad = total - trail - ncell
        assert pad >= 0, "0x%x %r: %d > %d cells" % (addr, zh, ncell, total)
        new = " " * pad + zh + " " * trail
    elif kind == 'P6':                        # 6x10 font: px preserving
        opx = total * 6
        zpx = sum(10 if ord(c) > 0x7F else 6 for c in zh)
        ns = round((opx - zpx) / 6)
        assert ns >= 0, "0x%x %r too wide" % (addr, zh)
        new = zh + " " * ns
    elif kind == 'X':
        new = zh
    else:
        raise ValueError(kind)
    assert disp_cells(new) == total or kind in ('X', 'P6'), (addr, new)
    blob += b"\0" * ((-len(blob)) % 4)          # keep every string 4-byte aligned
    blob += enc
    blob += b"\0"
    OFFSETS[addr] = len(blob) - len(enc) - 1
    report.append((addr, kind, o, new, len(enc)))

# ------------------------------------------------------------------ code sites
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM); md.detail = True
TEXT_VA = 0xE320; TEXT_SZ = 0x11A85C - 0xE320
insns = list(md.disasm(d[TEXT_VA:TEXT_VA + TEXT_SZ], TEXT_VA))

pending = {}          # reg -> (adrp_addr, page)
XREGS = set(getattr(__import__('capstone.arm64', fromlist=['x']),
                    "ARM64_REG_X%d" % i) for i in range(31))
CODE_SITES = []       # (adrp_addr, add_addr, dest_reg, str_addr)
for i, ins in enumerate(insns):
    m = ins.mnemonic
    ops = ins.operands
    if m == 'adrp':
        pending[ops[0].reg] = (ins.address, ops[1].imm)
        continue
    if m == 'add' and len(ops) == 3 and ops[2].type == ARM64_OP_IMM \
            and ops[1].type == ARM64_OP_REG and ops[1].reg in pending:
        base = pending[ops[1].reg]
        addr = base[1] + ops[2].imm
        if addr in OFFSETS:
            # the pair is  adrp xB, page ; add xD, xB, #imm  (xB may feed more
            # adds, so only the `add` slot is rewritten -- see patch.py: it
            # becomes a single `adr xD, target`).
            assert ops[0].reg in XREGS, "not a 64-bit reg at 0x%x" % ins.address
            CODE_SITES.append((base[0], ins.address, ops[0].reg, addr))
    if m in ('bl', 'blr', 'ret') or (m == 'b' and i + 1 < len(insns) and
                                     insns[i + 1].address != ins.address + 4):
        pending.clear()
    if m in ('movz', 'mov') and ops and ops[0].type == ARM64_OP_REG:
        pending.pop(ops[0].reg, None)

# ------------------------------------------------------------------ reloc sites
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
rela_off, rela_sz, rela_ent = tags[7], tags[8], tags[9] or 24
REL_SITES = []
for i in range(rela_sz // rela_ent):
    fo = rela_off + i * rela_ent
    off, info, add = struct.unpack_from("<QQq", d, fo)
    if add in OFFSETS:
        assert (info & 0xFFFFFFFF) == 1027, "unexpected reloc type at 0x%x" % off
        REL_SITES.append((fo, add))

# ------------------------------------------------------------------ emit
os.makedirs(C.ASSETS, exist_ok=True)
with open(C.MENU_BIN, "wb") as f:
    f.write(blob)

all_addrs = set(a for a, _, _, zh in E)
covered = set(a for _, _, _, a in CODE_SITES) | set(a for _, a in REL_SITES)
missing = all_addrs - covered
assert not missing, "unreferenced strings: %s" % [hex(a) for a in missing]

with open(C.MENU_SITES, "w", encoding="utf-8") as f:
    f.write('"""menu_sites.py -- generated by genmenu.py, do not edit.\n"""\n')
    f.write("OFFSETS = " + json.dumps({hex(k): v for k, v in OFFSETS.items()}) + "\n")
    f.write("CODE_SITES = " + repr([(hex(a), hex(b), c, hex(s)) for a, b, c, s in CODE_SITES]) + "\n")
    f.write("REL_SITES = " + repr([(hex(a), hex(b)) for a, b in REL_SITES]) + "\n")

with open(C.build("genmenu_report.py"), "w", encoding="utf-8") as f:
    f.write("# generated by genmenu.py\nREPORT = " + repr(report) + "\n")

print("strings: %d, blob %d bytes" % (len(E), len(blob)))
print("code sites: %d, reloc sites: %d" % (len(CODE_SITES), len(REL_SITES)))
print()
for addr, kind, o, new, n in report:
    print("0x%06x %s %-42r -> %r" % (addr, kind, o, new))
