"""Deterministic replay engine — the production execution path.

NO model in the decision loop. NO import from agent/ or any LLM SDK (CI-enforced by
import-linter). OCR + matching are pure functions of pixels; every branch is
enumerated in the artifact; anything unrecognized halts loudly.

Per-step algorithm:
  SETTLE   -> CLASSIFY (recoverable? business outcome?) -> RESOLVE (anchor bundle)
          -> POLICY -> ACT -> VERIFY (expect.any_of) -> EXTRACT (for reads)

Result contract distinguishes, per the brief:
  success           - goal reached, outputs returned
  business_outcome  - a legitimate result the caller needs (e.g. MEMBER_NOT_FOUND)
  escalated         - could not safely proceed; hand to a human
  failed            - hard, debuggable failure (expected vs observed)
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field

from ..perception import ocr
from ..perception.match import read_value, resolve_target
from ..perception.states import classify


class PolicyDenied(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class ReplayResult:
    status: str  # success | business_outcome | escalated | failed
    outputs: dict = field(default_factory=dict)
    outcome_code: str | None = None
    failed_step: str | None = None
    expected: list | None = None
    observed: list | None = None
    degraded: bool = False
    reason: str | None = None
    evidence_dir: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], {})} or {"status": self.status}


def _substitute(value: str | None, inputs: dict) -> str | None:
    if value is None:
        return None
    def repl(m):
        key = m.group(1)
        if key not in inputs:
            raise KeyError(f"missing input parameter: {key}")
        return str(inputs[key])
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", repl, value)


def _digest(png: bytes) -> str:
    return hashlib.sha1(png).hexdigest()


class ReplayEngine:
    def __init__(self, surface, policy=None, run_log=None, settle_ms: int = 1500, poll_ms: int = 250):
        self.surface = surface
        self.policy = policy  # object with .check(kind, x, y, state_name) or None (allow)
        self.log = run_log
        self.settle_ms = settle_ms
        self.poll_ms = poll_ms
        self.degraded = False

    # --- helpers -------------------------------------------------------------
    def _emit(self, type_, **f):
        if self.log:
            self.log.event(type_, **f)

    def _settle(self) -> bytes:
        """Return a screenshot once two consecutive frames are identical (or timeout)."""
        deadline = time.monotonic() + self.settle_ms / 1000
        prev = self.surface.screenshot()
        prev_h = _digest(prev)
        while time.monotonic() < deadline:
            time.sleep(self.poll_ms / 1000)
            cur = self.surface.screenshot()
            if _digest(cur) == prev_h:
                return cur
            prev, prev_h = cur, _digest(cur)
        return prev

    def _run_recovery(self, png, state, states) -> bytes | None:
        """Execute a recoverable state's recovery, bounded. Return cleared screenshot or None."""
        rec = state.recovery
        if not rec:
            return None
        self._emit("recovery_start", recovery=rec.kind, max_attempts=rec.max_attempts)
        for attempt in range(rec.max_attempts):
            if rec.kind == "wait":
                time.sleep((rec.ms or 500) / 1000)
            elif rec.kind == "click" and rec.target is not None:
                words = ocr.words(png)
                res = resolve_target(words, png, rec.target)
                if res:
                    self.surface.click(res.x, res.y)
            elif rec.kind == "key" and rec.value:
                self.surface.key(rec.value)
            png = self._settle()
            # cleared if this state no longer matches
            from ..perception.states import state_matches
            if not state_matches(ocr.words(png), state):
                self._emit("recovery_ok", attempt=attempt + 1)
                return png
        self._emit("recovery_exhausted")
        return None

    def _verify(self, expect, states):
        """Poll until an expected state matches; recover interstitials any-time.

        Returns (name, state, png) or (None, None, last_png) on timeout.
        """
        deadline = time.monotonic() + expect.timeout_ms / 1000
        last_png = self.surface.screenshot()
        while time.monotonic() < deadline:
            png = self._settle()
            last_png = png
            words = ocr.words(png)
            # recoverable interstitial that isn't part of the expected set
            allc = classify(words, states)
            prim = allc.primary()
            if prim and prim[1].state_class == "recoverable" and prim[0] not in expect.any_of:
                cleared = self._run_recovery(png, prim[1], states)
                if cleared is None:
                    return (None, None, png)
                continue
            exp = classify(words, states, expected=expect.any_of)
            if exp.matched:
                name, state = exp.primary()
                return (name, state, png)
            time.sleep(self.poll_ms / 1000)
        return (None, None, last_png)

    # --- main loop -----------------------------------------------------------
    def run(self, artifact, inputs: dict, allow_draft: bool = False, artifact_dir=None) -> ReplayResult:
        cap = artifact.capability
        states = artifact.screen_states

        if cap.status == "draft" and not allow_draft:
            return ReplayResult(status="failed", reason="artifact is draft; pass allow_draft to replay")

        # PRE-RUN: assert precondition (are we even looking at the right app?)
        png = self._settle()
        if self.log:
            self.log.screenshot(png, "precondition")
        pre_names = [n for n, s in states.items() if s.state_class == "precondition"]
        pre = classify(ocr.words(png), states, expected=pre_names)
        if pre_names and not pre.matched:
            observed = ocr.full_text(ocr.words(png))[:200]
            self._emit("precondition_failed", expected=pre_names, observed=observed)
            return ReplayResult(status="failed", reason="app_not_ready", expected=pre_names,
                                observed=[observed], evidence_dir=str(self.log.dir) if self.log else None)

        outputs: dict = {}
        for step in artifact.steps:
            self._emit("step_start", step=step.id, action=step.action.kind)
            png = self._settle()
            words = ocr.words(png)

            # CLASSIFY (top): recover interstitials, catch unexpected business outcomes
            allc = classify(words, states)
            prim = allc.primary()
            if prim and prim[1].state_class == "recoverable":
                cleared = self._run_recovery(png, prim[1], states)
                if cleared is None:
                    return self._escalate(step, "recovery_exhausted", states, png)
                png = cleared
                words = ocr.words(png)

            # READ actions extract from the current (verified) screen
            if step.action.kind == "read":
                name, state, png = self._verify(step.expect, states)
                if name is None:
                    return self._fail_verify(step, png, states)
                ta = step.target.text_anchor if step.target else None
                val = None
                if ta:
                    val = read_value(words if state else ocr.words(png), ta.text,
                                     ta.relation or "right_of", ta.max_px or 400, ta.fuzzy_min)
                key = step.extract_as or step.id
                outputs[key] = val
                self._emit("extract", step=step.id, output=key, value=val or "")
                continue

            # RESOLVE target
            res = resolve_target(words, png, step.target, artifact_dir) if step.target else None
            if step.target is not None and res is None:
                self._emit("target_not_found", step=step.id)
                if self.log:
                    self.log.screenshot(png, f"{step.id}_target_not_found")
                return ReplayResult(status="failed", failed_step=step.id, reason="target_not_found",
                                    degraded=self.degraded, evidence_dir=self._dir())
            if res:
                if res.rung == "fallback_point":
                    self.degraded = True
                self._emit("resolve", step=step.id, rung=res.rung, score=round(res.score, 3),
                           x=res.x, y=res.y)

            # POLICY gate at the single dispatch chokepoint (screen-scope + risk + allowlist)
            try:
                if self.policy:
                    label = step.target.text_anchor.text if (step.target and step.target.text_anchor) else None
                    self.policy.check(step.action.kind, label, allc.names)
            except PolicyDenied as e:
                return self._escalate(step, f"policy_denied:{e.reason}", states, png)

            # ACT
            self._act(step, res, inputs)

            # VERIFY
            name, state, png = self._verify(step.expect, states)
            if self.log:
                self.log.screenshot(png, f"{step.id}_after")
            if name is None:
                return self._fail_verify(step, png, states)
            self._emit("verify_ok", step=step.id, state=name, state_class=state.state_class)
            if state.state_class == "business_outcome":
                return ReplayResult(status="business_outcome", outcome_code=state.outcome_code,
                                    outputs=outputs, degraded=self.degraded,
                                    observed=[name], evidence_dir=self._dir())

        return ReplayResult(status="success", outputs=outputs, degraded=self.degraded,
                            evidence_dir=self._dir())

    # --- act + failure helpers ----------------------------------------------
    def _act(self, step, res, inputs):
        kind = step.action.kind
        if kind == "click" and res:
            self.surface.click(res.x, res.y)
        elif kind == "type" and res:
            self.surface.click(res.x, res.y)  # focus the field
            value = _substitute(step.action.value, inputs)
            self.surface.type_text(value or "")
            self._emit("type", step=step.id, param=step.action.value)  # name, not literal
        elif kind == "key":
            self.surface.key(step.action.value or "enter")
        elif kind == "wait":
            time.sleep(1.0)

    def _fail_verify(self, step, png, states):
        observed = classify(ocr.words(png), states).names or [ocr.full_text(ocr.words(png))[:120]]
        self._emit("verify_timeout", step=step.id, expected=step.expect.any_of, observed=observed)
        if self.log:
            self.log.screenshot(png, f"{step.id}_verify_timeout")
        return ReplayResult(status="failed", failed_step=step.id, reason="verify_timeout",
                            expected=step.expect.any_of, observed=observed,
                            degraded=self.degraded, evidence_dir=self._dir())

    def _escalate(self, step, reason, states, png):
        observed = classify(ocr.words(png), states).names
        self._emit("escalate", step=step.id, reason=reason, observed=observed)
        if self.log:
            self.log.screenshot(png, f"{step.id}_escalate")
        return ReplayResult(status="escalated", failed_step=step.id, reason=reason,
                            observed=observed, degraded=self.degraded, evidence_dir=self._dir())

    def _dir(self):
        return str(self.log.dir) if self.log else None
