"""The Surface protocol — the load-bearing seam.

A Surface answers *how we perceive/act on a surface*: pixels in, input events out.
Everything above it (perception, artifact, replay, discovery) deals only in pixels
and coordinates and never imports a concrete Surface. Swapping CdpSurface for
OsSurface (or a future desktop surface) changes nothing downstream.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Surface(Protocol):
    """Minimal contract: see the screen, act on it by coordinate."""

    def screenshot(self) -> bytes:
        """Return a PNG of the current viewport."""
        ...

    def click(self, x: int, y: int) -> None:
        """Left-click at viewport pixel (x, y)."""
        ...

    def type_text(self, text: str) -> None:
        """Type text into whatever is currently focused."""
        ...

    def key(self, name: str) -> None:
        """Press a named key (e.g. 'enter', 'tab')."""
        ...

    def viewport(self) -> tuple[int, int]:
        """Return (width, height) in the same pixel space as screenshot/click."""
        ...

    def close(self) -> None:
        ...
