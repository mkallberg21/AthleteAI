"""What a form-shooting session can and cannot say.

This is the drill that was called too hard to build twice, and the reason was
never the motion. A shot is a clean elbow cycle and pose reads it easily. The
problem is that **the app cannot see whether the ball went in** -- there is no
hoop in a driveway drill, and a camera propped against a water bottle would not
find one if there were.

So the honest version does not try. It scores nothing about accuracy, reports
no makes, and says so in the drill description, in the setup hint, and in
`LIMITS` below. What it measures instead is the one thing every shooting coach
says first and pose can genuinely see: whether the elbow stayed under the ball.

The same two rules that shaped the goalie report and the footwork one apply
here, for the same reasons.

**Counted, never scored.** A flare is reported as a number and a sentence. It
subtracts nothing. A child rebuilding a shot will flare for weeks, and an app
that quietly paid them less for it would teach them to stop using the app
rather than to fix the elbow.

**Said to the athlete.** The line goes on their own screen in their own words.
A fault the app can see and only reports to a coach is surveillance.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

#: What this drill is and is not, carried on every result. The gap between
#: "your elbow is under the ball" and "you are a good shooter" is exactly the
#: gap a number on a screen will be assumed to have closed.
LIMITS = (
    "There is no hoop in this drill and the app cannot see one. It knows "
    "nothing about whether anything went in, and no number here is a shooting "
    "percentage.",
    "It watches your elbow, not the ball's flight. A shot can have a perfect "
    "elbow and still be short, flat or wide.",
    "Turned sideways to the phone it cannot tell an elbow under the ball from "
    "one flared out, so those reps are reported as unreadable rather than good.",
)

#: Below this many readable releases the median is noise.
MIN_RELEASES = 8

#: Elbow offset from the wrist, in torso lengths, at or under which the elbow
#: is under the ball. A shooting arm at full extension puts the elbow almost
#: directly beneath the wrist; a flare pushes it out toward the shoulder.
UNDER = 0.18

#: ...and beyond which it has genuinely flared rather than drifted.
FLARED = 0.32

#: Share of readable releases that must be flared before it is a habit rather
#: than the occasional rep.
HABIT_SHARE = 0.30

#: Below this share of releases being readable, the session describes the phone
#: angle rather than the athlete.
MIN_READABLE = 0.60


@dataclass
class ShotReport:
    releases: int = 0
    readable: int = 0
    flared: int = 0
    #: Median elbow offset in torso lengths, or None when too few were readable.
    median_flare: float | None = None
    note: str = ""

    @property
    def scored(self) -> bool:
        return self.median_flare is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "releases": self.releases,
            "readable": self.readable,
            "flared": self.flared,
            "median_flare": (None if self.median_flare is None
                             else round(self.median_flare, 3)),
            "scored": self.scored,
            "note": self.note,
            "limits": list(LIMITS),
        }


def analyze(reps: list[dict[str, Any]]) -> ShotReport:
    """Read the elbow across a set of releases."""
    releases = [r for r in reps if "flare" in r]
    report = ShotReport(releases=len(releases))
    if not releases:
        return report

    seen = [float(r["flare"]) for r in releases if r.get("flare") is not None]
    report.readable = len(seen)

    if report.readable / len(releases) < MIN_READABLE:
        report.note = (
            "The phone could not see your shooting elbow on most of these. "
            "Stand square to it rather than side-on -- from the side, an elbow "
            "under the ball and one flared out look identical."
        )
        return report
    if report.readable < MIN_RELEASES:
        report.note = (
            "Not enough clean releases yet to say anything about your elbow. "
            "A longer set and the app will tell you."
        )
        return report

    report.median_flare = median(seen)
    report.flared = sum(1 for f in seen if f >= FLARED)
    share = report.flared / report.readable

    # Ordered so a good median cannot hide bad reps. Checking "is the median
    # under the ball" first said everything was fine to a shooter with two
    # flared shots in twenty, which is exactly the rep they need to hear about.
    if report.flared == 0 and report.median_flare <= UNDER:
        report.note = (
            "Your elbow stayed under the ball on every shot. That is the hard "
            "part and the part that survives being tired, so keep the reps "
            "where they are rather than moving further out."
        )
    elif share >= HABIT_SHARE:
        report.note = (
            f"Your elbow came out from under the ball on {report.flared} of "
            f"{report.readable} shots. That is often enough to be how you are "
            "shooting rather than the odd rep -- get closer to the wall and "
            "slow it right down until it stops."
        )
    else:
        report.note = (
            f"Mostly under the ball, with {report.flared} of "
            f"{report.readable} shots flaring out. Watch for it late in a set: "
            "that is usually when a tired shoulder starts pushing the elbow "
            "sideways."
        )
    return report
