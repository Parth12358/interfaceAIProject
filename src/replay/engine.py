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

Hardening guarantees:
  * `run()` never raises to the caller — every internal error becomes a structured
    `failed` result (so evidence/result.json is always written).
  * Every surface dispatch (normal steps *and* recovery) passes the policy gate and
    the handoff control-token assertion; there is no unpoliced dispatch path.
  * Escalation builds a real intervention request and, when a control session is
    wired in, pauses until a human takes control and hands back, then re-derives
    state from the screen before resuming.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field

from ..handoff.capture import HumanActionCapture
from ..handoff.control import ControlError, ControlState, InterventionRequest
from ..perception import ocr
from ..perception.match import read_value, resolve_target
from ..perception.states import classify


class PolicyDenied(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Escalation(Exception):
    """Internal signal: this step cannot safely proceed; hand to a human."""

    def __init__(self, reason: str, png: bytes):
        super().__init__(reason)
        self.reason = reason
        self.png = png


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
    capability_id: str | None = None
    capability_version: str | None = None
    intervention: dict | None = None

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
    def __init__(self, surface, policy=None, run_log=None, settle_ms: int = 1500,
                 poll_ms: int = 250, control=None, wait_for_human: bool = True,
                 escalation_timeout_s: float = 600.0, max_step_retries: int = 1,
                 strict_inputs: bool = False):
        self.surface = surface
        self.policy = policy  # object with .check(kind, label, states, value) or None (allow)
        self.log = run_log
        self.settle_ms = settle_ms
        self.poll_ms = poll_ms
        self.control = control  # ControlSession | None
        self.wait_for_human = wait_for_human
        self.escalation_timeout_s = escalation_timeout_s
        self.max_step_retries = max_step_retries
        # Input `pattern` is advisory by default: the target app is the source of
        # truth for business validation, and the artifact declares a business
        # outcome (INVALID_INPUT) precisely so bad input is surfaced, not blocked.
        # `strict_inputs=True` makes a pattern mismatch a hard `invalid_input`.
        self.strict_inputs = strict_inputs
        self.degraded = False
        self._cap = None
        self._last_request: InterventionRequest | None = None

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

    def _assert_automation(self) -> None:
        """Control-token guard: automation may only act while it holds the token."""
        if self.control is not None:
            self.control.assert_can_act("automation")

    def _policy_gate(self, kind: str, label: str | None, states, words, value: str | None = None) -> None:
        """Single dispatch chokepoint: allowlist + screen-scope + risk. Raises PolicyDenied."""
        if not self.policy or states is None:
            return
        names = classify(words, states).names if words is not None else []
        self.policy.check(kind, label, names, value)

    def _gate_or_escalate(self, kind, label, states, words, png, value=None) -> None:
        """Policy gate that converts a denial into an escalation (used by recovery)."""
        try:
            self._policy_gate(kind, label, states, words, value)
        except PolicyDenied as e:
            raise _Escalation(f"policy_denied:{e.reason}", png)

    def _check_inputs(self, cap, inputs: dict) -> str | None:
        """Validate supplied inputs against the artifact's typed contract. Returns error or None."""
        for name, spec in cap.inputs.items():
            if name not in inputs:
                return f"missing_input:{name}"  # cannot run at all without a param
            if spec.pattern:
                try:
                    ok = re.fullmatch(spec.pattern, str(inputs[name])) is not None
                except re.error:
                    continue  # a malformed artifact regex must not crash replay
                if not ok:
                    if self.strict_inputs:
                        return f"invalid_input:{name}"
                    self._emit("input_pattern_warning", input=name)
        return None

    # --- recovery ------------------------------------------------------------
    def _run_recovery(self, png, state, states) -> bytes | None:
        """Execute a recoverable state's recovery, bounded. Return cleared screenshot or None.

        Every recovery dispatch passes the same policy gate + control-token guard as
        a normal step (no unpoliced primitive).
        """
        rec = state.recovery
        if not rec:
            return None
        self._emit("recovery_start", recovery=rec.kind, max_attempts=rec.max_attempts)
        for attempt in range(rec.max_attempts):
            if rec.kind == "wait":
                time.sleep((rec.ms or 500) / 1000)
            elif rec.kind == "click" and rec.target is not None:
                words = ocr.words(png)
                label = rec.target.text_anchor.text if rec.target.text_anchor else None
                self._gate_or_escalate("click", label, states, words, png)
                res = resolve_target(words, png, rec.target)
                if res:
                    self._assert_automation()
                    self.surface.click(res.x, res.y)
            elif rec.kind == "key" and rec.value:
                self._gate_or_escalate("key", None, states, None, png, value=rec.value)
                self._assert_automation()
                self.surface.key(rec.value)
            png = self._settle()
            # cleared if this state no longer matches
            from ..perception.states import state_matches
            if not state_matches(ocr.words(png), state):
                self._emit("recovery_ok", attempt=attempt + 1)
                return png
        self._emit("recovery_exhausted")
        return None

    # --- verify --------------------------------------------------------------
    def _verify(self, expect, states):
        """Poll until an expected state matches; recover interstitials any-time.

        Also surfaces an *unexpected* business outcome that isn't in the step's
        declared branch set, so a legitimate result is never misreported as a
        verify timeout. Returns (name, state, png) or (None, None, last_png).
        """
        expected = expect.any_of or list(states.keys())  # empty any_of == "any known state"
        deadline = time.monotonic() + expect.timeout_ms / 1000
        last_png = self.surface.screenshot()
        while time.monotonic() < deadline:
            png = self._settle()
            last_png = png
            words = ocr.words(png)
            allc = classify(words, states)
            prim = allc.primary()
            if prim and prim[1].state_class == "recoverable" and prim[0] not in expected:
                cleared = self._run_recovery(png, prim[1], states)
                if cleared is None:
                    return (None, None, png)
                continue
            exp = classify(words, states, expected=expected)
            if exp.matched:
                name, state = exp.primary()
                return (name, state, png)
            # unexpected business outcome -> surface it rather than time out
            biz = [ns for ns in allc.matched if ns[1].state_class == "business_outcome"]
            if biz:
                name, state = biz[0]
                return (name, state, png)
            time.sleep(self.poll_ms / 1000)
        return (None, None, last_png)

    # --- run -----------------------------------------------------------------
    def run(self, artifact, inputs: dict, allow_draft: bool = False, artifact_dir=None) -> ReplayResult:
        """Never raises: any internal error becomes a structured `failed` result."""
        try:
            return self._run(artifact, inputs, allow_draft, artifact_dir)
        except Exception as e:  # noqa: BLE001 - contract: run() must not raise
            self._emit("engine_error", error=f"{type(e).__name__}: {e}")
            return ReplayResult(
                status="failed", reason=f"engine_error:{type(e).__name__}",
                observed=[str(e)[:200]], degraded=self.degraded, evidence_dir=self._dir(),
                capability_id=getattr(self._cap, "id", None),
                capability_version=getattr(self._cap, "version", None),
            )

    def _run(self, artifact, inputs: dict, allow_draft: bool, artifact_dir) -> ReplayResult:
        cap = artifact.capability
        self._cap = cap
        states = artifact.screen_states

        if cap.status == "draft" and not allow_draft:
            return self._result("failed", reason="artifact is draft; pass allow_draft to replay")

        if self.policy is not None:
            try:
                self.policy.check_app(cap.app.id)
            except PolicyDenied as e:
                return self._result("failed", reason=f"policy_denied:{e.reason}")

        err = self._check_inputs(cap, inputs)
        if err:
            self._emit("input_invalid", error=err)
            return self._result("failed", reason=err)

        if self.policy and len(artifact.steps) > self.policy.max_steps:
            return self._result("failed", reason=f"too_many_steps:{len(artifact.steps)}>{self.policy.max_steps}")

        # PRE-RUN: assert precondition (are we even looking at the right app?)
        png = self._settle()
        if self.log:
            self.log.screenshot(png, "precondition")
        pre_names = [n for n, s in states.items() if s.state_class == "precondition"]
        pre = classify(ocr.words(png), states, expected=pre_names)
        if pre_names and not pre.matched:
            observed = ocr.full_text(ocr.words(png))[:200]
            self._emit("precondition_failed", expected=pre_names, observed=observed)
            return self._result("failed", reason="app_not_ready", expected=pre_names, observed=[observed])

        outputs: dict = {}
        step_index = 0
        retries = 0
        while step_index < len(artifact.steps):
            step = artifact.steps[step_index]
            try:
                outcome = self._run_step(step, inputs, artifact_dir, states, outputs)
            except _Escalation as esc:
                resumed = self._handle_escalation(step, esc, states)
                if resumed is None and retries < self.max_step_retries:
                    retries += 1
                    continue  # human fixed it; re-derive and retry the same step
                return resumed or self._escalated_result(self._last_request)
            if outcome is not None:
                return outcome
            retries = 0
            step_index += 1

        return self._result("success", outputs=outputs)

    # --- one step ------------------------------------------------------------
    def _run_step(self, step, inputs, artifact_dir, states, outputs) -> ReplayResult | None:
        self._emit("step_start", step=step.id, action=step.action.kind)
        png = self._settle()
        words = ocr.words(png)

        # CLASSIFY (top): unknown screen -> escalate; recover interstitials
        allc = classify(words, states)
        prim = allc.primary()
        if not allc.matched:
            raise _Escalation("unknown_screen", png)
        if prim and prim[1].state_class == "recoverable" and prim[0] not in (step.expect.any_of or []):
            cleared = self._run_recovery(png, prim[1], states)
            if cleared is None:
                raise _Escalation("recovery_exhausted", png)
            png = cleared
            words = ocr.words(png)

        # READ actions extract from the current (verified) screen
        if step.action.kind == "read":
            name, state, png = self._verify(step.expect, states)
            if name is None:
                return self._fail_verify(step, png, states)
            if state.state_class == "business_outcome":  # pragma: no cover - defensive
                return self._outcome(name, state, outputs)
            ta = step.target.text_anchor if step.target else None
            val = None
            if ta:
                rwords = ocr.words(png)
                val = read_value(rwords, ta.text, ta.relation or "right_of",
                                 ta.max_px or 400, ta.fuzzy_min)
            key = step.extract_as or step.id
            outputs[key] = val
            self._emit("extract", step=step.id, output=key, value=val or "")
            return None

        # RESOLVE target
        res = resolve_target(words, png, step.target, artifact_dir) if step.target else None
        if step.target is not None and res is None:
            self._emit("target_not_found", step=step.id)
            if self.log:
                self.log.screenshot(png, f"{step.id}_target_not_found")
            return self._result("failed", reason="target_not_found", failed_step=step.id)
        if res:
            if res.rung == "fallback_point":
                self.degraded = True
            self._emit("resolve", step=step.id, rung=res.rung, score=round(res.score, 3),
                       x=res.x, y=res.y)

        # POLICY gate at the single dispatch chokepoint
        label = step.target.text_anchor.text if (step.target and step.target.text_anchor) else None
        gate_value = None
        if step.action.kind == "type":
            gate_value = _substitute(step.action.value, inputs)  # risk-inspect the actual typed value
        elif step.action.kind == "key":
            gate_value = step.action.value
        try:
            self._policy_gate(step.action.kind, label, states, words, value=gate_value)
        except PolicyDenied as e:
            raise _Escalation(f"policy_denied:{e.reason}", png)

        # ACT (control-token asserted inside _act)
        self._act(step, res, inputs, states, words)

        # VERIFY
        name, state, png = self._verify(step.expect, states)
        if self.log:
            self.log.screenshot(png, f"{step.id}_after")
        if name is None:
            return self._fail_verify(step, png, states)
        self._emit("verify_ok", step=step.id, state=name, state_class=state.state_class)
        if state.state_class == "business_outcome":
            return self._outcome(name, state, outputs)
        return None

    # --- handoff -------------------------------------------------------------
    def _handle_escalation(self, step, esc: _Escalation, states) -> ReplayResult | None:
        """Raise an intervention request; if a control session is wired, pause for a
        human, re-derive state from the screen, and resume (or re-escalate). Returns a
        terminal ReplayResult to stop, or None if the run should retry the step."""
        req = self._build_request(step, esc.reason, states, esc.png)
        self._last_request = req
        if self.control is not None and self.wait_for_human:
            try:
                self.control.escalate(req)
            except ControlError:
                pass  # already escalated (e.g. a re-entrant handoff); just wait
            self._emit("escalated_waiting", step=step.id, reason=esc.reason)
            took_over = self.control.wait_for_states(
                {ControlState.HUMAN_CONTROL, ControlState.RESUMING}, self.escalation_timeout_s)
            if took_over:
                if self.control.state == ControlState.HUMAN_CONTROL:
                    capture = HumanActionCapture(self.log) if self.log else None
                    if capture:
                        capture.start()
                    try:
                        handed_back = self.control.wait_for_state(ControlState.RESUMING,
                                                                  self.escalation_timeout_s)
                    finally:
                        if capture:
                            capture.stop()
                else:
                    handed_back = True  # operator handed back inside one poll window
                if handed_back:
                    png2 = self._settle()
                    cls = classify(ocr.words(png2), states)
                    recognized = bool(cls.matched)
                    self._emit("resume_reclassify", recognized=recognized, observed=cls.names)
                    self.control.resume(recognized)
                    if recognized:
                        return None  # caller retries the step against the live screen
            return self._escalated_result(req)
        # No control session (or wait disabled): record, request, and stop.
        if self.control is not None:
            try:
                self.control.escalate(req)
            except ControlError:
                pass
        return self._escalated_result(req)

    def _build_request(self, step, reason, states, png) -> InterventionRequest:
        observed = classify(ocr.words(png), states).names
        shot = self.log.screenshot(png, f"{step.id}_escalate") if self.log else None
        tail = self.log.tail(8) if self.log else []
        self._emit("escalate", step=step.id, reason=reason, observed=observed)
        return InterventionRequest(
            capability_id=getattr(self._cap, "id", "unknown"),
            version=getattr(self._cap, "version", "0.0.0"),
            step_id=step.id, reason=reason, observed=observed,
            screenshot_path=shot, log_tail=tail,
        )

    # --- act + failure helpers ----------------------------------------------
    def _act(self, step, res, inputs, states, words):
        kind = step.action.kind
        if kind == "click" and res:
            self._assert_automation()
            self.surface.click(res.x, res.y)
        elif kind == "type" and res:
            self._assert_automation()
            self.surface.click(res.x, res.y)  # focus the field
            value = _substitute(step.action.value, inputs)
            self.surface.type_text(value or "")
            self._emit("type", step=step.id, param=step.action.value)  # name, not literal
        elif kind == "key":
            self._assert_automation()
            self.surface.key(step.action.value or "enter")
        elif kind == "wait":
            time.sleep(1.0)

    def _outcome(self, name, state, outputs) -> ReplayResult:
        return self._result("business_outcome", outputs=outputs, outcome_code=state.outcome_code,
                            observed=[name])

    def _fail_verify(self, step, png, states):
        observed = classify(ocr.words(png), states).names or [ocr.full_text(ocr.words(png))[:120]]
        self._emit("verify_timeout", step=step.id, expected=step.expect.any_of, observed=observed)
        if self.log:
            self.log.screenshot(png, f"{step.id}_verify_timeout")
        return self._result("failed", reason="verify_timeout", failed_step=step.id,
                            expected=step.expect.any_of, observed=observed)

    def _escalated_result(self, req: InterventionRequest) -> ReplayResult:
        return self._result("escalated", reason=req.reason, failed_step=req.step_id,
                            observed=req.observed, intervention=req.to_dict())

    def _result(self, status, outputs=None, outcome_code=None, failed_step=None,
                expected=None, observed=None, reason=None, intervention=None) -> ReplayResult:
        return ReplayResult(
            status=status, outputs=outputs or {}, outcome_code=outcome_code,
            failed_step=failed_step, expected=expected, observed=observed,
            degraded=self.degraded, reason=reason, evidence_dir=self._dir(),
            capability_id=getattr(self._cap, "id", None),
            capability_version=getattr(self._cap, "version", None),
            intervention=intervention,
        )

    def _dir(self):
        return str(self.log.dir) if self.log else None
