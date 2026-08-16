#!/usr/bin/env python3
"""Generate or byte-check the deterministic Prisoners release manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from tidy_orchestrator.prisoners_release import (  # noqa: E402
    build_family_membership,
    build_source_inventory,
)


def encoded(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    arguments = parser.parse_args()
    project = arguments.project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    downloads_path = root / "prisoners-release-downloads-v1.json"
    crosswalk_path = root / "prisoners-release-family-crosswalk-v1.json"
    downloads = json.loads(downloads_path.read_text())
    crosswalk = json.loads(crosswalk_path.read_text())
    inventory = build_source_inventory(project)
    membership = build_family_membership(project, inventory)
    outputs = {
        downloads_path: encoded(downloads),
        crosswalk_path: encoded(crosswalk),
        root / "prisoners-release-source-inventory-v1.json": encoded(inventory),
        root / "prisoners-release-family-membership-v1.json": encoded(membership),
    }
    for path, content in outputs.items():
        if arguments.check:
            if not path.is_file() or path.read_bytes() != content:
                print(
                    f"generated file differs: {path.relative_to(project)}",
                    file=sys.stderr,
                )
                return 1
        else:
            path.write_bytes(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
