"""CLI for deterministic no-copy real-import canary selection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .migration_canary import (
    freeze_canary_from_snapshot,
    load_canary_manifest,
    verify_migration_canary,
    write_canary_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tidy-migration-canary")
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--snapshot", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--frozen-at", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--snapshot", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "freeze":
        manifest = freeze_canary_from_snapshot(
            snapshot_path=args.snapshot,
            frozen_at=args.frozen_at,
        )
        write_canary_manifest(args.output, manifest)
        result = {
            "command": "freeze",
            "ok": True,
            "manifestDigest": manifest["manifestDigest"],
            "itemCount": manifest["coverage"]["itemCount"],
            "sourceReadBytes": manifest["coverage"]["sourceReadBytes"],
            "uniqueCopyBytes": manifest["coverage"]["uniqueCopyBytes"],
            "sourceBytesCopied": False,
            "importAuthorized": False,
        }
    else:
        manifest = load_canary_manifest(args.manifest)
        verify_migration_canary(manifest=manifest, snapshot_path=args.snapshot)
        result = {
            "command": "verify",
            "ok": True,
            "manifestDigest": manifest["manifestDigest"],
            "itemCount": manifest["coverage"]["itemCount"],
            "sourceBytesCopied": False,
            "importAuthorized": False,
        }
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
