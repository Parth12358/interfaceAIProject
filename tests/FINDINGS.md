# Adversarial audit — findings

Scope: falsify the system against the assignment requirements (sections 3.1–3.7, 6, 7).
Method: two independent read-only reviews of the codebase, then adversarial tests written
against the confirmed breaks. Tests were added to encode both the **fixed** behavior and the
**remaining** limitations. No test here is a tautology over the docs — each asserts behavior.

Run: `pytest` (59 tests), `lint-imports`.

## Resolved — now enforced and regression-tested

| # | Flaw | Fix | Test |
|---|---|---|---|
| 1 | `ReplayEngine.run()` raised to the caller (missing input → `KeyError`; oversized template → `cv2.error`) | `run()` wraps `_run()`; every internal error → structured `failed` | `test_engine_hardening.py::test_missing_input_is_structured_failure_not_crash` |
| 2 | `template_ref` path traversal read arbitrary files | `resolve()` + containment check under the artifact dir; oversized templates fail closed | `test_template_ref_path_traversal_fails_closed` |
| 3 | Recovery actions bypassed the policy gate entirely | recovery `click`/`key` route through the same chokepoint | `test_recovery_action_is_policed` |
| 4 | Risk gate ignored typed values / key actions / label-less targets | `is_risky` inspects target label **and** the substituted typed value | `test_typed_value_risk_is_escalated` |
| 5 | `max_steps` and the allowed `app.id` were never enforced | engine enforces both; `--policy` loads a real per-app policy | `test_max_steps_enforced`, `test_app_id_not_allowed_is_denied` |
| 6 | Unexpected business outcome became `verify_timeout` | `_verify` surfaces any matched `business_outcome` | `test_unexpected_business_outcome_surfaced_not_timeout` |
| 7 | Empty `expect.any_of` could never verify | empty set means "any known state" | `test_empty_expect_verifies_against_any_known_state` |
| 8 | Handoff was a standalone mock, not wired to the engine | engine asserts the control token before every dispatch, builds a real `InterventionRequest`, pauses, resumes via screen re-classification | `test_handoff_integration.py` (3 tests) |
| 9 | Redaction was top-level only; `result.json` written raw | recursive `redact_data` in `event` and `result` | `test_run_log_redacts_nested_values`, `test_result_json_is_redacted` |
| 10 | Compiler persisted unmatched discovery literals | unmatched typed values become synthesized parameters; literal never written | `test_type_literal_without_input_is_parameterized_and_not_persisted` |
| 11 | Compiler dropped `key`/`wait` steps and `done` outputs | both now compiled | `test_compiler_emits_key_step`, `test_compiler_preserves_done_outputs` |
| 12 | Discovery loop silently burned steps on bad marks / provider faults | invalid-mark + repeat detection → `stalled`; provider exception → `escalated` | `test_discovery_hardening.py` |
| 13 | Same-second evidence dirs collided; committed `evidence_dir` was an absolute gitignored path | uuid-suffixed run dirs; `evidence_dir` stored repo-relative | `python -m src.cli demo --evidence evidence/replay_demo` regenerated |
| 14 | Committed `replay_demo` was stale/hand-copied | regenerated via the CLI with relative paths | `evidence/replay_demo/` |

## Open — deliberately not fixed (documented)

1. **No committed LLM discovery run yet.** Requires `DEEPSEEK_API_KEY` + a live browser; the run is the
   user's. The code path is verified offline (`test_discovery.py`) and the capture command writes a
   committable bundle:
   `python -m src.cli discover --goal "…" --input member_id=12345 --evidence evidence/discovery_demo`.
   Until this is run, the brief's "the discovery run has to be real, with evidence in /evidence/" is not
   satisfied.
2. **Public repo not pushed.** `origin` (`Parth12358/interfaceAIProject`) is empty; the local history is
   unpushed. Pushing is an explicit user action.
3. **Screenshot region-masking does not exist.** Redaction is text/JSON-level only. REPORT says so.
4. **Multi-tenant reuse is design-only.** The schema has no `overrides[]`/tenant field; `REPORT §4`
   describes the plan, not an implementation. Section 3.7 only asks for a design, but the report's
   "the schema leaves room" is generous.
5. **Template-match rung is implemented + traversal-guarded but untested live** (no crops are generated).
   `read` actions use only `text_anchor`; `fallback_point`/`template_ref` are unusable for reads.
6. **`OsSurface` is unreachable from the CLI** (`--surface` is `cdp|scripted`); it compiles but no demo
   exercises it, so `REPORT §1`'s "three real Surface implementations" overstates the running set.
7. **Recovery `then` semantics** (`retry_step` vs `continue`) remain unread by the engine.
8. **Screen-scope is anchored on `app_ready`**, which is present on every in-app screen; it catches
   "wrong app / blank foreground" but not "wrong *screen within* the app". There is no URL/DOM to gate on
   in a driver-less design; this is the honest limit.

## Test suite map (67 tests, all green)

- `test_engine_hardening.py` — contract/escalation/risk/traversal/redaction (12)
- `test_handoff_integration.py` — engine↔control-token pause/resume (3)
- `test_discovery_hardening.py` — loop dead-ends, provider faults, compiler safety (8)
- `test_operator_api.py` — operator console HTTP contract, 409 not 500 (3)
- `test_fuzz.py` — Hypothesis invariants: redaction/policy/anchoring never raise, `run()` is total (5)
- `test_policy.py`, `test_schema.py`, `test_perception.py`, `test_replay.py`, `test_discovery.py`,
  `test_handoff.py`, `test_boundaries.py` — existing coverage, kept green.

## Verification numbers

- `pytest` → 67 passed. `lint-imports` → contract kept.
- Coverage on the load-bearing modules (targeted run): `replay/engine.py` 86%,
  `agent/compiler.py` 89%, `agent/loop.py` 91%, `handoff/control.py` 92%,
  `handoff/operator_api.py` 100%, `policy/*` 93–100% (total 86%).
  `agent/llm_deepseek.py` (live provider, 0%) is the only unexercised module — it needs the
  real API call and is covered by the user's live discovery run.
- Mutation testing (`mutmut`) is not run here (it multiplies the suite runtime); the recommended
  command is documented in this file's header comment and in `requirements.txt`. Run it after the
  live discovery bundle exists.

```bash
pip install mutmut coverage hypothesis httpx
coverage run -m pytest && coverage report -m
# mutmut run --paths-to-mutate src/replay,src/policy,src/agent/compiler.py
```
