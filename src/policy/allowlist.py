"""Policy gate — enforced at the single dispatch chokepoint both discovery and
replay pass through (engine calls Policy.check before every action).

Three rules:
  1. Action allowlist: only permitted action kinds may run.
  2. Screen-scope: since there is no navigation API to gate, the current screen
     must match a known state of the allowed app; if the foreground content stops
     matching (wrong window / unexpected app), acting is refused and the run
     escalates. This is how a driver-less system stays inside its lane.
  3. Risk: risky/irreversible actions are blocked in unattended replay and
     escalated to a human (see risk.py). Unknown action kinds default-deny.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from ..replay.engine import PolicyDenied  # shared exception type
from .risk import DEFAULT_RISKY_PATTERNS, is_risky


@dataclass
class Policy:
    app_id: str = "coreserv-demo"
    allowed_actions: set = field(default_factory=lambda: {"click", "type", "read", "key", "wait"})
    max_steps: int = 25
    risky_patterns: list = field(default_factory=lambda: list(DEFAULT_RISKY_PATTERNS))
    unattended: bool = True  # block risky actions instead of prompting

    def check(self, action_kind: str, target_label: str | None, current_states: list[str]) -> None:
        # 1. action allowlist (default-deny unknown kinds)
        if action_kind not in self.allowed_actions:
            raise PolicyDenied(f"action '{action_kind}' not in allowlist")
        # 2. screen-scope: must be on a known state of the allowed app
        if not current_states:
            raise PolicyDenied("off_app: current screen matches no known app state")
        # 3. risk gate
        if self.unattended and is_risky(action_kind, target_label, self.risky_patterns):
            raise PolicyDenied(f"risky_action: '{target_label}' requires human confirmation")

    @staticmethod
    def load(path: str | pathlib.Path) -> "Policy":
        data = json.loads(pathlib.Path(path).read_text())
        return Policy(
            app_id=data.get("app_id", "coreserv-demo"),
            allowed_actions=set(data.get("allowed_actions", ["click", "type", "read", "key", "wait"])),
            max_steps=int(data.get("max_steps", 25)),
            risky_patterns=data.get("risky_patterns", list(DEFAULT_RISKY_PATTERNS)),
            unattended=bool(data.get("unattended", True)),
        )
