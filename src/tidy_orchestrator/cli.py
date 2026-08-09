"""Provider-free command-line entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .application import run_fixture_suite, suite_wire
from .artifacts import LocalArtifactRepository


def main() -> int:
    parser = argparse.ArgumentParser(prog="tidy-provider-free")
    subcommands = parser.add_subparsers(dest="command", required=True)
    demo = subcommands.add_parser("demo", help="run every licensed fixture twice")
    demo.add_argument("--repository", type=Path, required=True)
    demo.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    if arguments.command == "demo":
        repository = LocalArtifactRepository(arguments.repository)
        result = run_fixture_suite(
            repository=repository, project_root=arguments.project_root
        )
        print(json.dumps(suite_wire(result), sort_keys=True, separators=(",", ":")))
        return 0
    return 2
