# Evidence

Everything here is committed unless noted. All data is fake and seeded for the demo/test apps.

## `replay_demo/` — offline end-to-end replay

Committed output of `python -m src.cli demo` (no browser, no API key): a happy path with extracted
outputs, `not_found` and `validation` business outcomes, and a `timeout` run that is recovered and then
succeeds. Each scenario dir has `log.jsonl`, per-step screenshots, and `result.json`.

## `discovery_demo/` — genuine LLM discovery (CoreServ)

A committed, real LLM-driven discovery run against a live browser over the legacy CoreServ app, produced
by:

```bash
python -m src.cli discover \
    --goal "Look up member 12345 and read their savings balance and name" \
    --target http://127.0.0.1:5000/ --app-id coreserv-demo \
    --input member_id=12345 --cap-id member_lookup_discovered \
    --timeout 300 --evidence evidence/discovery_demo
```

It contains `log.jsonl` (observe→decide→act; each `agent_action` carries the target control and, when the
model states one, its `reason`), per-step overlay screenshots, `compile_notes.txt`, and the compiled
`artifact.json` (`status: draft`; discovery-time literals parameterized, never stored). The compiled
capability replays deterministically from `artifacts/member_lookup_discovered.json`.

## `live_sites/` — the multi-site live pass

The bulk of the evidence. Produced by `python scripts/live_site_matrix.py` against the eight test sites in
`test_sites/` (a real Chrome, no LLM):

- **75 replay bundles** — one directory per case (`<site>_<condition>`), each with `log.jsonl`, step
  screenshots, and `result.json`. They cover the full result taxonomy:
  - `success` (happy lookups on all sites; one VaultCore artifact replays on both VaultCore tenants),
  - `business_outcome` (`MEMBER_NOT_FOUND`, `INVALID_INPUT`, `ACCESS_DENIED`, `ACCOUNT_IN_ARREARS`,
    `INVALID_FORM`),
  - `recoverable` (session-timeout interstitial recovered; slow-load recovered),
  - `failure` (outage → `APP_ERROR_500`; compliance hold → `COMPLIANCE_HOLD`), e.g.
    `meridian_app_error/`,
  - `escalated` (risky "Close Account"/"Send Wire" blocked unattended), e.g. `meridian_close_blocked/`.
- **8 genuine LLM discovery bundles** — `discovery_{meridian,summit,novabank,firstcoastal,pioneer,harbor,cascade,unionsquare}/`,
  each with `log.jsonl`, screenshots, `compile_notes.txt`, and the compiled `artifact.json`. Regenerate
  with `python scripts/live_site_matrix.py --discover <site-path>` or `--discover-all`.

Transient/local runs land under `runs/` (gitignored). The live CDP replay path is also exercised directly,
e.g. `python -m src.cli replay artifacts/member_lookup.json --input member_id=00000`.
