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
        """Soccer should not receive lacrosse emphasis with the labels changed."""
        assert P.for_sport("soccer") == ()
        assert P.normalize("striker", sport="soccer") is None
        assert P.resolve("striker", sport="soccer").key == "general"


class TestUnrecognised:

    def test_typos_are_reported_once_each_for_a_coach_to_fix(self):
        raw = ["Middie", "TBD", "Goalie", "TBD", "wingback", ""]
        assert P.unrecognised(raw) == ["TBD", "wingback"]
