/* Payload is mapped into the vendor's address-space hole between the two
 * PT_LOADs: 0x14c8000 (end of the R-X segment) .. 0x15d1f8 (start of RW).
 * Staying in there keeps elf_bss/elf_brk -- and therefore the kernel's single
 * anonymous .bss mapping -- bit-for-bit identical to the vendor image.       */
ENTRY(cjk_entry)

SECTIONS
{
  . = 0x150000;

  .text : ALIGN(16) { *(.text*) }

  .rodata : ALIGN(16) { *(.rodata*) }

  .data : ALIGN(16) { *(.data*) }

  .bss : ALIGN(16) { *(.bss*) *(COMMON) }

  /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.ARM.exidx*) }
}
