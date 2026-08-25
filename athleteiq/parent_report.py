"""The monthly report a guardian gets about their own child.

The weekly team digest names nobody on purpose -- it gets forwarded, pasted
into team channels, and read aloud in car parks, and a document like that
must not carry a child's name in either direction. This is the opposite
object. It goes to one household, it is about one child, and naming them is
the entire point.

That inversion is the whole reason it needs its own rules rather than a
filter on the digest.

**No comparison to teammates.** Not a rank, not a percentile, not "above
average for the squad". This product refuses volume comparison between
children everywhere else, and a parent report is exactly where that refusal
would be easiest to quietly drop and most damaging to drop -- it is the
document that gets held up at a kitchen table next to a sibling's. What a
child is measured against is their own last month and their own age-band
budget, both of which they can act on.

**A quiet month is reported honestly and kindly.** Not hidden, because a
parent paying for this is owed the truth, and not scolded, because the child
did not do anything wrong. Two sessions in a month with exams on is a fact,
not a failing, and the report says the fact.

**Nothing here is a medical claim.** Wellness appears as whether the app was
asking a child to ease off, never as an injury the parent is being informed
of by software. If something needed a grown-up, that already went to them the
day it happened -- a monthly summary is far too late to be the first anyone
hears of it, and it must not read as though it were.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .drills import DRILLS_BY_KEY

#: Sessions below this in a month read as "they had a go" rather than a
#: routine, and the copy changes accordingly.
QUIET_MONTH = 4

#: How many highlights to carry. Three fits a phone screen; a list of twelve
#: is a spreadsheet, and nobody reads a spreadsheet about their own child.
MAX_HIGHLIGHTS = 3


def month_bounds(anchor: date) -> tuple[date, date]:
    """First and last day of the calendar month `anchor` falls in."""
    first = anchor.replace(day=1)
    next_first = (first + timedelta(days=32)).replace(day=1)
    return first, next_first - timedelta(days=1)


def last_complete_month(today: date) -> tuple[date, date]:
    """The month that has finished.

    A report about the month you are standing in is a report that changes
    after you read it, which is not a report.
    """
    return month_bounds(today.replace(day=1) - timedelta(days=1))


@dataclass
class MonthStats:
    sessions: int = 0
    days: int = 0
    minutes: float = 0.0
    reps: int = 0
    drills: int = 0
    quality: int | None = None
    offhand_share: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions": self.sessions,
            "days": self.days,
            "minutes": round(self.minutes),
            "reps": self.reps,
            "drills": self.drills,
            "quality": self.quality,
            "offhand_share": (round(self.offhand_share, 3)
                              if self.offhand_share is not None else None),
        }


@dataclass
class Report:
    athlete_id: int
    display_name: str
    first_name: str
    month_label: str
    start: str
    end: str
    current: MonthStats = field(default_factory=MonthStats)
    previous: MonthStats = field(default_factory=MonthStats)
    headline: str = ""
    highlights: list[str] = field(default_factory=list)
    #: What the app asked of them, in plain terms. Never a diagnosis.
    care: list[str] = field(default_factory=list)
    recognition: list[dict[str, str]] = field(default_factory=list)

    @property
    def quiet(self) -> bool:
        return self.current.sessions < QUIET_MONTH

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "display_name": self.display_name,
            "month_label": self.month_label,
            "start": self.start,
            "end": self.end,
            "current": self.current.to_dict(),
            "previous": self.previous.to_dict(),
            "headline": self.headline,
            "highlights": self.highlights,
            "care": self.care,
            "recognition": self.recognition,
            "quiet": self.quiet,
        }


def _measure(
    conn: sqlite3.Connection, athlete_id: int, start: date, end: date
) -> MonthStats:
    row = conn.execute(
        "SELECT COUNT(*) AS sessions, "
        "  COUNT(DISTINCT date(submitted_at)) AS days, "
        "  COALESCE(SUM(duration_ms), 0) AS ms, "
        "  COALESCE(SUM(reps_total), 0) AS reps, "
        "  COUNT(DISTINCT drill_key) AS drills, "
        "  COALESCE(SUM(reps_left), 0) AS left_reps, "
        "  COALESCE(SUM(reps_right), 0) AS right_reps "
        "FROM sessions WHERE athlete_id = ? AND status = 'counted' "
        "AND date(submitted_at) BETWEEN ? AND ?",
        (athlete_id, start.isoformat(), end.isoformat()),
    ).fetchone()

    stats = MonthStats(
        sessions=int(row["sessions"]), days=int(row["days"]),
        minutes=int(row["ms"]) / 60_000.0, reps=int(row["reps"]),
        drills=int(row["drills"]),
    )

    # Averaged over sessions that actually produced a form score. A session
    # the scorer could not read is not a zero.
    scored = conn.execute(
        "SELECT AVG(quality_score) AS q FROM sessions WHERE athlete_id = ? "
        "AND status = 'counted' AND quality_score IS NOT NULL "
        "AND date(submitted_at) BETWEEN ? AND ?",
        (athlete_id, start.isoformat(), end.isoformat()),
    ).fetchone()
    if scored["q"] is not None:
        stats.quality = round(float(scored["q"]))

    handed = int(row["left_reps"]) + int(row["right_reps"])
    if handed:
        weaker = min(int(row["left_reps"]), int(row["right_reps"]))
        stats.offhand_share = weaker / handed
    return stats


def _headline(report: Report) -> str:
    """One sentence, addressed to a parent, about their own child only.

    Never a comparison to the squad. What moved is measured against the same
    child last month, which is the only comparison a family can act on and
    the only one that does not make a child a data point next to their
    teammates.
    """
    first, current, previous = report.first_name, report.current, report.previous

    if current.sessions == 0:
        return (
            f"{first} did not log any training at home last month."
            if previous.sessions == 0 else
            f"{first} did not log any training at home last month, after "
            f"{previous.sessions} the month before."
        )

    if report.quiet:
        got_out = (
            f"{first} got out {current.sessions} time"
            f"{'' if current.sessions == 1 else 's'} last month"
        )
        # A drop still gets named. Tone is the reason the quiet branch exists,
        # but a parent going from twelve sessions to three is owed the fact,
        # and swallowing it to stay gentle is how a report stops being honest.
        if previous.sessions > current.sessions * 2:
            return (
                f"{got_out}, down from {previous.sessions} the month before. "
                "Months vary a lot at this age."
            )
        return (
            f"{got_out} — a few sessions rather than a routine, which some "
            "months are."
        )

    if previous.sessions == 0:
        return (
            f"{first} trained on {current.days} days last month, which is a "
            "start from nothing."
        )

    if current.days > previous.days:
        return (
            f"{first} trained on {current.days} days last month, up from "
            f"{previous.days}."
        )
    if current.days == previous.days:
        return (
            f"{first} trained on {current.days} days last month, the same as "
            "the month before — steady is the hard part."
        )
    return (
        f"{first} trained on {current.days} days last month, down from "
        f"{previous.days}. Months vary; it is the year that matters."
    )


def _highlights(report: Report, best: sqlite3.Row | None) -> list[str]:
    """Things worth telling a parent, in the order a parent cares about.

    Effort and improvement before totals. A number that only goes up with
    volume is the one metric this product will not celebrate on its own,
    because celebrating it is how a child learns that more is always better.
    """
    out: list[str] = []
    current, previous = report.current, report.previous

    if (current.quality is not None and previous.quality is not None
            and current.quality > previous.quality):
        out.append(
            f"Their form score improved from {previous.quality} to "
            f"{current.quality} — the reps are getting better, not just more "
            "numerous."
        )
    elif current.quality is not None:
        out.append(f"Their form score averaged {current.quality} out of 100.")

    if current.offhand_share is not None and current.offhand_share >= 0.4:
        out.append(
            f"{round(current.offhand_share * 100)}% of their reps were on their "
            "weaker side, which is the habit that is hardest to keep up and "
            "makes the most difference."
        )

    if best is not None and best["drill_key"] in DRILLS_BY_KEY:
        out.append(
            f"Their best session was {DRILLS_BY_KEY[best['drill_key']].name} on "
            f"{best['submitted_at'][:10]}."
        )

    if current.drills >= 3:
        out.append(
            f"They worked on {current.drills} different drills rather than "
            "repeating one."
        )

    return out[:MAX_HIGHLIGHTS]


def _care(conn: sqlite3.Connection, athlete_id: int, start: date, end: date,
          first_name: str) -> list[str]:
    """What the app asked of them, in plain terms.

    Deliberately not a medical summary and deliberately not news. Anything
    that needed a grown-up reached this household the day it happened; a
    monthly report arriving as the first anyone hears of an injury would be
    a serious failure, so this only ever describes what the app did.
    """
    out: list[str] = []

    eased = conn.execute(
        "SELECT COUNT(*) AS n FROM discomfort_reports WHERE athlete_id = ? "
        "AND date(reported_on) BETWEEN ? AND ?",
        (athlete_id, start.isoformat(), end.isoformat()),
    ).fetchone()["n"]
    if eased:
        out.append(
            f"{first_name} told the app they were sore on {eased} occasion"
            f"{'' if eased == 1 else 's'}, and it eased their training off each "
            "time. Saying so costs them nothing here, which is the point."
        )

    ramps = conn.execute(
        "SELECT COUNT(*) AS n FROM return_plans WHERE athlete_id = ? "
        "AND date(started_on) BETWEEN ? AND ?",
        (athlete_id, start.isoformat(), end.isoformat()),
    ).fetchone()["n"]
    if ramps:
        out.append(
            "They started a graded return to full training, which needs a "
            "grown-up to sign off at each stage — you will have seen those "
            "at the time."
        )

    checkins = conn.execute(
        "SELECT COUNT(*) AS n FROM wellness_checkins WHERE athlete_id = ? "
        "AND day BETWEEN ? AND ?",
        (athlete_id, start.isoformat(), end.isoformat()),
    ).fetchone()["n"]
    if checkins and not out:
        out.append(
            f"{first_name} checked in on how they were feeling {checkins} time"
            f"{'' if checkins == 1 else 's'} and reported nothing wrong."
        )
    return out


def build(
    conn: sqlite3.Connection,
    athlete_id: int,
    today: date | None = None,
) -> Report | None:
    """The finished month for one child, or None if we do not know them."""
    today = today or date.today()
    start, end = last_complete_month(today)

    row = conn.execute(
        "SELECT display_name FROM users WHERE id = ? AND role = 'athlete'",
        (athlete_id,),
    ).fetchone()
    if row is None:
        return None

    name = row["display_name"] or ""
    previous_end = start - timedelta(days=1)
    previous_start, _ = month_bounds(previous_end)

    report = Report(
        athlete_id=athlete_id,
        display_name=name,
        first_name=name.split()[0] if name else "They",
        month_label=start.strftime("%B %Y"),
        start=start.isoformat(),
        end=end.isoformat(),
        current=_measure(conn, athlete_id, start, end),
        previous=_measure(conn, athlete_id, previous_start, previous_end),
    )

    best = conn.execute(
        "SELECT drill_key, submitted_at, quality_score FROM sessions "
        "WHERE athlete_id = ? AND status = 'counted' AND quality_score IS NOT NULL "
        "AND date(submitted_at) BETWEEN ? AND ? "
        "ORDER BY quality_score DESC LIMIT 1",
        (athlete_id, start.isoformat(), end.isoformat()),
    ).fetchone()

    report.headline = _headline(report)
    report.highlights = _highlights(report, best)
    report.care = _care(conn, athlete_id, start, end, report.first_name)
    report.recognition = [
        {"title": r["title"], "from_name": r["from_name"] or "",
         "on": (r["created_at"] or "")[:10]}
        for r in conn.execute(
            "SELECT title, from_name, created_at FROM notifications "
            "WHERE about_athlete_id = ? AND kind = 'recognition' "
            "AND date(created_at) BETWEEN ? AND ? AND is_copy = 0 "
            "ORDER BY created_at",
            (athlete_id, start.isoformat(), end.isoformat()),
        )
    ]
    return report


# ---------------------------------------------------------------------------
# Rendering
#
# Reuses the digest's palette and table-based email shell, because an email
# that renders in one client and not another is an email nobody trusts.
# ---------------------------------------------------------------------------

from .digest import ACCENT, CARD, FONT, INK, LINE, MUTED, PAPER, _esc  # noqa: E402


def _stat_cell(value: str, label: str) -> str:
    return (
        f'<td width="33%" align="center" style="padding:10px 4px">'
        f'<div style="font-size:24px;font-weight:800;color:{INK};line-height:1.1">'
        f'{_esc(value)}</div>'
        f'<div style="font-size:11px;color:{MUTED};text-transform:uppercase;'
        f'letter-spacing:.06em;margin-top:3px">{_esc(label)}</div></td>'
    )


def _bullets(title: str, items: list[str]) -> str:
    if not items:
        return ""
    rows = "".join(
        f'<tr><td style="padding:7px 0;border-bottom:1px solid {LINE};'
        f'font-size:14px;color:{INK};line-height:1.5">'
        f'<span style="color:{ACCENT};font-weight:700">&#8226;</span> '
        f'&nbsp;{_esc(item)}</td></tr>'
        for item in items
    )
    return f"""
<tr><td style="padding:18px 22px 4px">
  <div style="font-size:13px;font-weight:700;letter-spacing:.06em;
              text-transform:uppercase;color:{MUTED};margin-bottom:6px">
    {_esc(title)}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
</td></tr>"""


def render_html(report: Report, unsubscribe: str = "") -> str:
    """The month as an email-client-safe document."""
    stats = "".join((
        _stat_cell(str(report.current.days), "days trained"),
        _stat_cell(str(report.current.sessions), "sessions"),
        _stat_cell(f"{report.current.minutes:.0f}", "minutes"),
    ))

    recognition = _bullets("What their coach said", [
        f"{r['title']}" + (f" — {r['from_name']}" if r["from_name"] else "")
        for r in report.recognition
    ])

    footer = (
        f'<div style="font-size:12px;color:{MUTED};line-height:1.6">'
        "This is about your own child only. We do not rank children against "
        "their teammates here or anywhere else."
        + (f' <a href="{_esc(unsubscribe)}" style="color:{MUTED}">Stop these '
           "emails</a>." if unsubscribe else "")
        + "</div>"
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_esc(report.first_name)} &mdash; {_esc(report.month_label)}</title>
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
      {_esc(report.month_label)}</div>
    <div style="font-size:24px;font-weight:800;color:{INK};margin-top:6px;
                line-height:1.15">{_esc(report.display_name)}</div>
  </td></tr>

  <tr><td style="padding:16px 22px 0">
    <div style="font-size:15px;color:{INK};line-height:1.55">
      {_esc(report.headline)}</div>
  </td></tr>

  <tr><td style="padding:6px 12px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr>{stats}</tr>
    </table>
  </td></tr>

  {_bullets("Worth knowing", report.highlights)}
  {recognition}
  {_bullets("Looking after themselves", report.care)}

  <tr><td style="padding:18px 22px 22px;border-top:1px solid {LINE}">
    {footer}
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


def render_text(report: Report) -> str:
    """Plain text, for clients that will not render HTML."""
    lines = [
        f"{report.display_name} — {report.month_label}",
        "",
        report.headline,
        "",
        f"{report.current.days} days trained, {report.current.sessions} sessions, "
        f"{report.current.minutes:.0f} minutes.",
    ]
    for title, items in (
        ("Worth knowing", report.highlights),
        ("What their coach said", [
            r["title"] + (f" — {r['from_name']}" if r["from_name"] else "")
            for r in report.recognition
        ]),
        ("Looking after themselves", report.care),
    ):
        if items:
            lines += ["", title.upper()] + [f"  - {i}" for i in items]
    lines += [
        "",
        "This is about your own child only. We do not rank children against "
        "their teammates here or anywhere else.",
    ]
    return "\n".join(lines)


def subject_line(report: Report) -> str:
    """Names the child and the month.

    Not the number of sessions: a subject line that says "2 sessions" turns
    a quiet month into a public verdict in a notification preview, which is
    the last place a parent should first read it.
    """
    return f"{report.first_name}'s month — {report.month_label}"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def generate(conn: sqlite3.Connection, today: date | None = None) -> int:
    """Queue last month's report for every guardian. Safe to run repeatedly.

    Deduped on the month rather than the day, so a cron that fires nightly
    through the first week of the month sends one report, not seven.

    A child with no guardian linked produces nothing rather than an orphan
    notification: this document is addressed to a household, and there is no
    sensible fallback recipient for a report about a child.
    """
    from . import notifications

    today = today or date.today()
    start, _ = last_complete_month(today)
    made = 0

    pairs = conn.execute(
        "SELECT DISTINCT g.guardian_id, g.athlete_id FROM guardians g "
        "JOIN users a ON a.id = g.athlete_id "
        "JOIN users p ON p.id = g.guardian_id "
        "WHERE a.role = 'athlete' AND a.active = 1 AND p.active = 1"
    ).fetchall()

    for pair in pairs:
        report = build(conn, int(pair["athlete_id"]), today)
        if report is None:
            continue
        if notifications.enqueue(
            conn,
            int(pair["guardian_id"]),
            notifications.Kind.GUARDIAN_DIGEST,
            subject_line(report),
            report.headline,
            link="/app/parent.html",
            dedupe_key=f"parent_report:{pair['athlete_id']}:{start.isoformat()}",
            about_athlete_id=int(pair["athlete_id"]),
            # Already addressed to the guardian. Mirroring would post a report
            # written for a parent into the child's own alerts, where "a few
            # sessions rather than a routine" reads very differently.
            mirror=False,
        ):
            made += 1
    return made
