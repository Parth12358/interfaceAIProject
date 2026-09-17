"""Evidence: JSONL step log + per-step screenshots + final result JSON.

One run directory holds everything needed to understand and debug a run. A
redaction hook masks sensitive-looking values before they hit the log — the
artifact and logs store parameter *names* and masked values, never raw secrets.
"""
from __future__ import annotations

import json
import pathlib
import time

from ..policy.redact import redact_text


class RunLog:
    def __init__(self, run_dir: str | pathlib.Path, kind: str = "replay"):
        self.dir = pathlib.Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.kind = kind
        self._seq = 0
        self._log_path = self.dir / "log.jsonl"
        self._t0 = time.time()
        self.event("run_start", kind=kind)

    def event(self, type_: str, **fields) -> None:
        self._seq += 1
        # Redact any string values defensively.
        clean = {k: (redact_text(v) if isinstance(v, str) else v) for k, v in fields.items()}
        rec = {"seq": self._seq, "t_ms": int((time.time() - self._t0) * 1000), "type": type_, **clean}
        with self._log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def screenshot(self, png_bytes: bytes, name: str) -> str:
        path = self.dir / f"{self._seq:02d}_{name}.png"
        path.write_bytes(png_bytes)
        self.event("screenshot", file=path.name, label=name)
        return str(path)

    def result(self, result: dict) -> None:
        (self.dir / "result.json").write_text(json.dumps(result, indent=2))
        self.event("run_end", status=result.get("status"))
