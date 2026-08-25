"""X.509 chain validation for SNS signing certificates.

Until now the trust in an SNS signing certificate rested entirely on the TLS
connection used to fetch it: the URL was checked to be a genuine AWS host, so
whatever came back had to be Amazon's. That is a real argument, but it is a
single point of failure. It assumes every fetcher in every deployment validates
TLS properly, and it assumes no certificate is ever misissued for an AWS
hostname. Neither assumption should be the only thing between an attacker and
the ability to suppress a coach's email.

So the certificate is also verified to chain to a trust anchor, independently of
how it arrived.

**Anchors are pinned to Amazon, not to the whole system store.** A machine
trusts roughly a hundred and fifty root CAs; trusting all of them here would
mean a misissuance by any one of them is enough. Amazon is a known issuer, so
the anchor set is filtered to Amazon's roots and the Starfield roots that
cross-sign them -- read from the system trust store at runtime rather than
embedded, so they stay current with the operating system and there is no
hardcoded certificate to go stale.

The validation itself is deliberately explicit rather than delegated. The
library's built-in path validator is built for *server* certificates and applies
policy this use does not want -- hostname matching, an extended-key-usage
requirement for TLS server auth -- which would reject a perfectly good signing
certificate for entirely the wrong reason.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

log = logging.getLogger(__name__)

# Where a system trust bundle usually lives. Tried in order.
SYSTEM_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
)

# Subjects of the roots Amazon actually signs from: their own four roots, and
# the Starfield roots that cross-sign Amazon Root CA 1 for older clients.
AMAZON_ANCHOR_PATTERN = re.compile(r"Amazon Root CA|Starfield", re.IGNORECASE)

MAX_CHAIN_DEPTH = 8

PEM_BLOCK = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL
)


class ChainError(Exception):
    """The certificate does not chain to a trusted anchor."""


def load_pem_bundle(data: bytes) -> list:
    """Parse every certificate in a PEM blob.

    A bundle fetched from SNS may contain the leaf alone or the leaf plus
    intermediates, and both have to work.
    """
    from cryptography import x509

    certificates = []
    for block in PEM_BLOCK.findall(data):
        try:
            certificates.append(x509.load_pem_x509_certificate(block))
        except Exception:  # noqa: BLE001 -- skip anything unparseable
            continue
    return certificates


def _read_first_existing(paths: Iterable[str]) -> bytes:
    for path in paths:
        try:
            return Path(path).read_bytes()
        except OSError:
            continue
    return b""


def load_anchors(
    bundle_path: str | None = None,
    *,
    pin_to_amazon: bool = True,
) -> list:
    """The certificates a chain is allowed to terminate at.

    Reads an explicit bundle if configured, otherwise certifi, otherwise the
    system store -- and by default keeps only Amazon's roots, because trusting
    every CA on the machine to vouch for an AWS signing certificate makes the
    pinning pointless.
    """
    if bundle_path:
        data = Path(bundle_path).read_bytes()
    else:
        data = b""
        try:
            import certifi

            data = Path(certifi.where()).read_bytes()
        except Exception:  # noqa: BLE001 -- fall through to the system store
            pass
        if not data:
            data = _read_first_existing(SYSTEM_BUNDLES)

    if not data:
        raise ChainError("no trust store could be read")

    anchors = load_pem_bundle(data)
    if pin_to_amazon:
        anchors = [
            a for a in anchors
            if AMAZON_ANCHOR_PATTERN.search(a.subject.rfc4514_string())
        ]
    if not anchors:
        raise ChainError(
            "no trusted anchors found. Amazon's roots are usually in the system "
            "CA bundle; point OFFDAYS_SNS_CA_BUNDLE at a PEM file containing "
            "them, or disable pinning."
        )
    return anchors


# ---------------------------------------------------------------------------
# Path building and verification
# ---------------------------------------------------------------------------

def _validity(certificate) -> tuple[float, float]:
    """Validity window as timestamps, across cryptography versions."""
    def stamp(name: str) -> float:
        value = getattr(certificate, f"{name}_utc", None)
        if value is None:
            value = getattr(certificate, name).replace(tzinfo=timezone.utc)
        return value.timestamp()

    return stamp("not_valid_before"), stamp("not_valid_after")


def _is_ca(certificate) -> bool:
    """Whether a certificate may sign other certificates.

    An issuer without CA=TRUE is the classic path-validation hole: without this
    check, any leaf certificate -- including one an attacker legitimately owns
    for their own domain -- can be used to sign a forged intermediate.
    """
    from cryptography import x509

    try:
        constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound:
        return False
    return bool(constraints.ca)


def _path_length(certificate) -> int | None:
    from cryptography import x509

    try:
        return certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value.path_length
    except x509.ExtensionNotFound:
        return None


def _verify_signature(certificate, issuer) -> bool:
    """Whether `issuer` actually signed `certificate`."""
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

    public_key = issuer.public_key()
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                padding.PKCS1v15(),
                certificate.signature_hash_algorithm,
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                ec.ECDSA(certificate.signature_hash_algorithm),
            )
        elif isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(certificate.signature, certificate.tbs_certificate_bytes)
        else:
            return False
        return True
    except Exception:  # noqa: BLE001 -- any failure is a failed signature
        return False


def verify_chain(
    certificates: Sequence,
    anchors: Sequence,
    *,
    now: float | None = None,
) -> list:
    """Verify a leaf chains to a trusted anchor. Returns the path it found.

    `certificates` is the bundle as fetched: the leaf first, then whatever
    intermediates the sender chose to include. Anything not needed is ignored
    rather than trusted -- an attacker padding the bundle with their own
    certificates should change nothing.
    """
    if not certificates:
        raise ChainError("no certificate to verify")
    if not anchors:
        raise ChainError("no trust anchors configured")

    stamp = now if now is not None else datetime.now(timezone.utc).timestamp()
    anchors_by_subject: dict[str, list] = {}
    for anchor in anchors:
        anchors_by_subject.setdefault(anchor.subject.rfc4514_string(), []).append(anchor)

    intermediates = list(certificates[1:])
    leaf = certificates[0]
    path = [leaf]
    current = leaf
    from cryptography.hazmat.primitives import hashes

    seen = {leaf.fingerprint(hashes.SHA256())}

    for depth in range(MAX_CHAIN_DEPTH):
        not_before, not_after = _validity(current)
        if not (not_before <= stamp <= not_after):
            raise ChainError(
                f"certificate for {current.subject.rfc4514_string()!r} is not "
                "currently valid"
            )

        issuer_name = current.issuer.rfc4514_string()

        # An anchor ends the chain. Checked before intermediates so a sender
        # cannot lengthen a path that is already complete.
        for anchor in anchors_by_subject.get(issuer_name, []):
            if _verify_signature(current, anchor):
                anchor_before, anchor_after = _validity(anchor)
                if not (anchor_before <= stamp <= anchor_after):
                    raise ChainError("trust anchor is not currently valid")
                path.append(anchor)
                return path

        # Otherwise look for an intermediate that issued it.
        issuer = None
        for candidate in intermediates:
            if candidate.subject.rfc4514_string() != issuer_name:
                continue
            if not _is_ca(candidate):
                # A non-CA certificate must never be accepted as an issuer.
                continue
            limit = _path_length(candidate)
            if limit is not None and limit < depth:
                continue
            if _verify_signature(current, candidate):
                issuer = candidate
                break

        if issuer is None:
            raise ChainError(
                f"no trusted issuer found for {current.subject.rfc4514_string()!r}"
            )

        marker = issuer.fingerprint(hashes.SHA256())
        if marker in seen:
            raise ChainError("certificate chain contains a loop")
        seen.add(marker)

        path.append(issuer)
        intermediates = [c for c in intermediates if c is not issuer]
        current = issuer

    raise ChainError(f"certificate chain is longer than {MAX_CHAIN_DEPTH}")


def validate_pem(
    pem: bytes,
    anchors: Sequence,
    *,
    now: float | None = None,
) -> list:
    """Parse a PEM bundle and verify it chains to a trusted anchor."""
    certificates = load_pem_bundle(pem)
    if not certificates:
        raise ChainError("no certificate found in the bundle")
    return verify_chain(certificates, anchors, now=now)
