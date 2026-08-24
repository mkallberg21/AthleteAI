"""Outbound email: queueing, retries, suppression, and unsubscribe.

Composing a digest and actually getting it into a coach's inbox are different
problems, and the second one is where weekly email quietly stops working.

Four things this exists to get right:

* **Queue, then send.** A Monday job that mails a hundred coaches inside one
  SMTP session loses the whole week when the ninetieth times out. Composition
  writes rows; delivery drains them and can be re-run.
* **Idempotent queueing.** Every message carries a dedupe key. A cron that
  fires twice on a Monday queues once, so nobody gets the same digest twice.
* **Retry the transient, give up on the permanent.** A connection reset is
  worth another go in ten minutes; "no such mailbox" never will be, and
  retrying it forever damages the sending domain for everyone else.
* **An unsubscribe that works in one click.** Legally required for anything
  commercial, and the alternative to someone marking the mail as spam -- which
  costs far more than the one recipient.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .config import CONFIG

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5

# Minutes to wait before each retry. Deliberately spread over hours rather than
# minutes: a mail server that is refusing connections now is usually still
# refusing them in sixty seconds, and hammering it makes the block worse.
BACKOFF_MINUTES = (5, 20, 60, 240)


class Kind:
    COACH_DIGEST = "coach_digest"
    GUARDIAN_DIGEST = "guardian_digest"
    TRANSACTIONAL = "transactional"


# Mail a person cannot opt out of, because it is a direct response to something
# they did rather than a periodic broadcast.
ALWAYS_SEND = {Kind.TRANSACTIONAL}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Unsubscribe tokens
# ---------------------------------------------------------------------------

def _secret() -> bytes:
    """Signing key for unsubscribe links.

    Falls back to a per-database constant when unset so links still work in
    development; a real deployment sets ATHLETEIQ_SECRET, and an unset secret
    means links are forgeable, not broken.
    """
    return (CONFIG.secret_key or "athleteiq-dev-secret").encode("utf-8")


def unsubscribe_token(user_id: int, kind: str) -> str:
    """A signed token identifying one person and one kind of mail.

    Signed rather than random so it needs no storage and cannot be enumerated:
    guessing another coach's unsubscribe link would otherwise let anyone switch
    off someone else's mail.
    """
    payload = f"{user_id}:{kind}"
    signature = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{kind}.{signature}"


def verify_unsubscribe(token: str) -> tuple[int, str] | None:
    """Return (user_id, kind) if the token is genuine, else None."""
    try:
        user_part, kind, signature = token.split(".", 2)
        user_id = int(user_part)
    except (ValueError, AttributeError):
        return None
    expected = unsubscribe_token(user_id, kind).rsplit(".", 1)[-1]
    # Constant-time: a timing oracle here would let someone forge a token.
    if not hmac.compare_digest(signature, expected):
        return None
    return user_id, kind


def unsubscribe_url(user_id: int, kind: str) -> str:
    base = CONFIG.app_base_url.rstrip("/") if CONFIG.app_base_url else ""
    return f"{base}/api/email/unsubscribe?token={unsubscribe_token(user_id, kind)}"


# ---------------------------------------------------------------------------
# Preferences and suppression
# ---------------------------------------------------------------------------

def set_preference(
    conn: sqlite3.Connection, user_id: int, kind: str, enabled: bool
) -> None:
    conn.execute(
        "INSERT INTO email_preferences(user_id, kind, enabled, updated_at) "
        "VALUES (?,?,?,?) ON CONFLICT(user_id, kind) DO UPDATE SET "
        "enabled = excluded.enabled, updated_at = excluded.updated_at",
        (user_id, kind, 1 if enabled else 0, _iso(_now())),
    )
    conn.commit()


def wants(conn: sqlite3.Connection, user_id: int | None, kind: str) -> bool:
    """Whether this person still wants this kind of mail. Absent means yes."""
    if kind in ALWAYS_SEND or user_id is None:
        return True
    row = conn.execute(
        "SELECT enabled FROM email_preferences WHERE user_id = ? AND kind = ?",
        (user_id, kind),
    ).fetchone()
    return True if row is None else bool(row["enabled"])


def preferences(conn: sqlite3.Connection, user_id: int) -> dict[str, bool]:
    state = {Kind.COACH_DIGEST: True, Kind.GUARDIAN_DIGEST: True}
    for row in conn.execute(
        "SELECT kind, enabled FROM email_preferences WHERE user_id = ?", (user_id,)
    ):
        state[row["kind"]] = bool(row["enabled"])
    return state


def suppress(conn: sqlite3.Connection, email: str, reason: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO email_suppressions(email, reason, created_at) "
        "VALUES (?,?,?)",
        (email.strip().lower(), reason, _iso(_now())),
    )
    conn.commit()


def unsuppress(conn: sqlite3.Connection, email: str) -> None:
    conn.execute(
        "DELETE FROM email_suppressions WHERE email = ?", (email.strip().lower(),)
    )
    conn.commit()


def is_suppressed(conn: sqlite3.Connection, email: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM email_suppressions WHERE email = ?", (email.strip().lower(),)
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------

def looks_like_email(value: str | None) -> bool:
    if not value:
        return False
    value = value.strip()
    if " " in value or value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain and not domain.endswith(".")


def enqueue(
    conn: sqlite3.Connection,
    *,
    to_email: str,
    subject: str,
    html: str,
    text: str,
    kind: str,
    dedupe_key: str,
    user_id: int | None = None,
) -> int | None:
    """Queue one message. Returns its id, or None if it was not queued.

    Not queued means one of: a duplicate, an opt-out, a suppressed address, or
    an address that is not an address. All four are ordinary outcomes rather
    than errors -- a weekly job runs over everyone and most weeks some of them
    do not get mail.
    """
    if not looks_like_email(to_email):
        return None
    if not wants(conn, user_id, kind):
        return None
    if is_suppressed(conn, to_email):
        return None

    now = _now()
    try:
        cur = conn.execute(
            "INSERT INTO email_outbox(user_id, to_email, subject, html_body, text_body, "
            "kind, dedupe_key, queued_at, next_attempt_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                user_id, to_email.strip(), subject, html, text, kind,
                dedupe_key, _iso(now), _iso(now),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        # Already queued this exact message. The cron ran twice; that is fine.
        return None


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

@dataclass
class SendResult:
    ok: bool
    permanent: bool = False
    error: str = ""


class Transport(Protocol):
    """Where a mail provider plugs in."""

    def send(
        self, to_email: str, subject: str, html: str, text: str, headers: dict[str, str]
    ) -> SendResult:
        ...


class SmtpTransport:
    """Delivery over SMTP using the standard library."""

    def send(
        self, to_email: str, subject: str, html: str, text: str, headers: dict[str, str]
    ) -> SendResult:
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = CONFIG.smtp_from
        message["To"] = to_email
        for name, value in headers.items():
            message[name] = value
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        try:
            with smtplib.SMTP(CONFIG.smtp_host, CONFIG.smtp_port, timeout=20) as server:
                server.starttls()
                if CONFIG.smtp_user:
                    server.login(CONFIG.smtp_user, CONFIG.smtp_password)
                server.send_message(message)
            return SendResult(ok=True)
        except smtplib.SMTPRecipientsRefused as exc:
            return SendResult(ok=False, permanent=True, error=str(exc))
        except smtplib.SMTPResponseException as exc:
            # 5xx is the server saying "never"; 4xx is "not right now".
            return SendResult(
                ok=False, permanent=500 <= exc.smtp_code < 600, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 -- network faults are transient
            return SendResult(ok=False, error=str(exc))


class ConsoleTransport:
    """Logs instead of sending. The default when no SMTP host is configured.

    Deliberately reports success: in development the queue should drain and be
    observable, not pile up pretending the mail server is down.
    """

    def send(
        self, to_email: str, subject: str, html: str, text: str, headers: dict[str, str]
    ) -> SendResult:
        log.info("[email] to=%s subject=%s", to_email, subject)
        return SendResult(ok=True)


def default_transport() -> Transport:
    return SmtpTransport() if CONFIG.smtp_configured else ConsoleTransport()


def _headers(row: sqlite3.Row) -> dict[str, str]:
    """Headers every message carries.

    List-Unsubscribe is what turns a "this is spam" click into a quiet opt-out
    in most modern clients, which protects deliverability for every other
    recipient on the domain.
    """
    headers = {
        "Message-ID": (
            f"<{row['kind']}-{row['id']}-"
            f"{hashlib.sha256(row['dedupe_key'].encode()).hexdigest()[:12]}"
            f"@athleteiq>"
        ),
        "Auto-Submitted": "auto-generated",
    }
    if row["user_id"] and row["kind"] not in ALWAYS_SEND:
        url = unsubscribe_url(row["user_id"], row["kind"])
        if url.startswith("http"):
            headers["List-Unsubscribe"] = f"<{url}>"
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return headers


def flush(
    conn: sqlite3.Connection,
    transport: Transport | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> dict[str, int]:
    """Attempt delivery of everything due. Safe to call repeatedly."""
    transport = transport or default_transport()
    now = now or _now()
    stats = {"sent": 0, "retrying": 0, "failed": 0, "suppressed": 0}

    rows = conn.execute(
        "SELECT * FROM email_outbox WHERE status = 'queued' AND next_attempt_at <= ? "
        "ORDER BY queued_at LIMIT ?",
        (_iso(now), limit),
    ).fetchall()

    for row in rows:
        # Someone may have unsubscribed between queueing and sending.
        if is_suppressed(conn, row["to_email"]) or not wants(
            conn, row["user_id"], row["kind"]
        ):
            conn.execute(
                "UPDATE email_outbox SET status = 'suppressed' WHERE id = ?", (row["id"],)
            )
            stats["suppressed"] += 1
            continue

        result = transport.send(
            row["to_email"], row["subject"], row["html_body"],
            row["text_body"], _headers(row),
        )
        attempts = int(row["attempts"]) + 1

        if result.ok:
            conn.execute(
                "UPDATE email_outbox SET status = 'sent', attempts = ?, sent_at = ? "
                "WHERE id = ?",
                (attempts, _iso(now), row["id"]),
            )
            stats["sent"] += 1
            continue

        give_up = result.permanent or attempts >= MAX_ATTEMPTS
        if give_up:
            conn.execute(
                "UPDATE email_outbox SET status = 'failed', attempts = ?, last_error = ? "
                "WHERE id = ?",
                (attempts, result.error[:500], row["id"]),
            )
            stats["failed"] += 1
            # A permanently rejected address is retired so the next weekly run
            # does not queue for it again.
            if result.permanent:
                suppress(conn, row["to_email"], f"hard bounce: {result.error[:200]}")
        else:
            delay = BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]
            conn.execute(
                "UPDATE email_outbox SET attempts = ?, last_error = ?, next_attempt_at = ? "
                "WHERE id = ?",
                (
                    attempts, result.error[:500],
                    _iso(now + timedelta(minutes=delay)), row["id"],
                ),
            )
            stats["retrying"] += 1

    conn.commit()
    return stats


def outbox_summary(conn: sqlite3.Connection, limit: int = 50) -> dict[str, Any]:
    """What has been sent, what is stuck, and why.

    Exists so "did the coach actually get it?" has an answer other than a
    shrug.
    """
    counts = {
        row["status"]: row["n"]
        for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status"
        )
    }
    recent = [
        dict(r)
        for r in conn.execute(
            "SELECT id, to_email, subject, kind, status, attempts, last_error, "
            "       queued_at, sent_at FROM email_outbox "
            "ORDER BY queued_at DESC LIMIT ?",
            (limit,),
        )
    ]
    return {"counts": counts, "recent": recent}


def prune(conn: sqlite3.Connection, days: int = 90) -> int:
    """Drop delivered mail past the retention window. Failures are kept."""
    cutoff = _iso(_now() - timedelta(days=days))
    cur = conn.execute(
        "DELETE FROM email_outbox WHERE status = 'sent' AND sent_at < ?", (cutoff,)
    )
    conn.commit()
    return cur.rowcount
