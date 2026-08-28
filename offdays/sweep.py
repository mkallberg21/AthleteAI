"""What a hand-sweep session says about the two sides of an athlete.

The sweep signal is signed, so every counted rep already carries how far the
hands got in each direction: `peak` is the furthest one way and `peak - rom` is
the furthest the other. Nothing extra is recorded, no new column, and no new
field on the rep payload.

**Two sports read the same number and mean different things by it, which is why
this module names neither.** A hockey player holds the stick the same way for
their whole life -- their weak side is the backhand, and it is weak in exactly
the way an off-hand is. A rugby player is required to pass off both hands from
anywhere, so their weak side is a gap the sport will find inside one game. The
measurement is identical; the conclusion belongs to the athlete, who knows
which sport they play and which way they hold things.

Three rules shape what comes out, and two of them are the rules that shaped the
goalie report and the crossed-feet report.

**Counted, never scored.** A short side is reported as a measurement, not a
deduction. A thirteen-year-old's weak side is short because it is their weak
side, and the useful response is being told so, not being quietly paid less.

**Said plainly to the athlete.** The line below goes on their own screen.

**It never says which side.** With one camera and no stick or ball in the pose
model, the app knows the hands went further one way than the other; it does not
know which way the athlete shoots or passes, and a coaching instruction built
on a coin flip is worse than none. So it reports the asymmetry and lets the
athlete -- who knows perfectly well -- supply the label. That is the same rule
the tennis drills follow about forehand and backhand wings.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

#: Below this many readable reps the medians are noise.
MIN_REPS = 12

#: The short side has to be under this share of the long one before it is
#: worth saying anything. Some asymmetry is in every athlete and always will
#: be; a drill that flagged 5% would be flagging everybody.
SHORT_SIDE = 0.70

#: Under this, the short side has stopped being weaker and is barely being
#: used -- the reps are firing on the threshold and nothing more.
VERY_SHORT = 0.50


@dataclass
class SweepReport:
    reps: int = 0
    #: Median distance the hands reached each way, in torso lengths. Sides are
    #: 'a' and 'b' rather than left and right on purpose: they are the
    #: athlete's own sides, and naming either one would be a guess about which
    #: way they hold a stick or which hand they pass off.
    reach_a: float | None = None
    reach_b: float | None = None
    #: Short side over long side. 1.0 is perfectly even.
    balance: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reps": self.reps,
            "reach_a": None if self.reach_a is None else round(self.reach_a, 3),
            "reach_b": None if self.reach_b is None else round(self.reach_b, 3),
            "balance": None if self.balance is None else round(self.balance, 3),
            "note": self.note,
        }


def analyze(reps: list[dict[str, Any]]) -> SweepReport:
    """Measure how even a stick session was across the two sides of the body."""
    # A rep needs both numbers: `peak` alone is one side of the sweep, and the
    # other side is only recoverable with the range of motion beside it.
    usable = [
        r for r in reps
        if r.get("peak") is not None and r.get("rom") is not None
    ]
    report = SweepReport(reps=len(usable))
    if not usable:
        return report

    # `peak` is the far end in the firing direction; the rom spans the whole
    # cycle, so the other extreme is peak - rom. Both are measured from the
    # middle of the chest, so each is a distance out to one side.
    side_a = [float(r["peak"]) for r in usable]
    side_b = [float(r["rom"]) - float(r["peak"]) for r in usable]

    report.reach_a = median(side_a)
    report.reach_b = median(side_b)

    if len(usable) < MIN_REPS:
        report.note = (
            "Not enough reps yet to say anything about your two sides. Give it "
            "a longer set and the app will tell you whether one is short."
        )
        return report

    long_side = max(report.reach_a, report.reach_b)
    short_side = min(report.reach_a, report.reach_b)
    if long_side <= 0:
        return report

    report.balance = max(0.0, short_side) / long_side

    if report.balance >= SHORT_SIDE:
        report.note = (
            "Your hands went about as far one way as the other. That is the "
            "hard part of this drill, and most players never get there."
        )
    elif report.balance >= VERY_SHORT:
        report.note = (
            f"One side is going about {round(report.balance * 100)}% as far as "
            "the other. The app cannot tell which of your two sides that is "
            "-- but you can, and that is the one to work on."
        )
    else:
        report.note = (
            f"One side is going about {round(report.balance * 100)}% as far as "
            "the other, which is barely using it at all. The app cannot tell "
            "which of your two sides that is -- but you can. Slow the whole "
            "drill down until both sides look the same, then build the speed "
            "back."
        )
    return report
