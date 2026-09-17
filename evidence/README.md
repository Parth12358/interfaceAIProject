# Evidence

- `replay_demo/` — a committed offline end-to-end **replay** run (`python -m src.cli demo`):
  happy path (with extracted outputs), `not_found` and `validation` business outcomes, and a
  `timeout` run that is recovered then succeeds. Each scenario dir has `log.jsonl`, per-step
  screenshots, and `result.json`.
- `discovery_demo/` — the genuine **discovery** run (LLM-driven, against a live browser). Produce it
  with an explicit committable path (needs `DEEPSEEK_API_KEY` + chromium):

  ```bash
  python -m src.cli discover \
      --goal "Look up member 12345 and read their savings balance and name" \
      --input member_id=12345 --cap-id member_lookup_discovered \
      --evidence evidence/discovery_demo
  ```

  This writes `log.jsonl` (observe→decide→act + `agent_action` entries), per-step overlay
  screenshots, `compile_notes.txt`, and the compiled `artifact.json` (status `draft`, discovery-time
  literals parameterized, never stored). Its code path is identical to the offline-verified
  discover→compile→replay round-trip in `tests/test_discovery.py`.

- Transient/local runs land under `runs/` (gitignored). The live CDP replay path is exercised the same
  way, e.g. `python -m src.cli replay artifacts/member_lookup.json --input member_id=00000`.
