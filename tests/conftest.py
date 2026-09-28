"""Every test gets its own database. None of them may touch data/offdays.db.

Fourteen API fixtures used to set OFFDAYS_DB (the variable config.py reads is
OFFDAYS_DB_PATH, and CONFIG is frozen at import anyway) and never reset the
module-level store, so they all shared the developer's real database. It
went unnoticed while a failed sign-in wrote nothing; the guess throttle
writes on every failure, and the shared file started locking.

This fixture runs for every test: api._store is pointed at a fresh temp
database before, and closed after. Fixtures that build their own Store on
a tmp_path keep working; they simply replace what this set up.

health.py holds a second, module-level probe connection, opened at import
against the configured path -- the developer's real database again. /api/health
read that, so test_health passed on a machine with a seeded data/offdays.db and
failed on a clean CI runner. It is pointed at the same temp database.
"""

from __future__ import annotations

import pytest

from offdays import api as api_module
from offdays import health as health_module
from offdays.db import connect
from offdays.store import Store


@pytest.fixture(autouse=True)
def _isolated_api_store(tmp_path):
    previous = api_module._store
    previous_probe = (health_module._probe_conn, health_module._db_ok)
    api_module._store = Store(connect(tmp_path / "autouse.db"))
    health_module._probe_conn = api_module._store.conn
    health_module._db_ok = True
    try:
        yield
    finally:
        health_module._probe_conn, health_module._db_ok = previous_probe
        current = api_module._store
        api_module._store = previous
        if current is not None and current is not previous:
            current.close()
