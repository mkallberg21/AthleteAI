"""Wall ball, strong hand and off hand, say the same thing about what it pays off for.

They are the same drill on a different hand. Telling a kid that one helps hockey
and baseball while the other helps hockey and basketball made the screen read as
if they were different work.
"""
from __future__ import annotations

from offdays import transfer

PAIR = ("lax_wall_ball_strong", "lax_wall_ball_offhand")


def _sports(key: str) -> list[str]:
    return [t.sport for t in transfer.TRANSFERS[key]]


def _lines(key: str) -> list[tuple[str, str]]:
    return [(t.sport, t.why) for t in transfer.TRANSFERS[key]]


class TestWallBallPair:
    def test_both_hands_name_the_same_sports(self):
        assert _sports(PAIR[0]) == _sports(PAIR[1])

    def test_and_say_the_same_thing_about_each(self):
        assert _lines(PAIR[0]) == _lines(PAIR[1])

    def test_the_list_is_not_empty(self):
        assert _sports(PAIR[1])

    def test_each_still_reads_true_for_a_lacrosse_player(self):
        # The athlete's own sport is never listed; the pair must not start to.
        for key in PAIR:
            assert "Lacrosse" not in _sports(key)

    def test_the_other_wall_ball_drills_are_untouched(self):
        # One-hand, cross, behind-the-back and split are different work.
        assert _sports("lax_wall_ball_one_hand") == ["Baseball", "Tennis"]
        assert _sports("lax_wall_ball_cross") == ["Basketball", "Hockey"]
        assert _sports("lax_wall_ball_btb") == ["Basketball"]
        assert _sports("lax_wall_ball_split") == ["Basketball", "Soccer", "Football"]
