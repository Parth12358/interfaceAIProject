"""Discovery -> compile -> replay round-trip, driven by a mock provider (no API key).

Proves the compiler emits a valid, replayable artifact from a recorded trajectory —
the same code path the real DeepSeek run uses, minus the network.
"""
import re

import pytest

from _util import HAS_TESS

pytestmark = pytest.mark.skipif(not HAS_TESS, reason="tesseract binary not installed")

from src.agent.compiler import compile_artifact  # noqa: E402
from src.agent.loop import run_discovery  # noqa: E402
from src.agent.provider import AgentAction  # noqa: E402
from src.artifact.schema import AppRef, Artifact  # noqa: E402
from src.replay.engine import ReplayEngine  # noqa: E402
from fake_surface import FakeSurface  # noqa: E402

HAPPY = {"welcome": ("Member Lookup", "search_form"), "search_form": ("Find", "member_detail")}


class TextMock:
    """Scripted provider that resolves marks from the legend by (exact-first) text match."""

    def __init__(self, script):
        self._script = list(script)
        self._i = 0

    def decide(self, goal, png_overlay, legend, history):
        if self._i >= len(self._script):
            return AgentAction(kind="done", outputs={})
        kind, target, text = self._script[self._i]
        self._i += 1
        if kind in ("done", "escalate"):
            return AgentAction(kind=kind, outputs={}, reason="scripted")
        mark = self._resolve(legend, target)
        return AgentAction(kind=kind, mark=mark, text=text)

    @staticmethod
    def _resolve(legend, target):
        rows = re.findall(r"\[(\d+)\]\s+'([^']*)'", legend)
        for mid, txt in rows:  # exact (case-insensitive) first
            if txt.strip().lower() == target.lower():
                return int(mid)
        for mid, txt in rows:  # substring fallback
            if target.lower() in txt.lower():
                return int(mid)
        return None


SCRIPT = [
    ("click", "Member Lookup", None),
    ("type", "Member Number", "12345"),
    ("click", "Find", None),
    ("read", "Savings Balance", None),
    ("read", "Member Name", None),
    ("done", None, None),
]


def test_discovery_compiles_valid_replayable_artifact():
    # 1. discover
    surface = FakeSurface("welcome", HAPPY)
    traj = run_discovery("Look up member 12345 and read savings balance", surface,
                         TextMock(SCRIPT), inputs={"member_id": "12345"}, max_steps=8)
    assert traj.outcome == "done"
    assert len(traj.steps) == 5

    # 2. compile
    app = AppRef(id="coreserv-demo", entry="http://127.0.0.1:5000/")
    artifact, notes = compile_artifact(traj, "member_lookup_discovered", app,
                                       model="deepseek-flash", discovery_run="evidence/runs/test")
    assert isinstance(artifact, Artifact)
    assert artifact.capability.status == "draft"
    assert "member_id" in artifact.capability.inputs
    assert artifact.capability.inputs["member_id"].pattern == r"^[0-9]{5}$"
    assert set(artifact.capability.outputs) == {"savings_balance", "member_name"}
    assert any("hand-authored error states" in n for n in notes)

    # 3. replay the compiled draft artifact -> success with outputs
    fresh = FakeSurface("welcome", HAPPY)
    engine = ReplayEngine(fresh, settle_ms=200, poll_ms=20)
    result = engine.run(artifact, {"member_id": "12345"}, allow_draft=True)
    assert result.status == "success"
    assert "4,213" in (result.outputs.get("savings_balance") or "")
    assert "Ada" in (result.outputs.get("member_name") or "")
