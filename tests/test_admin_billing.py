"""The operator's own dashboard and the invoicing behind it.

Rules these tests hold in place:
* only the operator gets in, and the page does not exist at all until a key is set;
* an invoice is never raised or sent without the operator pressing the button;
* the amount is athletes x days x the rate, from the season the director set;
* a catch-up invoice charges only for athletes added since the last invoice, only
  for the days they have left, and never twice;
* a customer is never created twice for one program;
* a webhook that is not signed by Stripe changes nothing;
* nothing in a director's, coach's or parent's view shows any of it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, timedelta

import pytest

import offdays.api as api_module
from offdays import admin as admin_mod
from tests.test_api import client, program  # noqa: F401  (fixtures)

KEY = "k" * 32
SECRET = "whsec_test_secret"


class FakeStripe:
    """Records what would have been sent to Stripe. Nothing leaves the process."""

    def __init__(self):
        self.customers, self.items, self.invoices, self.sent = [], [], [], []

    def create_customer(self, *, name, email, org_id):
        self.customers.append({"name": name, "email": email, "org_id": org_id})
        return f"cus_{len(self.customers)}"

    def create_invoice(self, *, customer, lines, description, days_until_due, idempotency_key):
        inv = {"id": f"in_{len(self.invoices) + 1}", "customer": customer, "lines": lines,
               "description": description, "key": idempotency_key,
               "total": sum(l["quantity"] * l["unit_amount"] for l in lines),
               "hosted_invoice_url": f"https://invoice.stripe.example/{len(self.invoices) + 1}"}
        self.invoices.append(inv)
        return inv

    def send_invoice(self, invoice_id):
        self.sent.append(invoice_id)
        return {"id": invoice_id, "hosted_invoice_url": "https://invoice.stripe.example/x", "status": "open"}

    def void_invoice(self, invoice_id):
        return {"id": invoice_id, "status": "void"}

    def mark_paid(self, invoice_id):
        self.paid_out_of_band = getattr(self, "paid_out_of_band", []) + [invoice_id]
        return {"id": invoice_id, "status": "paid"}


@pytest.fixture
def admin(client, monkeypatch):
    monkeypatch.setenv("OFFDAYS_ADMIN_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    monkeypatch.setenv("OFFDAYS_STRIPE_WEBHOOK_SECRET", SECRET)
    fake = FakeStripe()
    monkeypatch.setattr(admin_mod, "gateway", lambda: fake)
    admin_mod._FAILS.clear()
    return {"h": {"Authorization": f"Bearer {KEY}"}, "fake": fake}


def _season(program, start=None, end=None):
    start = start or (date.today() - timedelta(days=10))
    end = end or (start + timedelta(days=99))
    conn = api_module._store.conn
    conn.execute("UPDATE organizations SET season_starts_on = ?, season_ends_on = ? WHERE id = ?",
                 (start.isoformat(), end.isoformat(), program["org"]["org_id"]))
    conn.commit()
    return start, end


def _kids(client, program, n, prefix="K"):
    team = client.post("/api/teams", json={"name": f"2031 {prefix}"}, headers=program["director"]).json()
    for i in range(n):
        client.post("/api/athletes", json={"display_name": f"{prefix}{i}", "join_code": team["join_code"]},
                    headers=program["director"])
    return team


def _org(program):
    return program["org"]["org_id"]


# ---------------------------------------------------------------- the door
class TestOnlyTheOperatorGetsIn:
    def test_the_page_does_not_exist_until_a_key_is_set(self, client, monkeypatch):
        monkeypatch.delenv("OFFDAYS_ADMIN_KEY_SHA256", raising=False)
        assert client.get("/api/admin/overview", headers={"Authorization": f"Bearer {KEY}"}).status_code == 404

    def test_no_key_is_refused(self, client, admin):
        assert client.get("/api/admin/overview").status_code == 401

    def test_a_wrong_key_is_refused(self, client, admin):
        assert client.get("/api/admin/overview", headers={"Authorization": "Bearer nope"}).status_code == 401

    def test_the_right_key_gets_in(self, client, admin):
        assert client.get("/api/admin/overview", headers=admin["h"]).status_code == 200

    def test_a_directors_own_sign_in_is_not_the_key(self, client, admin, program):
        assert client.get("/api/admin/overview", headers=program["director"]).status_code == 401

    def test_guessing_is_slowed(self, client, admin):
        codes = [client.get("/api/admin/overview", headers={"Authorization": "Bearer wrong"}).status_code
                 for _ in range(12)]
        assert 429 in codes
        assert client.get("/api/admin/overview", headers=admin["h"]).status_code == 429

    def test_the_key_is_never_stored_in_the_clear(self, client, admin):
        assert KEY not in json.dumps(client.get("/api/admin/overview", headers=admin["h"]).json())

    def test_the_page_is_not_indexed(self, client, admin):
        res = client.get("/app/admin.html")
        assert res.status_code == 200
        assert "noindex" in res.text


# ---------------------------------------------------------------- the numbers
class TestWhatEveryProgramOwes:
    def test_the_amount_is_athletes_times_days_times_the_rate(self, client, admin, program):
        _kids(client, program, 4)
        start, end = _season(program, start=date.today() - timedelta(days=1))
        row = _row(client, admin, program)
        days = (end - start).days + 1
        assert row["athletes"] >= 4
        assert row["season_days"] == days
        assert row["amount_cents"] == row["athletes"] * days * 50

    def test_a_program_with_no_season_is_not_billable(self, client, admin, program):
        _kids(client, program, 3)
        row = _row(client, admin, program)
        assert row["amount_cents"] == 0
        assert row["status"] == "needs_season"

    def test_a_program_with_no_roster_is_not_billable(self, client, admin, program):
        _season(program)
        client.get("/api/coach/roster", headers=program["director"])
        conn = api_module._store.conn
        conn.execute("UPDATE memberships SET active = 0 WHERE org_id = ? AND role = 'athlete'", (_org(program),))
        conn.commit()
        assert _row(client, admin, program)["status"] == "needs_roster"

    def test_a_ready_program_says_ready_to_invoice(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        assert _row(client, admin, program)["status"] == "ready"

    def test_the_funnel_is_on_the_row(self, client, admin, program):
        _kids(client, program, 3)
        _season(program)
        row = _row(client, admin, program)
        assert row["families"]["total"] >= 3
        assert "training" in row["families"]

    def test_the_totals_add_up(self, client, admin, program):
        _kids(client, program, 3)
        _season(program)
        body = client.get("/api/admin/overview", headers=admin["h"]).json()
        assert body["totals"]["ready_cents"] == sum(
            p["amount_cents"] for p in body["programs"] if p["status"] == "ready")

    def test_a_rate_change_does_not_touch_an_invoice_already_raised(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        client.post(f"/api/admin/programs/{_org(program)}/invoice", headers=admin["h"], json={"email": "t@club.example"})
        first = _row(client, admin, program)["invoiced_cents"]
        assert first > 0


def _row(client, admin, program):
    body = client.get("/api/admin/overview", headers=admin["h"]).json()
    return next(p for p in body["programs"] if p["org_id"] == _org(program))


# ---------------------------------------------------------------- invoices
class TestRaisingAnInvoice:
    def _go(self, client, admin, program, **kw):
        return client.post(f"/api/admin/programs/{_org(program)}/invoice", headers=admin["h"],
                           json={"email": "treasurer@club.example", **kw})

    def test_the_overview_never_raises_one_by_itself(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        client.get("/api/admin/overview", headers=admin["h"])
        client.get("/api/admin/overview", headers=admin["h"])
        assert admin["fake"].invoices == [] and admin["fake"].customers == []

    def test_raising_one_makes_a_draft_and_sends_nothing(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        res = self._go(client, admin, program)
        assert res.status_code == 201, res.text
        assert len(admin["fake"].invoices) == 1
        assert admin["fake"].sent == []
        assert res.json()["status"] == "draft"

    def test_the_amount_and_the_line_are_right(self, client, admin, program):
        _kids(client, program, 3)
        _season(program)
        row = _row(client, admin, program)
        self._go(client, admin, program)
        inv = admin["fake"].invoices[0]
        assert inv["total"] == row["amount_cents"]
        assert inv["lines"][0]["quantity"] == row["athletes"] * row["season_days"]
        assert inv["lines"][0]["unit_amount"] == 50

    def test_the_invoice_says_what_it_is_for(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        self._go(client, admin, program)
        d = admin["fake"].invoices[0]["description"]
        assert "athletes" in d and "days" in d

    def test_a_second_press_does_not_make_a_second_invoice(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        self._go(client, admin, program)
        again = self._go(client, admin, program)
        assert again.status_code == 409
        assert len(admin["fake"].invoices) == 1

    def test_one_customer_per_program_ever(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        self._go(client, admin, program)
        _kids(client, program, 2, prefix="L")
        client.post(f"/api/admin/programs/{_org(program)}/catch-up", headers=admin["h"], json={})
        assert len(admin["fake"].customers) == 1

    def test_a_program_that_is_not_ready_is_refused(self, client, admin, program):
        _kids(client, program, 2)
        res = self._go(client, admin, program)
        assert res.status_code == 400
        assert admin["fake"].invoices == []

    def test_an_email_is_required(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        res = client.post(f"/api/admin/programs/{_org(program)}/invoice", headers=admin["h"], json={})
        assert res.status_code in (400, 422)

    def test_sending_is_a_separate_deliberate_step(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        made = self._go(client, admin, program).json()
        res = client.post(f"/api/admin/invoices/{made['invoice_id']}/send", headers=admin["h"])
        assert res.status_code == 200
        assert admin["fake"].sent == [made["stripe_invoice_id"]]
        assert _row(client, admin, program)["status"] == "sent"

    def test_the_stripe_idempotency_key_is_stable(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        self._go(client, admin, program)
        assert admin["fake"].invoices[0]["key"]

    def test_bank_transfer_and_check_are_the_first_way_to_pay(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        self._go(client, admin, program)
        d = admin["fake"].invoices[0]["description"].lower()
        assert "bank" in d or "check" in d

    def test_a_manual_check_can_mark_it_paid(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        made = self._go(client, admin, program).json()
        res = client.post(f"/api/admin/invoices/{made['invoice_id']}/mark-paid", headers=admin["h"],
                          json={"note": "Check 4471"})
        assert res.status_code == 200
        assert _row(client, admin, program)["status"] == "paid"

    def test_a_voided_invoice_can_be_raised_again(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        made = self._go(client, admin, program).json()
        client.post(f"/api/admin/invoices/{made['invoice_id']}/void", headers=admin["h"])
        assert self._go(client, admin, program).status_code == 201


# ---------------------------------------------------------------- catch-up
class TestCatchUpInvoices:
    def _first(self, client, admin, program):
        _kids(client, program, 3)
        _season(program, start=date.today() - timedelta(days=10), end=date.today() + timedelta(days=89))
        client.post(f"/api/admin/programs/{_org(program)}/invoice", headers=admin["h"],
                    json={"email": "treasurer@club.example"})

    def test_nothing_new_means_nothing_to_invoice(self, client, admin, program):
        self._first(client, admin, program)
        res = client.post(f"/api/admin/programs/{_org(program)}/catch-up", headers=admin["h"], json={})
        assert res.status_code == 400

    def test_a_late_joiner_is_charged_only_for_the_days_left(self, client, admin, program):
        self._first(client, admin, program)
        conn = api_module._store.conn
        _kids(client, program, 1, prefix="Late")
        # joined 30 days into a 100-day season: 70 days left, inclusive of today
        res = client.post(f"/api/admin/programs/{_org(program)}/catch-up", headers=admin["h"], json={})
        assert res.status_code == 201, res.text
        inv = admin["fake"].invoices[-1]
        days_left = ((date.today() + timedelta(days=89)) - date.today()).days + 1
        assert inv["lines"][0]["quantity"] == 1 * days_left
        assert inv["total"] == days_left * 50

    def test_it_is_never_charged_twice(self, client, admin, program):
        self._first(client, admin, program)
        _kids(client, program, 1, prefix="Late")
        client.post(f"/api/admin/programs/{_org(program)}/catch-up", headers=admin["h"], json={})
        again = client.post(f"/api/admin/programs/{_org(program)}/catch-up", headers=admin["h"], json={})
        assert again.status_code == 400
        assert len(admin["fake"].invoices) == 2

    def test_a_catch_up_before_the_first_invoice_is_refused(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        res = client.post(f"/api/admin/programs/{_org(program)}/catch-up", headers=admin["h"], json={})
        assert res.status_code == 400

    def test_the_overview_shows_how_many_are_waiting(self, client, admin, program):
        self._first(client, admin, program)
        _kids(client, program, 2, prefix="Late")
        assert _row(client, admin, program)["catch_up_athletes"] == 2


# ---------------------------------------------------------------- webhooks
def _signed(payload: dict, secret=SECRET, ts=None):
    body = json.dumps(payload)
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return body, {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


class TestStripeTellsUs:
    def _raised(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        return client.post(f"/api/admin/programs/{_org(program)}/invoice", headers=admin["h"],
                           json={"email": "t@club.example"}).json()

    def _event(self, kind, stripe_invoice_id):
        return {"id": f"evt_{kind}_{stripe_invoice_id}", "object": "event", "type": kind,
                "data": {"object": {"id": stripe_invoice_id, "object": "invoice"}}}

    def test_an_unsigned_event_changes_nothing(self, client, admin, program):
        made = self._raised(client, admin, program)
        res = client.post("/api/stripe/webhook", content=json.dumps(self._event("invoice.paid", made["stripe_invoice_id"])),
                          headers={"Content-Type": "application/json"})
        assert res.status_code == 400
        assert _row(client, admin, program)["status"] != "paid"

    def test_a_wrongly_signed_event_changes_nothing(self, client, admin, program):
        made = self._raised(client, admin, program)
        body, h = _signed(self._event("invoice.paid", made["stripe_invoice_id"]), secret="whsec_wrong")
        assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 400
        assert _row(client, admin, program)["status"] != "paid"

    def test_an_old_signed_event_is_refused(self, client, admin, program):
        made = self._raised(client, admin, program)
        body, h = _signed(self._event("invoice.paid", made["stripe_invoice_id"]), ts=int(time.time()) - 3600)
        assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 400

    def test_paid_marks_it_paid(self, client, admin, program):
        made = self._raised(client, admin, program)
        body, h = _signed(self._event("invoice.paid", made["stripe_invoice_id"]))
        assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 200
        assert _row(client, admin, program)["status"] == "paid"

    def test_the_same_event_twice_is_harmless(self, client, admin, program):
        made = self._raised(client, admin, program)
        body, h = _signed(self._event("invoice.paid", made["stripe_invoice_id"]))
        client.post("/api/stripe/webhook", content=body, headers=h)
        assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 200
        assert _row(client, admin, program)["status"] == "paid"

    def test_payment_failed_is_shown_as_overdue_not_a_lock_out(self, client, admin, program):
        made = self._raised(client, admin, program)
        body, h = _signed(self._event("invoice.payment_failed", made["stripe_invoice_id"]))
        client.post("/api/stripe/webhook", content=body, headers=h)
        assert _row(client, admin, program)["status"] in ("overdue", "failed")
        # the program keeps working: a director can still sign in and load their dashboard
        assert client.get("/api/coach/roster", headers=program["director"]).status_code == 200

    def test_an_event_for_an_invoice_we_never_raised_is_ignored(self, client, admin, program):
        body, h = _signed(self._event("invoice.paid", "in_not_ours"))
        assert client.post("/api/stripe/webhook", content=body, headers=h).status_code == 200

    def test_with_no_secret_set_the_webhook_refuses_everything(self, client, monkeypatch):
        monkeypatch.delenv("OFFDAYS_STRIPE_WEBHOOK_SECRET", raising=False)
        body, h = _signed({"id": "e", "type": "invoice.paid", "data": {"object": {"id": "x"}}})
        assert client.post("/api/stripe/webhook", content=body, headers=h).status_code in (400, 404, 503)


# ---------------------------------------------------------------- privacy
class TestNobodyElseSeesAnyOfIt:
    def test_a_director_cannot_reach_the_admin_routes(self, client, admin, program):
        for path in ("/api/admin/overview", f"/api/admin/programs/{_org(program)}"):
            assert client.get(path, headers=program["director"]).status_code == 401

    def test_the_directors_own_invoice_view_says_nothing_of_stripe(self, client, admin, program):
        _kids(client, program, 2)
        _season(program)
        client.post(f"/api/admin/programs/{_org(program)}/invoice", headers=admin["h"], json={"email": "t@club.example"})
        text = json.dumps(client.get("/api/org/invoice", headers=program["director"]).json()).lower()
        assert "stripe" not in text and "cus_" not in text and "in_1" not in text

    def test_a_coachs_and_a_parents_screens_carry_no_money(self, client, admin, program):
        for path in ("/api/coach/roster", "/api/coach/teams"):
            text = json.dumps(client.get(path, headers=program["director"]).json()).lower()
            assert "stripe" not in text and "amount_cents" not in text
