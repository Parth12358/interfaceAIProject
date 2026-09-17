"""Redaction — thin but real. Mask account-number-like patterns before logging.

The artifact stores parameter *names* only (never discovery-time literals). Logs
run through this hook so long digit runs / card-like / SSN-like values are masked.
Business outputs the caller needs (names, balances) are not account numbers and are
preserved; only account-number-shaped strings are masked.
"""
from __future__ import annotations

import re

# 6+ consecutive digits (account numbers), card-like groups, SSN-like.
_PATTERNS = [
    re.compile(r"\b\d{6,}\b"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
]


def redact_text(s: str) -> str:
    if not s:
        return s
    out = s
    for pat in _PATTERNS:
        out = pat.sub("«redacted»", out)
    return out
