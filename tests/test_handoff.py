"""Handoff control-transfer state machine — pure logic, no browser."""
import pytest

from _util import ROOT  # noqa: F401 (sets sys.path)

from src.handoff.control import ControlError, ControlSession, ControlState, InterventionRequest


def _req():
    return InterventionRequest(capability_id="member_lookup", version="1.0.0",
                               step_id="submit", reason="unknown_screen")


def test_full_handoff_cycle():
    s = ControlSession()
    assert s.state == ControlState.AUTO_RUNNING and s.can_act("automation")
    s.escalate(_req())
    assert s.state == ControlState.ESCALATED
    assert not s.can_act("automation") and not s.can_act("human")  # nobody acts
    s.take_control()
    assert s.state == ControlState.HUMAN_CONTROL and s.can_act("human")
    assert not s.can_act("automation")  # automation emits zero input
    s.hand_back()
    assert s.state == ControlState.RESUMING
    s.resume(recognized=True)
    assert s.state == ControlState.AUTO_RUNNING and s.can_act("automation")
    assert s.request is None


def test_resume_unrecognized_bounces_back_to_escalated():
    s = ControlSession()
    s.escalate(_req()); s.take_control(); s.hand_back()
    s.resume(recognized=False)
    assert s.state == ControlState.ESCALATED


def test_single_controller_token_is_enforced():
    s = ControlSession()
    s.assert_can_act("automation")  # ok
    s.escalate(_req())
    with pytest.raises(ControlError):
        s.assert_can_act("automation")  # token released on escalate
    s.take_control()
    with pytest.raises(ControlError):
        s.assert_can_act("automation")  # human holds it now


def test_illegal_transitions_rejected():
    s = ControlSession()
    with pytest.raises(ControlError):
        s.take_control()  # not escalated
    with pytest.raises(ControlError):
        s.hand_back()  # not in human control
