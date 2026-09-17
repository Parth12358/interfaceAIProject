"""OCR — deterministic word-box extraction over a screenshot.

Pure function of pixels: PNG bytes in, word boxes out. No model, no network.
Everything downstream (anchor resolution, state matching) works on these boxes,
so it is cheap and deterministic to unit-test against saved PNG fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float
    line_id: tuple[int, int, int] = (0, 0, 0)  # (block, par, line) for grouping

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def cx(self) -> float:
        return self.left + self.width / 2

    @property
    def cy(self) -> float:
        return self.top + self.height / 2


def decode_png(png_bytes: bytes) -> np.ndarray:
    """PNG bytes -> BGR image array."""
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode PNG")
    return img


def words(png_bytes: bytes, min_conf: float = 25.0, scale: int = 2) -> list[Word]:
    """Return word boxes above a confidence threshold.

    Legacy screens use small (~11px) fonts and colored values (green balances) plus
    multi-column layouts (a nav link aligned with a content heading). No single
    Tesseract page-segmentation mode reads all of it, so we run two passes and merge:
      - PSM 3  (auto/full layout): reads dense content incl. colored balance values;
      - PSM 11 (sparse text):      reads columned UI chrome (nav) that PSM 3 drops.
    Images are upscaled 2x first (recovers small fonts); coords map back to viewport.

    Live CDP captures on Windows additionally render text with ClearType subpixel
    anti-aliasing (colored red/blue fringes), from which Tesseract drops small bold
    UI text (e.g. a "Find" button) that grayscale-AA fixtures read fine. We therefore
    OCR a second variant — Otsu-binarized at native resolution, then upscaled with the
    same cubic filter — and merge. Because merging only adds candidates (dedupe keeps
    the highest-confidence copy), saving fixtures keep working unchanged.
    """
    import pytesseract

    color = decode_png(png_bytes)
    img = color
    if scale != 1:
        img = cv2.resize(color, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if scale != 1:
        binary = cv2.resize(binary, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    candidates: list[Word] = []
    for variant in (img, binary):
        for psm in ("3", "11"):
            data = pytesseract.image_to_data(variant, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
            for i in range(len(data["text"])):
                text = (data["text"][i] or "").strip()
                if not text or not any(c.isalnum() for c in text):
                    continue  # drop table-border artifacts ("|", "=", "—")
                try:
                    conf = float(data["conf"][i])
                except (TypeError, ValueError):
                    conf = -1.0
                if conf < min_conf:
                    continue
                candidates.append(Word(
                    text=text,
                    left=int(data["left"][i] / scale), top=int(data["top"][i] / scale),
                    width=int(data["width"][i] / scale), height=int(data["height"][i] / scale),
                    conf=conf,
                ))
    return _dedupe(candidates)


def _dedupe(candidates: list[Word], tol: int = 10, iou_thresh: float = 0.5) -> list[Word]:
    """Keep the highest-confidence copy of each word.

    Duplicates come from two sources: the same word read identically by two passes
    (match by text + center proximity), and the same *visual* word read differently by
    the binarized pass ("Account" -> "at"/"4ccou"). The latter fragments are small and
    sit inside the real word's box, so we also drop a lower-confidence box whose center
    falls inside a kept box, or that overlaps a kept box by >= `iou_thresh`. Without
    this, cross-pass garbage pollutes line grouping and splits multi-word labels
    ("Account Nickname") so phrase anchors stop resolving.
    """
    def iou(a: Word, b: Word) -> float:
        x1, y1 = max(a.left, b.left), max(a.top, b.top)
        x2, y2 = min(a.right, b.right), min(a.bottom, b.bottom)
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        if inter <= 0:
            return 0.0
        union = a.width * a.height + b.width * b.height - inter
        return inter / union if union > 0 else 0.0

    def contains(k: Word, w: Word) -> bool:
        return (k.left - 1 <= w.cx <= k.right + 1) and (k.top - 1 <= w.cy <= k.bottom + 1)

    kept: list[Word] = []
    for w in sorted(candidates, key=lambda x: x.conf, reverse=True):
        dup = False
        for k in kept:
            if (k.text.lower() == w.text.lower()
                    and abs(k.cx - w.cx) <= tol and abs(k.cy - w.cy) <= tol):
                dup = True
                break
            if contains(k, w) or iou(k, w) >= iou_thresh:
                dup = True
                break
        if not dup:
            kept.append(w)
    return kept


def full_text(word_list: list[Word]) -> str:
    """Flat text of the screen — for quick 'contains' checks / debugging."""
    return " ".join(w.text for w in word_list)


def lines(word_list: list[Word], gap_px: int = 16) -> list[list[Word]]:
    """Group words into visual line-segments by geometry (robust across PSM modes).

    Words are clustered into rows by vertical proximity, then each row is split on
    large horizontal gaps so separate columns (e.g. left nav vs content) become
    distinct segments instead of one merged line.
    """
    if not word_list:
        return []
    rows: list[dict] = []
    for w in sorted(word_list, key=lambda w: (w.top, w.left)):
        placed = False
        for row in rows:
            if abs(w.cy - row["cy"]) <= max(6, w.height * 0.6):
                row["words"].append(w)
                row["cy"] = sum(x.cy for x in row["words"]) / len(row["words"])
                placed = True
                break
        if not placed:
            rows.append({"cy": w.cy, "words": [w]})

    segments: list[list[Word]] = []
    for row in sorted(rows, key=lambda r: r["cy"]):
        rw = sorted(row["words"], key=lambda w: w.left)
        seg = [rw[0]]
        for prev, cur in zip(rw, rw[1:]):
            if cur.left - prev.right > gap_px:
                segments.append(seg)
                seg = [cur]
            else:
                seg.append(cur)
        segments.append(seg)
    return segments
