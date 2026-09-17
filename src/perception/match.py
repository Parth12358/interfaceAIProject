"""Anchor resolution — turn an artifact `target` into a concrete pixel point.

Ordered degradation path (each rung logged by the caller; a lower rung marks the
run 'degraded'):
    text_anchor (+ optional context disambiguation)  ->  template match  ->  fallback_point

Also provides read_value(): extract the value next to a label for `read` actions,
straight from the word boxes (no re-OCR).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz

from .ocr import Word, decode_png, lines


@dataclass(frozen=True)
class Span:
    text: str
    left: int
    top: int
    right: int
    bottom: int
    score: float

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class Resolution:
    x: int
    y: int
    rung: str  # "text_anchor" | "template" | "fallback_point"
    score: float


def _fuzz(a: str, b: str) -> float:
    return fuzz.ratio(a.lower(), b.lower()) / 100.0


def find_text(words: list[Word], query: str, fuzzy_min: float = 0.85) -> list[Span]:
    """Find fuzzy matches of `query` across visual lines; best span per line."""
    q_words = query.split()
    max_span = len(q_words) + 2
    spans: list[Span] = []
    for line in lines(words):
        best: Span | None = None
        for i in range(len(line)):
            for j in range(i, min(i + max_span, len(line))):
                seq = line[i : j + 1]
                cand = " ".join(w.text for w in seq)
                score = _fuzz(cand, query)
                if score >= fuzzy_min and (best is None or score > best.score):
                    best = Span(
                        text=cand,
                        left=min(w.left for w in seq),
                        top=min(w.top for w in seq),
                        right=max(w.right for w in seq),
                        bottom=max(w.bottom for w in seq),
                        score=score,
                    )
        if best:
            spans.append(best)
    spans.sort(key=lambda s: s.score, reverse=True)
    return spans


def _offset_point(span: Span, relation: str | None, pad: int = 35) -> tuple[int, int]:
    if relation == "right_of":
        return int(span.right + pad), int(span.cy)
    if relation == "left_of":
        return int(span.left - pad), int(span.cy)
    if relation == "below":
        return int(span.cx), int(span.bottom + pad)
    if relation == "above":
        return int(span.cx), int(span.top - pad)
    # near / None -> the matched text's own center (click a link/button)
    return int(span.cx), int(span.cy)


def _pick_with_context(candidates: list[Span], context: list[Span], relation: str, max_px: int) -> Span:
    """Prefer the candidate best satisfying the context relation, else highest score."""
    def ok(c: Span) -> bool:
        if not context:
            return False
        ctx = context[0]
        if relation == "below":
            return 0 <= (c.top - ctx.bottom) <= max_px
        if relation == "above":
            return 0 <= (ctx.top - c.bottom) <= max_px
        if relation == "right_of":
            return 0 <= (c.left - ctx.right) <= max_px
        if relation == "left_of":
            return 0 <= (ctx.left - c.right) <= max_px
        return abs(c.cy - ctx.cy) <= max_px
    preferred = [c for c in candidates if ok(c)]
    return (preferred or candidates)[0]


def resolve_target(words: list[Word], png_bytes: bytes, target, artifact_dir=None) -> Resolution | None:
    """Resolve an artifact Target to a point via the ordered degradation path."""
    # Rung 1: text anchor (+ optional context disambiguation)
    ta = getattr(target, "text_anchor", None)
    if ta:
        cands = find_text(words, ta.text, ta.fuzzy_min)
        if cands:
            ctx = getattr(target, "context_anchor", None)
            if ctx:
                ctx_spans = find_text(words, ctx.text, ctx.fuzzy_min)
                chosen = _pick_with_context(cands, ctx_spans, ctx.relation, ctx.max_px)
            else:
                chosen = cands[0]
            x, y = _offset_point(chosen, ta.relation)
            return Resolution(x=x, y=y, rung="text_anchor", score=chosen.score)

    # Rung 2: template match on a saved element crop
    tref = getattr(target, "template_ref", None)
    if tref and artifact_dir is not None:
        res = _template_match(png_bytes, artifact_dir, tref, target.template_min)
        if res:
            return res

    # Rung 3: fallback point (marks the run degraded)
    fp = getattr(target, "fallback_point", None)
    if fp:
        return Resolution(x=int(fp.x), y=int(fp.y), rung="fallback_point", score=0.0)

    return None


def _template_match(png_bytes: bytes, artifact_dir, tref: str, template_min: float) -> Resolution | None:
    import pathlib

    import cv2

    tpath = pathlib.Path(artifact_dir) / tref
    if not tpath.exists():
        return None
    screen = decode_png(png_bytes)
    template = cv2.imread(str(tpath), cv2.IMREAD_COLOR)
    if template is None:
        return None
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < template_min:
        return None
    th, tw = template.shape[:2]
    return Resolution(x=int(max_loc[0] + tw / 2), y=int(max_loc[1] + th / 2),
                      rung="template", score=float(max_val))


def read_value(words: list[Word], label: str, relation: str = "right_of",
               max_px: int = 400, fuzzy_min: float = 0.85) -> str | None:
    """Extract the value positioned next to a label (for `read` actions)."""
    spans = find_text(words, label, fuzzy_min)
    if not spans:
        return None
    lab = spans[0]
    row_tol = max(10, (lab.bottom - lab.top))
    picked: list[Word] = []
    for w in words:
        # same visual row as the label
        if abs(w.cy - lab.cy) > row_tol:
            continue
        if relation == "right_of" and lab.right <= w.left <= lab.right + max_px:
            picked.append(w)
        elif relation == "left_of" and lab.left - max_px <= w.right <= lab.left:
            picked.append(w)
    picked.sort(key=lambda w: w.left)
    value = " ".join(w.text for w in picked).strip()
    return value or None
