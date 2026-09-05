"""Server-side checks on ball-tracked sessions.

The browser does the tracking, so the browser is where the numbers come from,
so the browser cannot be trusted with them -- the same reasoning that produced
`integrity.py` for pose drills. A ball payload is easier to fake than a pose
one, because a rep is just a timestamp and a speed rather than a whole skeleton.

Three things are checked here that the client cannot be relied on to enforce.

**Track quality.** Every ball drill declares the share of frames that must
have had a real detection behind them. A client can report whatever it likes;
the server compares it against the spec and holds the session for review if it
is short. Silence is the failure mode being avoided: a session that says
"42 juggles" from a track that saw the ball twice.

**Physical plausibility.** Contacts have a rhythm. Juggling is roughly one
touch a second because the ball has to come back down; a payload claiming
forty touches in four seconds is describing something that did not happen.
Gaps below the drill's own refractory window cannot occur in a real client at
all, so their presence means the payload was not produced by one.

**Left/right honesty.** A perfectly even split across hundreds of contacts is
not what a child juggling in a garden produces. It is what a loop produces.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from .drills.base import DrillSpec

#: Below this the session is held rather than counted. A separate, lower bar
#: than the drill's own floor: the client should have stopped already, so
#: reaching the server at all means something is off.
HARD_QUALITY_FLOOR = 0.15

#: A left/right split this close to perfect, over this many reps, is a loop.
SUSPICIOUS_BALANCE = 0.002
BALANCE_MIN_REPS = 40

#: Confirm mode. Below this share of reps corroborated by a ball contact --
#: on a session where the ball *was* clearly visible -- the reps did not
#: involve a ball.
CONFIRM_MIN_SHARE = 0.25

#: And not judged at all below this many reps: a handful of throws where the
#: detector happened to miss the ball is noise, not evidence.
CONFIRM_MIN_REPS = 15

#: Share of tracked frames the ball must spend away from the hands.
#:
#: The check that separates wall ball from waving a ball around. An arm
#: whipping through a throwing motion with the ball still in it produces
#: accelerations that read as impulses and a wrist beside them that reads as a
#: contact, so contact counting alone scores that fake exactly like the real
#: thing -- measured at twelve contacts for twelve fake throws. What it cannot
#: fake is the ball leaving: real wall ball sends it metres away and brings it
#: back, and a ball that never gets more than a hand's width from a wrist has
#: not been thrown at anything.
CONFIRM_MIN_TRAVEL = 0.15


@dataclass
class BallReview:
    ok: bool = True
    hold: bool = False
    reasons: list[str] = field(default_factory=list)
    quality: float = 0.0

    #: Things worth saying that are not accusations. Kept separate from
    #: `reasons` so a note can never hold a session by accident.
    notes: list[str] = field(default_factory=list)

    def flag(self, reason: str, hold: bool = True) -> None:
        self.reasons.append(reason)
        self.ok = False
        self.hold = self.hold or hold

    def note(self, message: str) -> None:
        self.notes.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "hold": self.hold,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "quality": round(self.quality, 3),
        }


def review(
    spec: DrillSpec,
    reps: list[dict[str, Any]],
    track_quality: float | None,
    duration_ms: int,
    ball_contacts: int | None = None,
    ball_travel: float | None = None,
) -> BallReview:
    """Decide whether a ball-tracked submission can be counted."""
    result = BallReview(quality=float(track_quality or 0.0))
    if spec.ball is None:
        return result
    if spec.ball.confirms:
        return _review_confirmation(
            spec, reps, track_quality, ball_contacts, ball_travel, result,
        )

    if track_quality is None:
        result.flag(
            "This drill needs the ball tracked, and the recording did not "
            "report whether it saw one."
        )
        return result

    floor = spec.ball.min_track_quality
    if result.quality < HARD_QUALITY_FLOOR:
        result.flag(
            f"The ball was only visible in {result.quality:.0%} of the frames. "
            "Try again with the ball and your whole body in shot."
        )
    elif result.quality < floor:
        result.flag(
            f"The ball was visible in {result.quality:.0%} of frames, under the "
            f"{floor:.0%} this drill needs to count."
        )

    if not reps:
        return result

    times = sorted(int(r.get("t_ms", 0)) for r in reps)
    gaps = [b - a for a, b in zip(times, times[1:])]

    # A real client enforces the refractory window itself, so a gap below it
    # did not come from one.
    too_fast = [g for g in gaps if g < spec.ball.min_gap_ms * 0.75]
    if too_fast:
        result.flag(
            f"{len(too_fast)} contacts came faster than this drill allows.",
        )

    if duration_ms > 0:
        rate = len(reps) / (duration_ms / 1000)
        if rate > spec.validation.max_reps_per_second:
            result.flag(
                f"{rate:.1f} contacts a second is faster than the ball can "
                "come back."
            )

    # Perfectly even timing is a generator, not a child in a garden. Same
    # check the pose integrity layer makes, for the same reason.
    if len(gaps) >= 12:
        mean = statistics.fmean(gaps)
        if mean > 0:
            spread = statistics.pstdev(gaps) / mean
            if spread < 0.03:
                result.flag("The contacts are too evenly spaced to be real.")

    _review_alternation(spec, reps, result)

    if spec.ball.attribute_side:
        left = sum(1 for r in reps if r.get("hand") == "left")
        right = sum(1 for r in reps if r.get("hand") == "right")
        total = left + right
        if total >= BALANCE_MIN_REPS:
            share = left / total
            if abs(share - 0.5) < SUSPICIOUS_BALANCE:
                result.flag(
                    "The left/right split is too exact to have happened.",
                )
    return result


#: Below this many attributed contacts the hand pattern is noise. A crossover
#: session of six bounces says nothing about whether the athlete crossed over.
ALTERNATION_MIN_CONTACTS = 12

#: A crossover drill is not required to be perfect -- a fumbled rep or a hand
#: the camera misread should not fail the session. It is required to look like
#: somebody changing hands rather than somebody dribbling on one.
ALTERNATION_FLOOR = 0.60

#: ...and the mirror of it: a one-handed drill may lose the odd contact to
#: misattribution without becoming a two-handed one.
SAME_HAND_FLOOR = 0.80


def _review_alternation(
    spec: DrillSpec, reps: list[dict[str, Any]], result: BallReview,
) -> None:
    """Check the hands did what the drill asked of them.

    The point of this check is what it lets the catalogue do honestly. A
    crossover pays more than a plain dribble, and that is only defensible
    because this function can tell the difference -- unlike the wall-ball
    patterns, where the fancier name paid more for a movement the camera could
    not distinguish at all.

    Worded as a note rather than a refusal when the pattern is simply absent:
    an athlete who meant to cross over and mostly dribbled on their strong hand
    has done real work and should be told what happened, not have the session
    thrown away.
    """
    rule = spec.ball.alternation
    if rule == "any":
        return
    hands = [r.get("hand") for r in reps if r.get("hand") in ("left", "right")]
    if len(hands) < ALTERNATION_MIN_CONTACTS:
        return

    swaps = sum(1 for a, b in zip(hands, hands[1:]) if a != b)
    share = swaps / (len(hands) - 1)

    if rule == "alternating" and share < ALTERNATION_FLOOR:
        result.note(
            f"The ball changed hands on {share:.0%} of contacts. This drill is "
            "the change itself -- if it stayed on your strong hand, it counted "
            "as dribbling rather than as crossovers."
        )
    elif rule == "same_hand" and (1 - share) < SAME_HAND_FLOOR:
        result.note(
            f"The ball changed hands on {share:.0%} of contacts. This one is "
            "meant to stay on the one hand, which is the whole reason it is "
            "worth doing."
        )


def summarise(reps: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-session ball numbers worth keeping, for a coach and for scoring."""
    speeds = [float(r["speed"]) for r in reps if r.get("speed")]
    parts: dict[str, int] = {}
    for rep in reps:
        part = rep.get("part") or ""
        if part:
            parts[part] = parts.get(part, 0) + 1
    return {
        "contacts": len(reps),
        "median_speed": round(statistics.median(speeds), 3) if speeds else 0.0,
        "parts": parts,
    }


def _review_confirmation(
    spec: DrillSpec,
    reps: list[dict[str, Any]],
    track_quality: float | None,
    ball_contacts: int | None,
    ball_travel: float | None,
    result: BallReview,
) -> BallReview:
    """Confirm mode: the body counted the reps, the ball corroborates them.

    Deliberately asymmetric, and that asymmetry is the whole design. Not
    seeing a ball proves nothing -- a lacrosse ball is outside the detector's
    vocabulary, the light was bad, the phone was too far back -- so it never
    costs the athlete anything. Seeing the ball clearly and watching it never
    leave a hand while the arms threw forty times proves quite a lot.

    Penalising only on positive evidence is what stops this becoming a feature
    that quietly marks down every kid whose ball happens to be white.
    """
    if track_quality is None:
        # An older client, or one that never loaded the detector. Counts
        # exactly as it did before ball tracking existed.
        return result

    result.note(
        f"Ball visible in {result.quality:.0%} of frames."
    )
    if result.quality < spec.ball.min_track_quality:
        result.note(
            "Not enough to confirm a ball was used, which is common with a "
            "lacrosse ball, and it does not count against the session."
        )
        return result

    if len(reps) < CONFIRM_MIN_REPS or ball_contacts is None:
        return result

    share = ball_contacts / len(reps)
    if share < CONFIRM_MIN_SHARE:
        result.flag(
            f"The ball was tracked clearly for this session but was involved "
            f"in only {share:.0%} of the {len(reps)} throws counted."
        )
        return result

    # Contacts alone cannot tell a throw from a wave, because an arm whipping
    # forward with the ball still in it produces the same impulse beside the
    # same wrist. Whether the ball ever left the hand can.
    if ball_travel is not None and ball_travel < CONFIRM_MIN_TRAVEL:
        result.flag(
            "The ball never travelled away from your hands, so these look like "
            "throwing motions rather than throws."
        )
    return result
