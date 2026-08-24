"""Email delivery: queueing, retries, suppression, and unsubscribe.

Composing a digest and getting it into an inbox are different problems, and the
second one is where weekly email quietly stops working. These tests are mostly
about the failure paths, because the success path is the one that gets
exercised by hand and the failure paths are the ones nobody notices breaking.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from athleteiq import mailer
from athleteiq.db import connect
from athleteiq.store import Store

NOW = datetime(2026, 8, 24, 9, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "m.db"))


@pytest.fixture
def coach(store):
    org = store.create_org("Northshore LC")
    return store.create_user(org, "coach", "Coach R", email="coach@example.com")


def queue(store, coach, key="k1", to="coach@example.com", kind=None):
    return mailer.enqueue(
        store.conn, to_email=to, subject="Weekly numbers",
        html="<p>hi</p>", text="hi",
        kind=kind or mailer.Kind.COACH_DIGEST,
        dedupe_key=key, user_id=coach["id"],
    )


class Always:
    """A transport with a fixed answer."""

    def __init__(self, result: mailer.SendResult):
        self.result = result
        self.calls: list[str] = []

    def send(self, to_email, subject, html, text, headers):
        self.calls.append(to_email)
        self.headers = headers
        return self.result


OK = mailer.SendResult(ok=True)
TRANSIENT = mailer.SendResult(ok=False, error="connection reset")
PERMANENT = mailer.SendResult(ok=False, permanent=True, error="550 no such mailbox")


class TestAddressValidation:
    @pytest.mark.parametrize(
        "value,valid",
        [
            ("coach@example.com", True),
            ("a.b+tag@sub.example.co.uk", True),
            ("coach@example", False),
            ("no-at-sign", False),
            ("two@@example.com", False),
            ("has space@example.com", False),
            ("trailing@example.", False),
            ("", False),
            (None, False),
        ],
    )
    def test_addresses(self, value, valid):
        assert mailer.looks_like_email(value) is valid

    def test_an_invalid_address_is_not_queued(self, store, coach):
        assert queue(store, coach, to="not-an-address") is None


class TestQueueing:
    def test_a_message_is_queued(self, store, coach):
        assert queue(store, coach) is not None
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM email_outbox"
        ).fetchone()["n"] == 1

    def test_the_same_dedupe_key_queues_once(self, store, coach):
        """A cron that fires twice on a Monday must not send twice."""
        assert queue(store, coach, key="week-34") is not None
        assert queue(store, coach, key="week-34") is None
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM email_outbox"
        ).fetchone()["n"] == 1

    def test_different_keys_queue_separately(self, store, coach):
        assert queue(store, coach, key="week-34") is not None
        assert queue(store, coach, key="week-35") is not None

    def test_a_suppressed_address_is_not_queued(self, store, coach):
        mailer.suppress(store.conn, "coach@example.com", "bounced")
        assert queue(store, coach) is None

    def test_an_opted_out_person_is_not_queued(self, store, coach):
        mailer.set_preference(store.conn, coach["id"], mailer.Kind.COACH_DIGEST, False)
        assert queue(store, coach) is None

    def test_transactional_mail_ignores_an_opt_out(self, store, coach):
        """Opting out of a weekly broadcast is not opting out of a reply."""
        mailer.set_preference(store.conn, coach["id"], mailer.Kind.TRANSACTIONAL, False)
        assert queue(store, coach, kind=mailer.Kind.TRANSACTIONAL) is not None


class TestDelivery:
    def test_a_successful_send_is_marked_sent(self, store, coach):
        queue(store, coach)
        assert mailer.flush(store.conn, Always(OK))["sent"] == 1
        row = store.conn.execute("SELECT status, sent_at FROM email_outbox").fetchone()
        assert row["status"] == "sent"
        assert row["sent_at"]

    def test_a_sent_message_is_not_sent_again(self, store, coach):
        queue(store, coach)
        transport = Always(OK)
        mailer.flush(store.conn, transport)
        mailer.flush(store.conn, transport)
        assert len(transport.calls) == 1

    def test_a_transient_failure_is_retried_later(self, store, coach):
        queue(store, coach)
        assert mailer.flush(store.conn, Always(TRANSIENT), now=NOW)["retrying"] == 1
        row = store.conn.execute(
            "SELECT status, attempts, next_attempt_at FROM email_outbox"
        ).fetchone()
        assert row["status"] == "queued"
        assert row["attempts"] == 1
        assert datetime.fromisoformat(row["next_attempt_at"]) > NOW

    def test_a_retry_is_not_attempted_before_its_time(self, store, coach):
        queue(store, coach)
        transport = Always(TRANSIENT)
        mailer.flush(store.conn, transport, now=NOW)
        mailer.flush(store.conn, transport, now=NOW + timedelta(seconds=30))
        assert len(transport.calls) == 1

    def test_a_transient_failure_eventually_succeeds(self, store, coach):
        class Flaky:
            def __init__(self):
                self.n = 0

            def send(self, *args, **kwargs):
                self.n += 1
                return OK if self.n > 2 else TRANSIENT

        queue(store, coach)
        transport = Flaky()
        when = NOW
        for _ in range(3):
            mailer.flush(store.conn, transport, now=when)
            when += timedelta(hours=6)
        assert store.conn.execute(
            "SELECT status FROM email_outbox"
        ).fetchone()["status"] == "sent"

    def test_a_permanent_failure_gives_up_immediately(self, store, coach):
        """Retrying "no such mailbox" forever damages the sending domain."""
        queue(store, coach)
        assert mailer.flush(store.conn, Always(PERMANENT))["failed"] == 1
        row = store.conn.execute("SELECT status, attempts FROM email_outbox").fetchone()
        assert row["status"] == "failed"
        assert row["attempts"] == 1

    def test_a_hard_bounce_suppresses_the_address(self, store, coach):
        queue(store, coach)
        mailer.flush(store.conn, Always(PERMANENT))
        assert mailer.is_suppressed(store.conn, "coach@example.com")
        # And nothing is queued for it next week.
        assert queue(store, coach, key="next-week") is None

    def test_retries_stop_after_the_attempt_limit(self, store, coach):
        queue(store, coach)
        transport = Always(TRANSIENT)
        when = NOW
        for _ in range(mailer.MAX_ATTEMPTS + 2):
            mailer.flush(store.conn, transport, now=when)
            when += timedelta(days=1)
        row = store.conn.execute("SELECT status, attempts FROM email_outbox").fetchone()
        assert row["status"] == "failed"
        assert row["attempts"] == mailer.MAX_ATTEMPTS

    def test_a_transient_failure_does_not_suppress(self, store, coach):
        """A bad night for a mail server is not a dead address."""
        queue(store, coach)
        transport = Always(TRANSIENT)
        when = NOW
        for _ in range(mailer.MAX_ATTEMPTS + 1):
            mailer.flush(store.conn, transport, now=when)
            when += timedelta(days=1)
        assert not mailer.is_suppressed(store.conn, "coach@example.com")

    def test_unsubscribing_between_queue_and_send_is_honoured(self, store, coach):
        """The window is a week long; someone will use it."""
        queue(store, coach)
        mailer.set_preference(store.conn, coach["id"], mailer.Kind.COACH_DIGEST, False)
        transport = Always(OK)
        assert mailer.flush(store.conn, transport)["suppressed"] == 1
        assert transport.calls == []

    def test_one_failure_does_not_block_the_queue(self, store, coach):
        """The ninetieth coach timing out must not cost the other ten."""
        other = store.create_user(1, "coach", "Coach Two", email="two@example.com")
        queue(store, coach, key="a")
        mailer.enqueue(
            store.conn, to_email="two@example.com", subject="x", html="x", text="x",
            kind=mailer.Kind.COACH_DIGEST, dedupe_key="b", user_id=other["id"],
        )

        class OnlySecond:
            def send(self, to_email, *args, **kwargs):
                return OK if to_email == "two@example.com" else TRANSIENT

        stats = mailer.flush(store.conn, OnlySecond())
        assert stats["sent"] == 1
        assert stats["retrying"] == 1


class TestHeaders:
    def test_list_unsubscribe_is_set_when_a_base_url_exists(self, store, coach, monkeypatch):
        import athleteiq.mailer as mailer_mod
        from athleteiq.config import Config

        monkeypatch.setattr(
            mailer_mod, "CONFIG", Config(app_base_url="https://athleteiq.example.com")
        )
        queue(store, coach)
        transport = Always(OK)
        mailer.flush(store.conn, transport)
        assert "List-Unsubscribe" in transport.headers
        assert transport.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"

    def test_every_message_carries_a_message_id(self, store, coach):
        queue(store, coach)
        transport = Always(OK)
        mailer.flush(store.conn, transport)
        assert transport.headers["Message-ID"].startswith("<")

    def test_transactional_mail_has_no_unsubscribe_header(self, store, coach):
        queue(store, coach, kind=mailer.Kind.TRANSACTIONAL)
        transport = Always(OK)
        mailer.flush(store.conn, transport)
        assert "List-Unsubscribe" not in transport.headers


class TestUnsubscribeTokens:
    def test_a_token_round_trips(self):
        token = mailer.unsubscribe_token(42, mailer.Kind.COACH_DIGEST)
        assert mailer.verify_unsubscribe(token) == (42, mailer.Kind.COACH_DIGEST)

    def test_a_tampered_signature_is_refused(self):
        token = mailer.unsubscribe_token(42, mailer.Kind.COACH_DIGEST)
        assert mailer.verify_unsubscribe(token[:-1] + "0") is None

    def test_another_users_id_cannot_be_swapped_in(self):
        """Otherwise anyone could switch off someone else's mail."""
        token = mailer.unsubscribe_token(42, mailer.Kind.COACH_DIGEST)
        signature = token.rsplit(".", 1)[-1]
        assert mailer.verify_unsubscribe(f"99.coach_digest.{signature}") is None

    def test_the_kind_cannot_be_swapped(self):
        token = mailer.unsubscribe_token(42, mailer.Kind.COACH_DIGEST)
        signature = token.rsplit(".", 1)[-1]
        assert mailer.verify_unsubscribe(f"42.guardian_digest.{signature}") is None

    @pytest.mark.parametrize("junk", ["", "nonsense", "1.2", "..", "abc.def.ghi"])
    def test_malformed_tokens_are_refused_without_raising(self, junk):
        assert mailer.verify_unsubscribe(junk) is None


class TestMaintenance:
    def test_the_summary_reports_status_counts(self, store, coach):
        queue(store, coach, key="a")
        mailer.flush(store.conn, Always(OK))
        summary = mailer.outbox_summary(store.conn)
        assert summary["counts"]["sent"] == 1
        assert summary["recent"][0]["to_email"] == "coach@example.com"

    def test_pruning_drops_delivered_mail_and_keeps_failures(self, store, coach):
        """A failure is evidence; a delivered message is just storage."""
        queue(store, coach, key="a")
        mailer.flush(store.conn, Always(OK))
        other = store.create_user(1, "coach", "Two", email="two@example.com")
        mailer.enqueue(
            store.conn, to_email="two@example.com", subject="x", html="x", text="x",
            kind=mailer.Kind.COACH_DIGEST, dedupe_key="b", user_id=other["id"],
        )
        mailer.flush(store.conn, Always(PERMANENT))

        store.conn.execute(
            "UPDATE email_outbox SET sent_at = ? WHERE status = 'sent'",
            ((datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),),
        )
        store.conn.commit()

        assert mailer.prune(store.conn, days=90) == 1
        remaining = store.conn.execute(
            "SELECT status FROM email_outbox"
        ).fetchall()
        assert [r["status"] for r in remaining] == ["failed"]

    def test_unsuppressing_lets_mail_flow_again(self, store, coach):
        mailer.suppress(store.conn, "coach@example.com", "bounced")
        assert queue(store, coach, key="a") is None
        mailer.unsuppress(store.conn, "coach@example.com")
        assert queue(store, coach, key="b") is not None
