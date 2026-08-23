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
) -> int | None:
    """Record a notification. Returns its id, or None if it was a duplicate.

    Duplicate suppression is the whole reason `dedupe_key` exists: generators
    are expected to run repeatedly over the same state.
    """
    key = dedupe_key or f"{kind}:{_now().date().isoformat()}"
    try:
        cur = conn.execute(
            "INSERT INTO notifications(user_id, kind, title, body, link, created_at, dedupe_key) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, kind, title, body, link, _iso(_now()), key),
        )
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        # Already sent this exact nudge to this user.
        return None


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


def run_all(conn: sqlite3.Connection, today: date | None = None) -> dict[str, int]:
    """Every scheduled generator. Safe to run repeatedly."""
    return {
        "streak_warnings": generate_streak_warnings(conn, today),
        "assignment_reminders": generate_assignment_reminders(conn, today),
        "rest_nudges": generate_rest_nudges(conn, today),
        "inactive": notify_inactive(conn, today=today),
    }
