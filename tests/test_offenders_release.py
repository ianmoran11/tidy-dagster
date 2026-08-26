from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tidy_orchestrator.offenders_release import (
    OffendersReleaseError,
    _registered_members,
    _validate_download_identity,
    _validate_title,
    build_family_membership,
    build_source_inventory,
    inspect_workbook,
    semantic_cells,
    verify_offenders_release,
)

PROJECT = Path(__file__).parents[1]
FIXTURES = PROJECT / "fixtures" / "product-prototype"
DOWNLOADS = FIXTURES / "offenders-release-downloads-v1.json"
CROSSWALK = FIXTURES / "offenders-release-family-crosswalk-v1.json"
INVENTORY = FIXTURES / "offenders-release-source-inventory-v1.json"
MEMBERSHIP = FIXTURES / "offenders-release-family-membership-v1.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _write_crosswalk(root: Path, value: dict[str, object]) -> None:
    fixture_root = root / "fixtures" / "product-prototype"
    fixture_root.mkdir(parents=True, exist_ok=True)
    (fixture_root / CROSSWALK.name).write_text(json.dumps(value))


def _write_downloads(root: Path, value: dict[str, object]) -> None:
    fixture_root = root / "fixtures" / "product-prototype"
    fixture_root.mkdir(parents=True, exist_ok=True)
    (fixture_root / DOWNLOADS.name).write_text(json.dumps(value))


def _rewrite_zip(source: Path, target: Path, changes: dict[str, bytes]) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as changed:
        for item in original.infolist():
            changed.writestr(
                item, changes.get(item.filename, original.read(item.filename))
            )


def _copy_release_project(target: Path) -> None:
    fixture_root = target / "fixtures" / "product-prototype"
    (fixture_root / "workbooks").mkdir(parents=True)
    downloads = _load(DOWNLOADS)
    for declaration in downloads["downloads"]:
        relative = declaration["path"]
        destination = fixture_root / relative
        shutil.copyfile(FIXTURES / relative, destination)
    for path in (DOWNLOADS, CROSSWALK, INVENTORY, MEMBERSHIP):
        shutil.copyfile(path, fixture_root / path.name)
    for path in (
        FIXTURES / "data-asset-status-v1.json",
        FIXTURES / "batch-workbook-normalization-v1.json",
    ):
        shutil.copyfile(path, fixture_root / path.name)
    status = _load(FIXTURES / "data-asset-status-v1.json")
    for declaration in status["cohorts"]:
        cohort = PROJECT / declaration["cohortPath"]
        if cohort.is_file():
            destination = target / declaration["cohortPath"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cohort, destination)


def test_release_verifier_proves_exact_custody_and_membership() -> None:
    report = verify_offenders_release(PROJECT)

    assert (
        report["registeredMemberCount"],
        report["pendingSemanticContractCount"],
    ) in {
        (20, 170),
        (190, 0),
    }
    assert report == {
        "verified": True,
        "releaseCount": 4,
        "downloadCount": 33,
        "reviewedExclusionDownloadCount": 6,
        "substantiveCubeCount": 27,
        "numberedDataSheetCount": 190,
        "familyCount": 52,
        "registeredMemberCount": report["registeredMemberCount"],
        "pendingSemanticContractCount": report["pendingSemanticContractCount"],
        "providerCalls": 0,
        "inventoryDigest": report["inventoryDigest"],
        "membershipDigest": report["membershipDigest"],
    }
    inventory = _load(INVENTORY)
    assert inventory["releaseCounts"] == {
        "2021-22": 47,
        "2022-23": 47,
        "2023-24": 48,
        "2024-25": 48,
    }
    assert inventory["totalByteLength"] == 3_990_797
    downloads = inventory["downloads"]
    assert sum(item["kind"] == "guide" for item in downloads) == 4
    assert sum(item["kind"] == "concordance" for item in downloads) == 2
    assert all(
        not any(sheet["classification"] == "numbered-data" for sheet in item["sheets"])
        for item in downloads
        if item["kind"] != "cube"
    )


def test_declared_downloads_and_generated_files_are_byte_reproducible() -> None:
    inventory = build_source_inventory(PROJECT)
    membership = build_family_membership(PROJECT, inventory)
    declarations = _load(DOWNLOADS)["downloads"]

    assert len(declarations) == 33
    assert all(
        len((FIXTURES / item["path"]).read_bytes()) == item["byteLength"]
        for item in declarations
    )
    assert json.loads(INVENTORY.read_text()) == inventory
    assert json.loads(MEMBERSHIP.read_text()) == membership
    assert membership["memberCount"] == 190
    assert {family["availability"] for family in membership["families"]} == {
        "published-2021-2024",
        "discontinued-after-2021",
        "introduced-2022",
        "introduced-2023",
    }


def test_generator_check_and_cli_are_cwd_independent(tmp_path: Path) -> None:
    generated = subprocess.run(
        [
            str(PROJECT / "scripts" / "generate-offenders-release-inventory.py"),
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
        [str(PROJECT / "scripts" / "tidy-offenders-release"), "verify"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(cli.stdout)["verified"] is True
    assert json.loads(cli.stdout)["providerCalls"] == 0

    registered_cli = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT),
            "tidy-offenders-release",
            "verify",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    registered_report = json.loads(registered_cli.stdout)
    assert registered_report["verified"] is True
    assert registered_report["providerCalls"] == 0


def test_exclusion_kinds_are_bound_by_release_ordinal_and_exact_sheet(
    tmp_path: Path,
) -> None:
    manifest = _load(DOWNLOADS)
    declarations = manifest["downloads"]
    guide_2021 = next(
        item
        for item in declarations
        if item["releaseId"] == "2021-22" and item["kind"] == "guide"
    )
    concordance_2021 = next(
        item
        for item in declarations
        if item["releaseId"] == "2021-22" and item["kind"] == "concordance"
    )
    guide_2023 = next(
        item
        for item in declarations
        if item["releaseId"] == "2023-24" and item["kind"] == "guide"
    )

    swapped = copy.deepcopy(manifest)
    first = next(
        item
        for item in swapped["downloads"]
        if item["releaseId"] == "2021-22" and item["kind"] == "guide"
    )
    last = next(
        item
        for item in swapped["downloads"]
        if item["releaseId"] == "2021-22" and item["kind"] == "concordance"
    )
    first["kind"], last["kind"] = last["kind"], first["kind"]
    first["cubeId"], last["cubeId"] = last["cubeId"], first["cubeId"]
    _write_downloads(tmp_path, swapped)
    with pytest.raises(OffendersReleaseError, match="release ordinal"):
        build_source_inventory(tmp_path)

    wrong_guide_sheet = copy.deepcopy(guide_2021)
    wrong_guide_sheet["expectedSheetNames"] = ["Table Concordance"]
    with pytest.raises(OffendersReleaseError, match="exactly one Guide"):
        _validate_download_identity(wrong_guide_sheet)

    wrong_concordance_sheet = copy.deepcopy(concordance_2021)
    wrong_concordance_sheet["expectedSheetNames"] = ["Guide"]
    with pytest.raises(OffendersReleaseError, match="Table Concordance"):
        _validate_download_identity(wrong_concordance_sheet)

    fabricated_late_concordance = copy.deepcopy(guide_2023)
    fabricated_late_concordance["kind"] = "concordance"
    fabricated_late_concordance["cubeId"] = "table-concordance"
    with pytest.raises(OffendersReleaseError, match="release ordinal"):
        _validate_download_identity(fabricated_late_concordance)


def test_namespace_cube_release_and_semantic_title_swaps_are_rejected() -> None:
    declarations = _load(DOWNLOADS)["downloads"]
    fdv = next(
        item
        for item in declarations
        if item["releaseId"] == "2021-22"
        and item["cubeId"] == "family-domestic-violence"
    )
    covid = next(item for item in declarations if item["cubeId"] == "covid-19")

    wrong_namespace = copy.deepcopy(fdv)
    wrong_namespace["tableNamespace"] = "covid-19"
    with pytest.raises(OffendersReleaseError, match="cube, or namespace"):
        _validate_download_identity(wrong_namespace)

    wrong_cube = copy.deepcopy(fdv)
    wrong_cube["cubeId"] = "covid-19"
    wrong_cube["tableNamespace"] = "covid-19"
    with pytest.raises(OffendersReleaseError, match="cube, or namespace"):
        _validate_download_identity(wrong_cube)

    wrong_release = copy.deepcopy(covid)
    wrong_release["releaseId"] = "2023-24"
    with pytest.raises(OffendersReleaseError, match="cube, or namespace"):
        _validate_download_identity(wrong_release)

    relabeled_fdv = {
        "physicalTableNumber": 1,
        "title": (
            "Table 1 Offenders of COVID-19 related offences, Age by sex, "
            "2019-20 to 2021-22"
        ),
    }
    with pytest.raises(OffendersReleaseError, match="semantic cube"):
        _validate_title(
            "2021-22",
            "family-domestic-violence",
            "family-domestic-violence",
            relabeled_fdv,
        )


def test_cube_local_namespaces_do_not_collide_and_covid_space_is_preserved() -> None:
    membership = _load(MEMBERSHIP)
    table_ones = [
        member
        for family in membership["families"]
        for member in family["members"]
        if member["releaseId"] == "2021-22" and member["physicalTableNumber"] == 1
    ]
    assert {
        (item["tableNamespace"], item["physicalSheetName"]) for item in table_ones
    } == {
        ("main", "Table 1"),
        ("family-domestic-violence", "Table 1"),
        ("covid-19", "Table 1 "),
    }
    identities = [
        member["displayIdentity"]
        for family in membership["families"]
        for member in family["members"]
    ]
    assert len(identities) == len(set(identities)) == 190

    inventory = _load(INVENTORY)
    preliminary = [
        sheet
        for download in inventory["downloads"]
        if download["cubeId"] == "preliminary-anzsoc-2023"
        for sheet in download["sheets"]
        if sheet["classification"] == "numbered-data"
    ]
    assert len(preliminary) == 2
    assert all(item["name"] == "Table 1" for item in preliminary)
    assert all(
        item["tableNamespace"] == "preliminary-anzsoc-2023" for item in preliminary
    )
    assert all(item["title"].startswith("ANZSOC 2023 Table 1") for item in preliminary)


def test_preliminary_anzsoc_exact_geometry_labels_markers_zeros_and_totals() -> None:
    inventory = _load(INVENTORY)
    data_sheets = {
        download["releaseId"]: next(
            sheet
            for sheet in download["sheets"]
            if sheet["classification"] == "numbered-data"
        )
        for download in inventory["downloads"]
        if download["cubeId"] == "preliminary-anzsoc-2023"
    }
    assert {
        release: (
            sheet["declaredMaxRow"],
            sheet["declaredMaxColumn"],
            sheet["semanticMaxRow"],
            sheet["semanticMaxColumn"],
            sheet["semanticCellCount"],
        )
        for release, sheet in data_sheets.items()
    } == {
        "2023-24": (45, 14877, 33, 8, 164),
        "2024-25": (46, 14877, 35, 8, 166),
    }

    expected_totals = {
        "2023-24": ["114449", "58649", "79727", "39286", "7622", "8681", "2533"],
        "2024-25": ["111485", "58493", "77447", "42604", "8105", "11536", "2659"],
    }
    for release in ("2023-24", "2024-25"):
        path = (
            FIXTURES
            / "workbooks"
            / f"recorded-crime-offenders-{release}-cube-7-source.xlsx"
        )
        cells = semantic_cells(path)
        assert [cells[("Table 1", f"{column}6")][1] for column in "BCDEFGH"] == [
            "NSW",
            "Vic.",
            "Qld",
            "WA",
            "Tas.",
            "NT",
            "ACT",
        ]
        labels = [
            cells[("Table 1", f"A{row}")][1].replace("\xa0", " ")
            for row in range(7, 24)
        ]
        assert labels[0] == "01 Homicide"
        assert labels[7].startswith("Fare evasion")
        assert labels[-1] == "17 Miscellaneous offences"
        assert [cells[("Table 1", f"{column}14")][1] for column in "EFGH"] == ["na"] * 4
        assert cells[("Table 1", "H23")][1] == "0"
        assert [
            cells[("Table 1", f"{column}24")][1] for column in "BCDEFGH"
        ] == expected_totals[release]
    cells_2024 = semantic_cells(
        FIXTURES / "workbooks" / "recorded-crime-offenders-2024-25-cube-7-source.xlsx"
    )
    assert "A1 to H33" in cells_2024[("Table 1", "A1")][1]
    assert cells_2024[("Table 1", "A35")][0] == "Contents!$A$14"


def test_crosswalk_rejects_duplicate_missing_unpublished_wrong_cube_and_availability(
    tmp_path: Path,
) -> None:
    inventory = build_source_inventory(PROJECT)
    original = _load(CROSSWALK)

    duplicate = copy.deepcopy(original)
    duplicate["families"][0]["members"].append(
        copy.deepcopy(duplicate["families"][0]["members"][0])
    )
    _write_crosswalk(tmp_path, duplicate)
    with pytest.raises(OffendersReleaseError, match="duplicates"):
        build_family_membership(tmp_path, inventory)

    missing = copy.deepcopy(original)
    missing["families"] = missing["families"][:-1]
    _write_crosswalk(tmp_path, missing)
    with pytest.raises(OffendersReleaseError, match="schema"):
        build_family_membership(tmp_path, inventory)

    unpublished = copy.deepcopy(original)
    unpublished["families"][0]["members"][0]["physicalSheetName"] = "Table 999"
    _write_crosswalk(tmp_path, unpublished)
    with pytest.raises(OffendersReleaseError, match="not published"):
        build_family_membership(tmp_path, inventory)

    wrong_cube = copy.deepcopy(original)
    wrong_cube["families"][0]["members"][0]["cubeId"] = "covid-19"
    _write_crosswalk(tmp_path, wrong_cube)
    with pytest.raises(OffendersReleaseError, match="cube or namespace"):
        build_family_membership(tmp_path, inventory)

    fabricated = copy.deepcopy(original)
    fabricated["families"][0]["members"].pop(1)
    _write_crosswalk(tmp_path, fabricated)
    with pytest.raises(OffendersReleaseError, match="fabricated availability"):
        build_family_membership(tmp_path, inventory)


def test_registration_resolves_by_source_cube_not_ambiguous_sheet_name() -> None:
    membership = _load(MEMBERSHIP)
    registered = _registered_members(PROJECT, membership)
    assert len(registered) in {20, 190}
    if len(registered) == 20:
        assert all(ordinal == 1 for _release, ordinal, _sheet in registered)
    assert ("2021-22", 1, "Table 1") in registered
    if len(registered) == 20:
        assert ("2021-22", 6, "Table 1") not in registered
        assert ("2021-22", 7, "Table 1 ") not in registered
    else:
        assert ("2021-22", 6, "Table 1") in registered
        assert ("2021-22", 7, "Table 1 ") in registered


def test_safe_path_byte_mutation_and_generated_drift_fail_closed(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "fixtures" / "product-prototype"
    (fixture_root / "workbooks").mkdir(parents=True)
    declarations = _load(DOWNLOADS)
    first = declarations["downloads"][0]
    link = fixture_root / first["path"]
    os.symlink(FIXTURES / first["path"], link)
    (fixture_root / DOWNLOADS.name).write_text(json.dumps(declarations))
    with pytest.raises(OffendersReleaseError, match="unsafe"):
        build_source_inventory(tmp_path)

    copied = tmp_path / "copied"
    _copy_release_project(copied)
    first_path = copied / "fixtures" / "product-prototype" / first["path"]
    first_path.write_bytes(first_path.read_bytes() + b"mutation")
    with pytest.raises(OffendersReleaseError, match="custody mismatch"):
        build_source_inventory(copied)

    drifted = tmp_path / "drifted"
    _copy_release_project(drifted)
    inventory_path = drifted / "fixtures" / "product-prototype" / INVENTORY.name
    drift = _load(inventory_path)
    drift["downloadCount"] = 32
    inventory_path.write_text(json.dumps(drift))
    with pytest.raises(OffendersReleaseError, match="not reproducible"):
        verify_offenders_release(drifted)


def test_invalid_relationship_and_shared_string_index_fail_closed(
    tmp_path: Path,
) -> None:
    source = FIXTURES / "workbooks" / "recorded-crime-offenders-2021-22-source.xlsx"
    relationship_name = "xl/_rels/workbook.xml.rels"
    with zipfile.ZipFile(source) as archive:
        relationships = ET.fromstring(archive.read(relationship_name))
    relationship = next(
        item for item in relationships if item.get("Type", "").endswith("/worksheet")
    )
    relationship.set("Target", "../escaping.xml")
    invalid_relationship = tmp_path / "invalid-relationship.xlsx"
    _rewrite_zip(
        source,
        invalid_relationship,
        {
            relationship_name: ET.tostring(
                relationships, encoding="utf-8", xml_declaration=True
            )
        },
    )
    with pytest.raises(OffendersReleaseError, match="escapes"):
        inspect_workbook(invalid_relationship, table_namespace="main")

    with zipfile.ZipFile(source) as archive:
        sheet_name = "xl/worksheets/sheet1.xml"
        sheet = ET.fromstring(archive.read(sheet_name))
    shared_cell = next(
        cell
        for cell in sheet.iter()
        if cell.tag.endswith("}c") and cell.get("t") == "s"
    )
    value = next(child for child in shared_cell if child.tag.endswith("}v"))
    value.text = "999999999"
    invalid_shared = tmp_path / "invalid-shared-string.xlsx"
    _rewrite_zip(
        source,
        invalid_shared,
        {sheet_name: ET.tostring(sheet, encoding="utf-8", xml_declaration=True)},
    )
    with pytest.raises(OffendersReleaseError, match="shared-string"):
        inspect_workbook(invalid_shared, table_namespace="main")
