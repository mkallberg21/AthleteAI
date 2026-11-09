"""The operator's own dashboard, and the invoicing behind it.

One person -- the operator -- sees every program, what each owes, and how far
its families have got, and raises one invoice per program per season. This is
deliberately not a subscription and not usage metering: the price is known the
day the roster lands (athletes x season days x the rate), so one Stripe invoice
is the whole of it.

Rules that are easy to break and expensive when broken:

* **Nothing is raised or sent by itself.** Opening the dashboard reads; it
  never creates a customer or an invoice. Raising makes a *draft*. Sending is a
  second, deliberate press. A wrong invoice to a club on day one costs more
  than one extra click.
* **The door is a key, not a sign-in.** Only a hash of it is on the server, and
  the page does not exist at all (404) until one is set. A director's own
  sign-in code is not accepted.
* **A catch-up invoice charges only athletes added since the last invoice, only
  for the days they have left, and never twice.**
* **Nothing here locks a child out.** An unpaid invoice shows as overdue to the
  operator. It does not pause a program; a parent should never lose a kid's
  training because a club treasurer is slow.
* **A webhook that is not signed by Stripe changes nothing.**
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import date, datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import billing as billing_mod
from . import funnel as funnel_mod

#: Failed attempts at the operator key, per source address.
_FAILS: dict[str, list[float]] = {}
_MAX_FAILS = 8
_WINDOW_SECONDS = 15 * 60

#: Programs made by the UI health workflow are not customers.
_NOT_CUSTOMERS = ("UI health",)

#: How the invoice tells the club to pay. Bank transfer and a check come first;
#: the card is the backup. Which methods Stripe actually offers is set in the
#: Stripe Dashboard (Settings > Invoices), never hard-coded here.
PAYMENT_NOTE = (
    "Please pay by bank transfer or check. Card is available as a backup."
)


# --------------------------------------------------------------------- door
def _key_hash() -> str:
    return os.environ.get("OFFDAYS_ADMIN_KEY_SHA256", "").strip().lower()


def _locked(host: str) -> bool:
    now = time.time()
    recent = [t for t in _FAILS.get(host, []) if now - t < _WINDOW_SECONDS]
    _FAILS[host] = recent
    return len(recent) >= _MAX_FAILS


def operator(request: Request) -> str:
    """Let the operator in; nobody else. 404 when no key is configured."""
    wanted = _key_hash()
    if not wanted:
        raise HTTPException(status_code=404)
    host = request.client.host if request.client else "?"
    if _locked(host):
        raise HTTPException(status_code=429, detail="too many wrong keys; wait and try again",
                            headers={"Retry-After": str(_WINDOW_SECONDS)})
    auth = request.headers.get("authorization", "")
    given = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    digest = hashlib.sha256(given.encode()).hexdigest() if given else ""
    if not given or not hmac.compare_digest(digest, wanted):
        _FAILS.setdefault(host, []).append(time.time())
        raise HTTPException(status_code=401, detail="not the operator key")
    _FAILS.pop(host, None)
    return host


# ------------------------------------------------------------------- Stripe
class StripeGateway:
    """The only code that talks to Stripe. Kept thin so tests replace all of it."""

    def __init__(self, secret_key: str) -> None:
        import stripe  # imported here: the app must start without it

        self._stripe = stripe
        self.client = stripe.StripeClient(secret_key)

    def create_customer(self, *, name: str, email: str, org_id: int) -> str:
        c = self.client.v1.customers.create({"name": name, "email": email,
                                             "metadata": {"offdays_org_id": str(org_id)}})
        return c.id

    def create_invoice(self, *, customer: str, lines: list[dict[str, Any]], description: str,
                       days_until_due: int, idempotency_key: str) -> dict[str, Any]:
        # collection_method=send_invoice: the club pays on its own schedule, by
        # bank transfer or check as readily as by card. auto_advance is off so
        # Stripe never finalises or emails it on its own.
        inv = self.client.v1.invoices.create(
            {"customer": customer, "collection_method": "send_invoice",
             "days_until_due": days_until_due, "auto_advance": False,
             "description": description, "footer": PAYMENT_NOTE,
             "pending_invoice_items_behavior": "exclude"},
            {"idempotency_key": idempotency_key},
        )
        for i, line in enumerate(lines):
            self.client.v1.invoice_items.create(
                {"customer": customer, "invoice": inv.id, "currency": "usd",
                 "description": line["description"], "quantity": line["quantity"],
                 "unit_amount": line["unit_amount"]},
                {"idempotency_key": f"{idempotency_key}-line{i}"},
            )
        got = self.client.v1.invoices.retrieve(inv.id)
        return {"id": got.id, "total": got.total, "hosted_invoice_url": getattr(got, "hosted_invoice_url", "") or ""}

    def send_invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self.client.v1.invoices.retrieve(invoice_id)
        if inv.status == "draft":
            inv = self.client.v1.invoices.finalize_invoice(invoice_id)
        sent = self.client.v1.invoices.send_invoice(invoice_id)
        return {"id": sent.id, "status": sent.status,
                "hosted_invoice_url": getattr(sent, "hosted_invoice_url", "") or ""}

    def mark_paid(self, invoice_id: str) -> dict[str, Any]:
        inv = self.client.v1.invoices.retrieve(invoice_id)
        if inv.status == "draft":
            self.client.v1.invoices.finalize_invoice(invoice_id)
        done = self.client.v1.invoices.pay(invoice_id, {"paid_out_of_band": True})
        return {"id": done.id, "status": done.status}

    def void_invoice(self, invoice_id: str) -> dict[str, Any]:
        inv = self.client.v1.invoices.retrieve(invoice_id)
        if inv.status == "draft":
            self.client.v1.invoices.delete(invoice_id)
            return {"id": invoice_id, "status": "void"}
        done = self.client.v1.invoices.void_invoice(invoice_id)
        return {"id": done.id, "status": done.status}


def gateway() -> Any:
    """The live gateway, or a clear refusal when no key is configured."""
    key = os.environ.get("OFFDAYS_STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="Stripe is not connected on this server yet")
    return StripeGateway(key)


# --------------------------------------------------------------- the numbers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _real_programs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT id, name FROM organizations ORDER BY id").fetchall()
    return [r for r in rows if not any((r["name"] or "").startswith(p) for p in _NOT_CUSTOMERS)]


def _season_invoice(conn: sqlite3.Connection, org_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM org_invoices WHERE org_id = ? AND kind = 'season' AND status <> 'void' "
        "ORDER BY id DESC LIMIT 1", (org_id,)).fetchone()


def _uninvoiced_athletes(conn: sqlite3.Connection, org_id: int) -> list[int]:
    """Active athletes on the roster who are on no invoice yet."""
    rows = conn.execute(
        "SELECT m.user_id FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = ? AND m.role = 'athlete' AND m.active = 1 AND u.active = 1 "
        "AND m.user_id NOT IN (SELECT athlete_id FROM invoiced_athletes ia "
        "  JOIN org_invoices oi ON oi.id = ia.invoice_id WHERE oi.org_id = ? AND oi.status <> 'void') "
        "ORDER BY m.user_id", (org_id, org_id)).fetchall()
    return [int(r[0]) for r in rows]


def _roster_count(conn: sqlite3.Connection, org_id: int) -> int:
    return billing_mod._rostered(conn, org_id)


def _program_row(conn: sqlite3.Connection, org: sqlite3.Row) -> dict[str, Any]:
    org_id = int(org["id"])
    rate = billing_mod.get_plan("club_roster").per_athlete_day_cents
    starts, ends = billing_mod.season_window(conn, org_id)
    days = billing_mod.season_days(starts, ends)
    athletes = _roster_count(conn, org_id)
    amount = athletes * days * rate
    season = _season_invoice(conn, org_id)
    sums = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN status <> 'void' THEN amount_cents END), 0) AS invoiced, "
        "       COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_cents END), 0) AS paid, "
        "       COALESCE(SUM(CASE WHEN status = 'overdue' THEN amount_cents END), 0) AS overdue "
        "FROM org_invoices WHERE org_id = ?", (org_id,)).fetchone()
    if season is not None:
        status = season["status"]
    elif athletes == 0:
        status = "needs_roster"
    elif days == 0:
        status = "needs_season"
    else:
        status = "ready"
    director = conn.execute(
        "SELECT u.display_name, u.email FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.org_id = ? AND m.role = 'director' AND m.active = 1 ORDER BY u.id LIMIT 1",
        (org_id,)).fetchone()
    fam = funnel_mod.funnel(conn, org_id)
    waiting = len(_uninvoiced_athletes(conn, org_id)) if season is not None else 0
    return {
        "org_id": org_id, "name": org["name"],
        "director": director["display_name"] if director else "",
        "director_email": (director["email"] or "") if director else "",
        "athletes": athletes,
        "season_starts_on": starts.isoformat() if starts else "",
        "season_ends_on": ends.isoformat() if ends else "",
        "season_days": days,
        "rate_cents": rate,
        "amount_cents": amount if (athletes and days) else 0,
        "status": status,
        "invoiced_cents": int(sums["invoiced"]), "paid_cents": int(sums["paid"]),
        "overdue_cents": int(sums["overdue"]),
        "catch_up_athletes": waiting,
        "families": {"total": fam["total"], "training": fam["counts"].get("training", 0),
                     "counts": fam["counts"]},
    }


def overview(conn: sqlite3.Connection) -> dict[str, Any]:
    programs = [_program_row(conn, o) for o in _real_programs(conn)]
    totals = {
        "programs": len(programs),
        "athletes": sum(p["athletes"] for p in programs),
        "ready_cents": sum(p["amount_cents"] for p in programs if p["status"] == "ready"),
        "invoiced_cents": sum(p["invoiced_cents"] for p in programs),
        "paid_cents": sum(p["paid_cents"] for p in programs),
        "overdue_cents": sum(p["overdue_cents"] for p in programs),
        "to_send": sum(1 for p in programs if p["status"] == "draft"),
        "waiting_ready": sum(1 for p in programs if p["status"] == "ready"),
    }
    return {
        "programs": programs, "totals": totals,
        "stripe_connected": bool(os.environ.get("OFFDAYS_STRIPE_SECRET_KEY", "").strip()),
        "webhook_connected": bool(os.environ.get("OFFDAYS_STRIPE_WEBHOOK_SECRET", "").strip()),
    }


# ----------------------------------------------------------------- invoices
class InvoiceRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    days_until_due: int = Field(default=30, ge=1, le=120)


class CatchUpRequest(BaseModel):
    email: str | None = Field(default=None, max_length=200)
    days_until_due: int = Field(default=30, ge=1, le=120)


class PaidRequest(BaseModel):
    note: str = Field(default="", max_length=200)


def _customer(conn: sqlite3.Connection, gw: Any, org_id: int, name: str, email: str) -> str:
    """One Stripe customer per program, ever."""
    row = conn.execute("SELECT stripe_customer_id FROM stripe_customers WHERE org_id = ?", (org_id,)).fetchone()
    if row:
        return row["stripe_customer_id"]
    cid = gw.create_customer(name=name, email=email, org_id=org_id)
    conn.execute("INSERT INTO stripe_customers(org_id, stripe_customer_id, email, created_at) VALUES (?,?,?,?)",
                 (org_id, cid, email, _now()))
    return cid


def _count_of(conn: sqlite3.Connection, org_id: int, kind: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM org_invoices WHERE org_id = ? AND kind = ?",
                            (org_id, kind)).fetchone()[0])


def _record(conn, *, org_id, kind, made, athletes, days, amount_cents, athlete_ids, email) -> dict[str, Any]:
    cur = conn.execute(
        "INSERT INTO org_invoices(org_id, kind, stripe_invoice_id, status, athletes, days, amount_cents, "
        "hosted_url, email, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (org_id, kind, made["id"], "draft", athletes, days, amount_cents,
         made.get("hosted_invoice_url", ""), email, _now()))
    invoice_id = int(cur.lastrowid)
    for aid in athlete_ids:
        conn.execute("INSERT OR IGNORE INTO invoiced_athletes(invoice_id, athlete_id, days) VALUES (?,?,?)",
                     (invoice_id, aid, days))
    conn.commit()
    return {"invoice_id": invoice_id, "stripe_invoice_id": made["id"], "status": "draft",
            "amount_cents": amount_cents, "athletes": athletes, "days": days,
            "hosted_invoice_url": made.get("hosted_invoice_url", "")}


def raise_season_invoice(conn: sqlite3.Connection, gw: Any, org_id: int, email: str,
                         days_until_due: int) -> dict[str, Any]:
    org = conn.execute("SELECT id, name FROM organizations WHERE id = ?", (org_id,)).fetchone()
    if org is None:
        raise HTTPException(status_code=404, detail="unknown program")
    if _season_invoice(conn, org_id) is not None:
        raise HTTPException(status_code=409, detail="this program already has a season invoice; void it to raise another")
    row = _program_row(conn, org)
    if row["status"] != "ready":
        why = {"needs_roster": "no athletes on the roster yet",
               "needs_season": "the director has not set the season dates yet"}.get(row["status"], "not ready")
        raise HTTPException(status_code=400, detail=f"not ready to invoice: {why}")
    athlete_ids = _uninvoiced_athletes(conn, org_id)
    days, rate = row["season_days"], row["rate_cents"]
    quantity = len(athlete_ids) * days
    description = (f"0FFDAYS season: {len(athlete_ids)} athletes x {days} days "
                   f"({row['season_starts_on']} to {row['season_ends_on']}). {PAYMENT_NOTE}")
    cid = _customer(conn, gw, org_id, org["name"], email)
    made = gw.create_invoice(
        customer=cid, days_until_due=days_until_due, description=description,
        idempotency_key=f"season-{org_id}-{_count_of(conn, org_id, 'season')}",
        lines=[{"description": f"0FFDAYS, {len(athlete_ids)} athletes x {days} days",
                "quantity": quantity, "unit_amount": rate}])
    return _record(conn, org_id=org_id, kind="season", made=made, athletes=len(athlete_ids), days=days,
                   amount_cents=quantity * rate, athlete_ids=athlete_ids, email=email)


def raise_catch_up(conn: sqlite3.Connection, gw: Any, org_id: int, email: str | None,
                   days_until_due: int) -> dict[str, Any]:
    org = conn.execute("SELECT id, name FROM organizations WHERE id = ?", (org_id,)).fetchone()
    if org is None:
        raise HTTPException(status_code=404, detail="unknown program")
    if _season_invoice(conn, org_id) is None:
        raise HTTPException(status_code=400, detail="raise the season invoice first")
    starts, ends = billing_mod.season_window(conn, org_id)
    if starts is None or ends is None:
        raise HTTPException(status_code=400, detail="the season has no dates")
    ids = _uninvoiced_athletes(conn, org_id)
    if not ids:
        raise HTTPException(status_code=400, detail="nobody has been added since the last invoice")
    days_left = (ends - max(date.today(), starts)).days + 1
    if days_left <= 0:
        raise HTTPException(status_code=400, detail="the season is over; nothing to charge for")
    rate = billing_mod.get_plan("club_roster").per_athlete_day_cents
    quantity = len(ids) * days_left
    known = conn.execute("SELECT email FROM stripe_customers WHERE org_id = ?", (org_id,)).fetchone()
    to = (email or (known["email"] if known else "") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="an email is needed")
    cid = _customer(conn, gw, org_id, org["name"], to)
    description = (f"0FFDAYS catch-up: {len(ids)} athletes added mid-season x {days_left} days left. "
                   f"{PAYMENT_NOTE}")
    made = gw.create_invoice(
        customer=cid, days_until_due=days_until_due, description=description,
        idempotency_key=f"catchup-{org_id}-{_count_of(conn, org_id, 'catch_up')}",
        lines=[{"description": f"0FFDAYS catch-up, {len(ids)} athletes x {days_left} days",
                "quantity": quantity, "unit_amount": rate}])
    return _record(conn, org_id=org_id, kind="catch_up", made=made, athletes=len(ids), days=days_left,
                   amount_cents=quantity * rate, athlete_ids=ids, email=to)


def _set_status(conn: sqlite3.Connection, invoice_id: int, status: str, *, note: str = "") -> None:
    row = conn.execute("SELECT org_id, amount_cents, status FROM org_invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown invoice")
    if row["status"] == status:
        return
    if row["status"] == "paid" and status != "void":
        return  # paid is final: a late "overdue" event must not undo it
    paid_at = _now() if status == "paid" else None
    conn.execute("UPDATE org_invoices SET status = ?, note = CASE WHEN ? <> '' THEN ? ELSE note END, "
                 "paid_at = COALESCE(?, paid_at), updated_at = ? WHERE id = ?",
                 (status, note, note, paid_at, _now(), invoice_id))
    if status == "paid":
        # The sponsorship rebate is earned on what the club has actually paid.
        billing_mod.accrue_rebate(conn, int(row["org_id"]), int(row["amount_cents"]))
    conn.commit()


def _invoice(conn: sqlite3.Connection, invoice_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM org_invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown invoice")
    return row


# ------------------------------------------------------------------ webhook
#: What Stripe says -> what we show. Anything else is ignored.
_EVENT_STATUS = {
    "invoice.paid": "paid", "invoice.payment_succeeded": "paid",
    "invoice.payment_failed": "overdue", "invoice.overdue": "overdue",
    "invoice.voided": "void", "invoice.marked_uncollectible": "overdue",
    "invoice.sent": "sent",
}


def handle_event(conn: sqlite3.Connection, event: dict[str, Any]) -> str:
    """Apply one verified Stripe event. Safe to apply twice."""
    event_id = str(event.get("id") or "")
    if event_id:
        seen = conn.execute("INSERT OR IGNORE INTO stripe_events(id, received_at) VALUES (?,?)",
                            (event_id, _now())).rowcount
        conn.commit()
        if not seen:
            return "duplicate"
    status = _EVENT_STATUS.get(str(event.get("type") or ""))
    if status is None:
        return "ignored"
    obj = (event.get("data") or {}).get("object") or {}
    row = conn.execute("SELECT id FROM org_invoices WHERE stripe_invoice_id = ?", (str(obj.get("id") or ""),)).fetchone()
    if row is None:
        return "not ours"
    _set_status(conn, int(row["id"]), status)
    return status


# ------------------------------------------------------------------- routes
def make_router(get_store: Callable[[], Any], app: Any = None) -> Any:
    """Add the operator routes. Given the app, they are registered on it directly so
    `app.routes` lists them like any other route."""
    router = app if app is not None else APIRouter()

    def conn_of(store=Depends(get_store)) -> sqlite3.Connection:
        return store.conn

    @router.get("/api/admin/overview")
    def admin_overview(_: str = Depends(operator), conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        return overview(conn)

    @router.get("/api/admin/programs/{org_id}")
    def admin_program(org_id: int, _: str = Depends(operator),
                      conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        org = conn.execute("SELECT id, name FROM organizations WHERE id = ?", (org_id,)).fetchone()
        if org is None:
            raise HTTPException(status_code=404, detail="unknown program")
        invoices = [dict(r) for r in conn.execute(
            "SELECT id, kind, stripe_invoice_id, status, athletes, days, amount_cents, hosted_url, email, "
            "created_at, paid_at, note FROM org_invoices WHERE org_id = ? ORDER BY id DESC", (org_id,))]
        return {"program": _program_row(conn, org), "invoices": invoices}

    @router.post("/api/admin/programs/{org_id}/invoice", status_code=201)
    def admin_invoice(org_id: int, body: InvoiceRequest, _: str = Depends(operator),
                      conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        if "@" not in body.email:
            raise HTTPException(status_code=422, detail="that does not look like an email address")
        return raise_season_invoice(conn, gateway(), org_id, body.email.strip(), body.days_until_due)

    @router.post("/api/admin/programs/{org_id}/catch-up", status_code=201)
    def admin_catch_up(org_id: int, body: CatchUpRequest, _: str = Depends(operator),
                       conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        return raise_catch_up(conn, gateway(), org_id, body.email, body.days_until_due)

    @router.post("/api/admin/invoices/{invoice_id}/send")
    def admin_send(invoice_id: int, _: str = Depends(operator),
                   conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        inv = _invoice(conn, invoice_id)
        if inv["status"] not in ("draft", "sent", "overdue"):
            raise HTTPException(status_code=400, detail=f"a {inv['status']} invoice cannot be sent")
        sent = gateway().send_invoice(inv["stripe_invoice_id"])
        conn.execute("UPDATE org_invoices SET status = CASE WHEN status = 'draft' THEN 'sent' ELSE status END, "
                     "hosted_url = COALESCE(NULLIF(?, ''), hosted_url), sent_at = ?, updated_at = ? WHERE id = ?",
                     (sent.get("hosted_invoice_url", ""), _now(), _now(), invoice_id))
        conn.commit()
        return {"invoice_id": invoice_id, "status": _invoice(conn, invoice_id)["status"],
                "hosted_invoice_url": _invoice(conn, invoice_id)["hosted_url"]}

    @router.post("/api/admin/invoices/{invoice_id}/mark-paid")
    def admin_mark_paid(invoice_id: int, body: PaidRequest, _: str = Depends(operator),
                        conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        inv = _invoice(conn, invoice_id)
        if inv["status"] in ("void", "paid"):
            raise HTTPException(status_code=400, detail=f"already {inv['status']}")
        gateway().mark_paid(inv["stripe_invoice_id"])
        _set_status(conn, invoice_id, "paid", note=body.note.strip())
        return {"invoice_id": invoice_id, "status": "paid"}

    @router.post("/api/admin/invoices/{invoice_id}/void")
    def admin_void(invoice_id: int, _: str = Depends(operator),
                   conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        inv = _invoice(conn, invoice_id)
        if inv["status"] == "paid":
            raise HTTPException(status_code=400, detail="a paid invoice cannot be voided; refund it in Stripe")
        if inv["status"] != "void":
            gateway().void_invoice(inv["stripe_invoice_id"])
            _set_status(conn, invoice_id, "void")
            # the athletes on it are free to be invoiced again
        return {"invoice_id": invoice_id, "status": "void"}

    @router.post("/api/stripe/webhook")
    async def stripe_webhook(request: Request, conn: sqlite3.Connection = Depends(conn_of)) -> dict[str, Any]:
        secret = os.environ.get("OFFDAYS_STRIPE_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise HTTPException(status_code=503, detail="webhook not configured")
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        try:
            import stripe

            event = stripe.Webhook.construct_event(payload, sig, secret, tolerance=300)
        except Exception:
            # Bad signature, stale timestamp, or garbage: say nothing useful and change nothing.
            raise HTTPException(status_code=400, detail="bad signature")
        result = handle_event(conn, json.loads(payload))
        return {"received": True, "result": result}

    return router
