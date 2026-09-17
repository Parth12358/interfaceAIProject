"""Policy gate tests — pure logic, no OCR/browser."""
import pytest

from _util import ROOT  # noqa: F401 (sets sys.path)

from src.policy.allowlist import Policy
from src.policy.redact import redact_text
from src.replay.engine import PolicyDenied


def test_allowed_action_on_known_state_passes():
    Policy().check("click", "Member Lookup", ["search_form"])  # no raise


def test_unknown_action_denied():
    p = Policy(allowed_actions={"click", "read"})
    with pytest.raises(PolicyDenied):
        p.check("type", "Member Number", ["search_form"])


def test_off_app_screen_denied():
    with pytest.raises(PolicyDenied) as e:
        Policy().check("click", "Anything", [])
    assert "off_app" in str(e.value)


def test_risky_action_blocked_unattended():
    with pytest.raises(PolicyDenied) as e:
        Policy().check("click", "Confirm Transfer", ["member_detail"])
    assert "risky_action" in str(e.value)


def test_risky_action_allowed_when_attended():
    Policy(unattended=False).check("click", "Confirm Transfer", ["member_detail"])  # no raise


def test_read_is_never_risky():
    Policy().check("read", "Delete", ["member_detail"])  # reads are safe


def test_redaction_masks_account_numbers():
    assert "«redacted»" in redact_text("account 1234567890 balance")
    # short member ids and balances are preserved
    assert redact_text("member 12345 has $4,213.55") == "member 12345 has $4,213.55"
