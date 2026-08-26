"""Exact custody and semantic-family closure for Federal Defendants, Australia."""

from __future__ import annotations

import json
import re
import stat
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .offenders_release import (
    OffendersReleaseError,
    inspect_workbook,
    semantic_cells,
)

DOWNLOAD_SCHEMA = "tidy.federal-defendants-release-downloads/v1"
CROSSWALK_SCHEMA = "tidy.federal-defendants-release-family-crosswalk/v1"
INVENTORY_SCHEMA = "tidy.federal-defendants-release-source-inventory/v1"
MEMBERSHIP_SCHEMA = "tidy.federal-defendants-release-family-membership/v1"
BOUNDED_RANGE_SCHEMA = "tidy.federal-defendants-bounded-range-exclusions/v1"
PUBLICATION_ID = "federal-defendants-australia"
RELEASES = ["2021-22", "2022-23", "2023-24", "2024-25"]
EXPECTED_DOWNLOAD_COUNTS = {release: 3 for release in RELEASES}
EXPECTED_NUMBERED_COUNTS = {
    "2021-22": 8,
    "2022-23": 10,
    "2023-24": 9,
    "2024-25": 9,
}
EXPECTED_DOWNLOAD_COUNT = 12
EXPECTED_CUBE_COUNT = 8
EXPECTED_NUMBERED_COUNT = 36
EXPECTED_FAMILY_COUNT = 23
EXPECTED_REGISTERED_COUNT = 0
EXPECTED_BOUNDED_SHEET_COUNT = 2
PUBLICATION_VINTAGE_DATES = {
    "2021-22": "2023-05-04",
    "2022-23": "2024-05-09",
    "2023-24": "2025-05-01",
    "2024-25": "2026-04-30",
}
EXPECTED_DOWNLOAD_IDENTITIES = {
    ("2021-22", 0): (
        "guide",
        "guide",
        None,
        "Guide to finding data in the Federal Defendants publication tables 2021-22",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2021-22/Guide%20to%20finding%20data%20in%20the%20Federal%20Defendants%20publication%20tables%202021-22.xlsx",
        "workbooks/federal-defendants-australia-2021-22-guide-source.xlsx",
        ("Guide Federal Defendants data",),
        0,
    ),
    ("2021-22", 1): (
        "cube",
        "national",
        "main",
        "Federal defendants, Australia (Tables 1 to 4) 2021-22",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2021-22/1.%20Federal%20defendants%2C%20Australia%20%28Tables%201%20to%204%29%202021-22.xlsx",
        "workbooks/federal-defendants-australia-2021-22-national-source.xlsx",
        ("Contents", "Table 1", "Table 2", "Table 3", "Table 4"),
        4,
    ),
    ("2021-22", 2): (
        "cube",
        "federal-offence-group",
        "main",
        "Federal defendants, Federal Offence Group, Australia (Tables 5 to 8) 2021-22",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2021-22/2.%20Federal%20defendants%2C%20Federal%20Offence%20Group%2C%20Australia%20%28Tables%205%20to%208%29%202021-22.xlsx",
        "workbooks/federal-defendants-australia-2021-22-federal-offence-group-source.xlsx",
        ("Contents", "Table 5", "Table 6", "Table 7", "Table 8"),
        4,
    ),
    ("2022-23", 0): (
        "guide",
        "guide",
        None,
        "Guide to finding data in the Federal Defendants publication tables 2022-23",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2022-23/Guide%20to%20finding%20data%20in%20the%20Federal%20Defendants%20publication%20tables%202022-23.xlsx",
        "workbooks/federal-defendants-australia-2022-23-guide-source.xlsx",
        ("Guide Federal Defendants data",),
        0,
    ),
    ("2022-23", 1): (
        "cube",
        "national",
        "main",
        "Federal defendants, Australia (Tables 1 to 5) 2022-23",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2022-23/1.%20Federal%20defendants%2C%20Australia%20%28Tables%201%20to%205%29%202022-23.xlsx",
        "workbooks/federal-defendants-australia-2022-23-national-source.xlsx",
        ("Contents", "Table 1", "Table 2", "Table 3", "Table 4", "Table 5"),
        5,
    ),
    ("2022-23", 2): (
        "cube",
        "federal-offence-group",
        "main",
        "Federal defendants, Federal Offence Group, Australia (Tables 6 to 10) 2022-23",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2022-23/2.%20Federal%20defendants%2C%20Federal%20Offence%20Group%2C%20Australia%20%28Tables%206%20to%2010%29%202022-23.xlsx",
        "workbooks/federal-defendants-australia-2022-23-federal-offence-group-source.xlsx",
        ("Contents", "Table 6", "Table 7", "Table 8", "Table 9", "Table 10"),
        5,
    ),
    ("2023-24", 0): (
        "guide",
        "guide",
        None,
        "Guide to finding data in the Federal Defendants tables, 2023-24",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2023-24/Guide%20to%20finding%20data%20in%20the%20Federal%20Defendants%20tables%2C%202023-24.xlsx",
        "workbooks/federal-defendants-australia-2023-24-guide-source.xlsx",
        ("Guide Federal Defendants data",),
        0,
    ),
    ("2023-24", 1): (
        "cube",
        "national",
        "main",
        "Federal defendants, Australia (Tables 1 to 5)",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2023-24/1.%20Federal%20defendants%2C%20Australia%20%28Tables%201%20to%205%29.xlsx",
        "workbooks/federal-defendants-australia-2023-24-national-source.xlsx",
        ("Contents", "Table 1", "Table 2", "Table 3", "Table 4", "Table 5"),
        5,
    ),
    ("2023-24", 2): (
        "cube",
        "federal-offence-group",
        "main",
        "Federal defendants, Federal Offence Group, Australia (Tables 6 to 9)",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2023-24/2.%20Federal%20defendants%2C%20Federal%20Offence%20Group%2C%20Australia%20%28Tables%206%20to%209%29.xlsx",
        "workbooks/federal-defendants-australia-2023-24-federal-offence-group-source.xlsx",
        ("Contents", "Table 6", "Table 7", "Table 8", "Table 9"),
        4,
    ),
    ("2024-25", 0): (
        "guide",
        "guide",
        None,
        "Guide to finding data in the Federal defendants, 2024-25 publication tables",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2024-25/Guide%20to%20finding%20data%20in%20the%20Federal%20defendants%2C%202024-25%20publication%20tables.xlsx",
        "workbooks/federal-defendants-australia-2024-25-guide-source.xlsx",
        ("Guide to finding data",),
        0,
    ),
    ("2024-25", 1): (
        "cube",
        "national",
        "main",
        "Federal defendants, Australia (Tables 1 to 5)",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2024-25/1.%20Federal%20defendants%2C%20Australia%20%28Tables%201%20to%205%29.xlsx",
        "workbooks/federal-defendants-australia-2024-25-national-source.xlsx",
        ("Contents", "Table 1", "Table 2", "Table 3", "Table 4", "Table 5"),
        5,
    ),
    ("2024-25", 2): (
        "cube",
        "federal-offence-group",
        "main",
        "Federal defendants, Federal offence group, Australia (Tables 6 to 9)",
        "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2024-25/2.%20Federal%20defendants%2C%20Federal%20offence%20group%2C%20Australia%20%28Tables%206%20to%209%29.xlsx",
        "workbooks/federal-defendants-australia-2024-25-federal-offence-group-source.xlsx",
        ("Contents", "Table 6", "Table 7", "Table 8", "Table 9"),
        4,
    ),
}
RECOGNIZED_VALUE_MARKERS = (
    "..",
    "na",
    "n.a.",
    "np",
    "n.p.",
    "-",
    "–",  # noqa: RUF001 - exact published en-dash marker
)

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_MARKERS = {marker.lower() for marker in RECOGNIZED_VALUE_MARKERS}
_CELL = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
_BOUNDED_RANGES = {
    ("2023-24", 1, "Table 1"): "A1:O69",
    ("2023-24", 1, "Table 3"): "A1:J86",
}


class FederalDefendantsReleaseError(RuntimeError):
    """Federal Defendants release custody or coverage is invalid."""


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise FederalDefendantsReleaseError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise FederalDefendantsReleaseError(f"{label} must be an object")
    return value


def _safe_file(project: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise FederalDefendantsReleaseError(f"{label} escapes the project")
    parts = relative.split("/")
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or pure.as_posix() != relative
    ):
        raise FederalDefendantsReleaseError(f"{label} escapes the project")

    try:
        trusted_root = project.resolve(strict=True)
    except (OSError, ValueError) as error:
        raise FederalDefendantsReleaseError(f"{label} is missing or unsafe") from error
    if not trusted_root.is_dir():
        raise FederalDefendantsReleaseError(f"{label} is missing or unsafe")

    candidate = trusted_root
    terminal_identity: tuple[int, int] | None = None
    for part in parts:
        candidate /= part
        try:
            component = candidate.lstat()
        except (OSError, ValueError) as error:
            raise FederalDefendantsReleaseError(
                f"{label} is missing or unsafe"
            ) from error
        if stat.S_ISLNK(component.st_mode):
            raise FederalDefendantsReleaseError(f"{label} is missing or unsafe")
        terminal_identity = (component.st_dev, component.st_ino)

    try:
        path = candidate.resolve(strict=True)
        path.relative_to(trusted_root)
        resolved = path.stat()
    except (OSError, ValueError) as error:
        raise FederalDefendantsReleaseError(f"{label} escapes the project") from error
    if (
        terminal_identity != (resolved.st_dev, resolved.st_ino)
        or not stat.S_ISREG(resolved.st_mode)
    ):
        raise FederalDefendantsReleaseError(f"{label} is missing or unsafe")
    return path


def _without_digest(value: dict[str, Any], field: str) -> dict[str, Any]:
    semantic = json.loads(json.dumps(value))
    semantic.pop(field, None)
    return semantic


def _publication_vintage_date(release: str) -> str:
    try:
        return PUBLICATION_VINTAGE_DATES[release]
    except KeyError as error:
        raise FederalDefendantsReleaseError(
            "publication vintage date is not pinned"
        ) from error


def _table_provenance(
    release: str, cube_id: str, physical_table_number: int, published_title: str
) -> dict[str, str]:
    """Return exact member-level classification and selection provenance."""
    if cube_id == "federal-offence-group":
        row_classification = "abs-federal-offence-group"
        principal_classification = (
            "anzsoc-2023" if release == "2024-25" else "anzsoc-2011"
        )
        classification_treatment = "native-federal-offence-group"
    else:
        row_classification = "anzsoc-2023" if release == "2024-25" else "anzsoc-2011"
        principal_classification = row_classification
        classification_treatment = (
            "observation-period-dependent:anzsoc-2023-concorded-from-anzsoc-2011-"
            "through-2022-23|anzsoc-2023-native-from-2023-24"
            if release == "2024-25" and "concorded from ANZSOC 2011" in published_title
            else "native"
        )

    pre_sentence = {
        ("2021-22", "national", 2),
        ("2021-22", "national", 3),
        ("2021-22", "national", 4),
        ("2021-22", "federal-offence-group", 7),
    }
    mapped_sentence = {
        ("2022-23", "national", 2),
        ("2022-23", "national", 4),
        ("2022-23", "national", 5),
        ("2022-23", "federal-offence-group", 8),
        ("2023-24", "national", 2),
        ("2023-24", "national", 4),
        ("2023-24", "national", 5),
        ("2023-24", "federal-offence-group", 8),
        ("2024-25", "national", 3),
        ("2024-25", "national", 5),
    }
    current_sentence = {
        ("2022-23", "national", 3),
        ("2023-24", "national", 3),
        ("2024-25", "national", 2),
        ("2024-25", "national", 4),
        ("2024-25", "federal-offence-group", 8),
    }
    key = (release, cube_id, physical_table_number)
    if key in pre_sentence:
        sentence_classification = "pre-2022-23-sentence-classification"
        sentence_treatment = "native"
    elif key in mapped_sentence:
        sentence_classification = "sentence-type-classification-2023"
        sentence_treatment = (
            "observation-period-dependent:stc-2023-backcast-from-old-before-"
            "2022-23|stc-2023-native-from-2022-23"
        )
    elif key in current_sentence:
        sentence_classification = "sentence-type-classification-2023"
        sentence_treatment = "native-current-period"
    else:
        sentence_classification = "not-applicable"
        sentence_treatment = "not-applicable-no-sentence-dimension"

    period_dependent_selection = {
        ("2021-22", "national", 1),
        ("2021-22", "national", 2),
        ("2021-22", "national", 4),
        ("2021-22", "federal-offence-group", 5),
        ("2021-22", "federal-offence-group", 6),
        ("2021-22", "federal-offence-group", 7),
        ("2022-23", "national", 1),
        ("2022-23", "national", 2),
        ("2022-23", "national", 4),
        ("2022-23", "national", 5),
        ("2022-23", "federal-offence-group", 6),
        ("2022-23", "federal-offence-group", 7),
        ("2022-23", "federal-offence-group", 8),
        ("2023-24", "national", 1),
        ("2023-24", "national", 2),
        ("2023-24", "national", 4),
        ("2023-24", "national", 5),
        ("2023-24", "federal-offence-group", 6),
        ("2023-24", "federal-offence-group", 7),
        ("2023-24", "federal-offence-group", 8),
        ("2024-25", "national", 1),
        ("2024-25", "national", 3),
        ("2024-25", "national", 5),
    }
    principal_selection_treatment = (
        "observation-period-dependent:pre-2018-19-method-finalisation-then-noi|"
        "2018-19-plus-method-finalisation-sentence-then-noi"
        if key in period_dependent_selection
        else "2018-19-plus-method-finalisation-sentence-then-noi"
    )
    revision_treatment = (
        "observation-period-dependent:2023-24-refined-preliminary-anzsoc-2023-"
        "republication|otherwise-as-published"
        if release == "2024-25"
        and cube_id == "national"
        and physical_table_number in {1, 3, 5}
        else "as-published-no-member-specific-revision-rule"
    )
    return {
        "rowClassification": row_classification,
        "principalOffenceClassification": principal_classification,
        "classificationTreatment": classification_treatment,
        "sentenceClassification": sentence_classification,
        "sentenceTreatment": sentence_treatment,
        "principalSelectionTreatment": principal_selection_treatment,
        "revisionTreatment": revision_treatment,
    }


def _relationship_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError) as error:
        raise FederalDefendantsReleaseError(
            "workbook relationships are invalid"
        ) from error
    targets: dict[str, str] = {}
    for relationship in root.findall(f"{{{_PACKAGE_REL}}}Relationship"):
        identifier = relationship.get("Id")
        target = relationship.get("Target")
        if not identifier or not target or relationship.get("TargetMode") == "External":
            raise FederalDefendantsReleaseError(
                "workbook relationship is external or invalid"
            )
        pure = PurePosixPath(target)
        parts = pure.parts[1:] if pure.is_absolute() else ("xl", *pure.parts)
        if ".." in parts:
            raise FederalDefendantsReleaseError("workbook relationship escapes archive")
        targets[identifier] = PurePosixPath(*parts).as_posix()
    return targets


def _worksheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        root = ET.fromstring(archive.read("xl/workbook.xml"))
    except (KeyError, ET.ParseError) as error:
        raise FederalDefendantsReleaseError("workbook metadata is invalid") from error
    relationships = _relationship_targets(archive)
    targets: dict[str, str] = {}
    for sheet in root.findall(f".//{{{_MAIN}}}sheet"):
        name = sheet.get("name")
        identifier = sheet.get(f"{{{_REL}}}id")
        target = relationships.get(identifier or "")
        if not name or not target or name in targets:
            raise FederalDefendantsReleaseError("worksheet binding is invalid")
        targets[name] = target
    return targets


def _is_hidden(value: str | None) -> bool:
    return value in {"1", "true", "True"}


def _column_number(label: str) -> int:
    result = 0
    for character in label:
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _cell_position(address: str) -> tuple[int, int]:
    match = _CELL.fullmatch(address)
    if match is None:
        raise FederalDefendantsReleaseError("semantic cell address is invalid")
    return int(match.group(2)), _column_number(match.group(1))


def _range_bounds(reference: str) -> tuple[int, int, int, int]:
    try:
        start, end = reference.split(":", 1)
        start_row, start_column = _cell_position(start)
        end_row, end_column = _cell_position(end)
    except ValueError as error:
        raise FederalDefendantsReleaseError("authoritative range is invalid") from error
    if start_row > end_row or start_column > end_column:
        raise FederalDefendantsReleaseError("authoritative range is reversed")
    return start_row, start_column, end_row, end_column


def _inside_range(address: str, reference: str) -> bool:
    row, column = _cell_position(address)
    start_row, start_column, end_row, end_column = _range_bounds(reference)
    return start_row <= row <= end_row and start_column <= column <= end_column


def _semantic_payload(
    address: str, formula: str | None, scalar: str | None
) -> dict[str, str]:
    payload = {"address": address}
    if formula is not None:
        payload["formula"] = formula
    if scalar not in (None, ""):
        payload["value"] = scalar
    return payload


def build_bounded_range_exclusion_ledger(project_root: Path) -> dict[str, Any]:
    """Rebuild exact nonblank exclusions outside source-declared Federal ranges."""
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    custody = _load(
        root / "federal-defendants-release-downloads-v1.json", "download custody"
    )
    declarations = custody.get("downloads")
    if not isinstance(declarations, list):
        raise FederalDefendantsReleaseError("download custody schema is invalid")
    sheets: list[dict[str, Any]] = []
    for (release, ordinal, sheet_name), authoritative_range in sorted(
        _BOUNDED_RANGES.items()
    ):
        declaration = next(
            (
                item
                for item in declarations
                if isinstance(item, dict)
                and item.get("releaseId") == release
                and item.get("downloadOrdinal") == ordinal
            ),
            None,
        )
        if declaration is None or not isinstance(declaration.get("path"), str):
            raise FederalDefendantsReleaseError("bounded source declaration is missing")
        path = _safe_file(root, declaration["path"], "bounded Federal workbook")
        data = path.read_bytes()
        if len(data) != declaration.get("byteLength") or sha256_digest(
            data
        ) != declaration.get("contentDigest"):
            raise FederalDefendantsReleaseError("download bytes differ from custody")
        try:
            source_cells = semantic_cells(path)
        except (OffendersReleaseError, OSError) as error:
            raise FederalDefendantsReleaseError(
                "bounded workbook semantic cells are invalid"
            ) from error
        authority = source_cells.get((sheet_name, "A1"))
        if (
            authority is None
            or authority[0] is not None
            or not isinstance(authority[1], str)
            or f"ranges from cell A1 to {authoritative_range.split(':')[1]}"
            not in authority[1]
        ):
            raise FederalDefendantsReleaseError(
                "bounded range lacks exact source authority"
            )
        bounded = [
            _semantic_payload(address, formula, scalar)
            for (physical_sheet, address), (formula, scalar) in source_cells.items()
            if physical_sheet == sheet_name
            and _inside_range(address, authoritative_range)
        ]
        excluded = [
            _semantic_payload(address, formula, scalar)
            for (physical_sheet, address), (formula, scalar) in source_cells.items()
            if physical_sheet == sheet_name
            and not _inside_range(address, authoritative_range)
        ]
        bounded.sort(key=lambda item: item["address"])
        excluded.sort(key=lambda item: item["address"])
        entry: dict[str, Any] = {
            "releaseId": release,
            "downloadOrdinal": ordinal,
            "sourcePath": declaration["path"],
            "sourceDigest": declaration["contentDigest"],
            "physicalSheetName": sheet_name,
            "authorityCell": "A1",
            "authorityText": authority[1],
            "authoritativeRange": authoritative_range,
            "boundedSemanticCellCount": len(bounded),
            "boundedSemanticCellDigest": domain_digest(
                "tidy.xlsx-bounded-semantic-cells/v1", bounded
            ),
            "excludedNonblankCellCount": len(excluded),
            "excludedNonblankCells": excluded,
        }
        entry["exclusionDigest"] = domain_digest(
            "tidy.xlsx-out-of-authoritative-range-nonblank-cells/v1", excluded
        )
        sheets.append(entry)
    ledger: dict[str, Any] = {
        "schemaVersion": BOUNDED_RANGE_SCHEMA,
        "recordedAt": custody.get("recordedAt"),
        "publicationId": PUBLICATION_ID,
        "boundedSheetCount": len(sheets),
        "excludedNonblankCellCount": sum(
            item["excludedNonblankCellCount"] for item in sheets
        ),
        "sheets": sheets,
    }
    ledger["ledgerDigest"] = domain_digest(BOUNDED_RANGE_SCHEMA, ledger)
    return ledger


def _structure_inventory(path: Path) -> dict[str, dict[str, Any]]:
    """Digest-pin merged, hidden, marker, and formula structures per worksheet."""
    try:
        cells = semantic_cells(path)
        with zipfile.ZipFile(path) as archive:
            result: dict[str, dict[str, Any]] = {}
            for name, target in _worksheet_targets(archive).items():
                root = ET.fromstring(archive.read(target))
                hidden_rows = sorted(
                    int(row.get("r", "0"))
                    for row in root.findall(f".//{{{_MAIN}}}row")
                    if _is_hidden(row.get("hidden"))
                )
                hidden_columns = sorted(
                    [int(column.get("min", "0")), int(column.get("max", "0"))]
                    for column in root.findall(f".//{{{_MAIN}}}col")
                    if _is_hidden(column.get("hidden"))
                )
                merged_ranges = sorted(
                    item.get("ref", "")
                    for item in root.findall(f".//{{{_MAIN}}}mergeCell")
                    if item.get("ref")
                )
                sheet_cells = [
                    payload
                    for (sheet_name, _address), payload in cells.items()
                    if sheet_name == name
                ]
                marker_counts = Counter(
                    scalar
                    for _formula, scalar in sheet_cells
                    if scalar is not None and scalar.strip().lower() in _MARKERS
                )
                structure = {
                    "hiddenRows": hidden_rows,
                    "hiddenColumnRanges": hidden_columns,
                    "mergedRanges": merged_ranges,
                }
                result[name] = {
                    "formulaCellCount": sum(
                        formula is not None for formula, _scalar in sheet_cells
                    ),
                    "valueMarkerCounts": dict(sorted(marker_counts.items())),
                    "hiddenRowCount": len(hidden_rows),
                    "hiddenColumnRangeCount": len(hidden_columns),
                    "mergedRangeCount": len(merged_ranges),
                    "worksheetStructureDigest": domain_digest(
                        "tidy.xlsx-worksheet-structure/v1", structure
                    ),
                }
            return result
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile) as error:
        raise FederalDefendantsReleaseError(
            f"workbook structure is invalid: {path.name}"
        ) from error


def _inspect_federal_workbook(
    path: Path, *, table_namespace: str | None, kind: str
) -> list[dict[str, Any]]:
    try:
        sheets = inspect_workbook(path, table_namespace=table_namespace, kind=kind)
    except (OffendersReleaseError, OSError) as error:
        raise FederalDefendantsReleaseError("workbook inspection failed") from error
    structures = _structure_inventory(path)
    if {sheet["name"] for sheet in sheets} != set(structures):
        raise FederalDefendantsReleaseError("worksheet structure cover is incomplete")
    return [{**sheet, **structures[sheet["name"]]} for sheet in sheets]


def build_source_inventory(project_root: Path) -> dict[str, Any]:
    """Rebuild the complete exact-byte, sheet, and bounded-range inventory."""
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    custody = _load(
        root / "federal-defendants-release-downloads-v1.json", "download custody"
    )
    declarations = custody.get("downloads")
    if (
        set(custody)
        != {"schemaVersion", "recordedAt", "publicationId", "releases", "downloads"}
        or custody.get("schemaVersion") != DOWNLOAD_SCHEMA
        or custody.get("publicationId") != PUBLICATION_ID
        or custody.get("releases") != RELEASES
        or not isinstance(declarations, list)
        or len(declarations) != EXPECTED_DOWNLOAD_COUNT
    ):
        raise FederalDefendantsReleaseError("download custody schema is invalid")
    ledger = build_bounded_range_exclusion_ledger(project)
    if ledger.get("boundedSheetCount") != EXPECTED_BOUNDED_SHEET_COUNT:
        raise FederalDefendantsReleaseError("bounded range sheet count is invalid")
    bounded_by_key = {
        (item["releaseId"], item["downloadOrdinal"], item["physicalSheetName"]): item
        for item in ledger["sheets"]
    }
    declaration_keys = {
        "releaseId",
        "downloadOrdinal",
        "kind",
        "cubeId",
        "tableNamespace",
        "officialTitle",
        "releasePageUrl",
        "url",
        "path",
        "contentDigest",
        "byteLength",
        "expectedSheetNames",
        "expectedNumberedSheetCount",
    }
    per_release_downloads = {release: 0 for release in RELEASES}
    per_release_numbered = {release: 0 for release in RELEASES}
    ordinals = {release: set() for release in RELEASES}
    paths: set[str] = set()
    urls: set[str] = set()
    downloads: list[dict[str, Any]] = []
    total_bytes = 0
    cube_count = 0
    guide_count = 0
    marker_counts: Counter[str] = Counter()
    consumed_bounded: set[tuple[str, int, str]] = set()
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) != declaration_keys:
            raise FederalDefendantsReleaseError("download declaration is invalid")
        release = declaration.get("releaseId")
        ordinal = declaration.get("downloadOrdinal")
        kind = declaration.get("kind")
        cube_id = declaration.get("cubeId")
        namespace = declaration.get("tableNamespace")
        relative = declaration.get("path")
        url = declaration.get("url")
        release_page = declaration.get("releasePageUrl")
        expected_sheets = declaration.get("expectedSheetNames")
        expected_numbered = declaration.get("expectedNumberedSheetCount")
        identity_key = (
            (release, ordinal)
            if isinstance(release, str)
            and isinstance(ordinal, int)
            and not isinstance(ordinal, bool)
            else None
        )
        actual_identity = (
            kind,
            cube_id,
            namespace,
            declaration.get("officialTitle"),
            url,
            relative,
            tuple(expected_sheets) if isinstance(expected_sheets, list) else None,
            expected_numbered,
        )
        if (
            identity_key is None
            or identity_key not in EXPECTED_DOWNLOAD_IDENTITIES
            or ordinal in ordinals[release]
            or actual_identity != EXPECTED_DOWNLOAD_IDENTITIES[identity_key]
            or release_page
            != (
                "https://www.abs.gov.au/statistics/people/crime-and-justice/"
                f"federal-defendants-australia/{release}"
            )
            or url in urls
            or relative in paths
        ):
            raise FederalDefendantsReleaseError(
                "download declaration binding is invalid"
            )
        ordinals[release].add(ordinal)
        paths.add(relative)
        urls.add(url)
        path = _safe_file(root, relative, "declared Federal Defendants workbook")
        data = path.read_bytes()
        if len(data) != declaration.get("byteLength") or sha256_digest(
            data
        ) != declaration.get("contentDigest"):
            raise FederalDefendantsReleaseError("download bytes differ from custody")
        raw_sheets = _inspect_federal_workbook(
            path, table_namespace=namespace, kind=kind
        )
        sheets: list[dict[str, Any]] = []
        for raw_sheet in raw_sheets:
            marker_counts.update(raw_sheet["valueMarkerCounts"])
            if raw_sheet["classification"] != "numbered-data":
                sheets.append(raw_sheet)
                continue
            if not isinstance(raw_sheet.get("title"), str) or not raw_sheet["title"]:
                raise FederalDefendantsReleaseError("numbered sheet title is missing")
            provenance = _table_provenance(
                release,
                cube_id,
                raw_sheet["physicalTableNumber"],
                raw_sheet["title"],
            )
            key = (release, ordinal, raw_sheet["name"])
            bounded = bounded_by_key.get(key)
            execution: dict[str, Any] = {
                "executionCellSelection": "raw-semantic-cells-v1"
            }
            if bounded is not None:
                if (
                    bounded["sourcePath"] != relative
                    or bounded["sourceDigest"] != declaration["contentDigest"]
                ):
                    raise FederalDefendantsReleaseError(
                        "bounded range source binding is invalid"
                    )
                execution = {
                    "executionCellSelection": "federal-authoritative-range-bounded-v1",
                    "authoritativeRange": bounded["authoritativeRange"],
                    "boundedSemanticCellCount": bounded["boundedSemanticCellCount"],
                    "boundedSemanticCellDigest": bounded["boundedSemanticCellDigest"],
                    "excludedNonblankCellCount": bounded["excludedNonblankCellCount"],
                    "outOfRangeExclusionDigest": bounded["exclusionDigest"],
                }
                consumed_bounded.add(key)
            sheets.append({**raw_sheet, **provenance, **execution})
        numbered = sum(sheet["classification"] == "numbered-data" for sheet in sheets)
        if [
            sheet["name"] for sheet in sheets
        ] != expected_sheets or numbered != expected_numbered:
            raise FederalDefendantsReleaseError(
                "declared sheet inventory differs from source"
            )
        if kind == "guide" and numbered != 0:
            raise FederalDefendantsReleaseError("guide contains a numbered data sheet")
        per_release_downloads[release] += 1
        per_release_numbered[release] += numbered
        total_bytes += len(data)
        cube_count += kind == "cube"
        guide_count += kind == "guide"
        downloads.append({**declaration, "sheets": sheets})
    if (
        per_release_downloads != EXPECTED_DOWNLOAD_COUNTS
        or per_release_numbered != EXPECTED_NUMBERED_COUNTS
        or cube_count != EXPECTED_CUBE_COUNT
        or guide_count != len(RELEASES)
        or sum(per_release_numbered.values()) != EXPECTED_NUMBERED_COUNT
        or any(ordinals[release] != {0, 1, 2} for release in RELEASES)
        or consumed_bounded != set(bounded_by_key)
    ):
        raise FederalDefendantsReleaseError("release inventory totals are invalid")
    inventory: dict[str, Any] = {
        "schemaVersion": INVENTORY_SCHEMA,
        "recordedAt": custody["recordedAt"],
        "publicationId": PUBLICATION_ID,
        "releases": RELEASES,
        "downloadCount": len(downloads),
        "reviewedExclusionDownloadCount": guide_count,
        "substantiveCubeCount": cube_count,
        "numberedDataSheetCount": EXPECTED_NUMBERED_COUNT,
        "totalByteLength": total_bytes,
        "numberedDataSheetCountsByRelease": per_release_numbered,
        "recognizedValueMarkers": list(RECOGNIZED_VALUE_MARKERS),
        "workbookValueMarkerCounts": dict(sorted(marker_counts.items())),
        "boundedRangeSheetCount": ledger["boundedSheetCount"],
        "boundedRangeExcludedNonblankCellCount": ledger["excludedNonblankCellCount"],
        "boundedRangeExclusionLedgerDigest": ledger["ledgerDigest"],
        "downloads": downloads,
    }
    inventory["inventoryDigest"] = domain_digest(INVENTORY_SCHEMA, inventory)
    return inventory


def _registered_members(
    project: Path, inventory: dict[str, Any]
) -> set[tuple[str, int, str]]:
    root = project / "fixtures" / "product-prototype"
    status = _load(root / "data-asset-status-v1.json", "status registry")
    sources: dict[tuple[str, str], tuple[str, int, str, str]] = {}
    for download in inventory["downloads"]:
        if download["kind"] != "cube":
            continue
        for sheet in download["sheets"]:
            if sheet["classification"] == "numbered-data":
                sources[(download["path"], sheet["name"])] = (
                    download["releaseId"],
                    download["downloadOrdinal"],
                    sheet["name"],
                    download["contentDigest"],
                )
    cohorts = status.get("cohorts")
    if not isinstance(cohorts, list):
        raise FederalDefendantsReleaseError("status cohort list is invalid")
    registered: set[tuple[str, int, str]] = set()
    seen_families: set[str] = set()
    for item in cohorts:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("cohortPath"), str)
            or not item["cohortPath"]
        ):
            raise FederalDefendantsReleaseError("status cohort entry is invalid")
        cohort = _load(
            _safe_file(project, item["cohortPath"], "status cohort"),
            "registered cohort",
        )
        if cohort.get("publicationId") != PUBLICATION_ID:
            continue
        if EXPECTED_REGISTERED_COUNT == 0:
            raise FederalDefendantsReleaseError(
                "premature Federal Defendants cohort registration"
            )
        family_id = cohort.get("tableFamilyId")
        workbooks = cohort.get("workbooks")
        if (
            not isinstance(family_id, str)
            or family_id in seen_families
            or not isinstance(workbooks, list)
            or not workbooks
        ):
            raise FederalDefendantsReleaseError("registered family identity is invalid")
        seen_families.add(family_id)
        for workbook in workbooks:
            if not isinstance(workbook, dict):
                raise FederalDefendantsReleaseError("registered workbook is invalid")
            source = sources.get((workbook.get("path"), workbook.get("sheet")))
            if source is None or workbook.get("contentDigest") != source[3]:
                raise FederalDefendantsReleaseError(
                    "registered workbook has no exact source custody"
                )
            registered.add(source[:3])
    return registered


def build_family_membership(
    project_root: Path, inventory: dict[str, Any]
) -> dict[str, Any]:
    """Expand and verify the complete explicit semantic family crosswalk."""
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    crosswalk = _load(
        root / "federal-defendants-release-family-crosswalk-v1.json",
        "family crosswalk",
    )
    raw_families = crosswalk.get("families")
    if (
        set(crosswalk) != {"schemaVersion", "recordedAt", "publicationId", "families"}
        or crosswalk.get("schemaVersion") != CROSSWALK_SCHEMA
        or crosswalk.get("publicationId") != PUBLICATION_ID
        or not isinstance(raw_families, list)
        or len(raw_families) != EXPECTED_FAMILY_COUNT
    ):
        raise FederalDefendantsReleaseError("family crosswalk schema is invalid")
    sources: dict[tuple[str, int, str], dict[str, Any]] = {}
    for download in inventory["downloads"]:
        if download["kind"] != "cube":
            continue
        for sheet in download["sheets"]:
            if sheet["classification"] != "numbered-data":
                continue
            key = (download["releaseId"], download["downloadOrdinal"], sheet["name"])
            source = {
                "releaseId": download["releaseId"],
                "publicationVintageDate": _publication_vintage_date(
                    download["releaseId"]
                ),
                "downloadOrdinal": download["downloadOrdinal"],
                "cubeId": download["cubeId"],
                "tableNamespace": download["tableNamespace"],
                "physicalSheetName": sheet["name"],
                "physicalTableNumber": sheet["physicalTableNumber"],
                "publishedTitle": sheet["title"],
                "sourcePath": download["path"],
                "sourceDigest": download["contentDigest"],
                "rowClassification": sheet["rowClassification"],
                "principalOffenceClassification": sheet[
                    "principalOffenceClassification"
                ],
                "classificationTreatment": sheet["classificationTreatment"],
                "sentenceClassification": sheet["sentenceClassification"],
                "sentenceTreatment": sheet["sentenceTreatment"],
                "principalSelectionTreatment": sheet["principalSelectionTreatment"],
                "revisionTreatment": sheet["revisionTreatment"],
                "executionCellSelection": sheet["executionCellSelection"],
            }
            if sheet["executionCellSelection"] == (
                "federal-authoritative-range-bounded-v1"
            ):
                source.update(
                    {
                        "authoritativeRange": sheet["authoritativeRange"],
                        "boundedSemanticCellDigest": sheet["boundedSemanticCellDigest"],
                        "outOfRangeExclusionDigest": sheet["outOfRangeExclusionDigest"],
                    }
                )
            sources[key] = source
    registered = _registered_members(project, inventory)
    assigned: set[tuple[str, int, str]] = set()
    family_ids: set[str] = set()
    families: list[dict[str, Any]] = []
    provenance_keys = {
        "rowClassification",
        "principalOffenceClassification",
        "classificationTreatment",
        "sentenceClassification",
        "sentenceTreatment",
        "principalSelectionTreatment",
        "revisionTreatment",
    }
    member_keys = {
        "releaseId",
        "downloadOrdinal",
        "physicalSheetName",
        "publishedTitle",
        *provenance_keys,
    }
    for family in raw_families:
        if (
            not isinstance(family, dict)
            or set(family) != {"familyId", "semanticTitle", "members"}
            or not isinstance(family.get("familyId"), str)
            or not re.fullmatch(r"federal-defendants-[a-z0-9-]+", family["familyId"])
            or family["familyId"] in family_ids
            or not isinstance(family.get("semanticTitle"), str)
            or not family["semanticTitle"]
            or not isinstance(family.get("members"), list)
            or not family["members"]
        ):
            raise FederalDefendantsReleaseError("family declaration is invalid")
        family_ids.add(family["familyId"])
        members: list[dict[str, Any]] = []
        for member in family["members"]:
            if not isinstance(member, dict) or set(member) != member_keys:
                raise FederalDefendantsReleaseError(
                    "family member declaration is invalid"
                )
            key = (
                member.get("releaseId"),
                member.get("downloadOrdinal"),
                member.get("physicalSheetName"),
            )
            source = sources.get(key)
            if (
                key in assigned
                or source is None
                or member.get("publishedTitle") != source["publishedTitle"]
                or any(member.get(field) != source[field] for field in provenance_keys)
            ):
                raise FederalDefendantsReleaseError(
                    "family member does not bind exact source identity and contexts"
                )
            assigned.add(key)
            members.append({**source, "registered": key in registered})
        families.append(
            {
                "familyId": family["familyId"],
                "semanticTitle": family["semanticTitle"],
                "members": members,
            }
        )
    if assigned != set(sources):
        raise FederalDefendantsReleaseError("family crosswalk is not an exact cover")
    if len(registered) != EXPECTED_REGISTERED_COUNT:
        raise FederalDefendantsReleaseError(
            "registered semantic coverage count is invalid"
        )
    membership: dict[str, Any] = {
        "schemaVersion": MEMBERSHIP_SCHEMA,
        "recordedAt": crosswalk["recordedAt"],
        "publicationId": PUBLICATION_ID,
        "familyCount": len(families),
        "numberedDataSheetCount": len(sources),
        "registeredMemberCount": len(registered),
        "pendingSemanticContractCount": len(sources) - len(registered),
        "families": families,
    }
    membership["membershipDigest"] = domain_digest(MEMBERSHIP_SCHEMA, membership)
    return membership


def verify_federal_defendants_release(project_root: Path) -> dict[str, Any]:
    """Verify downloads, all data sheets, semantic cover, and registration state."""
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    ledger = build_bounded_range_exclusion_ledger(project)
    inventory = build_source_inventory(project)
    membership = build_family_membership(project, inventory)
    checked_ledger = _load(
        root / "federal-defendants-bounded-range-exclusions-v1.json",
        "bounded range exclusion ledger",
    )
    checked_inventory = _load(
        root / "federal-defendants-release-source-inventory-v1.json",
        "source inventory",
    )
    checked_membership = _load(
        root / "federal-defendants-release-family-membership-v1.json",
        "family membership",
    )
    if canonical_json_bytes(ledger) != canonical_json_bytes(checked_ledger):
        raise FederalDefendantsReleaseError(
            "bounded range exclusion ledger is not reproducible"
        )
    if canonical_json_bytes(inventory) != canonical_json_bytes(checked_inventory):
        raise FederalDefendantsReleaseError("source inventory is not reproducible")
    if canonical_json_bytes(membership) != canonical_json_bytes(checked_membership):
        raise FederalDefendantsReleaseError("family membership is not reproducible")
    if ledger.get("ledgerDigest") != domain_digest(
        BOUNDED_RANGE_SCHEMA, _without_digest(ledger, "ledgerDigest")
    ):
        raise FederalDefendantsReleaseError(
            "bounded range exclusion ledger digest is invalid"
        )
    if inventory.get("inventoryDigest") != domain_digest(
        INVENTORY_SCHEMA, _without_digest(inventory, "inventoryDigest")
    ):
        raise FederalDefendantsReleaseError("source inventory digest is invalid")
    if membership.get("membershipDigest") != domain_digest(
        MEMBERSHIP_SCHEMA, _without_digest(membership, "membershipDigest")
    ):
        raise FederalDefendantsReleaseError("family membership digest is invalid")
    return {
        "verified": True,
        "releaseCount": len(RELEASES),
        "downloadCount": inventory["downloadCount"],
        "reviewedExclusionDownloadCount": inventory["reviewedExclusionDownloadCount"],
        "substantiveCubeCount": inventory["substantiveCubeCount"],
        "numberedDataSheetCount": inventory["numberedDataSheetCount"],
        "boundedRangeSheetCount": ledger["boundedSheetCount"],
        "boundedRangeExcludedNonblankCellCount": ledger["excludedNonblankCellCount"],
        "familyCount": membership["familyCount"],
        "registeredMemberCount": membership["registeredMemberCount"],
        "pendingSemanticContractCount": membership["pendingSemanticContractCount"],
        "boundedRangeExclusionLedgerDigest": ledger["ledgerDigest"],
        "inventoryDigest": inventory["inventoryDigest"],
        "membershipDigest": membership["membershipDigest"],
        "providerCalls": 0,
    }
