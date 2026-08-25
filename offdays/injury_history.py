"""What an athlete's body has already been through, and what that changes.

Prior injury is among the strongest predictors of the next one. An athlete who
ramped back from an ankle in March should not start August on the same
thresholds as a teammate who never has -- but "should start differently" is a
sentence that can be taken in two very different directions, and only one of
them belongs in a product used on children.

**It makes a caution arrive earlier. It never blocks, and it never scores.**
A prior injury lowers the point at which this app raises a question about the
tissue involved. It does not stop an athlete training, does not reduce their
budget, and does not appear as a number anywhere a decision about the child
gets made by somebody else.

**A coach does not get an injury history.** This is the line that matters most
and it is not obvious, so it is worth being explicit: a coach can already see
what an athlete is carrying *now*, because that changes today's session. A
career count of past injuries changes nothing about today's session and would
change quite a lot about a tryout. Making prior injury visible to the people
selecting teams is how a child learns that reporting pain costs them a place,
and this whole subsystem depends on that not being true. Anything derived
here reaches the athlete's own load screen and the return-to-play flow, and
stops there.

**Influence decays, and the record does not last forever.** An ankle sprain
two years ago is history, not a live risk factor, and treating it as one turns
a childhood injury into a permanent mark. Weight fades with time, and the
underlying rows are purged on a bounded horizon like every other health record
here.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import wellness as wellness_mod

#: A completed ramp is kept for two years: long enough to inform the season
#: after the one it happened in, bounded so a nine-year-old's ankle is not
#: still on file when they are nineteen. Open plans are never purged, on the
#: same rule as open reports -- a live plan is about a body that is still
#: recovering.
PLAN_RETENTION_DAYS = 730

#: Recency bands. Prior injury predicts most strongly in the first months
#: after return and fades from there; these are a defensible ordering rather
#: than measured hazard ratios, and the module says so out loud.
RECENT_DAYS = 90
SAME_SEASON_DAYS = 365


@dataclass(frozen=True)
class Weight:
    key: str
    label: str
    #: How much earlier a caution should arrive for this tissue, as a fraction
    #: of the usual threshold. 0.15 means "flag at 85% of the normal point".
    tightening: float


WEIGHTS: tuple[Weight, ...] = (
    Weight("recent", "in the last few months", 0.20),
    Weight("this_year", "earlier this year", 0.10),
    Weight("older", "more than a year ago", 0.0),
)
BY_KEY = {w.key: w for w in WEIGHTS}


def _band(days_ago: int) -> Weight:
    if days_ago <= RECENT_DAYS:
        return BY_KEY["recent"]
    if days_ago <= SAME_SEASON_DAYS:
        return BY_KEY["this_year"]
    return BY_KEY["older"]


@dataclass
class PriorInjury:
    """One thing that happened, in the terms that change training."""

    area: str
    area_label: str
    #: When the ramp finished, or when it started if it never did.
    on: date
    days_ago: int
    completed: bool
    setbacks: int = 0

    @property
    def band(self) -> Weight:
        return _band(self.days_ago)

    @property
    def tissues(self) -> tuple[str, ...]:
        area = wellness_mod.AREAS_BY_KEY.get(self.area)
        return tuple(t.value for t in area.tissues) if area else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "area": self.area,
            "area_label": self.area_label,
            "on": self.on.isoformat(),
            "days_ago": self.days_ago,
            "completed": self.completed,
            "setbacks": self.setbacks,
            "band": self.band.key,
            "when": self.band.label,
        }


@dataclass
class History:
    injuries: list[PriorInjury] = field(default_factory=list)

    def tightening(self) -> dict[str, float]:
        """Per tissue, how much earlier a caution should arrive.

        The worst applicable band wins rather than accumulating: three ankle
        niggles in a year is not three times the risk of one, and a scheme
        that adds them up would eventually tighten a child's thresholds to
        the point of telling them to stop moving.
        """
        out: dict[str, float] = {}
        for injury in self.injuries:
            bump = injury.band.tightening
            # A ramp that had setbacks is the clearest signal in here: the
            # body already said once that it was not ready.
            if injury.setbacks:
                bump = min(0.30, bump + 0.05)
            for tissue in injury.tissues:
                out[tissue] = max(out.get(tissue, 0.0), bump)
        return {k: v for k, v in out.items() if v > 0}

    def note(self) -> str:
        """What the athlete reads on their own load screen. Nobody else."""
        live = [i for i in self.injuries if i.band.tightening > 0]
        if not live:
            return ""
        areas = sorted({i.area_label.lower() for i in live})
        joined = areas[0] if len(areas) == 1 else (
            ", ".join(areas[:-1]) + f" and {areas[-1]}")
        return (
            f"Because of your {joined} {live[0].band.label}, this app asks a "
            "question a bit sooner than it otherwise would. It is not stopping "
            "you doing anything."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "injuries": [i.to_dict() for i in self.injuries],
            "tightening": self.tightening(),
            "note": self.note(),
        }


def for_athlete(
    conn: sqlite3.Connection, athlete_id: int, today: date | None = None
) -> History:
    """Completed ramps, most recent first.

    Read from `return_plans` rather than from every reported niggle: a ramp
    means an adult was involved and the thing was serious enough to need one,
    which is a far better signal than a child saying their leg ached once.
    """
    today = today or datetime.now(timezone.utc).date()
    history = History()

    for row in conn.execute(
        "SELECT area, started_on, completed_on, setbacks FROM return_plans "
        "WHERE athlete_id = ? ORDER BY COALESCE(completed_on, started_on) DESC",
        (athlete_id,),
    ):
        completed = bool(row["completed_on"])
        try:
            on = date.fromisoformat(row["completed_on"] or row["started_on"])
        except (TypeError, ValueError):
            continue
        area = wellness_mod.AREAS_BY_KEY.get(row["area"])
        history.injuries.append(PriorInjury(
            area=row["area"],
            area_label=area.label if area else row["area"],
            on=on,
            days_ago=max(0, (today - on).days),
            completed=completed,
            setbacks=int(row["setbacks"] or 0),
        ))
    return history


def purge_old_plans(conn: sqlite3.Connection, today: date | None = None) -> int:
    """Delete completed ramps past the retention window.

    `purge_old_wellness` has always cleared resolved discomfort reports, but
    return plans were never purged at all -- so the one health record here
    that names a specific injury to a specific child was being kept forever,
    directly against what the wellness module says it does. Open plans stay,
    because an open plan is about a body that is still recovering.
    """
    today = today or datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=PLAN_RETENTION_DAYS)).isoformat()
    with conn:
        removed = conn.execute(
            "DELETE FROM return_plan_events WHERE plan_id IN ("
            "  SELECT id FROM return_plans WHERE completed_on IS NOT NULL "
            "  AND completed_on < ?)",
            (cutoff,),
        ).rowcount
        removed += conn.execute(
            "DELETE FROM return_plans WHERE completed_on IS NOT NULL "
            "AND completed_on < ?",
            (cutoff,),
        ).rowcount
    return removed
