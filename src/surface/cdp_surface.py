"""CdpSurface — PRIMARY surface. Raw Chrome DevTools Protocol over a websocket.

NO DOM management. We use exactly two CDP capabilities:
  - Page.captureScreenshot        -> pixels
  - Input.dispatchMouseEvent/KeyEvent, Input.insertText -> coordinate input
We never query/select DOM nodes, never read the accessibility tree, never inject
content-script DOM events. OCR + template matching on the screenshot decide *where*;
we send pixel coordinates. This is computer-use over a browser transport, not a
selector-driven browser driver.

Determinism: we pin deviceScaleFactor=1 and a fixed viewport via
Emulation.setDeviceMetricsOverride, so screenshot pixels == CSS pixels == Input
coordinates, with no DPI guesswork.
"""
from __future__ import annotations

import base64
import json
import time

import requests
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

# Minimal key map (extend as needed). CDP wants key/code/keyCode triplets.
_KEYS = {
    "enter": {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
    "tab": {"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9},
    "escape": {"key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27},
    "backspace": {"key": "Backspace", "code": "Backspace", "windowsVirtualKeyCode": 8},
}


class CdpSurface:
    # A form submit can swap the renderer and re-create the page target, so the
    # websocket we hold may close (or stall) mid-navigation. Bound every recv so a
    # stalled capture becomes a recoverable error instead of an infinite hang.
    _RECV_TIMEOUT_S = 8.0

    def __init__(self, port: int, viewport: tuple[int, int] = (1280, 800)):
        self._port = port
        self._w, self._h = viewport
        self._id = 0
        self._ws = None
        self._reconnect()

    def _configure(self) -> None:
        self._send("Page.enable")
        self._send("Runtime.enable")
        # Pin the coordinate space: screenshot px == CSS px == Input coords.
        self._send(
            "Emulation.setDeviceMetricsOverride",
            {"width": self._w, "height": self._h, "deviceScaleFactor": 1, "mobile": False},
        )

    def _reconnect(self) -> None:
        """(Re)acquire the current page target. After a cross-process navigation
        Chrome exposes a NEW target id; the old websocket is stale."""
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws_url = self._find_page_target(self._port)
        self._ws = connect(self._ws_url, max_size=64 * 1024 * 1024, open_timeout=10)
        self._configure()

    # --- CDP transport -------------------------------------------------------
    @staticmethod
    def _find_page_target(port: int, timeout_s: float = 10.0) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                targets = requests.get(f"http://127.0.0.1:{port}/json", timeout=1.0).json()
                pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    return pages[0]["webSocketDebuggerUrl"]
            except Exception:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"No CDP page target found on port {port}")

    def _send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        # Read until the matching command response; discard async events.
        while True:
            raw = self._ws.recv(timeout=self._RECV_TIMEOUT_S)
            msg = json.loads(raw)
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} error: {msg['error']}")
                return msg.get("result", {})

    # --- Surface protocol ----------------------------------------------------
    def screenshot(self) -> bytes:
        try:
            result = self._send("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        except (ConnectionClosed, OSError, TimeoutError):
            # The target was replaced (navigation) — rebind and retry once.
            self._reconnect()
            result = self._send("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        return base64.b64decode(result["data"])

    def click(self, x: int, y: int) -> None:
        base = {"x": int(x), "y": int(y), "button": "left", "clickCount": 1}
        self._send("Input.dispatchMouseEvent", {"type": "mouseMoved", **base})
        self._send("Input.dispatchMouseEvent", {"type": "mousePressed", **base})
        self._send("Input.dispatchMouseEvent", {"type": "mouseReleased", **base})

    def type_text(self, text: str) -> None:
        # insertText inserts into the focused element and fires an input event —
        # no element lookup, purely "type what a keyboard would".
        self._send("Input.insertText", {"text": text})

    def key(self, name: str) -> None:
        spec = _KEYS.get(name.lower())
        if not spec:
            raise ValueError(f"Unknown key: {name}")
        self._send("Input.dispatchKeyEvent", {"type": "keyDown", **spec})
        self._send("Input.dispatchKeyEvent", {"type": "keyUp", **spec})

    def viewport(self) -> tuple[int, int]:
        return (self._w, self._h)

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass
