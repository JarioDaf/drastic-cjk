#!/bin/sh
# gen-assets.sh -- regenerate every generated blob in assets/.
#
# Only needed when you change the translation table or the font design.
# The resulting files are committed so that a plain ./build.sh is
# byte-reproducible with no external font at all.
#
#   DRASTIC_SRC=/path/to/drastic ./gen-assets.sh
set -eu
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

mkdir -p build

echo "== menu string table (needs capstone) =="
"$PY" tools/genmenu.py | head -20

echo
echo "== 15x15 / 10x10 / 8x8 CJK bitmaps (GNU Unifont) =="
"$PY" tools/genfont5.py

echo
echo "== 16x16 CJK + reference 2x ASCII (GNU Unifont; needs DRASTIC_SRC) =="
"$PY" tools/genfont6.py

echo
echo "== GB2312 -> Unicode map =="
"$PY" tools/genfont_uni.py

echo
echo "assets:"
ls -l assets
