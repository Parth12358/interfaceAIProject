"""Multi-tenant banking test sites for the computer-use automation system.

These are intentionally detailed stand-ins for back-office bank applications:
server-rendered, table-based, no test IDs, branded differently per institution.
They exist to exercise discovery + deterministic replay against the runtime
conditions the assignment calls out: validation errors, record-not-found,
permission denial, unexpected confirmation dialogs, session/timeout expiry,
transient slowness, outright app errors, and risky/irreversible actions.

Three tenants are served (see `serve.py`):
  * /meridian  — "VaultCore" legacy frameset app (Meridian Trust branding)
  * /summit    — "VaultCore" legacy single-page app (Summit Credit Union branding)
  * /novabank  — a modern web app (NovaBank)

All data is fake and seeded. No real PII, no real credentials.
"""
