"""Rugby, and the sport where most of the game cannot be practised alone.

Tackling, rucking, scrummaging and lineout lifting all need at least one other
person, and none of them belong to a fourteen-year-old alone in a garden. What
is left is passing, kicking and conditioning -- which is exactly what a rugby
player's hour at home has always been, so the honest build is a small one, and
saying that plainly is most of the work.

The interesting part is that passing lands on a signal built for hockey and
means something different on it. A hockey player's short side is their
backhand, which they will have for life. A rugby player is required to pass off
both hands from anywhere, so a short side is a gap the opposition finds inside
one game. Identical number, opposite conclusion -- which is why `sweep.py`
reports the asymmetry and names neither side.
"""

from __future__ import annotations

import pytest

from offdays import curriculum, film, sweep, technique, transfer
from offdays.drills import ALL_DRILLS, get_drill
from offdays.drills.base import SignalKind, Tissue
from offdays.positions import BY_SPORT

RUGBY = [d for d in ALL_DRILLS if d.sport == "rugby"]
KEYS = [d.key for d in RUGBY]
SWEEP_FAMILY = [d for d in ALL_DRILLS if d.signal.kind is SignalKind.HAND_SWEEP]


class TestTheDrillSet:
    def test_the_passing_ladder_exists(self):
        assert set(KEYS) == {"rug_quick_hands", "rug_wall_pass", "rug_spin_pass"}

    @pytest.mark.parametrize("drill", RUGBY, ids=lambda d: d.key)
    def test_every_drill_has_cues_and_transfers(self, drill):
        assert technique.cues_for(drill.key), drill.key
        assert transfer.for_drill(drill.key), drill.key

    def test_there_is_no_contact_drill_anywhere(self):
        """The whole shape of this build.

        A tackle, a ruck and a scrum are the three most-coached things in the
        sport and none of them can be done alone, safely or at all. They are
        taught on film and absent from the catalogue rather than approximated
        by something a camera could count.
        """
        words = ("tackle", "ruck", "scrum", "maul", "lineout", "contact")
        for drill in RUGBY:
            blob = (drill.name + " " + drill.description).lower()
            for word in words:
                assert word not in blob, f"{drill.key}: {word}"

    def test_passing_is_not_throwing(self):
        # A rugby pass is a chest-height push off both hands, not an overhead
        # throw. Putting it on the arm's ledger would fill the one number that
        # ledger exists to protect with work that does not threaten it.
        for drill in RUGBY:
            assert drill.load.throws_per_rep == 0.0, drill.key
            assert drill.load.tissue is Tissue.UPPER_BODY, drill.key


class TestTheLadderNowSpansTwoSports:
    """Six drills, one measurement, and a rate that has to rise with width."""

    def test_both_sports_are_on_it(self):
        sports = {d.sport for d in SWEEP_FAMILY}
        assert sports == {"hockey", "rugby"}, sports

    def test_it_is_monotonic_across_the_whole_family(self):
        # The subsumption guard enforces this pairwise. Asserting it as one
        # chain says the thing a reader actually needs to know: there is no way
        # anywhere in this ladder to earn more by moving less.
        ordered = sorted(SWEEP_FAMILY, key=lambda d: d.counter.up_threshold)
        rates = [d.scoring.xp_per_rep for d in ordered]
        assert rates == sorted(rates), [(d.key, d.scoring.xp_per_rep) for d in ordered]

    def test_the_rugby_bands_interleave_with_the_hockey_ones(self):
        # Not a tidy block per sport, and that is the point: the ladder is
        # ordered by what the athlete actually did, not by which sport they
        # picked from the menu.
        ordered = [d.sport for d in
                   sorted(SWEEP_FAMILY, key=lambda d: d.counter.up_threshold)]
        assert len(set(ordered[:3])) > 1

    def test_a_rep_still_has_to_cross_the_body(self):
        for drill in SWEEP_FAMILY:
            assert drill.counter.down_threshold < 0 < drill.counter.up_threshold

    def test_a_pop_pass_is_verified_by_a_rate_floor(self):
        # The cheapest rung has to be honest rather than merely cheap: a full
        # pass cannot be repeated at this rate.
        pop = get_drill("rug_quick_hands")
        assert (pop.validation.min_reps_per_second
                > get_drill("rug_wall_pass").validation.max_reps_per_second / 3)
        assert pop.validation.min_reps_per_second >= 0.7


class TestTheSweepReportNowServesBothSports:
    @staticmethod
    def _reps(a, b, n=20):
        return [{"peak": a, "rom": a + b} for _ in range(n)]

    def test_it_no_longer_speaks_in_hockey_terms(self):
        """It used to say "your backhand", which is the right word for one
        sport and meaningless in the other. A rugby player has no backhand;
        they have a weak hand, and the sport demands they fix it."""
        for pair in ((0.60, 0.40), (0.60, 0.18), (0.45, 0.44)):
            note = sweep.analyze(self._reps(*pair)).note.lower()
            assert "backhand" not in note
            assert "forehand" not in note

    def test_it_still_never_says_which_side(self):
        for pair in ((0.60, 0.20), (0.20, 0.60), (0.45, 0.44)):
            note = sweep.analyze(self._reps(*pair)).note.lower()
            assert "left" not in note and "right" not in note

    def test_a_short_side_still_gets_named_as_one(self):
        report = sweep.analyze(self._reps(0.60, 0.40))
        assert report.balance == pytest.approx(0.667, abs=0.01)
        assert "one side" in report.note.lower()

    def test_it_is_still_counted_and_never_scored(self):
        assert set(sweep.analyze(self._reps(0.6, 0.1)).to_dict()) == {
            "reps", "reach_a", "reach_b", "balance", "note",
        }


class TestThePositionPlans:
    PLANS = BY_SPORT["rugby"]

    def test_every_plan_sums_to_one(self):
        for plan in self.PLANS:
            assert sum(plan.emphasis.values()) == pytest.approx(1.0)

    def test_every_position_passes(self):
        # In this sport that is not a nicety. A player who can only pass one way
        # is a player the opposition finds inside one game, and it is true of a
        # prop as much as a fly half.
        for plan in self.PLANS:
            assert set(plan.emphasis) & set(KEYS), plan.key

    def test_the_half_backs_are_the_most_sport_specific_plan(self):
        own = {
            p.key: sum(v for k, v in p.emphasis.items() if k in KEYS)
            for p in self.PLANS
        }
        assert max(own, key=own.get) == "half_back", own

    def test_the_half_backs_kick_and_the_forwards_do_not(self):
        by_key = {p.key: p.emphasis for p in self.PLANS}
        assert "fb_kick" in by_key["half_back"]
        for key in ("front_row", "second_row"):
            assert "fb_kick" not in by_key[key]

    def test_the_kick_is_shared_rather_than_duplicated(self):
        """One measurement, one drill.

        A rugby punt and a football punt are the same leg swing, and the camera
        could not tell them apart even if two drills were wanted. So the fly
        half's plan reaches across to the football-keyed drill rather than the
        catalogue growing a second name for one thing. The key prefix is a wart;
        the alternative was a duplicate, which is worse.
        """
        kick = get_drill("fb_kick")
        assert kick.sport == "football"
        assert "either code" in kick.description
        twins = [d.key for d in ALL_DRILLS
                 if d.key != "fb_kick"
                 and (d.signal.landmark, d.signal.reference)
                 == (kick.signal.landmark, kick.signal.reference)]
        assert twins == [], twins

    def test_every_alias_resolves_to_one_position(self):
        seen: dict[str, str] = {}
        for plan in self.PLANS:
            for alias in plan.aliases:
                assert alias not in seen, f"{alias}: {seen[alias]} and {plan.key}"
                seen[alias] = plan.key


class TestTheFilmCurriculum:
    TOPICS = curriculum.topics_for("rugby")

    def test_there_is_one(self):
        assert len(self.TOPICS) >= 10

    def test_every_topic_fits_its_age_ceiling(self):
        for topic in self.TOPICS:
            cap = film.band_for(topic.min_age).clip_max_s
            assert topic.target_s <= cap, f"{topic.key}: {topic.target_s} > {cap}"

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

    def test_contact_is_most_of_the_safety_teaching_and_starts_young(self):
        safety = [t for t in self.TOPICS if t.focus == "Staying safe"]
        assert len(safety) >= 5, [t.key for t in self.TOPICS]
        assert min(t.min_age for t in safety) == 0

    def test_the_tackle_height_topic_refuses_to_state_a_law(self):
        """This sport has changed its own tackle-height law repeatedly, and
        differently in different unions. A syllabus that baked one country's
        current number in would be teaching something false somewhere, and
        teaching it confidently. So the topic teaches why the height moves and
        sends the coach to their own union for the number."""
        topic = curriculum.BY_KEY["rug_iq_tackle_height_law"]
        blob = (topic.ask.prompt + " " + topic.ask.because
                + " " + " ".join(topic.ask.options)).lower()
        for banned in ("waist", "sternum", "armpit", "nipple", "below the"):
            assert banned not in blob, banned
        assert "your own union" in topic.find.lower()

    def test_the_neck_is_taught_and_says_it_cannot_be_counted(self):
        # The same gap football has. Named rather than filled with something
        # that would look like a number.
        topic = curriculum.BY_KEY["rug_iq_neck"]
        assert "cannot count" in topic.ask.because.lower()

    def test_every_topic_key_is_unique_across_the_whole_catalogue(self):
        rows = [t for topics in curriculum.BY_SPORT.values() for t in topics]
        distinct = list({id(t): t for t in rows}.values())
        assert len({t.key for t in distinct}) == len(distinct)
