# AGENTS.md — working in this repo

Guidance for AI coding agents (and humans) operating on this project. Read this before
running anything.

## What this is

A computer-use automation system: an LLM **discovers** how to complete a goal against a
legacy web UI, compiles the run into a typed, parameterized **artifact**, and then
**replays** it deterministically with no model in the decision loop. When replay can't
safely proceed it **escalates** to a human who takes over the same live session.

Pipeline: `goal → discover (LLM) → compile → artifacts/*.json → replay (deterministic) → result`.

The authoritative docs are `README.md` and `REPORT.md`. `TECH_DOC.md` is a **superseded**
pre-build design doc — do not treat it as spec. Assignment requirements are in the PDF
`Assignment A — Computer-Use Automation System.pdf` (extractable with `pdftotext -layout`).

## Repo map

| Path | What |
|---|---|
| `target_app/` | Flask "CoreServ" legacy demo bank app (the surface to drive) |
| `src/surface/` | Surface protocol + `CdpSurface` (primary), `OsSurface` (secondary), `ScriptedSurface` (offline) |
| `src/perception/` | Deterministic OCR word boxes, anchor resolution, screen-state matching |
| `src/artifact/` | Pydantic v2 schema, load/save, exported JSON Schema |
| `src/replay/engine.py` | Deterministic replay + error taxonomy + policy + handoff wiring |
| `src/agent/` | Discovery loop, set-of-marks, DeepSeek adapter, compiler |
| `src/policy/` | Allowlist / screen-scope / risk gate / redaction |
| `src/handoff/` | Control-token state machine, operator FastAPI console, human-action capture |
| `src/evidence/` | JSONL run log + per-step screenshots + result JSON |
| `src/cli.py` | `discover | replay | operator | demo` |
| `tests/` | pytest suite; `tests/FINDINGS.md` is the adversarial audit report |
| `evidence/replay_demo/` | committed offline replay evidence |

## Hard rules (CI-enforced — do not violate)

- `src/replay/` must not import `src/agent/` or any LLM SDK (`openai`, `anthropic`).
  Enforced by `.importlinter` and `tests/test_boundaries.py`.
- `sys.platform` may appear **only** in `src/platformx/` (`tests/test_boundaries.py`).
- `ReplayEngine.run()` must never raise — internal errors become structured `failed` results.
- Never persist secrets, credentials, or discovery-time literal values into artifacts or logs.
- Only commit/push when explicitly asked.

## Setup

### Windows (primary dev target for the live run)

```powershell
# 1. Python deps
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Tesseract OCR is a SYSTEM dependency (not pip)
#    Install the UB-Mannheim build, then either add it to PATH or set:
#    TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# 3. Chromium/Chrome/Edge must exist — auto-discovered from PATH or
#    C:\Program Files\...\chrome.exe / msedge.exe

# 4. Config
copy .env.example .env
# edit .env (see below)
```

### Linux/macOS

Install `tesseract` (`sudo pacman -S tesseract tesseract-data-eng` /
`sudo apt install tesseract-ocr` / `brew install tesseract`) and any Chromium.

## Config — `.env` (gitignored; copy from `.env.example`)

```
DEEPSEEK_API_KEY=sk-...                 # REQUIRED for discovery only
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash               # verified available; supports vision + function calling
TARGET_APP_URL=http://127.0.0.1:5000/
TARGET_APP_PORT=5000
CORESERV_INJECT_TIMEOUT=0              # set 1 to arm the session-timeout interstitial
CHROME_HEADLESS=1                      # 1 = headless (reliable in sandboxes); 0 = real window
CHROME_REMOTE_DEBUG_PORT=9222
VIEWPORT_W=1280
VIEWPORT_H=800
```

`src/config.py` reads these via `python-dotenv`. Replay, demo, tests, and the operator
console need **no key**; only `discover` does. If a provider call hangs, the DeepSeek
client is bounded to 120s/1 retry in `src/agent/llm_deepseek.py`.

**Windows note:** `CHROME_HEADLESS=0` is fine on a real desktop. On headless sandboxes a
*headed* Chromium can stall `Page.captureScreenshot`; keep `CHROME_HEADLESS=1` there.

## Common commands

Run everything from the repo root.

```bash
pytest                                  # full suite (needs tesseract; OCR tests skip without it)
pytest tests/test_engine_hardening.py   # a single file
lint-imports                            # replay/ has no agent/LLM imports
python -m src.cli demo --evidence evidence/replay_demo   # offline end-to-end replay evidence
python -m src.cli replay artifacts/member_lookup.json --input member_id=12345
python -m src.cli replay artifacts/member_lookup.json --surface scripted --scenario timeout
python -m src.cli operator              # handoff console at http://127.0.0.1:8700
```

`replay` supports: `--input k=v` (repeatable), `--surface cdp|scripted`, `--scenario
happy|not_found|validation|timeout`, `--allow-draft`, `--strict-inputs`, `--policy FILE`,
`--operator` (runs the console in-process and actually pauses/resumes on escalation),
`--evidence DIR`.

## The real discovery run (only thing needing a key)

Two terminals:

```bash
# Terminal A
python target_app/app.py

# Terminal B  (Windows PowerShell: put the command on one line or use backticks)
python -m src.cli discover \
  --goal "Look up member 12345 and read their savings balance and name" \
  --input member_id=12345 --cap-id member_lookup_discovered \
  --evidence evidence/discovery_demo
```

Then prove the compiled capability replays:

```bash
python -m src.cli replay artifacts/member_lookup_discovered.json --input member_id=12345 --allow-draft
```

`--evidence evidence/discovery_demo` writes a **committable** bundle (`log.jsonl`,
overlay screenshots, `compile_notes.txt`, `artifact.json`). Without `--evidence` the run
goes to the gitignored `evidence/runs/`. Commit the discovery bundle once it succeeds —
it is a graded deliverable.

## Before you finish a change

1. `pytest` green (or note skips if tesseract is missing) and `lint-imports` kept.
2. If you touched behavior, update `README.md` / `REPORT.md` so docs match code —
   the previous review specifically penalized doc claims not backed by code.
3. Do not commit unless asked. When asked, author/committer must be the repo owner
   (`git config user.name` / `user.email` are already set), with no `Co-Authored-By`
   trailers.

## Known open items (see `tests/FINDINGS.md` for the full list)

- The genuine LLM discovery evidence is not committed yet (needs the key + a live run).
- The public remote is `Parth12358/interfaceAIProject`; `main` may be ahead of `origin/main`.
- Screenshot region-masking is not implemented (redaction is text/JSON only).
- Multi-tenant `overrides[]` is design-only; the multi-bank stress harness was deferred.
- `OsSurface` is not selectable from the CLI (`--surface` is `cdp|scripted`).
