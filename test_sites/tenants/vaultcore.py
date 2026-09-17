"""VaultCore — the shared legacy "vendor product" served for two institutions.

`build_bp` is called once per tenant, so the exact same server-rendered code runs
for Meridian Trust (frameset shell) and Summit Credit Union (single page). The
institution is only branding; the anchor vocabulary the automation relies on
("VaultCore", "Member Lookup", "Member Number", "Find", "Member Profile",
"Savings Balance", "Member Name") is shared — which is what makes one artifact
reusable across the two tenants.

Runtime conditions are reached by member id (see data.SPECIAL) plus one session
flag (`?arm=timeout`) so the assignment's exceptional states are reproducible.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from .. import data


def _ctx(t: dict, **kw) -> dict:
    return {"tenant": t, "theme": t["theme"], **kw}


def _arms(bp_name: str) -> str:
    return f"{bp_name}__arm_timeout"


def _pending(bp_name: str) -> str:
    return f"{bp_name}__pending"


def _timeout_done(bp_name: str) -> str:
    return f"{bp_name}__timeout_done"


def build_bp(bp_name: str, tenant_name: str) -> Blueprint:
    t = data.TENANTS[tenant_name]
    frameset = bool(t["frameset"])
    bp = Blueprint(bp_name, __name__)

    def page(template: str, **kw):
        # Content pages render inside a frame for the frameset tenant, else as a
        # full page with inline masthead + nav. Same markup either way.
        return render_template(template, **_ctx(t, is_frame=frameset, **kw))

    # --- shell / entry --------------------------------------------------------
    @bp.get("/")
    def index():
        if request.args.get("arm") == "timeout":
            session[_arms(bp_name)] = True
        if frameset:
            return render_template("vaultcore/frameset.html", **_ctx(t))
        return page("vaultcore/welcome.html", title_bar="Servicing Console")

    @bp.get("/nav")
    def nav():
        return render_template("vaultcore/nav.html", **_ctx(t))

    @bp.get("/welcome")
    def welcome():
        return page("vaultcore/welcome.html", title_bar="Servicing Console")

    # --- member lookup --------------------------------------------------------
    @bp.get("/search")
    def search():
        return page("vaultcore/search.html", title_bar="Member Search", error=None)

    @bp.post("/search")
    def search_post():
        member_id = (request.form.get("member_number") or "").strip()
        if session.pop(_arms(bp_name), False) and not session.get(_timeout_done(bp_name)):
            session[_timeout_done(bp_name)] = True
            session[_pending(bp_name)] = member_id
            return page("vaultcore/timeout.html", title_bar="Session Notice")
        return _resolve(member_id)

    @bp.route("/continue", methods=["GET", "POST"])
    def continue_session():
        member_id = session.pop(_pending(bp_name), "")
        return _resolve(member_id)

    @bp.get("/slow_resolve")
    def slow_resolve():
        return _resolve(request.args.get("member_id", ""), skip_slow=True)

    def _resolve(member_id: str, skip_slow: bool = False):
        r = data.resolve(tenant_name, member_id, skip_slow=skip_slow)
        kind = r["kind"]
        if kind == "validation":
            return page("vaultcore/validation.html", title_bar="Search Result", value=r["member_id"])
        if kind == "outage":
            return page("vaultcore/error.html", title_bar="System Notice",
                        error_code="E-BATCH-503")
        if kind == "compliance":
            # Full-page notice with no product masthead -> unrecognized screen.
            return render_template("vaultcore/compliance.html", **_ctx(t))
        if kind == "slow" and not skip_slow:
            return page("vaultcore/slow.html", title_bar="Please Wait",
                        member_id=r["member_id"])
        if kind == "not_found":
            return page("vaultcore/not_found.html", title_bar="Search Result", member_id=r["member_id"])
        if kind == "restricted":
            return page("vaultcore/permission.html", title_bar="Access Denied", member_id=r["member_id"])
        if kind == "arrears":
            return page("vaultcore/arrears.html", title_bar="Account Alert",
                        member_id=r["member_id"], member=r["member"])
        member = r["member"]
        return page("vaultcore/detail.html", title_bar="Member Profile",
                    member_id=r["member_id"], member=member)

    # --- risky action: close account (confirmation interstitial) --------------
    @bp.post("/close")
    def close():
        member_id = (request.form.get("member_number") or "").strip()
        return page("vaultcore/confirm_close.html", title_bar="Closure Review",
                    member_id=member_id)

    @bp.post("/close_final")
    def close_final():
        member_id = (request.form.get("member_number") or "").strip()
        return page("vaultcore/closed.html", title_bar="Account Closed",
                    member_id=member_id, reference="CLS-" + (member_id or "00000") + "-A")

    # --- control --------------------------------------------------------------
    @bp.get("/__reset")
    def reset():
        for k in (_arms(bp_name), _pending(bp_name), _timeout_done(bp_name)):
            session.pop(k, None)
        return redirect(url_for(f"{bp_name}.index"))

    return bp
