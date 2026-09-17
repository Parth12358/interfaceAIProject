"""Redaction — thin but real. Mask account-number-like patterns before logging.

The artifact stores parameter *names* only (never discovery-time literals). Logs
run through this hook so long digit runs / card-like / SSN-like values are masked.
Business outputs the caller needs (names, balances) are not account numbers and are
preserved; only account-number-shaped strings are masked.
"""
from __future__ import annotations

import re

# Account/PII shapes, plus credential shapes (API keys, bearer tokens, secrets).
_PATTERNS = [
    re.compile(r"\b\d{6,}\b"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Credentials: provider keys, bearer tokens, JWT-ish, and key=value secrets.
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b(?:sk|pk|rk|ghp|xox[baprs])-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}\b"),
    re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret)\b"
               r"\s*[:=]\s*[^\s,;\"']+"),
]


def redact_text(s: str) -> str:
    if not s:
        return s
    out = s
    for pat in _PATTERNS:
        out = pat.sub("«redacted»", out)
    return out


def redact_data(obj):
    """Recursively redact string values inside dicts/lists/tuples.

    `RunLog.event` used to redact only top-level strings, so a sensitive value nested
    in `observed`/`expected`/`outputs` was persisted raw. This closes that gap for
    both the JSONL log and `result.json`.
    """
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact_data(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_data(v) for v in obj]
    return obj
