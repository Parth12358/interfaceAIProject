"""The capability artifact — typed, versioned, reviewable (Pydantic v2).

This is the contract between the AI agent (caller) and the deterministic replay
engine. It is expressed ONLY in terms of anchors + surface actions + screen-state
assertions, so it is surface-neutral: the same artifact replays over CdpSurface,
OsSurface, or a future desktop surface.

Design points (defended in REPORT):
  1. `target` is an anchor *bundle* with an ordered degradation path
     (text -> context-disambiguated text -> template -> fallback point). Using a
     lower rung is reported, not silent (replay flags the run "degraded").
  2. `expect.any_of` makes every step a branch over known screen-states — the
     error taxonomy lives in the artifact, not in code.
  3. inputs/outputs are the agent-facing typed contract.
  4. `status` gates unattended replay (draft is refused unless --allow-draft).
  5. Input values are placeholders ("{member_id}"); discovery-time literals are
     never persisted.
  6. The `precondition` state class is how a driver-less system verifies it is
     even looking at the right window before acting.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

ActionKind = Literal["click", "type", "read", "key", "wait"]
Relation = Literal["right_of", "left_of", "below", "above", "near"]
StateClass = Literal["precondition", "progress", "business_outcome", "recoverable", "failure"]


# --- Targeting (anchor bundle) ----------------------------------------------
class TextAnchor(BaseModel):
    """Primary locator: find this text via OCR, optionally offset to the action point."""

    text: str
    role_hint: str | None = None  # informational: "link" | "button" | "field" ...
    fuzzy_min: float = Field(0.85, ge=0, le=1)  # rapidfuzz ratio threshold (OCR noise)
    relation: Relation | None = None  # where the action point sits vs the matched text
    max_px: int | None = None  # search radius for the related point


class ContextAnchor(BaseModel):
    """Disambiguator: prefer the text-anchor match nearest this context text."""

    text: str
    relation: Relation = "below"
    max_px: int = 300
    fuzzy_min: float = Field(0.85, ge=0, le=1)


class FallbackPoint(BaseModel):
    """Last resort. Using it marks the run 'degraded'."""

    x: int
    y: int


class Target(BaseModel):
    text_anchor: TextAnchor | None = None
    context_anchor: ContextAnchor | None = None
    template_ref: str | None = None  # path to a saved element crop (relative to artifact dir)
    template_min: float = Field(0.90, ge=0, le=1)
    fallback_point: FallbackPoint | None = None


# --- Steps -------------------------------------------------------------------
class Action(BaseModel):
    kind: ActionKind
    value: str | None = None  # for type/key; parameterized e.g. "{member_id}"


class Expect(BaseModel):
    any_of: list[str] = Field(default_factory=list)  # screen_state names
    timeout_ms: int = 5000


class Step(BaseModel):
    id: str
    action: Action
    target: Target | None = None  # read/click/type need one; wait/key may not
    expect: Expect = Field(default_factory=Expect)
    extract_as: str | None = None  # for read actions: output name to bind


# --- Screen states (the error taxonomy vocabulary) --------------------------
class TextMatcher(BaseModel):
    text: str
    fuzzy_min: float = Field(0.85, ge=0, le=1)


class Recovery(BaseModel):
    kind: Literal["click", "wait", "key"]
    target: Target | None = None
    value: str | None = None
    ms: int | None = None
    max_attempts: int = 1
    then: Literal["retry_step", "continue"] = "retry_step"


class ScreenState(BaseModel):
    all_of: list[TextMatcher] = Field(default_factory=list)
    state_class: StateClass = Field(..., alias="class")
    outcome_code: str | None = None  # for business_outcome: MEMBER_NOT_FOUND, ...
    error_code: str | None = None  # for failure: APP_ERROR, INTEGRITY_ERROR, ...
    recovery: Recovery | None = None  # for recoverable

    model_config = {"populate_by_name": True}


# --- Capability contract -----------------------------------------------------
class InputSpec(BaseModel):
    type: str = "string"
    pattern: str | None = None
    description: str | None = None


class OutputSpec(BaseModel):
    type: str = "string"
    extract: str | None = None  # e.g. "step:read_balance"
    description: str | None = None


class AppRef(BaseModel):
    id: str
    entry: str
    launch: str = "browser-app-mode"
    viewport: tuple[int, int] = (1280, 800)


class Capability(BaseModel):
    id: str
    version: str = "1.0.0"
    status: Literal["draft", "approved"] = "draft"
    description: str = ""
    app: AppRef
    inputs: dict[str, InputSpec] = Field(default_factory=dict)
    outputs: dict[str, OutputSpec] = Field(default_factory=dict)


class Provenance(BaseModel):
    discovered_at: str | None = None
    model: str | None = None
    platform: str | None = None  # informational, not a replay constraint
    surface: Literal["cdp", "os"] | None = None
    discovery_run: str | None = None


class Artifact(BaseModel):
    schema_version: str = SCHEMA_VERSION
    capability: Capability
    steps: list[Step] = Field(default_factory=list)
    screen_states: dict[str, ScreenState] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)

    def state(self, name: str) -> ScreenState | None:
        return self.screen_states.get(name)


def json_schema() -> dict:
    """Exported JSON Schema — a reviewer/agent can validate artifacts against this."""
    return Artifact.model_json_schema(by_alias=True)
