"""Certificate revocation checking.

The tests that carry the weight are the forged-response ones. An OCSP answer is
signed, and an implementation that does not check that signature will happily
accept "good" from anyone able to answer the request -- which is worse than not
checking revocation at all, because it reads as protection.

The soft-fail tests matter for the opposite reason: they pin down a deliberate
choice. When a responder cannot be reached the default is to proceed, and that
is a real limitation rather than an oversight.
"""
from __future__ import annotations

import datetime

import pytest

from athleteiq import revocation as R

NOW = datetime.datetime.now(datetime.timezone.utc)
OCSP_URL = "http://ocsp.example.com"
CRL_URL = "http://crl.example.com/ca.crl"


def issue(cn, issuer_key=None, issuer_cert=None, *, ca=False, endpoints=True, eku=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_cert.subject if issuer_cert else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - datetime.timedelta(days=1))
        .not_valid_after(NOW + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if endpoints:
        builder = builder.add_extension(
            x509.AuthorityInformationAccess([
                x509.AccessDescription(
                    AuthorityInformationAccessOID.OCSP,
                    x509.UniformResourceIdentifier(OCSP_URL),
                )
            ]),
            critical=False,
        ).add_extension(
            x509.CRLDistributionPoints([
                x509.DistributionPoint(
                    full_name=[x509.UniformResourceIdentifier(CRL_URL)],
                    relative_name=None, reasons=None, crl_issuer=None,
                )
            ]),
            critical=False,
        )
    if eku:
        builder = builder.add_extension(x509.ExtendedKeyUsage(eku), critical=False)
    return key, builder.sign(issuer_key or key, hashes.SHA256())


@pytest.fixture
def ca():
    root_key, root = issue("Test Root CA", ca=True, endpoints=False)
    leaf_key, leaf = issue("sns.amazonaws.com", root_key, root)
    R.clear_cache()
    return {"root_key": root_key, "root": root, "leaf": leaf}


def ocsp_bytes(ca, status, signer_key=None, signer_cert=None, certs=None, subject=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509 import ocsp

    revoked = status == ocsp.OCSPCertStatus.REVOKED
    builder = (
        ocsp.OCSPResponseBuilder()
        .add_response(
            cert=subject or ca["leaf"], issuer=ca["root"], algorithm=hashes.SHA1(),
            cert_status=status,
            this_update=NOW - datetime.timedelta(minutes=5),
            next_update=NOW + datetime.timedelta(hours=12),
            revocation_time=NOW - datetime.timedelta(days=1) if revoked else None,
            revocation_reason=x509.ReasonFlags.key_compromise if revoked else None,
        )
        .responder_id(
            ocsp.OCSPResponderEncoding.NAME, signer_cert or ca["root"]
        )
    )
    if certs:
        builder = builder.certificates(certs)
    return builder.sign(
        signer_key or ca["root_key"], hashes.SHA256()
    ).public_bytes(serialization.Encoding.DER)


def crl_bytes(ca, serials, signer_key=None, signer_cert=None, expired=False):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name((signer_cert or ca["root"]).subject)
        .last_update(NOW - datetime.timedelta(hours=1))
        .next_update(
            NOW - datetime.timedelta(hours=1) if expired
            else NOW + datetime.timedelta(days=7)
        )
    )
    for serial in serials:
        builder = builder.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(serial)
            .revocation_date(NOW - datetime.timedelta(days=1))
            .build()
        )
    return builder.sign(
        signer_key or ca["root_key"], hashes.SHA256()
    ).public_bytes(serialization.Encoding.DER)


def fetcher(ocsp_body=None, crl_body=None, fail=()):
    def fetch(url, data=None, content_type=""):
        if "ocsp" in url:
            if "ocsp" in fail or ocsp_body is None:
                raise ConnectionError("responder unreachable")
            return ocsp_body
        if "crl" in fail or crl_body is None:
            raise ConnectionError("CRL unreachable")
        return crl_body

    return fetch


class TestEndpointDiscovery:
    def test_ocsp_and_crl_urls_are_read_from_the_certificate(self, ca):
        assert R.ocsp_urls(ca["leaf"]) == [OCSP_URL]
        assert R.crl_urls(ca["leaf"]) == [CRL_URL]

    def test_a_certificate_without_endpoints_yields_none(self, ca):
        assert R.ocsp_urls(ca["root"]) == []
        assert R.crl_urls(ca["root"]) == []


class TestOcsp:
    def test_a_good_response_clears_the_certificate(self, ca):
        from cryptography.x509 import ocsp

        result = R.check_ocsp(
            ca["leaf"], ca["root"],
            fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        assert result.status == R.Status.GOOD
        assert result.source == "ocsp"

    def test_a_revoked_response_is_reported_with_its_reason(self, ca):
        from cryptography.x509 import ocsp

        result = R.check_ocsp(
            ca["leaf"], ca["root"],
            fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.REVOKED)),
        )
        assert result.status == R.Status.REVOKED
        assert "key_compromise" in result.reason

    def test_a_delegated_responder_with_the_right_eku_is_accepted(self, ca):
        from cryptography.x509 import ocsp
        from cryptography.x509.oid import ExtendedKeyUsageOID

        key, cert = issue(
            "Responder", ca["root_key"], ca["root"],
            endpoints=False, eku=[ExtendedKeyUsageOID.OCSP_SIGNING],
        )
        result = R.check_ocsp(
            ca["leaf"], ca["root"],
            fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.GOOD, key, cert, [cert])),
        )
        assert result.status == R.Status.GOOD

    def test_a_response_signed_by_a_foreign_key_is_not_believed(self, ca):
        """Otherwise anyone able to answer can clear a revoked certificate."""
        from cryptography.x509 import ocsp
        from cryptography.x509.oid import ExtendedKeyUsageOID

        key, cert = issue(
            "Attacker Responder", endpoints=False,
            eku=[ExtendedKeyUsageOID.OCSP_SIGNING],
        )
        result = R.check_ocsp(
            ca["leaf"], ca["root"],
            fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.GOOD, key, cert, [cert])),
        )
        assert result.status == R.Status.UNKNOWN
        assert "signature did not verify" in result.reason

    def test_a_delegated_responder_without_the_eku_is_refused(self, ca):
        """Any certificate the CA ever issued would otherwise be a responder."""
        from cryptography.x509 import ocsp

        key, cert = issue("No EKU", ca["root_key"], ca["root"], endpoints=False)
        result = R.check_ocsp(
            ca["leaf"], ca["root"],
            fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.GOOD, key, cert, [cert])),
        )
        assert result.status == R.Status.UNKNOWN

    def test_a_response_about_another_certificate_is_refused(self, ca):
        from cryptography.x509 import ocsp

        _, other = issue("other", ca["root_key"], ca["root"])
        result = R.check_ocsp(
            ca["leaf"], ca["root"],
            fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.GOOD, subject=other)),
        )
        assert result.status == R.Status.UNKNOWN
        assert "different certificate" in result.reason

    def test_an_unreachable_responder_is_unknown_not_good(self, ca):
        result = R.check_ocsp(ca["leaf"], ca["root"], fetcher(fail=("ocsp",)))
        assert result.status == R.Status.UNKNOWN

    def test_garbage_from_the_responder_is_unknown(self, ca):
        result = R.check_ocsp(
            ca["leaf"], ca["root"], fetcher(b"not an ocsp response")
        )
        assert result.status == R.Status.UNKNOWN


class TestCrl:
    def test_a_certificate_absent_from_the_crl_is_good(self, ca):
        result = R.check_crl(ca["leaf"], ca["root"], fetcher(None, crl_bytes(ca, [])))
        assert result.status == R.Status.GOOD

    def test_a_listed_serial_is_revoked(self, ca):
        result = R.check_crl(
            ca["leaf"], ca["root"],
            fetcher(None, crl_bytes(ca, [ca["leaf"].serial_number])),
        )
        assert result.status == R.Status.REVOKED

    def test_an_unsigned_crl_is_not_believed(self, ca):
        """An attacker's list could simply omit the serial they care about."""
        key, cert = issue("Attacker CA", ca=True, endpoints=False)
        result = R.check_crl(
            ca["leaf"], ca["root"], fetcher(None, crl_bytes(ca, [], key, cert))
        )
        assert result.status == R.Status.UNKNOWN
        assert "signature did not verify" in result.reason

    def test_an_expired_crl_is_not_believed(self, ca):
        result = R.check_crl(
            ca["leaf"], ca["root"], fetcher(None, crl_bytes(ca, [], expired=True))
        )
        assert result.status == R.Status.UNKNOWN
        assert "expired" in result.reason


class TestCombined:
    def test_ocsp_is_preferred_over_the_crl(self, ca):
        from cryptography.x509 import ocsp

        result = R.check(
            ca["leaf"], ca["root"],
            fetcher=fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.GOOD), crl_bytes(ca, [])),
            use_cache=False,
        )
        assert result.source == "ocsp"

    def test_the_crl_is_used_when_ocsp_cannot_be_reached(self, ca):
        result = R.check(
            ca["leaf"], ca["root"],
            fetcher=fetcher(None, crl_bytes(ca, []), fail=("ocsp",)),
            use_cache=False,
        )
        assert result.status == R.Status.GOOD
        assert result.source == "crl"

    def test_a_revoked_certificate_raises_even_in_soft_mode(self, ca):
        """Never a judgement call."""
        from cryptography.x509 import ocsp

        with pytest.raises(R.RevocationError, match="revoked"):
            R.check(
                ca["leaf"], ca["root"],
                fetcher=fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.REVOKED)),
                strict=False, use_cache=False,
            )

    def test_the_crl_still_catches_a_revocation_ocsp_missed(self, ca):
        with pytest.raises(R.RevocationError, match="revoked"):
            R.check(
                ca["leaf"], ca["root"],
                fetcher=fetcher(
                    None, crl_bytes(ca, [ca["leaf"].serial_number]), fail=("ocsp",)
                ),
                use_cache=False,
            )

    def test_soft_fail_proceeds_when_nothing_answers(self, ca):
        """A deliberate limitation, pinned so it cannot change unnoticed."""
        result = R.check(
            ca["leaf"], ca["root"],
            fetcher=fetcher(fail=("ocsp", "crl")), strict=False, use_cache=False,
        )
        assert result.status == R.Status.UNKNOWN

    def test_strict_mode_refuses_what_it_cannot_clear(self, ca):
        with pytest.raises(R.RevocationError, match="could not be established"):
            R.check(
                ca["leaf"], ca["root"],
                fetcher=fetcher(fail=("ocsp", "crl")), strict=True, use_cache=False,
            )

    def test_a_good_answer_is_cached(self, ca):
        from cryptography.x509 import ocsp

        calls = []
        body = ocsp_bytes(ca, ocsp.OCSPCertStatus.GOOD)

        def counting(url, data=None, content_type=""):
            calls.append(url)
            return body

        R.clear_cache()
        R.check(ca["leaf"], ca["root"], fetcher=counting)
        R.check(ca["leaf"], ca["root"], fetcher=counting)
        assert len(calls) == 1

    def test_a_revocation_is_never_cached_as_good(self, ca):
        from cryptography.x509 import ocsp

        R.clear_cache()
        with pytest.raises(R.RevocationError):
            R.check(
                ca["leaf"], ca["root"],
                fetcher=fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.REVOKED)),
            )
        with pytest.raises(R.RevocationError):
            R.check(
                ca["leaf"], ca["root"],
                fetcher=fetcher(ocsp_bytes(ca, ocsp.OCSPCertStatus.REVOKED)),
            )

    def test_the_whole_chain_is_checked_not_just_the_leaf(self, ca):
        """A revoked intermediate compromises everything beneath it at once."""
        from cryptography.x509 import ocsp

        intermediate_key, intermediate = issue(
            "Intermediate", ca["root_key"], ca["root"], ca=True
        )
        _, leaf = issue("sns.amazonaws.com", intermediate_key, intermediate)

        def fetch(url, data=None, content_type=""):
            # The responder reports the intermediate as revoked.
            return ocsp_bytes(
                {"root": ca["root"], "root_key": ca["root_key"], "leaf": intermediate},
                ocsp.OCSPCertStatus.REVOKED, subject=intermediate,
            )

        R.clear_cache()
        with pytest.raises(R.RevocationError, match="revoked"):
            R.check_chain([leaf, intermediate, ca["root"]], fetcher=fetch)


class TestSnsIntegration:
    def test_a_revoked_signing_certificate_is_refused(self):
        """The whole point: a valid signature from a revoked key is not enough."""
        import base64
        import json

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.x509 import ocsp

        from athleteiq import sns

        root_key, root = issue("Test Root CA", ca=True, endpoints=False)
        leaf_key, leaf = issue("sns.amazonaws.com", root_key, root)
        pem = b"".join(
            c.public_bytes(serialization.Encoding.PEM) for c in (leaf, root)
        )
        topic = "arn:aws:sns:us-east-1:1:bounces"
        message = {
            "Type": "Notification", "MessageId": "m1", "TopicArn": topic,
            "Message": "{}", "Timestamp": "2026-08-24T10:00:00.000Z",
            "SignatureVersion": "2",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/c.pem",
        }
        message["Signature"] = base64.b64encode(
            leaf_key.sign(
                sns.canonical_string(message), padding.PKCS1v15(), hashes.SHA256()
            )
        ).decode()

        revoked = ocsp_bytes(
            {"root": root, "root_key": root_key, "leaf": leaf},
            ocsp.OCSPCertStatus.REVOKED,
        )
        sns.clear_cert_cache()
        R.clear_cache()
        with pytest.raises(sns.SnsError, match="revoked"):
            sns.verify(
                message, allowed_topics=[topic], fetcher=lambda url: pem,
                anchors=[root], check_revocation=True,
                revocation_fetcher=lambda url, data=None, content_type="": revoked,
            )

    def test_the_default_configuration_checks_revocation_softly(self):
        from athleteiq.config import CONFIG

        assert CONFIG.sns_check_revocation is True
        assert CONFIG.sns_revocation_strict is False
