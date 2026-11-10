"""Self-service password reset by email, for coaches and directors. Unattended.

A coach types their own address on the sign-in page. The server emails that address a
link; the coach opens it and chooses a new password. Nobody at 0FFDAYS reads a
mailbox, forwards a code or presses a button. The sender (`no-reply@mail.0ffdays.com`)
is a return label nobody logs into; staff keep using their own Gmail or club address.

Because nobody is watching, the rules are built into the code:

* **Confirm before trusting.** A reset link is only ever sent to an address the person
  has *opened a link at*. Otherwise a typo when setting a password would let a stranger
  who owns the typo'd address take the account.
* **The answer never says who has an account.** "Email me a link" gives the same reply
  for a known, unknown, unconfirmed, deactivated or malformed address.
* **Links are single use, short lived and replaceable.** Asking again kills the earlier
  link; a changed address kills every link sent to the old one; a weak password does
  not spend the link; a successful reset ends every open session.
* **Only the person asking is emailed**, at once, and never through the parents' email
  hold: that hold exists so wiring up a provider cannot start mailing families. This
  mail goes to one staff member who asked for it. It checks that the server has a
  provider (`CONFIG.smtp_configured`) and nothing else.
* **Limits.** A few links an hour per address and per person; guessing a link is
  throttled like guessing a code. Nothing secret is stored in the clear.

The reply "we sent it" is also honest about the one case nobody can fix by themselves:
a wrong address. The message points to the director, who can still hand out a one-time
code (passwords.issue_reset), and the operator script covers a director who has lost
every door.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from . import mailer
from . import passwords as pw

logger = logging.getLogger(__name__)

CONFIRM_HOURS = 24
RESET_MINUTES = 60
#: At most this many emails of one kind to one person in an hour.
HOURLY_LIMIT = 3

#: The one reply to "email me a link", whoever asked and whatever happened.
FORGOT_REPLY = ("If that address is set up for sign-in, a link is on its way. It works once, for an "
                "hour. Check your spam folder too.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _digest(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def mail_available() -> bool:
    """The server can send at all. Deliberately NOT the parents' hold."""
    return bool(mailer.CONFIG.smtp_configured)


# --------------------------------------------------------------------- links
def _recent(conn: sqlite3.Connection, user_id: int, purpose: str) -> int:
    since = _iso(_now() - timedelta(hours=1))
    return int(conn.execute(
        "SELECT COUNT(*) FROM email_tokens WHERE user_id = ? AND purpose = ? AND created_at >= ?",
        (user_id, purpose, since)).fetchone()[0])


def _issue(conn: sqlite3.Connection, user_id: int, purpose: str, email: str, ttl: timedelta) -> str | None:
    """A fresh link, replacing any live one. None when asked for too often."""
    if _recent(conn, user_id, purpose) >= HOURLY_LIMIT:
        return None
    token = secrets.token_urlsafe(32)
    now = _now()
    # Retire the live link rather than delete it: it can no longer be used, but it
    # still counts toward the hourly limit, which is what stops a mailbox flood.
    conn.execute("UPDATE email_tokens SET used_at = ? WHERE user_id = ? AND purpose = ? AND used_at IS NULL",
                 (_iso(now), user_id, purpose))
    conn.execute(
        "INSERT INTO email_tokens(user_id, purpose, email, token_hash, created_at, expires_at) "
        "VALUES (?,?,?,?,?,?)", (user_id, purpose, email, _digest(token), _iso(now), _iso(now + ttl)))
    conn.commit()
    return token


def _spend(conn: sqlite3.Connection, token: str, purpose: str) -> sqlite3.Row | None:
    """The row for a live link of this purpose, marked used. None if wrong, used or expired."""
    if not token or len(token) > 200:
        return None
    row = conn.execute(
        "SELECT t.*, c.email AS current_email FROM email_tokens t "
        "LEFT JOIN credentials c ON c.user_id = t.user_id "
        "WHERE t.token_hash = ? AND t.purpose = ?", (_digest(token), purpose)).fetchone()
    if row is None or row["used_at"] is not None:
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
    except ValueError:
        return None
    # A link follows the address it was sent to: change the address and it is dead.
    if row["current_email"] != row["email"]:
        return None
    conn.execute("UPDATE email_tokens SET used_at = ? WHERE id = ?", (_iso(_now()), row["id"]))
    return row


def _link(kind: str, token: str) -> str:
    base = mailer.CONFIG.app_base_url.rstrip("/") if mailer.CONFIG.app_base_url else ""
    return f"{base}/app/index.html?{kind}={token}"


# ------------------------------------------------------------------- sending
_FOOTER_TEXT = ("\n\nThis message was sent automatically and the mailbox is not monitored, so please do "
                "not reply. If you did not ask for it, ignore it and nothing changes.")
_FOOTER_HTML = ('<p style="color:#666;font-size:90%">This message was sent automatically and the mailbox '
                "is not monitored, so please do not reply. If you did not ask for it, ignore it and "
                "nothing changes.</p>")


def _button(url: str, label: str) -> str:
    return (f'<p><a href="{escape(url)}" style="display:inline-block;padding:12px 20px;background:#111;'
            f'color:#fff;text-decoration:none;border-radius:6px">{escape(label)}</a></p>')


def _compose(kind: str, org_name: str, link: str = "") -> tuple[str, str, str]:
    if kind == "confirm":
        return (f"{org_name}: confirm your email for 0FFDAYS",
                f"Confirm that this is your email address so you can reset your 0FFDAYS password "
                f"yourself if you ever forget it:\n\n{link}\n\nThe link works once and lasts "
                f"{CONFIRM_HOURS} hours. You stay signed in either way." + _FOOTER_TEXT,
                "<p>Confirm that this is your email address so you can reset your 0FFDAYS password "
                "yourself if you ever forget it.</p>" + _button(link, "Confirm my email")
                + f"<p>The link works once and lasts {CONFIRM_HOURS} hours. You stay signed in either way.</p>"
                + _FOOTER_HTML)
    if kind == "reset":
        return (f"{org_name}: reset your 0FFDAYS password",
                f"Someone asked to reset the password for this 0FFDAYS account. If that was you, "
                f"choose a new one here:\n\n{link}\n\nThe link works once and expires in about an "
                f"hour. If it has expired, ask for another on the sign-in page. If you cannot get "
                f"in, your program director can give you a one-time code." + _FOOTER_TEXT,
                "<p>Someone asked to reset the password for this 0FFDAYS account. If that was you, "
                "choose a new one.</p>" + _button(link, "Choose a new password")
                + "<p>The link works once and expires in about an hour. If it has expired, ask for "
                "another on the sign-in page. If you cannot get in, your program director can give "
                "you a one-time code.</p>" + _FOOTER_HTML)
    return (f"{org_name}: your 0FFDAYS password was changed",
            "The password for your 0FFDAYS account was just changed. If that was you, there is "
            "nothing to do. If it was not, ask your program director for a one-time code right "
            "away and choose a new password." + _FOOTER_TEXT,
            "<p>The password for your 0FFDAYS account was just changed. If that was you, there is "
            "nothing to do. If it was not, ask your program director for a one-time code right away "
            "and choose a new password.</p>" + _FOOTER_HTML)


def _org_name(conn: sqlite3.Connection, user_id: int) -> str:
    row = conn.execute("SELECT o.name FROM users u JOIN organizations o ON o.id = u.org_id WHERE u.id = ?",
                       (user_id,)).fetchone()
    return row["name"] if row else "0FFDAYS"


def _send(conn: sqlite3.Connection, *, user_id: int, to: str, kind: str, token: str = "") -> bool:
    """Queue one message and send just that one now. True only if it was handed to the provider.

    A broken provider must never break the page the person is on: whatever happens
    here is swallowed and logged, and the message stays queued for the hourly retry.
    """
    if not mail_available():
        return False
    link = _link({"confirm": "confirm", "reset": "reset"}.get(kind, ""), token) if token else ""
    subject, text, html = _compose(kind, _org_name(conn, user_id), link)
    try:
        queued = mailer.enqueue(
            conn, to_email=to, subject=subject, html=html, text=text, kind=mailer.Kind.TRANSACTIONAL,
            dedupe_key=f"staff_{kind}:{user_id}:{secrets.token_hex(6)}", user_id=user_id)
        if queued is None:
            return False
        mailer.flush(conn, only_ids=[queued])
        row = conn.execute("SELECT status FROM email_outbox WHERE id = ?", (queued,)).fetchone()
        return bool(row and row["status"] == "sent")
    except Exception:  # noqa: BLE001 - never let mail break sign-in
        logger.exception("staff mail (%s) failed for user %s", kind, user_id)
        return False


# -------------------------------------------------------------------- confirm
def send_confirmation(conn: sqlite3.Connection, user_id: int) -> bool:
    """Email the confirm link to the address on file. False if not sent (no provider,
    already confirmed, asked too often, or the mail did not go)."""
    row = pw.get(conn, user_id)
    if row is None or row["email_verified_at"] or not mail_available():
        return False
    token = _issue(conn, user_id, "confirm", row["email"], timedelta(hours=CONFIRM_HOURS))
    if token is None:
        return False
    return _send(conn, user_id=user_id, to=row["email"], kind="confirm", token=token)


def confirm(conn: sqlite3.Connection, token: str) -> bool:
    row = _spend(conn, token, "confirm")
    if row is None:
        conn.commit()
        return False
    conn.execute("UPDATE credentials SET email_verified_at = ?, updated_at = ? WHERE user_id = ?",
                 (_iso(_now()), _iso(_now()), row["user_id"]))
    conn.commit()
    return True


# --------------------------------------------------------------------- forgot
def send_reset(conn: sqlite3.Connection, email: str) -> None:
    """Email a reset link if, and only if, this is a confirmed, active staff address.

    Returns nothing on purpose: the caller must not be able to tell the cases apart.
    """
    if not mail_available():
        return
    try:
        address = pw.check_email(email)
    except pw.PasswordError:
        return
    row = pw.by_email(conn, address)
    if row is None or not row["email_verified_at"]:
        return
    user = conn.execute("SELECT active, role FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if user is None or not user["active"] or user["role"] not in ("coach", "director"):
        return
    if mailer.is_suppressed(conn, address):
        return
    token = _issue(conn, int(row["user_id"]), "reset", row["email"], timedelta(minutes=RESET_MINUTES))
    if token is None:
        return
    _send(conn, user_id=int(row["user_id"]), to=row["email"], kind="reset", token=token)


def reset_with_link(conn: sqlite3.Connection, token: str, new_password: str) -> int | None:
    """Spend a reset link and set the password. Returns the user id, or None if the link is
    no good. A weak password raises PasswordError and leaves the link usable."""
    row = conn.execute(
        "SELECT t.id, t.user_id, t.expires_at, t.used_at, t.email, c.email AS current_email "
        "FROM email_tokens t LEFT JOIN credentials c ON c.user_id = t.user_id "
        "WHERE t.token_hash = ? AND t.purpose = 'reset'", (_digest(token or ""),)).fetchone()
    if row is None or row["used_at"] is not None or row["current_email"] != row["email"]:
        pw.burn_time()
        return None
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
    except ValueError:
        return None
    pw.check_password(new_password, row["current_email"])   # raises, link NOT spent
    spent = _spend(conn, token, "reset")
    if spent is None:
        return None
    conn.execute("UPDATE credentials SET pw_hash = ?, reset_hash = NULL, reset_expires = NULL, "
                 "updated_at = ? WHERE user_id = ?",
                 (pw.hash_password(new_password), _iso(_now()), spent["user_id"]))
    conn.execute("DELETE FROM email_tokens WHERE user_id = ? AND purpose = 'reset'", (spent["user_id"],))
    pw.end_sessions(conn, int(spent["user_id"]))
    conn.commit()
    _send(conn, user_id=int(spent["user_id"]), to=spent["email"], kind="changed")
    return int(spent["user_id"])


# --------------------------------------------------------------- change address
def change_email(conn: sqlite3.Connection, user_id: int, new_email: str, current_password: str) -> bool:
    """Move the sign-in address. Needs the current password. The new address starts
    unconfirmed, every link sent to the old one dies, and a confirm link is sent."""
    row = pw.get(conn, user_id)
    if row is None:
        raise pw.PasswordError("Set a password first.")
    if not pw.verify_password(current_password or "", row["pw_hash"]):
        raise pw.PasswordError("The current password is not right.")
    address = pw.check_email(new_email)
    other = pw.by_email(conn, address)
    if other is not None and int(other["user_id"]) != user_id:
        raise pw.PasswordError("That email cannot be used for sign-in. Try a different one.")
    conn.execute("UPDATE credentials SET email = ?, email_verified_at = NULL, reset_hash = NULL, "
                 "reset_expires = NULL, updated_at = ? WHERE user_id = ?", (address, _iso(_now()), user_id))
    conn.execute("DELETE FROM email_tokens WHERE user_id = ?", (user_id,))
    conn.execute("UPDATE users SET email = ? WHERE id = ?", (address, user_id))
    conn.commit()
    send_confirmation(conn, user_id)
    return True


def status(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    row = pw.get(conn, user_id)
    return {"verified": bool(row and row["email_verified_at"]), "mail": mail_available()}
