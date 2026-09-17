"""Browser discovery + launch — OS-conditional, confined to platformx.

Launches chromium at fixed geometry with a remote-debugging port so a Surface
implementation can attach over CDP. This is the ONLY place that knows how to
find/launch a browser per platform; everything above it is platform-agnostic.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time

import requests

# Candidate binaries per platform (first hit wins).
_CANDIDATES = {
    "linux": ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"],
    "win32": ["chrome.exe", "msedge.exe"],
    "darwin": ["Google Chrome", "Chromium"],
}


def find_chromium() -> str:
    for name in _CANDIDATES.get(sys.platform, _CANDIDATES["linux"]):
        path = shutil.which(name)
        if path:
            return path
    # Windows: known install locations (registry lookup omitted for brevity).
    if sys.platform == "win32":
        import os

        for base in (r"C:\Program Files", r"C:\Program Files (x86)"):
            for rel in (r"\Google\Chrome\Application\chrome.exe", r"\Microsoft\Edge\Application\msedge.exe"):
                cand = base + rel
                if os.path.exists(cand):
                    return cand
    raise RuntimeError(
        "No chromium/chrome/edge binary found. Install chromium or set it on PATH."
    )


def launch_chromium(
    url: str,
    port: int,
    viewport: tuple[int, int] = (1280, 800),
    headless: bool = False,
) -> subprocess.Popen:
    """Launch the target in app-mode at fixed geometry with CDP enabled.

    Fixed launch geometry + a stable capture region is our determinism anchor.
    """
    binary = find_chromium()
    profile = tempfile.mkdtemp(prefix="coreserv-chrome-")
    w, h = viewport
    args = [
        binary,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",  # Chrome 111+ requires this for non-browser CDP clients
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-features=Translate,MediaRouter",
        # Containerized/CI stability: chromium's own sandbox can't initialize inside
        # a restricted environment (renderer crashes at first paint), and small
        # /dev/shm crashes the renderer. Standard automation flags.
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--window-size={w},{h}",
        "--window-position=0,0",
        f"--app={url}",
    ]
    if headless:
        args += ["--headless=new", "--disable-gpu"]
    # start_new_session so the caller can kill the whole chromium process group.
    proc = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )
    _wait_for_cdp(port)
    return proc


def kill_process_group(proc: subprocess.Popen) -> None:
    """Kill chromium and all its child processes (it forks a process tree)."""
    if sys.platform == "win32":
        # Windows has no process groups: os.killpg is unavailable and proc.kill()
        # terminates only the browser process, leaking the renderer/gpu children
        # that keep holding the remote-debugging port. taskkill /T reaps the tree.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )
            return
        except Exception:
            pass
    import os
    import signal

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _wait_for_cdp(port: int, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1.0)
            if r.ok:
                return
        except Exception as e:  # not up yet
            last_err = e
        time.sleep(0.2)
    raise RuntimeError(f"Chromium CDP endpoint not ready on port {port}: {last_err}")
