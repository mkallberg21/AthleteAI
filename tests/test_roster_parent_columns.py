"""Parent columns are read by what they say, in the names real exports use.

A roster whose parents are all in the file once imported with 'No parent on
file' for every player, because the header was "Contact 1 Email" or
"Parent/Guardian Phone" and the alias match either missed it or read a
phone column as the email. Each header here is one a club actually sends.
"""

from __future__ import annotations

import pytest

from offdays import roster


def read(headers: list[str]) -> dict[str, str]:
    return roster.detect_columns(headers)


@pytest.mark.parametrize("headers, email, phone", [
    (["First Name", "Last Name", "Parent Email", "Parent Phone"], "Parent Email", "Parent Phone"),
    (["First", "Last", "Contact 1 Email", "Contact 1 Phone"], "Contact 1 Email", "Contact 1 Phone"),
    (["Name", "Parent/Guardian Email", "Parent/Guardian Phone"], "Parent/Guardian Email", "Parent/Guardian Phone"),
    (["First Name", "Last Name", "Email Address 1", "Phone 1"], "Email Address 1", "Phone 1"),
    (["First Name", "Last Name", "Guardian 1 Email", "Guardian 1 Phone"], "Guardian 1 Email", "Guardian 1 Phone"),
    (["Name", "Parent/Guardian 1 Email", "Parent/Guardian 1 Mobile"], "Parent/Guardian 1 Email", "Parent/Guardian 1 Mobile"),
    (["Participant First Name", "Participant Last Name", "Primary Contact Email", "Primary Contact Phone"],
     "Primary Contact Email", "Primary Contact Phone"),
    (["Name", "Parent's Email", "Parent's Phone"], "Parent's Email", "Parent's Phone"),
    (["Name", "Parent email address", "Parent cell phone"], "Parent email address", "Parent cell phone"),
])
def test_the_parents_email_and_phone_are_found(headers, email, phone):
    cols = read(headers)
    assert cols.get("guardian_email") == email
    assert cols.get("guardian_phone") == phone


def test_a_phone_column_is_never_read_as_the_email():
    """The old failure: 'parent' in 'Parent/Guardian Phone' made it the email."""
    cols = read(["Name", "Parent/Guardian Phone"])
    assert "guardian_email" not in cols
    assert cols["guardian_phone"] == "Parent/Guardian Phone"


def test_a_second_parent_is_the_second_slot():
    cols = read(["Name", "Contact 1 Email", "Contact 2 Email", "Contact 2 Phone"])
    assert cols["guardian_email"] == "Contact 1 Email"
    assert cols["guardian2_email"] == "Contact 2 Email"
    assert cols["guardian2_phone"] == "Contact 2 Phone"


def test_mom_and_dad_columns():
    cols = read(["Player", "Mom Email", "Dad Email", "Mom Cell"])
    assert cols["guardian_email"] == "Mom Email"
    assert cols["guardian2_email"] == "Dad Email"
    assert cols["guardian_phone"] == "Mom Cell"


def test_only_a_dad_column_makes_dad_the_contact():
    cols = read(["Player", "Dad Email"])
    assert cols["guardian_email"] == "Dad Email" and "guardian2_email" not in cols


def test_a_parents_last_name_is_not_the_athletes():
    cols = read(["First Name", "Last Name", "Guardian 1 First Name", "Guardian 1 Last Name", "Guardian 1 Email"])
    assert cols["last_name"] == "Last Name"
    assert cols["guardian_email"] == "Guardian 1 Email"


def test_an_emergency_contact_is_not_a_parent():
    cols = read(["Name", "Emergency Contact Phone", "Parent Email"])
    assert cols["guardian_email"] == "Parent Email"
    assert "guardian_phone" not in cols


def test_the_athletes_own_email_is_not_taken_for_a_parents():
    """A bare 'Email' is the athlete's; guessing otherwise would invite the wrong person."""
    cols = read(["First Name", "Last Name", "Email"])
    assert "guardian_email" not in cols and cols.get("email") == "Email"


def test_a_whole_file_ends_up_with_a_parent_on_every_row():
    csv = (
        "First,Last,Contact 1 Name,Contact 1 Email,Contact 1 Phone,Contact 2 Email\n"
        "Mason,Reed,Dana Reed,dana@example.com,615-555-0100,chris@example.com\n"
        "Owen,Hale,Pat Hale,pat@example.com,615-555-0101,\n"
    )
    plan = roster.parse(csv)
    assert [a.guardian_email for a in plan.athletes] == ["dana@example.com", "pat@example.com"]
    assert [a.guardian_name for a in plan.athletes] == ["Dana Reed", "Pat Hale"]
    assert [g["email"] for g in plan.athletes[0].guardians] == ["dana@example.com", "chris@example.com"]
