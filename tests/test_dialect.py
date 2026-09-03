"""What a Postgres migration would actually cost.

The README said `store.py` was "the only module that speaks SQL", and the
executive summary that prompted this work repeated it back as a reason a
migration would be cheap. It was not true: twenty-four modules execute SQL and
store.py holds well under half the call sites. An estimate built on that
sentence would have been wrong by a factor of two and a half, and it would
have been made by somebody committing to a district-wide rollout.

So the inventory runs as a test. The point is not the exact number -- it is
that the number comes from the code rather than from a memory of the code, and
that the documentation cannot drift away from it again without something
failing.

These tests also guard the tool against itself. An inventory that counts
Python's own `date()` as a SQLite date function produces a confidently wrong
estimate, which is precisely what it exists to replace.
"""
from __future__ import annotations

import re

from offdays import dialect


class TestTheClaimThatWasWrong:
    def test_sql_is_not_confined_to_one_module(self):
        """The sentence the README carried, and the estimate it supported."""
        assert len(dialect.sql_modules()) > 1

    def test_store_holds_well_under_half_of_it(self):
        modules = dialect.sql_modules()
        share = modules["store.py"] / sum(modules.values())
        assert 0.2 < share < 0.6

    def test_the_readme_no_longer_says_otherwise(self):
        """Pins the correction. A documentation defect that can silently come
        back is a documentation defect that will."""
        from pathlib import Path

        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
        assert "The only module that speaks SQL" not in readme

    def test_the_readme_figure_matches_the_code(self):
        from pathlib import Path

        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
        stated = re.search(r"~(\d+)% of queries", readme)
        assert stated, "the README should state store.py's share"

        modules = dialect.sql_modules()
        actual = modules["store.py"] / sum(modules.values()) * 100
        assert abs(int(stated.group(1)) - actual) < 5, (
            f"README says {stated.group(1)}%, code says {actual:.0f}%"
        )


    def test_the_readme_module_and_call_site_counts_match(self):
        """The sentence this module exists to keep honest, kept honest.

        Only store.py's percentage was pinned, so "24 modules across 371 call
        sites" drifted the moment three modules with SQL in them arrived. A
        figure nobody checks is a figure that goes stale and is quoted anyway
        -- which is the exact failure that prompted writing dialect.py.
        """
        from pathlib import Path

        readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
        stated = re.search(
            r"SQL lives in (\d+) modules across (\d+) call sites", readme
        )
        assert stated, "the README should state both counts"
        modules = dialect.sql_modules()
        assert int(stated.group(1)) == len(modules), (
            f"README says {stated.group(1)} modules, code has {len(modules)}"
        )
        assert int(stated.group(2)) == sum(modules.values()), (
            f"README says {stated.group(2)} call sites, "
            f"code has {sum(modules.values())}"
        )


class TestTheInventoryIsAccurate:
    """An inventory that over-counts produces a confidently wrong estimate,
    which is what this module exists to replace."""

    def test_python_date_calls_are_not_counted_as_sqlite_ones(self):
        """The bug that made the first run report 115 date functions when
        there are 21. Python's own date() is on every other line here."""
        finding = self._find("date_functions")
        assert finding.total < 40, (
            f"{finding.total} 'SQLite date functions' is Python's date() "
            "leaking into the count"
        )

    #: Where SQLite is spoken directly, and why each one is allowed to.
    #: Named rather than counted so a new site fails this test and has to
    #: justify itself here -- which is the whole job of the guard. The
    #: alternative, asserting "exactly one", stopped being true the moment
    #: monitoring arrived and would only ever be made to pass by lying.
    CONNECT_SITES = {
        "db.py": "the application seam every request is served through",
        # backup() needs a destination handle. Routing it through db.connect
        # would apply WAL and foreign keys to a file that is about to be
        # overwritten wholesale by the backup itself.
        "health.py": "the destination handle for an online backup",
    }
    PRAGMA_SITES = {
        "db.py": "foreign keys and WAL, set once per connection",
        # wal_checkpoint and integrity_check are not implementation details
        # of the health check, they are the health check. There is no
        # portable spelling of them, which is precisely why they are counted.
        "health.py": "wal_checkpoint and integrity_check probes",
    }

    def test_connect_happens_only_where_it_is_meant_to(self):
        """It matched sqlite3.Connection type hints under IGNORECASE at first,
        reporting 156 of what was then genuinely one."""
        finding = self._find("connect_call")
        assert set(finding.counts) == set(self.CONNECT_SITES), (
            "a new sqlite3.connect() appeared; add it to CONNECT_SITES with a "
            "reason, or route it through db.connect"
        )
        assert finding.counts["db.py"] == 1, "the app seam is still one call"

    def test_pragma_lives_only_where_it_has_to(self):
        assert set(self._find("pragma").counts) == set(self.PRAGMA_SITES), (
            "a new PRAGMA appeared; add it to PRAGMA_SITES with a reason"
        )

    def test_prose_about_sql_is_not_counted_as_sql(self):
        """A log line reading "schedule a full PRAGMA integrity_check from
        scripts/health_reap.py" was reported as api.py executing a PRAGMA.

        That is the failure this module exists to prevent, pointed at itself:
        a number that looks measured, is not, and goes into an estimate as
        fact. Only strings actually handed to execute() are counted now.
        """
        assert "api.py" not in self._find("pragma").counts
        # The sentence is still there -- it is the counting that changed.
        api = (dialect.PACKAGE / "api.py").read_text()
        assert "PRAGMA integrity_check from scripts/health_reap.py" in api

    def test_the_schema_is_still_inventoried(self):
        """It reaches the database as executescript(SCHEMA) -- a name, not a
        literal. Counting only inline strings reported zero AUTOINCREMENT
        columns in a file that has thirty."""
        finding = self._find("autoincrement_pk")
        assert finding.counts.get("db.py", 0) >= 25, finding.counts

    def test_placeholder_counts_come_from_sql_strings_only(self):
        """A question mark in a docstring is not a bind parameter."""
        finding = self._find("qmark_params")
        assert finding.total > 100
        # If prose were being counted, every module with a comment would show
        # up -- including ones with no SQL at all.
        assert set(finding.counts) <= set(dialect.sql_modules())

    def test_it_does_not_count_itself(self):
        """The module is full of the very patterns it looks for."""
        for finding in dialect.scan():
            assert "dialect.py" not in finding.counts

    @staticmethod
    def _find(key):
        return next(f for f in dialect.scan() if f.construct.key == key)


class TestTheReportIsHonest:
    def test_it_says_it_has_not_been_run_against_postgres(self):
        """There is no driver here. A silently wrong port of a query about a
        child's training load is worse than no port at all."""
        report = dialect.report()
        assert report["driver_available"] is False
        assert "does not perform one" in report["caveat"]

    def test_it_separates_mechanical_work_from_judgement(self):
        """The two cost very different amounts, and lumping them together is
        how a migration estimate goes wrong."""
        report = dialect.report()
        assert report["mechanical_occurrences"] > 0
        assert report["judgement_occurrences"] > 0

    def test_every_construct_carries_a_remedy(self):
        """A list of problems is not a plan."""
        for construct in dialect.CONSTRUCTS:
            assert len(construct.remedy) > 30, construct.key

    def test_the_things_needing_judgement_say_why(self):
        for construct in dialect.CONSTRUCTS:
            if not construct.mechanical:
                assert "judgement" in construct.remedy.lower() \
                    or "no equivalent" in construct.remedy.lower(), construct.key

    def test_it_renders_for_a_human(self):
        text = dialect.render()
        assert "Postgres migration scope" in text
        assert "JUDGEMENT" in text
        assert "does not perform one" in text

    def test_the_findings_name_where_the_work_is(self):
        """"Nineteen lastrowid calls" is not actionable. "Nineteen across
        seven modules, here they are" is."""
        for item in dialect.report()["constructs"]:
            assert item["by_module"]
            assert sum(item["by_module"].values()) == item["total"]
