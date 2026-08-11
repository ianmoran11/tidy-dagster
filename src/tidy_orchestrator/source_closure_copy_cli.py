"""CLI for transactional reviewed source-closure custody."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .source_closure_copy import copy_source_closure, verify_source_closure_copy


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tidy-source-closure-copy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    copy_parser = subparsers.add_parser("copy")
    copy_parser.add_argument("--config", type=Path, required=True)
    copy_parser.add_argument("--manifest", type=Path, required=True)
    copy_parser.add_argument("--review", type=Path, required=True)
    copy_parser.add_argument("--destination", type=Path, required=True)
    copy_parser.add_argument("--copied-at", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--directory", type=Path, required=True)
    arguments = parser.parse_args(argv)

    if arguments.command == "copy":
        commit = copy_source_closure(
            request_path=arguments.config,
            manifest_path=arguments.manifest,
            review_path=arguments.review,
            destination=arguments.destination,
            copied_at=arguments.copied_at,
        )
        result = {
            "command": "copy",
            "ok": True,
            "commitDigest": commit["commitDigest"],
            "closureManifestDigest": commit["closureManifestDigest"],
            "itemCount": commit["itemCount"],
            "byteLength": commit["byteLength"],
            "runtimeAuthorized": False,
            "parityEstablished": False,
        }
    else:
        commit = verify_source_closure_copy(arguments.directory)
        result = {
            "command": "verify",
            "ok": True,
            "commitDigest": commit["commitDigest"],
            "closureManifestDigest": commit["closureManifestDigest"],
            "itemCount": commit["itemCount"],
            "byteLength": commit["byteLength"],
            "runtimeAuthorized": False,
            "parityEstablished": False,
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0
