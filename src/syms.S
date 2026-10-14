/* syms.S -- module-relative addresses inside the host executable.
 * They are absolute symbols: the payload is linked as if the module were
 * loaded at its link-time base, so all PC-relative references stay valid
 * once the loader applies its (single) relocation bias to the whole module.
 */
    .globl __draw_text      /* 0x87f00  public draw_text() entry          */
    .set   __draw_text, 0x87f00
    .globl __resume         /* 0x87f04  first instruction after the hook  */
    .set   __resume, 0x87f04
    .globl __f9x15          /* 0x160a50  built-in 9x15 font               */
    .set   __f9x15, 0x160a50
    .globl __f8x8           /* 0x162e58  built-in 8x8 font                */
    .set   __f8x8, 0x162e58
    .globl __f6x10          /* 0x165260  built-in 6x10 font               */
    .set   __f6x10, 0x165260
    .globl __font_slot      /* 0x167668  current-font pointer variable    */
    .set   __font_slot, 0x167668
    .globl __fill           /* 0x88430  public fill_rect() entry          */
    .set   __fill, 0x88430
    .globl __resume_fill    /* 0x88434  first instruction after the hook  */
    .set   __resume_fill, 0x88434
