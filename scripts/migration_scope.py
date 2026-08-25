#!/usr/bin/env python3
"""Print what a Postgres migration would actually cost.

Run before estimating one. The number is measured from the code rather than
remembered from the README, which was wrong about it for a long time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from athleteiq import dialect  # noqa: E402

if __name__ == "__main__":
    print(dialect.render())
