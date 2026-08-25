"""Athletes the camera was not built for.

Pose estimation assumes a body with two arms, two legs, and a typical range
of motion at every joint. That assumption is baked into every layer of this
product: the counter reads elbow angles, form scoring marks a rep against a
target range, the off-hand comparison assumes two comparable sides, and the
integrity layer treats an unusual movement pattern as evidence of cheating.

For an athlete who moves differently, each of those becomes a small insult
delivered by software. The form score says their range is short. The off-hand
gap says their weak side is failing. And the integrity check -- the worst of
them -- can reject a real session as fabricated because the movement did not
look like the movement it expected.

Saying nothing about this is not neutral. A product that quietly scores an
adaptive athlete as a deficient typical athlete has taken a position; it has
just not admitted to it.

**The framing is deliberate and load-bearing.** This is not a disability flag
and nothing here records a diagnosis. It records that *our camera analysis
does not fit how this athlete trains* -- a limitation of the tool, stated as
one. The copy says so in those words everywhere it appears, because a child
reading their own settings screen should find a sentence about the app's
limits and not about their body.

What it changes:

- **Form scoring goes silent, not to zero.** A score of 34 out of 100 against
  a range their body does not have is worse than no score. They keep counts,
  streaks and consistency, which measure turning up.
- **The off-hand comparison switches off.** Nothing here should tell a child
  their weaker side is a problem to fix when the difference is not a training
  gap.
- **Integrity never auto-rejects them.** A held session gets a person; a
  rejected one gets a child told they cheated. Where the usual rules would
  reject, this holds for review instead, and the note says why so a coach
  reading the queue is not left guessing.
- **Peer comparison drops to their own history.** They are not a poor version
  of the pool; the pool is simply not theirs.
- **They can log a session the camera could not count.** If the analysis
  cannot see the work, the work still happened. Self-reported sessions are
  marked as such for ever, count toward streaks and participation, and are
  kept out of every statistic that would be corrupted by a number nobody
  measured.

What it does not change: the load budgets, the wellness ladder, and the
recognition messages all apply unchanged, because none of them depend on a
typical movement pattern.

The honest limit, stated in the README too: this makes the product usable and
fair. It does not make the pose counter work for a movement it cannot see,
and no setting here can.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class AdaptiveError(Exception):
    pass


@dataclass(frozen=True)
class Accommodation:
    key: str
    label: str
    #: Written about the tool, never about the athlete.
    detail: str


#: Chosen separately, because they are separate facts. An athlete who trains
#: seated may still have a perfectly symmetric upper body; one with asymmetric
#: limb function may be counted fine by the camera.
ACCOMMODATIONS: tuple[Accommodation, ...] = (
    Accommodation(
        "no_form_score",
        "Do not score technique from the camera",
        "Our form scoring compares a rep against a typical range of motion. "
        "Where that comparison does not fit, the score is not shown at all "
        "rather than shown as a low one.",
    ),
    Accommodation(
        "no_side_comparison",
        "Do not compare left and right",
        "The off-hand comparison assumes two sides that should match. Turning "
        "this off removes it from this athlete's screens and from their "
        "coach's.",
    ),
    Accommodation(
        "self_report",
        "Let this athlete log a session the camera could not count",
        "If our analysis cannot see the work, the work still happened. These "
        "sessions are marked as self-reported, count toward streaks and "
        "participation, and are kept out of any statistic that needs a "
        "measured number.",
    ),
    Accommodation(
        "own_history_only",
        "Compare only against their own history",
        "Peer benchmarks are built from athletes the camera reads the usual "
        "way. Where that is not a fair pool, this athlete is measured against "
        "themselves instead.",
    ),
)
BY_KEY = {a.key: a for a in ACCOMMODATIONS}

#: Applied whenever any accommodation is on, and not separately switchable.
#: A held session gets a person; a rejected one gets a child told they
#: cheated, and that must not happen because a movement looked unfamiliar.
NEVER_AUTO_REJECT = True

#: The sentence an athlete reads on their own settings screen.
ATHLETE_NOTE = (
    "Some of this app's camera analysis assumes a particular way of moving, "
    "and it does not fit how you train. That is a limit of our tool, not of "
    "you. Your counts, your streak and your consistency all work exactly the "
    "same."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Profile:
    athlete_id: int
    accommodations: frozenset[str] = frozenset()
    note: str = ""
    set_by_name: str = ""

    @property
    def active(self) -> bool:
        return bool(self.accommodations)

    def has(self, key: str) -> bool:
        return key in self.accommodations

    @property
    def scores_form(self) -> bool:
        return not self.has("no_form_score")

    @property
    def compares_sides(self) -> bool:
        return not self.has("no_side_comparison")

    @property
    def may_self_report(self) -> bool:
        return self.has("self_report")

    @property
    def compares_to_peers(self) -> bool:
        return not self.has("own_history_only")

    @property
    def never_auto_reject(self) -> bool:
        """Any accommodation at all buys this. It is not a separate choice."""
        return self.active and NEVER_AUTO_REJECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "athlete_id": self.athlete_id,
            "active": self.active,
            "accommodations": sorted(self.accommodations),
            "options": [
                {"key": a.key, "label": a.label, "detail": a.detail,
                 "on": a.key in self.accommodations}
                for a in ACCOMMODATIONS
            ],
            "note": self.note,
            "set_by_name": self.set_by_name,
            "athlete_note": ATHLETE_NOTE if self.active else "",
            "never_auto_reject": self.never_auto_reject,
        }


def get(conn: sqlite3.Connection, athlete_id: int) -> Profile:
    row = conn.execute(
        "SELECT accommodations, note, set_by_name FROM adaptive_profiles "
        "WHERE athlete_id = ?",
        (athlete_id,),
    ).fetchone()
    if row is None:
        return Profile(athlete_id=athlete_id)
    keys = frozenset(
        k for k in (row["accommodations"] or "").split(",") if k in BY_KEY
    )
    return Profile(
        athlete_id=athlete_id, accommodations=keys,
        note=row["note"] or "", set_by_name=row["set_by_name"] or "",
    )


def set_profile(
    conn: sqlite3.Connection,
    athlete_id: int,
    accommodations: list[str],
    *,
    set_by: int | None = None,
    set_by_name: str = "",
    note: str = "",
) -> Profile:
    """Record which parts of the analysis do not fit this athlete.

    Nothing here is a diagnosis and the free-text note is deliberately about
    logistics rather than a condition -- a coach writing "uses a chair for
    lower-body work" is describing training, and this table is not the place
    for anything more than that.
    """
    unknown = [k for k in accommodations if k not in BY_KEY]
    if unknown:
        raise AdaptiveError(f"unknown accommodation: {unknown[0]}")

    keys = ",".join(sorted(set(accommodations)))
    conn.execute(
        "INSERT INTO adaptive_profiles(athlete_id, accommodations, note, "
        "  set_by, set_by_name, updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(athlete_id) DO UPDATE SET "
        "  accommodations = excluded.accommodations, note = excluded.note, "
        "  set_by = excluded.set_by, set_by_name = excluded.set_by_name, "
        "  updated_at = excluded.updated_at",
        (athlete_id, keys, note.strip()[:300], set_by,
         set_by_name.strip()[:80], _now()),
    )
    conn.commit()
    return get(conn, athlete_id)


def clear(conn: sqlite3.Connection, athlete_id: int) -> None:
    conn.execute(
        "DELETE FROM adaptive_profiles WHERE athlete_id = ?", (athlete_id,))
    conn.commit()


def soften_verdict(result, profile: Profile):
    """Turn a rejection into a review for an athlete the camera misreads.

    The single most important thing in this module. An unusual movement
    pattern scores badly on checks written around a typical one, and the
    difference between "held for a coach to look at" and "rejected" is the
    difference between a conversation and a child being told by software that
    they cheated.

    The score is left exactly as it was. Nothing here pretends the session
    looked normal -- it changes what happens next, and says why.
    """
    if not profile.never_auto_reject or result.status != "rejected":
        return result
    result.status = "review"
    result.notes.append(
        "Held for a person rather than rejected: this athlete's profile says "
        "our movement analysis does not fit how they train, so an unusual "
        "pattern here is expected and is not evidence of anything."
    )
    return result
