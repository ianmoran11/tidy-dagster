from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .data_asset_status import DEFAULT_REGISTRY, default_project_root
from .sqlite_export import (
    DEFAULT_OUTPUT,
    SQLiteExportError,
    build_export,
    check_export,
    package_checked_export,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tidy-sqlite-export",
        description="build and verify the consolidated registered-data SQLite export",
    )
    parser.add_argument("--project-root", type=Path, default=default_project_root())
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="atomically build the raw SQLite file")
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    check = commands.add_parser(
        "check", help="check SQLite and current registered evidence"
    )
    check.add_argument("--database", type=Path, default=DEFAULT_OUTPUT)
    package = commands.add_parser(
        "package", help="create a deterministic, release-ready gzip"
    )
    package.add_argument("--database", type=Path, default=DEFAULT_OUTPUT)
    package.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.project_root.resolve()
    try:
        if arguments.command == "build":
            result = build_export(root, arguments.registry, arguments.output)
        elif arguments.command == "check":
            result = check_export(root, arguments.registry, arguments.database)
        else:
            database = (
                arguments.database
                if arguments.database.is_absolute()
                else root / arguments.database
            )
            output = arguments.output
            if output is not None and not output.is_absolute():
                output = root / output
            checked = check_export(root, arguments.registry, database)
            result = package_checked_export(database, checked, output)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except SQLiteExportError as error:
        print(f"sqlite export error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
