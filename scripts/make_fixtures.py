"""Generate PNG screen fixtures for offline perception/replay tests.

Renders each CoreServ screen's HTML via the Flask test client (no server needed),
then rasterizes it with a one-shot headless chromium screenshot. These fixtures
let perception and the replay engine be tested deterministically with no live
browser — the live CdpSurface path is exercised separately in the demo.

Usage:  python scripts/make_fixtures.py
Output: tests/fixtures/<screen>.png  (1280x800)
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
VIEWPORT = (1280, 800)

# Arm the timeout interstitial so we can render it.
os.environ["CORESERV_INJECT_TIMEOUT"] = "1"
sys.path.insert(0, str(ROOT))
from target_app.app import app  # noqa: E402


def render(client, method: str, path: str, data=None) -> str:
    fn = client.post if method == "POST" else client.get
    resp = fn(path, data=data)
    return resp.get_data(as_text=True)


def shoot(html: str, out: pathlib.Path) -> None:
    binary = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not binary:
        raise RuntimeError("no chromium binary found")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name
    w, h = VIEWPORT
    subprocess.run(
        [
            binary, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-dev-shm-usage", "--hide-scrollbars",
            f"--window-size={w},{h}", f"--screenshot={out}", f"file://{html_path}",
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
    )
    os.unlink(html_path)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    client = app.test_client()
    screens = {
        "welcome": ("GET", "/", None),
        "search_form": ("GET", "/search", None),
        "member_detail": ("POST", "/continue", None),   # after timeout cleared -> real result
        "no_member_found": ("POST", "/search", {"member_number": "00000"}),
        "validation_error": ("POST", "/search", {"member_number": "abc"}),
        "session_timeout": ("POST", "/search", {"member_number": "12345"}),
    }
    # member_detail needs a pending member; prime session via a client that has timeout armed:
    # simplest: render member_detail directly by disarming timeout for that one.
    with app.test_request_context():
        pass

    for name, (method, path, data) in screens.items():
        # For member_detail, use a fresh client with timeout disarmed.
        if name == "member_detail":
            os.environ["CORESERV_INJECT_TIMEOUT"] = "0"
            c2 = app.test_client()
            html = render(c2, "POST", "/search", {"member_number": "12345"})
            os.environ["CORESERV_INJECT_TIMEOUT"] = "1"
        elif name == "session_timeout":
            html = render(app.test_client(), method, path, data)
        else:
            os.environ["CORESERV_INJECT_TIMEOUT"] = "0"
            html = render(app.test_client(), method, path, data)
            os.environ["CORESERV_INJECT_TIMEOUT"] = "1"
        out = FIXTURES / f"{name}.png"
        shoot(html, out)
        print(f"  wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
