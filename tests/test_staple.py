"""Pre-fetched OCSP responses.

Stapling adapted to a certificate that arrives as a file: fetch the responder's
answer ahead of time, verify it once, keep it, and let verification read the
stored answer instead of reaching for the network while a webhook waits.

Two properties carry the weight. A response is verified *on the way in*, so
nothing unverifiable can ever be stored and read back later as an answer. And a
staple past its own nextUpdate is not believed -- an expired answer that keeps
being trusted is worse than no staple at all, because it silently pins a
verdict from before whatever went wrong.
"""
from __future__ import annotations

import datetime

import pytest

from athleteiq import revocation as R
from athleteiq import staple as S
from athleteiq.db import connect, init_db

NOW = datetime.datetime.now(datetime.timezone.utc)
OCSP_URL = "http://ocsp.example.com"


def issue(cn, issuer_key=None, issuer_cert=None, *, ca=False, endpoints=True):
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
        )
    return key, builder.sign(issuer_key or key, hashes.SHA256())


def response_bytes(ca, status, subject=None, hours=12, signer_key=None, signer_cert=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509 import ocsp

    revoked = status == ocsp.OCSPCertStatus.REVOKED
    return (
        ocsp.OCSPResponseBuilder()
        .add_response(
            cert=subject or ca["leaf"], issuer=ca["root"], algorithm=hashes.SHA1(),
            cert_status=status,
            this_update=NOW - datetime.timedelta(minutes=5),
            next_update=NOW + datetime.timedelta(hours=hours),
            revocation_time=NOW - datetime.timedelta(days=1) if revoked else None,
            revocation_reason=x509.ReasonFlags.key_compromise if revoked else None,
        )
        .responder_id(
            ocsp.OCSPResponderEncoding.NAME, signer_cert or ca["root"]
        )
        .sign(signer_key or ca["root_key"], hashes.SHA256())
        .public_bytes(serialization.Encoding.DER)
    )


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "s.db")
    init_db(connection)
    R.clear_cache()
    return connection


@pytest.fixture
def ca():
    root_key, root = issue("Root CA", ca=True, endpoints=False)
    leaf_key, leaf = issue("sns.amazonaws.com", root_key, root)
    return {"root_key": root_key, "root": root, "leaf_key": leaf_key, "leaf": leaf}


def serve(body):
    def fetch(url, data=None, content_type=""):
        return body

    return fetch


class TestIngest:
    def test_a_valid_response_is_stored(self, conn, ca):
        from cryptography.x509 import ocsp

        staple = S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        assert staple.status == R.Status.GOOD
        assert S.get(conn, ca["leaf"], ca["root"]) is not None

    def test_a_response_signed_by_a_stranger_never_enters_the_store(self, conn, ca):
        """Verified on the way in, so nothing unverifiable can be read back."""
        from cryptography.x509 import ocsp

        evil_key, evil = issue("Evil CA", ca=True, endpoints=False)
        with pytest.raises(S.StapleError, match="signature did not verify"):
            S.staple_response(
                conn,
                response_bytes(ca, ocsp.OCSPCertStatus.GOOD, signer_key=evil_key, signer_cert=evil),
                ca["leaf"], ca["root"],
            )
        assert S.get(conn, ca["leaf"], ca["root"]) is None

    def test_a_response_about_another_certificate_is_refused(self, conn, ca):
        from cryptography.x509 import ocsp

        _, other = issue("other", ca["root_key"], ca["root"])
        with pytest.raises(S.StapleError, match="different certificate"):
            S.staple_response(
                conn, response_bytes(ca, ocsp.OCSPCertStatus.GOOD, subject=other),
                ca["leaf"], ca["root"],
            )

    def test_an_already_expired_response_is_refused(self, conn, ca):
        from cryptography.x509 import ocsp

        with pytest.raises(S.StapleError, match="already expired"):
            S.staple_response(
                conn, response_bytes(ca, ocsp.OCSPCertStatus.GOOD, hours=-2),
                ca["leaf"], ca["root"],
            )

    def test_garbage_is_refused(self, conn, ca):
        with pytest.raises(S.StapleError, match="could not be parsed"):
            S.staple_response(conn, b"not a response", ca["leaf"], ca["root"])

    def test_a_supplied_response_is_stored_like_a_fetched_one(self, conn, ca):
        """The literal form of stapling: handed over rather than fetched."""
        from cryptography.x509 import ocsp

        staple = S.staple_response(
            conn, response_bytes(ca, ocsp.OCSPCertStatus.GOOD),
            ca["leaf"], ca["root"], source="supplied",
        )
        assert staple.source == "supplied"
        assert S.get(conn, ca["leaf"], ca["root"]).source == "supplied"

    def test_staples_are_keyed_on_the_issuer_key_not_its_name(self, conn, ca):
        """Two CAs can share a subject across a key rollover."""
        other_key, other_root = issue("Root CA", ca=True, endpoints=False)
        assert S.issuer_key_id(ca["root"]) != S.issuer_key_id(other_root)


class TestFreshness:
    def test_a_current_staple_is_fresh(self, conn, ca):
        from cryptography.x509 import ocsp

        staple = S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        assert staple.is_fresh()

    def test_a_staple_past_its_next_update_is_not_believed(self, conn, ca):
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        conn.execute(
            "UPDATE ocsp_staples SET next_update = ?",
            ((NOW - datetime.timedelta(hours=1)).isoformat(timespec="seconds"),),
        )
        conn.commit()
        assert not S.get(conn, ca["leaf"], ca["root"]).is_fresh()
        assert S.check(conn, ca["leaf"], ca["root"]) is None

    def test_a_staple_is_capped_by_age_regardless_of_next_update(self, conn, ca):
        """A responder promising a month should not pin one answer that long."""
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD, hours=24 * 60)),
        )
        conn.execute(
            "UPDATE ocsp_staples SET fetched_at = ?",
            ((NOW - datetime.timedelta(days=30)).isoformat(timespec="seconds"),),
        )
        conn.commit()
        assert not S.get(conn, ca["leaf"], ca["root"]).is_fresh()

    def test_a_staple_near_expiry_is_flagged_for_refresh_while_still_fresh(self, conn, ca):
        """So a scheduled job has several chances before anything goes stale."""
        from cryptography.x509 import ocsp

        staple = S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD, hours=1)),
        )
        assert staple.is_fresh()
        assert staple.needs_refresh()

    def test_refresh_skips_a_staple_that_is_not_due(self, conn, ca):
        from cryptography.x509 import ocsp

        calls = []

        def counting(url, data=None, content_type=""):
            calls.append(url)
            return response_bytes(ca, ocsp.OCSPCertStatus.GOOD, hours=48)

        S.refresh(conn, ca["leaf"], ca["root"], counting)
        S.refresh(conn, ca["leaf"], ca["root"], counting)
        assert len(calls) == 1

    def test_force_refreshes_anyway(self, conn, ca):
        from cryptography.x509 import ocsp

        calls = []

        def counting(url, data=None, content_type=""):
            calls.append(url)
            return response_bytes(ca, ocsp.OCSPCertStatus.GOOD, hours=48)

        S.refresh(conn, ca["leaf"], ca["root"], counting)
        S.refresh(conn, ca["leaf"], ca["root"], counting, force=True)
        assert len(calls) == 2


class TestVerificationPath:
    def _no_network(self, url, data=None, content_type=""):
        raise AssertionError("verification reached the network")

    def test_a_fresh_staple_answers_without_a_network_call(self, conn, ca):
        """The point of the whole exercise."""
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        R.clear_cache()
        result = R.check(
            ca["leaf"], ca["root"], fetcher=self._no_network,
            conn=conn, use_cache=False,
        )
        assert result.status == R.Status.GOOD
        assert result.source == "staple"

    def test_a_revoked_staple_is_fatal(self, conn, ca):
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.REVOKED)),
        )
        R.clear_cache()
        with pytest.raises(R.RevocationError, match="revoked"):
            R.check(
                ca["leaf"], ca["root"], fetcher=self._no_network,
                conn=conn, use_cache=False,
            )

    def test_a_stale_staple_falls_through_to_live_ocsp(self, conn, ca):
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        conn.execute(
            "UPDATE ocsp_staples SET next_update = ?",
            ((NOW - datetime.timedelta(hours=1)).isoformat(timespec="seconds"),),
        )
        conn.commit()

        R.clear_cache()
        result = R.check(
            ca["leaf"], ca["root"],
            fetcher=serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
            conn=conn, use_cache=False,
        )
        assert result.source == "ocsp"

    def test_no_staple_falls_through_to_live_ocsp(self, conn, ca):
        from cryptography.x509 import ocsp

        R.clear_cache()
        result = R.check(
            ca["leaf"], ca["root"],
            fetcher=serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
            conn=conn, use_cache=False,
        )
        assert result.source == "ocsp"


class TestStrictModeBecomesPractical:
    """The reason this feature exists.

    Strict revocation was an availability risk while the answer had to be
    fetched during a request. With staples refreshed out of band it is not.
    """

    def test_strict_passes_on_a_fresh_staple_with_no_network(self, conn, ca):
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )

        def no_network(url, data=None, content_type=""):
            raise AssertionError("reached the network in strict mode")

        R.clear_cache()
        result = R.check(
            ca["leaf"], ca["root"], fetcher=no_network,
            conn=conn, strict=True, use_cache=False,
        )
        assert result.source == "staple"

    def test_strict_refuses_when_there_is_no_staple_and_no_responder(self, conn, ca):
        def unreachable(url, data=None, content_type=""):
            raise ConnectionError("responder down")

        R.clear_cache()
        with pytest.raises(R.RevocationError, match="could not be established"):
            R.check(
                ca["leaf"], ca["root"], fetcher=unreachable,
                conn=conn, strict=True, use_cache=False,
            )

    def test_soft_mode_proceeds_in_the_same_situation(self, conn, ca):
        def unreachable(url, data=None, content_type=""):
            raise ConnectionError("responder down")

        R.clear_cache()
        result = R.check(
            ca["leaf"], ca["root"], fetcher=unreachable,
            conn=conn, strict=False, use_cache=False,
        )
        assert result.status == R.Status.UNKNOWN


class TestMaintenance:
    def test_the_summary_counts_fresh_and_stale(self, conn, ca):
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        summary = S.summary(conn)
        assert summary["total"] == 1
        assert summary["fresh"] == 1
        assert summary["stale"] == 0

    def test_pruning_drops_long_stale_staples(self, conn, ca):
        from cryptography.x509 import ocsp

        S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        conn.execute(
            "UPDATE ocsp_staples SET next_update = ?",
            ((NOW - datetime.timedelta(days=60)).isoformat(timespec="seconds"),),
        )
        conn.commit()
        assert S.prune(conn, older_than_days=30) == 1
        assert S.summary(conn)["total"] == 0

    def test_the_whole_chain_can_be_stapled(self, conn, ca):
        from cryptography.x509 import ocsp

        intermediate_key, intermediate = issue(
            "Intermediate", ca["root_key"], ca["root"], ca=True
        )
        _, leaf = issue("sns.amazonaws.com", intermediate_key, intermediate)

        def fetch(url, data=None, content_type=""):
            # A responder that answers "good" for whatever it is asked about.
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.x509 import ocsp as ocsp_mod

            request = ocsp_mod.load_der_ocsp_request(data)
            subject = leaf if request.serial_number == leaf.serial_number else intermediate
            issuer = intermediate if subject is leaf else ca["root"]
            signer_key = intermediate_key if subject is leaf else ca["root_key"]
            signer = intermediate if subject is leaf else ca["root"]
            return (
                ocsp_mod.OCSPResponseBuilder()
                .add_response(
                    cert=subject, issuer=issuer, algorithm=hashes.SHA1(),
                    cert_status=ocsp_mod.OCSPCertStatus.GOOD,
                    this_update=NOW - datetime.timedelta(minutes=5),
                    next_update=NOW + datetime.timedelta(hours=12),
                    revocation_time=None, revocation_reason=None,
                )
                .responder_id(ocsp_mod.OCSPResponderEncoding.NAME, signer)
                .sign(signer_key, hashes.SHA256())
                .public_bytes(serialization.Encoding.DER)
            )

        staples = S.refresh_chain(conn, [leaf, intermediate, ca["root"]], fetch)
        assert len(staples) == 2

    def test_a_staple_can_be_exported_for_another_host(self, conn, ca):
        from cryptography.x509 import ocsp

        staple = S.refresh(
            conn, ca["leaf"], ca["root"],
            serve(response_bytes(ca, ocsp.OCSPCertStatus.GOOD)),
        )
        exported = S.export_staple(staple)
        import base64

        assert base64.b64decode(exported) == staple.response
