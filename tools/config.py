"""config.py -- shared paths for the DraStic CJK patch toolchain.

Every tool resolves its inputs through here, so the whole tree is relocatable
and the pristine binary can live anywhere.

    DRASTIC_SRC   path to the *unmodified* `drastic` executable
                  (default: <repo>/drastic)
    DRASTIC_BUILD directory for intermediates (default: <repo>/build)
    DRASTIC_ASSETS directory holding the generated blobs (default: <repo>/assets)

Nothing in this repository ships or downloads the vendor binary -- you must
point DRASTIC_SRC at your own copy.  See NOTICE.md.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SRC = os.environ.get("DRASTIC_SRC") or os.path.join(ROOT, "drastic")
BUILD = os.environ.get("DRASTIC_BUILD") or os.path.join(ROOT, "build")
ASSETS = os.environ.get("DRASTIC_ASSETS") or os.path.join(ROOT, "assets")
SRC_DIR = os.path.join(ROOT, "src")

# generated assets that get committed so builds are byte-reproducible
FONT_FILES = ["font_15.bin", "font_10.bin", "font_8.bin", "font_16.bin",
              "uni_tab.bin"]
MENU_BIN = os.path.join(ASSETS, "menu.bin")
MENU_SITES = os.path.join(ASSETS, "menu_sites.py")


def asset(name):
    return os.path.join(ASSETS, name)


def build(name):
    return os.path.join(BUILD, name)


def require_src():
    """return the pristine binary path, or explain what to do."""
    p = os.path.abspath(SRC)
    if not os.path.isfile(p):
        raise SystemExit(
            "pristine DraStic binary not found: %s\n"
            "Point DRASTIC_SRC at your own unmodified copy, e.g.\n"
            "    DRASTIC_SRC=/path/to/drastic ./build.sh" % p)
    return p
