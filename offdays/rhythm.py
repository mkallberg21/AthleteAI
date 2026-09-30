"""What the sound of a wall-ball session says about its rhythm.

A wall-ball drill counted by ear hands the server one timestamp per impact,
accurate to about ten milliseconds, with pose deciding which hand threw it.
That is a much better clock than pose ever was: a pose-timed rep lands on
whichever video frame crossed the threshold, so every gap carries a frame of
jitter either side and the small differences below would be lost in it. So
this report only runs when the reps were heard, and says nothing otherwise.

Four things come out of the gaps between impacts, and nothing else is needed
-- no new column, no new field on the rep payload.

**Which hand is slower.** A gap belongs to the hand of the rep that ENDS it:
the time from the last impact to this one is the time this hand took to catch,
cradle and throw. An off-hand that is working harder shows up here long before
it shows up as fewer reps.

**Whether the rhythm is steady.** The same trimmed coefficient of variation
the form scorer uses on cycles, so "steady" means the same thing in both.

**Whether it faded.** The last third against the first third. Only on a set
long enough for thirds to mean anything.

**Where it stopped.** A dropped ball, a ground-ball pickup or a breather is a
gap far longer than the rest. Those are counted and shown, and taken out of
every other number -- one chase after a bad bounce is not the off-hand being
slow, and folding it in would say that it was.

The rules are the ones the sweep and footwork reports follow. **Counted, never
scored**: nothing here changes XP or integrity. **Said plainly to the
athlete**: the note goes on their own screen, one sentence, and it never
shames -- an off-hand is slower because it is the off-hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any

try:  # The same spread the form scorer uses, so "steady" means one thing.
    from .quality import _spread
except Exception:  # pragma: no cover - only if quality.py moves
    import statistics as _stats

    def _spread(values: list[float]) -> float:
        ordered = sorted(values)
        if len(ordered) >= 5:
            cut = int(len(ordered) * 0.10)
            ordered = ordered[cut: len(ordered) - cut] or ordered
        if len(ordered) < 2:
            return 0.0
        centre = _stats.median(ordered)
        return 0.0 if centre == 0 else _stats.pstdev(ordered) / abs(centre)


#: Below this many heard reps the medians are noise and nothing is claimed.
MIN_REPS = 12

#: Share of reps that must have been heard rather than seen. A handful of pose
#: reps (the mic dropped out for a second) do not spoil the clock; a session
#: that was mostly pose-timed has a frame of jitter on every gap and the
#: differences this report looks for are smaller than that.
MIN_SOUND_SHARE = 0.80

#: A gap longer than this multiple of the session's median gap is a stop --
#: a drop, a ground-ball pickup, a rest -- not a slow rep. Two-and-a-bit
#: cycles is long enough that a merely sloppy catch never reaches it.
BREAK_FACTOR = 2.2

#: Each side needs at least this many (non-break) gaps before its median is
#: compared with the other's.
MIN_SIDE_GAPS = 5

#: The slower hand has to take this much longer per rep before it is worth
#: saying. Every athlete has some difference and always will.
SLOWER_HAND = 1.15

#: Fewer reps than this and thirds are too short to compare.
FADE_MIN_REPS = 18

#: Last third this much slower than the first third reads as fading.
FADE = 1.15

#: A trimmed coefficient of variation under this is a steady rhythm. Wall
#: ball at a real rebounder sits around 0.05-0.10; a scrambling set is 0.25+.
STEADY_CV = 0.15

#: More stops than this in one set is worth mentioning on its own.
MANY_BREAKS = 3

#: The UI strip is capped so a ten-minute session does not ship thousands of
#: points to draw a bar a few hundred pixels wide.
STRIP_CAP = 400

#: Share of reps that must carry a heard catch before release time is
#: reported at all. Below it the phone was on the wrong side of the stick to
#: hear catches, and a median of a few would be one lucky rep.
MIN_RELEASE_SHARE = 0.5

#: Each hand needs this many release readings before the two are compared.
MIN_SIDE_RELEASES = 5

#: The slower hand's release has to be this much longer before it is said.
#: Release is the part of the cycle the athlete controls, so it is where an
#: off-hand shows first -- and flight time, which both hands share, is not in
#: the difference.
SLOWER_RELEASE = 1.15

_HAND_CODE = {"left": "L", "right": "R"}


@dataclass
class RhythmReport:
    #: False when the reps were not sound-timed; the store drops the report.
    applicable: bool = False
    reps: int = 0
    #: 'strong_off' when the athlete's dominant hand is known, else 'a_b'
    #: (a = left, b = right as pose saw them), mirroring sweep.py's refusal
    #: to put a label on a side the app does not actually know.
    labels: str = "a_b"
    sides: list[dict[str, Any]] = field(default_factory=list)
    #: Off-hand median over strong-hand median when labels are strong/off;
    #: slower side over faster side otherwise. >1 means that hand is slower.
    pace_ratio: float | None = None
    median_gap_ms: float | None = None
    steadiness_cv: float | None = None
    #: Last-third median gap over first-third. >1 is slowing down.
    fade: float | None = None
    breaks: int = 0
    break_ms_lost: int = 0
    strip: list[list[Any]] = field(default_factory=list)
    break_intervals: list[list[int]] = field(default_factory=list)
    #: Catch-to-next-impact, in ms. Includes the ball's flight to the wall, so
    #: it compares reps and hands within this session and setup -- never one
    #: athlete, wall or phone position with another. None when too few catches
    #: were heard to say anything.
    release_median_ms: float | None = None
    #: Share of reps that carried a heard catch.
    release_coverage: float | None = None
    #: Off-hand release over strong-hand release (or slower over faster when
    #: the sides are unlabelled). >1 means that hand holds on longer.
    release_ratio: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        def r(v: float | None, n: int = 3) -> float | None:
            return None if v is None else round(v, n)

        return {
            "reps": self.reps,
            "labels": self.labels,
            "sides": self.sides,
            "pace_ratio": r(self.pace_ratio),
            "median_gap_ms": r(self.median_gap_ms, 1),
            "steadiness_cv": r(self.steadiness_cv),
            "fade": r(self.fade),
            "breaks": self.breaks,
            "break_ms_lost": self.break_ms_lost,
            "strip": self.strip,
            "break_intervals": self.break_intervals,
            "release_median_ms": r(self.release_median_ms, 1),
            "release_coverage": r(self.release_coverage),
            "release_ratio": r(self.release_ratio),
            "note": self.note,
        }


def _strip(events: list[tuple[int, str]]) -> list[list[Any]]:
    points = [[t, _HAND_CODE.get(h, "-")] for t, h in events]
    n = len(points)
    if n <= STRIP_CAP:
        return points
    # Evenly spaced, always keeping the first and last so the bar spans the
    # whole session.
    step = (n - 1) / (STRIP_CAP - 1)
    return [points[round(i * step)] for i in range(STRIP_CAP)]


def analyze(reps: list[dict[str, Any]], dominant_hand: str | None) -> RhythmReport:
    """Read the rhythm out of a sound-timed session. Never raises."""
    try:
        return _analyze(reps, dominant_hand)
    except Exception:
        return RhythmReport()


def _analyze(reps: list[dict[str, Any]], dominant_hand: str | None) -> RhythmReport:
    report = RhythmReport()
    if not reps:
        return report
    heard = sum(1 for r in reps if r.get("source") == "sound")
    if heard / len(reps) < MIN_SOUND_SHARE:
        return report

    events = sorted(
        (int(r.get("t_ms") or 0), str(r.get("hand") or "none")) for r in reps
    )
    report.applicable = True
    report.reps = len(events)
    report.strip = _strip(events)

    known = dominant_hand in ("left", "right")
    report.labels = "strong_off" if known else "a_b"

    if len(events) < MIN_REPS:
        report.note = (
            "Not enough reps yet to read your rhythm. Keep it going a bit "
            "longer and the app will show you how steady you were."
        )
        return report

    # (gap, hand that ended it, start, end). A zero gap is two readings of
    # one impact, not a rep that took no time.
    gaps = [
        (b[0] - a[0], b[1], a[0], b[0])
        for a, b in zip(events, events[1:])
        if b[0] > a[0]
    ]
    if not gaps:
        return report

    session_median = median(g for g, *_ in gaps)
    limit = BREAK_FACTOR * session_median
    stops = [g for g in gaps if g[0] > limit]
    pace = [g for g in gaps if g[0] <= limit]
    report.breaks = len(stops)
    report.break_ms_lost = int(sum(g - session_median for g, *_ in stops))
    report.break_intervals = [[s, e] for _, _, s, e in stops]

    values = [float(g) for g, *_ in pace]
    report.median_gap_ms = median(values)
    report.steadiness_cv = _spread(values)

    # Per hand. Side order is strong then off when known, else left then
    # right as 'a' then 'b'.
    if known:
        off = "left" if dominant_hand == "right" else "right"
        order = [("strong", dominant_hand), ("off", off)]
    else:
        order = [("a", "left"), ("b", "right")]
    medians: dict[str, float] = {}
    for label, hand in order:
        mine = [float(g) for g, h, *_ in pace if h == hand]
        side_median = median(mine) if mine else None
        report.sides.append({
            "side": label,
            "hand": hand,
            "reps": sum(1 for _, h in events if h == hand),
            "median_gap_ms": None if side_median is None else round(side_median, 1),
        })
        if len(mine) >= MIN_SIDE_GAPS and side_median:
            medians[label] = side_median

    if len(medians) == 2:
        first, second = (medians[order[0][0]], medians[order[1][0]])
        if known:
            report.pace_ratio = second / first
        else:
            report.pace_ratio = max(first, second) / min(first, second)

    if len(events) >= FADE_MIN_REPS and len(values) >= 6:
        third = len(values) // 3
        early, late = median(values[:third]), median(values[-third:])
        if early > 0:
            report.fade = late / early

    _releases(report, reps, order, known)
    report.note = _note(report, known)
    return report


def _releases(
    report: RhythmReport,
    reps: list[dict[str, Any]],
    order: list[tuple[str, str]],
    known: bool,
) -> None:
    """Release time, from the catches the phone heard. Silent if it heard few.

    Per hand, a release belongs to the rep it ends, the same rule the gaps
    follow: the time from catching to the next impact is the time the hand that
    threw it took.
    """
    heard = [
        (int(r["release_ms"]), str(r.get("hand") or "none"))
        for r in reps
        if isinstance(r.get("release_ms"), (int, float)) and r["release_ms"] > 0
    ]
    if not reps:
        return
    report.release_coverage = len(heard) / len(reps)
    if report.release_coverage < MIN_RELEASE_SHARE or len(heard) < MIN_SIDE_RELEASES:
        return
    report.release_median_ms = median(float(ms) for ms, _ in heard)

    medians: dict[str, float] = {}
    for side in report.sides:
        mine = [float(ms) for ms, h in heard if h == side["hand"]]
        side["median_release_ms"] = round(median(mine), 1) if mine else None
        if len(mine) >= MIN_SIDE_RELEASES:
            medians[side["side"]] = median(mine)
    if len(medians) == 2:
        first, second = medians[order[0][0]], medians[order[1][0]]
        if first > 0 and second > 0:
            report.release_ratio = (
                second / first if known else max(first, second) / min(first, second)
            )


def _note(report: RhythmReport, known: bool) -> str:
    # Release first when there is one to speak of: it is the part of the
    # cycle a player controls, and the part coaches mean by "quick hands".
    rel = report.release_ratio
    if rel is not None and rel >= SLOWER_RELEASE:
        pct = round((rel - 1) * 100)
        if known:
            return (
                f"Your off-hand is holding the ball about {pct}% longer before "
                "it lets go. Catch and fire on that side -- the release is "
                "where quick hands come from."
            )
        return (
            f"One hand holds the ball about {pct}% longer before it lets go. "
            "You know which -- catch and fire on that side."
        )
    ratio = report.pace_ratio
    if ratio is not None and ratio >= SLOWER_HAND:
        pct = round((ratio - 1) * 100)
        if known:
            return (
                f"Your off-hand is taking about {pct}% longer per rep than your "
                "strong hand -- that is normal, and it is exactly the gap wall "
                "ball closes if you keep feeding it reps."
            )
        return (
            f"One hand is taking about {pct}% longer per rep than the other. "
            "You know which one that is -- give it the extra reps."
        )
    if ratio is not None and known and ratio <= 1 / SLOWER_HAND:
        return (
            "Your off-hand is actually quicker than your strong hand today -- "
            "make sure the strong side is still catching it clean, not rushing."
        )
    if report.fade is not None and report.fade >= FADE:
        pct = round((report.fade - 1) * 100)
        return (
            f"You slowed down by about {pct}% in the last part of the set. "
            "That is your legs and arms getting tired -- a short rest between "
            "sets keeps every rep sharp."
        )
    if report.breaks > MANY_BREAKS:
        return (
            f"You stopped {report.breaks} times. Slow it down a touch until "
            "it stays clean, then build the speed back."
        )
    if report.steadiness_cv is not None and report.steadiness_cv < STEADY_CV:
        if ratio is not None:
            return (
                "Your rhythm was steady from start to finish and both hands "
                "kept the same pace. That is exactly the sound to aim for."
            )
        return (
            "Your rhythm was steady from start to finish. That is exactly "
            "the sound to aim for."
        )
    return (
        "Your pace moved around a bit this set. Try to hear the same beat "
        "every rep -- steady is faster than rushed."
    )
