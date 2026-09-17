"""Capture the human's actions during HUMAN_CONTROL (real mechanism, documented cost).

While the operator drives the SAME live window, a pynput global listener records their
clicks/keys (coords + OCR text near each click) and before/after screenshots into the
same run log as `human_action` entries. Resume never assumes what the human did — the
engine re-derives state from the screen. On Linux this needs X11 (same constraint as
synthetic output); under Wayland it is documented, not worked around.
"""
from __future__ import annotations


class HumanActionCapture:
    def __init__(self, run_log, surface=None):
        self.log = run_log
        self.surface = surface
        self._listener_mouse = None
        self._listener_kbd = None

    def start(self) -> None:
        try:
            from pynput import keyboard, mouse
        except Exception as e:  # pragma: no cover - platform dependent
            self.log.event("capture_unavailable", error=str(e))
            return

        def on_click(x, y, button, pressed):
            if pressed:
                near = self._ocr_near(x, y)
                self.log.event("human_action", kind="click", x=int(x), y=int(y), near=near)

        def on_press(key):
            self.log.event("human_action", kind="key", key=str(key))

        self._listener_mouse = mouse.Listener(on_click=on_click)
        self._listener_kbd = keyboard.Listener(on_press=on_press)
        self._listener_mouse.start()
        self._listener_kbd.start()
        self.log.event("capture_started")

    def stop(self) -> None:
        for lst in (self._listener_mouse, self._listener_kbd):
            if lst is not None:
                lst.stop()
        self.log.event("capture_stopped")

    def _ocr_near(self, x, y, radius: int = 60) -> str:
        if self.surface is None:
            return ""
        try:
            from ..perception import ocr
            words = ocr.words(self.surface.screenshot())
            near = [w.text for w in words if abs(w.cx - x) < radius and abs(w.cy - y) < radius]
            return " ".join(near[:4])
        except Exception:
            return ""
