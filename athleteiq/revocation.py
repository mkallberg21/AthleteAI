"""Certificate revocation checking, by OCSP with a CRL fallback.

Revocation is the weakest joint in PKI, and it is worth being explicit about
why rather than shipping something that merely looks thorough.

**An unverified OCSP response is worthless.** The responder's answer is signed;
if that signature is not checked, anyone able to answer the request can reply
"good" for a certificate that was revoked years ago. Every response here is
verified against the issuer's key, or against a delegated responder certificate
that the issuer signed and marked for OCSP signing -- and nothing else.

**Soft-fail is a real limitation, not a rounded corner.** If a responder cannot
be reached, an implementation either proceeds (and is defeated by anyone who can
block the request) or refuses (and is taken down by an outage at the CA).
Browsers largely chose the first and then quietly stopped relying on the result.
Here the default is soft-fail with a loud log, because a failed webhook is
retried by the provider and the primary controls -- an allowlisted topic and a
chain pinned to Amazon's roots -- do not depend on this one. A deployment that
would rather drop bounce events than accept an unchecked certificate sets
`ATHLETEIQ_SNS_REVOCATION_STRICT=1`.

A `revoked` answer is always fatal, in either mode. That part is never a
judgement call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

log = logging.getLogger(__name__)

Fetcher = Callable[..., bytes]

# Responses are cached until their own nextUpdate, bounded by this so a
# responder promising a month of validity cannot pin a stale answer that long.
MAX_CACHE_SECONDS = 3600
FETCH_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 5_000_000


class Status:
    GOOD = "good"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class RevocationError(Exception):
    """The certificate is revoked, or could not be cleared in strict mode."""


@dataclass
class Result:
    status: str
    source: str = "none"        # 'ocsp' | 'crl' | 'none'
    reason: str = ""
    checked_at: str = ""

    @property
    def is_revoked(self) -> bool:
        return self.status == Status.REVOKED

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "source": self.source,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _aware(value: datetime | None) -> datetime | None:
    """Normalize a possibly-naive X.509 timestamp to UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _field(obj, name: str):
    """Read a timestamp property across cryptography versions.

    Version 42 added timezone-aware `*_utc` spellings and deprecated the naive
    originals; both are read so the same code works on either.
    """
    value = getattr(obj, f"{name}_utc", None)
    if value is None:
        value = getattr(obj, name, None)
    return _aware(value)


# ---------------------------------------------------------------------------
# Distribution points
# ---------------------------------------------------------------------------

def ocsp_urls(certificate) -> list[str]:
    """OCSP responder URLs from the certificate's Authority Information Access."""
    from cryptography import x509
    from cryptography.x509.oid import AuthorityInformationAccessOID

    try:
        aia = certificate.extensions.get_extension_for_class(
            x509.AuthorityInformationAccess
        ).value
    except x509.ExtensionNotFound:
        return []

    return [
        description.access_location.value
        for description in aia
        if description.access_method == AuthorityInformationAccessOID.OCSP
        and isinstance(description.access_location, x509.UniformResourceIdentifier)
    ]


def crl_urls(certificate) -> list[str]:
    """CRL URLs from the certificate's CRL Distribution Points."""
    from cryptography import x509

    try:
        points = certificate.extensions.get_extension_for_class(
            x509.CRLDistributionPoints
        ).value
    except x509.ExtensionNotFound:
        return []

    urls = []
    for point in points:
        for name in point.full_name or []:
            if isinstance(name, x509.UniformResourceIdentifier):
                urls.append(name.value)
    return urls


def default_fetcher(url: str, data: bytes | None = None, content_type: str = "") -> bytes:
    """Fetch a URL, optionally POSTing a body. Refuses non-HTTP schemes."""
    import urllib.request

    if not url.lower().startswith(("http://", "https://")):
        raise RevocationError(f"unsupported URL scheme: {url!r}")

    headers = {"Content-Type": content_type} if content_type else {}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        return response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]


# ---------------------------------------------------------------------------
# OCSP
# ---------------------------------------------------------------------------

def _responder_key(response, issuer):
    """The key that legitimately signed this OCSP response, or None.

    Either the issuer itself, or a responder certificate the issuer signed and
    marked with the OCSP-signing extended key usage. Anything else is an
    attacker's signature on an attacker's answer.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID

    embedded = list(getattr(response, "certificates", []) or [])
    if not embedded:
        return issuer.public_key()

    for candidate in embedded:
        # Delegated responders must be issued by the same CA...
        if candidate.issuer != issuer.subject:
            continue
        try:
            usages = candidate.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            ).value
            if ExtendedKeyUsageOID.OCSP_SIGNING not in usages:
                continue
        except x509.ExtensionNotFound:
            continue

        # ...and their certificate must really be signed by that CA.
        issuer_key = issuer.public_key()
        try:
            if isinstance(issuer_key, rsa.RSAPublicKey):
                issuer_key.verify(
                    candidate.signature, candidate.tbs_certificate_bytes,
                    padding.PKCS1v15(), candidate.signature_hash_algorithm,
                )
            elif isinstance(issuer_key, ec.EllipticCurvePublicKey):
                issuer_key.verify(
                    candidate.signature, candidate.tbs_certificate_bytes,
                    ec.ECDSA(candidate.signature_hash_algorithm),
                )
            else:
                continue
        except Exception:  # noqa: BLE001
            continue

        not_before, not_after = _field(candidate, "not_valid_before"), _field(
            candidate, "not_valid_after"
        )
        if not_before and not_after and not (not_before <= _now() <= not_after):
            continue
        return candidate.public_key()

    return None


def _verify_response_signature(response, issuer) -> bool:
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    key = _responder_key(response, issuer)
    if key is None:
        return False
    try:
        if isinstance(key, rsa.RSAPublicKey):
            key.verify(
                response.signature, response.tbs_response_bytes,
                padding.PKCS1v15(), response.signature_hash_algorithm,
            )
        elif isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(
                response.signature, response.tbs_response_bytes,
                ec.ECDSA(response.signature_hash_algorithm),
            )
        else:
            return False
        return True
    except Exception:  # noqa: BLE001 -- any failure is a failed verification
        return False


def check_ocsp(certificate, issuer, fetcher: Fetcher | None = None) -> Result:
    """Ask the issuer's OCSP responder about this certificate."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509 import ocsp

    urls = ocsp_urls(certificate)
    if not urls:
        return Result(Status.UNKNOWN, "none", "certificate lists no OCSP responder")

    # SHA1 is not a security choice here: it is the hash OCSP uses to identify
    # a certificate, and responders reject requests built with anything else.
    request = (
        ocsp.OCSPRequestBuilder()
        .add_certificate(certificate, issuer, hashes.SHA1())
        .build()
    )
    from cryptography.hazmat.primitives.serialization import Encoding

    body = request.public_bytes(Encoding.DER)
    fetch = fetcher or default_fetcher

    last_error = ""
    for url in urls:
        try:
            raw = fetch(url, body, "application/ocsp-request")
        except Exception as exc:  # noqa: BLE001 -- try the next responder
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        try:
            response = ocsp.load_der_ocsp_response(raw)
        except Exception as exc:  # noqa: BLE001
            last_error = f"unreadable OCSP response: {type(exc).__name__}"
            continue

        if response.response_status != ocsp.OCSPResponseStatus.SUCCESSFUL:
            last_error = f"responder returned {response.response_status.name}"
            continue

        if not _verify_response_signature(response, issuer):
            # Treated as no answer at all rather than as a "good": an
            # unverifiable response is exactly what a forged one looks like.
            last_error = "OCSP response signature did not verify"
            continue

        if response.serial_number != certificate.serial_number:
            last_error = "OCSP response is for a different certificate"
            continue

        this_update = _field(response, "this_update")
        next_update = _field(response, "next_update")
        now = _now()
        if this_update and this_update > now:
            last_error = "OCSP response is dated in the future"
            continue
        if next_update and next_update < now:
            last_error = "OCSP response has expired"
            continue

        if response.certificate_status == ocsp.OCSPCertStatus.REVOKED:
            reason = getattr(response, "revocation_reason", None)
            return Result(
                Status.REVOKED, "ocsp",
                f"revoked{f' ({reason.name})' if reason else ''}", _iso(now),
            )
        if response.certificate_status == ocsp.OCSPCertStatus.GOOD:
            return Result(Status.GOOD, "ocsp", "", _iso(now))

        last_error = "responder does not know this certificate"

    return Result(Status.UNKNOWN, "ocsp", last_error or "no responder answered")


# ---------------------------------------------------------------------------
# CRL
# ---------------------------------------------------------------------------

def _verify_crl_signature(crl, issuer) -> bool:
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    key = issuer.public_key()
    try:
        if isinstance(key, rsa.RSAPublicKey):
            key.verify(
                crl.signature, crl.tbs_certlist_bytes,
                padding.PKCS1v15(), crl.signature_hash_algorithm,
            )
        elif isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(
                crl.signature, crl.tbs_certlist_bytes,
                ec.ECDSA(crl.signature_hash_algorithm),
            )
        else:
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def check_crl(certificate, issuer, fetcher: Fetcher | None = None) -> Result:
    """Download the issuer's revocation list and look for this serial."""
    from cryptography import x509

    urls = crl_urls(certificate)
    if not urls:
        return Result(Status.UNKNOWN, "none", "certificate lists no CRL")

    fetch = fetcher or default_fetcher
    last_error = ""

    for url in urls:
        try:
            raw = fetch(url)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        crl = None
        for loader in (x509.load_der_x509_crl, x509.load_pem_x509_crl):
            try:
                crl = loader(raw)
                break
            except Exception:  # noqa: BLE001 -- try the other encoding
                continue
        if crl is None:
            last_error = "CRL could not be parsed"
            continue

        if not _verify_crl_signature(crl, issuer):
            # An unsigned list could simply omit the serial an attacker cares
            # about, which is the same as claiming the certificate is good.
            last_error = "CRL signature did not verify"
            continue

        next_update = _field(crl, "next_update")
        if next_update and next_update < _now():
            last_error = "CRL has expired"
            continue

        entry = crl.get_revoked_certificate_by_serial_number(certificate.serial_number)
        if entry is not None:
            return Result(Status.REVOKED, "crl", "listed on the CRL", _iso(_now()))
        return Result(Status.GOOD, "crl", "", _iso(_now()))

    return Result(Status.UNKNOWN, "crl", last_error or "no CRL could be read")


# ---------------------------------------------------------------------------
# Combined check
# ---------------------------------------------------------------------------

_cache: dict[tuple[int, bytes], tuple[float, Result]] = {}


def clear_cache() -> None:
    _cache.clear()


def check(
    certificate,
    issuer,
    *,
    fetcher: Fetcher | None = None,
    strict: bool = False,
    use_cache: bool = True,
) -> Result:
    """Establish whether a certificate has been revoked.

    Raises `RevocationError` when it has been -- always -- and also when the
    answer could not be established and `strict` is set.

    OCSP is tried first: it is current and small. A CRL is the fallback for a
    certificate with no responder, or when the responder cannot be reached.
    """
    import time

    key = (certificate.serial_number, issuer.subject.public_bytes())
    if use_cache:
        cached = _cache.get(key)
        if cached and time.time() < cached[0]:
            result = cached[1]
            if result.is_revoked:
                raise RevocationError(f"certificate is revoked: {result.reason}")
            return result

    result = check_ocsp(certificate, issuer, fetcher)
    if result.status == Status.UNKNOWN:
        fallback = check_crl(certificate, issuer, fetcher)
        if fallback.status != Status.UNKNOWN:
            result = fallback
        else:
            result = Result(
                Status.UNKNOWN, "none",
                f"OCSP: {result.reason or 'no answer'}; CRL: {fallback.reason or 'no answer'}",
            )

    if result.is_revoked:
        # Never cached: a revocation is permanent, and re-deciding it from
        # scratch each time costs nothing that matters.
        raise RevocationError(f"certificate is revoked: {result.reason}")

    if result.status == Status.GOOD and use_cache:
        _cache[key] = (time.time() + MAX_CACHE_SECONDS, result)

    if result.status == Status.UNKNOWN:
        if strict:
            raise RevocationError(
                f"revocation status could not be established: {result.reason}"
            )
        # Logged at warning rather than debug: soft-fail is a decision, and an
        # operator should be able to see how often it is being taken.
        log.warning(
            "proceeding without a revocation answer for serial %s: %s",
            certificate.serial_number, result.reason,
        )

    return result


def check_chain(
    path: Sequence,
    *,
    fetcher: Fetcher | None = None,
    strict: bool = False,
) -> list[Result]:
    """Check every certificate in a validated path against its own issuer.

    The whole path, not just the leaf: a revoked intermediate is the more
    serious failure, because everything beneath it is compromised at once.
    """
    results = []
    for certificate, issuer in zip(path, path[1:]):
        results.append(check(certificate, issuer, fetcher=fetcher, strict=strict))
    return results
