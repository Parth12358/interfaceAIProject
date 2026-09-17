"""OsSurface — SECONDARY surface (documented). OS-level control via mss + pyautogui.

This is the "generalizes to a native desktop app, where there's no DOM at all"
implementation of the same Surface protocol. It is intentionally kept as a real,
compilable second surface to demonstrate the seam: the artifact, perception, and
replay engine are unchanged; only this module differs from CdpSurface.

Runtime cost (documented, not hidden): needs a real display with foreground focus;
on Linux requires X11 (Wayland refuses synthetic input); on Windows needs the DPI
awareness + scale-calibration step (see platformx.win_dpi). Because our dev/CI
environment is Wayland + sandboxed, this path is exercised by design review, not
by the automated demo — CdpSurface is the primary.
"""
from __future__ import annotations

import io

from ..platformx import win_dpi


class OsSurface:
    def __init__(self, region: tuple[int, int, int, int], scale: float = 1.0):
        """region = (left, top, width, height) of the fixed target window."""
        win_dpi.set_dpi_awareness()
        self._left, self._top, self._w, self._h = region
        self._scale = scale
        import mss  # imported lazily so headless/CI import of this module never fails

        self._sct = mss.mss()

    def _to_screen(self, x: int, y: int) -> tuple[int, int]:
        # viewport pixel -> physical screen coordinate (scale-corrected)
        return (
            int(self._left + x / self._scale),
            int(self._top + y / self._scale),
        )

    def screenshot(self) -> bytes:
        import mss.tools

        monitor = {"left": self._left, "top": self._top, "width": self._w, "height": self._h}
        raw = self._sct.grab(monitor)
        buf = io.BytesIO()
        mss.tools.to_png(raw.rgb, raw.size, output=buf)
        return buf.getvalue()

    def click(self, x: int, y: int) -> None:
        import pyautogui

        sx, sy = self._to_screen(x, y)
        pyautogui.click(sx, sy)

    def type_text(self, text: str) -> None:
        import pyautogui

        pyautogui.typewrite(text, interval=0.01)

    def key(self, name: str) -> None:
        import pyautogui

        pyautogui.press(name)

    def viewport(self) -> tuple[int, int]:
        return (self._w, self._h)

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass
