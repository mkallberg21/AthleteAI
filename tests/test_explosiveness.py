"""Every athlete gets explosive work, whatever sport they picked.

This started as an audit and turned into a defect. Asking "is this athlete
doing anything that makes them more explosive?" was not a question the codebase
could answer: `Category` files a burpee under conditioning, a lateral bound
under agility and a squat jump under speed, which is a fine way to lay out a
menu and useless for this.

Answered properly, **six position plans contained no power or quickness work at
all** -- a cheer base, a cheer backspot, a ballet dancer, a bars gymnast, a
rugby prop and a distance swimmer -- and **eighteen of the sixty-three sat below
ten percent**, across ten different sports. Both pitchers were among them at
seven and eight percent, and a track thrower at eight, which is the worst of the
lot: a throw *is* power.

None of those plans looked wrong. Every one was full of drills that a category
listing makes look varied. That is exactly the kind of hole a guard exists to
find, so `Stimulus` says what a drill develops rather than what shelf it sits
on, and the floor below is enforced for every position in every sport.
"""

from __future__ import annotations

import pytest

from offdays.drills import ALL_DRILLS, DRILLS_BY_KEY, get_drill
from offdays.drills.base import EXPLOSIVE, Category, Stimulus
from offdays.positions import ALL_POSITIONS

#: The share of a position's solo time that has to be power or quickness.
#:
#: Low on purpose. It is a floor, not a target -- a prop and a bars gymnast
#: should be nowhere near a sprinter's share, and the point is that nobody sits
#: at zero, not that everybody looks the same.
MIN_EXPLOSIVE_SHARE = 0.10


def explosive_share(position) -> float:
    return sum(
        v for k, v in position.emphasis.items()
        if DRILLS_BY_KEY[k].stimulus in EXPLOSIVE
    )


class TestEveryPlanBuildsExplosiveness:
    @pytest.mark.parametrize(
        "position", ALL_POSITIONS, ids=lambda p: f"{p.sport}-{p.key}"
    )
    def test_it_clears_the_floor(self, position):
        share = explosive_share(position)
        assert share >= MIN_EXPLOSIVE_SHARE, (
            f"{position.sport}/{position.key} gives {share:.1%} to power or "
            "quickness"
        )

    def test_the_floor_is_a_floor_and_not_a_template(self):
        """A prop and a sprinter should not end up with the same plan.

        A guard that pushed everybody to the same share would be a guard that
        flattened sixty-three carefully different plans into one, which is
        worse than the hole it was closing.
        """
        shares = [explosive_share(p) for p in ALL_POSITIONS]
        assert max(shares) - min(shares) > 0.30

    def test_the_sports_that_need_it_most_lead(self):
        by_key = {f"{p.sport}/{p.key}": explosive_share(p) for p in ALL_POSITIONS}
        assert by_key["track/jumps"] > by_key["swimming/distance"]
        assert by_key["football/defensive_back"] > by_key["football/line"]

    def test_a_pitcher_trains_the_leg_the_velocity_comes_from(self):
        # Both codes. This was the single most surprising zero in the audit:
        # the position whose whole output is one explosive movement had a plan
        # containing nothing explosive at all.
        for sport in ("baseball", "softball"):
            plan = next(p for p in ALL_POSITIONS
                        if p.sport == sport and p.key == "pitcher")
            assert "gen_squat_jump" in plan.emphasis
            assert explosive_share(plan) >= MIN_EXPLOSIVE_SHARE

    def test_a_thrower_is_not_short_of_power(self):
        plan = next(p for p in ALL_POSITIONS
                    if p.sport == "track" and p.key == "throws")
        # A throw is power. This plan sat at 8% before the audit.
        assert explosive_share(plan) > 0.25


class TestTheStimulusAxisIsHonest:
    def test_every_drill_declares_one(self):
        # The field has no default, so this cannot regress by omission -- a new
        # drill will not construct without answering.
        for drill in ALL_DRILLS:
            assert isinstance(drill.stimulus, Stimulus), drill.key

    def test_it_is_not_a_rename_of_category(self):
        """If stimulus tracked category one-to-one it would be dead weight, and
        the hole it found would still be open."""
        pairs = {(d.category, d.stimulus) for d in ALL_DRILLS}
        by_category: dict[Category, set[Stimulus]] = {}
        for cat, stim in pairs:
            by_category.setdefault(cat, set()).add(stim)
        assert any(len(v) > 1 for v in by_category.values()), by_category

    def test_a_burpee_is_not_filed_as_power(self):
        """It has a jump in it and it is still a conditioning staple.

        Filing it as power would let a plan built on burpees pass the check it
        should fail, which is the exact failure this axis exists to catch.
        """
        assert get_drill("gen_burpee").stimulus is Stimulus.ENDURANCE

    def test_a_fast_skill_drill_is_still_a_skill_drill(self):
        # A quick release and quick hands are verified BY speed; speed is not
        # what they develop. Counting them as quickness would let a plan satisfy
        # the floor with hand speed and no legs at all.
        for key in ("fb_quick_release", "bb_quick_hands", "rug_quick_hands"):
            assert get_drill(key).stimulus is Stimulus.SKILL, key

    def test_footwork_drills_are_quickness_rather_than_skill(self):
        # These have no ball and no implement. They are agility with a sport's
        # name on them.
        for key in ("bkb_slide", "soc_shuffle", "ten_recovery", "hoc_shuffle",
                    "fb_shuffle", "bb_fielding", "ten_split_step"):
            assert get_drill(key).stimulus is Stimulus.QUICKNESS, key

    def test_every_holding_drill_is_strength(self):
        from offdays.drills.base import Metric
        for drill in ALL_DRILLS:
            if drill.metric is Metric.HOLD_SECONDS:
                assert drill.stimulus is Stimulus.STRENGTH, drill.key

    def test_the_explosive_set_is_named_once(self):
        assert EXPLOSIVE == {Stimulus.POWER, Stimulus.QUICKNESS}

    def test_it_serializes_for_the_client(self):
        assert get_drill("gen_pogo").to_dict()["stimulus"] == "quickness"


class TestTheTwoNewQualities:
    def test_the_general_shelf_now_has_both(self):
        general = [d for d in ALL_DRILLS
                   if d.sport == "general" and d.stimulus in EXPLOSIVE]
        assert {d.stimulus for d in general} == EXPLOSIVE
        # Before this build there were three power drills and no reactive
        # quickness drill anywhere.
        assert len(general) >= 6

    def test_a_pogo_is_verified_by_a_rate_nothing_else_can_hold(self):
        pogo = get_drill("gen_pogo")
        assert pogo.stimulus is Stimulus.QUICKNESS
        floor = pogo.validation.min_reps_per_second
        for other in ("ten_split_step", "gen_squat_jump", "gen_tuck_jump"):
            assert floor > get_drill(other).validation.max_reps_per_second, other

    def test_a_pogo_never_out_earns_the_drill_that_contains_it(self):
        # Its band sits inside the tennis split step's, so the subsumption
        # guard applies. Asserted here too because the relationship is the
        # reason the rate is as low as it is.
        pogo, split = get_drill("gen_pogo"), get_drill("ten_split_step")
        assert split.counter.down_threshold <= pogo.counter.down_threshold
        assert split.counter.up_threshold >= pogo.counter.up_threshold
        assert pogo.scoring.xp_per_rep <= split.scoring.xp_per_rep

    def test_a_skater_bound_is_a_lateral_bound_opened_right_up(self):
        skater, quick = get_drill("gen_skater_bound"), get_drill("gen_lateral_bound")
        assert (skater.signal.landmark, skater.signal.reference) \
            == (quick.signal.landmark, quick.signal.reference)
        assert skater.counter.up_threshold > quick.counter.up_threshold * 2
        # It contains the quick one, so it has to pay more.
        assert skater.scoring.xp_per_rep > quick.scoring.xp_per_rep

    def test_the_skater_bound_records_which_leg_took_off(self):
        # An athlete who can only bound one way is the thing this finds.
        assert get_drill("gen_skater_bound").tracks_handedness

    def test_both_are_general_rather_than_owned_by_a_sport(self):
        for key in ("gen_pogo", "gen_skater_bound"):
            assert get_drill(key).sport == "general"
