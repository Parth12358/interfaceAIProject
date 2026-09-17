"""Engine <-> handoff integration: the control token, pause, and resume are real.

These tests exercise the seam the interview's §3.6 requires: a replay that escalates
must actually stop acting, let a human take the *same* live session, then re-derive
state from the screen and resume -- or re-escalate if still unrecognized.
"""
import threading
import time

import pytest

from _util import HAS_TESS, ROOT, png

pytestmark = pytest.mark.skipif(not HAS_TESS, reason="tesseract binary not installed")

from src.artifact import store  # noqa: E402
from src.evidence.run_log import RunLog  # noqa: E402
from src.handoff.control import ControlSession, ControlState  # noqa: E402
from src.replay.engine import ReplayEngine  # noqa: E402

ART = store.load(ROOT / "artifacts" / "member_lookup.json")
HAPPY = {"welcome": ("Member Lookup", "search_form"), "search_form": ("Find", "member_detail")}


class InterruptingSurface:
    """Fixture-backed surface that shows an *unknown* screen after the precondition,
    forcing the first step to escalate. `human_fix` models the operator repairing the
    live session; resume then re-classifies the repaired screen."""

    def __init__(self):
        self.current = "welcome"
        self.arm = True
        self._calls = 0
        self.clicks: list[tuple[int, int]] = []
        self.typed: list[str] = []
        self.keys: list[str] = []
        self._transitions = dict(HAPPY)

    def screenshot(self) -> bytes:
        self._calls += 1
        if self.arm and self._calls > 2:  # after the precondition's stable read
            self.current = "unknown"
        return png(self.current)

    def human_fix(self, screen: str) -> None:
        self.arm = False
        self.current = screen

    def click(self, x: int, y: int, pad: int = 18) -> None:
        from src.perception.match import find_text
        from src.perception import ocr

        self.clicks.append((x, y))
        nav = self._transitions.get(self.current)
        if not nav:
            return
        label, to_screen = nav
        for s in find_text(ocr.words(png(self.current)), label, 0.85):
            if s.left - pad <= x <= s.right + pad and s.top - pad <= y <= s.bottom + pad:
                self.current = to_screen
                return

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def key(self, name: str) -> None:
        self.keys.append(name)

    def viewport(self) -> tuple[int, int]:
        return (1280, 800)

    def close(self) -> None:
        pass


def _operator(control, surface, target):
    """Simulated human: wait for escalation, fix the screen, take control, hand back."""
    try:
        deadline = time.monotonic() + 10
        while control.state != ControlState.ESCALATED and time.monotonic() < deadline:
            time.sleep(0.01)
        surface.human_fix(target)
        control.take_control()
        time.sleep(0.25)  # "operate the live session"
        control.hand_back()
    except Exception:  # pragma: no cover - surfaced by assertions, not a thread warning
        pass


def test_escalation_pauses_then_resumes_to_success():
    control = ControlSession()
    surface = InterruptingSurface()
    log = RunLog(ROOT / "evidence" / "runs" / "_test_handoff_resume", kind="replay:test")
    engine = ReplayEngine(surface, control=control, run_log=log, settle_ms=200, poll_ms=20,
                          escalation_timeout_s=10)

    t = threading.Thread(target=_operator, args=(control, surface, "welcome"), daemon=True)
    t.start()
    result = engine.run(ART, {"member_id": "12345"})
    t.join(3)

    assert result.status == "success"
    assert "4,213" in (result.outputs.get("savings_balance") or "")
    assert control.state == ControlState.AUTO_RUNNING
    assert control.request is None
    assert any('"resume_reclassify"' in line for line in log.tail(50))
    # automation resumed and completed: nav click + field focus + submit click
    assert len(surface.clicks) >= 3


def test_escalation_without_operator_returns_context_and_stops():
    control = ControlSession()
    surface = InterruptingSurface()
    log = RunLog(ROOT / "evidence" / "runs" / "_test_handoff_context", kind="replay:test")
    engine = ReplayEngine(surface, control=control, run_log=log, wait_for_human=False,
                          settle_ms=200, poll_ms=20)
    result = engine.run(ART, {"member_id": "12345"})

    assert result.status == "escalated"
    assert result.failed_step == "open_search"
    assert result.intervention is not None
    assert result.intervention["capability_id"] == "member_lookup"
    assert result.intervention["version"] == "1.0.0"
    assert result.intervention["screenshot_path"]
    assert control.state == ControlState.ESCALATED
    assert len(surface.clicks) == 0  # automation emitted zero input


def test_resume_unrecognized_re_escalates():
    control = ControlSession()
    surface = InterruptingSurface()
    engine = ReplayEngine(surface, control=control, settle_ms=200, poll_ms=20,
                          escalation_timeout_s=10)

    # human hands back while the screen is still unknown
    t = threading.Thread(target=_operator, args=(control, surface, "unknown"), daemon=True)
    t.start()
    result = engine.run(ART, {"member_id": "12345"})
    t.join(3)

    assert result.status == "escalated"
    assert control.state in (ControlState.ESCALATED, ControlState.AUTO_RUNNING)
