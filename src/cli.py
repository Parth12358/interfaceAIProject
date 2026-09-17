"""Command-line entrypoint: discover | replay | operator | demo.

    python -m src.cli replay artifacts/member_lookup.json --input member_id=12345
    python -m src.cli discover --goal "Look up member 12345 ..." --input member_id=12345
    python -m src.cli operator            # start the handoff operator console
    python -m src.cli demo                 # offline evidence run (no browser/key)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

from . import config as cfg
from .artifact import store
from .evidence.run_log import RunLog
from .platformx.tesseract import configure_pytesseract
from .policy.allowlist import Policy
from .replay.engine import ReplayEngine

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

# Offline demo scenarios over saved screens (no browser / no key).
SCENARIOS = {
    "happy": ("welcome", {"welcome": ("Member Lookup", "search_form"),
                          "search_form": ("Find", "member_detail")}, {"member_id": "12345"}),
    "not_found": ("welcome", {"welcome": ("Member Lookup", "search_form"),
                             "search_form": ("Find", "no_member_found")}, {"member_id": "00000"}),
    "validation": ("welcome", {"welcome": ("Member Lookup", "search_form"),
                              "search_form": ("Find", "validation_error")}, {"member_id": "abc"}),
    "timeout": ("welcome", {"welcome": ("Member Lookup", "search_form"),
                          "search_form": ("Find", "session_timeout"),
                          "session_timeout": ("Continue", "member_detail")}, {"member_id": "12345"}),
}


def _run_dir(kind: str) -> pathlib.Path:
    return ROOT / "evidence" / "runs" / f"{kind}-{int(time.time())}"


def _parse_inputs(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        out[k.strip()] = v.strip()
    return out


def _make_live_surface(conf):
    from .platformx import browser
    from .surface.cdp_surface import CdpSurface

    proc = browser.launch_chromium(conf.target_app_url, conf.chrome_debug_port, conf.viewport)
    surface = CdpSurface(conf.chrome_debug_port, conf.viewport)
    return surface, (lambda: browser.kill_process_group(proc))


# --- commands ----------------------------------------------------------------
def cmd_replay(args):
    configure_pytesseract()
    conf = cfg.load()
    artifact = store.load(args.artifact)
    inputs = _parse_inputs(args.input)
    run_dir = pathlib.Path(args.evidence) if args.evidence else _run_dir("replay")
    log = RunLog(run_dir, kind="replay")

    cleanup = lambda: None
    if args.surface == "scripted":
        from .surface.scripted import ScriptedSurface
        initial, transitions, demo_inputs = SCENARIOS[args.scenario]
        inputs = inputs or demo_inputs
        surface = ScriptedSurface(FIXTURES, initial, transitions)
    else:
        surface, cleanup = _make_live_surface(conf)

    try:
        engine = ReplayEngine(surface, policy=Policy(), run_log=log)
        result = engine.run(artifact, inputs, allow_draft=args.allow_draft,
                            artifact_dir=pathlib.Path(args.artifact).parent)
    finally:
        surface.close()
        cleanup()
    log.result(result.to_dict())
    print(json.dumps(result.to_dict(), indent=2))
    print(f"\nevidence: {run_dir}")
    return 0 if result.status in ("success", "business_outcome") else 1


def cmd_discover(args):
    configure_pytesseract()
    conf = cfg.load()
    if not conf.llm.api_key:
        print("ERROR: no DEEPSEEK_API_KEY set (needed for the genuine discovery run).")
        return 2
    from .agent.compiler import compile_artifact
    from .agent.llm_deepseek import DeepSeekProvider
    from .agent.loop import run_discovery
    from .artifact.schema import AppRef

    inputs = _parse_inputs(args.input)
    run_dir = _run_dir("disc")
    log = RunLog(run_dir, kind="discovery")
    provider = DeepSeekProvider(conf.llm.api_key, conf.llm.base_url, conf.llm.model)
    goal = args.goal + (f"\nUse these input values: {inputs}" if inputs else "")

    surface, cleanup = _make_live_surface(conf)
    try:
        traj = run_discovery(goal, surface, provider, run_log=log, policy=Policy(),
                             max_steps=args.max_steps, inputs=inputs)
    finally:
        surface.close()
        cleanup()

    app = AppRef(id="coreserv-demo", entry=conf.target_app_url, viewport=conf.viewport)
    artifact, notes = compile_artifact(traj, args.cap_id, app, model=conf.llm.model,
                                       discovery_run=str(run_dir))
    out_path = ROOT / "artifacts" / f"{args.cap_id}.json"
    store.save(artifact, out_path)
    (run_dir / "compile_notes.txt").write_text("\n".join(notes))
    log.event("discovery_done", outcome=traj.outcome, steps=len(traj.steps), artifact=str(out_path))
    print(f"discovery outcome: {traj.outcome}; steps: {len(traj.steps)}")
    print(f"artifact (draft): {out_path}\nevidence: {run_dir}")
    return 0 if traj.outcome == "done" else 1


def cmd_operator(args):
    import uvicorn

    from .handoff.operator_api import app
    print(f"Operator console on http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_demo(args):
    """Offline end-to-end evidence run over saved screens (no browser / no key)."""
    configure_pytesseract()
    from .surface.scripted import ScriptedSurface
    artifact = store.load(ROOT / "artifacts" / "member_lookup.json")
    base = _run_dir("demo")
    summary = {}
    for name in ("happy", "not_found", "validation", "timeout"):
        initial, transitions, inputs = SCENARIOS[name]
        log = RunLog(base / name, kind=f"replay:{name}")
        surface = ScriptedSurface(FIXTURES, initial, transitions)
        result = ReplayEngine(surface, policy=Policy(), run_log=log).run(artifact, inputs)
        log.result(result.to_dict())
        summary[name] = result.to_dict()
        print(f"  {name:11s} -> {result.status}"
              + (f" ({result.outcome_code})" if result.outcome_code else "")
              + (f" outputs={result.outputs}" if result.outputs else ""))
    (base / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nevidence: {base}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="coreserv-cua")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("replay", help="deterministically replay an artifact")
    r.add_argument("artifact")
    r.add_argument("--input", action="append", help="key=value (repeatable)")
    r.add_argument("--surface", choices=["cdp", "scripted"], default="cdp")
    r.add_argument("--scenario", choices=list(SCENARIOS), default="happy", help="scripted surface only")
    r.add_argument("--evidence")
    r.add_argument("--allow-draft", action="store_true")
    r.set_defaults(func=cmd_replay)

    d = sub.add_parser("discover", help="run the LLM discovery loop -> draft artifact")
    d.add_argument("--goal", required=True)
    d.add_argument("--input", action="append", help="key=value (repeatable)")
    d.add_argument("--cap-id", default="member_lookup_discovered")
    d.add_argument("--max-steps", type=int, default=12)
    d.set_defaults(func=cmd_discover)

    o = sub.add_parser("operator", help="start the handoff operator console")
    o.add_argument("--port", type=int, default=8700)
    o.set_defaults(func=cmd_operator)

    dm = sub.add_parser("demo", help="offline evidence run over saved screens")
    dm.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
