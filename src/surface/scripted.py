"""ScriptedSurface — a Surface backed by saved PNG screens instead of a live browser.

Same protocol as CdpSurface/OsSurface, but returns fixture screenshots and advances
to the next scripted screen only when a click lands on the actual control (located
by OCR). Used for deterministic offline demos/tests and for producing evidence
without a display or network — the live CdpSurface path is identical from the
engine's point of view.
"""
from __future__ import annotations

import pathlib

from ..perception import ocr
from ..perception.match import find_text


class ScriptedSurface:
    def __init__(self, fixtures_dir: str | pathlib.Path, initial: str,
                 transitions: dict[str, tuple[str, str]]):
        self._dir = pathlib.Path(fixtures_dir)
        self.current = initial
        self._transitions = transitions
        self.typed: list[str] = []
        self.clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self._cache: dict[str, list] = {}

    def _png(self, screen: str) -> bytes:
        return (self._dir / f"{screen}.png").read_bytes()

    def _words(self, screen: str):
        if screen not in self._cache:
            self._cache[screen] = ocr.words(self._png(screen))
        return self._cache[screen]

    def screenshot(self) -> bytes:
        return self._png(self.current)

    def click(self, x: int, y: int, pad: int = 18) -> None:
        self.clicks.append((x, y))
        nav = self._transitions.get(self.current)
        if not nav:
            return
        label, to_screen = nav
        for s in find_text(self._words(self.current), label, 0.85):
            if s.left - pad <= x <= s.right + pad and s.top - pad <= y <= s.bottom + pad:
                self.current = to_screen
                return

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def key(self, name: str) -> None:
        self.keys.append(name)

    def viewport(self) -> tuple[int, int]:
        return (1280, 800)

    def close(self) -> None:
        pass
