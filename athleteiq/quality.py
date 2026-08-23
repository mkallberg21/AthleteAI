"""Form quality analysis.

Counting reps is the easy half of the pose stream. This module reads the half
that a coach cannot get from a stopwatch and a clipboard: whether the reps were
well executed, whether they *stayed* well executed as the athlete tired, and
whether the weak hand looks anything like the strong one.

Four things are measured, all derived from per-rep features the browser already
computes and previously discarded:

  * **Consistency** -- rep-to-rep variability of range of motion. A repeatable
    movement is the precondition for a coachable one.
  * **Depth** -- how much of the drill's full range each rep actually covers.
    Half reps count toward volume; they should not count toward quality.
  * **Tempo** -- whether reps land in a controlled band, and how evenly.
  * **Endurance** -- whether the last third of the session looks like the first.
    Form collapsing under fatigue is precisely when to stop, and it is invisible
    in a rep count.

Two deliberate choices about how this is used:

  * **Statistics are robust.** Medians and trimmed spreads throughout, because
    one glitched rep from the detector should not tank an honest session.
  * **Quality never subtracts.** It earns a bonus and ranks on its own board; it
    never reduces XP. Penalizing a 13-year-old's form is how you lose them, and
    the athlete who most needs to improve is the one a penalty would punish
    hardest.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from .drills import DrillSpec, Metric

# A component score at or above this is worth praising rather than coaching.
STRONG = 0.80
# And at or below this is the thing to work on next.
WEAK = 0.62

# Components are combined as a weighted *geometric* mean rather than an
# arithmetic one. A movement with textbook consistency and half the range is
# not a good movement, and an arithmetic mean lets three strong components hide
# one bad one -- a session of 99% half reps scored 79/100 under that model.
# The geometric mean makes the weakest link actually cost something.
#
# Each component is floored before the product so one collapsed dimension
# reduces the score sharply without zeroing an otherwise real session.
COMPONENT_FLOOR = 0.05


@dataclass
class RepFeature:
    """One rep's shape, as measured on the athlete's device."""

    t_ms: int
    hand: str = "none"
    confidence: float = 0.0
    # The signal's extreme during the rep -- release height, deepest elbow
    # angle, lowest hip. None for clients too old to report it.
    peak: float | None = None
    # Range of motion covered by the rep, in the signal's units.
    rom: float | None = None
    # Arm-to-fire duration.
    cycle_ms: int | None = None

    @property
    def measurable(self) -> bool:
        return self.rom is not None and self.rom > 0


@dataclass
class Component:
    key: str
    label: str
    score: float          # 0..1
    detail: str           # one plain sentence a 14-year-old can act on

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(self.score, 3),
            "percent": round(self.score * 100),
            "detail": self.detail,
        }


@dataclass
class QualityReport:
    # None when the session is too short or the client reported no shape data.
    score: int | None = None
    components: list[Component] = field(default_factory=list)
    # Separate scores per side, so the off-hand gap is visible.
    per_hand: dict[str, int] = field(default_factory=dict)
    offhand_gap: int | None = None
    rom_retention: float | None = None
    # Trimmed rep-to-rep variability of range of motion across the session.
    rom_spread: float | None = None
    # The same variability measured *within* each hand. This is the true noise
    # floor for an off-hand comparison: a genuine gap between the hands widens
    # the pooled spread, so gating on the pooled figure would hide exactly the
    # deficit this feature exists to find.
    within_hand_spread: float | None = None
    # Median range of motion on the off-hand as a fraction of the dominant
    # hand. This is the physical quantity a coach cares about, and unlike the
    # composite score gap it is not compressed by the scoring ramps.
    offhand_rom_ratio: float | None = None
    coaching_note: str = ""
    measurable_reps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "components": [c.to_dict() for c in self.components],
            "per_hand": self.per_hand,
            "offhand_gap": self.offhand_gap,
            "rom_retention": self.rom_retention,
            "rom_spread": self.rom_spread,
            "within_hand_spread": self.within_hand_spread,
            "offhand_rom_ratio": self.offhand_rom_ratio,
            "coaching_note": self.coaching_note,
            "measurable_reps": self.measurable_reps,
        }


# ---------------------------------------------------------------------------
# Robust statistics
#
# Pose detection glitches. One rep where a wrist was briefly lost produces an
# absurd range of motion, and a mean would let that single rep dominate the
# whole session's score.
# ---------------------------------------------------------------------------

def _trimmed(values: list[float], fraction: float = 0.10) -> list[float]:
    """Drop the most extreme `fraction` from each end."""
    if len(values) < 5:
        return sorted(values)
    ordered = sorted(values)
    cut = int(len(ordered) * fraction)
    return ordered[cut: len(ordered) - cut] or ordered


def _spread(values: list[float]) -> float:
    """Trimmed coefficient of variation. 0 means perfectly repeatable."""
    kept = _trimmed(values)
    if len(kept) < 2:
        return 0.0
    centre = statistics.median(kept)
    if centre == 0:
        return 0.0
    return statistics.pstdev(kept) / abs(centre)


def _median(values: list[float]) -> float:
    kept = _trimmed(values)
    return statistics.median(kept) if kept else 0.0


def _combine(weighted: list[tuple[float, float]]) -> float:
    """Weighted geometric mean of (score, weight) pairs."""
    total = 0.0
    for score, weight in weighted:
        total += weight * math.log(max(COMPONENT_FLOOR, score))
    return math.exp(total)


def _ramp(value: float, good: float, bad: float) -> float:
    """Map a value onto 0..1, where `good` scores 1 and `bad` scores 0."""
    if good == bad:
        return 1.0
    if good < bad:                       # lower is better
        if value <= good:
            return 1.0
        if value >= bad:
            return 0.0
        return 1.0 - (value - good) / (bad - good)
    if value >= good:                    # higher is better
        return 1.0
    if value <= bad:
        return 0.0
    return (value - bad) / (good - bad)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def _consistency(drill: DrillSpec, roms: list[float]) -> Component:
    spec = drill.quality
    cv = _spread(roms)
    score = _ramp(cv, spec.consistency_target, spec.consistency_ceiling)
    if score >= STRONG:
        detail = "Your reps look the same every time. That's the hard part."
    elif score >= WEAK:
        detail = "Mostly repeatable, with some reps drifting off the pattern."
    else:
        detail = "Reps vary a lot from one to the next. Slow down and groove one motion."
    return Component("consistency", "Consistency", score, detail)


def _depth(drill: DrillSpec, roms: list[float]) -> Component:
    spec = drill.quality
    median_rom = _median(roms)
    ratio = median_rom / spec.target_rom if spec.target_rom else 0.0
    # Exceeding the target is not better than hitting it, so cap at 1.
    score = min(1.0, _ramp(ratio, 1.0, 0.45))
    partials = sum(1 for r in roms if r < spec.target_rom * 0.65)
    share = partials / len(roms) if roms else 0.0

    if score >= STRONG:
        detail = "Full range on nearly every rep."
    elif share > 0.25:
        detail = f"{share:.0%} of your reps were short of full range."
    else:
        detail = "Reps are landing a bit short of full range."
    return Component("depth", "Range of motion", score, detail)


def _tempo(drill: DrillSpec, cycles: list[int]) -> Component:
    spec = drill.quality
    if not cycles:
        return Component("tempo", "Tempo", 1.0, "Not enough timing data to judge tempo.")

    in_band = sum(1 for c in cycles if spec.tempo_min_ms <= c <= spec.tempo_max_ms)
    band_score = in_band / len(cycles)
    evenness = _ramp(_spread([float(c) for c in cycles]), 0.20, 0.60)
    score = 0.6 * band_score + 0.4 * evenness

    median_cycle = _median([float(c) for c in cycles])
    if score >= STRONG:
        detail = "Controlled, even rhythm throughout."
    elif median_cycle < spec.tempo_min_ms:
        detail = "You're rushing. Slower reps score better and build more."
    elif median_cycle > spec.tempo_max_ms:
        detail = "Long pauses between reps -- keep the rhythm going."
    else:
        detail = "Rhythm is uneven between reps."
    return Component("tempo", "Tempo", score, detail)


def _endurance(roms: list[float]) -> tuple[Component, float]:
    """Does the last third of the session still look like the first?

    This is the measurement a rep count structurally cannot make, and the one
    that matters most for injury: form collapsing under fatigue is the moment to
    stop, not to push for a round number.
    """
    third = len(roms) // 3
    if third < 3:
        return (
            Component("endurance", "Held up", 1.0,
                      "Session too short to judge whether form held up."),
            1.0,
        )

    early = _median(roms[:third])
    late = _median(roms[-third:])
    retention = (late / early) if early else 1.0

    # Losing a tenth of your range by the end is normal; a third is a warning.
    score = min(1.0, _ramp(retention, 0.95, 0.65))
    if retention >= 0.97:
        detail = "Your last reps looked like your first. Strong."
    elif retention >= 0.88:
        detail = f"Range dropped {(1 - retention):.0%} by the end -- normal fatigue."
    else:
        detail = (
            f"Range dropped {(1 - retention):.0%} by the end. "
            "Stop the set there next time; those reps aren't building anything."
        )
    return Component("endurance", "Held up", score, detail), retention


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _score_subset(drill: DrillSpec, reps: list[RepFeature]) -> float | None:
    """Overall 0..1 score for a set of reps, or None if too few to judge."""
    spec = drill.quality
    usable = [r for r in reps if r.measurable]
    if len(usable) < spec.min_reps:
        return None

    roms = [r.rom for r in usable]
    cycles = [r.cycle_ms for r in usable if r.cycle_ms]
    consistency = _consistency(drill, roms)
    depth = _depth(drill, roms)
    tempo = _tempo(drill, cycles)
    endurance, _ = _endurance(roms)

    return _combine([
        (consistency.score, spec.w_consistency),
        (depth.score, spec.w_depth),
        (tempo.score, spec.w_tempo),
        (endurance.score, spec.w_endurance),
    ])


def analyze(
    drill: DrillSpec,
    reps: list[RepFeature],
    *,
    dominant_hand: str | None = None,
    hold_ms: int = 0,
    duration_ms: int = 0,
) -> QualityReport:
    """Score a session's form. Never raises; an unscorable session returns None."""
    if drill.quality is None:
        return QualityReport(coaching_note="This drill doesn't score form yet.")

    # Hold drills have no reps, so quality is time spent genuinely in position.
    if drill.metric is Metric.HOLD_SECONDS:
        return _analyze_hold(hold_ms, duration_ms)

    usable = [r for r in reps if r.measurable]
    report = QualityReport(measurable_reps=len(usable))

    if len(usable) < drill.quality.min_reps:
        report.coaching_note = (
            f"Need at least {drill.quality.min_reps} clean reps to score your form."
        )
        return report

    roms = [r.rom for r in usable]
    cycles = [r.cycle_ms for r in usable if r.cycle_ms]

    consistency = _consistency(drill, roms)
    depth = _depth(drill, roms)
    tempo = _tempo(drill, cycles)
    endurance, retention = _endurance(roms)

    spec = drill.quality
    overall = _combine([
        (consistency.score, spec.w_consistency),
        (depth.score, spec.w_depth),
        (tempo.score, spec.w_tempo),
        (endurance.score, spec.w_endurance),
    ])

    report.components = [consistency, depth, tempo, endurance]
    report.score = round(max(0.0, min(1.0, overall)) * 100)
    report.rom_retention = round(retention, 3)
    report.rom_spread = round(_spread(roms), 3)

    # Per-hand scoring is the point of the whole feature for lacrosse: the gap
    # between hands is what a coach acts on.
    if drill.tracks_handedness:
        within: list[float] = []
        for side in ("left", "right"):
            side_reps = [r for r in usable if r.hand == side]
            side_score = _score_subset(drill, side_reps)
            if side_score is not None:
                report.per_hand[side] = round(side_score * 100)
            if len(side_reps) >= 4:
                within.append(_spread([r.rom for r in side_reps]))
        if within:
            # The noisier hand sets the floor -- a comparison is only as
            # trustworthy as its shakier half.
            report.within_hand_spread = round(max(within), 3)

        if len(report.per_hand) == 2 and dominant_hand in ("left", "right"):
            offhand = "left" if dominant_hand == "right" else "right"
            report.offhand_gap = report.per_hand[dominant_hand] - report.per_hand[offhand]

            strong_rom = _median([r.rom for r in usable if r.hand == dominant_hand])
            weak_rom = _median([r.rom for r in usable if r.hand == offhand])
            if strong_rom > 0:
                report.offhand_rom_ratio = round(weak_rom / strong_rom, 3)

    report.coaching_note = _coaching_note(report, drill, dominant_hand)
    return report


def _analyze_hold(hold_ms: int, duration_ms: int) -> QualityReport:
    """For a plank, quality is the share of the session actually held in position."""
    report = QualityReport(measurable_reps=0)
    if duration_ms <= 0:
        report.coaching_note = "No timing data for this hold."
        return report

    share = max(0.0, min(1.0, hold_ms / duration_ms))
    score = _ramp(share, 0.92, 0.45)
    if share >= 0.92:
        detail = "You held the line the whole way. That's the hard part."
    elif share >= 0.7:
        detail = f"You were in position {share:.0%} of the time -- hips are dropping."
    else:
        detail = f"Only {share:.0%} of that was a real plank. Shorter and stricter beats longer and sagging."

    report.components = [Component("position", "Position held", score, detail)]
    report.score = round(score * 100)
    report.coaching_note = detail
    return report


# How much shorter the off-hand's range has to be before it is called out.
#
# Judged on the ROM ratio rather than the composite score gap, because the
# scoring ramps compress a real deficit: a genuine 20% shorter off-hand shows
# up as only ~11 composite points, which would sit under any threshold loose
# enough to also reject noise.
#
# The band scales with the noise *within* each hand -- not the pooled spread,
# since a real gap shifts the two hands apart and inflates the pooled figure,
# which would hide exactly the deficit this exists to find. It is floored so a
# suspiciously smooth session cannot flag a trivial difference, and capped so a
# very jittery one still surfaces a large genuine gap.
OFFHAND_MIN_DEFICIT = 0.08
OFFHAND_MAX_DEFICIT = 0.25
OFFHAND_NOISE_FACTOR = 2.0


def offhand_deficit_threshold(within_hand_spread: float | None) -> float:
    """How far below 1.0 the off-hand ROM ratio must fall to be called out."""
    if within_hand_spread is None:
        return OFFHAND_MIN_DEFICIT
    scaled = OFFHAND_NOISE_FACTOR * within_hand_spread
    return min(OFFHAND_MAX_DEFICIT, max(OFFHAND_MIN_DEFICIT, scaled))


def _coaching_note(
    report: QualityReport, drill: DrillSpec, dominant_hand: str | None
) -> str:
    """The single most useful sentence for this session.

    One sentence, not four. A wall of feedback gets skimmed; the weakest
    component is the thing to work on next, and that is what gets said.
    """
    # An off-hand gap outranks everything else on a handed drill -- it is the
    # thing the whole product exists to surface. But it is only claimed when the
    # deficit is bigger than this session's own noise could explain.
    if report.offhand_rom_ratio is not None:
        deficit = 1.0 - report.offhand_rom_ratio
        if deficit >= offhand_deficit_threshold(report.within_hand_spread):
            offhand = "left" if dominant_hand == "right" else "right"
            return (
                f"Your {offhand} hand is getting {deficit:.0%} less range than your "
                f"{dominant_hand}. That gap is the fastest thing you can fix."
            )

    if not report.components:
        return ""

    weakest = min(report.components, key=lambda c: c.score)
    if weakest.score >= STRONG:
        strongest = max(report.components, key=lambda c: c.score)
        return f"Clean session. {strongest.detail}"
    return weakest.detail
