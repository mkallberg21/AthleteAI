"""Which parent-column headers does the roster parser understand?

Real exports name the parent columns every way there is. Run each header
through the parser and report whether a parent email came out.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from offdays import roster  # noqa: E402

CASES = {
    "ours": ["First Name", "Last Name", "Parent Email", "Parent Phone"],
    "teamsnap export 1": ["First", "Last", "Contact 1 Email", "Contact 1 Phone", "Contact 2 Email"],
    "teamsnap export 2": ["Name", "Jersey Number", "Parent/Guardian Email", "Parent/Guardian Phone"],
    "teamsnap export 3": ["Player First Name", "Player Last Name", "Email Address 1", "Phone 1", "Email Address 2"],
    "teamsnap export 4": ["First Name", "Last Name", "Parent 1 Email", "Parent 2 Email", "Parent 1 Name"],
    "teamsnap export 5": ["First Name", "Last Name", "Guardian 1 Email", "Guardian 1 Phone", "Guardian 1 First Name", "Guardian 1 Last Name"],
    "teamsnap export 6": ["First Name", "Last Name", "Email", "Mobile Phone"],
    "sportsengine 1": ["First Name", "Last Name", "Parent/Guardian 1 Email", "Parent/Guardian 1 Mobile"],
    "sportsengine 2": ["Participant First Name", "Participant Last Name", "Primary Contact Email", "Primary Contact Phone"],
    "spreadsheet": ["Player", "Mom Email", "Dad Email", "Mom Cell"],
    "spreadsheet 2": ["Name", "Parent's Email", "Parent's Phone"],
    "spreadsheet 3": ["Name", "Parent email address", "Parent cell phone"],
}

for label, headers in CASES.items():
    cols = roster.detect_columns(headers)
    row = ",".join(["Mason Reed"] + ["x@example.com" if "mail" in h.lower() else "615-555-0100" if any(k in h.lower() for k in ("phone", "cell", "mobile")) else "Mason" if "first" in h.lower() else "Reed" if "last" in h.lower() else "7" for h in headers[1:]])
    parent_cols = {k: v for k, v in cols.items() if "guardian" in k}
    print(f"{label:20} parent email read: {'YES' if 'guardian_email' in cols else 'NO ':3}  {parent_cols}")
