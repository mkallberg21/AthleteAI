"""Automated coach recognition when an athlete puts the work in at home.

The gap this fills is small and matters more than its size. A kid who does
wall ball in the driveway on a Tuesday gets a number on a dashboard their coach
may look at on Friday. What they wanted was for someone to notice. This makes
someone notice, on the day, by name.

Three rules shape it.

**It comes from a person.** Every message carries a coach's name, because
"Coach Ada noticed" is the thing that lands and "the system detected" is not.
The coach does not have to be at their computer for that to be true -- they
wrote the words once, in advance, and this delivers them at the moment they
mean something.

**The words are the coach's, not ours.** Every milestone ships with a default
that a program can replace with their own, per milestone, in their own voice.
The defaults are deliberately plain so a coach reading them thinks "I would say
that differently", which is the point.

**It fires once per run, not once per day.** A ten-day streak is worth saying
something about. Saying it again on day eleven, and twelve, is how a child
learns to ignore the app. Milestones dedupe on the streak they belong to, so
an athlete who breaks a streak and rebuilds it is congratulated again -- which
is right, because doing it a second time is harder than doing it once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Milestone:
    key: str
    label: str
    #: Consecutive days for a streak milestone; None for the first session.
    streak: int | None
    #: What a coach sees when choosing which to customise.
    description: str = ""
    default_body: str = ""
    #: The same milestone as a parent would put it.
    #:
    #: A separate default rather than the coach one with the nouns swapped.
    #: "See you at practice" and "the thing that separates players" are things
    #: a coach says; a parent saying them sounds like a parent trying to talk
    #: like a coach, and a child can hear the difference. Shorter and warmer on
    #: purpose, and like the coach set these are placeholders a parent should
    #: want to rewrite.
    family_body: str = ""

    def body_for(self, kind: str = "program") -> str:
        if kind == "family" and self.family_body:
            return self.family_body
        return self.default_body

    def to_dict(
        self, body: str = "", customised: bool = False, from_voice: str = "",
        kind: str = "program",
    ) -> dict[str, Any]:
        shipped = self.body_for(kind)
        return {
            "key": self.key,
            "label": self.label,
            "streak": self.streak,
            "default_body": shipped,
            "body": body or shipped,
            "customised": customised,
            "from_voice": from_voice or self.default_voice,
        }

    @property
    def default_voice(self) -> str:
        return Voice.VOICE if self.key in VOICE_DEFAULTS else Voice.COACH


class Voice:
    """Who a milestone comes from."""

    COACH = "coach"
    #: A senior figure in the program -- a director of player development, a
    #: former professional. Worth reserving for the rare milestones: a note
    #: from someone like that means something precisely because it does not
    #: arrive every week, and putting their name on a three-day streak spends
    #: the thing that made it valuable.
    VOICE = "voice"

    ALL = (COACH, VOICE)


#: Milestones that default to the senior voice where a program has set one.
#: The long ones only, for the reason above.
VOICE_DEFAULTS = ("streak_30", "streak_100")


#: Placeholders a coach can use. Deliberately few -- a template language is a
#: thing to learn, and a coach writing one sentence should not have to.
TOKENS = ("{first_name}", "{streak}", "{coach}", "{team}")

MILESTONES: tuple[Milestone, ...] = (
    Milestone(
        key="first_session",
        label="Their first session",
        streak=None,
        default_body=(
            "{first_name}, that is your first one logged. The hard part is "
            "starting and you have done it — see you at practice."
        ),
        family_body=(
            "{first_name}, you did the first one. Starting is the hard bit, and you started."
        ),
    ),
    Milestone(
        key="streak_3",
        label="Three days in a row",
        streak=3,
        default_body=(
            "{first_name}, three days running. That is how a habit starts, and "
            "I noticed."
        ),
        family_body=(
            "Three days running, {first_name}. I noticed, and I am not just saying that."
        ),
    ),
    Milestone(
        key="streak_5",
        label="Five days in a row",
        streak=5,
        default_body=(
            "Five days in a row, {first_name}. Most people do not get here. "
            "Well done."
        ),
        family_body=(
            "Five days, {first_name}. You did that on your own and I am proud of you."
        ),
    ),
    Milestone(
        key="streak_10",
        label="Ten days in a row",
        streak=10,
        default_body=(
            "{first_name}, ten days straight. That is real work and it will "
            "show up on the field. Proud of you."
        ),
        family_body=(
            "Ten days straight, {first_name}. Nobody made you do any of them. That is the part that counts."
        ),
    ),
    Milestone(
        key="streak_30",
        label="Thirty days in a row",
        streak=30,
        default_body=(
            "Thirty days, {first_name}. A month of turning up when nobody made "
            "you. That is the thing that separates players."
        ),
        family_body=(
            "A whole month, {first_name}. Thirty days of choosing to. I hope you are as pleased with that as I am."
        ),
    ),
    Milestone(
        key="streak_100",
        label="A hundred days in a row",
        streak=100,
        default_body=(
            "{first_name} — one hundred days. I am not sure what to say except "
            "that I have coached a long time and this is rare."
        ),
        family_body=(
            "One hundred days, {first_name}. I do not really have words for it. Well done."
        ),
    ),
)

BY_KEY = {m.key: m for m in MILESTONES}

#: Streak milestones, longest first, so the biggest one an athlete just
#: crossed is the one they hear about rather than all of them at once.
STREAK_MILESTONES = tuple(
    sorted((m for m in MILESTONES if m.streak), key=lambda m: -m.streak)
)


def render(body: str, *, first_name: str, streak: int, coach: str, team: str) -> str:
    """Fill a coach's template.

    Unknown tokens are left alone rather than erroring: a coach who typos
    `{firstname}` should get a slightly odd message, not silence.
    """
    return (
        body.replace("{first_name}", first_name or "there")
        .replace("{streak}", str(streak))
        .replace("{coach}", coach or "your coach")
        .replace("{team}", team or "the team")
    )


def earned(
    *, sessions_before: int, streak: int, streak_start: date | None
) -> list[tuple[Milestone, str]]:
    """Which milestones this submission just crossed, with their dedupe keys.

    `sessions_before` is the count *before* this one, so the first session is
    recognised on the session that makes it true rather than the one after.

    Streak milestones key off the day the current run began, which is what
    makes "once per run" work: the same ten-day mark reached in March and again
    in June are two different achievements and two different keys.
    """
    out: list[tuple[Milestone, str]] = []
    if sessions_before == 0:
        out.append((BY_KEY["first_session"], "first_session"))

    # Only the largest crossed, so passing day 10 does not also replay day 5
    # and day 3 in the same breath.
    for milestone in STREAK_MILESTONES:
        if streak >= milestone.streak:
            run = streak_start.isoformat() if streak_start else "unknown"
            out.append((milestone, f"{milestone.key}:{run}"))
            break
    return out
