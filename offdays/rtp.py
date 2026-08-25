"""Getting back to training after something has hurt.

The single most important thing in this module is what it refuses to do: **it
never clears anyone**. A graduated return after an injury is a medical
decision, and an app that produces a green tick saying "you are ready" is
actively dangerous no matter how carefully the stages are worded. So clearance
is always a human's, recorded here as a fact with a name and a date attached --
this app stores the sentence "Jordan's guardian recorded that a doctor cleared
them on the 3rd", and never generates it.

What it *is* good for is the part after that decision: a ramp is a schedule,
and schedules are what software does well. Once an adult has said go, the
stages below step the load back up, hold each one for a minimum time, and
require the athlete to say they feel fine before the next one opens.

Two design choices carry most of the weight.

**A setback drops one stage, never back to the start.** The temptation is to
reset the plan when symptoms return, and it is the same mistake as charging a
kid a streak for reporting soreness: if speaking up costs a week, a
thirteen-year-old who wants to play on Saturday will not speak up. Dropping one
stage is enough to be meaningful and cheap enough to be survivable, and the
copy says outright that it is not a punishment.

**Head and neck plans cannot start without a clinician.** Everywhere else the
adult who clears an athlete can be a parent or a coach using their judgement.
For anything that was flagged as urgent, the guardian has to record that a
healthcare professional cleared it -- the app cannot verify that, and does not
pretend to, but requiring someone to type a name and a date makes the step
deliberate rather than a tap on the way to the pitch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .drills.base import Tissue

#: A plan nobody has touched for this long is treated as abandoned rather than
#: live. A kid who got better and drifted off should not be greeted six weeks
#: later by a half-finished ramp they have forgotten the reason for.
STALE_AFTER_DAYS = 45

#: Two setbacks is the point where the ramp itself is not the answer any more
#: and an adult should look again.
SETBACKS_BEFORE_RECLEARANCE = 2


class Clearance:
    """Who has to say yes before the ramp can start."""

    NONE = "none"            # self-managed; the athlete closed it themselves
    ADULT = "adult"          # a parent or coach, using their judgement
    CLINICIAN = "clinician"  # a guardian recording a healthcare professional


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    #: Shortest time this stage can be held, in days. Time is a floor, not a
    #: test -- feeling fine is what actually opens the next one.
    min_days: int
    #: Cap on a single session's length at this stage. None means no cap.
    minutes_cap: int | None
    #: Whether drills loading the injured area are back on the list yet.
    loads_injury: bool
    what: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "min_days": self.min_days,
            "minutes_cap": self.minutes_cap,
            "loads_injury": self.loads_injury,
            "what": self.what,
        }


STAGES: tuple[Stage, ...] = (
    Stage(
        "rest", "Resting", min_days=1, minutes_cap=0, loads_injury=False,
        what="Nothing yet. This stage ends when an adult says it can.",
    ),
    Stage(
        "light", "Moving again", min_days=1, minutes_cap=15, loads_injury=False,
        what=(
            "Easy stuff that leaves the sore bit alone. Some of this happens "
            "away from the app — a walk, a gentle bike — and that counts."
        ),
    ),
    Stage(
        "drills", "Back to drills, easy", min_days=2, minutes_cap=25, loads_injury=True,
        what=(
            "Everything is back on the list, including the drills that load it, "
            "but short and nowhere near flat out."
        ),
    ),
    Stage(
        "full_solo", "Full solo training", min_days=2, minutes_cap=None, loads_injury=True,
        what=(
            "Train the way you normally would on your own. Still no games and "
            "no full-contact practice until you finish this stage."
        ),
    ),
    Stage(
        "released", "Done", min_days=0, minutes_cap=None, loads_injury=True,
        what=(
            "The ramp is finished. Going back to team practice and games is "
            "your coach's call and your parent's, not this app's."
        ),
    ),
)

STAGES_BY_KEY = {s.key: s for s in STAGES}
FIRST_STAGE = STAGES[0]
LAST_STAGE = STAGES[-1]


def next_stage(key: str) -> Stage:
    index = min(len(STAGES) - 1, STAGES.index(STAGES_BY_KEY[key]) + 1)
    return STAGES[index]


def previous_stage(key: str) -> Stage:
    index = max(0, STAGES.index(STAGES_BY_KEY[key]) - 1)
    return STAGES[index]


def required_clearance(area_urgent: bool, action: str) -> str:
    """How serious a sign-off this return needs.

    Keyed off the assessment that was reached rather than the raw severity, so
    the judgement lives in one place: a niggle that gave way already escalated
    to an adult, and it comes back through an adult too.
    """
    if area_urgent:
        return Clearance.CLINICIAN
    if action in ("stop", "tell_someone"):
        return Clearance.ADULT
    return Clearance.NONE


@dataclass
class Plan:
    id: int
    athlete_id: int
    area: str
    area_label: str
    stage: str
    started_on: date
    stage_started_on: date
    clearance: str
    cleared_on: date | None = None
    cleared_by_name: str = ""
    clinician_name: str = ""
    setbacks: int = 0
    completed_on: date | None = None
    #: Days on which the athlete said they felt fine while this plan was live.
    clear_days: tuple[date, ...] = ()

    @property
    def spec(self) -> Stage:
        return STAGES_BY_KEY[self.stage]

    @property
    def active(self) -> bool:
        return self.completed_on is None

    @property
    def awaiting_clearance(self) -> bool:
        return self.clearance != Clearance.NONE and self.cleared_on is None

    def days_at_stage(self, today: date) -> int:
        return max(0, (today - self.stage_started_on).days)

    def blocked_tissues(self, injured: tuple[Tissue, ...]) -> set[Tissue]:
        """What the ramp holds back, on top of anything wellness holds back."""
        if not self.active:
            return set()
        if self.spec.minutes_cap == 0:
            return set(Tissue)
        if not self.spec.loads_injury:
            return set(injured) | {Tissue.WHOLE_BODY}
        return set()

    def to_dict(self, today: date | None = None) -> dict[str, Any]:
        today = today or date.today()
        gate = can_advance(self, today)
        return {
            "id": self.id,
            "area": self.area,
            "area_label": self.area_label,
            "stage": self.stage,
            "stage_label": self.spec.label,
            "stage_what": self.spec.what,
            "stage_index": STAGES.index(self.spec),
            "stage_count": len(STAGES) - 1,
            "minutes_cap": self.spec.minutes_cap,
            "started_on": self.started_on.isoformat(),
            "stage_started_on": self.stage_started_on.isoformat(),
            "days_at_stage": self.days_at_stage(today),
            "clearance": self.clearance,
            "awaiting_clearance": self.awaiting_clearance,
            "cleared_on": self.cleared_on.isoformat() if self.cleared_on else None,
            "cleared_by_name": self.cleared_by_name,
            "clinician_name": self.clinician_name,
            "setbacks": self.setbacks,
            "completed_on": self.completed_on.isoformat() if self.completed_on else None,
            "can_advance": gate["ok"],
            "blocker": gate["reason"],
            "headline": headline(self, today),
        }


def can_advance(plan: Plan, today: date) -> dict[str, Any]:
    """Whether the next stage is open, and what is holding it if not.

    Always returns a reason, because "the button is greyed out" with no
    explanation is how an athlete decides the app is broken and goes back to
    training on their own.
    """
    if not plan.active:
        return {"ok": False, "reason": "This ramp is already finished."}

    if plan.awaiting_clearance:
        if plan.clearance == Clearance.CLINICIAN:
            return {
                "ok": False,
                "reason": (
                    "Waiting on a grown-up to record that a doctor or "
                    "physio has said you can start."
                ),
            }
        return {"ok": False, "reason": "Waiting on your parent or coach to say you can start."}

    held = plan.spec.min_days - plan.days_at_stage(today)
    if held > 0:
        return {
            "ok": False,
            "reason": (
                f"{held} more day{'' if held == 1 else 's'} at this stage. "
                "Time is part of it, not just how you feel."
            ),
        }

    if today not in plan.clear_days:
        return {
            "ok": False,
            "reason": "Tell the app how you feel today first — it takes one tap.",
        }

    return {"ok": True, "reason": ""}


def headline(plan: Plan, today: date) -> str:
    if not plan.active:
        return f"Back to full training after your {plan.area_label.lower()}"
    if plan.awaiting_clearance:
        return f"Waiting to start your {plan.area_label.lower()} ramp"
    return f"Stage {STAGES.index(plan.spec) + 1} of {len(STAGES) - 1}: {plan.spec.label}"


def setback_message(plan: Plan, area_label: str) -> str:
    """What an athlete reads when their symptoms come back mid-ramp.

    Written to be survivable. If speaking up costs a week, a thirteen-year-old
    who wants to play on Saturday will not speak up, and the ramp becomes a
    formality they walk through while hurt.
    """
    base = (
        f"Your {area_label.lower()} spoke up, so you have gone back one stage. "
        "That is not a punishment and it is not starting over — it is the ramp "
        "doing exactly what it is for. Telling us is the right call every time."
    )
    if plan.setbacks >= SETBACKS_BEFORE_RECLEARANCE:
        return (
            f"{base} That is the second time, so a grown-up needs to look at "
            "this again before you carry on."
        )
    return base
