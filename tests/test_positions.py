"""Positions: normalisation, emphasis integrity, and the guards around both.

The failure this module exists to prevent is silent: a position filter that
looks implemented, compiles, runs, and matches nobody because the column
says "Middie" and the query said "midfield". So the tests here lean on real
roster spellings rather than canonical keys.
"""

import pytest

from athleteiq import positions as P
from athleteiq.drills.catalog import DRILLS_BY_KEY


class TestNormalisation:
    """Every string here came from the shape a coach actually types."""

    @pytest.mark.parametrize("raw,expected", [
        ("Attack", "attack"), ("attackman", "attack"), ("Attackmen", "attack"),
        ("ATT", "attack"), ("A", "attack"),
        ("Midfield", "midfield"), ("Middie", "midfield"), ("MID-FIELD", "midfield"),
        ("MF", "midfield"), ("M", "midfield"), ("midfielders", "midfield"),
        ("Defense", "defense"), ("Defence", "defense"), ("Defensemen", "defense"),
        ("D", "defense"), ("D-Pole", "defense"), ("close D", "defense"),
        ("LSM", "lsm"), ("Long Stick Midfield", "lsm"), ("d-mid", "lsm"),
        ("longstick", "lsm"),
        ("FOGO", "fogo"), ("faceoff", "fogo"), ("Face-Off", "fogo"),
        ("draw specialist", "fogo"),
        ("Goalie", "goalie"), ("keeper", "goalie"), ("GK", "goalie"),
        ("G", "goalie"), ("goaltender", "goalie"),
    ])
    def test_roster_spellings_resolve(self, raw, expected):
        assert P.normalize(raw).key == expected

    @pytest.mark.parametrize("raw", ["Goalie (JV)", "JV Goalie", "starting midfield"])
    def test_qualifiers_are_ignored(self, raw):
        assert P.normalize(raw) is not None

    def test_the_first_listed_position_wins(self):
        """A dual-position row is primary-first by convention."""
        assert P.normalize("attackman/midfield").key == "attack"
        assert P.normalize("midfield, attack").key == "midfield"

    @pytest.mark.parametrize("raw", ["TBD", "?", "", "   ", None, "N/A", "unassigned"])
    def test_placeholders_do_not_become_positions(self, raw):
        """Inventing a position from 'TBD' is worse than admitting we don't know."""
        assert P.normalize(raw) is None

    def test_a_stray_letter_is_not_a_position(self):
        """'A Team' is a squad name. Single letters count only when alone."""
        assert P.normalize("A Team") is None
        assert P.normalize("B squad") is None
        assert P.normalize("A").key == "attack"

    def test_resolve_always_gives_something_usable(self):
        assert P.resolve("TBD").key == "general"
        assert P.resolve(None).key == "general"
        assert P.resolve("Goalie").key == "goalie"


class TestTheRegistryIsInternallySound:

    def test_emphasis_shares_sum_to_one(self):
        for pos in (*P.LACROSSE, P.GENERIC):
            assert sum(pos.emphasis.values()) == pytest.approx(1.0), pos.key

    def test_emphasis_only_names_drills_that_exist(self):
        """A typo'd drill key would produce a target for a drill nobody can do."""
        for pos in (*P.LACROSSE, P.GENERIC):
            for key in pos.emphasis:
                assert key in DRILLS_BY_KEY, f"{pos.key} -> {key}"

    def test_no_alias_is_claimed_by_two_positions(self):
        """A shared alias silently sorts athletes into the wrong peer group."""
        owner: dict[str, str] = {}
        for pos in P.LACROSSE:
            for alias in (pos.key, pos.label, *pos.aliases):
                cleaned = P._clean(alias)
                assert owner.get(cleaned, pos.key) == pos.key, (
                    f"{cleaned!r} claimed by {owner.get(cleaned)} and {pos.key}"
                )
                owner[cleaned] = pos.key

    def test_every_position_has_a_readable_plural(self):
        """'midfields your age' is the tell that nobody read the sentence."""
        for pos in P.LACROSSE:
            assert pos.plural == pos.plural.lower() or pos.key == "general"
            assert not pos.plural.endswith("ss")
        assert P.normalize("Middie").plural == "midfielders"
        assert P.normalize("Defense").plural == "defenders"

    def test_every_group_has_a_label(self):
        for pos in (*P.LACROSSE, P.GENERIC):
            assert pos.group in P.GROUP_LABELS

    def test_a_sport_with_no_model_gets_silence_not_a_guess(self):
        """Curling should not receive lacrosse emphasis with the labels changed.

        This used to say soccer, which now has its own positions -- the whole
        point of going multi-sport. The rule it protects is unchanged: an
        unmodelled sport gets nothing rather than somebody else's positions.
        """
        assert P.for_sport("curling") == ()
        assert P.normalize("skip", sport="curling") is None
        assert P.resolve("skip", sport="curling").key == "general"


class TestUnrecognised:

    def test_typos_are_reported_once_each_for_a_coach_to_fix(self):
        raw = ["Middie", "TBD", "Goalie", "TBD", "wingback", ""]
        assert P.unrecognised(raw) == ["TBD", "wingback"]



class TestCrossSportTransfer:
    """The honest argument for not specialising, written where a kid reads it."""

    def test_every_drill_in_the_catalog_has_a_transfer_entry(self):
        """A drill with no entry silently renders a blank where the reason goes."""
        from athleteiq import transfer
        for key in DRILLS_BY_KEY:
            assert key in transfer.TRANSFERS, key
            assert transfer.TRANSFERS[key], key

    def test_the_home_sport_is_filtered_out(self):
        from athleteiq import transfer
        for key in DRILLS_BY_KEY:
            for item in transfer.for_drill(key, "lacrosse", limit=0):
                assert item.sport.lower() != "lacrosse"

    def test_a_reason_is_given_not_just_a_sport_name(self):
        """Every 'why' names a moment in the sport, not a quality.

        Length is a poor proxy for this -- "the 80th minute" is fifteen
        characters and one of the most concrete lines in the table -- so the
        test bans the filler phrasings instead.
        """
        from athleteiq import transfer
        filler = ("helps with", "good for", "improves your", "builds your",
                  "is useful", "great for", "works your")
        for key, items in transfer.TRANSFERS.items():
            for item in items:
                assert item.sport.strip(), key
                assert item.why.strip(), key
                for phrase in filler:
                    assert phrase not in item.why.lower(), (key, item.why)

    def test_stick_drills_are_not_padded_out(self):
        """A claim a kid can check and find false costs every other claim."""
        from athleteiq import transfer
        assert len(transfer.TRANSFERS["lax_quick_stick"]) <= 2
        assert len(transfer.TRANSFERS["lax_wall_ball"]) <= 2

    def test_the_blurb_reads_as_a_sentence(self):
        from athleteiq import transfer
        assert transfer.blurb("gen_lateral_bound", "lacrosse") == (
            "This one pays off in Basketball, Soccer and Tennis too."
        )
        assert transfer.blurb("lax_wall_ball", "lacrosse") == (
            "This one pays off in Baseball and Hockey too."
        )

    def test_an_unknown_drill_says_nothing_rather_than_guessing(self):
        from athleteiq import transfer
        assert transfer.for_drill("gen_nonexistent") == []
        assert transfer.blurb("gen_nonexistent") == ""


class TestEverySportIsWiredUpProperly:
    """The failure this catches is silent: a sport whose positions reference a
    drill that does not exist, or whose weights do not add up, looks fine until
    an athlete opens the app and sees an empty mix."""

    SPORTS = (
        "lacrosse", "basketball", "soccer", "volleyball", "baseball", "softball",
        "cheer", "dance", "swimming", "track", "football", "gymnastics",
        "tennis", "cross_country", "hockey", "rugby",
    )

    @pytest.mark.parametrize("sport", SPORTS)
    def test_the_sport_has_positions(self, sport):
        assert P.for_sport(sport), sport

    @pytest.mark.parametrize("sport", SPORTS)
    def test_the_sport_is_in_the_signup_catalog(self, sport):
        from athleteiq import sports
        assert sports.BY_KEY.get(sport) is not None, sport

    def test_every_position_only_names_drills_that_exist(self):
        for position in P.ALL_POSITIONS:
            for key in position.emphasis:
                assert key in DRILLS_BY_KEY, f"{position.sport}/{position.key} -> {key}"

    def test_every_emphasis_sums_to_one(self):
        for position in P.ALL_POSITIONS:
            assert sum(position.emphasis.values()) == pytest.approx(1.0), position.key

    def test_every_position_says_something_useful(self):
        for position in P.ALL_POSITIONS:
            assert len(position.focus) > 20, position.key
            assert position.plural and position.plural != position.label

    def test_no_alias_is_claimed_by_two_positions_in_the_same_sport(self):
        """A shared alias silently sorts athletes into the wrong peer group."""
        for sport, group in P.BY_SPORT.items():
            owner: dict[str, str] = {}
            for position in group:
                for alias in (position.key, position.label, *position.aliases):
                    cleaned = P._clean(alias)
                    assert owner.get(cleaned, position.key) == position.key, \
                        f"{sport}: {cleaned!r} claimed twice"
                    owner[cleaned] = position.key

    def test_the_same_shorthand_can_mean_different_things_in_different_sports(self):
        """'C' is a centre in basketball and a catcher in baseball. Positions
        are resolved per sport for exactly this reason."""
        assert P.normalize("C", "basketball").key == "post"
        assert P.normalize("C", "baseball").key == "catcher"
        assert P.normalize("D", "lacrosse").key == "defense"
        assert P.normalize("D", "hockey").key == "defence"

    @pytest.mark.parametrize("sport,raw,expected", [
        ("basketball", "PG", "guard"), ("basketball", "Small Forward", "wing"),
        ("soccer", "GK", "goalkeeper"), ("soccer", "Striker", "forward"),
        ("volleyball", "Libero", "libero"), ("volleyball", "OH", "hitter"),
        ("baseball", "SS", "infield"), ("softball", "Pitcher", "pitcher"),
        ("cheer", "Flyer", "flyer"), ("cheer", "Back Spot", "backspot"),
        ("dance", "Hip Hop", "hip_hop"), ("swimming", "Butterfly", "stroke"),
        ("track", "Shot Put", "throws"), ("track", "800", "middle_distance"),
        ("football", "QB", "quarterback"), ("football", "Wide Receiver", "skill"),
        ("gymnastics", "Uneven Bars", "bars"), ("tennis", "Doubles", "doubles"),
        ("cross_country", "Runner", "distance"), ("hockey", "Goalie", "goaltender"),
        ("rugby", "Prop", "front_row"), ("rugby", "Fullback", "backs"),
    ])
    def test_the_shorthand_a_coach_types(self, sport, raw, expected):
        assert P.normalize(raw, sport).key == expected

    def test_weak_hand_is_only_compared_where_a_drill_reports_it(self):
        """Only the two stick drills report a left/right split, so ranking any
        other sport on it would rank every child on zero."""
        for position in P.ALL_POSITIONS:
            if position.sport not in ("lacrosse", "general"):
                assert position.offhand_matters is False, position.key

    def test_a_sport_with_no_model_still_gets_honest_silence(self):
        assert P.for_sport("underwater basket weaving") == ()
        assert P.resolve("striker", sport="curling").key == "general"


class TestTheMixHelper:

    def test_it_normalises_relative_weights(self):
        assert P.mix(a=3, b=1) == {"a": 0.75, "b": 0.25}

    def test_it_refuses_an_empty_position(self):
        with pytest.raises(ValueError):
            P.mix()
