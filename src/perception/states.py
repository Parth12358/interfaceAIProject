"""Screen-state matching — classify the current screen against the artifact's states.

A state matches when ALL of its text matchers are found (fuzzy) on screen. When
several states match (e.g. the persistent 'CoreServ' precondition matches on every
screen), the primary is chosen by class priority so business outcomes and progress
states win over the always-present precondition.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .match import find_text
from .ocr import Word

_PRIORITY = {"business_outcome": 3, "recoverable": 2, "progress": 1, "precondition": 0}


def state_matches(words: list[Word], state) -> bool:
    return all(find_text(words, m.text, m.fuzzy_min) for m in state.all_of)


@dataclass
class Classification:
    matched: list[tuple[str, object]] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.matched]

    def primary(self):
        """(name, state) of the highest-priority matched state, or None."""
        if not self.matched:
            return None
        return max(self.matched, key=lambda ns: _PRIORITY.get(ns[1].state_class, 0))


def classify(words: list[Word], screen_states: dict, expected: list[str] | None = None) -> Classification:
    """Return the states that match the current screen.

    If `expected` is given, only those state names are considered — this scopes a
    step's VERIFY to the branch set the artifact declared for that step.
    """
    names = expected if expected is not None else list(screen_states.keys())
    matched = []
    for name in names:
        state = screen_states.get(name)
        if state is not None and state_matches(words, state):
            matched.append((name, state))
    return Classification(matched=matched)
