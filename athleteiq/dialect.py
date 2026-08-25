"""What a move to Postgres would actually cost, measured rather than guessed.

The README used to say `store.py` was "the only module that speaks SQL", and
the executive summary that prompted this work repeated the claim back as a
reason a Postgres migration would be cheap. It was not true: twenty-four
modules execute SQL and `store.py` holds well under half the call sites. A
migration estimate built on that sentence would have been wrong by a factor of
two and a half, and the estimate would have been made by somebody committing
to a district-wide rollout.

So this module does the honest version. It inventories every SQLite-specific
construct in the codebase and reports where it lives, which turns "how hard is
Postgres" from a guess into a list. It runs as a test, so the answer stays
true as the code changes and the claim cannot drift back.

**What this is not.** It is not a compatibility layer and it does not make the
product run on Postgres. Writing one blind would mean refactoring a working,
heavily-tested system against a database this environment cannot run, with no
way to check any of it -- and a silently wrong port of a query about a child's
training load is worse than no port at all. There is no Postgres driver here;
`psycopg` is not installed and nothing below has ever been run against a real
server. The migration is scoped, not done, and the README says so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Construct:
    key: str
    pattern: str
    label: str
    #: What it takes to move it, in the terms somebody planning would want.
    remedy: str
    #: Mechanical work can be done by a careful search and replace with tests
    #: behind it. Judgement means somebody has to think about each one.
    mechanical: bool = True
    #: Count only inside string literals that look like SQL. Without this,
    #: `date(` matches Python's own date() on every other line and the
    #: estimate comes out several times too large -- which would make this
    #: module exactly the kind of confidently wrong number it exists to
    #: replace.
    sql_only: bool = False


CONSTRUCTS: tuple[Construct, ...] = (
    Construct(
        "qmark_params",
        r"\?",
        "SQLite `?` placeholders",
        "Postgres uses %s. Mechanical, but it touches nearly every query, so "
        "it wants a parameter-style shim rather than a sweep.",
        sql_only=True,
    ),
    Construct(
        "sqlite3_row",
        r"sqlite3\.Row",
        "sqlite3.Row row factory",
        "Replace with a Postgres row factory that also supports mapping "
        "access, so call sites keep using row['column'].",
    ),
    Construct(
        "sqlite3_errors",
        r"sqlite3\.(IntegrityError|OperationalError|DatabaseError|Error)",
        "sqlite3 exception types",
        "Map to the driver's equivalents. Small but easy to miss, and a "
        "missed one turns a handled duplicate into a 500.",
    ),
    Construct(
        "insert_or_ignore",
        r"INSERT\s+OR\s+IGNORE",
        "INSERT OR IGNORE",
        "Rewrite as INSERT ... ON CONFLICT DO NOTHING.",
        sql_only=True,
    ),
    Construct(
        "insert_or_replace",
        r"INSERT\s+OR\s+REPLACE",
        "INSERT OR REPLACE",
        "Rewrite as ON CONFLICT DO UPDATE. Needs judgement: REPLACE deletes "
        "and reinserts, which fires different cascades.",
        mechanical=False,
        sql_only=True,
    ),
    Construct(
        "date_functions",
        r"\b(?:date|datetime|julianday|strftime)\s*\(",
        "SQLite date functions",
        "Postgres has different names and semantics. Needs judgement: these "
        "sit inside comparisons where a timezone assumption changes results.",
        mechanical=False,
        sql_only=True,
    ),
    Construct(
        "string_functions",
        r"\b(?:instr|substr)\s*\(",
        "SQLite string functions",
        "instr -> position, substr -> substring. Mechanical.",
        sql_only=True,
    ),
    Construct(
        "pragma",
        r"\bPRAGMA\b",
        "PRAGMA statements",
        "No equivalent. Foreign keys are always on in Postgres; WAL and "
        "table_info have separate mechanisms (information_schema).",
        mechanical=False,
        sql_only=True,
    ),
    Construct(
        "lastrowid",
        r"\.lastrowid",
        "cursor.lastrowid",
        "Postgres needs INSERT ... RETURNING id. Judgement, because the "
        "returning value has to be threaded back through each call.",
        mechanical=False,
    ),
    Construct(
        "autoincrement_pk",
        r"INTEGER\s+PRIMARY\s+KEY(?!\s+REFERENCES)",
        "INTEGER PRIMARY KEY rowid columns",
        "Becomes GENERATED ALWAYS AS IDENTITY or SERIAL in the schema.",
        sql_only=True,
    ),
    Construct(
        "connect_call",
        r"sqlite3\.connect\s*\(",
        "sqlite3.connect() calls",
        "The single genuine seam. Everything else is downstream of it.",
    ),
)


@dataclass
class Finding:
    construct: Construct
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def modules(self) -> int:
        return len(self.counts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.construct.key,
            "label": self.construct.label,
            "remedy": self.construct.remedy,
            "mechanical": self.construct.mechanical,
            "total": self.total,
            "modules": self.modules,
            "by_module": dict(sorted(
                self.counts.items(), key=lambda kv: -kv[1])),
        }


#: Words that make a string literal a SQL statement rather than prose.
#: Without this filter `date(` matches Python's own date() on every other
#: line and the estimate comes out several times too large -- which would
#: make this module exactly the kind of confidently wrong number it exists
#: to replace.
_SQL_WORDS = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|VALUES|FROM|JOIN|PRAGMA|"
    r"CREATE TABLE|ORDER BY|GROUP BY|SET )",
    re.IGNORECASE,
)

#: String literals, triple-quoted first so a multi-line query is one match.
_STRINGS = re.compile(
    r'"""[\s\S]*?"""'
    r"|'''[\s\S]*?'''"
    r'|"(?:[^"\\\n]|\\.)*"'
    r"|'(?:[^'\\\n]|\\.)*'",
)


def _sql_text(src: str) -> str:
    """Only the string literals that look like SQL, joined together."""
    return "\n".join(
        lit for lit in _STRINGS.findall(src) if _SQL_WORDS.search(lit)
    )

def _sources() -> dict[str, str]:
    return {
        path.name: path.read_text()
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.name != "dialect.py"
    }


def scan() -> list[Finding]:
    """Where every SQLite-specific construct lives, and how many there are."""
    sources = _sources()
    findings = []
    for construct in CONSTRUCTS:
        pattern = re.compile(construct.pattern, re.IGNORECASE)
        counts = {}
        for name, src in sources.items():
            haystack = _sql_text(src) if construct.sql_only else src
            hits = len(pattern.findall(haystack))
            if hits:
                counts[name] = hits
        findings.append(Finding(construct=construct, counts=counts))
    return findings


def sql_modules() -> dict[str, int]:
    """Every module that executes SQL, and how many call sites it has.

    The number the README got wrong. Kept as a function so a test can assert
    the documentation against reality rather than against a memory of it.
    """
    pattern = re.compile(r"\.execute(?:many|script)?\s*\(")
    return {
        name: len(pattern.findall(src))
        for name, src in _sources().items()
        if pattern.search(src)
    }


def report() -> dict[str, Any]:
    """The migration, scoped."""
    findings = scan()
    modules = sql_modules()
    mechanical = sum(f.total for f in findings if f.construct.mechanical)
    judgement = sum(f.total for f in findings if not f.construct.mechanical)
    return {
        "sql_modules": len(modules),
        "sql_call_sites": sum(modules.values()),
        "store_share": (
            round(modules.get("store.py", 0) / sum(modules.values()), 3)
            if modules else 0.0
        ),
        "by_module": dict(sorted(modules.items(), key=lambda kv: -kv[1])),
        "mechanical_occurrences": mechanical,
        "judgement_occurrences": judgement,
        "constructs": [f.to_dict() for f in findings if f.total],
        "driver_available": _driver_available(),
        "caveat": (
            "This scopes a Postgres migration; it does not perform one. No "
            "Postgres driver is installed and nothing here has been run "
            "against a server."
        ),
    }


def _driver_available() -> bool:
    try:
        import psycopg  # noqa: F401
        return True
    except ImportError:
        try:
            import psycopg2  # noqa: F401
            return True
        except ImportError:
            return False


def render() -> str:
    """The report as text, for a human deciding whether to start."""
    data = report()
    lines = [
        "Postgres migration scope",
        "========================",
        "",
        f"SQL lives in {data['sql_modules']} modules across "
        f"{data['sql_call_sites']} call sites.",
        f"store.py holds {data['store_share']:.0%} of them.",
        "",
        f"{data['mechanical_occurrences']} occurrences are mechanical "
        "(search-and-replace with tests behind it).",
        f"{data['judgement_occurrences']} need judgement.",
        "",
        "By construct:",
    ]
    for item in data["constructs"]:
        kind = "mechanical" if item["mechanical"] else "JUDGEMENT"
        lines.append(
            f"  {item['label']:<34} {item['total']:>5} in "
            f"{item['modules']:>2} modules  [{kind}]"
        )
        lines.append(f"      {item['remedy']}")
    lines += ["", data["caveat"]]
    return "\n".join(lines)
