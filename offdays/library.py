"""The program's drill library: what a coach offers, and what they wrote.

Two things live here, and they answer two different complaints.

**Curation.** `drills.for_sport()` decides what a program is offered, and it
decides well: your own sport first, then the general work, and nothing from
anybody else's game. But it decides the same way for every club. A team with
no wall cannot use wall ball; a club that trains in a sports hall in February
wants the conditioning drills and not much else; a coach who has watched two
athletes hurt themselves rushing tuck jumps wants that one gone. None of that
is a defect in the default, and all of it needs a switch.

**Coach-written drills.** Every coach has a drill they run that is not in
anybody's catalog. They should be able to add it, and the honest version of
that is narrower than a text box.

The counter reads one pose signal against thresholds somebody tuned by
running video through it. No name a coach types conjures a detector. So a
custom drill here *borrows a movement*: the coach supplies the name, the
words and the setup, and picks the catalog movement it is counted as.
"Keeper Reaction Squats" is counted as squats, scores what squats score, and
is honest on both counts -- the athlete gets a real rep count, and nobody has
been told the app can see something it cannot.

The rejected alternative is worth naming, because it is the obvious one: let a
coach write a drill the athlete self-certifies. That machinery exists, gated
per athlete behind an accommodation (`adaptive.may_self_report`), for athletes
whose training this app structurally cannot see. Opening it to every coach
would make an uncounted drill the cheapest route to a streak, which is the one
thing the integrity layer exists to prevent.

A custom drill is a real `DrillSpec`, built by copying the borrowed one and
replacing what the coach chose. That matters more than it looks: thirty-five
places in this codebase look a drill up by key and expect a spec back, and a
parallel type would have needed all of them to learn about a second kind of
drill. It carries its own key, so a coach's own drill is a row in their own
reporting rather than blurred into whatever it was counted as.
"""
from __future__ import annotations

import dataclasses
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .drills import ALL_DRILLS, DRILLS_BY_KEY
from .drills.base import DrillSpec
from .drills.catalog import for_sport as catalog_for_sport


class LibraryError(Exception):
    """A coach asked for something the library cannot do."""


#: Custom drills, by key. Populated from the database and merged into the
#: catalog's own lookup so every existing call site keeps working unchanged.
#: Keys are namespaced per organization, so this staying global is safe: two
#: clubs cannot collide, and a stale entry can never be reached by the wrong
#: one.
CUSTOM: dict[str, DrillSpec] = {}

#: How many a single program may have. Not a licensing lever -- a picker with
#: two hundred entries is a picker nobody reads, and the whole argument for
#: curation is the opposite of that.
MAX_PER_ORG = 40

_SLUG = re.compile(r"[^a-z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key_for(org_id: int, name: str) -> str:
    """A stable, namespaced key for a coach's drill."""
    slug = _SLUG.sub("_", name.strip().lower()).strip("_")
    if not slug:
        raise LibraryError("that drill needs a name with letters in it")
    return f"org{org_id}_{slug}"[:60]


def _adopt(spec: DrillSpec, based_on: str) -> None:
    """Give a coach's drill everything the movement it borrows already has.

    A custom drill is not a new movement, it is an existing one wearing a
    coach's name. So it inherits that movement's cross-sport notes, its
    technique cues and its drawing. Without this an athlete opening it gets a
    blank where the "this pays off in" line goes, a form score with no fix
    attached, and no picture of what they are about to attempt -- three of the
    things this app is for, quietly missing on exactly the drills a coach
    cared enough to write.
    """
    from . import demo as demo_mod
    from . import technique as technique_mod
    from . import transfer as transfer_mod

    transfer_mod.TRANSFERS.setdefault(
        spec.key, transfer_mod.TRANSFERS.get(based_on, ()))
    if based_on in technique_mod.CUES:
        technique_mod.CUES.setdefault(spec.key, technique_mod.CUES[based_on])
    if based_on in demo_mod.DEMOS:
        demo_mod.DEMOS.setdefault(spec.key, demo_mod.DEMOS[based_on])


def _spec_from_row(row: sqlite3.Row) -> DrillSpec:
    """Build a real DrillSpec from a coach's row and the drill it borrows."""
    base = DRILLS_BY_KEY.get(row["based_on"])
    if base is None:
        raise LibraryError(f"unknown movement: {row['based_on']!r}")
    return dataclasses.replace(
        base,
        key=row["drill_key"],
        name=row["name"],
        description=row["description"] or base.description,
        setup_hint=row["setup_hint"] or base.setup_hint,
    )


def load_all(conn: sqlite3.Connection) -> int:
    """Register every active custom drill so lookups by key resolve.

    Called when a Store opens. Cheap: one query, and clubs have tens of these
    rather than thousands.
    """
    try:
        rows = conn.execute(
            "SELECT drill_key, name, description, setup_hint, based_on "
            "FROM custom_drills WHERE active = 1"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0  # a database older than this table
    count = 0
    for row in rows:
        try:
            spec = _spec_from_row(row)
        except LibraryError:
            continue  # the movement it borrowed has since been retired
        CUSTOM[spec.key] = spec
        DRILLS_BY_KEY[spec.key] = spec
        _adopt(spec, row["based_on"])
        count += 1
    return count


# ---------------------------------------------------------------------------
# What a program offers
# ---------------------------------------------------------------------------

def _prefs(conn: sqlite3.Connection, org_id: int) -> dict[str, bool]:
    try:
        rows = conn.execute(
            "SELECT drill_key, offered FROM org_drill_prefs WHERE org_id = ?",
            (org_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r["drill_key"]: bool(r["offered"]) for r in rows}


def offered(conn: sqlite3.Connection, org_id: int, sport: str) -> list[DrillSpec]:
    """The drills this program actually puts in front of its athletes.

    The default set, minus what the coach turned off, plus what they turned on
    from the wider library, plus their own. Order is preserved from the
    catalog so a club that changes nothing sees exactly what it saw before.
    """
    prefs = _prefs(conn, org_id)
    default = catalog_for_sport(sport)
    out = [d for d in default if prefs.get(d.key, True)]

    have = {d.key for d in out}
    added = [k for k, on in prefs.items() if on and k not in have]
    if added:
        out.extend(d for d in ALL_DRILLS if d.key in added)

    out.extend(customs(conn, org_id))
    return out


def customs(conn: sqlite3.Connection, org_id: int) -> list[DrillSpec]:
    """This program's own drills, newest last."""
    try:
        rows = conn.execute(
            "SELECT drill_key, name, description, setup_hint, based_on "
            "FROM custom_drills WHERE org_id = ? AND active = 1 ORDER BY id",
            (org_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for row in rows:
        try:
            out.append(_spec_from_row(row))
        except LibraryError:
            continue
    return out


def shelf(conn: sqlite3.Connection, org_id: int, sport: str) -> list[dict[str, Any]]:
    """Every drill in the catalog, and whether this program offers it.

    The coach's own view. Shows the whole library rather than only their
    sport's slice, because reaching across sports is one of the two things
    this screen is for -- a soccer club that wants the basketball defensive
    slide should be able to see that it exists.
    """
    prefs = _prefs(conn, org_id)
    default = {d.key for d in catalog_for_sport(sport)}
    rows = []
    for d in ALL_DRILLS:
        by_default = d.key in default
        on = prefs.get(d.key, by_default)
        rows.append({
            "key": d.key,
            "name": d.name,
            "sport": d.sport,
            "category": d.category.value,
            "stimulus": d.stimulus.value,
            "metric": d.metric.value,
            "description": d.description,
            "offered": on,
            "by_default": by_default,
            # So the page can say *why* a row looks the way it does rather
            # than leaving a coach to work out which switch they flipped.
            "state": ("default" if on and by_default
                      else "added" if on
                      else "hidden" if by_default
                      else "off"),
        })
    return rows


def set_offered(
    conn: sqlite3.Connection,
    org_id: int,
    drill_key: str,
    on: bool,
    sport: str,
    set_by: int | None = None,
) -> None:
    """Turn one library drill on or off for a program."""
    if drill_key not in DRILLS_BY_KEY:
        raise LibraryError(f"unknown drill: {drill_key!r}")
    by_default = drill_key in {d.key for d in catalog_for_sport(sport)}
    if on == by_default:
        # Back to the default, so stop recording an exception. A club that
        # toggles something off and on again should end up with no row rather
        # than a row that says "same as default".
        conn.execute(
            "DELETE FROM org_drill_prefs WHERE org_id = ? AND drill_key = ?",
            (org_id, drill_key),
        )
    else:
        conn.execute(
            "INSERT INTO org_drill_prefs(org_id, drill_key, offered, set_by, set_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(org_id, drill_key) DO UPDATE SET "
            "offered = excluded.offered, set_by = excluded.set_by, "
            "set_at = excluded.set_at",
            (org_id, drill_key, int(on), set_by, _now()),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# A coach's own drills
# ---------------------------------------------------------------------------

def create(
    conn: sqlite3.Connection,
    org_id: int,
    *,
    name: str,
    based_on: str,
    description: str = "",
    setup_hint: str = "",
    created_by: int | None = None,
) -> DrillSpec:
    """Add a coach's drill, counted as an existing movement."""
    name = " ".join(name.split())
    if not 2 <= len(name) <= 60:
        raise LibraryError("a drill name is between 2 and 60 characters")
    base = DRILLS_BY_KEY.get(based_on)
    if base is None:
        raise LibraryError(f"unknown movement: {based_on!r}")
    if based_on in CUSTOM:
        # Otherwise a chain of custom drills borrows a custom drill borrowing
        # a custom drill, and the thing actually being counted is three hops
        # away from anything anybody tuned.
        raise LibraryError("a custom drill has to borrow a catalog movement")

    existing = conn.execute(
        "SELECT COUNT(*) FROM custom_drills WHERE org_id = ? AND active = 1",
        (org_id,),
    ).fetchone()[0]
    if existing >= MAX_PER_ORG:
        raise LibraryError(
            f"that is {MAX_PER_ORG} custom drills, which is as many as a "
            "picker can carry and still be read. Retire one first.")

    key = key_for(org_id, name)
    clash = conn.execute(
        "SELECT active FROM custom_drills WHERE drill_key = ?", (key,)
    ).fetchone()
    if clash is not None and clash["active"]:
        raise LibraryError("this program already has a drill with that name")

    now = _now()
    if clash is not None:
        conn.execute(
            "UPDATE custom_drills SET name=?, description=?, setup_hint=?, "
            "based_on=?, created_by=?, created_at=?, active=1 WHERE drill_key=?",
            (name, description.strip(), setup_hint.strip(), based_on,
             created_by, now, key),
        )
    else:
        conn.execute(
            "INSERT INTO custom_drills(org_id, drill_key, name, description, "
            "setup_hint, based_on, created_by, created_at, active) "
            "VALUES (?,?,?,?,?,?,?,?,1)",
            (org_id, key, name, description.strip(), setup_hint.strip(),
             based_on, created_by, now),
        )
    conn.commit()

    row = conn.execute(
        "SELECT drill_key, name, description, setup_hint, based_on "
        "FROM custom_drills WHERE drill_key = ?", (key,)
    ).fetchone()
    spec = _spec_from_row(row)
    CUSTOM[spec.key] = spec
    DRILLS_BY_KEY[spec.key] = spec
    _adopt(spec, based_on)
    return spec


def retire(conn: sqlite3.Connection, org_id: int, drill_key: str) -> None:
    """Take a coach's drill off the list.

    Deactivated rather than deleted, and left in DRILLS_BY_KEY on purpose:
    sessions already recorded against it still have to resolve to a spec, or
    an athlete's history develops a hole where their work used to be.
    """
    cur = conn.execute(
        "UPDATE custom_drills SET active = 0 WHERE org_id = ? AND drill_key = ?",
        (org_id, drill_key),
    )
    if cur.rowcount == 0:
        raise LibraryError("that is not one of this program's drills")
    conn.commit()
    CUSTOM.pop(drill_key, None)
