"""CLI for freezing and resolving exact reviewer-label confirmation requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .reviewer_confirmation import (
    create_reviewer_confirmation_decision,
    freeze_reviewer_confirmation_request,
    write_confirmation_request,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="tidy-reviewer-confirmation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--snapshot", required=True, type=Path)
    freeze.add_argument("--source-root", required=True, type=Path)
    freeze.add_argument("--output", required=True, type=Path)
    freeze.add_argument("--frozen-at", required=True)

    decide = subparsers.add_parser("decide")
    decide.add_argument("--request", required=True, type=Path)
    decide.add_argument("--output", required=True, type=Path)
    decide.add_argument("--display-name", required=True)
    decide.add_argument("--label", required=True, action="append")
    decide.add_argument("--curated-by", required=True)
    decide.add_argument("--selected-answer", required=True)
    decide.add_argument("--recorded-at", required=True)

    args = parser.parse_args()
    if args.command == "freeze":
        record = freeze_reviewer_confirmation_request(
            snapshot_path=args.snapshot,
            source_root=args.source_root,
            frozen_at=args.frozen_at,
        )
        write_confirmation_request(args.output, record)
        summary = {
            "ok": True,
            "command": "freeze",
            "requestDigest": record["requestDigest"],
            "approvalRowCount": record["approvalRowCount"],
            "distinctExactLabelCount": record["distinctExactLabelCount"],
            "reviewerAuthorityCreated": False,
        }
    else:
        request = json.loads(args.request.read_bytes())
        record = create_reviewer_confirmation_decision(
            request=request,
            display_name=args.display_name,
            confirmed_labels=args.label,
            curated_by=args.curated_by,
            selected_answer=args.selected_answer,
            recorded_at=args.recorded_at,
        )
        write_confirmation_request(args.output, record)
        summary = {
            "ok": True,
            "command": "decide",
            "decisionDigest": record["decisionDigest"],
            "reviewerId": record["reviewerIdentity"]["reviewerId"],
            "confirmedLabelCount": sum(
                entry["decision"] == "confirmed-human-identity"
                for entry in record["decisions"]
            ),
            "approvalAuthorityCreated": False,
        }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
