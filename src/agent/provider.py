"""LLM provider interface for discovery + a Mock for offline tests.

The discovery loop talks to this 5-function interface only; all model-specifics
live in a provider (llm_deepseek.DeepSeekProvider). Swapping providers is a
one-class change — the loop, recorder, and compiler never import an SDK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class AgentAction:
    kind: str  # click | type | key | read | done | escalate
    mark: int | None = None
    text: str | None = None
    name: str | None = None
    outputs: dict = field(default_factory=dict)
    reason: str | None = None


class Provider(Protocol):
    def decide(self, goal: str, png_overlay: bytes, legend: str, history: list[str]) -> AgentAction:
        ...


class MockProvider:
    """Returns a scripted sequence of actions — drives discovery deterministically
    in tests without a network call or API key."""

    def __init__(self, actions: list[AgentAction]):
        self._actions = list(actions)
        self._i = 0

    def decide(self, goal, png_overlay, legend, history) -> AgentAction:
        if self._i >= len(self._actions):
            return AgentAction(kind="escalate", reason="mock exhausted")
        a = self._actions[self._i]
        self._i += 1
        return a
