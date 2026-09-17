"""Discovery loop — the ONLY place a model is in the decision loop.

observe (screenshot -> OCR -> set-of-marks) -> decide (provider) -> act (surface),
recording everything, until done / escalate / max-steps. Every action passes the
same policy gate replay uses. Output is a trajectory the compiler turns into a
typed artifact; the model is never consulted again.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..perception import ocr
from ..policy.allowlist import Policy
from ..replay.engine import PolicyDenied
from .marks import Mark, build_marks, legend, overlay
from .provider import AgentAction, Provider


@dataclass
class DiscoveryStep:
    action: str                      # click | type | read | key
    mark_text: str | None = None     # -> anchor
    neighbors: list = field(default_factory=list)
    x: int | None = None
    y: int | None = None
    param_value: str | None = None   # literal typed at discovery (NOT persisted to artifact)
    read_value: str | None = None
    post_state_text: str = ""        # flat text of the resulting screen (logging)
    post_words: list = field(default_factory=list)  # word boxes of the resulting screen (for the compiler)


@dataclass
class Trajectory:
    goal: str
    steps: list = field(default_factory=list)
    outcome: str = "incomplete"      # done | escalated | max_steps | incomplete
    outputs: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)   # {param_name: literal used at discovery}
    reason: str | None = None


def _neighbors(words, mark: Mark) -> list[str]:
    near = [w.text for w in words if abs(w.cy - mark.cy) < 30 and w.text != mark.text]
    return near[:6]


def run_discovery(goal: str, surface, provider: Provider, run_log=None,
                  policy: Policy | None = None, max_steps: int = 12,
                  inputs: dict | None = None) -> Trajectory:
    traj = Trajectory(goal=goal, inputs=dict(inputs or {}))
    policy = policy or Policy()
    history: list[str] = []

    for i in range(max_steps):
        png = surface.screenshot()
        words = ocr.words(png)
        marks = build_marks(words, png)
        by_id = {m.id: m for m in marks}
        if run_log:
            run_log.screenshot(overlay(png, marks), f"disc_{i:02d}")
        action: AgentAction = provider.decide(goal, overlay(png, marks), legend(marks), history)
        if run_log:
            run_log.event("agent_action", step=i, kind=action.kind, mark=action.mark,
                          text=("<param>" if action.text else None))

        if action.kind == "done":
            traj.outcome, traj.outputs = "done", action.outputs
            break
        if action.kind == "escalate":
            traj.outcome, traj.reason = "escalated", action.reason
            break

        # Policy gate — same chokepoint as replay. current_states non-empty iff there is app content.
        label = by_id.get(action.mark).text if action.mark in by_id else None
        try:
            policy.check(action.kind, label, ["discovery"] if marks else [])
        except PolicyDenied as e:
            traj.outcome, traj.reason = "escalated", f"policy_denied:{e.reason}"
            break

        m = by_id.get(action.mark) if action.mark is not None else None
        rec = DiscoveryStep(action=action.kind, mark_text=(m.text if m else None),
                            neighbors=_neighbors(words, m) if m else [],
                            x=(m.cx if m else None), y=(m.cy if m else None))
        if action.kind == "click" and m:
            surface.click(m.cx, m.cy)
        elif action.kind == "type" and m:
            surface.click(m.cx, m.cy)
            surface.type_text(action.text or "")
            rec.param_value = action.text
        elif action.kind == "key":
            surface.key(action.name or "enter")
        elif action.kind == "read" and m:
            from ..perception.match import read_value
            rec.read_value = read_value(words, m.text, "right_of", 400) or m.text

        post = ocr.words(surface.screenshot())
        rec.post_state_text = ocr.full_text(post)
        rec.post_words = post
        traj.steps.append(rec)
        history.append(f"{action.kind}({label or action.text or action.name or ''})")

    else:
        traj.outcome = "max_steps"
    return traj
