"""Hockey, built to the depth lacrosse has.

The sport whose skill work happens somewhere a phone cannot go. Nobody props a
camera on the boards and skates a drill past it, so every drill here is off-ice
-- which is not a compromise but a description of what a hockey player's hour
at home has always actually been.

Two things in this build are load-bearing enough to have their own sections
below.

**The sweep signal.** Everything a stick does off the ice is the hands crossing
the body: stickhandling is that crossing repeated fast, a wrist shot is it done
once, slowly and hard. None of it moves the hands far enough up or down for a
height signal to see, which is why the defining skill of the sport had no
drill anywhere in the catalogue.

**No puck.** A puck is black, and black has no chroma -- it is not a colour, it
is an absence of light. A black preset in the ball detector would match every
shadow in every garage, so there is none, and nothing in this sport claims to
have seen a puck. What replaces the ball check is the sweep signal's sign: a
rep arms on one side of the chest and fires on the other, so a handle that
never crosses is not a small rep, it is no rep.
"""

from __future__ import annotations

import pytest

from offdays import curriculum, film, sweep, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import Metric, SignalKind
from offdays.positions import ALL_POSITIONS, BY_SPORT

HOCKEY = [d for d in ALL_DRILLS if d.sport == "hockey"]
HOCKEY_KEYS = [d.key for d in HOCKEY]
SWEEP_DRILLS = [d for d in ALL_DRILLS if d.signal.kind is SignalKind.HAND_SWEEP]


class TestTheDrillSet:
    def test_there_are_enough_to_be_a_programme(self):
        assert len(HOCKEY) >= 6, HOCKEY_KEYS

    def test_it_covers_hands_shooting_feet_and_the_crease(self):
        assert "hoc_stickhandle" in HOCKEY_KEYS
        assert "hoc_shot" in HOCKEY_KEYS
        assert "hoc_shuffle" in HOCKEY_KEYS
        assert "hoc_butterfly" in HOCKEY_KEYS

    @pytest.mark.parametrize("drill", HOCKEY, ids=lambda d: d.key)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    @pytest.mark.parametrize("drill", HOCKEY, ids=lambda d: d.key)
    def test_every_drill_serializes(self, drill):
        assert drill.to_dict()["key"] == drill.key


class TestNoDrillClaimsToHaveSeenAPuck:
    """A puck is the one object in this catalogue the detector cannot find.

    It is black and matte, usually on a dark surface, and the vision detector
    works in illumination-normalised chroma where black is not a point at all.
    A black preset would match every shadow, every dark shoe and the gap under
    a garage door -- and a detector that fires on shadows is worse than no
    detector, because it produces confident wrong numbers instead of silence.
    """

    def test_no_hockey_drill_carries_a_ball_spec(self):
        offenders = [d.key for d in HOCKEY if d.ball is not None]
        assert offenders == [], offenders

    def test_the_descriptions_admit_it(self):
        # The stick drills have to say out loud that the count came from the
        # body, because a player reading "Wrist Shots" will otherwise assume
        # the app watched the puck go in.
        for key in ("hoc_stickhandle", "hoc_shot"):
            text = get_drill(key).description.lower()
            assert "hands" in text or "puck" in text
            assert "cannot see" in text or "no idea" in text or "not the puck" in text


class TestTheSweepSignal:
    """The horizontal hand measurement, and the structural work its sign does."""

    def test_the_signal_kind_exists_and_is_used(self):
        assert SWEEP_DRILLS, "a signal kind nothing uses is one nobody tested"

    def test_a_rep_has_to_cross_the_body_to_count_at_all(self):
        # The whole two-sided requirement, expressed as arithmetic rather than
        # as a rule that rejects reps: the arming threshold is on one side of
        # the chest and the firing threshold is on the other, so a sweep that
        # stays on the forehand side never arms and never fires.
        for drill in SWEEP_DRILLS:
            assert drill.counter.down_threshold < 0 < drill.counter.up_threshold, \
                drill.key

    def test_the_bands_nest_and_the_pay_rises_with_them(self):
        # Three drills on one signal, deliberately contained one inside the
        # next. That is only safe while each pays more than the one it
        # contains -- otherwise the best-earning thing in the product is to
        # pick the widest name and do the narrowest movement.
        ordered = sorted(SWEEP_DRILLS, key=lambda d: d.counter.up_threshold)
        for inner, outer in zip(ordered, ordered[1:]):
            assert outer.counter.down_threshold <= inner.counter.down_threshold
            assert outer.counter.up_threshold >= inner.counter.up_threshold
            assert outer.scoring.xp_per_rep >= inner.scoring.xp_per_rep, \
                f"{outer.key} contains {inner.key} but pays less"

    def test_no_sweep_drill_tracks_handedness(self):
        """A rep fires at the positive extreme every single time.

        So a hand read there would say "right" for every rep ever counted --
        and handed reps carry an off-hand premium, which would have made
        stickhandling the highest-paying drill in the product for doing
        nothing in particular.
        """
        for drill in SWEEP_DRILLS:
            assert not drill.tracks_handedness, drill.key

    def test_stick_work_never_touches_the_throwing_ledger(self):
        # Nothing here goes overhead. The arm ledger exists to protect one
        # number in the diamond sports, and filling it with stick work would
        # make that number mean nothing.
        for drill in HOCKEY:
            assert drill.load.throws_per_rep == 0.0, drill.key


class TestTheSweepReport:
    """The backhand, reported without ever guessing which side it is.

    The report itself no longer uses the word: rugby reads the same number and
    a rugby player has no backhand, so `sweep.py` names neither side and lets
    the athlete supply the label. For a hockey player the label is always the
    same one.
    """

    @staticmethod
    def _reps(a, b, n=20):
        # peak is the far end one way; the other end is peak - rom.
        return [{"peak": a, "rom": a + b} for _ in range(n)]

    def test_an_even_session_is_recognised_as_even(self):
        report = sweep.analyze(self._reps(0.45, 0.44))
        assert report.balance is not None and report.balance > 0.9
        assert "as far one way as the other" in report.note

    def test_a_short_side_is_reported(self):
        report = sweep.analyze(self._reps(0.60, 0.40))
        assert report.balance == pytest.approx(0.667, abs=0.01)
        assert "one side" in report.note.lower()
        # Says it cannot tell which one, which is the load-bearing half.
        assert "cannot tell" in report.note

    def test_a_side_that_is_barely_moving_is_said_more_strongly(self):
        report = sweep.analyze(self._reps(0.60, 0.18))
        assert report.balance == pytest.approx(0.30, abs=0.01)
        assert "barely" in report.note
        # Still admits it cannot tell which side. The worst case is exactly
        # where a confident guess would do the most damage.
        assert "cannot tell" in report.note

    def test_it_never_says_which_side_is_the_backhand(self):
        """With one camera and no stick in the pose model, the app knows the
        hands went further one way. It does not know which way the player
        shoots, and a coaching instruction built on a coin flip is worse than
        no instruction."""
        for pair in ((0.60, 0.20), (0.20, 0.60), (0.45, 0.44)):
            note = sweep.analyze(self._reps(*pair)).note.lower()
            assert "left" not in note and "right" not in note

    def test_a_short_set_says_so_rather_than_reporting_noise(self):
        report = sweep.analyze(self._reps(0.60, 0.20, n=4))
        assert report.balance is None
        assert "not enough" in report.note.lower()

    def test_reps_without_shape_data_are_not_counted_as_even(self):
        # An older client sends no peak or rom. That is missing information,
        # not a balanced session.
        report = sweep.analyze([{"peak": None, "rom": None} for _ in range(30)])
        assert report.reps == 0
        assert report.balance is None

    def test_nothing_is_ever_deducted_for_a_short_side(self):
        # Counted, never scored -- the same rule as the crossed-feet report. A
        # thirteen-year-old's backhand is short because it is a backhand.
        report = sweep.analyze(self._reps(0.60, 0.10))
        assert set(report.to_dict()) == {
            "reps", "reach_a", "reach_b", "balance", "note",
        }


class TestThePositionPlans:
    PLANS = BY_SPORT["hockey"]

    def test_there_is_one_for_every_position(self):
        assert len(self.PLANS) >= 4

    def test_every_plan_sums_to_one(self):
        for plan in self.PLANS:
            assert sum(plan.emphasis.values()) == pytest.approx(1.0)

    def test_every_plan_is_built_from_real_drills(self):
        keys = {d.key for d in ALL_DRILLS}
        for plan in self.PLANS:
            assert set(plan.emphasis) <= keys, plan.key

    def test_no_hockey_position_is_scored_on_off_hand_balance(self):
        """A hockey player holds the stick the same way for their whole life.

        Scoring them on left/right hand balance would measure nothing they are
        trying to build. Their weak side is the backhand, and the sweep report
        is where that shows up instead.
        """
        for plan in self.PLANS:
            assert plan.offhand_matters is False, plan.key

    def test_a_centre_and_a_winger_get_genuinely_different_hours(self):
        by_key = {p.key: p for p in self.PLANS}
        centre = by_key["centre"].emphasis
        winger = by_key["winger"].emphasis
        assert centre["hoc_stickhandle"] > winger["hoc_stickhandle"]
        assert winger["hoc_shot"] > centre["hoc_shot"]

    def test_the_goaltender_plan_is_mostly_not_stick_work(self):
        goalie = {p.key: p for p in self.PLANS}["goaltender"].emphasis
        stick = sum(v for k, v in goalie.items()
                    if k in ("hoc_stickhandle", "hoc_wide_handles", "hoc_shot"))
        assert stick == 0.0, goalie

    def test_the_defence_plan_leads_with_the_footwork(self):
        d = {p.key: p for p in self.PLANS}["defence"].emphasis
        assert max(d, key=d.get) == "hoc_shuffle"

    def test_every_alias_resolves_to_one_position(self):
        seen: dict[str, str] = {}
        for plan in self.PLANS:
            for alias in plan.aliases:
                assert alias not in seen, f"{alias}: {seen.get(alias)} and {plan.key}"
                seen[alias] = plan.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("hockey")

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 10

    def test_every_topic_fits_its_age_ceiling(self):
        for topic in self.TOPICS:
            cap = film.band_for(topic.min_age).clip_max_s
            assert topic.target_s <= cap, f"{topic.key}: {topic.target_s} > {cap}"

    def test_the_youngest_band_gets_something(self):
        assert [t for t in self.TOPICS if t.min_age == 0]

    def test_every_topic_carries_a_question_with_its_reasoning(self):
        for topic in self.TOPICS:
            assert topic.ask.because, topic.key
            assert 0 <= topic.ask.answer < len(topic.ask.options), topic.key

    def test_no_topic_ships_a_video_id(self):
        blob = " ".join(t.find + t.title for t in self.TOPICS).lower()
        for banned in ("youtu.be", "youtube.com", "watch?v="):
            assert banned not in blob

    def test_no_topic_reads_like_a_highlight_reel(self):
        for topic in self.TOPICS:
            assert film.looks_like_highlights(topic.title) is None, topic.key

    def test_the_goaltender_is_taught_something_of_their_own(self):
        assert [t for t in self.TOPICS if t.positions == ("goaltender",)]

    def test_head_contact_is_taught_and_taught_early(self):
        """This sport's defining risk is head contact the way the diamond's is
        throwing volume. A syllabus that covered gaps and breakouts and said
        nothing about the boards would be teaching the easy half."""
        safety = [t for t in self.TOPICS if t.focus == "Staying safe"]
        assert len(safety) >= 2, [t.key for t in self.TOPICS]
        # Not held back to the oldest band: the age at which players start
        # hitting each other is the age at which this needs to have been said.
        assert min(t.min_age for t in safety) <= 13

    def test_every_topic_key_is_unique_across_the_whole_catalogue(self):
        keys = [t.key for topics in curriculum.BY_SPORT.values() for t in topics]
        # Baseball and softball deliberately share one syllabus object, so
        # count distinct syllabuses rather than distinct sports.
        distinct = {id(t): t for t in
                    [t for topics in curriculum.BY_SPORT.values() for t in topics]}
        assert len(distinct) == len(set(keys))
