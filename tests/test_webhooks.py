"""Inbound delivery events from a mail provider.

TestVerification is the class that matters. This endpoint's whole job is to
take instructions from the public internet about which addresses to stop
mailing; unverified, it is a one-request tool for cutting any coach in the
program off from their digest. Every negative case here is a real attack.

TestSoftBounces is the second one. A soft bounce is a full mailbox or a
greylisting server, not a dead address, and suppressing on the first one loses
real recipients silently -- which is the exact failure this module exists to
prevent.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from athleteiq import mailer
from athleteiq import webhooks as W
from athleteiq.db import connect
from athleteiq.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "w.db"))


@pytest.fixture
def coach(store):
    org = store.create_org("Northshore")
    person = store.create_user(org, "coach", "Coach R", email="coach@example.com")
    mailer.enqueue(
        store.conn, to_email="coach@example.com", subject="x", html="x", text="x",
        kind=mailer.Kind.COACH_DIGEST, dedupe_key="seed", user_id=person["id"],
    )
    return person


# --------------------------------------------------------------- fixtures

def mailgun_request(secret="mg-secret", *, age=0, email="coach@example.com",
                    severity="permanent", event_id="ev1"):
    timestamp = str(int(time.time()) - age)
    token = "tok"
    signature = hmac.new(
        secret.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
    ).hexdigest()
    return json.dumps({
        "signature": {"timestamp": timestamp, "token": token, "signature": signature},
        "event-data": {
            "event": "failed", "severity": severity, "id": event_id,
            "recipient": email, "reason": "550 mailbox unavailable",
        },
    }).encode()


def sendgrid_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )).decode()
    return private, public


def sendgrid_request(private, body: bytes, age=0):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    timestamp = str(int(time.time()) - age)
    signature = base64.b64encode(
        private.sign(timestamp.encode() + body, ec.ECDSA(hashes.SHA256()))
    ).decode()
    return {
        "X-Twilio-Email-Event-Webhook-Signature": signature,
        "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
    }


class TestVerification:
    def test_a_valid_mailgun_signature_passes(self):
        assert W.verify("mailgun", {}, mailgun_request(), "mg-secret")

    def test_the_wrong_secret_fails(self):
        assert not W.verify("mailgun", {}, mailgun_request(), "wrong-secret")

    def test_a_replayed_request_fails(self):
        """A captured webhook must not still work tomorrow."""
        assert not W.verify("mailgun", {}, mailgun_request(age=3600), "mg-secret")

    def test_an_unset_secret_never_verifies(self):
        """Absent configuration must not mean 'trust anything'."""
        assert not W.verify("mailgun", {}, mailgun_request(), "")

    def test_an_unknown_provider_never_verifies(self):
        assert not W.verify("nonesuch", {}, b"{}", "secret")

    def test_a_valid_sendgrid_signature_passes(self):
        private, public = sendgrid_keypair()
        body = json.dumps([{"event": "bounce", "email": "a@b.com"}]).encode()
        assert W.verify("sendgrid", sendgrid_request(private, body), body, public)

    def test_a_tampered_body_fails_sendgrid(self):
        """The signature covers the body; changing a byte must break it."""
        private, public = sendgrid_keypair()
        body = json.dumps([{"event": "bounce", "email": "a@b.com"}]).encode()
        headers = sendgrid_request(private, body)
        assert not W.verify("sendgrid", headers, body + b" ", public)

    def test_another_key_cannot_sign_for_us(self):
        private, _ = sendgrid_keypair()
        _, other_public = sendgrid_keypair()
        body = b"[]"
        assert not W.verify("sendgrid", sendgrid_request(private, body), body, other_public)

    def test_a_malformed_public_key_denies_rather_than_raising(self):
        private, _ = sendgrid_keypair()
        body = b"[]"
        assert not W.verify("sendgrid", sendgrid_request(private, body), body, "not-a-key")

    def test_a_stale_sendgrid_timestamp_fails(self):
        private, public = sendgrid_keypair()
        body = b"[]"
        assert not W.verify("sendgrid", sendgrid_request(private, body, age=3600), body, public)

    def test_a_token_provider_compares_the_shared_secret(self):
        assert W.verify("postmark", {"X-Webhook-Token": "s3cret"}, b"{}", "s3cret")
        assert not W.verify("postmark", {"X-Webhook-Token": "wrong"}, b"{}", "s3cret")
        assert not W.verify("postmark", {}, b"{}", "s3cret")

    def test_a_bearer_header_also_works_for_token_providers(self):
        assert W.verify("postmark", {"Authorization": "Bearer s3cret"}, b"{}", "s3cret")

    def test_headers_are_matched_case_insensitively(self):
        """HTTP header case is not guaranteed by anything."""
        assert W.verify("postmark", {"x-webhook-token": "s3cret"}, b"{}", "s3cret")

    def test_the_generic_hmac_scheme_covers_the_body(self):
        timestamp = str(int(time.time()))
        body = b'{"hello":"world"}'
        signature = hmac.new(b"gen", timestamp.encode() + body, hashlib.sha256).hexdigest()
        headers = {"X-Webhook-Signature": signature, "X-Webhook-Timestamp": timestamp}
        assert W.verify("generic", headers, body, "gen")
        assert not W.verify("generic", headers, body + b"!", "gen")


class TestParsing:
    def test_sendgrid_bounce(self):
        body = json.dumps([{
            "event": "bounce", "email": "a@b.com", "sg_event_id": "s1", "reason": "550",
        }]).encode()
        events = W.parse("sendgrid", body)
        assert events[0].type == W.EventType.HARD_BOUNCE
        assert events[0].email == "a@b.com"

    def test_sendgrid_blocked_is_a_soft_bounce(self):
        """A blocked send is temporary; treating it as permanent loses a recipient."""
        body = json.dumps([{
            "event": "bounce", "type": "blocked", "email": "a@b.com", "sg_event_id": "s2",
        }]).encode()
        assert W.parse("sendgrid", body)[0].type == W.EventType.SOFT_BOUNCE

    def test_sendgrid_spam_report(self):
        body = json.dumps([{"event": "spamreport", "email": "a@b.com", "sg_event_id": "s3"}]).encode()
        assert W.parse("sendgrid", body)[0].type == W.EventType.COMPLAINT

    def test_postmark_hard_and_soft(self):
        hard = json.dumps({"RecordType": "Bounce", "Type": "HardBounce",
                           "ID": "p1", "Email": "a@b.com"}).encode()
        soft = json.dumps({"RecordType": "Bounce", "Type": "SoftBounce",
                           "ID": "p2", "Email": "a@b.com"}).encode()
        assert W.parse("postmark", hard)[0].type == W.EventType.HARD_BOUNCE
        assert W.parse("postmark", soft)[0].type == W.EventType.SOFT_BOUNCE

    def test_mailgun_severity_decides_permanence(self):
        permanent = W.parse("mailgun", mailgun_request(severity="permanent"))[0]
        temporary = W.parse("mailgun", mailgun_request(severity="temporary"))[0]
        assert permanent.type == W.EventType.HARD_BOUNCE
        assert temporary.type == W.EventType.SOFT_BOUNCE

    def test_ses_unwraps_the_sns_envelope(self):
        """The bounce is a JSON string inside SNS's Message field."""
        body = json.dumps({"Message": json.dumps({
            "notificationType": "Bounce",
            "mail": {"messageId": "m1"},
            "bounce": {
                "bounceType": "Permanent", "feedbackId": "f1",
                "bouncedRecipients": [{"emailAddress": "a@b.com", "diagnosticCode": "550"}],
            },
        })}).encode()
        events = W.parse("ses", body)
        assert events[0].type == W.EventType.HARD_BOUNCE
        assert events[0].email == "a@b.com"

    def test_ses_reports_every_bounced_recipient(self):
        body = json.dumps({"Message": json.dumps({
            "notificationType": "Bounce", "mail": {"messageId": "m1"},
            "bounce": {
                "bounceType": "Permanent", "feedbackId": "f1",
                "bouncedRecipients": [
                    {"emailAddress": "a@b.com"}, {"emailAddress": "c@d.com"},
                ],
            },
        })}).encode()
        assert {e.email for e in W.parse("ses", body)} == {"a@b.com", "c@d.com"}

    def test_events_without_an_address_are_dropped(self):
        body = json.dumps([{"event": "bounce", "sg_event_id": "s9"}]).encode()
        assert W.parse("sendgrid", body) == []

    def test_an_unknown_event_type_is_kept_but_marked(self):
        """Recorded rather than discarded: the raw payload is the evidence."""
        body = json.dumps([{"event": "processed", "email": "a@b.com", "sg_event_id": "s8"}]).encode()
        assert W.parse("sendgrid", body)[0].type == W.EventType.UNKNOWN

    def test_malformed_json_raises_a_clear_error(self):
        with pytest.raises(W.WebhookError, match="not JSON"):
            W.parse("sendgrid", b"{not json")

    def test_an_unknown_provider_raises(self):
        with pytest.raises(W.WebhookError, match="no parser"):
            W.parse("nonesuch", b"{}")

    def test_an_oversized_payload_is_refused(self):
        with pytest.raises(W.WebhookError, match="too large"):
            W.parse("sendgrid", b"x" * (W.MAX_BODY_BYTES + 1))

    def test_a_provider_without_ids_still_deduplicates(self):
        """A content hash means a retry produces the same id."""
        body = json.dumps({"RecordType": "Bounce", "Type": "HardBounce",
                           "Email": "a@b.com"}).encode()
        first = W.parse("postmark", body)[0].event_id
        second = W.parse("postmark", body)[0].event_id
        assert first == second


class TestActions:
    def test_a_hard_bounce_suppresses_immediately(self, store, coach):
        event = W.parse("mailgun", mailgun_request())[0]
        assert W.apply_event(store.conn, event) == "suppressed"
        assert mailer.is_suppressed(store.conn, "coach@example.com")

    def test_a_suppressed_address_is_not_queued_again(self, store, coach):
        W.apply_event(store.conn, W.parse("mailgun", mailgun_request())[0])
        assert mailer.enqueue(
            store.conn, to_email="coach@example.com", subject="x", html="x", text="x",
            kind=mailer.Kind.COACH_DIGEST, dedupe_key="next", user_id=coach["id"],
        ) is None

    def test_a_retried_event_is_a_no_op(self, store, coach):
        """Providers retry. Counting the same event twice is the bug."""
        event = W.parse("mailgun", mailgun_request())[0]
        assert W.apply_event(store.conn, event) == "suppressed"
        assert W.apply_event(store.conn, event) == "duplicate"
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM webhook_events"
        ).fetchone()["n"] == 1

    def test_a_complaint_suppresses_and_opts_out(self, store, coach):
        """The strongest signal a recipient can send."""
        event = W.Event(
            provider="sendgrid", event_id="c1",
            type=W.EventType.COMPLAINT, email="coach@example.com",
        )
        assert W.apply_event(store.conn, event) == "suppressed+opted_out"
        assert mailer.is_suppressed(store.conn, "coach@example.com")
        prefs = mailer.preferences(store.conn, coach["id"])
        assert prefs[mailer.Kind.COACH_DIGEST] is False

    def test_an_unsubscribe_sets_the_preference(self, store, coach):
        event = W.Event(
            provider="sendgrid", event_id="u1",
            type=W.EventType.UNSUBSCRIBE, email="coach@example.com",
        )
        assert W.apply_event(store.conn, event) == "opted_out"
        assert not mailer.wants(store.conn, coach["id"], mailer.Kind.COACH_DIGEST)

    def test_an_unknown_recipient_unsubscribe_falls_back_to_suppression(self, store):
        event = W.Event(
            provider="sendgrid", event_id="u2",
            type=W.EventType.UNSUBSCRIBE, email="stranger@example.com",
        )
        assert W.apply_event(store.conn, event) == "suppressed"

    def test_a_delivered_event_is_only_recorded(self, store, coach):
        event = W.Event(
            provider="sendgrid", event_id="d1",
            type=W.EventType.DELIVERED, email="coach@example.com",
        )
        assert W.apply_event(store.conn, event) == "recorded"
        assert not mailer.is_suppressed(store.conn, "coach@example.com")

    def test_the_payload_cannot_name_a_user_to_target(self, store, coach):
        """A forged event must not be able to pick an account directly."""
        event = W.Event(
            provider="sendgrid", event_id="x1", type=W.EventType.COMPLAINT,
            email="nobody@example.com", raw={"user_id": coach["id"]},
        )
        W.apply_event(store.conn, event)
        # The real coach's preferences are untouched; only the address matched.
        assert mailer.wants(store.conn, coach["id"], mailer.Kind.COACH_DIGEST)


class TestSoftBounces:
    def test_one_soft_bounce_does_not_suppress(self, store, coach):
        """A full mailbox recovers. Suppressing here loses a real recipient."""
        event = W.Event(
            provider="mailgun", event_id="s1",
            type=W.EventType.SOFT_BOUNCE, email="coach@example.com",
        )
        assert W.apply_event(store.conn, event) == "counted"
        assert not mailer.is_suppressed(store.conn, "coach@example.com")

    def test_repeated_soft_bounces_eventually_suppress(self, store, coach):
        for i in range(W.SOFT_BOUNCE_LIMIT):
            event = W.Event(
                provider="mailgun", event_id=f"s{i}",
                type=W.EventType.SOFT_BOUNCE, email="coach@example.com",
            )
            action = W.apply_event(store.conn, event)
        assert action == "suppressed"
        assert mailer.is_suppressed(store.conn, "coach@example.com")

    def test_a_retried_soft_bounce_does_not_count_twice(self, store, coach):
        """Otherwise a provider's retries alone push a live address off the list."""
        event = W.Event(
            provider="mailgun", event_id="same",
            type=W.EventType.SOFT_BOUNCE, email="coach@example.com",
        )
        for _ in range(W.SOFT_BOUNCE_LIMIT + 2):
            W.apply_event(store.conn, event)
        assert not mailer.is_suppressed(store.conn, "coach@example.com")

    def test_soft_bounces_for_different_addresses_are_independent(self, store, coach):
        for i in range(W.SOFT_BOUNCE_LIMIT):
            W.apply_event(store.conn, W.Event(
                provider="mailgun", event_id=f"other{i}",
                type=W.EventType.SOFT_BOUNCE, email="someone@else.com",
            ))
        assert not mailer.is_suppressed(store.conn, "coach@example.com")


class TestHandle:
    def test_an_unverified_request_never_reaches_the_parser(self, store, coach):
        with pytest.raises(W.WebhookError, match="verification"):
            W.handle("mailgun", {}, mailgun_request(), "wrong-secret", store.conn)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM webhook_events"
        ).fetchone()["n"] == 0

    def test_a_verified_request_is_applied(self, store, coach):
        result = W.handle("mailgun", {}, mailgun_request(), "mg-secret", store.conn)
        assert result["received"] == 1
        assert result["actions"]["suppressed"] == 1

    def test_the_summary_lists_failing_addresses(self, store, coach):
        W.handle("mailgun", {}, mailgun_request(), "mg-secret", store.conn)
        summary = W.bounce_summary(store.conn)
        entry = summary["addresses"][0]
        assert entry["email"] == "coach@example.com"
        assert entry["suppressed"] is True
