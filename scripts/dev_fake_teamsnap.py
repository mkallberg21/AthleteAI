"""A local server that behaves as if TeamSnap were connected, for walking the
real page. TeamSnap's HTTP layer is replaced with the fixture the tests use;
every other layer (routes, store, roster join, preview, the page) is real.

Run: python scripts/dev_fake_teamsnap.py   (port 8001, throwaway database)
Then every program created on it already has TeamSnap 'connected'.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

os.environ.setdefault("OFFDAYS_DB_PATH", str(Path(tempfile.mkdtemp()) / "fake-teamsnap.db"))
os.environ["OFFDAYS_TEAMSNAP_CLIENT_ID"] = "dummy-id"
os.environ["OFFDAYS_TEAMSNAP_CLIENT_SECRET"] = "dummy-secret"

import uvicorn  # noqa: E402

import offdays.api as api_module  # noqa: E402
from offdays import teamsnap  # noqa: E402
from test_teamsnap import FAKE  # noqa: E402

teamsnap._get = lambda token, path, **params: FAKE[path]

# Every new program is already connected, so the page can be walked without
# a TeamSnap login.
_orig = api_module.Store.teamsnap_status


def _status(self, org_id):
    if not self.teamsnap_token(org_id):
        self.set_teamsnap(org_id, "tok-fake", "Joel White (fake)")
    return _orig(self, org_id)


api_module.Store.teamsnap_status = _status

if __name__ == "__main__":
    uvicorn.run(api_module.app, host="127.0.0.1", port=8001, log_level="warning")
