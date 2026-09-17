# Tech Doc — Computer-Use Automation System
### Vision-first discovery → typed capability artifact → deterministic, LLM-free replay

**Status:** Locked for build. Deviations require a note in REPORT.md §Cuts.
**Thesis:** The LLM is allowed to be uncertain exactly once — during discovery. That uncertainty is compiled into a typed artifact; production execution is deterministic replay with no model in the decision loop.

---

## 1. Stack (locked decisions + why)

| Layer | Choice | Why (the defense) |
|---|---|---|
| Language | **Python 3.11+** | Best-in-class CV/OCR ecosystem (OpenCV, Tesseract), fastest iteration for a solo time-boxed build; every library below is Linux+Windows. |
| LLM (discovery only) | **OpenAI GPT-4o (vision + function calling)** via the `openai` SDK | Native screenshot input; function calling gives a clean typed action interface (`click(mark)`, `type(mark,text)`, …); one provider keeps the loop simple. Model ID in config, never hardcoded — the agent loop is provider-thin (one adapter module), so swapping providers later is a one-file change. |
| Surface control | **Pure OS-level, cross-platform (Linux + Windows): `mss` (screenshots) + `pyautogui` (mouse/keyboard out) + `pynput` (input capture during handoff)** | No browser driver anywhere. The system sees pixels and emits input events — the same contract a human operator has. All three libraries support Linux (X11) and Windows natively, so one `OsSurface` implementation covers both platforms. This is the most literal answer to "works when the surface has no clean DOM": it works when the surface has no DOM at all. |
| Platform layer | **`src/platformx/` — the only OS-conditional code**: browser discovery + launch flags, Tesseract path resolution, Windows DPI-awareness call, coordinate-scale calibration | Everything above it is platform-agnostic. Windows: declare per-monitor DPI awareness at startup (`ctypes` → `SetProcessDpiAwareness`) so pyautogui click coords and mss capture pixels agree, then verify with a one-shot calibration (capture size vs reported screen size → scale factor stored per run). Linux: **X11 required** (Wayland blocks synthetic input by design; documented, not worked around). |
| Window discipline | Target launched via subprocess in **app mode at fixed geometry** — Linux: `chromium`/`google-chrome --app=<url> --window-size=1280,800 --window-position=0,0`; Windows: same flags on `msedge.exe`/`chrome.exe` (discovered via registry/known paths by `platformx`) | Coordinates and anchors are only meaningful relative to a stable frame. Fixed launch geometry + fixed capture region is our determinism anchor, recorded in the artifact (`app.viewport`). Replay asserts the window is present/foreground before step 1 (a `state:app_ready` matcher), else hard-fails with a clear message. |
| Replay perception | **Tesseract OCR (pytesseract, word-level boxes) + OpenCV template matching + rapidfuzz** | The deterministic eye. OCR word boxes → text-anchor resolution; template match on saved element crops → visual fallback; fuzzy matching absorbs OCR noise. Same layered stack mature RPA (UiPath AI CV) converged on for selector-less environments. Tesseract installed via apt (Linux) or the UB-Mannheim installer / choco (Windows); binary path resolved in `platformx`. |
| Schemas | **Pydantic v2 → JSON artifacts** (+ exported JSON Schema) | Typed in code, serialized as reviewable JSON. A compliance reviewer can read the artifact; an agent can validate against the JSON Schema. |
| Target app | **Self-built local "legacy" core-banking app** (Flask, server-rendered, framesets, table layout, no test IDs, no unique element IDs) | Leans into the brief's "intentionally hostile surface" option. Full control lets us script the error taxonomy demo: seeded members, a "no such member" path, validation errors, a random session-timeout interstitial (flag-controlled for reproducible evidence). No ToS/PII risk. Runs identically on both OSes (pure Flask). |
| Operator console (handoff) | **Minimal FastAPI + single HTML page** (view intervention request, "Take control" / "Hand back" buttons); the human then drives the real screen directly | The brief says mock the UI but make the control-transfer model real. The state machine is real; the console is deliberately bare. |
| Evidence | **JSONL step logs + per-step PNG screenshots + final result JSON** per run directory | Satisfies §3.5 and doubles as the typed run-records substrate (confidence scoring later). |
| Tests | **pytest**; perception + replay classification tested against saved screenshots (no live screen needed) | Perception is pure functions over images → cheap, deterministic tests where it counts, and they run identically on both OSes and in CI. Live end-to-end runs are demos, not unit tests. |

**Explicitly rejected:** Playwright/Selenium/any browser driver (unneeded — OS-level control is the general case and the browser-specific layer added nothing the thesis requires), DOM selectors (fails the no-clean-DOM bias), accessibility tree as primary (legacy apps have broken trees; noted as a pluggable second perception source), API/network interception (out of scope per brief), separate OCR pipeline during discovery (the vision model sees screenshots natively; OCR is replay-time).

**Accepted costs of going driver-less (documented, not hidden):** runs need a real display and foreground focus (no headless CI for e2e; unit tests use saved PNGs); Linux requires X11 (Wayland refuses synthetic input); Windows requires the DPI-awareness + calibration step for display scaling ≠ 100%; focus theft by other windows is a hard-fail condition we detect via the `app_ready` matcher rather than pretend away. These are the honest costs of generality and go in REPORT.md.

---

## 2. Architecture

```
repo/
├── README.md, REPORT.md, evidence/
├── target_app/            # Flask legacy-style demo bank app (its own thing, no imports from src)
└── src/
    ├── platformx/         # ONLY OS-conditional code: browser discovery/launch, tesseract path,
    │                      #   win_dpi.py (DPI awareness + scale calibration)
    ├── surface/           # Surface protocol: screenshot() -> PNG, click(x,y), type(text), key(k), launch()
    │   └── os_surface.py  # mss + pyautogui against a fixed window region (platform-agnostic; uses platformx)
    ├── perception/        # DETERMINISTIC. ocr.py (word boxes), match.py (anchor->point resolution,
    │                      #   template match), states.py (screen-state matchers)
    ├── agent/             # DISCOVERY ONLY. loop.py (set-of-marks driver), llm_openai.py (thin adapter:
    │                      #   screenshots + function-calling), recorder.py, compiler.py (trajectory -> artifact)
    ├── artifact/          # schema.py (Pydantic models), store.py (load/save/validate)
    ├── replay/            # engine.py — NO import from agent/ or any LLM SDK. CI-enforced (import-linter).
    ├── policy/            # allowlist.py, risk.py (safe vs risky actions), redact.py
    ├── handoff/           # control.py (state machine), operator_api.py (FastAPI), capture.py (pynput)
    ├── evidence/          # run_log.py (JSONL writer, screenshot saver, redaction hook)
    └── cli.py             # discover | replay | operator | demo
```

**The load-bearing seam:** `surface/` answers *how we perceive/act on a surface* (pixels in, input events out). `perception/` answers *how we deterministically find things in pixels*. The artifact is expressed **only** in terms of anchors + surface actions. With OS-level control this seam is already surface-agnostic: pointing the same system at a native desktop app is a `launch()` change, not a new Surface implementation — and the same artifact replays on Linux or Windows because nothing in it is platform-specific. That sentence is the §3.7 answer.

**Hard rules (CI-enforced):** `replay/` cannot import `agent/` or any LLM SDK; only `platformx/` may contain `sys.platform` checks. The brief's core claims must be mechanically true.

---

## 3. Artifact schema (v1 draft — the focal point)

```jsonc
{
  "schema_version": "1.0",
  "capability": {
    "id": "member_lookup",
    "version": "1.0.0",
    "status": "draft",                        // draft | approved — replay refuses draft unless --allow-draft
    "description": "Look up a member by ID and read their savings balance.",
    "app": { "id": "coreserv-demo", "entry": "http://localhost:5000/",
             "launch": "browser-app-mode", "viewport": [1280, 800] },   // platform-neutral; platformx maps it
    "inputs": {
      "member_id": { "type": "string", "pattern": "^[0-9]{5}$", "description": "5-digit member number" }
    },
    "outputs": {
      "savings_balance": { "type": "string", "extract": "step:read_balance" },
      "member_name":     { "type": "string", "extract": "step:read_name" }
    }
  },
  "steps": [
    {
      "id": "open_search",
      "action": { "kind": "click" },
      "target": {                              // resolved by perception/, in priority order
        "text_anchor":  { "text": "Member Lookup", "role_hint": "link", "fuzzy_min": 0.85 },
        "context_anchor": { "text": "Navigation", "relation": "below", "max_px": 300 },  // disambiguator
        "template_ref": "crops/open_search.png", "template_min": 0.90,
        "fallback_point": { "x": 132, "y": 214 }   // last resort; using it flags the run "degraded"
      },
      "expect": {                              // checkpoint: screen-state assertions after acting
        "any_of": ["state:search_form"], "timeout_ms": 5000
      }
    },
    {
      "id": "enter_id",
      "action": { "kind": "type", "value": "{member_id}" },   // parameterized — literal never stored
      "target": { "text_anchor": { "text": "Member Number", "relation": "right_of", "max_px": 250 } },
      "expect": { "any_of": ["state:search_form"] }
    },
    {
      "id": "submit",
      "action": { "kind": "click" },
      "target": { "text_anchor": { "text": "Search" } },
      "expect": {
        "any_of": ["state:member_detail", "state:no_member_found", "state:validation_error"],
        "timeout_ms": 8000
      }
    },
    {
      "id": "read_balance",
      "action": { "kind": "read" },
      "target": { "text_anchor": { "text": "Savings Balance", "relation": "right_of", "max_px": 400 } },
      "expect": { "any_of": ["state:member_detail"] }
    }
  ],
  "screen_states": {                           // the error-taxonomy vocabulary, per capability + app-shared
    "app_ready":       { "all_of": [{ "text": "CoreServ" }], "class": "precondition" },
    "search_form":     { "all_of": [{ "text": "Member Search" }], "class": "progress" },
    "member_detail":   { "all_of": [{ "text": "Member Profile" }], "class": "progress" },
    "no_member_found": { "all_of": [{ "text": "No member found" }], "class": "business_outcome",
                         "outcome_code": "MEMBER_NOT_FOUND" },
    "validation_error":{ "all_of": [{ "text": "Invalid member number" }], "class": "business_outcome",
                         "outcome_code": "INVALID_INPUT" },
    "session_timeout": { "all_of": [{ "text": "Session expired" }], "class": "recoverable",
                         "recovery": { "kind": "click", "target": { "text_anchor": { "text": "Continue" } },
                                       "max_attempts": 1, "then": "retry_step" } },
    "slow_load":       { "all_of": [{ "text": "Loading" }], "class": "recoverable",
                         "recovery": { "kind": "wait", "ms": 1500, "max_attempts": 4 } }
  },
  "provenance": { "discovered_at": "...", "model": "gpt-4o-...", "platform": "linux-x11 | windows",
                  "discovery_run": "evidence/runs/disc-.../" }
}
```

Design points to defend in REPORT.md: (1) targets are **anchor bundles with an ordered degradation path**, and using a lower rung is *reported*, not silent; (2) `expect.any_of` makes every step a branch over known screen-states — the error taxonomy lives in the artifact, not in code; (3) params/outputs are the **agent-facing contract**; (4) `status` gates unattended replay; (5) input values are placeholders — discovery-time literals are never persisted; (6) the `precondition` class (`app_ready`) is how a driver-less system verifies it's even looking at the right window before acting; (7) artifacts are platform-neutral — an artifact discovered on Linux replays on Windows (`platform` in provenance is informational, not a constraint).

---

## 4. Replay engine (per-step algorithm)

```
pre-run: platformx init (DPI awareness on Windows, scale calibration);
         launch/attach target window at fixed geometry; assert state:app_ready else HARD FAIL

for step in steps:
    1. SETTLE     screenshot; wait until two consecutive frames stable (hash) or timeout
    2. CLASSIFY   run screen_states matchers on OCR text:
                    business_outcome -> STOP, return {status: business_outcome, code, evidence}
                    recoverable      -> run recovery (bounded attempts) -> re-CLASSIFY; exhausted -> ESCALATE
                    unknown screen   -> HARD FAIL (screenshot + expected vs observed) or ESCALATE per policy
    3. RESOLVE    target: text_anchor (+context disambiguation) -> template match -> fallback_point
                    each rung logged with confidence; all miss -> HARD FAIL "target_not_found"
    4. POLICY     action+coords through allowlist & risk gate BEFORE acting (see §6)
    5. ACT        via Surface (pyautogui event into the fixed window region, scale-corrected)
    6. VERIFY     wait for expect.any_of within timeout; matched state drives branch; timeout -> HARD FAIL
    7. EXTRACT    for read actions: OCR the anchored region -> typed output (redaction hook applied to logs)

ReplayResult = { status: success | business_outcome | escalated | failed,
                 outputs?, outcome_code?, failed_step?, expected?, observed?, evidence_dir }
```

Determinism claims: no model calls; OCR+matching are pure functions of pixels; window geometry is pinned at launch and asserted; DPI scale is calibrated once per run, not guessed; all waits are bounded and condition-based (never bare sleeps); every branch is enumerated in the artifact; anything unrecognized halts loudly instead of proceeding blindly.

---

## 5. Discovery loop (agent/)

1. Screenshot → OCR word boxes → **set-of-marks overlay** (numbered boxes on interactive-looking regions) so the model grounds actions as "click mark 7", not raw pixels.
2. GPT-4o via function calling (`click(mark)`, `type(mark, text)`, `key`, `read(mark)`, `done(outputs)`, `escalate(reason)`) decides one action per turn; screenshots sent as base64 image parts; max-steps + timeout stop conditions. All OpenAI specifics live in `agent/llm_openai.py` — the loop itself talks to a 5-function interface.
3. Recorder captures per step: pre/post screenshots, chosen mark's OCR text + neighbors (→ anchors), element crop (→ template), coords, and the model's stated expectation of the next screen.
4. **Compiler** turns the trajectory into the artifact: substitutes input params for literals, builds anchor bundles, derives screen_states from observed screens (+ hand-authored error states for screens discovery never hit — documented as a deliberate seam), emits `status: draft` + a compile-notes sidecar.
5. Every discovery action passes the same policy gate as replay (§6). Evidence saved under `evidence/runs/disc-*/`.

---

## 6. Safety & policy (policy/)

- **Allowlist** (JSON per app): permitted action kinds, max steps/run, and — since there is no navigation API to gate — a **screen-scope rule**: before every action, the current screen must match a known state of the allowed app (`app_ready` ancestry); if the foreground content stops matching (wrong window, unexpected app), acting is refused and the run escalates. Enforced at the single dispatch chokepoint both discovery and replay pass through.
- **Risk classes:** `read` = safe; `click` on targets matching irreversible patterns (configurable regexes: "Confirm Transfer", "Delete", "Post Transaction") = **risky → block in unattended replay, escalate to human confirm**. Default deny for unknown action kinds.
- **Redaction:** outputs and logs pass a redaction hook (mask account-number-like patterns in logs; artifact stores parameter *names* only; screenshots of screens flagged sensitive get region masking — thin but real, documented). Screenshots sent to the LLM during discovery are of the demo app with fake data only; the same redaction hook runs on anything persisted.
- **Secrets:** none in repo; `OPENAI_API_KEY` via env; target app uses fake seeded data only.

---

## 7. Handoff (handoff/) — control-token state machine

```
AUTO_RUNNING -> (stuck: unknown screen | recovery exhausted | risky action) -> ESCALATED
ESCALATED    -> operator clicks "Take control"                              -> HUMAN_CONTROL
HUMAN_CONTROL-> operator clicks "Hand back"                                 -> RESUMING
RESUMING     -> engine re-CLASSIFIES current screen:
                 recognized -> continue at appropriate step (AUTO_RUNNING)
                 still unknown -> ESCALATED again or FAIL
```

Exactly one controller at a time (a token, asserted before every `Surface.act`; automation emits **zero** input events while in HUMAN_CONTROL). The intervention request carries: capability id/version, step id, reason, current screenshot, last N log lines. The handoff itself is trivially real in a driver-less design: the human just uses the actual mouse and keyboard on the same live window. During HUMAN_CONTROL a `pynput` global listener (works on both OSes; on Linux requires X11, same constraint as output) records their clicks/keys (coords + OCR text near each click) plus before/after screenshots — written into the same run log as `human_action` entries. Resume never assumes what the human did; it re-derives state from the screen. Operator console = the minimal FastAPI page (mocked UI, real mechanism).

---

## 8. Build order (vertical slice first)

1. **Target app** (member lookup happy path + not-found + validation error + timeout interstitial behind a flag) + `platformx` launcher (browser discovery + app-mode launch at fixed geometry, Linux + Windows)
2. **Surface + perception** (mss screenshot of fixed region, pyautogui click/type with scale correction; OCR boxes; anchor resolution; state matchers) — with pytest on saved PNGs; smoke-test the surface on both OSes early (this is where platform bugs live)
3. **Artifact schema** (Pydantic + JSON Schema export)
4. **Replay engine** against a *hand-written* artifact — proves determinism before any LLM exists
5. **Discovery loop + recorder + compiler** — the real LLM run (GPT-4o); save evidence
6. **Policy gate** (screen-scope allowlist, risk classes, redaction hook)
7. **Handoff** (state machine + minimal console + pynput capture)
8. **Evidence polish + error-state replay demo** (bad input → business_outcome; timeout flag on → recovery; unknown screen → escalation)
9. README (setup for both OSes: tesseract install, X11 note, Windows scaling note) + REPORT
10. *(only if time)* one stretch goal: multi-run stability report **or** confidence/approval gating

Step 4 before step 5 is deliberate: it forces the artifact to be sufficient on its own, which is the whole thesis.

## 9. Known cuts (pre-declared for REPORT.md)

Desktop-app target demo (the mechanism already supports it; demoing one is a launch-config change we skip for time) · macOS support (Accessibility-permission flow; Linux/Windows cover the demo) · Wayland support (X11 required; OS design decision, not ours to fight in a take-home) · multi-tenant overrides (schema leaves room: app id + future `overrides[]`; write-up only) · real operator console UX · assisted-LLM fallback on replay failure (mentioned as stretch) · region-masking beyond basic patterns · headless/CI e2e (unit tests on saved PNGs instead) · RL/training on run data (two sentences in Cuts: escalation demonstrations are the valuable labeled data).
