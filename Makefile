# drastic-cjk -- convenience wrapper around build.sh / gen-assets.sh /
# tools/verify.py.  The shell scripts are the real entry points; this just
# gives you `make`, `make verify`, `make assets`, `make test`, `make clean`.
#
#   make DRASTIC_SRC=/path/to/drastic
#   make verify

DRASTIC_SRC ?=
export DRASTIC_SRC

PYTHON ?= python3
export PYTHON

OUT ?= build/drastic.cjk

.PHONY: all build verify assets test harness clean distclean help

all: build verify

build:
	./build.sh $(OUT)

verify: $(OUT)
	$(PYTHON) tools/verify.py $(OUT)

## regenerate every blob in assets/ (GNU Unifont -- see assets/README.md)
assets:
	./gen-assets.sh

## 12-invariant regression suite (needs unicorn)
test harness: $(OUT)
	$(PYTHON) harness/test200.py

clean:
	rm -rf build
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

## also drop the generated assets -- ./gen-assets.sh rebuilds them from assets/unifont.hex
distclean: clean
	rm -f assets/font_*.bin assets/uni_tab.bin

help:
	@sed -n 's/^## //p' Makefile
	@echo
	@echo 'DRASTIC_SRC=/path/to/drastic   (required)'
