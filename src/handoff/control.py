"""Control-transfer state machine + single-controller token.

The mechanism is real (the token and transitions are enforced); the operator UI is
a thin mock. Exactly one controller holds the token at a time; automation must assert
it before every Surface action and emits zero input while the human holds it.

  AUTO_RUNNING -(stuck)-> ESCALATED -(take control)-> HUMAN_CONTROL
       ^                                                    |
       |                                              (hand back)
       +------(resume: re-classify recognized)-- RESUMING <-+
                       (still unknown -> ESCALATED/FAILED)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ControlState(str, Enum):
    AUTO_RUNNING = "AUTO_RUNNING"
    ESCALATED = "ESCALATED"
    HUMAN_CONTROL = "HUMAN_CONTROL"
    RESUMING = "RESUMING"
    FAILED = "FAILED"


@dataclass
class InterventionRequest:
    capability_id: str
    version: str
    step_id: str | None
    reason: str
    observed: list = field(default_factory=list)
    screenshot_path: str | None = None
    log_tail: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id, "version": self.version,
            "step_id": self.step_id, "reason": self.reason, "observed": self.observed,
            "screenshot_path": self.screenshot_path, "log_tail": self.log_tail,
        }


class ControlError(RuntimeError):
    pass


class ControlSession:
    """Owns the current control state + token holder ('automation' | 'human' | None)."""

    def __init__(self):
        self.state = ControlState.AUTO_RUNNING
        self.holder: str | None = "automation"
        self.request: InterventionRequest | None = None

    # token guard — asserted before every Surface.act
    def can_act(self, actor: str) -> bool:
        return self.holder == actor

    def assert_can_act(self, actor: str) -> None:
        if not self.can_act(actor):
            raise ControlError(f"{actor} does not hold the control token (holder={self.holder})")

    # transitions
    def escalate(self, request: InterventionRequest) -> None:
        if self.state not in (ControlState.AUTO_RUNNING, ControlState.RESUMING):
            raise ControlError(f"cannot escalate from {self.state}")
        self.state = ControlState.ESCALATED
        self.holder = None  # nobody acts until a human takes control
        self.request = request

    def take_control(self) -> None:
        if self.state != ControlState.ESCALATED:
            raise ControlError(f"cannot take control from {self.state}")
        self.state = ControlState.HUMAN_CONTROL
        self.holder = "human"

    def hand_back(self) -> None:
        if self.state != ControlState.HUMAN_CONTROL:
            raise ControlError(f"cannot hand back from {self.state}")
        self.state = ControlState.RESUMING
        self.holder = None

    def resume(self, recognized: bool) -> ControlState:
        """After hand-back, the engine re-derives state from the screen (never assumes
        what the human did) and reports whether the current screen is recognized."""
        if self.state != ControlState.RESUMING:
            raise ControlError(f"cannot resume from {self.state}")
        if recognized:
            self.state = ControlState.AUTO_RUNNING
            self.holder = "automation"
            self.request = None
        else:
            self.state = ControlState.ESCALATED  # bounce back to a human
            self.holder = None
        return self.state

    def snapshot(self) -> dict:
        return {
            "state": self.state.value,
            "holder": self.holder,
            "request": self.request.to_dict() if self.request else None,
        }
