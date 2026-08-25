"""Nudges: generation, storage, and delivery.

Every streak mechanic is really a notification mechanic. The app already knows
when a streak is about to lapse and never tells anyone, which makes the streak
decorative.

Two deliberate separations here:

  * **Generation is separate from delivery.** Rules produce notification rows;
    channels ship them. The in-app feed therefore works with no third-party
    service configured at all, and adding Web Push or email later changes
    nothing about the rules.
  * **Every notification carries a dedupe key.** A cron that runs hourly must
    not send "your streak is at risk" twelve times. The key is unique per user,
    so re-running the generator is safe and idempotent.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import wellness
from .config import CONFIG
from .scoring import compute_streak

log = logging.getLogger(__name__)


class Kind:
    STREAK_AT_RISK = "streak_at_risk"
    ASSIGNMENT_NEW = "assignment_new"
    ASSIGNMENT_DUE = "assignment_due"
    ASSIGNMENT_DONE = "assignment_done"
    BADGE = "badge"
    COACH_MESSAGE = "coach_message"
    INACTIVE = "inactive"
    REST_DAY = "rest_day"
    GUARDIAN_DIGEST = "guardian_digest"
    DISCOMFORT = "discomfort"
    COACH_DIGEST = "coach_digest"
    RECOGNITION = "recognition"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def enqueue(
    conn: sqlite3.Connection,
    user_id: int,
    kind: str,
    title: str,
    body: str = "",
    *,
    link: str = "",
    dedupe_key: str | None = None,
    from_name: str = "",
    about_athlete_id: int | None = None,
    mirror: bool = True,
) -> int | None:
    """Record a notification. Returns its id, or None if it was a duplicate.

    Duplicate suppression is the whole reason `dedupe_key` exists: generators
    are expected to run repeatedly over the same state.

    **Every message an athlete receives is copied to their guardians**, and
    that happens here rather than at each call site. Putting it in the one
    function every notification passes through is the difference between a
    rule and an intention: a new kind of message added next year inherits it
    without anyone remembering to.
    """
    key = dedupe_key or f"{kind}:{_now().date().isoformat()}"
    about = about_athlete_id
    if about is None:
        row = conn.execute(
            "SELECT role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is not None and row["role"] == "athlete":
            about = user_id
    try:
        cur = conn.execute(
            "INSERT INTO notifications(user_id, kind, title, body, link, created_at, "
            "dedupe_key, about_athlete_id, is_copy, from_name) "
            "VALUES (?,?,?,?,?,?,?,?,0,?)",
            (user_id, kind, title, body, link, _iso(_now()), key, about, from_name),
        )
        made = int(cur.lastrowid)
    except sqlite3.IntegrityError:
        # Already sent this exact nudge to this user.
        return None

    if mirror and about == user_id:
        _mirror_to_guardians(conn, user_id, kind, title, body, key, from_name)
    conn.commit()
    return made


def _mirror_to_guardians(
    conn: sqlite3.Connection,
    athlete_id: int,
    kind: str,
    title: str,
    body: str,
    key: str,
    from_name: str,
) -> int:
    """Give every guardian a copy of what their athlete just received.

    The copy is marked as one and points at the parent portal rather than the
    athlete's screen, so a parent reads it as "here is what your child was
    sent" rather than as something addressed to them.
    """
    sent = 0
    for row in conn.execute(
        "SELECT guardian_id FROM guardians WHERE athlete_id = ?", (athlete_id,)
    ).fetchall():
        try:
            conn.execute(
                "INSERT INTO notifications(user_id, kind, title, body, link, created_at, "
                "dedupe_key, about_athlete_id, is_copy, from_name) "
                "VALUES (?,?,?,?,?,?,?,?,1,?)",
                (row["guardian_id"], kind, title, body, "/parent", _iso(_now()),
                 f"copy:{athlete_id}:{key}", athlete_id, from_name),
            )
            sent += 1
        except sqlite3.IntegrityError:
            continue
    return sent


def unread_count(conn: sqlite3.Connection, user_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
            (user_id,),
        ).fetchone()["n"]
    )


def feed(conn: sqlite3.Connection, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, kind, title, body, link, created_at, read_at "
            "FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
    ]


def mark_read(conn: sqlite3.Connection, user_id: int, notification_id: int | None = None) -> int:
    """Mark one notification read, or all of them when no id is given."""
    if notification_id is None:
        cur = conn.execute(
            "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
            (_iso(_now()), user_id),
        )
    else:
        cur = conn.execute(
            "UPDATE notifications SET read_at = ? WHERE user_id = ? AND id = ? AND read_at IS NULL",
            (_iso(_now()), user_id, notification_id),
        )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Delivery channels
# ---------------------------------------------------------------------------

@dataclass
class Payload:
    id: int
    user_id: int
    kind: str
    title: str
    body: str
    link: str


class Channel(ABC):
    """A way to get a notification onto a phone."""

    @abstractmethod
    def send(self, conn: sqlite3.Connection, payload: Payload) -> bool:
        """Return True if delivered. False means try again later."""


class LogChannel(Channel):
    """Default channel: writes to the log.

    Deliberately the default so the whole notification path is exercised in
    development and tests without credentials for anything.
    """

    def send(self, conn: sqlite3.Connection, payload: Payload) -> bool:
        log.info("notify user=%s [%s] %s -- %s", payload.user_id, payload.kind,
                 payload.title, payload.body)
        return True


class WebPushChannel(Channel):
    """Web Push via VAPID.

    Requires `pywebpush` and a VAPID keypair. Absent either, this degrades to a
    no-op that leaves the notification unpushed rather than crashing the
    generator -- the in-app feed still has it.
    """

    def __init__(self, vapid_private_key: str, vapid_claims_email: str) -> None:
        self.private_key = vapid_private_key
        self.claims_email = vapid_claims_email

    def send(self, conn: sqlite3.Connection, payload: Payload) -> bool:
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            log.warning("pywebpush is not installed; skipping push delivery")
            return False

        subs = conn.execute(
            "SELECT id, endpoint, p256dh, auth FROM push_subscriptions "
            "WHERE user_id = ? AND failed_at IS NULL",
            (payload.user_id,),
        ).fetchall()
        if not subs:
            return False

        data = json.dumps({
            "title": payload.title,
            "body": payload.body,
            "link": payload.link or "/app/capture.html",
        })
        delivered = False
        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                    },
                    data=data,
                    vapid_private_key=self.private_key,
                    vapid_claims={"sub": f"mailto:{self.claims_email}"},
                )
                delivered = True
            except WebPushException as exc:
                # A 404/410 means the browser dropped the subscription -- the
                # athlete uninstalled or cleared data. Retiring it keeps the
                # table from filling with dead endpoints.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (404, 410):
                    conn.execute(
                        "UPDATE push_subscriptions SET failed_at = ? WHERE id = ?",
                        (_iso(_now()), sub["id"]),
                    )
                    conn.commit()
                else:
                    log.warning("push failed for user %s: %s", payload.user_id, exc)
        return delivered


def send_coach_digests(
    conn: sqlite3.Connection, today: date | None = None, dry_run: bool = False
) -> dict[str, int]:
    """Compose the weekly digest for every coach and queue it for delivery.

    Scoped to what each person is responsible for. A director gets the
    programme-wide numbers; a coach assigned to JV gets JV's, because folding
    varsity's participation into a JV coach's email makes the number they are
    supposed to move meaningless -- and it hands them data about children they
    are not responsible for.

    Queues rather than sends: delivery is a separate step that retries, so a
    mail server having a bad Monday does not cost the week's digest.
    """
    from . import digest as digest_mod
    from . import mailer

    today = today or _now().date()
    start, _ = digest_mod.last_complete_week(today)
    week = start.isoformat()

    dashboard = (
        f"{CONFIG.app_base_url.rstrip('/')}/app/coach.html"
        if CONFIG.app_base_url else ""
    )
    stats = {"composed": 0, "queued": 0, "not_queued": 0}

    staff = conn.execute(
        "SELECT DISTINCT u.id, m.org_id, m.role, u.display_name, u.email "
        "FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.role IN ('coach', 'director') AND m.active = 1 AND u.active = 1"
    ).fetchall()

    for member in staff:
        # Directors, and coaches with no assignment, see the whole programme.
        teams = [
            r["team_id"]
            for r in conn.execute(
                "SELECT ts.team_id FROM team_staff ts JOIN teams t ON t.id = ts.team_id "
                "WHERE ts.user_id = ? AND t.org_id = ?",
                (member["id"], member["org_id"]),
            )
        ] if member["role"] == "coach" else []

        scopes: list[int | None] = teams or [None]

        for team_id in scopes:
            report = digest_mod.compute(
                conn, member["org_id"], team_id=team_id, today=today
            )
            subject = digest_mod.subject_line(report)
            stats["composed"] += 1

            # The in-app copy always lands, so a coach with no email on file
            # still gets the digest.
            enqueue(
                conn, member["id"], Kind.COACH_DIGEST, subject,
                report.headline, link="/app/coach.html",
                dedupe_key=f"{Kind.COACH_DIGEST}:{week}:{team_id or 'org'}",
            )

            if dry_run:
                stats["not_queued"] += 1
                continue

            unsubscribe = mailer.unsubscribe_url(member["id"], mailer.Kind.COACH_DIGEST)
            queued = mailer.enqueue(
                conn,
                to_email=member["email"] or "",
                subject=subject,
                html=digest_mod.render_html(report, dashboard, unsubscribe_url=unsubscribe),
                text=digest_mod.render_text(report, dashboard, unsubscribe_url=unsubscribe),
                kind=mailer.Kind.COACH_DIGEST,
                dedupe_key=f"digest:{member['id']}:{week}:{team_id or 'org'}",
                user_id=member["id"],
            )
            stats["queued" if queued else "not_queued"] += 1

    return stats


def dispatch(conn: sqlite3.Connection, channels: list[Channel], limit: int = 200) -> int:
    """Ship notifications that have not been pushed yet. Returns the count."""
    rows = conn.execute(
        "SELECT id, user_id, kind, title, body, link FROM notifications "
        "WHERE pushed_at IS NULL ORDER BY created_at LIMIT ?",
        (limit,),
    ).fetchall()

    sent = 0
    for row in rows:
        payload = Payload(
            id=row["id"], user_id=row["user_id"], kind=row["kind"],
            title=row["title"], body=row["body"], link=row["link"],
        )
        if any(channel.send(conn, payload) for channel in channels):
            conn.execute(
                "UPDATE notifications SET pushed_at = ? WHERE id = ?",
                (_iso(_now()), payload.id),
            )
            sent += 1
    conn.commit()
    return sent


def save_subscription(
    conn: sqlite3.Connection, user_id: int, endpoint: str, p256dh: str, auth: str
) -> None:
    """Store (or revive) a browser push subscription."""
    conn.execute(
        "INSERT INTO push_subscriptions(user_id, endpoint, p256dh, auth, created_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, "
        "  p256dh=excluded.p256dh, auth=excluded.auth, failed_at=NULL",
        (user_id, endpoint, p256dh, auth, _iso(_now())),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Generation rules
# ---------------------------------------------------------------------------

def generate_streak_warnings(conn: sqlite3.Connection, today: date | None = None) -> int:
    """Warn athletes whose streak lapses if they do nothing today.

    Only fires for streaks worth protecting -- warning someone about a one-day
    streak is noise, and noise is how notification permission gets revoked.
    """
    today = today or _now().date()
    made = 0
    athletes = conn.execute(
        "SELECT id, display_name FROM users WHERE role = 'athlete' AND active = 1"
    ).fetchall()

    for athlete in athletes:
        days = [
            date.fromisoformat(r["day"])
            for r in conn.execute(
                "SELECT day FROM xp_ledger WHERE athlete_id = ? GROUP BY day "
                "HAVING SUM(amount) >= ? ORDER BY day",
                (athlete["id"], CONFIG.scoring.streak_min_xp),
            )
        ]
        streak = compute_streak(days, today)
        if streak.current >= 3 and streak.at_risk:
            if enqueue(
                conn,
                athlete["id"],
                Kind.STREAK_AT_RISK,
                f"{streak.current}-day streak on the line",
                "Train today to keep it going.",
                link="/app/capture.html",
                dedupe_key=f"{Kind.STREAK_AT_RISK}:{today.isoformat()}",
            ):
                made += 1
    return made


def generate_assignment_reminders(conn: sqlite3.Connection, today: date | None = None) -> int:
    """Remind athletes about assignments coming due that they have not finished."""
    from . import assignments as assignments_mod

    today = today or _now().date()
    made = 0
    athletes = conn.execute(
        "SELECT id FROM users WHERE role = 'athlete' AND active = 1"
    ).fetchall()

    for athlete in athletes:
        for item in assignments_mod.for_athlete(conn, athlete["id"], today=today):
            if item["progress"]["complete"]:
                continue
            remaining = item["days_remaining"]
            # Two touches only: a heads-up with two days left, and a final one
            # on the due date. Anything more trains people to ignore the app.
            if remaining not in (0, 2):
                continue
            when = "today" if remaining == 0 else f"in {remaining} days"
            if enqueue(
                conn,
                athlete["id"],
                Kind.ASSIGNMENT_DUE,
                f"{item['title']} is due {when}",
                _assignment_gap(item),
                link="/app/capture.html",
                dedupe_key=f"{Kind.ASSIGNMENT_DUE}:{item['id']}:{remaining}",
            ):
                made += 1
    return made


def _assignment_gap(item: dict[str, Any]) -> str:
    """Say exactly what is still outstanding, not just that something is."""
    progress = item["progress"]
    gaps: list[str] = []
    if not progress["reps_met"]:
        gaps.append(f"{item['target_reps'] - progress['reps_done']} more reps")
    if not progress["sessions_met"]:
        left = item["target_sessions"] - progress["sessions_done"]
        gaps.append(f"{left} more session{'s' if left != 1 else ''}")
    if not progress["offhand_met"]:
        gaps.append(f"{item['min_offhand']:.0%} off-hand needed")
    return ", ".join(gaps) or "Nearly there."


def notify_new_assignment(conn: sqlite3.Connection, assignment_id: int) -> int:
    """Tell an assignment's athletes it exists. Called at creation time."""
    from . import assignments as assignments_mod

    assignment = assignments_mod.get(conn, assignment_id)
    if assignment is None:
        return 0

    parts = []
    if assignment.target_reps:
        parts.append(f"{assignment.target_reps} reps")
    if assignment.target_sessions:
        parts.append(f"{assignment.target_sessions} sessions")
    if assignment.min_offhand:
        parts.append(f"{assignment.min_offhand:.0%} off-hand")
    detail = " · ".join(parts)

    made = 0
    for athlete in assignments_mod.roster_for(conn, assignment):
        if enqueue(
            conn,
            athlete["id"],
            Kind.ASSIGNMENT_NEW,
            f"New assignment: {assignment.title}",
            f"{assignment.drill_name} — {detail}. Due {assignment.due_on}.",
            link="/app/capture.html",
            dedupe_key=f"{Kind.ASSIGNMENT_NEW}:{assignment_id}",
        ):
            made += 1
    return made


def notify_badges(conn: sqlite3.Connection, athlete_id: int, badge_keys: list[str]) -> int:
    """Celebrate newly earned badges."""
    from .scoring import BADGES_BY_KEY

    made = 0
    for key in badge_keys:
        badge = BADGES_BY_KEY.get(key)
        if badge is None:
            continue
        if enqueue(
            conn,
            athlete_id,
            Kind.BADGE,
            f"Badge unlocked: {badge.name}",
            badge.description,
            link="/app/capture.html",
            dedupe_key=f"{Kind.BADGE}:{key}",
        ):
            made += 1
    return made


def broadcast(
    conn: sqlite3.Connection, team_id: int, title: str, body: str, sender_id: int
) -> int:
    """A coach message to a whole team."""
    made = 0
    stamp = _iso(_now())
    for athlete in conn.execute(
        "SELECT u.id FROM users u JOIN team_members tm ON tm.user_id = u.id "
        "WHERE tm.team_id = ? AND u.role = 'athlete' AND u.active = 1",
        (team_id,),
    ):
        if enqueue(
            conn, athlete["id"], Kind.COACH_MESSAGE, title, body,
            dedupe_key=f"{Kind.COACH_MESSAGE}:{sender_id}:{stamp}",
        ):
            made += 1
    return made


def notify_inactive(conn: sqlite3.Connection, quiet_days: int = 7, today: date | None = None) -> int:
    """Nudge athletes who have gone quiet, once per stretch of silence."""
    today = today or _now().date()
    cutoff = _iso(_now() - timedelta(days=quiet_days))
    made = 0
    rows = conn.execute(
        """
        SELECT u.id, MAX(COALESCE(s.completed_at, s.submitted_at)) AS last
        FROM users u
        LEFT JOIN sessions s ON s.athlete_id = u.id AND s.status = 'counted'
        WHERE u.role = 'athlete' AND u.active = 1
        GROUP BY u.id
        HAVING last IS NOT NULL AND last < ?
        """,
        (cutoff,),
    ).fetchall()

    for row in rows:
        # Keyed to the week so a long absence produces a weekly nudge, not a
        # daily one.
        week = today.isocalendar()
        if enqueue(
            conn,
            row["id"],
            Kind.INACTIVE,
            "Your team is still putting in work",
            f"It's been over {quiet_days} days. Ten minutes of wall ball counts.",
            link="/app/capture.html",
            dedupe_key=f"{Kind.INACTIVE}:{week[0]}-W{week[1]}",
        ):
            made += 1
    return made


def generate_rest_nudges(conn: sqlite3.Connection, today: date | None = None) -> int:
    """Tell athletes carrying high load to take a day, and that it is free.

    This is the counterweight to everything else in the app. Streaks, XP, and
    leaderboards all push training every day; without this the athlete with the
    most to protect is the one most pressured to train through fatigue.
    """
    from .store import Store

    today = today or _now().date()
    store = Store(conn)
    made = 0
    for row in conn.execute(
        "SELECT id FROM users WHERE role = 'athlete' AND active = 1"
    ).fetchall():
        state = store.load_state(row["id"])
        if not (state.rest_recommended or state.zone == "high"):
            continue

        body = (
            f"{state.consecutive_days} days straight. Take today off -- "
            "it still counts toward your streak."
        )
        if enqueue(
            conn,
            row["id"],
            Kind.REST_DAY,
            "Time for a recovery day",
            body,
            link="/app/capture.html",
            dedupe_key=f"{Kind.REST_DAY}:{today.isoformat()}",
        ):
            made += 1
    return made


def generate_guardian_digests(
    conn: sqlite3.Connection, today: date | None = None
) -> int:
    """A weekly summary for each parent.

    Parents will not log into a dashboard, so the dashboard goes to them. Framed
    around what their child did rather than where they rank -- there is no
    leaderboard in the parent view, and there is none in this either.
    """
    from .store import Store

    today = today or _now().date()
    year, week, _ = today.isocalendar()
    store = Store(conn)
    made = 0

    guardians = conn.execute(
        "SELECT id FROM users WHERE role = 'guardian' AND active = 1"
    ).fetchall()

    for guardian in guardians:
        summary = store.guardian_summary(guardian["id"])
        athletes = summary["athletes"]
        if not athletes:
            continue

        lines = []
        concerns = 0
        for athlete in athletes:
            name = athlete["display_name"].split()[0]
            if athlete["week_sessions"]:
                line = (
                    f"{name}: {athlete['week_sessions']} sessions, "
                    f"{athlete['week_reps']:,} reps"
                )
                if athlete["streak"] >= 3:
                    line += f", {athlete['streak']}-day streak"
            else:
                line = f"{name}: no sessions logged this week"
            if athlete["load_advisories"]:
                concerns += 1
                line += " — worth a look at their rest"
            lines.append(line)

        if enqueue(
            conn,
            guardian["id"],
            Kind.GUARDIAN_DIGEST,
            "This week's training" + (" — one thing to check" if concerns else ""),
            " · ".join(lines),
            link="/app/parent.html",
            dedupe_key=f"{Kind.GUARDIAN_DIGEST}:{year}-W{week}",
        ):
            made += 1
    return made


def run_all(conn: sqlite3.Connection, today: date | None = None) -> dict[str, int]:
    """Every scheduled generator. Safe to run repeatedly."""
    return {
        "streak_warnings": generate_streak_warnings(conn, today),
        "assignment_reminders": generate_assignment_reminders(conn, today),
        "rest_nudges": generate_rest_nudges(conn, today),
        "inactive": notify_inactive(conn, today=today),
        "guardian_digests": generate_guardian_digests(conn, today),
        # Deduped on the month, so a nightly cron sends one, not thirty.
        "parent_reports": _parent_reports(conn, today),
    }


def notify_discomfort(
    conn: sqlite3.Connection,
    athlete_id: int,
    report: "wellness.Report",
    assessment: "wellness.Assessment",
) -> int:
    """Tell this athlete's guardians that something needs an adult.

    Sent on the assessment, not on the severity: a "niggle" with swelling
    escalates and a "sore" thigh does not, and that judgement belongs in one
    place rather than being re-derived by every caller.

    The athlete's own note is not included. A guardian can read it in the app,
    where they are logged in as themselves -- a push notification is read on a
    lock screen in front of whoever is standing there.
    """
    if not assessment.tell_guardian:
        return 0

    athlete = conn.execute(
        "SELECT display_name FROM users WHERE id = ?", (athlete_id,)
    ).fetchone()
    name = (athlete["display_name"] if athlete else "Your athlete").split()[0]
    side = f"{report.side} " if report.side in ("left", "right") else ""
    where = f"{side}{report.area.label.lower()}".strip()

    sent = 0
    for row in conn.execute(
        "SELECT guardian_id FROM guardians WHERE athlete_id = ?", (athlete_id,)
    ).fetchall():
        created = enqueue(
            conn,
            row["guardian_id"],
            Kind.DISCOMFORT,
            f"{name} reported their {where}",
            assessment.headline,
            link="/parent",
            # One per area per day: an athlete correcting a typo in their own
            # report should not buzz a parent's phone twice.
            dedupe_key=f"discomfort:{athlete_id}:{report.area.key}:{report.reported_on}",
        )
        sent += 1 if created else 0
    return sent


def purge_old_wellness(conn: sqlite3.Connection, today: "date | None" = None) -> int:
    """Delete resolved reports past the retention window.

    Health data about a child is not kept because it might be interesting
    later. Only resolved rows are eligible -- an open report is still a live
    thing about a body that still hurts.
    """
    cutoff = wellness.purge_cutoff(today)
    with conn:
        removed = conn.execute(
            "DELETE FROM discomfort_reports WHERE resolved_on IS NOT NULL "
            "AND resolved_on < ?",
            (cutoff,),
        ).rowcount
        removed += conn.execute(
            "DELETE FROM wellness_checkins WHERE day < ?", (cutoff,)
        ).rowcount
    return removed


def purge_expired_clips(conn: sqlite3.Connection, now: "datetime | None" = None) -> int:
    """Delete shared clips past their expiry.

    A child's video is kept for as long as it is useful for feedback and not
    a day longer. Runs from the same cron as everything else.
    """
    cutoff = _iso(now or _now())
    with conn:
        return conn.execute(
            "DELETE FROM shared_clips WHERE expires_at < ?", (cutoff,)
        ).rowcount


def _parent_reports(conn: sqlite3.Connection, today: date | None) -> int:
    """Imported here rather than at module scope: parent_report reads this
    module for `enqueue`, and a top-level import would close the loop."""
    from . import parent_report

    return parent_report.generate(conn, today)
