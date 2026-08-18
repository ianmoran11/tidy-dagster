"""CLI for the checked Criminal Courts, Australia release inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .criminal_courts_release import verify_criminal_courts_release


def default_project_root() -> Path:
    """Locate the source repository independently of caller CWD."""
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(prog="tidy-criminal-courts-release")
    parser.add_argument("command", choices=("verify",))
    parser.add_argument(
        "--project-root",
        type=Path,
        default=default_project_root(),
        help="repository root (defaults to the installed module repository)",
    )
    arguments = parser.parse_args()
    report = verify_criminal_courts_release(arguments.project_root)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
