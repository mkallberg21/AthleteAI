"""Athletes the camera was not built for.

Pose estimation assumes a body with two arms, two legs, and a typical range of
motion at every joint, and that assumption runs through every layer: the
counter reads joint angles, form scoring marks a rep against a target range,
the off-hand comparison assumes two sides that should match, and the integrity
layer treats an unusual movement pattern as evidence of cheating.

For an athlete who moves differently each of those becomes a small insult
delivered by software. Saying nothing about it is not neutral -- a product
that scores an adaptive athlete as a deficient typical athlete has taken a
position and simply not admitted to it.

The most important test in this file is the integrity one. A held session gets
a person; a rejected one gets a child told by software that they cheated, and
that must not happen because a movement looked unfamiliar.
"""
from __future__ import annotations

import random
from datetime import date

import pytest

from athleteiq import adaptive
from athleteiq.adaptive import AdaptiveError
from athleteiq.db import connect
from athleteiq.drills import DRILLS_BY_KEY
from athleteiq.integrity import IntegrityResult
from athleteiq.store import Store, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "ad.db"))


@pytest.fixture
def athlete(store):
    org = store.create_org("Northshore")
    director = store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    person = store.create_user(
        org, "athlete", "Jordan P.", birth_year=2011, dominant_hand="right")
    store.join_team(team["join_code"], person["id"])
    return {"org": org, "director": director, "team": team, "person": person}


def enable(store, athlete, *keys):
    return store.set_adaptive_profile(
        athlete["person"]["id"], list(keys),
        set_by=athlete["director"]["id"], set_by_name="Coach Ada")


class TestTheFramingIsAboutTheToolNotTheAthlete:
    """A child reading their own settings screen should find a sentence about
    the app's limits, not about their body."""

    def test_the_athlete_note_describes_the_app(self):
        note = adaptive.ATHLETE_NOTE.lower()
        assert "our tool" in note or "this app" in note
        assert "not of you" in note

    def test_no_option_names_a_condition(self):
        """Nothing here is a diagnosis and nothing here should read like one."""
        for option in adaptive.ACCOMMODATIONS:
            text = f"{option.label} {option.detail}".lower()
            for clinical in ("disabled", "disability", "impair", "amputee",
                             "wheelchair", "condition", "diagnos", "patient",
                             "special needs"):
                assert clinical not in text, \
                    f"{option.key} uses clinical language: {clinical!r}"

    def test_every_option_explains_what_our_analysis_cannot_do(self):
        for option in adaptive.ACCOMMODATIONS:
            assert option.detail
            assert len(option.detail) > 60, option.key


class TestIntegrityNeverAutoRejects:
    """The one that matters most."""

    def test_a_rejection_becomes_a_review(self, store, athlete):
        profile = enable(store, athlete, "no_form_score")
        verdict = IntegrityResult(score=0.1, status="rejected", notes=["odd cadence"])
        softened = adaptive.soften_verdict(verdict, profile)
        assert softened.status == "review"

    def test_the_note_says_why_so_a_coach_is_not_guessing(self, store, athlete):
        profile = enable(store, athlete, "no_form_score")
        verdict = adaptive.soften_verdict(
            IntegrityResult(score=0.1, status="rejected", notes=[]), profile)
        assert any("does not fit how they train" in n for n in verdict.notes)

    def test_the_score_is_left_exactly_as_it_was(self, store, athlete):
        """Nothing here pretends the session looked normal. It changes what
        happens next."""
        profile = enable(store, athlete, "no_form_score")
        verdict = adaptive.soften_verdict(
            IntegrityResult(score=0.07, status="rejected", notes=[]), profile)
        assert verdict.score == 0.07

    def test_any_accommodation_at_all_buys_it(self, store, athlete):
        """Not a separate switch. A coach should not be able to record that
        the camera misreads an athlete and still have them auto-rejected for
        being misread."""
        for key in (a.key for a in adaptive.ACCOMMODATIONS):
            profile = enable(store, athlete, key)
            assert profile.never_auto_reject is True

    def test_an_athlete_with_no_profile_is_unaffected(self, store, athlete):
        profile = store.adaptive_profile(athlete["person"]["id"])
        verdict = adaptive.soften_verdict(
            IntegrityResult(score=0.1, status="rejected", notes=[]), profile)
        assert verdict.status == "rejected"

    def test_a_clean_session_is_not_touched(self, store, athlete):
        profile = enable(store, athlete, "no_form_score")
        verdict = adaptive.soften_verdict(
            IntegrityResult(score=0.95, status="counted", notes=[]), profile)
        assert verdict.status == "counted"


class TestFormScoringGoesSilentNotToZero:
    def test_a_session_comes_back_with_no_score(self, store, athlete):
        """A score of 34 against a range this athlete's body does not have is
        worse than no score."""
        enable(store, athlete, "no_form_score")
        result = self._session(store, athlete)
        assert result["quality"]["score"] is None

    def test_and_says_what_still_works(self, store, athlete):
        enable(store, athlete, "no_form_score")
        note = self._session(store, athlete)["quality"]["coaching_note"]
        assert "counts, streak and consistency" in note

    def test_it_never_says_their_range_was_short(self, store, athlete):
        enable(store, athlete, "no_form_score")
        payload = str(self._session(store, athlete)["quality"]).lower()
        for insult in ("short of full range", "shallow", "not enough range"):
            assert insult not in payload

    def test_the_session_still_counts_and_earns(self, store, athlete):
        enable(store, athlete, "no_form_score")
        result = self._session(store, athlete)
        assert result["status"] == "counted"
        assert result["xp_awarded"] > 0

    def test_without_the_accommodation_scoring_is_normal(self, store, athlete):
        assert self._session(store, athlete)["quality"]["score"] is not None

    @staticmethod
    def _session(store, athlete, rom=72.0):
        rng = random.Random(4)
        started = store.start_session(athlete["person"]["id"], "gen_squat")
        t, reps = 0, []
        for _ in range(20):
            t += max(600, int(rng.gauss(1500, 220)))
            value = rom + rng.uniform(-3, 3)
            reps.append({"t_ms": t, "hand": "none", "confidence": 0.9,
                         "rom": value, "peak": value,
                         "cycle_ms": 1150 + rng.randint(-120, 120)})
        return store.submit_session(
            athlete["person"]["id"], started["session_id"], started["nonce"],
            duration_ms=t + 900, reps=reps, mean_confidence=0.9)


class TestTheSideComparisonSwitchesOff:
    def test_no_offhand_gap_is_reported(self, store, athlete):
        """Nothing should tell a child their weaker side is a problem to fix
        when the difference is not a training gap."""
        enable(store, athlete, "no_side_comparison")
        rng = random.Random(7)
        started = store.start_session(athlete["person"]["id"], "lax_wall_ball")
        t, reps = 0, []
        for i in range(40):
            t += max(400, int(rng.gauss(900, 150)))
            strong = i % 2 == 0
            value = (0.5 if strong else 0.2) + rng.uniform(-0.02, 0.02)
            reps.append({"t_ms": t, "hand": "right" if strong else "left",
                         "confidence": 0.9, "rom": value, "peak": value,
                         "cycle_ms": 800 + rng.randint(-80, 80)})
        result = store.submit_session(
            athlete["person"]["id"], started["session_id"], started["nonce"],
            duration_ms=t + 700, reps=reps, mean_confidence=0.9)
        quality = result["quality"]
        assert quality["offhand_gap"] is None
        assert quality["offhand_rom_ratio"] is None


class TestLoggingWorkTheCameraCannotSee:
    def test_it_is_refused_without_the_accommodation(self, store, athlete):
        """A general self-report button would be a way around the integrity
        layer for anybody who wanted one."""
        with pytest.raises(StoreError, match="not switched on"):
            store.log_self_reported(
                athlete["person"]["id"], "gen_squat", minutes=20)

    def test_it_works_with_it(self, store, athlete):
        enable(store, athlete, "self_report")
        out = store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=25,
            note="in the chair")
        assert out["self_reported"] is True
        assert out["xp_awarded"] > 0

    def test_it_counts_toward_the_streak(self, store, athlete):
        """The point of a streak is turning up, and they turned up."""
        enable(store, athlete, "self_report")
        store.log_self_reported(athlete["person"]["id"], "gen_squat", minutes=20)
        assert store.athlete_stats(athlete["person"]["id"]).current_streak >= 1

    def test_it_is_marked_for_ever(self, store, athlete):
        enable(store, athlete, "self_report")
        out = store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=20)
        assert store.conn.execute(
            "SELECT self_reported FROM sessions WHERE id = ?",
            (out["session_id"],),
        ).fetchone()["self_reported"] == 1

    def test_it_carries_no_form_score(self, store, athlete):
        """Nobody measured it, so there is nothing to score."""
        enable(store, athlete, "self_report")
        out = store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=20, reps=40)
        assert store.conn.execute(
            "SELECT quality_score FROM sessions WHERE id = ?",
            (out["session_id"],),
        ).fetchone()["quality_score"] is None

    def test_the_xp_does_not_scale_with_the_reps_claimed(self, store, athlete):
        """Scaling it would hand exactly the wrong incentive to the one path
        here that nothing verifies."""
        enable(store, athlete, "self_report")
        modest = store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=20, reps=10,
            day=date(2026, 8, 1))
        wild = store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=20, reps=5000,
            day=date(2026, 8, 2))
        assert modest["xp_awarded"] == wild["xp_awarded"]

    def test_an_absurd_duration_is_refused(self, store, athlete):
        enable(store, athlete, "self_report")
        with pytest.raises(StoreError, match="between 1 and 240"):
            store.log_self_reported(
                athlete["person"]["id"], "gen_squat", minutes=900)


class TestUnverifiedRepsStayOutOfComparisons:
    def test_they_do_not_reach_the_reps_leaderboard(self, store, athlete):
        """Nobody has an incentive to overstate a number that only tightens
        their own load advisories, and a strong one to overstate a number on
        a board."""
        from athleteiq.leaderboard import leaderboard

        enable(store, athlete, "self_report")
        store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=30, reps=2000)
        rows = leaderboard(store.conn, athlete["org"], board="reps", window="week")
        assert all(r["value"] == 0 for r in rows), rows

    def test_but_they_do_reach_that_athletes_own_load(self, store, athlete):
        """Overuse protection matters most for an athlete whose training this
        app structurally cannot see. Failing safe means counting it."""
        enable(store, athlete, "self_report")
        store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=30, reps=200)
        history = store.load_history(athlete["person"]["id"])
        assert any(d.load > 0 for d in history)

    def test_participation_still_counts_them(self, store, athlete):
        """Dropping the row would have removed the athlete from participation
        too, which is backwards -- turning up is exactly what this measures."""
        from athleteiq import digest

        enable(store, athlete, "self_report")
        today = date.today()
        store.log_self_reported(
            athlete["person"]["id"], "gen_squat", minutes=20, day=today)
        stats = digest.measure_week(
            store.conn, [athlete["person"]["id"]], today, today)
        assert stats.active_athletes == 1
        assert stats.reps == 0


class TestSettingIt:
    def test_an_unknown_accommodation_is_refused(self, store, athlete):
        with pytest.raises(AdaptiveError, match="unknown accommodation"):
            store.set_adaptive_profile(athlete["person"]["id"], ["make_it_easier"])

    def test_it_can_be_cleared(self, store, athlete):
        enable(store, athlete, "no_form_score")
        store.set_adaptive_profile(athlete["person"]["id"], [])
        assert store.adaptive_profile(athlete["person"]["id"]).active is False

    def test_setting_it_twice_replaces_rather_than_accumulates(
        self, store, athlete
    ):
        enable(store, athlete, "no_form_score", "self_report")
        profile = enable(store, athlete, "no_form_score")
        assert profile.accommodations == frozenset({"no_form_score"})

    def test_who_set_it_is_recorded(self, store, athlete):
        assert enable(store, athlete, "no_form_score").set_by_name == "Coach Ada"


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATHLETEIQ_DB", str(tmp_path / "api.db"))
    from athleteiq import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


@pytest.fixture
def wired(client):
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    kid = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director,
    ).json()
    return {"director": director, "kid": kid,
            "athlete": {"Authorization": f"Bearer {kid['token']}"}}


class TestOverTheWire:
    def test_the_options_are_public(self, client):
        """A program evaluating this product should be able to read the stance
        before signing up to it."""
        res = client.get("/api/adaptive/options")
        assert res.status_code == 200
        assert len(res.json()["options"]) == len(adaptive.ACCOMMODATIONS)

    def test_a_coach_can_set_it(self, client, wired):
        res = client.put(
            "/api/adaptive",
            json={"athlete_id": wired["kid"]["id"],
                  "accommodations": ["no_form_score", "self_report"]},
            headers=wired["director"])
        assert res.status_code == 200
        assert res.json()["active"] is True

    def test_the_athlete_can_read_their_own(self, client, wired):
        client.put(
            "/api/adaptive",
            json={"athlete_id": wired["kid"]["id"],
                  "accommodations": ["no_form_score"]},
            headers=wired["director"])
        body = client.get(f"/api/adaptive?athlete_id={wired['kid']['id']}",
                          headers=wired["athlete"]).json()
        assert body["athlete_note"]
        assert "not of you" in body["athlete_note"]

    def test_an_athlete_cannot_set_their_own(self, client, wired):
        res = client.put(
            "/api/adaptive",
            json={"athlete_id": wired["kid"]["id"],
                  "accommodations": ["self_report"]},
            headers=wired["athlete"])
        assert res.status_code == 403

    def test_an_athlete_cannot_read_a_teammates(self, client, wired):
        assert client.get(
            f"/api/adaptive?athlete_id={wired['kid']['id'] + 1}",
            headers=wired["athlete"]).status_code == 403

    def test_self_reporting_is_refused_without_the_accommodation(
        self, client, wired
    ):
        res = client.post(
            "/api/sessions/self-reported",
            json={"drill_key": "gen_squat", "minutes": 20},
            headers=wired["athlete"])
        assert res.status_code == 400

    def test_and_allowed_with_it(self, client, wired):
        client.put(
            "/api/adaptive",
            json={"athlete_id": wired["kid"]["id"],
                  "accommodations": ["self_report"]},
            headers=wired["director"])
        res = client.post(
            "/api/sessions/self-reported",
            json={"drill_key": "gen_squat", "minutes": 20, "note": "in the chair"},
            headers=wired["athlete"])
        assert res.status_code == 201
        assert res.json()["self_reported"] is True

    def test_another_program_cannot_set_it(self, client, wired):
        other = client.post(
            "/api/orgs", json={"name": "Southside", "director_name": "Other"}
        ).json()
        headers = {"Authorization": f"Bearer {other['director']['token']}"}
        assert client.put(
            "/api/adaptive",
            json={"athlete_id": wired["kid"]["id"],
                  "accommodations": ["self_report"]},
            headers=headers).status_code == 404
