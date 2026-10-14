# NOTICE — provenance, licensing and what you must bring yourself

## 1. This repository contains no vendor binary

The toolchain here **patches** a `drastic` executable that you already own.
Neither the original executable nor a patched copy of it is distributed with
this repository, and `.gitignore` refuses to commit one.

### Reference target

The reference target is the **DraStic** shipped with the **ROCKNIX** system
image for the **Anbernic RG DS** handheld (Rockchip RK3566, Linux, AArch64).

Source image: `ROCKNIX-RK3566.aarch64-20261001-Specific.img.gz`
(ROCKNIX RK3566 build **20261001**).

- The unmodified executable this project patches was **extracted, unchanged,
  from that system image, as installed on an Anbernic RG DS**.
- The patched executable produced by `./build.sh` was **verified on real
  Anbernic RG DS hardware** — Chinese menu text, game boot and the cheat list
  all confirmed working. The build used for that check is the reference build
  below, byte for byte.

    original `drastic`  : 1 411 544 bytes
                          md5 3e5a8b427561b9473751869de22cb40b
                          ELF64 AArch64, ET_DYN (PIE), stripped
                          extracted from ROCKNIX-RK3566.aarch64-20261001-Specific.img.gz
    produced by ./build.sh: 2 403 166 bytes
                          md5 373b50bfde2112438b37c968073ff853
                          verified on Anbernic RG DS hardware
                          reference build (see docs/BUILD.md §8)

If you do not have a legitimate copy of the executable, this project is of no
use to you.

## 2. What may and may not be published

This repository ships the **toolchain**, not the program it patches. Keep it
that way — nothing below is optional if you fork or republish.

| | what | publish? |
|---|---|---|
| ✅ | `src/` `tools/` `harness/` `docs/` `assets/` — sources, scripts, generated blobs and documentation | yes |
| ❌ | the unmodified `drastic` executable | **no** |
| ❌ | a patched build — `drastic.cjk`, or any `*.cjk` / `*.elf` / `*.o` | **no** |

Concretely: do not attach either kind of binary to the repository, to a
release, to an issue or to a discussion. If you publish a release at all,
publish source archives (GitHub's own "Source code" zips) and nothing else.

What *is* distributed here carries its own licence: the **source code** is MIT
(`LICENSE`), the **font bitmaps** in `assets/` are SIL OFL 1.1 (section 4). The
vendor binary is neither — this toolchain only ever touches a copy you already
have, on your own machine. Patching that copy for your own use is what it is
for.

## 3. Scope of the source license

Everything written for this project — `src/`, `tools/`, `harness/`, the
scripts and the documentation — is released under the MIT license in
`LICENSE`.

Reverse engineering for interoperability and personal modification is a
widely accepted practice, but it does **not** grant you any rights to the
original program. All rights in DraStic remain with its authors.

## 4. The committed `assets/` — and the font licence

`assets/` holds the generated blobs that `build.sh` consumes. They are
committed so that a fresh clone reproduces the reference build byte for byte
with no external font, no network and no Windows installation:

| file | how it is produced | provenance |
|---|---|---|
| `unifont.hex` | `tools/unifont_subset.py` | **GNU Unifont** 18.0.01, GB2312 subset |
| `font_15.bin`, `font_10.bin`, `font_8.bin` | `tools/genfont5.py` | Unifont glyphs, box-filtered down to each cell |
| `font_16.bin` | `tools/genfont6.py` | Unifont glyphs, 16×16, unmodified |
| `uni_tab.bin` | `tools/genfont_uni.py` | pure function of the GB2312 codec — no font involved |
| `menu.bin`, `menu_sites.py` | `tools/genmenu.py` | derived from the vendor binary's own string offsets |

**The font data is not MIT.** `unifont.hex` and the four bitmap sets derived
from it are font software, and stay under the licence GNU Unifont releases its
glyphs under: the **SIL Open Font License 1.1** (`assets/OFL-1.1.txt`).
Unifont is dual-licensed — GPLv2-or-later with the GNU font embedding
exception is the other option — and either one is fine for embedding these
bitmaps in a patched executable. Upstream URLs and hashes are in
`assets/README.md`.

The patch is distributed **without** the vendor binary; see section 1.

## 5. Trademarks

"Nintendo DS", "Nintendo" and "DraStic" are the property of their respective
owners. This project is unofficial and is not affiliated with or endorsed by
any of them.
