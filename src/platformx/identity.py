"""Platform identity — the single place outside the rest of the codebase that may
consult `sys.platform` (enforced by tests/test_boundaries.py). Everything above
platformx works with the neutral name returned here.
"""
from __future__ import annotations

import sys

_NEUTRAL_NAMES = {"win32": "windows", "darwin": "macos", "linux": "linux"}


def platform_name() -> str:
    """Return a neutral platform name (windows | macos | linux | <raw>)."""
    return _NEUTRAL_NAMES.get(sys.platform, sys.platform)
