"""Roster import.

Parsing is tested against the file shapes coaches actually have -- exports with
"Last, First" in one column, jersey columns called "#", grades instead of birth
years -- because a parser that only reads a format nobody exports is a parser
nobody uses.

Idempotency gets its own class. Coaches fix a spelling and upload the file
again, and an import that duplicates the roster on the second pass is worse
than one that never ran.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from athleteiq import roster
from athleteiq.db import connect
from athleteiq.store import Store, StoreError

NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(connect(tmp_path / "r.db"))


@pytest.fixture
def program(store):
    org = store.create_org("Northshore")
    coach = store.create_user(org, "coach", "Coach R")
    team = store.create_team(org, "Varsity")
    return {"org": org, "coach": coach, "team": team}


class TestHeaderDetection:
    @pytest.mark.parametrize("header", ["Jersey #", "#", "No.", "Number", "Uniform Number", "jersey_number"])
    def test_jersey_columns_are_all_recognised(self, header):
        assert roster.detect_columns(["Name", header]).get("jersey") == header

    @pytest.mark.parametrize(
        "header", ["Parent Email", "Guardian E-mail", "Mother Email", "parent_email"]
    )
    def test_guardian_email_columns_are_recognised(self, header):
        assert roster.detect_columns(["Name", header]).get("guardian_email") == header

    def test_first_and_last_beat_a_generic_name_column(self):
        mapping = roster.detect_columns(["Name", "First Name", "Last Name"])
        assert mapping["first_name"] == "First Name"
        assert mapping["last_name"] == "Last Name"

    def test_a_header_is_claimed_by_only_one_field(self):
        mapping = roster.detect_columns(["First Name", "Last Name", "#", "Position"])
        assert len(set(mapping.values())) == len(mapping.values())

    def test_unknown_columns_are_left_alone(self):
        plan = roster.parse("Name,Notes,Emergency Contact\nJordan Pierce,x,y\n")
        assert "Notes" in plan.unmapped_headers
        assert "Emergency Contact" in plan.unmapped_headers


class TestNameParsing:
    @pytest.mark.parametrize(
        "first,last,full,expected",
        [
            ("Jordan", "Pierce", "", "Jordan Pierce"),
            ("", "", "Jordan Pierce", "Jordan Pierce"),
            ("", "", "Pierce, Jordan", "Jordan Pierce"),
            # A quoted "Last, First" landing wholly in one column.
            ("", "Pierce, Jordan", "", "Jordan Pierce"),
            ("Pierce, Jordan", "", "", "Jordan Pierce"),
            ("Jordan", "", "", "Jordan"),
        ],
    )
    def test_name_forms(self, first, last, full, expected):
        assert roster.normalize_name(first, last, full) == expected

    def test_match_key_ignores_punctuation_and_case(self):
        assert roster.match_key("Jordan O'Pierce-Smith") == roster.match_key(
            "jordan opiercesmith"
        )


class TestBirthYear:
    @pytest.mark.parametrize(
        "year,date,grade,expected,estimated",
        [
            ("2011", "", "", 2011, False),
            ("", "2011-04-09", "", 2011, False),
            ("", "04/09/2011", "", 2011, False),
            ("", "", "9", 2012, True),
            ("", "", "Junior", 2010, True),
            ("", "", "", None, False),
        ],
    )
    def test_resolution(self, year, date, grade, expected, estimated):
        assert roster.parse_birth_year(year, date, grade, NOW) == (expected, estimated)

    def test_a_graduation_year_is_not_read_as_a_birth_year(self):
        """"Class Of 2029" is a future year and must not become a birth year."""
        birth_year, estimated = roster.parse_birth_year("2029", "", "", NOW)
        assert estimated is True
        assert 2005 < birth_year < 2020


class TestMinorDefault:
    def test_an_unknown_age_is_treated_as_a_minor(self):
        """Erring the other way puts a child's full name on a public board."""
        athlete = roster.Athlete(row=2, display_name="Jordan", birth_year=None)
        assert athlete.is_minor

    def test_an_estimated_age_is_treated_as_a_minor(self):
        athlete = roster.Athlete(
            row=2, display_name="Jordan", birth_year=2000, birth_year_estimated=True
        )
        assert athlete.is_minor

    def test_a_confirmed_adult_is_not(self):
        athlete = roster.Athlete(row=2, display_name="Jordan", birth_year=1999)
        assert not athlete.is_minor


class TestParsing:
    def test_a_clean_file_parses(self):
        plan = roster.parse(
            "First Name,Last Name,#,Position,Birth Year,Shoots\n"
            "Jordan,Pierce,14,Midfield,2011,Right\n"
            "Sam,Rivera,7,Attack,2010,Left\n"
        )
        assert len(plan.athletes) == 2
        assert plan.athletes[0].display_name == "Jordan Pierce"
        assert plan.athletes[0].jersey == "14"
        assert plan.athletes[1].dominant_hand == "left"

    def test_tab_separated_files_work(self):
        plan = roster.parse("Name\t#\tPosition\nJordan Pierce\t14\tMidfield\n")
        assert plan.athletes[0].display_name == "Jordan Pierce"
        assert plan.athletes[0].jersey == "14"

    def test_semicolon_separated_files_work(self):
        plan = roster.parse("Name;#;Position\nJordan Pierce;14;Midfield\n")
        assert plan.athletes[0].jersey == "14"

    def test_a_byte_order_mark_does_not_break_the_first_column(self):
        """Excel writes one, and it silently corrupts the first header."""
        plan = roster.parse("﻿Name,#\nJordan Pierce,14\n")
        assert plan.athletes[0].display_name == "Jordan Pierce"

    def test_blank_lines_are_ignored_not_reported(self):
        plan = roster.parse("Name,#\nJordan Pierce,14\n\n\nSam Rivera,7\n")
        assert len(plan.athletes) == 2

    def test_a_row_with_no_name_is_skipped_with_a_reason(self):
        plan = roster.parse("Name,#\n,99\nJordan Pierce,14\n")
        skipped = [a for a in plan.athletes if a.problems]
        assert len(skipped) == 1
        assert "No name" in skipped[0].problems[0]

    def test_duplicate_names_in_one_file_are_skipped(self):
        plan = roster.parse("Name,#\nJordan Pierce,14\nJordan Pierce,15\n")
        assert plan.athletes[1].action == "skip"
        assert "row 2" in plan.athletes[1].problems[0]

    def test_one_bad_row_does_not_lose_the_file(self):
        plan = roster.parse("Name,#\nJordan Pierce,14\n,99\nSam Rivera,7\n")
        assert len(plan.creates) == 2

    def test_a_bad_guardian_email_warns_but_still_imports(self):
        """A malformed parent email is no reason to leave a kid off the roster."""
        plan = roster.parse("Name,Parent Email\nJordan Pierce,not-an-email\n")
        athlete = plan.athletes[0]
        assert athlete.ok
        assert athlete.warnings
        assert not athlete.problems

    def test_a_file_with_no_name_column_is_rejected_clearly(self):
        plan = roster.parse("Jersey,Position\n14,Midfield\n")
        assert plan.file_problems
        assert "name column" in plan.file_problems[0].lower()

    def test_an_empty_file_raises(self):
        with pytest.raises(roster.RosterError, match="empty"):
            roster.parse("   ")

    def test_a_header_only_file_reports_no_rows(self):
        plan = roster.parse("Name,#\n")
        assert plan.file_problems
        assert not plan.athletes

    def test_row_numbers_match_the_spreadsheet(self):
        """A coach fixing a problem needs the row number their editor shows."""
        plan = roster.parse("Name,#\nJordan Pierce,14\nSam Rivera,7\n")
        assert [a.row for a in plan.athletes] == [2, 3]


class TestImport:
    CSV = (
        "Last Name,First Name,#,Pos,Birth Year,Shoots,Parent Email\n"
        "Pierce,Jordan,14,Midfield,2011,Right,dana@example.com\n"
        "Rivera,Sam,7,Attack,2010,left,\n"
        "Halloran,Drew,22,Defense,2011,R,drew.parent@example.com\n"
    )

    def run(self, store, program, text=None, **kw):
        plan = store.resolve_import(program["org"], roster.parse(text or self.CSV))
        return plan, store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"], **kw
        )

    def test_athletes_are_created_and_placed_on_the_team(self, store, program):
        _, result = self.run(store, program)
        assert len(result["created"]) == 3
        roster_rows = store.conn.execute(
            "SELECT COUNT(*) AS n FROM team_members WHERE team_id = ?",
            (program["team"]["id"],),
        ).fetchone()["n"]
        assert roster_rows == 3

    def test_every_new_athlete_gets_a_claim_code(self, store, program):
        _, result = self.run(store, program)
        codes = {a["claim_code"] for a in result["created"]}
        assert len(codes) == 3
        assert all(codes)

    def test_guardian_invites_are_issued_for_parent_emails(self, store, program):
        _, result = self.run(store, program)
        assert len(result["guardian_invites"]) == 2

    def test_guardian_invites_can_be_declined(self, store, program):
        _, result = self.run(store, program, issue_guardian_invites=False)
        assert result["guardian_invites"] == []

    def test_fields_are_stored(self, store, program):
        self.run(store, program)
        row = store.conn.execute(
            "SELECT birth_year, dominant_hand FROM users WHERE display_name = ?",
            ("Sam Rivera",),
        ).fetchone()
        assert row["birth_year"] == 2010
        assert row["dominant_hand"] == "left"

    def test_an_import_into_another_program_is_refused(self, store, program):
        other_org = store.create_org("Rival")
        other_team = store.create_team(other_org, "Theirs")
        plan = store.resolve_import(program["org"], roster.parse(self.CSV))
        with pytest.raises(StoreError, match="different program"):
            store.apply_import(
                program["org"], other_team["id"], plan, program["coach"]["id"]
            )


class TestIdempotency:
    CSV = TestImport.CSV

    def test_reimporting_the_same_file_updates_nothing_new(self, store, program):
        """Coaches always upload again. This must not duplicate the roster."""
        for _ in range(2):
            plan = store.resolve_import(program["org"], roster.parse(self.CSV))
            store.apply_import(
                program["org"], program["team"]["id"], plan, program["coach"]["id"]
            )
        total = store.conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role = 'athlete'"
        ).fetchone()["n"]
        assert total == 3

    def test_the_second_pass_is_planned_as_updates(self, store, program):
        plan = store.resolve_import(program["org"], roster.parse(self.CSV))
        store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        second = store.resolve_import(program["org"], roster.parse(self.CSV))
        assert len(second.updates) == 3
        assert second.creates == []

    def test_an_edited_field_is_applied_on_reimport(self, store, program):
        plan = store.resolve_import(program["org"], roster.parse(self.CSV))
        store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        edited = self.CSV.replace("Halloran,Drew,22", "Halloran,Drew,23")
        plan2 = store.resolve_import(program["org"], roster.parse(edited))
        store.apply_import(
            program["org"], program["team"]["id"], plan2, program["coach"]["id"]
        )
        jersey = store.conn.execute(
            "SELECT tm.jersey FROM team_members tm JOIN users u ON u.id = tm.user_id "
            "WHERE u.display_name = 'Drew Halloran'"
        ).fetchone()["jersey"]
        assert jersey == "23"

    def test_a_partial_file_does_not_blank_existing_data(self, store, program):
        """A file with fewer columns must not erase what is already known."""
        plan = store.resolve_import(program["org"], roster.parse(self.CSV))
        store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        sparse = "Name,#\nSam Rivera,9\n"
        plan2 = store.resolve_import(program["org"], roster.parse(sparse))
        store.apply_import(
            program["org"], program["team"]["id"], plan2, program["coach"]["id"]
        )
        row = store.conn.execute(
            "SELECT birth_year, dominant_hand FROM users WHERE display_name = 'Sam Rivera'"
        ).fetchone()
        assert row["birth_year"] == 2010
        assert row["dominant_hand"] == "left"

    def test_an_external_id_matches_even_when_the_name_changed(self, store, program):
        first = "Athlete ID,Name,#\nA-1,Jonathan Pierce,14\n"
        plan = store.resolve_import(program["org"], roster.parse(first))
        store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        renamed = "Athlete ID,Name,#\nA-1,Jordan Pierce,14\n"
        plan2 = store.resolve_import(program["org"], roster.parse(renamed))
        assert len(plan2.updates) == 1
        assert plan2.creates == []

    def test_an_ambiguous_name_is_skipped_rather_than_guessed(self, store, program):
        """Guessing could overwrite the wrong child's record."""
        for _ in range(2):
            store.create_user(program["org"], "athlete", "Jordan Pierce")
        plan = store.resolve_import(program["org"], roster.parse("Name,#\nJordan Pierce,14\n"))
        assert plan.athletes[0].action == "skip"
        assert "more than one" in plan.athletes[0].problems[0].lower()


class TestClaimCodes:
    def test_a_code_exchanges_for_a_working_token(self, store, program):
        plan = store.resolve_import(program["org"], roster.parse("Name,#\nJordan Pierce,14\n"))
        result = store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        claimed = store.claim_account(result["created"][0]["claim_code"])
        principal = store.authenticate(claimed["token"])
        assert principal.display_name == "Jordan Pierce"
        assert principal.role == "athlete"

    def test_a_code_works_only_once(self, store, program):
        """A slip picked up off the floor afterwards has to be worthless."""
        plan = store.resolve_import(program["org"], roster.parse("Name,#\nJordan Pierce,14\n"))
        result = store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        code = result["created"][0]["claim_code"]
        store.claim_account(code)
        with pytest.raises(StoreError, match="not valid"):
            store.claim_account(code)

    def test_an_unknown_code_is_refused(self, store, program):
        with pytest.raises(StoreError, match="not valid"):
            store.claim_account("ZZZZ-ZZZZ")

    def test_an_expired_code_is_refused(self, store, program):
        from datetime import timedelta

        plan = store.resolve_import(program["org"], roster.parse("Name,#\nJordan Pierce,14\n"))
        result = store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        store.conn.execute(
            "UPDATE users SET claim_expires_at = ? WHERE claim_code_hash IS NOT NULL",
            ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),),
        )
        store.conn.commit()
        with pytest.raises(StoreError, match="not valid"):
            store.claim_account(result["created"][0]["claim_code"])

    def test_the_code_is_stored_only_as_a_hash(self, store, program):
        plan = store.resolve_import(program["org"], roster.parse("Name,#\nJordan Pierce,14\n"))
        result = store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        code = result["created"][0]["claim_code"]
        stored = store.conn.execute(
            "SELECT claim_code_hash FROM users WHERE claim_code_hash IS NOT NULL"
        ).fetchone()["claim_code_hash"]
        assert code not in stored
        assert len(stored) == 64

    def test_an_unclaimed_account_cannot_be_logged_into(self, store, program):
        """The placeholder token is nobody's; only the claim code opens it."""
        plan = store.resolve_import(program["org"], roster.parse("Name,#\nJordan Pierce,14\n"))
        store.apply_import(
            program["org"], program["team"]["id"], plan, program["coach"]["id"]
        )
        with pytest.raises(StoreError, match="invalid or inactive"):
            store.authenticate("")
