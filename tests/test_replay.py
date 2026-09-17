"""Replay engine tests — end-to-end over FakeSurface + fixtures. Requires tesseract.

Proves the determinism contract: same artifact + scripted screens ->
success / business_outcome / recovered, with outputs and clean error separation.
"""
import pytest

from _util import HAS_TESS, ROOT

pytestmark = pytest.mark.skipif(not HAS_TESS, reason="tesseract binary not installed")

from src.artifact import store  # noqa: E402
from src.replay.engine import ReplayEngine  # noqa: E402
from fake_surface import FakeSurface  # noqa: E402

ART = store.load(ROOT / "artifacts" / "member_lookup.json")


def _run(initial, transitions, inputs):
    surface = FakeSurface(initial, transitions)
    engine = ReplayEngine(surface, settle_ms=200, poll_ms=20)
    return engine.run(ART, inputs), surface


HAPPY = {"welcome": ("Member Lookup", "search_form"), "search_form": ("Find", "member_detail")}


def test_happy_path_returns_outputs():
    result, surface = _run("welcome", HAPPY, {"member_id": "12345"})
    assert result.status == "success"
    assert "4,213" in (result.outputs.get("savings_balance") or "")
    assert "Ada" in (result.outputs.get("member_name") or "")
    # input literal was never stored; it was typed into the surface
    assert surface.typed == ["12345"]


def test_not_found_is_business_outcome_not_failure():
    transitions = {"welcome": ("Member Lookup", "search_form"), "search_form": ("Find", "no_member_found")}
    result, _ = _run("welcome", transitions, {"member_id": "00000"})
    assert result.status == "business_outcome"
    assert result.outcome_code == "MEMBER_NOT_FOUND"


def test_validation_error_is_business_outcome():
    transitions = {"welcome": ("Member Lookup", "search_form"), "search_form": ("Find", "validation_error")}
    result, _ = _run("welcome", transitions, {"member_id": "abc"})
    assert result.status == "business_outcome"
    assert result.outcome_code == "INVALID_INPUT"


def test_session_timeout_is_recovered_then_succeeds():
    # submit lands on session_timeout; recovery click on "Continue" advances to member_detail.
    transitions = {
        "welcome": ("Member Lookup", "search_form"),
        "search_form": ("Find", "session_timeout"),
        "session_timeout": ("Continue", "member_detail"),
    }
    result, surface = _run("welcome", transitions, {"member_id": "12345"})
    assert result.status == "success"
    assert "4,213" in (result.outputs.get("savings_balance") or "")
    # recovery consumed an extra click beyond the two scripted user actions
    assert len(surface.clicks) >= 3


def test_precondition_failure_when_wrong_app():
    # Start on a screen with no CoreServ precondition -> app_not_ready hard fail.
    surface = FakeSurface("session_timeout", [])
    # session_timeout fixture still shows CoreServ? It does not (standalone wall),
    # so precondition should fail there.
    engine = ReplayEngine(surface, settle_ms=200, poll_ms=20)
    result = engine.run(ART, {"member_id": "12345"})
    assert result.status == "failed"
    assert result.reason == "app_not_ready"
