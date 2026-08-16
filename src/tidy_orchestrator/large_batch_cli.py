"""Provider-free CLI for the registered product-prototype batch."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .artifacts import LocalArtifactRepository, canonical_json_bytes, domain_digest
from .large_batch import (
    LargeBatchSpec,
    load_large_batch_registry,
    verify_batch_normalization,
    verify_large_batch_evidence,
    verify_large_batch_reproduction,
)
from .product_prototype import run_product_prototype

BATCH_RUN_SCHEMA = "tidy.product-prototype-large-batch-run/v1"


def _run_one(
    project: Path,
    output: Path,
    spec: LargeBatchSpec,
    recorded_at: str,
) -> dict[str, Any]:
    cohort_output = output / spec.family_id
    result = run_product_prototype(
        repository=LocalArtifactRepository(cohort_output / "repository"),
        project_root=project,
        cohort_path=project / spec.cohort_path,
        output_root=cohort_output,
        mode="replay",
        recorded_at=recorded_at,
    )
    report = result.report
    verify_large_batch_reproduction(project, spec, cohort_output)
    passed = (
        report["providerCalls"] == 0
        and report["acceptedWorkbookCount"] == len(spec.expected_years)
        and report["exceptionWorkbookCount"] == 0
        and report["canonicalObservationCount"] == spec.expected_canonical_count
        and report["crossYearIssues"] == []
        and [item["observationCount"] for item in report["workbooks"]]
        == list(spec.expected_year_counts)
        and all(
            item["decision"] == "prototype_auto_accepted"
            and item["issues"] == []
            and all(item["checks"].values())
            for item in report["workbooks"]
        )
    )
    return {
        "familyId": spec.family_id,
        "passed": passed,
        "runDigest": report["runDigest"],
        "acceptedWorkbookCount": report["acceptedWorkbookCount"],
        "exceptionWorkbookCount": report["exceptionWorkbookCount"],
        "canonicalObservationCount": report["canonicalObservationCount"],
        "providerCalls": report["providerCalls"],
        "crossYearIssues": report["crossYearIssues"],
        "outputPath": spec.family_id,
    }


def run_batch(
    project: Path,
    output: Path,
    *,
    concurrency: int,
) -> dict[str, Any]:
    registry = load_large_batch_registry(project)
    recorded_at = registry.replay_recorded_at
    verify_batch_normalization(project, registry)
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_run_one, project, output, spec, recorded_at): spec
            for spec in registry.entries
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                results.append(future.result())
            except Exception as error:
                results.append(
                    {
                        "familyId": spec.family_id,
                        "passed": False,
                        "error": str(error),
                    }
                )
    results.sort(key=lambda item: item["familyId"])
    semantic = {
        "schemaVersion": BATCH_RUN_SCHEMA,
        "batchId": registry.batch_id,
        "recordedAt": recorded_at,
        "concurrency": concurrency,
        "providerCalls": sum(int(item.get("providerCalls", 0)) for item in results),
        "acceptedWorksheetCount": sum(
            int(item.get("acceptedWorkbookCount", 0)) for item in results
        ),
        "exceptionWorksheetCount": sum(
            int(item.get("exceptionWorkbookCount", 0)) for item in results
        ),
        "canonicalObservationCount": sum(
            int(item.get("canonicalObservationCount", 0)) for item in results
        ),
        "passed": len(results) == len(registry.entries)
        and all(item.get("passed") is True for item in results),
        "cohorts": results,
    }
    report = {
        **semantic,
        "batchRunDigest": domain_digest(BATCH_RUN_SCHEMA, semantic),
    }
    (output / "batch-run.json").write_bytes(canonical_json_bytes(report) + b"\n")
    return report


def verify_batch(project: Path) -> dict[str, Any]:
    registry = load_large_batch_registry(project)
    verify_batch_normalization(project, registry)
    manifests = [
        verify_large_batch_evidence(project, spec) for spec in registry.entries
    ]
    return {
        "batchId": registry.batch_id,
        "worksheetCount": registry.worksheet_count,
        "cohortCount": len(registry.entries),
        "canonicalObservationCount": sum(
            item["canonicalObservationCount"] for item in manifests
        ),
        "providerCalls": sum(item["providerCalls"] for item in manifests),
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="tidy-prototype-batch")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run all registered provider-free cohorts")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--concurrency", type=int, default=3)
    commands.add_parser("verify", help="verify all committed batch evidence")
    arguments = parser.parse_args()
    project = arguments.project_root.resolve()
    if arguments.command == "verify":
        report = verify_batch(project)
    else:
        if not 1 <= arguments.concurrency <= 4:
            parser.error("--concurrency must be between 1 and 4")
        report = run_batch(
            project,
            arguments.output.resolve(),
            concurrency=arguments.concurrency,
        )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report.get("verified") is True or report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
