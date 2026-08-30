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
    #: Ways of saying the same thing. The first is the shipped default and
    #: the rest exist so two athletes on the same squad never open the same
    #: sentence in the same week -- see WINDOW_DAYS below for why that
    #: matters more than it sounds.
    bodies: tuple[str, ...] = ()
    #: The same milestone as a parent would put it.
    #:
    #: A separate default rather than the coach one with the nouns swapped.
    #: "See you at practice" and "the thing that separates players" are things
    #: a coach says; a parent saying them sounds like a parent trying to talk
    #: like a coach, and a child can hear the difference. Shorter and warmer on
    #: purpose, and like the coach set these are placeholders a parent should
    #: want to rewrite.
    family_bodies: tuple[str, ...] = ()

    @property
    def default_body(self) -> str:
        return self.bodies[0] if self.bodies else ""

    @property
    def family_body(self) -> str:
        return self.family_bodies[0] if self.family_bodies else ""

    def pool(self, kind: str = "program") -> tuple[str, ...]:
        """Every way this milestone can be said, in this voice."""
        if kind == "family" and self.family_bodies:
            return self.family_bodies
        return self.bodies

    def body_for(self, kind: str = "program", locale: str = "en") -> str:
        """The shipped default, in the reader's language where we have one.

        Shipped only. A coach who rewrites this in English produces English,
        and there is no translation service in this application -- inventing
        one silently would be worse than the gap. `translated_default` says
        which case a caller is in so the parent view can be honest about it.
        """
        from . import i18n

        locale = i18n.normalize(locale)
        family = kind == "family" and self.family_body
        key = f"recognition.family.{self.key}" if family else f"recognition.{self.key}"
        translated = i18n.t(key, locale)
        if translated:
            return translated
        return self.family_body if family else self.default_body

    def has_translation(self, kind: str = "program", locale: str = "en") -> bool:
        from . import i18n

        locale = i18n.normalize(locale)
        family = kind == "family" and self.family_body
        key = f"recognition.family.{self.key}" if family else f"recognition.{self.key}"
        return bool(i18n.STRINGS.get(key, {}).get(locale))

    def to_dict(
        self, body: str = "", customised: bool = False, from_voice: str = "",
        kind: str = "program", locale: str = "en",
    ) -> dict[str, Any]:
        shipped = self.body_for(kind, locale)
        return {
            "key": self.key,
            "label": self.label,
            "streak": self.streak,
            "default_body": shipped,
            "body": body or shipped,
            "customised": customised,
            "from_voice": from_voice or self.default_voice,
            # False when a coach wrote their own: that text is in whatever
            # language they typed it in, and the parent view says so rather
            # than leaving a Spanish-reading parent to wonder why one message
            # arrived in English.
            "translated": bool(customised) is False
                          and self.has_translation(kind, locale),
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
        bodies=(
            "{first_name}, that is your first one logged. The hard part is "
            "starting and you have done it — see you at practice.",
            "First one on the board, {first_name}. Everything after this is "
            "just keeping it going.",
            "{first_name}, you have got one in the bank. That is one more "
            "than most people manage.",
            "That is your name on the list, {first_name}. Nobody starts "
            "twice, so enjoy it.",
            "{first_name}, first session done. The blank page was the hard "
            "part and you have written on it.",
            "You are off the mark, {first_name}. See you at practice.",
            "{first_name}, one down. I like that you did not wait to be told.",
            "Session one, {first_name}. The rest is arithmetic now.",
            "{first_name}, you started. That sounds small and it is not.",
            "First rep of the first session is the one nobody sees, "
            "{first_name}. I saw this one.",
            "{first_name}, that is a beginning. Come and find me at practice.",
            "One in the log, {first_name}. Let us see what you do with it.",
            "{first_name}, that is one more session than yesterday. Simple as that.",
            "Logged, {first_name}. The second one is easier than this one was.",
            "{first_name}, you turned up. Half of this is just that.",
            "One session in, {first_name}. Now it is a question of habit.",
        ),
        family_bodies=(
            "{first_name}, you did the first one. Starting is the hard bit, "
            "and you started.",
            "First one done, {first_name}. I am proud of you for just "
            "beginning it.",
            "{first_name}, that is one. Nobody made you, which is the part "
            "I like.",
            "You started, {first_name}. That is the bit most people skip.",
            "{first_name}, first session in the bag. Well done you.",
            "One down, {first_name}. I noticed, and I am glad.",
        ),
    ),
    Milestone(
        key="streak_3",
        label="Three days in a row",
        streak=3,
        bodies=(
            "{first_name}, three days running. That is how a habit starts, "
            "and I noticed.",
            "Three in a row, {first_name}. Two is a coincidence; three is a "
            "decision.",
            "{first_name}, that is three straight. The hard bit is day two "
            "and you are past it.",
            "Three days, {first_name}. Something is starting here.",
            "{first_name}, three on the trot. Keep the chain going.",
            "That is three, {first_name}. Habits are built in threes.",
            "{first_name}, day three. Most people stop at one — you did not.",
            "Three days deep, {first_name}. This is the part that counts.",
            "{first_name}, three in three. That is a pattern, not luck.",
            "Third day running, {first_name}. I am watching this one.",
            "{first_name}, three days and no excuses. Good.",
            "Three straight, {first_name}. You are turning up for yourself.",
            "{first_name}, three days without being asked. I noticed that part.",
            "Day three, {first_name}. This is where it starts to stick.",
            "{first_name}, that is three. Small thing, done three times.",
            "Three in a row, {first_name}. Do not break it now.",
        ),
        family_bodies=(
            "Three days running, {first_name}. I noticed, and I am not just "
            "saying that.",
            "{first_name}, that is three days on the bounce. Well done.",
            "Three in a row, {first_name}. You are making it a habit.",
            "{first_name}, three days. Nobody reminded you once.",
            "That is three, {first_name}. I am quietly impressed.",
            "Three days straight, {first_name}. Keep going.",
        ),
    ),
    Milestone(
        key="streak_5",
        label="Five days in a row",
        streak=5,
        bodies=(
            "Five days in a row, {first_name}. Most people do not get here. "
            "Well done.",
            "{first_name}, that is five. A working week of turning up.",
            "Five straight, {first_name}. You are past where most stop.",
            "{first_name}, five days. This is no longer a good week — it is "
            "how you train.",
            "That is five in five, {first_name}. Quietly excellent.",
            "{first_name}, five on the trot. The chain is getting hard to "
            "break now.",
            "Five days running, {first_name}. That is discipline, not mood.",
            "{first_name}, day five. You have made this ordinary, which is "
            "the whole trick.",
            "Five in a row, {first_name}. I would not have to ask you twice.",
            "{first_name}, five straight days. That shows up on a field.",
            "Five days, {first_name}. Nobody made you do a single one.",
            "{first_name}, that is five. The habit has teeth now.",
            "Five days, {first_name}. You have gone past the interesting bit "
            "and into the useful bit.",
            "{first_name}, five in a row. That is a proper week's work.",
            "Five straight, {first_name}. Nobody had to ask.",
            "{first_name}, day five. Whatever this is, keep it.",
        ),
        family_bodies=(
            "Five days, {first_name}. You did that on your own and I am "
            "proud of you.",
            "{first_name}, five in a row. That is a real run.",
            "Five days straight, {first_name}. I have noticed every one.",
            "{first_name}, that is five. You are making it look normal.",
            "Five on the trot, {first_name}. Well done, love.",
            "{first_name}, five days and counting. Keep it up.",
        ),
    ),
    Milestone(
        key="streak_10",
        label="Ten days in a row",
        streak=10,
        bodies=(
            "{first_name}, ten days straight. That is real work and it will "
            "show up on the field. Proud of you.",
            "Ten in a row, {first_name}. Double figures, and none of them "
            "handed to you.",
            "{first_name}, that is ten days. You have stopped needing a "
            "reason.",
            "Ten straight, {first_name}. This is the bit that separates "
            "players.",
            "{first_name}, day ten. Whatever you are doing, keep doing it.",
            "Ten days running, {first_name}. That is not a streak any more, "
            "it is a standard.",
            "{first_name}, ten on the bounce. I have coached a long time and "
            "this is not common.",
            "That is ten, {first_name}. Your teammates will notice before "
            "you do.",
            "{first_name}, ten days in a row. Somebody is getting better.",
            "Ten in ten, {first_name}. The season will pay you back for it.",
            "{first_name}, ten straight days. That is the work nobody sees.",
            "Ten days, {first_name}. Very few people get this far.",
            "{first_name}, ten days unbroken. That is a decision repeated ten times.",
            "Ten straight, {first_name}. I would back you in a hard week.",
            "{first_name}, that is ten in a row. The work is doing its job now.",
            "Ten days, {first_name}. You have made it boring, which is perfect.",
        ),
        family_bodies=(
            "Ten days straight, {first_name}. Nobody made you do any of "
            "them. That is the part that counts.",
            "{first_name}, ten in a row. I do not think you realise how good "
            "that is.",
            "Ten days, {first_name}. You have kept a promise to yourself.",
            "{first_name}, that is ten. I am really proud of you.",
            "Ten on the trot, {first_name}. Nobody nagged you once.",
            "{first_name}, ten days running. That takes something.",
        ),
    ),
    Milestone(
        key="streak_30",
        label="Thirty days in a row",
        streak=30,
        bodies=(
            "Thirty days, {first_name}. A month of turning up when nobody "
            "made you. That is the thing that separates players.",
            "{first_name}, a month straight. That is not motivation any "
            "more, it is character.",
            "Thirty in a row, {first_name}. Whole month. No days off "
            "borrowed from anybody.",
            "{first_name}, thirty days. Most athletes never string together "
            "half of that.",
            "A month unbroken, {first_name}. You have changed what normal "
            "looks like for you.",
            "{first_name}, thirty straight. I will be using you as the "
            "example, if that is alright.",
            "Thirty days, {first_name}. This is the kind of thing that "
            "shows up two seasons later.",
            "{first_name}, a full month. That is rarer than any single "
            "good performance.",
        ),
        family_bodies=(
            "A whole month, {first_name}. Thirty days of choosing to. I hope "
            "you are as pleased with that as I am.",
            "{first_name}, thirty days. I have watched every one of them.",
            "A month straight, {first_name}. That is something to be proud of.",
            "{first_name}, thirty in a row. You did that yourself.",
            "Thirty days, {first_name}. I am not sure I could have done it.",
            "{first_name}, a whole month. Extraordinary, quietly.",
        ),
    ),
    Milestone(
        key="streak_100",
        label="A hundred days in a row",
        streak=100,
        bodies=(
            "{first_name} — one hundred days. I am not sure what to say "
            "except that I have coached a long time and this is rare.",
            "One hundred, {first_name}. Three months and change without "
            "missing. I have not seen many of those.",
            "{first_name}, a hundred days in a row. That is a season of "
            "somebody else's career.",
            "A hundred straight, {first_name}. Whatever happens on the "
            "field, you have already proved something.",
            "{first_name} — one hundred. I would like to shake your hand.",
            "A hundred days, {first_name}. That is not talent. That is much "
            "harder to come by than talent.",
        ),
        family_bodies=(
            "One hundred days, {first_name}. I do not really have words for "
            "it. Well done.",
            "{first_name}, a hundred days. I am so proud I could burst.",
            "A hundred in a row, {first_name}. Nobody in this house made you "
            "do a single one.",
            "{first_name} — one hundred days. That is remarkable and you "
            "should know it.",
            "A hundred straight, {first_name}. I will remember this one.",
            "{first_name}, one hundred. Extraordinary.",
        ),
    ),
)


BY_KEY = {m.key: m for m in MILESTONES}

#: Streak milestones, longest first, so the biggest one an athlete just
#: crossed is the one they hear about rather than all of them at once.
STREAK_MILESTONES = tuple(
    sorted((m for m in MILESTONES if m.streak), key=lambda m: -m.streak)
)


#: How long a wording stays "spent" for the rest of the squad.
#:
#: A month, because that is the span over which two families actually compare
#: notes -- at a tournament, in a group chat, on the drive home. Inside it, no
#: two athletes in a program get the same sentence for the same milestone.
WINDOW_DAYS = 31

#: Why a repeat happened, when one had to.
NO_COLLISION = ""
SQUAD_COLLISION = "squad"    # more athletes than wordings, so one had to repeat
REPEAT_COLLISION = "repeat"  # this athlete has now had every wording there is


def pick_variant(
    *,
    pool_size: int,
    athlete_id: int,
    used_by_athlete: set[int],
    used_recently: set[int],
) -> tuple[int, str]:
    """Which wording this athlete gets, and whether it had to repeat.

    Two rules, in order. An athlete never gets a sentence they have already
    had for this milestone, and nobody in the program gets a sentence another
    athlete has had inside the window. The first matters to the child; the
    second matters because the value of "coach noticed" survives exactly as
    long as it takes two of them to hold their phones side by side.

    The scan starts at an offset derived from the athlete rather than at zero,
    so two athletes crossing the same milestone on the same morning with no
    history between them still get different words. Deterministic, not random:
    the same athlete in the same state always gets the same sentence, which is
    what makes this testable and a preview honest.

    Returns the index and a collision reason, empty when neither rule bent.
    A caller that gets a reason should tell the coach rather than quietly
    sending a duplicate -- the fix is more wordings, and only they can write
    them.
    """
    if pool_size <= 0:
        return 0, NO_COLLISION
    order = [(athlete_id + i) % pool_size for i in range(pool_size)]

    for i in order:
        if i not in used_by_athlete and i not in used_recently:
            return i, NO_COLLISION
    # More athletes than wordings. Somebody has to hear an echo, and it should
    # at least be a sentence this particular athlete has not had before.
    for i in order:
        if i not in used_by_athlete:
            return i, SQUAD_COLLISION
    # This athlete has had all of them. Give back the one longest ago.
    return order[0], REPEAT_COLLISION


def variants(body: str) -> tuple[str, ...]:
    """A coach's template split into the wordings it contains.

    Blank-line separated, so the existing box takes several without needing a
    new control: one message per paragraph. A coach who types one paragraph
    gets exactly what they typed, every time, which is their right -- and the
    coverage figure beside the box tells them what that costs.
    """
    blocks = [b.strip() for b in body.replace("\r\n", "\n").split("\n\n")]
    return tuple(b for b in blocks if b)


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
