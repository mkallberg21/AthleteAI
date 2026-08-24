"""Bulk roster import.

Nobody hand-creates two hundred athletes, and a coach who has to will not
finish. In practice this is a more common reason a pilot dies than any missing
feature, so the parsing here is deliberately forgiving of the files people
actually have rather than demanding one they would have to build.

Four things make the difference between an import that works and one that gets
abandoned halfway:

* **Headers are matched, not dictated.** A roster exported from TeamSnap, one
  from a school system, and one typed by an assistant coach will not agree on
  what the jersey column is called. They are all read.
* **Nothing happens without a preview.** Every import is planned first and shows
  what it will create, update, and skip. Applying is a second, explicit step.
* **Re-importing an edited file updates, it does not duplicate.** Coaches fix a
  spelling and upload again; that has to be safe.
* **One bad row does not fail the file.** Problems are reported per row and the
  rest still imports.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import positions

# How long a printed claim code stays valid. Long enough to survive a coach
# printing a sheet and handing it out at the next practice.
CLAIM_TTL_DAYS = 30

MAX_ROWS = 2_000


class RosterError(Exception):
    """The file itself cannot be read."""


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


# Headers that carry meaning entirely in punctuation. "#" is the single most
# common jersey header in a real roster and normalizes to an empty string, so
# without this it can never match anything.
LITERAL_HEADERS: dict[str, str] = {
    "#": "jersey",
    "no.": "jersey",
    "no": "jersey",
    "num": "jersey",
    "#/pos": "jersey",
}


# Ordered by specificity: the first alias that matches wins, so "firstname"
# beats the looser "name".
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "external_id": ("externalid", "memberid", "playerid", "athleteid", "id", "uid"),
    "first_name": ("firstname", "first", "givenname", "fname"),
    "last_name": ("lastname", "last", "surname", "familyname", "lname"),
    "full_name": ("fullname", "name", "athlete", "player", "athletename", "playername"),
    "jersey": ("jersey", "jerseynumber", "jerseyno", "number", "no", "num", "uniform"),
    "position": ("position", "pos", "role"),
    "birth_year": ("birthyear", "yearofbirth", "yob", "classof", "gradyear", "graduationyear"),
    "birth_date": ("birthdate", "dob", "dateofbirth", "birthday"),
    "grade": ("grade", "gradelevel", "year", "schoolyear"),
    "dominant_hand": ("dominanthand", "hand", "handedness", "shoots", "shot"),
    "email": ("athleteemail", "playeremail", "email", "emailaddress"),
    "guardian_email": (
        "parentemail", "guardianemail", "parent", "guardian", "parentcontact",
        "contactemail", "parent1email", "motheremail", "fatheremail",
    ),
    "guardian_name": ("parentname", "guardianname", "parent1name", "contactname"),
    "team": ("team", "teamname", "squad", "roster"),
}


def detect_columns(headers: Iterable[str]) -> dict[str, str]:
    """Map our field names onto whatever this file calls them.

    Returns {field: original header}. A header is claimed by at most one field,
    so a file with both "Name" and "First Name" does not map both to the same
    place.
    """
    normalized = {h: _norm(h) for h in headers if h}
    claimed: set[str] = set()
    mapping: dict[str, str] = {}

    # Punctuation-only headers, which normalization would erase.
    for header in normalized:
        literal = LITERAL_HEADERS.get(header.strip().lower())
        if literal and literal not in mapping:
            mapping[literal] = header
            claimed.add(header)

    # Exact alias matches first -- they are unambiguous.
    for field_name, aliases in FIELD_ALIASES.items():
        for header, norm in normalized.items():
            if header in claimed:
                continue
            if norm in aliases:
                mapping[field_name] = header
                claimed.add(header)
                break

    # Then containment, which catches things like "Player Jersey #".
    for field_name, aliases in FIELD_ALIASES.items():
        if field_name in mapping:
            continue
        for header, norm in normalized.items():
            if header in claimed or not norm:
                continue
            if any(alias in norm or norm in alias for alias in aliases if len(alias) > 3):
                mapping[field_name] = header
                claimed.add(header)
                break

    return mapping


# ---------------------------------------------------------------------------
# Value normalization
# ---------------------------------------------------------------------------

def _swap_comma(text: str) -> str:
    """"Pierce, Jordan" -> "Jordan Pierce".

    The export format nobody asks for and everyone has.
    """
    surname, _, given = text.partition(",")
    return f"{given.strip()} {surname.strip()}".strip()


def normalize_name(first: str, last: str, full: str) -> str:
    """Build a display name from whichever columns the file happened to have."""
    first, last, full = (first or "").strip(), (last or "").strip(), (full or "").strip()

    if first or last:
        # A quoted "Last, First" sometimes lands wholly inside one column while
        # the other is blank, which the naive join would leave reversed.
        if not first and "," in last:
            return _swap_comma(last)
        if not last and "," in first:
            return _swap_comma(first)
        return " ".join(part for part in (first, last) if part)

    if "," in full:
        return _swap_comma(full)
    return full


def match_key(name: str) -> str:
    """Normalized form used to spot the same athlete across re-imports."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def parse_hand(value: str) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text.startswith(("l", "gauche")):
        return "left"
    if text.startswith(("r", "d")):
        return "right"
    return None


def parse_birth_year(
    birth_year: str, birth_date: str, grade: str, today: datetime
) -> tuple[int | None, bool]:
    """Resolve a birth year, and say whether it had to be estimated.

    Returns (year, estimated). An estimate is never treated as proof of age --
    see `Athlete.is_minor`.
    """
    raw = (birth_year or "").strip()
    if raw:
        digits = re.findall(r"\d{4}", raw)
        if digits:
            year = int(digits[0])
            # A "Class of 2028" column is a graduation year, not a birth year;
            # a plausible birth year for a current youth athlete is in the past.
            if year > today.year:
                return today.year - (18 - (year - today.year)), True
            if 1900 <= year <= today.year:
                return year, False

    date_text = (birth_date or "").strip()
    if date_text:
        for pattern, group in (
            (r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", 1),   # 2011-04-09
            (r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", 3),   # 04/09/2011
        ):
            match = re.search(pattern, date_text)
            if match:
                return int(match.group(group)), False

    grade_text = (grade or "").strip().lower()
    if grade_text:
        named = {"freshman": 9, "sophomore": 10, "junior": 11, "senior": 12}
        level = named.get(grade_text)
        if level is None:
            digits = re.findall(r"\d{1,2}", grade_text)
            level = int(digits[0]) if digits else None
        if level is not None and 1 <= level <= 12:
            # A US student in grade N is typically N+5 or N+6 years old.
            return today.year - (level + 5), True

    return None, False


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

@dataclass
class Athlete:
    row: int
    display_name: str = ""
    external_id: str | None = None
    jersey: str = ""
    position: str = ""
    birth_year: int | None = None
    birth_year_estimated: bool = False
    dominant_hand: str | None = None
    email: str | None = None
    guardian_email: str | None = None
    guardian_name: str | None = None
    team_name: str | None = None

    action: str = "create"        # 'create' | 'update' | 'skip'
    existing_id: int | None = None
    # Blocking: this row cannot be imported.
    problems: list[str] = field(default_factory=list)
    # Non-blocking: the athlete imports, but something was dropped or guessed.
    # Kept separate because a malformed parent email is no reason to leave a
    # kid off the roster.
    warnings: list[str] = field(default_factory=list)

    @property
    def is_minor(self) -> bool:
        """Unknown or estimated ages are treated as minors.

        Getting this wrong in the permissive direction means a child's full name
        on a public leaderboard, so the default has to fall the other way.
        """
        if self.birth_year is None or self.birth_year_estimated:
            return True
        return (datetime.now(timezone.utc).year - self.birth_year) <= 17

    @property
    def ok(self) -> bool:
        return self.action != "skip" and not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "display_name": self.display_name,
            "external_id": self.external_id,
            "jersey": self.jersey,
            "position": self.position,
            "birth_year": self.birth_year,
            "birth_year_estimated": self.birth_year_estimated,
            "dominant_hand": self.dominant_hand,
            "guardian_email": self.guardian_email,
            "team_name": self.team_name,
            "action": self.action,
            "existing_id": self.existing_id,
            "problems": self.problems,
            "warnings": self.warnings,
            "is_minor": self.is_minor,
        }


@dataclass
class ImportPlan:
    columns: dict[str, str] = field(default_factory=dict)
    unmapped_headers: list[str] = field(default_factory=list)
    athletes: list[Athlete] = field(default_factory=list)
    file_problems: list[str] = field(default_factory=list)

    @property
    def creates(self) -> list[Athlete]:
        return [a for a in self.athletes if a.action == "create" and a.ok]

    @property
    def updates(self) -> list[Athlete]:
        return [a for a in self.athletes if a.action == "update" and a.ok]

    @property
    def skipped(self) -> list[Athlete]:
        return [a for a in self.athletes if not a.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "unmapped_headers": self.unmapped_headers,
            "file_problems": self.file_problems,
            "summary": {
                "total_rows": len(self.athletes),
                "create": len(self.creates),
                "update": len(self.updates),
                "skip": len(self.skipped),
                "warnings": sum(1 for a in self.athletes if a.ok and a.warnings),
                "with_guardian_email": sum(
                    1 for a in self.athletes if a.ok and a.guardian_email
                ),
            },
            "athletes": [a.to_dict() for a in self.athletes],
        }


def _sniff_dialect(text: str) -> csv.Dialect | type[csv.Dialect]:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        # Sniffing fails on single-column files and unusual quoting; comma is
        # the right guess far more often than not.
        return csv.excel


def parse(
    text: str, *, today: datetime | None = None, sport: str = "lacrosse"
) -> ImportPlan:
    """Read a delimited roster file into a plan. Never raises on row content."""
    today = today or datetime.now(timezone.utc)
    plan = ImportPlan()

    if not text or not text.strip():
        raise RosterError("that file is empty")

    # Strip a BOM, which Excel adds and which otherwise corrupts the first
    # header so it never matches anything.
    text = text.lstrip("﻿")

    reader = csv.DictReader(io.StringIO(text), dialect=_sniff_dialect(text))
    if not reader.fieldnames:
        raise RosterError("could not find a header row in that file")

    headers = [h for h in reader.fieldnames if h is not None]
    plan.columns = detect_columns(headers)
    plan.unmapped_headers = [
        h for h in headers if h and h not in plan.columns.values()
    ]

    if "full_name" not in plan.columns and not (
        "first_name" in plan.columns or "last_name" in plan.columns
    ):
        plan.file_problems.append(
            "No name column found. Add a column called Name, or First Name and "
            "Last Name."
        )
        return plan

    def value(row: dict[str, Any], field_name: str) -> str:
        header = plan.columns.get(field_name)
        if header is None:
            return ""
        raw = row.get(header)
        return str(raw).strip() if raw is not None else ""

    seen_keys: dict[str, int] = {}
    for index, row in enumerate(reader, start=2):  # row 1 is the header
        if len(plan.athletes) >= MAX_ROWS:
            plan.file_problems.append(
                f"Only the first {MAX_ROWS:,} rows were read."
            )
            break

        athlete = Athlete(row=index)
        athlete.display_name = normalize_name(
            value(row, "first_name"), value(row, "last_name"), value(row, "full_name")
        )

        if not athlete.display_name:
            # A trailing blank line is not worth reporting as an error.
            if not any(str(v or "").strip() for v in row.values()):
                continue
            athlete.action = "skip"
            athlete.problems.append("No name in this row.")
            plan.athletes.append(athlete)
            continue

        athlete.external_id = value(row, "external_id") or None
        athlete.jersey = value(row, "jersey")
        athlete.position = value(row, "position")
        if athlete.position and positions.normalize(athlete.position, sport) is None:
            # Worth a warning rather than silence: an unresolved position does
            # not just look untidy, it drops the athlete out of every position
            # comparison and out of their own drill-mix guidance.
            athlete.warnings.append(
                f"Position {athlete.position!r} was not recognised, so it will "
                "not be used for position benchmarks. The athlete still trains "
                "and still counts everywhere else."
            )
        athlete.dominant_hand = parse_hand(value(row, "dominant_hand"))
        athlete.email = value(row, "email") or None
        athlete.guardian_name = value(row, "guardian_name") or None
        athlete.team_name = value(row, "team") or None

        guardian_email = value(row, "guardian_email")
        if guardian_email:
            if "@" in guardian_email and "." in guardian_email.split("@")[-1]:
                athlete.guardian_email = guardian_email
            else:
                athlete.warnings.append(
                    f"Guardian contact {guardian_email!r} is not an email address; "
                    "no invite will be sent."
                )

        athlete.birth_year, athlete.birth_year_estimated = parse_birth_year(
            value(row, "birth_year"), value(row, "birth_date"), value(row, "grade"), today
        )
        if athlete.birth_year_estimated:
            athlete.warnings.append(
                "Age estimated from grade or graduation year. Treated as a minor "
                "until a birth year is confirmed."
            )
        elif athlete.birth_year is None:
            athlete.warnings.append(
                "No age given. Treated as a minor, so their full name stays off "
                "shared leaderboards."
            )

        # Duplicates within the same file, which happens when a coach pastes two
        # team tabs together.
        key = match_key(athlete.display_name)
        if key in seen_keys:
            athlete.action = "skip"
            athlete.problems.append(
                f"Same name as row {seen_keys[key]} in this file."
            )
        else:
            seen_keys[key] = index

        plan.athletes.append(athlete)

    if not plan.athletes:
        plan.file_problems.append("No athlete rows found below the header.")
    return plan


# ---------------------------------------------------------------------------
# Claim codes
# ---------------------------------------------------------------------------

def new_claim_code() -> str:
    """Short enough to print on a slip and type on a phone."""
    alphabet = "ABCDEFGHJKLMNPQRTUVWXYZ234679"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))


def hash_claim(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def claim_expiry(today: datetime | None = None) -> str:
    today = today or datetime.now(timezone.utc)
    return (today + timedelta(days=CLAIM_TTL_DAYS)).isoformat(timespec="seconds")
