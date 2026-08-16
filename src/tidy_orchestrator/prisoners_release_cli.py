"""CLI for the checked Prisoners in Australia release inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .prisoners_release import verify_prisoners_release


def main() -> int:
    parser = argparse.ArgumentParser(prog="tidy-prisoners-release")
    parser.add_argument("command", choices=("verify",))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    report = verify_prisoners_release(arguments.project_root)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
