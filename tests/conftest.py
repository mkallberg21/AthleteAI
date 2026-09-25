"""Every test gets its own database. None of them may touch data/offdays.db.

Fourteen API fixtures used to set OFFDAYS_DB (the variable config.py reads is
OFFDAYS_DB_PATH, and CONFIG is frozen at import anyway) and never reset the
module-level store, so they all shared the developer's real database. It
went unnoticed while a failed sign-in wrote nothing; the guess throttle
writes on every failure, and the shared file started locking.

This fixture runs for every test: api._store is pointed at a fresh temp
database before, and closed after. Fixtures that build their own Store on
a tmp_path keep working; they simply replace what this set up.
"""

from __future__ import annotations

import pytest

from offdays import api as api_module
from offdays.db import connect
from offdays.store import Store


@pytest.fixture(autouse=True)
def _isolated_api_store(tmp_path):
    previous = api_module._store
    api_module._store = Store(connect(tmp_path / "autouse.db"))
    try:
        yield
    finally:
        current = api_module._store
        api_module._store = previous
        if current is not None and current is not previous:
            current.close()
