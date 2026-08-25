"""Soreness and injury reporting, built so that telling the truth is free.

This is the most sensitive data in the product: health information about
children. Three failure modes decide the whole design, and two of them are not
privacy failures at all.

**A kid who loses something by reporting pain will stop reporting pain.** If a
check-in costs a streak, an XP total, or a place on a board, athletes learn
within a fortnight to tick "fine". The data then becomes worse than useless --
it becomes a record that says everyone is healthy. So a wellness check-in
protects the streak exactly as a recovery day does, awards nothing, costs
nothing, and never appears on any leaderboard. That is not generosity; it is
the only way the numbers mean anything.

**A tool that reads like a diagnosis will be used as one.** Nothing here names
a condition. There is no "tendinitis", no "probable strain", no severity score
out of ten that a parent can search. Every output is either a thing to do
(stop, rest that area, tell an adult) or a thing to notice. Tests enforce the
vocabulary, because the pressure to write "looks like tendonitis" is real and
one commit away.

**A coach who can read a child's free-text note is a coach reading a child's
diary.** Coaches get what changes a training decision: which area, how bad in
bands, how long, which way it is going. The note the athlete writes goes to
them and their guardian, and to nobody else. The app says so on the form, so
the kid knows before they type.

Head and neck are deliberately not on the same ladder as everything else. Any
report there stops training outright and escalates to an adult, at any
severity, with no gradations and no algorithm -- because the failure mode of
being wrong about a head injury in a twelve-year-old is not symmetrical with
the failure mode of an unnecessary rest day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .drills.base import Tissue

#: How long a report stays open before it is treated as stale rather than
#: ongoing. A kid who got better and forgot to close it should not be blocked
#: from training forever.
STALE_AFTER_DAYS = 10

#: Health data about a minor is not kept indefinitely. Resolved reports older
#: than this are purged by `purge_old`, which runs from the same cron that
#: sends notifications.
RETENTION_DAYS = 400


class Severity:
    """Words, not a number out of ten.

    A ten-point pain scale invites a twelve-year-old to compare their 6 with a
    teammate's 8, and invites an adult to treat the number as clinical. These
    four are phrased by what the athlete can still do, which is both easier to
    answer honestly and the thing that actually decides whether they train.
    """

    FINE = "fine"
    NIGGLE = "niggle"
    SORE = "sore"
    HURTS = "hurts"

    ORDER = (FINE, NIGGLE, SORE, HURTS)
    PROMPTS = {
        FINE: "All good",
        NIGGLE: "I notice it, but it doesn't stop me",
        SORE: "It changes how I move",
        HURTS: "I can't do it properly",
    }

    @staticmethod
    def rank(value: str) -> int:
        try:
            return Severity.ORDER.index(value)
        except ValueError:
            return 0


@dataclass(frozen=True)
class Area:
    key: str
    label: str
    #: Which drill loads this area carries. Used to decide what to hold back.
    tissues: tuple[Tissue, ...]
    #: Head and neck. Any report stops everything and goes to an adult.
    urgent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "urgent": self.urgent,
            "tissues": [t.value for t in self.tissues],
        }


AREAS: tuple[Area, ...] = (
    Area("head", "Head", (), urgent=True),
    Area("neck", "Neck", (Tissue.UPPER_BODY,), urgent=True),
    Area("shoulder", "Shoulder", (Tissue.THROWING, Tissue.UPPER_BODY)),
    Area("elbow", "Elbow", (Tissue.THROWING, Tissue.UPPER_BODY)),
    Area("wrist", "Wrist or hand", (Tissue.THROWING, Tissue.UPPER_BODY)),
    Area("chest", "Chest", (Tissue.UPPER_BODY, Tissue.CORE)),
    Area("back", "Back", (Tissue.CORE, Tissue.WHOLE_BODY)),
    Area("abdomen", "Stomach", (Tissue.CORE,)),
    Area("hip", "Hip", (Tissue.LOWER_BODY,)),
    Area("groin", "Groin", (Tissue.LOWER_BODY,)),
    Area("thigh", "Thigh or hamstring", (Tissue.LOWER_BODY,)),
    Area("knee", "Knee", (Tissue.LOWER_BODY,)),
    Area("shin", "Shin or calf", (Tissue.LOWER_BODY,)),
    Area("ankle", "Ankle", (Tissue.LOWER_BODY,)),
    Area("foot", "Foot", (Tissue.LOWER_BODY,)),
)

AREAS_BY_KEY = {a.key: a for a in AREAS}
SIDES = ("left", "right", "both", "")

#: Things that mean "an adult should look at this", regardless of how the
#: athlete rated the severity. Phrased as the athlete would notice them, not
#: as a clinician would record them.
FLAGS = {
    "at_rest": "It hurts even when I'm sitting still",
    "at_night": "It wakes me up or hurts at night",
    "swelling": "It's puffy or swollen",
    "giving_way": "It gives way, locks, or catches",
    "numbness": "Pins and needles, or it feels numb",
    "cant_weight": "I can't put weight on it",
}


class Action:
    """What the app is asking the athlete to do. Never what it thinks it is."""

    MONITOR = "monitor"
    EASE_OFF = "ease_off"
    TELL_SOMEONE = "tell_someone"
    STOP = "stop"

    ORDER = (MONITOR, EASE_OFF, TELL_SOMEONE, STOP)

    @staticmethod
    def rank(value: str) -> int:
        try:
            return Action.ORDER.index(value)
        except ValueError:
            return 0


@dataclass
class Report:
    id: int
    athlete_id: int
    area: Area
    side: str
    severity: str
    started_on: date
    reported_on: date
    flags: tuple[str, ...] = ()
    note: str = ""
    resolved_on: date | None = None
    #: Severity of the previous open report for the same area, when there was
    #: one. Direction of travel matters more than any single reading.
    previous: str | None = None

    @property
    def days_running(self) -> int:
        return max(1, (self.reported_on - self.started_on).days + 1)

    @property
    def worsening(self) -> bool:
        return (
            self.previous is not None
            and Severity.rank(self.severity) > Severity.rank(self.previous)
        )

    def to_dict(self, include_note: bool = True) -> dict[str, Any]:
        out = {
            "id": self.id,
            "area": self.area.key,
            "area_label": self.area.label,
            "side": self.side,
            "severity": self.severity,
            "started_on": self.started_on.isoformat(),
            "reported_on": self.reported_on.isoformat(),
            "days_running": self.days_running,
            "worsening": self.worsening,
            "flags": [FLAGS[f] for f in self.flags if f in FLAGS],
            "flag_keys": list(self.flags),
            "resolved_on": self.resolved_on.isoformat() if self.resolved_on else None,
        }
        # The note is the athlete's, and the coach view passes include_note
        # False. Omitting the key entirely rather than blanking it means a
        # client cannot accidentally render an empty box where a private
        # thing used to be and invite someone to ask what it said.
        if include_note:
            out["note"] = self.note
        return out


@dataclass
class Assessment:
    """What to do about one report. Deliberately not what it is."""

    action: str
    headline: str
    detail: str
    blocked_tissues: tuple[Tissue, ...] = ()
    tell_guardian: bool = False
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "headline": self.headline,
            "detail": self.detail,
            "blocked_tissues": [t.value for t in self.blocked_tissues],
            "tell_guardian": self.tell_guardian,
            "reasons": list(self.reasons),
        }


def assess(report: Report) -> Assessment:
    """Decide what to ask of an athlete who has reported something.

    Reads in order of seriousness and stops at the first thing that matters.
    Every branch produces an instruction and a reason, and none of them names
    a condition.
    """
    if report.area.urgent:
        # No ladder here on purpose. Being wrong about a head knock in a
        # twelve-year-old is not symmetrical with an unnecessary rest day, so
        # there is no severity at which this reads as "keep going".
        return Assessment(
            action=Action.STOP,
            headline="Stop for today and find an adult now",
            detail=(
                f"Anything in your {report.area.label.lower()} is worth an adult "
                "looking at straight away — today, not tomorrow. Don't train, "
                "don't play, and tell your parent or your coach now. If you took "
                "a knock to the head and feel dizzy, sick, foggy or your vision "
                "is off, that is a hospital question, not an app question."
            ),
            blocked_tissues=tuple(Tissue),
            tell_guardian=True,
            reasons=(f"{report.area.label} reported",),
        )

    reasons: list[str] = []
    if report.flags:
        reasons.extend(FLAGS[f] for f in report.flags if f in FLAGS)
    if report.severity == Severity.HURTS:
        reasons.append("can't do it properly")
    if report.worsening:
        reasons.append(f"worse than last time ({report.previous} → {report.severity})")
    if report.days_running >= 7:
        reasons.append(f"going on {report.days_running} days")

    blocked = tuple(report.area.tissues) + (Tissue.WHOLE_BODY,)

    if report.flags or report.severity == Severity.HURTS:
        return Assessment(
            action=Action.TELL_SOMEONE,
            headline="Tell a grown-up about this one today",
            detail=(
                f"Your {report.area.label.lower()} is telling you something and "
                "this app is not the right thing to ask. Talk to your parent or "
                "your coach today, and leave it alone until someone who can "
                "actually look at it has. Nothing you miss this week matters "
                "next to getting this right."
            ),
            blocked_tissues=blocked,
            tell_guardian=True,
            reasons=tuple(reasons),
        )

    if report.severity == Severity.SORE or report.worsening or report.days_running >= 7:
        return Assessment(
            action=Action.EASE_OFF,
            headline=f"Give your {report.area.label.lower()} a couple of days",
            detail=(
                "Anything that loads it is off the list for now — the app will "
                "hide those drills and leave the rest. Your streak is safe "
                "either way. If it is still there in a few days, or it gets "
                "worse, tell someone rather than waiting it out."
            ),
            blocked_tissues=blocked,
            tell_guardian=False,
            reasons=tuple(reasons),
        )

    return Assessment(
        action=Action.MONITOR,
        headline="Noted. Keep an eye on it",
        detail=(
            "A niggle after training is normal and usually settles in a day or "
            "two. Nothing is being held back. Say something if it starts "
            "changing how you move, or if it is still around next week."
        ),
        blocked_tissues=(),
        tell_guardian=False,
        reasons=tuple(reasons),
    )


@dataclass
class Status:
    """Everything currently open for one athlete, and what it adds up to."""

    reports: list[Report] = field(default_factory=list)
    assessments: list[Assessment] = field(default_factory=list)
    checked_in_today: bool = False
    #: Live return-to-play ramps. Typed loosely to keep `rtp` importing this
    #: module rather than the other way round.
    plans: list[Any] = field(default_factory=list)
    today: date | None = None

    @property
    def action(self) -> str:
        if not self.assessments:
            return Action.MONITOR
        return max((a.action for a in self.assessments), key=Action.rank)

    @property
    def blocked_tissues(self) -> set[Tissue]:
        out: set[Tissue] = set()
        for assessment in self.assessments:
            out.update(assessment.blocked_tissues)
        # A ramp holds things back too, and for a different reason: not
        # "this hurts now" but "this is not back to full load yet".
        for plan in self.plans:
            area = AREAS_BY_KEY.get(plan.area)
            out.update(plan.blocked_tissues(tuple(area.tissues) if area else ()))
        return out

    def to_dict(self, include_notes: bool = True) -> dict[str, Any]:
        today = self.today or datetime.now(timezone.utc).date()
        return {
            "action": self.action,
            "checked_in_today": self.checked_in_today,
            "open_reports": [r.to_dict(include_notes) for r in self.reports],
            "guidance": [a.to_dict() for a in self.assessments],
            "blocked_tissues": sorted(t.value for t in self.blocked_tissues),
            "plans": [p.to_dict(today) for p in self.plans],
        }


def drill_availability(
    status: Status, drill_key: str, tissue: Tissue
) -> dict[str, Any]:
    """Whether a drill is offered right now, and what to say if it is not.

    Held back rather than forbidden. The athlete can still see the drill and
    can still record one if they insist -- the app is not their physio and
    should not pretend it can stop them -- but it does not sit on the home
    screen inviting them to load a sore knee.
    """
    if tissue not in status.blocked_tissues:
        return {"drill_key": drill_key, "available": True, "reason": ""}

    areas = sorted({
        report.area.label
        for report, assessment in zip(status.reports, status.assessments)
        if tissue in assessment.blocked_tissues
    })
    if areas:
        named = areas[0].lower() if len(areas) == 1 else " and ".join(a.lower() for a in areas)
        return {
            "drill_key": drill_key,
            "available": False,
            "reason": f"Resting your {named}. This one loads it.",
        }

    # Held by a ramp rather than by pain. Worth saying differently: "resting
    # your knee" is confusing to a kid whose knee stopped hurting last week.
    for plan in status.plans:
        area = AREAS_BY_KEY.get(plan.area)
        if tissue in plan.blocked_tissues(tuple(area.tissues) if area else ()):
            return {
                "drill_key": drill_key,
                "available": False,
                "reason": f"Not at this stage of your {plan.area_label.lower()} ramp yet.",
            }
    return {"drill_key": drill_key, "available": False, "reason": "Held back for now."}


def purge_cutoff(today: date | None = None) -> str:
    """The date before which resolved reports are deleted, as an ISO string."""
    today = today or datetime.now(timezone.utc).date()
    return (today - timedelta(days=RETENTION_DAYS)).isoformat()
