"""FakeSurface — thin test wrapper over the reusable ScriptedSurface, bound to the
tests/fixtures directory. Navigation is realistic (clicks must land on the actual
control located by OCR), so the replay engine is exercised exactly as with a browser.
"""
from __future__ import annotations

from _util import FIXTURES

from src.surface.scripted import ScriptedSurface


class FakeSurface(ScriptedSurface):
    def __init__(self, initial: str, transitions: dict[str, tuple[str, str]]):
        super().__init__(FIXTURES, initial, transitions)
