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

# 2. DISCOVER — one genuine LLM-driven run compiles a draft artifact + evidence
python -m src.cli discover \
    --goal "Look up member 12345 and read their savings balance and name" \
    --input member_id=12345 --cap-id member_lookup_discovered
#   -> writes artifacts/member_lookup_discovered.json (status: draft) + evidence/runs/disc-*/

# 3. REPLAY — deterministic, no LLM. Use the hand-written approved artifact or the discovered draft:
python -m src.cli replay artifacts/member_lookup.json --input member_id=12345
python -m src.cli replay artifacts/member_lookup_discovered.json --input member_id=12345 --allow-draft

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

## License

Released under the **GNU General Public License v2.0** — see [LICENSE](LICENSE).
