# Evidence

- `replay_demo/` — a committed offline end-to-end **replay** run (`python -m src.cli demo`):
  happy path (with extracted outputs), `not_found` and `validation` business outcomes, and a
  `timeout` run that is recovered then succeeds. Each scenario dir has `log.jsonl`, per-step
  screenshots, and `result.json`.
- The genuine **discovery** run (LLM-driven, against a live browser) is produced by
  `python -m src.cli discover …` and lands under `runs/disc-*/` (gitignored as transient).
  Its code path is identical to the offline-verified discover→compile→replay round-trip in
  `tests/test_discovery.py`.
