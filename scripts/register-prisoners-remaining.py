#!/usr/bin/env python3
"""Freeze and atomically register the checked remaining Prisoners campaign."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tidy_orchestrator.artifacts import (  # noqa: E402
    LocalArtifactRepository,
    canonical_json_bytes,
    domain_digest,
    sha256_digest,
)
from tidy_orchestrator.large_batch import (  # noqa: E402
    load_large_batch_registry,
    verify_large_batch_complete_reproduction,
    verify_large_batch_evidence,
)
from tidy_orchestrator.product_prototype import run_product_prototype  # noqa: E402

FIX = ROOT / "fixtures" / "product-prototype"
PLAN_PATH = FIX / "prisoners-remaining-semantic-map-plan-v1.json"
SCRATCH = ROOT / ".product-prototype" / "prisoners-remaining-phase1" / "scratch"
LARGE_BATCH_PATH = FIX / "large-batch-assets-v1.json"
STATUS_PATH = FIX / "data-asset-status-v1.json"
NORMALIZATION_PATH = FIX / "prisoners-remaining-workbook-normalization-v1.json"
NORMALIZATION_SCHEMA = "tidy.prisoners-remaining-workbook-normalization/v1"
RECORDED_AT = "2026-08-25T12:00:00+00:00"
EVIDENCE_FILES = {
    "README.md",
    "canonical-observations.csv",
    "canonical-observations.json",
    "collation-report.json",
    "exceptions.json",
    "manifest.json",
    "run.json",
}
COPIED_FILES = EVIDENCE_FILES - {"README.md", "manifest.json"}
EXPECTED = {
    "families": 21,
    "members": 69,
    "observations": 34_837,
    "largeBatchCohorts": 241,
    "largeBatchWorksheets": 628,
    "largeBatchObservations": 512_957,
    "statusCohorts": 246,
    "statusWorksheets": 653,
    "statusObservations": 526_240,
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _title(family_id: str) -> str:
    title = " ".join(
        word.upper() if word == "anzsoc" else word for word in family_id.split("-")
    )
    return title[:1].upper() + title[1:]


def _family_ids() -> list[str]:
    plan = _load(PLAN_PATH)
    if (
        plan.get("acceptanceAuthority") is not False
        or plan.get("trainingEligibility") is not False
        or not isinstance(plan.get("families"), list)
    ):
        raise RuntimeError("remaining Prisoners plan authority claims are unsafe")
    family_ids = [item["familyId"] for item in plan["families"]]
    members = sum(len(item["members"]) for item in plan["families"])
    if len(family_ids) != EXPECTED["families"] or members != EXPECTED["members"]:
        raise RuntimeError("remaining Prisoners plan closure mismatch")
    if len(family_ids) != len(set(family_ids)):
        raise RuntimeError("remaining Prisoners plan repeats a family")
    return family_ids


def _validate_scratch(
    family_ids: list[str], scratch: Path
) -> dict[str, dict[str, Any]]:
    actual_dirs = {item.name for item in scratch.iterdir() if item.is_dir()}
    if actual_dirs != set(family_ids):
        raise RuntimeError("scratch family directory closure mismatch")
    reports: dict[str, dict[str, Any]] = {}
    members = observations = providers = exceptions = warnings = issues = 0
    for family_id in family_ids:
        root = scratch / family_id
        actual = {item.name for item in root.iterdir() if item.is_file()}
        if not actual >= COPIED_FILES:
            raise RuntimeError(f"scratch evidence is incomplete: {family_id}")
        run = _load(root / "run.json")
        rows = _load(root / "canonical-observations.json")
        excluded = _load(root / "exceptions.json")
        collation = _load(root / "collation-report.json")
        workbooks = run.get("workbooks", [])
        if (
            run.get("providerCalls") != 0
            or run.get("historicalReplayIsAcceptanceAuthority") is not False
            or run.get("trainingEligibility") is not False
            or run.get("exceptionWorkbookCount") != 0
            or run.get("crossYearIssues") != []
            or excluded != []
            or len(rows) != run.get("canonicalObservationCount")
            or collation.get("rowCount") != len(rows)
            or any(
                workbook.get("decision") != "prototype_auto_accepted"
                or workbook.get("issues") != []
                or workbook.get("executionWarningCount") != 0
                or any(
                    value is not True for value in workbook.get("checks", {}).values()
                )
                for workbook in workbooks
            )
        ):
            raise RuntimeError(f"scratch evidence is not clean: {family_id}")
        members += len(workbooks)
        observations += len(rows)
        providers += run["providerCalls"]
        exceptions += run["exceptionWorkbookCount"]
        warnings += sum(item["executionWarningCount"] for item in workbooks)
        issues += sum(len(item["issues"]) for item in workbooks)
        reports[family_id] = run
    if (members, observations, providers, exceptions, warnings, issues) != (
        EXPECTED["members"],
        EXPECTED["observations"],
        0,
        0,
        0,
        0,
    ):
        raise RuntimeError("scratch aggregate closure mismatch")
    return reports


def _readme(family_id: str) -> bytes:
    text = (
        f"# Checked evidence: Prisoners in Australia — {_title(family_id)}\n\n"
        "This directory freezes provider-free deterministic replay evidence for "
        f"`{family_id}`. Historical replay maps are generation inputs only and have "
        "`acceptanceAuthority: false`; the exact policy-v2 acceptance contract, "
        "date-bound decisions, pinned recipes, checks, workbook bytes, worksheet "
        "names, reference dates, and source cells are the acceptance evidence.\n\n"
        "Every member was accepted with zero provider calls, warnings, issues, "
        "exclusions, or exceptions. Training eligibility is false. Original ABS "
        "workbook bytes and source-custody manifests remain unchanged; any narrowly "
        "bounded workbook derivative is digest-pinned and preserves semantic cell, "
        "formula, and value parity.\n"
    )
    return text.encode()


def _manifest(family_id: str, bundle: Path) -> dict[str, Any]:
    cohort_relative = f"fixtures/product-prototype/prisoners-{family_id}.json"
    cohort_path = ROOT / cohort_relative
    cohort = _load(cohort_path)
    contract_relative = f"fixtures/product-prototype/{cohort['acceptanceContract']}"
    run = _load(bundle / "run.json")
    rows = _load(bundle / "canonical-observations.json")
    files = []
    for name in sorted(EVIDENCE_FILES - {"manifest.json"}):
        data = (bundle / name).read_bytes()
        files.append(
            {
                "path": name,
                "contentDigest": sha256_digest(data),
                "byteLength": len(data),
            }
        )
    historical_years = [
        workbook["year"]
        for workbook in cohort["workbooks"]
        if workbook["replayResponse"]["historicalModel"].startswith("human-authored")
    ]
    return {
        "schemaVersion": "tidy.product-prototype-large-batch-evidence/v1",
        "familyId": family_id,
        "cohortPath": cohort_relative,
        "cohortDigest": sha256_digest(cohort_path.read_bytes()),
        "acceptanceContractPath": contract_relative,
        "acceptanceContractDigest": sha256_digest(
            (ROOT / contract_relative).read_bytes()
        ),
        "recordedAt": RECORDED_AT,
        "mode": "replay",
        "providerCalls": 0,
        "acceptedWorkbookCount": run["acceptedWorkbookCount"],
        "exceptionWorkbookCount": 0,
        "rawObservationCount": sum(
            item["rawObservationCount"] for item in run["workbooks"]
        ),
        "excludedObservationCount": sum(
            item["excludedObservationCount"] for item in run["workbooks"]
        ),
        "canonicalObservationCount": len(rows),
        "measureCounts": dict(
            sorted(Counter(row["measure_id"] for row in rows).items())
        ),
        "valueStatusCounts": dict(
            sorted(Counter(row["value_status"] for row in rows).items())
        ),
        "warningCountsByYear": {
            str(item["year"]): item["executionWarningCount"]
            for item in run["workbooks"]
        },
        "manualReplayYears": historical_years,
        "publicationVintagePreserved": all(
            "publication_vintage_date" in row for row in rows
        ),
        "runDigest": run["runDigest"],
        "files": files,
    }


def _build_bundle(family_id: str, scratch: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for name in sorted(COPIED_FILES):
        shutil.copyfile(scratch / family_id / name, destination / name)
    (destination / "README.md").write_bytes(_readme(family_id))
    _write_json(destination / "manifest.json", _manifest(family_id, destination))
    actual = {item.name for item in destination.iterdir() if item.is_file()}
    if actual != EVIDENCE_FILES:
        raise RuntimeError(f"generated evidence closure mismatch: {family_id}")


def _large_entry(family_id: str, bundle: Path) -> dict[str, Any]:
    cohort = _load(FIX / f"prisoners-{family_id}.json")
    manifest = _load(bundle / "manifest.json")
    years = [item["year"] for item in cohort["workbooks"]]
    run = _load(bundle / "run.json")
    slug = family_id.replace("-", "_")
    return {
        "familyId": family_id,
        "label": f"Prisoners in Australia — {_title(family_id)}",
        "cohortPath": f"fixtures/product-prototype/prisoners-{family_id}.json",
        "evidenceManifestPath": (
            f"fixtures/product-prototype/prisoners-{family_id}-evidence/manifest.json"
        ),
        "dagsterAsset": f"product_prototype_prisoners_remaining_{slug}_replay",
        "dagsterJob": f"product_prototype_prisoners_remaining_{slug}_replay_job",
        "outputDirectory": f"dagster-prisoners-remaining-{family_id}-replay",
        "expectedYears": years,
        "expectedYearCounts": [item["observationCount"] for item in run["workbooks"]],
        "expectedCanonicalCount": manifest["canonicalObservationCount"],
        "expectedMeasureCounts": manifest["measureCounts"],
        "expectedValueStatusCounts": manifest["valueStatusCounts"],
        "expectedManualReplayYears": manifest["manualReplayYears"],
        "preservesPublicationVintage": manifest["publicationVintagePreserved"],
        "expectedExcludedObservationCount": 0,
        "expectedExcludedObservationCountsByYear": {str(year): 0 for year in years},
        "acceptancePolicyVersion": "tidy.table-family-acceptance/v2",
        "replayRecordedAt": RECORDED_AT,
    }


def _generated_normalization_manifest() -> dict[str, Any]:
    audit = _load(FIX / "prisoners-remaining-acceptance-audit-v1.json")
    generator_relative = "scripts/generate-prisoners-remaining-workbooks.py"
    entries = []
    normalization_by_output = {
        "workbooks/prisoners-australia-2025-national-remaining-bounded.xlsx": (
            "trim-pathological-full-width-formatting-merge-v1"
        ),
        "workbooks/prisoners-australia-2024-federal-remaining-bounded.xlsx": (
            "isolate-repeated-total-label-formatting-v1"
        ),
        "workbooks/prisoners-australia-2025-federal-remaining-bounded.xlsx": (
            "trim-table-37-and-isolate-repeated-total-label-formatting-v1"
        ),
    }
    year_by_output = {
        path: int(Path(path).name.split("-")[2]) for path in normalization_by_output
    }
    for parity in audit["boundedWorkbookParity"]:
        source = FIX / parity["sourcePath"]
        output = FIX / parity["boundedPath"]
        if (
            parity.get("coordinateValueFormulaParity") is not True
            or parity["boundedPath"] not in normalization_by_output
            or sha256_digest(source.read_bytes()) != parity["sourceDigest"]
            or sha256_digest(output.read_bytes()) != parity["boundedDigest"]
        ):
            raise RuntimeError("bounded workbook parity declaration is invalid")
        entries.append(
            {
                "normalization": normalization_by_output[parity["boundedPath"]],
                "year": year_by_output[parity["boundedPath"]],
                "sourcePath": f"fixtures/product-prototype/{parity['sourcePath']}",
                "sourceDigest": parity["sourceDigest"],
                "sourceByteLength": source.stat().st_size,
                "outputPath": f"fixtures/product-prototype/{parity['boundedPath']}",
                "outputDigest": parity["boundedDigest"],
                "outputByteLength": output.stat().st_size,
                "coordinateValueFormulaParity": True,
                "sourceSemanticCellCount": parity["sourceSemanticCellCount"],
                "outputSemanticCellCount": parity["boundedSemanticCellCount"],
            }
        )
    entries.sort(key=lambda item: item["outputPath"])
    manifest = {
        "schemaVersion": NORMALIZATION_SCHEMA,
        "recordedAt": RECORDED_AT,
        "generatorPath": generator_relative,
        "generatorDigest": sha256_digest((ROOT / generator_relative).read_bytes()),
        "entries": entries,
    }
    manifest["manifestDigest"] = domain_digest(NORMALIZATION_SCHEMA, manifest)
    return manifest


def _generated_registries(
    family_ids: list[str], bundles: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = [
        _large_entry(fid, bundles / f"prisoners-{fid}-evidence") for fid in family_ids
    ]
    campaign_ids = set(family_ids)
    large = _load(LARGE_BATCH_PATH)
    retained = [
        item for item in large["entries"] if item["familyId"] not in campaign_ids
    ]
    insertion = next(
        (
            i
            for i, item in enumerate(retained)
            if "recorded-crime-offenders" in item["cohortPath"]
        ),
        len(retained),
    )
    large["entries"] = retained[:insertion] + campaign + retained[insertion:]
    large["batchId"] = "justice-six-hundred-twenty-eight-worksheets-v1"
    large["recordedAt"] = RECORDED_AT
    large["worksheetCount"] = sum(
        len(item["expectedYears"]) for item in large["entries"]
    )
    if (
        len(large["entries"]) != EXPECTED["largeBatchCohorts"]
        or large["worksheetCount"] != EXPECTED["largeBatchWorksheets"]
        or sum(item["expectedCanonicalCount"] for item in large["entries"])
        != EXPECTED["largeBatchObservations"]
    ):
        raise RuntimeError("generated large-batch registry totals mismatch")

    status = _load(STATUS_PATH)
    campaign_status = [
        {
            "cohortId": f"prisoners-australia-{fid}",
            "label": entry["label"],
            "cohortPath": entry["cohortPath"],
            "evidenceManifestPath": entry["evidenceManifestPath"],
            "dagsterAsset": entry["dagsterAsset"],
        }
        for fid, entry in zip(family_ids, campaign, strict=True)
    ]
    campaign_cohort_ids = {item["cohortId"] for item in campaign_status}
    retained_status = [
        item
        for item in status["cohorts"]
        if item["cohortId"] not in campaign_cohort_ids
    ]
    insertion = next(
        (
            i
            for i, item in enumerate(retained_status)
            if "recorded-crime-offenders" in item["cohortPath"]
        ),
        len(retained_status),
    )
    status["cohorts"] = (
        retained_status[:insertion] + campaign_status + retained_status[insertion:]
    )
    status["recordedAt"] = RECORDED_AT
    if len(status["cohorts"]) != EXPECTED["statusCohorts"]:
        raise RuntimeError("generated status registry cohort total mismatch")
    return large, status


def _compare_tree(expected: Path, actual: Path) -> None:
    expected_files = {
        item.relative_to(expected).as_posix()
        for item in expected.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    actual_files = {
        item.relative_to(actual).as_posix()
        for item in actual.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    if expected_files != actual_files:
        raise RuntimeError("evidence tree file closure mismatch")
    for relative in sorted(expected_files):
        left, right = expected / relative, actual / relative
        if (
            left.is_symlink()
            or right.is_symlink()
            or left.read_bytes() != right.read_bytes()
        ):
            raise RuntimeError(f"evidence bytes differ: {relative}")


def _build_all(family_ids: list[str], scratch: Path, root: Path) -> None:
    _validate_scratch(family_ids, scratch)
    for family_id in family_ids:
        _build_bundle(family_id, scratch, root / f"prisoners-{family_id}-evidence")


def _with_fixed_scratch_reproduction(
    scratch: Path, reproduce: Callable[[Path], None]
) -> None:
    backup_prefix = f".{scratch.name}-reproduction-backup-"
    stale_backups = list(scratch.parent.glob(f"{backup_prefix}*"))
    if stale_backups:
        raise RuntimeError("stale scratch reproduction backup exists")
    if scratch.is_symlink() or not scratch.is_dir():
        raise RuntimeError("scratch reproduction source must be a real directory")
    backup = scratch.parent / f"{backup_prefix}{uuid.uuid4().hex}"
    if backup.exists() or backup.is_symlink():
        raise RuntimeError("scratch reproduction backup destination is occupied")

    os.replace(scratch, backup)
    try:
        reproduce(scratch)
    finally:
        _remove_path(scratch)
        if scratch.exists() or scratch.is_symlink():
            raise RuntimeError("generated scratch could not be removed before restore")
        os.replace(backup, scratch)


def _check(family_ids: list[str], *, reproduce: bool) -> None:
    _validate_scratch(family_ids, SCRATCH)
    with tempfile.TemporaryDirectory(prefix="prisoners-evidence-check-") as temporary:
        generated = Path(temporary) / "generated"
        generated.mkdir()
        _build_all(family_ids, SCRATCH, generated)
        for family_id in family_ids:
            checked = FIX / f"prisoners-{family_id}-evidence"
            _compare_tree(generated / checked.name, checked)
        large, status = _generated_registries(family_ids, generated)
        if canonical_json_bytes(large) + b"\n" != LARGE_BATCH_PATH.read_bytes():
            raise RuntimeError("large-batch registry differs from checked generation")
        if canonical_json_bytes(status) + b"\n" != STATUS_PATH.read_bytes():
            raise RuntimeError("status registry differs from checked generation")
        normalization = _generated_normalization_manifest()
        if (
            canonical_json_bytes(normalization) + b"\n"
            != NORMALIZATION_PATH.read_bytes()
        ):
            raise RuntimeError("bounded normalization manifest differs from generation")
        registry = load_large_batch_registry(ROOT)
        specs = {item.family_id: item for item in registry.entries}
        for family_id in family_ids:
            verify_large_batch_evidence(ROOT, specs[family_id])
            verify_large_batch_complete_reproduction(
                ROOT, specs[family_id], generated / f"prisoners-{family_id}-evidence"
            )
        if reproduce:

            def reproduce_from_empty_fixed_scratch(replay: Path) -> None:
                for family_id in family_ids:
                    output = replay / family_id
                    run_product_prototype(
                        repository=LocalArtifactRepository(output / "repository"),
                        project_root=ROOT,
                        cohort_path=FIX / f"prisoners-{family_id}.json",
                        output_root=output,
                        mode="replay",
                        recorded_at=RECORDED_AT,
                    )
                reproduced = Path(temporary) / "reproduced"
                reproduced.mkdir()
                _build_all(family_ids, replay, reproduced)
                _compare_tree(generated, reproduced)

            # Worker sandbox identities bind the fixed scratch path. Move the
            # checked tree aside atomically, reproduce from an empty path, then
            # restore the exact original tree even when execution or comparison fails.
            _with_fixed_scratch_reproduction(
                SCRATCH, reproduce_from_empty_fixed_scratch
            )


FailureInjector = Callable[[str, Path], None]
Replacement = tuple[str, Path, Path]


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _transactional_replace(
    replacements: list[Replacement],
    backup_root: Path,
    validate: Callable[[], None],
    failure_injector: FailureInjector | None = None,
) -> None:
    destinations = [destination for _kind, _staged, destination in replacements]
    if len(destinations) != len(set(destinations)):
        raise RuntimeError("transaction repeats a destination")
    if any(not staged.exists() for _kind, staged, _destination in replacements):
        raise RuntimeError("transaction has a missing staged output")

    existed = {
        destination: destination.exists() or destination.is_symlink()
        for destination in destinations
    }
    backups = {
        destination: backup_root / f"{index:02d}-{destination.name}"
        for index, destination in enumerate(destinations)
    }
    backed_up: set[Path] = set()
    installed: set[Path] = set()
    backup_root.mkdir(parents=True)
    try:
        try:
            # Preserve every pre-transaction destination before installing any output.
            # Missing destinations are recorded in ``existed`` and restored as absent.
            for destination in destinations:
                if existed[destination]:
                    os.replace(destination, backups[destination])
                    backed_up.add(destination)
            for kind, staged, destination in replacements:
                os.replace(staged, destination)
                installed.add(destination)
                if failure_injector is not None:
                    failure_injector(kind, destination)
            validate()
            if failure_injector is not None:
                failure_injector("post-swap-validation", FIX)
        except BaseException as error:
            rollback_errors: list[BaseException] = []
            for destination in reversed(destinations):
                try:
                    if destination in installed or not existed[destination]:
                        _remove_path(destination)
                    if destination in backed_up:
                        _remove_path(destination)
                        os.replace(backups[destination], destination)
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                raise RuntimeError(
                    f"registration rollback failed for {len(rollback_errors)} output(s)"
                ) from error
            raise
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)


def _write(
    family_ids: list[str], failure_injector: FailureInjector | None = None
) -> None:
    _validate_scratch(family_ids, SCRATCH)
    with tempfile.TemporaryDirectory(
        prefix="prisoners-evidence-freeze-", dir=FIX
    ) as temporary:
        transaction = Path(temporary)
        generated = transaction / "generated"
        generated.mkdir()
        _build_all(family_ids, SCRATCH, generated)
        large, status = _generated_registries(family_ids, generated)
        normalization = _generated_normalization_manifest()

        staged_registries = transaction / "registries"
        staged_registries.mkdir()
        registry_values = (
            (NORMALIZATION_PATH, normalization),
            (LARGE_BATCH_PATH, large),
            (STATUS_PATH, status),
        )
        for destination, value in registry_values:
            staged = staged_registries / destination.name
            _write_json(staged, value)
            if staged.read_bytes() != canonical_json_bytes(value) + b"\n":
                raise RuntimeError(f"staged registry validation failed: {destination}")

        replacements: list[Replacement] = [
            (
                "evidence-swap",
                generated / f"prisoners-{family_id}-evidence",
                FIX / f"prisoners-{family_id}-evidence",
            )
            for family_id in family_ids
        ]
        replacements.extend(
            ("registry-write", staged_registries / path.name, path)
            for path, _value in registry_values
        )
        _transactional_replace(
            replacements,
            transaction / "backups",
            lambda: _check(family_ids, reproduce=False),
            failure_injector,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--reproduce", action="store_true")
    args = parser.parse_args()
    if args.write == args.check:
        parser.error("choose exactly one of --write or --check")
    if args.reproduce and not args.check:
        parser.error("--reproduce requires --check")
    family_ids = _family_ids()
    if args.write:
        _write(family_ids)
    else:
        _check(family_ids, reproduce=args.reproduce)
    print(
        json.dumps(
            {**EXPECTED, "recordedAt": RECORDED_AT, "verified": True},
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
