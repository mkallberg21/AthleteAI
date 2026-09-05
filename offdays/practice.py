"""The ninety seconds before practice starts.

A coach standing on a field with a whistle in one hand and a phone in the
other will not open five tabs. They have time for one card, read once, and
what they need from it is not a report -- it is a short list of decisions they
have to make differently today.

So this is deliberately not a dashboard. It composes the three coach views
that already exist -- squad coverage, load, and who is carrying something --
picks out only what changes a plan, and caps what it shows. A card that lists
everybody is a card nobody reads, and a card nobody reads is worse than no
card, because it looks like diligence.

Three rules shape the output.

Nobody is named twice. An athlete mid-ramp who is also behind on reps appears
once, under the ramp, because the ramp is the decision.

An athlete on a hold or a ramp never appears on the behind-on-work list. That
one is not a formatting nicety: telling a coach to chase a child for missed
reps when the child is injured is precisely the wrong instruction, and it is
the instruction a naive join would produce.

And every line says what to do rather than what is wrong. "Modified work
today" is actionable on a field. "ACWR 1.6" is not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import assignments as assignments_mod
from . import load as load_mod
from . import rtp as rtp_mod
from . import wellness as wellness_mod

#: How many people the card will name before it starts counting instead. Six
#: fits on a phone without scrolling; past that a coach is reading, not
#: glancing, and the whole point was the glance.
MAX_PEOPLE = 6

#: How many names to attach to a coverage line. Two is a reminder; twelve is
#: a list of children who are in trouble, which is not what this is for.
MAX_BEHIND_NAMES = 3


class Kind:
    """Ordered by how much they change what happens in the next hour."""

    HOLD = "hold"        # not training today
    MODIFY = "modify"    # training, but not everything
    WATCH = "watch"      # training normally, worth an eye
    RANK = {HOLD: 3, MODIFY: 2, WATCH: 1}


@dataclass
class Item:
    """One person on the card, and the decision they represent."""

    kind: str
    athlete_id: int
    display_name: str
    line: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "athlete_id": self.athlete_id,
            "display_name": self.display_name,
            "line": self.line,
            "detail": self.detail,
        }


@dataclass
class Coverage:
    """What a squad has and has not got through, for one assignment."""

    assignment_id: int
    title: str
    due_on: str
    done: int
    total: int
    behind: list[str] = field(default_factory=list)
    behind_total: int = 0

    @property
    def complete(self) -> bool:
        return self.done >= self.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "title": self.title,
            "due_on": self.due_on,
            "done": self.done,
            "total": self.total,
            "complete": self.complete,
            "behind": self.behind,
            "behind_total": self.behind_total,
        }


@dataclass
class Briefing:
    team_id: int | None = None
    team_name: str = ""
    roster: int = 0
    people: list[Item] = field(default_factory=list)
    hidden: int = 0
    #: Counts across *everyone*, including those the card had no room to name.
    #: The headline reads from here rather than from `people`, because
    #: counting only the visible ones understates who needs modified work --
    #: and it understates it in the direction of training a hurt child.
    counts: dict[str, int] = field(default_factory=dict)
    coverage: list[Coverage] = field(default_factory=list)

    @property
    def quiet(self) -> bool:
        """Nothing needs a different decision today.

        Worth saying out loud rather than showing an empty card. "Nothing to
        flag" is information; blankness reads as a loading bug.
        """
        return not self.people and all(c.complete for c in self.coverage)

    def headline(self) -> str:
        if self.quiet:
            return "Nothing to flag. Everyone is clear for a normal session."
        parts = []
        for kind, phrase in (
            (Kind.HOLD, "not training"),
            (Kind.MODIFY, "on modified work"),
            (Kind.WATCH, "to keep an eye on"),
        ):
            n = self.counts.get(kind, 0)
            if n:
                parts.append(f"{n} {phrase}")
        return "; ".join(parts) or "A few things to look at."

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "team_name": self.team_name,
            "roster": self.roster,
            "headline": self.headline(),
            "quiet": self.quiet,
            "people": [p.to_dict() for p in self.people],
            "hidden": self.hidden,
            "counts": self.counts,
            "coverage": [c.to_dict() for c in self.coverage],
        }


def _from_return_plan(plan: rtp_mod.Plan, name: str) -> Item:
    """A ramp, in the words of what the coach does about it.

    The area is here because it changes the session -- you cannot modify work
    for an ankle without knowing it is an ankle. Nothing else from the report
    is: severity wording, the athlete's own note, and how it happened are
    theirs and their guardian's, and none of them change a drill.
    """
    if plan.awaiting_clearance:
        return Item(
            kind=Kind.HOLD,
            athlete_id=plan.athlete_id,
            display_name=name,
            line="Not training, waiting on clearance",
            detail=f"{plan.area_label} ramp cannot start until someone signs it off.",
        )
    stage = plan.spec
    return Item(
        kind=Kind.MODIFY,
        athlete_id=plan.athlete_id,
        display_name=name,
        line=f"Modified: {stage.label.lower()}",
        detail=f"{plan.area_label} ramp, stage {rtp_mod.STAGES.index(stage) + 1} "
               f"of {len(rtp_mod.STAGES) - 1}.",
    )


#: How the app's four actions read to somebody running a session. STOP and
#: TELL_SOMEONE both mean not today; the difference between them is who else
#: needs to know, which the wellness screen handles and a field card does not.
_ACTIONS = {
    wellness_mod.Action.STOP: (
        Kind.HOLD, "Not training today",
        "They reported something that needs a day off it.",
    ),
    wellness_mod.Action.TELL_SOMEONE: (
        Kind.HOLD, "Not training, needs a grown-up first",
        "They reported something that should be looked at before they train.",
    ),
    wellness_mod.Action.EASE_OFF: (
        Kind.MODIFY, "Modified work", "",
    ),
    wellness_mod.Action.MONITOR: (
        Kind.WATCH, "Worth asking how it feels",
        "They reported something mild that has not cleared.",
    ),
}

#: Tissue keys in the words a coach would use on a field.
_TISSUE_WORDS = {
    "throwing": "throwing",
    "lower_body": "running and jumping",
    "upper_body": "upper-body work",
    "whole_body": "hard conditioning",
    "core": "core work",
}


def _from_wellness(status, name: str, athlete_id: int) -> Item | None:
    """Something they are carrying that has not become a ramp yet."""
    mapped = _ACTIONS.get(status.action)
    if mapped is None:
        return None
    kind, line, detail = mapped
    if kind == Kind.MODIFY and not detail:
        blocked = ", ".join(sorted(
            _TISSUE_WORDS.get(t.value, t.value) for t in status.blocked_tissues
        ))
        detail = f"Keep them off {blocked}." if blocked else "Ease them off today."
    return Item(kind=kind, athlete_id=athlete_id, display_name=name,
                line=line, detail=detail)


def _from_load(state: load_mod.LoadState, name: str, athlete_id: int) -> Item | None:
    """A load advisory, if it rises to something a coach would act on.

    Only warnings make the card. An informational advisory is real and belongs
    on the load screen, but a card that fires for every one of them stops
    being read within a week, and then the warnings do not land either.
    """
    worst = None
    for advisory in state.advisories:
        if advisory.level == "warning":
            worst = advisory
            break
        if advisory.level == "caution" and worst is None:
            worst = advisory
    if worst is None or worst.level == "info":
        return None
    return Item(
        kind=Kind.WATCH, athlete_id=athlete_id, display_name=name,
        line="Ramping up quickly" if worst.level == "warning" else "Load worth a look",
        detail=worst.message,
    )


def brief(
    store,
    org_id: int,
    team_id: int | None = None,
    *,
    today: date | None = None,
    scope: list[int] | None = None,
) -> Briefing:
    """Build the card for one team.

    Everything here comes from the same functions the full coach screens use.
    A briefing that computed its own version of "behind" would drift from the
    screen the coach opens next, and then neither could be trusted.
    """
    from .leaderboard import coach_roster

    today = today or date.today()
    athletes = coach_roster(store.conn, org_id, team_id, "week", scope=scope)
    briefing = Briefing(team_id=team_id, roster=len(athletes))
    if team_id is not None:
        row = store.conn.execute(
            "SELECT name FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        briefing.team_name = row["name"] if row else ""

    items: list[Item] = []
    # Anyone here is excused from the behind-on-work list below. Chasing an
    # injured child for missed reps is the one output this card must never
    # produce.
    excused: set[int] = set()

    for athlete in athletes:
        athlete_id = athlete["athlete_id"]
        name = athlete["display_name"]
        status = store.wellness_status(athlete_id, today)

        item = None
        if status.plans:
            # The ramp outranks the report it came from -- it is the newer,
            # more specific decision, and it is the one with stages.
            item = _from_return_plan(status.plans[0], name)
        elif status.reports:
            item = _from_wellness(status, name, athlete_id)

        if item is not None:
            excused.add(athlete_id)
        else:
            item = _from_load(store.load_state(athlete_id), name, athlete_id)

        if item is not None:
            items.append(item)

    items.sort(key=lambda i: (-Kind.RANK.get(i.kind, 0), i.display_name))
    briefing.people = items[:MAX_PEOPLE]
    briefing.hidden = max(0, len(items) - MAX_PEOPLE)
    for item in items:
        briefing.counts[item.kind] = briefing.counts.get(item.kind, 0) + 1

    briefing.coverage = _coverage(store, org_id, team_id, excused, today)
    return briefing


def _coverage(
    store, org_id: int, team_id: int | None, excused: set[int], today: date
) -> list[Coverage]:
    """What the squad has got through, per live assignment."""
    out = []
    for assignment in assignments_mod.list_for_org(
        store.conn, org_id, team_id=team_id
    ):
        progress = assignments_mod.compliance(store.conn, assignment)
        applicable = [p for p in progress if p.athlete_id not in excused]
        behind = [p for p in applicable if not p.complete]
        out.append(Coverage(
            assignment_id=assignment.id,
            title=assignment.title,
            due_on=assignment.due_on or "",
            done=sum(1 for p in applicable if p.complete),
            total=len(applicable),
            behind=[p.display_name for p in behind[:MAX_BEHIND_NAMES]],
            behind_total=len(behind),
        ))
    # Soonest due first: the one being handed out at this practice is the one
    # the coach came here to check.
    out.sort(key=lambda c: (c.complete, c.due_on or "9999"))
    return out
