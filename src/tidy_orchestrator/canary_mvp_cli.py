"""CLI for the exact frozen 63-item hobby canary."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
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
    run.add_argument("--recorded-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command != "run":
        raise AssertionError("unreachable")
    recorded_at = arguments.recorded_at or datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        smb_verifier = _verify_smb(arguments.blob_root)
        report = run_canary_mvp(
            source_snapshot_path=arguments.source_snapshot,
            manifest_path=arguments.manifest,
            source_root=arguments.source_root,
            metadata_root=arguments.metadata_root,
            blob_root=arguments.blob_root,
            output_root=arguments.output_root,
            recorded_at=recorded_at,
            smb_verifier=smb_verifier,
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


def _verify_smb(blob_root: Path) -> dict[str, object]:
    blob_root = blob_root.resolve()
    mount_output = subprocess.run(
        ["/sbin/mount"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    ).stdout
    candidates = []
    for line in mount_output.splitlines():
        if " (smbfs," not in line or " on " not in line:
            continue
        target = Path(line.split(" on ", 1)[1].split(" (", 1)[0]).resolve()
        if blob_root == target or target in blob_root.parents:
            candidates.append((len(target.parts), target, line))
    if not candidates:
        raise CanaryMvpError("Canary blob root is not on a mounted SMB share")
    _depth, mount, mount_line = max(candidates)
    completed = subprocess.run(
        ["/usr/bin/smbutil", "statshares", "-m", str(mount), "-f", "JSON"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    values = json.loads(completed.stdout)
    if not isinstance(values, list) or len(values) != 1:
        raise CanaryMvpError("SMB verifier did not return one mounted share")
    share = values[0]
    if not isinstance(share, dict):
        raise CanaryMvpError("SMB verifier returned an invalid share")
    service_label = mount_line.removeprefix("//").split("@", 1)[0]
    return {
        "shareName": share.get("share_name"),
        "smbVersion": share.get("SMB_VERSION"),
        "signingRequired": share.get("SIGNING_REQUIRED") is True,
        "signingOn": share.get("SIGNING_ON") is True,
        "signingAlgorithm": share.get("SMB_CURR_SIGN_ALGORITHM"),
        "serviceIdentityLabel": service_label,
    }


if __name__ == "__main__":
    raise SystemExit(main())
