"""Run the 0FFDAYS API server.

    python -m offdays
    python -m offdays --help

Defaults to one worker on 127.0.0.1:8000. Override with env or CLI flags.
The app is a single-process, stdlib-only service; the right production setup
is one uvicorn worker behind a reverse proxy, with scripts/health_reap.py on a
cron timer for WAL checkpointing, stale-session cleanup, disk alarms, and
optional live backups.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger("offdays")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--host",
        default=os.environ.get("OFFDAYS_HOST", "127.0.0.1"),
        help="bind host (default: 127.0.0.1 or OFFDAYS_HOST)",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OFFDAYS_PORT", "8000")),
        help="bind port (default: 8000 or OFFDAYS_PORT)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="uvicorn workers (default: 1, because this app is not yet stateless "
        "at the worker level; see docs before setting >1)",
    )
    ap.add_argument(
        "--log-level",
        default=os.environ.get("OFFDAYS_LOG_LEVEL", "info"),
        help="uvicorn log level (default: info or OFFDAYS_LOG_LEVEL)",
    )
    ap.add_argument(
        "--db",
        default=os.environ.get("OFFDAYS_DB_PATH"),
        help="database path (default: CONFIG default or OFFDAYS_DB_PATH)",
    )
    ap.add_argument(
        "--reload",
        action="store_true",
        help="uvicorn reload (development only)",
    )
    args = ap.parse_args()

    if args.db:
        from offdays.config import CONFIG

        CONFIG.db_path = Path(args.db)

    # Import here so the config can be adjusted before the app binds the DB.
    from uvicorn import run as uvicorn_run

    from offdays.api import app

    logger.info(
        "starting offdays %s on %s:%s (db=%s, workers=%s, reload=%s)",
        app.version,
        args.host,
        args.port,
        CONFIG.db_path,
        args.workers,
        args.reload,
    )

    uvicorn_run(
        "offdays.api:app",
        host=args.host,
        port=args.port,
        workers=args.workers or 1,
        log_level=args.log_level,
        reload=args.reload,
        proxy_headers=True,
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
