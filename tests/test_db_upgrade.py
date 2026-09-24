"""The upgrade path: a database from an earlier release gets every column.

`CREATE TABLE IF NOT EXISTS` skips tables that already exist, so columns added
after a table's first release are applied by `db.migrate` from `ADDED_COLUMNS`.
Two things can quietly break that:

1. A table listed twice in `ADDED_COLUMNS`. Python keeps only the last
   duplicate key in a dict literal, so the first block's columns vanish from
   every upgraded deployment while a fresh database (which gets them from the
   CREATE TABLE) looks fine. This happened once with `organizations`.
2. A column in `ADDED_COLUMNS` that never made it into the CREATE TABLE, so a
   fresh install lacks what an upgraded one has. This happened once with
   `sessions.self_reported`.

Both are checked here by actually building the old shape and upgrading it.
"""

import ast
import re
import sqlite3
from pathlib import Path

from offdays import db as db_module
from offdays.db import ADDED_COLUMNS, SCHEMA, migrate

DB_SOURCE = Path(db_module.__file__)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on commas that are not inside parentheses."""
    items, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))
    return [i.strip() for i in items if i.strip()]


def _old_shape() -> sqlite3.Connection:
    """A database as it looked before any ADDED_COLUMNS column shipped.

    Derived from the real SCHEMA by removing the listed columns (and any
    index on them), so the fixture cannot drift from the schema the way a
    frozen SQL copy would.
    """
    schema = re.sub(r"--[^\n]*", "", SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        names = {name for name, _ in columns}
        m = re.search(
            rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);", schema, re.S
        )
        assert m, f"{table} listed in ADDED_COLUMNS but has no CREATE TABLE"
        kept = [
            item
            for item in _split_top_level(m.group(1))
            if item.split()[0] not in names
        ]
        schema = schema[: m.start(1)] + "\n    " + ",\n    ".join(kept) + schema[m.end(1) :]
        for name in names:
            schema = re.sub(
                rf"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS \w+ ON {table}\([^)]*\b{name}\b[^)]*\)[^;]*;",
                "",
                schema,
            )
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema)
    return conn


def test_added_columns_lists_each_table_once():
    tree = ast.parse(DB_SOURCE.read_text(encoding="utf-8"))
    literal = None
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "ADDED_COLUMNS":
            literal = node.value
            break
    assert isinstance(literal, ast.Dict), "ADDED_COLUMNS literal not found in db.py"
    keys = [k.value for k in literal.keys]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, (
        f"ADDED_COLUMNS lists {dupes} more than once; only the last block "
        "survives, so the earlier columns never reach an upgraded database"
    )


def test_every_added_column_is_in_create_table():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    missing = [
        f"{table}.{name}"
        for table, columns in ADDED_COLUMNS.items()
        for name, _ in columns
        if name not in _columns(conn, table)
    ]
    assert not missing, (
        f"in ADDED_COLUMNS but not in the CREATE TABLE, so a fresh database "
        f"would not have: {missing}"
    )


def test_old_database_upgrades_to_every_column():
    conn = _old_shape()

    # Confirm the fixture really is the old shape.
    for table, columns in ADDED_COLUMNS.items():
        present = _columns(conn, table)
        for name, _ in columns:
            assert name not in present, f"fixture still had {table}.{name}"

    migrate(conn)

    missing = [
        f"{table}.{name}"
        for table, columns in ADDED_COLUMNS.items()
        for name, _ in columns
        if name not in _columns(conn, table)
    ]
    assert not missing, f"migrate left these columns off: {missing}"

    # Second run must be a no-op, not a "duplicate column name" error.
    migrate(conn)
