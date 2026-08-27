"""What a stance-width session says about the feet.

Every other drill in the catalogue scores how much work was done and how well
shaped it was. A defensive slide has a third question that matters more than
either: did the feet cross.

Crossing is the error every defensive coach spends a season shouting about, and
it is the one technique fault anywhere in this product that the camera can
establish rather than infer. The stance-width signal is signed, so a crossed
step is not a judgement call about form -- it is the number going below zero,
which happens or it does not.

Two rules shape what comes out of here, and they are the same two that shaped
the goalie report.

**Counted, never scored.** Crossed steps are reported as a count and a share.
There is no penalty, no deduction and nothing subtracted from the session,
because a twelve-year-old learning to slide will cross their feet and the
useful response to that is a coach saying so, not an app quietly paying them
less for it.

**Said plainly to the athlete.** The line below goes on their own screen in
their own words. A fault the app can see and only tells the coach about is
surveillance; a fault it tells the athlete about is coaching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Below this many steps the share is noise -- one crossed step out of four is
#: 25% and means nothing at all.
MIN_STEPS = 10

#: Above this share of steps, crossing has stopped being the occasional slip
#: and become how the athlete is sliding.
HABIT_SHARE = 0.25


@dataclass
class FootworkReport:
    steps: int = 0
    crossed: int = 0
    #: None when there were too few steps to say anything.
    share: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "crossed": self.crossed,
            "share": None if self.share is None else round(self.share, 3),
            "note": self.note,
        }


def analyze(reps: list[dict[str, Any]]) -> FootworkReport:
    """Count the crossed steps in a slide session and say what they mean."""
    steps = [r for r in reps if r.get("crossed") is not None]
    report = FootworkReport(steps=len(steps))
    if not steps:
        return report

    report.crossed = sum(1 for r in steps if r.get("crossed"))
    if len(steps) < MIN_STEPS:
        report.note = (
            "Not enough steps yet to say anything about your feet. Give it a "
            "longer set and the app will tell you whether they crossed."
        )
        return report

    report.share = report.crossed / len(steps)
    if report.crossed == 0:
        report.note = (
            "Your feet never crossed. That is the whole drill, and it is the "
            "thing most players cannot do once they get tired."
        )
    elif report.share >= HABIT_SHARE:
        report.note = (
            f"Your feet crossed on {report.crossed} of {len(steps)} steps. "
            "That is often enough that it is how you are sliding rather than "
            "a slip -- slow it down until they stop, then build the speed back."
        )
    else:
        report.note = (
            f"Your feet crossed on {report.crossed} of {len(steps)} steps, "
            "which is the odd slip rather than a habit. Watch for it late in "
            "a set, when it usually starts."
        )
    return report
