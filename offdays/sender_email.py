"""The address a coach or director's messages are sent on behalf of.

0FFDAYS sends parent emails from its own verified mail domain (a message from a Gmail or Outlook address would be
rejected by the receiving server, because 0FFDAYS is not Google or Microsoft). What makes it THEIR message is the name on the
From line and where a reply goes. So the one thing needed from the sender is an address they have proved is theirs:

1. They enter it in the Families screen's message box.
2. 0FFDAYS emails that address a link. Only someone who can open that mailbox can use it.
3. Clicking it confirms the address. From then on, every message they send says it is on their behalf and a parent's
   reply lands in their own inbox, in whatever email platform they use there.

Nothing here reads their inbox or sends from their account. An address that has not been confirmed is never used as a
reply address: a typo must not send a parent's reply to a stranger.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape

from . import mailer

logger = logging.getLogger(__name__)

CONFIRM_HOURS = 24
HOURLY_LIMIT = 5


class SenderEmailError(ValueError):
    """Something the person can fix: a bad address, or too many requests."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _digest(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def valid_address(email: str | None) -> str:
    """The address, trimmed and lower-cased, or '' when it is not one plain address."""
    e = (email or "").strip().lower()
    if not mailer.looks_like_email(e) or any(c in e for c in " \r\n\t,;<>\"'()"):
        return ""
    return e


def status(conn: sqlite3.Connection, user_id: int) -> dict[str, object]:
    """{email, confirmed, pending}: what the message box shows."""
    row = conn.execute("SELECT * FROM sender_emails WHERE user_id = ?", (user_id,)).fetchone()
    if row is not None and row["confirmed_at"]:
        return {"email": row["email"], "confirmed": True, "pending": False}
    # An address already confirmed for email sign-in is proved just as well.
    cred = conn.execute("SELECT email, email_verified_at FROM credentials WHERE user_id = ?", (user_id,)).fetchone()
    if cred is not None and cred["email_verified_at"] and valid_address(cred["email"]):
        return {"email": cred["email"], "confirmed": True, "pending": False}
    if row is not None and row["token_hash"]:
        try:
            live = datetime.fromisoformat(row["expires_at"]) > _now()
        except (TypeError, ValueError):
            live = False
        return {"email": row["email"], "confirmed": False, "pending": live}
    return {"email": "", "confirmed": False, "pending": False}


def confirmed_address(conn: sqlite3.Connection, user_id: int | None) -> str:
    """Where a reply goes: the sender's own address, only once they have proved it is theirs."""
    if not user_id:
        return ""
    s = status(conn, int(user_id))
    return str(s["email"]) if s["confirmed"] else ""


def _compose(org_name: str, link: str) -> tuple[str, str, str]:
    subject = f"{org_name}: confirm your email for 0FFDAYS messages"
    text = (
        "Confirm that this is your email address:\n\n"
        f"{link}\n\n"
        "After you do, the emails you send to parents from 0FFDAYS say they are sent on your behalf, and when a "
        "parent replies, the reply comes to this inbox. 0FFDAYS never reads your email or sends from your account.\n\n"
        f"The link works once and lasts {CONFIRM_HOURS} hours. If you did not ask for this, ignore it and nothing changes."
    )
    html = (
        "<p>Confirm that this is your email address.</p>"
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;background:#111;color:#fff;'
        'text-decoration:none;border-radius:6px">Confirm my email</a></p>'
        "<p>After you do, the emails you send to parents from 0FFDAYS say they are sent on your behalf, and when a "
        "parent replies, the reply comes to this inbox. 0FFDAYS never reads your email or sends from your account.</p>"
        f'<p style="color:#666;font-size:90%">The link works once and lasts {CONFIRM_HOURS} hours. If you did not ask '
        "for this, ignore it and nothing changes.</p>"
    )
    return subject, html, text


def request(conn: sqlite3.Connection, user_id: int, email: str) -> dict[str, object]:
    """Email a confirm link to this address. Raises SenderEmailError for a bad address or too many asks."""
    address = valid_address(email)
    if not address:
        raise SenderEmailError("That does not look like one email address.")
    if not mailer.provider_ready():
        raise SenderEmailError("This server cannot send email yet, so there is nothing to confirm with.")
    now = _now()
    row = conn.execute("SELECT * FROM sender_emails WHERE user_id = ?", (user_id,)).fetchone()
    count, window = 0, now
    if row is not None and row["window_start"]:
        try:
            started = datetime.fromisoformat(row["window_start"])
        except ValueError:
            started = now
        if now - started < timedelta(hours=1):
            count, window = int(row["sent_count"]), started
    if count >= HOURLY_LIMIT:
        raise SenderEmailError("That is a lot of emails in an hour. Try again a little later.")
    token = secrets.token_urlsafe(32)
    keep_confirmed = row is not None and row["confirmed_at"] and row["email"] == address
    conn.execute(
        "INSERT INTO sender_emails(user_id, email, confirmed_at, token_hash, expires_at, window_start, sent_count) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET email = excluded.email, "
        "confirmed_at = ?, token_hash = excluded.token_hash, expires_at = excluded.expires_at, "
        "window_start = excluded.window_start, sent_count = excluded.sent_count",
        (user_id, address, row["confirmed_at"] if keep_confirmed else None, _digest(token),
         _iso(now + timedelta(hours=CONFIRM_HOURS)), _iso(window), count + 1,
         row["confirmed_at"] if keep_confirmed else None))
    conn.commit()
    org = conn.execute("SELECT o.name FROM users u JOIN organizations o ON o.id = u.org_id WHERE u.id = ?",
                       (user_id,)).fetchone()
    base = mailer.CONFIG.app_base_url.rstrip("/") if mailer.CONFIG.app_base_url else ""
    link = f"{base}/app/index.html?sender={token}"
    subject, html, text = _compose(org["name"] if org else "0FFDAYS", link)
    sent = False
    try:
        queued = mailer.enqueue(conn, to_email=address, subject=subject, html=html, text=text,
                                kind=mailer.Kind.TRANSACTIONAL,
                                dedupe_key=f"sender_confirm:{user_id}:{secrets.token_hex(6)}", user_id=user_id)
        if queued is not None:
            mailer.flush(conn, only_ids=[queued])
            r = conn.execute("SELECT status FROM email_outbox WHERE id = ?", (queued,)).fetchone()
            sent = bool(r and r["status"] == "sent")
    except Exception:  # noqa: BLE001 - a broken provider must not break the page
        logger.exception("sender confirmation mail failed for user %s", user_id)
    return {**status(conn, user_id), "sent": sent}


def confirm(conn: sqlite3.Connection, token: str) -> str:
    """Spend a confirm link. Returns the confirmed address, or '' if the link is wrong, used or expired."""
    if not token or len(token) > 200:
        return ""
    row = conn.execute("SELECT * FROM sender_emails WHERE token_hash = ?", (_digest(token),)).fetchone()
    if row is None:
        return ""
    try:
        if datetime.fromisoformat(row["expires_at"]) <= _now():
            return ""
    except (TypeError, ValueError):
        return ""
    conn.execute("UPDATE sender_emails SET confirmed_at = ?, token_hash = NULL WHERE user_id = ?",
                 (_iso(_now()), row["user_id"]))
    conn.commit()
    return str(row["email"])
