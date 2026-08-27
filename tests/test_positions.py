"""Positions: normalisation, emphasis integrity, and the guards around both.

The failure this module exists to prevent is silent: a position filter that
looks implemented, compiles, runs, and matches nobody because the column
says "Middie" and the query said "midfield". So the tests here lean on real
roster spellings rather than canonical keys.
"""

import pytest

from offdays import positions as P
from offdays.drills import ALL_DRILLS
from offdays.positions import ALL_POSITIONS
from offdays.drills.catalog import DRILLS_BY_KEY


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
        from offdays import transfer
        for key in DRILLS_BY_KEY:
            assert key in transfer.TRANSFERS, key
            assert transfer.TRANSFERS[key], key

    def test_the_home_sport_is_filtered_out(self):
        from offdays import transfer
        for key in DRILLS_BY_KEY:
            for item in transfer.for_drill(key, "lacrosse", limit=0):
                assert item.sport.lower() != "lacrosse"

    def test_a_reason_is_given_not_just_a_sport_name(self):
        """Every 'why' names a moment in the sport, not a quality.

        Length is a poor proxy for this -- "the 80th minute" is fifteen
        characters and one of the most concrete lines in the table -- so the
        test bans the filler phrasings instead.
        """
        from offdays import transfer
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
        from offdays import transfer
        assert len(transfer.TRANSFERS["lax_quick_stick"]) <= 2
        assert len(transfer.TRANSFERS["lax_wall_ball"]) <= 2

    def test_the_blurb_reads_as_a_sentence(self):
        from offdays import transfer
        assert transfer.blurb("gen_lateral_bound", "lacrosse") == (
            "This one pays off in Basketball, Soccer and Tennis too."
        )
        assert transfer.blurb("lax_wall_ball", "lacrosse") == (
            "This one pays off in Baseball and Hockey too."
        )

    def test_an_unknown_drill_says_nothing_rather_than_guessing(self):
        from offdays import transfer
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
        from offdays import sports
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
        """The rule, restated once the premise stopped being true.

        This used to assert "lacrosse only", on the reasoning that the two
        stick drills were the only ones reporting a left/right split. That held
        while every other sport's own drill sat in nobody's plan. Now that they
        are prescribed, juggling reports which foot and dribbling reports which
        hand -- so the rule has to be the thing it always meant: compare weak-
        hand parity where a position's own sport has a drill that reports the
        split.
        """
        for position in P.ALL_POSITIONS:
            if not position.offhand_matters or position.sport == "general":
                continue
            reporting = [
                key for key in position.emphasis
                if DRILLS_BY_KEY[key].sport == position.sport
                and DRILLS_BY_KEY[key].tracks_handedness
            ]
            assert reporting, (
                f"{position.key} is compared on weak-hand parity but nothing in "
                "its plan reports a split, so the number would be zero for "
                "every child in the sport"
            )

    def test_the_sports_that_do_not_compare_it_have_a_reason(self):
        # Each of these is a judgement rather than an oversight, and the
        # reasons live next to BILATERAL_SPORTS. Pinned so that turning one on
        # is a deliberate edit.
        assert P.BILATERAL_SPORTS == {"lacrosse", "soccer", "basketball"}

    def test_bilateral_throwing_is_never_encouraged(self):
        # The one place parity would be actively harmful: a growing elbow does
        # not want to learn to throw with the other arm.
        for position in P.ALL_POSITIONS:
            if position.sport in ("baseball", "softball"):
                assert not position.offhand_matters, position.key

    def test_a_sport_with_no_model_still_gets_honest_silence(self):
        assert P.for_sport("underwater basket weaving") == ()
        assert P.resolve("striker", sport="curling").key == "general"


class TestTheMixHelper:

    def test_it_normalises_relative_weights(self):
        assert P.mix(a=3, b=1) == {"a": 0.75, "b": 0.25}

    def test_it_refuses_an_empty_position(self):
        with pytest.raises(ValueError):
            P.mix()


class TestGroundBallsBelongToEveryone:
    """Ground balls are the one part of lacrosse that belongs to nobody.

    The plans used to range from 6% for an attacker to 20% for a long pole,
    which quietly taught the attacker that picking the ball up is somebody
    else's job. They are level now, and this is the test that keeps them level
    when the next position gets retuned.
    """

    GROUND_BALLS = "lax_ground_ball"

    def _lacrosse(self):
        return [p for p in ALL_POSITIONS if p.sport == "lacrosse"]

    def test_every_position_gets_the_same_share(self):
        shares = {p.key: p.emphasis.get(self.GROUND_BALLS) for p in self._lacrosse()}
        assert None not in shares.values(), f"a position has no ground balls: {shares}"
        assert len(set(shares.values())) == 1, shares

    def test_the_share_is_a_real_allocation(self):
        # Levelling at 2% would satisfy the test above and mean nothing.
        for pos in self._lacrosse():
            assert pos.emphasis[self.GROUND_BALLS] >= 0.10, pos.key

    def test_it_is_never_the_thing_a_position_is_told_to_do_least(self):
        for pos in self._lacrosse():
            lowest = min(pos.emphasis.values())
            assert pos.emphasis[self.GROUND_BALLS] > lowest, pos.key

    def test_every_plan_still_sums_to_one(self):
        for pos in ALL_POSITIONS:
            assert abs(sum(pos.emphasis.values()) - 1.0) < 1e-9, pos.key


class TestTheGoalieTrainsBothHands:
    def _goalie(self):
        return next(p for p in ALL_POSITIONS if p.key == "goalie")

    def test_the_off_hand_comparison_is_no_longer_withheld(self):
        # True of the grip, false of the job: the save is two-handed, and the
        # outlet that follows it is a real throw.
        assert self._goalie().offhand_matters

    def test_the_plan_actually_prescribes_off_hand_work(self):
        # Turning the flag on without giving them the work would compare a
        # goalie on something nothing in their plan builds.
        assert self._goalie().emphasis.get("lax_wall_ball_offhand", 0) > 0

    def test_every_lacrosse_position_now_trains_both_hands(self):
        for pos in ALL_POSITIONS:
            if pos.sport != "lacrosse":
                continue
            assert pos.offhand_matters, pos.key
            assert pos.emphasis.get("lax_wall_ball_offhand", 0) > 0, pos.key

    def test_other_sports_keep_their_own_carve_outs(self):
        # The flag is not obsolete -- basketball positions still use it, and
        # this change was about lacrosse rather than about deleting the idea.
        assert any(not p.offhand_matters for p in ALL_POSITIONS)


class TestEverySportsOwnDrillIsReachable:
    """A drill nobody's plan prescribes is a drill the position system cannot
    reach.

    Five sports shipped exactly one drill each -- juggling, dribbling, setting,
    wall throws, wall rally. All five existed, counted, were tested, and
    appeared in nobody's plan, so a soccer player following their position's
    guidance did push-ups and squats and never touched a ball. The plans were
    100% general fitness for every sport except lacrosse.
    """

    #: Lacrosse patterns that are deliberately choosable but not prescribed:
    #: strong-hand-only duplicates what an athlete does by default, and
    #: behind-the-back is a trick before it is a skill. Listed rather than
    #: inferred, so a genuinely stranded drill still fails below.
    ON_THE_MENU_ONLY = {"lax_wall_ball_strong", "lax_wall_ball_btb"}

    def test_no_sport_drill_is_stranded(self):
        stranded = {
            d.key for d in ALL_DRILLS
            if d.sport != "general"
            and not any(d.key in p.emphasis for p in ALL_POSITIONS)
        }
        assert stranded == self.ON_THE_MENU_ONLY, stranded

    def test_every_sport_with_a_drill_prescribes_it_somewhere(self):
        sports = {d.sport for d in ALL_DRILLS if d.sport != "general"}
        for sport in sports:
            own = {
                key for p in ALL_POSITIONS if p.sport == sport
                for key in p.emphasis if DRILLS_BY_KEY[key].sport == sport
            }
            assert own, f"{sport} positions prescribe none of their own drills"

    def test_a_plan_is_never_pure_general_fitness_when_the_sport_has_a_drill(self):
        # "Its own sport's work" has to mean the shared pool, not the key
        # prefix. A softball player throws, fields and hits with the same
        # motions a baseball player does, so five of the six diamond drills are
        # keyed `bb_` and shared rather than duplicated -- and a guard reading
        # prefixes would call a softball catcher's plan pure conditioning when
        # more than half of it is the sport.
        from offdays.drills import drill_sports

        with_drills = set()
        for pos in ALL_POSITIONS:
            pool = drill_sports(pos.sport)
            if any(d.sport in pool for d in ALL_DRILLS if d.sport != "general"):
                with_drills.add(pos.sport)

        for pos in ALL_POSITIONS:
            if pos.sport not in with_drills:
                continue
            pool = drill_sports(pos.sport)
            share = sum(
                v for k, v in pos.emphasis.items()
                if DRILLS_BY_KEY[k].sport in pool
            )
            assert share > 0, f"{pos.key} prescribes no {pos.sport} at all"

    def test_the_shared_pool_is_declared_rather_than_guessed(self):
        # One entry, and it should stay that way unless another pair of sports
        # genuinely does the same movements.
        from offdays.drills import SHARES_DRILLS_WITH
        assert SHARES_DRILLS_WITH == {"softball": "baseball"}

    def test_a_pitchers_plan_stays_light_on_throwing(self):
        # Wall throws cost a full throw per rep against a growing shoulder.
        for pos in ALL_POSITIONS:
            if pos.key == "pitcher":
                assert pos.emphasis["bb_wall_throw"] <= 0.08, pos.sport
