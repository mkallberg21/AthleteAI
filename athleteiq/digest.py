"""The weekly team digest.

Coaches will not log into a dashboard, so the dashboard goes to them. But a
digest is a different object from a dashboard: it gets forwarded to assistant
coaches, pasted into team channels, and read aloud in the parking lot before
practice. That changes what belongs in it.

**No athlete is named in this document.** Not the ones who did nothing, and not
the ones who did the most. Naming the bottom is obviously corrosive, but naming
the same top three every week is the same mechanism inverted -- it tells
everyone else, weekly, that they are not one of them. Individual detail stays in
the coach's dashboard behind a login, where it is a working tool rather than a
broadcast. The digest reports how many athletes need a nudge and links to the
names; it never carries them.

What it does instead is measure the **team**, on numbers a squad can move
together and try to beat next week. The headline metric is participation rate,
deliberately: it goes up when the quiet kids show up, not when the committed
ones do more. That is the only volume metric in this product where the marginal
contributor is the athlete you actually want to reach.

Every KPI carries last week's value, the change, and whether it is a program
record, because "we beat last week" is the mechanic that makes a team read the
same email eight weeks running.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .config import CONFIG


@dataclass
class KPI:
    key: str
    label: str
    value: float
    previous: float | None = None
    best: float | None = None          # best week in the trailing window
    unit: str = "count"                # 'count' | 'percent' | 'score'
    higher_is_better: bool = True
    blurb: str = ""                    # what this number means, in one line

    @property
    def delta(self) -> float | None:
        if self.previous is None:
            return None
        return self.value - self.previous

    @property
    def delta_pct(self) -> float | None:
        """Relative change. None when last week was zero -- a jump from nothing
        is not a percentage, and printing one would be theatre."""
        if self.previous in (None, 0):
            return None
        return (self.value - self.previous) / abs(self.previous)

    @property
    def _resolution(self) -> float:
        """The smallest change this KPI can actually show.

        A percentage is printed to the whole point, a score to the whole
        number, a count to the unit. A delta below that renders as "up 0%",
        which reads as a bug rather than as stability.
        """
        return {"percent": 0.005, "score": 0.5}.get(self.unit, 1.0)

    @property
    def moved(self) -> bool:
        """Whether the change is big enough to be worth calling a change."""
        return self.delta is not None and abs(self.delta) >= self._resolution

    @property
    def direction(self) -> str:
        if not self.moved:
            return "flat"
        improving = (self.delta > 0) == self.higher_is_better
        return "up" if improving else "down"

    @property
    def is_record(self) -> bool:
        """True when this week genuinely beats every week in the window.

        A first week is not a record, and neither is matching the previous best
        to four decimal places -- a record badge on a flat number devalues
        every other one on the page.
        """
        if self.best is None or self.previous is None:
            return False
        return self.value >= self.best and self.moved

    def formatted(self, value: float | None = None) -> str:
        raw = self.value if value is None else value
        if raw is None:
            return "—"
        if self.unit == "percent":
            return f"{raw * 100:.0f}%"
        if self.unit == "score":
            return f"{raw:.0f}"
        return f"{int(round(raw)):,}"

    def change_text(self) -> str:
        if self.delta is None:
            return "first week"
        if not self.moved:
            return "holding steady"
        pct = self.delta_pct
        if self.unit == "percent":
            points = abs(self.delta) * 100
            return f"{'up' if self.delta > 0 else 'down'} {points:.0f} points"
        if pct is not None:
            return f"{'up' if self.delta > 0 else 'down'} {abs(pct) * 100:.0f}%"
        return f"{'up' if self.delta > 0 else 'down'} {self.formatted(abs(self.delta))}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "display": self.formatted(),
            "previous": self.previous,
            "previous_display": self.formatted(self.previous) if self.previous is not None else None,
            "delta": self.delta,
            "delta_pct": self.delta_pct,
            "direction": self.direction,
            "is_record": self.is_record,
            "change_text": self.change_text(),
            "unit": self.unit,
            "blurb": self.blurb,
        }


@dataclass
class TeamDigest:
    org_name: str = ""
    team_name: str = "All teams"
    team_id: int | None = None
    week_start: str = ""
    week_end: str = ""
    roster_size: int = 0

    headline: str = ""
    kpis: list[KPI] = field(default_factory=list)
    milestones: list[str] = field(default_factory=list)
    # Counts only -- never names. The dashboard has the names.
    attention: dict[str, int] = field(default_factory=dict)
    team_standings: list[dict[str, Any]] = field(default_factory=list)
    target: str = ""

    def kpi(self, key: str) -> KPI | None:
        return next((k for k in self.kpis if k.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_name": self.org_name,
            "team_name": self.team_name,
            "team_id": self.team_id,
            "week_start": self.week_start,
            "week_end": self.week_end,
            "roster_size": self.roster_size,
            "headline": self.headline,
            "kpis": [k.to_dict() for k in self.kpis],
            "milestones": self.milestones,
            "attention": self.attention,
            "team_standings": self.team_standings,
            "target": self.target,
        }


# ---------------------------------------------------------------------------
# Week arithmetic
# ---------------------------------------------------------------------------

def week_bounds(anchor: date) -> tuple[date, date]:
    """The Monday-to-Sunday week containing `anchor`."""
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def last_complete_week(today: date) -> tuple[date, date]:
    """The most recent week that has actually finished.

    A digest sent Monday reports the week that just ended, not the one two days
    into itself.
    """
    this_start, _ = week_bounds(today)
    end = this_start - timedelta(days=1)
    return week_bounds(end)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def _roster(conn: sqlite3.Connection, org_id: int, team_id: int | None) -> list[int]:
    if team_id is not None:
        rows = conn.execute(
            "SELECT u.id FROM users u JOIN team_members tm ON tm.user_id = u.id "
            "WHERE tm.team_id = ? AND u.role = 'athlete' AND u.active = 1",
            (team_id,),
        )
    else:
        rows = conn.execute(
            "SELECT id FROM users WHERE org_id = ? AND role = 'athlete' AND active = 1",
            (org_id,),
        )
    return [r[0] for r in rows]


@dataclass
class WeekStats:
    """Raw measurements for one week. Percentages are derived from these."""

    active_athletes: int = 0
    consistent_athletes: int = 0     # trained 3+ separate days
    sessions: int = 0
    reps: int = 0
    offhand_reps: int = 0
    sided_reps: int = 0
    athlete_days: int = 0
    quality_sum: float = 0.0
    quality_n: int = 0
    assignments_due: int = 0
    assignments_done: int = 0
    rest_days: int = 0


def measure_week(
    conn: sqlite3.Connection, athlete_ids: list[int], start: date, end: date
) -> WeekStats:
    stats = WeekStats()
    if not athlete_ids:
        return stats

    placeholders = ",".join("?" for _ in athlete_ids)
    params = [*athlete_ids, start.isoformat(), end.isoformat()]

    rows = conn.execute(
        f"""
        SELECT s.athlete_id,
               date(COALESCE(s.completed_at, s.submitted_at)) AS day,
               s.reps_total, s.reps_left, s.reps_right, s.quality_score,
               u.dominant_hand
        FROM sessions s JOIN users u ON u.id = s.athlete_id
        WHERE s.athlete_id IN ({placeholders}) AND s.status = 'counted'
          AND date(COALESCE(s.completed_at, s.submitted_at)) BETWEEN ? AND ?
        """,
        params,
    ).fetchall()

    days_by_athlete: dict[int, set[str]] = {}
    for row in rows:
        stats.sessions += 1
        stats.reps += int(row["reps_total"])
        hand = row["dominant_hand"] or "right"
        stats.offhand_reps += int(
            row["reps_left"] if hand == "right" else row["reps_right"]
        )
        stats.sided_reps += int(row["reps_left"]) + int(row["reps_right"])
        if row["quality_score"] is not None:
            stats.quality_sum += float(row["quality_score"])
            stats.quality_n += 1
        days_by_athlete.setdefault(row["athlete_id"], set()).add(row["day"])

    stats.active_athletes = len(days_by_athlete)
    stats.consistent_athletes = sum(1 for d in days_by_athlete.values() if len(d) >= 3)
    stats.athlete_days = sum(len(d) for d in days_by_athlete.values())

    stats.rest_days = int(
        conn.execute(
            f"SELECT COUNT(*) AS n FROM recovery_days "
            f"WHERE athlete_id IN ({placeholders}) AND day BETWEEN ? AND ?",
            params,
        ).fetchone()["n"]
    )

    # Assignment completion, counted over assignments whose window overlaps
    # this one.
    from . import assignments as assignments_mod

    for assignment in conn.execute(
        "SELECT a.*, t.name AS team_name FROM assignments a "
        "JOIN teams t ON t.id = a.team_id "
        "WHERE a.due_on BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall():
        obj = assignments_mod.get(conn, assignment["id"])
        if obj is None:
            continue
        for progress in assignments_mod.compliance(conn, obj):
            if progress.athlete_id not in athlete_ids:
                continue
            stats.assignments_due += 1
            if progress.complete:
                stats.assignments_done += 1

    return stats


def _rate(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator else 0.0


def build_kpis(
    current: WeekStats, previous: WeekStats, history: list[WeekStats], roster: int
) -> list[KPI]:
    """Turn raw weekly measurements into the numbers a team competes on."""

    def best(extract) -> float | None:
        values = [extract(w) for w in history]
        return max(values) if values else None

    participation = KPI(
        key="participation",
        label="Athletes who trained",
        value=_rate(current.active_athletes, roster),
        previous=_rate(previous.active_athletes, roster) if roster else None,
        best=best(lambda w: _rate(w.active_athletes, roster)) if roster else None,
        unit="percent",
        blurb=(
            f"{current.active_athletes} of {roster} put in work on their own time. "
            "This is the number that moves when the quiet ones show up."
        ),
    )

    consistency = KPI(
        key="consistency",
        label="Trained 3+ days",
        value=_rate(current.consistent_athletes, roster),
        previous=_rate(previous.consistent_athletes, roster) if roster else None,
        best=best(lambda w: _rate(w.consistent_athletes, roster)) if roster else None,
        unit="percent",
        blurb="Turning up once is a good week. Three times is a habit.",
    )

    volume = KPI(
        key="reps",
        label="Reps outside practice",
        value=float(current.reps),
        previous=float(previous.reps),
        best=best(lambda w: float(w.reps)),
        blurb="Every one of these happened in a driveway, a backyard, or a wall.",
    )

    sessions = KPI(
        key="athlete_days",
        label="Training days logged",
        value=float(current.athlete_days),
        previous=float(previous.athlete_days),
        best=best(lambda w: float(w.athlete_days)),
        blurb="Athlete-days across the squad -- the raw amount of showing up.",
    )

    offhand = KPI(
        key="offhand",
        label="Work on the weak hand",
        value=_rate(current.offhand_reps, current.sided_reps),
        previous=_rate(previous.offhand_reps, previous.sided_reps),
        best=best(lambda w: _rate(w.offhand_reps, w.sided_reps)),
        unit="percent",
        blurb=(
            "Share of reps on the hand nobody wants to use. The single most "
            "coachable number on this page."
        ),
    )

    quality = KPI(
        key="quality",
        label="Average form score",
        value=_rate(current.quality_sum, current.quality_n),
        previous=_rate(previous.quality_sum, previous.quality_n),
        best=best(lambda w: _rate(w.quality_sum, w.quality_n)),
        unit="score",
        blurb="How well the reps were done, not how many. Out of 100.",
    )

    kpis = [participation, consistency, volume, sessions, offhand, quality]

    if current.assignments_due or previous.assignments_due:
        kpis.append(KPI(
            key="assignments",
            label="Assigned work completed",
            value=_rate(current.assignments_done, current.assignments_due),
            previous=_rate(previous.assignments_done, previous.assignments_due),
            best=best(lambda w: _rate(w.assignments_done, w.assignments_due)),
            unit="percent",
            blurb=f"{current.assignments_done} of {current.assignments_due} assignments finished.",
        ))

    return kpis


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------

def _headline(digest: TeamDigest, current: WeekStats) -> str:
    """The single best true thing about this week.

    Records first, then improvements, then a plain statement of the work. Never
    invented -- if the week was quiet, it says so and points forward.
    """
    records = [k for k in digest.kpis if k.is_record]
    if records:
        top = max(records, key=lambda k: abs(k.delta_pct or 0))
        return f"Program record: {top.label.lower()} hit {top.formatted()} this week."

    improving = [k for k in digest.kpis if k.direction == "up"]
    if improving:
        top = max(improving, key=lambda k: abs(k.delta_pct or 0.05))
        return f"{top.label} {top.change_text()} — now {top.formatted()}."

    if current.reps:
        return (
            f"{current.reps:,} reps logged outside practice by "
            f"{current.active_athletes} athletes."
        )
    return "Quiet week off the field. One session from each athlete turns that around."


def _milestones(current: WeekStats, previous: WeekStats, roster: int) -> list[str]:
    """Collective achievements, phrased as counts.

    Deliberately never "Jordan hit 1,000 reps" -- the same three names every
    week tells everyone else, weekly, that they are not one of them.
    """
    out: list[str] = []

    if current.active_athletes == roster and roster > 0:
        out.append(f"Every single athlete on the roster trained. All {roster} of them.")
    elif current.active_athletes > previous.active_athletes:
        gained = current.active_athletes - previous.active_athletes
        out.append(
            f"{gained} more athlete{'s' if gained != 1 else ''} trained than last week."
        )

    if current.reps > previous.reps and previous.reps:
        out.append(
            f"{current.reps - previous.reps:,} more reps than last week — "
            f"{current.reps / max(1, current.active_athletes):,.0f} per active athlete."
        )

    offhand_share = _rate(current.offhand_reps, current.sided_reps)
    if offhand_share >= 0.40:
        out.append(
            f"{offhand_share * 100:.0f}% of reps went to the weak hand. "
            "That is genuinely hard to do."
        )

    if current.rest_days:
        out.append(
            f"{current.rest_days} recovery day{'s' if current.rest_days != 1 else ''} "
            "logged. Resting on purpose is training too."
        )

    if current.quality_n and _rate(current.quality_sum, current.quality_n) >= 85:
        out.append(
            f"Average form score of {_rate(current.quality_sum, current.quality_n):.0f} "
            "across every session."
        )
    return out


def _target(digest: TeamDigest, roster: int) -> str:
    """One concrete thing to beat next week."""
    participation = digest.kpi("participation")
    if participation and roster:
        active = round(participation.value * roster)
        if active < roster:
            need = roster - active
            return (
                f"Next week's target: {need} more athlete{'s' if need != 1 else ''} "
                f"logging a session takes participation to 100%."
            )

    offhand = digest.kpi("offhand")
    if offhand and offhand.value < 0.45:
        return (
            f"Next week's target: push weak-hand work from "
            f"{offhand.value * 100:.0f}% to 45%."
        )

    reps = digest.kpi("reps")
    if reps and reps.best:
        return f"Next week's target: beat {reps.formatted(reps.best)} reps."
    return "Next week's target: hold the line."


def compute(
    conn: sqlite3.Connection,
    org_id: int,
    *,
    team_id: int | None = None,
    today: date | None = None,
    history_weeks: int = 12,
) -> TeamDigest:
    """Build a digest for the most recently completed week."""
    today = today or date.today()
    start, end = last_complete_week(today)

    org = conn.execute(
        "SELECT name FROM organizations WHERE id = ?", (org_id,)
    ).fetchone()
    digest = TeamDigest(
        org_name=org["name"] if org else "",
        week_start=start.isoformat(),
        week_end=end.isoformat(),
        team_id=team_id,
    )
    if team_id is not None:
        team = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
        digest.team_name = team["name"] if team else "Team"

    athlete_ids = _roster(conn, org_id, team_id)
    digest.roster_size = len(athlete_ids)
    if not athlete_ids:
        digest.headline = "No athletes on this roster yet."
        return digest

    current = measure_week(conn, athlete_ids, start, end)
    prev_start, prev_end = week_bounds(start - timedelta(days=1))
    previous = measure_week(conn, athlete_ids, prev_start, prev_end)

    # Trailing weeks, excluding this one, so "record" means beating the past.
    history = []
    for back in range(1, history_weeks + 1):
        h_start, h_end = week_bounds(start - timedelta(days=7 * back))
        history.append(measure_week(conn, athlete_ids, h_start, h_end))

    digest.kpis = build_kpis(current, previous, history, len(athlete_ids))
    digest.headline = _headline(digest, current)
    digest.milestones = _milestones(current, previous, len(athlete_ids))
    digest.target = _target(digest, len(athlete_ids))

    # Counts only. The names live in the dashboard.
    inactive = len(athlete_ids) - current.active_athletes
    digest.attention = {
        "not_trained_this_week": inactive,
        "needs_rest": 0,
        "review_queue": int(conn.execute(
            "SELECT COUNT(*) AS n FROM sessions s JOIN users u ON u.id = s.athlete_id "
            "WHERE s.status = 'review' AND u.org_id = ?",
            (org_id,),
        ).fetchone()["n"]),
    }

    from .store import Store

    store = Store(conn)
    digest.attention["needs_rest"] = sum(
        1 for aid in athlete_ids if store.load_state(aid).rest_recommended
    )

    if team_id is None:
        from .leaderboard import team_standings

        digest.team_standings = team_standings(conn, org_id, "week")

    return digest


# ---------------------------------------------------------------------------
# Rendering
#
# Email HTML is not web HTML. Layout is tables, every style is inline because
# most clients strip <style>, the body is capped near 600px, and flexbox and
# grid are unavailable. It is also rendered light: dark-mode handling across
# email clients is unreliable enough that a deliberately light design reads
# correctly far more often than a clever one.
# ---------------------------------------------------------------------------

INK = "#14202c"
MUTED = "#5b6b7c"
LINE = "#dde3ea"
PAPER = "#f4f6f8"
CARD = "#ffffff"
UP = "#0f7a54"
DOWN = "#a8531f"
ACCENT = "#d6491a"

FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def attention_lines(attention: dict[str, int]) -> list[str]:
    """Counts a coach should act on, phrased so the grammar survives a count of one."""
    lines: list[str] = []
    missing = attention.get("not_trained_this_week", 0)
    if missing:
        lines.append(
            f"{missing} athlete{'s' if missing != 1 else ''} "
            f"didn't log a session"
        )
    rest = attention.get("needs_rest", 0)
    if rest:
        lines.append(
            f"{rest} {'is' if rest == 1 else 'are'} due a rest day"
        )
    review = attention.get("review_queue", 0)
    if review:
        lines.append(
            f"{review} session{'s' if review != 1 else ''} "
            f"need{'s' if review == 1 else ''} a quick look"
        )
    return lines


def _esc(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _kpi_cell(kpi: KPI) -> str:
    color = UP if kpi.direction == "up" else DOWN if kpi.direction == "down" else MUTED
    arrow = "&#9650;" if kpi.direction == "up" else "&#9660;" if kpi.direction == "down" else "&ndash;"
    record = (
        f'<span style="display:inline-block;background:{ACCENT};color:#fff;'
        f'font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;'
        f'padding:2px 6px;border-radius:3px;margin-left:6px">record</span>'
        if kpi.is_record else ""
    )
    return f"""
<td width="50%" valign="top" style="padding:6px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{CARD};border:1px solid {LINE};border-radius:8px">
    <tr><td style="padding:14px 16px">
      <div style="font-size:11px;font-weight:700;letter-spacing:.06em;
                  text-transform:uppercase;color:{MUTED}">{_esc(kpi.label)}{record}</div>
      <div style="font-size:30px;font-weight:800;color:{INK};line-height:1.1;
                  margin:6px 0 2px">{kpi.formatted()}</div>
      <div style="font-size:12px;color:{color};font-weight:600">
        {arrow} {_esc(kpi.change_text())}
        <span style="color:{MUTED};font-weight:400">
          (was {_esc(kpi.formatted(kpi.previous)) if kpi.previous is not None else "&mdash;"})</span>
      </div>
      <div style="font-size:12px;color:{MUTED};line-height:1.45;margin-top:8px">
        {_esc(kpi.blurb)}</div>
    </td></tr>
  </table>
</td>"""


def render_html(digest: TeamDigest, dashboard_url: str = "") -> str:
    """The digest as an email-client-safe HTML document."""
    rows = []
    cells = [_kpi_cell(k) for k in digest.kpis]
    for i in range(0, len(cells), 2):
        pair = cells[i:i + 2]
        if len(pair) == 1:
            pair.append('<td width="50%" style="padding:6px"></td>')
        rows.append(f"<tr>{''.join(pair)}</tr>")
    kpi_table = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'{"".join(rows)}</table>'
    )

    milestones = "".join(
        f'<tr><td style="padding:7px 0;border-bottom:1px solid {LINE};'
        f'font-size:14px;color:{INK};line-height:1.5">'
        f'<span style="color:{ACCENT};font-weight:700">&#8226;</span> &nbsp;{_esc(m)}</td></tr>'
        for m in digest.milestones
    )
    milestones_block = f"""
<tr><td style="padding:18px 22px 4px">
  <div style="font-size:13px;font-weight:700;letter-spacing:.06em;
              text-transform:uppercase;color:{MUTED};margin-bottom:6px">
    What the squad did</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{milestones}</table>
</td></tr>""" if milestones else ""

    standings = ""
    if digest.team_standings:
        rows_html = "".join(
            f'<tr><td style="padding:6px 0;font-size:14px;color:{INK}">'
            f'<b>{t["rank"]}.</b> {_esc(t["team_name"])}</td>'
            f'<td align="right" style="padding:6px 0;font-size:14px;color:{INK};'
            f'font-weight:700">{t["xp_per_athlete"]:,.0f}</td>'
            f'<td align="right" style="padding:6px 0;font-size:12px;color:{MUTED}">'
            f'{t["participation"] * 100:.0f}% training</td></tr>'
            for t in digest.team_standings
        )
        standings = f"""
<tr><td style="padding:18px 22px 4px">
  <div style="font-size:13px;font-weight:700;letter-spacing:.06em;
              text-transform:uppercase;color:{MUTED};margin-bottom:6px">
    Team standings <span style="font-weight:400;text-transform:none;
    letter-spacing:0">&mdash; XP per athlete, so squad size doesn't decide it</span></div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows_html}</table>
</td></tr>"""

    needs = attention_lines(digest.attention)

    attention_block = f"""
<tr><td style="padding:16px 22px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{PAPER};border:1px solid {LINE};border-radius:8px">
    <tr><td style="padding:14px 16px">
      <div style="font-size:13px;font-weight:700;color:{INK};margin-bottom:5px">
        For your eyes only</div>
      <div style="font-size:13px;color:{MUTED};line-height:1.55">
        {_esc(" &middot; ".join(needs))}.
        <br>Names are in your dashboard, deliberately not in this email &mdash;
        it gets forwarded.
      </div>
      {f'<div style="margin-top:10px"><a href="{_esc(dashboard_url)}" '
       f'style="display:inline-block;background:{INK};color:#fff;text-decoration:none;'
       f'font-size:13px;font-weight:600;padding:9px 16px;border-radius:6px">'
       f'Open the dashboard</a></div>' if dashboard_url else ''}
    </td></tr>
  </table>
</td></tr>""" if needs else ""

    scope = digest.team_name if digest.team_id else digest.org_name

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_esc(scope)} &mdash; week of {_esc(digest.week_start)}</title>
</head>
<body style="margin:0;padding:0;background:{PAPER};font-family:{FONT}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{PAPER};padding:20px 10px">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="max-width:600px;width:100%;background:{CARD};border:1px solid {LINE};
              border-radius:12px;overflow:hidden">

  <tr><td style="padding:22px 22px 16px;border-bottom:2px solid {INK}">
    <div style="font-size:11px;font-weight:700;letter-spacing:.14em;
                text-transform:uppercase;color:{ACCENT}">
      Off-field training &middot; week of {_esc(digest.week_start)}</div>
    <div style="font-size:24px;font-weight:800;color:{INK};margin-top:6px;
                line-height:1.15">{_esc(scope)}</div>
  </td></tr>

  <tr><td style="padding:20px 22px 6px">
    <div style="font-size:18px;font-weight:700;color:{INK};line-height:1.4">
      {_esc(digest.headline)}</div>
  </td></tr>

  <tr><td style="padding:8px 16px">{kpi_table}</td></tr>

  {milestones_block}
  {standings}

  <tr><td style="padding:18px 22px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="background:{INK};border-radius:8px">
      <tr><td style="padding:16px 18px">
        <div style="font-size:11px;font-weight:700;letter-spacing:.08em;
                    text-transform:uppercase;color:#8fa3b5">Beat this</div>
        <div style="font-size:16px;font-weight:700;color:#fff;margin-top:5px;
                    line-height:1.4">{_esc(digest.target)}</div>
      </td></tr>
    </table>
  </td></tr>

  {attention_block}

  <tr><td style="padding:16px 22px 22px;border-top:1px solid {LINE}">
    <div style="font-size:11px;color:{MUTED};line-height:1.6">
      {digest.roster_size} athletes on this roster.
      No individual athlete is named in this email, by design &mdash; these are
      team numbers, meant to be shared.
      <br>Athletes' video is analysed on their own phones and never uploaded.
    </div>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


def render_text(digest: TeamDigest, dashboard_url: str = "") -> str:
    """Plain-text alternative.

    Sent alongside the HTML rather than instead of it: some clients prefer it,
    some strip HTML entirely, and a multipart email without it lands in spam
    more often.
    """
    scope = digest.team_name if digest.team_id else digest.org_name
    lines = [
        f"{scope.upper()} - OFF-FIELD TRAINING",
        f"Week of {digest.week_start} to {digest.week_end}",
        "",
        digest.headline,
        "",
        "THIS WEEK",
    ]
    for kpi in digest.kpis:
        record = "  ** RECORD **" if kpi.is_record else ""
        lines.append(
            f"  {kpi.label}: {kpi.formatted()}  ({kpi.change_text()}){record}"
        )

    if digest.milestones:
        lines += ["", "WHAT THE SQUAD DID"]
        lines += [f"  - {m}" for m in digest.milestones]

    if digest.team_standings:
        lines += ["", "TEAM STANDINGS (XP per athlete)"]
        lines += [
            f"  {t['rank']}. {t['team_name']}: {t['xp_per_athlete']:,.0f}"
            f"  ({t['participation'] * 100:.0f}% training)"
            for t in digest.team_standings
        ]

    lines += ["", f"BEAT THIS: {digest.target}"]

    needs = attention_lines(digest.attention)
    if needs:
        lines += [
            "",
            "FOR YOUR EYES ONLY",
            "  " + " | ".join(needs),
            "  Names are in your dashboard, deliberately not in this email.",
        ]
        if dashboard_url:
            lines.append(f"  {dashboard_url}")

    lines += [
        "",
        f"{digest.roster_size} athletes on this roster. No individual athlete is",
        "named in this email, by design. Video is analysed on athletes' own",
        "phones and never uploaded.",
    ]
    return "\n".join(lines)


def subject_line(digest: TeamDigest) -> str:
    """Concrete enough that a coach opens it without opening it."""
    scope = digest.team_name if digest.team_id else digest.org_name
    participation = digest.kpi("participation")
    if participation and participation.is_record:
        return f"{scope}: record week — {participation.formatted()} of the squad trained"
    if participation and participation.value:
        return (
            f"{scope}: {participation.formatted()} trained last week"
            f" ({participation.change_text()})"
        )
    return f"{scope}: last week's off-field training"
