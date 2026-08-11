"""CLI for sanitized, read-only NAS readiness inspection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .nas_readiness import inspect_nas_readiness, write_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tidy-nas-readiness")
    parser.add_argument("--mount-path", type=Path, required=True)
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inspected-at", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = inspect_nas_readiness(
        mount_path=args.mount_path,
        metadata_root=args.metadata_root,
        inspected_at=args.inspected_at,
    )
    write_report(args.output, report)
    result = {
        "ok": True,
        "reportDigest": report["reportDigest"],
        "smb3Current": report["gates"]["smb3Current"],
        "smbSigningRequired": report["gates"]["smbSigningRequired"],
        "sqliteLocal": report["gates"]["sqliteLocal"],
        "canaryImportReady": False,
        "blockers": report["blockers"],
        "configurationChanged": False,
    }
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
