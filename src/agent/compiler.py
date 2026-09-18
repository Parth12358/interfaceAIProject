"""Compiler — turn a discovery trajectory into a typed capability artifact (draft).

It substitutes input params for discovery-time literals, builds anchor bundles from
the chosen marks + their neighbors, derives progress screen_states from the observed
post-screens, and grafts in hand-authored error/recoverable states the happy-path
run never hit (a deliberate, documented seam). Emits status=draft plus compile notes.
"""
from __future__ import annotations

import re

from ..artifact.schema import (
    Action, AppRef, Artifact, Capability, Expect, InputSpec, OutputSpec,
    Provenance, ScreenState, Step, Target, TextAnchor, TextMatcher, Recovery,
)
from ..perception.match import find_text

# App-shared error/recoverable taxonomy (hand-authored — discovery of the happy
# path never reaches these). Progress states are derived from observations below.
_ERROR_STATES = {
    "no_member_found": ScreenState(all_of=[TextMatcher(text="No member found")],
                                   **{"class": "business_outcome"}, outcome_code="MEMBER_NOT_FOUND"),
    "validation_error": ScreenState(all_of=[TextMatcher(text="Invalid member number")],
                                    **{"class": "business_outcome"}, outcome_code="INVALID_INPUT"),
    "session_timeout": ScreenState(
        all_of=[TextMatcher(text="Session expired")], **{"class": "recoverable"},
        recovery=Recovery(kind="click", target=Target(text_anchor=TextAnchor(text="Continue")),
                          max_attempts=1, then="retry_step")),
}
# Known progress/precondition signatures for this app family.
_PROGRESS_SIGNATURES = {
    "app_ready": ("CoreServ", "precondition"),
    "search_form": ("Member Search", "progress"),
    "member_detail": ("Member Profile", "progress"),
}


def _param_for_literal(literal: str, inputs: dict) -> str | None:
    for name, val in inputs.items():
        if str(val) == literal:
            return name
    return None


def _infer_pattern(value: str) -> str | None:
    if re.fullmatch(r"\d{5}", value):
        return r"^[0-9]{5}$"
    if value.isdigit():
        return rf"^[0-9]{{{len(value)}}}$"
    return None


def _sanitized_description(trajectory) -> str:
    """Human-readable goal with discovery-time input literals parameterized.

    The discovery loop appends 'Use these input values: {...}' so the model knows
    what to type; that line and any literal value must never be persisted. We drop
    the suffix and substitute each supplied value with its `{param}` placeholder.
    """
    description = (trajectory.goal or "").split("\nUse these input values:")[0].strip()
    for name, val in (trajectory.inputs or {}).items():
        if val and len(str(val)) >= 3:
            description = description.replace(str(val), "{" + name + "}")
    return description or "discovered capability"


_COMMON_WORDS = {
    "the", "and", "for", "with", "this", "that", "from", "have", "home", "search",
    "welcome", "accounts", "transactions", "administration", "navigation", "member",
    "members", "lookup", "login", "logout", "submit", "cancel", "back", "next",
    "continue", "previous", "dashboard", "profile", "details", "account",
}


def _infer_app_ready(trajectory) -> str | None:
    """Infer a precondition anchor from text persistent across the run's screens.

    The app masthead/brand appears on every screen, so the word present on (almost)
    all observed screens and highest on the first is the app-level anchor. This keeps
    a discovered artifact portable instead of hard-coding one app's brand.
    """
    screens = [rec.post_words for rec in trajectory.steps if rec.post_words]
    if not screens:
        return None
    counts: dict[str, int] = {}
    for words in screens:
        for text in {w.text for w in words if _is_brand_candidate(w.text)}:
            counts[text] = counts.get(text, 0) + 1
    threshold = max(1, int(0.8 * len(screens)))
    persistent = [t for t, c in counts.items() if c >= threshold]
    if not persistent:
        return None
    first = screens[0]

    def first_top(text: str) -> int:
        return min((w.top for w in first if w.text == text), default=10 ** 9)

    return min(persistent, key=first_top)


def _is_brand_candidate(text: str) -> bool:
    return (text.isalpha() and 4 <= len(text) <= 24
            and text.lower() not in _COMMON_WORDS
            and any(c.islower() for c in text))


def _output_key(raw: str, idx: int | None = None) -> str:
    """Output names are identifiers, normalized identically wherever they are minted.

    Read steps derive `<label> -> savings_balance`; the model's `done` outputs are
    normalized the same way, otherwise "Savings Balance" and "savings_balance" become
    phantom twins and the entry the model reported is never produced on replay.
    """
    key = "_".join(w.lower() for w in (raw or "value").split()[:2])
    return key or (f"output_{idx}" if idx is not None else "output")


def _state_for_words(words) -> tuple[str | None, str]:
    """Map an observed screen's word boxes to a known state name + class (phrase match)."""
    for name, st in _ERROR_STATES.items():
        if all(find_text(words, m.text, 0.85) for m in st.all_of):
            return name, st.state_class
    for name, (sig, cls) in _PROGRESS_SIGNATURES.items():
        if name != "app_ready" and find_text(words, sig, 0.85):
            return name, cls
    return None, "progress"


def _label_anchor(rec) -> TextAnchor | None:
    """Anchor for a type/read step: the mark's own text, or the nearest label neighbor."""
    text = rec.mark_text
    if not text or text == "(input field)":
        # pick a neighbor that looks like a label (title-case words)
        for n in rec.neighbors:
            if n and n[0:1].isupper():
                return TextAnchor(text=n, relation="right_of", max_px=300)
        return None
    return TextAnchor(text=text, relation="right_of", max_px=300)


def compile_artifact(trajectory, cap_id: str, app: AppRef, model: str,
                     discovery_run: str, platform: str = "linux") -> tuple[Artifact, list[str]]:
    notes: list[str] = []
    steps: list[Step] = []
    screen_states: dict[str, ScreenState] = {}
    outputs: dict[str, OutputSpec] = {}
    inputs: dict[str, InputSpec] = {}

    # Infer the app-level precondition from the run (persistent brand text) rather
    # than hard-coding one app's name, so a discovered artifact is portable.
    app_ready = _infer_app_ready(trajectory)
    if app_ready:
        screen_states["app_ready"] = ScreenState(all_of=[TextMatcher(text=app_ready)], **{"class": "precondition"})
        notes.append(f"Inferred precondition anchor '{app_ready}' (present across observed screens).")
    else:
        notes.append("No persistent precondition text inferred; app_ready omitted.")
    screen_states.update(_ERROR_STATES)
    notes.append("Grafted hand-authored error states (no_member_found, validation_error, "
                 "session_timeout) — not reached by the happy-path discovery run.")

    for idx, rec in enumerate(trajectory.steps):
        post_name, post_cls = _state_for_words(rec.post_words)
        if post_name and post_name in _PROGRESS_SIGNATURES:
            sig, cls = _PROGRESS_SIGNATURES[post_name]
            screen_states[post_name] = ScreenState(all_of=[TextMatcher(text=sig)], **{"class": cls})

        expect_states = [post_name] if post_name else []

        if rec.action == "click":
            # a click that lands on member_detail is the "submit" — it branches over outcomes
            is_submit = post_name == "member_detail"
            if is_submit:
                expect_states = ["member_detail", "no_member_found", "validation_error"]
            steps.append(Step(
                id=f"step_{idx}_{'submit' if is_submit else 'click'}",
                action=Action(kind="click"),
                target=Target(text_anchor=TextAnchor(text=rec.mark_text or "", role_hint="control")),
                expect=Expect(any_of=expect_states, timeout_ms=8000),
            ))
        elif rec.action == "type":
            param = _param_for_literal(rec.param_value or "", trajectory.inputs)
            if param:
                inputs.setdefault(param, InputSpec(
                    type="string", pattern=_infer_pattern(rec.param_value or ""),
                    description=f"{param} (parameterized from discovery)"))
                value = "{" + param + "}"
            else:
                # NEVER persist a discovery-time literal. If it doesn't match a
                # supplied input, synthesize a parameter so the artifact stays
                # value-free (and note the parameterization, not the literal).
                param = f"param_{idx}"
                inputs.setdefault(param, InputSpec(
                    type="string", pattern=_infer_pattern(rec.param_value or ""),
                    description=f"{param} (typed at discovery; value not persisted)"))
                value = "{" + param + "}"
                notes.append(
                    f"Typed value at step {idx} had no matching input; parameterized as "
                    f"'{{{param}}}' (literal intentionally not persisted).")
            steps.append(Step(
                id=f"step_{idx}_enter",
                action=Action(kind="type", value=value),
                target=Target(text_anchor=_label_anchor(rec)),
                expect=Expect(any_of=expect_states, timeout_ms=3000),
            ))
        elif rec.action == "read":
            out_name = _output_key(rec.mark_text, idx)
            outputs[out_name] = OutputSpec(type="string", extract=f"step:step_{idx}_read")
            steps.append(Step(
                id=f"step_{idx}_read", action=Action(kind="read"),
                target=Target(text_anchor=_label_anchor(rec)),
                expect=Expect(any_of=expect_states, timeout_ms=3000),
                extract_as=out_name,
            ))
        elif rec.action == "key":
            steps.append(Step(
                id=f"step_{idx}_key", action=Action(kind="key", value=rec.key or "enter"),
                target=None, expect=Expect(any_of=expect_states, timeout_ms=8000),
            ))
        elif rec.action == "wait":
            steps.append(Step(
                id=f"step_{idx}_wait", action=Action(kind="wait"),
                target=None, expect=Expect(any_of=expect_states),
            ))

    # Outputs the model reported at `done` but that weren't bound by a read step
    # (e.g. a run that finished without explicit reads) are kept as declared outputs,
    # normalized to the same identifier form as read-step outputs so duplicates of a
    # backed output collapse instead of surviving as phantom entries.
    for raw_name, _val in (trajectory.outputs or {}).items():
        outputs.setdefault(_output_key(raw_name), OutputSpec(
            type="string", description="reported by the model at discovery (no read step)"))

    artifact = Artifact(
        capability=Capability(
            id=cap_id, version="1.0.0", status="draft",
            description=_sanitized_description(trajectory),
            app=app, inputs=inputs, outputs=outputs,
        ),
        steps=steps,
        screen_states=screen_states,
        provenance=Provenance(model=model, platform=platform, surface="cdp",
                              discovery_run=discovery_run, discovered_at="discovery"),
    )
    return artifact, notes
