"""Generate the five banks' capability artifacts from their tenant config.

Hand-authoring five near-identical ~200-line JSON files is error-prone; this keeps
them consistent and reproducible. Each bank gets:
  * <bank>_member_lookup.json  — the full runtime-condition state set
  * <bank>_close_account.json  — where the bank has the closure flow
  * <bank>_send_wire.json      — where the bank has the wire flow

Run from the repo root:  python scripts/build_bank_artifacts.py
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.artifact import store  # noqa: E402
from src.artifact.schema import (  # noqa: E402
    Action, AppRef, Artifact, Capability, Expect, InputSpec, OutputSpec, Provenance,
    Recovery, ScreenState, Step, Target, TextAnchor, TextMatcher,
)
from test_sites import data  # noqa: E402

BANKS = ["firstcoastal", "pioneer", "harbor", "cascade", "unionsquare"]
ENTRY = "http://127.0.0.1:5055/{bank}/"

_LOOKUP_OUTCOMES = ["member_detail", "no_member_found", "validation_error",
                    "permission_denied", "arrears", "compliance_hold", "app_error"]


def _m(text: str, fuzzy: float = 0.85) -> TextMatcher:
    return TextMatcher(text=text, fuzzy_min=fuzzy)


def _states(t: dict) -> dict[str, ScreenState]:
    lab = t["labels"]
    return {
        "app_ready": ScreenState(all_of=[_m(t["product"])], state_class="precondition"),
        # The search page is identified by its submit button: unique to that page,
        # larger/bolder than the field label, and therefore far less prone to OCR
        # word-drop than a multi-word label like "Member Number".
        "search_form": ScreenState(all_of=[_m(lab["button"])], state_class="progress"),
        "member_detail": ScreenState(all_of=[_m(lab["detail_title"])], state_class="progress"),
        "no_member_found": ScreenState(all_of=[_m("No member found")],
                                       state_class="business_outcome", outcome_code="MEMBER_NOT_FOUND"),
        "validation_error": ScreenState(all_of=[_m("Invalid member number")],
                                        state_class="business_outcome", outcome_code="INVALID_INPUT"),
        "permission_denied": ScreenState(all_of=[_m("Access denied")],
                                         state_class="business_outcome", outcome_code="ACCESS_DENIED"),
        "arrears": ScreenState(all_of=[_m("Account in arrears")],
                               state_class="business_outcome", outcome_code="ACCOUNT_IN_ARREARS"),
        "app_error": ScreenState(all_of=[_m("System error")],
                                 state_class="failure", error_code="APP_ERROR_500"),
        "compliance_hold": ScreenState(all_of=[_m("Compliance hold")],
                                       state_class="failure", error_code="COMPLIANCE_HOLD"),
        "slow_load": ScreenState(
            all_of=[_m("Processing request")], state_class="recoverable",
            recovery=Recovery(kind="wait", ms=1500, max_attempts=4, then="retry_step")),
        "session_timeout": ScreenState(
            all_of=[_m("Session expired")], state_class="recoverable",
            recovery=Recovery(kind="click", target=Target(text_anchor=TextAnchor(text="Continue")),
                              max_attempts=1, then="retry_step")),
    }


def _open_steps(t: dict):
    lab = t["labels"]
    return [
        Step(id="open_search", action=Action(kind="click"),
             target=Target(text_anchor=TextAnchor(text=lab["nav_name"], role_hint="link")),
             expect=Expect(any_of=["search_form"], timeout_ms=8000)),
        Step(id="enter_id", action=Action(kind="type", value="{member_id}"),
             target=Target(text_anchor=TextAnchor(text=lab["member"], relation="right_of", max_px=300)),
             expect=Expect(any_of=["search_form"], timeout_ms=5000)),
        Step(id="submit", action=Action(kind="click"),
             target=Target(text_anchor=TextAnchor(text=lab["button"], role_hint="button")),
             expect=Expect(any_of=_LOOKUP_OUTCOMES, timeout_ms=10000)),
    ]


def _read_step(step_id: str, label: str, out: str) -> Step:
    return Step(id=step_id, action=Action(kind="read"),
                target=Target(text_anchor=TextAnchor(text=label, relation="right_of", max_px=500)),
                expect=Expect(any_of=["member_detail"], timeout_ms=4000), extract_as=out)


def _cap(t: dict, cap_id: str, description: str, inputs: dict, outputs: dict,
         steps: list[Step], states: dict, flow: str | None = None) -> Artifact:
    return Artifact(
        capability=Capability(
            id=cap_id, version="1.0.0", status="approved", description=description,
            app=AppRef(id=t["app_id"], entry=ENTRY.format(bank=cap_id.split("_")[0]), viewport=(1280, 800)),
            inputs=inputs, outputs=outputs),
        steps=steps, screen_states=states,
        provenance=Provenance(discovered_at="hand-authored", model="none",
                              platform="cross-platform", surface="cdp",
                              discovery_run="n/a — generated from tenant config"),
    )


def _lookup(bank: str) -> Artifact:
    t = data.TENANTS[bank]
    lab = t["labels"]
    steps = _open_steps(t) + [
        _read_step("read_name", lab["name"], "member_name"),
        _read_step("read_status", lab["status"], "account_status"),
        _read_step("read_savings", lab["savings"], "savings_balance"),
        _read_step("read_checking", lab["checking"], "checking_balance"),
    ]
    outputs = {n: OutputSpec(type="string", extract=f"step:{s}",
                             description=lab[k])
               for n, s, k in (("member_name", "read_name", "name"),
                               ("account_status", "read_status", "status"),
                               ("savings_balance", "read_savings", "savings"),
                               ("checking_balance", "read_checking", "checking"))}
    inputs = {"member_id": InputSpec(type="string", pattern="^[0-9]{5}$",
                                     description="5-digit member id")}
    return _cap(t, f"{bank}_member_lookup",
                f"Look up a member at {t['institution']} and read name, status, savings and checking balances.",
                inputs, outputs, steps, _states(t))


def _closure(bank: str) -> Artifact:
    t = data.TENANTS[bank]
    lab = t["labels"]
    states = _states(t)
    states["confirm_closure"] = ScreenState(all_of=[_m("Confirm account closure")], state_class="progress")
    states["account_closed"] = ScreenState(all_of=[_m("Account closed")], state_class="progress")
    steps = _open_steps(t) + [
        Step(id="start_closure", action=Action(kind="click"),
             target=Target(text_anchor=TextAnchor(text="Close Account", role_hint="button")),
             expect=Expect(any_of=["confirm_closure"], timeout_ms=8000)),
        Step(id="confirm_closure", action=Action(kind="click"),
             target=Target(text_anchor=TextAnchor(text="Confirm Close", role_hint="button")),
             expect=Expect(any_of=["account_closed"], timeout_ms=8000)),
        Step(id="read_reference", action=Action(kind="read"),
             target=Target(text_anchor=TextAnchor(text="Confirmation reference", relation="right_of",
                                                   max_px=500, fuzzy_min=0.80)),
             expect=Expect(any_of=["account_closed"], timeout_ms=4000), extract_as="closure_reference"),
    ]
    outputs = {"closure_reference": OutputSpec(type="string", extract="step:read_reference",
                                               description="Closure confirmation reference")}
    inputs = {"member_id": InputSpec(type="string", pattern="^[0-9]{5}$", description="5-digit member id")}
    return _cap(t, f"{bank}_close_account",
                f"Look up a member at {t['institution']}, start closure and clear the confirmation interstitial.",
                inputs, outputs, steps, states)


def _wire(bank: str) -> Artifact:
    t = data.TENANTS[bank]
    lab = t["labels"]
    states = _states(t)
    states["wire_form"] = ScreenState(all_of=[_m("Wire transfer request")], state_class="progress")
    states["wire_review"] = ScreenState(all_of=[_m("Wire review")], state_class="progress")
    states["wire_done"] = ScreenState(all_of=[_m("Wire sent")], state_class="progress")
    steps = _open_steps(t) + [
        Step(id="start_wire", action=Action(kind="click"),
             target=Target(text_anchor=TextAnchor(text="Send Wire", role_hint="button")),
             expect=Expect(any_of=["wire_form"], timeout_ms=8000)),
        Step(id="enter_beneficiary", action=Action(kind="type", value="{beneficiary}"),
             target=Target(text_anchor=TextAnchor(text="Beneficiary", relation="right_of", max_px=300)),
             expect=Expect(any_of=["wire_form"], timeout_ms=5000)),
        Step(id="enter_amount", action=Action(kind="type", value="{amount}"),
             target=Target(text_anchor=TextAnchor(text="Amount", relation="right_of", max_px=300)),
             expect=Expect(any_of=["wire_form"], timeout_ms=5000)),
        Step(id="review_wire", action=Action(kind="click"),
             target=Target(text_anchor=TextAnchor(text="Review Wire", role_hint="button")),
             expect=Expect(any_of=["wire_review"], timeout_ms=8000)),
        Step(id="confirm_wire", action=Action(kind="click"),
             target=Target(text_anchor=TextAnchor(text="Confirm Wire", role_hint="button")),
             expect=Expect(any_of=["wire_done"], timeout_ms=8000)),
        Step(id="read_reference", action=Action(kind="read"),
             target=Target(text_anchor=TextAnchor(text="Confirmation reference", relation="right_of",
                                                   max_px=500, fuzzy_min=0.80)),
             expect=Expect(any_of=["wire_done"], timeout_ms=4000), extract_as="wire_reference"),
    ]
    outputs = {"wire_reference": OutputSpec(type="string", extract="step:read_reference",
                                            description="Wire confirmation reference")}
    inputs = {
        "member_id": InputSpec(type="string", pattern="^[0-9]{5}$", description="5-digit member id"),
        "beneficiary": InputSpec(type="string", pattern="^.{1,40}$", description="Beneficiary name"),
        "amount": InputSpec(type="string", pattern=r"^\$?[0-9][0-9,]*(\.[0-9]{2})?$",
                            description="Wire amount"),
    }
    return _cap(t, f"{bank}_send_wire",
                f"Look up a member at {t['institution']} and send a wire through the review/confirm flow.",
                inputs, outputs, steps, states)


def main() -> None:
    out_dir = ROOT / "artifacts"
    for bank in BANKS:
        flow = data.TENANTS[bank].get("special_flow")
        artifacts = [_lookup(bank)]
        if flow == "closure":
            artifacts.append(_closure(bank))
        elif flow == "wire":
            artifacts.append(_wire(bank))
        for a in artifacts:
            path = out_dir / f"{a.capability.id}.json"
            store.save(a, path)
            print(f"wrote {path.relative_to(ROOT)}  ({len(a.steps)} steps, {len(a.screen_states)} states)")


if __name__ == "__main__":
    main()
