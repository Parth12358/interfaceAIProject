"""Live end-to-end pass over the multi-tenant banking test sites.

Opt-in because it launches a real Chrome and the site server. Run it with:

    set RUN_LIVE=1
    pytest tests/test_live_sites.py -q

It drives scripts/live_site_matrix.py, which replays every capability against the
live sites and asserts the assignment's full result taxonomy. Requires Tesseract,
Chrome, and no API key (replay only).
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from _util import HAS_TESS, ROOT

pytestmark = pytest.mark.skipif(
    not (HAS_TESS and os.environ.get("RUN_LIVE") == "1"),
    reason="live site matrix is opt-in: set RUN_LIVE=1 (needs tesseract + Chrome)",
)


def test_live_site_matrix():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "live_site_matrix.py")],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, "live site matrix reported failures"
