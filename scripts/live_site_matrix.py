"""Live site matrix — deterministic replay of the test-site artifacts against a
real Chrome, covering every runtime condition the assignment calls out.

    python scripts/live_site_matrix.py                 # all cases, headless
    python scripts/live_site_matrix.py --no-headless   # watch it run
    python scripts/live_site_matrix.py --filter novabank
    python scripts/live_site_matrix.py --discover meridian   # one genuine LLM run

This is the "live pass" harness: it starts the multi-tenant banking sites
(test_sites.serve), launches Chrome over CDP, replays each artifact without an
LLM, and asserts the result taxonomy:
  success | business_outcome (MEMBER_NOT_FOUND, INVALID_INPUT, ACCESS_DENIED,
  ACCOUNT_IN_ARREARS, INVALID_FORM) | recoverable (session timeout, slow load)
  | failure (APP_ERROR_500, COMPLIANCE_HOLD) | escalated (risky_action).

Exit code is non-zero if any case fails, so it is CI-usable.
"""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.getLogger("werkzeug").setLevel(logging.ERROR)

from werkzeug.serving import make_server  # noqa: E402

from src.artifact import store  # noqa: E402
from src.evidence.run_log import RunLog  # noqa: E402
from src.platformx import browser  # noqa: E402
from src.platformx.tesseract import configure_pytesseract  # noqa: E402
from src.policy.allowlist import Policy  # noqa: E402
from src.replay.engine import ReplayEngine  # noqa: E402
from src.surface.cdp_surface import CdpSurface  # noqa: E402
from test_sites import data as site_data  # noqa: E402
from test_sites.serve import create_app  # noqa: E402

PORT = 5055
DEBUG_PORT = 9333
VIEWPORT = (1280, 800)

BANKS = ["firstcoastal", "pioneer", "harbor", "cascade", "unionsquare"]


def _rel(path) -> str:
    """Repo-relative path for anything persisted (keeps usernames out of evidence)."""
    try:
        return str(pathlib.Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _lookup_case(name, path, member_id, expect, arm=False):
    return dict(name=name, site=path, artifact="vaultcore_member_lookup.json", app_id="vaultcore",
                inputs={"member_id": member_id}, arm=arm, expect=expect)


def _nova_case(name, member_id, expect, nickname="Vacation Fund", deposit="600", arm=False):
    return dict(name=name, site="/novabank/", artifact="novabank_open_subaccount.json", app_id="novabank",
                inputs={"member_id": member_id, "nickname": nickname, "deposit": deposit},
                arm=arm, expect=expect)


def _bank_cases():
    """Every runtime condition for each of the five banks, plus its risky flow."""
    cases = []
    for bank in BANKS:
        t = site_data.TENANTS[bank]
        app, path = t["app_id"], f"/{bank}/"
        art = f"{bank}_member_lookup.json"
        members = t["members"]

        def add(tag, member_id, expect, arm=False):
            cases.append(dict(name=f"{bank}_{tag}", site=path, artifact=art, app_id=app,
                              inputs={"member_id": member_id}, arm=arm, expect=expect))

        add("happy", "11111", {"status": "success", "outputs": {"member_name": members["11111"]["name"]}})
        add("slow_recovery", "77777", {"status": "success", "outputs": {"member_name": members["77777"]["name"]}})
        add("timeout_recovery", "11111", {"status": "success", "outputs": {"member_name": members["11111"]["name"]}}, arm=True)
        add("not_found", "00000", {"status": "business_outcome", "outcome_code": "MEMBER_NOT_FOUND"})
        add("invalid_input", "abc", {"status": "business_outcome", "outcome_code": "INVALID_INPUT"})
        add("permission_denied", "33333", {"status": "business_outcome", "outcome_code": "ACCESS_DENIED"})
        add("arrears", "55555", {"status": "business_outcome", "outcome_code": "ACCOUNT_IN_ARREARS"})
        add("app_error", "99999", {"status": "failed", "reason": "APP_ERROR_500"})
        add("compliance_hold", "66666", {"status": "failed", "reason": "COMPLIANCE_HOLD"})

        if t.get("special_flow") == "closure":
            cases.append(dict(name=f"{bank}_close_blocked", site=path, artifact=f"{bank}_close_account.json",
                              app_id=app, inputs={"member_id": "11111"},
                              expect={"status": "escalated", "reason_contains": "risky_action"}))
            cases.append(dict(name=f"{bank}_close_permissive", site=path, artifact=f"{bank}_close_account.json",
                              app_id=app, inputs={"member_id": "11111"}, risky_patterns=[],
                              expect={"status": "success", "outputs": {"closure_reference_prefix": "CLS-"}}))
        elif t.get("special_flow") == "wire":
            wire_inputs = {"member_id": "11111", "beneficiary": "Acme Ltd", "amount": "1500"}
            cases.append(dict(name=f"{bank}_wire_blocked", site=path, artifact=f"{bank}_send_wire.json",
                              app_id=app, inputs=dict(wire_inputs),
                              expect={"status": "escalated", "reason_contains": "risky_action"}))
            cases.append(dict(name=f"{bank}_wire_permissive", site=path, artifact=f"{bank}_send_wire.json",
                              app_id=app, inputs=dict(wire_inputs), risky_patterns=[],
                              expect={"status": "success", "outputs": {"wire_reference_prefix": "WR-"}}))
    return cases



CASES = [
    # --- VaultCore lookup across both tenants (one artifact, two institutions) ---
    _lookup_case("meridian_happy", "/meridian/", "11111", {"status": "success", "outputs": {"member_name": "Jordan Avery", "savings_balance": "$18,204.77"}}),
    _lookup_case("meridian_slow_recovery", "/meridian/", "77777", {"status": "success", "outputs": {"member_name": "Samir Haddad"}}),
    _lookup_case("meridian_timeout_recovery", "/meridian/", "11111", {"status": "success", "outputs": {"member_name": "Jordan Avery"}}, arm=True),
    _lookup_case("meridian_not_found", "/meridian/", "00000", {"status": "business_outcome", "outcome_code": "MEMBER_NOT_FOUND"}),
    _lookup_case("meridian_invalid_input", "/meridian/", "abc", {"status": "business_outcome", "outcome_code": "INVALID_INPUT"}),
    _lookup_case("meridian_permission_denied", "/meridian/", "33333", {"status": "business_outcome", "outcome_code": "ACCESS_DENIED"}),
    _lookup_case("meridian_arrears", "/meridian/", "55555", {"status": "business_outcome", "outcome_code": "ACCOUNT_IN_ARREARS"}),
    _lookup_case("meridian_app_error", "/meridian/", "99999", {"status": "failed", "reason": "APP_ERROR_500"}),
    _lookup_case("meridian_compliance_hold", "/meridian/", "66666", {"status": "failed", "reason": "COMPLIANCE_HOLD"}),
    _lookup_case("summit_happy", "/summit/", "11111", {"status": "success", "outputs": {"member_name": "Robin Okafor", "savings_balance": "$42,318.09"}}),
    _lookup_case("summit_permission_denied", "/summit/", "33333", {"status": "business_outcome", "outcome_code": "ACCESS_DENIED"}),
    # --- genuinely LLM-discovered draft, replayed deterministically ---
    dict(name="meridian_discovered_draft", site="/meridian/", artifact="discovered_meridian.json",
         app_id="vaultcore", inputs={"member_id": "11111"},
         expect={"status": "success", "outputs": {"member_name": "Jordan Avery", "account_status": "Active"}}),
    # --- NovaBank multi-field form + review/confirm ---
    _nova_case("novabank_open_subaccount", "11111", {"status": "success", "outputs": {"account_number_prefix": "NOVA-"}}),
    _nova_case("novabank_slow_recovery", "77777", {"status": "success", "outputs": {"account_number_prefix": "NOVA-"}}),
    _nova_case("novabank_timeout_recovery", "11111", {"status": "success", "outputs": {"account_number_prefix": "NOVA-"}}, arm=True),
    _nova_case("novabank_not_found", "00000", {"status": "business_outcome", "outcome_code": "MEMBER_NOT_FOUND"}),
    _nova_case("novabank_permission_denied", "33333", {"status": "business_outcome", "outcome_code": "ACCESS_DENIED"}),
    _nova_case("novabank_not_eligible", "44444", {"status": "business_outcome", "outcome_code": "ACCESS_DENIED"}),
    _nova_case("novabank_form_invalid", "11111", {"status": "business_outcome", "outcome_code": "INVALID_FORM"}, nickname="", deposit="10"),
    _nova_case("novabank_app_error", "99999", {"status": "failed", "reason": "APP_ERROR_500"}),
    # --- risky / irreversible action ---
    dict(name="meridian_close_blocked", site="/meridian/", artifact="vaultcore_close_account.json",
         app_id="vaultcore", inputs={"member_id": "11111"},
         expect={"status": "escalated", "reason_contains": "risky_action"}),
    dict(name="meridian_close_permissive", site="/meridian/", artifact="vaultcore_close_account.json",
         app_id="vaultcore", inputs={"member_id": "11111"}, risky_patterns=[],
         expect={"status": "success", "outputs": {"closure_reference_prefix": "CLS-"}}),
]

# Every runtime condition on each of the five banks (+ its risky flow).
CASES += _bank_cases()


def _matches(result, expect) -> tuple[bool, str]:
    if result.status != expect["status"]:
        return False, f"status={result.status} expected={expect['status']}"
    if "outcome_code" in expect and result.outcome_code != expect["outcome_code"]:
        return False, f"outcome_code={result.outcome_code} expected={expect['outcome_code']}"
    if "reason" in expect and result.reason != expect["reason"]:
        return False, f"reason={result.reason!r} expected={expect['reason']!r}"
    if "reason_contains" in expect and (expect["reason_contains"] not in (result.reason or "")):
        return False, f"reason={result.reason!r} expected to contain {expect['reason_contains']!r}"
    for key, want in (expect.get("outputs") or {}).items():
        if key.endswith("_prefix"):
            name = key[: -len("_prefix")]
            got = result.outputs.get(name) or ""
            if not str(got).startswith(want):
                return False, f"output {name}={got!r} expected prefix {want!r}"
        else:
            got = result.outputs.get(key)
            if got != want:
                return False, f"output {key}={got!r} expected {want!r}"
    return True, ""


def run_case(case, headless, evidence_root) -> tuple[bool, str, float, float, float]:
    url = f"http://127.0.0.1:{PORT}{case['site']}"
    if case.get("arm"):
        url += "?arm=timeout"
    t0 = time.monotonic()
    proc = browser.launch_chromium(url, DEBUG_PORT, VIEWPORT, headless=headless)
    t_launch = time.monotonic()
    surface = None
    try:
        surface = CdpSurface(DEBUG_PORT, VIEWPORT)
        log = RunLog(evidence_root / case["name"], kind="replay")
        policy = Policy(app_id=case["app_id"],
                        risky_patterns=case.get("risky_patterns", Policy().risky_patterns))
        engine = ReplayEngine(surface, policy=policy, run_log=log,
                              settle_ms=1200, poll_ms=200, escalation_timeout_s=5.0)
        artifact = store.load(ROOT / "artifacts" / case["artifact"])
        result = engine.run(artifact, case["inputs"], allow_draft=True,
                            artifact_dir=ROOT / "artifacts")
        out = result.to_dict()
        out["evidence_dir"] = _rel(out.get("evidence_dir"))
        log.result(out)
        ok, why = _matches(result, case["expect"])
        t_end = time.monotonic()
        return ok, why, t_end - t0, t_launch - t0, t_end - t_launch
    finally:
        if surface is not None:
            surface.close()
        browser.kill_process_group(proc)
        time.sleep(0.3)


def _app_id_for_site(site: str) -> str:
    name = site.strip("/").split("/")[0]
    if name in ("meridian", "summit"):
        return "vaultcore"
    if name == "novabank":
        return "novabank"
    t = site_data.TENANTS.get(name)
    return t["app_id"] if t else name


def run_discovery(site, headless, evidence_root) -> int:
    """One genuine LLM discovery run against a test site (needs DEEPSEEK_API_KEY)."""
    from src import config as cfg
    from src.agent.compiler import compile_artifact
    from src.agent.llm_deepseek import DeepSeekProvider
    from src.agent.loop import run_discovery
    from src.artifact.schema import AppRef
    from src.platformx.identity import platform_name

    conf = cfg.load()
    if not conf.llm.api_key:
        print("ERROR: no DEEPSEEK_API_KEY set; skipping discovery.")
        return 2
    name = site.strip("/").split("/")[0]
    app_id = _app_id_for_site(site)
    url = f"http://127.0.0.1:{PORT}{site}"
    cap_id = f"discovered_{name}"
    run_dir = evidence_root / f"discovery_{name}"
    log = RunLog(run_dir, kind="discovery")
    provider = DeepSeekProvider(conf.llm.api_key, conf.llm.base_url, conf.llm.model)
    proc = browser.launch_chromium(url, DEBUG_PORT, VIEWPORT, headless=headless)
    surface = None
    try:
        surface = CdpSurface(DEBUG_PORT, VIEWPORT)
        traj = run_discovery(
            "Look up member 11111 and read their name, account status and savings balance",
            surface, provider, run_log=log, policy=Policy(app_id=app_id),
            max_steps=10, inputs={"member_id": "11111"})
    finally:
        if surface is not None:
            surface.close()
        browser.kill_process_group(proc)
    app = AppRef(id=app_id, entry=url, viewport=VIEWPORT)
    artifact, notes = compile_artifact(traj, cap_id, app, model=conf.llm.model,
                                       discovery_run=_rel(run_dir), platform=platform_name())
    store.save(artifact, run_dir / "artifact.json")
    store.save(artifact, ROOT / "artifacts" / f"{cap_id}.json")
    (run_dir / "compile_notes.txt").write_text("\n".join(notes), encoding="utf-8")
    print(f"discovery[{site}] app={app_id} outcome={traj.outcome} steps={len(traj.steps)} "
          f"-> artifacts/{cap_id}.json")
    return 0 if traj.outcome == "done" else 1


DISCOVER_SITES = ["/meridian/", "/summit/", "/novabank/", "/firstcoastal/", "/pioneer/",
                  "/harbor/", "/cascade/", "/unionsquare/"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter", default="", help="substring filter on case name")
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--discover", help="run one LLM discovery against this site path (e.g. /meridian/)")
    ap.add_argument("--discover-all", action="store_true",
                    help="run genuine LLM discovery against every vendor and bank")
    ap.add_argument("--repeat", type=int, default=1, help="run each selected case N times")
    ap.add_argument("--timing", action="store_true", help="print a replay-timing summary")
    ap.add_argument("--evidence", default=str(ROOT / "evidence" / "live_sites"))
    args = ap.parse_args()

    configure_pytesseract()
    evidence_root = pathlib.Path(args.evidence)
    evidence_root.mkdir(parents=True, exist_ok=True)

    server = make_server("127.0.0.1", PORT, create_app(), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.5)
    print(f"test sites on http://127.0.0.1:{PORT}  (chrome debug :{DEBUG_PORT})")

    try:
        if args.discover_all:
            rc = 0
            for site in DISCOVER_SITES:
                rc |= run_discovery(site, not args.no_headless, evidence_root)
            return rc
        if args.discover:
            return run_discovery(args.discover, not args.no_headless, evidence_root)

        selected = [c for c in CASES if args.filter in c["name"]]
        cases = [c for c in selected for _ in range(max(1, args.repeat))]
        print(f"running {len(cases)} live cases\n")
        failures = []
        rows: list[tuple[str, float, float, float]] = []
        for case in cases:
            ok, why, dt, launch, replay = run_case(case, not args.no_headless, evidence_root)
            rows.append((case["name"], dt, launch, replay))
            tag = "PASS" if ok else "FAIL"
            print(f"  {tag}  {case['name']:34s} {dt:5.1f}s  {case['expect']['status']:16s} {why}")
            if not ok:
                failures.append(case["name"])
        print()

        if args.timing or args.repeat > 1:
            _print_timing(rows)

        if failures:
            print(f"FAILED {len(failures)}/{len(cases)}: {', '.join(failures)}")
            return 1
        print(f"ALL {len(cases)} LIVE CASES PASSED")
        return 0
    finally:
        server.shutdown()


def _print_timing(rows) -> None:
    import statistics

    by_name: dict[str, list[tuple[float, float, float]]] = {}
    for name, dt, launch, replay in rows:
        by_name.setdefault(name, []).append((dt, launch, replay))
    print("TIMING — deterministic replay, no LLM (end-to-end includes Chrome launch)")
    print(f"  {'case':34s} {'n':>2s} {'launch':>8s} {'replay':>8s} {'e2e mean':>9s} {'min':>7s} {'max':>7s}")
    all_dt: list[float] = []
    for name, vals in by_name.items():
        dts = [v[0] for v in vals]
        launches = [v[1] for v in vals]
        replays = [v[2] for v in vals]
        all_dt += dts
        print(f"  {name:34s} {len(vals):2d} {statistics.mean(launches):7.1f}s "
              f"{statistics.mean(replays):7.1f}s {statistics.mean(dts):8.1f}s "
              f"{min(dts):6.1f}s {max(dts):6.1f}s")
    print(f"\n  OVERALL n={len(all_dt)}  mean={statistics.mean(all_dt):.1f}s  "
          f"median={statistics.median(all_dt):.1f}s  min={min(all_dt):.1f}s  "
          f"max={max(all_dt):.1f}s  total={sum(all_dt):.1f}s")
    print("  (launch = Chrome start; replay = engine run incl. navigation settle/OCR)\n")


if __name__ == "__main__":
    raise SystemExit(main())
