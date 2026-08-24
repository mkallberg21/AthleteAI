"""Pre-fetched OCSP responses -- stapling, adapted to a fetched certificate.

In TLS, stapling means the server obtains an OCSP response for its own
certificate and hands it over during the handshake, so the client never has to
ask the responder itself. That removes a round trip from the request path, and
with it the soft-fail window an attacker can open by simply blocking the
request.

An SNS signing certificate arrives as a file over HTTPS, not in a handshake, so
there is no handshake to staple it into. What *is* available is the same
division of labour: fetch the responder's answer ahead of time, verify it once,
keep it, and let verification read the stored answer instead of reaching for the
network while a webhook waits.

That matters for more than latency. Revocation checking soft-fails because
refusing on an unreachable responder would mean an outage at the CA takes down
bounce processing. Once staples are refreshed on a schedule -- with their own
retries, out of band -- refusing a certificate with no fresh staple stops being
an availability risk, because a missing staple is a condition an operator can
see and fix before it matters rather than a race decided per request.

Responses are verified on the way *in*, never on the way out. A staple is only
stored if it was genuinely signed by the issuer, which means the fast path at
verification time is a freshness check rather than another round of
cryptography.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from . import revocation as revocation_mod

log = logging.getLogger(__name__)

# A staple is refreshed once it is within this of expiring, so a scheduled
# refresh has several chances before anything goes stale.
REFRESH_MARGIN = timedelta(hours=6)

# A responder promising a very long validity should not pin one answer for
# that long.
MAX_STAPLE_AGE = timedelta(days=7)


class StapleError(Exception):
    """A staple that cannot be trusted or stored."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def issuer_key_id(issuer) -> str:
    """A stable identifier for the issuing CA.

    Hashed from the public key rather than taken from the subject name: two
    CAs can share a subject across a key rollover, and a staple keyed on the
    name alone would then be matched against the wrong key.
    """
    from cryptography.hazmat.primitives import serialization

    der = issuer.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()[:32]


@dataclass
class Staple:
    serial: str
    issuer_key_id: str
    subject: str
    status: str
    response: bytes
    this_update: str
    next_update: str
    fetched_at: str
    source: str = "prefetch"

    def is_fresh(self, now: datetime | None = None) -> bool:
        """Whether this staple may still be believed."""
        now = now or _now()
        next_update = _parse(self.next_update)
        fetched = _parse(self.fetched_at)

        if next_update is not None and now >= next_update:
            return False
        # A responder that omits nextUpdate, or offers an implausibly distant
        # one, should not be able to pin an answer indefinitely.
        if fetched is not None and now - fetched > MAX_STAPLE_AGE:
            return False
        return True

    def needs_refresh(self, now: datetime | None = None) -> bool:
        now = now or _now()
        next_update = _parse(self.next_update)
        if next_update is None:
            return True
        return now + REFRESH_MARGIN >= next_update

    def to_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "subject": self.subject,
            "status": self.status,
            "this_update": self.this_update,
            "next_update": self.next_update,
            "fetched_at": self.fetched_at,
            "source": self.source,
            "fresh": self.is_fresh(),
            "needs_refresh": self.needs_refresh(),
        }


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def verify_and_parse(response_der: bytes, certificate, issuer) -> Staple:
    """Check a raw OCSP response and turn it into a storable staple.

    Everything is checked here so that reading a staple later is a freshness
    test rather than a second round of signature verification -- and so an
    unverifiable response can never reach the store at all.
    """
    from cryptography.x509 import ocsp

    try:
        response = ocsp.load_der_ocsp_response(response_der)
    except Exception as exc:  # noqa: BLE001
        raise StapleError(f"response could not be parsed: {type(exc).__name__}") from None

    if response.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
        raise StapleError(f"responder returned {response.response_status.name}")

    if not revocation_mod._verify_response_signature(response, issuer):
        raise StapleError("response signature did not verify")

    if response.serial_number != certificate.serial_number:
        raise StapleError("response is for a different certificate")

    this_update = revocation_mod._field(response, "this_update")
    next_update = revocation_mod._field(response, "next_update")
    now = _now()
    if this_update and this_update > now + timedelta(minutes=5):
        raise StapleError("response is dated in the future")
    if next_update and next_update < now:
        raise StapleError("response has already expired")

    if response.certificate_status == ocsp.OCSPCertStatus.REVOKED:
        status = revocation_mod.Status.REVOKED
    elif response.certificate_status == ocsp.OCSPCertStatus.GOOD:
        status = revocation_mod.Status.GOOD
    else:
        raise StapleError("responder does not know this certificate")

    return Staple(
        serial=str(certificate.serial_number),
        issuer_key_id=issuer_key_id(issuer),
        subject=certificate.subject.rfc4514_string()[:200],
        status=status,
        response=response_der,
        this_update=_iso(this_update) if this_update else "",
        next_update=_iso(next_update) if next_update else "",
        fetched_at=_iso(now),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def put(conn: sqlite3.Connection, staple: Staple, source: str = "prefetch") -> None:
    conn.execute(
        "INSERT INTO ocsp_staples(serial, issuer_key_id, subject, status, response, "
        "this_update, next_update, fetched_at, source) VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(serial, issuer_key_id) DO UPDATE SET "
        "  status=excluded.status, response=excluded.response, "
        "  this_update=excluded.this_update, next_update=excluded.next_update, "
        "  fetched_at=excluded.fetched_at, source=excluded.source",
        (
            staple.serial, staple.issuer_key_id, staple.subject, staple.status,
            staple.response, staple.this_update, staple.next_update,
            staple.fetched_at, source,
        ),
    )
    conn.commit()


def get(conn: sqlite3.Connection, certificate, issuer) -> Staple | None:
    row = conn.execute(
        "SELECT * FROM ocsp_staples WHERE serial = ? AND issuer_key_id = ?",
        (str(certificate.serial_number), issuer_key_id(issuer)),
    ).fetchone()
    if row is None:
        return None
    return Staple(
        serial=row["serial"], issuer_key_id=row["issuer_key_id"],
        subject=row["subject"], status=row["status"], response=row["response"],
        this_update=row["this_update"], next_update=row["next_update"],
        fetched_at=row["fetched_at"], source=row["source"],
    )


def staple_response(
    conn: sqlite3.Connection,
    response_der: bytes,
    certificate,
    issuer,
    source: str = "supplied",
) -> Staple:
    """Verify a response supplied from outside and store it.

    The literal form of stapling available here: an operator, a sidecar, or a
    provider that starts offering one can hand over a response and it is
    checked and kept exactly like a prefetched one.
    """
    staple = verify_and_parse(response_der, certificate, issuer)
    # Set on the object as well as in the row: a returned staple that claims a
    # different origin from the one stored is a small lie that costs an hour
    # when someone is working out where an answer came from.
    staple.source = source
    put(conn, staple, source)
    return staple


def refresh(
    conn: sqlite3.Connection,
    certificate,
    issuer,
    fetcher: revocation_mod.Fetcher | None = None,
    force: bool = False,
) -> Staple | None:
    """Fetch a fresh OCSP response for one certificate and store it.

    Returns the staple, or None if the responder could not be reached -- a
    failure here is a scheduled job's problem to retry, not a request's.
    """
    existing = get(conn, certificate, issuer)
    if existing and not force and not existing.needs_refresh():
        return existing

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509 import ocsp

    urls = revocation_mod.ocsp_urls(certificate)
    if not urls:
        return None

    request = (
        ocsp.OCSPRequestBuilder()
        .add_certificate(certificate, issuer, hashes.SHA1())
        .build()
        .public_bytes(Encoding.DER)
    )
    fetch = fetcher or revocation_mod.default_fetcher

    for url in urls:
        try:
            raw = fetch(url, request, "application/ocsp-request")
        except Exception as exc:  # noqa: BLE001 -- try the next responder
            log.warning("could not reach OCSP responder %s: %s", url, exc)
            continue
        try:
            staple = verify_and_parse(raw, certificate, issuer)
        except StapleError as exc:
            log.warning("rejected OCSP response from %s: %s", url, exc)
            continue
        put(conn, staple)
        return staple

    return None


def refresh_chain(
    conn: sqlite3.Connection,
    path: Sequence,
    fetcher: revocation_mod.Fetcher | None = None,
    force: bool = False,
) -> list[Staple]:
    """Refresh staples for every issued certificate in a validated path."""
    staples = []
    for certificate, issuer in zip(path, path[1:]):
        staple = refresh(conn, certificate, issuer, fetcher, force)
        if staple is not None:
            staples.append(staple)
    return staples


def check(
    conn: sqlite3.Connection, certificate, issuer, now: datetime | None = None
) -> revocation_mod.Result | None:
    """Answer from the staple store, or None if there is nothing fresh to say.

    The signature was verified when the staple was stored, so this is a
    freshness test rather than a second round of cryptography -- which is the
    whole reason it can sit on the request path.
    """
    staple = get(conn, certificate, issuer)
    if staple is None:
        return None
    if not staple.is_fresh(now):
        log.warning(
            "staple for %s is stale (next update %s)", staple.subject, staple.next_update
        )
        return None

    if staple.status == revocation_mod.Status.REVOKED:
        raise revocation_mod.RevocationError(
            f"certificate is revoked: stapled response for {staple.subject}"
        )
    return revocation_mod.Result(
        revocation_mod.Status.GOOD, "staple", "", staple.fetched_at
    )


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """What is stored, and whether any of it has gone stale.

    Exists so a missing or stale staple is something an operator sees before it
    matters, rather than something discovered when strict mode starts refusing
    webhooks.
    """
    rows = conn.execute(
        "SELECT * FROM ocsp_staples ORDER BY next_update"
    ).fetchall()
    staples = [
        Staple(
            serial=r["serial"], issuer_key_id=r["issuer_key_id"], subject=r["subject"],
            status=r["status"], response=b"", this_update=r["this_update"],
            next_update=r["next_update"], fetched_at=r["fetched_at"], source=r["source"],
        )
        for r in rows
    ]
    return {
        "total": len(staples),
        "fresh": sum(1 for s in staples if s.is_fresh()),
        "stale": sum(1 for s in staples if not s.is_fresh()),
        "due_refresh": sum(1 for s in staples if s.needs_refresh()),
        "revoked": sum(1 for s in staples if s.status == revocation_mod.Status.REVOKED),
        "staples": [s.to_dict() for s in staples],
    }


def prune(conn: sqlite3.Connection, older_than_days: int = 30) -> int:
    """Drop staples that have been stale long enough to be irrelevant."""
    cutoff = _iso(_now() - timedelta(days=older_than_days))
    cur = conn.execute(
        "DELETE FROM ocsp_staples WHERE next_update != '' AND next_update < ?",
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount


def export_staple(staple: Staple) -> str:
    """Base64 form, for handing a staple to another process or host."""
    return base64.b64encode(staple.response).decode()
