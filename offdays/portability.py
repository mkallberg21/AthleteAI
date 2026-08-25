"""Everything a program owns, in a form somebody else could read.

A cautious director asks the lock-in question, and they are right to. The
answer has to be an artifact rather than a promise: a file they can take to a
competitor, a spreadsheet, or their own analyst, with enough documentation
that a stranger can use it without asking us anything.

Three properties make this portability rather than a checkbox.

**It is complete.** Every table a program owns, not a curated summary. A
export that quietly drops the parts that would be inconvenient to lose is the
lock-in it claims to answer.

**It is documented from inside.** A README travels in the archive naming every
file, every column, and every unit. An export whose meaning lives in our
documentation is an export that stops making sense the day a program leaves.

**The roster comes back in.** `athletes.csv` is written in exactly the shape
our own importer reads, and a test round-trips it. That is the difference
between a dump and a format: if it can be re-imported here, it can be parsed
anywhere.

What is deliberately *not* in it is as considered as what is.

**No wellness or injury records.** This is the one that would be wrong by
default. A guardian can already export their own child's complete record --
that is their right and it is already built. A director exporting the program
gets roster, teams, sessions and assignments; they do not get a bulk health
file on every child in the club. The whole wellness subsystem depends on a
child believing that saying "my knee hurts" does not travel, and a director
who can download all of it at once has made that false.

**No credentials.** Token hashes, claim codes and provider tokens are left
out. They are not the program's data to take; they are keys to accounts.

**No video.** There has never been any, outside the one consented table.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

#: Bumped when a column changes meaning, so a file that outlives this codebase
#: can still be read correctly by whatever reads it next.
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv(rows: list[sqlite3.Row], columns: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row[c] is None else row[c] for c in columns])
    return out.getvalue()


#: Tables a program export is allowed to read. Named rather than
#: pattern-matched, the same discipline the binary-column privacy guard uses:
#: a new table is excluded by default and somebody has to consciously add it
#: here, in a diff, with a test that will ask them why.
#:
#: The health tables are absent deliberately and permanently --
#: `wellness_checkins`, `discomfort_reports`, `return_plans`,
#: `return_plan_events` and `adaptive_profiles`. A guardian can export their
#: own child's complete record and that is their right; a director exporting
#: the program does not get a bulk health file on every child in the club.
#: `adaptive_profiles` sits with them: it records what our tool cannot do
#: rather than anything clinical, but a downloadable list of which children
#: have accommodations is the same object by another name.
SOURCE_TABLES: frozenset[str] = frozenset({
    "users", "teams", "team_members", "sessions", "assignments",
    "team_goals", "badges", "xp_ledger", "organizations",
})


@dataclass
class Table:
    name: str
    columns: list[str]
    rows: list[sqlite3.Row]
    describes: str
    #: The query that produced these rows. Carried so a test can prove what
    #: this export reads rather than infer it from what came out -- a
    #: word-scan over the output would pass an empty health table and fail
    #: the day a child is called Ankle.
    sql: str = ""

    @property
    def filename(self) -> str:
        return f"{self.name}.csv"

    def to_csv(self) -> str:
        return _csv(self.rows, self.columns)


README = """0FFDAYS program export
========================

Everything this program owns, as CSV. Written so somebody who has never seen
this product can use it.

Files
-----
{files}

Conventions
-----------
* Every timestamp is ISO 8601 in UTC.
* Every duration is milliseconds unless the column name says otherwise.
* `athlete_id`, `team_id` and `assignment_id` join across files.
* `athletes.csv` is written in the shape this product's own roster importer
  reads, so it can be re-imported here or parsed anywhere. That round-trip is
  covered by a test.

What is deliberately not here
-----------------------------
* **No wellness or injury records.** A guardian can export their own child's
  complete record, including those, and that is their right. A program-level
  export is roster, teams, sessions and assignments -- not a bulk health file
  on every child in the club. The wellness features only work because a child
  believes that saying "my knee hurts" does not travel, and an export that
  handed all of it to a director at once would make that untrue.
* **No credentials.** Token hashes, athlete claim codes and roster-provider
  tokens are keys to accounts rather than program data.
* **No video.** None is ever uploaded. Pose analysis runs on the athlete's own
  device. The single exception is a clip an athlete chose to send with
  guardian consent, which lives with that household and not here.
* **Nothing from any other program.**

Exported {exported_at} · schema version {version}
"""


def _tables(conn: sqlite3.Connection, org_id: int) -> list[Table]:
    ran: list[str] = []

    def q(sql: str, params: tuple = (org_id,)) -> list[sqlite3.Row]:
        ran.append(sql)
        return list(conn.execute(sql, params))

    tables = [
        Table(
            "athletes",
            ["first_name", "last_name", "jersey", "position", "birth_year",
             "dominant_hand", "external_id", "athlete_id", "team_id",
             "joined_at", "active"],
            q(
                "SELECT "
                "  CASE WHEN instr(u.display_name, ' ') > 0 "
                "    THEN substr(u.display_name, 1, instr(u.display_name, ' ') - 1) "
                "    ELSE u.display_name END AS first_name, "
                "  CASE WHEN instr(u.display_name, ' ') > 0 "
                "    THEN substr(u.display_name, instr(u.display_name, ' ') + 1) "
                "    ELSE '' END AS last_name, "
                "  tm.jersey, tm.position, u.birth_year, u.dominant_hand, "
                "  u.external_id, u.id AS athlete_id, tm.team_id, tm.joined_at, "
                "  u.active "
                "FROM users u LEFT JOIN team_members tm ON tm.user_id = u.id "
                "WHERE u.org_id = ? AND u.role = 'athlete' ORDER BY u.id"
            ),
            "One row per athlete. Re-importable by this product's roster importer.",
        ),
        Table(
            "teams",
            ["team_id", "name", "season", "created_at"],
            q("SELECT id AS team_id, name, season, created_at FROM teams "
              "WHERE org_id = ? ORDER BY id"),
            "Teams in this program. Join codes are omitted -- they are credentials.",
        ),
        Table(
            "staff",
            ["user_id", "display_name", "role", "email", "created_at"],
            q("SELECT id AS user_id, display_name, role, email, created_at "
              "FROM users WHERE org_id = ? AND role IN ('coach','director') "
              "ORDER BY id"),
            "Coaches and directors.",
        ),
        Table(
            "sessions",
            ["session_id", "athlete_id", "drill_key", "started_at",
             "submitted_at", "completed_at", "duration_ms", "reps_total",
             "reps_left", "reps_right", "hold_ms", "xp_awarded",
             "quality_score", "integrity_score", "status", "self_reported"],
            q("SELECT s.id AS session_id, s.athlete_id, s.drill_key, "
              "  s.started_at, s.submitted_at, s.completed_at, s.duration_ms, "
              "  s.reps_total, s.reps_left, s.reps_right, s.hold_ms, "
              "  s.xp_awarded, s.quality_score, s.integrity_score, s.status, "
              "  s.self_reported "
              "FROM sessions s JOIN users u ON u.id = s.athlete_id "
              "WHERE u.org_id = ? AND s.status != 'open' ORDER BY s.id"),
            "Every recorded session. quality_score is 0-100 or blank where "
            "form was not scored; self_reported marks work the camera could "
            "not count.",
        ),
        Table(
            "assignments",
            ["assignment_id", "team_id", "drill_key", "title",
             "target_reps", "target_sessions", "min_offhand", "starts_on",
             "due_on", "active"],
            q("SELECT id AS assignment_id, team_id, drill_key, title, "
              "  target_reps, target_sessions, min_offhand, starts_on, due_on, "
              "  active FROM assignments WHERE org_id = ? ORDER BY id"),
            "What coaches prescribed. min_offhand is a fraction, 0 to 1.",
        ),
        Table(
            "team_goals",
            ["goal_id", "team_id", "title", "target_athletes",
             "per_athlete_days", "per_athlete_sessions", "starts_on",
             "ends_on", "active"],
            q("SELECT id AS goal_id, team_id, title, target_athletes, "
              "  per_athlete_days, per_athlete_sessions, starts_on, ends_on, "
              "  active FROM team_goals WHERE org_id = ? ORDER BY id"),
            "Shared squad goals. A count of athletes clearing a small bar, "
            "never a volume total.",
        ),
        Table(
            "badges",
            ["athlete_id", "badge_key", "awarded_at"],
            q("SELECT b.athlete_id, b.badge_key, b.awarded_at FROM badges b "
              "JOIN users u ON u.id = b.athlete_id WHERE u.org_id = ? "
              "ORDER BY b.id"),
            "Awards earned.",
        ),
        Table(
            "xp_ledger",
            ["athlete_id", "session_id", "amount", "reason", "day"],
            q("SELECT x.athlete_id, x.session_id, x.amount, x.reason, x.day "
              "FROM xp_ledger x JOIN users u ON u.id = x.athlete_id "
              "WHERE u.org_id = ? ORDER BY x.id"),
            "Every XP award, with what earned it.",
        ),
    ]
    # Pair each table with the query that produced it. Recorded rather than
    # re-derived so a test can assert what this export *reads*, which is the
    # guarantee -- scanning the output would pass an empty health table and
    # would fail the day a child is called Ankle.
    for table, sql in zip(tables, ran):
        table.sql = sql
    return tables


def manifest(conn: sqlite3.Connection, org_id: int, tables: list[Table]) -> dict[str, Any]:
    org = conn.execute(
        "SELECT name, sport, kind, season_phase, created_at FROM organizations "
        "WHERE id = ?",
        (org_id,),
    ).fetchone()
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": _now(),
        "program": dict(org) if org else {},
        "files": {
            table.filename: {
                "rows": len(table.rows),
                "columns": table.columns,
                "describes": table.describes,
            }
            for table in tables
        },
        "excluded": {
            "wellness_and_injury": (
                "Held for each athlete and exportable by their guardian, not "
                "in a program-level export."
            ),
            "credentials": "Token hashes, claim codes and provider tokens.",
            "video": "None is ever uploaded.",
        },
    }


def build(conn: sqlite3.Connection, org_id: int) -> bytes:
    """The whole program as a zip archive of CSVs plus documentation."""
    tables = _tables(conn, org_id)
    files = "\n".join(
        f"* {t.filename:<20} {t.describes}" for t in tables
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README.format(
            files=files, exported_at=_now(), version=SCHEMA_VERSION))
        archive.writestr(
            "manifest.json",
            json.dumps(manifest(conn, org_id, tables), indent=2),
        )
        for table in tables:
            archive.writestr(table.filename, table.to_csv())
    return buffer.getvalue()


def roster_csv(conn: sqlite3.Connection, org_id: int) -> str:
    """Just the roster, in the shape our own importer reads.

    Separate from the archive because it is the piece a program most often
    wants on its own -- moving a squad to another product, or into a
    spreadsheet -- and because it is the file the round-trip test exercises.
    """
    for table in _tables(conn, org_id):
        if table.name == "athletes":
            return table.to_csv()
    return ""
