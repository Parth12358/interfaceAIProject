"""NovaBank — a modern (but still no-test-ID) relationship-banking web app.

The distinguishing flow is the assignment's multi-field-form example: look up a
member, then open a new sub-account through a multi-field form with a review and
confirmation step. It shares the same runtime-condition vocabulary as VaultCore
(validation, not found, permission, timeout, slow, outage, compliance) but is
rendered with a modern card layout and a different visual language.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from .. import data

_ACTIONS = {"click", "type", "read", "key", "wait"}


def build_bp(bp_name: str, tenant_name: str) -> Blueprint:
    t = data.TENANTS[tenant_name]
    products = t["products"]
    bp = Blueprint(bp_name, __name__)

    def page(template: str, **kw):
        return render_template(template, tenant=t, theme=t["theme"], **kw)

    @bp.get("/")
    def index():
        if request.args.get("arm") == "timeout":
            session[f"{bp_name}__arm_timeout"] = True
        return page("novabank/welcome.html")

    # --- lookup ---------------------------------------------------------------
    @bp.get("/search")
    def search():
        return page("novabank/search.html", error=None)

    @bp.post("/search")
    def search_post():
        member_id = (request.form.get("member_id") or "").strip()
        if session.pop(f"{bp_name}__arm_timeout", False) and not session.get(f"{bp_name}__timeout_done"):
            session[f"{bp_name}__timeout_done"] = True
            session[f"{bp_name}__pending"] = member_id
            return page("novabank/timeout.html")
        return _resolve(member_id)

    @bp.route("/continue", methods=["GET", "POST"])
    def continue_session():
        return _resolve(session.pop(f"{bp_name}__pending", ""))

    @bp.get("/slow_resolve")
    def slow_resolve():
        return _resolve(request.args.get("member_id", ""), skip_slow=True)

    def _resolve(member_id: str, skip_slow: bool = False):
        r = data.resolve(tenant_name, member_id, skip_slow=skip_slow)
        kind = r["kind"]
        if kind == "validation":
            return page("novabank/validation.html", value=r["member_id"])
        if kind == "outage":
            return page("novabank/error.html", error_code="NOVA-500-UPSTREAM")
        if kind == "compliance":
            return page("novabank/compliance.html")
        if kind == "slow" and not skip_slow:
            return page("novabank/slow.html", member_id=r["member_id"])
        if kind == "not_found":
            return page("novabank/not_found.html", member_id=r["member_id"])
        if kind == "restricted":
            return page("novabank/permission.html", member_id=r["member_id"],
                        reason="Your role cannot view restricted member records.")
        if kind == "arrears":
            return page("novabank/arrears.html", member_id=r["member_id"], member=r["member"])
        if r["member_id"] == data.SPECIAL["not_eligible"]:
            return page("novabank/permission.html", member_id=r["member_id"],
                        reason="This member is not eligible to open additional accounts.")
        session[f"{bp_name}__member"] = r["member_id"]
        return page("novabank/detail.html", member_id=r["member_id"], member=r["member"])

    # --- multi-field sub-account form ----------------------------------------
    @bp.post("/subaccount")
    def subaccount():
        member_id = (request.form.get("member_number") or session.get(f"{bp_name}__member") or "").strip()
        return page("novabank/form.html", member_id=member_id, products=products,
                    values={"product": list(products)[0], "nickname": "", "deposit": "", "agree": False},
                    errors=[])

    @bp.post("/subaccount_submit")
    def subaccount_submit():
        member_id = (request.form.get("member_number") or "").strip()
        values = {
            "product": (request.form.get("product") or "").strip(),
            "nickname": (request.form.get("nickname") or "").strip(),
            "deposit": (request.form.get("deposit") or "").strip(),
            "agree": bool(request.form.get("agree")),
        }
        errors = _validate(values, products)
        if errors:
            return page("novabank/validation_form.html", member_id=member_id,
                        products=products, values=values, errors=errors)
        return page("novabank/review.html", member_id=member_id, values=values,
                    min_deposit=products[values["product"]]["min_deposit"])

    @bp.post("/confirm")
    def confirm():
        member_id = (request.form.get("member_number") or "").strip()
        product = (request.form.get("product") or "Holiday Savings").strip()
        nickname = (request.form.get("nickname") or "").strip()
        deposit = (request.form.get("deposit") or "").strip()
        account_number = "NOVA-" + (member_id or "00000") + "-" + str(abs(hash(nickname)) % 90 + 10)
        return page("novabank/receipt.html", member_id=member_id, product=product,
                    nickname=nickname, deposit=deposit, account_number=account_number)

    @bp.get("/__reset")
    def reset():
        for k in list(session.keys()):
            if k.startswith(bp_name):
                session.pop(k, None)
        return redirect(url_for(f"{bp_name}.index"))

    return bp


def _validate(values: dict, products: dict) -> list[str]:
    errors: list[str] = []
    if values["product"] not in products:
        errors.append("Select an account type.")
    if not values["nickname"]:
        errors.append("Account nickname is required.")
    dep = values["deposit"].replace("$", "").replace(",", "")
    try:
        amount = float(dep)
    except ValueError:
        amount = None
    if amount is None or amount <= 0:
        errors.append("Initial deposit must be a positive amount.")
    elif values["product"] in products and amount < products[values["product"]]["min_deposit"]:
        errors.append(
            f"Initial deposit must be at least ${products[values['product']]['min_deposit']:,} "
            f"for {values['product']}."
        )
    if not values["agree"]:
        errors.append("You must accept the account terms.")
    return errors
