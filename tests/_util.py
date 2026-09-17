"""Shared test helpers: fixture loading + tesseract availability gate."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures"

from src.platformx.tesseract import configure_pytesseract  # noqa: E402

HAS_TESS = configure_pytesseract()


def png(name: str) -> bytes:
    return (FIXTURES / f"{name}.png").read_bytes()
