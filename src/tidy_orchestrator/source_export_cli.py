"""Provider-free source-estate inventory and freeze CLI."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes
from .source_export import (
    SourceExportError,
    build_inventory,
    freeze_snapshot,
    load_and_verify_export,
    load_policy,
    publish_snapshot_to_nas,
    verify_nas_snapshot_publication,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "verify":
            wire, digest = load_and_verify_export(arguments.input)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "verify",
                        "schemaVersion": wire["schemaVersion"],
                        "verifiedDigest": digest,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        if arguments.command == "verify-publication":
            commit = verify_nas_snapshot_publication(arguments.directory)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "verify-publication",
                        "directory": str(arguments.directory),
                        **commit,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        if arguments.command == "publish":
            directory, commit, created = publish_snapshot_to_nas(
                snapshot_path=arguments.input,
                destination_root=arguments.destination_root,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "publish",
                        "directory": str(directory),
                        "created": created,
                        **commit,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        _require_output_outside_source(arguments.source_root, arguments.output)
        policy = load_policy(arguments.policy)
        result = build_inventory(
            source_root=arguments.source_root,
            source_root_id=arguments.source_root_id,
            destination_root=arguments.destination_root,
            destination_id=arguments.destination_id,
            policy=policy,
        )
        if arguments.command == "inventory":
            wire = result.report_wire()
            replace = arguments.replace
        else:
            wire = freeze_snapshot(result, frozen_at=arguments.frozen_at)
            replace = False
        _write_json_atomic(arguments.output, wire, replace=replace)
        _print_success(arguments.command, arguments.output, wire)
        return 0
    except (OSError, ValueError, SourceExportError) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(error).__name__,
                    "message": str(error),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tidy-source-export")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inventory = subcommands.add_parser(
        "inventory",
        help="write a deterministic read-only inventory plus storage assessment",
    )
    _common_arguments(inventory)
    inventory.add_argument(
        "--replace",
        action="store_true",
        help="atomically replace an existing inventory report",
    )
    freeze = subcommands.add_parser(
        "freeze",
        help="write an immutable snapshot only when destination headroom passes",
    )
    _common_arguments(freeze)
    freeze.add_argument("--frozen-at", required=True)
    verify = subcommands.add_parser(
        "verify", help="verify a report or frozen snapshot and its digests"
    )
    verify.add_argument("--input", type=Path, required=True)
    publish = subcommands.add_parser(
        "publish",
        help="publish a verified snapshot to a NAS behind a commit marker",
    )
    publish.add_argument("--input", type=Path, required=True)
    publish.add_argument("--destination-root", type=Path, required=True)
    verify_publication = subcommands.add_parser(
        "verify-publication",
        help="verify a committed NAS snapshot directory and exact bytes",
    )
    verify_publication.add_argument("--directory", type=Path, required=True)
    return parser


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-root-id", required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--destination-id", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)


def _require_output_outside_source(source_root: Path, output: Path) -> None:
    source = source_root.absolute()
    candidate = output.absolute()
    try:
        candidate.relative_to(source)
    except ValueError:
        return
    raise ValueError("Output must not be written inside the source root")


def _write_json_atomic(path: Path, value: Any, *, replace: bool) -> None:
    path = path.absolute()
    parent = path.parent
    parent_existed = parent.exists()
    if not parent_existed:
        try:
            parent.mkdir(parents=True, exist_ok=False, mode=0o700)
        except FileExistsError:
            parent_existed = True
    parent_stat = parent.lstat()
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise ValueError("Output parent must be a non-symlink directory")
    if not parent_existed:
        os.chmod(parent, 0o700)
    if path.exists() or path.is_symlink():
        target = path.lstat()
        if stat.S_ISLNK(target.st_mode) or not stat.S_ISREG(target.st_mode):
            raise ValueError("Existing output must be a regular non-symlink file")
        if not replace:
            raise FileExistsError("Output already exists")
    payload = canonical_json_bytes(value) + b"\n"
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            descriptor = -1
            raise
        if replace:
            os.replace(temporary, path)
            temporary = None
        else:
            os.link(temporary, path, follow_symlinks=False)
            temporary.unlink()
            temporary = None
        os.chmod(path, 0o600)
        directory_descriptor = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _print_success(command: str, output: Path, wire: dict[str, Any]) -> None:
    inventory = wire["inventory"]
    storage = wire["storageAssessment"]
    print(
        json.dumps(
            {
                "ok": True,
                "command": command,
                "output": str(output),
                "inventoryDigest": inventory["inventoryDigest"],
                "itemCount": inventory["summary"]["itemCount"],
                "uniqueImportObjects": inventory["summary"]["uniqueImportObjects"],
                "uniqueImportBytes": inventory["summary"]["uniqueImportBytes"],
                "headroomPasses": storage["passes"],
                "snapshotDigest": wire.get("snapshotDigest"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
