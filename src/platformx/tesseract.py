"""Tesseract binary resolution — confined to platformx (OS-conditional paths)."""
from __future__ import annotations

import os
import shutil
import sys


# A no-root local extraction location (used when a system package isn't installed).
_LOCAL_PREFIX = os.path.expanduser("~/.local/tess")
_LOCAL_BIN = os.path.join(_LOCAL_PREFIX, "usr", "bin", "tesseract")


def resolve_tesseract() -> str | None:
    """Return the tesseract binary path, or None if not found."""
    env = os.environ.get("TESSERACT_CMD")
    if env and os.path.exists(env):
        return env
    found = shutil.which("tesseract")
    if found:
        return found
    if os.path.exists(_LOCAL_BIN):
        return _LOCAL_BIN
    if sys.platform == "win32":
        for cand in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(cand):
                return cand
    return None


def configure_pytesseract() -> bool:
    """Point pytesseract at the resolved binary. Returns True if configured.

    pytesseract invokes the binary as a subprocess, so setting LD_LIBRARY_PATH /
    TESSDATA_PREFIX in os.environ here is enough for a no-root local extraction to
    load its bundled leptonica and language data.
    """
    path = resolve_tesseract()
    if not path:
        return False
    # If the binary lives under a self-contained prefix, wire up its libs/data.
    prefix = os.path.dirname(os.path.dirname(os.path.dirname(path)))  # .../usr/bin/tesseract -> prefix
    lib = os.path.join(prefix, "usr", "lib")
    tessdata = os.path.join(prefix, "usr", "share", "tessdata")
    if os.path.isdir(lib) and prefix != "/":
        os.environ["LD_LIBRARY_PATH"] = lib + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
    if os.path.isdir(tessdata) and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = tessdata

    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = path
    return True
