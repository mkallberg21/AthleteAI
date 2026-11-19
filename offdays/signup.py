"""Starting a program starts with proving the email address.

The director fills in the program name, sport, their name and email and agrees to the terms. Nothing is created yet: the details wait
in `program_signups` and an email goes to that address with a **Verify email** link. Opening the link shows the program name and asks
for a password (one field); only then is the program, its director and the director's email and password login created, the address
marked confirmed, and the director signed in to add teams, coaches and rosters.

Why it works this way
* No half-made programs: a typo in the address, or someone filling the form in for a stranger, creates nothing to clean up.
* The login is made at the same moment, so a director never has to be handed a code and nobody has to send a link later.
* The reply to "start" is the same whether or not the address already has a login, so the form cannot be used to find out who is a
  director. A person who already has a login is told, in that same reply, to sign in or use Forgot your password.
* Links work once, last 24 hours, and a new one retires the old. A few a day per address. Only a hash of the link is kept.
* A weak password does not spend the link.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import mailer
from . import passwords as pw
from . import staff_mail

logger = logging.getLogger(__name__)

LINK_HOURS = 24
DAILY_LIMIT = 4
#: How long an unfinished signup is kept before it is forgotten (a resend can revive it until then).
KEEP_DAYS = 7

REPLY = ("Check your email. We sent a link to verify it; open it and choose a password to finish. "
         "Already have a login with this address? Sign in instead, or use Forgot your password.")


class SignupError(ValueError):
    """Something the person can fix: shown to them as is."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _digest(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def link_for(token: str) -> str:
    return staff_mail._link("verify", token)


def _taken(conn: sqlite3.Connection, address: str) -> bool:
    """Whether this address already belongs to a login or to staff someone added (a coach, a director)."""
    if pw.by_email(conn, address) is not None:
        return True
    row = conn.execute("SELECT 1 FROM users WHERE active = 1 AND role IN ('coach','director') AND lower(email) = ?",
                       (address,)).fetchone()
    return row is not None


def _recent(conn: sqlite3.Connection, address: str) -> int:
    since = _iso(_now() - timedelta(hours=24))
    return int(conn.execute("SELECT COUNT(*) FROM program_signups WHERE email = ? AND created_at >= ?",
                            (address, since)).fetchone()[0])


def _compose(org_name: str, who: str, link: str) -> tuple[str, str, str]:
    subject = f"Verify your email to start {org_name} on 0FFDAYS"
    text = (f"Hi {who},\n\nYou asked to start {org_name} on 0FFDAYS. Verify that this is your email address, choose a "
            f"password, and then add your teams, coaches and rosters.\n\n{link}\n\n"
            f"The link works once and lasts {LINK_HOURS} hours." + staff_mail._FOOTER_TEXT)
    html = (f"<p>Hi {staff_mail.escape(who)},</p><p>You asked to start {staff_mail.escape(org_name)} on 0FFDAYS. Verify that "
            f"this is your email address, choose a password, and then add your teams, coaches and rosters.</p>"
            + staff_mail._button(link, "Verify email")
            + f"<p>The link works once and lasts {LINK_HOURS} hours.</p>" + staff_mail._FOOTER_HTML)
    return subject, text, html


def _send(conn: sqlite3.Connection, address: str, org_name: str, who: str, token: str) -> bool:
    subject, text, html = _compose(org_name, who, link_for(token))
    try:
        queued = mailer.enqueue(conn, to_email=address, subject=subject, html=html, text=text,
                                kind=mailer.Kind.TRANSACTIONAL, dedupe_key=f"program_signup:{secrets.token_hex(8)}",
                                user_id=None)
        if queued is None:
            return False
        mailer.flush(conn, only_ids=[queued])
        row = conn.execute("SELECT status FROM email_outbox WHERE id = ?", (queued,)).fetchone()
        return bool(row and row["status"] == "sent")
    except Exception:  # noqa: BLE001 - mail must never break the page the person is on
        logger.exception("program signup email failed")
        return False


def _issue(conn: sqlite3.Connection, address: str, org_name: str, sport: str, director_name: str) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    # The live link is retired rather than deleted: it can no longer be used, but it still counts toward the daily limit.
    conn.execute("UPDATE program_signups SET used_at = ? WHERE email = ? AND used_at IS NULL", (_iso(now), address))
    conn.execute(
        "INSERT INTO program_signups(email, org_name, sport, director_name, token_hash, created_at, expires_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (address, org_name, sport, director_name, _digest(token), _iso(now), _iso(now + timedelta(hours=LINK_HOURS))))
    conn.commit()
    return token


def forget_old(conn: sqlite3.Connection) -> None:
    """Drop signups nobody finished (details of a person who never verified are not worth keeping)."""
    conn.execute("DELETE FROM program_signups WHERE created_at < ?", (_iso(_now() - timedelta(days=KEEP_DAYS)),))
    conn.commit()


def start(conn: sqlite3.Connection, *, org_name: str, sport: str, director_name: str, email: str) -> dict[str, Any]:
    """Hold the details and email the verify link. Raises SignupError for what the person can fix.

    Returns {"sent": bool}. `sent` is False when the server cannot send at all (the caller says so) or when the address already
    has a login; the caller shows the same reply for both, except when the server cannot send.
    """
    org_name = " ".join((org_name or "").split())
    director_name = " ".join((director_name or "").split())
    if not org_name or not director_name:
        raise SignupError("A program name and your name, please.")
    try:
        address = pw.check_email(email)
    except pw.PasswordError as exc:
        raise SignupError(str(exc)) from None
    if not staff_mail.mail_available():
        return {"sent": False, "mail": False}
    if mailer.is_suppressed(conn, address) or _taken(conn, address):
        return {"sent": False, "mail": True}
    if _recent(conn, address) >= DAILY_LIMIT:
        return {"sent": False, "mail": True}
    forget_old(conn)
    token = _issue(conn, address, org_name, sport, director_name)
    return {"sent": _send(conn, address, org_name, director_name, token), "mail": True}


def resend(conn: sqlite3.Connection, email: str) -> dict[str, Any]:
    """Send the link again for a signup that is waiting. Nothing to say when there is none."""
    if not staff_mail.mail_available():
        return {"sent": False, "mail": False}
    address = (email or "").strip().lower()
    row = conn.execute(
        "SELECT org_name, sport, director_name FROM program_signups WHERE email = ? AND created_at >= ? "
        "ORDER BY id DESC LIMIT 1", (address, _iso(_now() - timedelta(days=KEEP_DAYS)))).fetchone()
    if row is None or _taken(conn, address) or _recent(conn, address) >= DAILY_LIMIT:
        return {"sent": False, "mail": True}
    token = _issue(conn, address, row["org_name"], row["sport"], row["director_name"])
    return {"sent": _send(conn, address, row["org_name"], row["director_name"], token), "mail": True}


def _live(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    if not token or len(token) > 200:
        pw.burn_time()
        return None
    row = conn.execute("SELECT * FROM program_signups WHERE token_hash = ?", (_digest(token),)).fetchone()
    if row is None or row["used_at"] is not None:
        pw.burn_time()
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
    except ValueError:
        return None
    return row


def peek(conn: sqlite3.Connection, token: str) -> dict[str, str] | None:
    """What a live link is for, without using it: the program and the address, so the page can say who they are verifying."""
    row = _live(conn, token)
    if row is None:
        return None
    return {"org_name": row["org_name"], "email": row["email"], "director_name": row["director_name"]}


def finish(store: Any, token: str, password: str) -> dict[str, Any] | None:
    """Spend the link: create the program, its director and the director's login, and sign them in.

    None when the link is wrong, used or expired. A weak password raises PasswordError and leaves the link usable.
    """
    conn = store.conn
    row = _live(conn, token)
    if row is None:
        return None
    pw.check_password(password, row["email"])            # raises, link NOT spent
    if _taken(conn, row["email"]):
        return None
    conn.execute("UPDATE program_signups SET used_at = ? WHERE id = ?", (_iso(_now()), row["id"]))
    conn.commit()
    org_id = store.create_org(row["org_name"], row["sport"], terms_accepted=True)
    # The address is the director's contact address as well, so the "how the program reaches you" step only asks for a mobile.
    director = store.create_user(org_id, "director", row["director_name"], email=row["email"])
    uid = int(director["id"])
    pw.set_first(conn, uid, row["email"], password)
    conn.execute("UPDATE credentials SET email_verified_at = ?, updated_at = ? WHERE user_id = ?",
                 (_iso(_now()), _iso(_now()), uid))
    conn.commit()
    return {"user_id": uid, "org_id": org_id, "role": "director", "display_name": row["director_name"],
            "email": row["email"], "token": pw.start_session(conn, uid)}
