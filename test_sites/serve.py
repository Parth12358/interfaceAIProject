"""Serve the multi-tenant banking test sites on one port.

    python -m test_sites.serve                 # http://127.0.0.1:5055/
    python -m test_sites.serve --port 5055

Tenants:
    /meridian  VaultCore (Meridian Trust)  — legacy frameset
    /summit    VaultCore (Summit CU)       — legacy single page, same vendor product
    /novabank  NovaBank                    — modern multi-field form flow

Each tenant reaches the assignment's runtime conditions by member id and the
`?arm=timeout` session flag — see test_sites/data.py.
"""
from __future__ import annotations

import argparse

from flask import Flask, render_template_string

from .tenants.bank import build_bp as build_bank
from .tenants.novabank import build_bp as build_novabank
from .tenants.vaultcore import build_bp as build_vaultcore

_LANDING = """<!doctype html><title>Test banking sites</title>
<h1>Computer-use test sites</h1>
<h2>Original vendors</h2><ul>
<li><a href="/meridian/">/meridian</a> — VaultCore @ Meridian Trust (legacy frameset)</li>
<li><a href="/summit/">/summit</a> — VaultCore @ Summit Credit Union (legacy single page)</li>
<li><a href="/novabank/">/novabank</a> — NovaBank (modern multi-field form)</li>
</ul>
<h2>Five banks</h2><ul>
<li><a href="/firstcoastal/">/firstcoastal</a> — First Coastal Bank · TellerCore (legacy frameset)</li>
<li><a href="/pioneer/">/pioneer</a> — Pioneer Savings Bank · AccountView (dense legacy)</li>
<li><a href="/harbor/">/harbor</a> — Harbor Federal CU · HARBOR GREEN (3270 terminal)</li>
<li><a href="/cascade/">/cascade</a> — Cascade National Bank · CascadeOne (modern)</li>
<li><a href="/unionsquare/">/unionsquare</a> — Union Square Bank · LedgerPro (legacy + wire desk)</li>
</ul>
<p>Special member ids: 11111/22222 ok, 33333 permission, 44444 not-eligible,
55555 arrears, 66666 compliance, 77777 slow, 99999 outage, 00000 not found.
Add <code>?arm=timeout</code> to a tenant root to arm the session-timeout interstitial.</p>"""

# Five banks rendered by the generic `bank` builder (see data.TENANTS).
_BANKS = ["firstcoastal", "pioneer", "harbor", "cascade", "unionsquare"]


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test-sites-not-a-secret"

    app.register_blueprint(build_vaultcore("meridian", "meridian"), url_prefix="/meridian")
    app.register_blueprint(build_vaultcore("summit", "summit"), url_prefix="/summit")
    app.register_blueprint(build_novabank("novabank", "novabank"), url_prefix="/novabank")
    for name in _BANKS:
        app.register_blueprint(build_bank(name, name), url_prefix=f"/{name}")

    @app.get("/")
    def landing():
        return render_template_string(_LANDING)

    @app.get("/__health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
