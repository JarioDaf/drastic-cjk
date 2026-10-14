# assets/ — generated blobs and their provenance

`build.sh` consumes these files; `gen-assets.sh` regenerates them. They are
committed so that a fresh clone reproduces the reference build byte for byte
with no external font, no network and no Windows installation.

| file | produced by | source |
|---|---|---|
| `unifont.hex` | `tools/unifont_subset.py` | **GNU Unifont** 18.0.01, GB2312 subset |
| `font_15.bin`, `font_10.bin`, `font_8.bin` | `tools/genfont5.py` | box-filtered down from `unifont.hex` |
| `font_16.bin` | `tools/genfont6.py` | `unifont.hex`, 1:1 (16×16) |
| `uni_tab.bin` | `tools/genfont_uni.py` | pure function of the GB2312 codec — no font involved |
| `menu.bin`, `menu_sites.py` | `tools/genmenu.py` | derived from the vendor binary's own string offsets |
| `OFL-1.1.txt` | — | the SIL Open Font License 1.1, as shipped with Unifont |

## The font data is not MIT

Everything under this directory that is *font software* — `unifont.hex` and the
four `font_*.bin` sets derived from it — is distributed under the **SIL Open
Font License 1.1** (`OFL-1.1.txt`), the licence GNU Unifont releases its glyphs
under. It is **not** covered by this repository's MIT licence; see the scope
note at the end of [LICENSE](../LICENSE) and [NOTICE.md](../NOTICE.md) §4.

Unifont is dual-licensed, so the GPLv2-or-later-with-font-embedding-exception
option is equally available; this project takes the OFL route because OFL 1.1
spells out embedding and bundling font data together with software.

## Reproducing `unifont.hex`

```sh
UNIFONT_HEX=/path/to/unifont_all-18.0.01.hex python3 tools/unifont_subset.py
```

Upstream files (GNU FTP and mirrors, e.g. `https://ftp.gnu.org/gnu/unifont/`):

```
unifont-18.0.01.tar.gz                41 427 259 B
  sha256 eab60847aac34c8768765cecc7821faf50de2636187b452b9b5fa50a12b00bc3
unifont_all-18.0.01.hex.gz             1 712 610 B
  md5    1337503af932f3d9e1759944f3e7af6d
  sha256 14c96e497466a82e46cf20032ce510e186bdc8658c9158e2290f452cda9bc498
```

The committed subset holds exactly the 7 445 codepoints the GB2312 codec can
produce, each line copied **verbatim** from the upstream file in its own order:
a trimmed copy, not a modified font. sha256 `bc682ebd…` (7 445 lines,
511 710 bytes).

Some Unifont glyphs are 8 pixels wide and are stored with two hex digits per
scanline; `tools/unifont.py` centres those in the 16-pixel cell, which is where
a CJK font puts the GB2312 symbol zones they belong to.
