"""Exact custody and semantic-family closure for Criminal Courts, Australia."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .offenders_release import OffendersReleaseError, inspect_workbook

DOWNLOAD_SCHEMA = "tidy.criminal-courts-release-downloads/v1"
CROSSWALK_SCHEMA = "tidy.criminal-courts-release-family-crosswalk/v1"
INVENTORY_SCHEMA = "tidy.criminal-courts-release-source-inventory/v1"
MEMBERSHIP_SCHEMA = "tidy.criminal-courts-release-family-membership/v1"
PUBLICATION_ID = "criminal-courts-australia"
RELEASES = ["2021-22", "2022-23", "2023-24", "2024-25"]
EXPECTED_DOWNLOAD_COUNTS = {
    "2021-22": 16,
    "2022-23": 17,
    "2023-24": 18,
    "2024-25": 18,
}
EXPECTED_NUMBERED_COUNTS = {
    "2021-22": 94,
    "2022-23": 102,
    "2023-24": 116,
    "2024-25": 118,
}
EXPECTED_DOWNLOAD_COUNT = 69
EXPECTED_CUBE_COUNT = 65
EXPECTED_NUMBERED_COUNT = 430
EXPECTED_FAMILY_COUNT = 198
EXPECTED_REGISTERED_COUNT = 148
REGISTERED_FAMILY_IDS = frozenset(
    {
        "criminal-courts-defendants-finalised-summary-by-court-level",
        "criminal-courts-defendants-finalised-summary-by-jurisdiction",
        "criminal-courts-defendants-finalised-sex-age-by-principal-offence-anzsoc-2011",
        "criminal-courts-defendants-finalised-sex-age-by-principal-offence-anzsoc-2023",
        "criminal-courts-defendants-finalised-sex-offence-by-method-anzsoc-2011",
        "criminal-courts-defendants-finalised-sex-offence-by-method-anzsoc-2023",
        "criminal-courts-defendants-finalised-sex-age-by-method",
        "criminal-courts-defendants-finalised-method-by-duration",
        "criminal-courts-guilty-outcome-summary-by-court-level",
        "criminal-courts-defendants-finalised-method-by-principal-offence-anzsoc-2023",
        "criminal-courts-guilty-outcome-summary-by-jurisdiction",
        "criminal-courts-guilty-outcome-sex-age-by-sentence-and-court-level",
        "criminal-courts-guilty-outcome-sex-age-by-sentence-all-courts",
        "criminal-courts-guilty-outcome-sex-age-by-sentence-higher-courts",
        "criminal-courts-guilty-outcome-sex-age-by-sentence-magistrates-courts",
        "criminal-courts-guilty-outcome-sex-age-by-sentence-childrens-courts",
        "criminal-courts-guilty-outcome-offence-by-sentence",
        "criminal-courts-guilty-outcome-offence-by-duration",
        "criminal-courts-guilty-outcome-principal-sentence-by-length-and-court-level",
        "criminal-courts-custody-by-offence-sentence-length-all-courts-anzsoc-2011",
        "criminal-courts-custody-by-offence-sentence-length-all-courts-anzsoc-2023",
        "criminal-courts-custody-by-offence-sentence-length-higher-courts-anzsoc-2011",
        "criminal-courts-custody-by-offence-sentence-length-higher-courts-anzsoc-2023",
        "criminal-courts-custody-by-offence-sentence-length-magistrates-courts-anzsoc-2011",
        "criminal-courts-custody-by-offence-sentence-length-magistrates-courts-anzsoc-2023",
        "criminal-courts-custody-by-offence-sentence-length-childrens-courts-anzsoc-2011",
        "criminal-courts-custody-by-offence-sentence-length-childrens-courts-anzsoc-2023",
        "criminal-courts-community-service-work-by-offence-length-court-jurisdiction-anzsoc-2011",
        "criminal-courts-community-service-work-by-offence-length-court-jurisdiction-anzsoc-2023",
        "criminal-courts-fines-by-offence-amount-court-jurisdiction-anzsoc-2011",
        "criminal-courts-fines-by-offence-amount-court-jurisdiction-anzsoc-2023",
        "criminal-courts-custody-by-offence-indigenous-status-length-jurisdiction-anzsoc-2011",
        "criminal-courts-custody-by-offence-indigenous-status-length-jurisdiction-anzsoc-2023",
        "criminal-courts-main-defendants-finalised-excluding-traffic-offences-summary-characteristics-by-indigenous-status-selected-sta-b7c24101f2",
        "criminal-courts-main-defendants-finalised-excluding-transfers-and-traffic-offences-court-level-by-indigenous-status-selected-s-95ed08966c",
        "criminal-courts-main-defendants-finalised-excluding-transfers-and-traffic-offences-summary-characteristics-by-indigenous-statu-eb8b64429d",
        "criminal-courts-main-defendants-with-a-guilty-outcome-excluding-traffic-offences-principal-sentence-and-age-by-indigenous-stat-904a1a9407",
        "criminal-courts-main-rate-of-defendants-finalised-excluding-transfers-and-traffic-offences-crude-and-age-standardised-by-selec-0ec1bf61ab",
        "criminal-courts-youth-summary-characteristics-australia",
        "criminal-courts-youth-summary-characteristics-by-jurisdiction",
        "criminal-courts-youth-finalised-sex-age-by-principal-offence",
        "criminal-courts-youth-guilty-outcome-offence-by-principal-sentence",
        "criminal-courts-youth-guilty-outcome-sex-age-by-principal-sentence",
        "criminal-courts-youth-indigenous-status-by-jurisdiction",
        "criminal-courts-youth-indigenous-status-age-by-jurisdiction",
        "criminal-courts-youth-guilty-outcome-sex-age-by-principal-offence",
        "criminal-courts-youth-guilty-outcome-sentence-length-by-jurisdiction",
        "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-and-traffic-offences-preliminary-anzsoc-2023--9011820c8c",
        "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-preliminary-anzsoc-2023-principal-offence-by--73da8de2bb",
        "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-preliminary-anzsoc-2023-principal-offence-sta-44f35a79b0",
        "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-sex-and-age-by-preliminary-anzsoc-2023-princi-e9e65af772",
        "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-preliminary-anzsoc-2023-principal-offence-by-method-of-finalisati-1ae417f119",
        "criminal-courts-preliminary-anzsoc-2023-defendants-with-a-guilty-outcome-sex-and-preliminary-anzsoc-2023-principal-offence-by--b7e20f2c51",
        "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-all-courts-new-s-4d8d4a9753",
        "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-magistrates-cour-b264f70ae9",
        "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-all-courts--08d5fe90c2",
        "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-children-s--3dc8642f72",
        "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-higher-cour-06556eaa3c",
        "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-ff440749dc",
        "criminal-courts-main-defendants-finalised-principal-offence-by-method-of-finalisation-new-south-wales-be08f0a014",
        "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-new-south-wales-275c7f7671",
        "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-new-south-wales-and-99870bae7c",
    }
)


class CriminalCourtsReleaseError(RuntimeError):
    """Criminal Courts release custody or coverage is invalid."""


def _classification_context(
    release: str, namespace: str | None, published_title: str
) -> str:
    if namespace == "family-domestic-violence":
        return "experimental-fdv-publication-namespace"
    if namespace == "preliminary-anzsoc-2023":
        return "preliminary-anzsoc-2023"
    if release in {"2021-22", "2022-23", "2023-24"}:
        return "anzsoc-2011"
    if "concorded from ANZSOC 2011" in published_title:
        return "anzsoc-2023-with-concorded-anzsoc-2011-series"
    return "anzsoc-2023"


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise CriminalCourtsReleaseError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise CriminalCourtsReleaseError(f"{label} must be an object")
    return value


def _safe_file(project: Path, relative: str, label: str) -> Path:
    path = (project / relative).resolve()
    try:
        path.relative_to(project)
    except ValueError as error:
        raise CriminalCourtsReleaseError(f"{label} escapes the project") from error
    if path.is_symlink() or not path.is_file():
        raise CriminalCourtsReleaseError(f"{label} is missing or unsafe")
    return path


def _without_digest(value: dict[str, Any], field: str) -> dict[str, Any]:
    semantic = json.loads(json.dumps(value))
    semantic.pop(field, None)
    return semantic


def build_source_inventory(project_root: Path) -> dict[str, Any]:
    """Rebuild the complete exact-byte and sheet inventory."""
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    custody = _load(
        root / "criminal-courts-release-downloads-v1.json", "download custody"
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
        raise CriminalCourtsReleaseError("download custody schema is invalid")
    declaration_keys = {
        "releaseId",
        "downloadOrdinal",
        "kind",
        "cubeId",
        "tableNamespace",
        "classificationContext",
        "officialTitle",
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
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) != declaration_keys:
            raise CriminalCourtsReleaseError("download declaration is invalid")
        release = declaration.get("releaseId")
        ordinal = declaration.get("downloadOrdinal")
        kind = declaration.get("kind")
        namespace = declaration.get("tableNamespace")
        relative = declaration.get("path")
        url = declaration.get("url")
        expected_sheets = declaration.get("expectedSheetNames")
        expected_numbered = declaration.get("expectedNumberedSheetCount")
        if (
            release not in RELEASES
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 0
            or ordinal in ordinals.get(release, set())
            or kind not in {"guide", "cube"}
            or not isinstance(declaration.get("cubeId"), str)
            or not declaration["cubeId"]
            or (kind == "guide" and namespace is not None)
            or (
                kind == "cube"
                and namespace
                not in {
                    "main",
                    "preliminary-anzsoc-2023",
                    "family-domestic-violence",
                }
            )
            or not isinstance(declaration.get("classificationContext"), str)
            or not declaration["classificationContext"]
            or not isinstance(declaration.get("officialTitle"), str)
            or not declaration["officialTitle"]
            or declaration["classificationContext"]
            != _classification_context(release, namespace, declaration["officialTitle"])
            or not isinstance(url, str)
            or not url.startswith(
                f"https://www.abs.gov.au/statistics/people/crime-and-justice/"
                f"criminal-courts-australia/{release}/"
            )
            or url in urls
            or not isinstance(relative, str)
            or not relative.startswith(f"workbooks/criminal-courts-{release}-")
            or not relative.endswith("-source.xlsx")
            or relative in paths
            or not isinstance(expected_sheets, list)
            or not expected_sheets
            or any(not isinstance(name, str) or not name for name in expected_sheets)
            or len(expected_sheets) != len(set(expected_sheets))
            or isinstance(expected_numbered, bool)
            or not isinstance(expected_numbered, int)
            or expected_numbered < 0
        ):
            raise CriminalCourtsReleaseError("download declaration binding is invalid")
        ordinals[release].add(ordinal)
        paths.add(relative)
        urls.add(url)
        path = _safe_file(root, relative, "declared Criminal Courts workbook")
        data = path.read_bytes()
        if len(data) != declaration.get("byteLength") or sha256_digest(
            data
        ) != declaration.get("contentDigest"):
            raise CriminalCourtsReleaseError("download bytes differ from custody")
        try:
            sheets = inspect_workbook(path, table_namespace=namespace, kind=kind)
        except (OffendersReleaseError, OSError) as error:
            raise CriminalCourtsReleaseError("workbook inspection failed") from error
        numbered = sum(sheet["classification"] == "numbered-data" for sheet in sheets)
        if [
            sheet["name"] for sheet in sheets
        ] != expected_sheets or numbered != expected_numbered:
            raise CriminalCourtsReleaseError(
                "declared sheet inventory differs from source"
            )
        if kind == "guide" and numbered != 0:
            raise CriminalCourtsReleaseError("guide contains a numbered data sheet")
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
        or any(
            ordinals[release] != set(range(EXPECTED_DOWNLOAD_COUNTS[release]))
            for release in RELEASES
        )
    ):
        raise CriminalCourtsReleaseError("release inventory totals are invalid")
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
        "downloads": downloads,
    }
    inventory["inventoryDigest"] = domain_digest(INVENTORY_SCHEMA, inventory)
    return inventory


def _registered_members(
    project: Path, inventory: dict[str, Any]
) -> set[tuple[str, int, str]]:
    root = project / "fixtures" / "product-prototype"
    status = _load(root / "data-asset-status-v1.json", "status registry")
    normalization = _load(
        root / "batch-workbook-normalization-v1.json", "normalization registry"
    )
    output_to_source: dict[str, tuple[str, str]] = {}
    for entry in normalization.get("entries", []):
        if not isinstance(entry, dict):
            continue
        output = entry.get("outputPath")
        source = entry.get("sourcePath")
        digest = entry.get("sourceDigest")
        prefix = "fixtures/product-prototype/"
        if (
            isinstance(output, str)
            and output.startswith(prefix)
            and isinstance(source, str)
            and source.startswith(prefix)
            and isinstance(digest, str)
        ):
            output_to_source[output[len(prefix) :]] = (source[len(prefix) :], digest)
    by_source_sheet: dict[tuple[str, str], tuple[str, int, str]] = {}
    for download in inventory["downloads"]:
        if download["kind"] != "cube":
            continue
        for sheet in download["sheets"]:
            if sheet["classification"] == "numbered-data":
                by_source_sheet[(download["path"], sheet["name"])] = (
                    download["releaseId"],
                    download["downloadOrdinal"],
                    sheet["name"],
                )
    registered: set[tuple[str, int, str]] = set()
    seen_families: set[str] = set()
    for item in status.get("cohorts", []):
        if not isinstance(item, dict) or not isinstance(item.get("cohortPath"), str):
            continue
        cohort_path = _safe_file(project, item["cohortPath"], "status cohort")
        cohort = _load(cohort_path, "registered cohort")
        if cohort.get("publicationId") != PUBLICATION_ID:
            continue
        family_id = cohort.get("tableFamilyId")
        if family_id not in REGISTERED_FAMILY_IDS or family_id in seen_families:
            raise CriminalCourtsReleaseError("registered family identity is invalid")
        seen_families.add(family_id)
        for workbook in cohort.get("workbooks", []):
            if not isinstance(workbook, dict):
                raise CriminalCourtsReleaseError("registered workbook is invalid")
            path = workbook.get("path")
            sheet = workbook.get("sheet")
            digest = workbook.get("contentDigest")
            if not all(isinstance(value, str) for value in (path, sheet, digest)):
                raise CriminalCourtsReleaseError(
                    "registered workbook binding is invalid"
                )
            source_path, source_digest = output_to_source.get(path, (path, digest))
            key = by_source_sheet.get((source_path, sheet))
            if key is None or source_digest != next(
                download["contentDigest"]
                for download in inventory["downloads"]
                if download["path"] == source_path
            ):
                raise CriminalCourtsReleaseError(
                    "registered workbook has no exact source custody"
                )
            registered.add(key)
    return registered


def build_family_membership(
    project_root: Path, inventory: dict[str, Any]
) -> dict[str, Any]:
    """Expand and verify the complete explicit family crosswalk."""
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    crosswalk = _load(
        root / "criminal-courts-release-family-crosswalk-v1.json", "family crosswalk"
    )
    raw_families = crosswalk.get("families")
    if (
        set(crosswalk) != {"schemaVersion", "recordedAt", "publicationId", "families"}
        or crosswalk.get("schemaVersion") != CROSSWALK_SCHEMA
        or crosswalk.get("publicationId") != PUBLICATION_ID
        or not isinstance(raw_families, list)
        or len(raw_families) != EXPECTED_FAMILY_COUNT
    ):
        raise CriminalCourtsReleaseError("family crosswalk schema is invalid")
    sources: dict[tuple[str, int, str], dict[str, Any]] = {}
    for download in inventory["downloads"]:
        if download["kind"] != "cube":
            continue
        for sheet in download["sheets"]:
            if sheet["classification"] != "numbered-data":
                continue
            key = (download["releaseId"], download["downloadOrdinal"], sheet["name"])
            sources[key] = {
                "releaseId": download["releaseId"],
                "downloadOrdinal": download["downloadOrdinal"],
                "cubeId": download["cubeId"],
                "tableNamespace": download["tableNamespace"],
                "physicalSheetName": sheet["name"],
                "physicalTableNumber": sheet["physicalTableNumber"],
                "publishedTitle": sheet["title"],
                "sourcePath": download["path"],
                "sourceDigest": download["contentDigest"],
                "classificationContext": _classification_context(
                    download["releaseId"],
                    download["tableNamespace"],
                    sheet["title"],
                ),
            }
    registered = _registered_members(project, inventory)
    assigned: set[tuple[str, int, str]] = set()
    family_ids: set[str] = set()
    families: list[dict[str, Any]] = []
    for family in raw_families:
        if (
            not isinstance(family, dict)
            or set(family) != {"familyId", "semanticTitle", "members"}
            or not isinstance(family.get("familyId"), str)
            or not family["familyId"]
            or family["familyId"] in family_ids
            or not isinstance(family.get("semanticTitle"), str)
            or not family["semanticTitle"]
            or not isinstance(family.get("members"), list)
            or not family["members"]
        ):
            raise CriminalCourtsReleaseError("family declaration is invalid")
        family_ids.add(family["familyId"])
        members: list[dict[str, Any]] = []
        for member in family["members"]:
            if (
                not isinstance(member, dict)
                or set(member)
                != {
                    "releaseId",
                    "downloadOrdinal",
                    "physicalSheetName",
                    "publishedTitle",
                    "classificationContext",
                }
                or not isinstance(member.get("classificationContext"), str)
                or not member["classificationContext"]
            ):
                raise CriminalCourtsReleaseError("family member declaration is invalid")
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
                or member.get("classificationContext")
                != source["classificationContext"]
            ):
                raise CriminalCourtsReleaseError(
                    "family member does not bind exact source identity and "
                    "classification context"
                )
            assigned.add(key)
            members.append(
                {
                    **source,
                    "registered": key in registered,
                }
            )
        families.append(
            {
                "familyId": family["familyId"],
                "semanticTitle": family["semanticTitle"],
                "members": members,
            }
        )
    if assigned != set(sources):
        raise CriminalCourtsReleaseError("family crosswalk is not an exact cover")
    if len(registered) != EXPECTED_REGISTERED_COUNT:
        raise CriminalCourtsReleaseError(
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


def verify_criminal_courts_release(project_root: Path) -> dict[str, Any]:
    """Verify exact downloads, all numbered sheets, family cover, and registration."""
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype"
    inventory = build_source_inventory(project)
    membership = build_family_membership(project, inventory)
    checked_inventory = _load(
        root / "criminal-courts-release-source-inventory-v1.json", "source inventory"
    )
    checked_membership = _load(
        root / "criminal-courts-release-family-membership-v1.json", "family membership"
    )
    if canonical_json_bytes(inventory) != canonical_json_bytes(checked_inventory):
        raise CriminalCourtsReleaseError("source inventory is not reproducible")
    if canonical_json_bytes(membership) != canonical_json_bytes(checked_membership):
        raise CriminalCourtsReleaseError("family membership is not reproducible")
    if inventory.get("inventoryDigest") != domain_digest(
        INVENTORY_SCHEMA, _without_digest(inventory, "inventoryDigest")
    ):
        raise CriminalCourtsReleaseError("source inventory digest is invalid")
    if membership.get("membershipDigest") != domain_digest(
        MEMBERSHIP_SCHEMA, _without_digest(membership, "membershipDigest")
    ):
        raise CriminalCourtsReleaseError("family membership digest is invalid")
    return {
        "verified": True,
        "releaseCount": len(RELEASES),
        "downloadCount": inventory["downloadCount"],
        "reviewedExclusionDownloadCount": inventory["reviewedExclusionDownloadCount"],
        "substantiveCubeCount": inventory["substantiveCubeCount"],
        "numberedDataSheetCount": inventory["numberedDataSheetCount"],
        "familyCount": membership["familyCount"],
        "registeredMemberCount": membership["registeredMemberCount"],
        "pendingSemanticContractCount": membership["pendingSemanticContractCount"],
        "inventoryDigest": inventory["inventoryDigest"],
        "membershipDigest": membership["membershipDigest"],
        "providerCalls": 0,
    }
