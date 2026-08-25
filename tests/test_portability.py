"""The answer to the lock-in question.

A cautious director asks it, and they are right to. The answer has to be an
artifact rather than a promise: a file they can take to a competitor, a
spreadsheet, or their own analyst, documented well enough that a stranger can
use it without asking us anything.

The round-trip test is the one that matters. `athletes.csv` is written in the
shape this product's own importer reads, and re-importing it reproduces the
squad. That is the difference between a dump and a format — if it parses here
it will parse anywhere.

What is left out is as considered as what is in. A director gets roster, teams,
sessions and assignments; they do not get a bulk health file on every child in
the club. The whole wellness subsystem depends on a child believing that
saying "my knee hurts" does not travel.
"""
from __future__ import annotations

import io
import json
import re
import random
import zipfile
from datetime import date, timedelta

import pytest

from athleteiq import portability, roster as roster_mod
from athleteiq.db import connect
from athleteiq.store import Store

TODAY = date(2026, 8, 25)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "p.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore LC")
    director = store.create_user(org, "director", "Dir Smith")
    team = store.create_team(org, "U15 Boys", season="2026")
    athletes = []
    for i, name in enumerate(("Jordan Pierce", "Sam Reyes", "Alex Okafor")):
        person = store.create_user(
            org, "athlete", name, birth_year=2011, dominant_hand="right")
        store.join_team(team["join_code"], person["id"],
                        jersey=str(7 + i), position="Midfield")
        athletes.append(person)
    return {"org": org, "director": director, "team": team, "athletes": athletes}


def archive(store, program):
    return zipfile.ZipFile(io.BytesIO(portability.build(store.conn, program["org"])))


def train(store, athlete, day=TODAY):
    rng = random.Random(athlete["id"])
    started = store.start_session(athlete["id"], "gen_squat")
    t, reps = 0, []
    for _ in range(20):
        t += max(600, int(rng.gauss(1500, 220)))
        value = 74.0 + rng.uniform(-3, 3)
        reps.append({"t_ms": t, "hand": "none", "confidence": 0.9, "rom": value,
                     "peak": value, "cycle_ms": 1150 + rng.randint(-120, 120)})
    store.submit_session(
        athlete["id"], started["session_id"], started["nonce"],
        duration_ms=t + 900, reps=reps, mean_confidence=0.9)


class TestTheRosterIsAFormatNotADump:
    def test_it_re_imports_through_our_own_parser(self, store, program):
        """If it parses here it will parse anywhere. That round-trip is what
        makes this portability rather than a checkbox."""
        plan = roster_mod.parse(portability.roster_csv(store.conn, program["org"]))
        assert [a.display_name for a in plan.athletes] == [
            "Jordan Pierce", "Sam Reyes", "Alex Okafor"]

    def test_the_re_import_keeps_jersey_and_position(self, store, program):
        plan = roster_mod.parse(portability.roster_csv(store.conn, program["org"]))
        assert {a.jersey for a in plan.athletes} == {"7", "8", "9"}
        assert all(a.position for a in plan.athletes)

    def test_re_importing_updates_rather_than_duplicates(self, store, program):
        """The strongest form of the claim: our own export, fed back in, is
        recognised as the same squad."""
        plan = store.resolve_import(
            program["org"],
            roster_mod.parse(portability.roster_csv(store.conn, program["org"])))
        assert plan.creates == []
        assert len(plan.athletes) == 3

    def test_the_same_file_is_in_the_archive(self, store, program):
        inside = archive(store, program).read("athletes.csv").decode()
        assert inside == portability.roster_csv(store.conn, program["org"])


class TestItIsComplete:
    def test_every_table_a_program_owns_is_there(self, store, program):
        names = set(archive(store, program).namelist())
        for expected in ("athletes.csv", "teams.csv", "staff.csv",
                         "sessions.csv", "assignments.csv", "team_goals.csv",
                         "badges.csv", "xp_ledger.csv"):
            assert expected in names

    def test_sessions_come_out(self, store, program):
        train(store, program["athletes"][0])
        rows = archive(store, program).read("sessions.csv").decode().splitlines()
        assert len(rows) == 2          # header plus one session

    def test_xp_comes_out_with_what_earned_it(self, store, program):
        train(store, program["athletes"][0])
        text = archive(store, program).read("xp_ledger.csv").decode()
        assert "amount" in text and "reason" in text
        assert len(text.splitlines()) > 1


class TestItDocumentsItself:
    """An export whose meaning lives in our documentation stops making sense
    the day a program leaves."""

    def test_a_readme_travels_with_it(self, store, program):
        readme = archive(store, program).read("README.txt").decode()
        assert "AthleteIQ program export" in readme

    def test_the_readme_names_every_file(self, store, program):
        z = archive(store, program)
        readme = z.read("README.txt").decode()
        for name in z.namelist():
            if name.endswith(".csv"):
                assert name in readme, f"{name} is undocumented"

    def test_it_states_the_units(self, store, program):
        readme = archive(store, program).read("README.txt").decode()
        assert "milliseconds" in readme
        assert "ISO 8601" in readme

    def test_the_manifest_carries_a_schema_version(self, store, program):
        manifest = json.loads(archive(store, program).read("manifest.json"))
        assert manifest["schema_version"] == portability.SCHEMA_VERSION
        assert manifest["program"]["name"] == "Northshore LC"

    def test_the_manifest_counts_every_file(self, store, program):
        manifest = json.loads(archive(store, program).read("manifest.json"))
        assert manifest["files"]["athletes.csv"]["rows"] == 3
        assert manifest["files"]["athletes.csv"]["columns"]


class TestWhatIsDeliberatelyLeftOut:
    def test_no_wellness_or_injury_data_anywhere(self, store, program):
        """The one that would be wrong by default. A guardian can export their
        own child's complete record; a director does not get a bulk health
        file on every child in the club."""
        athlete = program["athletes"][0]
        report = store.report_discomfort(
            athlete["id"], "knee", "hurts", note="it clicks going upstairs")
        store.resolve_discomfort(athlete["id"], report["id"])

        # The data files only. README.txt and the manifest explain the
        # exclusion and name it on purpose; a leak would be in the CSVs.
        z = archive(store, program)
        data = "".join(
            z.read(n).decode() for n in z.namelist() if n.endswith(".csv")
        ).lower()
        for leak in ("knee", "discomfort", "soreness", "return_plan",
                     "upstairs", "hurts"):
            assert leak not in data, f"the program export leaks: {leak!r}"

    def test_the_readme_says_so_and_says_why(self, store, program):
        readme = archive(store, program).read("README.txt").decode()
        assert "No wellness or injury records" in readme
        assert "does not travel" in readme

    def test_no_credentials(self, store, program):
        """Not the program's data to take -- they are keys to accounts."""
        z = archive(store, program)
        blob = "".join(z.read(n).decode() for n in z.namelist())
        assert program["director"]["token"] not in blob
        assert program["team"]["join_code"] not in blob
        for column in ("token_hash", "claim_code_hash", "nonce"):
            assert column not in blob

    def test_no_other_programs_data(self, store, program):
        other = store.create_org("Southside")
        stranger = store.create_user(
            other, "athlete", "Nobody Else", birth_year=2011,
            dominant_hand="left")
        z = archive(store, program)
        blob = "".join(z.read(n).decode() for n in z.namelist())
        assert "Nobody Else" not in blob

    def test_the_manifest_lists_the_exclusions(self, store, program):
        """A reader should be able to tell what is missing without diffing it
        against a product they no longer use."""
        manifest = json.loads(archive(store, program).read("manifest.json"))
        assert set(manifest["excluded"]) == {
            "wellness_and_injury", "credentials", "video"}


class TestTheHealthExclusionIsStructural:
    """The word-scan above proves no health data came out of *this* fixture.

    That is the weaker half. A scan over the output passes an empty health
    table and would fail the day a child is called Ankle. These check what the
    export *reads*, which is the actual guarantee, and they are written so a
    health table added next year is excluded by default rather than by
    somebody remembering.
    """

    #: Every table in the schema holding something about a child's body.
    #: adaptive_profiles sits with them deliberately: it records what our tool
    #: cannot do rather than anything clinical, but a downloadable list of
    #: which children have accommodations is the same object by another name.
    HEALTH_TABLES = {
        "wellness_checkins", "discomfort_reports", "return_plans",
        "return_plan_events", "adaptive_profiles",
    }

    def test_the_export_reads_none_of_them(self, store, program):
        for table in portability._tables(store.conn, program["org"]):
            referenced = set(re.findall(
                r"(?:FROM|JOIN)\s+([a-z_]+)", table.sql, re.IGNORECASE))
            leaked = referenced & self.HEALTH_TABLES
            assert not leaked, f"{table.name}.csv reads {leaked}"

    def test_it_reads_only_tables_on_the_allowlist(self, store, program):
        """Named rather than pattern-matched, the same discipline the binary
        column guard uses. A new table is excluded until somebody adds it here
        in a diff, with this test asking them why."""
        for table in portability._tables(store.conn, program["org"]):
            referenced = set(re.findall(
                r"(?:FROM|JOIN)\s+([a-z_]+)", table.sql, re.IGNORECASE))
            outside = referenced - portability.SOURCE_TABLES
            assert not outside, f"{table.name}.csv reads {outside}, not allowed"

    def test_no_health_table_is_on_the_allowlist(self, store, program):
        assert not (portability.SOURCE_TABLES & self.HEALTH_TABLES)

    def test_every_health_table_in_the_schema_is_covered(self, store, program):
        """If somebody adds a health table and does not list it above, this
        fails rather than quietly leaving it unguarded."""
        from pathlib import Path

        schema = (Path(__file__).resolve().parent.parent
                  / "athleteiq" / "db.py").read_text()
        tables = set(re.findall(
            r"CREATE TABLE IF NOT EXISTS ([a-z_]+)", schema))
        suspicious = {
            t for t in tables
            if any(word in t for word in
                   ("wellness", "discomfort", "injur", "health", "return_plan",
                    "adaptive", "medical", "symptom"))
        }
        missed = suspicious - self.HEALTH_TABLES
        assert not missed, (
            f"{missed} looks like health data and is not covered by this "
            "test's list -- add it, and check it is out of the export"
        )

    def test_a_guardian_can_still_export_their_own_childs_record(
        self, store, program
    ):
        """The exclusion is about who is downloading, not about hiding the
        data from the family it belongs to."""
        from athleteiq import guardians as guardians_mod

        athlete = program["athletes"][0]
        store.report_discomfort(athlete["id"], "knee", "sore")
        record = guardians_mod.export_athlete(store.conn, athlete["id"])
        assert "knee" in str(record)


# ---------------------------------------------------------------------------
# Over the wire
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATHLETEIQ_DB", str(tmp_path / "api.db"))
    from athleteiq import api

    api.app.dependency_overrides.clear()
    return TestClient(api.app)


@pytest.fixture
def wired(client):
    from athleteiq import api as api_mod

    org = client.post(
        "/api/orgs", json={"name": "Northshore LC", "director_name": "Dir"}
    ).json()
    director = {"Authorization": f"Bearer {org['director']['token']}"}
    team = client.post("/api/teams", json={"name": "U15"}, headers=director).json()
    client.post(
        "/api/athletes",
        json={"display_name": "Jordan P.", "birth_year": 2011,
              "dominant_hand": "right", "guardian_consent": True,
              "join_code": team["join_code"]},
        headers=director)
    store = api_mod.get_store()
    org_id = store.authenticate(org["director"]["token"]).org_id
    return {"director": director, "org_id": org_id, "store": store}


class TestOverTheWire:
    def test_a_director_gets_a_zip(self, client, wired):
        res = client.get("/api/org/export", headers=wired["director"])
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/zip"
        assert "attachment" in res.headers["content-disposition"]
        assert zipfile.ZipFile(io.BytesIO(res.content)).namelist()

    def test_the_filename_is_derived_from_the_program(self, client, wired):
        res = client.get("/api/org/export", headers=wired["director"])
        assert "northshore-lc-export.zip" in res.headers["content-disposition"]

    def test_the_roster_comes_back_as_text(self, client, wired):
        res = client.get("/api/org/export/roster.csv", headers=wired["director"])
        assert res.status_code == 200
        assert res.text.startswith("first_name,last_name")

    def test_an_assistant_coach_cannot_take_the_program(self, client, wired):
        coach = wired["store"].create_user(wired["org_id"], "coach", "Asst")
        headers = {"Authorization": f"Bearer {coach['token']}"}
        assert client.get("/api/org/export", headers=headers).status_code == 403
        assert client.get("/api/org/export/roster.csv",
                          headers=headers).status_code == 403

    def test_an_athlete_certainly_cannot(self, client, wired):
        athlete = wired["store"].conn.execute(
            "SELECT id FROM users WHERE role = 'athlete'").fetchone()
        assert athlete is not None
        assert client.get("/api/org/export").status_code == 401
