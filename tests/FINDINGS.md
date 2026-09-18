# Adversarial audit — findings

Scope: falsify the system against the assignment requirements (sections 3.1–3.7, 6, 7).
Method: two independent read-only reviews of the codebase, then adversarial tests written
against the confirmed breaks. Tests were added to encode both the **fixed** behavior and the
**remaining** limitations. No test here is a tautology over the docs — each asserts behavior.

Run: `pytest` (94 collected), `lint-imports`.

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
| 15 | **No committed LLM discovery run** — the brief's one non-negotiable was unmet | 9 genuine DeepSeek runs committed: `evidence/discovery_demo/` (CoreServ) + `evidence/live_sites/discovery_*/` (8 test sites). `meridian_discovered_draft/` replays a model-produced artifact with no model present | `test_discovery.py` (offline round-trip); evidence bundles |
| 16 | Discovery had no wall-clock bound and logged *what* but not *why* | `--timeout` budget; each `agent_action` records its target control and the model's stated rationale | `test_discovery_wall_clock_timeout`, `test_discovery_logs_rationale` |
| 17 | The model's free-text rationale could echo a discovery-time literal into committed evidence | `_scrub()` substitutes supplied inputs with `{param}` and applies the redaction hook before logging | `test_discovery_rationale_is_scrubbed_of_input_literals` |
| 18 | Compile kept title-case twins of read-backed outputs (`"Savings Balance"` **and** `savings_balance`), so drafts declared outputs replay could never produce | `_output_key` normalizes both mint sites; exact twins collapse | `test_model_reported_outputs_dedupe_against_read_steps` |
| 19 | A machine without Tesseract ran `pytest`, saw green, and silently lost ~half the suite | `addopts = -q -rs` plus a `conftest.py` report header and terminal-summary warning | `tests/conftest.py` |

## Open — deliberately not fixed (documented)

1. **Screenshot region-masking does not exist.** Redaction is text/JSON-level only. `REPORT §6/§7`
   say so explicitly.
2. **Declared business outputs are returned verbatim.** A capability whose job is "open a
   sub-account" must return the new account number, so masking it would break the contract.
   Per-field output classification (`OutputSpec.sensitive`) is the production answer and is not
   implemented — stated in `REPORT §6`.
3. **Drafts can over-declare outputs.** Exact twins now collapse (#18), but *synonyms* still
   survive — `savings_bal` read off a 3270 screen label vs the model's reported `savings_balance`,
   or the input echoed back (`member_id`). Pruning them is the `draft→approved` review's job.
   Every **approved** artifact's declared outputs are step-backed; the gap exists only in drafts.
4. **Multi-tenant reuse is design-only.** The schema has no `overrides[]`/tenant field; `REPORT §4`
   describes the plan, not an implementation. Section 3.7 asks only for a design.
5. **The template-match rung is lightly exercised.** Implemented and traversal-guarded, but only one
   committed artifact uses `template_ref` (plus `context_anchor` ×1, `fallback_point` ×3) against
   152 `text_anchor` uses. `read` actions resolve via `text_anchor` only.
6. **`OsSurface` is unreachable from the CLI.** `--surface` accepts `cdp|scripted`
   (`src/cli.py:222`); the OS-level surface implements the same protocol and compiles, but no demo
   exercises it — it is there to prove the seam generalizes to a driver-less desktop target, not as
   a running path.
7. **Recovery `then` semantics** (`retry_step` vs `continue`) are declared in the schema but remain
   unread by the engine; recovery always re-runs the step.
8. **Screen-scope is anchored on `app_ready`**, which is present on every in-app screen; it catches
   "wrong app / blank foreground" but not "wrong *screen within* the app". There is no URL/DOM to
   gate on in a driver-less design; this is the honest limit.

## Test suite map (94 collected — 93 pass, 1 skip)

The skip is `test_live_sites.py`, the opt-in live-Chrome matrix (`RUN_LIVE=1`); `-rs` prints the
reason rather than hiding it behind a dot.

| File | Tests | Covers |
|---|---|---|
| `test_engine_hardening.py` | 16 | contract totality, escalation, risk, traversal, redaction, slow-frame regression |
| `test_test_sites.py` | 16 | every runtime condition across all 8 tenants via the Flask test client |
| `test_discovery_hardening.py` | 13 | loop dead-ends, provider faults, budget, rationale scrubbing, compiler safety |
| `test_perception.py` | 12 | OCR over saved PNGs, anchors, `read_value`, resolve rungs, state classification |
| `test_policy.py` | 7 | allowlist, `off_app`, risky attended/unattended, redaction |
| `test_schema.py` | 6 | artifact validation, outcome codes, round-trip, JSON-Schema export |
| `test_replay.py` | 5 | end-to-end determinism, business outcomes, timeout recovery, precondition |
| `test_fuzz.py` | 5 | Hypothesis invariants: redaction/policy/anchoring never raise, `run()` is total |
| `test_handoff.py` | 4 | control-token state machine, illegal transitions |
| `test_handoff_integration.py` | 3 | engine↔control-token pause/resume, zero automation input under human control |
| `test_operator_api.py` | 3 | operator console HTTP contract, 409 not 500 |
| `test_boundaries.py` | 2 | `sys.platform` confined to `platformx/`; replay references no LLM SDK |
| `test_discovery.py` | 1 | discover → compile → replay round-trip (mock provider) |
| `test_live_sites.py` | 1 | opt-in live Chrome matrix over all 8 sites |

## Verification numbers

- `pytest` → **93 passed, 1 skipped**. `lint-imports` → contract kept
  (`src.replay` may not import `src.agent`, `openai`, or `anthropic`).
- Verified from a clean `git clone`: modules import, `python -m src.cli demo` runs with no API key
  and no browser, full suite green.
- Coverage (`coverage run -m pytest && coverage report -m --include="src/*"`) — **89% total**
  (1396 statements, 160 missed). Load-bearing modules:

  | Module | Cover | | Module | Cover |
  |---|---|---|---|---|
  | `artifact/schema.py` | 100% | | `replay/engine.py` | 86% |
  | `policy/redact.py` | 100% | | `perception/match.py` | 86% |
  | `policy/risk.py` | 100% | | `agent/compiler.py` | 92% |
  | `policy/allowlist.py` | 93% | | `agent/loop.py` | 78% |
  | `handoff/operator_api.py` | 100% | | `perception/ocr.py` | 97% |
  | `handoff/control.py` | 92% | | `perception/states.py` | 100% |

  `agent/llm_deepseek.py` is absent from the report: it is never imported offline (it needs a live
  key), which is the point — it is the only module the deterministic path cannot reach. It is
  exercised by the committed discovery runs under `evidence/`.

```bash
pip install coverage hypothesis httpx
coverage run -m pytest && coverage report -m --include="src/*"
```
