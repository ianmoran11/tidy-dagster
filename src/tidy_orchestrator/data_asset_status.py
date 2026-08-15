# ruff: noqa: E501
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any

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
    normalization: str | None
    live_evidence_path: str | None


@dataclass(frozen=True)
class CohortStatus:
    cohort_id: str
    label: str
    dagster_asset: str
    assets: tuple[AssetStatus, ...]
    checks_state: str
    issues: tuple[str, ...]
    evidence_recorded_at: str | None


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


@dataclass(frozen=True)
class EvidenceBundle:
    recorded_at: str | None
    run: dict[str, Any] | None
    collation: dict[str, Any] | None
    canonical_counts: dict[tuple[str, str, str], int]
    file_states: dict[str, bool | None]
    file_paths: dict[str, str]
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
    if set(value) != required or value.get("schemaVersion") != REGISTRY_SCHEMA:
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
    for workbook in workbooks:
        if (
            not isinstance(workbook, dict)
            or not required_workbook <= set(workbook)
            or set(workbook) - required_workbook - {"normalization"}
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
        "canonical-observations.json",
        "collation-report.json",
        "run.json",
    }
    file_states: dict[str, bool | None] = {name: None for name in required_files}
    file_paths = {
        name: f"{manifest_path.parent.relative_to(project_root).as_posix()}/{name}"
        for name in required_files
    }
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
                key = (
                    row["source_workbook_digest"],
                    row["source_sheet"],
                    row["reference_date"],
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


def _derive_asset(
    project_root: Path,
    cohort_path: Path,
    cohort_config: dict[str, Any],
    workbook: dict[str, Any],
    evidence: EvidenceBundle,
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
    asset_id = f"{cohort_config['cohortId']}:{workbook['year']}:{workbook['sheet']}"
    return AssetStatus(
        asset_id=asset_id,
        cohort_id=cohort_config["cohortId"],
        cohort_label=cohort_config["label"],
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
        normalization=workbook.get("normalization"),
        live_evidence_path=live_path,
    )


def build_dashboard(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> DashboardStatus:
    root = (project_root or default_project_root()).resolve()
    registry_path = _safe_relative_path(root, registry_relative.as_posix(), "registry")
    registry = _load_json_object(registry_path, "status registry")
    _validate_registry(registry)
    _safe_relative_path(root, registry["outputPath"], "status output")
    cohorts: list[CohortStatus] = []
    physical_workbooks: set[tuple[str, str]] = set()
    for cohort_config in registry["cohorts"]:
        cohort_path = _safe_relative_path(
            root, cohort_config["cohortPath"], "cohort manifest"
        )
        cohort = _load_json_object(cohort_path, "cohort manifest")
        _validate_cohort(cohort, cohort_config["cohortId"])
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
            _derive_asset(root, cohort_path, cohort_config, workbook, evidence)
            for workbook in cohort["workbooks"]
        ]
        for asset in assets:
            physical_workbooks.add((asset.source_path, asset.source_digest))
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
                dagster_asset=cohort_config["dagsterAsset"],
                assets=tuple(assets),
                checks_state=checks_state,
                issues=tuple(cohort_issues),
                evidence_recorded_at=evidence.recorded_at,
            )
        )
    cohorts.sort(
        key=lambda item: (
            {"issues": 0, "no_evidence": 1, "pass": 2}[item.checks_state],
            item.label,
        )
    )
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
        _detail_item("Canonical output", asset.canonical_path, code=True),
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


def _asset_rows(asset: AssetStatus) -> str:
    search_parts = [
        asset.cohort_label,
        str(asset.year),
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
        asset.normalization or "",
        asset.live_evidence_path or "",
        *asset.issues,
        *(CHECK_LABELS.get(name, name) for name, _passed in asset.checks),
    ]
    search = " ".join(search_parts).lower()
    sort_state = {"failed": 0, "no_evidence": 1, "yes": 2}
    sort_checks = {"issues": 0, "no_evidence": 1, "pass": 2}
    attrs = {
        "cohort": asset.cohort_id,
        "year": str(asset.year),
        "checks": asset.checks_state,
        "search": search,
        "stage-identified": asset.stages["identified"],
        "stage-on-disk": asset.stages["on_disk"],
        "stage-tidied": asset.stages["tidied"],
        "stage-canonicalised": asset.stages["canonicalised"],
        "stage-integrated": asset.stages["integrated"],
        "sort-asset": f"{asset.cohort_label} {asset.year}",
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
    return f"""
<tbody class="asset-pair" {rendered_attrs}>
  <tr class="asset-row">
    <th scope="row"><span class="asset-name">{_e(asset.cohort_label)}</span><span class="sheet-name">{_e(asset.sheet)}</span></th>
    <td>{asset.year}</td>
    <td>{_status_markup(asset.stages["identified"])}</td>
    <td>{_status_markup(asset.stages["on_disk"])}</td>
    <td>{_status_markup(asset.stages["tidied"])}</td>
    <td>{_status_markup(asset.stages["canonicalised"])}</td>
    <td>{_status_markup(asset.stages["integrated"])}</td>
    <td class="number">{count}</td>
    <td>{_status_markup(asset.checks_state, checks=True)}</td>
    <td><button class="detail-toggle" type="button" aria-expanded="false" aria-controls="{detail_id}">Evidence</button></td>
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
        ("year", "Year"),
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
  <div class="table-wrap"><table><thead><tr>{header_cells}<th scope="col">Details</th></tr></thead>{rows}</table></div>
  <p class="empty-cohort" hidden>No assets in this cohort match the current filters.</p>
</section>"""


def render_dashboard(status: DashboardStatus) -> bytes:
    assets = status.assets
    issue_count = sum(asset.checks_state == "issues" for asset in assets)
    integrated_count = sum(asset.stages["integrated"] == "yes" for asset in assets)
    years = sorted({asset.year for asset in assets})
    cohort_options = "".join(
        f'<option value="{_e(cohort.cohort_id)}">{_e(cohort.label)}</option>'
        for cohort in status.cohorts
    )
    year_options = "".join(f'<option value="{year}">{year}</option>' for year in years)
    sections = "".join(_cohort_section(cohort) for cohort in status.cohorts)
    summary = (
        f"{len(status.cohorts)} cohorts · {len(assets)} sheet-assets across "
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
h4 {{ margin:1rem 0 .35rem; }}
p {{ margin:.35rem 0; }}
a {{ color:var(--accent); }}
header {{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:18px; }}
.subtitle,.summary,.cohort-heading p,.muted {{ color:var(--muted); }}
.summary {{ font-size:.93rem; margin-bottom:18px; }}
.controls {{ display:grid; grid-template-columns:minmax(180px,2fr) repeat(4,minmax(135px,1fr)) auto; gap:10px; align-items:end; padding:14px; margin-bottom:20px; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
label {{ display:grid; gap:4px; color:var(--muted); font-size:.8rem; font-weight:650; }}
input,select,button {{ font:inherit; }}
input,select {{ width:100%; min-height:38px; border:1px solid #aeb8c2; border-radius:5px; background:#fff; padding:7px 9px; color:var(--ink); }}
button,.button {{ min-height:36px; border:1px solid #9da9b5; border-radius:5px; padding:6px 10px; background:#fff; color:var(--ink); cursor:pointer; text-decoration:none; }}
button:hover,.button:hover {{ border-color:var(--accent); color:var(--accent); }}
.cohort {{ margin:26px 0 34px; }}
.cohort-heading {{ display:flex; justify-content:space-between; gap:20px; align-items:flex-start; margin-bottom:10px; }}
.cohort-banner {{ max-width:620px; margin:0; padding:7px 10px; border-radius:5px; font-size:.9rem; }}
.cohort-banner ul {{ margin:.4rem 0 0 1rem; padding:0; }}
.banner-pass {{ color:var(--pass); background:var(--pass-bg); }}
.banner-issues {{ color:var(--issue); background:var(--issue-bg); }}
.banner-unknown {{ color:var(--unknown); background:var(--unknown-bg); }}
.table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:7px; }}
table {{ width:100%; min-width:1120px; border-collapse:collapse; }}
th,td {{ padding:10px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:middle; white-space:nowrap; }}
thead th {{ color:#44515e; background:#f3f6f8; font-size:.78rem; text-transform:uppercase; letter-spacing:.035em; }}
thead .sort {{ min-height:auto; border:0; padding:0; color:inherit; background:transparent; font-size:inherit; text-transform:inherit; letter-spacing:inherit; font-weight:700; }}
tbody:last-child tr:last-child > * {{ border-bottom:0; }}
.asset-name,.sheet-name {{ display:block; }}
.asset-name {{ font-weight:650; }}
.sheet-name {{ color:var(--muted); font-size:.82rem; }}
.number {{ text-align:right; font-variant-numeric:tabular-nums; }}
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
@media (max-width:980px) {{ .controls {{ grid-template-columns:1fr 1fr; }} header,.cohort-heading {{ display:block; }} .cohort-banner {{ margin-top:9px; }} .detail-grid {{ grid-template-columns:1fr; }} }}
@media (max-width:600px) {{ main {{ padding:20px 12px 40px; }} .controls {{ grid-template-columns:1fr; }} dl {{ grid-template-columns:1fr; gap:2px; }} dd {{ margin-bottom:8px; }} }}
</style>
</head>
<body>
<main>
<header><div><h1>{_e(status.title)}</h1><p class="subtitle">Read-only projection from checked manifests. Evidence remains authoritative; this page does not edit or approve data.</p></div><a class="button dagster-link" data-dagster-root href="http://127.0.0.1:{status.dagster_port}/assets">Open Dagster</a></header>
<p class="summary" id="summary">{_e(summary)}</p>
<div class="controls" role="search" aria-label="Filter data assets">
<label>Search<input id="search" type="search" placeholder="Asset, sheet, path, check…"></label>
<label>Cohort<select id="cohort-filter"><option value="">All cohorts</option>{cohort_options}</select></label>
<label>Year<select id="year-filter"><option value="">All years</option>{year_options}</select></label>
<label>Checks<select id="checks-filter"><option value="">All check states</option><option value="pass">Pass</option><option value="issues">Issues</option><option value="no_evidence">No evidence</option></select></label>
<label>Incomplete stage<select id="stage-filter"><option value="">Any stage</option><option value="identified">Identified</option><option value="on-disk">On disk</option><option value="tidied">Tidied</option><option value="canonicalised">Canonicalised</option><option value="integrated">Integrated</option></select></label>
<button id="reset" type="button">Reset</button>
</div>
<p id="visible-count" class="muted" aria-live="polite">Showing {len(assets)} of {len(assets)} assets.</p>
{sections}
<p class="no-results" id="no-results" hidden>No assets match the current filters.</p>
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
    cohort: document.getElementById("cohort-filter"),
    year: document.getElementById("year-filter"),
    checks: document.getElementById("checks-filter"),
    stage: document.getElementById("stage-filter")
  }};
  const dataKey = (value) => value.replace(/-([a-z])/g, (_, char) => char.toUpperCase());
  function applyFilters() {{
    const query = controls.search.value.trim().toLowerCase();
    let shown = 0;
    for (const pair of allPairs) {{
      const stage = controls.stage.value;
      const visible = (!query || pair.dataset.search.includes(query))
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
    document.getElementById("visible-count").textContent = `Showing ${{shown}} of ${{allPairs.length}} assets.`;
    document.getElementById("no-results").hidden = shown !== 0;
  }}
  Object.values(controls).forEach((control) => control.addEventListener("input", applyFilters));
  document.getElementById("reset").addEventListener("click", () => {{
    Object.values(controls).forEach((control) => {{ control.value = ""; }});
    applyFilters();
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
  applyFilters();
}})();
</script>
</body>
</html>
"""
    return document.encode()


def expected_snapshot(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> tuple[DashboardStatus, bytes]:
    status = build_dashboard(project_root, registry_relative)
    return status, render_dashboard(status)


def refresh_snapshot(
    project_root: Path | None = None,
    registry_relative: Path = DEFAULT_REGISTRY,
) -> tuple[DashboardStatus, Path, bool]:
    root = (project_root or default_project_root()).resolve()
    status, rendered = expected_snapshot(root, registry_relative)
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
    status, rendered = expected_snapshot(root, registry_relative)
    output = _safe_relative_path(root, status.output_path, "status output")
    expected = sha256_digest(rendered)
    if not output.is_file():
        return False, output, expected, None
    actual_data = output.read_bytes()
    return actual_data == rendered, output, expected, sha256_digest(actual_data)


class StatusPageServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def status_handler(page_path: Path) -> type[BaseHTTPRequestHandler]:
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
            if path not in {"/", "/index.html"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                body = page_path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send(HTTPStatus.OK, body, "text/html; charset=utf-8", head)

        def _send(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            head: bool,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            super().log_message(format, *args)

    return Handler


def make_status_server(host: str, port: int, page_path: Path) -> StatusPageServer:
    if host != "127.0.0.1":
        raise DataAssetStatusError("Status server must bind exactly to 127.0.0.1")
    return StatusPageServer((host, port), status_handler(page_path))
