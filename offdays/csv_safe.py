"""A name that starts with = + - or @ is a formula to a spreadsheet.

A player or parent whose name was typed (or uploaded) as `=HYPERLINK(...)` would run when a director opens the
parents list or the program export in Excel or Sheets. Every CSV this product writes passes its text cells
through `cell`, which puts a leading apostrophe on anything a spreadsheet could read as a formula -- the
standard defence -- and leaves ordinary text and plain numbers (`+2`, `-3`, `0.5`) exactly as they were.

Reading is unaffected: the apostrophe is only added on the way out, and only to the rare cell that needs it.
"""

from __future__ import annotations

import re
from typing import Any

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(?:[.,]\d+)?%?$")


def cell(value: Any) -> Any:
    """`value` made safe to write into a CSV cell. Non-text values (numbers, None) are returned untouched."""
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(_TRIGGERS) and not _PLAIN_NUMBER.match(value.strip()):
        return "'" + value
    return value
