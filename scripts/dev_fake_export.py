"""A local server whose "Another program" export link always answers with a
small CSV, for walking the roster sync links table on the real page. Only the
HTTP GET to the other service is replaced; routes, store, parser and page are
real.

Run: python scripts/dev_fake_export.py [port]   (default 8002, throwaway database)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("OFFDAYS_DB_PATH", str(Path(tempfile.mkdtemp()) / "fake-export.db"))

import uvicorn  # noqa: E402

import offdays.api as api_module  # noqa: E402
from offdays import roster_sync  # noqa: E402

CSV = (
    "First Name,Last Name,Jersey,Birth Year,Parent Email\n"
    "Bo,Short,7,2013,bo.parent@example.invalid\n"
    "Alexandra,Montgomery-Smith,12,2013,am.parent@example.invalid\n"
)

roster_sync._get = lambda url, headers=None: CSV.encode()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8002
    uvicorn.run(api_module.app, host="127.0.0.1", port=port, log_level="warning")
