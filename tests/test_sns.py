"""SNS message signature verification for SES bounce notifications.

Almost every test here is an attack, because that is what this code is for. Two
of them describe the mistakes that make SNS verification worthless in practice:

* The signing certificate's URL comes *from the message*. Fetch it blindly and
  an attacker hosts their own certificate, signs their own payload with the
  matching key, and the signature verifies perfectly.
* A valid AWS signature only proves the sender has an AWS account. Anyone can
  create a topic and have Amazon sign for it legitimately, so without a topic
  allowlist "signed by AWS" means almost nothing.
"""
from __future__ import annotations

import base64
import datetime
import json

import pytest

from athleteiq import sns

TOPIC = "arn:aws:sns:us-east-1:123456789012:athleteiq-bounces"
CERT_URL = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-abc123.pem"


def make_cert(days=(-1, 365)):
    """A self-signed RSA certificate standing in for AWS's."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + datetime.timedelta(days=days[0]))
        .not_valid_after(now + datetime.timedelta(days=days[1]))
        .sign(key, hashes.SHA256())
    )
    return key, certificate.public_bytes(serialization.Encoding.PEM)


def sign(key, message: dict, version="2") -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    message = {**message, "SignatureVersion": version}
    algorithm = hashes.SHA256() if version == "2" else hashes.SHA1()
    message["Signature"] = base64.b64encode(
        key.sign(sns.canonical_string(message), padding.PKCS1v15(), algorithm)
    ).decode()
    return message


def notification(topic=TOPIC, email="coach@example.com", cert_url=CERT_URL) -> dict:
    body = json.dumps({
        "notificationType": "Bounce",
        "mail": {"messageId": "m1"},
        "bounce": {
            "bounceType": "Permanent", "feedbackId": "f1",
            "bouncedRecipients": [{"emailAddress": email}],
        },
    })
    return {
        "Type": "Notification", "MessageId": "mid-1", "TopicArn": topic,
        "Message": body, "Timestamp": "2026-08-24T10:00:00.000Z",
        "SigningCertURL": cert_url,
    }


@pytest.fixture
def signer():
    key, pem = make_cert()
    sns.clear_cert_cache()
    return key, pem, (lambda url: pem)


class TestCertificateUrl:
    @pytest.mark.parametrize("url", [
        "https://sns.us-east-1.amazonaws.com/cert.pem",
        "https://sns.eu-west-2.amazonaws.com/cert.pem",
        "https://sns.us-gov-west-1.amazonaws.com/cert.pem",
        "https://sns.cn-north-1.amazonaws.com.cn/cert.pem",
    ])
    def test_genuine_aws_hosts_are_accepted(self, url):
        assert sns.is_aws_url(url)

    @pytest.mark.parametrize("url", [
        "http://sns.us-east-1.amazonaws.com/cert.pem",              # not TLS
        "https://sns.us-east-1.amazonaws.com.attacker.net/c.pem",   # suffix trick
        "https://notsns.amazonaws.com/cert.pem",                    # not the sns host
        "https://attacker.com/cert.pem",
        "https://attacker.com/?x=sns.us-east-1.amazonaws.com",      # host in the query
        "https://sns.amazonaws.com.evil/cert.pem",
        "",
        "not a url at all",
    ])
    def test_everything_else_is_refused(self, url):
        assert not sns.is_aws_url(url)

    def test_a_bad_url_is_refused_before_any_fetch(self, signer):
        """The check has to happen before the request, not after."""
        fetched = []

        def fetcher(url):
            fetched.append(url)
            return b""

        with pytest.raises(sns.SnsError, match="not an SNS endpoint"):
            sns.fetch_certificate("https://attacker.com/cert.pem", fetcher)
        assert fetched == []

    def test_certificates_are_cached(self, signer):
        _, pem, _ = signer
        calls = []

        def fetcher(url):
            calls.append(url)
            return pem

        sns.fetch_certificate(CERT_URL, fetcher)
        sns.fetch_certificate(CERT_URL, fetcher)
        assert len(calls) == 1


class TestCanonicalString:
    def test_fields_are_ordered_as_aws_specifies(self):
        message = {
            "Type": "Notification", "MessageId": "m", "TopicArn": "t",
            "Message": "b", "Timestamp": "ts",
        }
        assert sns.canonical_string(message) == (
            b"Message\nb\nMessageId\nm\nTimestamp\nts\nTopicArn\nt\nType\nNotification\n"
        )

    def test_an_absent_subject_is_omitted_entirely(self):
        """Including it as an empty string produces a signature that never verifies."""
        without = sns.canonical_string({
            "Type": "Notification", "MessageId": "m", "TopicArn": "t",
            "Message": "b", "Timestamp": "ts",
        })
        assert b"Subject" not in without

    def test_a_present_subject_is_included(self):
        with_subject = sns.canonical_string({
            "Type": "Notification", "MessageId": "m", "TopicArn": "t",
            "Message": "b", "Timestamp": "ts", "Subject": "s",
        })
        assert b"Subject\ns\n" in with_subject

    def test_subscription_confirmations_sign_different_fields(self):
        canonical = sns.canonical_string({
            "Type": "SubscriptionConfirmation", "MessageId": "m", "TopicArn": "t",
            "Message": "b", "Timestamp": "ts", "Token": "tok",
            "SubscribeURL": "https://sns.us-east-1.amazonaws.com/x",
        })
        assert b"Token\ntok\n" in canonical
        assert b"SubscribeURL" in canonical

    def test_an_unknown_type_raises(self):
        with pytest.raises(sns.SnsError, match="unknown SNS message type"):
            sns.canonical_string({"Type": "Nonsense"})


class TestVerification:
    def test_a_genuine_message_verifies(self, signer):
        key, _, fetcher = signer
        result = sns.verify(
            sign(key, notification()), allowed_topics=[TOPIC], fetcher=fetcher
        )
        assert result.type == "Notification"
        assert result.topic_arn == TOPIC

    @pytest.mark.parametrize("version", ["1", "2"])
    def test_both_signature_versions_are_supported(self, signer, version):
        """AWS still emits version 1 for older topics."""
        key, _, fetcher = signer
        assert sns.verify(
            sign(key, notification(), version=version),
            allowed_topics=[TOPIC], fetcher=fetcher,
        ).type == "Notification"

    def test_a_tampered_body_is_refused(self, signer):
        key, _, fetcher = signer
        message = sign(key, notification())
        message["Message"] = json.dumps({"bounce": {
            "bouncedRecipients": [{"emailAddress": "victim@example.com"}]
        }})
        with pytest.raises(sns.SnsError, match="signature does not match"):
            sns.verify(message, allowed_topics=[TOPIC], fetcher=fetcher)

    def test_another_topic_is_refused_even_with_a_valid_signature(self, signer):
        """Anyone can create a topic and have Amazon sign for it legitimately."""
        key, _, fetcher = signer
        message = sign(key, notification(topic="arn:aws:sns:us-east-1:999:attacker"))
        with pytest.raises(sns.SnsError, match="unexpected topic"):
            sns.verify(message, allowed_topics=[TOPIC], fetcher=fetcher)

    def test_no_configured_topics_disables_the_endpoint(self, signer):
        key, _, fetcher = signer
        with pytest.raises(sns.SnsError, match="no SNS topic ARNs"):
            sns.verify(sign(key, notification()), allowed_topics=[], fetcher=fetcher)

    def test_an_attacker_hosted_certificate_is_refused(self, signer):
        """The canonical way this verification is got wrong."""
        key, _, fetcher = signer
        message = sign(key, notification(cert_url="https://attacker.com/cert.pem"))
        with pytest.raises(sns.SnsError, match="not an SNS endpoint"):
            sns.verify(message, allowed_topics=[TOPIC], fetcher=fetcher)

    def test_a_different_key_does_not_verify(self, signer):
        """Even a genuine-looking certificate URL cannot rescue a foreign key."""
        _, pem, _ = signer
        other_key, _ = make_cert()
        sns.clear_cert_cache()
        with pytest.raises(sns.SnsError, match="signature does not match"):
            sns.verify(
                sign(other_key, notification()),
                allowed_topics=[TOPIC], fetcher=lambda url: pem,
            )

    def test_an_expired_certificate_is_refused(self):
        key, pem = make_cert(days=(-800, -400))
        sns.clear_cert_cache()
        with pytest.raises(sns.SnsError, match="not currently valid"):
            sns.verify(
                sign(key, notification()),
                allowed_topics=[TOPIC], fetcher=lambda url: pem,
            )

    def test_an_unsigned_message_is_refused(self, signer):
        key, _, fetcher = signer
        message = sign(key, notification())
        del message["Signature"]
        with pytest.raises(sns.SnsError, match="not signed"):
            sns.verify(message, allowed_topics=[TOPIC], fetcher=fetcher)

    def test_an_unknown_signature_version_is_refused(self, signer):
        key, _, fetcher = signer
        message = sign(key, notification())
        message["SignatureVersion"] = "9"
        with pytest.raises(sns.SnsError, match="unsupported signature version"):
            sns.verify(message, allowed_topics=[TOPIC], fetcher=fetcher)

    def test_an_unparseable_certificate_is_refused(self, signer):
        key, _, _ = signer
        sns.clear_cert_cache()
        with pytest.raises(sns.SnsError, match="could not be parsed"):
            sns.verify(
                sign(key, notification()),
                allowed_topics=[TOPIC], fetcher=lambda url: b"not a certificate",
            )

    def test_a_redirect_off_aws_is_refused(self, signer):
        """A 302 from a genuine host would otherwise bypass the URL check."""
        key, _, _ = signer

        def redirecting(url):
            raise sns.SnsError("certificate URL redirected to 'https://attacker.com'")

        sns.clear_cert_cache()
        with pytest.raises(sns.SnsError, match="redirected"):
            sns.verify(
                sign(key, notification()), allowed_topics=[TOPIC], fetcher=redirecting
            )


class TestSubscriptionConfirmation:
    def _message(self, key, url="https://sns.us-east-1.amazonaws.com/?Action=Confirm"):
        return sign(key, {
            "Type": "SubscriptionConfirmation", "MessageId": "s1", "TopicArn": TOPIC,
            "Message": "You have chosen to subscribe",
            "Timestamp": "2026-08-24T10:00:00.000Z", "Token": "tok",
            "SubscribeURL": url, "SigningCertURL": CERT_URL,
        })

    def test_a_genuine_confirmation_verifies_and_is_visited(self, signer):
        key, _, fetcher = signer
        verified = sns.verify(
            self._message(key), allowed_topics=[TOPIC], fetcher=fetcher
        )
        visited = []
        assert sns.confirm_subscription(
            verified, fetcher=lambda url: visited.append(url) or b""
        )
        assert len(visited) == 1

    def test_a_confirmation_for_another_topic_is_refused(self, signer):
        key, _, fetcher = signer
        message = self._message(key)
        message["TopicArn"] = "arn:aws:sns:us-east-1:999:attacker"
        message = sign(key, message)
        with pytest.raises(sns.SnsError, match="unexpected topic"):
            sns.verify(message, allowed_topics=[TOPIC], fetcher=fetcher)

    def test_an_attacker_supplied_subscribe_url_is_not_fetched(self, signer):
        """A second attacker-controlled URL this server would otherwise visit."""
        key, _, fetcher = signer
        verified = sns.verify(
            self._message(key, url="https://attacker.com/confirm"),
            allowed_topics=[TOPIC], fetcher=fetcher,
        )
        visited = []
        with pytest.raises(sns.SnsError, match="not an SNS endpoint"):
            sns.confirm_subscription(
                verified, fetcher=lambda url: visited.append(url) or b""
            )
        assert visited == []

    def test_a_notification_is_not_treated_as_a_confirmation(self, signer):
        key, _, fetcher = signer
        verified = sns.verify(
            sign(key, notification()), allowed_topics=[TOPIC], fetcher=fetcher
        )
        assert sns.confirm_subscription(verified) is False


class TestWebhookIntegration:
    def test_a_verified_ses_bounce_suppresses_the_address(self, tmp_path, signer):
        from athleteiq import mailer, webhooks
        from athleteiq.db import connect
        from athleteiq.store import Store

        key, _, fetcher = signer
        store = Store(connect(tmp_path / "s.db"))
        body = json.dumps(sign(key, notification())).encode()

        result = webhooks._handle_ses(
            body, store.conn, topics=[TOPIC], fetcher=fetcher
        )
        assert result["actions"]["suppressed"] == 1
        assert mailer.is_suppressed(store.conn, "coach@example.com")

    def test_an_unverified_ses_message_changes_nothing(self, tmp_path, signer):
        from athleteiq import mailer, webhooks
        from athleteiq.db import connect
        from athleteiq.store import Store

        key, _, fetcher = signer
        store = Store(connect(tmp_path / "s.db"))
        message = sign(key, notification())
        message["Message"] = json.dumps({"bounce": {
            "bouncedRecipients": [{"emailAddress": "victim@example.com"}]
        }})

        with pytest.raises(webhooks.WebhookError, match="verification failed"):
            webhooks._handle_ses(
                json.dumps(message).encode(), store.conn,
                topics=[TOPIC], fetcher=fetcher,
            )
        assert not mailer.is_suppressed(store.conn, "victim@example.com")

    def test_a_subscription_confirmation_is_handled_not_parsed(self, tmp_path, signer):
        from athleteiq import webhooks
        from athleteiq.db import connect
        from athleteiq.store import Store

        key, _, fetcher = signer
        store = Store(connect(tmp_path / "s.db"))
        message = sign(key, {
            "Type": "SubscriptionConfirmation", "MessageId": "s1", "TopicArn": TOPIC,
            "Message": "confirm", "Timestamp": "2026-08-24T10:00:00.000Z",
            "Token": "tok",
            "SubscribeURL": "https://sns.us-east-1.amazonaws.com/?Action=Confirm",
            "SigningCertURL": CERT_URL,
        })
        result = webhooks._handle_ses(
            json.dumps(message).encode(), store.conn,
            topics=[TOPIC], fetcher=fetcher, auto_confirm=True,
        )
        assert result["subscription"] == "SubscriptionConfirmation"
        assert result["confirmed"] is True
        assert result["received"] == 0

    def test_auto_confirm_can_be_turned_off(self, tmp_path, signer):
        from athleteiq import webhooks
        from athleteiq.db import connect
        from athleteiq.store import Store

        key, _, fetcher = signer
        store = Store(connect(tmp_path / "s.db"))
        message = sign(key, {
            "Type": "SubscriptionConfirmation", "MessageId": "s1", "TopicArn": TOPIC,
            "Message": "confirm", "Timestamp": "2026-08-24T10:00:00.000Z",
            "Token": "tok",
            "SubscribeURL": "https://sns.us-east-1.amazonaws.com/?Action=Confirm",
            "SigningCertURL": CERT_URL,
        })
        result = webhooks._handle_ses(
            json.dumps(message).encode(), store.conn,
            topics=[TOPIC], fetcher=fetcher, auto_confirm=False,
        )
        assert result["confirmed"] is False
