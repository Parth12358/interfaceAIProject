"""Discovery-loop + compiler robustness: dead ends, provider faults, literal safety."""
import pytest

from _util import HAS_TESS, ROOT

pytestmark = pytest.mark.skipif(not HAS_TESS, reason="tesseract binary not installed")

from src.agent.compiler import compile_artifact  # noqa: E402
from src.agent.loop import DiscoveryStep, Trajectory, run_discovery  # noqa: E402
from src.agent.provider import AgentAction, MockProvider  # noqa: E402
from src.artifact.schema import AppRef  # noqa: E402
from src.policy.allowlist import Policy  # noqa: E402
from fake_surface import FakeSurface  # noqa: E402

HAPPY = {"welcome": ("Member Lookup", "search_form"), "search_form": ("Find", "member_detail")}
APP = AppRef(id="coreserv-demo", entry="http://127.0.0.1:5000/")


def _compile(traj):
    return compile_artifact(traj, "cap_test", APP, model="mock", discovery_run="evidence/runs/test")


# --- loop robustness ---------------------------------------------------------
def test_repeated_invalid_marks_stall_not_loop_forever():
    provider = MockProvider([AgentAction(kind="click", mark=999) for _ in range(6)])
    traj = run_discovery("goal", FakeSurface("welcome", HAPPY), provider, max_steps=6)
    assert traj.outcome == "stalled"


def test_repeated_same_action_stalls():
    provider = MockProvider([AgentAction(kind="click", mark=1) for _ in range(6)])
    traj = run_discovery("goal", FakeSurface("welcome", HAPPY), provider, max_steps=6)
    assert traj.outcome == "stalled"


def test_provider_exception_escalates_not_crash():
    class Boom:
        def decide(self, *a, **k):
            raise RuntimeError("network down")

    traj = run_discovery("goal", FakeSurface("welcome", HAPPY), Boom(), max_steps=3)
    assert traj.outcome == "escalated"
    assert "provider_error" in (traj.reason or "")


def test_policy_denial_escalates_discovery():
    provider = MockProvider([AgentAction(kind="click", mark=1)] * 3)
    traj = run_discovery("goal", FakeSurface("welcome", HAPPY), provider, max_steps=3,
                         policy=Policy(allowed_actions={"read"}))
    assert traj.outcome == "escalated"
    assert "policy_denied" in (traj.reason or "")


# --- compiler -----------------------------------------------------------------
def test_type_literal_without_input_is_parameterized_and_not_persisted():
    traj = Trajectory(goal="g", inputs={}, steps=[
        DiscoveryStep(action="type", mark_text="Password", param_value="hunter2secret", post_words=[]),
    ])
    artifact, notes = _compile(traj)
    dump = artifact.model_dump_json()
    assert "hunter2secret" not in dump
    assert "param_0" in artifact.capability.inputs
    assert any("not persisted" in n for n in notes)


def test_compiler_emits_key_step():
    traj = Trajectory(goal="g", inputs={}, steps=[
        DiscoveryStep(action="key", key="enter", post_words=[]),
    ])
    artifact, _ = _compile(traj)
    assert [s.action.kind for s in artifact.steps] == ["key"]
    assert artifact.steps[0].action.value == "enter"


def test_compiler_preserves_done_outputs():
    traj = Trajectory(goal="g", inputs={}, outputs={"confirmation_id": "ABC"}, steps=[])
    artifact, _ = _compile(traj)
    assert "confirmation_id" in artifact.capability.outputs


def test_compiled_artifact_round_trips_through_schema():
    from src.artifact.schema import Artifact

    traj = Trajectory(goal="g", inputs={}, steps=[
        DiscoveryStep(action="click", mark_text="Member Lookup", post_words=[]),
    ])
    artifact, _ = _compile(traj)
    Artifact.model_validate(artifact.model_dump(by_alias=True))
