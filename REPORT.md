# REPORT — Computer-Use Automation System

**Thesis.** The LLM is allowed to be uncertain exactly once — during *discovery*. That uncertainty is
compiled into a typed capability artifact; production is deterministic replay with no model in the
decision loop. Everything below serves making that split real and mechanically checkable.

## 1. Architecture

```
goal ──► DISCOVERY (LLM, once) ──► ARTIFACT (typed, versioned) ──► REPLAY (deterministic) ──► result
              │  set-of-marks + DeepSeek                                │  OCR + anchors
              └── recorder → compiler                                   └── escalate → HUMAN HANDOFF
```

The load-bearing seam is the **Surface protocol** (`screenshot`, `click(x,y)`, `type`, `key`): *how we
perceive/act on a surface*. Above it, `perception/` answers *how we deterministically find things in
pixels*, and the **artifact is expressed only in anchors + surface actions** — so it is surface-neutral.
There are three real Surface implementations behind that one protocol:

- **`CdpSurface` (primary):** Chrome DevTools Protocol over a websocket — `Page.captureScreenshot` for
  pixels, `Input.dispatchMouseEvent/Key` for coordinate input, `deviceScaleFactor` pinned to 1 so
  screenshot px == CSS px == click coords. **No DOM management**: we never query/select nodes or read the
  a11y tree. This is a deliberate pivot from an OS-level-primary design — CDP is a *transport for pixels +
  coordinate input, not a selector engine* — chosen because it is cross-platform and dodges the
  Linux/Wayland synthetic-input problem while staying literally DOM-blind.
- **`OsSurface` (secondary):** `mss` + `pyautogui`. The "generalizes to a native desktop app, where there
  is no DOM at all" path. Kept real to prove the seam; it carries the documented X11/DPI costs.
- **`ScriptedSurface`:** returns saved PNG screens; used for deterministic offline tests/evidence.

Pointing the system at a native desktop app is a `launch()` + Surface change — **not** a schema or replay
change. That sentence is the generalization story, and it is demonstrated, not just asserted (the same
artifact replays over `CdpSurface` and `ScriptedSurface`).

**Boundaries (CI-enforced).** `replay/` may not import `agent/` or any LLM SDK (import-linter contract);
`sys.platform` appears only in `src/platformx/` (test). Single process; no queues/services — replay is a
synchronous per-step loop. Simplicity is the point; the abstractions, not infrastructure, carry scale.

## 2. Artifact schema

The artifact (`src/artifact/schema.py`, JSON in `artifacts/`, JSON Schema exported to
`artifacts/artifact.schema.json`) is the contract between the calling agent and the replay engine. Shape:

- **`capability`** — `id`, semver `version`, `status` (`draft|approved`), typed **`inputs`** (name → type
  + regex `pattern`) and **`outputs`** (name → `extract: step:<id>`). This is the agent-facing contract:
  what it needs, what it gets back.
- **`steps[]`** — each an `action` (`click|type|read|key|wait`) + a **`target` anchor bundle** with an
  **ordered degradation path**: `text_anchor` (+ optional `context_anchor` to disambiguate) →
  `template_ref` (saved crop) → `fallback_point`. Using a lower rung is *reported* (run flagged
  `degraded`), never silent. Each step carries **`expect.any_of`** — the set of screen-states it may
  legitimately land on.
- **`screen_states{}`** — the error taxonomy as data, not code. Each state has text matchers and a
  `class`: `precondition` (am I even on the right app?), `progress`, `business_outcome`
  (+`outcome_code`), or `recoverable` (+`recovery`).
- **`provenance`** — model, platform, surface, discovery-run pointer (informational; an artifact
  discovered on one platform/surface replays on another).

Design choices that matter: input values are **placeholders** (`{member_id}`) — discovery-time literals
are never persisted; `expect.any_of` makes **every step a branch over known states**, so the error
taxonomy lives in the artifact; `status` gates unattended replay (`draft` is refused without
`--allow-draft`).

## 3. Determinism & error handling

Replay (`src/replay/engine.py`) is a pure function of pixels + artifact. No model calls; OCR and matching
are deterministic; all waits are bounded and condition-based (never bare sleeps); window geometry and
`deviceScaleFactor` are pinned. Per step: **settle** (two identical frames) → **classify** →
**resolve** (anchor bundle, each rung logged with confidence) → **policy** → **act** → **verify**
(`expect.any_of` within timeout) → **extract** (for reads).

The interesting part is not layout drift; it is runtime states. The result contract separates them:

| Situation | Class | Replay behavior | Result |
|---|---|---|---|
| "No member found" | `business_outcome` | stop, report | `business_outcome` + `MEMBER_NOT_FOUND` |
| "Invalid member number" | `business_outcome` | stop, report | `business_outcome` + `INVALID_INPUT` |
| Session-expired interstitial | `recoverable` | run bounded recovery, re-classify, continue | `success` (recovered) |
| Slow load | `recoverable` | bounded wait/retry | continues |
| Unknown screen / target not found / verify timeout | — | stop loudly with expected-vs-observed | `failed` (debuggable) |
| Can't safely proceed | — | escalate | `escalated` |

A **business outcome is not a failure** — conflating them is the classic mistake here, so it is a
first-class status. `verify` also recovers interstitials that appear *between* action and expected
outcome. Every branch is enumerated in the artifact; anything unrecognized halts rather than proceeding
blindly. OCR robustness (the real-world tax of a no-DOM surface) is handled with a two-pass merge
(PSM 3 ∪ PSM 11) + 2× upscale + geometric line grouping + fuzzy matching — enough to read colored
values, small legacy fonts, and multi-column layouts deterministically. Evidence in
`evidence/replay_demo/` shows a timeout run: `recovery_start → recovery_ok → verify_ok(member_detail) →
extract`.

## 4. Heterogeneity & multi-tenant (design)

**Surfaces.** Because the artifact is anchors + actions, extending from this legacy web app to a modern
web app or a desktop app is a new Surface, not a schema change — shown by three working Surface impls
today. A cleaner-DOM surface could add a `dom_anchor` rung *above* `text_anchor` in the same bundle; the
degradation path already models "prefer the strong locator, fall back to pixels."

**Multi-tenant reuse.** Hundreds of tenants run ~20 apps, many the same vendor product branded/versioned
differently. The artifact carries `app.id`; the plan is a **base artifact per vendor product + per-tenant
`overrides[]`** (anchor text, viewport, an extra recovery state) rather than re-recording per tenant.
Concrete routes/values canonicalize to parameters (`/item/12345 → /item/:id`); `provenance` + a
multi-run stability signal detect version drift so a tenant that has diverged degrades gracefully
(falls to a lower anchor rung, flags `degraded`, or escalates) instead of silently misfiring. Not built
(explicitly out of scope) but the schema leaves room and nothing here paints us into a corner.

## 5. Escalation & handoff

Replay escalates on: unknown screen, recovery exhausted, a risky action, or a policy denial — returning
`escalated` with capability id/version, step, reason, observed states, screenshot, and last log lines.
The handoff mechanism (`src/handoff/`) is a real **control-token state machine**:

```
AUTO_RUNNING → ESCALATED → HUMAN_CONTROL → RESUMING → (recognized? AUTO_RUNNING : ESCALATED)
```

**Exactly one controller holds the token** (`can_act(actor)`, asserted before every Surface action);
automation emits zero input while the human holds it. The handoff is trivially real in a driver-less
design — the human uses the actual mouse/keyboard on the same live window — and a `pynput` listener
records their clicks/keys (+ nearby OCR text, before/after screenshots) into the same run log as
`human_action` entries. **Resume never assumes what the human did**: the engine re-derives state from the
screen; recognized → continue, still unknown → re-escalate. The operator console is a deliberately minimal
FastAPI page (mocked UI, real mechanism). The state machine is unit-tested (`tests/test_handoff.py`).

## 6. Safety

One dispatch chokepoint (`src/policy/`), enforced for both discovery and replay:
- **Allowlist** — permitted action kinds + max steps; unknown kinds default-deny.
- **Screen-scope** — since there is no navigation API to gate, before every action the current screen
  must match a known state of the allowed app; if the foreground content stops matching (wrong window),
  acting is refused and the run escalates. This is how a driver-less system stays in its lane.
- **Risk classes** — `read` is safe; a `click` whose target matches irreversible patterns ("Confirm
  Transfer", "Delete", "Post Transaction", …) is **risky → blocked in unattended replay, escalated**.
- **Redaction / secrets** — logs pass a redaction hook (mask account-number-shaped strings); the artifact
  stores parameter *names* only, never discovery-time literals; `DEEPSEEK_API_KEY` via env; the target
  app uses fake seeded data only.

## 7. Cuts (and what's next)

- **Live discovery is the user's run.** The genuine DeepSeek run needs an API key + a live browser; the
  code path is identical to the mock-driven `tests/test_discovery.py` round-trip (discover → compile →
  replay), which is verified offline. Evidence committed here is the **replay** side; the discovery
  evidence is produced by `python -m src.cli discover …`.
- **Provider deviation:** DeepSeek V4.1 Flash instead of GPT-4o (vision + function calling via an
  OpenAI-compatible API); one adapter module, model/base_url in config.
- **Deliberately thin/mocked (seam real):** operator console UX; multi-tenant `overrides[]`
  (design-only); template-match rung and region-masking (present but lightly exercised); desktop &
  Windows/Wayland paths (`OsSurface` compiles, documented costs).
- **Next with more time:** confidence scoring → `draft→approved` gating on replay stability; a bounded,
  policy-checked single-step LLM recovery on replay failure (recorded as evidence); the multi-tenant
  base+overrides representation; assisted `dom_anchor` rung for clean-DOM surfaces.
