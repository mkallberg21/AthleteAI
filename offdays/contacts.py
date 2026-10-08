"""The program's parent list.

A club's parent list is a real asset -- sponsors, fundraising, next season's
sign-up -- and it should not depend on which parents happened to tap an
invite. So every parent named on a roster is kept from the moment the roster
is imported, account or no account, and the record is joined to the account
when the parent redeems an invite.

What the list may be *used for* is a different question from whether it is
kept. Contact details arrived for one purpose (running the child's training
app), and using them for a sponsor's message is another purpose, which in
most of the places this will be used needs the parent to have said yes
first: CAN-SPAM for email, and for texts the TCPA, which carries statutory
damages per message. So the export carries a `marketing` column that is the
parent's own answer to "may sponsors and program partners contact you",
off until they switch it on in their portal, and the director's job is to
filter on it before anything goes out.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


def upsert(
    conn: sqlite3.Connection,
    *,
    org_id: int,
    athlete_id: int,
    name: str = "",
    email: str = "",
    phone: str = "",
    relationship: str = "parent",
    source: str = "roster",
    guardian_id: int | None = None,
) -> int:
    """Record one parent for one athlete, filling in rather than overwriting.

    Keyed on (athlete, email). A roster re-import with a phone number added
    fills the phone in; one with the name blank does not blank the name. A
    row with no email at all is keyed on the empty string, so one phone-only
    parent per athlete is kept and a second overwrites it -- which is the
    honest outcome, because without an email there is nothing to tell them
    apart by.
    """
    email = _norm_email(email)
    name = (name or "").strip()
    phone = (phone or "").strip()
    now = _now()
    row = conn.execute(
        "SELECT id FROM guardian_contacts WHERE athlete_id = ? AND email = ?",
        (athlete_id, email),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO guardian_contacts(org_id, athlete_id, guardian_id, name, email, "
            "phone, relationship, source, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (org_id, athlete_id, guardian_id, name, email, phone, relationship,
             source, now, now),
        )
        conn.commit()
        return int(cur.lastrowid)
    conn.execute(
        "UPDATE guardian_contacts SET "
        "  name = CASE WHEN ? != '' THEN ? ELSE name END, "
        "  phone = CASE WHEN ? != '' THEN ? ELSE phone END, "
        "  guardian_id = COALESCE(?, guardian_id), "
        "  updated_at = ? "
        "WHERE id = ?",
        (name, name, phone, phone, guardian_id, now, row["id"]),
    )
    conn.commit()
    return int(row["id"])


def link_account(
    conn: sqlite3.Connection,
    *,
    guardian_id: int,
    athlete_id: int,
    org_id: int,
    name: str,
    email: str | None,
    phone: str | None = None,
) -> int:
    """Join a redeemed guardian account to its roster record.

    Matched on email when the account has one and the roster had the same;
    otherwise this is a parent the roster did not name (or named without an
    email) and they get a row of their own, source 'invite'.
    """
    return upsert(
        conn, org_id=org_id, athlete_id=athlete_id, name=name,
        email=email or "", phone=phone or "", source="invite",
        guardian_id=guardian_id,
    )


def for_org(conn: sqlite3.Connection, org_id: int) -> list[dict[str, Any]]:
    """Every parent in the program, one row per (athlete, parent).

    Carries the athlete and team so a sponsor list can be cut by age group,
    and the parent's own marketing decision so it can be cut by consent.
    """
    rows = conn.execute(
        "SELECT c.id, c.name, c.email, c.phone, c.relationship, c.source, "
        "       c.guardian_id, c.created_at, c.updated_at, "
        "       a.id AS athlete_id, a.display_name AS athlete_name, a.birth_year, "
        "       (SELECT GROUP_CONCAT(t.name, '; ') FROM team_members tm "
        "        JOIN teams t ON t.id = tm.team_id WHERE tm.user_id = a.id) AS teams, "
        "       (SELECT granted FROM consents k WHERE k.athlete_id = a.id "
        "        AND k.scope = 'marketing' ORDER BY k.id DESC LIMIT 1) AS marketing, "
        "       (SELECT granted FROM consents k WHERE k.athlete_id = a.id "
        "        AND k.scope = 'participation' ORDER BY k.id DESC LIMIT 1) AS participation "
        "FROM guardian_contacts c JOIN users a ON a.id = c.athlete_id "
        "WHERE c.org_id = ? AND a.active = 1 "
        "ORDER BY a.display_name, c.id",
        (org_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": int(r["id"]),
            "name": r["name"],
            "email": r["email"],
            "phone": r["phone"],
            "relationship": r["relationship"],
            "athlete_id": int(r["athlete_id"]),
            "athlete_name": r["athlete_name"],
            "birth_year": r["birth_year"],
            "teams": r["teams"] or "",
            "has_account": r["guardian_id"] is not None,
            # Three states on purpose: a parent who has not answered is not a
            # parent who said no, but neither may be contacted.
            "marketing": (None if r["marketing"] is None else bool(r["marketing"])),
            "participation": (None if r["participation"] is None else bool(r["participation"])),
            "source": r["source"],
            "added_on": (r["created_at"] or "")[:10],
        })
    return out


CSV_COLUMNS = (
    "name", "email", "phone", "relationship", "athlete_name", "birth_year",
    "teams", "has_account", "marketing", "participation", "source", "added_on",
)


def to_csv(rows: list[dict[str, Any]]) -> str:
    """The list as a spreadsheet. `marketing` reads yes / no / not asked."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in rows:
        def tri(v: bool | None) -> str:
            return "not asked" if v is None else ("yes" if v else "no")
        w.writerow([
            r["name"], r["email"], r["phone"], r["relationship"], r["athlete_name"],
            r["birth_year"] or "", r["teams"], "yes" if r["has_account"] else "no",
            tri(r["marketing"]), tri(r["participation"]), r["source"], r["added_on"],
        ])
    return buf.getvalue()


def summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "parents": len(rows),
        "with_email": sum(1 for r in rows if r["email"]),
        "with_phone": sum(1 for r in rows if r["phone"]),
        "with_account": sum(1 for r in rows if r["has_account"]),
        "marketing_yes": sum(1 for r in rows if r["marketing"] is True),
        "marketing_no": sum(1 for r in rows if r["marketing"] is False),
        "marketing_not_asked": sum(1 for r in rows if r["marketing"] is None),
    }
