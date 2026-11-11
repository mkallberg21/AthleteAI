"""Spreadsheet formula injection: every CSV the product writes neutralises a cell that would run as a formula.

The names come from people typing into a roster (or a file), and the CSVs go to a director's Excel or Sheets. A name
like =HYPERLINK("http://evil","click") must come out as text, and an honest value like +2 must not be damaged.
"""

from __future__ import annotations

import csv
import io

import pytest

from offdays import contacts, csv_safe, portability
from offdays.db import connect
from offdays.store import Store


class TestTheHelper:

    @pytest.mark.parametrize("evil", ['=cmd|"/c calc"!A1', '=HYPERLINK("http://x","y")', "+1+1", "-2+3", "@SUM(1)", "\t=1", "\r=1",
                                      "-cmd", "+cmd", "=1+1"])
    def test_a_formula_becomes_text(self, evil):
        assert csv_safe.cell(evil) == "'" + evil

    @pytest.mark.parametrize("fine", ["Sam O'Brien", "Ana García-Núñez", "Lee Smith, Jr.", "x=y", "a+b", "e-mail", "name@example.com", "", "7", "O'Neil"])
    def test_ordinary_text_is_left_alone(self, fine):
        assert csv_safe.cell(fine) == fine

    @pytest.mark.parametrize("number", ["+2", "-3", "+12", "-0.5", "0.5", "42", "+3%", "-7%", "1,5"])
    def test_an_honest_number_is_not_damaged(self, number):
        assert csv_safe.cell(number) == number

    @pytest.mark.parametrize("not_text", [None, 0, 7, 3.5, True])
    def test_non_text_is_untouched(self, not_text):
        assert csv_safe.cell(not_text) is not_text or csv_safe.cell(not_text) == not_text

    def test_a_phone_with_a_plus_is_text_not_a_formula(self):
        assert csv_safe.cell("+1 615 555 0101") == "'+1 615 555 0101"


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "t.db"))


def rows_of(text):
    return [r for r in csv.reader(io.StringIO(text)) if r and not r[0].startswith("#")]


class TestTheExports:

    def test_the_parents_list(self):
        row = {"name": "=EVIL()", "email": "+x@example.com", "phone": "@1", "relationship": "-", "athlete_name": "=KID()",
               "birth_year": 2013, "teams": "A", "has_account": False, "marketing": None, "participation": None,
               "source": "roster", "added_on": "2026-01-01"}
        out = rows_of(contacts.to_csv([row]))[1]
        assert out[0] == "'=EVIL()" and out[1] == "'+x@example.com" and out[2] == "'@1" and out[4] == "'=KID()"
        assert out[5] == "2013", "a number stays a number"

    def test_the_program_export(self, store):
        org = store.create_org("Probe")
        store.create_user(org, "athlete", "=cmd Evil", birth_year=2013, dominant_hand="right", guardian_consent=True)
        exported = portability.export_program(store.conn, org) if hasattr(portability, "export_program") else None
        text = None
        if isinstance(exported, dict):
            text = next((v for k, v in exported.items() if "athlete" in k.lower() or "user" in k.lower()), None)
        if text is None:
            # the table writer itself
            rows = store.conn.execute("SELECT display_name FROM users WHERE role = 'athlete'").fetchall()
            text = portability._csv(rows, ["display_name"])
        assert "'=cmd Evil" in text and ",=cmd" not in text and not any(line.startswith("=") for line in text.splitlines())

    def test_a_date_or_number_column_is_not_damaged(self, store):
        org = store.create_org("Probe")
        rows = store.conn.execute("SELECT id, name FROM organizations").fetchall()
        text = portability._csv(rows, ["id", "name"])
        assert rows_of(text)[1][0] == str(org)
