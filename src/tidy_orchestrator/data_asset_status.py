# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any

from .offenders_acceptance import c4_shared_access

# The generated single-file interface embeds intentionally compact HTML, CSS, and JS.

REGISTRY_SCHEMA = "tidy.data-asset-status-registry/v1"
DEFAULT_REGISTRY = Path("fixtures/product-prototype/data-asset-status-v1.json")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
STAGE_KEYS = ("identified", "on_disk", "tidied", "canonicalised", "integrated")
STAGE_LABELS = {
    "identified": "Identified",
    "on_disk": "On disk",
    "tidied": "Tidied",
    "canonicalised": "Canonicalised",
    "integrated": "Integrated",
}
CHECK_LABELS = {
    "codelists": "Code lists",
    "coverage": "Expected category coverage",
    "deterministicReplay": "Deterministic replay",
    "interpretation": "Interpretation and execution",
    "nonEmpty": "Non-empty output",
    "requiredDimensions": "Required dimensions",
    "rowBounds": "Row bounds",
    "rowSelection": "Row selection and exclusions",
    "sourceCellUniqueness": "Source-cell uniqueness",
    "totalEquations": "Total equations",
    "uniqueKeys": "Unique keys",
    "warningAllowlist": "Warning allowlist",
}
COLLATION_ISSUE_FIELDS = {
    "codeListFailures": "Code-list failures",
    "conflictingValues": "Conflicting values",
    "duplicateCanonicalKeys": "Duplicate canonical keys",
    "excludedExceptions": "Excluded exceptions",
    "missingExpectedCategories": "Missing expected categories",
    "schemaFailures": "Schema failures",
    "unmappedLabels": "Unmapped labels",
}


class DataAssetStatusError(ValueError):
    """The status registry or configured cohort cannot be interpreted safely."""


@dataclass(frozen=True)
class AssetStatus:
    asset_id: str
    cohort_id: str
    cohort_label: str
    publication_id: str
    publication_label: str
    period_format: str
    dagster_asset: str
    year: int
    reference_date: str
    sheet: str
    source_path: str
    source_digest: str
    source_byte_length: int
    stages: dict[str, str]
    checks_state: str
    checks: tuple[tuple[str, bool], ...]
    issues: tuple[str, ...]
    canonical_count: int | None
    raw_count: int | None
    excluded_count: int | None
    decision: str | None
    decision_id: str | None
    prepare_derivation_id: str | None
    interpret_derivation_id: str | None
    replay_model: str | None
    evidence_recorded_at: str | None
    evidence_manifest_path: str
    run_path: str
    collation_path: str
    canonical_path: str
    canonical_csv_path: str
    canonical_csv_digest: str | None
    canonical_csv_byte_length: int | None
    csv_route: str | None
    normalization: str | None
    live_evidence_path: str | None


@dataclass(frozen=True)
class CohortStatus:
    cohort_id: str
    label: str
    publication_id: str
    publication_label: str
    period_format: str
    dagster_asset: str
    assets: tuple[AssetStatus, ...]
    checks_state: str
    issues: tuple[str, ...]
    evidence_recorded_at: str | None


@dataclass(frozen=True)
class PublicationStatus:
    publication_id: str
    label: str
    period_format: str
    cohorts: tuple[CohortStatus, ...]


@dataclass(frozen=True)
class DashboardStatus:
    title: str
    recorded_at: str
    output_path: str
    host: str
    port: int
    tailnet_hostname: str
    tailnet_https_port: int
    dagster_port: int
    cohorts: tuple[CohortStatus, ...]
    physical_workbook_count: int

    @property
    def assets(self) -> tuple[AssetStatus, ...]:
        return tuple(asset for cohort in self.cohorts for asset in cohort.assets)

    @property
    def publications(self) -> tuple[PublicationStatus, ...]:
        grouped: dict[str, list[CohortStatus]] = {}
        for cohort in self.cohorts:
            grouped.setdefault(cohort.publication_id, []).append(cohort)
        return tuple(
            PublicationStatus(
                publication_id=cohorts[0].publication_id,
                label=cohorts[0].publication_label,
                period_format=cohorts[0].period_format,
                cohorts=tuple(cohorts),
            )
            for cohorts in grouped.values()
        )


@dataclass(frozen=True)
class EvidenceBundle:
    recorded_at: str | None
    run: dict[str, Any] | None
    collation: dict[str, Any] | None
    canonical_counts: dict[tuple[str, str, str], int]
    file_states: dict[str, bool | None]
    file_paths: dict[str, str]
    file_declarations: dict[str, tuple[str, int]]
    evidence_issues: tuple[str, ...]
    quality_issues: tuple[str, ...]


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise DataAssetStatusError(f"{label} does not exist: {path}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise DataAssetStatusError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise DataAssetStatusError(f"{label} must be a JSON object: {path}")
    return value


def _safe_relative_path(root: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise DataAssetStatusError(f"{label} must be a non-empty relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise DataAssetStatusError(f"{label} is not a safe relative path: {relative}")
    target = root.joinpath(*pure.parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise DataAssetStatusError(
            f"{label} escapes the project: {relative}"
        ) from error
    return target


def _safe_nested_path(
    project_root: Path, base: Path, relative: str, label: str
) -> Path:
    if not isinstance(relative, str) or not relative:
        raise DataAssetStatusError(f"{label} must be a non-empty relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise DataAssetStatusError(f"{label} is not a safe relative path: {relative}")
    target = base.joinpath(*pure.parts).resolve()
    try:
        target.relative_to(project_root.resolve())
    except ValueError as error:
        raise DataAssetStatusError(
            f"{label} escapes the project: {relative}"
        ) from error
    return target


def _relative(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _valid_recorded_at(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def _validate_registry(value: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "title",
        "recordedAt",
        "outputPath",
        "server",
        "cohorts",
    }
    if (
        not required <= set(value) <= required | {"publications"}
        or value.get("schemaVersion") != REGISTRY_SCHEMA
    ):
        raise DataAssetStatusError("Status registry shape or schema version is invalid")
    if not isinstance(value.get("title"), str) or not value["title"]:
        raise DataAssetStatusError("Status registry title is invalid")
    if not _valid_recorded_at(value.get("recordedAt")):
        raise DataAssetStatusError("Status registry recordedAt must include a timezone")
    server = value.get("server")
    if not isinstance(server, dict) or set(server) != {
        "host",
        "port",
        "tailnetHostname",
        "tailnetHttpsPort",
        "dagsterPort",
    }:
        raise DataAssetStatusError("Status registry server configuration is invalid")
    if (
        server.get("host") != "127.0.0.1"
        or server.get("port") != 3031
        or server.get("tailnetHttpsPort") != 3031
        or server.get("dagsterPort") != 3030
        or not isinstance(server.get("tailnetHostname"), str)
        or not server["tailnetHostname"]
    ):
        raise DataAssetStatusError("Status registry server boundary is invalid")
    publications = value.get("publications")
    if publications is not None:
        if not isinstance(publications, list) or not publications:
            raise DataAssetStatusError("Status registry publications are invalid")
        publication_ids: set[str] = set()
        for publication in publications:
            if (
                not isinstance(publication, dict)
                or set(publication) != {"publicationId", "label", "periodFormat"}
                or not isinstance(publication.get("publicationId"), str)
                or not publication["publicationId"]
                or not isinstance(publication.get("label"), str)
                or not publication["label"]
                or publication.get("periodFormat")
                not in {"calendar-year", "fiscal-year"}
                or publication["publicationId"] in publication_ids
            ):
                raise DataAssetStatusError("Status registry publications are invalid")
            publication_ids.add(publication["publicationId"])
    cohorts = value.get("cohorts")
    if not isinstance(cohorts, list) or not cohorts:
        raise DataAssetStatusError("Status registry must configure at least one cohort")
    seen: set[str] = set()
    required_cohort = {
        "cohortId",
        "label",
        "cohortPath",
        "evidenceManifestPath",
        "dagsterAsset",
    }
    for cohort in cohorts:
        if not isinstance(cohort, dict) or not required_cohort <= set(cohort) <= (
            required_cohort | {"liveEvidence"}
        ):
            raise DataAssetStatusError("Status registry cohort entry is invalid")
        if any(
            not isinstance(cohort.get(key), str) or not cohort[key]
            for key in required_cohort
        ):
            raise DataAssetStatusError("Status registry cohort strings are invalid")
        if cohort["cohortId"] in seen:
            raise DataAssetStatusError("Status registry cohort IDs must be unique")
        seen.add(cohort["cohortId"])
        live = cohort.get("liveEvidence")
        if live is not None and (
            not isinstance(live, dict)
            or set(live) != {"manifestPath", "years"}
            or not isinstance(live.get("manifestPath"), str)
            or not live["manifestPath"]
            or not isinstance(live.get("years"), list)
            or not live["years"]
            or any(
                isinstance(year, bool) or not isinstance(year, int)
                for year in live["years"]
            )
            or len(live["years"]) != len(set(live["years"]))
        ):
            raise DataAssetStatusError("Status registry live-evidence entry is invalid")


def _validate_cohort(value: dict[str, Any], expected_id: str) -> None:
    required = {
        "schemaVersion",
        "cohortId",
        "publicationId",
        "tableFamilyId",
        "generation",
        "acceptanceContract",
        "workbooks",
    }
    if not required <= set(value) <= required | {"workerLimits"}:
        raise DataAssetStatusError(f"Cohort {expected_id} has an invalid shape")
    if value.get("cohortId") != expected_id:
        raise DataAssetStatusError(f"Cohort identity does not match {expected_id}")
    workbooks = value.get("workbooks")
    if not isinstance(workbooks, list) or not workbooks:
        raise DataAssetStatusError(f"Cohort {expected_id} has no workbook entries")
    seen: set[tuple[int, str]] = set()
    required_workbook = {
        "year",
        "referenceDate",
        "path",
        "contentDigest",
        "byteLength",
        "sheet",
        "replayResponse",
    }
    c4_workbook_metadata = {
        "releaseId",
        "downloadOrdinal",
        "cubeId",
        "tableNamespace",
    }
    for workbook in workbooks:
        keys = set(workbook) if isinstance(workbook, dict) else set()
        extras = keys - required_workbook - {"normalization"}
        is_c4 = extras == c4_workbook_metadata
        if (
            not isinstance(workbook, dict)
            or not required_workbook <= keys
            or (extras and not is_c4)
        ):
            raise DataAssetStatusError(
                f"Cohort {expected_id} has an invalid workbook entry"
            )
        year = workbook.get("year")
        sheet = workbook.get("sheet")
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not isinstance(sheet, str)
            or not sheet
            or not isinstance(workbook.get("referenceDate"), str)
            or not workbook["referenceDate"]
            or not isinstance(workbook.get("path"), str)
            or not workbook["path"]
            or not isinstance(workbook.get("contentDigest"), str)
            or DIGEST_PATTERN.fullmatch(workbook["contentDigest"]) is None
            or isinstance(workbook.get("byteLength"), bool)
            or not isinstance(workbook.get("byteLength"), int)
            or workbook["byteLength"] < 0
        ):
            raise DataAssetStatusError(
                f"Cohort {expected_id} has invalid workbook identity fields"
            )
        key = (year, sheet)
        if key in seen:
            raise DataAssetStatusError(
                f"Cohort {expected_id} repeats workbook/sheet {year} {sheet}"
            )
        seen.add(key)
        replay = workbook.get("replayResponse")
        if (
            not isinstance(replay, dict)
            or not isinstance(replay.get("historicalModel"), str)
            or not replay["historicalModel"]
        ):
            raise DataAssetStatusError(
                f"Cohort {expected_id} has invalid replay provenance"
            )
        if is_c4:
            expected_replay_keys = {
                "path",
                "contentDigest",
                "byteLength",
                "historicalModel",
                "acceptanceAuthority",
                "recipeProtocol",
            }
            if (
                value.get("publicationId") != "recorded-crime-offenders"
                or set(replay) != expected_replay_keys
                or replay.get("acceptanceAuthority") is not False
                or replay.get("recipeProtocol")
                not in {"RecipeV01", "TargetScopedRecipeV02"}
                or not replay["historicalModel"].startswith(
                    "provider-free/offenders-c4/"
                )
                or not isinstance(workbook.get("releaseId"), str)
                or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}", workbook["releaseId"])
                or isinstance(workbook.get("downloadOrdinal"), bool)
                or not isinstance(workbook.get("downloadOrdinal"), int)
                or workbook["downloadOrdinal"] <= 0
                or any(
                    not isinstance(workbook.get(field), str) or not workbook[field]
                    for field in ("cubeId", "tableNamespace")
                )
            ):
                raise DataAssetStatusError(
                    f"Cohort {expected_id} has invalid C4 metadata"
                )


def _read_json_for_evidence(
    path: Path, relative_path: str, issues: list[str]
) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        issues.append(f"Evidence JSON is unreadable: {relative_path}")
        return None


def _load_evidence(
    project_root: Path,
    manifest_path: Path,
    manifest_relative: str,
    cohort_relative: str,
    cohort_digest: str,
) -> EvidenceBundle:
    required_files = {
        "canonical-observations.csv",
        "canonical-observations.json",
        "collation-report.json",
        "run.json",
    }
    file_states: dict[str, bool | None] = {name: None for name in required_files}
    file_paths = {
        name: f"{manifest_path.parent.relative_to(project_root).as_posix()}/{name}"
        for name in required_files
    }
    file_declarations: dict[str, tuple[str, int]] = {}
    evidence_issues: list[str] = []
    quality_issues: list[str] = []
    if not manifest_path.is_file() or manifest_path.is_symlink():
        evidence_issues.append(f"Evidence manifest is missing: {manifest_relative}")
        return EvidenceBundle(
            None,
            None,
            None,
            {},
            file_states,
            file_paths,
            file_declarations,
            tuple(evidence_issues),
            (),
        )
    manifest_value = _read_json_for_evidence(
        manifest_path, manifest_relative, evidence_issues
    )
    if not isinstance(manifest_value, dict):
        return EvidenceBundle(
            None,
            None,
            None,
            {},
            file_states,
            file_paths,
            file_declarations,
            tuple(evidence_issues),
            (),
        )
    recorded_at = manifest_value.get("recordedAt")
    if not _valid_recorded_at(recorded_at):
        evidence_issues.append("Evidence manifest recordedAt is invalid")
        recorded_at = None
    if manifest_value.get("cohortPath") != cohort_relative:
        evidence_issues.append("Evidence manifest points to a different cohort")
    if manifest_value.get("cohortDigest") != cohort_digest:
        evidence_issues.append("Evidence manifest cohort digest does not match")
    files = manifest_value.get("files")
    declared: dict[str, dict[str, Any]] = {}
    if not isinstance(files, list):
        evidence_issues.append("Evidence manifest file list is invalid")
        files = []
    for entry in files:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "contentDigest", "byteLength"}
            or not isinstance(entry.get("path"), str)
            or not entry["path"]
            or not isinstance(entry.get("contentDigest"), str)
            or DIGEST_PATTERN.fullmatch(entry["contentDigest"]) is None
            or isinstance(entry.get("byteLength"), bool)
            or not isinstance(entry.get("byteLength"), int)
            or entry["byteLength"] < 0
        ):
            evidence_issues.append("Evidence manifest contains an invalid file entry")
            continue
        name = entry["path"]
        if name in declared:
            evidence_issues.append(f"Evidence manifest repeats file: {name}")
            continue
        declared[name] = entry
        file_declarations[name] = (entry["contentDigest"], entry["byteLength"])
        try:
            target = _safe_nested_path(
                project_root, manifest_path.parent, name, "evidence file path"
            )
        except DataAssetStatusError:
            evidence_issues.append(f"Evidence file path is unsafe: {name}")
            if name in file_states:
                file_states[name] = False
            continue
        if name in file_paths:
            file_paths[name] = _relative(project_root, target)
        if not target.is_file() or target.is_symlink():
            evidence_issues.append(
                f"Evidence file is missing: {_relative(project_root, target)}"
            )
            if name in file_states:
                file_states[name] = False
            continue
        data = target.read_bytes()
        valid = (
            len(data) == entry["byteLength"]
            and sha256_digest(data) == entry["contentDigest"]
        )
        if name in file_states:
            file_states[name] = valid
        if not valid:
            evidence_issues.append(
                f"Evidence file digest or length mismatch: {_relative(project_root, target)}"
            )
    for name in required_files - set(declared):
        evidence_issues.append(f"Evidence manifest omits required file: {name}")

    run: dict[str, Any] | None = None
    if file_states["run.json"] is True:
        run_path = project_root / file_paths["run.json"]
        run_value = _read_json_for_evidence(
            run_path, file_paths["run.json"], evidence_issues
        )
        if isinstance(run_value, dict):
            run = run_value
            if run.get("runDigest") != manifest_value.get("runDigest"):
                evidence_issues.append("Run digest does not match evidence manifest")
            if run.get("cohortDigest") != cohort_digest:
                evidence_issues.append(
                    "Run cohort digest does not match current cohort"
                )
            cross_year = run.get("crossYearIssues")
            if not isinstance(cross_year, list):
                evidence_issues.append("Run crossYearIssues field is invalid")
            elif cross_year:
                quality_issues.append(f"Cross-year issues: {len(cross_year)}")
        else:
            file_states["run.json"] = False

    canonical_counts: dict[tuple[str, str, str], int] = {}
    if file_states["canonical-observations.json"] is True:
        canonical_path = project_root / file_paths["canonical-observations.json"]
        rows = _read_json_for_evidence(
            canonical_path, file_paths["canonical-observations.json"], evidence_issues
        )
        if isinstance(rows, list):
            malformed = 0
            for row in rows:
                if not isinstance(row, dict) or not all(
                    isinstance(row.get(key), str) and row[key]
                    for key in (
                        "source_workbook_digest",
                        "source_sheet",
                        "reference_date",
                    )
                ):
                    malformed += 1
                    continue
                publication_date = row.get(
                    "publication_vintage_date", row["reference_date"]
                )
                if not isinstance(publication_date, str) or not publication_date:
                    malformed += 1
                    continue
                key = (
                    row["source_workbook_digest"],
                    row["source_sheet"],
                    publication_date,
                )
                canonical_counts[key] = canonical_counts.get(key, 0) + 1
            if malformed:
                evidence_issues.append(
                    f"Canonical output contains malformed rows: {malformed}"
                )
                file_states["canonical-observations.json"] = False
        else:
            file_states["canonical-observations.json"] = False

    collation: dict[str, Any] | None = None
    if file_states["collation-report.json"] is True:
        collation_path = project_root / file_paths["collation-report.json"]
        collation_value = _read_json_for_evidence(
            collation_path, file_paths["collation-report.json"], evidence_issues
        )
        if isinstance(collation_value, dict):
            collation = collation_value
            for key, label in COLLATION_ISSUE_FIELDS.items():
                found = collation.get(key)
                if not isinstance(found, list):
                    evidence_issues.append(f"Collation field is invalid: {key}")
                elif found:
                    quality_issues.append(f"{label}: {len(found)}")
        else:
            file_states["collation-report.json"] = False

    return EvidenceBundle(
        recorded_at,
        run,
        collation,
        canonical_counts,
        file_states,
        file_paths,
        file_declarations,
        tuple(dict.fromkeys(evidence_issues)),
        tuple(dict.fromkeys(quality_issues)),
    )


def _issue_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        code = value.get("code")
        message = value.get("message")
        if isinstance(code, str) and isinstance(message, str):
            return f"{code}: {message}"
        if isinstance(code, str):
            return code
    return "Unstructured workbook issue"


def _matching_report(
    run: dict[str, Any] | None, workbook: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    if run is None or not isinstance(run.get("workbooks"), list):
        return None, False
    matches = [
        report
        for report in run["workbooks"]
        if isinstance(report, dict)
        and report.get("year") == workbook["year"]
        and report.get("sheet") == workbook["sheet"]
        and report.get("workbookDigest") == workbook["contentDigest"]
    ]
    return (matches[0], False) if len(matches) == 1 else (None, len(matches) > 1)


def _stage_state_for_file(value: bool | None) -> str:
    if value is False:
        return "failed"
    return "no_evidence"


def _asset_csv_route(asset_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", asset_id.lower()).strip("-")[:100]
    suffix = hashlib.sha256(asset_id.encode()).hexdigest()[:12]
    return f"/csv/{slug}-{suffix}.csv"


def _derive_asset(
    project_root: Path,
    cohort_path: Path,
    cohort_config: dict[str, Any],
    workbook: dict[str, Any],
    evidence: EvidenceBundle,
    *,
    publication_id: str,
    publication_label: str,
    period_format: str,
) -> AssetStatus:
    source = _safe_nested_path(
        project_root, cohort_path.parent, workbook["path"], "workbook path"
    )
    source_relative = _relative(project_root, source)
    row_issues: list[str] = []
    if not source.is_file() or source.is_symlink():
        on_disk = "failed"
        row_issues.append("Source workbook is missing or not a regular file")
    else:
        data = source.read_bytes()
        if (
            len(data) != workbook["byteLength"]
            or sha256_digest(data) != workbook["contentDigest"]
        ):
            on_disk = "failed"
            row_issues.append("Source workbook digest or byte length does not match")
        else:
            on_disk = "yes"

    report, duplicate_report = _matching_report(evidence.run, workbook)
    if duplicate_report:
        row_issues.append("Run evidence repeats this workbook/sheet report")
    check_values: tuple[tuple[str, bool], ...] = ()
    if report is not None:
        raw_checks = report.get("checks")
        if isinstance(raw_checks, dict):
            check_values = tuple(
                sorted((str(name), value is True) for name, value in raw_checks.items())
            )
            for name, passed in check_values:
                if not passed:
                    row_issues.append(
                        f"Automated check failed: {CHECK_LABELS.get(name, name)}"
                    )
        else:
            row_issues.append("Workbook automated-check evidence is invalid")
        raw_issues = report.get("issues")
        if isinstance(raw_issues, list):
            row_issues.extend(_issue_text(issue) for issue in raw_issues)
        else:
            row_issues.append("Workbook issue evidence is invalid")

    run_state = evidence.file_states["run.json"]
    if run_state is False:
        tidied = "failed"
        row_issues.append("Run evidence file is invalid")
    elif report is None:
        tidied = "no_evidence"
    else:
        raw_count = report.get("rawObservationCount", report.get("observationCount"))
        checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
        tidy_ok = (
            isinstance(raw_count, int)
            and not isinstance(raw_count, bool)
            and raw_count > 0
            and checks.get("interpretation") is True
            and checks.get("deterministicReplay") is True
            and isinstance(report.get("prepareDerivationId"), str)
            and DIGEST_PATTERN.fullmatch(report["prepareDerivationId"]) is not None
            and isinstance(report.get("interpretDerivationId"), str)
            and DIGEST_PATTERN.fullmatch(report["interpretDerivationId"]) is not None
        )
        tidied = "yes" if tidy_ok else "failed"
        if not tidy_ok:
            row_issues.append("Deterministic tidy execution evidence is incomplete")

    canonical_file_state = evidence.file_states["canonical-observations.json"]
    canonical_key = (
        workbook["contentDigest"],
        workbook["sheet"],
        workbook["referenceDate"],
    )
    canonical_count = evidence.canonical_counts.get(canonical_key)
    if canonical_file_state is False:
        canonicalised = "failed"
        row_issues.append("Canonical observation evidence file is invalid")
    elif canonical_file_state is None or report is None:
        canonicalised = "no_evidence"
    else:
        expected_count = report.get("observationCount")
        canonical_ok = (
            report.get("decision") == "prototype_auto_accepted"
            and isinstance(expected_count, int)
            and not isinstance(expected_count, bool)
            and expected_count > 0
            and canonical_count == expected_count
        )
        canonicalised = "yes" if canonical_ok else "failed"
        if not canonical_ok:
            row_issues.append(
                "Accepted decision and canonical observation count do not agree"
            )

    collation_file_state = evidence.file_states["collation-report.json"]
    included: dict[str, Any] | None = None
    duplicate_inclusion = False
    if evidence.collation is not None and isinstance(
        evidence.collation.get("includedWorkbooks"), list
    ):
        inclusions = [
            item
            for item in evidence.collation["includedWorkbooks"]
            if isinstance(item, dict)
            and item.get("year") == workbook["year"]
            and item.get("workbookDigest") == workbook["contentDigest"]
        ]
        if len(inclusions) == 1:
            included = inclusions[0]
        elif len(inclusions) > 1:
            duplicate_inclusion = True
    if collation_file_state is False:
        integrated = "failed"
        row_issues.append("Collation evidence file is invalid")
    elif collation_file_state is None or report is None or included is None:
        integrated = "no_evidence"
        if duplicate_inclusion:
            integrated = "failed"
            row_issues.append("Collation repeats this workbook inclusion")
    else:
        integrated_ok = included.get("decisionId") == report.get(
            "decisionId"
        ) and included.get("rowCount") == report.get("observationCount")
        integrated = "yes" if integrated_ok else "failed"
        if not integrated_ok:
            row_issues.append("Collation inclusion does not match workbook decision")

    if any(state is False for state in evidence.file_states.values()):
        row_issues.extend(evidence.evidence_issues)
    stages = {
        "identified": "yes",
        "on_disk": on_disk,
        "tidied": tidied,
        "canonicalised": canonicalised,
        "integrated": integrated,
    }
    row_issues = list(dict.fromkeys(row_issues))
    if row_issues:
        checks_state = "issues"
    elif any(state != "yes" for state in stages.values()) or not check_values:
        checks_state = "no_evidence"
    else:
        checks_state = "pass"

    raw_count_value = report.get("rawObservationCount") if report else None
    excluded_count = report.get("excludedObservationCount") if report else None
    live = cohort_config.get("liveEvidence")
    live_path = (
        live["manifestPath"]
        if isinstance(live, dict) and workbook["year"] in live["years"]
        else None
    )
    evidence_root = Path(cohort_config["evidenceManifestPath"]).parent
    csv_declaration = evidence.file_declarations.get("canonical-observations.csv")
    asset_id = f"{cohort_config['cohortId']}:{workbook['year']}:{workbook['sheet']}"
    return AssetStatus(
        asset_id=asset_id,
        cohort_id=cohort_config["cohortId"],
        cohort_label=cohort_config["label"],
        publication_id=publication_id,
        publication_label=publication_label,
        period_format=period_format,
        dagster_asset=cohort_config["dagsterAsset"],
        year=workbook["year"],
        reference_date=workbook["referenceDate"],
        sheet=workbook["sheet"],
        source_path=source_relative,
        source_digest=workbook["contentDigest"],
        source_byte_length=workbook["byteLength"],
        stages=stages,
        checks_state=checks_state,
        checks=check_values,
        issues=tuple(row_issues),
        canonical_count=(canonical_count if isinstance(canonical_count, int) else None),
        raw_count=(raw_count_value if isinstance(raw_count_value, int) else None),
        excluded_count=(excluded_count if isinstance(excluded_count, int) else None),
        decision=(report.get("decision") if report else None),
        decision_id=(report.get("decisionId") if report else None),
        prepare_derivation_id=(report.get("prepareDerivationId") if report else None),
        interpret_derivation_id=(
            report.get("interpretDerivationId") if report else None
        ),
        replay_model=workbook["replayResponse"].get("historicalModel"),
        evidence_recorded_at=evidence.recorded_at,
        evidence_manifest_path=cohort_config["evidenceManifestPath"],
        run_path=(
            evidence.file_paths.get("run.json")
            or (evidence_root / "run.json").as_posix()
        ),
        collation_path=(
            evidence.file_paths.get("collation-report.json")
            or (evidence_root / "collation-report.json").as_posix()
        ),
        canonical_path=(
            evidence.file_paths.get("canonical-observations.json")
            or (evidence_root / "canonical-observations.json").as_posix()
        ),
        canonical_csv_path=(
            evidence.file_paths.get("canonical-observations.csv")
            or (evidence_root / "canonical-observations.csv").as_posix()
        ),
        canonical_csv_digest=(csv_declaration[0] if csv_declaration else None),
        canonical_csv_byte_length=(csv_declaration[1] if csv_declaration else None),
        csv_route=(
            _asset_csv_route(asset_id)
            if canonicalised == "yes"
            and evidence.file_states["canonical-observations.csv"] is True
            and csv_declaration is not None
            else None
        ),
        normalization=workbook.get("normalization"),
        live_evidence_path=live_path,
    )


def _build_dashboard_unlocked(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> DashboardStatus:
    root = (project_root or default_project_root()).resolve()
    registry_path = _safe_relative_path(root, registry_relative.as_posix(), "registry")
    registry = _load_json_object(registry_path, "status registry")
    _validate_registry(registry)
    _safe_relative_path(root, registry["outputPath"], "status output")
    configured_publications = registry.get("publications")
    publication_metadata = {
        item["publicationId"]: (item["label"], item["periodFormat"])
        for item in configured_publications or []
    }
    publication_order = {
        item["publicationId"]: index
        for index, item in enumerate(configured_publications or [])
    }
    observed_publications: set[str] = set()
    cohorts: list[CohortStatus] = []
    physical_workbooks: set[tuple[str, str]] = set()
    bounded_derivatives: list[tuple[tuple[str, str], str]] = []
    for cohort_config in registry["cohorts"]:
        cohort_path = _safe_relative_path(
            root, cohort_config["cohortPath"], "cohort manifest"
        )
        cohort = _load_json_object(cohort_path, "cohort manifest")
        _validate_cohort(cohort, cohort_config["cohortId"])
        publication_id = cohort.get("publicationId")
        if not isinstance(publication_id, str) or not publication_id:
            raise DataAssetStatusError("Cohort publication identity is invalid")
        if (
            configured_publications is not None
            and publication_id not in publication_metadata
        ):
            raise DataAssetStatusError(
                f"Cohort publication is not configured: {publication_id}"
            )
        if publication_id not in publication_metadata:
            inferred_label = cohort_config["label"].split("—", 1)[0].strip()
            publication_metadata[publication_id] = (
                inferred_label or publication_id,
                "calendar-year",
            )
            publication_order[publication_id] = len(publication_order)
        publication_label, period_format = publication_metadata[publication_id]
        observed_publications.add(publication_id)
        cohort_data = cohort_path.read_bytes()
        cohort_digest = sha256_digest(cohort_data)
        evidence_manifest = _safe_relative_path(
            root, cohort_config["evidenceManifestPath"], "evidence manifest"
        )
        evidence = _load_evidence(
            root,
            evidence_manifest,
            cohort_config["evidenceManifestPath"],
            cohort_config["cohortPath"],
            cohort_digest,
        )
        assets = [
            _derive_asset(
                root,
                cohort_path,
                cohort_config,
                workbook,
                evidence,
                publication_id=publication_id,
                publication_label=publication_label,
                period_format=period_format,
            )
            for workbook in cohort["workbooks"]
        ]
        for asset in assets:
            identity = (asset.source_path, asset.source_digest)
            physical_workbooks.add(identity)
            suffix = "-remaining-bounded.xlsx"
            if asset.normalization and asset.source_path.endswith(suffix):
                source_path = asset.source_path.removesuffix(suffix) + "-source.xlsx"
                bounded_derivatives.append((identity, source_path))
        assets.sort(
            key=lambda item: (
                {"issues": 0, "no_evidence": 1, "pass": 2}[item.checks_state],
                -item.year,
                item.sheet,
            )
        )
        cohort_issues = list(evidence.evidence_issues) + list(evidence.quality_issues)
        affected = sum(asset.checks_state == "issues" for asset in assets)
        if affected:
            cohort_issues.append(f"Sheet-assets with row-level issues: {affected}")
        cohort_issues = list(dict.fromkeys(cohort_issues))
        if cohort_issues:
            checks_state = "issues"
        elif any(asset.checks_state == "no_evidence" for asset in assets):
            checks_state = "no_evidence"
        else:
            checks_state = "pass"
        cohorts.append(
            CohortStatus(
                cohort_id=cohort_config["cohortId"],
                label=cohort_config["label"],
                publication_id=publication_id,
                publication_label=publication_label,
                period_format=period_format,
                dagster_asset=cohort_config["dagsterAsset"],
                assets=tuple(assets),
                checks_state=checks_state,
                issues=tuple(cohort_issues),
                evidence_recorded_at=evidence.recorded_at,
            )
        )
    if configured_publications is not None and observed_publications != set(
        publication_metadata
    ):
        raise DataAssetStatusError("Status registry contains an unused publication")
    cohorts.sort(
        key=lambda item: (
            publication_order[item.publication_id],
            {"issues": 0, "no_evidence": 1, "pass": 2}[item.checks_state],
            item.label,
        )
    )
    # A bounded derivative and its registered original are one physical workbook.
    # Keep a derivative as its own checked identity when its original is not registered.
    physical_paths = {path for path, _digest in physical_workbooks}
    for derivative, source_path in bounded_derivatives:
        if source_path in physical_paths:
            physical_workbooks.discard(derivative)
    server = registry["server"]
    return DashboardStatus(
        title=registry["title"],
        recorded_at=registry["recordedAt"],
        output_path=registry["outputPath"],
        host=server["host"],
        port=server["port"],
        tailnet_hostname=server["tailnetHostname"],
        tailnet_https_port=server["tailnetHttpsPort"],
        dagster_port=server["dagsterPort"],
        cohorts=tuple(cohorts),
        physical_workbook_count=len(physical_workbooks),
    )


def build_dashboard(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> DashboardStatus:
    root = (project_root or default_project_root()).resolve()
    with c4_shared_access(root):
        return _build_dashboard_unlocked(root, registry_relative)


def _build_asset_csv_payloads_unlocked(
    project_root: Path | None = None,
    status: DashboardStatus | None = None,
) -> dict[str, bytes]:
    root = (project_root or default_project_root()).resolve()
    dashboard = status or _build_dashboard_unlocked(root)
    grouped: dict[str, list[AssetStatus]] = {}
    routes = [asset.csv_route for asset in dashboard.assets if asset.csv_route]
    if len(routes) != len(set(routes)):
        raise DataAssetStatusError("Asset CSV routes are not unique")
    csv_paths = {
        asset.canonical_csv_path for asset in dashboard.assets if asset.csv_route
    }
    for asset in dashboard.assets:
        if asset.canonical_csv_path in csv_paths:
            grouped.setdefault(asset.canonical_csv_path, []).append(asset)

    payloads: dict[str, bytes] = {}
    for relative_path, assets in grouped.items():
        source = _safe_relative_path(root, relative_path, "canonical CSV")
        if source.is_symlink() or not source.is_file():
            raise DataAssetStatusError(
                f"Canonical CSV is missing or not a regular file: {relative_path}"
            )
        declarations = {
            (asset.canonical_csv_digest, asset.canonical_csv_byte_length)
            for asset in assets
            if asset.csv_route is not None
        }
        if len(declarations) != 1 or None in next(iter(declarations), (None, None)):
            raise DataAssetStatusError(
                f"Canonical CSV declaration is inconsistent: {relative_path}"
            )
        expected_digest, expected_length = next(iter(declarations))
        try:
            data = source.read_bytes()
            if len(data) != expected_length or sha256_digest(data) != expected_digest:
                raise DataAssetStatusError(
                    f"Canonical CSV digest or length changed: {relative_path}"
                )
            reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
            fieldnames = reader.fieldnames
            if not fieldnames or not {
                "source_workbook_digest",
                "source_sheet",
                "reference_date",
            } <= set(fieldnames):
                raise DataAssetStatusError(
                    f"Canonical CSV has invalid headers: {relative_path}"
                )
            asset_by_key = {
                (asset.source_digest, asset.sheet, asset.reference_date): asset
                for asset in assets
            }
            selected: dict[str, list[dict[str, str]]] = {
                asset.csv_route: [] for asset in assets if asset.csv_route is not None
            }
            unmatched = 0
            for row in reader:
                date = row.get("publication_vintage_date") or row.get("reference_date")
                asset = asset_by_key.get(
                    (
                        row.get("source_workbook_digest"),
                        row.get("source_sheet"),
                        date,
                    )
                )
                if asset is None:
                    unmatched += 1
                elif asset.csv_route is not None:
                    selected[asset.csv_route].append(row)
        except (OSError, UnicodeError, csv.Error) as error:
            raise DataAssetStatusError(
                f"Canonical CSV is unreadable: {relative_path}"
            ) from error
        if unmatched:
            raise DataAssetStatusError(
                f"Canonical CSV has rows that do not map to a sheet-asset: "
                f"{relative_path} ({unmatched})"
            )
        for asset in assets:
            if asset.csv_route is None:
                continue
            rows = selected[asset.csv_route]
            if asset.canonical_count is None or len(rows) != asset.canonical_count:
                raise DataAssetStatusError(
                    f"Canonical CSV row count does not match {asset.asset_id}"
                )
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            payloads[asset.csv_route] = output.getvalue().encode("utf-8")
    if set(payloads) != set(routes):
        raise DataAssetStatusError("Asset CSV route payloads are incomplete")
    return payloads


def build_asset_csv_payloads(
    project_root: Path | None = None,
    status: DashboardStatus | None = None,
) -> dict[str, bytes]:
    root = (project_root or default_project_root()).resolve()
    with c4_shared_access(root):
        return _build_asset_csv_payloads_unlocked(root, status)


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _status_markup(state: str, *, checks: bool = False) -> str:
    values = (
        {
            "pass": ("✓", "Pass", "pass"),
            "issues": ("!", "Issues", "issues"),
            "no_evidence": ("—", "No evidence", "unknown"),
        }
        if checks
        else {
            "yes": ("✓", "Yes", "pass"),
            "failed": ("✕", "Failed", "issues"),
            "no_evidence": ("—", "No evidence", "unknown"),
        }
    )
    icon, label, css = values[state]
    return (
        f'<span class="status status-{css}"><span aria-hidden="true">'
        f"{_e(icon)}</span> {_e(label)}</span>"
    )


def _detail_item(term: str, value: Any, *, code: bool = False) -> str:
    rendered = f"<code>{_e(value)}</code>" if code else _e(value)
    return f"<dt>{_e(term)}</dt><dd>{rendered}</dd>"


def _asset_details(asset: AssetStatus) -> str:
    items = [
        _detail_item("Source", asset.source_path, code=True),
        _detail_item("Workbook digest", asset.source_digest, code=True),
        _detail_item("Declared bytes", f"{asset.source_byte_length:,}"),
        _detail_item("Sheet", asset.sheet),
        _detail_item("Reference date", asset.reference_date),
        _detail_item("Evidence recorded", asset.evidence_recorded_at or "No evidence"),
        _detail_item("Evidence manifest", asset.evidence_manifest_path, code=True),
        _detail_item("Run evidence", asset.run_path, code=True),
        _detail_item("Collation evidence", asset.collation_path, code=True),
        _detail_item("Canonical JSON", asset.canonical_path, code=True),
        _detail_item("Canonical CSV", asset.canonical_csv_path, code=True),
    ]
    if asset.raw_count is not None:
        items.append(_detail_item("Raw observations", f"{asset.raw_count:,}"))
    if asset.excluded_count is not None:
        items.append(_detail_item("Explicitly excluded", f"{asset.excluded_count:,}"))
    if asset.decision:
        items.append(_detail_item("Decision", asset.decision, code=True))
    if asset.decision_id:
        items.append(_detail_item("Decision ID", asset.decision_id, code=True))
    if asset.prepare_derivation_id:
        items.append(
            _detail_item(
                "Preparation derivation", asset.prepare_derivation_id, code=True
            )
        )
    if asset.interpret_derivation_id:
        items.append(
            _detail_item(
                "Interpretation derivation", asset.interpret_derivation_id, code=True
            )
        )
    if asset.replay_model:
        items.append(
            _detail_item("Replay fixture model", asset.replay_model, code=True)
        )
    if asset.normalization:
        items.append(
            _detail_item("Source normalisation", asset.normalization, code=True)
        )
    if asset.live_evidence_path:
        items.append(
            _detail_item(
                "Original live-campaign evidence", asset.live_evidence_path, code=True
            )
        )
    checks = "".join(
        "<li>"
        + _status_markup("pass" if passed else "issues", checks=True)
        + f" {_e(CHECK_LABELS.get(name, name))}</li>"
        for name, passed in asset.checks
    )
    if not checks:
        checks = '<li><span class="muted">No workbook check evidence</span></li>'
    issues = "".join(f"<li>{_e(issue)}</li>" for issue in asset.issues)
    if not issues:
        issues = (
            '<li><span class="status status-pass">✓ No row-level issues</span></li>'
        )
    return (
        '<div class="detail-grid"><dl>'
        + "".join(items)
        + '</dl><div><h4>Automated checks</h4><ul class="check-list">'
        + checks
        + "</ul><h4>Flagged issues</h4><ul>"
        + issues
        + "</ul>"
        + f'<p><a class="dagster-link" data-dagster-asset="{_e(asset.dagster_asset)}" '
        + 'href="http://127.0.0.1:3030/assets/">Open cohort asset in Dagster</a></p>'
        + "</div></div>"
    )


def _publication_period(year: int, period_format: str) -> str:
    if period_format == "calendar-year":
        return str(year)
    return f"{year}\N{EN DASH}{(year + 1) % 100:02d}"


def _asset_rows(asset: AssetStatus) -> str:
    period = _publication_period(asset.year, asset.period_format)
    search_parts = [
        asset.publication_label,
        asset.publication_id,
        asset.cohort_label,
        str(asset.year),
        period,
        asset.reference_date,
        asset.sheet,
        asset.source_path,
        asset.source_digest,
        asset.checks_state,
        str(asset.canonical_count or ""),
        str(asset.raw_count or ""),
        str(asset.excluded_count or ""),
        asset.decision or "",
        asset.decision_id or "",
        asset.prepare_derivation_id or "",
        asset.interpret_derivation_id or "",
        asset.replay_model or "",
        asset.evidence_manifest_path,
        asset.run_path,
        asset.collation_path,
        asset.canonical_path,
        asset.canonical_csv_path,
        asset.normalization or "",
        asset.live_evidence_path or "",
        *asset.issues,
        *(CHECK_LABELS.get(name, name) for name, _passed in asset.checks),
    ]
    search = " ".join(search_parts).lower()
    sort_state = {"failed": 0, "no_evidence": 1, "yes": 2}
    sort_checks = {"issues": 0, "no_evidence": 1, "pass": 2}
    attrs = {
        "publication": asset.publication_id,
        "cohort": asset.cohort_id,
        "year": str(asset.year),
        "checks": asset.checks_state,
        "search": search,
        "stage-identified": asset.stages["identified"],
        "stage-on-disk": asset.stages["on_disk"],
        "stage-tidied": asset.stages["tidied"],
        "stage-canonicalised": asset.stages["canonicalised"],
        "stage-integrated": asset.stages["integrated"],
        "sort-asset": f"{asset.publication_label} {asset.cohort_label} {asset.year}",
        "sort-year": str(asset.year),
        "sort-identified": str(sort_state[asset.stages["identified"]]),
        "sort-on-disk": str(sort_state[asset.stages["on_disk"]]),
        "sort-tidied": str(sort_state[asset.stages["tidied"]]),
        "sort-canonicalised": str(sort_state[asset.stages["canonicalised"]]),
        "sort-integrated": str(sort_state[asset.stages["integrated"]]),
        "sort-count": str(
            asset.canonical_count if asset.canonical_count is not None else -1
        ),
        "sort-checks": str(sort_checks[asset.checks_state]),
    }
    rendered_attrs = " ".join(
        f'data-{key}="{_e(value)}"' for key, value in attrs.items()
    )
    count = f"{asset.canonical_count:,}" if asset.canonical_count is not None else "—"
    detail_id = "detail-" + hashlib.sha256(asset.asset_id.encode()).hexdigest()[:12]
    csv_link = (
        f'<a class="button csv-link" href="{_e(asset.csv_route)}" '
        'target="_blank" rel="noopener noreferrer">Open CSV</a>'
        if asset.csv_route
        else '<span class="muted">CSV unavailable</span>'
    )
    return f"""
<tbody class="asset-pair" {rendered_attrs}>
  <tr class="asset-row">
    <th scope="row"><span class="asset-name">{_e(asset.cohort_label)}</span><span class="sheet-name">{_e(asset.sheet)}</span></th>
    <td title="Source year {asset.year}">{_e(period)}</td>
    <td>{_status_markup(asset.stages["identified"])}</td>
    <td>{_status_markup(asset.stages["on_disk"])}</td>
    <td>{_status_markup(asset.stages["tidied"])}</td>
    <td>{_status_markup(asset.stages["canonicalised"])}</td>
    <td>{_status_markup(asset.stages["integrated"])}</td>
    <td class="number">{count}</td>
    <td>{_status_markup(asset.checks_state, checks=True)}</td>
    <td><div class="row-actions">{csv_link}<button class="detail-toggle" type="button" aria-expanded="false" aria-controls="{detail_id}">Evidence</button></div></td>
  </tr>
  <tr class="detail-row" id="{detail_id}" hidden><td colspan="10">{_asset_details(asset)}</td></tr>
</tbody>"""


def _cohort_section(cohort: CohortStatus) -> str:
    if cohort.checks_state == "pass":
        banner = '<p class="cohort-banner banner-pass">✓ All automated and integration checks pass.</p>'
    elif cohort.checks_state == "no_evidence":
        banner = '<p class="cohort-banner banner-unknown">— Automated check evidence is incomplete.</p>'
    else:
        issue_items = "".join(f"<li>{_e(issue)}</li>" for issue in cohort.issues)
        banner = (
            '<div class="cohort-banner banner-issues"><strong>! Automated checks flag issues.</strong>'
            f"<ul>{issue_items}</ul></div>"
        )
    rows = "".join(_asset_rows(asset) for asset in cohort.assets)
    headers = [
        ("asset", "Asset"),
        ("year", "Publication period"),
        ("identified", "Identified"),
        ("on-disk", "On disk"),
        ("tidied", "Tidied"),
        ("canonicalised", "Canonicalised"),
        ("integrated", "Integrated"),
        ("count", "Canonical rows"),
        ("checks", "Checks"),
    ]
    header_cells = "".join(
        f'<th scope="col"><button class="sort" type="button" data-sort="{key}">{_e(label)} <span aria-hidden="true">↕</span></button></th>'
        for key, label in headers
    )
    return f"""
<section class="cohort" data-cohort-section="{_e(cohort.cohort_id)}">
  <div class="cohort-heading"><div><h2>{_e(cohort.label)}</h2><p>{len(cohort.assets)} sheet-assets · Evidence recorded {_e(cohort.evidence_recorded_at or "not available")}</p></div>{banner}</div>
  <div class="table-wrap"><table><thead><tr>{header_cells}<th scope="col">Open</th></tr></thead>{rows}</table></div>
  <p class="empty-cohort" hidden>No assets in this cohort match the current filters.</p>
</section>"""


def _publication_asset_section(publication: PublicationStatus) -> str:
    assets = sum(len(cohort.assets) for cohort in publication.cohorts)
    sections = "".join(_cohort_section(cohort) for cohort in publication.cohorts)
    heading_id = (
        "assets-publication-"
        + hashlib.sha256(publication.publication_id.encode()).hexdigest()[:12]
    )
    return f"""
<section class="assets-publication publication-group" data-publication-section="{_e(publication.publication_id)}" aria-labelledby="{heading_id}">
  <div class="publication-heading"><div><p class="eyebrow">Publication</p><h2 id="{heading_id}">{_e(publication.label)}</h2></div><p>{len(publication.cohorts)} cohorts · {assets} sheet-assets</p></div>
{sections}
</section>"""


def _coverage_state(asset: AssetStatus) -> tuple[str, str, str]:
    if asset.checks_state == "issues" or any(
        state == "failed" for state in asset.stages.values()
    ):
        return "issues", "!", "Issues"
    if (
        all(state == "yes" for state in asset.stages.values())
        and asset.checks_state == "pass"
    ):
        return "complete", "✓", "Integrated; checks pass"
    for stage, symbol, label in (
        ("integrated", "G", "Integrated; checks incomplete"),
        ("canonicalised", "C", "Canonicalised"),
        ("tidied", "T", "Tidied"),
        ("on_disk", "D", "On disk"),
        ("identified", "I", "Identified"),
    ):
        if asset.stages[stage] == "yes":
            return stage.replace("_", "-"), symbol, label
    return "no-evidence", "?", "No evidence"


def _coverage_label(label: str) -> str:
    return label.rsplit("—", 1)[-1].strip()


def _coverage_stage_summary(status: DashboardStatus) -> str:
    assets = status.assets
    total = len(assets)
    stages = [
        ("Identified", sum(asset.stages["identified"] == "yes" for asset in assets)),
        ("On disk", sum(asset.stages["on_disk"] == "yes" for asset in assets)),
        ("Tidied", sum(asset.stages["tidied"] == "yes" for asset in assets)),
        (
            "Canonicalised",
            sum(asset.stages["canonicalised"] == "yes" for asset in assets),
        ),
        ("Integrated", sum(asset.stages["integrated"] == "yes" for asset in assets)),
        ("Checks pass", sum(asset.checks_state == "pass" for asset in assets)),
    ]
    return "".join(
        f'<div class="coverage-meter"><span>{_e(label)}</span>'
        f'<strong>{count}/{total}</strong><i aria-hidden="true"><b '
        f'style="width:{(count / total * 100) if total else 0:.1f}%"></b></i></div>'
        for label, count in stages
    )


def _coverage_group_state(
    assets: list[AssetStatus],
) -> tuple[str, str, str]:
    ranked = {
        "issues": 0,
        "no-evidence": 1,
        "identified": 2,
        "on-disk": 3,
        "tidied": 4,
        "canonicalised": 5,
        "integrated": 6,
        "complete": 7,
    }
    states = [_coverage_state(asset) for asset in assets]
    least_complete = min(states, key=lambda item: ranked[item[0]])
    if len({item[0] for item in states}) > 1:
        return (
            least_complete[0],
            least_complete[1],
            f"Mixed states; least complete: {least_complete[2]}",
        )
    return least_complete


def _coverage_matrix(publication: PublicationStatus) -> str:
    years = sorted(
        {asset.year for cohort in publication.cohorts for asset in cohort.assets}
    )
    year_headers = "".join(
        f'<th scope="col">{_e(_publication_period(year, publication.period_format))}</th>'
        for year in years
    )
    rows = []
    for cohort in publication.cohorts:
        by_year: dict[int, list[AssetStatus]] = {}
        for asset in cohort.assets:
            by_year.setdefault(asset.year, []).append(asset)
        cells = []
        for year in years:
            period = _publication_period(year, publication.period_format)
            year_assets = by_year.get(year, [])
            if not year_assets:
                cells.append(
                    f'<td><span class="coverage-cell coverage-absent" '
                    f'aria-label="{_e(cohort.label)}, {_e(period)}: not registered" '
                    f'title="Not registered in this prototype scope">·</span></td>'
                )
                continue
            state, symbol, label = _coverage_group_state(year_assets)
            counts = [asset.canonical_count for asset in year_assets]
            count = (
                f"{sum(counts):,} canonical rows"
                if all(value is not None for value in counts)
                else "canonical row count incomplete"
            )
            if len(year_assets) == 1:
                asset = year_assets[0]
                next_step = (
                    "Select to view the asset and open its CSV."
                    if asset.csv_route
                    else "Select to view the asset; CSV is unavailable."
                )
                description = (
                    f"{cohort.label}, {period}, {asset.sheet}: {label}; {count}. "
                    f"{next_step}"
                )
                content = _e(symbol)
                multiple_class = ""
            else:
                description = (
                    f"{cohort.label}, {period}: {len(year_assets)} registered assets; "
                    f"{label}; {count}. Select to view all {len(year_assets)} assets."
                )
                content = f"{_e(symbol)}<small>{len(year_assets)}</small>"
                multiple_class = " coverage-multiple"
            cells.append(
                f'<td><button class="coverage-cell coverage-{state}{multiple_class}" type="button" '
                f'data-target-cohort="{_e(cohort.cohort_id)}" '
                f'data-target-year="{year}" aria-label="{_e(description)}" '
                f'title="{_e(description)}">{content}</button></td>'
            )
        compact_label = _coverage_label(cohort.label)
        search = f"{publication.label} {cohort.label}".lower()
        rows.append(
            f'<tr class="coverage-row" data-coverage-search="{_e(search)}">'
            f'<th scope="row" title="{_e(cohort.label)}">{_e(compact_label)}</th>'
            + "".join(cells)
            + "</tr>"
        )
    heading_id = (
        "coverage-publication-"
        + hashlib.sha256(publication.publication_id.encode()).hexdigest()[:12]
    )
    asset_count = sum(len(cohort.assets) for cohort in publication.cohorts)
    return f"""
<section class="coverage-publication publication-group" data-publication-section="{_e(publication.publication_id)}" aria-labelledby="{heading_id}">
<div class="publication-heading"><div><p class="eyebrow">Publication</p><h3 id="{heading_id}">{_e(publication.label)}</h3></div><p>{len(publication.cohorts)} cohorts · {asset_count} sheet-assets</p></div>
<div class="coverage-scroll">
<table class="coverage-grid" aria-label="{_e(publication.label)} registered sheet-asset coverage by cohort and publication period">
<thead><tr><th scope="col">Cohort</th>{year_headers}</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>
</section>"""


def render_dashboard(status: DashboardStatus) -> bytes:
    assets = status.assets
    issue_count = sum(asset.checks_state == "issues" for asset in assets)
    integrated_count = sum(asset.stages["integrated"] == "yes" for asset in assets)
    years = sorted({asset.year for asset in assets})
    coverage_summary = _coverage_stage_summary(status)
    coverage_matrix = "".join(
        _coverage_matrix(publication) for publication in status.publications
    )
    publication_options = "".join(
        f'<option value="{_e(publication.publication_id)}">{_e(publication.label)}</option>'
        for publication in status.publications
    )
    cohort_options = "".join(
        f'<optgroup label="{_e(publication.label)}">'
        + "".join(
            f'<option value="{_e(cohort.cohort_id)}">{_e(_coverage_label(cohort.label))}</option>'
            for cohort in publication.cohorts
        )
        + "</optgroup>"
        for publication in status.publications
    )
    year_labels = {
        year: sorted(
            {
                _publication_period(year, asset.period_format)
                for asset in assets
                if asset.year == year
            }
        )
        for year in years
    }
    year_options = "".join(
        f'<option value="{year}">{_e(" / ".join(year_labels[year]))}</option>'
        for year in years
    )
    sections = "".join(
        _publication_asset_section(publication) for publication in status.publications
    )
    summary = (
        f"{len(status.publications)} publications · {len(status.cohorts)} cohorts · "
        f"{len(assets)} sheet-assets across "
        f"{status.physical_workbook_count} physical workbooks · {integrated_count} "
        f"integrated · {issue_count} with issues · Snapshot recorded "
        f"{status.recorded_at}"
    )
    document = f"""<!doctype html>
<html lang="en" data-tailnet-host="{_e(status.tailnet_hostname)}" data-dagster-port="{status.dagster_port}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
<title>{_e(status.title)}</title>
<style>
:root {{ color-scheme: light; --ink:#17202a; --muted:#5f6b76; --line:#d9e0e7; --panel:#f7f9fb; --pass:#17663a; --pass-bg:#eaf7ef; --issue:#9b2c2c; --issue-bg:#fff0f0; --unknown:#615b52; --unknown-bg:#f3f1ed; --accent:#165d9c; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; color:var(--ink); background:#fff; font:15px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ max-width:1500px; margin:0 auto; padding:28px 24px 60px; }}
h1 {{ margin:0; font-size:clamp(1.7rem,4vw,2.35rem); letter-spacing:-.025em; }}
h2 {{ margin:0; font-size:1.15rem; }}
h3 {{ margin:0; font-size:1.05rem; }}
h4 {{ margin:1rem 0 .35rem; }}
p {{ margin:.35rem 0; }}
a {{ color:var(--accent); }}
header {{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:18px; }}
.subtitle,.summary,.cohort-heading p,.muted {{ color:var(--muted); }}
.summary {{ font-size:.93rem; margin-bottom:14px; }}
.tabs {{ display:flex; gap:4px; margin-bottom:14px; border-bottom:1px solid var(--line); }}
.tab {{ min-height:38px; margin-bottom:-1px; border:0; border-bottom:3px solid transparent; border-radius:0; padding:7px 14px; background:transparent; font-weight:700; color:var(--muted); }}
.tab[aria-selected="true"] {{ border-bottom-color:var(--accent); color:var(--accent); }}
.tab-panel[hidden] {{ display:none; }}
.coverage-toolbar {{ display:flex; align-items:end; justify-content:space-between; gap:14px; margin-bottom:10px; }}
.coverage-toolbar h2 {{ margin-bottom:2px; }}
.coverage-search {{ width:min(280px,40vw); }}
.stage-summary {{ display:grid; grid-template-columns:repeat(6,minmax(105px,1fr)); gap:6px; margin-bottom:10px; }}
.coverage-meter {{ display:grid; grid-template-columns:1fr auto; gap:1px 8px; padding:6px 8px; border:1px solid var(--line); border-radius:5px; background:var(--panel); font-size:.72rem; }}
.coverage-meter span {{ color:var(--muted); white-space:nowrap; }}
.coverage-meter strong {{ font-variant-numeric:tabular-nums; }}
.coverage-meter i {{ grid-column:1/-1; height:3px; overflow:hidden; border-radius:2px; background:#dfe5ea; }}
.coverage-meter b {{ display:block; height:100%; background:var(--pass); }}
.publication-group[hidden] {{ display:none; }}
.publication-heading {{ display:flex; align-items:end; justify-content:space-between; gap:18px; padding:8px 10px; border-bottom:1px solid var(--line); background:#f8fafb; }}
.publication-heading p {{ color:var(--muted); font-size:.78rem; }}
.publication-heading .eyebrow {{ margin:0; color:var(--accent); font-size:.65rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
.coverage-publication {{ margin:0 0 14px; border:1px solid var(--line); border-radius:7px; overflow:hidden; }}
.coverage-scroll {{ max-height:min(54vh,620px); overflow:auto; }}
.coverage-grid {{ width:max-content; min-width:100%; border-collapse:separate; border-spacing:0; font-size:.76rem; }}
.coverage-grid th,.coverage-grid td {{ height:31px; padding:2px 4px; border:0; border-right:1px solid #edf0f2; border-bottom:1px solid #edf0f2; text-align:center; }}
.coverage-grid thead th {{ position:sticky; top:0; z-index:3; padding:5px 7px; background:#f3f6f8; }}
.coverage-grid th:first-child {{ position:sticky; left:0; z-index:2; width:245px; max-width:245px; overflow:hidden; text-align:left; text-overflow:ellipsis; background:#fff; white-space:nowrap; }}
.coverage-grid thead th:first-child {{ z-index:4; background:#f3f6f8; }}
.coverage-cell {{ display:inline-flex; width:34px; min-height:25px; align-items:center; justify-content:center; border:1px solid transparent; border-radius:4px; padding:0; font-size:.75rem; font-weight:800; line-height:1; }}
.coverage-multiple {{ gap:2px; width:39px; }}
.coverage-multiple small {{ font-size:.58rem; font-weight:800; }}
button.coverage-cell:hover,button.coverage-cell:focus-visible {{ outline:2px solid var(--accent); outline-offset:1px; }}
.coverage-complete {{ color:#fff; background:#237a46; }}
.coverage-issues {{ color:#fff; background:#b33a3a; }}
.coverage-integrated {{ color:#174d2d; background:#a9dbb9; }}
.coverage-canonicalised {{ color:#123f68; background:#acd2ee; }}
.coverage-tidied {{ color:#3c356b; background:#c9c0ed; }}
.coverage-on-disk {{ color:#65460c; background:#efd18f; }}
.coverage-identified {{ color:#4f5358; background:#dfe4e8; }}
.coverage-no-evidence {{ color:#625b50; background:#eeeae3; }}
.coverage-absent {{ color:#858b91; background:#fff; border-color:#dfe3e6; }}
.coverage-legend {{ display:flex; flex-wrap:wrap; gap:5px 12px; margin:9px 0 4px; color:var(--muted); font-size:.75rem; }}
.coverage-legend span {{ display:inline-flex; align-items:center; gap:4px; }}
.coverage-legend i {{ width:11px; height:11px; border-radius:3px; }}
.coverage-scope {{ margin-top:6px; color:var(--muted); font-size:.76rem; }}
.controls {{ display:grid; grid-template-columns:minmax(180px,2fr) repeat(5,minmax(130px,1fr)) auto; gap:10px; align-items:end; padding:14px; margin-bottom:20px; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
label {{ display:grid; gap:4px; color:var(--muted); font-size:.8rem; font-weight:650; }}
input,select,button {{ font:inherit; }}
input,select {{ width:100%; min-height:38px; border:1px solid #aeb8c2; border-radius:5px; background:#fff; padding:7px 9px; color:var(--ink); }}
button,.button {{ min-height:36px; border:1px solid #9da9b5; border-radius:5px; padding:6px 10px; background:#fff; color:var(--ink); cursor:pointer; text-decoration:none; }}
button:hover,.button:hover {{ border-color:var(--accent); color:var(--accent); }}
.assets-publication {{ margin:24px 0 40px; border-top:3px solid var(--accent); }}
.assets-publication > .publication-heading {{ margin-bottom:14px; }}
.cohort {{ margin:18px 0 30px; padding:0 8px; }}
.cohort-heading {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-start; margin-bottom:10px; }}
.cohort-banner {{ max-width:620px; margin:0; padding:7px 10px; border-radius:5px; font-size:.9rem; }}
.cohort-banner ul {{ margin:.4rem 0 0 1rem; padding:0; }}
.banner-pass {{ color:var(--pass); background:var(--pass-bg); }}
.banner-issues {{ color:var(--issue); background:var(--issue-bg); }}
.banner-unknown {{ color:var(--unknown); background:var(--unknown-bg); }}
.table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:7px; }}
table {{ width:100%; min-width:1240px; border-collapse:collapse; }}
th,td {{ padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; white-space:nowrap; }}
thead th {{ color:#44515e; background:#f3f6f8; font-size:.78rem; text-transform:uppercase; letter-spacing:.035em; }}
thead .sort {{ min-height:auto; border:0; padding:0; color:inherit; background:transparent; font-size:inherit; text-transform:inherit; letter-spacing:inherit; font-weight:700; }}
tbody:last-child tr:last-child > * {{ border-bottom:0; }}
.asset-name,.sheet-name {{ display:block; }}
.asset-name {{ font-weight:650; }}
.sheet-name {{ color:var(--muted); font-size:.82rem; }}
.number {{ text-align:right; font-variant-numeric:tabular-nums; }}
.row-actions {{ display:flex; align-items:center; gap:7px; }}
.row-actions .button {{ display:inline-flex; align-items:center; }}
.status {{ display:inline-flex; align-items:center; gap:3px; border-radius:999px; padding:2px 7px; font-size:.82rem; font-weight:650; }}
.status-pass {{ color:var(--pass); background:var(--pass-bg); }}
.status-issues {{ color:var(--issue); background:var(--issue-bg); }}
.status-unknown {{ color:var(--unknown); background:var(--unknown-bg); }}
.detail-row td {{ padding:16px; white-space:normal; background:#fbfcfd; }}
.detail-grid {{ display:grid; grid-template-columns:minmax(340px,1fr) minmax(280px,1fr); gap:30px; }}
dl {{ display:grid; grid-template-columns:max-content minmax(0,1fr); gap:6px 14px; margin:0; }}
dt {{ color:var(--muted); font-weight:650; }}
dd {{ margin:0; overflow-wrap:anywhere; }}
code {{ font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace; overflow-wrap:anywhere; }}
ul {{ padding-left:1.3rem; }}
.check-list {{ list-style:none; padding:0; }}
.check-list li {{ margin:4px 0; }}
.empty-cohort,.no-results {{ color:var(--muted); padding:14px; }}
footer {{ margin-top:40px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); font-size:.88rem; }}
footer dl {{ margin-top:10px; }}
@media (max-width:980px) {{ .stage-summary {{ grid-template-columns:repeat(3,1fr); }} .controls {{ grid-template-columns:1fr 1fr; }} header,.cohort-heading {{ display:block; }} .cohort-banner {{ margin-top:9px; }} .detail-grid {{ grid-template-columns:1fr; }} }}
@media (max-width:600px) {{ main {{ padding:20px 12px 40px; }} .coverage-toolbar {{ display:block; }} .coverage-search {{ width:100%; margin-top:8px; }} .stage-summary {{ grid-template-columns:repeat(2,1fr); }} .coverage-grid th:first-child {{ width:180px; max-width:180px; }} .controls {{ grid-template-columns:1fr; }} dl {{ grid-template-columns:1fr; gap:2px; }} dd {{ margin-bottom:8px; }} }}
</style>
</head>
<body>
<main>
<header><div><h1>{_e(status.title)}</h1><p class="subtitle">Read-only projection from checked manifests. Open any asset's tidied CSV directly; this page does not edit or approve data.</p></div><a class="button dagster-link" data-dagster-root href="http://127.0.0.1:{status.dagster_port}/assets">Open Dagster</a></header>
<p class="summary" id="summary">{_e(summary)}</p>
<div class="tabs" role="tablist" aria-label="Data asset views">
<button class="tab" id="coverage-tab" type="button" role="tab" aria-selected="true" aria-controls="coverage-panel" data-tab="coverage">Coverage</button>
<button class="tab" id="assets-tab" type="button" role="tab" aria-selected="false" aria-controls="assets-panel" data-tab="assets" tabindex="-1">Assets</button>
</div>
<section class="tab-panel" id="coverage-panel" role="tabpanel" aria-labelledby="coverage-tab">
<div class="coverage-toolbar"><div><h2>Registered asset coverage</h2><p class="muted">Compact publication-grouped cohort-by-period view. Select a cell to inspect that asset.</p></div><label class="coverage-search">Find publication or cohort<input id="coverage-search" type="search" placeholder="Publication, table, topic…"></label></div>
<div class="stage-summary" aria-label="Pipeline stage coverage">{coverage_summary}</div>
{coverage_matrix}
<div class="coverage-legend" aria-label="Coverage state legend">
<span><i class="coverage-complete"></i>Integrated + pass</span><span><i class="coverage-issues"></i>Issues</span><span><i class="coverage-integrated"></i>Integrated</span><span><i class="coverage-canonicalised"></i>Canonicalised</span><span><i class="coverage-tidied"></i>Tidied</span><span><i class="coverage-on-disk"></i>On disk</span><span><i class="coverage-identified"></i>Identified</span><span><i class="coverage-no-evidence"></i>No evidence</span><span><i class="coverage-absent"></i>Not registered</span>
</div>
<p class="coverage-scope"><strong>Scope:</strong> this shows the explicit prototype registry, not completeness of the full spreadsheet estate. Missing cells mean “not registered here”, not “source data does not exist”. <span id="coverage-visible-count">Showing {len(status.cohorts)} of {len(status.cohorts)} cohorts.</span></p>
</section>
<section class="tab-panel" id="assets-panel" role="tabpanel" aria-labelledby="assets-tab" hidden>
<div class="controls" role="search" aria-label="Filter data assets">
<label>Search<input id="search" type="search" placeholder="Publication, asset, sheet, check…"></label>
<label>Publication<select id="publication-filter"><option value="">All publications</option>{publication_options}</select></label>
<label>Cohort<select id="cohort-filter"><option value="">All cohorts</option>{cohort_options}</select></label>
<label>Publication period<select id="year-filter"><option value="">All periods</option>{year_options}</select></label>
<label>Checks<select id="checks-filter"><option value="">All check states</option><option value="pass">Pass</option><option value="issues">Issues</option><option value="no_evidence">No evidence</option></select></label>
<label>Incomplete stage<select id="stage-filter"><option value="">Any stage</option><option value="identified">Identified</option><option value="on-disk">On disk</option><option value="tidied">Tidied</option><option value="canonicalised">Canonicalised</option><option value="integrated">Integrated</option></select></label>
<button id="reset" type="button">Reset</button>
</div>
<p id="visible-count" class="muted" aria-live="polite">Showing {len(assets)} of {len(assets)} assets.</p>
{sections}
<p class="no-results" id="no-results" hidden>No assets match the current filters.</p>
</section>
<footer>
<strong>Status definitions</strong>
<dl>
{_detail_item("Identified", "Selected sheet appears in the configured cohort manifest.")}
{_detail_item("On disk", "Source exists and its byte length and SHA-256 match.")}
{_detail_item("Tidied", "Deterministic preparation, interpretation, and execution evidence exists.")}
{_detail_item("Canonicalised", "Automatic acceptance emitted the expected canonical observations.")}
{_detail_item("Integrated", "The workbook/sheet decision appears in checked collation evidence.")}
{_detail_item("Checks", "Pass, Issues, or No evidence; cohort-wide issues appear above their rows.")}
</dl>
<p>{len(assets)} sheet-assets may share {status.physical_workbook_count} physical workbooks. Source normalisation is shown only in evidence details where explicitly recorded. Historical downstream evidence remains visible if current on-disk custody later fails.</p>
<p>Local: <code>http://{_e(status.host)}:{status.port}/</code> · Tailnet: <code>https://{_e(status.tailnet_hostname)}:{status.tailnet_https_port}/</code></p>
</footer>
</main>
<script>
(() => {{
  "use strict";
  const allPairs = Array.from(document.querySelectorAll("tbody.asset-pair"));
  const controls = {{
    search: document.getElementById("search"),
    publication: document.getElementById("publication-filter"),
    cohort: document.getElementById("cohort-filter"),
    year: document.getElementById("year-filter"),
    checks: document.getElementById("checks-filter"),
    stage: document.getElementById("stage-filter")
  }};
  const dataKey = (value) => value.replace(/-([a-z])/g, (_, char) => char.toUpperCase());
  const tabButtons = Array.from(document.querySelectorAll("button.tab"));
  const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));
  function activateTab(name, focus = false) {{
    for (const button of tabButtons) {{
      const selected = button.dataset.tab === name;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (selected && focus) button.focus();
    }}
    for (const panel of tabPanels) panel.hidden = panel.id !== `${{name}}-panel`;
  }}
  tabButtons.forEach((button, index) => {{
    button.addEventListener("click", () => activateTab(button.dataset.tab, true));
    button.addEventListener("keydown", (event) => {{
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      const target = tabButtons[(index + offset + tabButtons.length) % tabButtons.length];
      activateTab(target.dataset.tab, true);
    }});
  }});
  const coverageRows = Array.from(document.querySelectorAll("tr.coverage-row"));
  const coverageSearch = document.getElementById("coverage-search");
  function applyCoverageFilter() {{
    const query = coverageSearch.value.trim().toLowerCase();
    let shown = 0;
    for (const row of coverageRows) {{
      row.hidden = Boolean(query) && !row.dataset.coverageSearch.includes(query);
      if (!row.hidden) shown += 1;
    }}
    for (const publication of document.querySelectorAll("section.coverage-publication")) {{
      publication.hidden = !Array.from(publication.querySelectorAll("tr.coverage-row")).some((row) => !row.hidden);
    }}
    document.getElementById("coverage-visible-count").textContent = `Showing ${{shown}} of ${{coverageRows.length}} cohorts.`;
  }}
  coverageSearch.addEventListener("input", applyCoverageFilter);
  function applyFilters() {{
    const query = controls.search.value.trim().toLowerCase();
    let shown = 0;
    for (const pair of allPairs) {{
      const stage = controls.stage.value;
      const visible = (!query || pair.dataset.search.includes(query))
        && (!controls.publication.value || pair.dataset.publication === controls.publication.value)
        && (!controls.cohort.value || pair.dataset.cohort === controls.cohort.value)
        && (!controls.year.value || pair.dataset.year === controls.year.value)
        && (!controls.checks.value || pair.dataset.checks === controls.checks.value)
        && (!stage || pair.dataset[dataKey(`stage-${{stage}}`)] !== "yes");
      pair.hidden = !visible;
      if (visible) shown += 1;
    }}
    for (const section of document.querySelectorAll("section.cohort")) {{
      const visible = Array.from(section.querySelectorAll("tbody.asset-pair")).some((pair) => !pair.hidden);
      section.hidden = !visible;
      section.querySelector(".empty-cohort").hidden = visible;
    }}
    for (const publication of document.querySelectorAll("section.assets-publication")) {{
      publication.hidden = !Array.from(publication.querySelectorAll("section.cohort")).some((section) => !section.hidden);
    }}
    document.getElementById("visible-count").textContent = `Showing ${{shown}} of ${{allPairs.length}} assets.`;
    document.getElementById("no-results").hidden = shown !== 0;
  }}
  Object.values(controls).forEach((control) => control.addEventListener("input", applyFilters));
  document.getElementById("reset").addEventListener("click", () => {{
    Object.values(controls).forEach((control) => {{ control.value = ""; }});
    applyFilters();
  }});
  document.querySelectorAll("button.coverage-cell").forEach((button) => {{
    button.addEventListener("click", () => {{
      Object.values(controls).forEach((control) => {{ control.value = ""; }});
      controls.cohort.value = button.dataset.targetCohort;
      controls.year.value = button.dataset.targetYear;
      applyFilters();
      activateTab("assets", true);
      document.getElementById("assets-panel").scrollIntoView({{ block: "start" }});
    }});
  }});
  document.querySelectorAll("button.detail-toggle").forEach((button) => {{
    button.addEventListener("click", () => {{
      const detail = document.getElementById(button.getAttribute("aria-controls"));
      const expanded = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", String(!expanded));
      button.textContent = expanded ? "Evidence" : "Hide";
      detail.hidden = expanded;
    }});
  }});
  document.querySelectorAll("button.sort").forEach((button) => {{
    button.addEventListener("click", () => {{
      const table = button.closest("table");
      const key = dataKey(`sort-${{button.dataset.sort}}`);
      const direction = button.dataset.direction === "asc" ? "desc" : "asc";
      table.querySelectorAll("button.sort").forEach((item) => delete item.dataset.direction);
      button.dataset.direction = direction;
      const pairs = Array.from(table.querySelectorAll("tbody.asset-pair"));
      pairs.sort((left, right) => {{
        const a = left.dataset[key] || "";
        const b = right.dataset[key] || "";
        const numeric = [a, b].every((value) => /^-?\\d+$/.test(value));
        const compared = numeric ? Number(a) - Number(b) : a.localeCompare(b);
        return direction === "asc" ? compared : -compared;
      }}).forEach((pair) => table.appendChild(pair));
    }});
  }});
  const root = document.documentElement;
  const tailnet = root.dataset.tailnetHost;
  const dagsterPort = root.dataset.dagsterPort;
  const remote = location.hostname === tailnet;
  const dagsterBase = remote ? `https://${{tailnet}}:${{dagsterPort}}` : `http://127.0.0.1:${{dagsterPort}}`;
  document.querySelectorAll("a.dagster-link").forEach((link) => {{
    const asset = link.dataset.dagsterAsset;
    link.href = asset ? `${{dagsterBase}}/assets/${{encodeURIComponent(asset)}}` : `${{dagsterBase}}/assets`;
    link.referrerPolicy = "no-referrer";
  }});
  applyCoverageFilter();
  applyFilters();
  activateTab("coverage", false);
}})();
</script>
</body>
</html>
"""
    return document.encode()


def _expected_snapshot_unlocked(
    project_root: Path,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> tuple[DashboardStatus, bytes]:
    status = _build_dashboard_unlocked(project_root, registry_relative)
    return status, render_dashboard(status)


def expected_snapshot(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> tuple[DashboardStatus, bytes]:
    root = (project_root or default_project_root()).resolve()
    with c4_shared_access(root):
        return _expected_snapshot_unlocked(root, registry_relative)


def refresh_snapshot(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> tuple[DashboardStatus, Path, bool]:
    root = (project_root or default_project_root()).resolve()
    with c4_shared_access(root):
        status, rendered = _expected_snapshot_unlocked(root, registry_relative)
        output = _safe_relative_path(root, status.output_path, "status output")
        output.parent.mkdir(parents=True, exist_ok=True)
        changed = not output.is_file() or output.read_bytes() != rendered
        if changed:
            temporary = output.with_name(f".{output.name}.tmp")
            temporary.write_bytes(rendered)
            temporary.chmod(0o644)
            temporary.replace(output)
        return status, output, changed


def snapshot_matches(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> tuple[bool, Path, str, str | None]:
    root = (project_root or default_project_root()).resolve()
    with c4_shared_access(root):
        status, rendered = _expected_snapshot_unlocked(root, registry_relative)
        output = _safe_relative_path(root, status.output_path, "status output")
        expected = sha256_digest(rendered)
        if not output.is_file():
            return False, output, expected, None
        actual_data = output.read_bytes()
        return actual_data == rendered, output, expected, sha256_digest(actual_data)


class StatusPageServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def status_handler(
    page: Path | bytes,
    csv_payloads: dict[str, bytes] | None = None,
) -> type[BaseHTTPRequestHandler]:
    try:
        page_body = page if isinstance(page, bytes) else page.read_bytes()
    except OSError as error:
        raise DataAssetStatusError("Status HTML snapshot is unreadable") from error
    payloads = dict(csv_payloads or {})
    if any(
        re.fullmatch(r"/csv/[a-z0-9-]+\.csv", route) is None
        or not isinstance(body, bytes)
        for route, body in payloads.items()
    ):
        raise DataAssetStatusError("Status CSV route mapping is invalid")

    class Handler(BaseHTTPRequestHandler):
        server_version = "TidyDataAssetStatus/1"

        def do_GET(self) -> None:
            self._respond(head=False)

        def do_HEAD(self) -> None:
            self._respond(head=True)

        def do_POST(self) -> None:
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

        def _respond(self, *, head: bool) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._send(
                    HTTPStatus.OK, b'{"status":"ok"}\n', "application/json", head
                )
                return
            csv_body = payloads.get(path)
            if csv_body is not None:
                self._send(
                    HTTPStatus.OK,
                    csv_body,
                    "text/plain; charset=utf-8",
                    head,
                    content_disposition=(
                        f'inline; filename="{PurePosixPath(path).name}"'
                    ),
                )
                return
            if path not in {"/", "/index.html"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send(HTTPStatus.OK, page_body, "text/html; charset=utf-8", head)

        def _send(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            head: bool,
            *,
            content_disposition: str | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if content_disposition:
                self.send_header("Content-Disposition", content_disposition)
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            super().log_message(format, *args)

    return Handler


def make_status_server(
    host: str,
    port: int,
    page: Path | bytes,
    csv_payloads: dict[str, bytes] | None = None,
) -> StatusPageServer:
    if host != "127.0.0.1":
        raise DataAssetStatusError("Status server must bind exactly to 127.0.0.1")
    return StatusPageServer((host, port), status_handler(page, csv_payloads))
