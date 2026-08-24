from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .data_asset_status import (
    DEFAULT_REGISTRY,
    DIGEST_PATTERN,
    AssetStatus,
    DashboardStatus,
    DataAssetStatusError,
    build_dashboard,
    default_project_root,
    sha256_digest,
)

SCHEMA_VERSION = "tidy.sqlite-data-asset-export/v1"
DEFAULT_OUTPUT = Path(".product-prototype/sqlite-export/tidy-data-asset-status.sqlite3")
MAX_RELEASE_BYTES = 2 * 1024**3
ACCEPTED_DECISION = "prototype_auto_accepted"
PROVENANCE_ROLES = (
    "cohort_manifest",
    "acceptance_contract",
    "evidence_manifest",
    "canonical_json",
    "canonical_csv",
    "run",
    "collation",
)

SCHEMA_SQL = """
BEGIN IMMEDIATE;

CREATE TABLE export_metadata (
    export_id INTEGER PRIMARY KEY CHECK (export_id = 1),
    schema_version TEXT NOT NULL,
    registry_recorded_at TEXT NOT NULL,
    registry_path TEXT NOT NULL,
    registry_sha256 TEXT NOT NULL,
    registry_byte_length INTEGER NOT NULL CHECK (registry_byte_length >= 0),
    publication_count INTEGER NOT NULL CHECK (publication_count >= 0),
    cohort_count INTEGER NOT NULL CHECK (cohort_count >= 0),
    asset_count INTEGER NOT NULL CHECK (asset_count >= 0),
    observation_count INTEGER NOT NULL CHECK (observation_count >= 0),
    physical_workbook_count INTEGER NOT NULL CHECK (physical_workbook_count >= 0),
    logical_content_sha256 TEXT NOT NULL,
    acceptance_authority INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(acceptance_authority) = 'integer' AND acceptance_authority = 0),
    training_eligibility INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(training_eligibility) = 'integer' AND training_eligibility = 0),
    provider_calls INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(provider_calls) = 'integer' AND provider_calls = 0)
) STRICT;

CREATE TABLE publication (
    publication_id TEXT PRIMARY KEY,
    publication_ordinal INTEGER NOT NULL UNIQUE CHECK (publication_ordinal >= 0),
    label TEXT NOT NULL,
    period_format TEXT NOT NULL
        CHECK (period_format IN ('calendar-year', 'fiscal-year'))
) STRICT;

CREATE TABLE cohort (
    cohort_id TEXT PRIMARY KEY,
    cohort_ordinal INTEGER NOT NULL UNIQUE CHECK (cohort_ordinal >= 0),
    publication_id TEXT NOT NULL REFERENCES publication(publication_id),
    label TEXT NOT NULL,
    dagster_asset TEXT NOT NULL,
    checks_state TEXT NOT NULL CHECK (checks_state = 'pass'),
    evidence_recorded_at TEXT NOT NULL,
    asset_count INTEGER NOT NULL CHECK (asset_count > 0),
    observation_count INTEGER NOT NULL CHECK (observation_count > 0),
    UNIQUE (cohort_id, publication_id)
) STRICT;

CREATE TABLE asset (
    asset_id TEXT PRIMARY KEY,
    asset_ordinal INTEGER NOT NULL UNIQUE CHECK (asset_ordinal >= 0),
    cohort_id TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    reference_date TEXT NOT NULL,
    sheet TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    source_byte_length INTEGER NOT NULL CHECK (source_byte_length >= 0),
    identified_status TEXT NOT NULL CHECK (identified_status = 'yes'),
    on_disk_status TEXT NOT NULL CHECK (on_disk_status = 'yes'),
    tidied_status TEXT NOT NULL CHECK (tidied_status = 'yes'),
    canonicalised_status TEXT NOT NULL CHECK (canonicalised_status = 'yes'),
    integrated_status TEXT NOT NULL CHECK (integrated_status = 'yes'),
    checks_state TEXT NOT NULL CHECK (checks_state = 'pass'),
    canonical_count INTEGER NOT NULL CHECK (canonical_count > 0),
    raw_count INTEGER,
    excluded_count INTEGER,
    decision TEXT NOT NULL CHECK (decision = 'prototype_auto_accepted'),
    decision_id TEXT NOT NULL,
    prepare_derivation_id TEXT NOT NULL,
    interpret_derivation_id TEXT NOT NULL,
    replay_model TEXT NOT NULL,
    evidence_recorded_at TEXT NOT NULL,
    normalization TEXT,
    live_evidence_path TEXT,
    UNIQUE (asset_id, cohort_id, publication_id),
    FOREIGN KEY (cohort_id, publication_id)
        REFERENCES cohort(cohort_id, publication_id)
) STRICT;

CREATE TABLE asset_check (
    asset_id TEXT NOT NULL REFERENCES asset(asset_id),
    check_name TEXT NOT NULL,
    passed INTEGER NOT NULL CHECK (passed = 1),
    PRIMARY KEY (asset_id, check_name)
) STRICT, WITHOUT ROWID;

CREATE TABLE provenance_file (
    provenance_ordinal INTEGER PRIMARY KEY CHECK (provenance_ordinal >= 0),
    cohort_id TEXT NOT NULL REFERENCES cohort(cohort_id),
    role TEXT NOT NULL CHECK (role IN (
        'cohort_manifest', 'acceptance_contract', 'evidence_manifest', 'canonical_json',
        'canonical_csv', 'run', 'collation'
    )),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    UNIQUE (cohort_id, role)
) STRICT;

CREATE TABLE observation (
    observation_id INTEGER PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES asset(asset_id),
    asset_row_ordinal INTEGER NOT NULL CHECK (asset_row_ordinal >= 0),
    cohort_id TEXT NOT NULL REFERENCES cohort(cohort_id),
    publication_id TEXT NOT NULL REFERENCES publication(publication_id),
    canonical_publication_id TEXT NOT NULL,
    publication_vintage_date TEXT,
    reference_date TEXT NOT NULL,
    observation_period_id TEXT,
    measure_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    value_status TEXT NOT NULL,
    value_type TEXT NOT NULL CHECK (value_type IN ('null', 'integer', 'real')),
    value_integer INTEGER,
    value_real REAL,
    raw_value_type TEXT NOT NULL CHECK (raw_value_type IN (
        'missing', 'null', 'boolean', 'integer', 'real', 'string'
    )),
    raw_value_text TEXT,
    raw_value_integer INTEGER,
    raw_value_real REAL,
    source_workbook_digest TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_cell TEXT NOT NULL,
    acceptance_decision_digest TEXT NOT NULL,
    acceptance_policy_digest TEXT NOT NULL,
    acceptance_policy_version TEXT NOT NULL,
    recipe_digest TEXT NOT NULL,
    execution_digest TEXT NOT NULL,
    prompt_package_digest TEXT NOT NULL,
    generation_attempt_id TEXT NOT NULL,
    generation_model TEXT NOT NULL,
    canonical_json TEXT NOT NULL CHECK (json_valid(canonical_json)),
    UNIQUE (asset_id, asset_row_ordinal),
    CHECK (
        (value_type = 'null' AND value_integer IS NULL AND value_real IS NULL) OR
        (value_type = 'integer' AND value_integer IS NOT NULL AND value_real IS NULL) OR
        (value_type = 'real' AND value_integer IS NULL AND value_real IS NOT NULL)
    ),
    CHECK (
        (raw_value_type IN ('missing', 'null') AND raw_value_text IS NULL
            AND raw_value_integer IS NULL AND raw_value_real IS NULL) OR
        (raw_value_type = 'boolean' AND raw_value_text IS NULL
            AND raw_value_integer IS NOT NULL
            AND raw_value_integer IN (0, 1) AND raw_value_real IS NULL) OR
        (raw_value_type = 'integer' AND raw_value_text IS NULL
            AND raw_value_integer IS NOT NULL AND raw_value_real IS NULL) OR
        (raw_value_type = 'real' AND raw_value_text IS NULL
            AND raw_value_integer IS NULL AND raw_value_real IS NOT NULL) OR
        (raw_value_type = 'string' AND raw_value_text IS NOT NULL
            AND raw_value_integer IS NULL AND raw_value_real IS NULL)
    ),
    FOREIGN KEY (asset_id, cohort_id, publication_id)
        REFERENCES asset(asset_id, cohort_id, publication_id)
) STRICT;

CREATE INDEX asset_cohort_idx ON asset(cohort_id, year, sheet);
CREATE INDEX observation_publication_date_idx
    ON observation(publication_id, publication_vintage_date, reference_date);
CREATE INDEX observation_measure_idx ON observation(measure_id, unit_id, value_status);
"""

TABLE_COLUMNS = {
    "export_metadata": (
        "export_id",
        "schema_version",
        "registry_recorded_at",
        "registry_path",
        "registry_sha256",
        "registry_byte_length",
        "publication_count",
        "cohort_count",
        "asset_count",
        "observation_count",
        "physical_workbook_count",
        "logical_content_sha256",
        "acceptance_authority",
        "training_eligibility",
        "provider_calls",
    ),
    "publication": ("publication_id", "publication_ordinal", "label", "period_format"),
    "cohort": (
        "cohort_id",
        "cohort_ordinal",
        "publication_id",
        "label",
        "dagster_asset",
        "checks_state",
        "evidence_recorded_at",
        "asset_count",
        "observation_count",
    ),
    "asset": (
        "asset_id",
        "asset_ordinal",
        "cohort_id",
        "publication_id",
        "year",
        "reference_date",
        "sheet",
        "source_path",
        "source_digest",
        "source_byte_length",
        "identified_status",
        "on_disk_status",
        "tidied_status",
        "canonicalised_status",
        "integrated_status",
        "checks_state",
        "canonical_count",
        "raw_count",
        "excluded_count",
        "decision",
        "decision_id",
        "prepare_derivation_id",
        "interpret_derivation_id",
        "replay_model",
        "evidence_recorded_at",
        "normalization",
        "live_evidence_path",
    ),
    "asset_check": ("asset_id", "check_name", "passed"),
    "provenance_file": (
        "provenance_ordinal",
        "cohort_id",
        "role",
        "path",
        "sha256",
        "byte_length",
    ),
    "observation": (
        "observation_id",
        "asset_id",
        "asset_row_ordinal",
        "cohort_id",
        "publication_id",
        "canonical_publication_id",
        "publication_vintage_date",
        "reference_date",
        "observation_period_id",
        "measure_id",
        "unit_id",
        "value_status",
        "value_type",
        "value_integer",
        "value_real",
        "raw_value_type",
        "raw_value_text",
        "raw_value_integer",
        "raw_value_real",
        "source_workbook_digest",
        "source_sheet",
        "source_cell",
        "acceptance_decision_digest",
        "acceptance_policy_digest",
        "acceptance_policy_version",
        "recipe_digest",
        "execution_digest",
        "prompt_package_digest",
        "generation_attempt_id",
        "generation_model",
        "canonical_json",
    ),
}


class SQLiteExportError(ValueError):
    """The consolidated export cannot be built or verified safely."""


@dataclass(frozen=True)
class CohortInput:
    cohort_id: str
    cohort_path: str
    evidence_manifest_path: str
    acceptance_contract_path: str
    acceptance_contract_digest: str
    acceptance_contract_length: int
    acceptance_policy_version: str
    acceptance_policy_digest: str
    canonical_path: str
    declarations: dict[str, tuple[str, int]]


@dataclass(frozen=True)
class ExportContext:
    root: Path
    registry_relative: Path
    registry_digest: str
    registry_length: int
    status: DashboardStatus
    cohorts: tuple[CohortInput, ...]


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST_PATTERN.fullmatch(value) is not None


def _require_digest(value: Any, label: str) -> str:
    if not _is_digest(value):
        raise SQLiteExportError(f"{label} must be a literal sha256 digest")
    return value


def _require_length(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SQLiteExportError(f"{label} must be a non-negative integer length")
    return value


def _require_count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SQLiteExportError(f"{label} must be a non-negative integer")
    return value


def _strict_zero(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise SQLiteExportError(f"{label} must be the integer 0")
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise SQLiteExportError(
            "Canonical evidence contains unsupported JSON"
        ) from error


def _path(root: Path, relative: str, label: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SQLiteExportError(f"{label} is not a safe relative path: {relative}")
    target = root.joinpath(*pure.parts).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise SQLiteExportError(f"{label} escapes the project: {relative}") from error
    return target


def _validate_aggregate_counts(
    cohort_id: str,
    manifest: dict[str, Any],
    run: dict[str, Any],
    assets: Sequence[AssetStatus],
) -> None:
    reports = run.get("workbooks")
    if not isinstance(reports, list) or len(reports) != len(assets):
        raise SQLiteExportError(
            f"Run workbook cardinality does not match registered assets: {cohort_id}"
        )
    asset_by_key = {
        (asset.year, asset.sheet, asset.source_digest): asset for asset in assets
    }
    if len(asset_by_key) != len(assets):
        raise SQLiteExportError(f"Registered asset identity is ambiguous: {cohort_id}")
    seen: set[tuple[int, str, str]] = set()
    accepted_total = 0
    exception_total = 0
    canonical_total = 0
    raw_total = 0
    excluded_total = 0
    for report in reports:
        if not isinstance(report, dict):
            raise SQLiteExportError(f"Run workbook report is invalid: {cohort_id}")
        year = report.get("year")
        sheet = report.get("sheet")
        workbook_digest = report.get("workbookDigest")
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not isinstance(sheet, str)
            or not _is_digest(workbook_digest)
        ):
            raise SQLiteExportError(f"Run workbook identity is invalid: {cohort_id}")
        key = (year, sheet, workbook_digest)
        asset = asset_by_key.get(key)
        if asset is None or key in seen:
            raise SQLiteExportError(
                f"Run workbook association does not match registry: {cohort_id}"
            )
        seen.add(key)
        canonical_count = _require_count(
            report.get("observationCount"),
            f"Run workbook observationCount for {asset.asset_id}",
        )
        raw_count = (
            _require_count(
                report.get("rawObservationCount"),
                f"Run workbook rawObservationCount for {asset.asset_id}",
            )
            if "rawObservationCount" in report
            else canonical_count
        )
        excluded_count = (
            _require_count(
                report.get("excludedObservationCount"),
                f"Run workbook excludedObservationCount for {asset.asset_id}",
            )
            if "excludedObservationCount" in report
            else 0
        )
        if canonical_count != asset.canonical_count:
            raise SQLiteExportError(
                f"Run workbook canonical count does not match asset: {asset.asset_id}"
            )
        if asset.raw_count is not None and raw_count != asset.raw_count:
            raise SQLiteExportError(
                f"Run workbook raw count does not match asset: {asset.asset_id}"
            )
        if asset.excluded_count is not None and excluded_count != asset.excluded_count:
            raise SQLiteExportError(
                f"Run workbook excluded count does not match asset: {asset.asset_id}"
            )
        decision = report.get("decision")
        if decision == ACCEPTED_DECISION:
            accepted_total += 1
            if report.get("decisionId") != asset.decision_id:
                raise SQLiteExportError(
                    f"Run workbook decision does not match asset: {asset.asset_id}"
                )
        else:
            exception_total += 1
        canonical_total += canonical_count
        raw_total += raw_count
        excluded_total += excluded_count
    if seen != set(asset_by_key):
        raise SQLiteExportError(f"Run workbook coverage is incomplete: {cohort_id}")

    expected_required = {
        "acceptedWorkbookCount": accepted_total,
        "exceptionWorkbookCount": exception_total,
        "canonicalObservationCount": canonical_total,
    }
    for field, expected in expected_required.items():
        manifest_count = _require_count(
            manifest.get(field), f"Manifest {field} for {cohort_id}"
        )
        run_count = _require_count(run.get(field), f"Run {field} for {cohort_id}")
        if manifest_count != run_count:
            raise SQLiteExportError(f"Manifest/run {field} mismatch: {cohort_id}")
        if manifest_count != expected:
            raise SQLiteExportError(
                f"Declared {field} does not match derived total: {cohort_id}"
            )
    if accepted_total != len(assets) or exception_total != 0:
        raise SQLiteExportError(
            f"Run workbook acceptance totals are not all-pass: {cohort_id}"
        )

    for field, expected in {
        "rawObservationCount": raw_total,
        "excludedObservationCount": excluded_total,
    }.items():
        declared: list[tuple[str, int]] = []
        for label, document in (("Manifest", manifest), ("Run", run)):
            if field in document:
                declared.append(
                    (
                        label,
                        _require_count(
                            document[field], f"{label} {field} for {cohort_id}"
                        ),
                    )
                )
        if len(declared) == 2 and declared[0][1] != declared[1][1]:
            raise SQLiteExportError(f"Manifest/run {field} mismatch: {cohort_id}")
        for _label, count in declared:
            if count != expected:
                raise SQLiteExportError(
                    f"Declared {field} does not match derived total: {cohort_id}"
                )


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise SQLiteExportError(f"{label} is unreadable: {path}") from error


def _json_bytes_object(data: bytes, path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SQLiteExportError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise SQLiteExportError(f"{label} must be a JSON object: {path}")
    return value


def _json_object(path: Path, label: str) -> dict[str, Any]:
    return _json_bytes_object(_read_bytes(path, label), path, label)


def _prepare_context(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> ExportContext:
    root = (project_root or default_project_root()).resolve()
    try:
        status = build_dashboard(root, registry_relative)
    except DataAssetStatusError as error:
        raise SQLiteExportError(str(error)) from error
    if any(cohort.checks_state != "pass" or cohort.issues for cohort in status.cohorts):
        raise SQLiteExportError("Every registered cohort must have passing evidence")
    if not status.assets:
        raise SQLiteExportError("The explicit status registry contains no assets")
    for asset in status.assets:
        if (
            asset.checks_state != "pass"
            or asset.issues
            or any(state != "yes" for state in asset.stages.values())
            or not asset.checks
            or any(not passed for _name, passed in asset.checks)
            or asset.canonical_count is None
            or asset.canonical_count <= 0
            or asset.decision != ACCEPTED_DECISION
            or not _is_digest(asset.decision_id)
            or not _is_digest(asset.source_digest)
            or not _is_digest(asset.prepare_derivation_id)
            or not _is_digest(asset.interpret_derivation_id)
            or not asset.replay_model
            or not asset.evidence_recorded_at
        ):
            raise SQLiteExportError(
                f"Registered asset is not exportable: {asset.asset_id}"
            )

    registry_path = _path(root, registry_relative.as_posix(), "registry")
    registry_bytes = _read_bytes(registry_path, "status registry")
    registry = _json_bytes_object(registry_bytes, registry_path, "status registry")
    configs = {item["cohortId"]: item for item in registry["cohorts"]}
    cohort_inputs: list[CohortInput] = []
    for cohort in status.cohorts:
        config = configs.get(cohort.cohort_id)
        if not isinstance(config, dict):
            raise SQLiteExportError(
                f"Cohort is absent from registry: {cohort.cohort_id}"
            )
        cohort_relative = config["cohortPath"]
        cohort_manifest = _json_object(
            _path(root, cohort_relative, "cohort manifest"), "cohort manifest"
        )
        contract_relative_value = cohort_manifest.get("acceptanceContract")
        if not isinstance(contract_relative_value, str):
            raise SQLiteExportError(
                f"Cohort acceptance contract is invalid: {cohort.cohort_id}"
            )
        contract_relative = (
            PurePosixPath(cohort_relative).parent / contract_relative_value
        ).as_posix()
        contract_path = _path(root, contract_relative, "acceptance contract")
        contract_bytes = _read_bytes(contract_path, "acceptance contract")
        contract = _json_bytes_object(
            contract_bytes, contract_path, "acceptance contract"
        )
        contract_digest = sha256_digest(contract_bytes)
        policy_version = contract.get("schemaVersion")
        if not isinstance(policy_version, str) or not policy_version:
            raise SQLiteExportError(
                f"Acceptance contract version is invalid: {cohort.cohort_id}"
            )
        policy_digest = (
            contract_digest
            if policy_version == "tidy.table-family-acceptance/v2"
            else sha256_digest(_canonical_json(contract).encode("utf-8"))
        )

        manifest_relative = config["evidenceManifestPath"]
        manifest_path = _path(root, manifest_relative, "evidence manifest")
        manifest = _json_object(manifest_path, "evidence manifest")
        manifest_provider_calls = _strict_zero(
            manifest.get("providerCalls"),
            f"Manifest providerCalls for {cohort.cohort_id}",
        )
        declarations: dict[str, tuple[str, int]] = {}
        for declaration in manifest.get("files", []):
            if isinstance(declaration, dict) and isinstance(
                declaration.get("path"), str
            ):
                declarations[declaration["path"]] = (
                    _require_digest(
                        declaration.get("contentDigest"),
                        f"Evidence declaration for {cohort.cohort_id}",
                    ),
                    _require_length(
                        declaration.get("byteLength"),
                        f"Evidence declaration for {cohort.cohort_id}",
                    ),
                )
        required = {
            "canonical-observations.json",
            "canonical-observations.csv",
            "run.json",
            "collation-report.json",
        }
        if not required <= declarations.keys():
            raise SQLiteExportError(
                f"Evidence manifest is incomplete: {cohort.cohort_id}"
            )
        run_path = manifest_path.parent / "run.json"
        run_bytes = _read_bytes(run_path, "run evidence")
        run_digest, run_length = declarations["run.json"]
        if len(run_bytes) != run_length or sha256_digest(run_bytes) != run_digest:
            raise SQLiteExportError(
                f"Run evidence changed after manifest validation: {cohort.cohort_id}"
            )
        run = _json_bytes_object(run_bytes, run_path, "run evidence")
        run_provider_calls = _strict_zero(
            run.get("providerCalls"), f"Run providerCalls for {cohort.cohort_id}"
        )
        if manifest_provider_calls != run_provider_calls:
            raise SQLiteExportError(
                f"Manifest/run providerCalls mismatch: {cohort.cohort_id}"
            )
        if run.get("historicalReplayIsAcceptanceAuthority") is not False:
            raise SQLiteExportError(
                "Run historicalReplayIsAcceptanceAuthority must be literal false: "
                f"{cohort.cohort_id}"
            )
        if run.get("trainingEligibility") is not False:
            raise SQLiteExportError(
                f"Run trainingEligibility must be literal false: {cohort.cohort_id}"
            )
        run_contract_digest = _require_digest(
            run.get("acceptanceContractDigest"),
            f"Run acceptanceContractDigest for {cohort.cohort_id}",
        )
        if run_contract_digest != contract_digest:
            raise SQLiteExportError(
                f"Run acceptance contract does not match cohort: {cohort.cohort_id}"
            )
        manifest_contract_digest = manifest.get("acceptanceContractDigest")
        if manifest_contract_digest is not None:
            manifest_contract_digest = _require_digest(
                manifest_contract_digest,
                f"Manifest acceptanceContractDigest for {cohort.cohort_id}",
            )
            if manifest_contract_digest != run_contract_digest:
                raise SQLiteExportError(
                    f"Manifest/run acceptance contract mismatch: {cohort.cohort_id}"
                )
        assets = cohort.assets
        _validate_aggregate_counts(cohort.cohort_id, manifest, run, assets)
        canonical_paths = {asset.canonical_path for asset in assets}
        if len(canonical_paths) != 1:
            raise SQLiteExportError(
                f"Cohort canonical evidence is ambiguous: {cohort.cohort_id}"
            )
        cohort_inputs.append(
            CohortInput(
                cohort_id=cohort.cohort_id,
                cohort_path=cohort_relative,
                evidence_manifest_path=manifest_relative,
                acceptance_contract_path=contract_relative,
                acceptance_contract_digest=contract_digest,
                acceptance_contract_length=len(contract_bytes),
                acceptance_policy_version=policy_version,
                acceptance_policy_digest=policy_digest,
                canonical_path=next(iter(canonical_paths)),
                declarations=declarations,
            )
        )
    if set(configs) != {cohort.cohort_id for cohort in status.cohorts}:
        raise SQLiteExportError("Registry/cohort association mismatch")
    return ExportContext(
        root=root,
        registry_relative=registry_relative,
        registry_digest=sha256_digest(registry_bytes),
        registry_length=len(registry_bytes),
        status=status,
        cohorts=tuple(cohort_inputs),
    )


def _publication_rows(context: ExportContext) -> list[tuple[Any, ...]]:
    return [
        (item.publication_id, ordinal, item.label, item.period_format)
        for ordinal, item in enumerate(context.status.publications)
    ]


def _cohort_rows(context: ExportContext) -> list[tuple[Any, ...]]:
    return [
        (
            item.cohort_id,
            ordinal,
            item.publication_id,
            item.label,
            item.dagster_asset,
            item.checks_state,
            item.evidence_recorded_at,
            len(item.assets),
            sum(asset.canonical_count or 0 for asset in item.assets),
        )
        for ordinal, item in enumerate(context.status.cohorts)
    ]


def _asset_rows(context: ExportContext) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for ordinal, item in enumerate(context.status.assets):
        rows.append(
            (
                item.asset_id,
                ordinal,
                item.cohort_id,
                item.publication_id,
                item.year,
                item.reference_date,
                item.sheet,
                item.source_path,
                item.source_digest,
                item.source_byte_length,
                item.stages["identified"],
                item.stages["on_disk"],
                item.stages["tidied"],
                item.stages["canonicalised"],
                item.stages["integrated"],
                item.checks_state,
                item.canonical_count,
                item.raw_count,
                item.excluded_count,
                item.decision,
                item.decision_id,
                item.prepare_derivation_id,
                item.interpret_derivation_id,
                item.replay_model,
                item.evidence_recorded_at,
                item.normalization,
                item.live_evidence_path,
            )
        )
    return rows


def _asset_check_rows(context: ExportContext) -> list[tuple[Any, ...]]:
    return [
        (asset.asset_id, name, 1)
        for asset in context.status.assets
        for name, passed in asset.checks
        if passed
    ]


def _file_digest(path: Path) -> tuple[str, int]:
    data = _read_bytes(path, "provenance file")
    return sha256_digest(data), len(data)


def _provenance_rows(context: ExportContext) -> list[tuple[Any, ...]]:
    status_by_cohort = {item.cohort_id: item for item in context.status.cohorts}
    rows: list[tuple[Any, ...]] = []
    ordinal = 0
    for item in context.cohorts:
        cohort = status_by_cohort[item.cohort_id]
        asset = cohort.assets[0]
        manifest_parent = PurePosixPath(item.evidence_manifest_path).parent
        role_paths = {
            "cohort_manifest": item.cohort_path,
            "acceptance_contract": item.acceptance_contract_path,
            "evidence_manifest": item.evidence_manifest_path,
            "canonical_json": item.canonical_path,
            "canonical_csv": asset.canonical_csv_path,
            "run": asset.run_path,
            "collation": asset.collation_path,
        }
        for role in PROVENANCE_ROLES:
            relative = role_paths[role]
            if role in {"cohort_manifest", "evidence_manifest"}:
                digest, length = _file_digest(_path(context.root, relative, role))
            elif role == "acceptance_contract":
                digest = item.acceptance_contract_digest
                length = item.acceptance_contract_length
            else:
                name = {
                    "canonical_json": "canonical-observations.json",
                    "canonical_csv": "canonical-observations.csv",
                    "run": "run.json",
                    "collation": "collation-report.json",
                }[role]
                digest, length = item.declarations[name]
                if PurePosixPath(relative).parent != manifest_parent:
                    raise SQLiteExportError(
                        f"Evidence path association mismatch: {item.cohort_id} {role}"
                    )
            if not isinstance(digest, str) or not isinstance(length, int):
                raise SQLiteExportError(
                    f"Evidence declaration is invalid: {item.cohort_id} {role}"
                )
            rows.append((ordinal, item.cohort_id, role, relative, digest, length))
            ordinal += 1
    return rows


def _require_string(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise SQLiteExportError(f"Canonical row has invalid {key}")
    return value


def _number_columns(
    value: Any, *, nullable: bool
) -> tuple[str, int | None, float | None]:
    if value is None and nullable:
        return ("null", None, None)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SQLiteExportError("Canonical value must be a number or null")
    if isinstance(value, int):
        if not -(2**63) <= value < 2**63:
            raise SQLiteExportError("Canonical integer is outside SQLite's range")
        return ("integer", value, None)
    return ("real", None, value)


def _raw_columns(
    row: dict[str, Any],
) -> tuple[str, str | None, int | None, float | None]:
    if "raw_value" not in row:
        return ("missing", None, None, None)
    value = row["raw_value"]
    if value is None:
        return ("null", None, None, None)
    if isinstance(value, bool):
        return ("boolean", None, int(value), None)
    if isinstance(value, int):
        if not -(2**63) <= value < 2**63:
            raise SQLiteExportError("Canonical raw integer is outside SQLite's range")
        return ("integer", None, value, None)
    if isinstance(value, float):
        return ("real", None, None, value)
    if isinstance(value, str):
        return ("string", value, None, None)
    raise SQLiteExportError("Canonical raw_value must be a JSON scalar")


def _observation_tuple(
    observation_id: int,
    asset: AssetStatus,
    cohort_input: CohortInput,
    asset_row_ordinal: int,
    row: dict[str, Any],
) -> tuple[Any, ...]:
    canonical = _canonical_json(row)
    if "value" not in row:
        raise SQLiteExportError("Canonical row omits value")
    value_type, value_integer, value_real = _number_columns(row["value"], nullable=True)
    raw_type, raw_text, raw_integer, raw_real = _raw_columns(row)
    decision_digest = _require_digest(
        row.get("acceptance_decision_digest"), "Canonical acceptance decision"
    )
    if decision_digest != asset.decision_id:
        raise SQLiteExportError(
            f"Canonical decision does not match registered asset: {asset.asset_id}"
        )
    policy_digest = _require_digest(
        row.get("acceptance_policy_digest"), "Canonical acceptance policy"
    )
    if (
        policy_digest != cohort_input.acceptance_policy_digest
        or row.get("acceptance_policy_version")
        != cohort_input.acceptance_policy_version
    ):
        raise SQLiteExportError(
            f"Canonical acceptance policy does not match contract: {asset.asset_id}"
        )
    recipe_digest = _require_digest(row.get("recipe_digest"), "Canonical recipe")
    execution_digest = _require_digest(
        row.get("execution_digest"), "Canonical execution"
    )
    prompt_digest = _require_digest(
        row.get("prompt_package_digest"), "Canonical prompt package"
    )
    publication_date = row.get("publication_vintage_date")
    if publication_date is not None and not isinstance(publication_date, str):
        raise SQLiteExportError("Canonical publication_vintage_date is invalid")
    observation_period = row.get("observation_period_id")
    if observation_period is not None and not isinstance(observation_period, str):
        raise SQLiteExportError("Canonical observation_period_id is invalid")
    return (
        observation_id,
        asset.asset_id,
        asset_row_ordinal,
        asset.cohort_id,
        asset.publication_id,
        _require_string(row, "publication_id"),
        publication_date,
        _require_string(row, "reference_date"),
        observation_period,
        _require_string(row, "measure_id"),
        _require_string(row, "unit_id"),
        _require_string(row, "value_status"),
        value_type,
        value_integer,
        value_real,
        raw_type,
        raw_text,
        raw_integer,
        raw_real,
        _require_string(row, "source_workbook_digest"),
        _require_string(row, "source_sheet"),
        _require_string(row, "source_cell"),
        decision_digest,
        policy_digest,
        cohort_input.acceptance_policy_version,
        recipe_digest,
        execution_digest,
        prompt_digest,
        _require_string(row, "generation_attempt_id"),
        _require_string(row, "generation_model"),
        canonical,
    )


def _iter_observations(context: ExportContext) -> Iterator[tuple[Any, ...]]:
    cohort_status = {item.cohort_id: item for item in context.status.cohorts}
    asset_counts = {asset.asset_id: 0 for asset in context.status.assets}
    observation_id = 1
    for item in context.cohorts:
        assets = cohort_status[item.cohort_id].assets
        asset_by_key: dict[tuple[str, str, str], AssetStatus] = {}
        for asset in assets:
            key = (asset.source_digest, asset.sheet, asset.reference_date)
            if key in asset_by_key:
                raise SQLiteExportError(
                    f"Ambiguous canonical-row association in {item.cohort_id}"
                )
            asset_by_key[key] = asset
        path = _path(context.root, item.canonical_path, "canonical JSON")
        canonical_bytes = _read_bytes(path, "canonical JSON")
        expected_digest, expected_length = item.declarations[
            "canonical-observations.json"
        ]
        if (
            len(canonical_bytes) != expected_length
            or sha256_digest(canonical_bytes) != expected_digest
        ):
            raise SQLiteExportError(
                f"Canonical JSON changed after evidence validation: {item.cohort_id}"
            )
        try:
            source_rows = json.loads(canonical_bytes)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise SQLiteExportError(
                f"Canonical JSON is unreadable: {item.canonical_path}"
            ) from error
        if not isinstance(source_rows, list):
            raise SQLiteExportError(
                f"Canonical JSON must be an array: {item.canonical_path}"
            )
        for row in source_rows:
            if not isinstance(row, dict):
                raise SQLiteExportError("Canonical evidence contains a non-object row")
            source_digest = _require_digest(
                row.get("source_workbook_digest"), "Canonical source workbook"
            )
            source_sheet = _require_string(row, "source_sheet")
            reference_date = _require_string(row, "reference_date")
            publication_date = row.get("publication_vintage_date", reference_date)
            if not isinstance(publication_date, str) or not publication_date:
                raise SQLiteExportError("Canonical row association date is invalid")
            asset = asset_by_key.get((source_digest, source_sheet, publication_date))
            if asset is None:
                raise SQLiteExportError(
                    "Canonical row does not map to a registered asset: "
                    f"{item.cohort_id}"
                )
            _require_string(row, "publication_id")
            asset_ordinal = asset_counts[asset.asset_id]
            yield _observation_tuple(observation_id, asset, item, asset_ordinal, row)
            asset_counts[asset.asset_id] += 1
            observation_id += 1
    for asset in context.status.assets:
        if asset_counts[asset.asset_id] != asset.canonical_count:
            raise SQLiteExportError(
                f"Canonical row count does not match asset: {asset.asset_id}"
            )


def _hash_part(hasher: Any, label: str, row: Sequence[Any]) -> None:
    data = _canonical_json([label, *row]).encode("utf-8")
    hasher.update(len(data).to_bytes(8, "big"))
    hasher.update(data)


def _insert_many(
    connection: sqlite3.Connection,
    table: str,
    rows: Sequence[tuple[Any, ...]],
    hasher: Any,
) -> None:
    placeholders = ",".join("?" for _ in TABLE_COLUMNS[table])
    connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    for row in rows:
        _hash_part(hasher, table, row)


SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(Path(str(path) + suffix) for suffix in SIDECAR_SUFFIXES)


def _assert_no_sidecars(path: Path, label: str) -> None:
    if any(item.exists() or item.is_symlink() for item in _sidecars(path)):
        raise SQLiteExportError(f"{label} has a WAL/SHM/journal sidecar: {path}")


def _cleanup_temporary_sidecars(path: Path) -> None:
    for sidecar in _sidecars(path):
        sidecar.unlink(missing_ok=True)


def _cleanup_temporary(path: Path) -> None:
    path.unlink(missing_ok=True)
    _cleanup_temporary_sidecars(path)


def _samefile(left: Path, right: Path, label: str) -> bool:
    try:
        return left.samefile(right)
    except OSError as error:
        raise SQLiteExportError(
            f"Cannot verify filesystem identity for {label}: {left} and {right}"
        ) from error


def _forbidden_build_inputs(context: ExportContext) -> set[Path]:
    forbidden = {_path(context.root, context.registry_relative.as_posix(), "registry")}
    for item in context.cohorts:
        forbidden.update(
            {
                _path(context.root, item.cohort_path, "cohort manifest"),
                _path(
                    context.root,
                    item.evidence_manifest_path,
                    "evidence manifest",
                ),
                _path(
                    context.root,
                    item.acceptance_contract_path,
                    "acceptance contract",
                ),
            }
        )
        manifest_parent = PurePosixPath(item.evidence_manifest_path).parent
        for declared_path in item.declarations:
            relative = (manifest_parent / declared_path).as_posix()
            forbidden.add(_path(context.root, relative, "declared evidence file"))
    forbidden.update(
        _path(context.root, asset.source_path, "registered source workbook")
        for asset in context.status.assets
    )
    return forbidden


def build_export(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    context = _prepare_context(project_root, registry_relative)
    candidate = output if output.is_absolute() else context.root / output
    if candidate.is_symlink():
        raise SQLiteExportError(f"Output path must not be a symlink: {candidate}")
    target = candidate.resolve()
    forbidden_inputs = _forbidden_build_inputs(context)
    if target in forbidden_inputs:
        raise SQLiteExportError(f"Output path is a registered input: {target}")
    if target.exists() and not target.is_file():
        raise SQLiteExportError(f"Output must be a regular file path: {target}")
    if target.exists() and any(
        _samefile(target, protected, "build output") for protected in forbidden_inputs
    ):
        raise SQLiteExportError(
            f"Output filesystem identity is a registered input: {target}"
        )
    _assert_no_sidecars(target, "Existing output")
    temporary: Path | None = None
    connection: sqlite3.Connection | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_handle, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.tmp-", dir=target.parent
        )
        os.close(temporary_handle)
        temporary = Path(temporary_name)
        connection = sqlite3.connect(temporary)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA temp_store = FILE")
        connection.executescript(SCHEMA_SQL)
        hasher = hashlib.sha256()
        publication_rows = _publication_rows(context)
        cohort_rows = _cohort_rows(context)
        asset_rows = _asset_rows(context)
        asset_check_rows = _asset_check_rows(context)
        provenance_rows = _provenance_rows(context)
        _insert_many(connection, "publication", publication_rows, hasher)
        _insert_many(connection, "cohort", cohort_rows, hasher)
        _insert_many(connection, "asset", asset_rows, hasher)
        _insert_many(connection, "asset_check", asset_check_rows, hasher)
        _insert_many(connection, "provenance_file", provenance_rows, hasher)
        insert_sql = (
            "INSERT INTO observation VALUES ("
            + ",".join("?" for _ in TABLE_COLUMNS["observation"])
            + ")"
        )
        observation_count = 0
        batch: list[tuple[Any, ...]] = []
        for row in _iter_observations(context):
            batch.append(row)
            _hash_part(hasher, "observation", row)
            observation_count += 1
            if len(batch) == 1000:
                connection.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            connection.executemany(insert_sql, batch)
        expected_count = sum(
            asset.canonical_count or 0 for asset in context.status.assets
        )
        if observation_count != expected_count:
            raise SQLiteExportError("Consolidated observation count mismatch")
        logical_digest = "sha256:" + hasher.hexdigest()
        metadata = (
            1,
            SCHEMA_VERSION,
            context.status.recorded_at,
            context.registry_relative.as_posix(),
            context.registry_digest,
            context.registry_length,
            len(publication_rows),
            len(cohort_rows),
            len(asset_rows),
            observation_count,
            context.status.physical_workbook_count,
            logical_digest,
            0,
            0,
            0,
        )
        connection.execute(
            "INSERT INTO export_metadata VALUES ("
            + ",".join("?" for _ in metadata)
            + ")",
            metadata,
        )
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise SQLiteExportError("Built database failed SQLite integrity_check")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise SQLiteExportError("Built database failed foreign_key_check")
        connection.close()
        connection = None
        _cleanup_temporary_sidecars(temporary)
        _assert_no_sidecars(target, "Existing output")
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except (OSError, sqlite3.Error) as error:
        raise SQLiteExportError(f"SQLite export build failed: {error}") from error
    finally:
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.close()
        if temporary is not None:
            with suppress(OSError):
                _cleanup_temporary(temporary)
    result = _artifact_metrics(target)
    result.update(
        {
            "schemaVersion": SCHEMA_VERSION,
            "publications": len(context.status.publications),
            "cohorts": len(context.status.cohorts),
            "assets": len(context.status.assets),
            "observations": sum(
                asset.canonical_count or 0 for asset in context.status.assets
            ),
            "logicalContentSha256": logical_digest,
            "integrityCheck": "ok",
            "foreignKeyViolations": 0,
            "acceptanceAuthority": False,
            "trainingEligibility": False,
            "providerCalls": 0,
        }
    )
    return result


def _artifact_metrics(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    length = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                length += len(chunk)
    except OSError as error:
        raise SQLiteExportError(f"Artifact is unreadable: {path}") from error
    return {
        "path": str(path),
        "byteLength": length,
        "sha256": "sha256:" + digest.hexdigest(),
    }


def _database_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _schema_rows(connection: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
        "ORDER BY type, name"
    ).fetchall()


def _expected_schema_rows() -> list[tuple[Any, ...]]:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(SCHEMA_SQL)
        return _schema_rows(connection)


def _compare_rows(
    connection: sqlite3.Connection,
    table: str,
    expected: Sequence[tuple[Any, ...]],
    order_by: str,
) -> None:
    actual = connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
    if actual != list(expected):
        raise SQLiteExportError(f"Database {table} content does not match evidence")


def check_export(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
    database: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    context = _prepare_context(project_root, registry_relative)
    target = database if database.is_absolute() else context.root / database
    if target.is_symlink() or not target.is_file():
        raise SQLiteExportError(f"Database is missing or not a regular file: {target}")
    _assert_no_sidecars(target, "Database")
    before_metrics = _artifact_metrics(target)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_database_uri(target), uri=True)
        connection.execute("PRAGMA foreign_keys = ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise SQLiteExportError(f"SQLite integrity_check failed: {integrity}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise SQLiteExportError(
                f"SQLite foreign_key_check failed: {foreign_keys[:5]}"
            )
        if _schema_rows(connection) != _expected_schema_rows():
            raise SQLiteExportError("Database DDL does not match the export schema")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != set(TABLE_COLUMNS):
            raise SQLiteExportError(
                "Database table set does not match the export schema"
            )
        for table, columns in TABLE_COLUMNS.items():
            actual_columns = tuple(
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual_columns != columns:
                raise SQLiteExportError(f"Database schema mismatch for {table}")
        publications = _publication_rows(context)
        cohorts = _cohort_rows(context)
        assets = _asset_rows(context)
        checks = _asset_check_rows(context)
        provenance = _provenance_rows(context)
        _compare_rows(connection, "publication", publications, "publication_ordinal")
        _compare_rows(connection, "cohort", cohorts, "cohort_ordinal")
        _compare_rows(connection, "asset", assets, "asset_ordinal")
        _compare_rows(connection, "asset_check", sorted(checks), "asset_id, check_name")
        _compare_rows(connection, "provenance_file", provenance, "provenance_ordinal")
        cursor = connection.execute("SELECT * FROM observation ORDER BY observation_id")
        hasher = hashlib.sha256()
        for table, rows in (
            ("publication", publications),
            ("cohort", cohorts),
            ("asset", assets),
            ("asset_check", checks),
            ("provenance_file", provenance),
        ):
            for row in rows:
                _hash_part(hasher, table, row)
        observation_count = 0
        for expected in _iter_observations(context):
            actual = cursor.fetchone()
            if actual != expected:
                raise SQLiteExportError(
                    f"Database observation content mismatch at row {expected[0]}"
                )
            _hash_part(hasher, "observation", expected)
            observation_count += 1
        if cursor.fetchone() is not None:
            raise SQLiteExportError(
                "Database contains observations outside registry scope"
            )
        logical_digest = "sha256:" + hasher.hexdigest()
        metadata = connection.execute("SELECT * FROM export_metadata").fetchall()
        expected_metadata = [
            (
                1,
                SCHEMA_VERSION,
                context.status.recorded_at,
                context.registry_relative.as_posix(),
                context.registry_digest,
                context.registry_length,
                len(publications),
                len(cohorts),
                len(assets),
                observation_count,
                context.status.physical_workbook_count,
                logical_digest,
                0,
                0,
                0,
            )
        ]
        if metadata != expected_metadata:
            raise SQLiteExportError("Database export metadata does not match evidence")
    except (OSError, sqlite3.Error) as error:
        raise SQLiteExportError(f"SQLite export check failed: {error}") from error
    finally:
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.close()
    _assert_no_sidecars(target, "Database")
    after_metrics = _artifact_metrics(target)
    if after_metrics != before_metrics:
        raise SQLiteExportError("Database changed during validation")
    result = after_metrics
    result.update(
        {
            "schemaVersion": SCHEMA_VERSION,
            "publications": len(publications),
            "cohorts": len(cohorts),
            "assets": len(assets),
            "observations": observation_count,
            "logicalContentSha256": logical_digest,
            "integrityCheck": "ok",
            "foreignKeyViolations": 0,
            "provenance": "matches-current-registered-evidence",
            "acceptanceAuthority": False,
            "trainingEligibility": False,
            "providerCalls": 0,
        }
    )
    return result


def _validated_source_metrics(checked: dict[str, Any]) -> tuple[int, str]:
    if (
        checked.get("schemaVersion") != SCHEMA_VERSION
        or checked.get("integrityCheck") != "ok"
        or checked.get("foreignKeyViolations") != 0
        or checked.get("provenance") != "matches-current-registered-evidence"
        or checked.get("acceptanceAuthority") is not False
        or checked.get("trainingEligibility") is not False
        or isinstance(checked.get("providerCalls"), bool)
        or checked.get("providerCalls") != 0
    ):
        raise SQLiteExportError("Packaging requires a full passing export check")
    length = _require_length(checked.get("byteLength"), "Checked database length")
    digest = _require_digest(checked.get("sha256"), "Checked database SHA-256")
    return length, digest


def package_checked_export(
    database: Path,
    checked: dict[str, Any],
    package: Path | None = None,
    *,
    max_bytes: int = MAX_RELEASE_BYTES,
) -> dict[str, Any]:
    expected_length, expected_digest = _validated_source_metrics(checked)
    if database.is_symlink() or not database.is_file():
        raise SQLiteExportError(
            f"Database is missing or not a regular file: {database}"
        )
    source = database.resolve()
    checked_path = checked.get("path")
    if not isinstance(checked_path, str) or Path(checked_path).resolve() != source:
        raise SQLiteExportError("Checked result belongs to a different database")
    _assert_no_sidecars(source, "Database")
    if max_bytes <= 0:
        raise SQLiteExportError("Release size limit must be positive")
    candidate = package or Path(str(source) + ".gz")
    if candidate.is_symlink():
        raise SQLiteExportError(f"Package output must not be a symlink: {candidate}")
    target = candidate.resolve()
    if target == source:
        raise SQLiteExportError("Package output must differ from the source database")
    if target.exists() and not target.is_file():
        raise SQLiteExportError(f"Package output must be a regular file: {target}")
    if target.exists() and _samefile(target, source, "package output"):
        raise SQLiteExportError(
            "Package output filesystem identity must differ from the source database"
        )
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.tmp-", dir=target.parent
        )
        os.close(handle)
        temporary = Path(temporary_name)
        source_hasher = hashlib.sha256()
        source_length = 0
        with (
            source.open("rb") as input_file,
            temporary.open("wb") as raw_output,
            gzip.GzipFile(
                filename="", mode="wb", fileobj=raw_output, compresslevel=9, mtime=0
            ) as output_file,
        ):
            while chunk := input_file.read(1024 * 1024):
                source_hasher.update(chunk)
                source_length += len(chunk)
                output_file.write(chunk)
        streamed_digest = "sha256:" + source_hasher.hexdigest()
        if (source_length, streamed_digest) != (expected_length, expected_digest):
            raise SQLiteExportError("Database changed after validation")
        current_metrics = _artifact_metrics(source)
        if (
            current_metrics["byteLength"],
            current_metrics["sha256"],
        ) != (expected_length, expected_digest):
            raise SQLiteExportError("Database changed during packaging")
        expanded_hasher = hashlib.sha256()
        expanded_length = 0
        with gzip.open(temporary, "rb") as expanded:
            while chunk := expanded.read(1024 * 1024):
                expanded_hasher.update(chunk)
                expanded_length += len(chunk)
        if (
            expanded_length,
            "sha256:" + expanded_hasher.hexdigest(),
        ) != (expected_length, expected_digest):
            raise SQLiteExportError(
                "Temporary gzip does not reproduce checked database"
            )
        size = temporary.stat().st_size
        if size >= max_bytes:
            raise SQLiteExportError(
                f"Release package must be strictly smaller than {max_bytes} bytes"
            )
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        raise SQLiteExportError(f"SQLite export packaging failed: {error}") from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    result = _artifact_metrics(target)
    result.update(
        {
            "format": "gzip",
            "source": {
                "path": str(source),
                "byteLength": expected_length,
                "sha256": expected_digest,
            },
            "maximumByteLengthExclusive": max_bytes,
            "underSizeLimit": True,
            "validatedAgainstEvidence": True,
            "releaseAsset": True,
            "decompressedSourceVerified": True,
        }
    )
    return result
