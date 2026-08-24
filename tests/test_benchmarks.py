"""Age-appropriate training budgets, and benchmarks that live inside them.

The class that matters is TestTheAppWillSayStop. A benchmark that can only ever
say "do more" is a pressure machine pointed at children, and these tests pin
down the behaviours that stop this one becoming that: a full week reads as
finished, an over-budget week is said plainly, and volume comparisons disappear
once an athlete has done enough.
"""
from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from athleteiq import benchmarks as B
from athleteiq.db import connect
from athleteiq.store import Store

TODAY = date(2026, 8, 24)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "b.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    team = store.create_team(org, "Varsity")
    return {"org": org, "team": team}


def add_athlete(store, program, name, age, position="Midfield"):
    athlete = store.create_user(
        program["org"], "athlete", name,
        birth_year=TODAY.year - age, dominant_hand="right",
    )
    store.join_team(program["team"]["join_code"], athlete["id"], position=position)
    return athlete


def train(store, athlete_id, on: date, minutes: float, seed=1, quality_rom_cv=0.08,
          drill="lax_wall_ball"):
    """Log a session of a given wall-clock length.

    Rep timings are jittered rather than evenly spaced: the integrity checks
    treat a metronomic stream as a generated payload and hold the session for
    review, so a helper without jitter silently produces sessions that never
    count and tests that fail for the wrong reason.
    """
    slot = store.start_session(athlete_id, drill)
    rng = random.Random(seed)
    duration_ms = int(minutes * 60_000)
    reps = []
    t = 0
    while True:
        gap = max(320, int(rng.gauss(900, 190)))
        if t + gap > duration_ms - 500:
            break
        t += gap
        rom = 0.47 * (1 + rng.gauss(0, quality_rom_cv))
        reps.append({
            "t_ms": t,
            "hand": "left" if len(reps) % 2 else "right", "confidence": 0.9,
            "rom": round(max(0.01, rom), 3), "peak": round(rom * 0.7, 3),
            "cycle_ms": max(200, int(rng.gauss(880, 150))),
        })
    when = datetime(on.year, on.month, on.day, 17, tzinfo=timezone.utc)
    return store.submit_session(
        athlete_id, slot["session_id"], slot["nonce"],
        duration_ms=duration_ms, reps=reps, mean_confidence=0.9,
        completed_at=when.isoformat(),
    )


class TestAgeBands:
    def test_every_age_lands_in_exactly_one_band(self):
        for age in range(5, 40):
            matches = [b for b in B.AGE_BANDS if b.contains(age)]
            assert len(matches) == 1, f"age {age} matched {len(matches)} bands"

    def test_budgets_grow_with_age(self):
        targets = [b.weekly_target for b in B.AGE_BANDS]
        assert targets == sorted(targets)

    def test_each_band_is_internally_ordered(self):
        for band in B.AGE_BANDS:
            assert band.weekly_min < band.weekly_target < band.weekly_max
            assert band.days_target <= band.days_max

    def test_the_youngest_budget_is_genuinely_small(self):
        """Under-11s should be playing, not doing an evening job."""
        youngest = B.AGE_BANDS[0]
        assert youngest.weekly_target <= 45
        assert youngest.session_max <= 20
        assert youngest.days_max <= 3

    def test_no_band_recommends_training_every_day(self):
        """Rest days are guidance, not an optional extra."""
        for band in B.AGE_BANDS:
            assert band.days_max <= 6

    def test_an_unknown_age_gets_a_conservative_budget(self):
        """Same principle as treating an unknown age as a minor."""
        band = B.band_for(None)
        assert band.weekly_target <= B.AGE_BANDS[2].weekly_target

    def test_an_estimated_age_is_treated_conservatively_too(self):
        assert B.band_for(17, estimated=True).weekly_target <= B.DEFAULT_BAND.weekly_target

    def test_a_program_can_scale_the_budget_but_must_choose_to(self, monkeypatch):
        from athleteiq.config import Config

        monkeypatch.setattr(B, "CONFIG", Config(budget_scale=1.5))
        scaled = B.scaled(B.band_for(13))
        assert scaled.weekly_target == round(B.band_for(13).weekly_target * 1.5)

    def test_the_default_scale_changes_nothing(self):
        band = B.band_for(13)
        assert B.scaled(band).weekly_target == band.weekly_target


class TestTheAppWillSayStop:
    """The behaviours that stop this becoming a pressure machine."""

    def test_a_full_week_reads_as_finished_not_as_progress(self):
        band = B.band_for(12)
        budget = B.assess_time(
            band, B.WeekOfTraining(minutes=band.weekly_target + 5, days=3, sessions=3)
        )
        assert budget.status == B.Status.FULL
        assert budget.is_enough
        assert "enough" in budget.headline.lower()

    def test_an_over_budget_week_is_said_plainly(self):
        band = B.band_for(12)
        budget = B.assess_time(
            band, B.WeekOfTraining(minutes=band.weekly_max + 60, days=6, sessions=8)
        )
        assert budget.status == B.Status.OVER
        assert budget.over_by_minutes > 0

    def test_the_over_budget_message_gives_a_reason_beyond_the_sport(self):
        """"There is more to being your age than this" is the point of it."""
        band = B.band_for(12)
        budget = B.assess_time(
            band, B.WeekOfTraining(minutes=band.weekly_max + 60, days=6, sessions=8)
        )
        assert "rest" in budget.detail.lower()
        assert "more to being your age" in budget.detail.lower()

    def test_a_finished_week_is_told_to_go_and_do_something_else(self):
        band = B.band_for(13)
        budget = B.assess_time(
            band, B.WeekOfTraining(minutes=band.weekly_target + 1, days=3, sessions=3)
        )
        assert "something else" in budget.detail.lower()

    def test_no_message_at_any_status_demands_more_of_a_full_athlete(self):
        band = B.band_for(14)
        for minutes in (band.weekly_target, band.weekly_max, band.weekly_max * 2):
            budget = B.assess_time(
                band, B.WeekOfTraining(minutes=minutes, days=4, sessions=5)
            )
            text = f"{budget.headline} {budget.detail}".lower()
            for nag in ("keep going", "push", "one more", "catch up", "behind"):
                assert nag not in text, f"{nag!r} said to an athlete at {minutes} min"

    def test_a_long_single_session_is_flagged(self, store, program):
        """Shorter and more often beats one long grind at this age."""
        athlete = add_athlete(store, program, "Jordan", 12)
        train(store, athlete["id"], TODAY, minutes=60)
        report = B.report(store.conn, athlete["id"], TODAY)
        assert any("in one go" in a for a in report["advisories"])

    def test_training_every_day_is_flagged(self, store, program):
        athlete = add_athlete(store, program, "Jordan", 13)
        for offset in range(7):
            train(store, athlete["id"], TODAY - timedelta(days=offset), minutes=8, seed=offset)
        report = B.report(store.conn, athlete["id"], TODAY)
        assert any("days off" in a for a in report["advisories"])

    def test_a_young_athlete_over_target_is_pointed_at_other_sports(self, store, program):
        athlete = add_athlete(store, program, "Small Kid", 10)
        for offset in range(3):
            train(store, athlete["id"], TODAY - timedelta(days=offset), minutes=20, seed=offset)
        report = B.report(store.conn, athlete["id"], TODAY)
        assert any("other sports" in a for a in report["advisories"])


class TestEncouragement:
    def test_an_athlete_who_has_not_started_is_told_how_little_it_takes(self):
        budget = B.assess_time(B.band_for(12), B.WeekOfTraining())
        assert budget.status == B.Status.UNKNOWN
        assert "not an evening job" in budget.detail

    def test_a_building_athlete_gets_a_small_concrete_ask(self):
        band = B.band_for(13)
        budget = B.assess_time(
            band, B.WeekOfTraining(minutes=10, days=1, sessions=1), "Jordan"
        )
        assert budget.status == B.Status.BUILDING
        assert "more short session" in budget.detail

    def test_a_name_does_not_break_the_grammar(self):
        """"Jordan are building" is what interpolating a name into a
        second-person sentence gets you."""
        for name in ("Jordan", ""):
            budget = B.assess_time(
                B.band_for(13), B.WeekOfTraining(minutes=10, days=1, sessions=1), name
            )
            assert " are building" not in budget.detail
            assert " are building" not in budget.headline

    def test_an_athlete_inside_the_range_is_told_it_is_already_solid(self):
        band = B.band_for(14)
        budget = B.assess_time(
            band,
            B.WeekOfTraining(minutes=(band.weekly_min + band.weekly_target) / 2, days=3, sessions=3),
        )
        assert budget.status == B.Status.GOOD
        assert "solid week" in budget.detail


class TestPeerComparison:
    def _squad(self, store, program, count=10, age=13):
        athletes = []
        for i in range(count):
            athlete = add_athlete(store, program, f"Athlete {i}", age)
            for offset in range(3):
                train(
                    store, athlete["id"], TODAY - timedelta(days=offset * 3),
                    minutes=10 + i, seed=i * 10 + offset,
                )
            athletes.append(athlete)
        return athletes

    def test_no_comparison_is_shown_for_a_tiny_peer_group(self, store, program):
        """Neither meaningful nor anonymous with three athletes."""
        athletes = self._squad(store, program, count=3)
        report = B.report(store.conn, athletes[0]["id"], TODAY)
        assert report["comparisons"] == []

    def test_comparisons_appear_once_the_group_is_big_enough(self, store, program):
        athletes = self._squad(store, program, count=10)
        report = B.report(store.conn, athletes[0]["id"], TODAY)
        assert report["comparisons"]
        assert all(c["peer_count"] >= B.MIN_PEER_GROUP for c in report["comparisons"])

    def test_athletes_are_compared_only_with_their_own_age_band(self, store, program):
        """Ranking a twelve-year-old against seventeen-year-olds reports their
        birthday, not their training."""
        young = self._squad(store, program, count=9, age=12)
        for i in range(9):
            add_athlete(store, program, f"Older {i}", 17)
        report = B.report(store.conn, young[0]["id"], TODAY)
        for comparison in report["comparisons"]:
            assert comparison["peer_count"] <= 9

    def test_volume_is_never_a_comparison(self, store, program):
        """The metric that would turn this into a race."""
        athletes = self._squad(store, program, count=10)
        report = B.report(store.conn, athletes[0]["id"], TODAY)
        metrics = {c["metric"] for c in report["comparisons"]}
        for banned in ("reps", "minutes", "volume", "xp", "sessions"):
            assert banned not in metrics

    def test_consistency_is_offered_only_to_an_athlete_still_building(self, store, program):
        """"You train fewer days than your peers" is the wrong thing to tell
        someone who has already done a full week."""
        athletes = self._squad(store, program, count=10, age=13)
        busy = athletes[0]
        band = B.band_for(13)
        # Push this one comfortably past their weekly target.
        for offset in range(4):
            train(
                store, busy["id"], TODAY - timedelta(days=offset),
                minutes=band.weekly_target / 3, seed=500 + offset,
            )
        report = B.report(store.conn, busy["id"], TODAY)
        assert report["budget"]["is_enough"]
        assert "consistency" not in {c["metric"] for c in report["comparisons"]}

    def test_quality_and_offhand_are_what_a_full_athlete_sees(self, store, program):
        athletes = self._squad(store, program, count=10, age=13)
        report = B.report(store.conn, athletes[0]["id"], TODAY)
        metrics = {c["metric"] for c in report["comparisons"]}
        assert metrics & {"quality", "offhand"}

    def test_a_percentile_is_a_whole_number_in_range(self, store, program):
        athletes = self._squad(store, program, count=12)
        report = B.report(store.conn, athletes[3]["id"], TODAY)
        for comparison in report["comparisons"]:
            if comparison["percentile"] is not None:
                assert 0 <= comparison["percentile"] <= 100


class TestReport:
    def test_a_report_leads_with_the_budget_not_the_percentile(self, store, program):
        athlete = add_athlete(store, program, "Jordan", 13)
        train(store, athlete["id"], TODAY, minutes=20)
        report = B.report(store.conn, athlete["id"], TODAY)
        assert "budget" in report
        assert report["budget"]["headline"]

    def test_the_report_says_where_the_numbers_come_from(self, store, program):
        athlete = add_athlete(store, program, "Jordan", 13)
        report = B.report(store.conn, athlete["id"], TODAY)
        assert "not medical advice" in report["disclaimer"]

    def test_only_this_week_is_counted(self, store, program):
        athlete = add_athlete(store, program, "Jordan", 13)
        # Ten days back: inside the offline backdate limit so it is honoured,
        # but outside the seven-day window the budget measures.
        train(store, athlete["id"], TODAY - timedelta(days=10), minutes=60)
        report = B.report(store.conn, athlete["id"], TODAY)
        assert report["budget"]["minutes"] == 0

    def test_an_unknown_athlete_returns_nothing_rather_than_raising(self, store):
        assert B.report(store.conn, 9999, TODAY) == {}

    def test_the_report_is_json_safe(self, store, program):
        import json

        athlete = add_athlete(store, program, "Jordan", 13)
        train(store, athlete["id"], TODAY, minutes=20)
        assert json.loads(json.dumps(B.report(store.conn, athlete["id"], TODAY)))


class TestProgramSummary:
    def test_over_budget_athletes_are_surfaced_to_the_coach(self, store, program):
        """As prominently as the quiet ones. A dashboard that only shows who is
        behind teaches a squad that more is always better."""
        quiet = add_athlete(store, program, "Quiet Kid", 12)
        busy = add_athlete(store, program, "Busy Kid", 12)
        band = B.band_for(12)
        for offset in range(6):
            train(
                store, busy["id"], TODAY - timedelta(days=offset),
                minutes=band.weekly_max / 3, seed=offset,
            )

        summary = B.program_summary(store.conn, [quiet["id"], busy["id"]], TODAY)
        assert summary["counts"][B.Status.OVER] == 1
        assert summary["over_budget"][0]["display_name"] == "Busy Kid"
        assert summary["counts"][B.Status.UNKNOWN] == 1

    def test_a_settled_squad_reports_nobody_over(self, store, program):
        band = B.band_for(13)
        for i in range(4):
            athlete = add_athlete(store, program, f"Athlete {i}", 13)
            train(store, athlete["id"], TODAY, minutes=band.weekly_target / 2, seed=i)
        ids = [
            r["id"] for r in store.conn.execute(
                "SELECT id FROM users WHERE role = 'athlete'"
            )
        ]
        summary = B.program_summary(store.conn, ids, TODAY)
        assert summary["over_budget"] == []


class TestTheCopyReadsLikeEnglish:
    """The wording is the product here, so it gets pinned like any other output."""

    def test_a_single_day_is_not_pluralised(self, store, program):
        athlete = add_athlete(store, program, "Jordan", 12)
        train(store, athlete["id"], TODAY, minutes=50)
        budget = B.report(store.conn, athlete["id"], TODAY)["budget"]
        assert budget["status"] == B.Status.FULL
        assert "over 1 day is" in budget["detail"]
        assert "1 days" not in budget["detail"]

    def test_the_empty_week_describes_this_band_not_a_fixed_one(self, store, program):
        for age, expected in ((12, "three short sessions"), (17, "four short sessions")):
            athlete = add_athlete(store, program, f"A{age}", age)
            detail = B.report(store.conn, athlete["id"], TODAY)["budget"]["detail"]
            assert expected in detail

    def test_the_suggested_sessions_never_exceed_the_bands_own_days(self, store, program):
        """Asking a 3-day band for 4 sessions is how a rest day gets trained away."""
        for age in (10, 12, 14, 16, 18):
            athlete = add_athlete(store, program, f"B{age}", age)
            band = B.scaled(B.band_for(age))
            train(store, athlete["id"], TODAY, minutes=max(1, band.weekly_min - 1))
            budget = B.report(store.conn, athlete["id"], TODAY)["budget"]
            assert budget["status"] == B.Status.BUILDING
            wanted = int(re.search(r"(\d+) more short session", budget["detail"]).group(1))
            assert 1 <= wanted <= band.days_target, (age, budget["detail"])

    def test_no_message_ever_reads_as_a_demand_for_more(self, store, program):
        """Every status, checked for the words a burnt-out kid does not need."""
        banned = ("must", "should be doing more", "behind", "falling behind", "only")
        for age, minutes in ((12, 0), (12, 8), (12, 34), (12, 50), (12, 200)):
            athlete = add_athlete(store, program, f"C{age}{minutes}", age)
            if minutes:
                train(store, athlete["id"], TODAY, minutes=minutes)
            budget = B.report(store.conn, athlete["id"], TODAY)["budget"]
            text = f"{budget['headline']} {budget['detail']}".lower()
            for word in banned:
                assert word not in text, (minutes, word, text)


# ---------------------------------------------------------------------------
# Position benchmarks
# ---------------------------------------------------------------------------

def squad(store, program, spec, age=12, drill="lax_wall_ball", minutes=12, days=3):
    """Build a roster written the way a coach types it: {'Middie': 9, 'D': 5}."""
    ids = {}
    for label, n in spec.items():
        for i in range(n):
            name = f"{label}{i}"
            athlete = add_athlete(store, program, name, age, position=label)
            ids[name] = athlete["id"]
            for d in range(days):
                train(store, athlete["id"], TODAY - timedelta(days=d), minutes=minutes,
                      seed=abs(hash(name)) % 997 + d, drill=drill)
    return ids


class TestThePeerPoolWidensUntilItMeansSomething:
    """A team has three goalies. A pool that only tried the narrowest option
    would return nothing for exactly the athletes whose position is most
    distinctive."""

    def test_a_deep_position_is_compared_within_itself(self, store, program):
        ids = squad(store, program, {"Middie": 9, "D": 5})
        pool = B.report(store.conn, ids["Middie0"], TODAY)["peer_pool"]
        assert pool["scope"] == "position"
        assert pool["count"] == 9
        assert pool["label"] == "midfielders your age"

    def test_a_thin_position_widens_to_its_family(self, store, program):
        """Five attackers is too few; attackers and midfielders together is not."""
        ids = squad(store, program, {"Middie": 9, "Attack": 5})
        pool = B.report(store.conn, ids["Attack0"], TODAY)["peer_pool"]
        assert pool["scope"] == "group"
        assert pool["count"] == 14
        assert pool["label"] == "attackers and midfielders your age"

    def test_a_lone_specialist_widens_all_the_way_to_the_age_band(self, store, program):
        ids = squad(store, program, {"Middie": 9, "FOGO": 1})
        pool = B.report(store.conn, ids["FOGO0"], TODAY)["peer_pool"]
        assert pool["scope"] == "band"
        assert pool["label"] == "athletes your age"

    def test_an_unrecognised_position_still_gets_compared(self, store, program):
        """A roster typo must not quietly remove a kid from the board."""
        ids = squad(store, program, {"Middie": 9, "TBD": 1})
        report = B.report(store.conn, ids["TBD0"], TODAY)
        assert report["position"] is None
        assert report["peer_pool"]["scope"] == "band"
        assert report["comparisons"], "a kid with a typo'd position still compares"

    def test_the_athlete_is_told_who_they_were_measured_against(self, store, program):
        ids = squad(store, program, {"Middie": 9})
        for comparison in B.report(store.conn, ids["Middie0"], TODAY)["comparisons"]:
            assert comparison["against"] == "9 midfielders your age"

    def test_spelling_variants_land_in_the_same_pool(self, store, program):
        """The whole feature turns on this: 'Middie' and 'MF' are one group."""
        ids = squad(store, program, {"Middie": 3, "MF": 3, "M": 2, "midfielder": 1})
        pool = B.report(store.conn, ids["Middie0"], TODAY)["peer_pool"]
        assert pool["scope"] == "position"
        assert pool["count"] == 9

    def test_volume_is_still_never_compared_at_any_pool_width(self, store, program):
        for spec in ({"Middie": 9}, {"Middie": 9, "Attack": 5}, {"Middie": 9, "FOGO": 1}):
            ids = squad(store, program, spec)
            who = "FOGO0" if "FOGO" in spec else list(ids)[0]
            metrics = {c["metric"] for c in B.report(store.conn, ids[who], TODAY)["comparisons"]}
            assert "volume" not in metrics and "minutes" not in metrics


class TestPositionDecidesWhatIsWorthComparing:

    def test_a_goalie_is_not_ranked_on_weak_hand_balance(self, store, program):
        """Their stick work is two-handed save mechanics. Ranking it would
        make them chase a number that measures nothing they are building."""
        ids = squad(store, program, {"Goalie": 9})
        metrics = {c["metric"] for c in B.report(store.conn, ids["Goalie0"], TODAY)["comparisons"]}
        assert "offhand" not in metrics
        assert "quality" in metrics

    def test_a_field_player_is(self, store, program):
        ids = squad(store, program, {"Middie": 9})
        metrics = {c["metric"] for c in B.report(store.conn, ids["Middie0"], TODAY)["comparisons"]}
        assert "offhand" in metrics


class TestTheMixWorksWithNoPeersAtAll:
    """The half of position benchmarking that a team of one still gets."""

    def test_a_goalie_who_only_does_wall_ball_is_told_so(self, store, program):
        athlete = add_athlete(store, program, "Sam", 12, position="Goalie")
        for d in range(3):
            train(store, athlete["id"], TODAY - timedelta(days=d), minutes=12, seed=d + 1)
        mix = B.report(store.conn, athlete["id"], TODAY)["mix"]
        assert mix["ready"]
        assert mix["position"]["key"] == "goalie"
        assert mix["suggestions"], "one goalie, no peers, still actionable"
        assert "quick stick" in " ".join(mix["suggestions"]).lower()

    def test_every_suggestion_is_a_swap_and_never_an_addition(self, store, program):
        """'Also do lateral bounds' quietly undoes the weekly budget."""
        banned = ("add", "more", "extra", "also", "as well", "on top")
        for position in ("Goalie", "Attack", "D", "FOGO", "LSM", "Middie"):
            athlete = add_athlete(store, program, f"S{position}", 12, position=position)
            for d in range(3):
                train(store, athlete["id"], TODAY - timedelta(days=d), minutes=12, seed=d + 7)
            for suggestion in B.report(store.conn, athlete["id"], TODAY)["mix"]["suggestions"]:
                low = suggestion.lower()
                assert "same minutes" in low
                for word in banned:
                    assert word not in low, (position, word, suggestion)

    def test_nothing_is_suggested_from_a_single_short_session(self, store, program):
        """One session is not a mix, it is a session."""
        athlete = add_athlete(store, program, "Sam", 12, position="Goalie")
        train(store, athlete["id"], TODAY, minutes=8, seed=3)
        mix = B.report(store.conn, athlete["id"], TODAY)["mix"]
        assert mix["ready"] is False
        assert mix["suggestions"] == []

    def test_an_athlete_past_their_ceiling_hears_stop_and_nothing_else(self, store, program):
        """Mix advice next to 'stop' reads as a second task and blunts the first."""
        athlete = add_athlete(store, program, "Sam", 12, position="Goalie")
        for d in range(6):
            train(store, athlete["id"], TODAY - timedelta(days=d), minutes=30, seed=d + 11)
        report = B.report(store.conn, athlete["id"], TODAY)
        assert report["budget"]["status"] == B.Status.OVER
        assert report["mix"]["suggestions"] == []
        assert report["mix"]["slices"], "the chart still shows; only the nudge goes"

    def test_an_athlete_with_no_position_gets_general_guidance(self, store, program):
        athlete = add_athlete(store, program, "Sam", 12, position="TBD")
        for d in range(3):
            train(store, athlete["id"], TODAY - timedelta(days=d), minutes=12, seed=d + 5)
        mix = B.report(store.conn, athlete["id"], TODAY)["mix"]
        assert mix["position"]["key"] == "general"
        assert mix["focus"]

    def test_the_mix_never_recommends_a_drill_that_does_not_exist(self, store, program):
        from athleteiq.drills.catalog import DRILLS_BY_KEY
        athlete = add_athlete(store, program, "Sam", 12, position="Attack")
        for d in range(3):
            train(store, athlete["id"], TODAY - timedelta(days=d), minutes=12, seed=d + 2)
        for item in B.report(store.conn, athlete["id"], TODAY)["mix"]["slices"]:
            assert item["drill_key"] in DRILLS_BY_KEY


class TestWhatTheCoachSeesAboutPositions:

    def test_the_squad_breaks_down_by_position(self, store, program):
        ids = squad(store, program, {"Middie": 4, "Attack": 2, "Goalie": 1})
        summary = B.program_summary(store.conn, list(ids.values()), TODAY)
        counts = {p["key"]: p["count"] for p in summary["positions"]}
        assert counts == {"midfield": 4, "attack": 2, "goalie": 1}

    def test_roster_typos_are_surfaced_rather_than_swallowed(self, store, program):
        """An unresolved position drops that kid out of every position feature."""
        ids = squad(store, program, {"Middie": 2, "wingback": 1})
        summary = B.program_summary(store.conn, list(ids.values()), TODAY)
        assert summary["unrecognised_positions"] == ["wingback"]
        counts = {p["key"]: p["count"] for p in summary["positions"]}
        assert counts["unrecognised"] == 1
