"""CLI for read-only, no-copy source-closure discovery."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .source_closure_discovery import (
    canonical_manifest_digest,
    discover_source_closure,
    load_discovery_manifest,
    load_discovery_request,
    verify_source_closure,
    write_manifest_atomic,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tidy-source-closure")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--config", type=Path, required=True)
    discover.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--config", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = load_discovery_request(args.config)
    if args.command == "discover":
        manifest = discover_source_closure(request)
        write_manifest_atomic(args.output, manifest)
        result = {
            "command": "discover",
            "ok": True,
            "manifestDigest": manifest["manifestDigest"],
            "itemCount": manifest["totals"]["itemCount"],
            "byteLength": manifest["totals"]["byteLength"],
            "sourceBytesCopied": False,
        }
    else:
        manifest = load_discovery_manifest(args.manifest)
        canonical_manifest_digest(manifest)
        verify_source_closure(manifest=manifest, request=request)
        result = {
            "command": "verify",
            "ok": True,
            "manifestDigest": manifest["manifestDigest"],
            "sourceBytesCopied": False,
        }
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0
