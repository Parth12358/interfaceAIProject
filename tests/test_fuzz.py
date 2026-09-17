"""Property-based tests (Hypothesis) for the pure functions and the run() contract.

These assert invariants the rest of the suite relies on: nothing in the policy/redaction
/anchoring path raises on adversarial input, and `run()` always returns a structured
ReplayResult for arbitrary caller inputs.
"""
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from _util import HAS_TESS, ROOT  # noqa: E402

from src.artifact import store  # noqa: E402
from src.artifact.schema import Target, TextAnchor  # noqa: E402
from src.perception.match import resolve_target  # noqa: E402
from src.perception.ocr import Word  # noqa: E402
from src.policy.allowlist import Policy  # noqa: E402
from src.policy.redact import redact_data, redact_text  # noqa: E402
from src.replay.engine import PolicyDenied  # noqa: E402

TEXT = st.text(max_size=24)
STATUSES = {"success", "business_outcome", "escalated", "failed"}


@given(TEXT)
@settings(max_examples=200, deadline=None)
def test_redact_text_is_safe_and_idempotent(s):
    once = redact_text(s)
    assert redact_text(once) == once  # idempotent


@given(st.recursive(TEXT, lambda c: st.one_of(st.lists(c, max_size=4), st.dictionaries(TEXT, c, max_size=4))))
@settings(max_examples=100, deadline=None)
def test_redact_data_never_raises(obj):
    redact_data(obj)


@given(
    st.sampled_from(["click", "type", "read", "key", "wait", "delete", ""]),
    st.one_of(st.none(), TEXT),
    st.lists(TEXT, max_size=3),
    st.one_of(st.none(), TEXT),
)
@settings(max_examples=200, deadline=None)
def test_policy_never_raises_unexpected(kind, label, states, value):
    try:
        Policy().check(kind, label, states, value)
    except PolicyDenied:
        pass  # the ONLY exception the policy contract may raise


@given(st.lists(TEXT, max_size=5), TEXT, st.one_of(st.none(), TEXT))
@settings(max_examples=200, deadline=None)
def test_resolve_target_never_raises(texts, query, ref):
    words = [Word(text=t, left=i * 20, top=0, width=18, height=12, conf=90.0,
                  line_id=(0, 0, 0)) for i, t in enumerate(texts)]
    target = Target(text_anchor=TextAnchor(text=query), template_ref=ref)
    res = resolve_target(words, b"not-a-png", target, artifact_dir=ROOT)
    assert res is None or (isinstance(res.x, int) and isinstance(res.y, int))


@pytest.mark.skipif(not HAS_TESS, reason="tesseract binary not installed")
@given(st.dictionaries(st.text(max_size=12), st.text(max_size=12), max_size=4))
@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_engine_run_never_raises_for_arbitrary_inputs(inputs):
    from fake_surface import FakeSurface
    from src.replay.engine import ReplayResult, ReplayEngine

    art = store.load(ROOT / "artifacts" / "member_lookup.json")
    surface = FakeSurface("welcome", {"welcome": ("Member Lookup", "search_form"),
                                      "search_form": ("Find", "member_detail")})
    result = ReplayEngine(surface, settle_ms=80, poll_ms=10).run(art, inputs)
    assert isinstance(result, ReplayResult)
    assert result.status in STATUSES
