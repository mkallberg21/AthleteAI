"""Multi-sport participation, and the two things that key off it."""

import pytest

from athleteiq import sports as S


def play(key, seasons, primary=False):
    return S.Participation(S.BY_KEY[key], tuple(seasons), primary)


class TestNormalisation:

    @pytest.mark.parametrize("raw,expected", [
        ("Basketball", "basketball"), ("bball", "basketball"), ("B-Ball", "basketball"),
        ("Basketball (JV)", "basketball"), ("XC", "cross_country"),
        ("cross country", "cross_country"), ("Track & Field", "track"),
        ("swim team", "swimming"), ("Karate", "martial_arts"),
        ("snowboarding", "skiing"), ("crew", "rowing"), ("lax", "lacrosse"),
    ])
    def test_real_spellings_resolve(self, raw, expected):
        assert S.normalize(raw).key == expected

    @pytest.mark.parametrize("raw", ["", None, "none", "n/a", "chess", "reading"])
    def test_a_non_sport_is_not_invented(self, raw):
        assert S.normalize(raw) is None

    def test_seasons_are_normalised_and_ordered(self):
        assert S.clean_seasons(["Summer", "FALL", "nonsense"]) == ["fall", "summer"]
        assert S.clean_seasons(None) == []


class TestScoringHowSingleSportAYearIs:

    def test_year_round_single_sport_scores_highest(self):
        profile = S.assess([play("lacrosse", S.SEASONS, True)])
        assert profile.level == S.Level.HIGH
        assert profile.score == 3
        assert len(profile.signals) == 3

    def test_three_sports_across_the_year_scores_lowest(self):
        profile = S.assess([
            play("lacrosse", ["spring"], True),
            play("basketball", ["winter"]),
            play("soccer", ["fall"]),
        ])
        assert profile.level == S.Level.LOW
        assert profile.score == 0
        assert profile.season_coverage == 3

    def test_one_short_season_is_not_specialisation(self):
        """A kid who plays only lacrosse, only in spring, is not the risk case."""
        profile = S.assess([play("lacrosse", ["spring"], True)])
        assert profile.level == S.Level.MODERATE
        assert "more than eight months" not in " ".join(profile.signals)

    def test_nothing_recorded_is_its_own_answer(self):
        """Not a score of zero -- an absence, which must behave as before."""
        profile = S.assess([])
        assert profile.level == S.Level.UNKNOWN
        assert profile.known is False
        assert S.effective_min_age(15, profile) == 15
        assert S.budget_scale(profile) == 1.0

    def test_a_primary_is_chosen_when_none_is_flagged(self):
        profile = S.assess([play("lacrosse", ["spring"]), play("hockey", S.SEASONS)])
        assert profile.primary.sport.key == "hockey"


class TestTheGateMoves:

    def test_variety_starts_position_work_earlier(self):
        profile = S.assess([
            play("lacrosse", ["spring"], True), play("basketball", ["winter"]),
            play("soccer", ["fall"]),
        ])
        assert S.effective_min_age(15, profile) == 13

    def test_year_round_single_sport_delays_it(self):
        profile = S.assess([play("lacrosse", S.SEASONS, True)])
        assert S.effective_min_age(15, profile) == 17

    def test_nothing_goes_below_the_absolute_floor(self):
        """A nine-year-old who plays four sports is the last child who needs a
        position-specific drill mix."""
        profile = S.assess([
            play("lacrosse", ["spring"], True), play("basketball", ["winter"]),
            play("soccer", ["fall"]), play("swimming", ["summer"]),
        ])
        for program_setting in (0, 5, 12, 13):
            assert S.effective_min_age(program_setting, profile) >= S.ABSOLUTE_MIN_AGE

    def test_a_program_that_turned_it_off_stays_off(self):
        """A director's 'never' is not overridden by a season picker."""
        profile = S.assess([
            play("lacrosse", ["spring"], True), play("basketball", ["winter"]),
        ])
        assert S.effective_min_age(99, profile) == 99

    def test_the_adjustment_is_bounded_on_both_sides(self):
        for level in (S.Level.LOW, S.Level.MODERATE, S.Level.HIGH, S.Level.UNKNOWN):
            assert abs(S.AGE_ADJUSTMENT[level]) <= 2


class TestTheBudgetShrinks:

    def test_a_multi_sport_athlete_is_expected_to_do_less_here(self):
        low = S.assess([
            play("lacrosse", ["spring"], True), play("basketball", ["winter"]),
            play("soccer", ["fall"]),
        ])
        assert S.budget_scale(low) < 1.0

    def test_a_single_sport_athlete_gets_the_full_budget(self):
        high = S.assess([play("lacrosse", S.SEASONS, True)])
        assert S.budget_scale(high) == 1.0

    def test_the_scale_never_inflates_a_budget(self):
        """Recording sports must never be a way to unlock more training."""
        for level in S.BUDGET_SCALE.values():
            assert 0 < level <= 1.0


class TestTheCatalogIsInternallySound:

    def test_no_alias_is_claimed_by_two_sports(self):
        """'ball' once resolved to baseball, which made 'B-Ball' basketball's
        problem. An ambiguous alias silently miscounts a child's sports."""
        owner: dict[str, str] = {}
        for sport in S.CATALOG:
            for alias in (sport.key, sport.label, *sport.aliases):
                cleaned = S._clean(alias)
                assert owner.get(cleaned, sport.key) == sport.key, (
                    f"{cleaned!r} claimed by {owner.get(cleaned)} and {sport.key}"
                )
                owner[cleaned] = sport.key

    def test_typical_seasons_are_real_seasons(self):
        for sport in S.CATALOG:
            for season in sport.typical_seasons:
                assert season in S.SEASONS, (sport.key, season)

    def test_no_alias_is_a_bare_ambiguous_word(self):
        vague = {"ball", "sport", "team", "club", "school", "travel", "rec"}
        for sport in S.CATALOG:
            for alias in sport.aliases:
                assert S._clean(alias) not in vague, (sport.key, alias)
