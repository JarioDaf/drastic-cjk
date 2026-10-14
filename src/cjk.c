/* ------------------------------------------------------------------
 * cjk.c -- GB2312 bitmap-font support injected into DraStic (aarch64 PIE)
 *
 * Hooked at module-relative 0x87f00, the public text entry:
 *     void draw_text(char *str, u32 fg, u32 bg, u32 x, u32 y)
 *
 * The host renderer is monospaced and consumes exactly one byte per glyph,
 * so CJK glyphs are emitted one at a time through a private scratch font
 * whose glyph #1 is rewritten just before the draw.  ASCII takes the
 * identical path through the host's own font, hence zero regression.
 *
 * ------------------------------------------------------------------
 * The layout is a TAB, not a guess
 * ------------------------------------------------------------------
 * Everything below was measured by running the vendor's own page builders
 * and row renderers under Unicorn (work/page_dump.py, work/row_trace2.py).
 * The facts that matter:
 *
 * 1. The row dispatchers call draw_text with  LR-4 == the dispatcher's `blr`
 *    site, and there are TWO of them:
 *        0x7d7a8   shared list drawer  (options / video / firmware / keys ...)
 *        0x7fdc0   main-menu drawer
 *    An early SITE_IN_DISPATCH window (0x7a2c0..0x7ab00) contained NEITHER, so
 *    every rowTail row -- 8 of the 10 main-menu rows, the four "exit" rows
 *    of the settings pages -- silently fell back to the pristine 1x path.
 *    That is the "some glyphs big, some small" the user filmed.
 *
 * 2. `rowTail` reaches draw_text with a TAIL BRANCH (`b 0x87f00`), so LR is
 *    the dispatcher's, never the row's own address.  Site-based recognition
 *    alone can therefore never see it as a row.
 *
 * 3. A row cannot be identified by its y: 280 is main-menu row 0 AND
 *    firmware row 0 AND options row 4.  But (label offset in the injected
 *    string table, source y) IS unique -- gen_rowtab.py proves it over all
 *    73 rows of the five list pages.  So the hook keys the layout on exactly
 *    those two numbers and nothing else; no sticky "current page" that can
 *    go stale, no fudge factors, no run detection.
 *
 * 4. Rows are drawn with the host's 8x8 font, page titles with 6x10 and the
 *    key-page header with 9x15, so the 200% path must accept every bitmap
 *    metric the host owns and scale each glyph from its OWN size into the
 *    shared 16x16 cell.  An early version hard-coded `if (cell == 8)`, so the
 *    firmware title, the key-page header and the version line stayed 1x.
 *
 * 5. comboRow / numRow compose `label + value` into a stack buffer and draw
 *    it as ONE string, so the value column can only be found by matching the
 *    table prefix and splitting there.  The injected labels carry no space
 *    padding (the vendor used spaces to right-align), so the split lands
 *    immediately after the label.
 *
 * 6. The firmware page's colour swatch is a 16x8 fill_rect at
 *    (x_origin + 0x118, 296) plus a 14x6 colour core one pixel inside.
 *    y is the vendor grid's literal 296 (the 喜爱颜色 row) and x is the
 *    page field + 0x118, which does NOT hold 256 at run time on hardware
 *    (measured: 88), so relayouting the list strands the swatch AND any
 *    match written against x is dead on the device.  Earlier versions also
 *    misread the pair as a stray "value cursor" and dropped it; it is the
 *    only rectangle in the whole menu and it must be visible, so the hook
 *    re-anchors it to 喜爱颜色's row using only the hard-coded y/w/h and
 *    the frame's call site (see cjk_rect()).
 *
 * Host constraints that shaped earlier versions and still hold:
 *
 * 1. The kernel maps the anonymous .bss exactly once, after the PT_LOAD
 *    loop, as set_brk(elf_bss, elf_brk) taken from the HIGHEST PT_LOAD --
 *    the injected image must stay strictly BELOW the .bss.
 * 2. The injected segment is R-X, so all mutable state lives in the zero
 *    filled file-tail padding between .data and .bss inside the vendor's
 *    own RW LOAD.
 * 3. The renderer tops out at 16 pixels per glyph row (bit(15-col) of a
 *    single u16), so put_glyph() splits wider glyphs into side-by-side
 *    scratch fonts.
 * 4. NOTHING IN THIS IMAGE MAY BE BASE DEPENDENT.  It is linked as a plain
 *    ET_EXEC at 0x150000 and spliced into the vendor's PIE as one extra
 *    PT_LOAD; no relocation is ever applied to it, so a pointer stored in
 *    rodata keeps its link-time value and dangles the moment the loader
 *    picks a random base.  Code, string literals and ABS-symbol references
 *    are all PC-relative and fine -- a *table of pointers* is not.  The
 *    VALMAP was the first such table and cost a device crash the instant
 *    the menu came up (the Unicorn harness loads the module at VA 0, which
 *    hid it).  Use fixed-size char arrays; patch.py asserts the invariant
 *    over the whole image and work/test_rebase.py runs the payload at two
 *    different bases.
 * ------------------------------------------------------------------ */
typedef signed long    i64;
typedef unsigned char  u8;
typedef unsigned short u16;
typedef unsigned int   u32;
typedef unsigned long  u64;

extern void __draw_text(char *s, u32 fg, u32 bg, u32 x, u32 y);  /* 0x87f00 (hooked) */
extern void __resume(void);                                      /* 0x87f04 pristine body */

/* module-relative address of the global holding the selected font */
#define MOD_SLOT   0x167668u

/* zero-filled writable padding inside the vendor's RW LOAD:
   0x1681a0 (.data end) .. 0x169000 (.bss start).  0x168E00 is past the
   end of the file (0x1589d8) so the page tail is guaranteed zero.        */
#define STATE_OFF  0x168E00u
#define STATE_MAGIC 0x4B434A31u     /* "KJC1" */

/* layout of the appended blob:
       cjk15 | cjk10 | cjk8 | cjk16 | uni_tab
   each font is  u32 width, u32 height, height rows of u16, glyphs packed
   back to back (bit 15 of a row == left-most pixel).                      */
#define FONT_OFF   0x170000u        /* 64K aligned, past the end of the image */
#define SZ15       265118u          /* 8 + 15 * 8837 * 2 */
#define SZ10       176748u          /* 8 + 10 * 8837 * 2 */
#define SZ8        141400u          /* 8 +  8 * 8837 * 2 */
#define SZ16       282792u          /* 8 + 16 * 8837 * 2 */
#define SZUNI       29780u
#define OFF_CJK16  (SZ15 + SZ10 + SZ8)
#define SZ_ALL     (OFF_CJK16 + SZ16 + SZUNI)

#define UNI_N      7445u
#define LAST_GB    8836u            /* fallback "missing glyph" box */
#define MAX_CHARS  4096u
#define TEMP_SIZE  0x2410u          /* scratch font: 0x2000 bitmap + offsets[256] */

/* the overlay canvas the whole UI is painted into */
#define CANVAS_W   800u
#define CANVAS_H   480u

/* ---- the 200% menu grid ----------------------------------------- */
#define CELL       16u              /* one CJK / scaled-ASCII cell, px      */
#define RIGHT      784u             /* hard right bound of the menu text    */
#define TITLE_Y    12u              /* firmware / options / video title     */
#define KEYH_Y     4u               /* key page: page title                 */
#define KEYH2_Y    22u              /* key page: current control + binding  */
#define NOTE_X     16u              /* firmware footnotes, drawn on one line */
#define NOTE_Y     412u

/* ---- draw_text call sites (module-relative, = the bl address) --------- */
#define S_LBL      0x79858u         /* rowGen: label                        */
#define S_VAL      0x7987cu         /* rowGen: value column 2               */
#define S_VAL3     0x7989cu         /* rowGen: value column 3               */
#define S_NUM      0x79bf0u         /* numRow : "%s%*d" in a stack buffer   */
#define S_COMBO    0x79cccu         /* comboRow: "%s%s" in a stack buffer   */
#define S_EDT_L    0x79fc0u         /* 0x79f40: row label, SELECTED         */
#define S_EDT_1    0x7a0ecu         /* 0x79f40: field text before cursor    */
#define S_EDT_2    0x7a114u         /* 0x79f40: cursor cell                 */
#define S_EDT_3    0x7a138u         /* 0x79f40: cursor cell (highlight)     */
#define S_EDT_4    0x7a150u         /* 0x79f40: field text after cursor     */
#define S_EDT_0L   0x7a164u         /* 0x79f40: row label, NOT selected     */
#define S_EDT_0V   0x7a188u         /* 0x79f40: field text, NOT selected    */
#define S_DISP1    0x7d7a8u         /* shared list dispatcher -> row renderer */
#define S_DISP2    0x7fdc0u         /* main-menu dispatcher  -> row renderer */
#define S_KEYH     0x79aa8u         /* key page: page title                 */
#define S_HDR2     0x79ae0u         /* key page: current control name       */
#define S_KEYV     0x79b18u         /* key page: current binding            */
#define S_FWNOTE1  0x799b0u         /* firmware note line 1                 */
#define S_FWNOTE2  0x799d0u         /* firmware note line 2                 */

/* a site that hands us a ROW LABEL (rowTail arrives with the dispatcher's
   LR because it tail-branches into draw_text)                            */
#define S_IS_LABEL(s) ((s)==S_LBL||(s)==S_NUM||(s)==S_COMBO|| \
                       (s)==S_EDT_L||(s)==S_EDT_0L|| \
                       (s)==S_DISP1||(s)==S_DISP2)

/* rows whose label is NOT one of our strings: the vendor's own text ("A",
   "B", ... are drawn from its ASCII table, space padded, and were never
   routed through the injected menu table).  They can only be placed when
   the page is already known, so they are keyed on (page, y) and the entry
   carries this marker instead of a table offset.                        */
#define OFF_ANY    0xFFFFu

#define STRTAB_REL  0x152000u       /* strtab VA relative to the module base */
#define MENU_SZ     1555u           /* bytes of injected menu strings        */

/* page-title string offsets (unique in the table) */
#define OFF_T_OPT   0x78u           /* "选项设置"     */
#define OFF_T_VIDEO 0x84u           /* "视频选项设置" */
#define OFF_T_FW    0x94u           /* "固件设置" */

/* cheat-list draw_text call sites (module-relative).  Only the columns
   that carry CJK are listed: the enabled/disabled column is pure ASCII
   and keeps the vendor 9x15 glyphs.                                      */
#define CH_NAME1    0x7cb54u        /* folder name   x=10   y=20+15i         */
#define CH_NAME2    0x7cc08u        /* cheat name    x=10   y=20+15i         */
#define CH_DESC     0x7cc30u        /* description   x=6    y=420            */
#define CELL_BIG    16u             /* native 16x16 CJK at the 1x pitch     */

static const char k_path[] = "/proc/self/exe";

/* ---------------------------------------------------------------- layout
 * One entry per menu row of the five list pages, generated by
 * gen_rowtab.py straight from the vendor builders.  Key = (offset of the
 * label inside the injected table, y the host chose).                     */
typedef struct { u16 off; u16 y; u8 page; u8 row; } rowdef_t;

/* generated by gen_rowtab.py -- (label_off, src_y, page, row) */
static const rowdef_t ROWTAB[] = {
    {0x000,280,0, 0}, {0x00c,288,0, 1}, {0x018,296,0, 2}, {0x024,304,0, 3},
    {0x030,320,0, 4}, {0x03c,328,0, 5}, {0x048,344,0, 6}, {0x054,352,0, 7},
    {0x060,368,0, 8}, {0x06c,384,0, 9},
    {0x258,280,1, 0}, {0x260,288,1, 1}, {0x268,296,1, 2}, {0x274,304,1, 3},
    {0x280,312,1, 4}, {0x160,328,1, 5}, {0x174,344,1, 6}, {0x188,352,1, 7},
    {0x19c,360,1, 8},
    {0x498,240,2, 0}, {0x4a4,248,2, 1}, {0x4b0,256,2, 2}, {0x4bc,264,2, 3},
    {0x4c8,272,2, 4}, {0x4d4,280,2, 5}, {0x4e0,288,2, 6}, {0x4ec,296,2, 7},
    {0x4f8,304,2, 8}, {0x500,312,2, 9}, {0x50c,320,2,10}, {0x518,328,2,11},
    {0x524,336,2,12}, {0x530,344,2,13}, {0x53c,352,2,14}, {0x548,360,2,15},
    {0x554,368,2,16}, {0x564,376,2,17}, {0x570,384,2,18}, {0x57c,392,2,19},
    {0x23c,408,2,20}, {0x160,416,2,21}, {0x174,432,2,22}, {0x19c,440,2,23},
    {0x0e4,240,3, 0}, {0x0f0,248,3, 1}, {0x0fc,256,3, 2}, {0x108,272,3, 3},
    {0x114,280,3, 4}, {0x120,288,3, 5}, {0x12c,296,3, 6}, {0x138,304,3, 7},
    {0x148,312,3, 8}, {0x154,320,3, 9}, {0x160,336,3,10}, {0x174,352,3,11},
    {0x188,360,3,12}, {0x19c,368,3,13},
    {0x1ac,240,4, 0}, {0x1b8,256,4, 1}, {0x1c4,264,4, 2}, {0x1d0,272,4, 3},
    {0x1d8,280,4, 4}, {0x1e8,288,4, 5}, {0x1f8,296,4, 6}, {0x204,304,4, 7},
    {0x20c,312,4, 8}, {0x214,320,4, 9}, {0x224,328,4,10}, {0x230,336,4,11},
    {0x160,352,4,12}, {0x174,368,4,13}, {0x188,376,4,14}, {0x19c,384,4,15},
    /* page 5: "配置按键" -- the page the main menu really opens.  It is
       NOT a 24-row list; that one is its 额外按键 sub-page
       (page 2).  Rows 4..7 (A / B / X / Y) draw the vendor's own ASCII
       labels, so they carry OFF_ANY and are resolved from the page.      */
    {0x588,240,5, 0}, {0x594,248,5, 1}, {0x5a0,256,5, 2}, {0x5ac,264,5, 3},
    {OFF_ANY,272,5, 4}, {OFF_ANY,280,5, 5},
    {OFF_ANY,288,5, 6}, {OFF_ANY,296,5, 7},
    {0x5b8,304,5, 8}, {0x5bc,312,5, 9}, {0x5c0,320,5,10}, {0x5c8,328,5,11},
    {0x5d0,336,5,12}, {0x5d8,344,5,13}, {0x5e4,352,5,14}, {0x5f0,360,5,15},
    {0x5fc,368,5,16}, {0x608,376,5,17}, {0x24c,392,5,18},
    {0x23c,408,5,19}, {0x160,416,5,20}, {0x174,432,5,21},
    {0x188,440,5,22}, {0x19c,448,5,23},
};
#define ROWTAB_N 97

/* page geometry, all measured from the vendor's own builders:
 *
 *   top     y of the page's first row, after the grid was expanded to 16 px
 *   pitch   row spacing
 *   lx      label column
 *   lmax    right limit of the label column
 *   vr1/vr2 value columns, RIGHT edges (0 == the page has none); the vendor
 *           right-aligns its values (it pads the strings), and the keys page
 *           really does have two of them -- one per binding slot
 *   edt     left edge of the firmware page's in-place editor field
 *   grp     first row of the page's trailing action group ("restore default",
 *           "delete config", "exit ..."): everything from here on is pushed
 *           down by `gap` so the destructive actions cannot be mistaken for
 *           another key binding (0xFFFF == the page has no such group)
 *   gap     the extra pixels that group is pushed down by
 *
 * The vendor geometry these come from:
 *   MAIN  x=344 y=280..384       one inline value (the savestate slot)
 *   FIRM  x=256 values end ~553  editor field 472..552, cursor 536
 *   KEYS  x=216 bindings at 384 and 504 (the two "Unmapped" columns)
 *   OPT   x=256 values end ~553  (builder 0x7D7F0, "Configure Video Options")
 *   VIDEO x=256 values end ~553  (builder 0x7DF80, "Configure Options")
 */
typedef struct { u16 top, pitch, lx, lmax, vr1, vr2, edt, grp, gap; } page_t;
static const page_t PAGES[] = {
    /* 0 MAIN  */ { 272, 20, 344, 784,   0,   0,   0, 0xFFFF,  0 },
    /* 1 FIRM  */ {  56, 36, 256, 400, 560,   0, 400, 0xFFFF,  0 },
    /* 2 KEYSX */ {  40, 17, 216, 384, 544, 720,   0,     20, 10 },
    /* 3 OPT   */ {  56, 28, 256, 408, 560,   0,   0, 0xFFFF,  0 },
    /* 4 VIDEO */ {  48, 26, 256, 408, 560,   0,   0, 0xFFFF,  0 },
    /* 5 KEYS  */ {  40, 17, 216, 384, 544, 720,   0,     19, 10 },
};
#define PAGE_N 6

typedef struct {
    u32 magic;
    u32 dead;                       /* 1 == blob unavailable, stop retrying */
    u64 font;                       /* mmap()ed blob, 0 until loaded        */
    u32 busy;                       /* re-entrancy guard, see cjk_draw      */
    /* the row whose columns are still being drawn */
    u32 have_row;                   /* 1 while a row's columns may follow   */
    u32 page;                       /* page id of that row                  */
    u32 row_src_y;                  /* the y the host passed for it         */
    u32 cur_y;                      /* the y we placed it at                */
    u32 edt_x;                      /* running x of an editor field         */
    u32 sticky;                     /* page of the row identified last      */
    u32 pad_;                       /* keep the struct 8-byte aligned       */
} state_t;

/* ---------------- raw syscalls (no libc in the injected image) -------- */
static long sc_openat(const char *path)
{
    register long x0 __asm__("x0") = -100;      /* AT_FDCWD  */
    register long x1 __asm__("x1") = (long)path;
    register long x2 __asm__("x2") = 0;         /* O_RDONLY  */
    register long x3 __asm__("x3") = 0;
    register long x8 __asm__("x8") = 56;        /* __NR_openat */
    __asm__ volatile("svc #0" : "+r"(x0)
                     : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
    return x0;
}

static long sc_close(long fd)
{
    register long x0 __asm__("x0") = fd;
    register long x8 __asm__("x8") = 57;        /* __NR_close */
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8) : "memory");
    return x0;
}

static long sc_mmap_file(long len, long fd, long off)
{
    register long x0 __asm__("x0") = 0;
    register long x1 __asm__("x1") = len;
    register long x2 __asm__("x2") = 1;         /* PROT_READ  */
    register long x3 __asm__("x3") = 2;         /* MAP_PRIVATE */
    register long x4 __asm__("x4") = fd;
    register long x5 __asm__("x5") = off;
    register long x8 __asm__("x8") = 222;       /* __NR_mmap  */
    __asm__ volatile("svc #0" : "+r"(x0)
                     : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8) : "memory");
    return x0;
}

/* once per process: validate the scratch area, then map the appended blob */
static int have_font(state_t *st)
{
    long fd, m;

    if (st->magic != STATE_MAGIC) {             /* first call */
        st->magic = STATE_MAGIC;
        st->dead  = 0;
        st->font  = 0;
        st->busy  = 0;
        st->have_row = 0;
        st->page = 0;
        st->row_src_y = 0;
        st->cur_y = 0;
        st->edt_x = 0;
        st->sticky = 0;
        st->pad_ = 0;
    }
    if (st->font)  return 1;
    if (st->dead)  return 0;

    fd = sc_openat(k_path);
    if (fd < 0) { st->dead = 1; return 0; }
    m = sc_mmap_file((long)SZ_ALL, fd, (long)FONT_OFF);
    sc_close(fd);
    if (m <= 0) { st->dead = 1; return 0; }     /* mmap errors come back as -errno */
    st->font = (u64)m;
    return 1;
}

/* ---------------- font plumbing -------------------------------------- */
/* accept the host font only when its metrics match a built-in bitmap set */
static u32 cell_of(void *f)
{
    u32 w = ((u32 *)f)[0];
    u32 h = ((u32 *)f)[1];

    if (w == 9 && h == 15) return 15;
    if (w == 8 && h == 8)  return 8;
    if (w == 6 && h == 10) return 10;
    return 0;                                   /* unknown -> caller falls back */
}

static const u8 *body_of(const state_t *st, u32 cell)
{
    const u8 *g = (const u8 *)st->font;

    if (cell == 15) return g + 8;
    if (cell == 16) return g + OFF_CJK16 + 8;
    if (cell == 10) return g + SZ15 + 8;
    return g + SZ15 + SZ10 + 8;
}

/* rows of glyph `c` of a host bitmap font.  The renderer locates a glyph as
   font + 8 + 2*(offsets[c] + row), i.e. offsets[] counts u16 rows, and it
   indexes them as u32 at font + 4*c + 0x2008. */
static const u16 *host_glyph(const void *f, u32 c)
{
    return (const u16 *)((const u8 *)f + 8
                         + 2 * ((const u32 *)((const u8 *)f + 0x2008))[c]);
}

/* install CJK glyph `gi` as glyph #1 of the scratch font (1x path).
   The scratch font lives on the stack: the renderer reads
   width/height as u32, the bitmap at font+8 and offsets[] at font+0x2008. */
static void setup_temp(const state_t *st, u8 *temp, u32 cell, u32 gi)
{
    const u16 *s = (const u16 *)(body_of(st, cell) + gi * cell * 2);
    u16 *d = (u16 *)(temp + 8);
    u32 i;

    *(u32 *)(temp + 0) = cell;                  /* width  */
    *(u32 *)(temp + 4) = cell;                  /* height */
    for (i = 0; i < cell; i++) d[i] = s[i];
    *(u32 *)(temp + 0x2008 + 4) = 0;            /* offsets[1] = 0 */
}

static int uni_lookup(const state_t *st, u32 cp)
{
    const u32 *t = (const u32 *)((const u8 *)st->font + OFF_CJK16 + SZ16);
    int lo = 0, hi = (int)UNI_N - 1;

    while (lo <= hi) {
        int m = (lo + hi) >> 1;
        u32 v = t[m];
        u32 c = v >> 16;
        if (c == cp) return (int)(v & 0xFFFF);
        if (c < cp)  lo = m + 1; else hi = m - 1;
    }
    return -1;
}

/* decode one source character; returns a gb index or -1, sets *used */
static int decode_cjk(const state_t *st, const u8 *s, int *used)
{
    u8 c  = s[0];
    u8 c1 = s[1];

    *used = 1;
    if (c1 == 0) return -1;

    if (c >= 0xE0 && c <= 0xEF && (c1 & 0xC0) == 0x80) {   /* UTF-8 3-byte */
        u8 c2 = s[2];
        if ((c2 & 0xC0) == 0x80) {
            u32 cp = ((u32)(c & 0x0F) << 12) |
                     ((u32)(c1 & 0x3F) << 6) | (u32)(c2 & 0x3F);
            *used = 3;
            return uni_lookup(st, cp);
        }
    }
    if (c >= 0xA1 && c <= 0xF7 && c1 >= 0xA1 && c1 <= 0xFE) {   /* GB2312 */
        *used = 2;
        return (int)(c - 0xA1) * 94 + (int)(c1 - 0xA1);
    }
    if (c >= 0x81 && c <= 0xFE && c1 >= 0x40 && c1 <= 0xFE && c1 != 0x7F) {
        *used = 2;                                          /* GBK, out of our set */
        return -1;
    }
    return -1;
}

/* ---------------- 200% glyph output ----------------------------------- */

/* nearest-neighbour scale of a sw x sh host glyph into the 16x16 cell.
   bit 15 of a source row is the left-most pixel, same for the output. */
static void scale16(const u16 *src, u32 sw, u32 sh, u16 *out)
{
    u32 r, c;

    if (sw == 0 || sw > 16) sw = 16;
    if (sh == 0) sh = 1;
    for (r = 0; r < CELL; r++) {
        u16 bits = src[(r * sh) / CELL];
        u16 o = 0;

        for (c = 0; c < CELL; c++) {
            u32 sx = (c * sw) / CELL;

            if ((bits >> (15 - sx)) & 1u) o |= (u16)(0x8000u >> c);
        }
        out[r] = o;
    }
}

/* copy a native 16x16 CJK glyph out of the blob */
static void cjk16(const state_t *st, u32 gi, u16 *out)
{
    const u16 *s = (const u16 *)((const u8 *)st->font + OFF_CJK16 + 8 + gi * 32u);
    u32 i;

    for (i = 0; i < CELL; i++) out[i] = s[i];
}

/* emit one CELL x CELL glyph at (x, y).  Chunks that would leave the
   canvas are dropped -- the renderer does no clipping of its own.        */
static void put_glyph(void **slot, u8 *temp, char *b, u32 fg, u32 bg,
                      const u16 *rows, u32 stride, u32 x, u32 y)
{
    u32 chunks = (CELL + 15) >> 4, c, r;

    for (c = 0; c < chunks; c++) {
        u32 cw = CELL - c * 16;

        if (cw > 16) cw = 16;
        if (x + c * 16 + cw > CANVAS_W) break;
        *(u32 *)(temp + 0) = cw;
        *(u32 *)(temp + 4) = CELL;
        for (r = 0; r < CELL; r++) ((u16 *)(temp + 8))[r] = rows[r * stride + c];
        *(u32 *)(temp + 0x2008 + 4) = 0;
        b[0] = 1; b[1] = 0;
        *slot = temp;
        __draw_text(b, fg, bg, x + c * 16, y);
    }
}

/* draws [p, end) (end == 0: up to the NUL) into the 16x16 grid starting at
   (x, y); nothing is emitted once cx would pass xmax                     */
static void draw_cell(state_t *st, void **slot, void *orig, u8 *temp, char *b,
                      u32 fg, u32 bg, const u8 *p, const u8 *end,
                      u32 x, u32 y, u32 xmax)
{
    u16 buf[CELL];
    u32 cx = x, n = 0;
    u32 sw = ((u32 *)orig)[0], sh = ((u32 *)orig)[1];

    while (*p && n < MAX_CHARS) {
        u8 c = *p;
        u32 stride;

        if (end && p >= end) break;
        if (c == 0x0A) { cx = x; y += CELL; p++; n++; continue; }
        if (c < 0x80) {
            scale16(host_glyph(orig, c), sw, sh, buf);
            stride = 1;
            p++;
        } else {
            int used = 1;
            int gi = decode_cjk(st, p, &used);

            if (gi < 0 || gi > (int)LAST_GB) gi = (int)LAST_GB;
            cjk16(st, (u32)gi, buf);
            stride = 1;
            p += used;
        }
        if (cx + CELL > xmax || y + CELL > CANVAS_H) return;
        put_glyph(slot, temp, b, fg, bg, buf, stride, cx, y);
        cx += CELL; n++;
    }
}

/* number of displayed characters (one CJK glyph counts as one) */
static u32 cp_count(const state_t *st, const u8 *p, const u8 *end)
{
    u32 n = 0;

    while (*p && n < MAX_CHARS) {
        int used = 1;

        if (end && p >= end) break;
        if (*p >= 0x80) decode_cjk(st, p, &used);
        p += used; n++;
    }
    return n;
}

/* drop trailing blanks of [p, e) */
static const u8 *trim_end(const u8 *p, const u8 *e)
{
    while (e > p && e[-1] == ' ') e--;
    return e;
}

/* [p, NUL) with the trailing blanks removed -- the vendor right-aligns its
   value strings by padding them, so "   Light Slate Gray   " becomes
   "Light Slate Gray" and lands on our own right-aligned column instead.  */
static const u8 *trim_nul(const u8 *p)
{
    const u8 *e = p;

    while (*e) e++;
    return trim_end(p, e);
}

/* skip leading blanks */
static const u8 *skip_sp(const u8 *p)
{
    while (*p == ' ') p++;
    return p;
}

/* ---- option values that never went through the menu string table -----
   The vendor keeps these in a fixed 16-byte-stride table of space-padded
   ASCII (3D option values, key bindings, slot-2 devices).  We translate
   them here, which is also the only safe place to do it: a substitution
   can then never leak into a string some *other* part of the program
   draws through the pristine renderer.

   NOTE the shape of this table: fixed-size CHARACTER ARRAYS, never
   pointers.  The payload is linked as a plain ET_EXEC at 0x150000 and
   spliced into the vendor's PIE as an extra PT_LOAD; nothing ever applies
   a relocation to it, so a pointer stored here would keep its link-time
   value (e.g. 0x151b78) and turn into a dangling low address the moment
   the loader picks a random base -- an instant SIGSEGV on the first row
   that has a value.  Arrays are addressed PC-relative and are safe at any
   base.  patch.py asserts this invariant for the whole image.           */
#define VEN_SZ 16
#define VZH_SZ 12

typedef struct { char en[VEN_SZ]; u8 zh[VZH_SZ]; } valmap_t;

static const valmap_t VALMAP[] = {
    { "no",          "\xB7\xF1" },                  /* 否       */
    { "yes",         "\xCA\xC7" },                  /* 是       */
    { "none",        "\xCE\xDE" },                  /* 无       */
    { "vertical",    "\xD7\xDD\xCF\xF2" },          /* 纵向     */
    { "horizontal",  "\xBA\xE1\xCF\xF2" },          /* 横向     */
    { "single",      "\xB5\xA5\xC6\xC1" },          /* 单屏     */
    { "manual",      "\xCA\xD6\xB6\xAF" },          /* 手动     */
    { "automatic",   "\xD7\xD4\xB6\xAF" },          /* 自动     */
    { "Unmapped",    "\xCE\xB4\xD3\xB3\xC9\xE4" },  /* 未映射   */
    { "gba cart",    "GBA\xBF\xA8\xB4\xF8" },       /* GBA卡带  */
    { "sram cart",   "SRAM\xBF\xA8\xB4\xF8" },      /* SRAM卡带 */
    { "rumble pack", "\xD5\xF0\xB6\xAF\xB0\xFC" },  /* 震动包   */
    { "motion pack", "\xD4\xCB\xB6\xAF\xB8\xD0\xD3\xA6\xB0\xFC" },
    { "hb motion",   "\xD7\xD4\xD6\xC6\xB8\xD0\xD3\xA6\xB0\xFC" },
};
#define VALMAP_N (sizeof VALMAP / sizeof VALMAP[0])

/* `p` is such a value: optional leading blanks, then the ASCII text.  On a
   hit, *eaten (blanks included) tells how many source bytes to drop.     */
static const u8 *val_zh(const u8 *p, u32 *eaten)
{
    u32 k;

    for (k = 0; k < VALMAP_N; k++) {
        const char *e = VALMAP[k].en;
        const u8 *q = skip_sp(p);
        u32 n = 0;

        while (e[n] && q[n] == (u8)e[n]) n++;
        if (e[n]) continue;                     /* not a full match      */
        if (q[n] != 0 && q[n] != ' ' && q[n] < 0x80) continue;
        *eaten = (u32)(q - p) + n;
        return VALMAP[k].zh;
    }
    return 0;
}

/* one line of the key page header.  The vendor builds it as
   "<binding>：修改" from a "%s：修改" format, so the value we know is only
   a prefix of the string we are handed; draw the replacement first and
   then whatever follows it.  col == 0 means left aligned at PAGES[2].lx. */
static void draw_hdr(state_t *st, void **slot, void *orig, u8 *temp, char *b,
                     u32 fg, u32 bg, const u8 *p, u32 col)
{
    u32 eaten = 0, wzh = 0, w, x;
    const u8 *zh = val_zh(p, &eaten);
    const u8 *tail = zh ? p + eaten : p;

    if (zh) wzh = CELL * cp_count(st, zh, 0);
    w = wzh + CELL * cp_count(st, tail, 0);
    x = col ? ((w < col) ? col - w : 0) : PAGES[2].lx;
    if (col && x == 0) x = PAGES[2].lx;
    if (zh) {
        draw_cell(st, slot, orig, temp, b, fg, bg, zh, 0, x, KEYH2_Y, RIGHT);
        x += wzh;
    }
    if (*tail)
        draw_cell(st, slot, orig, temp, b, fg, bg, tail, 0, x, KEYH2_Y, RIGHT);
}

/* ---------------- the injected string table --------------------------- */static u32 tab_len(const u8 *q, u32 max)
{
    u32 n = 0;

    while (n < max && q[n]) n++;
    return n;
}

/* exact: p points straight into the table */
static int tab_exact(const u8 *p, u64 base, u32 *off)
{
    u64 d = (u64)((const u8 *)p - (const u8 *)(base + STRTAB_REL));

    if (d >= MENU_SZ) return 0;
    *off = (u32)d;
    return 1;
}

/* exact, or the longest table entry that prefixes p (numRow / comboRow
   copy the label into a stack buffer before drawing it).  *rest points
   just past the matched label.                                           */
static int tab_match(const u8 *p, u64 base, u32 *off, const u8 **rest)
{
    const u8 *t = (const u8 *)(base + STRTAB_REL);
    u32 best = 0xFFFFFFFFu, bestlen = 0, o = 0;

    if (tab_exact(p, base, off)) {
        *rest = p + tab_len(p, MENU_SZ - *off);
        return 1;
    }
    while (o < MENU_SZ) {
        u32 n = tab_len(t + o, MENU_SZ - o);

        if (n > 0 && n <= 96) {
            u32 i;

            for (i = 0; i < n; i++) {
                if (p[i] != t[o + i] || p[i] == 0) break;
            }
            if (i == n && n > bestlen) { bestlen = n; best = o; }
        }
        o = (o + n + 1 + 3) & ~3u;              /* entries are 4-byte aligned */
    }
    if (best == 0xFFFFFFFFu) return 0;
    *off = best;
    *rest = p + bestlen;
    return 1;
}

/* the row a (label, host y) pair belongs to, or 0.
 *
 * A few (label, y) pairs are shared by two pages: the trailing action group
 * of 配置按键 (page 5) and of its 额外按键 sub-page (page 2) carries the same
 * three labels at the same host y.  The host draws every row of a page in
 * index order, and the first rows of both pages are unique, so the page
 * identified by the previous row -- `sticky` -- resolves those.  The rows
 * whose label is not ours at all (OFF_ANY) can ONLY be resolved that way. */
static int find_row(u32 off, u32 y, u32 sticky, u32 *page, u32 *row)
{
    int first = -1;
    u32 i;

    for (i = 0; i < ROWTAB_N; i++) {
        if (ROWTAB[i].y != (u16)y) continue;

        if (ROWTAB[i].off == (u16)OFF_ANY) {
            if (off != OFF_ANY) continue;       /* a real label never lands here */
            if (ROWTAB[i].page == sticky) {
                *page = ROWTAB[i].page; *row = ROWTAB[i].row;
                return 1;
            }
            continue;
        }
        if (ROWTAB[i].off != (u16)off) continue;
        if (ROWTAB[i].page == sticky) {
            *page = ROWTAB[i].page; *row = ROWTAB[i].row;
            return 1;
        }
        if (first < 0) first = (int)i;
    }
    if (first >= 0) {
        *page = ROWTAB[first].page;
        *row  = ROWTAB[first].row;
        return 1;
    }
    return 0;
}

/* right edge of a value that is `w` px wide, or 0 when it cannot fit */
static u32 right_at(u32 w, u32 col)
{
    return (w < col) ? col - w : 0;
}

/* the page a unique title string belongs to, or -1.  Note the vendor's own
   naming is the other way round from the builder addresses: 0x7D7F0 builds
   "Configure Video Options" while 0x7DF80 builds "Configure Options".      */
static int title_page(u32 off)
{
    if (off == OFF_T_FW)    return 1;
    if (off == OFF_T_OPT)   return 4;
    if (off == OFF_T_VIDEO) return 3;
    return -1;
}

/* where a row of `q` is drawn */
static u32 row_y(const page_t *q, u32 ri)
{
    u32 oy = (u32)q->top + (u32)q->pitch * ri;

    if (ri >= (u32)q->grp) oy += q->gap;
    return oy;
}

/* entry.S passes the module base as the 6th and the draw_text call site
   (LR - 4) as the 7th argument.
   returns 1 = string handled, 0 = caller must run the pristine renderer */
static int cjk_run(char *str, u32 fg, u32 bg, u32 x, u32 y, u64 base, u64 lr)
{
    u8 temp[TEMP_SIZE] __attribute__((aligned(16)));
    state_t *st = (state_t *)(base + STATE_OFF);
    void **slot = (void **)(base + MOD_SLOT);
    void  *orig = *slot;
    u32    site = (u32)(lr - base) - 4;
    u32    off, cx = x, cy = y, aw, ah, n = 0;
    u8    *p = (u8 *)str;
    char   b[2];

    if (orig == 0) return 0;
    if (cell_of(orig) == 0) return 0;           /* not a bitmap text font */
    if (!have_font(st)) return 0;               /* blob unavailable       */

    /* ---- fixed-position menu text --------------------------------- */
    switch (site) {
    case S_FWNOTE1: {                           /* the two footnotes share
                                                   one line at the bottom  */
        u32 w = CELL * cp_count(st, p, (const u8 *)0);

        st->have_row = 0;
        draw_cell(st, slot, orig, temp, b, fg, bg, p, (const u8 *)0,
                  NOTE_X, NOTE_Y, RIGHT);
        st->edt_x = NOTE_X + w;
        *slot = orig; return 1;
    }
    case S_FWNOTE2:
        st->have_row = 0;
        draw_cell(st, slot, orig, temp, b, fg, bg, p, (const u8 *)0,
                  st->edt_x, NOTE_Y, RIGHT);
        *slot = orig; return 1;
    case S_KEYH:                                /* key page title */
        st->have_row = 0;
        draw_cell(st, slot, orig, temp, b, fg, bg, p, (const u8 *)0,
                  PAGES[2].lx, KEYH_Y, RIGHT);
        *slot = orig; return 1;
    case S_HDR2:                                /* the control being edited */
        st->have_row = 0;
        draw_hdr(st, slot, orig, temp, b, fg, bg, p, 0);
        *slot = orig; return 1;
    case S_KEYV:                                /* its binding, right side */
        st->have_row = 0;
        draw_hdr(st, slot, orig, temp, b, fg, bg, p, PAGES[2].vr2);
        *slot = orig; return 1;
    default: break;
    }

    st->busy = 1;

    /* ---- page titles (their offsets are unique in the table) ------- */
    {
        const u8 *rest_;
        u32  o2;
        int  pg;

        if (tab_match(p, base, &o2, &rest_) &&
            (pg = title_page(o2)) >= 0) {
            st->have_row = 0;
            draw_cell(st, slot, orig, temp, b, fg, bg, p, (const u8 *)0,
                      PAGES[pg].lx, TITLE_Y, RIGHT);
            *slot = orig; return 1;
        }
    }

    /* ---- a row label: (table offset, host y) names the row -------- */
    if (S_IS_LABEL(site)) {
        const u8 *rest = 0;
        u32 pg, ri, off = OFF_ANY;
        int in_tab = tab_match(p, base, &off, &rest);

        if (!in_tab)                            /* the vendor's own label  */
            rest = p + tab_len(p, 255);
        if (find_row(in_tab ? off : OFF_ANY, y, st->sticky, &pg, &ri)) {
            const page_t *q = &PAGES[pg];
            u32 oy = row_y(q, ri);
            const u8 *e = trim_end(p, rest);

            st->have_row   = 1;
            st->page       = pg;
            st->sticky     = pg;
            st->row_src_y  = y;
            st->cur_y      = oy;
            st->edt_x      = q->edt;

            if (q->vr1 == 0) {
                /* single column: an inline value follows the label on the
                   same line, right where the vendor put it               */
                draw_cell(st, slot, orig, temp, b, fg, bg, p, e,
                          q->lx, oy, RIGHT);
                rest = skip_sp(rest);
                if (*rest) {
                    u32 eaten = 0;
                    const u8 *zh = val_zh(rest, &eaten);
                    const u8 *sp = zh ? zh : rest;
                    const u8 *vv = zh ? (const u8 *)0 : trim_nul(rest);

                    draw_cell(st, slot, orig, temp, b, fg, bg, sp, vv,
                              (u32)q->lx + CELL * cp_count(st, p, e) + CELL,
                              oy, RIGHT);
                }
            } else {
                /* label column, then the value right-aligned on its own */
                u32 w, x2, eaten = 0;
                const u8 *v, *sp;
                const u8 *zh;

                draw_cell(st, slot, orig, temp, b, fg, bg, p, e,
                          q->lx, oy, q->lmax);
                rest = skip_sp(rest);
                if (!*rest) { *slot = orig; return 1; }
                zh = val_zh(rest, &eaten);
                sp = zh ? zh : rest;
                v  = zh ? (const u8 *)0 : trim_nul(rest);
                w  = CELL * cp_count(st, sp, v);
                x2 = right_at(w, q->vr1);
                draw_cell(st, slot, orig, temp, b, fg, bg, sp,
                          v, x2 ? x2 : q->lx, oy, RIGHT);
            }
            *slot = orig; return 1;
        }
    }

    /* ---- the extra columns of the row just drawn ------------------ */
    if (st->have_row && st->row_src_y == y) {
        const page_t *q = &PAGES[st->page];
        u32 col = 0, xmax = RIGHT, adv = 0, left = 0;

        switch (site) {
        case S_VAL:  col = q->vr1; break;       /* binding slot 1 */
        case S_VAL3: col = q->vr2 ? (u32)q->vr2 : (u32)q->vr1; break;
        case S_EDT_0V: col = q->vr1; break;     /* field text, NOT selected */
        case S_EDT_1: left = st->edt_x; adv = 1; break;
        case S_EDT_2:
        case S_EDT_3: left = st->edt_x; break;
        case S_EDT_4: left = st->edt_x + CELL; adv = 1; break;
        default: break;
        }
        if (left) {                             /* editor field segments */
            draw_cell(st, slot, orig, temp, b, fg, bg, p, (const u8 *)0,
                      left, st->cur_y, xmax);
            if (adv) st->edt_x = left + CELL * cp_count(st, p, (const u8 *)0);
            *slot = orig; return 1;
        }
        if (col) {                              /* right-aligned column  */
            u32 eaten = 0;
            const u8 *zh = val_zh(p, &eaten);
            const u8 *sp = zh ? zh : p;
            const u8 *v  = zh ? (const u8 *)0 : trim_nul(p);
            u32 w  = CELL * cp_count(st, sp, v);
            u32 x2 = right_at(w, col);

            draw_cell(st, slot, orig, temp, b, fg, bg, sp, v,
                      x2 ? x2 : q->lx, st->cur_y, xmax);
            *slot = orig; return 1;
        }
    }

    /* ---- original 1x path (all other fonts and sites) ------------- */
    aw = ((u32 *)orig)[0];
    ah = ((u32 *)orig)[1];
    while (*p && n < MAX_CHARS) {
        u8 c = *p;

        if (c == 0x0A) {                        /* newline */
            cx = x; cy += ah;
            p++; n++;
            continue;
        }
        if (c < 0x80) {                         /* ASCII: native font + advance */
            b[0] = (char)c; b[1] = 0;
            *slot = orig;
            __draw_text(b, fg, bg, cx, cy);
            cx += aw;
            p++; n++;
            continue;
        }
        {
            int used = 1;
            int gi = decode_cjk(st, p, &used);
            u32 gcell = cell_of(orig);

            if (gi < 0 || gi > (int)LAST_GB) gi = (int)LAST_GB;
            if (gcell == 15 && (site == CH_NAME1 || site == CH_NAME2 ||
                                site == CH_DESC))
                gcell = CELL_BIG;
            setup_temp(st, temp, gcell, (u32)gi);
            b[0] = 1; b[1] = 0;
            *slot = temp;
            __draw_text(b, fg, bg, cx, cy);
            cx += gcell;
            p += used; n++;
        }
    }
    *slot = orig;
    return 1;
}

/* cjk_run() reaches the host renderer through the hooked entry, so every
   nested draw_text() lands back here.  Decline those and let the pristine
   body run with whatever font pointer the inner call just installed.       */
int cjk_draw(char *str, u32 fg, u32 bg, u32 x, u32 y, u64 base, u64 lr)
{
    state_t *st = (state_t *)(base + STATE_OFF);
    int r;

    if (st->magic == STATE_MAGIC && st->busy) return 0;
    r = cjk_run(str, fg, bg, x, y, base, lr);
    st->busy = 0;
    return r;
}

/* ------------------------------------------------------------------
 * fill_rect(0x88430) hook: void fill(u32 color, u32 x, u32 y, u32 w, u32 h)
 *
 * Returns 1 to let the pristine rect run -- possibly with rewritten
 * arguments -- and 0 to drop it.
 *
 * The only rectangle the menu draws is the firmware page's favourite
 * colour swatch, painted by that page's tail (0x79960) as a white 16x8
 * frame with the colour itself as a 14x6 core one pixel inside:
 *
 *     799d4: ldr   w1, [x19, #0x10]      w1 = page->x_origin = 256
 *     799d8: mov   w4, #8
 *     799dc: add   w1, w1, #0x118        x = 256 + 280 = 536
 *     799e0: mov   w3, #0x10             w = 16
 *     799e4: mov   w2, #0x128            y = 296   <-- ABSOLUTE
 *     799e8: mov   w0, #-1               white frame
 *     799ec: bl    #0x88430
 *     79a08: add   w1, w1, #0x119        x = 537
 *     79a14: mov   w4, #6 / w3, #0xe     the 14x6 colour core
 *
 * y is the literal 296 (the 喜爱颜色 row in the VENDOR grid) and never
 * moves when the host relayouts the list, so as soon as our rows are
 * spread onto the 36 px grid the swatch stops being next to 喜爱颜色: our
 * page-1 rows are 36 px apart, so vendor y 296 lands in the gap between
 * our rows 6 and 7 -- visually "between 退出：保存所有游戏 and 退出：保存
 * 当前游戏".
 *
 * An earlier revision also *dropped* the pair, because cjk_rect had misread it as
 * a stray "value cursor" (same x/window, same 16x8 + 14x6 shape).  It is
 * not: it is the only colour swatch in the UI, and it must be visible.
 *
 * So: re-anchor it to the row it belongs to and park it immediately right
 * of that row's value column.  Both rectangles of the pair are shifted by
 * the same delta, which keeps the 1 px frame around the colour intact.
 *
 * WHY EARLIER REVISIONS STILL SHOWED THE SWATCH IN THE OLD SPOT ON DEVICE:
 * x is NOT 536 at run time.  It is `page->x_origin + 0x118`, and the value
 * that field actually holds when the tail runs on hardware is not the 256
 * the Unicorn harness sees -- measured off a photo of the device, the
 * swatch was drawn at x = 368, i.e. that field held 88.  Both the drop
 * and the relocation keyed on `x == 536`, so neither ever matched on the
 * device (they did match in the harness, which is why the bug survived
 * local testing).  y/w/h, by contrast, are hard-coded immediates in the
 * tail (0x128 / 0x10,8 / 0xE,6) -- identical on both -- so they are the
 * only safe key.  The frame is additionally pinned by its call site: it is
 * the `bl` at 0x799ec, so the stub's saved LR is 0x799f0 (the core comes
 * in through the tail `b` at 0x79a24, whose LR is whatever the tail's own
 * caller left behind, so the core is keyed on its shape only).
 * ------------------------------------------------------------------ */
#define SW_PAGE  1u                 /* the firmware page                     */
#define SW_ROW   2u                 /* its 3rd row == 喜爱颜色                */
#define SW_GAP   8u                 /* gap between the value column and frame */
#define SW_FRAME_LR 0x799f0u        /* LR after the tail's `bl #0x88430`     */

int cjk_rect(u32 *a, u64 base)
{
    const page_t *q = &PAGES[SW_PAGE];
    u32 w = a[3], h = a[4], y = a[2];
    int frame;

    /* the stub parked the caller's LR at args[6..7] (see entry.S) */
    frame = (((u64)a[7] << 32) | a[6]) == (u64)SW_FRAME_LR;

    /* the white 16x8 frame (bl @0x799ec) and its 14x6 colour core (b
       @0x79a24).  Neither x nor the page field behind it is trusted.    */
    if (!frame && !((w == 16u && h == 8u && y == 296u) ||
                    (w == 14u && h == 6u && y == 297u)))
        return 1;                           /* not the swatch: leave alone */

    a[1] = (u32)q->vr1 + SW_GAP + (frame ? 0u : 1u);        /* 560 + 8 = 568 */
    a[2] = row_y(q, SW_ROW) + ((CELL - 8u) / 2u) + (frame ? 0u : 1u);
    return 1;                               /* let the vendor's fill run */
}
