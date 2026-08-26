"""Marking a cued goalie session.

Every other drill in the catalog answers "how many, and how well shaped". A
goalie's actual job is a different question and a rep count cannot reach it:
given a spot somebody else chose, how fast and how accurately do the hands get
there. So this module reads a session the counting machinery has already
processed and extracts the two numbers that matter -- where the hands went, and
how long they took -- against the cue sequence the server derived for itself
from the session nonce.

Three things this deliberately does not do.

It does not produce a mark out of ten. Goalie is the position where a blunt
score does the most damage: it is the one place on the field where every
mistake is public and final, and a child who already knows that does not need
an app agreeing with them. What comes out of here is a *pattern* -- which spot
lags, which side is slower -- because a pattern is something to go and work on
and a grade is only something to feel.

It does not average "we could not see your hands" into "you went to the wrong
place". Those are different facts, one about the phone and one about the
athlete, and blending them would quietly blame the second for the first.

It does not claim to have watched a save. See `LIMITS` below -- the honest
description of this drill is a reaction-and-positioning drill, and every
surface that shows these numbers says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

from . import cues as cue_seq
from .drills.base import CUE_UNREADABLE, DrillSpec

#: What this drill measures and, more importantly, what it does not. Shown to
#: coaches and athletes rather than kept in a docstring, because the gap
#: between "quick hands to the right spot" and "good goalie" is exactly the gap
#: a number on a screen will be assumed to have closed.
LIMITS = (
    "The app calls the spot out loud, so this trains the path to the ball, "
    "not reading a shooter. A real goalie has to know where it is going "
    "before it goes there, and no phone drill can ask that of them.",
    "There is no ball and no shooter. Nothing here is a save percentage, and "
    "it should never be read next to one.",
    "The camera tracks hands, not the stick head, which sits about a foot "
    "above the top hand. 'High' here means the hands got high.",
)

#: Below this share of readable reps the session describes the phone's view
#: rather than the athlete, and the breakdown is withheld.
MIN_READABLE = 0.70

#: A side or band has to be called at least this many times before the two
#: halves are worth comparing to each other.
MIN_PER_HALF = 4

#: ...and a single spot at least this many times before it is named.
MIN_PER_ZONE = 3

#: How much worse one half has to be before it is called out. Set high on
#: purpose: with a dozen cues, small gaps are noise, and sending a kid away to
#: fix a hole that does not exist costs more than saying nothing.
ACCURACY_GAP = 0.25
REACTION_GAP_MS = 150


@dataclass(frozen=True)
class ZoneRow:
    """One spot's record across the session."""

    zone: str
    called: int
    answered: int
    correct: int
    median_ms: int | None

    @property
    def accuracy(self) -> float:
        return self.correct / self.called if self.called else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "called": self.called,
            "answered": self.answered,
            "correct": self.correct,
            "median_ms": self.median_ms,
            "accuracy": round(self.accuracy, 3),
        }


@dataclass
class SaveReport:
    scored: bool = False
    #: Why there is no breakdown, in words an athlete can act on.
    reason: str = ""
    cues: int = 0
    answered: int = 0
    correct: int = 0
    unreadable: int = 0
    median_ms: int | None = None
    quick_share: float = 0.0
    zones: list[ZoneRow] = field(default_factory=list)
    #: The pattern worth working on, or None when nothing stands out.
    weakest: str | None = None
    note: str = ""

    @property
    def accuracy(self) -> float:
        return self.correct / self.cues if self.cues else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scored": self.scored,
            "reason": self.reason,
            "cues": self.cues,
            "answered": self.answered,
            "correct": self.correct,
            "unreadable": self.unreadable,
            "accuracy": round(self.accuracy, 3),
            "median_ms": self.median_ms,
            "quick_share": round(self.quick_share, 3),
            "zones": [z.to_dict() for z in self.zones],
            "weakest": self.weakest,
            "note": self.note,
            "limits": list(LIMITS),
        }


def _band(zone: str) -> str:
    return zone.split("_", 1)[0]


def _side(zone: str) -> str:
    return zone.split("_", 1)[1]


def label(zone: str, top_hand: str | None = None) -> str:
    """The spot in the words a goalie coach uses.

    Geometry names the regions neutrally (`low_centre`); a coach says "five
    hole". And a coach says "stick side", which is not a fixed direction -- it
    is whichever side the top hand is on, so the same region has two names
    depending on who is in the goal. Without a known top hand this falls back
    to plain left and right, which is worse coaching language but is never
    wrong.
    """
    band = {"high": "high", "mid": "hip", "low": "low"}[_band(zone)]
    side = _side(zone)
    if side == "centre":
        return "five hole" if _band(zone) == "low" else f"{band} middle"
    if top_hand in ("left", "right"):
        which = "stick-side" if side == top_hand else "off-stick"
        return f"{which} {band}"
    return f"{side} {band}"


def _rows(
    called: list[str], answers: dict[int, tuple[str, int]], zones: tuple[str, ...]
) -> list[ZoneRow]:
    rows = []
    for zone in zones:
        idxs = [i for i, z in enumerate(called) if z == zone]
        got = [answers[i] for i in idxs if i in answers]
        right = [ms for z, ms in got if z == zone]
        rows.append(ZoneRow(
            zone=zone,
            called=len(idxs),
            answered=len(got),
            correct=len(right),
            # Timed over the reps that reached the right spot. A fast trip to
            # the wrong place is not a fast reaction to this cue, and letting
            # it into the median would make guessing look like quickness.
            median_ms=int(median(right)) if right else None,
        ))
    return rows


def _half(rows: list[ZoneRow], keep) -> tuple[int, int, list[int]]:
    called = correct = 0
    times: list[int] = []
    for row in rows:
        if not keep(row.zone):
            continue
        called += row.called
        correct += row.correct
        if row.median_ms is not None:
            times.extend([row.median_ms] * row.correct)
    return called, correct, times


def _spread(rows: list[ZoneRow], keep, overall: float) -> bool:
    """Whether a group's weakness is a group problem or really one spot.

    A side is only worth calling out as a side when more than one spot on it is
    behind. Otherwise the honest description is the single spot, and saying
    "your whole off-stick side" would send an athlete away to drill three
    corners when two of them were already fine.
    """
    weak = [
        row for row in rows
        if keep(row.zone) and row.called >= 2 and row.accuracy < overall - 0.15
    ]
    return len(weak) >= 2


def _compare(
    rows: list[ZoneRow], overall: float, a_keep, b_keep, a_name: str, b_name: str,
) -> tuple[str, str] | None:
    """Whichever of two halves is behind, if either genuinely is."""
    a_called, a_correct, a_times = _half(rows, a_keep)
    b_called, b_correct, b_times = _half(rows, b_keep)
    if a_called < MIN_PER_HALF or b_called < MIN_PER_HALF:
        return None
    a_acc = a_correct / a_called
    b_acc = b_correct / b_called
    if abs(a_acc - b_acc) >= ACCURACY_GAP:
        behind, ahead = (a_name, b_name) if a_acc < b_acc else (b_name, a_name)
        keep = a_keep if a_acc < b_acc else b_keep
        # One broken spot drags its whole half down far enough to look like a
        # half-wide problem. Hand those to the single-spot path below, which
        # can say something much more useful about them.
        if not _spread(rows, keep, overall):
            return None
        return behind, (
            f"Your hands find {ahead} far more often than {behind}. "
            f"Spend a set going only to {behind} until it feels the same."
        )
    if a_times and b_times:
        a_med, b_med = median(a_times), median(b_times)
        if abs(a_med - b_med) >= REACTION_GAP_MS:
            behind, ahead = (a_name, b_name) if a_med > b_med else (b_name, a_name)
            gap = int(abs(a_med - b_med))
            return behind, (
                f"You get to {ahead} about {gap}ms quicker than {behind}. "
                f"That gap is the hole a shooter looks for."
            )
    return None


def _note(report: SaveReport, rows: list[ZoneRow], top_hand: str | None) -> tuple[str | None, str]:
    """The single most useful thing to say, and the pattern behind it.

    One pattern, not a list. A goalie who is handed four things to fix works on
    none of them, and the weakest one is the only one that changes games.
    """
    overall = report.accuracy
    sided = _compare(
        rows, overall,
        lambda z: _side(z) == "left", lambda z: _side(z) == "right",
        label("mid_left", top_hand).replace(" hip", ""),
        label("mid_right", top_hand).replace(" hip", ""),
    )
    if sided:
        return sided

    banded = _compare(
        rows, overall,
        lambda z: _band(z) == "high", lambda z: _band(z) == "low",
        "high", "low",
    )
    if banded:
        return banded

    named = [r for r in rows if r.called >= MIN_PER_ZONE]
    if named:
        worst = min(named, key=lambda r: (r.accuracy, -(r.median_ms or 0)))
        if worst.accuracy <= report.accuracy - 0.30:
            return worst.zone, (
                f"Everything is solid except {label(worst.zone, top_hand)}. "
                "One spot behind the rest is the easiest thing on this whole "
                "list to fix -- go and drill only that one."
            )

    if report.accuracy >= 0.85:
        return None, (
            "No hole worth naming. Your hands went where they were called, "
            "on both sides and at both heights. Next time set the phone "
            "further back and work on getting there sooner, not straighter."
        )
    return None, (
        "Nothing stands out as a single weak spot yet -- the misses are spread "
        "around. That usually means the ready position, not the reaction. "
        "Start each rep in the same place and see if this tightens up."
    )


def analyze(
    drill: DrillSpec,
    reps: list[dict[str, Any]],
    *,
    nonce: str,
    duration_ms: int,
    top_hand: str | None = None,
) -> SaveReport:
    """Mark a cued session against the sequence the nonce implies.

    The caller never passes the targets in. That is the point: the server
    re-derives them, so the only thing the client gets a say in is where it
    claims the hands went.
    """
    spec = drill.cues
    if spec is None:
        raise ValueError(f"{drill.key} is not a cued drill")

    total = cue_seq.cue_count(duration_ms, spec.lead_in_ms, spec.period_ms)
    called = cue_seq.sequence(nonce, total, spec.zones)
    report = SaveReport(cues=total)

    if total < spec.min_cues:
        report.reason = (
            f"Too short to read. This drill needs about "
            f"{_seconds(spec, spec.min_cues)} seconds of cues before the "
            "spot-by-spot breakdown means anything."
        )
        report.note = report.reason
        return report

    # Attribute each rep to the cue it answers. A rep landing outside every
    # window answers nothing -- warm-up movement, a reset, a fidget -- and is
    # dropped rather than blamed on the nearest cue.
    answers: dict[int, tuple[str, int]] = {}
    unreadable = 0
    for rep in reps:
        t_ms = int(rep.get("t_ms", 0))
        index = (t_ms - spec.lead_in_ms) // spec.period_ms
        if index < 0 or index >= total:
            continue
        delay = t_ms - cue_seq.cue_at(index, spec.lead_in_ms, spec.period_ms)
        if delay < 0 or delay > spec.late_ms:
            continue
        # First response only. Whatever the hands do after arriving is
        # follow-through or a reset, not a second answer to one cue.
        if index in answers:
            continue
        zone = str(rep.get("zone") or CUE_UNREADABLE)
        if zone == CUE_UNREADABLE:
            unreadable += 1
            continue
        answers[index] = (zone, delay)

    report.unreadable = unreadable
    readable = len(answers)
    if readable + unreadable and readable / (readable + unreadable) < MIN_READABLE:
        report.reason = (
            "The camera lost your hands on too many reps to break this down "
            "by spot. Step back so your whole body is in frame, and check "
            "nothing is behind you the same colour as your gloves."
        )
        report.note = report.reason
        return report

    correct = [(i, ms) for i, (z, ms) in answers.items() if z == called[i]]
    report.answered = readable
    report.correct = len(correct)
    times = [ms for _, ms in correct]
    report.median_ms = int(median(times)) if times else None
    report.quick_share = (
        sum(1 for ms in times if ms <= spec.quick_ms) / len(times) if times else 0.0
    )
    report.zones = _rows(called, answers, spec.zones)
    report.scored = True
    report.weakest, report.note = _note(report, report.zones, top_hand)
    return report


def _seconds(spec: Any, cues: int) -> int:
    return round((spec.lead_in_ms + cues * spec.period_ms) / 1000)
