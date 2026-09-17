"""Perception tests over saved PNG fixtures. Requires the tesseract binary."""
import pytest

from _util import HAS_TESS, png

pytestmark = pytest.mark.skipif(not HAS_TESS, reason="tesseract binary not installed")

from src.artifact import store  # noqa: E402
from src.perception import ocr  # noqa: E402
from src.perception.match import find_text, read_value, resolve_target  # noqa: E402
from src.perception.states import classify  # noqa: E402
from _util import ROOT  # noqa: E402

ART = store.load(ROOT / "artifacts" / "member_lookup.json")


def test_ocr_reads_brand_and_headings():
    # full_text is an unordered bag from a two-pass merge; phrase presence is a
    # find_text (per-line span) question, not a substring one.
    words = ocr.words(png("member_detail"))
    assert "CoreServ" in ocr.full_text(words)
    assert find_text(words, "Member Profile", 0.85)
    assert find_text(words, "Savings Balance", 0.85)


def test_find_text_multiword_anchor():
    words = ocr.words(png("search_form"))
    spans = find_text(words, "Member Number", 0.85)
    assert spans and spans[0].score >= 0.85


def test_read_value_extracts_balance_and_name():
    words = ocr.words(png("member_detail"))
    bal = read_value(words, "Savings Balance", "right_of", 400)
    assert bal and "4,213" in bal
    name = read_value(words, "Member Name", "right_of", 400)
    assert name and "Ada" in name


def test_resolve_click_target_on_nav():
    words = ocr.words(png("welcome"))
    step = next(s for s in ART.steps if s.id == "open_search")
    res = resolve_target(words, png("welcome"), step.target)
    assert res is not None and res.rung == "text_anchor"
    assert 0 <= res.x <= 1280 and 0 <= res.y <= 800


@pytest.mark.parametrize(
    "fixture,expected_state",
    [
        ("search_form", "search_form"),
        ("member_detail", "member_detail"),
        ("no_member_found", "no_member_found"),
        ("validation_error", "validation_error"),
        ("session_timeout", "session_timeout"),
    ],
)
def test_state_classification(fixture, expected_state):
    words = ocr.words(png(fixture))
    cls = classify(words, ART.screen_states)
    assert expected_state in cls.names


def test_precondition_present_on_every_screen():
    for fixture in ("welcome", "search_form", "member_detail", "no_member_found"):
        words = ocr.words(png(fixture))
        cls = classify(words, ART.screen_states, expected=["app_ready"])
        assert "app_ready" in cls.names, fixture


def test_business_outcome_wins_over_precondition():
    words = ocr.words(png("no_member_found"))
    cls = classify(words, ART.screen_states)
    name, state = cls.primary()
    assert name == "no_member_found"
    assert state.state_class == "business_outcome"
