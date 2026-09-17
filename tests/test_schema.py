"""Artifact schema tests — no OCR / no browser needed."""
from _util import ROOT  # noqa: F401  (sets sys.path)

from src.artifact import store
from src.artifact.schema import Artifact, json_schema


def test_hand_written_artifact_loads_and_validates():
    a = store.load(ROOT / "artifacts" / "member_lookup.json")
    assert a.capability.id == "member_lookup"
    assert a.capability.status == "approved"
    assert len(a.steps) == 5
    assert "no_member_found" in a.screen_states


def test_business_outcome_states_carry_codes():
    a = store.load(ROOT / "artifacts" / "member_lookup.json")
    nm = a.state("no_member_found")
    assert nm.state_class == "business_outcome"
    assert nm.outcome_code == "MEMBER_NOT_FOUND"
    ve = a.state("validation_error")
    assert ve.outcome_code == "INVALID_INPUT"


def test_recoverable_state_has_recovery():
    a = store.load(ROOT / "artifacts" / "member_lookup.json")
    st = a.state("session_timeout")
    assert st.state_class == "recoverable"
    assert st.recovery.kind == "click"
    assert st.recovery.then == "retry_step"


def test_round_trip(tmp_path):
    a = store.load(ROOT / "artifacts" / "member_lookup.json")
    p = tmp_path / "rt.json"
    store.save(a, p)
    b = store.load(p)
    assert b.model_dump() == a.model_dump()


def test_json_schema_exports_top_level():
    sch = json_schema()
    props = set(sch.get("properties", {}))
    assert {"capability", "steps", "screen_states", "provenance"} <= props


def test_submit_step_branches_over_outcomes():
    a = store.load(ROOT / "artifacts" / "member_lookup.json")
    submit = next(s for s in a.steps if s.id == "submit")
    assert set(submit.expect.any_of) == {"member_detail", "no_member_found", "validation_error"}
