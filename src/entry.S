/* entry.S -- stub installed over the first instruction of draw_text()
 *
 * Replaces the original prologue instruction (`sub sp,sp,#0x50`) at
 * module-relative 0x87f00.
 *
 * Every call goes through cjk_draw(): pure ASCII used to be replayed
 * straight into the pristine body, but the 200% menu needs the ASCII of
 * the 8x8 font doubled as well, so the decision now lives in C.  If
 * cjk_draw() returns 0 (unknown font, blob unavailable) the original
 * arguments are restored and the pristine body runs anyway, so the worst
 * case is the original behaviour.
 *
 * All module-relative addresses are materialised with adrp/add (they are
 * tens of megabytes away from this stub, so adr cannot reach them).
 */
    .text
    .globl cjk_entry
    .type  cjk_entry, %function
cjk_entry:
    sub   sp, sp, #0x40                 /* preserve args + LR across the call */
    stp   x0, x1, [sp, #0x00]
    stp   x2, x3, [sp, #0x10]
    stp   x4, x30, [sp, #0x20]
    adrp  x5, __font_slot
    add   x5, x5, :lo12:__font_slot
    movz  x6, #0x7668                   /* x5 -= 0x167668  ->  module base */
    movk  x6, #0x16, lsl #16
    sub   x5, x5, x6
    mov   x6, x30                       /* 7th arg: the draw_text call site */
    bl    cjk_draw
    mov   w11, w0                       /* keep the verdict: x0 is about
                                           to be restored below           */
    ldr   x30, [sp, #0x28]
    ldr   x4,  [sp, #0x20]
    ldp   x2, x3, [sp, #0x10]
    ldp   x0, x1, [sp, #0x00]
    add   sp, sp, #0x40
    cbz   w11, 3f                       /* declined -> pristine renderer  */
    ret

3:  sub   sp, sp, #0x50
    b     __resume
    .size cjk_entry, . - cjk_entry

/* ---------------------------------------------------------------
 * stub over the first instruction of fill_rect() @0x88430
 *      void fill(u32 color, u32 x, u32 y, u32 w, u32 h)
 * cjk_rect() returns 1 to let the pristine rectangle run -- optionally
 * with rewritten arguments -- and 0 to drop it.  Nothing is dropped any
 * more: earlier revisions dropped the 喜爱颜色 swatch, misreading it as a
 * stray "value cursor", and lost it from the UI.  The hook now only
 * re-anchors that swatch pair (see cjk_rect() in cjk.c).  x30 is parked
 * on the stack because the swatch frame is identified by its call site:
 * the bl at 0x799ec is the only one, so its LR is always 0x799f0.
 * --------------------------------------------------------------- */
    .globl cjk_rect_entry
    .type  cjk_rect_entry, %function
cjk_rect_entry:
    sub   sp, sp, #0x30                 /* u32 args[5] + LR, see cjk_rect() */
    str   w0, [sp, #0x00]
    str   w1, [sp, #0x04]
    str   w2, [sp, #0x08]
    str   w3, [sp, #0x0c]
    str   w4, [sp, #0x10]
    str   x30, [sp, #0x18]
    mov   x0, sp                        /* x0 = &args[0]      */
    adrp  x5, __font_slot               /* x1 = module base   */
    add   x5, x5, :lo12:__font_slot
    movz  x6, #0x7668
    movk  x6, #0x16, lsl #16
    sub   x5, x5, x6
    mov   x1, x5
    bl    cjk_rect
    mov   w9, w0                        /* keep the verdict */
    ldr   w0, [sp, #0x00]
    ldr   w1, [sp, #0x04]
    ldr   w2, [sp, #0x08]
    ldr   w3, [sp, #0x0c]
    ldr   w4, [sp, #0x10]
    ldr   x30, [sp, #0x18]
    add   sp, sp, #0x30
    cbz   w9, 4f                        /* verdict 0 -> skip the fill (unused today) */
    stp   x29, x30, [sp, #-0x40]!       /* replay the overwritten insn */
    b     __resume_fill
4:  ret
    .size cjk_rect_entry, . - cjk_rect_entry
