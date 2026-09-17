# CoreServ — Computer-Use Automation System

Vision-first **discovery** → typed **capability artifact** → deterministic, LLM-free **replay**.

An LLM is allowed to be uncertain exactly once — while *discovering* how to accomplish a goal on a
legacy UI. That uncertainty is compiled into a typed, versioned artifact. Production execution is
**deterministic replay** over pixels + coordinates, with **no model in the decision loop**. When replay
can't safely proceed, it **escalates to a human** who takes over the live session.

The system drives the UI the way a human operator does — it sees pixels (screenshots) and emits input
events (clicks/keystrokes). **No DOM selectors, no accessibility tree, no browser driver.** The primary
surface is the browser via the Chrome DevTools Protocol used *only* as a transport for
`captureScreenshot` + coordinate `Input.dispatch*` — never for element selection.

---

## What's here

| Piece | Path | Notes |
|---|---|---|
| Legacy demo app ("CoreServ") | `target_app/` | Flask, table layout, no test IDs; happy path + error taxonomy |
| Multi-tenant test bed | `test_sites/` | Three branded banking sites (frameset + modern) with every runtime condition |
| Surfaces | `src/surface/` | `CdpSurface` (primary), `OsSurface` (secondary), `ScriptedSurface` (offline) |
| Perception (deterministic) | `src/perception/` | OCR word boxes, anchor resolution, screen-state matching |
| Artifact schema | `src/artifact/` | Pydantic v2 + exported JSON Schema |
| Replay engine | `src/replay/engine.py` | no LLM imports (CI-enforced) |
| Discovery loop | `src/agent/` | set-of-marks + DeepSeek adapter + recorder + compiler |
| Policy / safety | `src/policy/` | allowlist, screen-scope, risk classes, redaction |
| Handoff | `src/handoff/` | control-token state machine + FastAPI operator console |
| Evidence | `src/evidence/` | JSONL step log + per-step screenshots + result JSON |
| CLI | `src/cli.py` | `discover | replay | operator | demo` |

Design write-up: **[REPORT.md](REPORT.md)**.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**System dependencies:**
- **Tesseract OCR** (the one non-pip dependency):
  - Arch: `sudo pacman -S tesseract tesseract-data-eng`
  - Debian/Ubuntu: `sudo apt install tesseract-ocr`
  - macOS: `brew install tesseract`
  - Windows: UB-Mannheim installer. The binary is auto-discovered; or set `TESSERACT_CMD`.
- **Chromium/Chrome** (for the live surface only): any Chromium/Chrome/Edge on `PATH`.

Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY` (only needed for the live discovery run).

## Run it without live services

Everything except the one genuine discovery run works with no browser and no API key.

```bash
# Unit tests: perception + replay + policy + handoff, over saved PNG fixtures
pytest

# Offline end-to-end evidence run (happy + not-found + validation + timeout-recovery)
python -m src.cli demo
```

`demo` replays the capability against saved screens and writes a full evidence bundle
(JSONL step log, per-step screenshots, `result.json`) under `evidence/runs/`. A committed
sample is in [`evidence/replay_demo/`](evidence/replay_demo/).

## Demo path — the real thread (live)

Start the target app, then discover a capability and replay it. (Chromium runs a real window;
see the note below about sandboxed shells.)

```bash
# 1. start the legacy target app
python target_app/app.py            # serves http://127.0.0.1:5000/

# 2. DISCOVER — one genuine LLM-driven run compiles a draft artifact + evidence.
#    --target/--app-id set the entry point and the app id; --timeout bounds the run.
#    Real runs are committed: evidence/discovery_demo/ and evidence/live_sites/discovery_*/.
python -m src.cli discover \
    --goal "Look up member 12345 and read their savings balance and name" \
    --target http://127.0.0.1:5000/ --app-id coreserv-demo \
    --input member_id=12345 --cap-id member_lookup_discovered \
    --timeout 300 --evidence evidence/discovery_demo
#   -> writes artifacts/member_lookup_discovered.json (status: draft)
#      + evidence/discovery_demo/{log.jsonl, *.png, compile_notes.txt, artifact.json}

# 3. REPLAY — deterministic, no LLM. Use the hand-written approved artifact or the discovered draft:
python -m src.cli replay artifacts/member_lookup.json --input member_id=12345
python -m src.cli replay artifacts/member_lookup_discovered.json --input member_id=12345 --allow-draft

#    Escalation/handoff on the live run: --operator runs the console in the same process,
#    so a replay that gets stuck actually pauses, lets you take control, and resumes.
python -m src.cli replay artifacts/member_lookup.json --input member_id=12345 --operator

#    Policy is configurable per app: --policy policy.example.json sets allowlist/risk/max_steps.
#    (Replay defaults the policy to the artifact's own app.id, so no policy is needed to try one.)
#    --strict-inputs makes an input pattern mismatch a hard failure (default: warn + let the app validate).

# error/outcome branches (no crash — a returned business outcome):
python -m src.cli replay artifacts/member_lookup.json --input member_id=00000   # MEMBER_NOT_FOUND
python -m src.cli replay artifacts/member_lookup.json --input member_id=abc      # INVALID_INPUT

# 4. OPERATOR console (handoff)
python -m src.cli operator            # http://127.0.0.1:8700
```

You can also drive replay against the saved screens with no browser:
```bash
python -m src.cli replay artifacts/member_lookup.json --surface scripted --scenario timeout
```

### Multi-site live pass (the test bed)

`test_sites/` serves eight branded banking sites from one Flask app, deliberately
built to exercise every runtime condition the brief calls out:

| Site | Vendor product | Surface | Notes |
|---|---|---|---|
| `/meridian` | VaultCore | legacy **frameset** | Meridian Trust branding |
| `/summit` | VaultCore | legacy single page | Summit CU branding — **same artifact replays on both** |
| `/novabank` | NovaBank | modern web app | multi-field form → review → confirmation |
| `/firstcoastal` | TellerCore | legacy frameset | First Coastal Bank |
| `/pioneer` | AccountView | dense legacy | Pioneer Savings Bank; "Close Account" risky flow |
| `/harbor` | HARBOR GREEN | **3270 terminal** (monospace, amber-on-black) | Harbor Federal CU; "Send Wire" risky flow |
| `/cascade` | CascadeOne | modern | Cascade National Bank |
| `/unionsquare` | LedgerPro | legacy | Union Square Bank; "Send Wire" risky flow |

Runtime conditions are reachable by member id (`11111` ok, `33333` permission,
`44444` not-eligible, `55555` arrears, `66666` compliance, `77777` slow,
`99999` outage, `00000` not found) and `?arm=timeout` on a site root arms the
session-timeout interstitial.

```bash
# serve the sites (no key needed)
python -m test_sites.serve                 # http://127.0.0.1:5055/

# the live pass: replay every capability against a real Chrome and assert the
# full taxonomy (success | business_outcome | recoverable | failure | escalated)
python scripts/live_site_matrix.py
python scripts/live_site_matrix.py --filter novabank --no-headless

# timing (no LLM): day-to-day replay latency, incl. browser launch
python scripts/live_site_matrix.py --filter _happy --repeat 3 --timing

# genuine LLM discovery against one site, or every vendor + bank
python scripts/live_site_matrix.py --discover /meridian/
python scripts/live_site_matrix.py --discover-all

# the live pass as an opt-in pytest suite
$env:RUN_LIVE=1; pytest tests/test_live_sites.py
```

The matrix (`scripts/live_site_matrix.py`) runs **75 cases** and covers, live: happy
lookup on both VaultCore tenants from one artifact, an LLM-discovered draft replay,
validation / not-found / permission / arrears / not-eligible business outcomes,
session timeout and slow-load recovery, compliance and backend-outage hard failures,
and the risky "Close Account"/"Send Wire" actions (blocked unattended → escalated;
permitted under a permissive policy → completes). Site routes are also covered
offline in `tests/test_test_sites.py`.

### Environment notes (honest costs)
- The live surfaces need a real display. On **Linux**, `OsSurface` (mss+pyautogui) needs **X11**
  (Wayland blocks synthetic input); the primary `CdpSurface` avoids this by driving the browser over
  CDP. On **Windows**, `OsSurface` needs the DPI-awareness + calibration step (`src/platformx`).
- A **sandboxed shell** (e.g. some CI/agent sandboxes) may kill a long-lived Chromium process group;
  run the live `discover`/`replay` in a normal terminal. Offline `demo`/`pytest` have no such issue.
- Chromium is launched with `--no-sandbox --disable-dev-shm-usage` (standard containerized flags).

## Tests & invariants

```bash
pytest                 # perception/replay/policy/handoff over saved PNGs (deterministic, offline)
lint-imports           # enforces: replay/ imports no agent/ code and no LLM SDK
```
`tests/test_boundaries.py` additionally asserts `sys.platform` appears only in `src/platformx/`.

Adversarial/hardening invariants asserted by the suite:
- `ReplayEngine.run()` never raises — every internal error becomes a structured result (`test_engine_hardening.py`).
- a declared `failure` screen (an outright app error) stops the run as `failed` with its `error_code` — never conflated with a business outcome or an escalation.
- the multi-tenant test bed emits every runtime condition with the vocabulary the artifacts key off (`test_test_sites.py`).
- a `template_ref` cannot read outside the artifact directory (path-traversal fails closed).
- every surface dispatch — normal **and** recovery — passes the policy gate (allowlist + screen-scope + risk, including typed values).
- `max_steps` is enforced; the artifact's `app.id` must match the policy's allowed app.
- `RunLog`/`result.json` redact recursively (nested `observed`/`outputs`), including credential shapes (provider keys, bearer tokens, `password=`/`token=`).
- escalation pauses automation, a human can take the live session, and resume re-derives state (`test_handoff_integration.py`).
- discovery dead-ends (bad marks, repeated actions, provider errors) stop with a structured outcome, is bounded by `max_steps` **and** a wall-clock `--timeout`, records the model's stated rationale per action, and never persists typed literals (`test_discovery_hardening.py`).

## License

Released under the **GNU General Public License v2.0** — see [LICENSE](LICENSE).
