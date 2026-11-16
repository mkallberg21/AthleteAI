"""A parent who has lost their way back in asks for a sign-in link by email. Unattended.

A parent signs up once, with an invite code, and from then on is signed in by a code their
phone keeps. A new phone or a cleared browser loses it, and a parent has no password. This
is the way back: type your email on the sign-in page, open the link that arrives, tap once.

Nobody at 0FFDAYS reads a mailbox or forwards anything. The rules are in the code:

* **Only an address the program gave us.** A link goes only to an address the director put
  on the roster, or that the invite itself was emailed to. The address a parent *typed* when
  signing up is not enough: a typo there would let a stranger who owns the typo'd address
  open a parent's account, and with it a child's details.
* **The answer never says who has an account.** The reply is the same for an address that is
  on file, one that is not, one on hold, and one that is not an address.
* **Links are single use, last an hour, and a new one kills the old.** A few an hour per
  parent and per source address.
* **The email hold stays in charge.** Nothing goes to a program's parents until its director
  has released the hold. This is mail to a parent about their own account, but the hold is
  the director's promise that no family is emailed before they are ready.
* **Spending a link signs the parent in on this phone and signs out the old one**: the old
  sign-in code is replaced, as with a lost key.
* Nothing secret is stored in the clear.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import mailer
from . import staff_mail
from .db import fresh_token, hash_token, transaction

logger = logging.getLogger(__name__)

LINK_MINUTES = 60
#: At most this many links to one parent in an hour.
HOURLY_LIMIT = 3

REPLY = ("If that address is on file for a parent in a program, a sign-in link is on its way. "
         "It works once, for an hour. Check your spam folder too. If nothing comes, ask your "
         "program director to check the address they have for you.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _digest(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


def _accounts_for(conn: sqlite3.Connection, address: str) -> list[sqlite3.Row]:
    """Active parent accounts this address is a *trusted* address for."""
    return conn.execute(
        "SELECT g.id, g.org_id, g.display_name, o.name AS org_name, o.mail_hold "
        "FROM users g JOIN organizations o ON o.id = g.org_id "
        "WHERE g.role = 'guardian' AND g.active = 1 AND ("
        "  EXISTS (SELECT 1 FROM guardian_invites i WHERE i.redeemed_by = g.id AND lower(i.email) = ?) "
        "  OR EXISTS (SELECT 1 FROM guardian_contacts c WHERE c.guardian_id = g.id "
        "             AND c.source = 'roster' AND lower(c.email) = ?)) "
        "ORDER BY g.id", (address, address)).fetchall()


def _recent(conn: sqlite3.Connection, guardian_id: int) -> int:
    since = _iso(_now() - timedelta(hours=1))
    return int(conn.execute(
        "SELECT COUNT(*) FROM parent_links WHERE guardian_id = ? AND created_at >= ?",
        (guardian_id, since)).fetchone()[0])


def _child_names(conn: sqlite3.Connection, guardian_id: int) -> str:
    names = [r[0].split()[0] for r in conn.execute(
        "SELECT a.display_name FROM guardians gu JOIN users a ON a.id = gu.athlete_id "
        "WHERE gu.guardian_id = ? AND a.active = 1 ORDER BY a.display_name", (guardian_id,)).fetchall()
        if r[0] and r[0].split()]
    return " and ".join(names)


def _compose(org_name: str, kids: str, link: str) -> tuple[str, str, str]:
    who = f" for {kids}" if kids else ""
    subject = f"{org_name}: your 0FFDAYS sign-in link"
    text = (f"Someone asked for a sign-in link to your 0FFDAYS parent account{who}. If that was you, "
            f"open it and tap Sign in:\n\n{link}\n\nThe link works once and expires in about an hour. "
            f"Opening it signs you in on that phone and signs you out of the old one. From there "
            f"you can send your athlete a new sign-in link."
            + staff_mail._FOOTER_TEXT)
    html = (f"<p>Someone asked for a sign-in link to your 0FFDAYS parent account{staff_mail.escape(who)}. "
            f"If that was you, open it and tap Sign in.</p>"
            + staff_mail._button(link, "Open my parent account")
            + "<p>The link works once and expires in about an hour. Opening it signs you in on that "
              "phone and signs you out of the old one. From there you can send your athlete a new "
              "sign-in link.</p>" + staff_mail._FOOTER_HTML)
    return subject, text, html


def send_link(conn: sqlite3.Connection, email: str) -> None:
    """Email a sign-in link if, and only if, this is a trusted address for a parent account
    whose program has released the email hold. Returns nothing on purpose: the caller must
    not be able to tell the cases apart."""
    if not staff_mail.mail_available():
        return
    address = (email or "").strip().lower()
    if not mailer.looks_like_email(address) or mailer.is_suppressed(conn, address):
        return
    for acct in _accounts_for(conn, address):
        if acct["mail_hold"]:
            continue
        gid = int(acct["id"])
        if _recent(conn, gid) >= HOURLY_LIMIT:
            continue
        token = secrets.token_urlsafe(32)
        now = _now()
        # Retire the live link rather than delete it: it can no longer be used, but it still
        # counts toward the hourly limit, which is what stops a mailbox flood.
        conn.execute("UPDATE parent_links SET used_at = ? WHERE guardian_id = ? AND used_at IS NULL",
                     (_iso(now), gid))
        conn.execute(
            "INSERT INTO parent_links(guardian_id, email, token_hash, created_at, expires_at) "
            "VALUES (?,?,?,?,?)",
            (gid, address, _digest(token), _iso(now), _iso(now + timedelta(minutes=LINK_MINUTES))))
        conn.commit()
        subject, text, html = _compose(acct["org_name"], _child_names(conn, gid),
                                       staff_mail._link("parent", token))
        try:
            queued = mailer.enqueue(
                conn, to_email=address, subject=subject, html=html, text=text,
                kind=mailer.Kind.TRANSACTIONAL,
                dedupe_key=f"parent_link:{gid}:{secrets.token_hex(6)}", user_id=gid)
            if queued is not None:
                mailer.flush(conn, only_ids=[queued])
        except Exception:  # noqa: BLE001 - mail must never break the page the parent is on
            logger.exception("parent sign-in link failed for guardian %s", gid)


def spend(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    """Use a link: replace the parent's sign-in code with a fresh one and return it.
    None when the link is wrong, used, expired, or the account is gone."""
    if not token or len(token) > 200:
        return None
    row = conn.execute(
        "SELECT l.id, l.guardian_id, l.expires_at, l.used_at, u.org_id, u.display_name, u.active, u.role "
        "FROM parent_links l JOIN users u ON u.id = l.guardian_id WHERE l.token_hash = ?",
        (_digest(token),)).fetchone()
    if row is None or row["used_at"] is not None or not row["active"] or row["role"] != "guardian":
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
    except ValueError:
        return None
    new_code = fresh_token(conn)
    with transaction(conn) as c:
        c.execute("UPDATE parent_links SET used_at = ? WHERE id = ?", (_iso(_now()), row["id"]))
        c.execute("UPDATE users SET token_hash = ? WHERE id = ?", (hash_token(new_code), row["guardian_id"]))
    return {"token": new_code, "role": "guardian", "athlete_id": int(row["guardian_id"]),
            "display_name": row["display_name"], "org_id": int(row["org_id"])}
