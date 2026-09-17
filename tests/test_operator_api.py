"""Operator console HTTP contract — real mechanism, real status codes (no 500s)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import src.handoff.operator_api as op  # noqa: E402
from src.handoff.control import ControlSession  # noqa: E402


def _client() -> TestClient:
    op.SESSION = ControlSession()  # fresh session per test
    return TestClient(op.app)


def test_full_control_cycle_over_http():
    c = _client()
    assert c.get("/state").json()["state"] == "AUTO_RUNNING"

    r = c.post("/escalate", json={
        "capability_id": "member_lookup", "version": "1.0.0", "step_id": "submit",
        "reason": "unknown_screen", "observed": ["weird"], "log_tail": ["line1"],
    })
    assert r.status_code == 200
    assert r.json()["state"] == "ESCALATED"
    assert r.json()["request"]["capability_id"] == "member_lookup"
    assert r.json()["holder"] is None  # nobody holds the token while escalated

    assert c.post("/take").json()["holder"] == "human"
    assert c.post("/handback").json()["state"] == "RESUMING"
    assert c.post("/resume", json={"recognized": True}).json()["state"] == "AUTO_RUNNING"


def test_illegal_transition_returns_409_not_500():
    c = _client()
    assert c.post("/take").status_code == 409   # not escalated
    assert c.post("/handback").status_code == 409


def test_index_renders_intervention_context():
    c = _client()
    c.post("/escalate", json={"capability_id": "member_lookup", "version": "1.0.0",
                              "step_id": "submit", "reason": "unknown_screen"})
    html = c.get("/").text
    assert "member_lookup" in html
    assert "unknown_screen" in html
