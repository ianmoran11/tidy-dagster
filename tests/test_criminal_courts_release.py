from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tidy_orchestrator.criminal_courts_release import (
    CriminalCourtsReleaseError,
    build_family_membership,
    build_source_inventory,
    verify_criminal_courts_release,
)

PROJECT = Path(__file__).parents[1]
FIXTURES = PROJECT / "fixtures" / "product-prototype"
DOWNLOADS = FIXTURES / "criminal-courts-release-downloads-v1.json"
CROSSWALK = FIXTURES / "criminal-courts-release-family-crosswalk-v1.json"
INVENTORY = FIXTURES / "criminal-courts-release-source-inventory-v1.json"
MEMBERSHIP = FIXTURES / "criminal-courts-release-family-membership-v1.json"
GUILTY_OUTCOME_FAMILIES = (
    "criminal-courts-guilty-outcome-summary-by-jurisdiction",
    "criminal-courts-guilty-outcome-sex-age-by-sentence-and-court-level",
    "criminal-courts-guilty-outcome-sex-age-by-sentence-all-courts",
    "criminal-courts-guilty-outcome-sex-age-by-sentence-higher-courts",
    "criminal-courts-guilty-outcome-sex-age-by-sentence-magistrates-courts",
    "criminal-courts-guilty-outcome-sex-age-by-sentence-childrens-courts",
    "criminal-courts-guilty-outcome-offence-by-sentence",
    "criminal-courts-guilty-outcome-offence-by-duration",
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _copy_release_project(target: Path) -> None:
    fixture_root = target / "fixtures" / "product-prototype"
    (fixture_root / "workbooks").mkdir(parents=True)
    downloads = _load(DOWNLOADS)
    for declaration in downloads["downloads"]:
        relative = declaration["path"]
        shutil.copyfile(FIXTURES / relative, fixture_root / relative)
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


def test_release_verifier_proves_complete_four_release_custody() -> None:
    report = verify_criminal_courts_release(PROJECT)

    assert report == {
        "verified": True,
        "releaseCount": 4,
        "downloadCount": 69,
        "reviewedExclusionDownloadCount": 4,
        "substantiveCubeCount": 65,
        "numberedDataSheetCount": 430,
        "familyCount": 192,
        "registeredMemberCount": 48,
        "pendingSemanticContractCount": 382,
        "providerCalls": 0,
        "inventoryDigest": report["inventoryDigest"],
        "membershipDigest": report["membershipDigest"],
    }
    inventory = _load(INVENTORY)
    assert inventory["numberedDataSheetCountsByRelease"] == {
        "2021-22": 94,
        "2022-23": 102,
        "2023-24": 116,
        "2024-25": 118,
    }
    downloads = inventory["downloads"]
    assert sum(item["kind"] == "guide" for item in downloads) == 4
    assert sum(item["kind"] == "cube" for item in downloads) == 65
    assert any(
        sheet["name"].startswith("FDV Table ")
        and sheet["classification"] == "numbered-data"
        for item in downloads
        for sheet in item["sheets"]
    )
    assert any(
        sheet["name"].startswith("ANZSOC 2023 Table ")
        and sheet["classification"] == "numbered-data"
        for item in downloads
        for sheet in item["sheets"]
    )


def test_generated_inventory_and_membership_are_byte_reproducible() -> None:
    inventory = build_source_inventory(PROJECT)
    membership = build_family_membership(PROJECT, inventory)

    assert json.loads(INVENTORY.read_text()) == inventory
    assert json.loads(MEMBERSHIP.read_text()) == membership
    assert sum(len(family["members"]) for family in membership["families"]) == 430
    assert (
        sum(
            member["registered"]
            for family in membership["families"]
            for member in family["members"]
        )
        == 48
    )


def test_generator_check_and_cli_are_cwd_independent(tmp_path: Path) -> None:
    generated = subprocess.run(
        [
            str(PROJECT / "scripts" / "generate-criminal-courts-release-inventory.py"),
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
        [str(PROJECT / "scripts" / "tidy-criminal-courts-release"), "verify"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(cli.stdout)["registeredMemberCount"] == 48
    assert json.loads(cli.stdout)["providerCalls"] == 0

    registered_cli = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT),
            "tidy-criminal-courts-release",
            "verify",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(registered_cli.stdout)["numberedDataSheetCount"] == 430


def test_guilty_outcome_cluster_preserves_semantics_and_provenance() -> None:
    membership = _load(MEMBERSHIP)
    families = {family["familyId"]: family for family in membership["families"]}
    assert (
        sum(
            len(families[family_id]["members"]) for family_id in GUILTY_OUTCOME_FAMILIES
        )
        == 19
    )
    assert all(
        all(member["registered"] for member in families[family_id]["members"])
        for family_id in GUILTY_OUTCOME_FAMILIES
    )

    rows: list[dict[str, object]] = []
    value_status_counts: dict[str, int] = {}
    for family_id in GUILTY_OUTCOME_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        assert manifest["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert run["acceptedWorkbookCount"] == len(run["workbooks"])
        assert all(
            item["decision"] == "prototype_auto_accepted" for item in run["workbooks"]
        )
        for status, count in manifest["valueStatusCounts"].items():
            value_status_counts[status] = value_status_counts.get(status, 0) + count
        by_asset: dict[tuple[str, str], set[str]] = {}
        for row in family_rows:
            key = (row["source_workbook_digest"], row["source_sheet"])
            assert row["source_cell"] not in by_asset.setdefault(key, set())
            by_asset[key].add(row["source_cell"])
            assert row["publication_vintage_date"]
            assert row["raw_value"] is not None
        rows.extend(family_rows)

    assert len(rows) == 25602
    assert value_status_counts == {
        "not_applicable": 3,
        "observed": 25493,
        "suppressed": 106,
    }
    assert {row["unit_id"] for row in rows} == {"person", "week", "year"}
    assert {row["measure_id"] for row in rows if row["unit_id"] == "week"} == {
        "defendant-mean-duration",
        "defendant-median-duration",
        "sentence-mean-duration",
        "sentence-median-duration",
    }
    assert all(
        row["raw_value"] in {"..", "na", "n.a.", "np", "n.p."}
        for row in rows
        if row["value_status"] != "observed"
    )

    offence_rows = [row for row in rows if "principal_offence_id" in row]
    assert all(
        row["principal_offence_id"].startswith(("ANZSOC_2011_", "OFFENCE_"))
        for row in offence_rows
        if row["publication_vintage_date"] < "2025-01-01"
    )
    assert all(
        row["principal_offence_id"].startswith(("ANZSOC_2023_", "OFFENCE_"))
        for row in offence_rows
        if row["publication_vintage_date"] >= "2025-01-01"
    )
    split_rows = [
        row
        for row in rows
        if row["source_sheet"] in {"Table 10", "Table 11", "Table 12", "Table 13"}
        and row["publication_vintage_date"] == "2025-06-30"
        and "court_level_id" in row
    ]
    assert {row["court_level_id"] for row in split_rows} == {
        "ALL_COURTS",
        "CHILDRENS_COURTS",
        "HIGHER_COURTS",
        "MAGISTRATES_COURTS",
    }
    assert all(
        str(row["raw_court_level"]).startswith("This table contains")
        for row in split_rows
    )

    for family_id in (
        "criminal-courts-guilty-outcome-offence-by-sentence",
        "criminal-courts-guilty-outcome-offence-by-duration",
    ):
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        assert {rule["dimension"] for rule in contract["allowedExecutionWarnings"]} == {
            "court_level",
            "observation_period",
        }


def test_download_digest_mutation_fails_closed(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    path = tmp_path / "fixtures" / "product-prototype" / DOWNLOADS.name
    downloads = _load(path)
    changed = copy.deepcopy(downloads)
    changed["downloads"][0]["contentDigest"] = "sha256:" + "0" * 64
    path.write_text(json.dumps(changed))

    with pytest.raises(CriminalCourtsReleaseError, match="bytes differ"):
        build_source_inventory(tmp_path)


def test_incomplete_or_retitled_family_cover_fails_closed(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    path = tmp_path / "fixtures" / "product-prototype" / CROSSWALK.name
    crosswalk = _load(path)
    incomplete = copy.deepcopy(crosswalk)
    multi_release = next(
        family for family in incomplete["families"] if len(family["members"]) > 1
    )
    multi_release["members"].pop()
    path.write_text(json.dumps(incomplete))
    inventory = build_source_inventory(tmp_path)
    with pytest.raises(CriminalCourtsReleaseError, match="exact cover"):
        build_family_membership(tmp_path, inventory)

    retitled = copy.deepcopy(crosswalk)
    retitled["families"][0]["members"][0]["publishedTitle"] += " fabricated"
    path.write_text(json.dumps(retitled))
    with pytest.raises(CriminalCourtsReleaseError, match="exact source identity"):
        build_family_membership(tmp_path, inventory)


def test_classification_context_is_exactly_custodied(tmp_path: Path) -> None:
    _copy_release_project(tmp_path)
    path = tmp_path / "fixtures" / "product-prototype" / CROSSWALK.name
    crosswalk = _load(path)
    changed = copy.deepcopy(crosswalk)
    changed["families"][0]["members"][0]["classificationContext"] = "generic-anzsoc"
    path.write_text(json.dumps(changed))
    inventory = build_source_inventory(tmp_path)
    with pytest.raises(CriminalCourtsReleaseError, match="classification context"):
        build_family_membership(tmp_path, inventory)
