"""Make your own login with an email address and a password, so nobody has to send you a new link.

Everyone who uses 0FFDAYS (director, coach, parent, athlete) can end up with an email and password. Nobody can simply
invent one: a login is attached to a real person the program already added, and the person proves the address is theirs
by opening a link sent to it.

* **Coaches and directors**: type the address the director added them with. A link goes to it.
* **Parents**: type an address the program gave us (on the roster, or the one their invite was emailed to), exactly as
  for "get back in". An address a parent typed at sign-up is never enough. Nothing is sent while the program's email
  hold is on.
* **Athletes**: a child has no address the program knows, so they cannot start from the front page. Signed in once with
  the link their parent sent, they can choose an address (their own, or one the family uses). A link goes to it, and the
  parent can switch the login off. Nothing is sent while the hold is on.

The answer to "email me a link" is the same for every address, known or not. Links are single use, last an hour, and a
new one kills the old. Opening one and choosing a password signs the person in. A weak password does not spend the link.
Only a hash of the link is kept.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import mailer
from . import parent_signin
from . import passwords as pw
from . import staff_mail

logger = logging.getLogger(__name__)

LINK_MINUTES = 60
HOURLY_LIMIT = 3

REPLY = ("If that address is set up with a program, a link to finish creating your login is on its way. It works "
         "once, for an hour. Check your spam folder too. If nothing comes, ask your program to check the address "
         "they have for you.")


class LoginError(ValueError):
    """Something the person can fix, in words they can read."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _digest(token: str) -> str:
    return hashlib.sha256((token or "").strip().encode("utf-8")).hexdigest()


def link_for(token: str) -> str:
    return staff_mail._link("create", token)


# ------------------------------------------------------------------- who it is
def _has_login(conn: sqlite3.Connection, user_id: int) -> bool:
    return pw.get(conn, user_id) is not None


def _account_for(conn: sqlite3.Connection, address: str) -> sqlite3.Row | None:
    """The one account this typed address may create a login for, or None.

    A login's email is unique, so one address can hold one account. A coach or director is found by the address the
    director added them with. A parent by an address the program gave us, preferring the account with the most children.
    """
    staff = conn.execute(
        "SELECT u.id, u.role, u.org_id, o.name AS org_name, o.mail_hold FROM users u "
        "JOIN organizations o ON o.id = u.org_id "
        "WHERE u.active = 1 AND u.role IN ('coach','director') AND lower(u.email) = ? ORDER BY u.id", (address,)
    ).fetchall()
    for row in staff:
        if not _has_login(conn, int(row["id"])):
            return row
    best = None
    for acct in parent_signin._accounts_for(conn, address):
        if _has_login(conn, int(acct["id"])):
            continue
        kids = int(conn.execute("SELECT COUNT(*) FROM guardians WHERE guardian_id = ?", (acct["id"],)).fetchone()[0])
        if best is None or kids > best[0]:
            best = (kids, acct)
    if best is None:
        return None
    a = best[1]
    return {"id": a["id"], "role": "guardian", "org_id": a["org_id"], "org_name": a["org_name"], "mail_hold": a["mail_hold"]}


# ----------------------------------------------------------------------- links
def _recent(conn: sqlite3.Connection, user_id: int) -> int:
    since = _iso(_now() - timedelta(hours=1))
    return int(conn.execute("SELECT COUNT(*) FROM login_links WHERE user_id = ? AND created_at >= ?",
                            (user_id, since)).fetchone()[0])


def _issue(conn: sqlite3.Connection, user_id: int, address: str) -> str | None:
    if _recent(conn, user_id) >= HOURLY_LIMIT:
        return None
    token = secrets.token_urlsafe(32)
    now = _now()
    # Retire the live link rather than delete it: it still counts toward the hourly limit, which stops a mailbox flood.
    conn.execute("UPDATE login_links SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (_iso(now), user_id))
    conn.execute("INSERT INTO login_links(user_id, email, token_hash, created_at, expires_at) VALUES (?,?,?,?,?)",
                 (user_id, address, _digest(token), _iso(now), _iso(now + timedelta(minutes=LINK_MINUTES))))
    conn.commit()
    return token


def _compose(org_name: str, who: str, link: str) -> tuple[str, str, str]:
    subject = f"{org_name}: finish creating your 0FFDAYS login"
    text = (f"You asked to create a login for 0FFDAYS{who}. Open this link and choose a password. After that you "
            f"sign in with this email address and your password, and nobody has to send you a new link.\n\n{link}\n\n"
            f"The link works once and expires in about an hour." + staff_mail._FOOTER_TEXT)
    html = (f"<p>You asked to create a login for 0FFDAYS{staff_mail.escape(who)}. Open the link and choose a password. "
            f"After that you sign in with this email address and your password, and nobody has to send you a new "
            f"link.</p>" + staff_mail._button(link, "Choose my password")
            + "<p>The link works once and expires in about an hour.</p>" + staff_mail._FOOTER_HTML)
    return subject, text, html


def _send(conn: sqlite3.Connection, user_id: int, address: str, org_name: str, who: str, token: str) -> bool:
    subject, text, html = _compose(org_name, who, link_for(token))
    try:
        queued = mailer.enqueue(conn, to_email=address, subject=subject, html=html, text=text,
                                kind=mailer.Kind.TRANSACTIONAL,
                                dedupe_key=f"create_login:{user_id}:{secrets.token_hex(6)}", user_id=user_id)
        if queued is None:
            return False
        mailer.flush(conn, only_ids=[queued])
        row = conn.execute("SELECT status FROM email_outbox WHERE id = ?", (queued,)).fetchone()
        return bool(row and row["status"] == "sent")
    except Exception:  # noqa: BLE001 - mail must never break the page the person is on
        logger.exception("create-login link failed for user %s", user_id)
        return False


def _kids_phrase(conn: sqlite3.Connection, guardian_id: int) -> str:
    names = parent_signin._child_names(conn, guardian_id)
    return f" (parent of {names})" if names else ""


# ----------------------------------------------------------------------- start
def start(conn: sqlite3.Connection, email: str) -> None:
    """Email a link to finish creating a login, if this address belongs to someone the program added.

    Returns nothing on purpose: the caller must not be able to tell the cases apart.
    """
    if not staff_mail.mail_available():
        return
    address = (email or "").strip().lower()
    if not mailer.looks_like_email(address) or mailer.is_suppressed(conn, address):
        return
    if pw.by_email(conn, address) is not None:
        return                                     # already has a login: "forgot your password" is the way back
    acct = _account_for(conn, address)
    if acct is None:
        return
    if acct["role"] == "guardian" and acct["mail_hold"]:
        return                                     # the director's promise: no family is emailed until released
    uid = int(acct["id"])
    token = _issue(conn, uid, address)
    if token is None:
        return
    who = _kids_phrase(conn, uid) if acct["role"] == "guardian" else ""
    _send(conn, uid, address, acct["org_name"], who, token)


def start_for(conn: sqlite3.Connection, user_id: int, email: str) -> dict[str, Any]:
    """A person who is already signed in (by their link) chooses the address for their own login.

    The proof is still the link sent to that address. Raises LoginError with something they can fix.
    """
    if not staff_mail.mail_available():
        raise LoginError("Email is not set up on this server, so a login cannot be created yet.")
    address = pw.check_email(email)                # PasswordError (a ValueError) for a bad address
    user = conn.execute(
        "SELECT u.id, u.role, u.display_name, o.name AS org_name, o.mail_hold FROM users u "
        "JOIN organizations o ON o.id = u.org_id WHERE u.id = ? AND u.active = 1", (user_id,)).fetchone()
    if user is None:
        raise LoginError("That account is not active.")
    if _has_login(conn, user_id):
        raise LoginError("You already have a login. Use Forgot your password if you cannot remember it.")
    if pw.by_email(conn, address) is not None:
        raise LoginError("That email cannot be used for sign-in. Try a different one.")
    if user["role"] in ("guardian", "athlete") and user["mail_hold"]:
        raise LoginError("Your program has not started sending email yet. Ask them, then try again.")
    if mailer.is_suppressed(conn, address):
        raise LoginError("We cannot email that address. Try a different one.")
    token = _issue(conn, user_id, address)
    if token is None:
        raise LoginError("A few links have been sent already. Wait an hour and try again.")
    who = f" for {user['display_name'].split()[0]}" if user["role"] == "athlete" and user["display_name"] else ""
    sent = _send(conn, user_id, address, user["org_name"], who, token)
    return {"ok": True, "sent": sent, "email": address}


# ---------------------------------------------------------------------- finish
def finish(conn: sqlite3.Connection, token: str, password: str) -> dict[str, Any] | None:
    """Spend a link and set the password. None when the link is wrong, used or expired.

    A weak password raises PasswordError and leaves the link usable. Opening the link proves the address, so it is
    marked confirmed.
    """
    if not token or len(token) > 200:
        pw.burn_time()
        return None
    row = conn.execute(
        "SELECT l.id, l.user_id, l.email, l.expires_at, l.used_at, u.active, u.role, u.org_id, u.display_name "
        "FROM login_links l JOIN users u ON u.id = l.user_id WHERE l.token_hash = ?", (_digest(token),)).fetchone()
    if row is None or row["used_at"] is not None or not row["active"]:
        pw.burn_time()
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
    except ValueError:
        return None
    uid = int(row["user_id"])
    pw.check_password(password, row["email"])          # raises, link NOT spent
    if _has_login(conn, uid) or pw.by_email(conn, row["email"]) is not None:
        return None
    conn.execute("UPDATE login_links SET used_at = ? WHERE id = ?", (_iso(_now()), row["id"]))
    pw.set_first(conn, uid, row["email"], password)
    conn.execute("UPDATE credentials SET email_verified_at = ?, updated_at = ? WHERE user_id = ?",
                 (_iso(_now()), _iso(_now()), uid))
    conn.commit()
    return {"user_id": uid, "role": row["role"], "org_id": int(row["org_id"]),
            "display_name": row["display_name"], "email": row["email"], "token": pw.start_session(conn, uid)}


def remove_login(conn: sqlite3.Connection, user_id: int) -> bool:
    """Switch a login off (a parent does this for their child). The link they were sent keeps working."""
    had = _has_login(conn, user_id)
    conn.execute("DELETE FROM credentials WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM login_links WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE users SET email = NULL WHERE id = ? AND role = 'athlete'", (user_id,))
    pw.end_sessions(conn, user_id)
    conn.commit()
    return had


def status(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = pw.get(conn, user_id)
    return {"has_login": row is not None, "email": row["email"] if row else ""}
