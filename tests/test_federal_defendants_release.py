# ruff: noqa: E501, RUF001 - authoritative family IDs and exact en-dash marker
from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from tidy_orchestrator.federal_defendants_release import (
    FederalDefendantsReleaseError,
    _safe_file,
    build_bounded_range_exclusion_ledger,
    build_family_membership,
    build_source_inventory,
    verify_federal_defendants_release,
)
from tidy_orchestrator.offenders_release import semantic_cells

PROJECT = Path(__file__).parents[1]
FIXTURES = PROJECT / "fixtures" / "product-prototype"
DOWNLOADS = FIXTURES / "federal-defendants-release-downloads-v1.json"
CROSSWALK = FIXTURES / "federal-defendants-release-family-crosswalk-v1.json"
LEDGER = FIXTURES / "federal-defendants-bounded-range-exclusions-v1.json"
INVENTORY = FIXTURES / "federal-defendants-release-source-inventory-v1.json"
MEMBERSHIP = FIXTURES / "federal-defendants-release-family-membership-v1.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _copy_release_project(target: Path) -> None:
    fixture_root = target / "fixtures" / "product-prototype"
    (fixture_root / "workbooks").mkdir(parents=True)
    downloads = _load(DOWNLOADS)
    for declaration in downloads["downloads"]:
        relative = declaration["path"]
        shutil.copyfile(FIXTURES / relative, fixture_root / relative)
    for path in (DOWNLOADS, CROSSWALK, LEDGER, INVENTORY, MEMBERSHIP):
        shutil.copyfile(path, fixture_root / path.name)
    status = _load(FIXTURES / "data-asset-status-v1.json")
    status["cohorts"] = []
    (fixture_root / "data-asset-status-v1.json").write_text(json.dumps(status))


def _member_refs(family: dict[str, object]) -> list[tuple[str, str]]:
    return [
        (item["releaseId"], item["physicalSheetName"]) for item in family["members"]
    ]


def _position(address: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", address)
    assert match is not None
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    return int(match.group(2)), column


def _inside(address: str, reference: str) -> bool:
    start, end = reference.split(":")
    row, column = _position(address)
    start_row, start_column = _position(start)
    end_row, end_column = _position(end)
    return start_row <= row <= end_row and start_column <= column <= end_column


def test_release_verifier_proves_complete_four_release_custody() -> None:
    report = verify_federal_defendants_release(PROJECT)

    assert report == {
        "verified": True,
        "releaseCount": 4,
        "downloadCount": 12,
        "reviewedExclusionDownloadCount": 4,
        "substantiveCubeCount": 8,
        "numberedDataSheetCount": 36,
        "boundedRangeSheetCount": 2,
        "boundedRangeExcludedNonblankCellCount": 1041,
        "familyCount": 23,
        "registeredMemberCount": 0,
        "pendingSemanticContractCount": 36,
        "providerCalls": 0,
        "boundedRangeExclusionLedgerDigest": report[
            "boundedRangeExclusionLedgerDigest"
        ],
        "inventoryDigest": report["inventoryDigest"],
        "membershipDigest": report["membershipDigest"],
    }
    inventory = _load(INVENTORY)
    assert inventory["numberedDataSheetCountsByRelease"] == {
        "2021-22": 8,
        "2022-23": 10,
        "2023-24": 9,
        "2024-25": 9,
    }
    assert sum(item["kind"] == "guide" for item in inventory["downloads"]) == 4
    assert sum(item["kind"] == "cube" for item in inventory["downloads"]) == 8


def test_all_generated_custody_artifacts_are_byte_reproducible() -> None:
    ledger = build_bounded_range_exclusion_ledger(PROJECT)
    inventory = build_source_inventory(PROJECT)
    membership = build_family_membership(PROJECT, inventory)

    assert _load(LEDGER) == ledger
    assert _load(INVENTORY) == inventory
    assert _load(MEMBERSHIP) == membership
    assert membership["familyCount"] == 23
    assert sum(len(family["members"]) for family in membership["families"]) == 36
    assert not any(
        member["registered"]
        for family in membership["families"]
        for member in family["members"]
    )


def test_authoritative_23_family_cover_matches_semantic_gate_exactly() -> None:
    families = {family["familyId"]: family for family in _load(MEMBERSHIP)["families"]}
    expected = {
        "federal-defendants-finalised-summary-anzsoc-2011-native": [
            ("2021-22", "Table 1"),
            ("2022-23", "Table 1"),
            ("2023-24", "Table 1"),
        ],
        "federal-defendants-finalised-summary-anzsoc-2023-concorded-history": [
            ("2024-25", "Table 1")
        ],
        "federal-defendants-guilty-summary-anzsoc-2011-pre-stc-2023": [
            ("2021-22", "Table 2")
        ],
        "federal-defendants-guilty-summary-anzsoc-2011-stc-2023-mapped-history": [
            ("2022-23", "Table 2"),
            ("2023-24", "Table 2"),
        ],
        "federal-defendants-guilty-summary-anzsoc-2023-concorded-stc-2023-mapped-history": [
            ("2024-25", "Table 3")
        ],
        "federal-defendants-jurisdiction-summary-anzsoc-2011-pre-stc-2023": [
            ("2021-22", "Table 3")
        ],
        "federal-defendants-jurisdiction-summary-anzsoc-2011-stc-2023-current": [
            ("2022-23", "Table 3"),
            ("2023-24", "Table 3"),
        ],
        "federal-defendants-jurisdiction-summary-anzsoc-2023-stc-2023-current": [
            ("2024-25", "Table 2")
        ],
        "federal-defendants-principal-offence-sentence-anzsoc-2011-pre-stc-2023": [
            ("2021-22", "Table 4")
        ],
        "federal-defendants-principal-offence-sentence-anzsoc-2011-stc-2023-mapped-current": [
            ("2022-23", "Table 4"),
            ("2023-24", "Table 4"),
        ],
        "federal-defendants-principal-offence-sentence-anzsoc-2023-stc-2023-current": [
            ("2024-25", "Table 4")
        ],
        "federal-defendants-selected-offence-summary-anzsoc-2011-stc-2023-mapped-current": [
            ("2022-23", "Table 5"),
            ("2023-24", "Table 5"),
        ],
        "federal-defendants-selected-offence-summary-anzsoc-2023-concorded-stc-2023-mapped-current": [
            ("2024-25", "Table 5")
        ],
        "federal-defendants-offence-group-finalisation-anzsoc-2011-principal-selection": [
            ("2021-22", "Table 5"),
            ("2022-23", "Table 6"),
            ("2023-24", "Table 6"),
        ],
        "federal-defendants-offence-group-finalisation-anzsoc-2023-principal-selection": [
            ("2024-25", "Table 6")
        ],
        "federal-defendants-offence-group-sex-anzsoc-2011-principal-selection": [
            ("2021-22", "Table 6"),
            ("2022-23", "Table 7"),
            ("2023-24", "Table 7"),
        ],
        "federal-defendants-offence-group-sex-age-anzsoc-2023-principal-selection": [
            ("2024-25", "Table 7")
        ],
        "federal-defendants-offence-group-sentence-anzsoc-2011-pre-stc-2023": [
            ("2021-22", "Table 7")
        ],
        "federal-defendants-offence-group-sentence-anzsoc-2011-stc-2023-mapped-current": [
            ("2022-23", "Table 8"),
            ("2023-24", "Table 8"),
        ],
        "federal-defendants-offence-group-sentence-anzsoc-2023-stc-2023-current": [
            ("2024-25", "Table 8")
        ],
        "federal-defendants-offence-group-jurisdiction-outcome-anzsoc-2011-principal-selection": [
            ("2021-22", "Table 8"),
            ("2022-23", "Table 9"),
            ("2023-24", "Table 9"),
        ],
        "federal-defendants-offence-group-jurisdiction-outcome-anzsoc-2023-principal-selection": [
            ("2024-25", "Table 9")
        ],
        "federal-defendants-offence-group-jurisdiction-series-anzsoc-2011-principal-selection": [
            ("2022-23", "Table 10")
        ],
    }
    assert set(families) == set(expected)
    assert {
        family_id: _member_refs(families[family_id]) for family_id in families
    } == expected


def test_member_level_classification_and_sentence_provenance_are_not_release_wide() -> (
    None
):
    downloads = _load(DOWNLOADS)
    assert all(
        "sentenceClassification" not in item
        and "sentenceTreatment" not in item
        and "classificationContext" not in item
        for item in downloads["downloads"]
    )
    members = [
        member
        for family in _load(MEMBERSHIP)["families"]
        for member in family["members"]
    ]
    by_source = {
        (item["releaseId"], item["physicalSheetName"]): item for item in members
    }
    assert (
        by_source[("2022-23", "Table 1")]["sentenceTreatment"]
        == "not-applicable-no-sentence-dimension"
    )
    assert (
        by_source[("2021-22", "Table 2")]["sentenceClassification"]
        == "pre-2022-23-sentence-classification"
    )
    assert by_source[("2022-23", "Table 2")]["sentenceTreatment"].startswith(
        "observation-period-dependent:stc-2023-backcast"
    )
    assert (
        by_source[("2022-23", "Table 3")]["sentenceTreatment"]
        == "native-current-period"
    )
    assert by_source[("2024-25", "Table 3")]["sentenceTreatment"].startswith(
        "observation-period-dependent:stc-2023-backcast"
    )
    assert (
        by_source[("2024-25", "Table 4")]["sentenceTreatment"]
        == "native-current-period"
    )
    assert {
        (item["sentenceClassification"], item["sentenceTreatment"]) for item in members
    } == {
        ("not-applicable", "not-applicable-no-sentence-dimension"),
        ("pre-2022-23-sentence-classification", "native"),
        ("sentence-type-classification-2023", "native-current-period"),
        (
            "sentence-type-classification-2023",
            "observation-period-dependent:stc-2023-backcast-from-old-before-2022-23|stc-2023-native-from-2022-23",
        ),
    }


def test_federal_offence_group_and_principal_anzsoc_provenance_are_separate() -> None:
    members = [
        member
        for family in _load(MEMBERSHIP)["families"]
        for member in family["members"]
    ]
    offence_group = [
        item for item in members if item["cubeId"] == "federal-offence-group"
    ]
    assert {item["rowClassification"] for item in offence_group} == {
        "abs-federal-offence-group"
    }
    assert {item["principalOffenceClassification"] for item in offence_group} == {
        "anzsoc-2011",
        "anzsoc-2023",
    }
    assert {item["classificationTreatment"] for item in offence_group} == {
        "native-federal-offence-group"
    }
    assert {item["principalSelectionTreatment"] for item in members} == {
        "2018-19-plus-method-finalisation-sentence-then-noi",
        "observation-period-dependent:pre-2018-19-method-finalisation-then-noi|2018-19-plus-method-finalisation-sentence-then-noi",
    }


def test_republished_2023_24_anzsoc_refinement_is_explicitly_pinned() -> None:
    members = [
        member
        for family in _load(MEMBERSHIP)["families"]
        for member in family["members"]
    ]
    special = [
        item
        for item in members
        if item["revisionTreatment"].startswith(
            "observation-period-dependent:2023-24-refined"
        )
    ]
    assert {
        (item["releaseId"], item["cubeId"], item["physicalSheetName"])
        for item in special
    } == {
        ("2024-25", "national", "Table 1"),
        ("2024-25", "national", "Table 3"),
        ("2024-25", "national", "Table 5"),
    }
    assert {
        item["revisionTreatment"]
        for item in members
        if item not in special
    } == {"as-published-no-member-specific-revision-rule"}


def test_exact_source_titles_labels_contexts_and_vintages_are_preserved() -> None:
    members = [
        member
        for family in _load(MEMBERSHIP)["families"]
        for member in family["members"]
    ]
    assert Counter(item["releaseId"] for item in members) == {
        "2021-22": 8,
        "2022-23": 10,
        "2023-24": 9,
        "2024-25": 9,
    }
    assert {
        item["releaseId"]: item["publicationVintageDate"] for item in members
    } == {
        "2021-22": "2023-05-04",
        "2022-23": "2024-05-09",
        "2023-24": "2025-05-01",
        "2024-25": "2026-04-30",
    }
    source_typo = next(
        item
        for item in members
        if item["releaseId"] == "2022-23" and item["physicalSheetName"] == "Table 7"
    )
    assert source_typo["publishedTitle"].startswith(
        "Table 6 Federal defendants finalised"
    )
    selected = [
        item
        for item in members
        if item["physicalSheetName"] == "Table 5" and item["cubeId"] == "national"
    ]
    assert "Harassment and threatening behaviour" in selected[0]["publishedTitle"]
    assert "Acts that threaten, harass or control" in selected[-1]["publishedTitle"]

    cells = semantic_cells(
        FIXTURES
        / "workbooks/federal-defendants-australia-2023-24-federal-offence-group-source.xlsx"
    )
    assert any(
        sheet == "Table 8"
        and scalar == "Total finalised (excluding transfer to other court levels)(f)"
        for (sheet, _address), (_formula, scalar) in cells.items()
    )


def test_bounded_range_ledger_records_every_nonblank_exclusion_exactly() -> None:
    ledger = _load(LEDGER)
    assert ledger["boundedSheetCount"] == 2
    assert ledger["excludedNonblankCellCount"] == 1041
    by_sheet = {item["physicalSheetName"]: item for item in ledger["sheets"]}
    assert {
        name: (
            item["authoritativeRange"],
            item["boundedSemanticCellCount"],
            item["excludedNonblankCellCount"],
        )
        for name, item in by_sheet.items()
    } == {
        "Table 1": ("A1:O69", 707, 21),
        "Table 3": ("A1:J86", 574, 1020),
    }
    assert all(
        "ranges from cell A1 to" in item["authorityText"]
        and item["exclusionDigest"].startswith("sha256:")
        and item["boundedSemanticCellDigest"].startswith("sha256:")
        and len(item["excludedNonblankCells"]) == item["excludedNonblankCellCount"]
        for item in ledger["sheets"]
    )
    assert all(
        "value" in cell or "formula" in cell
        for item in ledger["sheets"]
        for cell in item["excludedNonblankCells"]
    )
    for item in ledger["sheets"]:
        source_cells = semantic_cells(FIXTURES / item["sourcePath"])
        expected = []
        for (sheet, address), (formula, scalar) in source_cells.items():
            if sheet != item["physicalSheetName"] or _inside(
                address, item["authoritativeRange"]
            ):
                continue
            payload = {"address": address}
            if formula is not None:
                payload["formula"] = formula
            if scalar not in (None, ""):
                payload["value"] = scalar
            expected.append(payload)
        expected.sort(key=lambda cell: cell["address"])
        assert item["excludedNonblankCells"] == expected
    inventory = _load(INVENTORY)
    bounded_sheets = [
        sheet
        for download in inventory["downloads"]
        for sheet in download["sheets"]
        if sheet.get("executionCellSelection")
        == "federal-authoritative-range-bounded-v1"
    ]
    assert {(item["name"], item["authoritativeRange"]) for item in bounded_sheets} == {
        ("Table 1", "A1:O69"),
        ("Table 3", "A1:J86"),
    }


def test_marker_vocabulary_includes_dash_variants_without_matching_nfd_nec() -> None:
    inventory = _load(INVENTORY)
    assert inventory["recognizedValueMarkers"] == [
        "..",
        "na",
        "n.a.",
        "np",
        "n.p.",
        "-",
        "–",
    ]
    assert inventory["workbookValueMarkerCounts"] == {"-": 254, "np": 46}
    assert (
        sum(
            sheet["valueMarkerCounts"].get("np", 0)
            for download in inventory["downloads"]
            for sheet in download["sheets"]
            if download["releaseId"] == "2024-25"
        )
        == 36
    )
    label_values: set[str] = set()
    for declaration in _load(DOWNLOADS)["downloads"]:
        if declaration["kind"] != "cube":
            continue
        for (_sheet, _address), (_formula, scalar) in semantic_cells(
            FIXTURES / declaration["path"]
        ).items():
            if isinstance(scalar, str) and ("n.f.d." in scalar or "n.e.c." in scalar):
                label_values.add(scalar)
    assert label_values
    assert all(
        value not in inventory["workbookValueMarkerCounts"] for value in label_values
    )


def test_workbook_structure_formulas_markers_and_hidden_ranges_are_pinned() -> None:
    inventory = _load(INVENTORY)
    data_sheets = [
        (download["releaseId"], sheet)
        for download in inventory["downloads"]
        if download["kind"] == "cube"
        for sheet in download["sheets"]
        if sheet["classification"] == "numbered-data"
    ]
    assert len(data_sheets) == 36
    assert (
        sum(
            sheet["formulaCellCount"]
            for release, sheet in data_sheets
            if release == "2021-22"
        )
        == 8
    )
    assert (
        sum(
            sheet["formulaCellCount"]
            for release, sheet in data_sheets
            if release == "2022-23"
        )
        == 10
    )
    assert (
        sum(
            sheet["formulaCellCount"]
            for release, sheet in data_sheets
            if release in {"2023-24", "2024-25"}
        )
        == 0
    )
    assert all(sheet["hiddenRowCount"] == 0 for _release, sheet in data_sheets)
    assert all(
        sheet["worksheetStructureDigest"].startswith("sha256:")
        for _release, sheet in data_sheets
    )
    assert (
        sum(
            sheet["hiddenColumnRangeCount"]
            for release, sheet in data_sheets
            if release == "2023-24"
        )
        == 20
    )
    assert (
        sum(
            sheet["hiddenColumnRangeCount"]
            for release, sheet in data_sheets
            if release == "2024-25"
        )
        == 22
    )


def test_generator_check_and_cli_are_cwd_independent(tmp_path: Path) -> None:
    generated = subprocess.run(
        [
            str(
                PROJECT / "scripts" / "generate-federal-defendants-release-inventory.py"
            ),
            "--check",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert generated.stdout == ""
    assert generated.stderr == ""

    cli = subprocess.run(
        [str(PROJECT / "scripts" / "tidy-federal-defendants-release"), "verify"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(cli.stdout)
    assert report["numberedDataSheetCount"] == 36
    assert report["familyCount"] == 23
    assert report["providerCalls"] == 0

    registered_cli = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT),
            "tidy-federal-defendants-release",
            "verify",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(registered_cli.stdout)["familyCount"] == 23


def test_source_byte_tampering_fails_closed(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    downloads = _load(tmp_path / "fixtures/product-prototype" / DOWNLOADS.name)
    first_data = next(item for item in downloads["downloads"] if item["kind"] == "cube")
    workbook = tmp_path / "fixtures/product-prototype" / first_data["path"]
    workbook.write_bytes(workbook.read_bytes() + b"tamper")

    with pytest.raises(
        FederalDefendantsReleaseError, match="download bytes differ from custody"
    ):
        build_source_inventory(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("releasePageUrl", "https://example.invalid/release", "binding is invalid"),
        ("officialTitle", "Invented title", "binding is invalid"),
        (
            "url",
            "https://www.abs.gov.au/statistics/people/crime-and-justice/federal-defendants-australia/2024-25/invented.xlsx",
            "binding is invalid",
        ),
        (
            "path",
            "workbooks/federal-defendants-australia-2024-25-invented-source.xlsx",
            "binding is invalid",
        ),
        ("cubeId", "federal-offence-group", "binding is invalid"),
        ("tableNamespace", None, "binding is invalid"),
        ("expectedSheetNames", ["Contents"], "binding is invalid"),
        ("expectedNumberedSheetCount", 4, "binding is invalid"),
        ("unexpectedContext", "release-wide", "declaration is invalid"),
    ],
)
def test_download_identity_mutations_fail_closed(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    _copy_release_project(tmp_path)
    path = tmp_path / "fixtures/product-prototype" / DOWNLOADS.name
    downloads = _load(path)
    target = next(
        item
        for item in downloads["downloads"]
        if item["releaseId"] == "2024-25" and item["kind"] == "cube"
    )
    target[field] = value
    path.write_text(json.dumps(downloads))

    with pytest.raises(FederalDefendantsReleaseError, match=message):
        build_source_inventory(tmp_path)


def test_download_role_swap_fails_even_when_metadata_is_self_consistent(
    tmp_path: Path,
) -> None:
    _copy_release_project(tmp_path)
    path = tmp_path / "fixtures/product-prototype" / DOWNLOADS.name
    downloads = _load(path)
    release_items = [
        item for item in downloads["downloads"] if item["releaseId"] == "2024-25"
    ]
    national = next(item for item in release_items if item["downloadOrdinal"] == 1)
    offence_group = next(item for item in release_items if item["downloadOrdinal"] == 2)
    identity_fields = [
        "kind",
        "cubeId",
        "tableNamespace",
        "officialTitle",
        "url",
        "path",
        "contentDigest",
        "byteLength",
        "expectedSheetNames",
        "expectedNumberedSheetCount",
    ]
    for field in identity_fields:
        national[field], offence_group[field] = offence_group[field], national[field]
    path.write_text(json.dumps(downloads))

    with pytest.raises(FederalDefendantsReleaseError, match="binding is invalid"):
        build_source_inventory(tmp_path)


def test_declared_workbook_symlink_is_rejected_before_resolution(
    tmp_path: Path,
) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    downloads = _load(root / DOWNLOADS.name)
    cubes = [item for item in downloads["downloads"] if item["kind"] == "cube"]
    declared = root / cubes[0]["path"]
    alternate = root / cubes[1]["path"]
    declared.unlink()
    declared.symlink_to(alternate)

    with pytest.raises(FederalDefendantsReleaseError, match="missing or unsafe"):
        build_source_inventory(tmp_path)


def test_workbook_paths_reject_absolute_and_escape_return_lexically(
    tmp_path: Path,
) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    downloads = _load(root / DOWNLOADS.name)
    relative = next(
        item["path"] for item in downloads["downloads"] if item["kind"] == "cube"
    )
    source = root / relative

    for unsafe in (str(source), f"workbooks/../{relative}"):
        with pytest.raises(FederalDefendantsReleaseError, match="escapes the project"):
            _safe_file(root, unsafe, "declared Federal Defendants workbook")


def test_declared_workbook_intermediate_directory_symlink_is_rejected(
    tmp_path: Path,
) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    workbooks = root / "workbooks"
    owned_workbooks = root / "owned-workbooks"
    workbooks.rename(owned_workbooks)
    workbooks.symlink_to(owned_workbooks, target_is_directory=True)

    with pytest.raises(FederalDefendantsReleaseError, match="missing or unsafe"):
        build_source_inventory(tmp_path)


@pytest.mark.parametrize("status_item", [{}, {"cohortPath": ""}, "malformed"])
def test_malformed_status_cohort_entries_fail_closed(
    tmp_path: Path, status_item: object
) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    status_path = root / "data-asset-status-v1.json"
    status = _load(status_path)
    status["cohorts"] = [status_item]
    status_path.write_text(json.dumps(status))
    inventory = build_source_inventory(tmp_path)

    with pytest.raises(FederalDefendantsReleaseError, match="status cohort entry"):
        build_family_membership(tmp_path, inventory)


@pytest.mark.parametrize("workbooks", [None, []])
def test_any_premature_federal_cohort_fails_closed(
    tmp_path: Path, workbooks: object
) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    cohort_path = root / "federal-premature.json"
    cohort = {
        "publicationId": "federal-defendants-australia",
        "tableFamilyId": "premature-family",
    }
    if workbooks is not None:
        cohort["workbooks"] = workbooks
    cohort_path.write_text(json.dumps(cohort))
    status_path = root / "data-asset-status-v1.json"
    status = _load(status_path)
    status["cohorts"] = [
        {"cohortPath": "fixtures/product-prototype/federal-premature.json"}
    ]
    status_path.write_text(json.dumps(status))
    inventory = build_source_inventory(tmp_path)

    with pytest.raises(
        FederalDefendantsReleaseError,
        match="premature Federal Defendants cohort registration",
    ):
        build_family_membership(tmp_path, inventory)


def test_status_cohort_path_traversal_fails_closed(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    status_path = root / "data-asset-status-v1.json"
    status = _load(status_path)
    status["cohorts"] = [{"cohortPath": "../outside-cohort.json"}]
    status_path.write_text(json.dumps(status))
    inventory = build_source_inventory(tmp_path)

    with pytest.raises(FederalDefendantsReleaseError, match="escapes the project"):
        build_family_membership(tmp_path, inventory)


def test_status_cohort_paths_reject_absolute_and_escape_return_lexically(
    tmp_path: Path,
) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    cohort_path = root / "federal-premature.json"
    cohort_path.write_text(json.dumps({"publicationId": "federal-defendants-australia"}))
    status_path = root / "data-asset-status-v1.json"
    inventory = build_source_inventory(tmp_path)

    for unsafe in (
        str(cohort_path),
        "fixtures/product-prototype/../product-prototype/federal-premature.json",
    ):
        status = _load(status_path)
        status["cohorts"] = [{"cohortPath": unsafe}]
        status_path.write_text(json.dumps(status))
        with pytest.raises(FederalDefendantsReleaseError, match="escapes the project"):
            build_family_membership(tmp_path, inventory)


def test_status_cohort_intermediate_directory_symlink_is_rejected(
    tmp_path: Path,
) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    owned = root / "owned-cohorts"
    owned.mkdir()
    (owned / "federal-premature.json").write_text(
        json.dumps({"publicationId": "federal-defendants-australia"})
    )
    link = root / "cohorts-link"
    link.symlink_to(owned, target_is_directory=True)
    status_path = root / "data-asset-status-v1.json"
    status = _load(status_path)
    status["cohorts"] = [
        {
            "cohortPath": (
                "fixtures/product-prototype/cohorts-link/federal-premature.json"
            )
        }
    ]
    status_path.write_text(json.dumps(status))
    inventory = build_source_inventory(tmp_path)

    with pytest.raises(FederalDefendantsReleaseError, match="missing or unsafe"):
        build_family_membership(tmp_path, inventory)


def test_family_title_or_provenance_mutation_fails_closed(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    inventory = build_source_inventory(tmp_path)
    path = root / CROSSWALK.name
    crosswalk = _load(path)
    crosswalk["families"][0]["members"][0]["sentenceTreatment"] = "invented"
    path.write_text(json.dumps(crosswalk))

    with pytest.raises(
        FederalDefendantsReleaseError,
        match="does not bind exact source identity and contexts",
    ):
        build_family_membership(tmp_path, inventory)


def test_family_crosswalk_gap_or_version_merge_fails_closed(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    root = tmp_path / "fixtures/product-prototype"
    inventory = build_source_inventory(tmp_path)
    path = root / CROSSWALK.name
    crosswalk = _load(path)
    crosswalk["families"][0]["members"].extend(crosswalk["families"][1]["members"])
    crosswalk["families"].pop(1)
    path.write_text(json.dumps(crosswalk))

    with pytest.raises(
        FederalDefendantsReleaseError, match="family crosswalk schema is invalid"
    ):
        build_family_membership(tmp_path, inventory)


def test_checked_bounded_ledger_tampering_fails_closed(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    path = tmp_path / "fixtures/product-prototype" / LEDGER.name
    ledger = _load(path)
    ledger["sheets"][0]["excludedNonblankCells"][0]["value"] = "invented"
    path.write_text(json.dumps(ledger))

    with pytest.raises(
        FederalDefendantsReleaseError,
        match="bounded range exclusion ledger is not reproducible",
    ):
        verify_federal_defendants_release(tmp_path)
