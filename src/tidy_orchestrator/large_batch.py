"""Registry and digest-closed evidence verification for prototype batches."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import domain_digest, sha256_digest
from .product_prototype import RUN_SCHEMA

REGISTRY_SCHEMA = "tidy.product-prototype-large-batch-registry/v1"
EVIDENCE_SCHEMA = "tidy.product-prototype-large-batch-evidence/v1"
NORMALIZATION_SCHEMA = "tidy.product-prototype-workbook-normalization/v1"
REGISTRY_PATH = "fixtures/product-prototype/large-batch-assets-v1.json"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DAGSTER_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_CELL_ADDRESS = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
_CELL_RANGE = re.compile(r"^([A-Z]+)([1-9][0-9]*):([A-Z]+)([1-9][0-9]*)$")


def _column_number(label: str) -> int:
    value = 0
    for character in label:
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _cell_in_range(address: str, retained_range: str) -> bool:
    cell = _CELL_ADDRESS.fullmatch(address)
    bounds = _CELL_RANGE.fullmatch(retained_range)
    if cell is None or bounds is None:
        return False
    column = _column_number(cell.group(1))
    row = int(cell.group(2))
    return _column_number(bounds.group(1)) <= column <= _column_number(
        bounds.group(3)
    ) and int(bounds.group(2)) <= row <= int(bounds.group(4))


class LargeBatchError(RuntimeError):
    """The batch registry or checked evidence failed closed."""


@dataclass(frozen=True)
class LargeBatchSpec:
    family_id: str
    label: str
    cohort_path: str
    evidence_manifest_path: str
    dagster_asset: str
    dagster_job: str
    output_directory: str
    expected_years: tuple[int, ...]
    expected_year_counts: tuple[int, ...]
    expected_canonical_count: int
    expected_measure_counts: dict[str, int]
    expected_value_status_counts: dict[str, int]
    expected_manual_replay_years: tuple[int, ...]
    preserves_publication_vintage: bool


@dataclass(frozen=True)
class LargeBatchRegistry:
    batch_id: str
    recorded_at: str
    replay_recorded_at: str
    worksheet_count: int
    provider_calls: int
    normalization_manifest_path: str
    entries: tuple[LargeBatchSpec, ...]


def _safe_path(project: Path, relative: str, label: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or ".." in Path(relative).parts
    ):
        raise LargeBatchError(f"Unsafe {label}: {relative!r}")
    target = (project / relative).resolve()
    try:
        target.relative_to(project)
    except ValueError as error:
        raise LargeBatchError(f"{label} escapes the project") from error
    return target


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise LargeBatchError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise LargeBatchError(f"{label} is not an object")
    return value


def _positive_counts(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict) or not value:
        return None
    if any(
        not isinstance(key, str)
        or not key
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count <= 0
        for key, count in value.items()
    ):
        return None
    return dict(value)


def load_large_batch_registry(project_root: Path) -> LargeBatchRegistry:
    project = project_root.resolve()
    value = _load_object(project / REGISTRY_PATH, "large-batch registry")
    if (
        set(value)
        != {
            "schemaVersion",
            "batchId",
            "recordedAt",
            "replayRecordedAt",
            "worksheetCount",
            "providerCalls",
            "normalizationManifestPath",
            "entries",
        }
        or value.get("schemaVersion") != REGISTRY_SCHEMA
        or not isinstance(value.get("batchId"), str)
        or not value["batchId"]
        or not isinstance(value.get("recordedAt"), str)
        or not isinstance(value.get("replayRecordedAt"), str)
        or not value["replayRecordedAt"]
        or isinstance(value.get("worksheetCount"), bool)
        or not isinstance(value.get("worksheetCount"), int)
        or value["worksheetCount"] <= 0
        or value.get("providerCalls") != 0
        or not isinstance(value.get("normalizationManifestPath"), str)
        or not value["normalizationManifestPath"]
        or not isinstance(value.get("entries"), list)
        or not value["entries"]
    ):
        raise LargeBatchError("Large-batch registry header is invalid")
    _safe_path(
        project, value["normalizationManifestPath"], "normalization manifest path"
    )
    expected_keys = {
        "familyId",
        "label",
        "cohortPath",
        "evidenceManifestPath",
        "dagsterAsset",
        "dagsterJob",
        "outputDirectory",
        "expectedYears",
        "expectedYearCounts",
        "expectedCanonicalCount",
        "expectedMeasureCounts",
        "expectedValueStatusCounts",
        "expectedManualReplayYears",
        "preservesPublicationVintage",
    }
    entries: list[LargeBatchSpec] = []
    for item in value["entries"]:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise LargeBatchError("Large-batch entry shape is invalid")
        years = item.get("expectedYears")
        year_counts = item.get("expectedYearCounts")
        manual_years = item.get("expectedManualReplayYears")
        measure_counts = _positive_counts(item.get("expectedMeasureCounts"))
        status_counts = _positive_counts(item.get("expectedValueStatusCounts"))
        strings = (
            "familyId",
            "label",
            "cohortPath",
            "evidenceManifestPath",
            "dagsterAsset",
            "dagsterJob",
            "outputDirectory",
        )
        if (
            any(not isinstance(item.get(key), str) or not item[key] for key in strings)
            or _SLUG.fullmatch(str(item.get("familyId"))) is None
            or _SLUG.fullmatch(str(item.get("outputDirectory"))) is None
            or _DAGSTER_NAME.fullmatch(str(item.get("dagsterAsset"))) is None
            or _DAGSTER_NAME.fullmatch(str(item.get("dagsterJob"))) is None
            or not isinstance(years, list)
            or not years
            or any(
                isinstance(year, bool) or not isinstance(year, int) for year in years
            )
            or years != sorted(set(years))
            or not isinstance(year_counts, list)
            or len(year_counts) != len(years)
            or any(
                isinstance(count, bool) or not isinstance(count, int) or count <= 0
                for count in year_counts
            )
            or isinstance(item.get("expectedCanonicalCount"), bool)
            or not isinstance(item.get("expectedCanonicalCount"), int)
            or item["expectedCanonicalCount"] != sum(year_counts)
            or measure_counts is None
            or sum(measure_counts.values()) != item["expectedCanonicalCount"]
            or status_counts is None
            or sum(status_counts.values()) != item["expectedCanonicalCount"]
            or not isinstance(manual_years, list)
            or any(year not in years for year in manual_years)
            or len(manual_years) != len(set(manual_years))
            or not isinstance(item.get("preservesPublicationVintage"), bool)
        ):
            raise LargeBatchError(
                f"Large-batch entry is invalid: {item.get('familyId')}"
            )
        _safe_path(project, item["cohortPath"], "cohort path")
        _safe_path(project, item["evidenceManifestPath"], "evidence manifest path")
        entries.append(
            LargeBatchSpec(
                family_id=item["familyId"],
                label=item["label"],
                cohort_path=item["cohortPath"],
                evidence_manifest_path=item["evidenceManifestPath"],
                dagster_asset=item["dagsterAsset"],
                dagster_job=item["dagsterJob"],
                output_directory=item["outputDirectory"],
                expected_years=tuple(years),
                expected_year_counts=tuple(year_counts),
                expected_canonical_count=item["expectedCanonicalCount"],
                expected_measure_counts=measure_counts,
                expected_value_status_counts=status_counts,
                expected_manual_replay_years=tuple(manual_years),
                preserves_publication_vintage=item["preservesPublicationVintage"],
            )
        )
    for attribute in (
        "family_id",
        "cohort_path",
        "evidence_manifest_path",
        "dagster_asset",
        "dagster_job",
        "output_directory",
    ):
        values = [getattr(item, attribute) for item in entries]
        if len(values) != len(set(values)):
            raise LargeBatchError(f"Large-batch registry repeats {attribute}")
    if sum(len(entry.expected_years) for entry in entries) != value["worksheetCount"]:
        raise LargeBatchError("Large-batch worksheet count is inconsistent")
    return LargeBatchRegistry(
        batch_id=value["batchId"],
        recorded_at=value["recordedAt"],
        replay_recorded_at=value["replayRecordedAt"],
        worksheet_count=value["worksheetCount"],
        provider_calls=value["providerCalls"],
        normalization_manifest_path=value["normalizationManifestPath"],
        entries=tuple(entries),
    )


def verify_batch_normalization(
    project_root: Path,
    registry: LargeBatchRegistry,
) -> dict[str, Any]:
    project = project_root.resolve()
    path = _safe_path(
        project, registry.normalization_manifest_path, "normalization manifest"
    )
    manifest = _load_object(path, "normalization manifest")
    expected_keys = {
        "schemaVersion",
        "normalization",
        "recordedAt",
        "scriptPath",
        "scriptDigest",
        "correctionScriptPath",
        "correctionScriptDigest",
        "entries",
        "inRangeValuesChanged",
        "manifestDigest",
    }
    semantic = {
        key: value for key, value in manifest.items() if key != "manifestDigest"
    }
    if (
        set(manifest) != expected_keys
        or manifest.get("schemaVersion") != NORMALIZATION_SCHEMA
        or manifest.get("normalization") != "trim-pathological-styled-blank-cells-v1"
        or not isinstance(manifest.get("recordedAt"), str)
        or not isinstance(manifest.get("inRangeValuesChanged"), bool)
        or manifest.get("manifestDigest")
        != domain_digest(NORMALIZATION_SCHEMA, semantic)
        or not isinstance(manifest.get("scriptPath"), str)
        or _DIGEST.fullmatch(str(manifest.get("scriptDigest"))) is None
        or not isinstance(manifest.get("correctionScriptPath"), str)
        or _DIGEST.fullmatch(str(manifest.get("correctionScriptDigest"))) is None
        or not isinstance(manifest.get("entries"), list)
        or not manifest["entries"]
    ):
        raise LargeBatchError("Normalization manifest header is invalid")
    script = _safe_path(project, manifest["scriptPath"], "normalization script")
    correction_script = _safe_path(
        project, manifest["correctionScriptPath"], "correction script"
    )
    if (
        not script.is_file()
        or sha256_digest(script.read_bytes()) != manifest["scriptDigest"]
        or not correction_script.is_file()
        or sha256_digest(correction_script.read_bytes())
        != manifest["correctionScriptDigest"]
    ):
        raise LargeBatchError("Normalization script digest mismatch")

    outputs: dict[str, tuple[int, str, int]] = {}
    in_range_values_changed = False
    entry_keys = {
        "year",
        "sourcePath",
        "sourceDigest",
        "sourceByteLength",
        "outputPath",
        "outputDigest",
        "outputByteLength",
        "trimmedSheets",
        "correction",
    }
    for entry in manifest["entries"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != entry_keys
            or isinstance(entry.get("year"), bool)
            or not isinstance(entry.get("year"), int)
            or not isinstance(entry.get("sourcePath"), str)
            or not isinstance(entry.get("outputPath"), str)
            or entry.get("sourcePath") == entry.get("outputPath")
            or _DIGEST.fullmatch(str(entry.get("sourceDigest"))) is None
            or _DIGEST.fullmatch(str(entry.get("outputDigest"))) is None
            or isinstance(entry.get("sourceByteLength"), bool)
            or not isinstance(entry.get("sourceByteLength"), int)
            or entry["sourceByteLength"] <= 0
            or isinstance(entry.get("outputByteLength"), bool)
            or not isinstance(entry.get("outputByteLength"), int)
            or entry["outputByteLength"] <= 0
            or not isinstance(entry.get("trimmedSheets"), list)
            or not entry["trimmedSheets"]
            or (
                entry.get("correction") is not None
                and (
                    not isinstance(entry["correction"], dict)
                    or set(entry["correction"]) != {"id", "removedCells", "reason"}
                    or not isinstance(entry["correction"].get("id"), str)
                    or not entry["correction"]["id"]
                    or not isinstance(entry["correction"].get("reason"), str)
                    or not entry["correction"]["reason"]
                    or not isinstance(entry["correction"].get("removedCells"), list)
                    or not entry["correction"]["removedCells"]
                    or any(
                        not isinstance(cell, dict)
                        or set(cell)
                        != {
                            "sheet",
                            "cell",
                            "expectedStyle",
                            "expectedValue",
                            "insideRetainedRange",
                        }
                        or not all(
                            isinstance(cell.get(key), str) and cell[key]
                            for key in (
                                "sheet",
                                "cell",
                                "expectedStyle",
                                "expectedValue",
                            )
                        )
                        or not isinstance(cell.get("insideRetainedRange"), bool)
                        for cell in entry["correction"]["removedCells"]
                    )
                )
            )
        ):
            raise LargeBatchError("Normalization manifest entry is invalid")
        trimmed = entry["trimmedSheets"]
        if any(
            not isinstance(item, dict)
            or set(item) != {"sheet", "retainedRange"}
            or not isinstance(item.get("sheet"), str)
            or not item["sheet"]
            or not isinstance(item.get("retainedRange"), str)
            or re.fullmatch(
                r"[A-Z]+[1-9][0-9]*:[A-Z]+[1-9][0-9]*", item["retainedRange"]
            )
            is None
            for item in trimmed
        ) or len({item["sheet"] for item in trimmed}) != len(trimmed):
            raise LargeBatchError("Normalization trimmed-sheet declaration is invalid")
        retained_by_sheet = {item["sheet"]: item["retainedRange"] for item in trimmed}
        if entry["correction"] is not None:
            for cell in entry["correction"]["removedCells"]:
                inside = cell["sheet"] in retained_by_sheet and _cell_in_range(
                    cell["cell"], retained_by_sheet[cell["sheet"]]
                )
                if cell["insideRetainedRange"] is not inside:
                    raise LargeBatchError(
                        "Correction retained-range declaration is invalid"
                    )
                in_range_values_changed = in_range_values_changed or inside
        for prefix in ("source", "output"):
            file_path = _safe_path(
                project, entry[f"{prefix}Path"], f"normalization {prefix}"
            )
            if not file_path.is_file():
                raise LargeBatchError(f"Normalization {prefix} file is missing")
            data = file_path.read_bytes()
            if (
                len(data) != entry[f"{prefix}ByteLength"]
                or sha256_digest(data) != entry[f"{prefix}Digest"]
            ):
                raise LargeBatchError(f"Normalization {prefix} digest mismatch")
        with tempfile.TemporaryDirectory(prefix="tidy-normalization-verify-") as temp:
            reproduced = Path(temp) / "reproduced.xlsx"
            source = _safe_path(project, entry["sourcePath"], "normalization source")
            normalization_input = source
            if entry["correction"] is not None:
                normalization_input = Path(temp) / "corrected.xlsx"
                receipt_path = Path(temp) / "correction-receipt.json"
                correction = subprocess.run(
                    [
                        sys.executable,
                        str(correction_script),
                        str(source),
                        str(normalization_input),
                        "--receipt",
                        str(receipt_path),
                    ],
                    cwd=project,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if (
                    correction.returncode != 0
                    or not normalization_input.is_file()
                    or not receipt_path.is_file()
                ):
                    raise LargeBatchError(
                        "Workbook correction reproduction failed: "
                        f"{correction.stderr.strip() or correction.stdout.strip()}"
                    )
                try:
                    receipt = json.loads(receipt_path.read_text())
                except (OSError, json.JSONDecodeError) as error:
                    raise LargeBatchError(
                        "Workbook correction receipt is unreadable"
                    ) from error
                if receipt != entry["correction"]:
                    raise LargeBatchError(
                        "Workbook correction receipt does not match the manifest"
                    )
            command = [
                sys.executable,
                str(script),
                str(normalization_input),
                str(reproduced),
            ]
            for declaration in trimmed:
                command.extend(
                    [
                        "--sheet",
                        f"{declaration['sheet']}={declaration['retainedRange']}",
                    ]
                )
            completed = subprocess.run(
                command,
                cwd=project,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if completed.returncode != 0 or not reproduced.is_file():
                raise LargeBatchError(
                    "Normalization reproduction failed: "
                    f"{completed.stderr.strip() or completed.stdout.strip()}"
                )
            if (
                reproduced.read_bytes()
                != _safe_path(
                    project, entry["outputPath"], "normalization output"
                ).read_bytes()
            ):
                raise LargeBatchError("Normalized workbook is not reproducible")
        if entry["outputPath"] in outputs:
            raise LargeBatchError("Normalization manifest repeats an output path")
        outputs[entry["outputPath"]] = (
            entry["year"],
            entry["outputDigest"],
            entry["outputByteLength"],
        )

    if manifest["inRangeValuesChanged"] is not in_range_values_changed:
        raise LargeBatchError("Normalization in-range value-change claim is invalid")

    used_outputs: set[str] = set()
    for spec in registry.entries:
        cohort_path = _safe_path(project, spec.cohort_path, "cohort")
        cohort = _load_object(cohort_path, "large-batch cohort")
        workbooks = cohort.get("workbooks")
        if not isinstance(workbooks, list):
            raise LargeBatchError("Large-batch cohort workbook list is invalid")
        for workbook in workbooks:
            if not isinstance(workbook, dict) or not isinstance(
                workbook.get("path"), str
            ):
                raise LargeBatchError("Large-batch workbook normalization is invalid")
            output = _safe_path(
                cohort_path.parent, workbook["path"], "normalized workbook"
            )
            relative_output = output.relative_to(project).as_posix()
            if workbook.get("normalization") is None:
                if relative_output in outputs:
                    raise LargeBatchError(
                        "Normalized workbook is missing its normalization declaration"
                    )
                continue
            if (
                workbook.get("normalization")
                != "trim-pathological-styled-blank-cells-v1"
            ):
                raise LargeBatchError("Large-batch workbook normalization is invalid")
            expected = outputs.get(relative_output)
            if expected != (
                workbook.get("year"),
                workbook.get("contentDigest"),
                workbook.get("byteLength"),
            ):
                raise LargeBatchError(
                    "Large-batch workbook does not match normalization manifest"
                )
            used_outputs.add(relative_output)
    if used_outputs != set(outputs):
        raise LargeBatchError("Normalization manifest contains unused outputs")
    return manifest


def _verify_declared_file(root: Path, entry: Any) -> str:
    if (
        not isinstance(entry, dict)
        or set(entry) != {"path", "contentDigest", "byteLength"}
        or not isinstance(entry.get("path"), str)
        or not entry["path"]
        or _DIGEST.fullmatch(str(entry.get("contentDigest"))) is None
        or isinstance(entry.get("byteLength"), bool)
        or not isinstance(entry.get("byteLength"), int)
        or entry["byteLength"] < 0
    ):
        raise LargeBatchError("Evidence file declaration is invalid")
    target = _safe_path(root, entry["path"], "evidence file")
    if target.is_symlink() or not target.is_file():
        raise LargeBatchError(f"Evidence file is missing: {entry['path']}")
    data = target.read_bytes()
    if (
        len(data) != entry["byteLength"]
        or sha256_digest(data) != entry["contentDigest"]
    ):
        raise LargeBatchError(f"Evidence file digest mismatch: {entry['path']}")
    return entry["path"]


def verify_large_batch_evidence(
    project_root: Path,
    spec: LargeBatchSpec,
) -> dict[str, Any]:
    project = project_root.resolve()
    manifest_path = _safe_path(project, spec.evidence_manifest_path, "manifest")
    manifest = _load_object(manifest_path, "large-batch evidence manifest")
    root = manifest_path.parent.resolve()
    required_header = {
        "schemaVersion",
        "familyId",
        "cohortPath",
        "cohortDigest",
        "acceptanceContractPath",
        "acceptanceContractDigest",
        "recordedAt",
        "mode",
        "providerCalls",
        "acceptedWorkbookCount",
        "exceptionWorkbookCount",
        "rawObservationCount",
        "excludedObservationCount",
        "canonicalObservationCount",
        "measureCounts",
        "valueStatusCounts",
        "manualReplayYears",
        "publicationVintagePreserved",
        "runDigest",
        "files",
    }
    if (
        set(manifest) != required_header
        or manifest.get("schemaVersion") != EVIDENCE_SCHEMA
        or manifest.get("familyId") != spec.family_id
        or manifest.get("cohortPath") != spec.cohort_path
        or manifest.get("mode") != "replay"
        or manifest.get("providerCalls") != 0
        or manifest.get("acceptedWorkbookCount") != len(spec.expected_years)
        or manifest.get("exceptionWorkbookCount") != 0
        or manifest.get("excludedObservationCount") != 0
        or manifest.get("canonicalObservationCount") != spec.expected_canonical_count
        or manifest.get("rawObservationCount") != spec.expected_canonical_count
        or manifest.get("measureCounts") != spec.expected_measure_counts
        or manifest.get("valueStatusCounts") != spec.expected_value_status_counts
        or manifest.get("manualReplayYears") != list(spec.expected_manual_replay_years)
        or manifest.get("publicationVintagePreserved")
        != spec.preserves_publication_vintage
        or _DIGEST.fullmatch(str(manifest.get("runDigest"))) is None
        or not isinstance(manifest.get("files"), list)
    ):
        raise LargeBatchError(f"Evidence manifest claims are invalid: {spec.family_id}")
    declared = [_verify_declared_file(root, entry) for entry in manifest["files"]]
    if len(declared) != len(set(declared)):
        raise LargeBatchError("Evidence manifest repeats a file")
    required_files = {
        "README.md",
        "canonical-observations.csv",
        "canonical-observations.json",
        "collation-report.json",
        "exceptions.json",
        "run.json",
    }
    actual = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    }
    if set(declared) != required_files or actual != required_files:
        raise LargeBatchError("Evidence file closure is incomplete or contains extras")

    cohort_path = _safe_path(project, spec.cohort_path, "cohort")
    cohort_bytes = cohort_path.read_bytes()
    cohort = _load_object(cohort_path, "large-batch cohort")
    if sha256_digest(cohort_bytes) != manifest.get("cohortDigest"):
        raise LargeBatchError("Evidence cohort digest does not match")
    contract_relative = str(
        Path(spec.cohort_path).parent / cohort["acceptanceContract"]
    )
    if manifest.get("acceptanceContractPath") != contract_relative:
        raise LargeBatchError("Evidence acceptance contract path does not match cohort")
    contract_path = _safe_path(project, contract_relative, "acceptance contract")
    if sha256_digest(contract_path.read_bytes()) != manifest.get(
        "acceptanceContractDigest"
    ):
        raise LargeBatchError("Evidence acceptance contract digest does not match")
    if len(cohort.get("workbooks", [])) != len(spec.expected_years):
        raise LargeBatchError("Cohort workbook count does not match")
    manual_years = []
    for workbook in cohort["workbooks"]:
        workbook_path = _safe_path(
            cohort_path.parent, workbook["path"], "workbook source"
        )
        response_path = _safe_path(
            cohort_path.parent,
            workbook["replayResponse"]["path"],
            "replay response",
        )
        for path, declaration in (
            (workbook_path, workbook),
            (response_path, workbook["replayResponse"]),
        ):
            data = path.read_bytes()
            if (
                len(data) != declaration["byteLength"]
                or sha256_digest(data) != declaration["contentDigest"]
            ):
                raise LargeBatchError(f"Cohort input digest mismatch: {path}")
        if workbook["replayResponse"]["historicalModel"].startswith("human-authored"):
            manual_years.append(workbook["year"])
    if manual_years != list(spec.expected_manual_replay_years):
        raise LargeBatchError("Manual replay provenance does not match registry")

    run = _load_object(root / "run.json", "large-batch run")
    semantic = dict(run)
    run_digest = semantic.pop("runDigest", None)
    if (
        run_digest != domain_digest(RUN_SCHEMA, semantic)
        or run_digest != manifest["runDigest"]
        or run.get("cohortDigest") != manifest["cohortDigest"]
        or run.get("acceptanceContractDigest") != manifest["acceptanceContractDigest"]
        or run.get("providerCalls") != 0
        or run.get("acceptedWorkbookCount") != len(spec.expected_years)
        or run.get("exceptionWorkbookCount") != 0
        or run.get("canonicalObservationCount") != spec.expected_canonical_count
        or run.get("crossYearIssues") != []
        or [item.get("year") for item in run.get("workbooks", [])]
        != list(spec.expected_years)
        or [item.get("observationCount") for item in run.get("workbooks", [])]
        != list(spec.expected_year_counts)
        or any(
            item.get("decision") != "prototype_auto_accepted"
            or item.get("excludedObservationCount") != 0
            or not all(item.get("checks", {}).values())
            or item.get("issues") != []
            for item in run.get("workbooks", [])
        )
    ):
        raise LargeBatchError(f"Run evidence is invalid: {spec.family_id}")
    digest_bindings = {
        "canonical-observations.csv": "canonicalCsvDigest",
        "canonical-observations.json": "canonicalJsonDigest",
        "collation-report.json": "collationReportDigest",
    }
    for filename, run_field in digest_bindings.items():
        if sha256_digest((root / filename).read_bytes()) != run.get(run_field):
            raise LargeBatchError(f"Run does not bind {filename}")

    rows = json.loads((root / "canonical-observations.json").read_text())
    exceptions = json.loads((root / "exceptions.json").read_text())
    collation = _load_object(root / "collation-report.json", "collation report")
    clean_fields = (
        "excludedExceptions",
        "duplicateCanonicalKeys",
        "conflictingValues",
        "unmappedLabels",
        "missingExpectedCategories",
        "schemaFailures",
        "codeListFailures",
    )
    if (
        not isinstance(rows, list)
        or len(rows) != spec.expected_canonical_count
        or dict(sorted(Counter(row["measure_id"] for row in rows).items()))
        != spec.expected_measure_counts
        or dict(sorted(Counter(row["value_status"] for row in rows).items()))
        != spec.expected_value_status_counts
        or exceptions != []
        or collation.get("rowCount") != spec.expected_canonical_count
        or any(collation.get(field) != [] for field in clean_fields)
    ):
        raise LargeBatchError(
            f"Canonical or collation evidence is invalid: {spec.family_id}"
        )
    vintage_present = all("publication_vintage_date" in row for row in rows)
    if vintage_present != spec.preserves_publication_vintage:
        raise LargeBatchError("Publication-vintage fields do not match policy")
    return manifest


def verify_large_batch_reproduction(
    project_root: Path,
    spec: LargeBatchSpec,
    output_root: Path,
) -> dict[str, Any]:
    manifest = verify_large_batch_evidence(project_root, spec)
    evidence_root = _safe_path(
        project_root.resolve(), spec.evidence_manifest_path, "evidence manifest"
    ).parent
    declarations = {
        item["path"]: item
        for item in manifest["files"]
        if item["path"]
        in {
            "canonical-observations.csv",
            "canonical-observations.json",
            "collation-report.json",
            "exceptions.json",
        }
    }
    if len(declarations) != 4:
        raise LargeBatchError("Reproducible evidence declarations are incomplete")
    root = output_root.resolve()
    for filename, declaration in declarations.items():
        generated = root / filename
        if generated.is_symlink() or not generated.is_file():
            raise LargeBatchError(f"Generated reproduction is missing: {filename}")
        data = generated.read_bytes()
        if (
            len(data) != declaration["byteLength"]
            or sha256_digest(data) != declaration["contentDigest"]
            or data != (evidence_root / filename).read_bytes()
        ):
            raise LargeBatchError(
                f"Generated reproduction differs from checked evidence: {filename}"
            )
    return manifest
