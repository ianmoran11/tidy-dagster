"""Exact source and family-membership custody for Recorded Crime — Offenders."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

DOWNLOAD_SCHEMA = "tidy.offenders-release-downloads/v1"
CROSSWALK_SCHEMA = "tidy.offenders-release-family-crosswalk/v1"
INVENTORY_SCHEMA = "tidy.offenders-release-source-inventory/v1"
MEMBERSHIP_SCHEMA = "tidy.offenders-release-family-membership/v1"
PUBLICATION_ID = "recorded-crime-offenders"
RELEASES = ["2021-22", "2022-23", "2023-24", "2024-25"]
EXPECTED_RELEASE_COUNTS = {"2021-22": 47, "2022-23": 47, "2023-24": 48, "2024-25": 48}
EXPECTED_DOWNLOAD_COUNTS = {"2021-22": 9, "2022-23": 8, "2023-24": 8, "2024-25": 8}
# Tuple position is the exact download ordinal. This declaratively binds kind,
# semantic cube, and table namespace for every release download.
EXPECTED_RELEASE_DOWNLOADS = {
    "2021-22": (
        ("guide", "guide", None),
        ("cube", "offenders-australia", "main"),
        ("cube", "states-territories", "main"),
        ("cube", "youth", "main"),
        ("cube", "indigenous", "main"),
        ("cube", "police-proceedings", "main"),
        ("cube", "family-domestic-violence", "family-domestic-violence"),
        ("cube", "covid-19", "covid-19"),
        ("concordance", "table-concordance", None),
    ),
    "2022-23": (
        ("guide", "guide", None),
        ("cube", "offenders-australia", "main"),
        ("cube", "states-territories", "main"),
        ("cube", "youth", "main"),
        ("cube", "indigenous", "main"),
        ("cube", "police-proceedings", "main"),
        ("cube", "family-domestic-violence", "family-domestic-violence"),
        ("concordance", "table-concordance", None),
    ),
    "2023-24": (
        ("guide", "guide", None),
        ("cube", "offenders-australia", "main"),
        ("cube", "states-territories", "main"),
        ("cube", "youth", "main"),
        ("cube", "indigenous", "main"),
        ("cube", "police-proceedings", "main"),
        ("cube", "family-domestic-violence", "family-domestic-violence"),
        ("cube", "preliminary-anzsoc-2023", "preliminary-anzsoc-2023"),
    ),
    "2024-25": (
        ("guide", "guide", None),
        ("cube", "offenders-australia", "main"),
        ("cube", "states-territories", "main"),
        ("cube", "youth", "main"),
        ("cube", "indigenous", "main"),
        ("cube", "police-proceedings", "main"),
        ("cube", "family-domestic-violence", "family-domestic-violence"),
        ("cube", "preliminary-anzsoc-2023", "preliminary-anzsoc-2023"),
    ),
}
EXPECTED_RELEASE_KINDS = {
    release: {
        kind: sum(item[0] == kind for item in downloads)
        for kind in ("cube", "guide", "concordance")
    }
    for release, downloads in EXPECTED_RELEASE_DOWNLOADS.items()
}
EXPECTED_CUBE_TABLES = {
    "offenders-australia": {release: tuple(range(1, 6)) for release in RELEASES},
    "states-territories": {release: tuple(range(6, 18)) for release in RELEASES},
    "youth": {
        "2021-22": tuple(range(18, 23)),
        "2022-23": tuple(range(18, 26)),
        "2023-24": tuple(range(18, 26)),
        "2024-25": tuple(range(18, 26)),
    },
    "indigenous": {
        "2021-22": tuple(range(23, 27)),
        "2022-23": tuple(range(26, 30)),
        "2023-24": tuple(range(26, 30)),
        "2024-25": tuple(range(26, 30)),
    },
    "police-proceedings": {
        "2021-22": tuple(range(27, 34)),
        "2022-23": tuple(range(30, 37)),
        "2023-24": tuple(range(30, 37)),
        "2024-25": tuple(range(30, 37)),
    },
    "family-domestic-violence": {
        "2021-22": tuple(range(1, 12)),
        "2022-23": tuple(range(37, 48)),
        "2023-24": tuple(range(37, 48)),
        "2024-25": tuple(range(37, 48)),
    },
    "covid-19": {"2021-22": (1, 2, 3)},
    "preliminary-anzsoc-2023": {"2023-24": (1,), "2024-25": (1,)},
}
# Published wording differs by year in the FDV experimental prefix and in
# full-name versus acronym titles. These are the only accepted semantic aliases.
CUBE_TITLE_ALIASES = {
    "offenders-australia": ("offenders,", "offender rate,"),
    "states-territories": (
        "states and territories",
        "new south wales",
        "victoria",
        "queensland",
        "south australia",
        "western australia",
        "tasmania",
        "northern territory",
        "australian capital territory",
    ),
    "youth": ("youth offenders,",),
    "indigenous": ("indigenous status",),
    "police-proceedings": ("police proceedings",),
    "family-domestic-violence": ("family and domestic violence", "fdv"),
    "covid-19": ("covid-19",),
    "preliminary-anzsoc-2023": ("preliminary anzsoc 2023",),
}
EXPECTED_FAMILY_SHAPES = {
    "published-2021-2024": 43,
    "discontinued-after-2021": 4,
    "introduced-2022": 4,
    "introduced-2023": 1,
}
REGISTERED_FAMILY_IDS = {
    "offenders-by-principal-offence-and-period",
    "offenders-by-sex-principal-offence-and-period",
    "offenders-by-principal-offence-age-and-period",
    "offender-rates-by-principal-offence-age-and-period",
    "offenders-by-sex-age-period-and-statistic",
}

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NUMBERED_TABLE = re.compile(r"^Table ([1-9][0-9]*)$")
_CELL = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$")
_RANGE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)(?::([A-Z]{1,3})([1-9][0-9]*))?$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class OffendersReleaseError(RuntimeError):
    """The checked Offenders release inventory or membership is invalid."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha256_digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _domain_digest(domain: str, value: Any) -> str:
    return _sha256_digest(domain.encode() + b"\x00" + _canonical_json_bytes(value))


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise OffendersReleaseError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise OffendersReleaseError(f"{label} must be an object")
    return value


def _safe_file(root: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise OffendersReleaseError(f"{label} path is invalid")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise OffendersReleaseError(f"{label} path is unsafe or missing")
    candidate = root / relative
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if (
        not resolved.is_relative_to(resolved_root)
        or candidate.is_symlink()
        or not resolved.is_file()
    ):
        raise OffendersReleaseError(f"{label} path is unsafe or missing")
    return resolved


def _column_number(label: str) -> int:
    value = 0
    for character in label:
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _declared_geometry(reference: str | None) -> tuple[int, int]:
    if not isinstance(reference, str):
        return 0, 0
    match = _RANGE.fullmatch(reference)
    if match is None:
        raise OffendersReleaseError(f"worksheet dimension is invalid: {reference!r}")
    column = match.group(3) or match.group(1)
    row = match.group(4) or match.group(2)
    return int(row), _column_number(column)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        payload = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(payload)
    return [
        "".join(text.text or "" for text in item.iter(f"{{{_MAIN}}}t"))
        for item in root.findall(f"{{{_MAIN}}}si")
    ]


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets: dict[str, tuple[str | None, str | None]] = {}
    for item in relationships.findall(f"{{{_PKG_REL}}}Relationship"):
        relationship_id = item.get("Id")
        if not relationship_id or relationship_id in targets:
            raise OffendersReleaseError("workbook relationship identity is invalid")
        targets[relationship_id] = (item.get("Target"), item.get("TargetMode"))
    sheets = workbook.find(f"{{{_MAIN}}}sheets")
    if sheets is None:
        raise OffendersReleaseError("workbook has no sheets")
    result: list[tuple[str, str, str]] = []
    seen_names: set[str] = set()
    seen_targets: set[str] = set()
    archive_names = set(archive.namelist())
    for sheet in sheets:
        name = sheet.get("name")
        state = sheet.get("state", "visible")
        relationship = targets.get(sheet.get(f"{{{_DOC_REL}}}id"))
        if (
            not isinstance(name, str)
            or not name
            or name in seen_names
            or state not in {"visible", "hidden", "veryHidden"}
            or relationship is None
        ):
            raise OffendersReleaseError("workbook sheet relationship is invalid")
        target, target_mode = relationship
        if not isinstance(target, str) or target_mode == "External":
            raise OffendersReleaseError("worksheet target is external or invalid")
        pure = PurePosixPath(target)
        parts = pure.parts[1:] if pure.is_absolute() else ("xl", *pure.parts)
        if ".." in parts or not parts:
            raise OffendersReleaseError("worksheet target escapes the workbook")
        path = PurePosixPath(*parts).as_posix()
        if not path.startswith("xl/worksheets/") or path not in archive_names:
            raise OffendersReleaseError("worksheet target is missing or invalid")
        if path in seen_targets:
            raise OffendersReleaseError("worksheet target is duplicated")
        seen_names.add(name)
        seen_targets.add(path)
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
            index = int(value.text)
            if index < 0:
                raise IndexError
            scalar = shared[index]
        except (ValueError, IndexError) as error:
            raise OffendersReleaseError("shared-string index is invalid") from error
    else:
        scalar = value.text
    return formula_text, scalar


def inspect_workbook(
    path: Path,
    *,
    table_namespace: str | None = None,
    kind: str = "cube",
) -> list[dict[str, Any]]:
    """Inspect exact sheet identity and semantic OOXML cell payloads."""
    try:
        with zipfile.ZipFile(path) as archive:
            shared = _shared_strings(archive)
            result: list[dict[str, Any]] = []
            for name, state, target in _sheet_targets(archive):
                root = ET.fromstring(archive.read(target))
                dimension = root.find(f"{{{_MAIN}}}dimension")
                declared_row, declared_column = _declared_geometry(
                    dimension.get("ref") if dimension is not None else None
                )
                cells: list[dict[str, str]] = []
                visible_values: list[str] = []
                rows: list[int] = []
                columns: list[int] = []
                for cell in root.findall(f".//{{{_MAIN}}}c"):
                    address = cell.get("r")
                    formula, scalar = _cell_payload(cell, shared)
                    meaningful = formula is not None or scalar not in (None, "")
                    if scalar not in (None, ""):
                        visible_values.append(scalar)
                    if not meaningful:
                        continue
                    if (
                        not isinstance(address, str)
                        or (match := _CELL.fullmatch(address)) is None
                    ):
                        raise OffendersReleaseError("semantic cell address is invalid")
                    rows.append(int(match.group(2)))
                    columns.append(_column_number(match.group(1)))
                    payload = {"address": address}
                    if formula is not None:
                        payload["formula"] = formula
                    if scalar not in (None, ""):
                        payload["value"] = scalar
                    cells.append(payload)
                cells.sort(key=lambda item: item["address"])
                title = next(
                    (
                        value
                        for value in visible_values
                        if re.match(r"^(?:ANZSOC 2023 )?Table [1-9][0-9]*\b", value)
                    ),
                    None,
                )
                recognized = _NUMBERED_TABLE.fullmatch(name.strip())
                classification = "numbered-data" if recognized else "non-data"
                if classification == "numbered-data" and kind != "cube":
                    raise OffendersReleaseError(
                        "reviewed exclusion contains a numbered sheet"
                    )
                sheet: dict[str, Any] = {
                    "name": name,
                    "state": state,
                    "classification": classification,
                    "title": title,
                    "declaredMaxRow": declared_row,
                    "declaredMaxColumn": declared_column,
                    "semanticMinRow": min(rows, default=0),
                    "semanticMinColumn": min(columns, default=0),
                    "semanticMaxRow": max(rows, default=0),
                    "semanticMaxColumn": max(columns, default=0),
                    "semanticCellCount": len(cells),
                    "semanticCellDigest": _domain_digest(
                        "tidy.xlsx-semantic-cells/v1", cells
                    ),
                }
                if recognized:
                    if table_namespace is None:
                        raise OffendersReleaseError(
                            "numbered sheet has no declared namespace"
                        )
                    sheet["tableNamespace"] = table_namespace
                    sheet["physicalTableNumber"] = int(recognized.group(1))
                result.append(sheet)
            return result
    except OffendersReleaseError:
        raise
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile) as error:
        raise OffendersReleaseError(f"workbook is invalid: {path.name}") from error


def semantic_cells(path: Path) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    """Return formula/cached-value cells by exact physical sheet and coordinate."""
    try:
        with zipfile.ZipFile(path) as archive:
            shared = _shared_strings(archive)
            result: dict[tuple[str, str], tuple[str | None, str | None]] = {}
            for name, _state, target in _sheet_targets(archive):
                root = ET.fromstring(archive.read(target))
                for cell in root.findall(f".//{{{_MAIN}}}c"):
                    address = cell.get("r")
                    formula, scalar = _cell_payload(cell, shared)
                    if formula is None and scalar in (None, ""):
                        continue
                    if not isinstance(address, str) or _CELL.fullmatch(address) is None:
                        raise OffendersReleaseError("semantic cell address is invalid")
                    key = (name, address)
                    if key in result:
                        raise OffendersReleaseError("semantic cell is duplicated")
                    result[key] = (formula, scalar)
            return result
    except OffendersReleaseError:
        raise
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile) as error:
        raise OffendersReleaseError(f"workbook is invalid: {path.name}") from error


def _validate_download_identity(declaration: dict[str, Any]) -> None:
    release = declaration["releaseId"]
    ordinal = declaration["downloadOrdinal"]
    try:
        expected_kind, expected_cube, expected_namespace = EXPECTED_RELEASE_DOWNLOADS[
            release
        ][ordinal]
    except (KeyError, IndexError, TypeError) as error:
        raise OffendersReleaseError("download release or ordinal is invalid") from error
    actual = (
        declaration["kind"],
        declaration["cubeId"],
        declaration["tableNamespace"],
    )
    if actual != (expected_kind, expected_cube, expected_namespace):
        raise OffendersReleaseError(
            "download kind, cube, or namespace disagrees with its release ordinal"
        )
    if expected_kind == "guide":
        if (
            declaration["expectedSheetNames"] != ["Guide"]
            or declaration["expectedNumberedSheetCount"] != 0
        ):
            raise OffendersReleaseError(
                "guide declaration must be exactly one Guide sheet"
            )
        return
    if expected_kind == "concordance":
        if (
            declaration["expectedSheetNames"] != ["Table Concordance"]
            or declaration["expectedNumberedSheetCount"] != 0
        ):
            raise OffendersReleaseError(
                "concordance declaration must be exactly one Table Concordance sheet"
            )
        return
    table_numbers = EXPECTED_CUBE_TABLES[expected_cube][release]
    table_names = [f"Table {number}" for number in table_numbers]
    if expected_cube == "covid-19":
        table_names[0] = "Table 1 "
    if declaration["expectedSheetNames"] != ["Contents", *table_names] or declaration[
        "expectedNumberedSheetCount"
    ] != len(table_numbers):
        raise OffendersReleaseError(
            "cube declaration sheet inventory disagrees with release and cube"
        )


def _validate_title(
    release: str,
    cube_id: str,
    namespace: str,
    sheet: dict[str, Any],
) -> None:
    title = sheet.get("title")
    number = sheet["physicalTableNumber"]
    if number not in EXPECTED_CUBE_TABLES.get(cube_id, {}).get(release, ()):
        raise OffendersReleaseError("physical table is invalid for release and cube")
    if not isinstance(title, str):
        raise OffendersReleaseError("numbered sheet has no published title")
    expected = rf"^(?:ANZSOC 2023 )?Table {number}\b"
    if re.match(expected, title) is None:
        raise OffendersReleaseError("published title disagrees with physical table")
    is_preliminary = namespace == "preliminary-anzsoc-2023"
    if is_preliminary != title.startswith("ANZSOC 2023 Table "):
        raise OffendersReleaseError("published title disagrees with table namespace")
    semantic_title = title.casefold()
    if not any(alias in semantic_title for alias in CUBE_TITLE_ALIASES[cube_id]):
        raise OffendersReleaseError("published title disagrees with semantic cube")


def build_source_inventory(project_root: Path) -> dict[str, Any]:
    project = project_root.resolve()
    fixture_root = project / "fixtures" / "product-prototype"
    downloads = _load(
        fixture_root / "offenders-release-downloads-v1.json", "download custody"
    )
    declarations = downloads.get("downloads")
    if (
        set(downloads)
        != {"schemaVersion", "recordedAt", "publicationId", "releases", "downloads"}
        or downloads.get("schemaVersion") != DOWNLOAD_SCHEMA
        or downloads.get("publicationId") != PUBLICATION_ID
        or downloads.get("releases") != RELEASES
        or not isinstance(declarations, list)
        or len(declarations) != 33
    ):
        raise OffendersReleaseError("download custody schema is invalid")
    declaration_keys = {
        "releaseId",
        "downloadOrdinal",
        "kind",
        "cubeId",
        "tableNamespace",
        "url",
        "path",
        "contentDigest",
        "byteLength",
        "expectedSheetNames",
        "expectedNumberedSheetCount",
    }
    release_counts = {release: 0 for release in RELEASES}
    release_download_ordinals = {release: set() for release in RELEASES}
    paths: set[str] = set()
    urls: set[str] = set()
    output_downloads: list[dict[str, Any]] = []
    total_bytes = 0
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) != declaration_keys:
            raise OffendersReleaseError("download declaration is invalid")
        release = declaration.get("releaseId")
        ordinal = declaration.get("downloadOrdinal")
        kind = declaration.get("kind")
        cube_id = declaration.get("cubeId")
        namespace = declaration.get("tableNamespace")
        relative = declaration.get("path")
        url = declaration.get("url")
        digest = declaration.get("contentDigest")
        byte_length = declaration.get("byteLength")
        expected_sheets = declaration.get("expectedSheetNames")
        expected_numbered = declaration.get("expectedNumberedSheetCount")
        if (
            release not in RELEASES
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 0
            or ordinal in release_download_ordinals[release]
            or kind not in {"cube", "guide", "concordance"}
            or not isinstance(cube_id, str)
            or not cube_id
            or (kind == "cube") != isinstance(namespace, str)
            or (
                isinstance(namespace, str)
                and namespace
                not in {
                    "main",
                    "family-domestic-violence",
                    "covid-19",
                    "preliminary-anzsoc-2023",
                }
            )
            or not isinstance(url, str)
            or not url.startswith(
                f"https://www.abs.gov.au/statistics/people/crime-and-justice/recorded-crime-offenders/{release}/"
            )
            or url in urls
            or not isinstance(relative, str)
            or not relative.startswith("workbooks/recorded-crime-offenders-")
            or not relative.endswith("-source.xlsx")
            or relative in paths
            or not isinstance(digest, str)
            or _DIGEST.fullmatch(digest) is None
            or isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length <= 0
            or not isinstance(expected_sheets, list)
            or not expected_sheets
            or any(not isinstance(name, str) or not name for name in expected_sheets)
            or len(set(expected_sheets)) != len(expected_sheets)
            or isinstance(expected_numbered, bool)
            or not isinstance(expected_numbered, int)
            or expected_numbered < 0
        ):
            raise OffendersReleaseError("download identity or custody is invalid")
        _validate_download_identity(declaration)
        release_download_ordinals[release].add(ordinal)
        paths.add(relative)
        urls.add(url)
        path = _safe_file(fixture_root, relative, "download")
        data = path.read_bytes()
        if len(data) != byte_length or _sha256_digest(data) != digest:
            raise OffendersReleaseError(f"download custody mismatch: {relative}")
        sheets = inspect_workbook(path, table_namespace=namespace, kind=kind)
        if [item["name"] for item in sheets] != expected_sheets:
            raise OffendersReleaseError(f"exact sheet inventory mismatch: {relative}")
        numbered = [
            item for item in sheets if item["classification"] == "numbered-data"
        ]
        if len(numbered) != expected_numbered:
            raise OffendersReleaseError(f"numbered-sheet count mismatch: {relative}")
        if kind == "cube":
            if not numbered or any(
                item["classification"] != "numbered-data" and item["name"] != "Contents"
                for item in sheets
            ):
                raise OffendersReleaseError(
                    "substantive cube sheet inventory is invalid"
                )
            for sheet in numbered:
                _validate_title(release, cube_id, namespace, sheet)
        elif kind == "guide":
            if len(sheets) != 1 or sheets[0]["name"] != "Guide" or numbered:
                raise OffendersReleaseError(
                    "guide workbook must contain exactly one Guide sheet"
                )
        elif len(sheets) != 1 or sheets[0]["name"] != "Table Concordance" or numbered:
            raise OffendersReleaseError(
                "concordance workbook must contain exactly one Table Concordance sheet"
            )
        release_counts[release] += len(numbered)
        total_bytes += len(data)
        output_downloads.append({**declaration, "sheets": sheets})
    if any(
        release_download_ordinals[release]
        != set(range(EXPECTED_DOWNLOAD_COUNTS[release]))
        for release in RELEASES
    ):
        raise OffendersReleaseError("release download ordinals are not contiguous")
    kinds = {
        kind: sum(item["kind"] == kind for item in declarations)
        for kind in {"cube", "guide", "concordance"}
    }
    release_kinds = {
        release: {
            kind: sum(
                item["releaseId"] == release and item["kind"] == kind
                for item in declarations
            )
            for kind in ("cube", "guide", "concordance")
        }
        for release in RELEASES
    }
    if (
        release_counts != EXPECTED_RELEASE_COUNTS
        or release_kinds != EXPECTED_RELEASE_KINDS
        or kinds != {"cube": 27, "guide": 4, "concordance": 2}
        or total_bytes != 3_990_797
    ):
        raise OffendersReleaseError("release custody closure is invalid")
    inventory: dict[str, Any] = {
        "schemaVersion": INVENTORY_SCHEMA,
        "recordedAt": downloads["recordedAt"],
        "publicationId": PUBLICATION_ID,
        "releaseCounts": release_counts,
        "downloadCount": len(output_downloads),
        "reviewedExclusionDownloadCount": kinds["guide"] + kinds["concordance"],
        "substantiveCubeCount": kinds["cube"],
        "numberedDataSheetCount": sum(release_counts.values()),
        "totalByteLength": total_bytes,
        "downloads": output_downloads,
    }
    inventory["inventoryDigest"] = _domain_digest(INVENTORY_SCHEMA, inventory)
    return inventory


def build_family_membership(
    project_root: Path, inventory: dict[str, Any]
) -> dict[str, Any]:
    project = project_root.resolve()
    fixture_root = project / "fixtures" / "product-prototype"
    crosswalk = _load(
        fixture_root / "offenders-release-family-crosswalk-v1.json", "family crosswalk"
    )
    raw_families = crosswalk.get("families")
    if (
        set(crosswalk) != {"schemaVersion", "recordedAt", "publicationId", "families"}
        or crosswalk.get("schemaVersion") != CROSSWALK_SCHEMA
        or crosswalk.get("publicationId") != PUBLICATION_ID
        or not isinstance(raw_families, list)
        or len(raw_families) != 52
    ):
        raise OffendersReleaseError("family crosswalk schema is invalid")
    source_members: dict[tuple[str, int, str], dict[str, Any]] = {}
    display_identities: set[str] = set()
    for download in inventory["downloads"]:
        if download["kind"] != "cube":
            continue
        for sheet in download["sheets"]:
            if sheet["classification"] != "numbered-data":
                continue
            key = (download["releaseId"], download["downloadOrdinal"], sheet["name"])
            display_identity = (
                f"recorded-crime-offenders/{download['releaseId']}/"
                f"{download['tableNamespace']}/table-{sheet['physicalTableNumber']}"
            )
            if key in source_members or display_identity in display_identities:
                raise OffendersReleaseError("source member identity collides")
            display_identities.add(display_identity)
            source_members[key] = {
                "releaseId": download["releaseId"],
                "downloadOrdinal": download["downloadOrdinal"],
                "cubeId": download["cubeId"],
                "tableNamespace": download["tableNamespace"],
                "physicalSheetName": sheet["name"],
                "physicalTableNumber": sheet["physicalTableNumber"],
                "displayIdentity": display_identity,
                "publishedTitle": sheet["title"],
                "sourcePath": download["path"],
                "sourceDigest": download["contentDigest"],
            }
    assigned: dict[tuple[str, int, str], str] = {}
    families: list[dict[str, Any]] = []
    family_ids: set[str] = set()
    availability_counts: dict[str, int] = {}
    member_keys = {
        "releaseId",
        "downloadOrdinal",
        "cubeId",
        "tableNamespace",
        "physicalSheetName",
    }
    allowed_releases = {
        tuple(RELEASES): "published-2021-2024",
        ("2021-22",): "discontinued-after-2021",
        tuple(RELEASES[1:]): "introduced-2022",
        tuple(RELEASES[2:]): "introduced-2023",
    }
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
            raise OffendersReleaseError("family crosswalk entry is invalid")
        family_id = family["familyId"]
        family_ids.add(family_id)
        members: list[dict[str, Any]] = []
        for raw in family["members"]:
            if not isinstance(raw, dict) or set(raw) != member_keys:
                raise OffendersReleaseError("family crosswalk member is invalid")
            key = (
                raw.get("releaseId"),
                raw.get("downloadOrdinal"),
                raw.get("physicalSheetName"),
            )
            source = source_members.get(key)
            if source is None:
                raise OffendersReleaseError(
                    f"crosswalk member is not published: {key!r}"
                )
            if (
                raw.get("cubeId") != source["cubeId"]
                or raw.get("tableNamespace") != source["tableNamespace"]
            ):
                raise OffendersReleaseError(
                    "crosswalk member cube or namespace is invalid"
                )
            if key in assigned:
                raise OffendersReleaseError(f"crosswalk duplicates {key!r}")
            assigned[key] = family_id
            members.append({**source, "familyId": family_id})
        releases = [item["releaseId"] for item in members]
        if len(releases) != len(set(releases)) or releases != sorted(
            releases, key=RELEASES.index
        ):
            raise OffendersReleaseError("family releases must be unique and ordered")
        availability = allowed_releases.get(tuple(releases))
        if availability is None:
            raise OffendersReleaseError(
                f"family {family_id!r} has fabricated availability {releases!r}"
            )
        availability_counts[availability] = availability_counts.get(availability, 0) + 1
        families.append(
            {
                "familyId": family_id,
                "availability": availability,
                "releases": releases,
                "members": members,
            }
        )
    if set(assigned) != set(source_members):
        missing = sorted(set(source_members) - set(assigned))
        raise OffendersReleaseError(
            f"family crosswalk is not exact: missing={missing!r}"
        )
    if availability_counts != EXPECTED_FAMILY_SHAPES:
        raise OffendersReleaseError("family availability closure is invalid")
    preliminary = next(
        (
            family
            for family in families
            if family["familyId"]
            == "offenders-by-preliminary-anzsoc-2023-principal-offence-and-jurisdiction"
        ),
        None,
    )
    if preliminary is None or any(
        item["tableNamespace"] != "preliminary-anzsoc-2023"
        for item in preliminary["members"]
    ):
        raise OffendersReleaseError("preliminary ANZSOC family identity is invalid")
    membership: dict[str, Any] = {
        "schemaVersion": MEMBERSHIP_SCHEMA,
        "recordedAt": crosswalk["recordedAt"],
        "publicationId": PUBLICATION_ID,
        "sourceInventoryDigest": inventory["inventoryDigest"],
        "familyCount": len(families),
        "memberCount": len(assigned),
        "families": families,
    }
    membership["membershipDigest"] = _domain_digest(MEMBERSHIP_SCHEMA, membership)
    return membership


def _without_digest(value: dict[str, Any], field: str) -> dict[str, Any]:
    semantic = json.loads(json.dumps(value))
    semantic.pop(field, None)
    return semantic


def _registered_members(
    project: Path, membership: dict[str, Any]
) -> set[tuple[str, int, str]]:
    fixture_root = project / "fixtures" / "product-prototype"
    status = _load(fixture_root / "data-asset-status-v1.json", "status registry")
    normalization = _load(
        fixture_root / "batch-workbook-normalization-v1.json", "normalization registry"
    )
    source_by_output: dict[str, tuple[str, str]] = {}
    for entry in normalization.get("entries", []):
        output = entry.get("outputPath")
        source = entry.get("sourcePath")
        source_digest = entry.get("sourceDigest")
        if (
            isinstance(output, str)
            and isinstance(source, str)
            and isinstance(source_digest, str)
        ):
            if output in source_by_output:
                raise OffendersReleaseError("normalization output path is duplicated")
            source_by_output[output] = (source, source_digest)
    source_members = {
        (
            member["releaseId"],
            member["downloadOrdinal"],
            member["physicalSheetName"],
        ): member
        for family in membership["families"]
        for member in family["members"]
    }
    by_source_sheet = {
        (
            f"fixtures/product-prototype/{member['sourcePath']}",
            member["physicalSheetName"],
        ): key
        for key, member in source_members.items()
    }
    registered: set[tuple[str, int, str]] = set()
    registered_families: set[str] = set()
    for declaration in status.get("cohorts", []):
        cohort_path = declaration.get("cohortPath")
        if not isinstance(cohort_path, str):
            raise OffendersReleaseError("status cohort path is invalid")
        cohort = _load(
            _safe_file(project, cohort_path, "status cohort"), "registered cohort"
        )
        if cohort.get("publicationId") != PUBLICATION_ID:
            continue
        family_id = cohort.get("tableFamilyId")
        if not isinstance(family_id, str) or family_id not in REGISTERED_FAMILY_IDS:
            raise OffendersReleaseError("registered family identity is invalid")
        if family_id in registered_families:
            raise OffendersReleaseError("registered family is duplicated")
        registered_families.add(family_id)
        for workbook in cohort.get("workbooks", []):
            relative_output = workbook.get("path")
            sheet = workbook.get("sheet")
            if not isinstance(relative_output, str) or not isinstance(sheet, str):
                raise OffendersReleaseError("registered workbook identity is invalid")
            output = f"fixtures/product-prototype/{relative_output}"
            normalized = source_by_output.get(output)
            if normalized is None:
                raise OffendersReleaseError("registered workbook has no source custody")
            source_path, source_digest = normalized
            key = by_source_sheet.get((source_path, sheet))
            if key is None:
                raise OffendersReleaseError(
                    "registered workbook does not resolve by publication, cube, "
                    "and member"
                )
            member = source_members[key]
            if member["sourceDigest"] != source_digest:
                raise OffendersReleaseError("registered source digest is inconsistent")
            if member["familyId"] != family_id:
                raise OffendersReleaseError(
                    "registered workbook is assigned to the wrong family"
                )
            if key in registered:
                raise OffendersReleaseError("registered workbook is duplicated")
            registered.add(key)
    if registered_families != REGISTERED_FAMILY_IDS or len(registered) != 20:
        raise OffendersReleaseError("registered Offenders closure is invalid")
    return registered


def verify_offenders_release(project_root: Path) -> dict[str, Any]:
    """Verify exact downloads, sheet inventory, family cover, and registration."""
    project = project_root.resolve()
    fixture_root = project / "fixtures" / "product-prototype"
    generated_inventory = build_source_inventory(project)
    generated_membership = build_family_membership(project, generated_inventory)
    inventory = _load(
        fixture_root / "offenders-release-source-inventory-v1.json", "source inventory"
    )
    membership = _load(
        fixture_root / "offenders-release-family-membership-v1.json",
        "family membership",
    )
    if _canonical_json_bytes(inventory) != _canonical_json_bytes(generated_inventory):
        raise OffendersReleaseError("source inventory is not reproducible")
    if _canonical_json_bytes(membership) != _canonical_json_bytes(generated_membership):
        raise OffendersReleaseError("family membership is not reproducible")
    if inventory.get("inventoryDigest") != _domain_digest(
        INVENTORY_SCHEMA, _without_digest(inventory, "inventoryDigest")
    ):
        raise OffendersReleaseError("source inventory digest is invalid")
    if membership.get("membershipDigest") != _domain_digest(
        MEMBERSHIP_SCHEMA, _without_digest(membership, "membershipDigest")
    ):
        raise OffendersReleaseError("family membership digest is invalid")
    source_keys = {
        (member["releaseId"], member["downloadOrdinal"], member["physicalSheetName"])
        for family in membership["families"]
        for member in family["members"]
    }
    registered = _registered_members(project, membership)
    if not registered <= source_keys:
        raise OffendersReleaseError("registered Offenders coverage escapes membership")
    pending = len(source_keys) - len(registered)
    if pending != 170:
        raise OffendersReleaseError("pending semantic-contract closure is invalid")
    return {
        "verified": True,
        "releaseCount": len(RELEASES),
        "downloadCount": inventory["downloadCount"],
        "reviewedExclusionDownloadCount": inventory["reviewedExclusionDownloadCount"],
        "substantiveCubeCount": inventory["substantiveCubeCount"],
        "numberedDataSheetCount": inventory["numberedDataSheetCount"],
        "familyCount": membership["familyCount"],
        "registeredMemberCount": len(registered),
        "pendingSemanticContractCount": pending,
        "providerCalls": 0,
        "inventoryDigest": inventory["inventoryDigest"],
        "membershipDigest": membership["membershipDigest"],
    }
