"""Command-line entrypoint for the end-to-end product prototype."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .artifacts import LocalArtifactRepository, sha256_digest
from .product_prototype import PROMPT_CONTRACT, run_product_prototype
from .provider_gateway import AuthorizedPiProvider, BudgetLedger


def main() -> int:
    parser = argparse.ArgumentParser(prog="tidy-prototype")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="run the exact product cohort")
    run.add_argument("--cohort", type=Path, required=True)
    run.add_argument("--mode", choices=("replay", "live"), default="replay")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--repository", type=Path)
    run.add_argument("--project-root", type=Path, default=Path.cwd())
    run.add_argument("--recorded-at")
    run.add_argument("--live-response-root", type=Path)
    run.add_argument("--live-attempts", type=Path)
    run.add_argument("--live-authorization", type=Path)
    arguments = parser.parse_args()
    if arguments.command != "run":
        return 2
    project = arguments.project_root.resolve()
    repository_root = (
        arguments.repository or arguments.output / "repository"
    ).resolve()
    if arguments.live_authorization is not None and arguments.mode != "live":
        parser.error("--live-authorization requires --mode live")
    if arguments.live_attempts is not None and arguments.mode != "live":
        parser.error("--live-attempts requires --mode live")
    if arguments.live_authorization is not None and arguments.live_response_root:
        parser.error("choose live authorization or stored live responses, not both")
    live_attempts = (
        json.loads(arguments.live_attempts.read_text())
        if arguments.live_attempts is not None
        else None
    )
    provider = None
    if arguments.live_authorization is not None:
        cohort_digest = sha256_digest(arguments.cohort.resolve().read_bytes())
        prompt_contract_digest = sha256_digest(PROMPT_CONTRACT.encode("utf-8"))
        provider = AuthorizedPiProvider(
            authorization_path=arguments.live_authorization,
            cohort_digest=cohort_digest,
            prompt_contract_digest=prompt_contract_digest,
            ledger=BudgetLedger(
                (arguments.output / "provider-budget.sqlite3").resolve(),
                maximum_calls=6,
                maximum_cost=2.0,
            ),
            restricted_root=(arguments.output / "restricted").resolve(),
        )
    result = run_product_prototype(
        repository=LocalArtifactRepository(repository_root),
        project_root=project,
        cohort_path=arguments.cohort,
        output_root=arguments.output,
        mode=arguments.mode,
        recorded_at=arguments.recorded_at,
        live_response_root=arguments.live_response_root,
        live_attempts=live_attempts,
        provider=provider,
    )
    print(json.dumps(result.report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
