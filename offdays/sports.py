"""What else an athlete plays, and what that means for how hard we push.

The age gate in `benchmarks.py` was a blunt instrument: one number per program,
applied to every athlete in it. It could not tell a fourteen-year-old who plays
basketball in winter and runs track in spring from one who plays lacrosse
eleven months a year and nothing else. Those two children are in genuinely
different situations, and the second one is the situation the research is
actually about.

So this module records the other sports, and two things key off it.

**The specialisation gate moves.** An athlete with real variety already has the
broad athletic base that the delay was protecting, so position guidance can
start earlier for them. An athlete who is single-sport and year-round gets it
later. Both adjustments are bounded, and neither can push position training
below `ABSOLUTE_MIN_AGE` no matter what is recorded.

**The weekly solo budget shrinks.** A kid playing three sports is already
moving plenty; the driveway time this app measures is on top of a week we
cannot see. Treating them the same as a single-sport athlete overstates how
much solo work is left to give.

The specialisation score is shaped after the screening questions used in youth
sports medicine -- has this athlete dropped other sports, is one ranked above
the rest, do they train it more than eight months a year -- but it is answered
from a season picker a twelve-year-old can fill in, not an interview. It is a
routing heuristic for how cautious to be. It is not a diagnosis, and the code
says so where a caller might forget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Position guidance never starts below this age, whatever an athlete's sport
#: mix says. The multi-sport adjustment is a reason to be *less* cautious, not
#: a way to buy out of the floor entirely -- and a nine-year-old who genuinely
#: plays four sports is the last child who needs a position-specific drill mix.
ABSOLUTE_MIN_AGE = 12

SEASONS = ("fall", "winter", "spring", "summer")
MONTHS_PER_SEASON = 3


@dataclass(frozen=True)
class Sport:
    key: str
    label: str
    aliases: tuple[str, ...] = ()
    #: Where it usually falls in a school year. Only a default for the season
    #: picker -- the athlete's own answer always wins, because club and travel
    #: schedules ignore this completely.
    typical_seasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "typical_seasons": list(self.typical_seasons),
        }


CATALOG: tuple[Sport, ...] = (
    Sport("lacrosse", "Lacrosse", ("lax", "boys lacrosse", "girls lacrosse"), ("spring",)),
    Sport("basketball", "Basketball", ("bball", "b ball", "hoops"), ("winter",)),
    Sport("soccer", "Soccer", ("football uk", "futbol"), ("fall", "spring")),
    Sport("football", "Football", ("american football", "tackle football", "flag football"), ("fall",)),
    Sport("baseball", "Baseball", (), ("spring", "summer")),
    Sport("softball", "Softball", (), ("spring", "summer")),
    # Field hockey is a separate entry below; "hockey" alone means ice hockey.
    Sport("hockey", "Hockey", ("ice hockey",), ("winter",)),
    Sport("field_hockey", "Field Hockey", ("field hockey",), ("fall",)),
    Sport("volleyball", "Volleyball", ("vball",), ("fall",)),
    Sport("track", "Track & Field", ("track and field", "track", "athletics"), ("spring",)),
    Sport("cross_country", "Cross Country", ("xc", "cross country"), ("fall",)),
    Sport("swimming", "Swimming", ("swim", "swim team"), ("winter", "summer")),
    Sport("wrestling", "Wrestling", ("wrestle",), ("winter",)),
    Sport("tennis", "Tennis", (), ("spring", "summer")),
    Sport("golf", "Golf", (), ("spring", "summer")),
    Sport("gymnastics", "Gymnastics", ("gym",), ("fall", "winter", "spring", "summer")),
    Sport("cheer", "Cheer", ("cheerleading", "cheerleader", "competitive cheer", "stunt"),
          ("fall", "winter")),
    Sport("diving", "Diving", ("springboard", "platform diving"), ("winter",)),
    Sport("dance", "Dance", ("ballet", "competitive dance"), ("fall", "winter", "spring")),
    Sport("martial_arts", "Martial Arts", ("karate", "judo", "taekwondo", "bjj", "jiu jitsu"),
          ("fall", "winter", "spring", "summer")),
    Sport("climbing", "Climbing", ("rock climbing", "bouldering"), ("fall", "winter", "spring", "summer")),
    Sport("skiing", "Skiing & Snowboarding", ("ski", "snowboard", "snowboarding"), ("winter",)),
    Sport("rugby", "Rugby", (), ("spring",)),
    Sport("rowing", "Rowing", ("crew",), ("fall", "spring")),
    Sport("water_polo", "Water Polo", ("waterpolo",), ("fall",)),
    Sport("ultimate", "Ultimate", ("ultimate frisbee", "frisbee"), ("spring",)),
)

BY_KEY = {s.key: s for s in CATALOG}


def _clean(raw: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", (raw or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ALIASES: dict[str, Sport] = {}
for _sport in CATALOG:
    for _alias in (_sport.key, _sport.label, *_sport.aliases):
        _ALIASES.setdefault(_clean(_alias), _sport)


def normalize(raw: str | None) -> Sport | None:
    """Free-text sport name -> canonical sport, or None.

    Same discipline as positions: a roster or a kid's typing produces "Bball",
    "b-ball", "Basketball (JV)", and a lookup that misses them silently
    undercounts how many sports a child plays -- which here would push them
    toward looking single-sport, the cautious direction but the wrong answer.
    """
    text = _clean(raw or "")
    if not text:
        return None
    if text in _ALIASES:
        return _ALIASES[text]
    for token in text.split():
        if token in _ALIASES and len(token) > 2:
            return _ALIASES[token]
    return None


def clean_seasons(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalise and order a season list, dropping anything unrecognised."""
    given = {(_clean(v)) for v in (values or [])}
    return [s for s in SEASONS if s in given]


@dataclass(frozen=True)
class Participation:
    sport: Sport
    seasons: tuple[str, ...]
    is_primary: bool = False

    @property
    def months(self) -> int:
        return len(self.seasons) * MONTHS_PER_SEASON

    def to_dict(self) -> dict[str, Any]:
        return {
            "sport": self.sport.key,
            "label": self.sport.label,
            "seasons": list(self.seasons),
            "months": self.months,
            "is_primary": self.is_primary,
        }


class Level:
    """How concentrated an athlete's year is on one sport."""

    UNKNOWN = "unknown"   # nothing recorded; behave exactly as before
    LOW = "low"           # real variety across the year
    MODERATE = "moderate"
    HIGH = "high"         # single-sport and close to year-round


@dataclass(frozen=True)
class Profile:
    participations: tuple[Participation, ...]
    level: str
    score: int
    signals: tuple[str, ...]
    primary: Participation | None
    season_coverage: int

    @property
    def known(self) -> bool:
        return bool(self.participations)

    @property
    def sport_count(self) -> int:
        return len(self.participations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sports": [p.to_dict() for p in self.participations],
            "level": self.level,
            "score": self.score,
            "signals": list(self.signals),
            "sport_count": self.sport_count,
            "season_coverage": self.season_coverage,
            "primary": self.primary.sport.key if self.primary else None,
            "known": self.known,
        }


def assess(participations: list[Participation]) -> Profile:
    """Score how single-sport an athlete's year is.

    Shaped after the three screening questions used in youth sports medicine --
    dropped other sports, ranks one above the rest, trains it more than eight
    months a year -- but answered from a season picker rather than an
    interview. Two of the three are proxies, and deliberately conservative
    ones: an athlete we know nothing about scores `UNKNOWN` and is treated
    exactly as the age-only gate treated them.
    """
    items = tuple(participations)
    if not items:
        return Profile((), Level.UNKNOWN, 0, (), None, 0)

    ranked = sorted(items, key=lambda p: (not p.is_primary, -p.months, p.sport.key))
    primary = next((p for p in items if p.is_primary), ranked[0])
    others = [p for p in items if p is not primary]
    coverage = len({season for p in items for season in p.seasons})

    signals: list[str] = []
    score = 0

    if len(items) == 1:
        score += 1
        signals.append("only one sport recorded")

    # "Is one sport ranked above the others?" -- proxied by it taking up at
    # least twice the year of anything else. A single-sport athlete trivially
    # satisfies it, which is the intent.
    biggest_other = max((p.months for p in others), default=0)
    if biggest_other == 0 or primary.months >= 2 * biggest_other:
        score += 1
        signals.append(f"{primary.sport.label} dominates the year")

    if primary.months > 8:
        score += 1
        signals.append(f"{primary.sport.label} runs more than eight months a year")

    if score >= 3:
        level = Level.HIGH
    elif score == 2:
        level = Level.MODERATE
    else:
        level = Level.LOW
    return Profile(items, level, score, tuple(signals), primary, coverage)


#: Years added to (or taken off) the program's specialisation age. Bounded and
#: small: this is a nudge either side of the director's setting, not a second
#: policy that overrides it.
AGE_ADJUSTMENT = {Level.LOW: -2, Level.MODERATE: 0, Level.HIGH: 2, Level.UNKNOWN: 0}

#: Multiplier on the weekly solo-training budget. A kid playing three sports is
#: already moving plenty, and the driveway time this app measures sits on top
#: of a week it cannot see.
BUDGET_SCALE = {Level.LOW: 0.7, Level.MODERATE: 0.85, Level.HIGH: 1.0, Level.UNKNOWN: 1.0}


def effective_min_age(program_min_age: int, profile: Profile) -> int:
    """Where the specialisation line actually falls for this athlete.

    Never below `ABSOLUTE_MIN_AGE`, and never below the program's own setting
    when that setting is the stricter of the two -- a director who turned
    position guidance off entirely does not get it switched back on by an
    athlete filling in a season picker.
    """
    if program_min_age >= 99:
        return program_min_age
    adjusted = program_min_age + AGE_ADJUSTMENT.get(profile.level, 0)
    return max(ABSOLUTE_MIN_AGE, adjusted)


def budget_scale(profile: Profile) -> float:
    return BUDGET_SCALE.get(profile.level, 1.0)


# ---------------------------------------------------------------------------
# What the weaker side is called
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SideWords:
    """The vocabulary a sport uses for its weaker side.

    Underneath, every bilateral drill in the library measures the same two
    numbers: reps on the left and reps on the right. Which of those is the
    hard one is an athlete fact, not a sport fact. But the *word* is a sport
    fact, and getting it wrong is the fastest way to tell a soccer club that
    this is a lacrosse product with the names swapped: no coach has ever asked
    a midfielder about their off-hand.

    So the numbers stay shared and only the noun moves. A club that plays with
    its feet reads "weak foot" on the same column a lacrosse club reads
    "off-hand" on.
    """

    #: "hand" or "foot". The bare noun, for building a sentence.
    noun: str
    #: The column heading a coach scans: "Off-hand", "Weak foot".
    label: str
    #: Mid-sentence, lowercase: "reps on their weaker hand".
    weaker: str
    #: The badge and the goal that mean both sides: "Both Hands", "Both Feet".
    both: str
    #: Mid-sentence in Spanish: "la mano d\u00e9bil" / "el pie d\u00e9bil".
    weaker_es: str = "la mano d\u00e9bil"


_HANDS = SideWords(noun="hand", label="Off-hand", weaker="weaker hand", both="Both Hands")
_FEET = SideWords(noun="foot", label="Weak foot", weaker="weaker foot",
                  both="Both Feet", weaker_es="el pie d\u00e9bil")

#: Sports played with the feet. Everything else defaults to hands, which is
#: the right answer for the ten other sports that ship drills and a safe one
#: for any sport added later: a wrong "off-hand" reads as an odd word, while a
#: wrong "weak foot" on a throwing sport reads as a bug.
FOOT_SPORTS = frozenset({"soccer"})


def side_words(sport: str | None) -> SideWords:
    """The weaker-side vocabulary for a sport, defaulting to hands.

    Takes free text rather than a key, because callers hold whatever is on the
    organizations row, and normalize() is what turns "Futbol" into soccer.
    """
    found = normalize(sport or "")
    key = found.key if found is not None else ""
    return _FEET if key in FOOT_SPORTS else _HANDS
