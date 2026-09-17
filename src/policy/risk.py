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


def is_risky(action_kind: str, target_label: str | None, patterns: list[str],
             value: str | None = None) -> bool:
    """True if a mutating action is irreversible.

    Inspects both the target label *and* (for type/key) the action value: a
    destructive action can be triggered by a keystroke or by a value typed into a
    field, not only by the text of the clicked control.
    """
    if action_kind not in MUTATING_KINDS:
        return False
    haystack = " ".join(x for x in (target_label, value) if x).lower()
    if not haystack:
        return False
    return any(re.search(p, haystack) for p in patterns)
