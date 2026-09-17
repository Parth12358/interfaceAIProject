"""DPI awareness + scale calibration — OS-conditional, confined to platformx.

For the primary CdpSurface this is largely moot: we pin deviceScaleFactor=1 via
CDP so screenshot pixels and Input coordinates agree by construction. This module
exists for the secondary OsSurface (mss + pyautogui), where display scaling != 100%
would otherwise desync capture pixels and click coordinates on Windows.
"""
from __future__ import annotations

import sys


def set_dpi_awareness() -> None:
    """Declare per-monitor DPI awareness on Windows; no-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        # Older Windows fallback
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def calibrate_scale(capture_size: tuple[int, int], reported_size: tuple[int, int]) -> float:
    """Scale factor = captured pixels / reported logical size (OsSurface only)."""
    cap_w, _ = capture_size
    rep_w, _ = reported_size
    if rep_w == 0:
        return 1.0
    return round(cap_w / rep_w, 4)
