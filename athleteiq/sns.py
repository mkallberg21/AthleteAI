"""Amazon SNS message signature verification.

SES delivers bounce notifications through SNS, and SNS signs each message with
a certificate it tells you where to fetch. That last part is the whole problem.

**The certificate URL comes from the message.** Fetch whatever it points at and
an attacker hosts their own certificate, signs their own payload with the
matching key, and the signature verifies perfectly -- they can then suppress any
address in the program. This is the canonical way SNS verification is got wrong,
so the URL is checked against the real SNS hostname pattern before anything is
fetched, and redirects are refused outright: a 302 from a genuine AWS host to
somewhere else would otherwise walk straight through the check.

**A valid AWS signature is not enough either.** Anyone can create an SNS topic
in their own account and have Amazon sign messages for it quite legitimately.
The topic ARN is therefore checked against an allowlist; without that, "signed
by AWS" means only "signed by someone with an AWS account".

Network access is injected rather than imported, so the verification logic is
testable against a generated keypair without reaching the internet -- and so a
deployment can supply its own fetcher with whatever proxy or timeout policy it
needs.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# The only hosts a signing certificate may come from. Covers the standard
# partition and China; GovCloud regions also match the first pattern.
SNS_HOST = re.compile(r"^sns\.[a-z0-9\-]+\.amazonaws\.com(\.cn)?$")

CERT_CACHE_SECONDS = 3600
MAX_CERT_BYTES = 32_768
FETCH_TIMEOUT_SECONDS = 5

# Field order for the string SNS signs. Alphabetical, and specific per message
# type -- a Notification and a SubscriptionConfirmation sign different fields,
# and using the wrong list simply never verifies.
CANONICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "Notification": ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"),
    "SubscriptionConfirmation": (
        "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type",
    ),
    "UnsubscribeConfirmation": (
        "Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type",
    ),
}

Fetcher = Callable[[str], bytes]


class SnsError(Exception):
    """The message could not be trusted."""


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def is_aws_url(url: str) -> bool:
    """Whether a URL is a plausible AWS SNS endpoint over TLS.

    Checked before any request is made. The hostname must match exactly rather
    than merely end with amazonaws.com -- `sns.evil.amazonaws.com.attacker.net`
    ends with nothing useful, but a naive `endswith` on the *host* would also
    accept `notsns.amazonaws.com`.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return bool(SNS_HOST.match(host))


# ---------------------------------------------------------------------------
# Certificate fetching
# ---------------------------------------------------------------------------

_cert_cache: dict[str, tuple[float, bytes]] = {}


def default_fetcher(url: str) -> bytes:
    """Fetch a certificate over HTTPS, refusing redirects.

    Redirects are refused rather than followed because the host check happens
    on the URL in the message: a 302 from a genuine SNS host to an attacker's
    server would pass that check and then serve their certificate.
    """
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise SnsError(f"certificate URL redirected to {newurl!r}")

    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return response.read(MAX_CERT_BYTES + 1)[:MAX_CERT_BYTES]


def fetch_certificate(url: str, fetcher: Fetcher | None = None) -> bytes:
    """Fetch and cache a signing certificate.

    Cached because SNS reuses one certificate across many messages, and a
    bounce storm would otherwise mean one HTTPS round trip per bounce.
    """
    if not is_aws_url(url):
        raise SnsError(f"certificate URL is not an SNS endpoint: {url!r}")

    cached = _cert_cache.get(url)
    if cached and time.time() - cached[0] < CERT_CACHE_SECONDS:
        return cached[1]

    data = (fetcher or default_fetcher)(url)
    if not data:
        raise SnsError("certificate could not be fetched")
    _cert_cache[url] = (time.time(), data)
    return data


def clear_cert_cache() -> None:
    _cert_cache.clear()


# ---------------------------------------------------------------------------
# Canonical string
# ---------------------------------------------------------------------------

def canonical_string(message: dict[str, Any]) -> bytes:
    """The exact bytes SNS signed.

    Every present field appears as name, newline, value, newline, in the order
    AWS specifies. `Subject` is optional and is omitted entirely when absent --
    including it as an empty string produces a different string and a signature
    that never verifies.
    """
    message_type = str(message.get("Type", ""))
    fields = CANONICAL_FIELDS.get(message_type)
    if fields is None:
        raise SnsError(f"unknown SNS message type: {message_type!r}")

    parts = []
    for name in fields:
        if name not in message:
            continue
        value = message[name]
        if value is None:
            continue
        parts.append(f"{name}\n{value}\n")
    return "".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class VerifiedMessage:
    type: str
    topic_arn: str
    message_id: str
    body: str
    subscribe_url: str = ""


def _validity_window(certificate) -> tuple[float, float]:
    """The certificate's validity as POSIX timestamps.

    cryptography 42 renamed these to timezone-aware `*_utc` properties and
    deprecated the naive originals. Both are read so the same code works across
    the versions a deployment might actually have installed, rather than
    crashing on whichever one it does not.
    """
    from datetime import timezone

    def stamp(name: str) -> float:
        value = getattr(certificate, f"{name}_utc", None)
        if value is None:
            value = getattr(certificate, name)
            # The legacy properties are naive but documented as UTC.
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    return stamp("not_valid_before"), stamp("not_valid_after")


def _load_certificate(pem: bytes):
    from cryptography import x509

    try:
        return x509.load_pem_x509_certificate(pem)
    except Exception as exc:  # noqa: BLE001 -- any parse failure is a rejection
        raise SnsError(f"certificate could not be parsed: {type(exc).__name__}") from None


def verify(
    message: dict[str, Any],
    *,
    allowed_topics: Iterable[str],
    fetcher: Fetcher | None = None,
    now: float | None = None,
) -> VerifiedMessage:
    """Verify an SNS message, or raise SnsError explaining what failed.

    The topic allowlist is not optional. Anyone may create an SNS topic in
    their own AWS account and have Amazon sign messages for it entirely
    legitimately, so a valid signature alone establishes only that the sender
    has an AWS account.
    """
    allowed = {t.strip() for t in allowed_topics if t and t.strip()}
    if not allowed:
        raise SnsError("no SNS topic ARNs are configured; the endpoint is disabled")

    topic_arn = str(message.get("TopicArn", ""))
    if topic_arn not in allowed:
        raise SnsError(f"message is for an unexpected topic: {topic_arn!r}")

    message_type = str(message.get("Type", ""))
    if message_type not in CANONICAL_FIELDS:
        raise SnsError(f"unknown SNS message type: {message_type!r}")

    signature_b64 = message.get("Signature")
    cert_url = str(message.get("SigningCertURL") or message.get("SigningCertUrl") or "")
    if not signature_b64 or not cert_url:
        raise SnsError("message is not signed")

    version = str(message.get("SignatureVersion", "1"))
    if version not in ("1", "2"):
        raise SnsError(f"unsupported signature version: {version!r}")

    pem = fetch_certificate(cert_url, fetcher)
    certificate = _load_certificate(pem)

    # An expired certificate means either a misconfiguration or a replay of a
    # very old capture; neither should verify.
    stamp = now if now is not None else time.time()
    not_before, not_after = _validity_window(certificate)
    if not (not_before <= stamp <= not_after):
        raise SnsError("signing certificate is not currently valid")

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise SnsError("signing certificate does not carry an RSA key")

    # Version 1 is SHA1, version 2 is SHA256. AWS still emits version 1 for
    # older topics, so both are accepted rather than breaking real traffic.
    algorithm = hashes.SHA256() if version == "2" else hashes.SHA1()

    try:
        public_key.verify(
            base64.b64decode(signature_b64),
            canonical_string(message),
            padding.PKCS1v15(),
            algorithm,
        )
    except Exception:  # noqa: BLE001 -- any failure is a failed verification
        raise SnsError("signature does not match") from None

    return VerifiedMessage(
        type=message_type,
        topic_arn=topic_arn,
        message_id=str(message.get("MessageId", "")),
        body=str(message.get("Message", "")),
        subscribe_url=str(message.get("SubscribeURL", "")),
    )


def confirm_subscription(
    message: VerifiedMessage, fetcher: Fetcher | None = None
) -> bool:
    """Complete an SNS subscription by visiting its confirmation URL.

    Only ever called after `verify` has already established that the message is
    genuinely from AWS and belongs to an allowlisted topic. The URL is host-
    checked again anyway: it is a second attacker-supplied URL that this server
    would otherwise fetch on command.
    """
    if message.type != "SubscriptionConfirmation" or not message.subscribe_url:
        return False
    if not is_aws_url(message.subscribe_url):
        raise SnsError(
            f"subscription URL is not an SNS endpoint: {message.subscribe_url!r}"
        )
    (fetcher or default_fetcher)(message.subscribe_url)
    log.info("confirmed SNS subscription for topic %s", message.topic_arn)
    return True
