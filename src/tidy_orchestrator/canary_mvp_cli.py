"""CLI for the exact frozen 63-item hobby canary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .canary_mvp import CanaryMvpError, run_canary_mvp

_PROJECT = Path(__file__).parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tidy-canary-mvp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument(
        "--source-snapshot",
        type=Path,
        default=_PROJECT / ".source-exports/tidycell-phase-a-snapshot-v1-final.json",
    )
    run.add_argument(
        "--manifest",
        type=Path,
        default=_PROJECT / "fixtures/migration-canary/phase-b-canary-v1.json",
    )
    run.add_argument("--source-root", type=Path, required=True)
    run.add_argument("--metadata-root", type=Path, required=True)
    run.add_argument("--blob-root", type=Path, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument(
        "--recorded-at",
        default="2026-08-13T10:00:00Z",
        help="immutable evidence time (defaults to the checked local MVP run)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command != "run":
        raise AssertionError("unreachable")
    recorded_at = arguments.recorded_at
    try:
        report = run_canary_mvp(
            source_snapshot_path=arguments.source_snapshot,
            manifest_path=arguments.manifest,
            source_root=arguments.source_root,
            metadata_root=arguments.metadata_root,
            blob_root=arguments.blob_root,
            output_root=arguments.output_root,
            recorded_at=recorded_at,
        )
    except (CanaryMvpError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(error).__name__,
                    "message": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"ok": True, "report": report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
