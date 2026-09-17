"""Offline coverage of the multi-tenant banking test sites.

Drives every runtime condition directly through the Flask test client (no browser,
no Chrome), asserting each branch is reachable and emits the vocabulary the
artifacts' `screen_states` key off. The live, browser-driven pass over the same
site matrix lives in scripts/live_site_matrix.py (and tests/test_live_sites.py).
"""
import pytest

from test_sites.serve import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _get(client, path, needle):
    r = client.get(path)
    assert r.status_code == 200, path
    assert needle in r.get_data(as_text=True), f"{needle!r} not in GET {path}"


def _post(client, path, data, needle):
    r = client.post(path, data=data)
    assert r.status_code == 200, path
    assert needle in r.get_data(as_text=True), f"{needle!r} not in POST {path}"


VAULTCORE = ["/meridian", "/summit"]


@pytest.mark.parametrize("base", VAULTCORE)
def test_vaultcore_runtime_conditions(client, base):
    _get(client, f"{base}/", "VaultCore")
    _get(client, f"{base}/nav", "NAVIGATION")
    _post(client, f"{base}/search", {"member_number": "11111"}, "Account Holder")
    _post(client, f"{base}/search", {"member_number": "00000"}, "No member found")
    _post(client, f"{base}/search", {"member_number": "abc"}, "Invalid member number")
    _post(client, f"{base}/search", {"member_number": "33333"}, "Access denied")
    _post(client, f"{base}/search", {"member_number": "55555"}, "Account in arrears")
    _post(client, f"{base}/search", {"member_number": "66666"}, "Compliance hold")
    _post(client, f"{base}/search", {"member_number": "99999"}, "System error")
    _post(client, f"{base}/search", {"member_number": "77777"}, "Processing request")
    _get(client, f"{base}/slow_resolve?member_id=77777", "Account Holder")
    _post(client, f"{base}/close", {"member_number": "11111"}, "Confirm account closure")
    _post(client, f"{base}/close_final", {"member_number": "11111"}, "Account closed")


@pytest.mark.parametrize("base", VAULTCORE)
def test_vaultcore_timeout_interstitial(client, base):
    client.get(f"{base}/?arm=timeout")
    _post(client, f"{base}/search", {"member_number": "11111"}, "Session expired")
    _post(client, f"{base}/continue", {}, "Account Holder")


def test_novabank_runtime_conditions(client):
    _get(client, "/novabank/", "Find a Member")
    _post(client, "/novabank/search", {"member_id": "11111"}, "Member relationship")
    _post(client, "/novabank/search", {"member_id": "00000"}, "No member found")
    _post(client, "/novabank/search", {"member_id": "abc"}, "Invalid member number")
    _post(client, "/novabank/search", {"member_id": "33333"}, "Access denied")
    _post(client, "/novabank/search", {"member_id": "44444"}, "not eligible")
    _post(client, "/novabank/search", {"member_id": "66666"}, "Compliance hold")
    _post(client, "/novabank/search", {"member_id": "99999"}, "System error")
    _post(client, "/novabank/search", {"member_id": "77777"}, "Processing request")
    _get(client, "/novabank/slow_resolve?member_id=77777", "Member relationship")


def test_novabank_multifield_form_review_and_receipt(client):
    _post(client, "/novabank/subaccount", {"member_number": "11111"}, "Account Nickname")
    _post(client, "/novabank/subaccount_submit",
          {"member_number": "11111", "product": "High-Yield Savings",
           "nickname": "Vacation", "deposit": "600", "agree": "on"}, "Account review")
    _post(client, "/novabank/subaccount_submit",
          {"member_number": "11111", "product": "Money Market", "nickname": "", "deposit": "10"},
          "Please correct the following")
    _post(client, "/novabank/confirm",
          {"member_number": "11111", "product": "High-Yield Savings",
           "nickname": "Vacation", "deposit": "600"}, "New Account Number")


def test_novabank_timeout_interstitial(client):
    client.get("/novabank/?arm=timeout")
    _post(client, "/novabank/search", {"member_id": "11111"}, "Session expired")
    _post(client, "/novabank/continue", {}, "Member relationship")


# --- the five-bank suite (generic `bank` builder) ----------------------------
from test_sites import data  # noqa: E402

BANKS = ["firstcoastal", "pioneer", "harbor", "cascade", "unionsquare"]


@pytest.mark.parametrize("bank", BANKS)
def test_five_banks_reach_every_runtime_condition(client, bank):
    t = data.TENANTS[bank]
    lab = t["labels"]
    _get(client, f"/{bank}/", t["product"])
    _get(client, f"/{bank}/welcome", lab["prompt"])
    _post(client, f"/{bank}/search", {"member_key": "11111"}, lab["detail_title"])
    _post(client, f"/{bank}/search", {"member_key": "00000"}, "No member found")
    _post(client, f"/{bank}/search", {"member_key": "abc"}, "Invalid member number")
    _post(client, f"/{bank}/search", {"member_key": "33333"}, "Access denied")
    _post(client, f"/{bank}/search", {"member_key": "55555"}, "Account in arrears")
    _post(client, f"/{bank}/search", {"member_key": "66666"}, "Compliance hold")
    _post(client, f"/{bank}/search", {"member_key": "99999"}, "System error")
    _post(client, f"/{bank}/search", {"member_key": "77777"}, "Processing request")
    _get(client, f"/{bank}/slow_resolve?member_key=77777", lab["detail_title"])
    client.get(f"/{bank}/?arm=timeout")
    _post(client, f"/{bank}/search", {"member_key": "11111"}, "Session expired")
    _post(client, f"/{bank}/continue", {}, lab["detail_title"])


@pytest.mark.parametrize("bank", ["firstcoastal", "pioneer"])
def test_bank_closure_flow(client, bank):
    _post(client, f"/{bank}/close", {"member_key": "11111"}, "Confirm account closure")
    _post(client, f"/{bank}/close_final", {"member_key": "11111"}, "Account closed")


@pytest.mark.parametrize("bank", ["harbor", "unionsquare"])
def test_bank_wire_flow(client, bank):
    _post(client, f"/{bank}/wire", {"member_key": "11111"}, "Wire transfer request")
    _post(client, f"/{bank}/wire_submit",
          {"member_key": "11111", "beneficiary": "Acme Ltd", "amount": "1500"}, "Wire review")
    _post(client, f"/{bank}/wire_submit",
          {"member_key": "11111", "beneficiary": "", "amount": "-1"}, "Please correct the following")
    _post(client, f"/{bank}/wire_confirm", {"member_key": "11111", "amount": "1500"}, "Wire sent")
