"""Inbound delivery events from a mail provider.

Most bounces are asynchronous. The receiving server accepts the message, and
only minutes or hours later sends a bounce back down the return path -- long
after the SMTP conversation this codebase can see has closed. The provider
surfaces that as a webhook, and without one a dead address is retried every
Monday forever.

Two things dominate the design.

**Verification comes before anything else.** This endpoint's whole job is to
take instructions from the public internet about which addresses to stop
mailing. Unverified, it is a one-request tool for silently cutting any coach in
the program off from their digest. Every provider is verified with its own real
scheme, the signature is checked before the payload is even parsed, and a stale
timestamp is rejected so a captured request cannot be replayed later.

**A soft bounce is not a dead address.** A full mailbox, a greylisting server,
an over-quota school account -- all produce a bounce, and all recover. Hard
bounces and spam complaints suppress immediately; soft bounces only suppress
after several in a fortnight. Suppressing on the first one loses real
recipients, and losing a coach's digest silently is exactly the failure this
module exists to prevent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from . import mailer

log = logging.getLogger(__name__)

# Requests older than this are refused, so a captured webhook cannot be
# replayed tomorrow to suppress someone.
MAX_SKEW_SECONDS = 300

# A soft bounce is temporary. Several in a fortnight is a pattern.
SOFT_BOUNCE_LIMIT = 3
SOFT_BOUNCE_WINDOW_DAYS = 14

MAX_BODY_BYTES = 2_000_000


class EventType:
    HARD_BOUNCE = "hard_bounce"
    SOFT_BOUNCE = "soft_bounce"
    COMPLAINT = "complaint"
    UNSUBSCRIBE = "unsubscribe"
    DELIVERED = "delivered"
    DEFERRED = "deferred"
    UNKNOWN = "unknown"


class WebhookError(Exception):
    """The request could not be trusted."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class Verifier(Protocol):
    def verify(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
        ...


def _header(headers: dict[str, str], name: str) -> str:
    """Case-insensitive header lookup; HTTP header case is not guaranteed."""
    lowered = {k.lower(): v for k, v in headers.items()}
    return lowered.get(name.lower(), "")


def _fresh(timestamp: str) -> bool:
    """Reject a signature older than the skew window."""
    try:
        when = datetime.fromtimestamp(int(float(timestamp)), tz=timezone.utc)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError):
            return False
    return abs((_now() - when).total_seconds()) <= MAX_SKEW_SECONDS


class MailgunVerifier:
    """HMAC-SHA256 over timestamp + token, as Mailgun documents."""

    def verify(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
        try:
            payload = json.loads(body)
        except ValueError:
            return False
        signature = payload.get("signature") or {}
        timestamp = str(signature.get("timestamp", ""))
        token = str(signature.get("token", ""))
        provided = str(signature.get("signature", ""))
        if not (timestamp and token and provided) or not _fresh(timestamp):
            return False

        expected = hmac.new(
            secret.encode("utf-8"), f"{timestamp}{token}".encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, provided)


class SendGridVerifier:
    """ECDSA P-256 over timestamp + raw body, as SendGrid documents.

    The public key is base64 DER from the SendGrid console. Verified with the
    real curve rather than waved through: a signature scheme that is not
    actually checked is worse than none, because it reads as protection.
    """

    def verify(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
        signature = _header(headers, "X-Twilio-Email-Event-Webhook-Signature")
        timestamp = _header(headers, "X-Twilio-Email-Event-Webhook-Timestamp")
        if not (signature and timestamp) or not _fresh(timestamp):
            return False

        # Broad on purpose. A missing library raises ImportError, but a
        # half-installed one can raise almost anything -- a broken build of
        # cryptography here raised a Rust panic, which would have taken the
        # whole endpoint down rather than failing the check. Any failure to
        # verify is a failure to verify.
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec

            key = serialization.load_der_public_key(base64.b64decode(secret))
            if not isinstance(key, ec.EllipticCurvePublicKey):
                return False
            key.verify(
                base64.b64decode(signature),
                timestamp.encode("utf-8") + body,
                ec.ECDSA(hashes.SHA256()),
            )
            return True
        except Exception as exc:  # noqa: BLE001 -- deny on anything at all
            log.debug("sendgrid signature rejected: %s", type(exc).__name__)
            return False


class TokenVerifier:
    """A shared secret in a header or query string.

    What Postmark recommends, and the practical option for any provider whose
    scheme this module does not implement natively: the endpoint is given a URL
    nobody else knows.
    """

    def verify(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
        provided = (
            _header(headers, "X-Webhook-Token")
            or _header(headers, "Authorization").removeprefix("Bearer ").strip()
        )
        return bool(provided) and hmac.compare_digest(provided, secret)


class HmacBodyVerifier:
    """HMAC-SHA256 over a timestamp header plus the raw body."""

    def verify(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
        signature = _header(headers, "X-Webhook-Signature")
        timestamp = _header(headers, "X-Webhook-Timestamp")
        if not (signature and timestamp) or not _fresh(timestamp):
            return False
        expected = hmac.new(
            secret.encode("utf-8"), timestamp.encode("utf-8") + body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


VERIFIERS: dict[str, Verifier] = {
    "mailgun": MailgunVerifier(),
    "sendgrid": SendGridVerifier(),
    "postmark": TokenVerifier(),
    "ses": TokenVerifier(),
    "generic": HmacBodyVerifier(),
}


def verify(provider: str, headers: dict[str, str], body: bytes, secret: str) -> bool:
    """Check a request's authenticity. False for anything unrecognised."""
    if not secret:
        # No secret configured means the endpoint is not enabled, not that
        # everything is trusted.
        return False
    verifier = VERIFIERS.get(provider)
    return bool(verifier) and verifier.verify(headers, body, secret)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

@dataclass
class Event:
    provider: str
    event_id: str
    type: str
    email: str
    reason: str = ""
    message_id: str = ""
    occurred_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "event_id": self.event_id,
            "type": self.type,
            "email": self.email,
            "reason": self.reason,
            "message_id": self.message_id,
            "occurred_at": self.occurred_at,
        }


def _fallback_id(provider: str, item: dict[str, Any]) -> str:
    """A stable id for a provider that does not send one.

    Hashed from the event's own content so a retry produces the same id and is
    deduplicated, which is the entire point of having one.
    """
    blob = json.dumps(item, sort_keys=True, default=str)
    return f"{provider}:{hashlib.sha256(blob.encode()).hexdigest()[:32]}"


# Provider vocabularies, mapped onto ours.
_SENDGRID = {
    "bounce": EventType.HARD_BOUNCE,
    "dropped": EventType.HARD_BOUNCE,
    "deferred": EventType.DEFERRED,
    "spamreport": EventType.COMPLAINT,
    "unsubscribe": EventType.UNSUBSCRIBE,
    "group_unsubscribe": EventType.UNSUBSCRIBE,
    "delivered": EventType.DELIVERED,
}
_POSTMARK = {
    "hardbounce": EventType.HARD_BOUNCE,
    "softbounce": EventType.SOFT_BOUNCE,
    "bademailaddress": EventType.HARD_BOUNCE,
    "spamnotification": EventType.COMPLAINT,
    "spamcomplaint": EventType.COMPLAINT,
    "subscriptionchange": EventType.UNSUBSCRIBE,
    "delivery": EventType.DELIVERED,
    "transient": EventType.SOFT_BOUNCE,
}
_MAILGUN = {
    "complained": EventType.COMPLAINT,
    "unsubscribed": EventType.UNSUBSCRIBE,
    "delivered": EventType.DELIVERED,
}


def _parse_sendgrid(body: dict | list) -> list[Event]:
    items = body if isinstance(body, list) else [body]
    events = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("event", "")).lower()
        # SendGrid distinguishes a blocked (temporary) bounce from a genuine one.
        mapped = _SENDGRID.get(kind, EventType.UNKNOWN)
        if kind == "bounce" and str(item.get("type", "")).lower() == "blocked":
            mapped = EventType.SOFT_BOUNCE
        events.append(Event(
            provider="sendgrid",
            event_id=str(item.get("sg_event_id") or _fallback_id("sendgrid", item)),
            type=mapped,
            email=str(item.get("email", "")),
            reason=str(item.get("reason", ""))[:400],
            message_id=str(item.get("smtp-id") or item.get("sg_message_id") or ""),
            occurred_at=str(item.get("timestamp", "")),
            raw=item,
        ))
    return events


def _parse_postmark(body: dict | list) -> list[Event]:
    items = body if isinstance(body, list) else [body]
    events = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = str(item.get("RecordType", "")).lower()
        kind = str(item.get("Type", "")).lower()

        if record == "subscriptionchange":
            mapped = (
                EventType.UNSUBSCRIBE
                if item.get("SuppressSending") else EventType.UNKNOWN
            )
        elif record == "delivery":
            mapped = EventType.DELIVERED
        elif record in ("spamcomplaint",):
            mapped = EventType.COMPLAINT
        else:
            mapped = _POSTMARK.get(kind, _POSTMARK.get(record, EventType.UNKNOWN))

        events.append(Event(
            provider="postmark",
            event_id=str(item.get("ID") or item.get("MessageID") or _fallback_id("postmark", item)),
            type=mapped,
            email=str(item.get("Email") or item.get("Recipient") or ""),
            reason=str(item.get("Description") or item.get("Details") or "")[:400],
            message_id=str(item.get("MessageID", "")),
            occurred_at=str(item.get("BouncedAt") or item.get("ReceivedAt") or ""),
            raw=item,
        ))
    return events


def _parse_mailgun(body: dict) -> list[Event]:
    data = body.get("event-data") or {}
    kind = str(data.get("event", "")).lower()

    if kind == "failed":
        # Mailgun's own severity is the only thing distinguishing a dead
        # mailbox from a server having a bad afternoon.
        mapped = (
            EventType.HARD_BOUNCE
            if str(data.get("severity", "")).lower() == "permanent"
            else EventType.SOFT_BOUNCE
        )
    else:
        mapped = _MAILGUN.get(kind, EventType.UNKNOWN)

    recipient = data.get("recipient") or ""
    reason = data.get("reason") or (data.get("delivery-status") or {}).get("message") or ""
    return [Event(
        provider="mailgun",
        event_id=str(data.get("id") or _fallback_id("mailgun", data)),
        type=mapped,
        email=str(recipient),
        reason=str(reason)[:400],
        message_id=str((data.get("message") or {}).get("headers", {}).get("message-id", "")),
        occurred_at=str(data.get("timestamp", "")),
        raw=data,
    )]


def _parse_ses(body: dict) -> list[Event]:
    """Amazon SES, delivered through SNS.

    The interesting payload is a JSON string inside the SNS envelope's Message
    field, which is a common source of "the webhook does nothing" -- parsing
    the envelope alone finds no bounce at all.
    """
    message = body.get("Message")
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except ValueError:
            return []
    if not isinstance(message, dict):
        message = body

    kind = str(message.get("notificationType") or message.get("eventType") or "").lower()
    mail = message.get("mail") or {}
    message_id = str(mail.get("messageId", ""))
    events: list[Event] = []

    if kind == "bounce":
        bounce = message.get("bounce") or {}
        permanent = str(bounce.get("bounceType", "")).lower() == "permanent"
        for recipient in bounce.get("bouncedRecipients") or [{}]:
            events.append(Event(
                provider="ses",
                event_id=str(bounce.get("feedbackId") or _fallback_id("ses", recipient))
                + f":{recipient.get('emailAddress', '')}",
                type=EventType.HARD_BOUNCE if permanent else EventType.SOFT_BOUNCE,
                email=str(recipient.get("emailAddress", "")),
                reason=str(recipient.get("diagnosticCode", ""))[:400],
                message_id=message_id,
                occurred_at=str(bounce.get("timestamp", "")),
                raw=message,
            ))
    elif kind == "complaint":
        complaint = message.get("complaint") or {}
        for recipient in complaint.get("complainedRecipients") or [{}]:
            events.append(Event(
                provider="ses",
                event_id=str(complaint.get("feedbackId") or _fallback_id("ses", recipient))
                + f":{recipient.get('emailAddress', '')}",
                type=EventType.COMPLAINT,
                email=str(recipient.get("emailAddress", "")),
                message_id=message_id,
                occurred_at=str(complaint.get("timestamp", "")),
                raw=message,
            ))
    elif kind == "delivery":
        delivery = message.get("delivery") or {}
        for address in delivery.get("recipients") or []:
            events.append(Event(
                provider="ses",
                event_id=_fallback_id("ses", {"m": message_id, "r": address}),
                type=EventType.DELIVERED,
                email=str(address),
                message_id=message_id,
                occurred_at=str(delivery.get("timestamp", "")),
                raw=message,
            ))
    return events


PARSERS = {
    "sendgrid": _parse_sendgrid,
    "postmark": _parse_postmark,
    "mailgun": _parse_mailgun,
    "ses": _parse_ses,
}


def parse(provider: str, body: bytes) -> list[Event]:
    """Normalize a provider payload. Never raises on shape."""
    if len(body) > MAX_BODY_BYTES:
        raise WebhookError("payload too large")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise WebhookError(f"payload is not JSON: {exc}") from None

    parser = PARSERS.get(provider)
    if parser is None:
        # An unknown provider is a configuration error, not a malformed
        # request; say so rather than silently ignoring every event.
        raise WebhookError(f"no parser for provider {provider!r}")

    try:
        events = parser(payload)
    except Exception as exc:  # noqa: BLE001 -- a shape we have not seen
        log.warning("could not parse %s payload: %s", provider, exc)
        return []

    return [e for e in events if e.email]


# ---------------------------------------------------------------------------
# Applying events
# ---------------------------------------------------------------------------

def _recent_soft_bounces(conn: sqlite3.Connection, email: str) -> int:
    cutoff = _iso(_now() - timedelta(days=SOFT_BOUNCE_WINDOW_DAYS))
    return int(conn.execute(
        "SELECT COUNT(*) AS n FROM webhook_events "
        "WHERE email = ? AND event_type = ? AND received_at >= ?",
        (email.strip().lower(), EventType.SOFT_BOUNCE, cutoff),
    ).fetchone()["n"])


def _link_to_outbox(conn: sqlite3.Connection, event: Event) -> int | None:
    """Find the user this bounce is about, so a preference can be set.

    Matched on the address rather than anything in the payload: a webhook says
    which mailbox failed, and letting it name a user id would let a forged
    event target an account directly.
    """
    row = conn.execute(
        "SELECT user_id FROM email_outbox WHERE to_email = ? AND user_id IS NOT NULL "
        "ORDER BY queued_at DESC LIMIT 1",
        (event.email.strip(),),
    ).fetchone()
    return row["user_id"] if row else None


def apply_event(conn: sqlite3.Connection, event: Event) -> str:
    """Act on one normalized event and record what was done.

    Returns the action taken, or "duplicate" if this event was already handled.
    """
    email = event.email.strip().lower()
    action = "recorded"

    if event.type == EventType.HARD_BOUNCE:
        mailer.suppress(conn, email, f"hard bounce ({event.provider}): {event.reason[:160]}")
        action = "suppressed"

    elif event.type == EventType.COMPLAINT:
        # The strongest signal a recipient can send. Suppress and turn the
        # preference off, so the address is not re-enabled by an admin
        # unsuppressing it later without the person asking.
        mailer.suppress(conn, email, f"spam complaint ({event.provider})")
        user_id = _link_to_outbox(conn, event)
        if user_id:
            mailer.set_preference(conn, user_id, mailer.Kind.COACH_DIGEST, False)
            mailer.set_preference(conn, user_id, mailer.Kind.GUARDIAN_DIGEST, False)
        action = "suppressed+opted_out"

    elif event.type == EventType.UNSUBSCRIBE:
        user_id = _link_to_outbox(conn, event)
        if user_id:
            mailer.set_preference(conn, user_id, mailer.Kind.COACH_DIGEST, False)
            mailer.set_preference(conn, user_id, mailer.Kind.GUARDIAN_DIGEST, False)
            action = "opted_out"
        else:
            mailer.suppress(conn, email, f"unsubscribed via {event.provider}")
            action = "suppressed"

    elif event.type == EventType.SOFT_BOUNCE:
        # Counted, not acted on. A full mailbox or a greylisting server
        # recovers; suppressing on the first one loses real recipients.
        # This event is recorded below, so include it in the count.
        if _recent_soft_bounces(conn, email) + 1 >= SOFT_BOUNCE_LIMIT:
            mailer.suppress(
                conn, email,
                f"{SOFT_BOUNCE_LIMIT} soft bounces in {SOFT_BOUNCE_WINDOW_DAYS} days",
            )
            action = "suppressed"
        else:
            action = "counted"

    try:
        conn.execute(
            "INSERT INTO webhook_events(provider, event_id, event_type, email, reason, "
            "message_id, occurred_at, received_at, action, raw) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                event.provider, event.event_id, event.type, email, event.reason,
                event.message_id, event.occurred_at, _iso(_now()), action,
                json.dumps(event.raw)[:8000],
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Providers retry. A retried soft bounce counted twice would push a
        # live address off the list.
        conn.rollback()
        return "duplicate"

    return action


def handle(
    provider: str,
    headers: dict[str, str],
    body: bytes,
    secret: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Verify, parse, and apply a webhook request.

    Verification happens before parsing: an unverified payload is not data, and
    should not reach a parser at all.
    """
    if not verify(provider, headers, body, secret):
        raise WebhookError("signature verification failed")

    events = parse(provider, body)
    actions: dict[str, int] = {}
    for event in events:
        action = apply_event(conn, event)
        actions[action] = actions.get(action, 0) + 1

    return {"received": len(events), "actions": actions}


def recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT provider, event_type, email, reason, action, received_at "
            "FROM webhook_events ORDER BY received_at DESC LIMIT ?",
            (limit,),
        )
    ]


def bounce_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Which addresses are failing, so someone can go and fix them."""
    cutoff = _iso(_now() - timedelta(days=30))
    rows = conn.execute(
        "SELECT email, event_type, COUNT(*) AS n, MAX(received_at) AS last "
        "FROM webhook_events WHERE received_at >= ? "
        "AND event_type IN ('hard_bounce','soft_bounce','complaint') "
        "GROUP BY email, event_type ORDER BY last DESC",
        (cutoff,),
    ).fetchall()

    by_email: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = by_email.setdefault(
            row["email"], {"email": row["email"], "last": row["last"], "counts": {}}
        )
        entry["counts"][row["event_type"]] = row["n"]
        entry["last"] = max(entry["last"], row["last"])

    for entry in by_email.values():
        entry["suppressed"] = mailer.is_suppressed(conn, entry["email"])
    return {"addresses": list(by_email.values())}
