"""Parent and guardian accounts.

Weighted heavily toward authorization. An invite code that reaches the wrong
person grants a stranger access to a child's training data, and a guardian who
can read another family's athlete is a far worse failure than any feature bug in
this codebase.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from athleteiq import guardians as G
from athleteiq.db import connect
from athleteiq.store import Store, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "g.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    coach = store.create_user(org, "coach", "Coach R")
    team = store.create_team(org, "Varsity")
    kids = []
    for name in ("Jordan Pierce", "Sam Rivera"):
        kid = store.create_user(
            org, "athlete", name, birth_year=2012, dominant_hand="right"
        )
        store.join_team(team["join_code"], kid["id"])
        kids.append(kid)
    return {"org": org, "coach": coach, "team": team, "kids": kids}


def train(store, athlete_id, days_ago=0, seed=1):
    slot = store.start_session(athlete_id, "lax_wall_ball")
    rng = random.Random(seed)
    t, reps = 0, []
    for i in range(120):
        rom = 0.47 * (1 + rng.gauss(0, 0.08))
        t += max(150, int(rng.gauss(880, 180)))
        reps.append({
            "t_ms": t, "hand": "left" if i % 2 else "right", "confidence": 0.9,
            "rom": round(max(0.01, rom), 3), "peak": round(rom * 0.7, 3),
            "cycle_ms": max(120, int(rng.gauss(880, 150))),
        })
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return store.submit_session(
        athlete_id, slot["session_id"], slot["nonce"],
        duration_ms=t + 700, reps=reps, mean_confidence=0.9, completed_at=when,
    )


def onboard(store, program, index=0, name="Dana Pierce"):
    kid = program["kids"][index]
    invite = G.create_invite(store.conn, kid["id"], program["coach"]["id"])
    return invite, G.redeem_invite(store.conn, invite["code"], name)


class TestInvites:
    def test_an_invite_can_be_redeemed_once(self, store, program):
        invite, guardian = onboard(store, program)
        assert guardian["athlete_name"] == "Jordan Pierce"
        assert G.guards(store.conn, guardian["guardian_id"], program["kids"][0]["id"])

    def test_a_redeemed_code_cannot_be_reused(self, store, program):
        """Otherwise one leaked code is an unlimited key to a child's data."""
        invite, _ = onboard(store, program)
        with pytest.raises(G.GuardianError, match="not valid"):
            G.redeem_invite(store.conn, invite["code"], "Someone Else")

    def test_an_unknown_code_is_refused(self, store, program):
        with pytest.raises(G.GuardianError, match="not valid"):
            G.redeem_invite(store.conn, "ZZZZ-ZZZZ-ZZZZ", "Nobody")

    def test_an_expired_code_is_refused(self, store, program):
        invite = G.create_invite(
            store.conn, program["kids"][0]["id"], program["coach"]["id"]
        )
        store.conn.execute(
            "UPDATE guardian_invites SET expires_at = ?",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),),
        )
        store.conn.commit()
        with pytest.raises(G.GuardianError, match="not valid"):
            G.redeem_invite(store.conn, invite["code"], "Late Parent")

    def test_a_revoked_code_is_refused(self, store, program):
        invite = G.create_invite(
            store.conn, program["kids"][0]["id"], program["coach"]["id"]
        )
        invite_id = store.conn.execute("SELECT id FROM guardian_invites").fetchone()["id"]
        G.revoke_invite(store.conn, invite_id)
        with pytest.raises(G.GuardianError, match="not valid"):
            G.redeem_invite(store.conn, invite["code"], "Nobody")

    def test_the_code_is_stored_only_as_a_hash(self, store, program):
        """A database leak must not be a leak of live invite codes."""
        invite = G.create_invite(
            store.conn, program["kids"][0]["id"], program["coach"]["id"]
        )
        stored = store.conn.execute("SELECT code_hash FROM guardian_invites").fetchone()
        assert invite["code"] not in stored["code_hash"]
        assert len(stored["code_hash"]) == 64

    def test_failure_messages_do_not_distinguish_causes(self, store, program):
        """Different messages would let someone probe for valid codes."""
        invite = G.create_invite(
            store.conn, program["kids"][0]["id"], program["coach"]["id"]
        )
        G.redeem_invite(store.conn, invite["code"], "First")

        messages = []
        for code in (invite["code"], "ZZZZ-ZZZZ-ZZZZ"):
            with pytest.raises(G.GuardianError) as exc:
                G.redeem_invite(store.conn, code, "Someone")
            messages.append(str(exc.value))
        assert messages[0] == messages[1]

    def test_a_guardian_cannot_be_linked_to_a_coach(self, store, program):
        with pytest.raises(G.GuardianError, match="only be linked to athletes"):
            G.create_invite(store.conn, program["coach"]["id"], program["coach"]["id"])

    def test_a_second_child_can_be_linked_to_one_account(self, store, program):
        _, guardian = onboard(store, program, 0)
        second = G.create_invite(
            store.conn, program["kids"][1]["id"], program["coach"]["id"]
        )
        G.link_existing(store.conn, second["code"], guardian["guardian_id"])
        assert len(G.athletes_for(store.conn, guardian["guardian_id"])) == 2


class TestAuthorization:
    def test_a_guardian_only_sees_their_own_athlete(self, store, program):
        _, dana = onboard(store, program, 0, "Dana")
        _, other = onboard(store, program, 1, "Other Parent")

        assert G.guards(store.conn, dana["guardian_id"], program["kids"][0]["id"])
        assert not G.guards(store.conn, dana["guardian_id"], program["kids"][1]["id"])

    def test_guarding_another_family_raises(self, store, program):
        _, dana = onboard(store, program, 0, "Dana")
        with pytest.raises(G.GuardianError, match="not listed as a guardian"):
            G.require_guardianship(
                store.conn, dana["guardian_id"], program["kids"][1]["id"]
            )

    def test_the_summary_contains_only_their_athletes(self, store, program):
        _, dana = onboard(store, program, 0, "Dana")
        summary = store.guardian_summary(dana["guardian_id"])
        assert [a["display_name"] for a in summary["athletes"]] == ["Jordan Pierce"]


class TestParentViewOmissions:
    """Two things are deliberately absent, and both matter."""

    @staticmethod
    def _payload_keys(athlete: dict) -> set[str]:
        """Every field name in the parent payload, nested ones included.

        Checked on keys rather than a flattened string: the consent copy
        legitimately contains words like "review" ("used to review a disputed
        score"), and matching prose would fail on its own explanation.
        """
        found: set[str] = set()

        def walk(node, skip: bool = False):
            if isinstance(node, dict):
                for key, value in node.items():
                    # Consent entries are descriptive text, not athlete data.
                    if not skip:
                        found.add(str(key).lower())
                    walk(value, skip)
            elif isinstance(node, list):
                for item in node:
                    walk(item, skip)

        for key, value in athlete.items():
            found.add(key.lower())
            walk(value, skip=(key == "consents"))
        return found

    def _summary(self, store, program):
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, program["kids"][0]["id"], dana["guardian_id"],
                      G.Scope.PARTICIPATION, True)
        train(store, program["kids"][0]["id"])
        return store.guardian_summary(dana["guardian_id"])["athletes"][0]

    def test_there_is_no_leaderboard_or_ranking(self, store, program):
        keys = self._payload_keys(self._summary(store, program))
        for term in ("rank", "leaderboard", "standing", "percentile"):
            assert not any(term in key for key in keys), f"parent view exposes {term!r}"

    def test_there_is_no_integrity_or_review_status(self, store, program):
        """'Held for review' reads as an accusation; it is a coach conversation."""
        keys = self._payload_keys(self._summary(store, program))
        for term in ("integrity", "review", "status", "cadence", "confidence"):
            assert not any(term in key for key in keys), f"parent view exposes {term!r}"


class TestConsent:
    def test_scopes_start_ungranted(self, store, program):
        state = G.current_consents(store.conn, program["kids"][0]["id"])
        assert all(value is False for value in state.values())

    def test_granting_and_revoking_are_both_recorded(self, store, program):
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        assert G.has_consent(store.conn, kid, G.Scope.PARTICIPATION)

        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, False)
        assert not G.has_consent(store.conn, kid, G.Scope.PARTICIPATION)

        # Append-only: the history survives the revocation.
        rows = store.conn.execute(
            "SELECT COUNT(*) AS n FROM consents WHERE athlete_id = ?", (kid,)
        ).fetchone()["n"]
        assert rows == 2

    def test_consent_records_the_policy_version(self, store, program):
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        row = store.conn.execute(
            "SELECT policy_version FROM consents WHERE athlete_id = ?", (kid,)
        ).fetchone()
        assert row["policy_version"] == G.POLICY_VERSION

    def test_an_unknown_scope_is_refused(self, store, program):
        with pytest.raises(G.GuardianError, match="unknown consent scope"):
            G.set_consent(store.conn, program["kids"][0]["id"], None, "whatever", True)

    def test_leaderboard_consent_syncs_the_cached_flag(self, store, program):
        """The leaderboard query reads a denormalized column; it must not drift."""
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)

        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.LEADERBOARD_NAME, True)
        assert store.conn.execute(
            "SELECT guardian_consent_at FROM users WHERE id = ?", (kid,)
        ).fetchone()["guardian_consent_at"] is not None

        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.LEADERBOARD_NAME, False)
        assert store.conn.execute(
            "SELECT guardian_consent_at FROM users WHERE id = ?", (kid,)
        ).fetchone()["guardian_consent_at"] is None


class TestConsentEnforcement:
    def test_an_athlete_with_no_guardian_is_unaffected(self, store, program):
        """Enforcing on athletes onboarded before parents existed would lock them out."""
        assert train(store, program["kids"][0]["id"])["status"] == "counted"

    def test_a_linked_athlete_needs_consent_to_train(self, store, program):
        onboard(store, program, 0)
        with pytest.raises(StoreError, match="consent"):
            store.start_session(program["kids"][0]["id"], "lax_wall_ball")

    def test_consent_re_enables_training(self, store, program):
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, program["kids"][0]["id"], dana["guardian_id"],
                      G.Scope.PARTICIPATION, True)
        assert train(store, program["kids"][0]["id"])["status"] == "counted"

    def test_revoking_consent_stops_training_again(self, store, program):
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        train(store, kid)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, False)
        with pytest.raises(StoreError, match="consent"):
            store.start_session(kid, "lax_wall_ball")

    def test_offline_reservations_respect_consent(self, store, program):
        """Otherwise banked slots are a way around a withdrawn consent."""
        onboard(store, program, 0)
        with pytest.raises(StoreError, match="consent"):
            store.reserve_sessions(program["kids"][0]["id"], "lax_wall_ball", 3)


class TestDataRights:
    def test_export_contains_the_training_history(self, store, program):
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        train(store, kid)

        data = G.export_athlete(store.conn, kid)
        assert data["profile"]["display_name"] == "Jordan Pierce"
        assert len(data["sessions"]) == 1
        assert data["rep_events"]
        assert data["xp"]

    def test_export_is_json_safe(self, store, program):
        import json

        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        train(store, kid)
        assert json.loads(json.dumps(G.export_athlete(store.conn, kid)))["profile"]

    def test_export_states_that_no_video_is_held(self, store, program):
        data = G.export_athlete(store.conn, program["kids"][0]["id"])
        assert "never uploaded" in data["note"]

    def test_erasing_training_data_keeps_the_account(self, store, program):
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        train(store, kid)

        G.erase_athlete(store.conn, kid, "training_data")
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM sessions WHERE athlete_id = ?", (kid,)
        ).fetchone()["n"] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM xp_ledger WHERE athlete_id = ?", (kid,)
        ).fetchone()["n"] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE id = ?", (kid,)
        ).fetchone()["n"] == 1

    def test_erasing_everything_removes_the_account(self, store, program):
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        train(store, kid)

        G.erase_athlete(store.conn, kid, "all")
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE id = ?", (kid,)
        ).fetchone()["n"] == 0

    def test_erasure_is_logged_without_identifying_the_child(self, store, program):
        kid = program["kids"][0]["id"]
        G.erase_athlete(store.conn, kid, "training_data")
        row = store.conn.execute("SELECT * FROM erasure_log").fetchone()
        assert row is not None
        assert "Jordan" not in row["athlete_ref"]
        assert str(kid) != row["athlete_ref"]

    def test_an_invalid_erase_scope_is_refused(self, store, program):
        with pytest.raises(G.GuardianError, match="scope must be"):
            G.erase_athlete(store.conn, program["kids"][0]["id"], "everything")

    def test_withdrawing_retention_purges_rep_detail_immediately(self, store, program):
        """A consent decision that takes effect tomorrow is not a decision."""
        kid = program["kids"][0]["id"]
        _, dana = onboard(store, program, 0)
        G.set_consent(store.conn, kid, dana["guardian_id"], G.Scope.PARTICIPATION, True)
        train(store, kid)
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM rep_events"
        ).fetchone()["n"] > 0

        removed = store.purge_rep_detail(kid)
        assert removed > 0
        assert store.conn.execute(
            "SELECT COUNT(*) AS n FROM rep_events"
        ).fetchone()["n"] == 0
        # Totals survive; only the rep-by-rep detail goes.
        assert store.conn.execute(
            "SELECT reps_total FROM sessions WHERE athlete_id = ?", (kid,)
        ).fetchone()["reps_total"] > 0
