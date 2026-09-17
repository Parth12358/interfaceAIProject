# REPORT — Computer-Use Automation System

**Thesis.** The LLM is allowed to be uncertain exactly once — during *discovery*. That uncertainty is
compiled into a typed capability artifact; production is deterministic replay with no model in the
decision loop.

## 1. Architecture

```
goal ──► DISCOVERY (LLM, once) ──► ARTIFACT (typed, versioned) ──► REPLAY (deterministic) ──► result
              │ set-of-marks + DeepSeek                               │ OCR + anchors
              └ recorder → compiler                                    └ escalate → HUMAN HANDOFF
```

The load-bearing seam is the **Surface protocol** (`screenshot`, `click(x,y)`, `type`, `key`): *how we
perceive/act on a surface*. Above it, `perception/` answers *how we deterministically find things in
pixels*; the artifact is expressed only in anchors + surface actions, so it is surface-neutral. Three real
implementations sit behind one protocol — **`CdpSurface`** (primary: CDP as a transport for pixels and
coordinate input only; no DOM queries, no a11y tree; `deviceScaleFactor=1` so screenshot px == click px),
**`OsSurface`** (mss + pyautogui; the native-desktop path, with documented X11/DPI costs), and
**`ScriptedSurface`** (saved frames for deterministic offline tests). Pointing the system at a desktop app
is a `launch()` + Surface change, not a schema/replay change — demonstrated by the same artifact replaying
over `CdpSurface` and `ScriptedSurface`.

**Boundaries (CI-enforced).** `replay/` may not import `agent/` or any LLM SDK (import-linter contract);
`sys.platform` appears only in `src/platformx/` (test). Single process, synchronous per-step loop — the
abstractions, not infrastructure, carry scale.

## 2. Artifact schema

`src/artifact/schema.py` (Pydantic v2; JSON in `artifacts/`, exported JSON Schema alongside) is the
calling-agent contract:

- **`capability`** — `id`, semver `version`, `status` (`draft|approved`), typed **`inputs`** (type + regex
  `pattern`) and **`outputs`** (`extract: step:<id>`): what the agent supplies and gets back.
- **`steps[]`** — an `action` (`click|type|read|key|wait`) + a **`target` anchor bundle** with an ordered
  degradation path: `text_anchor` (+ optional `context_anchor` disambiguator) → `template_ref` saved crop
  → `fallback_point`. Lower rungs are reported, never silent. Each step declares **`expect.any_of`**, the
  screen-states it may legitimately land on.
- **`screen_states{}`** — the error taxonomy as data: `precondition` (is this the right app?), `progress`,
  `business_outcome` (+`outcome_code`), `recoverable` (+`recovery`), or `failure` (+`error_code`).
- **`provenance`** — model, platform, surface, discovery-run pointer (informational only).

Inputs are **placeholders** (`{member_id}`) — discovery-time literals are never persisted. `expect.any_of`
makes every step a branch over known states, so the taxonomy lives in the artifact. `status` gates
unattended replay.

## 3. Determinism & error handling

Replay is a pure function of pixels + artifact: no model calls, deterministic OCR/matching, bounded
condition-based waits, pinned geometry. Per step: **settle** (two identical frames) → **classify** →
**resolve** (anchor bundle, rung logged) → **policy** → **act** → **verify** (`expect.any_of`) →
**extract**. The interesting failures are runtime states, not layout drift; the result contract separates:

| Situation | Class | Result |
|---|---|---|
| No member / invalid number | `business_outcome` | outcome + `MEMBER_NOT_FOUND` / `INVALID_INPUT` |
| Permission denied / arrears | `business_outcome` | outcome + `ACCESS_DENIED` / `ACCOUNT_IN_ARREARS` |
| Session-expired interstitial | `recoverable` | recovered, run continues |
| Slow load | `recoverable` | bounded wait/retry, continues |
| Outright app error (outage, compliance) | `failure` | `failed` + `APP_ERROR_500` / `COMPLIANCE_HOLD` |
| Unknown screen / target missing / verify timeout | — | `failed`, expected-vs-observed |
| Risky/irreversible action | — | `escalated` |

A **business outcome is not a failure**; a declared **`failure`** is an app error the caller can debug —
kept distinct from both outcomes and escalations. `verify` also recovers interstitials appearing *between*
action and expected outcome. Anything unrecognized halts rather than proceeding blindly. OCR robustness
(the no-DOM tax) uses a two-pass merge (PSM 3 ∪ PSM 11), 2× upscale, geometric line grouping, geometric
dedupe of cross-pass garbage, and fuzzy matching. A single capture spanning a navigation is classified
before the verify deadline so it cannot masquerade as a timeout.

## 4. Heterogeneity & multi-tenant

**Surfaces.** Because the artifact is anchors + actions, extending to a modern web app or a desktop app is
a new Surface, not a schema change. A cleaner-DOM surface could add a `dom_anchor` rung *above*
`text_anchor`; the degradation path already models "prefer the strong locator, fall back to pixels."

**Multi-tenant reuse.** Tenants run the same vendor product branded/versioned differently. The artifact
carries `app.id`; the plan is a **base artifact per vendor product + per-tenant `overrides[]`** rather than
re-recording. Concrete routes/values canonicalize to parameters (`/item/12345 → /item/:id`); `provenance` +
a multi-run stability signal detect drift so a diverged tenant degrades (lower rung, `degraded`, escalate)
instead of misfiring. Demonstrated live: `test_sites/` serves **8 branded sites** — two instances of one
legacy vendor product (frameset + single page), a modern app, and five more banks (dense legacy, a 3270
terminal, a modern fintech, an enterprise ledger). **One** VaultCore artifact replays on both tenants, and
`scripts/live_site_matrix.py` runs **75 cases covering every runtime state** (plus a genuinely
LLM-discovered draft). Multi-tenant `overrides[]` itself remains design-only.

## 5. Escalation & handoff

Replay escalates on unknown screen, exhausted recovery, a risky action, or a policy denial, returning an
`escalated` result with capability id/version, step, reason, observed states, screenshot, and log tail. It
is wired to a real control session: before every dispatch it asserts it holds the automation token; on
escalation it builds an `InterventionRequest`, hands it over, and **pauses**. `cli replay --operator` runs
the console in the same process so the human drives the *same* session; the engine then re-derives state
and resumes (or re-escalates). `src/handoff/` is a real control-token state machine:

```
AUTO_RUNNING → ESCALATED → HUMAN_CONTROL → RESUMING → (recognized? AUTO_RUNNING : ESCALATED)
```

Exactly one controller holds the token (`can_act(actor)`, asserted before every action); automation emits
zero input while the human holds it. A `pynput` listener records the human's clicks/keys with nearby OCR
text into the same run log (X11 on Linux, documented). **Resume never assumes** what the human did. The
same handoff is reachable from discovery (`cli discover --operator`): a stuck/escalating discovery pauses
for a human and re-observes on hand-back. Unit-tested (`tests/test_handoff.py`) and integration-tested
(`tests/test_handoff_integration.py`).

## 6. Safety

One dispatch chokepoint (`src/policy/`), applied to both discovery and replay, including recoveries:
- **Allowlist** — permitted action kinds + `max_steps`, and the artifact's `app.id` must match the policy's
  app; unknown kinds default-deny. Configurable per app (`--policy`, sample at `policy.example.json`).
- **Screen-scope** — since there is no navigation API, the current screen must match a known state of the
  allowed app before acting; a wrong/unrecognized foreground refuses and escalates.
- **Risk classes** — `read` is safe; a mutating action whose target **or typed value** matches irreversible
  patterns ("Confirm Transfer", "Delete", "Wire", "Close Account", …) is **blocked in unattended replay and
  escalated**.
- **Containment** — a `template_ref` must resolve inside the artifact directory or it fails closed.
- **Redaction** — logs and `result.json` pass a recursive hook masking account-number shapes **and
  credential shapes** (provider keys, bearer tokens, JWT-ish, `password=/token=`); artifacts store parameter
  *names* only and the compiler never persists a discovery literal. Fake seeded data only.

## 7. Cuts

- **Live discovery is real and committed.** Genuine DeepSeek runs are committed under `evidence/` —
  `evidence/discovery_demo/` (CoreServ) plus `evidence/live_sites/discovery_*/` for the test sites — with
  `log.jsonl`, screenshots, `artifact.json`, and `compile_notes.txt`. Discovery is bounded by `max_steps`
  **and** a wall-clock `--timeout`; each logged action records its target control and, when the model
  supplies one, its stated rationale.
- **Grafted taxonomy.** The `screen_states` set is partly hand-authored: discovery reaches the happy path,
  and the error/recoverable/failure states (`no_member_found`, `validation_error`, `session_timeout`,
  permission/arrears/outage/compliance) are grafted from the app family's known vocabulary — recorded
  openly in each bundle's `compile_notes.txt`, not inferred by the model.
- **Provider deviation:** DeepSeek (vision + function calling via an OpenAI-compatible API), one adapter
  module, model/base_url in config.
- **Thin/mocked (seam real):** operator console UX (the control-token mechanism itself is real and
  engine-integrated); multi-tenant `overrides[]` (design-only); desktop/Wayland paths (OsSurface compiles,
  documented costs). **Screenshot region-masking is not implemented** — redaction is text/JSON only.
- **Next:** confidence scoring → `draft→approved` gating on replay stability; a bounded, policy-checked
  single-step LLM recovery on replay failure (recorded as evidence); the base+overrides representation; an
  assisted `dom_anchor` rung.
