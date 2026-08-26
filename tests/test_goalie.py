"""Tests for marking a cued goalie session.

Two things get checked hardest here, because they are the two places this
module could quietly do harm.

The first is that the targets come from the nonce and not from the payload. If
a client could ever influence what it is marked against, the whole reason for
building the sequence this way is gone.

The second is that "the camera could not see your hands" never turns into "you
went to the wrong place". Those are different facts, one about a phone and one
about a child, and a scorer that blends them tells a goalie they are bad at a
corner the app simply could not watch.
"""

from __future__ import annotations

import pytest

from offdays import goalie
from offdays.cues import cue_at, sequence
from offdays.drills.catalog import get_drill

DRILL = get_drill("lax_goalie_saves")
SPEC = DRILL.cues
NONCE = "session-nonce-1"


def targets(count: int, nonce: str = NONCE) -> list[str]:
    return sequence(nonce, count, SPEC.zones)


def duration_for(cues: int) -> int:
    """Exactly long enough for `cues` cues to be issued and answerable."""
    return SPEC.lead_in_ms + cues * SPEC.period_ms


def rep(index: int, zone: str, delay_ms: int = 500) -> dict:
    """A rep answering cue `index`, `delay_ms` after it appeared."""
    return {
        "t_ms": cue_at(index, SPEC.lead_in_ms, SPEC.period_ms) + delay_ms,
        "zone": zone,
    }


def perfect(count: int, delay_ms: int = 500, nonce: str = NONCE) -> list[dict]:
    return [rep(i, z, delay_ms) for i, z in enumerate(targets(count, nonce))]


def analyze(reps, cues=20, nonce=NONCE, top_hand="right"):
    return goalie.analyze(
        DRILL, reps, nonce=nonce, duration_ms=duration_for(cues), top_hand=top_hand,
    )


class TestTheTargetsComeFromTheNonce:
    def test_a_flawless_session_scores_flawlessly(self):
        report = analyze(perfect(20))
        assert report.scored
        assert report.cues == 20
        assert report.answered == 20
        assert report.correct == 20
        assert report.accuracy == 1.0

    def test_the_same_reps_against_a_different_nonce_are_not_correct(self):
        # The single most important test in this file. If the payload decided
        # the targets, these reps would score identically under both nonces.
        reps = perfect(20, nonce=NONCE)
        same = analyze(reps, nonce=NONCE)
        other = analyze(reps, nonce="a-completely-different-nonce")
        assert same.correct == 20
        assert other.correct < 20

    def test_a_client_cannot_smuggle_targets_in_the_payload(self):
        # Extra keys that look like targets are ignored outright: the scorer
        # reads t_ms and zone and nothing else.
        reps = [dict(r, target=r["zone"], correct=True) for r in perfect(20)]
        tampered = [dict(r, zone="high_left") for r in reps]
        report = analyze(tampered)
        # Only the cues that genuinely called high_left can be right.
        assert report.correct == targets(20).count("high_left")
        assert report.correct < 20


class TestAttributingRepsToCues:
    def test_a_rep_before_the_first_cue_answers_nothing(self):
        early = [{"t_ms": SPEC.lead_in_ms - 500, "zone": targets(20)[0]}]
        report = analyze(perfect(20) + early)
        assert report.answered == 20

    def test_a_rep_after_the_late_window_is_not_counted_as_an_answer(self):
        reps = perfect(20)
        reps[5] = rep(5, targets(20)[5], SPEC.late_ms + 200)
        report = analyze(reps)
        assert report.answered == 19
        assert report.correct == 19
        # It is a missed cue, not a wrong one -- the cue still counts against
        # accuracy, because not getting there is the failure.
        assert report.cues == 20
        assert report.accuracy == pytest.approx(19 / 20)

    def test_only_the_first_response_to_a_cue_counts(self):
        # Hands arriving, then drifting somewhere else before the next call, is
        # one answer and a reset -- not two answers, and certainly not a second
        # chance at the same cue.
        reps = perfect(20)
        wrong_second_move = rep(3, "high_left", 900)
        report = analyze(sorted(reps + [wrong_second_move], key=lambda r: r["t_ms"]))
        assert report.answered == 20
        assert report.correct == 20

    def test_a_rep_in_the_gap_between_sessions_of_cues_is_dropped(self):
        stray = [{"t_ms": duration_for(20) + 5_000, "zone": "low_left"}]
        report = analyze(perfect(20) + stray)
        assert report.answered == 20

    def test_reaction_time_is_measured_from_the_cue_not_the_session_start(self):
        report = analyze(perfect(20, delay_ms=640))
        assert report.median_ms == 640

    def test_a_fast_trip_to_the_wrong_spot_does_not_count_as_quick(self):
        # Guessing early and being wrong must not look like a fast reaction.
        called = targets(20)
        wrong = "high_left" if called[0] != "high_left" else "low_right"
        reps = [rep(0, wrong, 120)] + [
            rep(i, z, 800) for i, z in enumerate(called) if i > 0
        ]
        report = analyze(reps)
        assert report.median_ms == 800
        assert report.quick_share == 0.0


class TestUnreadableRepsAreNotWrongReps:
    def test_a_few_unreadable_reps_are_counted_separately(self):
        reps = perfect(20)
        for i in (2, 7):
            reps[i] = rep(i, "unknown")
        report = analyze(reps)
        assert report.unreadable == 2
        assert report.answered == 18
        assert report.correct == 18

    def test_an_unreadable_rep_never_lands_in_a_zone_row(self):
        reps = perfect(20)
        reps[4] = rep(4, "unknown")
        report = analyze(reps)
        assert sum(r.answered for r in report.zones) == 19
        assert all(r.zone != "unknown" for r in report.zones)

    def test_a_mostly_unreadable_session_is_withheld_rather_than_scored(self):
        reps = [rep(i, "unknown") for i in range(20)]
        report = analyze(reps)
        assert not report.scored
        assert report.zones == []
        assert "camera" in report.reason.lower()

    def test_the_withheld_message_blames_the_framing_not_the_athlete(self):
        report = analyze([rep(i, "unknown") for i in range(20)])
        blame = ("you missed", "you were wrong", "too slow", "poor")
        assert not any(word in report.reason.lower() for word in blame)
        # And it says what to actually do about it.
        assert "step back" in report.reason.lower()


class TestItRefusesToSpeakTooSoon:
    def test_a_short_session_gets_no_breakdown(self):
        report = analyze(perfect(4), cues=4)
        assert not report.scored
        assert report.zones == []

    def test_the_reason_says_how_long_is_long_enough(self):
        report = analyze(perfect(4), cues=4)
        assert str(round((SPEC.lead_in_ms + SPEC.min_cues * SPEC.period_ms) / 1000)) \
            in report.reason

    def test_exactly_the_minimum_is_enough(self):
        report = analyze(perfect(SPEC.min_cues), cues=SPEC.min_cues)
        assert report.scored

    def test_a_session_with_no_reps_at_all_still_reports_the_cues(self):
        report = analyze([], cues=20)
        assert report.cues == 20
        assert report.answered == 0
        assert report.correct == 0
        assert report.accuracy == 0.0


class TestTheCoachingNote:
    def _sided(self, weak_side: str, count: int = 28):
        """A session that is perfect except on one side."""
        reps = []
        for i, zone in enumerate(targets(count)):
            if zone.endswith(weak_side):
                reps.append(rep(i, "mid_centre", 900))   # never got out there
            else:
                reps.append(rep(i, zone, 500))
        return reps

    def test_a_weak_side_is_named(self):
        report = analyze(self._sided("_left"), cues=28)
        assert report.scored
        assert report.weakest == "off-stick"      # right-handed goalie
        assert "off-stick" in report.note

    def test_the_weak_side_flips_with_the_top_hand(self):
        report = analyze(self._sided("_left"), cues=28, top_hand="left")
        assert report.weakest == "stick-side"

    def test_an_unknown_top_hand_falls_back_to_plain_sides(self):
        report = analyze(self._sided("_left"), cues=28, top_hand=None)
        assert report.weakest == "left"

    def test_a_weak_height_band_is_named_when_the_sides_are_even(self):
        reps = []
        for i, zone in enumerate(targets(28)):
            reps.append(rep(i, "mid_centre", 900) if zone.startswith("low")
                        else rep(i, zone, 500))
        report = analyze(reps, cues=28)
        assert report.weakest == "low"
        assert "low" in report.note

    def test_a_single_weak_spot_is_named_when_nothing_broader_shows(self):
        called = targets(40)
        # Break one spot only, and pick one whose mirror stays perfect so
        # neither the side nor the band comparison fires first.
        reps = [
            rep(i, "mid_centre", 900) if z == "low_centre" else rep(i, z, 500)
            for i, z in enumerate(called)
        ]
        report = analyze(reps, cues=40)
        assert report.weakest == "low_centre"
        assert "five hole" in report.note

    def test_a_clean_session_names_nothing(self):
        report = analyze(perfect(28), cues=28)
        assert report.weakest is None
        assert report.note

    def test_a_slower_side_is_named_even_when_accuracy_is_even(self):
        reps = []
        for i, zone in enumerate(targets(28)):
            slow = zone.endswith("_left")
            reps.append(rep(i, zone, 1_100 if slow else 450))
        report = analyze(reps, cues=28)
        assert report.weakest == "off-stick"
        assert "ms" in report.note

    def test_only_one_thing_is_ever_asked_for(self):
        # A goalie handed four fixes works on none of them.
        report = analyze(self._sided("_left"), cues=28)
        assert report.note.count(".") <= 3

    def test_the_note_never_grades_the_athlete(self):
        for reps, cues in ((perfect(28), 28), (self._sided("_left"), 28)):
            note = analyze(reps, cues=cues).note.lower()
            for word in ("bad", "poor", "weak goalie", "failed", "score of"):
                assert word not in note


class TestTheZoneBreakdown:
    def test_every_zone_in_the_vocabulary_gets_a_row(self):
        report = analyze(perfect(28), cues=28)
        assert [r.zone for r in report.zones] == list(SPEC.zones)

    def test_calls_add_up_to_the_cues_issued(self):
        report = analyze(perfect(28), cues=28)
        assert sum(r.called for r in report.zones) == 28

    def test_a_zone_never_reached_reports_no_time_rather_than_zero(self):
        # A median of 0ms would read as instant, which is the opposite of what
        # happened.
        called = targets(28)
        reps = [
            rep(i, "mid_centre", 900) if z == "low_centre" else rep(i, z, 500)
            for i, z in enumerate(called)
        ]
        report = analyze(reps, cues=28)
        row = next(r for r in report.zones if r.zone == "low_centre")
        assert row.correct == 0
        assert row.median_ms is None
        assert row.accuracy == 0.0


class TestTheSpecItself:
    def test_the_drill_is_cued(self):
        assert DRILL.is_cued

    def test_a_self_paced_drill_is_refused(self):
        with pytest.raises(ValueError):
            goalie.analyze(
                get_drill("gen_push_up"), [], nonce="x", duration_ms=60_000,
            )

    def test_a_rep_can_never_answer_two_cues(self):
        assert SPEC.late_ms < SPEC.period_ms

    def test_the_counter_cannot_straddle_two_cues_either(self):
        assert DRILL.counter.max_rep_ms <= SPEC.period_ms

    def test_the_minimum_duration_allows_the_minimum_cues(self):
        # Otherwise the drill's own validation would accept a session the
        # scorer then refuses to read, which is the worst of both.
        assert DRILL.validation.min_duration_ms >= duration_for(SPEC.min_cues)

    def test_the_two_centre_cells_are_observable_but_never_called(self):
        assert "high_centre" not in SPEC.zones
        assert "mid_centre" not in SPEC.zones

    def test_it_does_not_count_towards_throwing_volume(self):
        assert DRILL.load.throws_per_rep == 0.0


class TestItSaysWhatItCannotDo:
    def test_the_limits_ride_along_with_every_result(self):
        assert analyze(perfect(20)).to_dict()["limits"] == list(goalie.LIMITS)

    def test_the_limits_survive_a_withheld_session(self):
        # The moment a coach is most likely to fill in the gaps themselves.
        report = analyze([rep(i, "unknown") for i in range(20)])
        assert report.to_dict()["limits"] == list(goalie.LIMITS)

    def test_it_disclaims_being_a_save_percentage(self):
        assert any("save percentage" in limit for limit in goalie.LIMITS)

    def test_it_admits_the_app_calls_the_shot(self):
        assert any("reading a shooter" in limit or "reading a shot" in limit
                   for limit in goalie.LIMITS)

    def test_it_admits_it_watches_hands_and_not_the_stick_head(self):
        assert any("stick head" in limit for limit in goalie.LIMITS)

    def test_the_description_repeats_the_disclaimer_where_athletes_read_it(self):
        text = DRILL.description.lower()
        assert "no ball" in text
        assert "save percentage" in text


class TestTheDictIsSafeToShip:
    def test_it_is_json_serializable(self):
        import json
        json.dumps(analyze(perfect(20)).to_dict())

    def test_it_carries_no_imagery_or_landmarks(self):
        def keys(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield key
                    yield from keys(value)
            elif isinstance(node, list):
                for item in node:
                    yield from keys(item)

        found = set(keys(analyze(perfect(20)).to_dict()))
        # No coordinates, no landmark names, no pose data of any kind -- this
        # dict travels to a coach dashboard.
        assert not found & {"x", "y", "z", "landmarks", "frame", "frames", "video"}

    def test_no_value_in_it_is_a_pose_coordinate(self):
        import json
        blob = json.dumps(analyze(perfect(20)).to_dict()).lower()
        for banned in ("landmark", "wrist", "shoulder", "video", "image"):
            assert banned not in blob
