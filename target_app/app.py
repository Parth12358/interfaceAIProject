"""CoreServ — a deliberately legacy-style demo "core banking" app.

Intentionally hostile surface (per the assignment's legacy-app option):
  - server-rendered, frameset shell, nested <table> layout, <font> tags
  - NO test IDs, NO semantic ids, NO stable selectors
The only reliable surface is what a human operator sees — which is exactly
what our vision-first discovery + OCR-anchored replay consumes.

Screens emit a fixed text vocabulary that the artifact's screen_states key off:
  app_ready="CoreServ", search_form="Member Search", member_detail="Member Profile",
  no_member_found="No member found", validation_error="Invalid member number",
  session_timeout="Session expired"/"Continue".

Fault injection: when CORESERV_INJECT_TIMEOUT=1, the first search in a session
returns a "Session expired" interstitial (reproducible recovery evidence).
All data is fake and seeded — no PII, no real accounts.
"""
from __future__ import annotations

import os

from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "coreserv-demo-not-a-secret"

# --- Seeded fake members (no real PII) ---------------------------------------
MEMBERS: dict[str, dict[str, str]] = {
    "12345": {"name": "Ada Lovelace", "savings": "$4,213.55", "checking": "$1,002.10"},
    "67890": {"name": "Alan Turing", "savings": "$12,900.00", "checking": "$338.72"},
    "24601": {"name": "Grace Hopper", "savings": "$88,410.19", "checking": "$5,120.00"},
}


def _inject_timeout() -> bool:
    return os.environ.get("CORESERV_INJECT_TIMEOUT", "0") == "1"


@app.route("/")
def index():
    return render_template("welcome.html")


@app.route("/search", methods=["GET"])
def search():
    return render_template("search.html", error=None)


@app.route("/search", methods=["POST"])
def search_post():
    member_id = (request.form.get("member_number") or "").strip()

    # Reproducible session-timeout interstitial: fire once per session when armed.
    if _inject_timeout() and not session.get("timeout_cleared"):
        session["pending_member"] = member_id
        return render_template("timeout.html")

    return _resolve(member_id)


@app.route("/continue", methods=["POST", "GET"])
def continue_session():
    # Operator/automation clears the interstitial; we resume the original search.
    session["timeout_cleared"] = True
    member_id = session.pop("pending_member", "")
    return _resolve(member_id)


def _resolve(member_id: str):
    # Validation: member numbers are exactly 5 digits.
    if not (len(member_id) == 5 and member_id.isdigit()):
        return render_template("validation_error.html", value=member_id)

    member = MEMBERS.get(member_id)
    if member is None:
        return render_template("not_found.html", member_id=member_id)

    return render_template("member_detail.html", member_id=member_id, member=member)


@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("TARGET_APP_PORT", "5000"))
    # threaded so the frameset's parallel frame requests don't deadlock the dev server
    app.run(host="127.0.0.1", port=port, threaded=True)
