"""Cue sequence tests.

The golden vectors are the important ones. `static/cues.js` carries the same
list, and if the two implementations ever disagree the browser shows an athlete
one spot while the server marks them against another -- silently, on every rep,
with no error raised anywhere. Nothing else in the system would catch that, so
these vectors are load-bearing rather than decorative.
"""

from __future__ import annotations

import pytest

from offdays.cues import MAX_CUES, Random, cue_at, cue_count, seed_of, sequence
from offdays.drills.catalog import get_drill

ZONES = get_drill("lax_goalie_saves").cues.zones

# Written out by hand and pasted into both suites. Deliberately not regenerated
# from either implementation -- a vector regenerated from the code under test
# agrees with whatever that code currently does, which is the single thing it
# must not do.
GOLDEN = {
    "a": (
        3826002220,
        ["high_left", "low_centre", "mid_right", "mid_left", "low_right",
         "high_right", "low_left", "high_right", "low_centre", "high_left",
         "mid_left", "low_right"],
    ),
    "session-nonce-1": (
        2073095791,
        ["low_left", "mid_left", "low_centre", "low_right", "mid_right",
         "high_right", "high_left", "high_right", "mid_right", "low_right",
         "mid_left", "low_left"],
    ),
    "ZZZ99": (
        2661185967,
        ["high_left", "mid_left", "low_left", "mid_right", "low_centre",
         "high_right", "low_right", "low_centre", "low_right", "low_left",
         "high_left", "mid_left"],
    ),
    "": (
        2166136261,
        ["low_centre", "high_left", "low_right", "high_right", "mid_right",
         "mid_left", "low_left", "mid_right", "high_left", "low_right",
         "mid_left", "low_left"],
    ),
}

GOLDEN_DRAWS = [
    0.594323272817, 0.943420797819, 0.303835050669,
    0.767653154675, 0.472406724002, 0.185853380011,
]


class TestItMatchesTheBrowser:
    @pytest.mark.parametrize("nonce", list(GOLDEN))
    def test_seed(self, nonce):
        assert seed_of(nonce) == GOLDEN[nonce][0]

    def test_random_stream(self):
        rng = Random(seed_of("golden"))
        assert [round(rng.next(), 12) for _ in GOLDEN_DRAWS] == GOLDEN_DRAWS

    @pytest.mark.parametrize("nonce", list(GOLDEN))
    def test_sequence(self, nonce):
        assert sequence(nonce, 12, ZONES) == GOLDEN[nonce][1]

    def test_every_value_stays_in_range(self):
        rng = Random(seed_of("range"))
        for _ in range(2_000):
            value = rng.next()
            assert 0.0 <= value < 1.0


class TestTheSequenceIsUsable:
    def test_the_same_nonce_always_gives_the_same_sequence(self):
        assert sequence("abc", 40, ZONES) == sequence("abc", 40, ZONES)

    def test_different_nonces_give_different_sequences(self):
        assert sequence("abc", 20, ZONES) != sequence("abd", 20, ZONES)

    def test_a_longer_sequence_extends_a_shorter_one(self):
        # The browser generates far more cues than a session uses; the server
        # generates exactly as many as the session ran for. They line up only
        # if the short list is a prefix of the long one -- otherwise every rep
        # after the cut point is marked against the wrong target.
        long = sequence("abc", 200, ZONES)
        assert sequence("abc", 31, ZONES) == long[:31]

    def test_every_zone_comes_up_once_per_bag(self):
        seq = sequence("balance", 70, ZONES)
        for start in range(0, 70, len(ZONES)):
            assert sorted(seq[start:start + len(ZONES)]) == sorted(ZONES)

    @pytest.mark.parametrize("nonce", ["a", "b", "c", "seam", "x" * 40])
    def test_the_same_spot_is_never_called_twice_running(self, nonce):
        seq = sequence(nonce, 400, ZONES)
        repeats = [i for i in range(1, len(seq)) if seq[i] == seq[i - 1]]
        assert repeats == []

    def test_it_spreads_across_the_whole_vocabulary(self):
        seq = sequence("spread", 700, ZONES)
        counts = {z: seq.count(z) for z in ZONES}
        # Bags make this exact rather than approximate.
        assert set(counts.values()) == {100}

    def test_a_unicode_nonce_does_not_explode(self):
        assert len(sequence("nonce-é中", 20, ZONES)) == 20


class TestItRefusesTheBadCases:
    def test_zero_or_negative_gives_nothing(self):
        assert sequence("a", 0, ZONES) == []
        assert sequence("a", -5, ZONES) == []

    def test_an_absurd_count_is_refused_rather_than_hanging(self):
        with pytest.raises(ValueError):
            sequence("a", MAX_CUES + 1, ZONES)

    def test_one_zone_is_refused(self):
        # With a single zone there is nothing to react to, and the no-repeat
        # swap below would loop forever looking for an alternative.
        with pytest.raises(ValueError):
            sequence("a", 10, ("high_left",))

    def test_a_zero_period_is_refused(self):
        with pytest.raises(ValueError):
            cue_count(60_000, 4_000, 0)


class TestCueTiming:
    def test_cues_land_on_a_fixed_cadence_after_the_lead_in(self):
        assert cue_at(0, 4_000, 2_400) == 4_000
        assert cue_at(3, 4_000, 2_400) == 11_200

    def test_a_session_ending_mid_cue_does_not_count_that_cue(self):
        # A cue the athlete never got a full window to answer must not be
        # recorded as one they missed.
        assert cue_count(4_000 + 2_400 * 4 + 900, 4_000, 2_400) == 4
        assert cue_count(4_000 + 2_400 * 5, 4_000, 2_400) == 5

    def test_a_session_shorter_than_the_lead_in_has_no_cues(self):
        assert cue_count(3_000, 4_000, 2_400) == 0

    def test_the_count_is_capped(self):
        assert cue_count(10 ** 9, 4_000, 2_400) == MAX_CUES
