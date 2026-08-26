"""Second looks: an athlete going back to a clip, and what a coach sees of it.

Watching a clip twice is the film module working, not failing. A fourteen-year-
old who reruns the slide-and-recover clip before Tuesday's practice because they
want to be sure is doing exactly what film study is for, and every instinct a
piece of software has about repeated views -- that they mean confusion, that
they are worth flagging, that a number should go down -- is wrong here.

So this module exists to carry that signal to a coach *without* turning it into
an accusation. Three rules shape everything below.

**The clip is the subject, never the athlete.** The headline a coach gets is
"six athletes went back to Sliding and Recovery", which is a practice plan. The
per-athlete list sits underneath it, and there is no ranking of who rewatched
most -- that list would be read as a list of the kids who are slow, and it
would be read that way within a week of shipping.

**A second look is never worth XP and never costs any.** The moment it pays,
somebody farms it; the moment it costs, nobody does it. It sits outside the
economy entirely, which is also the honest description of what it is.

**The athlete is told.** `NOTICE` below is shown on the film screen, in the
athlete's own words, before any of this is recorded. This product does not put
silent telemetry on a child anywhere else and will not start here -- and a kid
who finds out later that rewatching was reported is a kid who stops rewatching.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

#: Passes at which a repeat view becomes worth mentioning at all. One is just
#: watching it.
SECOND_LOOK = 2

#: ...and the point at which it is worth a coach's five minutes rather than a
#: coach's glance.
THIRD_LOOK = 3

#: How many athletes on one clip turns an individual habit into a squad-wide
#: signal about the material.
SQUAD_SIGNAL = 3

#: Shown to the athlete on the film screen, before anything here is recorded.
#: Deliberately plain: the point is that they know, not that they were told.
NOTICE = (
    "Watch anything here as many times as you want -- that is what it is for. "
    "Your coach can see when you have gone back for another look, so going "
    "over something twice reads as you making sure, which is exactly how they "
    "will take it."
)

#: The Spanish of it, for the same screen. Kept beside the English so the two
#: cannot drift.
NOTICE_ES = (
    "Mira lo que quieras las veces que quieras: para eso está. Tu entrenador "
    "puede ver cuándo has vuelto a mirar algo, así que repasar algo dos veces "
    "se ve como que te estás asegurando, que es justo como lo va a tomar."
)


@dataclass(frozen=True)
class AthleteLook:
    """One athlete's history with one clip."""

    athlete_id: int
    athlete_name: str
    looks: int
    days: int
    first_on: str
    last_on: str
    #: Whether the comprehension question has been answered correctly. None
    #: when the clip never carried one, which is not the same as unanswered.
    settled: bool | None

    @property
    def phrase(self) -> str:
        """How this reads to a coach, in words that describe the behaviour."""
        if self.looks >= THIRD_LOOK:
            return "kept going back to it"
        return "took a second look"

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "athlete_name": self.athlete_name,
            "looks": self.looks,
            "days": self.days,
            "first_on": self.first_on,
            "last_on": self.last_on,
            "settled": self.settled,
            "phrase": self.phrase,
        }


@dataclass(frozen=True)
class ClipLooks:
    """One clip, and everyone who went back to it."""

    clip_id: int
    title: str
    focus: str
    athletes: list[AthleteLook]

    @property
    def looks(self) -> int:
        return sum(a.looks for a in self.athletes)

    @property
    def unsettled(self) -> int:
        """Came back and still has the question wrong.

        The one number here that genuinely points at the material rather than
        at the athletes: a clip several people reran and still did not land is
        a clip that is not doing its job, or a concept that needs a coach.
        """
        return sum(1 for a in self.athletes if a.settled is False)

    @property
    def note(self) -> str:
        """What to do about it, phrased as practice rather than as a verdict."""
        n = len(self.athletes)
        if self.unsettled >= SECOND_LOOK:
            return (
                f"{self.unsettled} of the {n} who went back still have the "
                "question wrong. This one is worth walking through on the "
                "field rather than leaving on a screen."
            )
        if n >= SQUAD_SIGNAL:
            return (
                f"{n} athletes went back to this on their own. That is usually "
                "the topic to spend five minutes on at the next practice."
            )
        return (
            "Went over it again to be sure. Worth knowing they are the ones "
            "doing that, and worth saying so."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "title": self.title,
            "focus": self.focus,
            "athletes": [a.to_dict() for a in self.athletes],
            "count": len(self.athletes),
            "looks": self.looks,
            "unsettled": self.unsettled,
            "note": self.note,
        }


def for_clips(
    conn: sqlite3.Connection,
    athlete_ids: list[int],
    *,
    since: str | None = None,
    min_looks: int = SECOND_LOOK,
) -> list[ClipLooks]:
    """Second looks across a set of athletes, grouped by clip.

    Grouped by clip and not by athlete on purpose. The same rows sorted the
    other way would be a leaderboard of who needs the most help, which is a
    thing no coach asked for and no child should be on.
    """
    if not athlete_ids or min_looks < 1:
        return []

    marks = ",".join("?" * len(athlete_ids))
    params: list[Any] = list(athlete_ids)
    window = ""
    if since:
        window = " AND w.day >= ?"
        params.append(since)

    rows = conn.execute(
        "SELECT w.athlete_id, w.clip_id, u.display_name, c.title, c.focus, "
        "       SUM(w.looks) AS looks, COUNT(DISTINCT w.day) AS days, "
        "       MIN(w.day) AS first_on, MAX(w.day) AS last_on "
        "FROM clip_watches w "
        "JOIN users u ON u.id = w.athlete_id "
        "JOIN clips c ON c.id = w.clip_id "
        f"WHERE w.athlete_id IN ({marks}){window} "
        "GROUP BY w.athlete_id, w.clip_id "
        "HAVING looks >= ? "
        "ORDER BY c.title, u.display_name",
        (*params, min_looks),
    ).fetchall()

    grouped: dict[int, ClipLooks] = {}
    for row in rows:
        clip_id = int(row["clip_id"])
        entry = grouped.get(clip_id)
        if entry is None:
            entry = ClipLooks(
                clip_id=clip_id,
                title=row["title"],
                focus=row["focus"] or "",
                athletes=[],
            )
            grouped[clip_id] = entry
        entry.athletes.append(AthleteLook(
            athlete_id=int(row["athlete_id"]),
            athlete_name=row["display_name"],
            looks=int(row["looks"]),
            days=int(row["days"]),
            first_on=row["first_on"],
            last_on=row["last_on"],
            settled=_settled(conn, int(row["athlete_id"]), clip_id),
        ))

    # Most-shared first: a clip six athletes went back to is a practice plan,
    # and one athlete going back to something is a note about that athlete.
    return sorted(
        grouped.values(),
        key=lambda c: (-len(c.athletes), -c.unsettled, c.title),
    )


def _settled(conn: sqlite3.Connection, athlete_id: int, clip_id: int) -> bool | None:
    """Whether the comprehension question has landed yet.

    Reads the most recent answered watch rather than any of them: somebody who
    got it wrong, went back, and then got it right has settled it, and holding
    the first wrong answer against them would be the opposite of the point.
    """
    # `answered` holds the option they picked, not a flag -- so choosing the
    # first option stores a 0, and a truthiness test here would read every
    # athlete who picked option A as never having answered at all.
    row = conn.execute(
        "SELECT answer_ok FROM clip_watches "
        "WHERE athlete_id = ? AND clip_id = ? AND answered IS NOT NULL "
        "ORDER BY day DESC, id DESC LIMIT 1",
        (athlete_id, clip_id),
    ).fetchone()
    if row is None:
        return None
    return bool(row["answer_ok"])


def for_athlete(
    conn: sqlite3.Connection, athlete_id: int, clip_id: int
) -> int:
    """How many passes this athlete has made through this clip, ever."""
    row = conn.execute(
        "SELECT COALESCE(SUM(looks), 0) AS n FROM clip_watches "
        "WHERE athlete_id = ? AND clip_id = ?",
        (athlete_id, clip_id),
    ).fetchone()
    return int(row["n"])
