"""Where a program is in its year, and what that does to a training budget.

The age bands say what a week of self-directed work should look like at
twelve, at fifteen, at eighteen. What they cannot say is whether it is
February or July, and that changes the answer more than a birthday does.

The direction is the part worth being explicit about, because it is the
opposite of what a training app usually does. **In-season the solo budget
goes down, not up.** These budgets have only ever counted self-directed work
on top of team practice, and in-season a child already has three practices
and a game in their week. Holding the same solo target on top of that is not
ambition, it is how a season ends in a stress fracture. Off-season the team
week is empty, so the same child has room for more of their own work.

Post-season is the lowest of all, and deliberately so. A break after a season
is the single most protective thing a young athlete does, and an app that
treats a quiet November as a lapse is working against the child it is meant
to help. So the budget drops, and the wording changes with it: the app says
this is the break, rather than telling a kid they are behind.

A program picks its phase. There is no attempt to infer it from the calendar
-- sports do not share a season, a club may run two, and a wrong guess here
silently changes what every child in the program is told to do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Phase:
    key: str
    label: str
    #: Multiplier on the weekly *self-directed* volume figures.
    scale: float
    #: What a coach reads when choosing, in terms of the club's own calendar.
    coach_note: str
    #: What an athlete reads on their own budget. Second person, no jargon.
    athlete_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "scale": self.scale,
            "coach_note": self.coach_note,
            "athlete_note": self.athlete_note,
        }


PHASES: tuple[Phase, ...] = (
    Phase(
        key="offseason", label="Off-season", scale=1.25,
        coach_note=(
            "No team practices. Athletes have the most room for their own "
            "work now, so the budget goes up."
        ),
        athlete_note=(
            "It is the off-season, so there is more room for your own work "
            "than there will be once practices start."
        ),
    ),
    Phase(
        key="preseason", label="Pre-season", scale=1.0,
        coach_note=(
            "Building towards the season. The published budget as it stands."
        ),
        athlete_note="Pre-season. This is the normal budget for your age.",
    ),
    Phase(
        key="in_season", label="In-season", scale=0.6,
        coach_note=(
            "Practices and games already fill the week. The solo budget drops "
            "so it stacks on top of a real training load rather than ignoring "
            "it."
        ),
        athlete_note=(
            "You are in-season, so most of your training is already happening "
            "at practice. This is what is left on top of that."
        ),
    ),
    Phase(
        key="postseason", label="Post-season break", scale=0.4,
        coach_note=(
            "A deliberate break. The budget is low on purpose and athletes "
            "are not nudged for missing it -- the rest is the point."
        ),
        athlete_note=(
            "This is your break. Doing less right now is the plan, not a "
            "slip -- it is what lets you come back fresh."
        ),
    ),
)

BY_KEY = {p.key: p for p in PHASES}

#: Programs that have not chosen sit here. Pre-season is the neutral one: it
#: is the published budget unmodified, so nothing changes for anybody until a
#: director makes an actual decision.
DEFAULT = BY_KEY["preseason"]


def get(key: str | None) -> Phase:
    """Resolve a stored key, forgiving a null or a value we no longer ship."""
    return BY_KEY.get(key or "", DEFAULT)


def is_break(key: str | None) -> bool:
    """Whether this phase means an athlete should not be nudged upward.

    The whole feature turns on this. Encouraging a child to train more during
    the break is worse than saying nothing at all.
    """
    return get(key).key == "postseason"
