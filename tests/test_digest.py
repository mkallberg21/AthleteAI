"""The weekly coach digest.

The class that matters most is TestNoAthleteIsNamed. Everything else here is
correctness; that one is the product decision, and it is exactly the kind of
constraint a later change breaks without anyone noticing until a coach forwards
an email with a twelve-year-old's name next to "didn't log a session".
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

import pytest

from athleteiq import digest as D
from athleteiq.db import connect
from athleteiq.store import Store

# A Monday, so "last complete week" is unambiguous.
TODAY = date(2026, 8, 24)
LAST_WEEK_START = date(2026, 8, 17)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "d.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore Lacrosse Club")
    coach = store.create_user(org, "coach", "Coach Rivera", email="coach@example.com")
    team = store.create_team(org, "Varsity")
    athletes = []
    for name in ("Jordan Pierce", "Sam Rivera", "Drew Halloran", "Bailey Nguyen"):
        athlete = store.create_user(
            org, "athlete", name, birth_year=2011, dominant_hand="right"
        )
        store.join_team(team["join_code"], athlete["id"])
        athletes.append(athlete)
    return {"org": org, "coach": coach, "team": team, "athletes": athletes}


def train(store, athlete_id, on: date, seed=1, reps=120, offhand=0.5):
    slot = store.start_session(athlete_id, "lax_wall_ball")
    rng = random.Random(seed)
    t, events = 0, []
    for _ in range(reps):
        rom = 0.47 * (1 + rng.gauss(0, 0.08))
        t += max(150, int(rng.gauss(880, 180)))
        events.append({
            "t_ms": t,
            "hand": "left" if rng.random() < offhand else "right",
            "confidence": 0.9, "rom": round(max(0.01, rom), 3),
            "peak": round(rom * 0.7, 3), "cycle_ms": max(120, int(rng.gauss(880, 150))),
        })
    when = datetime(on.year, on.month, on.day, 12, tzinfo=timezone.utc)
    return store.submit_session(
        athlete_id, slot["session_id"], slot["nonce"],
        duration_ms=t + 700, reps=events, mean_confidence=0.9,
        completed_at=when.isoformat(),
    )


def busy_week(store, program, start: date, athletes=4, days=3, seed=1, offhand=0.5):
    for index, athlete in enumerate(program["athletes"][:athletes]):
        for day in range(days):
            train(
                store, athlete["id"], start + timedelta(days=day),
                seed=seed + index * 10 + day, offhand=offhand,
            )


class TestWeekArithmetic:
    def test_last_complete_week_is_the_one_that_ended(self):
        """A digest sent Monday reports the finished week, not this one."""
        start, end = D.last_complete_week(TODAY)
        assert start == LAST_WEEK_START
        assert end == date(2026, 8, 23)
        assert end < TODAY

    def test_weeks_run_monday_to_sunday(self):
        start, end = D.week_bounds(date(2026, 8, 19))  # a Wednesday
        assert start.weekday() == 0
        assert end.weekday() == 6
        assert (end - start).days == 6


class TestKPI:
    def test_a_tiny_change_reads_as_steady_not_as_zero_growth(self):
        """"up 0%" reads as a bug; the number simply did not move."""
        kpi = D.KPI("k", "Thing", value=0.4001, previous=0.4, unit="percent")
        assert kpi.direction == "flat"
        assert kpi.change_text() == "holding steady"

    def test_a_real_change_is_reported_with_direction(self):
        kpi = D.KPI("k", "Thing", value=0.55, previous=0.40, unit="percent")
        assert kpi.direction == "up"
        assert "up 15 points" == kpi.change_text()

    def test_lower_is_better_inverts_the_direction(self):
        kpi = D.KPI("k", "Injuries", value=2, previous=6, higher_is_better=False)
        assert kpi.direction == "up"

    def test_a_first_week_is_not_a_record(self):
        assert not D.KPI("k", "Thing", value=100, previous=None, best=None).is_record

    def test_matching_the_best_by_a_rounding_error_is_not_a_record(self):
        """A record badge on a flat number devalues every other one."""
        kpi = D.KPI("k", "Thing", value=0.4001, previous=0.4, best=0.4, unit="percent")
        assert not kpi.is_record

    def test_genuinely_beating_the_best_is_a_record(self):
        kpi = D.KPI("k", "Thing", value=0.55, previous=0.40, best=0.50, unit="percent")
        assert kpi.is_record

    def test_growth_from_zero_is_not_a_percentage(self):
        kpi = D.KPI("k", "Reps", value=500, previous=0)
        assert kpi.delta_pct is None
        assert "%" not in kpi.change_text()

    def test_percent_and_count_format_differently(self):
        assert D.KPI("k", "x", value=0.876, unit="percent").formatted() == "88%"
        assert D.KPI("k", "x", value=3828.0).formatted() == "3,828"
        assert D.KPI("k", "x", value=88.6, unit="score").formatted() == "89"


class TestComputation:
    def test_an_empty_program_says_so_without_crashing(self, store):
        org = store.create_org("Empty")
        report = D.compute(store.conn, org, today=TODAY)
        assert report.roster_size == 0
        assert "No athletes" in report.headline

    def test_participation_is_measured_against_the_whole_roster(self, store, program):
        busy_week(store, program, LAST_WEEK_START, athletes=2)
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert report.kpi("participation").value == pytest.approx(0.5)

    def test_consistency_needs_three_separate_days(self, store, program):
        # One athlete trains three days, another trains twice on one day.
        for day in range(3):
            train(store, program["athletes"][0]["id"], LAST_WEEK_START + timedelta(days=day), seed=day)
        train(store, program["athletes"][1]["id"], LAST_WEEK_START, seed=50)
        train(store, program["athletes"][1]["id"], LAST_WEEK_START, seed=51)

        report = D.compute(store.conn, program["org"], today=TODAY)
        assert report.kpi("consistency").value == pytest.approx(0.25)

    def test_sessions_outside_the_week_are_excluded(self, store, program):
        busy_week(store, program, LAST_WEEK_START - timedelta(days=14))
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert report.kpi("participation").value == 0

    def test_week_over_week_comparison_works(self, store, program):
        busy_week(store, program, LAST_WEEK_START - timedelta(days=7), athletes=2, seed=1)
        busy_week(store, program, LAST_WEEK_START, athletes=4, seed=200)
        report = D.compute(store.conn, program["org"], today=TODAY)
        participation = report.kpi("participation")
        assert participation.value > participation.previous
        assert participation.direction == "up"

    def test_offhand_share_is_measured(self, store, program):
        busy_week(store, program, LAST_WEEK_START, offhand=0.8)
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert report.kpi("offhand").value > 0.6

    def test_a_team_scope_only_counts_that_team(self, store, program):
        other = store.create_team(program["org"], "JV")
        outsider = store.create_user(program["org"], "athlete", "JV Kid", dominant_hand="right")
        store.join_team(other["join_code"], outsider["id"])
        busy_week(store, program, LAST_WEEK_START, athletes=4)

        team_report = D.compute(
            store.conn, program["org"], team_id=program["team"]["id"], today=TODAY
        )
        assert team_report.roster_size == 4
        assert team_report.kpi("participation").value == pytest.approx(1.0)

    def test_every_kpi_serializes(self, store, program):
        import json

        busy_week(store, program, LAST_WEEK_START)
        payload = json.loads(json.dumps(D.compute(store.conn, program["org"], today=TODAY).to_dict()))
        assert payload["kpis"]
        for kpi in payload["kpis"]:
            assert {"label", "display", "change_text", "direction"} <= kpi.keys()


class TestNarrative:
    def test_a_quiet_week_is_stated_not_dressed_up(self, store, program):
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert "Quiet week" in report.headline

    def test_a_busy_week_leads_with_something_true(self, store, program):
        busy_week(store, program, LAST_WEEK_START)
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert report.headline
        assert "Quiet week" not in report.headline

    def test_full_participation_is_called_out(self, store, program):
        busy_week(store, program, LAST_WEEK_START, athletes=4)
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert any("Every single athlete" in m for m in report.milestones)

    def test_there_is_always_a_target_to_beat(self, store, program):
        for athletes in (0, 2, 4):
            if athletes:
                busy_week(store, program, LAST_WEEK_START, athletes=athletes, seed=athletes * 7)
            report = D.compute(store.conn, program["org"], today=TODAY)
            assert report.target


class TestNoAthleteIsNamed:
    """The product decision this feature exists to hold.

    Not the athletes who did nothing, and not the ones who did the most --
    naming the same top three weekly tells everyone else, weekly, that they are
    not one of them.
    """

    def _rendered(self, store, program) -> str:
        report = D.compute(store.conn, program["org"], today=TODAY)
        return " ".join([
            D.subject_line(report),
            D.render_text(report),
            D.render_html(report, "https://example.com"),
            str(report.to_dict()),
        ])

    def test_no_athlete_name_appears_anywhere(self, store, program):
        # A deliberately lopsided week: one athlete does everything, one nothing.
        for day in range(5):
            train(store, program["athletes"][0]["id"], LAST_WEEK_START + timedelta(days=day), seed=day)
        train(store, program["athletes"][1]["id"], LAST_WEEK_START, seed=99)

        blob = self._rendered(store, program)
        for athlete in program["athletes"]:
            first, last = athlete["display_name"].split()
            assert athlete["display_name"] not in blob
            assert last not in blob, f"{last} leaked into the digest"

    def test_athletes_needing_attention_are_counted_not_listed(self, store, program):
        train(store, program["athletes"][0]["id"], LAST_WEEK_START, seed=5)
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert report.attention["not_trained_this_week"] == 3
        assert all(isinstance(v, int) for v in report.attention.values())

    def test_milestones_are_collective_not_individual(self, store, program):
        busy_week(store, program, LAST_WEEK_START, athletes=4, offhand=0.5)
        report = D.compute(store.conn, program["org"], today=TODAY)
        for milestone in report.milestones:
            for athlete in program["athletes"]:
                assert athlete["display_name"].split()[1] not in milestone

    def test_the_email_says_it_omits_names_on_purpose(self, store, program):
        """So a coach knows the omission is a decision, not a gap."""
        busy_week(store, program, LAST_WEEK_START)
        report = D.compute(store.conn, program["org"], today=TODAY)
        # Checked on "by design" rather than the full sentence: the plain-text
        # version wraps mid-phrase, and a test that breaks on line wrapping
        # stops protecting the thing it was written for.
        assert "by design" in D.render_html(report).lower()
        assert "by design" in D.render_text(report).lower()
        assert "no individual athlete" in D.render_html(report).lower()


class TestRendering:
    def test_html_is_email_safe(self, store, program):
        """No flexbox, no grid, no external stylesheet -- clients strip all three."""
        busy_week(store, program, LAST_WEEK_START)
        html = D.render_html(D.compute(store.conn, program["org"], today=TODAY))
        lowered = html.lower()
        assert "display:flex" not in lowered
        assert "display:grid" not in lowered
        assert "<link" not in lowered
        assert "table" in lowered

    def test_html_escapes_program_names(self, store):
        org = store.create_org("<script>alert(1)</script> LC")
        html = D.render_html(D.compute(store.conn, org, today=TODAY))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_text_and_html_carry_the_same_headline(self, store, program):
        busy_week(store, program, LAST_WEEK_START)
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert report.headline in D.render_text(report)

    def test_the_subject_line_carries_a_number(self, store, program):
        busy_week(store, program, LAST_WEEK_START)
        subject = D.subject_line(D.compute(store.conn, program["org"], today=TODAY))
        assert "%" in subject

    def test_the_dashboard_link_only_appears_when_configured(self, store, program):
        train(store, program["athletes"][0]["id"], LAST_WEEK_START, seed=3)
        report = D.compute(store.conn, program["org"], today=TODAY)
        assert "https://example.com" in D.render_html(report, "https://example.com")
        assert "href=" not in D.render_html(report, "")

    def test_attention_grammar_survives_a_count_of_one(self, store):
        lines = D.attention_lines(
            {"not_trained_this_week": 1, "needs_rest": 1, "review_queue": 1}
        )
        joined = " ".join(lines)
        assert "1 athlete didn't" in joined
        assert "1 is due" in joined
        assert "1 session needs" in joined

    def test_attention_grammar_survives_a_count_of_many(self, store):
        joined = " ".join(D.attention_lines(
            {"not_trained_this_week": 3, "needs_rest": 2, "review_queue": 4}
        ))
        assert "3 athletes didn't" in joined
        assert "2 are due" in joined
        assert "4 sessions need a" in joined
