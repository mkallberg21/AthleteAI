"""Soreness and injury reporting.

The tests are organised around the three ways this feature fails, because two
of them are not privacy failures and are easy to regress by accident: a
check-in that costs something, an output that reads like a diagnosis, and a
coach who can read a child's private note.
"""

from datetime import date, timedelta

import pytest

from offdays import wellness as W
from offdays.db import connect
from offdays.drills.base import Tissue
from offdays.store import Store, StoreError

TODAY = date.today()


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    team = store.create_team(org, "U13")
    return {"org": org, "team": team}


@pytest.fixture
def athlete(store, program):
    person = store.create_user(
        program["org"], "athlete", "Jordan P.", birth_year=TODAY.year - 13,
        dominant_hand="right",
    )
    store.join_team(program["team"]["join_code"], person["id"])
    return person


class TestTellingTheTruthIsFree:
    """The load-bearing promise. An athlete who loses a streak by admitting
    they are sore learns to tick 'fine', and then the feature is a machine for
    producing false reassurance."""

    def test_a_checkin_protects_the_streak(self, store, athlete):
        store.check_in(athlete["id"], W.Severity.HURTS)
        assert TODAY in store._streak_days(athlete["id"])

    def test_reporting_something_that_hurts_protects_it_too(self, store, athlete):
        """Reporting is itself a check-in -- asking a kid who just described a
        sore knee to also tick a mood face is friction with nothing behind it."""
        store.report_discomfort(athlete["id"], "knee", "hurts")
        assert TODAY in store._streak_days(athlete["id"])

    def test_it_awards_nothing(self, store, athlete):
        before = store.athlete_stats(athlete["id"]).total_xp
        store.check_in(athlete["id"], W.Severity.SORE)
        store.report_discomfort(athlete["id"], "knee", "sore")
        assert store.athlete_stats(athlete["id"]).total_xp == before

    def test_the_response_says_so_out_loud(self, store, athlete):
        assert store.check_in(athlete["id"], W.Severity.HURTS)["counts_toward_streak"]


class TestItNeverSaysWhatItIs:
    """The pressure to write 'looks like tendonitis' is real and one commit
    away, so the vocabulary is pinned."""

    DIAGNOSES = (
        "tendinitis", "tendonitis", "sprain", "strain", "fracture", "tear",
        "rupture", "shin splints", "bursitis", "arthritis", "dislocat",
        "concussion", "diagnos", "condition", "injury is", "you have",
    )

    def _all_text(self):
        out = []
        for area in W.AREAS:
            for severity in W.Severity.ORDER:
                for flags in ((), ("swelling",), ("at_rest", "giving_way")):
                    report = W.Report(
                        1, 1, area, "left", severity, TODAY, TODAY, flags,
                    )
                    result = W.assess(report)
                    out.append(f"{result.headline} {result.detail}")
        return out

    def test_no_output_names_a_condition(self):
        for text in self._all_text():
            for word in self.DIAGNOSES:
                assert word not in text.lower(), (word, text)

    def test_every_output_asks_for_something_doable(self):
        for text in self._all_text():
            assert any(
                verb in text.lower()
                for verb in ("tell", "stop", "rest", "leave it", "keep an eye", "talk")
            ), text

    def test_severity_is_words_a_child_can_answer(self):
        """A ten-point scale invites a kid to compare their 6 with a mate's 8."""
        for key in W.Severity.ORDER:
            assert not key.isdigit()
            assert W.Severity.PROMPTS[key]


class TestTheNoteIsNotTheCoachs:

    def test_the_coach_shape_omits_the_key_entirely(self, store, athlete):
        """Omitted, not blanked: an empty box invites someone to ask what it
        said."""
        store.report_discomfort(athlete["id"], "knee", "sore", note="dad shouted again")
        status = store.wellness_status(athlete["id"])
        assert "note" not in status.to_dict(include_notes=False)["open_reports"][0]
        assert status.to_dict()["open_reports"][0]["note"] == "dad shouted again"

    def test_the_coach_still_gets_what_changes_a_decision(self, store, athlete):
        store.report_discomfort(
            athlete["id"], "knee", "sore", side="left", note="private",
        )
        row = store.wellness_status(athlete["id"]).to_dict(False)["open_reports"][0]
        assert row["area_label"] == "Knee" and row["side"] == "left"
        assert row["severity"] == "sore" and row["days_running"] == 1


class TestHeadAndNeckAreNotOnTheLadder:
    """Being wrong about a head knock in a twelve-year-old is not symmetrical
    with an unnecessary rest day."""

    @pytest.mark.parametrize("area", ["head", "neck"])
    @pytest.mark.parametrize("severity", W.Severity.ORDER)
    def test_any_report_stops_everything(self, area, severity):
        result = W.assess(W.Report(1, 1, W.AREAS_BY_KEY[area], "", severity, TODAY, TODAY))
        assert result.action == W.Action.STOP
        assert set(result.blocked_tissues) == set(Tissue)
        assert result.tell_guardian is True

    def test_the_mildest_head_report_still_names_the_hospital_question(self):
        result = W.assess(W.Report(1, 1, W.AREAS_BY_KEY["head"], "", "niggle", TODAY, TODAY))
        assert "hospital" in result.detail.lower()
        assert "today, not tomorrow" in result.detail.lower()


class TestWhatEscalates:

    def test_a_flag_escalates_regardless_of_how_bad_it_feels(self):
        """A 'niggle' that gives way is not a niggle."""
        result = W.assess(W.Report(
            1, 1, W.AREAS_BY_KEY["knee"], "left", "niggle", TODAY, TODAY, ("giving_way",),
        ))
        assert result.action == W.Action.TELL_SOMEONE
        assert result.tell_guardian is True

    def test_cannot_do_it_properly_escalates(self):
        result = W.assess(W.Report(1, 1, W.AREAS_BY_KEY["knee"], "", "hurts", TODAY, TODAY))
        assert result.action == W.Action.TELL_SOMEONE

    def test_a_plain_niggle_holds_nothing_back(self):
        result = W.assess(W.Report(1, 1, W.AREAS_BY_KEY["knee"], "", "niggle", TODAY, TODAY))
        assert result.action == W.Action.MONITOR
        assert result.blocked_tissues == ()

    def test_getting_worse_matters_more_than_any_one_reading(self, store, athlete):
        store.report_discomfort(athlete["id"], "knee", "niggle",
                                day=TODAY - timedelta(days=2))
        store.report_discomfort(athlete["id"], "knee", "sore")
        report = store.wellness_status(athlete["id"]).reports[0]
        assert report.previous == "niggle" and report.worsening is True

    def test_something_dragging_on_gets_flagged(self, store, athlete):
        store.report_discomfort(athlete["id"], "knee", "niggle",
                                started_on=TODAY - timedelta(days=9))
        status = store.wellness_status(athlete["id"])
        assert status.reports[0].days_running == 10
        assert status.action == W.Action.EASE_OFF
        assert any("10 days" in r for r in status.assessments[0].reasons)


class TestWhatTheAppStopsOffering:

    def test_a_sore_knee_hides_leg_work_and_leaves_the_rest(self, store, athlete):
        store.report_discomfort(athlete["id"], "knee", "sore")
        status = store.wellness_status(athlete["id"])
        legs = W.drill_availability(status, "gen_squat", Tissue.LOWER_BODY)
        hands = W.drill_availability(status, "lax_wall_ball", Tissue.THROWING)
        assert legs["available"] is False and "knee" in legs["reason"]
        assert hands["available"] is True

    def test_a_sore_shoulder_hides_throwing(self, store, athlete):
        store.report_discomfort(athlete["id"], "shoulder", "sore")
        status = store.wellness_status(athlete["id"])
        assert not W.drill_availability(status, "lax_wall_ball", Tissue.THROWING)["available"]
        assert W.drill_availability(status, "gen_squat", Tissue.LOWER_BODY)["available"]

    def test_a_niggle_hides_nothing(self, store, athlete):
        store.report_discomfort(athlete["id"], "knee", "niggle")
        status = store.wellness_status(athlete["id"])
        assert W.drill_availability(status, "gen_squat", Tissue.LOWER_BODY)["available"]

    def test_a_forgotten_report_stops_blocking_eventually(self, store, athlete):
        """A kid who got better and forgot to close it is not blocked forever."""
        store.report_discomfort(
            athlete["id"], "knee", "sore",
            day=TODAY - timedelta(days=W.STALE_AFTER_DAYS + 1),
            started_on=TODAY - timedelta(days=W.STALE_AFTER_DAYS + 1),
        )
        assert store.wellness_status(athlete["id"]).reports == []


class TestRecordKeeping:

    def test_a_second_report_on_the_same_knee_is_the_same_knee(self, store, athlete):
        store.report_discomfort(athlete["id"], "knee", "niggle",
                                started_on=TODAY - timedelta(days=3))
        store.report_discomfort(athlete["id"], "knee", "sore")
        status = store.wellness_status(athlete["id"])
        assert len(status.reports) == 1
        assert status.reports[0].days_running == 4, "history is kept, not restarted"

    def test_two_different_areas_are_two_reports(self, store, athlete):
        store.report_discomfort(athlete["id"], "knee", "sore")
        store.report_discomfort(athlete["id"], "shoulder", "sore")
        assert len(store.wellness_status(athlete["id"]).reports) == 2

    def test_resolving_clears_the_hold(self, store, athlete):
        saved = store.report_discomfort(athlete["id"], "knee", "sore")
        done = store.resolve_discomfort(athlete["id"], saved["id"])
        assert done["resolved"] is True
        assert done["plan"] is None, "a sore knee does not need a ramp back"
        assert store.wellness_status(athlete["id"]).blocked_tissues == set()

    def test_one_athlete_cannot_resolve_anothers_report(self, store, program, athlete):
        other = store.create_user(program["org"], "athlete", "Someone Else")
        saved = store.report_discomfort(athlete["id"], "knee", "sore")
        assert store.resolve_discomfort(other["id"], saved["id"])["resolved"] is False

    def test_junk_is_refused_rather_than_stored(self, store, athlete):
        for bad in (
            {"area": "spleen", "severity": "sore"},
            {"area": "knee", "severity": "agony"},
            {"area": "knee", "severity": "sore", "side": "port"},
        ):
            with pytest.raises(StoreError):
                store.report_discomfort(athlete["id"], **bad)

    def test_unknown_flags_are_dropped_not_stored(self, store, athlete):
        store.report_discomfort(
            athlete["id"], "knee", "sore", flags=["swelling", "made_up"],
        )
        assert store.wellness_status(athlete["id"]).reports[0].flags == ("swelling",)


class TestTheTrendSurvivesAnEdit:

    def test_correcting_a_typo_does_not_erase_the_trend(self, store, athlete):
        """Re-submitting the same severity must not overwrite the real previous
        reading -- that is how "getting worse" quietly stops working."""
        store.report_discomfort(athlete["id"], "knee", "niggle",
                                day=TODAY - timedelta(days=2))
        store.report_discomfort(athlete["id"], "knee", "sore", note="first try")
        store.report_discomfort(athlete["id"], "knee", "sore", note="fixed typo")
        report = store.wellness_status(athlete["id"]).reports[0]
        assert report.previous == "niggle"
        assert report.worsening is True

    def test_getting_better_is_not_read_as_getting_worse(self, store, athlete):
        store.report_discomfort(athlete["id"], "knee", "hurts",
                                day=TODAY - timedelta(days=2))
        store.report_discomfort(athlete["id"], "knee", "niggle")
        report = store.wellness_status(athlete["id"]).reports[0]
        assert report.previous == "hurts" and report.worsening is False


class TestRetention:

    def test_only_resolved_reports_are_ever_purged(self, store, athlete):
        """An open report is a live thing about a body that still hurts."""
        from offdays.notifications import purge_old_wellness
        old = TODAY - timedelta(days=W.RETENTION_DAYS + 5)
        open_one = store.report_discomfort(athlete["id"], "knee", "sore", day=old)
        closed = store.report_discomfort(athlete["id"], "ankle", "sore", day=old)
        store.resolve_discomfort(athlete["id"], closed["id"], day=old)

        purge_old_wellness(store.conn, TODAY)
        remaining = {
            r["id"] for r in store.conn.execute("SELECT id FROM discomfort_reports")
        }
        assert open_one["id"] in remaining
        assert closed["id"] not in remaining

    def test_recent_history_is_left_alone(self, store, athlete):
        from offdays.notifications import purge_old_wellness
        saved = store.report_discomfort(athlete["id"], "knee", "sore")
        store.resolve_discomfort(athlete["id"], saved["id"])
        purge_old_wellness(store.conn, TODAY)
        assert store.conn.execute(
            "SELECT COUNT(*) FROM discomfort_reports"
        ).fetchone()[0] == 1


class TestGuardianEscalation:

    @pytest.fixture
    def linked(self, store, program, athlete):
        """A real guardian, through the real invite flow."""
        from offdays import guardians
        invite = guardians.create_invite(
            store.conn, athlete["id"], created_by=athlete["id"], email="p@example.com",
        )
        return guardians.redeem_invite(
            store.conn, invite["code"], "A Parent", email="p@example.com",
        )

    def _report_and_notify(self, store, athlete, **kwargs):
        from offdays.notifications import notify_discomfort
        store.report_discomfort(athlete["id"], **kwargs)
        status = store.wellness_status(athlete["id"])
        return notify_discomfort(
            store.conn, athlete["id"], status.reports[0], status.assessments[0]
        )

    def test_a_head_report_reaches_the_guardian(self, store, athlete, linked):
        assert self._report_and_notify(
            store, athlete, area="head", severity="niggle"
        ) == 1

    def test_a_plain_niggle_does_not(self, store, athlete, linked):
        """A parent buzzed for every twinge stops reading the notifications."""
        assert self._report_and_notify(
            store, athlete, area="knee", severity="niggle"
        ) == 0

    def test_the_note_never_reaches_a_lock_screen(self, store, athlete, linked):
        """A guardian can read it in the app, logged in as themselves. A push
        notification is read in front of whoever is standing there."""
        self._report_and_notify(
            store, athlete, area="knee", severity="hurts", note="secret thing",
        )
        rows = store.conn.execute(
            "SELECT title, body FROM notifications WHERE kind = 'discomfort'"
        ).fetchall()
        assert rows
        for row in rows:
            assert "secret thing" not in f"{row['title']} {row['body']}"

    def test_editing_a_report_does_not_buzz_twice(self, store, athlete, linked):
        self._report_and_notify(store, athlete, area="knee", severity="hurts")
        again = self._report_and_notify(store, athlete, area="knee", severity="hurts")
        assert again == 0
