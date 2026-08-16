"""Exact source and family-membership custody for Prisoners in Australia."""

from __future__ import annotations

import copy
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest

DOWNLOAD_SCHEMA = "tidy.prisoners-release-downloads/v1"
CROSSWALK_SCHEMA = "tidy.prisoners-release-family-crosswalk/v1"
INVENTORY_SCHEMA = "tidy.prisoners-release-source-inventory/v1"
MEMBERSHIP_SCHEMA = "tidy.prisoners-release-family-membership/v1"

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_ORDINARY_TABLE = re.compile(r"^Table[_ ]([1-9][0-9]*)$")
_ANZSOC_TABLE = re.compile(r"^ANZSOC 2023 Table ([1-5])$")
_RANGE = re.compile(r"^[A-Z]+[1-9][0-9]*(?::([A-Z]+)([1-9][0-9]*))?$")
_EXPECTED_RELEASE_COUNTS = {2021: 42, 2022: 39, 2023: 39, 2024: 39, 2025: 44}


class PrisonersReleaseError(RuntimeError):
    """The checked release inventory or membership closure is invalid."""


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PrisonersReleaseError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise PrisonersReleaseError(f"{label} must be an object")
    return value


def _safe_file(root: Path, relative: str, label: str) -> Path:
    candidate = root / relative
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if (
        not resolved.is_relative_to(resolved_root)
        or candidate.is_symlink()
        or not resolved.is_file()
    ):
        raise PrisonersReleaseError(f"{label} path is unsafe or missing")
    return resolved


def _column_number(label: str) -> int:
    value = 0
    for character in label:
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _dimensions(reference: str | None) -> tuple[int, int]:
    if not isinstance(reference, str):
        return 0, 0
    match = _RANGE.fullmatch(reference)
    if match is None:
        return 0, 0
    if match.group(1) is None:
        first = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", reference)
        assert first is not None
        return int(first.group(2)), _column_number(first.group(1))
    return int(match.group(2)), _column_number(match.group(1))


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(text.text or "" for text in item.iter(f"{{{_MAIN}}}t"))
        for item in root.findall(f"{{{_MAIN}}}si")
    ]


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        item.get("Id"): item.get("Target")
        for item in relationships.findall(f"{{{_PKG_REL}}}Relationship")
    }
    result: list[tuple[str, str, str]] = []
    sheets = workbook.find(f"{{{_MAIN}}}sheets")
    if sheets is None:
        raise PrisonersReleaseError("workbook has no sheets")
    for sheet in sheets:
        name = sheet.get("name")
        state = sheet.get("state", "visible")
        target = targets.get(sheet.get(f"{{{_DOC_REL}}}id"))
        if not isinstance(name, str) or not isinstance(target, str):
            raise PrisonersReleaseError("workbook sheet relationship is invalid")
        normalized = PurePosixPath(target.lstrip("/"))
        if normalized.parts[:1] == ("xl",):
            path = normalized.as_posix()
        else:
            path = (PurePosixPath("xl") / normalized).as_posix()
        result.append((name, state, path))
    return result


def _cell_payload(cell: ET.Element, shared: list[str]) -> tuple[str | None, str | None]:
    formula = cell.find(f"{{{_MAIN}}}f")
    formula_text = formula.text if formula is not None else None
    cell_type = cell.get("t")
    value = cell.find(f"{{{_MAIN}}}v")
    if cell_type == "inlineStr":
        scalar = "".join(item.text or "" for item in cell.iter(f"{{{_MAIN}}}t"))
    elif value is None or value.text is None:
        scalar = None
    elif cell_type == "s":
        try:
            scalar = shared[int(value.text)]
        except (ValueError, IndexError) as error:
            raise PrisonersReleaseError("shared-string index is invalid") from error
    else:
        scalar = value.text
    return formula_text, scalar


def inspect_workbook(path: Path) -> list[dict[str, Any]]:
    """Inspect sheet identity and semantic cell payloads using stdlib XLSX XML."""
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        result: list[dict[str, Any]] = []
        for name, state, target in _sheet_targets(archive):
            root = ET.fromstring(archive.read(target))
            dimension = root.find(f"{{{_MAIN}}}dimension")
            max_row, max_column = _dimensions(
                dimension.get("ref") if dimension is not None else None
            )
            cells: list[dict[str, str]] = []
            visible_values: list[str] = []
            for cell in root.findall(f".//{{{_MAIN}}}c"):
                address = cell.get("r")
                formula, scalar = _cell_payload(cell, shared)
                if scalar not in (None, ""):
                    visible_values.append(scalar)
                if isinstance(address, str) and (
                    formula is not None or scalar not in (None, "")
                ):
                    payload = {"address": address}
                    if formula is not None:
                        payload["formula"] = formula
                    if scalar not in (None, ""):
                        payload["value"] = scalar
                    cells.append(payload)
            title = next(
                (
                    value
                    for value in visible_values
                    if re.match(r"^(?:ANZSOC 2023 )?Table [1-9][0-9]*\b", value)
                ),
                None,
            )
            ordinary = _ORDINARY_TABLE.fullmatch(name)
            anzsoc = _ANZSOC_TABLE.fullmatch(name)
            classification = "numbered-data" if ordinary or anzsoc else "non-data"
            sheet: dict[str, Any] = {
                "name": name,
                "state": state,
                "classification": classification,
                "title": title,
                "maxRow": max_row,
                "maxColumn": max_column,
                "semanticCellCount": len(cells),
                "semanticCellDigest": domain_digest(
                    "tidy.xlsx-semantic-cells/v1", cells
                ),
            }
            if ordinary:
                sheet["tableNamespace"] = "ordinary"
                sheet["physicalTableNumber"] = int(ordinary.group(1))
            elif anzsoc:
                sheet["tableNamespace"] = "anzsoc-2023"
                sheet["physicalTableNumber"] = int(anzsoc.group(1))
            result.append(sheet)
        return result


def semantic_cells(path: Path) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        result: dict[tuple[str, str], tuple[str | None, str | None]] = {}
        for name, _state, target in _sheet_targets(archive):
            root = ET.fromstring(archive.read(target))
            for cell in root.findall(f".//{{{_MAIN}}}c"):
                address = cell.get("r")
                formula, scalar = _cell_payload(cell, shared)
                if isinstance(address, str) and (
                    formula is not None or scalar not in (None, "")
                ):
                    result[(name, address)] = (formula, scalar)
        return result


def _semantic_parity(left: Path, right: Path) -> dict[str, Any]:
    left_cells = semantic_cells(left)
    right_cells = semantic_cells(right)
    left_payload = [
        [sheet, address, formula, value]
        for (sheet, address), (formula, value) in sorted(left_cells.items())
    ]
    right_payload = [
        [sheet, address, formula, value]
        for (sheet, address), (formula, value) in sorted(right_cells.items())
    ]
    return {
        "coordinateValueFormulaParity": left_payload == right_payload,
        "leftSemanticCellCount": len(left_payload),
        "rightSemanticCellCount": len(right_payload),
        "leftSemanticCellDigest": domain_digest(
            "tidy.xlsx-semantic-cell-map/v1", left_payload
        ),
        "rightSemanticCellDigest": domain_digest(
            "tidy.xlsx-semantic-cell-map/v1", right_payload
        ),
    }


def build_source_inventory(project_root: Path) -> dict[str, Any]:
    project = project_root.resolve()
    fixture_root = project / "fixtures" / "product-prototype"
    downloads = _load(
        fixture_root / "prisoners-release-downloads-v1.json", "download custody"
    )
    declarations = downloads.get("downloads")
    if (
        set(downloads)
        != {"schemaVersion", "recordedAt", "publicationId", "releases", "downloads"}
        or downloads.get("schemaVersion") != DOWNLOAD_SCHEMA
        or downloads.get("publicationId") != "prisoners-australia"
        or downloads.get("releases") != [2021, 2022, 2023, 2024, 2025]
        or not isinstance(declarations, list)
        or len(declarations) != 22
    ):
        raise PrisonersReleaseError("download custody schema is invalid")
    output_downloads: list[dict[str, Any]] = []
    release_counts = {year: 0 for year in _EXPECTED_RELEASE_COUNTS}
    download_keys: set[tuple[int, int]] = set()
    declaration_keys = {
        "year",
        "downloadOrdinal",
        "kind",
        "cubeId",
        "tableNamespace",
        "url",
        "path",
        "contentDigest",
        "byteLength",
        "expectedNumberedSheetCount",
    }
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) != declaration_keys:
            raise PrisonersReleaseError("download declaration is invalid")
        year = declaration.get("year")
        ordinal = declaration.get("downloadOrdinal")
        relative = declaration.get("path")
        identity = (year, ordinal)
        if (
            isinstance(year, bool)
            or year not in release_counts
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or identity in download_keys
            or not isinstance(relative, str)
            or not relative
            or not isinstance(declaration.get("url"), str)
            or not declaration["url"].startswith(
                f"https://www.abs.gov.au/statistics/people/crime-and-justice/prisoners-australia/{year}/"
            )
        ):
            raise PrisonersReleaseError("download identity or path is invalid")
        download_keys.add(identity)
        path = _safe_file(fixture_root, relative, "download")
        data = path.read_bytes()
        if len(data) != declaration.get("byteLength") or sha256_digest(
            data
        ) != declaration.get("contentDigest"):
            raise PrisonersReleaseError(f"download custody mismatch: {relative}")
        sheets = inspect_workbook(path)
        numbered = [
            item for item in sheets if item["classification"] == "numbered-data"
        ]
        if len(numbered) != declaration.get("expectedNumberedSheetCount"):
            raise PrisonersReleaseError(f"numbered-sheet count mismatch: {relative}")
        release_counts[year] += len(numbered)
        output_downloads.append({**declaration, "sheets": sheets})
    if (
        release_counts != _EXPECTED_RELEASE_COUNTS
        or sum(item.get("kind") == "guide" for item in declarations) != 5
        or sum(item.get("kind") == "cube" for item in declarations) != 17
    ):
        raise PrisonersReleaseError("release worksheet counts are invalid")
    current = (
        fixture_root / "workbooks/prisoners-australia-2025-states-current-source.xlsx"
    )
    historical = fixture_root / "workbooks/prisoners-australia-2025.xlsx"
    execution = (
        fixture_root / "workbooks/prisoners-australia-2025-batch-normalized.xlsx"
    )
    parity = _semantic_parity(current, historical)
    execution_parity = _semantic_parity(historical, execution)
    if (
        not parity["coordinateValueFormulaParity"]
        or not execution_parity["coordinateValueFormulaParity"]
    ):
        raise PrisonersReleaseError(
            "2025 state source derivation changes semantic cells"
        )
    inventory: dict[str, Any] = {
        "schemaVersion": INVENTORY_SCHEMA,
        "recordedAt": downloads["recordedAt"],
        "publicationId": "prisoners-australia",
        "releaseCounts": {str(key): value for key, value in release_counts.items()},
        "downloadCount": len(output_downloads),
        "substantiveCubeCount": sum(
            item["kind"] == "cube" for item in output_downloads
        ),
        "numberedDataSheetCount": sum(release_counts.values()),
        "reviewedExclusionCount": sum(
            item["classification"] == "non-data"
            for download in output_downloads
            for item in download["sheets"]
        ),
        "downloads": output_downloads,
        "state2025Derivation": {
            "currentOfficialSourcePath": current.relative_to(fixture_root).as_posix(),
            "currentOfficialSourceDigest": sha256_digest(current.read_bytes()),
            "historicalSourcePath": historical.relative_to(fixture_root).as_posix(),
            "historicalSourceDigest": sha256_digest(historical.read_bytes()),
            "executionWorkbookPath": execution.relative_to(fixture_root).as_posix(),
            "executionWorkbookDigest": sha256_digest(execution.read_bytes()),
            "currentToHistoricalParity": parity,
            "historicalToExecutionParity": execution_parity,
        },
    }
    inventory["inventoryDigest"] = domain_digest(INVENTORY_SCHEMA, inventory)
    return inventory


def build_family_membership(
    project_root: Path, inventory: dict[str, Any]
) -> dict[str, Any]:
    project = project_root.resolve()
    fixture_root = project / "fixtures" / "product-prototype"
    crosswalk = _load(
        fixture_root / "prisoners-release-family-crosswalk-v1.json",
        "family crosswalk",
    )
    raw_families = crosswalk.get("families")
    if (
        set(crosswalk) != {"schemaVersion", "recordedAt", "publicationId", "families"}
        or crosswalk.get("schemaVersion") != CROSSWALK_SCHEMA
        or crosswalk.get("publicationId") != "prisoners-australia"
        or not isinstance(raw_families, list)
        or len(raw_families) != 48
    ):
        raise PrisonersReleaseError("family crosswalk schema is invalid")
    source_members: dict[tuple[int, int, str], dict[str, Any]] = {}
    for download in inventory["downloads"]:
        for sheet in download["sheets"]:
            if sheet["classification"] != "numbered-data":
                continue
            key = (download["year"], download["downloadOrdinal"], sheet["name"])
            if key in source_members:
                raise PrisonersReleaseError("source inventory repeats a numbered sheet")
            source_members[key] = {
                "year": download["year"],
                "downloadOrdinal": download["downloadOrdinal"],
                "cubeId": download["cubeId"],
                "sheet": sheet["name"],
                "tableNamespace": sheet["tableNamespace"],
                "physicalTableNumber": sheet["physicalTableNumber"],
                "publishedTitle": sheet["title"],
                "sourcePath": download["path"],
                "sourceDigest": download["contentDigest"],
            }
    assigned: dict[tuple[int, int, str], str] = {}
    families: list[dict[str, Any]] = []
    family_ids: set[str] = set()
    for family in raw_families:
        if (
            not isinstance(family, dict)
            or set(family) != {"familyId", "members"}
            or not isinstance(family.get("familyId"), str)
            or not family["familyId"]
            or family["familyId"] in family_ids
            or not isinstance(family.get("members"), list)
            or not family["members"]
        ):
            raise PrisonersReleaseError("family crosswalk entry is invalid")
        family_id = family["familyId"]
        family_ids.add(family_id)
        members: list[dict[str, Any]] = []
        for raw in family["members"]:
            if not isinstance(raw, dict) or set(raw) != {"year", "cube", "sheet"}:
                raise PrisonersReleaseError("family crosswalk member is invalid")
            key = (raw.get("year"), raw.get("cube"), raw.get("sheet"))
            source = source_members.get(key)
            if source is None:
                raise PrisonersReleaseError(
                    f"crosswalk member is not published: {key!r}"
                )
            if key in assigned:
                raise PrisonersReleaseError(f"crosswalk duplicates {key!r}")
            assigned[key] = family_id
            members.append({**source, "familyId": family_id})
        years = sorted({item["year"] for item in members})
        allowed_years = {
            (2025,): "new-in-2025",
            (2021,): "discontinued-after-2021",
            (2021, 2022, 2023, 2024): "discontinued-after-2024",
            (2021, 2022, 2023, 2024, 2025): "published-2021-2025",
        }
        availability = allowed_years.get(tuple(years))
        if availability is None:
            raise PrisonersReleaseError(
                f"family {family_id!r} has fabricated availability {years!r}"
            )
        families.append(
            {
                "familyId": family_id,
                "availability": availability,
                "years": years,
                "members": members,
            }
        )
    if set(assigned) != set(source_members):
        missing = sorted(set(source_members) - set(assigned))
        extra = sorted(set(assigned) - set(source_members))
        raise PrisonersReleaseError(
            f"family crosswalk is not exact: missing={missing!r}, extra={extra!r}"
        )
    membership: dict[str, Any] = {
        "schemaVersion": MEMBERSHIP_SCHEMA,
        "recordedAt": crosswalk["recordedAt"],
        "publicationId": "prisoners-australia",
        "sourceInventoryDigest": inventory["inventoryDigest"],
        "familyCount": len(families),
        "memberCount": len(assigned),
        "families": families,
    }
    membership["membershipDigest"] = domain_digest(MEMBERSHIP_SCHEMA, membership)
    return membership


def _semantic_without_digest(value: dict[str, Any], field: str) -> dict[str, Any]:
    semantic = copy.deepcopy(value)
    semantic.pop(field, None)
    return semantic


def _registered_members(
    project: Path, membership: dict[str, Any]
) -> set[tuple[int, int, str]]:
    fixture_root = project / "fixtures" / "product-prototype"
    status = _load(fixture_root / "data-asset-status-v1.json", "status registry")
    source_families = {
        (member["year"], member["downloadOrdinal"], member["sheet"]): family["familyId"]
        for family in membership["families"]
        for member in family["members"]
    }
    registered: set[tuple[int, int, str]] = set()
    for declaration in status.get("cohorts", []):
        cohort_path = declaration.get("cohortPath")
        if not isinstance(cohort_path, str):
            raise PrisonersReleaseError("status cohort path is invalid")
        cohort_file = _safe_file(project, cohort_path, "status cohort")
        cohort = _load(cohort_file, "registered cohort")
        if cohort.get("publicationId") != "prisoners-australia":
            continue
        family_id = cohort.get("tableFamilyId")
        if not isinstance(family_id, str):
            raise PrisonersReleaseError("registered family identity is invalid")
        for workbook in cohort.get("workbooks", []):
            year = workbook.get("year")
            sheet = workbook.get("sheet")
            candidates = [
                key for key in source_families if key[0] == year and key[2] == sheet
            ]
            if len(candidates) != 1:
                raise PrisonersReleaseError(
                    "registered workbook does not resolve to one release member"
                )
            key = candidates[0]
            if source_families[key] != family_id:
                raise PrisonersReleaseError(
                    "registered workbook is assigned to the wrong family"
                )
            if key in registered:
                raise PrisonersReleaseError("registered workbook is duplicated")
            registered.add(key)
    return registered


def verify_prisoners_release(project_root: Path) -> dict[str, Any]:
    project = project_root.resolve()
    fixture_root = project / "fixtures" / "product-prototype"
    inventory_path = fixture_root / "prisoners-release-source-inventory-v1.json"
    membership_path = fixture_root / "prisoners-release-family-membership-v1.json"
    generated_inventory = build_source_inventory(project)
    generated_membership = build_family_membership(project, generated_inventory)
    inventory = _load(inventory_path, "source inventory")
    membership = _load(membership_path, "family membership")
    if canonical_json_bytes(inventory) != canonical_json_bytes(generated_inventory):
        raise PrisonersReleaseError("source inventory is not reproducible")
    if canonical_json_bytes(membership) != canonical_json_bytes(generated_membership):
        raise PrisonersReleaseError("family membership is not reproducible")
    if inventory.get("inventoryDigest") != domain_digest(
        INVENTORY_SCHEMA, _semantic_without_digest(inventory, "inventoryDigest")
    ):
        raise PrisonersReleaseError("source inventory digest is invalid")
    if membership.get("membershipDigest") != domain_digest(
        MEMBERSHIP_SCHEMA, _semantic_without_digest(membership, "membershipDigest")
    ):
        raise PrisonersReleaseError("family membership digest is invalid")
    source_keys = {
        (member["year"], member["downloadOrdinal"], member["sheet"])
        for family in membership["families"]
        for member in family["members"]
    }
    registered = _registered_members(project, membership)
    if not registered <= source_keys:
        raise PrisonersReleaseError("registered Prisoners coverage escapes membership")
    pending = len(source_keys) - len(registered)
    return {
        "verified": True,
        "releaseCount": 5,
        "downloadCount": inventory["downloadCount"],
        "substantiveCubeCount": inventory["substantiveCubeCount"],
        "numberedDataSheetCount": inventory["numberedDataSheetCount"],
        "familyCount": membership["familyCount"],
        "registeredMemberCount": len(registered),
        "pendingSemanticContractCount": pending,
        "providerCalls": 0,
        "inventoryDigest": inventory["inventoryDigest"],
        "membershipDigest": membership["membershipDigest"],
    }
