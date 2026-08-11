"""CLI for freezing exact reviewer-label confirmation requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .reviewer_confirmation import (
    freeze_reviewer_confirmation_request,
    write_confirmation_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="tidy-reviewer-confirmation")
    parser.add_argument("freeze", choices=("freeze",))
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frozen-at", required=True)
    args = parser.parse_args()
    record = freeze_reviewer_confirmation_request(
        snapshot_path=args.snapshot,
        source_root=args.source_root,
        frozen_at=args.frozen_at,
    )
    write_confirmation_request(args.output, record)
    print(
        json.dumps(
            {
                "ok": True,
                "requestDigest": record["requestDigest"],
                "approvalRowCount": record["approvalRowCount"],
                "distinctExactLabelCount": record["distinctExactLabelCount"],
                "reviewerAuthorityCreated": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
