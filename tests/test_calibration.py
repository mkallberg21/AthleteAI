"""Using borrowed footage without letting it become the ground truth.

The honest answer to "can we calibrate from videos online instead of filming
children" is: for one half of the job yes, and for the other half no -- and the
halves are easy to confuse, because both produce a number.

A clip of somebody demonstrating a drill on the internet can establish that the
counter fires once per rep, on a real body, from an angle nobody here chose.
That is most of the "does it count at all" question and it is worth having.

It cannot establish `target_rom`, which exists to separate a full rep from a
half-hearted one in a tired child. A demonstration clip is the opposite of that
by construction: an adult, rehearsed, filmed because the rep was good.
Calibrating depth against it sets the bar at somebody's best rep and marks an
honest twelve-year-old short -- the mirror of the synthetic-sweep failure, and
no more correct.

So the module stratifies and refuses to pool. These tests are that refusal.
"""

from __future__ import annotations

import pytest

from offdays import calibration as C


def clips(n, **kw):
    base = dict(drill="gen_squat", source="own_youth", conditions="realistic",
                counted=20, truth=20, median_rom=0.70, target_rom=0.72)
    base.update(kw)
    return [C.Clip(**base) for _ in range(n)]


class TestBorrowedFootageCannotCertify:
    def test_a_pile_of_demo_clips_never_settles_a_threshold(self):
        """However many there are. This is the whole module."""
        verdict = C.verdict(clips(50, source="third_party_demo",
                                  conditions="studio"), "gen_squat")
        assert verdict["status"] == "not_yet_measured"
        assert "demonstration" in verdict["why"]

    def test_nor_does_game_footage(self):
        # Real effort, which is better -- but still not a youth athlete in the
        # conditions the product actually runs in.
        verdict = C.verdict(clips(30, source="third_party_game",
                                  conditions="realistic"), "gen_squat")
        assert verdict["status"] == "not_yet_measured"

    def test_nor_does_an_adult_filmed_here(self):
        verdict = C.verdict(clips(30, source="own_adult",
                                  conditions="realistic"), "gen_squat")
        assert verdict["status"] == "not_yet_measured"

    def test_nor_a_youth_athlete_in_studio_conditions(self):
        """A tripod and good light is not a phone on a water bottle.

        Who is in the clip and what it was shot on are separate axes, and the
        product runs in the second one.
        """
        verdict = C.verdict(clips(30, source="own_youth",
                                  conditions="studio"), "gen_squat")
        assert verdict["status"] == "not_yet_measured"

    def test_six_real_clips_do_settle_it(self):
        verdict = C.verdict(clips(C.MIN_CLIPS), "gen_squat")
        assert verdict["status"] == "measured"

    def test_five_do_not(self):
        verdict = C.verdict(clips(C.MIN_CLIPS - 1), "gen_squat")
        assert verdict["status"] == "not_yet_measured"


class TestWhatBorrowedFootageIsGoodFor:
    def test_it_can_still_prove_a_drill_is_broken(self):
        """The useful half. A counter that misses half the reps of an adult
        doing them properly is broken, and no footage of a child is needed to
        establish that."""
        verdict = C.verdict(
            clips(10, source="third_party_demo", conditions="studio",
                  counted=11, truth=24),
            "gen_squat",
        )
        assert verdict["status"] == "counting_problem"
        assert verdict["failing"]

    def test_a_counting_problem_outranks_a_depth_problem(self):
        # Retuning the depth target does not touch a counter that is not
        # finding the reps, and reporting the depth number first would send
        # somebody to fix the wrong thing.
        mixed = (clips(8, source="third_party_demo", conditions="studio",
                       counted=12, truth=24)
                 + clips(C.MIN_CLIPS, median_rom=0.30))
        assert C.verdict(mixed, "gen_squat")["status"] == "counting_problem"


class TestASpedUpClipIsNotABrokenCounter:
    """The failure this whole exercise found.

    Most drill footage on the internet is published sped up, because a
    three-minute set is a thirty-second clip. A sped-up clip produces exactly
    the shortfall a broken counter does -- and pointing an engineer at the
    counter because somebody's editor doubled the playback rate is a day spent
    fixing code that is correct.
    """

    def test_a_shortfall_the_counter_can_account_for_is_not_a_counting_problem(self):
        sped = [
            C.Clip(drill="gen_squat", source="third_party_demo",
                   conditions="studio", counted=6, truth=12, too_fast=6,
                   clip=f"demo{i}.mp4")
            for i in range(4)
        ]
        verdict = C.verdict(sped, "gen_squat")
        assert verdict["status"] == "playback_suspect"
        assert "double speed" in verdict["why"]
        assert len(verdict["suspect_clips"]) == 4

    def test_a_shortfall_it_cannot_account_for_still_is(self):
        # Same numbers, no refusals recorded: the movements were never seen.
        broken = [
            C.Clip(drill="gen_squat", source="third_party_demo",
                   conditions="studio", counted=6, truth=12)
            for _ in range(4)
        ]
        assert C.verdict(broken, "gen_squat")["status"] == "counting_problem"

    def test_a_real_counting_problem_outranks_a_suspect_clip(self):
        # If some clips are genuinely miscounted, that is the finding, and a
        # sped-up clip alongside them must not bury it.
        mixed = (
            [C.Clip(drill="gen_squat", source="third_party_demo",
                    conditions="studio", counted=6, truth=12, too_fast=6)] * 3
            + [C.Clip(drill="gen_squat", source="own_youth",
                      conditions="realistic", counted=5, truth=12)] * 3
        )
        assert C.verdict(mixed, "gen_squat")["status"] == "counting_problem"

    def test_partial_refusals_do_not_excuse_a_big_miss(self):
        # Two refusals do not explain eight missing reps.
        clips = [
            C.Clip(drill="gen_squat", source="own_youth", conditions="realistic",
                   counted=4, truth=12, too_fast=2)
            for _ in range(6)
        ]
        assert C.verdict(clips, "gen_squat")["status"] == "counting_problem"

    def test_a_full_count_is_never_suspect(self):
        clip = C.Clip(drill="gen_squat", source="own_youth",
                      conditions="realistic", counted=12, truth=12, too_slow=3)
        assert clip.playback_suspect is False


class TestItNeverAveragesAcrossProvenance:
    def test_strata_are_kept_apart(self):
        mixed = (clips(6, source="third_party_demo", conditions="studio", median_rom=0.95)
                 + clips(6, median_rom=0.60))
        groups = C.strata(mixed)
        assert len(groups) == 2
        assert {g.suggested_target for g in groups} == {0.95, 0.6}

    def test_a_demo_stratum_cannot_drag_the_suggestion(self):
        """The failure this module exists to prevent: an adult's best rep
        quietly raising the bar a child is measured against."""
        real_only = C.verdict(clips(6, median_rom=0.60), "gen_squat")
        polluted = C.verdict(
            clips(6, median_rom=0.60)
            + clips(20, source="third_party_demo", conditions="studio", median_rom=1.10),
            "gen_squat",
        )
        assert real_only["status"] == polluted["status"] == "retune_target_rom"
        assert real_only["suggested_target_rom"] == polluted["suggested_target_rom"]

    def test_every_stratum_is_reported_even_the_ones_that_cannot_certify(self):
        # They are evidence about the counter even when they are not evidence
        # about the target, so they are shown rather than dropped.
        verdict = C.verdict(
            clips(6) + clips(4, source="third_party_demo", conditions="studio"),
            "gen_squat",
        )
        sources = {s["source"] for s in verdict["strata"]}
        assert sources == {"own_youth", "third_party_demo"}
        assert any(s["certifying"] for s in verdict["strata"])
        assert any(not s["certifying"] for s in verdict["strata"])


class TestTheSuggestion:
    def test_it_reports_what_the_target_would_have_to_be(self):
        verdict = C.verdict(clips(C.MIN_CLIPS, median_rom=0.95), "gen_squat")
        assert verdict["status"] == "retune_target_rom"
        assert verdict["suggested_target_rom"] == 0.95

    def test_a_target_that_already_holds_is_left_alone(self):
        verdict = C.verdict(clips(C.MIN_CLIPS, median_rom=0.70), "gen_squat")
        assert verdict["status"] == "measured"
        assert "suggested_target_rom" not in verdict

    def test_a_drill_with_no_footage_says_so_rather_than_guessing(self):
        verdict = C.verdict([], "gen_squat")
        assert verdict["status"] == "not_yet_measured"
        assert verdict["strata"] == []


class TestTheBenchExport:
    def test_it_loads_what_the_page_writes(self):
        rows = [{
            "clip": "squat-01.mp4", "drill": "gen_squat",
            "source": "own_youth", "band": "13–15", "conditions": "realistic",
            "truth": 24, "counted": 24, "frames": 900, "lost_frames": 12,
            "mean_confidence": 0.91, "median_rom": 0.71, "target_rom": 0.72,
            "ratio": 0.99,
        }]
        loaded = C.load(rows)
        assert len(loaded) == 1 and loaded[0].certifying
        assert loaded[0].recall == 1.0

    def test_unknown_fields_do_not_break_it(self):
        # The bench will grow columns; the analysis should not need editing
        # every time it does.
        loaded = C.load([{"drill": "gen_squat", "source": "own_youth",
                          "conditions": "realistic", "counted": 5,
                          "something_new": 42}])
        assert loaded[0].counted == 5
