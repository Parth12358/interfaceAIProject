"""Risk classification for actions.

read  = safe (reversible).
click on a target whose label matches an irreversible pattern (Confirm Transfer,
Delete, Post Transaction, ...) = risky -> blocked in unattended replay, escalated
to a human. Unknown action kinds default-deny.
"""
from __future__ import annotations

import re

DEFAULT_RISKY_PATTERNS = [
    r"confirm\s+transfer",
    r"\bdelete\b",
    r"post\s+transaction",
    r"\bsubmit\s+payment\b",
    r"\bwire\b",
    r"\bapprove\b",
    r"\bclose\s+account\b",
]

SAFE_KINDS = {"read", "wait"}
MUTATING_KINDS = {"click", "type", "key"}


def is_risky(action_kind: str, target_label: str | None, patterns: list[str]) -> bool:
    if action_kind not in MUTATING_KINDS:
        return False
    if not target_label:
        return False
    label = target_label.lower()
    return any(re.search(p, label) for p in patterns)
