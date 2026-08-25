"""The tryout artifact, and everything deliberately kept out of it.

Coaches will use this data at selection whether or not anybody designs for it.
The realistic choice is not between "this gets used at tryouts" and "it does
not" -- it is between shipping something deliberate and leaving a coach to
screenshot a leaderboard, which is the worst version: ranked by volume, with a
child's name at the bottom.

So nearly every test here is about an absence. Volume is not in it, because
volume mostly measures opportunity -- a garage, a wall, and a lift to practice
-- rather than the athlete. It is not sorted by anything measured, because
sorting is ranking whatever the header says. And no injury history is in it,
because a child who learns that reporting pain costs them a place stops
reporting pain.

The interesting case is the collision between those last two: an athlete who
missed six weeks injured has terrible participation and the coach cannot be
told why. Hiding it makes them look lazy; showing it leaks health data to a
selector. The answer is that unavailable weeks leave their denominator, so the
rate is fair and the reason stays private.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from offdays import absence, evaluation
from offdays.db import connect
from offdays.evaluation import Trend
from offdays.store import Store

TODAY = date(2026, 8, 25)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "e.db"))


@pytest.fixture
def squad(store):
    org = store.create_org("Northshore")
    store.create_user(org, "director", "Coach Ada")
    team = store.create_team(org, "U15 Boys")
    athletes = {}
    for name in ("Zoe Ableman", "Alex Okafor", "Jordan Pierce", "Sam Reyes"):
        person = store.create_user(
            org, "athlete", name, birth_year=2011, dominant_hand="right")
        store.join_team(team["join_code"], person["id"])
        athletes[name] = person
    return {"org": org, "team": team, "athletes": athletes}


def train(store, athlete, day, rom=70.0, seed=None):
    rng = random.Random(seed if seed is not None else day.toordinal() + athlete["id"])
    started = store.start_session(athlete["id"], "gen_squat")
    t, reps = 0, []
    for _ in range(20):
        t += max(600, int(rng.gauss(1500, 220)))
        value = rom + rng.uniform(-3, 3)
        reps.append({"t_ms": t, "hand": "none", "confidence": 0.9, "rom": value,
                     "peak": value, "cycle_ms": 1150 + rng.randint(-120, 120)})
    store.submit_session(
        athlete["id"], started["session_id"], started["nonce"],
        duration_ms=t + 900, reps=reps, mean_confidence=0.9)
    store.conn.execute(
        "UPDATE sessions SET submitted_at = ? WHERE id = ?",
        (day.isoformat() + "T18:00:00+00:00", started["session_id"]))
    store.conn.commit()


def build(store, squad, **kwargs):
    return evaluation.build(
        store.conn, squad["org"], squad["team"]["id"], today=TODAY, **kwargs)


def row(export, name):
    return next(r for r in export.rows if r.display_name == name)


class TestVolumeIsNotInIt:
    """It mostly measures opportunity, and opportunity is not the athlete."""

    def test_no_volume_field_exists_at_all(self, store, squad):
        train(store, squad["athletes"]["Zoe Ableman"], TODAY - timedelta(days=3))
        keys = set(build(store, squad).rows[0].to_dict())
        for banned in ("reps", "xp", "minutes", "sessions", "volume", "total"):
            assert not any(banned in k for k in keys), \
                f"the export carries {banned!r}"

    def test_five_times_the_work_does_not_show_up(self, store, squad):
        """A child with a garage and a lift out-reps a child sharing a
        bedroom in a flat. Neither fact is about the athlete."""
        busy = squad["athletes"]["Zoe Ableman"]
        modest = squad["athletes"]["Alex Okafor"]
        for week in range(12):
            for day in range(5):
                train(store, busy, TODAY - timedelta(weeks=11 - week, days=day))
            train(store, modest, TODAY - timedelta(weeks=11 - week))

        export = build(store, squad)
        assert row(export, "Zoe Ableman").participation == \
            row(export, "Alex Okafor").participation

    def test_the_csv_carries_no_volume_column(self, store, squad):
        train(store, squad["athletes"]["Zoe Ableman"], TODAY - timedelta(days=3))
        header = build(store, squad).to_csv().splitlines()
        header = next(line for line in header if line.startswith("Athlete"))
        for banned in ("Reps", "XP", "Minutes", "Sessions"):
            assert banned not in header


class TestItIsNotARanking:
    def test_rows_are_alphabetical(self, store, squad):
        """Sorting is ranking. A list ordered by form score reads top-down as
        best-to-worst no matter what the header says."""
        names = [r.display_name for r in build(store, squad).rows]
        assert names == sorted(names)

    def test_the_best_performer_is_not_moved_to_the_top(self, store, squad):
        star = squad["athletes"]["Sam Reyes"]
        for week in range(12):
            train(store, star, TODAY - timedelta(weeks=11 - week), rom=78.0)
        export = build(store, squad)
        assert export.rows[0].display_name == "Alex Okafor"

    def test_there_is_no_composite_score(self, store, squad):
        """A single number is a ranking with one column."""
        keys = set(build(store, squad).rows[0].to_dict())
        for banned in ("score", "rating", "rank", "grade", "overall"):
            assert not any(k == banned or k.endswith(f"_{banned}") for k in keys), \
                f"the export carries a composite: {banned!r}"

    def test_form_score_is_present_but_is_not_the_sort_key(self, store, squad):
        """It is a real, useful figure. It just does not order the page."""
        assert "form_now" in build(store, squad).rows[0].to_dict()

    def test_the_csv_says_it_is_not_a_ranking(self, store, squad):
        assert "not a ranking" in build(store, squad).to_csv()


class TestNoInjuryHistoryReachesASelector:
    def test_a_past_ramp_is_not_named(self, store, squad):
        athlete = squad["athletes"]["Jordan Pierce"]
        store.conn.execute(
            "INSERT INTO return_plans(athlete_id, area, stage, clearance, "
            "  started_on, stage_started_on, completed_on, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (athlete["id"], "ankle", "done", "none",
             (TODAY - timedelta(weeks=8)).isoformat(),
             (TODAY - timedelta(weeks=8)).isoformat(),
             (TODAY - timedelta(weeks=3)).isoformat(), TODAY.isoformat()))
        store.conn.commit()
        export = build(store, squad)
        # The preamble explains the policy and uses those words on purpose;
        # a leak would be in the per-athlete rows, so that is what is scanned.
        rows = str([r.to_dict() for r in export.rows]).lower()
        body = "\n".join(
            line for line in export.to_csv().splitlines()
            if not line.startswith("#"))
        for leak in ("ankle", "injur", "return_plan", "ramp", "discomfort"):
            assert leak not in rows, f"the rows leak: {leak!r}"
            assert leak not in body.lower(), f"the csv body leaks: {leak!r}"

    def test_nor_is_the_reason_a_denominator_shrank(self, store, squad):
        athlete = squad["athletes"]["Jordan Pierce"]
        absence.schedule(
            store.conn, athlete["id"],
            (TODAY - timedelta(weeks=4)).isoformat(),
            (TODAY - timedelta(weeks=2)).isoformat(),
            today=TODAY - timedelta(weeks=4))
        export = build(store, squad)
        assert row(export, "Jordan Pierce").weeks_available < 12
        rows = str([r.to_dict() for r in export.rows]).lower()
        for leak in ("holiday", "absence", "away", "reason", "family"):
            assert leak not in rows, f"the rows leak: {leak!r}"


class TestUnavailableWeeksLeaveTheDenominator:
    """The hard case. Hiding an injury makes a child look lazy; showing it
    leaks health data to a selector. Neither -- shrink the denominator."""

    def test_an_injured_athlete_is_not_marked_down_for_missing_weeks(
        self, store, squad
    ):
        athlete = squad["athletes"]["Jordan Pierce"]
        for week in (0, 1, 2, 9, 10, 11):
            train(store, athlete, TODAY - timedelta(weeks=11 - week))
        store.conn.execute(
            "INSERT INTO return_plans(athlete_id, area, stage, clearance, "
            "  started_on, stage_started_on, completed_on, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (athlete["id"], "ankle", "done", "none",
             (TODAY - timedelta(weeks=8)).isoformat(),
             (TODAY - timedelta(weeks=8)).isoformat(),
             (TODAY - timedelta(weeks=3)).isoformat(), TODAY.isoformat()))
        store.conn.commit()

        entry = row(build(store, squad), "Jordan Pierce")
        assert entry.weeks_available < 12
        # Would have been 6/12 = 50% on a raw window.
        assert entry.participation > 0.7

    def test_a_booked_holiday_comes_out_too(self, store, squad):
        athlete = squad["athletes"]["Alex Okafor"]
        # Aligned to the export's own week grid rather than guessed at, so
        # the test measures the rule and not my arithmetic.
        start = TODAY - timedelta(weeks=12) + timedelta(days=1)
        weeks = evaluation._weeks(start, TODAY)
        away_start, away_end = weeks[4][0], weeks[5][1]

        for week_start, _ in weeks:
            if away_start <= week_start <= away_end:
                continue
            train(store, athlete, week_start)
        absence.schedule(
            store.conn, athlete["id"], away_start.isoformat(),
            away_end.isoformat(), today=away_start)

        entry = row(build(store, squad), "Alex Okafor")
        assert entry.weeks_available == len(weeks) - 2
        assert entry.participation == 1.0

    def test_an_athlete_who_simply_did_not_train_is_not_excused(
        self, store, squad
    ):
        """The adjustment is for weeks somebody was told not to train or was
        away with permission. It is not a general softening."""
        entry = row(build(store, squad), "Sam Reyes")
        assert entry.weeks_available == 12
        assert entry.participation == 0.0

    def test_a_week_only_partly_missed_still_counts(self, store, squad):
        """Two days away in a week is not a week off."""
        athlete = squad["athletes"]["Alex Okafor"]
        absence.schedule(
            store.conn, athlete["id"],
            (TODAY - timedelta(days=3)).isoformat(),
            (TODAY - timedelta(days=2)).isoformat(),
            today=TODAY - timedelta(days=3))
        assert row(build(store, squad), "Alex Okafor").weeks_available == 12


class TestImprovementIsMeasuredAgainstThemselves:
    def test_a_climbing_form_score_reads_as_improving(self, store, squad):
        athlete = squad["athletes"]["Alex Okafor"]
        for week in range(12):
            train(store, athlete, TODAY - timedelta(weeks=11 - week),
                  rom=45.0 + week * 3)
        entry = row(build(store, squad), "Alex Okafor")
        assert entry.trend == Trend.IMPROVING
        assert entry.form_change > 0

    def test_a_flat_one_reads_as_steady_not_as_a_failure(self, store, squad):
        athlete = squad["athletes"]["Zoe Ableman"]
        for week in range(12):
            train(store, athlete, TODAY - timedelta(weeks=11 - week), rom=70.0)
        assert row(build(store, squad), "Zoe Ableman").trend == Trend.STEADY

    def test_too_few_sessions_says_so_rather_than_guessing(self, store, squad):
        """Printing a trend from two sessions next to a child's name at a
        tryout would be worse than printing nothing."""
        athlete = squad["athletes"]["Sam Reyes"]
        train(store, athlete, TODAY - timedelta(days=3))
        entry = row(build(store, squad), "Sam Reyes")
        assert entry.trend == Trend.UNKNOWN
        assert entry.form_change is None

    def test_an_athlete_with_no_sessions_is_still_listed(self, store, squad):
        """Leaving them out would make them invisible at a tryout, which is
        worse for them than a row of blanks."""
        assert any(r.display_name == "Sam Reyes" for r in build(store, squad).rows)


class TestTheCaveatsTravelWithIt:
    def test_the_preamble_states_what_is_not_measured(self, store, squad):
        text = build(store, squad).preamble.lower()
        assert "not a ranking" in text
        assert "opportunity" in text

    def test_it_survives_the_export_to_csv(self, store, squad):
        """A caveat that lives only in the web page does not reach the
        selection meeting. The file does."""
        csv_text = build(store, squad).to_csv()
        assert "opportunity" in csv_text
        assert csv_text.startswith("# ")

    def test_it_says_it_is_one_input_among_many(self, store, squad):
        assert "one input among many" in build(store, squad).preamble


class TestAnAdaptiveAthleteIsNotIdentifiableHere:
    """A tryout document is the worst possible place to learn which children
    have accommodations, and the leak arrives by inference rather than by
    column: an athlete whose technique is not scored has a blank form score
    for ever, and "trained every week, never scored" is a signature.

    It cannot be made perfectly non-inferable without lying -- fabricating a
    form score would be far worse. What it can be is indistinguishable from
    the other reasons a reading is missing, and stated plainly enough that a
    coach is told not to draw the inference at all.
    """

    def _rows(self, store, squad):
        adaptive_kid = squad["athletes"]["Jordan Pierce"]
        store.set_adaptive_profile(adaptive_kid["id"], ["no_form_score"])
        # Identical training for an adaptive athlete and a typical one.
        for week in range(12):
            day = TODAY - timedelta(weeks=11 - week)
            train(store, adaptive_kid, day)
            train(store, squad["athletes"]["Zoe Ableman"], day)
        return build(store, squad)

    def test_the_sample_count_is_not_published(self, store, squad):
        """The sharpest edge of the tell: twelve weeks trained and zero
        scored sessions is a signature, and nothing renders the number."""
        export = self._rows(store, squad)
        assert "samples" not in row(export, "Jordan Pierce").to_dict()

    def test_the_trend_column_reads_the_same_as_any_other_missing_reading(
        self, store, squad
    ):
        export = self._rows(store, squad)
        adaptive = row(export, "Jordan Pierce")
        never_trained = row(export, "Sam Reyes")
        assert adaptive.trend == never_trained.trend == Trend.UNKNOWN
        assert adaptive.form_now is None and adaptive.form_change is None

    def test_nothing_in_the_row_names_the_accommodation(self, store, squad):
        export = self._rows(store, squad)
        text = str(row(export, "Jordan Pierce").to_dict()).lower()
        for leak in ("adaptive", "accommodation", "no_form_score", "not scored",
                     "switched off"):
            assert leak not in text, f"the row names it: {leak!r}"

    def test_the_csv_row_is_the_same_shape_as_a_camera_failure(
        self, store, squad
    ):
        """A coach comparing two blank rows cannot tell which is which."""
        export = self._rows(store, squad)
        lines = {
            line.split(",")[0]: line.split(",")[1:]
            for line in export.to_csv().splitlines()
            if line and not line.startswith("#") and not line.startswith("Athlete")
        }
        adaptive = lines["Jordan Pierce"]
        # An athlete who trained identically but whose sessions the camera
        # read normally, with the score columns blanked as a camera failure
        # would leave them. Everything else must match.
        camera_failed = list(lines["Zoe Ableman"])
        camera_failed[3] = camera_failed[4] = ""      # form score, form change
        camera_failed[5] = "not enough data"          # trend
        assert adaptive == camera_failed, (
            f"adaptive row {adaptive} is distinguishable from a camera "
            f"failure {camera_failed}"
        )

    def test_the_file_tells_the_coach_not_to_infer(self, store, squad):
        """An inference a coach makes unprompted is worse than a fact they
        are handed. The caveat travels in the CSV, not just the web page."""
        csv_text = self._rows(store, squad).to_csv()
        assert "A blank form score means our analysis had no reading" in csv_text
        assert "not a judgement about the athlete" in csv_text
        assert "which reason applies to which athlete" in csv_text

    def test_the_export_still_reads_nothing_from_the_profile_table(
        self, store, squad
    ):
        """The inference channel is the residual risk. A direct read would be
        the outright failure, and there is not one."""
        import inspect

        from offdays import evaluation as evaluation_mod

        source = inspect.getsource(evaluation_mod)
        assert "adaptive_profiles" not in source
        assert "adaptive" not in source.replace("adaptive_profiles", "")


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFDAYS_DB", str(tmp_path / "api.db"))
    from offdays import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


@pytest.fixture
def wired(client):
    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    athlete = client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director,
    ).json()
    return {"director": director, "team": team, "athlete": athlete}


class TestOverTheWire:
    def test_a_coach_gets_the_export(self, client, wired):
        res = client.get(
            f"/api/coach/evaluation?team_id={wired['team']['id']}",
            headers=wired["director"])
        assert res.status_code == 200
        assert res.json()["athletes"][0]["display_name"] == "Jordan P."

    def test_the_csv_comes_back_as_text(self, client, wired):
        res = client.get(
            f"/api/coach/evaluation.csv?team_id={wired['team']['id']}",
            headers=wired["director"])
        assert res.status_code == 200
        assert res.text.startswith("# What this is")

    def test_an_athlete_cannot_pull_the_squads_evaluation(self, client, wired):
        headers = {"Authorization": f"Bearer {wired['athlete']['token']}"}
        assert client.get("/api/coach/evaluation",
                          headers=headers).status_code == 403

    def test_another_program_gets_nobody(self, client, wired):
        other = client.post(
            "/api/orgs", json={"name": "Southside", "director_name": "Other"}
        ).json()
        headers = {"Authorization": f"Bearer {other['director']['token']}"}
        res = client.get(
            f"/api/coach/evaluation?team_id={wired['team']['id']}", headers=headers)
        assert res.json()["athletes"] == []
