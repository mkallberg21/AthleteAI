"""Which drills count by ear beyond lacrosse, and why the rest do not.

Wall ball earned sound counting on real footage. The drills pinned here were
given it by argument, drill by drill, in the "Sound beyond lacrosse" block of
`drills/catalog.py` -- none has been checked against a real recording yet. So
this file pins the list exactly: widening it should be a deliberate edit with
a reason next to it, not something that drifts in with a new drill.
"""
from __future__ import annotations

import json

import pytest

from offdays import technique, transfer
from offdays.drills import ALL_DRILLS, DRILLS_BY_KEY, SignalKind, get_drill
from offdays.drills.base import Metric, SoundSpec

WALL_BALL = {d.key for d in ALL_DRILLS if d.signal.kind is SignalKind.WALL_BALL_CYCLE}

#: Existing drills given sound, and each one's floor in ms.
EXTENDED = {
    "gen_jump_rope": 200,
    "bkb_dribble": 120,
    "bkb_crossover": 170,
    "bkb_between_legs": 200,
    "bkb_pound_weak": 130,
    "bkb_pound_low": 120,
    "bkb_wall_pass": 350,
    "bb_wall_throw": 450,
    "bb_quick_hands": 550,
    "ten_wall_rally": 350,
    "ten_alternate": 350,
    "ten_one_wing": 350,
    "ten_volley": 180,
    "soc_wall_pass": 450,
    "vb_set_wall": 250,
}

#: Drills added for sound, sound-first.
NEW = {"gen_double_under", "ten_racket_bounce"}

SOUND_DRILLS = WALL_BALL | set(EXTENDED) | NEW

#: Categories of work that must never ask for the microphone: no impact per
#: rep, a quiet touch, or a rep that is the motion rather than a sound.
EXCLUDED = (
    "soc_juggle", "soc_juggle_weak", "soc_juggle_alt", "soc_thigh", "soc_toe_taps",
    "vb_set", "vb_pass", "vb_serve", "ten_serve", "bb_long_toss", "bb_tee_swing",
    "sb_windmill", "fb_quick_release", "fb_wall_throw", "fb_deep_ball", "fb_kick",
    "hoc_stickhandle", "hoc_shot", "rug_quick_hands", "rug_wall_pass",
    "lax_ground_ball", "lax_faceoff_clamp", "lax_goalie_saves",
    "gen_pogo", "gen_tuck_jump", "gen_squat", "gen_push_up",
    "bkb_slide", "bkb_stance", "ten_split_step", "ten_recovery",
)


class TestWhichDrillsListen:
    def test_the_list_is_exactly_what_was_argued_for(self):
        heard = {d.key for d in ALL_DRILLS if d.sound is not None}
        assert heard == SOUND_DRILLS, (
            f"added: {sorted(heard - SOUND_DRILLS)}, "
            f"lost: {sorted(SOUND_DRILLS - heard)}"
        )

    @pytest.mark.parametrize("key", sorted(EXTENDED))
    def test_each_extended_drill_has_the_floor_its_comment_gives(self, key):
        assert get_drill(key).sound.min_cycle_ms == EXTENDED[key]

    @pytest.mark.parametrize("key", EXCLUDED)
    def test_excluded_work_never_asks_for_the_microphone(self, key):
        assert get_drill(key).sound is None

    def test_nothing_held_or_timed_listens(self):
        for drill in ALL_DRILLS:
            if drill.metric is Metric.HOLD_SECONDS:
                assert drill.sound is None, drill.key


class TestTheFloorsAreSane:
    @pytest.mark.parametrize("key", sorted(SOUND_DRILLS))
    def test_positive(self, key):
        assert get_drill(key).sound.min_cycle_ms > 0

    # Not the wall-ball family: its rate ceilings are loose anti-cheat
    # envelopes (3/s on a 1.4s cycle), and its floors came from real clips.
    @pytest.mark.parametrize("key", sorted(set(EXTENDED) | NEW))
    def test_under_the_quickest_honest_cycle(self, key):
        drill = get_drill(key)
        floor = drill.sound.min_cycle_ms
        # The drill's own rate ceiling is the quickest cycle it believes in.
        # A floor above that would drop real reps for the whole session.
        quickest = 1000 / drill.validation.max_reps_per_second
        assert floor <= quickest, (key, floor, quickest)

    @pytest.mark.parametrize("key", sorted(SOUND_DRILLS))
    def test_never_stricter_than_the_eye(self, key):
        # Where a ball tracker has its own refractory gap, the ear must not
        # refuse a contact the eye would have kept.
        drill = get_drill(key)
        if drill.ball is not None and drill.ball.counts:
            assert drill.sound.min_cycle_ms <= drill.ball.min_gap_ms, key

    def test_two_sound_drills_fold_the_second_sound(self):
        # Racket then wall, and wall then glove: the floor sits above the
        # quick sound pair's spacing (~150-300ms at these distances).
        for key in ("ten_wall_rally", "ten_alternate", "ten_one_wing",
                    "bb_wall_throw", "bb_quick_hands"):
            assert get_drill(key).sound.min_cycle_ms >= 350, key


class TestWhereTheHandComesFrom:
    def test_only_a_stick_uses_the_stick_reading(self):
        for drill in ALL_DRILLS:
            if drill.sound is None:
                continue
            if drill.key in WALL_BALL:
                assert drill.sound.hand_from == "wall_ball", drill.key
            else:
                assert drill.sound.hand_from != "wall_ball", drill.key

    def test_the_ball_is_only_asked_when_it_attributes_a_side(self):
        for drill in ALL_DRILLS:
            if drill.sound is not None and drill.sound.hand_from == "ball":
                assert drill.ball is not None and drill.ball.attribute_side, drill.key

    def test_the_dribbling_family_keeps_its_hand_check(self):
        # Crossovers and weak-hand pounds are paid for a hand pattern; the ear
        # must not strip the hands that pattern is checked on.
        for key in ("bkb_dribble", "bkb_crossover", "bkb_between_legs",
                    "bkb_pound_weak", "bkb_pound_low"):
            assert get_drill(key).sound.hand_from == "ball", key


class TestTheNewDrills:
    @pytest.mark.parametrize("key", sorted(NEW))
    def test_it_exists_and_listens(self, key):
        drill = get_drill(key)
        assert drill.sound is not None
        assert drill.metric is Metric.REPS

    @pytest.mark.parametrize("key", sorted(NEW))
    def test_pose_or_the_ball_can_still_count_it(self, key):
        # A refused microphone must leave a working drill, as on wall ball.
        drill = get_drill(key)
        assert drill.counter.min_rep_ms > 0
        assert drill.counter.down_threshold < drill.counter.up_threshold
        assert drill.setup_hint

    @pytest.mark.parametrize("key", sorted(NEW))
    def test_it_is_coached_and_carried_over(self, key):
        assert technique.cues_for(key)
        assert transfer.for_drill(key)

    def test_a_double_under_pays_what_a_single_does(self):
        # Neither the camera nor the ear can tell the rope went round twice.
        du, single = get_drill("gen_double_under"), get_drill("gen_jump_rope")
        assert du.scoring.xp_per_rep == single.scoring.xp_per_rep
        assert du.pattern_verified is False

    def test_a_double_under_floor_folds_its_two_slaps(self):
        # Two slaps of one jump land ~150-200ms apart; doubles repeat at 450+.
        assert 200 < get_drill("gen_double_under").sound.min_cycle_ms < 450

    def test_racket_bounces_pay_less_than_a_rally(self):
        assert (get_drill("ten_racket_bounce").scoring.xp_per_rep
                < get_drill("ten_wall_rally").scoring.xp_per_rep)


class TestTheBrowserGetsIt:
    def test_the_sound_spec_serializes_every_field(self):
        drill = get_drill("bkb_dribble")
        assert drill.to_dict()["sound"] == {
            "min_cycle_ms": 120, "hand_from": "ball", "measures_release": False}

    def test_a_drill_without_sound_sends_none(self):
        assert get_drill("gen_squat").to_dict()["sound"] is None

    @pytest.mark.parametrize("key", sorted(SOUND_DRILLS))
    def test_it_is_plain_json(self, key):
        json.dumps(DRILLS_BY_KEY[key].to_dict())

    def test_the_default_is_the_old_behaviour(self):
        assert SoundSpec().hand_from == "wall_ball"

    def test_an_unknown_hand_source_is_refused(self):
        with pytest.raises(ValueError):
            SoundSpec(hand_from="guess")

    def test_a_zero_floor_is_refused(self):
        with pytest.raises(ValueError):
            SoundSpec(min_cycle_ms=0)


class TestReleaseIsLacrosseOnly:
    """Release time is a catch-to-throw figure. Only a stick catch is a catch."""

    def test_every_lacrosse_wall_ball_drill_measures_release(self):
        for drill in ALL_DRILLS:
            if drill.sound is not None and drill.sound.hand_from == "wall_ball":
                assert drill.sound.measures_release, drill.key

    def test_no_other_sport_measures_release(self):
        for drill in ALL_DRILLS:
            if drill.sound is not None and drill.sport != "lacrosse":
                assert not drill.sound.measures_release, drill.key
