"""Set-of-marks overlay for grounding.

The model never reasons about raw pixels. We OCR the screen, turn salient text
lines into numbered marks, draw them on the screenshot, and let the model act as
"click mark 7" — which we resolve back to coordinates. This is the discovery-time
grounding; replay uses the compiled anchors instead.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ..perception import ocr
from ..perception.ocr import Word


@dataclass(frozen=True)
class Mark:
    id: int
    text: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def cx(self) -> int:
        return int((self.left + self.right) / 2)

    @property
    def cy(self) -> int:
        return int((self.top + self.bottom) / 2)


def build_marks(words: list[Word], png_bytes: bytes | None = None) -> list[Mark]:
    """One mark per visual line, plus detected empty input fields (which have no
    OCR text and would otherwise be untargetable in a no-DOM surface)."""
    marks: list[Mark] = []
    for i, line in enumerate(ocr.lines(words), start=1):
        text = " ".join(w.text for w in line)
        marks.append(Mark(
            id=i, text=text,
            left=min(w.left for w in line), top=min(w.top for w in line),
            right=max(w.right for w in line), bottom=max(w.bottom for w in line),
        ))
    if png_bytes is not None:
        for box in detect_fields(png_bytes, words):
            marks.append(Mark(id=len(marks) + 1, text="(input field)", **box))
    return marks


def detect_fields(png_bytes: bytes, words: list[Word]) -> list[dict]:
    """Heuristically find empty input boxes (wide, short, containing no OCR text)."""
    img = ocr.decode_png(png_bytes)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    word_centers = [(w.cx, w.cy) for w in words]
    boxes: list[dict] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (60 <= w <= 420 and 12 <= h <= 40 and w / max(h, 1) >= 2.5):
            continue
        if any(x <= cx <= x + w and y <= cy <= y + h for cx, cy in word_centers):
            continue  # has text inside -> not an empty field
        if any(abs(b["left"] - x) < 8 and abs(b["top"] - y) < 8 for b in boxes):
            continue  # dedupe near-identical rects
        boxes.append({"left": x, "top": y, "right": x + w, "bottom": y + h})
    return boxes[:6]


def overlay(png_bytes: bytes, marks: list[Mark]) -> bytes:
    """Draw numbered boxes on the screenshot (for the vision model)."""
    img = ocr.decode_png(png_bytes)
    for m in marks:
        cv2.rectangle(img, (m.left, m.top), (m.right, m.bottom), (0, 0, 255), 1)
        cv2.putText(img, str(m.id), (m.left, max(m.top - 2, 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else png_bytes


def legend(marks: list[Mark]) -> str:
    """Text legend so text-only models (or as a vision aid) can ground marks."""
    return "\n".join(f"[{m.id}] '{m.text}' at ({m.cx},{m.cy})" for m in marks)
