"""X.509 chain validation.

Built against a real generated CA hierarchy rather than mocks, because the
failure this guards against is subtle: a chain that *looks* valid because each
link was checked in isolation, or an issuer accepted without asking whether it
was ever allowed to be one.

The `issuer without CA=TRUE` test is the one worth reading. Without that check,
any certificate an attacker legitimately owns -- for their own domain, issued by
a genuine public CA -- can be used to sign a forged intermediate, and the chain
walks all the way up to a real root.
"""
from __future__ import annotations

import datetime

import pytest

from offdays import chain

NOW = datetime.datetime.now(datetime.timezone.utc)


def issue(cn, issuer_key=None, issuer_cert=None, *, ca=False, path_len=None,
          days=(-1, 365)):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_cert.subject if issuer_cert else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW + datetime.timedelta(days=days[0]))
        .not_valid_after(NOW + datetime.timedelta(days=days[1]))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=path_len), critical=True)
        .sign(issuer_key or key, hashes.SHA256())
    )
    return key, certificate


def pem(*certificates) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return b"".join(
        c.public_bytes(serialization.Encoding.PEM) for c in certificates
    )


@pytest.fixture
def hierarchy():
    """root -> intermediate -> leaf, as a real PKI is arranged."""
    root_key, root = issue("Test Root CA", ca=True, path_len=1)
    int_key, intermediate = issue("Test Intermediate", root_key, root, ca=True, path_len=0)
    leaf_key, leaf = issue("sns.amazonaws.com", int_key, intermediate)
    return {
        "root_key": root_key, "root": root,
        "int_key": int_key, "intermediate": intermediate,
        "leaf_key": leaf_key, "leaf": leaf, "anchors": [root],
    }


class TestAnchors:
    def test_amazon_roots_are_found_in_the_system_store(self):
        anchors = chain.load_anchors()
        subjects = [a.subject.rfc4514_string() for a in anchors]
        assert any("Amazon Root CA" in s for s in subjects)

    def test_pinning_keeps_far_fewer_roots_than_the_full_store(self):
        """The whole point: a misissuance by any of ~150 CAs should not help."""
        pinned = chain.load_anchors(pin_to_amazon=True)
        everything = chain.load_anchors(pin_to_amazon=False)
        assert len(pinned) < len(everything) / 5

    def test_an_explicit_bundle_is_read(self, tmp_path, hierarchy):
        path = tmp_path / "anchors.pem"
        path.write_bytes(pem(hierarchy["root"]))
        anchors = chain.load_anchors(str(path), pin_to_amazon=False)
        assert len(anchors) == 1

    def test_a_bundle_with_no_matching_anchor_is_an_error(self, tmp_path, hierarchy):
        """Silently ending up with zero anchors would fail open on every call."""
        path = tmp_path / "anchors.pem"
        path.write_bytes(pem(hierarchy["root"]))
        with pytest.raises(chain.ChainError, match="no trusted anchors"):
            chain.load_anchors(str(path), pin_to_amazon=True)


class TestValidChains:
    def test_leaf_through_intermediate_to_root(self, hierarchy):
        from cryptography.hazmat.primitives import hashes

        path = chain.validate_pem(
            pem(hierarchy["leaf"], hierarchy["intermediate"]), hierarchy["anchors"]
        )
        assert len(path) == 3
        # Compared by fingerprint: validate_pem re-parses the bundle, so these
        # are equal certificates rather than the same objects.
        assert path[0].fingerprint(hashes.SHA256()) == \
            hierarchy["leaf"].fingerprint(hashes.SHA256())
        assert path[-1].fingerprint(hashes.SHA256()) == \
            hierarchy["root"].fingerprint(hashes.SHA256())

    def test_a_leaf_signed_directly_by_the_root(self, hierarchy):
        _, direct = issue("direct.amazonaws.com", hierarchy["root_key"], hierarchy["root"])
        assert len(chain.validate_pem(pem(direct), hierarchy["anchors"])) == 2

    def test_extra_certificates_in_the_bundle_are_ignored(self, hierarchy):
        """A sender padding the bundle with their own certificates changes nothing."""
        evil_key, evil_root = issue("Attacker Root", ca=True)
        _, evil_int = issue("Attacker Intermediate", evil_key, evil_root, ca=True)
        from cryptography.hazmat.primitives import hashes

        path = chain.validate_pem(
            pem(hierarchy["leaf"], hierarchy["intermediate"], evil_int, evil_root),
            hierarchy["anchors"],
        )
        assert path[-1].fingerprint(hashes.SHA256()) == \
            hierarchy["root"].fingerprint(hashes.SHA256())


class TestRejections:
    def test_a_chain_to_an_untrusted_root_is_refused(self, hierarchy):
        evil_key, evil_root = issue("Attacker Root", ca=True)
        evil_int_key, evil_int = issue("Attacker Int", evil_key, evil_root, ca=True)
        _, evil_leaf = issue("sns.amazonaws.com", evil_int_key, evil_int)
        with pytest.raises(chain.ChainError, match="no trusted issuer"):
            chain.validate_pem(pem(evil_leaf, evil_int), hierarchy["anchors"])

    def test_a_self_signed_leaf_is_refused(self, hierarchy):
        _, self_signed = issue("sns.amazonaws.com")
        with pytest.raises(chain.ChainError, match="no trusted issuer"):
            chain.validate_pem(pem(self_signed), hierarchy["anchors"])

    def test_a_missing_intermediate_is_refused(self, hierarchy):
        with pytest.raises(chain.ChainError, match="no trusted issuer"):
            chain.validate_pem(pem(hierarchy["leaf"]), hierarchy["anchors"])

    def test_an_issuer_without_ca_true_is_refused(self, hierarchy):
        """The classic path-validation hole.

        A certificate an attacker legitimately owns would otherwise be usable
        to sign a forged intermediate that chains to a genuine root.
        """
        leaf_key, not_a_ca = issue(
            "Not A CA", hierarchy["root_key"], hierarchy["root"], ca=False
        )
        _, forged = issue("sns.amazonaws.com", leaf_key, not_a_ca)
        with pytest.raises(chain.ChainError, match="no trusted issuer"):
            chain.validate_pem(pem(forged, not_a_ca), hierarchy["anchors"])

    def test_an_expired_intermediate_is_refused(self, hierarchy):
        key, expired = issue(
            "Expired Int", hierarchy["root_key"], hierarchy["root"],
            ca=True, days=(-800, -400),
        )
        _, leaf = issue("sns.amazonaws.com", key, expired)
        with pytest.raises(chain.ChainError, match="not currently valid"):
            chain.validate_pem(pem(leaf, expired), hierarchy["anchors"])

    def test_an_expired_leaf_is_refused(self, hierarchy):
        _, leaf = issue(
            "sns.amazonaws.com", hierarchy["int_key"], hierarchy["intermediate"],
            days=(-800, -400),
        )
        with pytest.raises(chain.ChainError, match="not currently valid"):
            chain.validate_pem(pem(leaf, hierarchy["intermediate"]), hierarchy["anchors"])

    def test_a_path_length_constraint_is_honoured(self, hierarchy):
        """The intermediate is path_len=0, so it may not issue another CA."""
        deep_key, deep = issue(
            "Deep CA", hierarchy["int_key"], hierarchy["intermediate"], ca=True
        )
        _, leaf = issue("sns.amazonaws.com", deep_key, deep)
        with pytest.raises(chain.ChainError, match="no trusted issuer"):
            chain.validate_pem(
                pem(leaf, deep, hierarchy["intermediate"]), hierarchy["anchors"]
            )

    def test_a_forged_signature_is_refused(self, hierarchy):
        """A certificate claiming an issuer that did not actually sign it."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "forged")]))
            # Claims the real intermediate as issuer, but is signed by nobody.
            .issuer_name(hierarchy["intermediate"].subject)
            .public_key(stranger.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(NOW - datetime.timedelta(days=1))
            .not_valid_after(NOW + datetime.timedelta(days=30))
            .sign(stranger, hashes.SHA256())
        )
        with pytest.raises(chain.ChainError, match="no trusted issuer"):
            chain.validate_pem(pem(forged, hierarchy["intermediate"]), hierarchy["anchors"])

    def test_an_empty_bundle_is_refused(self, hierarchy):
        with pytest.raises(chain.ChainError, match="no certificate"):
            chain.validate_pem(b"", hierarchy["anchors"])

    def test_garbage_is_refused(self, hierarchy):
        with pytest.raises(chain.ChainError, match="no certificate"):
            chain.validate_pem(b"clearly not a certificate", hierarchy["anchors"])

    def test_no_anchors_refuses_everything(self, hierarchy):
        """Zero anchors must fail closed, never open."""
        with pytest.raises(chain.ChainError, match="no trust anchors"):
            chain.validate_pem(pem(hierarchy["leaf"], hierarchy["intermediate"]), [])

    def test_a_chain_longer_than_the_limit_is_refused(self, hierarchy):
        """Guards against a bundle crafted to make path building run long."""
        key, cert = hierarchy["root_key"], hierarchy["root"]
        certificates = []
        for i in range(chain.MAX_CHAIN_DEPTH + 3):
            key, cert = issue(f"Level {i}", key, cert, ca=True)
            certificates.append(cert)
        _, leaf = issue("sns.amazonaws.com", key, cert)
        with pytest.raises(chain.ChainError, match="longer than"):
            chain.validate_pem(
                pem(leaf, *reversed(certificates)), hierarchy["anchors"]
            )
