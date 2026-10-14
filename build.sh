#!/bin/sh
# build.sh -- compile the injected payload and produce the patched executable.
#
#   DRASTIC_SRC=/path/to/drastic ./build.sh [output]
#
# Inputs : $DRASTIC_SRC  (default ./drastic)  -- your own pristine binary
#          src/*.c src/*.S src/link.ld        -- the injected layer
#          assets/*                           -- generated blobs (committed)
# Output : build/payload.elf, build/drastic.cjk
set -eu
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
OUT="${1:-build/drastic.cjk}"

# ---- locate a cross compiler (zig cc is the only tested one) -------------
ZIG="${ZIG:-}"
if [ -z "$ZIG" ]; then
    if command -v zig >/dev/null 2>&1; then
        ZIG=zig
    else
        ZIG=$("$PY" - <<'EOF' 2>/dev/null || true
import os, sys
import ziglang
p = os.path.join(os.path.dirname(ziglang.__file__), "zig.exe")
if not os.path.exists(p):
    p = os.path.join(os.path.dirname(ziglang.__file__), "zig")
print(p if os.path.exists(p) else "")
EOF
)
    fi
fi
if [ -z "$ZIG" ] || [ ! -x "$ZIG" ]; then
    echo "error: no zig found.  Install it (pip install ziglang) or set ZIG=/path/to/zig" >&2
    exit 1
fi
echo "zig      : $ZIG ($("$ZIG" version))"

mkdir -p build
export ZIG_LOCAL_CACHE_DIR="$PWD/build/.zigcache"

T="-target aarch64-linux-musl -ffreestanding -nostdlib -fno-builtin \
   -fno-stack-protector -fno-asynchronous-unwind-tables -fomit-frame-pointer"

rm -f build/cjk.o build/entry.o build/syms.o build/payload.elf
# shellcheck disable=SC2086
"$ZIG" cc $T -O2 -c src/cjk.c   -o build/cjk.o
"$ZIG" cc $T     -c src/entry.S -o build/entry.o
"$ZIG" cc $T     -c src/syms.S  -o build/syms.o
# NOTE: the bitmap fonts are NOT linked in -- cjk.c mmap()s them from the blob
# appended to the executable (FONT_OFF); the injected ROM has no room for them.
"$ZIG" ld.lld -T src/link.ld --no-eh-frame-hdr -o build/payload.elf \
    build/entry.o build/syms.o build/cjk.o

echo "--- payload symbols ---"
"$ZIG" objdump -t build/payload.elf 2>/dev/null \
    | grep -E "cjk_entry|cjk_rect_entry|\.text" || true

# ---- patch ---------------------------------------------------------------
echo "--- patching ---"
"$PY" tools/patch.py "$OUT"

echo
echo "done -> $OUT"
ls -l "$OUT"
