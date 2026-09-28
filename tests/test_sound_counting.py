"""Wall ball counted by ear.

The browser listens and sends only the times it heard the ball; everything
here is what the server does with that. The fixture timings are the rebounder
impacts from a real clip of a fifteen-year-old's off-hand wall ball -- the clip
the pose counter scored 3 of 15 -- read off the audio track.
"""
from __future__ import annotations

import pytest

from offdays.api import RepPayload
from offdays.drills import ALL_DRILLS, SignalKind, get_drill
from offdays.integrity import RepEvent, SessionClaim, evaluate

#: Impact times (ms) from the reference clip, IMG_6827. Fifteen throws.
REAL_IMPACTS_MS = [
    410, 1890, 3340, 4790, 6270, 7720, 9250, 10710,
    12110, 13550, 15000, 16490, 17930, 19380, 20880,
]


def sound_reps(times, source="sound"):
    return [RepEvent(t_ms=t, hand="left", confidence=0.72, source=source) for t in times]


@pytest.fixture
def offhand():
    return get_drill("lax_wall_ball_offhand")


class TestCatalog:
    def test_every_wall_ball_drill_is_counted_by_ear(self):
        cycle = [d for d in ALL_DRILLS if d.signal.kind is SignalKind.WALL_BALL_CYCLE]
        assert cycle, "no wall-ball drills found"
        for drill in cycle:
            assert drill.sound is not None, drill.key
            assert drill.sound.min_cycle_ms > 0

    def test_nothing_else_asks_for_the_microphone(self):
        # The permission prompt is a cost. Only drills with a ball that makes
        # one sound per rep against something should ask for it.
        for drill in ALL_DRILLS:
            if drill.signal.kind is not SignalKind.WALL_BALL_CYCLE:
                assert drill.sound is None, drill.key

    def test_the_browser_receives_the_sound_spec(self, offhand):
        assert offhand.to_dict()["sound"] == {"min_cycle_ms": 700}

    def test_the_setup_hint_no_longer_promises_any_angle_works(self):
        # From behind, the body hides the stick hand. It was measured.
        assert "any angle" not in get_drill("lax_wall_ball").setup_hint


class TestIntegrity:
    def test_a_real_athletes_steady_rhythm_counts(self, offhand):
        # Cadence variation on this clip is 0.021 -- under the 0.03 floor that
        # pose-timed sessions are held to. A practised player on a rebounder
        # really is that steady, and the ear times it to the millisecond.
        reps = sound_reps(REAL_IMPACTS_MS)
        claim = SessionClaim(offhand.key, 21_130, reps, mean_confidence=0.72)
        result = evaluate(claim, offhand)
        assert not any("even" in n for n in result.notes), result.notes

    def test_the_same_timings_from_pose_are_still_held_to_the_pose_floor(self, offhand):
        reps = sound_reps(REAL_IMPACTS_MS, source=None)
        claim = SessionClaim(offhand.key, 21_130, reps, mean_confidence=0.72)
        assert any("even" in n for n in evaluate(claim, offhand).notes)

    def test_a_metronome_is_still_caught_when_it_claims_to_be_sound(self, offhand):
        reps = sound_reps([i * 1400 for i in range(1, 40)])
        claim = SessionClaim(offhand.key, 40 * 1400, reps, mean_confidence=0.9)
        result = evaluate(claim, offhand)
        assert result.status in ("review", "rejected")
        assert any("even" in n for n in result.notes)

    def test_one_pose_rep_among_sound_reps_uses_the_pose_floor(self, offhand):
        # The lower floor is for sessions timed by ear, not for any session
        # that mentions sound once.
        reps = sound_reps(REAL_IMPACTS_MS)
        reps[3] = RepEvent(t_ms=reps[3].t_ms, hand="left", confidence=0.72)
        claim = SessionClaim(offhand.key, 21_130, reps, mean_confidence=0.72)
        assert any("even" in n for n in evaluate(claim, offhand).notes)


class TestPayload:
    def test_sound_is_accepted(self):
        assert RepPayload(t_ms=410, source="sound").source == "sound"

    def test_absent_means_timed_off_video(self):
        assert RepPayload(t_ms=410).source is None

    def test_nothing_else_is(self):
        with pytest.raises(ValueError):
            RepPayload(t_ms=410, source="audio")

    def test_no_audio_is_accepted_anywhere(self):
        # A rep is a timestamp. The model has no field that could carry sound.
        fields = set(RepPayload.model_fields)
        assert not any(("audio" in f or "sample" in f or "wav" in f) for f in fields)
