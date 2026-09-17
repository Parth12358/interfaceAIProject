"""Generic bank tenant builder — one code path, five visually distinct banks.

Branding, label vocabulary, layout style (`legacy` | `dense` | `terminal` |
`modern`) and the optional risky action (`closure` | `wire`) all come from
`data.TENANTS`. The goal is heterogeneity: the same runtime conditions on
surfaces that look and read differently, not five reskins.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from .. import data

# Each bank gets its own layout so the sites read as genuinely different products
# (a classic teller frameset, a dense commercial suite, a 3270 terminal, a modern
# digital bank, and an enterprise ledger) rather than shared reskins.
_BASE_BY_TENANT = {
    "firstcoastal": "bank/base_firstcoastal.html",
    "pioneer": "bank/base_pioneer.html",
    "harbor": "bank/base_harbor.html",
    "cascade": "bank/base_cascade.html",
    "unionsquare": "bank/base_unionsquare.html",
}


def build_bp(bp_name: str, tenant_name: str) -> Blueprint:
    t = data.TENANTS[tenant_name]
    labels = t["labels"]
    frameset = bool(t["frameset"])
    flow = t.get("special_flow")
    base = _BASE_BY_TENANT.get(tenant_name, f"bank/base_{t['style']}.html")
    bp = Blueprint(bp_name, __name__)

    def page(template: str, **kw):
        return render_template(
            template, tenant=t, theme=t["theme"], labels=labels, base=base,
            is_frame=frameset, title_bar=kw.pop("title_bar", t["product"]), **kw)

    def k(suffix: str) -> str:
        return f"{bp_name}__{suffix}"

    # --- entry / shell --------------------------------------------------------
    @bp.get("/")
    def index():
        if request.args.get("arm") == "timeout":
            session[k("arm_timeout")] = True
        if frameset:
            return render_template("bank/frameset.html", tenant=t, theme=t["theme"])
        return page("bank/welcome.html", title_bar="Welcome")

    @bp.get("/nav")
    def nav():
        return render_template("bank/nav.html", tenant=t, theme=t["theme"])

    @bp.get("/welcome")
    def welcome():
        return page("bank/welcome.html", title_bar="Welcome")

    # --- lookup ---------------------------------------------------------------
    @bp.get("/search")
    def search():
        return page("bank/search.html", title_bar=labels["search_title"])

    @bp.post("/search")
    def search_post():
        member_id = (request.form.get("member_key") or "").strip()
        if session.pop(k("arm_timeout"), False) and not session.get(k("timeout_done")):
            session[k("timeout_done")] = True
            session[k("pending")] = member_id
            return page("bank/timeout.html", title_bar="Session Notice")
        return _resolve(member_id)

    @bp.route("/continue", methods=["GET", "POST"])
    def continue_session():
        return _resolve(session.pop(k("pending"), ""))

    @bp.get("/slow_resolve")
    def slow_resolve():
        return _resolve(request.args.get("member_key", ""), skip_slow=True)

    def _resolve(member_id: str, skip_slow: bool = False):
        r = data.resolve(tenant_name, member_id, skip_slow=skip_slow)
        kind = r["kind"]
        if kind == "validation":
            return page("bank/validation.html", title_bar="Search Result", value=r["member_id"])
        if kind == "outage":
            return page("bank/error.html", title_bar="System Notice", error_code="E-503-UPSTREAM")
        if kind == "compliance":
            return page("bank/compliance.html", title_bar="Compliance Notice")
        if kind == "slow" and not skip_slow:
            return page("bank/slow.html", title_bar="Please Wait", member_id=r["member_id"])
        if kind == "not_found":
            return page("bank/not_found.html", title_bar="Search Result", member_id=r["member_id"])
        if kind == "restricted":
            return page("bank/permission.html", title_bar="Access Denied", member_id=r["member_id"])
        if kind == "arrears":
            return page("bank/arrears.html", title_bar="Account Alert",
                        member_id=r["member_id"], member=r["member"])
        session[k("member")] = r["member_id"]
        return page("bank/detail.html", title_bar=labels["detail_title"],
                    member_id=r["member_id"], member=r["member"])

    # --- optional risky flows -------------------------------------------------
    if flow == "closure":
        @bp.post("/close")
        def close():
            member_id = (request.form.get("member_key") or "").strip()
            return page("bank/confirm_close.html", title_bar="Closure Review", member_id=member_id)

        @bp.post("/close_final")
        def close_final():
            member_id = (request.form.get("member_key") or "").strip()
            return page("bank/closed.html", title_bar="Account Closed", member_id=member_id,
                        reference="CLS-" + (member_id or "00000") + "-A")

    if flow == "wire":
        @bp.post("/wire")
        def wire():
            member_id = (request.form.get("member_key") or "").strip()
            return page("bank/wire_form.html", title_bar="Wire Transfer", member_id=member_id,
                        values={"beneficiary": "", "amount": ""}, errors=[])

        @bp.post("/wire_submit")
        def wire_submit():
            member_id = (request.form.get("member_key") or "").strip()
            values = {"beneficiary": (request.form.get("beneficiary") or "").strip(),
                      "amount": (request.form.get("amount") or "").strip()}
            errors = [msg for ok, msg in (
                (bool(values["beneficiary"]), "Beneficiary is required."),
                (_positive(values["amount"]), "Amount must be a positive number."),
            ) if not ok]
            if errors:
                return page("bank/wire_form.html", title_bar="Wire Transfer",
                            member_id=member_id, values=values, errors=errors)
            return page("bank/wire_confirm.html", title_bar="Wire Review",
                        member_id=member_id, values=values)

        @bp.post("/wire_confirm")
        def wire_confirm():
            member_id = (request.form.get("member_key") or "").strip()
            amount = (request.form.get("amount") or "").strip()
            return page("bank/wire_done.html", title_bar="Wire Sent", member_id=member_id,
                        amount=amount, reference="WR-" + (member_id or "00000") + "-9")

    # --- control --------------------------------------------------------------
    @bp.get("/__reset")
    def reset():
        for key in list(session.keys()):
            if key.startswith(bp_name):
                session.pop(key, None)
        return redirect(url_for(f"{bp_name}.index"))

    return bp


def _positive(value: str) -> bool:
    try:
        return float(value.replace("$", "").replace(",", "")) > 0
    except (TypeError, ValueError):
        return False
