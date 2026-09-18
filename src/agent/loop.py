"""Discovery loop — the ONLY place a model is in the decision loop.

observe (screenshot -> OCR -> set-of-marks) -> decide (provider) -> act (surface),
recording everything, until done / escalate / max-steps. Every action passes the
same policy gate replay uses. Output is a trajectory the compiler turns into a
typed artifact; the model is never consulted again.
"""
from __future__ import annotations

import hashlib
import time
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
    key: str | None = None           # key name for key actions
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


def _scrub(text, inputs: dict | None) -> str | None:
    """Remove discovery-time literals from free text before it is logged.

    The model's stated rationale (and a target that could be a value mark) is free
    text that may echo the supplied input or observed data. Mask supplied input
    values with their `{param}` placeholder and pass the rest through the same
    redaction hook the run log uses, so no literal reaches evidence.
    """
    if not text:
        return text
    out = str(text)
    for name, val in (inputs or {}).items():
        if val and len(str(val)) >= 2:
            out = out.replace(str(val), "{" + name + "}")
    from ..policy.redact import redact_text
    return redact_text(out)


def _neighbors(words, mark: Mark) -> list[str]:
    near = [w for w in words if abs(w.cy - mark.cy) < 30 and w.text != mark.text]
    # Closest first: for an input field the label ("Member Number") sits on the same
    # row, while unrelated nav text may also fall in the vertical band. Distance
    # ordering makes the compiler's same-row label choice reliable.
    near.sort(key=lambda w: abs(w.cx - mark.cx) + abs(w.cy - mark.cy))
    return [w.text for w in near[:6]]


def _settle(surface, timeout_s: float = 1.5, poll_s: float = 0.3) -> bytes:
    """A click may trigger navigation; capture once two consecutive frames match
    (or the deadline passes), mirroring replay's settle-before-classify."""
    deadline = time.monotonic() + timeout_s
    prev = surface.screenshot()
    prev_h = hashlib.md5(prev).hexdigest()
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        cur = surface.screenshot()
        cur_h = hashlib.md5(cur).hexdigest()
        if cur_h == prev_h:
            return cur
        prev, prev_h = cur, cur_h
    return prev


def _discovery_handoff(control, run_log, step_no: int, reason: str) -> bool:
    """Pause a stuck discovery and let a human take the same live session.

    Returns True if a human took control and handed back (discovery should re-observe
    and continue); False when no control session is wired or nobody responds.
    """
    if control is None:
        return False
    from ..handoff.control import ControlError, ControlState, InterventionRequest

    req = InterventionRequest(
        capability_id="discovery", version="0.0.0", step_id=f"discover_{step_no}",
        reason=reason, observed=[], screenshot_path=None,
        log_tail=run_log.tail(8) if run_log else [])
    try:
        control.escalate(req)
    except ControlError:
        pass  # already escalated (re-entrant handoff)
    if run_log:
        run_log.event("escalated_waiting", step=step_no, reason=reason)
    took_over = control.wait_for_states(
        {ControlState.HUMAN_CONTROL, ControlState.RESUMING}, 600.0)
    if not took_over:
        return False
    if control.state == ControlState.HUMAN_CONTROL:
        control.wait_for_state(ControlState.RESUMING, 600.0)
    try:
        control.resume(True)
    except ControlError:
        pass
    if run_log:
        run_log.event("resume_after_handoff", step=step_no)
    return True


def run_discovery(goal: str, surface, provider: Provider, run_log=None,
                  policy: Policy | None = None, max_steps: int = 12,
                  inputs: dict | None = None, timeout_s: float | None = None,
                  control=None) -> Trajectory:
    traj = Trajectory(goal=goal, inputs=dict(inputs or {}))
    policy = policy or Policy()
    history: list[str] = []
    no_progress = 0
    repeats = 0
    last_signature: str | None = None
    started = time.monotonic()

    def expired() -> bool:
        return timeout_s is not None and (time.monotonic() - started) > timeout_s

    for i in range(max_steps):
        if expired():
            traj.outcome, traj.reason = "timeout", f"wall-clock budget {timeout_s:.0f}s exceeded"
            if run_log:
                run_log.event("discovery_timeout", step=i, budget_s=timeout_s)
            break
        png = surface.screenshot()
        words = ocr.words(png)
        marks = build_marks(words, png)
        by_id = {m.id: m for m in marks}
        if run_log:
            run_log.screenshot(overlay(png, marks), f"disc_{i:02d}")
        if run_log:
            run_log.event("decide_start", step=i, marks=len(marks))
        try:
            action: AgentAction = provider.decide(goal, overlay(png, marks), legend(marks), history)
        except Exception as e:  # provider/network failure must not crash discovery
            traj.outcome, traj.reason = "escalated", f"provider_error:{type(e).__name__}"
            if run_log:
                run_log.event("provider_error", error=str(e)[:200])
            break
        label = by_id.get(action.mark).text if action.mark in by_id else None
        if run_log:
            # Record the target control and the model's stated rationale ("what and
            # why"), scrubbed of discovery-time literals.
            run_log.event("agent_action", step=i, kind=action.kind, mark=action.mark,
                          target=_scrub(label, inputs), text=("<param>" if action.text else None),
                          reason=_scrub(action.reason, inputs))
        if action.kind == "done":
            traj.outcome, traj.outputs = "done", action.outputs
            if run_log:
                run_log.event("agent_done", step=i, outputs=sorted(action.outputs),
                              reason=_scrub(action.reason, inputs))
            break
        if action.kind == "escalate":
            if _discovery_handoff(control, run_log, i, action.reason or "model escalated"):
                last_signature, repeats, no_progress = None, 0, 0
                continue
            traj.outcome, traj.reason = "escalated", action.reason
            break

        # Policy gate — same chokepoint as replay. current_states non-empty iff there is app content.
        try:
            policy.check(action.kind, label, ["discovery"] if marks else [])
        except PolicyDenied as e:
            if _discovery_handoff(control, run_log, i, f"policy_denied:{e.reason}"):
                last_signature, repeats, no_progress = None, 0, 0
                continue
            traj.outcome, traj.reason = "escalated", f"policy_denied:{e.reason}"
            break

        m = by_id.get(action.mark) if action.mark is not None else None
        signature = f"{action.kind}:{action.mark}:{action.text}:{action.name}"
        if signature == last_signature:
            repeats += 1
        else:
            repeats = 0
        last_signature = signature

        if action.kind in ("click", "type", "read") and m is None:
            # A hallucinated/out-of-range mark is a no-op, not an action. Detect the
            # dead end instead of silently burning every remaining step.
            no_progress += 1
            if run_log:
                run_log.event("invalid_mark", step=i, mark=action.mark, kind=action.kind)
            if no_progress >= 3:
                if _discovery_handoff(control, run_log, i, "model selected invalid marks repeatedly"):
                    no_progress = 0
                    continue
                traj.outcome, traj.reason = "stalled", "model selected invalid marks repeatedly"
                break
            history.append(f"{action.kind}(<invalid mark {action.mark}>)")
            continue

        no_progress = 0
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
            rec.key = action.name or "enter"
            surface.key(rec.key)
        elif action.kind == "read" and m:
            from ..perception.match import read_value
            rec.read_value = read_value(words, m.text, "right_of", 400) or m.text

        post = ocr.words(_settle(surface))
        rec.post_state_text = ocr.full_text(post)
        rec.post_words = post
        traj.steps.append(rec)
        if action.kind == "read":
            # Show the model the value it just read so it stops re-reading the same
            # mark and can finish. Discovery-time values stay in the trajectory/
            # history only — the compiler never persists them.
            history.append(f"read('{rec.mark_text or ''}') -> {rec.read_value!r}")
        else:
            why = f" reason={action.reason}" if action.reason else ""
            history.append(f"{action.kind}({label or action.text or action.name or ''}){why}")
        if repeats >= 3:
            if _discovery_handoff(control, run_log, i, "model repeated the same action"):
                last_signature, repeats = None, 0
                continue
            traj.outcome, traj.reason = "stalled", "model repeated the same action repeatedly"
            break

    else:
        traj.outcome = "max_steps"
    return traj
