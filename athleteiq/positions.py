"""Canonical positions, and what a position's solo time is actually for.

Three problems sit between a `position` column and a useful benchmark, and
this module exists because the first two are usually skipped:

1. **The column is free text.** A coach importing a roster types "Middie",
   "midfield", "MF", "M" and "Mid" across five rows of the same spreadsheet.
   Exact-match SQL groups none of them together, so a position filter looks
   implemented and silently matches nobody. Everything here normalises first.

2. **A team does not have eight goalies.** Position benchmarks that need a
   full peer group only work at program scale, which makes them useless to
   the single team that just signed up. So peers widen in steps -- position,
   then position family, then simply "athletes your age" -- and the answer
   says which step it settled on rather than quietly comparing a goalie to
   a squad of midfielders.

3. **Comparison is the least useful half.** What a defender should be doing
   with a driveway hour does not depend on how many other defenders logged
   sessions this week. The `emphasis` mix below is real position guidance
   that works with a peer group of zero, on day one.

Everything here is expressed as a **share of solo time**, never as an amount.
The weekly budget in `benchmarks.py` decides how long an athlete trains; this
module only ever has an opinion about how that time is divided. A position
suggestion that reads "and also do these" would quietly undo the budget, so
suggestions are phrased as swaps and tested for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Peer families, used when a position alone is too small to compare within.
# LSM sits with the defenders rather than the midfielders: they are defenders
# who run, and the stick work they practise is a defender's.
GROUP_LABELS = {
    "offense": "attackers and midfielders",
    "defense": "defenders",
    "specialist": "face-off specialists",
    "goalie": "goalies",
    "field": "field players",
}


@dataclass(frozen=True)
class Position:
    key: str
    label: str
    sport: str
    group: str
    aliases: tuple[str, ...]
    #: Drill key -> share of solo training time. Sums to 1.0.
    emphasis: dict[str, float]
    #: One line an athlete can act on, about what their solo time is for.
    focus: str
    #: Set where appending "s" to the label is wrong, which is most of them:
    #: a squad of Midfields is a squad of midfielders.
    plural_label: str = ""
    #: Whether weak-hand parity is a goal for this position. For a goalie it
    #: is not: their stick work is two-handed save mechanics and an outlet
    #: pass, so scoring them on left/right balance measures nothing they are
    #: trying to build.
    offhand_matters: bool = True

    @property
    def plural(self) -> str:
        if self.plural_label:
            return self.plural_label
        return f"{self.label}s" if not self.label.endswith("s") else self.label

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "sport": self.sport,
            "group": self.group,
            "focus": self.focus,
            "plural": self.plural,
            "emphasis": dict(self.emphasis),
            "offhand_matters": self.offhand_matters,
        }


LACROSSE: tuple[Position, ...] = (
    Position(
        key="attack", label="Attack", sport="lacrosse", group="offense",
        aliases=("attack", "attackman", "attackmen", "attacker", "att", "a",
                 "offense", "offence", "forward"),
        emphasis={
            "lax_wall_ball": 0.35, "lax_quick_stick": 0.20,
            "gen_lateral_bound": 0.12, "gen_squat": 0.10,
            "gen_squat_jump": 0.08, "gen_plank": 0.08, "gen_push_up": 0.07,
        },
        plural_label="attackers",
        focus="Hands and tight-space quickness. Most of your time is stick work.",
    ),
    Position(
        key="midfield", label="Midfield", sport="lacrosse", group="offense",
        aliases=("midfield", "midfielder", "midfielders", "middie", "middy",
                 "mid", "mids", "m", "mf", "midi"),
        emphasis={
            "lax_wall_ball": 0.30, "lax_quick_stick": 0.10,
            "gen_high_knees": 0.12, "gen_squat_jump": 0.10,
            "gen_lateral_bound": 0.10, "gen_squat": 0.10, "gen_burpee": 0.08,
            "gen_plank": 0.05, "gen_push_up": 0.05,
        },
        plural_label="midfielders",
        focus="You cover more ground than anyone. Stick work plus an engine.",
    ),
    Position(
        key="defense", label="Defense", sport="lacrosse", group="defense",
        aliases=("defense", "defence", "defender", "defenders", "defenseman",
                 "defencemen", "defensemen", "d", "def", "close d",
                 "close defense", "close defence", "pole", "dpole", "d pole"),
        emphasis={
            "lax_wall_ball": 0.22, "gen_lateral_bound": 0.18, "gen_squat": 0.15,
            "gen_high_knees": 0.10, "gen_push_up": 0.10, "gen_plank": 0.10,
            "gen_squat_jump": 0.08, "gen_pull_up": 0.07,
        },
        plural_label="defenders",
        focus="Footwork and strength first, but a defender still needs hands.",
    ),
    Position(
        key="lsm", label="Long-Stick Midfield", sport="lacrosse", group="defense",
        aliases=("lsm", "long stick midfield", "long stick midfielder",
                 "long stick middie", "longstick", "long pole", "long pole midfield",
                 "d mid", "dmid", "d midfield", "defensive midfield",
                 "defensive midfielder"),
        emphasis={
            "lax_wall_ball": 0.25, "gen_lateral_bound": 0.15, "gen_squat": 0.12,
            "gen_high_knees": 0.12, "gen_burpee": 0.10, "gen_squat_jump": 0.10,
            "gen_plank": 0.08, "gen_push_up": 0.08,
        },
        plural_label="long-stick midfielders",
        focus="A defender's job at a midfielder's pace. Ground balls and legs.",
    ),
    Position(
        key="fogo", label="Face-Off", sport="lacrosse", group="specialist",
        aliases=("fogo", "faceoff", "face off", "face-off", "faceoff specialist",
                 "fo", "fogos", "draw", "draw specialist", "draw control"),
        emphasis={
            "lax_quick_stick": 0.20, "lax_wall_ball": 0.18,
            "gen_squat_jump": 0.15, "gen_plank": 0.12, "gen_push_up": 0.10,
            "gen_pull_up": 0.10, "gen_burpee": 0.10, "gen_lateral_bound": 0.05,
        },
        plural_label="face-off specialists",
        focus="One explosive move, repeated. Grip, core and a fast first step.",
    ),
    Position(
        key="goalie", label="Goalie", sport="lacrosse", group="goalie",
        aliases=("goalie", "goalies", "goal", "goalkeeper", "goaltender",
                 "keeper", "gk", "g", "netminder", "net"),
        emphasis={
            "lax_quick_stick": 0.28, "lax_wall_ball": 0.18,
            "gen_lateral_bound": 0.18, "gen_plank": 0.12,
            "gen_squat_jump": 0.10, "gen_squat": 0.08, "gen_push_up": 0.06,
        },
        plural_label="goalies",
        focus="Hands, reactions and a hard first step sideways.",
        offhand_matters=False,
    ),
)

#: Used when the sport has no position model, or the athlete has not given one.
#: An even spread rather than a guess -- it should read as "no opinion yet",
#: which is honest, rather than as a recommendation nobody chose.
GENERIC = Position(
    key="general", label="Athlete", sport="general", group="field",
    aliases=(),
    emphasis={
        "gen_squat": 0.15, "gen_push_up": 0.15, "gen_plank": 0.12,
        "gen_lateral_bound": 0.12, "gen_high_knees": 0.12,
        "gen_squat_jump": 0.12, "gen_burpee": 0.12, "gen_sit_up": 0.10,
    },
    focus="General athleticism: move well, in every direction.",
)

BY_SPORT: dict[str, tuple[Position, ...]] = {"lacrosse": LACROSSE}


def for_sport(sport: str | None) -> tuple[Position, ...]:
    """Positions modelled for a sport, or none if it has no model yet.

    Returning empty rather than a plausible-looking guess matters: a soccer
    program should get honest silence on positions, not lacrosse emphasis
    with the labels changed.
    """
    return BY_SPORT.get((sport or "").strip().lower(), ())


def _clean(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Handles the shapes rosters actually contain: "Middie", "MID-FIELD",
    "Attack ", "D-Pole", "Goalie (JV)".
    """
    text = re.sub(r"\([^)]*\)", " ", (raw or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


#: Strings that mean "no position given", in cleaned form. Checked before
#: anything else, because some of them are actively dangerous: "N/A" splits on
#: the slash into ["N", "A"], and "A" is a perfectly good alias for Attack. A
#: roster that says it does not know must not be read as saying "attacker".
PLACEHOLDERS = frozenset({
    "n a", "na", "none", "no position", "not assigned", "unassigned",
    "tbd", "tba", "tbc", "unknown", "undecided", "pending", "x",
    "various", "multi", "multiple", "any", "all", "other",
})

_ALIAS_CACHE: dict[str, dict[str, Position]] = {}


def _alias_map(sport: str) -> dict[str, Position]:
    if sport not in _ALIAS_CACHE:
        table: dict[str, Position] = {}
        for pos in for_sport(sport):
            for alias in (pos.key, pos.label, *pos.aliases):
                table[_clean(alias)] = pos
        _ALIAS_CACHE[sport] = table
    return _ALIAS_CACHE[sport]


def normalize(raw: str | None, sport: str = "lacrosse") -> Position | None:
    """Free-text position -> canonical position, or None if unrecognised.

    None is a real answer, not a failure to try. A roster row reading
    "TBD" or "?" should widen the peer pool rather than invent a position,
    and a coach should be able to see which rows did not resolve.
    """
    text = _clean(raw or "")
    if not text or text in PLACEHOLDERS:
        return None
    table = _alias_map(sport)

    if text in table:
        return table[text]

    # "attackman/midfield" and "midfield, attack" -- take the first that
    # resolves, since the first listed is conventionally the primary.
    for part in re.split(r" (?:or|and) |/|,", raw or ""):
        cleaned = _clean(part)
        if cleaned and cleaned in table:
            return table[cleaned]

    # Multi-word entries that carry a qualifier the alias list does not
    # know: "starting midfield", "jv goalie", "midfield 2".
    tokens = text.split()
    for token in tokens:
        if token in table and len(token) > 1:
            return table[token]
    # Single letters only when the whole entry is that letter, handled above:
    # "a" in "a team" must not silently become Attack.
    return None


def resolve(raw: str | None, sport: str = "lacrosse") -> Position:
    """Like `normalize`, but always returns something usable.

    Callers that need guidance rather than grouping use this: an athlete
    with no position still deserves a sensible drill mix.
    """
    return normalize(raw, sport) or GENERIC


def group_of(position: Position | None) -> str:
    return position.group if position else "field"


def emphasis_for(position: Position | None) -> dict[str, float]:
    return dict((position or GENERIC).emphasis)


def unrecognised(values: list[str], sport: str = "lacrosse") -> list[str]:
    """Distinct free-text positions that did not resolve, for a coach to fix."""
    seen: dict[str, None] = {}
    for value in values:
        if (value or "").strip() and normalize(value, sport) is None:
            seen.setdefault(value.strip(), None)
    return sorted(seen)
