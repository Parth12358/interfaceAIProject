"""Adversarial engine tests — the hardening guarantees, asserted.

Covers the contract that `run()` never raises, that every dispatch is policed, that
artifacts can't escape their directory, and that the result taxonomy is faithful
(business outcome vs recoverable vs hard failure vs escalation).
"""
import pytest

from _util import HAS_TESS, ROOT

pytestmark = pytest.mark.skipif(not HAS_TESS, reason="tesseract binary not installed")

from src.artifact import store  # noqa: E402
from src.artifact.schema import Expect, Target, TextAnchor  # noqa: E402
from src.evidence.run_log import RunLog  # noqa: E402
from src.policy.allowlist import Policy  # noqa: E402
from src.replay.engine import ReplayEngine  # noqa: E402
from fake_surface import FakeSurface  # noqa: E402

ART = store.load(ROOT / "artifacts" / "member_lookup.json")
HAPPY = {"welcome": ("Member Lookup", "search_form"), "search_form": ("Find", "member_detail")}


def _mutate(step_id, **updates):
    a = ART.model_copy(deep=True)
    for s in a.steps:
        if s.id == step_id:
            for k, v in updates.items():
                setattr(s, k, v)
            return a
    raise AssertionError(f"no step {step_id}")


def _run(surface, artifact, inputs, **kw):
    return ReplayEngine(surface, settle_ms=150, poll_ms=15, **kw).run(artifact, inputs)


# --- contract: run never raises ----------------------------------------------
def test_missing_input_is_structured_failure_not_crash():
    result = _run(FakeSurface("welcome", HAPPY), ART, {})
    assert result.status == "failed"
    assert result.reason == "missing_input:member_id"


def test_strict_input_pattern_rejects_bad_value():
    result = _run(FakeSurface("welcome", HAPPY), ART, {"member_id": "abc"}, strict_inputs=True)
    assert result.status == "failed"
    assert result.reason == "invalid_input:member_id"


def test_pattern_mismatch_is_advisory_by_default():
    # "abc" is bad per pattern, but the app's validation screen is the business truth.
    result = _run(FakeSurface("welcome", {"welcome": ("Member Lookup", "search_form"),
                                         "search_form": ("Find", "validation_error")}),
                  ART, {"member_id": "abc"})
    assert result.status == "business_outcome"
    assert result.outcome_code == "INVALID_INPUT"


# --- artifact cannot escape its directory ------------------------------------
def test_template_ref_path_traversal_fails_closed():
    a = _mutate("open_search", target=Target(template_ref="../../../../etc/passwd"))
    result = _run(FakeSurface("welcome", HAPPY), a, {"member_id": "12345"})
    assert result.status == "failed"
    assert result.reason == "target_not_found"


# --- policy ------------------------------------------------------------------
def test_app_id_not_allowed_is_denied():
    result = _run(FakeSurface("welcome", HAPPY), ART, {"member_id": "12345"},
                  policy=Policy(app_id="some-other-app"))
    assert result.status == "failed"
    assert "app_not_allowed" in (result.reason or "")


def test_max_steps_enforced():
    result = _run(FakeSurface("welcome", HAPPY), ART, {"member_id": "12345"},
                  policy=Policy(max_steps=1))
    assert result.status == "failed"
    assert (result.reason or "").startswith("too_many_steps")


def test_typed_value_risk_is_escalated():
    # the *typed value*, not the target label, is destructive here
    a = _mutate("enter_id", action=ART.steps[1].action.model_copy(update={"value": "{member_id}"}))
    result = _run(FakeSurface("welcome", HAPPY), a, {"member_id": "delete all members"},
                  policy=Policy())
    assert result.status == "escalated"
    assert "risky_action" in (result.reason or "")


def test_recovery_action_is_policed():
    # make the recoverable interstitial's recovery click a risky target
    a = ART.model_copy(deep=True)
    st = a.screen_states["session_timeout"]
    st.recovery.target = Target(text_anchor=TextAnchor(text="Delete"))
    transitions = {"welcome": ("Member Lookup", "search_form"),
                   "search_form": ("Find", "session_timeout"),
                   "session_timeout": ("Continue", "member_detail")}
    result = _run(FakeSurface("welcome", transitions), a, {"member_id": "12345"},
                  policy=Policy())
    assert result.status == "escalated"
    assert "policy_denied" in (result.reason or "")


# --- result taxonomy ---------------------------------------------------------
def test_unexpected_business_outcome_surfaced_not_timeout():
    a = _mutate("submit", expect=Expect(any_of=["member_detail"], timeout_ms=3000))
    transitions = {"welcome": ("Member Lookup", "search_form"),
                   "search_form": ("Find", "no_member_found")}
    result = _run(FakeSurface("welcome", transitions), a, {"member_id": "00000"})
    assert result.status == "business_outcome"
    assert result.outcome_code == "MEMBER_NOT_FOUND"


def test_empty_expect_verifies_against_any_known_state():
    a = _mutate("read_name", expect=Expect(any_of=[], timeout_ms=3000))
    result = _run(FakeSurface("welcome", HAPPY), a, {"member_id": "12345"})
    assert result.status == "success"
    assert "Ada" in (result.outputs.get("member_name") or "")


# --- redaction ---------------------------------------------------------------
def test_run_log_redacts_nested_values(tmp_path):
    log = RunLog(tmp_path / "run", kind="test")
    log.event("x", observed=["account 1234567890"], nested={"ssn": "123-45-6789"})
    text = (tmp_path / "run" / "log.jsonl").read_text()
    assert "1234567890" not in text and "123-45-6789" not in text
    assert "redacted" in text


def test_result_json_is_redacted(tmp_path):
    log = RunLog(tmp_path / "run2", kind="test")
    log.result({"status": "success", "outputs": {"account": "1234567890"}})
    text = (tmp_path / "run2" / "result.json").read_text()
    assert "1234567890" not in text
