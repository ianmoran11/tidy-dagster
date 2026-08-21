from __future__ import annotations

import copy
import csv
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
from openpyxl import load_workbook

import tidy_orchestrator.product_prototype as product_prototype_module
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
SENTENCE_FINE_FAMILIES = (
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
)
INDIGENOUS_STATUS_FAMILIES = (
    "criminal-courts-custody-by-offence-indigenous-status-length-jurisdiction-anzsoc-2023",
    "criminal-courts-main-defendants-finalised-excluding-traffic-offences-summary-characteristics-by-indigenous-status-selected-sta-b7c24101f2",
    "criminal-courts-main-defendants-finalised-excluding-transfers-and-traffic-offences-court-level-by-indigenous-status-selected-s-95ed08966c",
    "criminal-courts-main-defendants-finalised-excluding-transfers-and-traffic-offences-summary-characteristics-by-indigenous-statu-eb8b64429d",
    "criminal-courts-main-defendants-with-a-guilty-outcome-excluding-traffic-offences-principal-sentence-and-age-by-indigenous-stat-904a1a9407",
    "criminal-courts-main-rate-of-defendants-finalised-excluding-transfers-and-traffic-offences-crude-and-age-standardised-by-selec-0ec1bf61ab",
)
YOUTH_FAMILIES = (
    "criminal-courts-youth-summary-characteristics-australia",
    "criminal-courts-youth-summary-characteristics-by-jurisdiction",
    "criminal-courts-youth-finalised-sex-age-by-principal-offence",
    "criminal-courts-youth-guilty-outcome-offence-by-principal-sentence",
    "criminal-courts-youth-guilty-outcome-sex-age-by-principal-sentence",
    "criminal-courts-youth-indigenous-status-by-jurisdiction",
    "criminal-courts-youth-indigenous-status-age-by-jurisdiction",
    "criminal-courts-youth-guilty-outcome-sex-age-by-principal-offence",
    "criminal-courts-youth-guilty-outcome-sentence-length-by-jurisdiction",
)
PRELIMINARY_ANZSOC_2023_FAMILIES = (
    "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-and-traffic-offences-preliminary-anzsoc-2023--9011820c8c",
    "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-preliminary-anzsoc-2023-principal-offence-by--73da8de2bb",
    "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-preliminary-anzsoc-2023-principal-offence-sta-44f35a79b0",
    "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-excluding-transfers-sex-and-age-by-preliminary-anzsoc-2023-princi-e9e65af772",
    "criminal-courts-preliminary-anzsoc-2023-defendants-finalised-preliminary-anzsoc-2023-principal-offence-by-method-of-finalisati-1ae417f119",
    "criminal-courts-preliminary-anzsoc-2023-defendants-with-a-guilty-outcome-sex-and-preliminary-anzsoc-2023-principal-offence-by--b7e20f2c51",
)
NEW_SOUTH_WALES_FAMILIES = (
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-all-courts-new-s-4d8d4a9753",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-magistrates-cour-b264f70ae9",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-all-courts--08d5fe90c2",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-children-s--3dc8642f72",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-higher-cour-06556eaa3c",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-ff440749dc",
    "criminal-courts-main-defendants-finalised-principal-offence-by-method-of-finalisation-new-south-wales-be08f0a014",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-new-south-wales-275c7f7671",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-new-south-wales-and-99870bae7c",
)
VICTORIA_FAMILIES = (
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-all-courts-victo-05e49f77ef",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-magistrates-cour-9118c3e02d",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-all-courts--c83b6750b7",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-children-s--c86993e818",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-higher-cour-39801494e2",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-173f3bac6d",
    "criminal-courts-main-defendants-finalised-principal-offence-by-method-of-finalisation-victoria-3594164858",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-victoria-and-4a552df2a2",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-victoria-b85a0d076d",
)
QUEENSLAND_FAMILIES = (
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-all-courts-queen-3ce9f383e3",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-magistrates-cour-7ae5115676",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-all-courts--f8da01fb54",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-children-s--0841d7f5ad",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-higher-cour-f847eba164",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-57f4983e16",
    "criminal-courts-main-defendants-finalised-principal-offence-by-method-of-finalisation-queensland-bef784f7d8",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-queensland-7022b11692",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-queensland-and-2925b8b521",
)
AUSTRALIAN_CAPITAL_TERRITORY_FAMILIES = (
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-all-courts-austr-4200e414a2",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-magistrates-cour-79856bc0b9",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-all-courts--0b4eef6926",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-children-s--7c61d6c40e",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-higher-cour-6c72c5eba2",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-139aaf92e0",
    "criminal-courts-main-defendants-finalised-principal-offence-by-method-of-finalisation-australian-capital-territory-5705af16d6",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-australian-capital-territory-1f84e9447d",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-australian-capital-territory-and-b377949ac0",
)
TASMANIA_FAMILIES = (
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-all-courts-tasma-1e1718730a",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-magistrates-cour-f2593de546",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-all-courts--cdc489d600",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-children-s--34dbc091f5",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-higher-cour-08dd480268",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-0a5e590f31",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-0cd32616d1",
    "criminal-courts-main-defendants-finalised-principal-offence-by-method-of-finalisation-tasmania-1d97a0925b",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-tasmania-and-4a82019ceb",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-tasmania-d897254a26",
)
NORTHERN_TERRITORY_FAMILIES = (
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-all-courts-north-9e1eae4d24",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-all-principal-offence-magistrates-cour-2dc791882d",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-all-courts--dff73e6680",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-children-s--d4b9910476",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-higher-cour-fb8ea665a2",
    "criminal-courts-main-defendants-finalised-and-with-a-guilty-outcome-summary-outcomes-by-selected-principal-offence-magistrates-7b3957ee89",
    "criminal-courts-main-defendants-finalised-principal-offence-by-method-of-finalisation-northern-territory-2e3b1c96f5",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-northern-territory-27c9d31040",
    "criminal-courts-main-defendants-finalised-summary-characteristics-by-court-level-northern-territory-and-cd3b98cdfb",
)
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
        "familyCount": 198,
        "registeredMemberCount": 302,
        "pendingSemanticContractCount": 128,
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
        == 302
    )
    wa_mixed = next(
        family
        for family in membership["families"]
        if family["familyId"].endswith("western-australia-and-be8fa3884d")
    )
    assert wa_mixed["semanticTitle"] == (
        "Defendants finalised, summary characteristics by court level — "
        "mixed concorded history — Western Australia"
    )
    nt_mixed = next(
        family
        for family in membership["families"]
        if family["familyId"].endswith("northern-territory-and-cd3b98cdfb")
    )
    assert nt_mixed["semanticTitle"] == (
        "Defendants finalised, summary characteristics by court level — "
        "mixed concorded history — Northern Territory"
    )
    act_mixed = next(
        family
        for family in membership["families"]
        if family["familyId"].endswith("australian-capital-territory-and-b377949ac0")
    )
    assert act_mixed["semanticTitle"] == (
        "Defendants finalised, summary characteristics by court level — "
        "mixed concorded history — Australian Capital Territory"
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
    assert json.loads(cli.stdout)["registeredMemberCount"] == 302
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


def test_sentence_and_fine_cluster_preserves_classification_and_measures() -> None:
    membership = _load(MEMBERSHIP)
    families = {family["familyId"]: family for family in membership["families"]}
    assert (
        sum(len(families[family_id]["members"]) for family_id in SENTENCE_FINE_FAMILIES)
        == 31
    )
    assert all(
        all(member["registered"] for member in families[family_id]["members"])
        for family_id in SENTENCE_FINE_FAMILIES
    )
    rows: list[dict[str, object]] = []
    measure_counts: dict[str, int] = {}
    value_status_counts: dict[str, int] = {}
    source_cells: set[tuple[str, str, str]] = set()
    for family_id in SENTENCE_FINE_FAMILIES:
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
        for measure, count in manifest["measureCounts"].items():
            measure_counts[measure] = measure_counts.get(measure, 0) + count
        for status, count in manifest["valueStatusCounts"].items():
            value_status_counts[status] = value_status_counts.get(status, 0) + count
        for row in family_rows:
            source_key = (
                row["source_workbook_digest"],
                row["source_sheet"],
                row["source_cell"],
            )
            assert source_key not in source_cells
            source_cells.add(source_key)
            assert row["publication_vintage_date"]
            assert row["raw_value"] is not None
            if family_id.endswith("anzsoc-2011") and "principal_offence_id" in row:
                assert row["principal_offence_id"].startswith(
                    ("ANZSOC_2011_", "OFFENCE_TOTAL")
                )
            if family_id.endswith("anzsoc-2023") and "principal_offence_id" in row:
                assert row["principal_offence_id"].startswith(
                    ("ANZSOC_2023_", "OFFENCE_TOTAL")
                )
            if row["measure_id"] == "defendant-proportion":
                assert row["principal_offence_id"] == "OFFENCE_TOTAL"
            if "fine_amount_id" in row:
                assert row["fine_amount_id"].startswith("FINE_")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        if family_id == SENTENCE_FINE_FAMILIES[0]:
            assert contract["allowedExecutionWarnings"] == []
        else:
            assert len(contract["allowedExecutionWarnings"]) == 1
            warning_rule = contract["allowedExecutionWarnings"][0]
            assert warning_rule["dimension"] == "jurisdiction"
            assert warning_rule["requireCanonicalOutputEquivalence"] is True
            assert warning_rule["expectedHeaderSourcesByYear"]
        rows.extend(family_rows)

    assert len(rows) == 43284
    assert measure_counts == {
        "defendant-count": 25844,
        "defendant-proportion": 2622,
        "fine-mean-amount": 2103,
        "fine-median-amount": 2103,
        "sentence-mean-duration": 5306,
        "sentence-median-duration": 5306,
    }
    assert value_status_counts == {
        "not_applicable": 1962,
        "observed": 40646,
        "suppressed": 676,
    }
    assert {(row["measure_id"], row["unit_id"]) for row in rows} == {
        ("defendant-count", "person"),
        ("defendant-proportion", "percent"),
        ("fine-mean-amount", "dollar"),
        ("fine-median-amount", "dollar"),
        ("sentence-mean-duration", "hour"),
        ("sentence-mean-duration", "month"),
        ("sentence-median-duration", "hour"),
        ("sentence-median-duration", "month"),
    }


def test_indigenous_status_cluster_preserves_periods_rates_and_null_markers() -> None:
    membership = _load(MEMBERSHIP)
    families = {family["familyId"]: family for family in membership["families"]}
    assert (
        sum(
            len(families[family_id]["members"])
            for family_id in INDIGENOUS_STATUS_FAMILIES
        )
        == 17
    )
    assert all(
        all(member["registered"] for member in families[family_id]["members"])
        for family_id in INDIGENOUS_STATUS_FAMILIES
    )

    rows: list[dict[str, object]] = []
    measure_counts: dict[str, int] = {}
    value_status_counts: dict[str, int] = {}
    source_cells: set[tuple[str, str, str]] = set()
    warning_dimensions: dict[str, set[str]] = {}
    for family_id in INDIGENOUS_STATUS_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        uses_observation_period = (
            contract.get("referenceDateDimension") == "observation_period"
        )
        assert manifest["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert run["acceptedWorkbookCount"] == len(run["workbooks"])
        assert all(
            item["decision"] == "prototype_auto_accepted" for item in run["workbooks"]
        )
        for measure, count in manifest["measureCounts"].items():
            measure_counts[measure] = measure_counts.get(measure, 0) + count
        for status, count in manifest["valueStatusCounts"].items():
            value_status_counts[status] = value_status_counts.get(status, 0) + count
        for row in family_rows:
            source_key = (
                row["source_workbook_digest"],
                row["source_sheet"],
                row["source_cell"],
            )
            assert source_key not in source_cells
            source_cells.add(source_key)
            assert row["publication_vintage_date"]
            assert row["raw_value"] is not None
            if uses_observation_period:
                assert "observation_period_id" in row
                assert row["reference_date"] == row["observation_period_id"]
        if uses_observation_period:
            assert any(
                row["publication_vintage_date"] != row["reference_date"]
                for row in family_rows
            )
        warning_dimensions[family_id] = {
            rule["dimension"] for rule in contract["allowedExecutionWarnings"]
        }
        assert all(
            rule["requireCanonicalOutputEquivalence"] is True
            and rule["expectedHeaderSourcesByYear"]
            for rule in contract["allowedExecutionWarnings"]
        )
        rows.extend(family_rows)

    assert len(rows) == 24643
    assert measure_counts == {
        "age-standardised-defendant-rate": 382,
        "crude-defendant-rate": 393,
        "defendant-count": 21018,
        "defendant-proportion": 144,
        "indigenous-to-non-indigenous-rate-ratio": 382,
        "mean-defendant-age": 856,
        "median-defendant-age": 856,
        "sentence-mean-duration": 306,
        "sentence-median-duration": 306,
    }
    assert value_status_counts == {
        "not_applicable": 318,
        "not_available": 794,
        "observed": 23479,
        "suppressed": 52,
    }
    assert {
        (row["raw_value"], row["value_status"])
        for row in rows
        if row["value_status"] != "observed"
    } == {
        ("..", "not_applicable"),
        ("na", "not_available"),
        ("np", "suppressed"),
    }
    assert {(row["measure_id"], row["unit_id"]) for row in rows} == {
        ("age-standardised-defendant-rate", "per-100000-persons-aged-10-plus"),
        ("crude-defendant-rate", "per-100000-persons-aged-10-plus"),
        ("defendant-count", "person"),
        ("defendant-proportion", "percent"),
        ("indigenous-to-non-indigenous-rate-ratio", "ratio"),
        ("mean-defendant-age", "year"),
        ("median-defendant-age", "year"),
        ("sentence-mean-duration", "month"),
        ("sentence-median-duration", "month"),
    }
    offence_rows = [row for row in rows if "principal_offence_id" in row]
    assert all(
        row["principal_offence_id"].startswith(("ANZSOC_2023_", "OFFENCE_TOTAL"))
        for row in offence_rows
    )
    assert {
        row["characteristic_group_id"]
        for row in rows
        if "characteristic_group_id" in row
        and str(row["characteristic_group_id"]).startswith("GROUP_PRINCIPAL_OFFENCE")
    } == {
        "GROUP_PRINCIPAL_OFFENCE_ANZSOC_2011",
        "GROUP_PRINCIPAL_OFFENCE_ANZSOC_2023",
    }
    for family_id, dimensions in warning_dimensions.items():
        assert dimensions == (
            {"observation_period"}
            if family_id
            in {
                INDIGENOUS_STATUS_FAMILIES[1],
                INDIGENOUS_STATUS_FAMILIES[3],
                INDIGENOUS_STATUS_FAMILIES[4],
            }
            else {"jurisdiction"}
        )


def test_youth_cluster_preserves_classification_periods_measures_and_markers() -> None:
    membership = _load(MEMBERSHIP)
    youth_members = [
        member
        for family in membership["families"]
        for member in family["members"]
        if member["cubeId"] == "youth-defendants-australia"
    ]
    assert len(youth_members) == 24
    assert all(member["registered"] for member in youth_members)

    rows: list[dict[str, object]] = []
    measure_counts: dict[str, int] = {}
    value_status_counts: dict[str, int] = {}
    source_cells: set[tuple[str, str, str]] = set()
    warning_dimensions: dict[str, set[str]] = {}
    for family_id in YOUTH_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        assert manifest["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert run["acceptedWorkbookCount"] == len(run["workbooks"])
        assert all(
            item["decision"] == "prototype_auto_accepted" for item in run["workbooks"]
        )
        for measure, count in manifest["measureCounts"].items():
            measure_counts[measure] = measure_counts.get(measure, 0) + count
        for status, count in manifest["valueStatusCounts"].items():
            value_status_counts[status] = value_status_counts.get(status, 0) + count
        uses_observation_period = (
            contract.get("referenceDateDimension") == "observation_period"
        )
        for row in family_rows:
            source_key = (
                row["source_workbook_digest"],
                row["source_sheet"],
                row["source_cell"],
            )
            assert source_key not in source_cells
            source_cells.add(source_key)
            assert row["publication_vintage_date"]
            assert row["raw_value"] is not None
            if uses_observation_period:
                assert row["reference_date"] == row["observation_period_id"]
            if "principal_offence_id" in row:
                expected_prefix = (
                    "ANZSOC_2023_"
                    if row["publication_vintage_date"] == "2025-06-30"
                    else "ANZSOC_2011_"
                )
                assert row["principal_offence_id"].startswith(
                    (expected_prefix, "OFFENCE_TOTAL")
                )
        if uses_observation_period:
            assert any(
                row["publication_vintage_date"] != row["reference_date"]
                for row in family_rows
            )
        warning_dimensions[family_id] = {
            rule["dimension"] for rule in contract["allowedExecutionWarnings"]
        }
        assert all(
            rule["requireCanonicalOutputEquivalence"] is True
            and rule["expectedHeaderSourcesByYear"]
            for rule in contract["allowedExecutionWarnings"]
        )
        rows.extend(family_rows)

    assert len(rows) == 10302
    assert measure_counts == {
        "defendant-count": 9762,
        "mean-case-duration": 69,
        "mean-defendant-age": 69,
        "median-case-duration": 69,
        "median-defendant-age": 69,
        "sentence-mean-duration": 132,
        "sentence-median-duration": 132,
    }
    assert value_status_counts == {
        "not_applicable": 2,
        "not_available": 447,
        "observed": 9847,
        "suppressed": 6,
    }
    assert {
        (row["raw_value"], row["value_status"])
        for row in rows
        if row["value_status"] != "observed"
    } == {
        ("..", "not_applicable"),
        ("na", "not_available"),
        ("np", "suppressed"),
    }
    assert {(row["measure_id"], row["unit_id"]) for row in rows} == {
        ("defendant-count", "person"),
        ("mean-case-duration", "week"),
        ("mean-defendant-age", "year"),
        ("median-case-duration", "week"),
        ("median-defendant-age", "year"),
        ("sentence-mean-duration", "month"),
        ("sentence-median-duration", "month"),
    }
    assert {
        row["characteristic_group_id"]
        for row in rows
        if str(row.get("characteristic_group_id", "")).startswith(
            "GROUP_PRINCIPAL_OFFENCE"
        )
    } == {
        "GROUP_PRINCIPAL_OFFENCE_ANZSOC_2011",
        "GROUP_PRINCIPAL_OFFENCE_ANZSOC_2023",
        "GROUP_PRINCIPAL_OFFENCE_ANZSOC_2023_WITH_CONCORDED_ANZSOC_2011_SERIES",
    }
    assert "NON_INDIGENOUS_AND_NOT_STATED" in {
        row.get("indigenous_status_id") for row in rows
    }
    assert {"CHAR_10_13_YEARS", "CHAR_14_17_YEARS"} <= {
        row.get("characteristic_category_id") for row in rows
    }
    sentence_length_csv = FIXTURES / (
        "criminal-courts-youth-guilty-outcome-sentence-length-by-jurisdiction-"
        "evidence/canonical-observations.csv"
    )
    with sentence_length_csv.open(newline="") as handle:
        assert "Table 80 " in {row["source_sheet"] for row in csv.DictReader(handle)}
    expected_warning_dimensions = {
        YOUTH_FAMILIES[2]: {"sex"},
        YOUTH_FAMILIES[4]: {"sex"},
        YOUTH_FAMILIES[5]: {"jurisdiction"},
        YOUTH_FAMILIES[6]: {"jurisdiction"},
        YOUTH_FAMILIES[7]: {"sex"},
    }
    assert warning_dimensions == {
        family_id: expected_warning_dimensions.get(family_id, set())
        for family_id in YOUTH_FAMILIES
    }


def test_preliminary_cluster_preserves_dual_classification_custody() -> None:
    membership = _load(MEMBERSHIP)
    preliminary_members = [
        member
        for family in membership["families"]
        for member in family["members"]
        if member["cubeId"] == "preliminary-anzsoc-2023-principal-offence"
    ]
    assert len(preliminary_members) == 6
    assert all(member["registered"] for member in preliminary_members)
    assert {member["classificationContext"] for member in preliminary_members} == {
        "preliminary-anzsoc-2023"
    }

    source = load_workbook(
        FIXTURES / "workbooks/criminal-courts-2023-24-cube-15-source.xlsx",
        data_only=False,
        read_only=True,
    )
    rows: list[dict[str, object]] = []
    source_cells: set[tuple[str, str]] = set()
    warning_dimensions: dict[str, set[str]] = {}
    for family_id in PRELIMINARY_ANZSOC_2023_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        cohort = _load(FIXTURES / f"{family_id}.json")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        replay = cohort["workbooks"][0]["replayResponse"]

        assert manifest["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert manifest["canonicalObservationCount"] == len(family_rows)
        assert run["acceptedWorkbookCount"] == 1
        assert run["workbooks"][0]["decision"] == "prototype_auto_accepted"
        assert replay["acceptanceAuthority"] is False
        assert contract["trainingEligibility"] is False
        assert contract["totalValidation"] == "not_applicable"
        assert contract["totalEquations"] == []
        warning_dimensions[family_id] = {
            rule["dimension"] for rule in contract["allowedExecutionWarnings"]
        }

        for row in family_rows:
            match = re.fullmatch(r"R([0-9]+)C([0-9]+)", row["source_cell"])
            assert match is not None
            source_key = (row["source_sheet"], row["source_cell"])
            assert source_key not in source_cells
            source_cells.add(source_key)
            cell = source[row["source_sheet"]].cell(
                row=int(match.group(1)), column=int(match.group(2))
            )
            assert cell.value == row["raw_value"] == row["value"]
            assert row["publication_vintage_date"] == "2024-06-30"
            assert row["reference_date"] == "2024-06-30"
            assert row["measure_id"] == "defendant-count"
            assert row["unit_id"] == "person"
            assert row["value_status"] == "observed"
            assert str(row["principal_offence_id"]).startswith("PRELIM_ANZSOC_2023_")
        rows.extend(family_rows)

    assert len(rows) == 2371
    assert sum(row["value"] == 0 for row in rows) == 204
    assert {row["source_sheet"] for row in rows} == {
        f"ANZSOC 2023 Table {table}" for table in range(1, 7)
    }
    concordance_rows = [
        row for row in rows if row["source_sheet"] == "ANZSOC 2023 Table 6"
    ]
    assert len(concordance_rows) == 306
    assert all(
        str(row["principal_offence_anzsoc_2011_id"]).startswith("ANZSOC_2011_")
        for row in concordance_rows
    )
    assert all(
        "principal_offence_anzsoc_2011_id" not in row
        for row in rows
        if row["source_sheet"] != "ANZSOC 2023 Table 6"
    )
    method_family = PRELIMINARY_ANZSOC_2023_FAMILIES[4]
    assert warning_dimensions == {
        family_id: ({"method_of_finalisation"} if family_id == method_family else set())
        for family_id in PRELIMINARY_ANZSOC_2023_FAMILIES
    }
    method_contract = _load(FIXTURES / "acceptance" / f"{method_family}-v1.json")
    warning_rule = method_contract["allowedExecutionWarnings"][0]
    assert warning_rule["requireCanonicalOutputEquivalence"] is True
    assert {
        header_source
        for sources in warning_rule["expectedHeaderSourcesByYear"]["2023"].values()
        for header_source in sources
    } == {"R5C2", "R24C2", "R43C2", "R62C2", "R81C2", "R100C2"}


def test_new_south_wales_cluster_preserves_source_and_classification() -> None:
    membership = _load(MEMBERSHIP)
    members = [
        member
        for family in membership["families"]
        for member in family["members"]
        if member["cubeId"] == "defendants-finalised-new-south-wales"
    ]
    assert len(members) == 22
    assert Counter(member["releaseId"] for member in members) == {
        "2021-22": 5,
        "2022-23": 5,
        "2023-24": 6,
        "2024-25": 6,
    }
    assert all(member["registered"] for member in members)

    source_books = {
        release: load_workbook(
            FIXTURES
            / next(
                member["sourcePath"]
                for member in members
                if member["releaseId"] == release
            ),
            data_only=False,
            read_only=False,
        )
        for release in {member["releaseId"] for member in members}
    }
    rows: list[dict[str, object]] = []
    source_cells: set[tuple[str, str, str]] = set()
    warning_dimensions: set[str] = set()
    warning_count = 0
    for family_id in NEW_SOUTH_WALES_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        assert manifest["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert manifest["canonicalObservationCount"] == len(family_rows)
        assert contract["totalValidation"] == "not_applicable"
        assert contract["totalEquations"] == []
        assert (
            manifest["warningCountsByYear"] == contract["expectedWarningCountsByYear"]
        )
        observed_warning_counts = {
            str(workbook["year"]): workbook["executionWarningCount"]
            for workbook in run["workbooks"]
        }
        assert observed_warning_counts == contract["expectedWarningCountsByYear"]
        warning_count += sum(observed_warning_counts.values())
        warning_dimensions.update(
            rule["dimension"] for rule in contract["allowedExecutionWarnings"]
        )
        assert all(
            rule["requireCanonicalOutputEquivalence"] is True
            and set(rule["expectedHeaderSourcesByYear"])
            == {str(year) for year in manifest["manualReplayYears"]}
            for rule in contract["allowedExecutionWarnings"]
        )

        for row in family_rows:
            match = re.fullmatch(r"R([0-9]+)C([0-9]+)", str(row["source_cell"]))
            assert match is not None
            release_start = int(str(row["publication_vintage_date"])[:4]) - 1
            release = f"{release_start}-{str(release_start + 1)[-2:]}"
            cell = source_books[release][str(row["source_sheet"])].cell(
                row=int(match.group(1)), column=int(match.group(2))
            )
            assert cell.value == row["raw_value"]
            source_key = (
                str(row["source_workbook_digest"]),
                str(row["source_sheet"]),
                str(row["source_cell"]),
            )
            assert source_key not in source_cells
            source_cells.add(source_key)
            assert row["reference_date"] == row["observation_period_id"]
            assert row["jurisdiction_id"] == "NSW"
        rows.extend(family_rows)

    assert len(rows) == 17_691
    assert len(source_cells) == len(rows)
    assert Counter(str(row["measure_id"]) for row in rows) == {
        "defendant-count": 16_827,
        "mean-case-duration": 216,
        "mean-defendant-age": 216,
        "median-case-duration": 216,
        "median-defendant-age": 216,
    }
    assert Counter(str(row["value_status"]) for row in rows) == {
        "observed": 17_578,
        "not_applicable": 61,
        "not_available": 52,
    }
    assert sum(row["value"] == 0 for row in rows) == 926
    assert {str(row["classification_context_id"]) for row in rows} == {
        "ANZSOC_2011",
        "ANZSOC_2023",
        "MIXED_CONCORDED_ANZSOC_2011_AND_ANZSOC_2023",
    }
    old_offences = {
        str(row["principal_offence_id"])
        for row in rows
        if row.get("classification_context_id") == "ANZSOC_2011"
        and "principal_offence_id" in row
    }
    new_offences = {
        str(row["principal_offence_id"])
        for row in rows
        if row.get("classification_context_id") == "ANZSOC_2023"
        and "principal_offence_id" in row
    }
    assert old_offences & new_offences
    assert warning_dimensions == {"court_level", "observation_period"}
    assert warning_count == 10_807
    assert any(row["publication_vintage_date"] != row["reference_date"] for row in rows)
    assert "Table 19 " in {str(row["source_sheet"]) for row in rows}
    with (
        FIXTURES / f"{NEW_SOUTH_WALES_FAMILIES[5]}-evidence/canonical-observations.csv"
    ).open(newline="") as handle:
        assert "Table 19 " in {row["source_sheet"] for row in csv.DictReader(handle)}


def test_victoria_cluster_preserves_source_and_classification() -> None:
    membership = _load(MEMBERSHIP)
    members = [
        member
        for family in membership["families"]
        for member in family["members"]
        if member["cubeId"] == "defendants-finalised-victoria"
    ]
    assert len(members) == 22
    assert Counter(member["releaseId"] for member in members) == {
        "2021-22": 5,
        "2022-23": 5,
        "2023-24": 6,
        "2024-25": 6,
    }
    assert all(member["registered"] for member in members)

    source_books = {
        release: load_workbook(
            FIXTURES
            / next(
                member["sourcePath"]
                for member in members
                if member["releaseId"] == release
            ),
            data_only=False,
            read_only=False,
        )
        for release in {member["releaseId"] for member in members}
    }
    rows: list[dict[str, object]] = []
    source_cells: set[tuple[str, str, str]] = set()
    warning_dimensions: set[str] = set()
    warning_header_sources: dict[str, set[str]] = {}
    warning_count = 0
    for family_id in VICTORIA_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        assert manifest["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert manifest["canonicalObservationCount"] == len(family_rows)
        assert contract["totalValidation"] == "not_applicable"
        assert contract["totalEquations"] == []
        assert (
            manifest["warningCountsByYear"] == contract["expectedWarningCountsByYear"]
        )
        observed_warning_counts = {
            str(workbook["year"]): workbook["executionWarningCount"]
            for workbook in run["workbooks"]
        }
        assert observed_warning_counts == contract["expectedWarningCountsByYear"]
        warning_count += sum(observed_warning_counts.values())
        warning_dimensions.update(
            rule["dimension"] for rule in contract["allowedExecutionWarnings"]
        )
        assert contract["trainingEligibility"] is False
        cohort = _load(FIXTURES / f"{family_id}.json")
        assert all(
            workbook["replayResponse"]["acceptanceAuthority"] is False
            for workbook in cohort["workbooks"]
        )
        for rule in contract["allowedExecutionWarnings"]:
            assert rule["requireCanonicalOutputEquivalence"] is True
            assert set(rule["expectedHeaderSourcesByYear"]) == {
                str(year) for year in manifest["manualReplayYears"]
            }
            sources = warning_header_sources.setdefault(rule["dimension"], set())
            sources.update(
                source
                for aliases in rule["expectedHeaderSourcesByYear"].values()
                for bound_sources in aliases.values()
                for source in bound_sources
            )

        for row in family_rows:
            match = re.fullmatch(r"R([0-9]+)C([0-9]+)", str(row["source_cell"]))
            assert match is not None
            release_start = int(str(row["publication_vintage_date"])[:4]) - 1
            release = f"{release_start}-{str(release_start + 1)[-2:]}"
            cell = source_books[release][str(row["source_sheet"])].cell(
                row=int(match.group(1)), column=int(match.group(2))
            )
            assert cell.value == row["raw_value"]
            source_key = (
                str(row["source_workbook_digest"]),
                str(row["source_sheet"]),
                str(row["source_cell"]),
            )
            assert source_key not in source_cells
            source_cells.add(source_key)
            assert row["reference_date"] == row["observation_period_id"]
            assert row["jurisdiction_id"] == "VIC"
        rows.extend(family_rows)

    assert len(rows) == 17_524
    assert len(source_cells) == len(rows)
    assert Counter(str(row["measure_id"]) for row in rows) == {
        "defendant-count": 16_660,
        "mean-case-duration": 216,
        "mean-defendant-age": 216,
        "median-case-duration": 216,
        "median-defendant-age": 216,
    }
    assert Counter(str(row["value_status"]) for row in rows) == {
        "observed": 17_411,
        "not_applicable": 61,
        "not_available": 52,
    }
    assert {
        (row["raw_value"], row["value_status"])
        for row in rows
        if row["value_status"] != "observed"
    } == {("..", "not_applicable"), ("na", "not_available")}
    assert sum(row["value"] == 0 for row in rows) == 1_419
    assert {str(row["classification_context_id"]) for row in rows} == {
        "ANZSOC_2011",
        "ANZSOC_2023",
        "MIXED_CONCORDED_ANZSOC_2011_AND_ANZSOC_2023",
    }
    old_offences = {
        str(row["principal_offence_id"])
        for row in rows
        if row.get("classification_context_id") == "ANZSOC_2011"
        and "principal_offence_id" in row
    }
    new_offences = {
        str(row["principal_offence_id"])
        for row in rows
        if row.get("classification_context_id") == "ANZSOC_2023"
        and "principal_offence_id" in row
    }
    assert old_offences & new_offences
    assert warning_dimensions == {"court_level", "observation_period"}
    assert warning_header_sources == {
        "court_level": {
            "R5C2",
            "R6C2",
            "R55C2",
            "R61C2",
            "R62C2",
            "R104C2",
            "R117C2",
            "R118C2",
            "R153C2",
            "R173C2",
            "R174C2",
        },
        "observation_period": {
            "R5C2",
            "R6C2",
            "R28C2",
            "R29C2",
            "R30C2",
            "R31C2",
        },
    }
    assert warning_count == 10_720
    assert any(row["publication_vintage_date"] != row["reference_date"] for row in rows)
    assert "Table 32" in {str(row["source_sheet"]) for row in rows}
    with (
        FIXTURES / f"{VICTORIA_FAMILIES[3]}-evidence/canonical-observations.csv"
    ).open(newline="") as handle:
        assert "Table 32" in {row["source_sheet"] for row in csv.DictReader(handle)}


def test_queensland_cluster_preserves_source_classification_and_warnings() -> None:
    membership = _load(MEMBERSHIP)
    members = [
        member
        for family in membership["families"]
        for member in family["members"]
        if member["cubeId"] == "defendants-finalised-queensland"
    ]
    assert len(members) == 22
    assert Counter(member["releaseId"] for member in members) == {
        "2021-22": 5,
        "2022-23": 5,
        "2023-24": 6,
        "2024-25": 6,
    }
    assert all(member["registered"] for member in members)

    source_books = {
        release: load_workbook(
            FIXTURES
            / next(
                member["sourcePath"]
                for member in members
                if member["releaseId"] == release
            ),
            data_only=False,
            read_only=False,
        )
        for release in {member["releaseId"] for member in members}
    }
    rows: list[dict[str, object]] = []
    source_cells: set[tuple[str, str, str]] = set()
    warning_dimensions: set[str] = set()
    warning_header_sources: dict[str, set[str]] = {}
    warning_count = 0
    for family_id in QUEENSLAND_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        cohort = _load(FIXTURES / f"{family_id}.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        assert manifest["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert manifest["canonicalObservationCount"] == len(family_rows)
        assert contract["totalValidation"] == "not_applicable"
        assert contract["totalEquations"] == []
        assert contract["trainingEligibility"] is False
        assert all(
            workbook["replayResponse"]["acceptanceAuthority"] is False
            for workbook in cohort["workbooks"]
        )
        observed_warning_counts = {
            str(workbook["year"]): workbook["executionWarningCount"]
            for workbook in run["workbooks"]
        }
        assert observed_warning_counts == contract["expectedWarningCountsByYear"]
        assert observed_warning_counts == manifest["warningCountsByYear"]
        warning_count += sum(observed_warning_counts.values())
        warning_dimensions.update(
            rule["dimension"] for rule in contract["allowedExecutionWarnings"]
        )
        for rule in contract["allowedExecutionWarnings"]:
            assert rule["requireCanonicalOutputEquivalence"] is True
            assert set(rule["expectedHeaderSourcesByYear"]) == {
                str(year) for year in manifest["manualReplayYears"]
            }
            warning_header_sources.setdefault(rule["dimension"], set()).update(
                source
                for aliases in rule["expectedHeaderSourcesByYear"].values()
                for bound_sources in aliases.values()
                for source in bound_sources
            )

        for row in family_rows:
            match = re.fullmatch(r"R([0-9]+)C([0-9]+)", str(row["source_cell"]))
            assert match is not None
            release_start = int(str(row["publication_vintage_date"])[:4]) - 1
            release = f"{release_start}-{str(release_start + 1)[-2:]}"
            cell = source_books[release][str(row["source_sheet"])].cell(
                row=int(match.group(1)), column=int(match.group(2))
            )
            assert cell.value == row["raw_value"]
            source_key = (
                str(row["source_workbook_digest"]),
                str(row["source_sheet"]),
                str(row["source_cell"]),
            )
            assert source_key not in source_cells
            source_cells.add(source_key)
            assert row["reference_date"] == row["observation_period_id"]
            assert row["jurisdiction_id"] == "QLD"
        rows.extend(family_rows)

    assert len(rows) == 17_415
    assert len(source_cells) == len(rows)
    assert Counter(str(row["measure_id"]) for row in rows) == {
        "defendant-count": 16_551,
        "mean-case-duration": 216,
        "mean-defendant-age": 216,
        "median-case-duration": 216,
        "median-defendant-age": 216,
    }
    assert Counter(str(row["value_status"]) for row in rows) == {
        "observed": 17_162,
        "not_available": 136,
        "not_applicable": 117,
    }
    assert {
        (row["raw_value"], row["value_status"])
        for row in rows
        if row["value_status"] != "observed"
    } == {("..", "not_applicable"), ("na", "not_available")}
    assert sum(row["value"] == 0 for row in rows) == 986
    assert {str(row["classification_context_id"]) for row in rows} == {
        "ANZSOC_2011",
        "ANZSOC_2023",
        "MIXED_CONCORDED_ANZSOC_2011_AND_ANZSOC_2023",
    }
    assert warning_dimensions == {"court_level", "observation_period"}
    assert warning_header_sources == {
        "court_level": {
            "R5C2",
            "R6C2",
            "R55C2",
            "R61C2",
            "R62C2",
            "R104C2",
            "R117C2",
            "R118C2",
            "R153C2",
            "R173C2",
            "R174C2",
        },
        "observation_period": {
            "R5C2",
            "R6C2",
            "R28C2",
            "R29C2",
            "R30C2",
            "R31C2",
        },
    }
    assert warning_count == 10_640
    assert any(row["publication_vintage_date"] != row["reference_date"] for row in rows)


def test_australian_capital_territory_aliases_are_exhaustively_source_bound() -> None:
    def normalize(value: str) -> str:
        return " ".join(value.strip().split())

    aliases: dict[tuple[str, str], str] = {}
    represented: set[tuple[str, str]] = set()
    aggregate_alias_count = 0
    for family_id in AUSTRALIAN_CAPITAL_TERRITORY_FAMILIES:
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        for dimension, dimension_aliases in contract["aliases"].items():
            aggregate_alias_count += len(dimension_aliases)
            for raw, target in dimension_aliases.items():
                identity = (dimension, normalize(raw))
                previous = aliases.setdefault(identity, target)
                assert previous == target, f"normalized alias collision: {identity}"
        rows = json.loads(
            (FIXTURES / f"{family_id}-evidence/canonical-observations.json").read_text()
        )
        for row in rows:
            for dimension in contract["requiredDimensions"]:
                raw_field = f"raw_{dimension}"
                identity = (dimension, normalize(str(row[raw_field])))
                represented.add(identity)
                target_field = product_prototype_module._DIMENSION_FIELDS[dimension]
                assert row[target_field] == aliases[identity]

    assert aggregate_alias_count == 630
    workbook_strings: set[str] = set()
    for release in ("2021-22", "2022-23", "2023-24", "2024-25"):
        for kind in ("source", "normalized"):
            path = (
                FIXTURES
                / "workbooks"
                / f"criminal-courts-{release}-cube-11-{kind}.xlsx"
            )
            workbook = load_workbook(path, data_only=False, read_only=True)
            try:
                workbook_strings.update(
                    normalize(cell.value)
                    for sheet in workbook.worksheets
                    for row in sheet.iter_rows()
                    for cell in row
                    if isinstance(cell.value, str)
                )
            finally:
                workbook.close()
    assert {raw for _dimension, raw in aliases} <= workbook_strings
    assert set(aliases) - represented == set()


def test_australian_capital_territory_cluster_preserves_exact_semantics() -> None:
    membership = _load(MEMBERSHIP)
    families = {
        family["familyId"]: family
        for family in membership["families"]
        if family["familyId"] in AUSTRALIAN_CAPITAL_TERRITORY_FAMILIES
    }
    assert set(families) == set(AUSTRALIAN_CAPITAL_TERRITORY_FAMILIES)
    members = [member for family in families.values() for member in family["members"]]
    assert len(members) == 22
    assert Counter(member["releaseId"] for member in members) == {
        "2021-22": 5,
        "2022-23": 5,
        "2023-24": 6,
        "2024-25": 6,
    }
    assert all(member["registered"] for member in members)
    assert {member["cubeId"] for member in members} == {
        "defendants-finalised-australian-capital-territory"
    }
    assert all(
        "Australian Capital Territory" in member["publishedTitle"] for member in members
    )
    assert families[AUSTRALIAN_CAPITAL_TERRITORY_FAMILIES[-1]]["semanticTitle"] == (
        "Defendants finalised, summary characteristics by court level — "
        "mixed concorded history — Australian Capital Territory"
    )

    workbooks = {
        release: load_workbook(
            FIXTURES
            / "workbooks"
            / f"criminal-courts-{release}-cube-11-normalized.xlsx",
            data_only=False,
            read_only=False,
        )
        for release in ("2021-22", "2022-23", "2023-24", "2024-25")
    }
    rows: list[dict[str, object]] = []
    source_cells: set[tuple[str, str, str]] = set()
    warning_count = 0
    for family_id in AUSTRALIAN_CAPITAL_TERRITORY_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        cohort = _load(FIXTURES / f"{family_id}.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        assert contract["schemaVersion"] == "tidy.table-family-acceptance/v2"
        assert contract["trainingEligibility"] is False
        assert manifest["canonicalObservationCount"] == len(family_rows)
        assert manifest["providerCalls"] == run["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert run["historicalReplayIsAcceptanceAuthority"] is False
        assert run["trainingEligibility"] is False
        assert all(
            workbook["replayResponse"]["acceptanceAuthority"] is False
            for workbook in cohort["workbooks"]
        )
        observed_warnings = {
            str(workbook["year"]): workbook["executionWarningCount"]
            for workbook in run["workbooks"]
        }
        assert observed_warnings == contract["expectedWarningCountsByYear"]
        assert observed_warnings == manifest["warningCountsByYear"]
        warning_count += sum(observed_warnings.values())
        decisions = {
            (workbook["workbookDigest"], workbook["sheet"]): workbook["decisionId"]
            for workbook in run["workbooks"]
        }
        for row in family_rows:
            match = re.fullmatch(r"R([0-9]+)C([0-9]+)", str(row["source_cell"]))
            assert match is not None
            release_start = int(str(row["publication_vintage_date"])[:4]) - 1
            release = f"{release_start}-{str(release_start + 1)[-2:]}"
            cell = workbooks[release][str(row["source_sheet"])].cell(
                row=int(match.group(1)), column=int(match.group(2))
            )
            assert cell.value == row["raw_value"]
            assert cell.data_type != "f"
            key = (
                str(row["source_workbook_digest"]),
                str(row["source_sheet"]),
                str(row["source_cell"]),
            )
            assert key not in source_cells
            source_cells.add(key)
            assert row["acceptance_decision_digest"] == decisions[key[:2]]
            assert row["reference_date"] == row["observation_period_id"]
            assert row["jurisdiction_id"] == "ACT"
        rows.extend(family_rows)

    assert len(rows) == len(source_cells) == 16_057
    assert Counter(str(row["measure_id"]) for row in rows) == {
        "defendant-count": 15_193,
        "mean-case-duration": 216,
        "mean-defendant-age": 216,
        "median-case-duration": 216,
        "median-defendant-age": 216,
    }
    assert Counter(str(row["value_status"]) for row in rows) == {
        "observed": 15_920,
        "not_available": 88,
        "not_applicable": 49,
    }
    assert {
        (row["raw_value"], row["value_status"])
        for row in rows
        if row["value_status"] != "observed"
    } == {("..", "not_applicable"), ("na", "not_available")}
    assert sum(row["value"] == 0 for row in rows) == 2_844
    assert Counter(str(row["classification_context_id"]) for row in rows) == {
        "ANZSOC_2011": 11_283,
        "ANZSOC_2023": 2_104,
        "MIXED_CONCORDED_ANZSOC_2011_AND_ANZSOC_2023": 2_670,
    }
    assert warning_count == 9_969
    method_ids = {
        "CHAR_GUILTY_EX_PARTE",
        "CHAR_TRANSFER_TO_OTHER_COURT_LEVELS",
        "CHAR_WITHDRAWN_BY_PROSECUTION",
        "CHAR_TOTAL_FINALISED",
    }
    assert all(
        row["characteristic_group_id"] == "GROUP_METHOD_OF_FINALISATION"
        for row in rows
        if row.get("characteristic_category_id") in method_ids
    )
    assert not any(
        row.get("characteristic_group_id") == "GROUP_GUILTY_EX_PARTE" for row in rows
    )


def test_tasmania_aliases_are_exhaustively_source_bound() -> None:
    def normalize(value: str) -> str:
        return " ".join(value.strip().split())

    aliases: dict[tuple[str, str], str] = {}
    represented: set[tuple[str, str]] = set()
    aggregate_alias_count = 0
    for family_id in TASMANIA_FAMILIES:
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        for dimension, dimension_aliases in contract["aliases"].items():
            aggregate_alias_count += len(dimension_aliases)
            for raw, target in dimension_aliases.items():
                identity = (dimension, normalize(raw))
                previous = aliases.setdefault(identity, target)
                assert previous == target, f"normalized alias collision: {identity}"
        rows = json.loads(
            (FIXTURES / f"{family_id}-evidence/canonical-observations.json").read_text()
        )
        for row in rows:
            for dimension in contract["requiredDimensions"]:
                identity = (dimension, normalize(str(row[f"raw_{dimension}"])))
                represented.add(identity)
                assert (
                    row[product_prototype_module._DIMENSION_FIELDS[dimension]]
                    == (aliases[identity])
                )

    assert aggregate_alias_count == 759
    workbook_strings: set[str] = set()
    for release in ("2021-22", "2022-23", "2023-24", "2024-25"):
        for kind in ("source", "normalized"):
            workbook = load_workbook(
                FIXTURES
                / "workbooks"
                / f"criminal-courts-{release}-cube-9-{kind}.xlsx",
                data_only=False,
                read_only=True,
            )
            try:
                workbook_strings.update(
                    normalize(cell.value)
                    for sheet in workbook.worksheets
                    for row in sheet.iter_rows()
                    for cell in row
                    if isinstance(cell.value, str)
                )
            finally:
                workbook.close()
    assert {raw for _dimension, raw in aliases} <= workbook_strings
    assert set(aliases) - represented == set()


def test_tasmania_cluster_preserves_exact_semantics() -> None:
    membership = _load(MEMBERSHIP)
    families = {
        family["familyId"]: family
        for family in membership["families"]
        if family["familyId"] in TASMANIA_FAMILIES
    }
    assert set(families) == set(TASMANIA_FAMILIES)
    members = [member for family in families.values() for member in family["members"]]
    assert len(members) == 22
    assert Counter(member["releaseId"] for member in members) == {
        "2021-22": 5,
        "2022-23": 5,
        "2023-24": 6,
        "2024-25": 6,
    }
    assert all(member["registered"] for member in members)
    assert {member["cubeId"] for member in members} == {"defendants-finalised-tasmania"}
    legacy = families[TASMANIA_FAMILIES[5]]["members"]
    proper = families[TASMANIA_FAMILIES[6]]["members"]
    assert [item["releaseId"] for item in legacy] == ["2021-22", "2022-23"]
    en_dash = "\N{EN DASH}"
    assert all(
        f"Magistrates' Courts {en_dash}Tasmania" in item["publishedTitle"]
        for item in legacy
    )
    assert [item["releaseId"] for item in proper] == ["2023-24"]
    assert f"Magistrates' Courts {en_dash} Tasmania" in proper[0]["publishedTitle"]
    assert families[TASMANIA_FAMILIES[8]]["semanticTitle"] == (
        "Defendants finalised, summary characteristics by court level — "
        "mixed concorded history — Tasmania"
    )
    assert (
        "concorded from ANZSOC 2011"
        in families[TASMANIA_FAMILIES[8]]["members"][0]["publishedTitle"]
    )

    workbooks = {
        release: load_workbook(
            FIXTURES
            / "workbooks"
            / f"criminal-courts-{release}-cube-9-normalized.xlsx",
            data_only=False,
            read_only=False,
        )
        for release in ("2021-22", "2022-23", "2023-24", "2024-25")
    }
    rows: list[dict[str, object]] = []
    source_cells: set[tuple[str, str, str]] = set()
    warning_count = 0
    for family_id in TASMANIA_FAMILIES:
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        cohort = _load(FIXTURES / f"{family_id}.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        assert contract["schemaVersion"] == "tidy.table-family-acceptance/v2"
        assert contract["trainingEligibility"] is False
        assert contract["totalEquations"] == []
        assert contract["totalValidation"] == "not_applicable"
        assert manifest["canonicalObservationCount"] == len(family_rows)
        assert manifest["providerCalls"] == run["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert run["historicalReplayIsAcceptanceAuthority"] is False
        assert all(
            workbook["replayResponse"]["acceptanceAuthority"] is False
            for workbook in cohort["workbooks"]
        )
        observed_warnings = {
            str(workbook["year"]): workbook["executionWarningCount"]
            for workbook in run["workbooks"]
        }
        assert observed_warnings == contract["expectedWarningCountsByYear"]
        assert observed_warnings == manifest["warningCountsByYear"]
        warning_count += sum(observed_warnings.values())
        decisions = {
            (workbook["workbookDigest"], workbook["sheet"]): workbook["decisionId"]
            for workbook in run["workbooks"]
        }
        for row in family_rows:
            match = re.fullmatch(r"R([0-9]+)C([0-9]+)", str(row["source_cell"]))
            assert match is not None
            release_start = int(str(row["publication_vintage_date"])[:4]) - 1
            release = f"{release_start}-{str(release_start + 1)[-2:]}"
            cell = workbooks[release][str(row["source_sheet"])].cell(
                row=int(match.group(1)), column=int(match.group(2))
            )
            assert cell.value == row["raw_value"]
            assert cell.data_type != "f"
            key = (
                str(row["source_workbook_digest"]),
                str(row["source_sheet"]),
                str(row["source_cell"]),
            )
            assert key not in source_cells
            source_cells.add(key)
            assert row["acceptance_decision_digest"] == decisions[key[:2]]
            assert row["reference_date"] == row["observation_period_id"]
            assert row["jurisdiction_id"] == "TAS"
        rows.extend(family_rows)

    assert len(rows) == len(source_cells) == 16_545
    assert Counter(str(row["measure_id"]) for row in rows) == {
        "defendant-count": 15_681,
        "mean-case-duration": 216,
        "mean-defendant-age": 216,
        "median-case-duration": 216,
        "median-defendant-age": 216,
    }
    assert Counter((str(row["measure_id"]), str(row["unit_id"])) for row in rows) == {
        ("defendant-count", "person"): 15_681,
        ("mean-case-duration", "week"): 216,
        ("mean-defendant-age", "year"): 216,
        ("median-case-duration", "week"): 216,
        ("median-defendant-age", "year"): 216,
    }
    assert Counter(str(row["value_status"]) for row in rows) == {
        "observed": 16_324,
        "suppressed": 129,
        "not_applicable": 53,
        "not_available": 39,
    }
    assert Counter(
        (row["raw_value"], row["value_status"])
        for row in rows
        if row["value_status"] != "observed"
    ) == {
        ("np", "suppressed"): 129,
        ("..", "not_applicable"): 53,
        ("na", "not_available"): 39,
    }
    assert sum(row["value"] == 0 for row in rows) == 2_342
    assert Counter(str(row["classification_context_id"]) for row in rows) == {
        "ANZSOC_2011": 11_622,
        "ANZSOC_2023": 2_268,
        "ANZSOC_2023_WITH_CONCORDED_ANZSOC_2011_SERIES": 2_655,
    }
    assert warning_count == 10_231
    assert Counter(
        (row["raw_principal_offence"], row["principal_offence_id"])
        for row in rows
        if "regulaton" in str(row.get("raw_principal_offence", "")).lower()
    ) == {
        (
            "163 Commercial/industry/financial regulaton",
            "OFFENCE_163_COMMERCIAL_INDUSTRY_FINANCIAL_REGULATION",
        ): 6
    }
    for row in rows:
        raw = str(row.get("raw_characteristic_category", "")).lower()
        if "excluding transfer" not in raw and any(
            term in raw for term in ("guilty ex-parte", "transfer", "withdraw")
        ):
            assert row["characteristic_group_id"] == "GROUP_METHOD_OF_FINALISATION"
        if raw.startswith("total finalised") and "excluding transfer" not in raw:
            assert row["characteristic_group_id"] == "GROUP_METHOD_OF_FINALISATION"
    assert all(
        row["characteristic_group_id"].startswith("GROUP_PRINCIPAL_OFFENCE")
        for row in rows
        if str(row.get("raw_characteristic_category", "")).startswith(
            "Total finalised (excluding transfer"
        )
    )


def test_northern_territory_aliases_are_exhaustively_source_bound() -> None:
    def normalize(value: str) -> str:
        return " ".join(value.strip().split())

    aliases: dict[tuple[str, str], str] = {}
    aggregate_alias_count = 0
    represented_aliases: set[tuple[str, str]] = set()
    for family_id in NORTHERN_TERRITORY_FAMILIES:
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        for dimension, dimension_aliases in contract["aliases"].items():
            aggregate_alias_count += len(dimension_aliases)
            for raw, target in dimension_aliases.items():
                identity = (dimension, normalize(raw))
                previous = aliases.setdefault(identity, target)
                assert previous == target, f"normalized alias collision: {identity}"

        rows = json.loads(
            (FIXTURES / f"{family_id}-evidence/canonical-observations.json").read_text()
        )
        for row in rows:
            for dimension in contract["requiredDimensions"]:
                raw_field = f"raw_{dimension}"
                assert raw_field in row
                identity = (dimension, normalize(str(row[raw_field])))
                represented_aliases.add(identity)
                assert identity in aliases
                target_field = product_prototype_module._DIMENSION_FIELDS[dimension]
                assert row[target_field] == aliases[identity]

    assert aggregate_alias_count == 750

    workbook_paths = {
        FIXTURES / "workbooks" / f"criminal-courts-{release}-cube-10-{kind}.xlsx"
        for release in ("2021-22", "2022-23", "2023-24", "2024-25")
        for kind in ("source", "normalized")
    }
    assert len(workbook_paths) == 8
    workbook_strings: set[str] = set()
    for path in workbook_paths:
        workbook = load_workbook(path, data_only=False, read_only=True)
        try:
            workbook_strings.update(
                normalize(cell.value)
                for sheet in workbook.worksheets
                for row in sheet.iter_rows()
                for cell in row
                if isinstance(cell.value, str)
            )
        finally:
            workbook.close()
    assert {raw for _dimension, raw in aliases} <= workbook_strings

    # No NT alias is justified only by a row excluded from canonical evidence. If
    # that changes, the excluded-row source cells must be added as a separate
    # authority rather than silently treating the contract as self-authorizing.
    source_only_excluded_aliases = set(aliases) - represented_aliases
    assert source_only_excluded_aliases == set()


def test_northern_territory_cluster_preserves_exact_source_semantics() -> None:
    membership = _load(MEMBERSHIP)
    nt_families = {
        family["familyId"]: family
        for family in membership["families"]
        if family["familyId"] in NORTHERN_TERRITORY_FAMILIES
    }
    assert set(nt_families) == set(NORTHERN_TERRITORY_FAMILIES)
    members = [
        member for family in nt_families.values() for member in family["members"]
    ]
    assert len(members) == 22
    assert Counter(member["releaseId"] for member in members) == {
        "2021-22": 5,
        "2022-23": 5,
        "2023-24": 6,
        "2024-25": 6,
    }
    assert all(member["registered"] for member in members)
    assert {member["cubeId"] for member in members} == {
        "defendants-finalised-northern-territory"
    }
    assert all("Northern Territory" in member["publishedTitle"] for member in members)
    assert nt_families[NORTHERN_TERRITORY_FAMILIES[-1]]["semanticTitle"] == (
        "Defendants finalised, summary characteristics by court level — "
        "mixed concorded history — Northern Territory"
    )

    expected_warning_counts = (
        {"2024": 342},
        {"2024": 342},
        {"2021": 306, "2022": 323, "2023": 323},
        {"2021": 144, "2022": 152, "2023": 152, "2024": 168},
        {"2021": 85, "2022": 90, "2023": 95, "2024": 95},
        {"2021": 306, "2022": 323, "2023": 323},
        {"2023": 0, "2024": 0},
        {"2021": 1308, "2022": 1690, "2023": 1862},
        {"2024": 1995},
    )
    source_books = {
        release: load_workbook(
            FIXTURES
            / next(
                member["sourcePath"]
                for member in members
                if member["releaseId"] == release
            ),
            data_only=False,
            read_only=False,
        )
        for release in {member["releaseId"] for member in members}
    }
    rows: list[dict[str, object]] = []
    source_cells: set[tuple[str, str, str]] = set()
    warning_sources: dict[str, set[str]] = {}
    warning_count = 0
    for family_id, expected_counts in zip(
        NORTHERN_TERRITORY_FAMILIES, expected_warning_counts, strict=True
    ):
        evidence = FIXTURES / f"{family_id}-evidence"
        manifest = _load(evidence / "manifest.json")
        contract = _load(FIXTURES / "acceptance" / f"{family_id}-v1.json")
        cohort = _load(FIXTURES / f"{family_id}.json")
        run = _load(evidence / "run.json")
        family_rows = json.loads((evidence / "canonical-observations.json").read_text())
        assert manifest["canonicalObservationCount"] == len(family_rows)
        assert manifest["providerCalls"] == run["providerCalls"] == 0
        assert manifest["exceptionWorkbookCount"] == 0
        assert run["historicalReplayIsAcceptanceAuthority"] is False
        assert all(
            workbook["decision"] == "prototype_auto_accepted"
            for workbook in run["workbooks"]
        )
        assert all(
            workbook["replayResponse"]["acceptanceAuthority"] is False
            for workbook in cohort["workbooks"]
        )
        observed_warning_counts = {
            str(workbook["year"]): workbook["executionWarningCount"]
            for workbook in run["workbooks"]
        }
        assert observed_warning_counts == expected_counts
        assert observed_warning_counts == contract["expectedWarningCountsByYear"]
        assert observed_warning_counts == manifest["warningCountsByYear"]
        warning_count += sum(observed_warning_counts.values())
        for rule in contract["allowedExecutionWarnings"]:
            assert rule["code"] == "AMBIGUOUS_HEADER"
            assert rule["requireCanonicalOutputEquivalence"] is True
            assert set(rule["expectedHeaderSourcesByYear"]) == set(expected_counts)
            warning_sources.setdefault(rule["dimension"], set()).update(
                source
                for resolved_headers in rule["expectedHeaderSourcesByYear"].values()
                for bound_sources in resolved_headers.values()
                for source in bound_sources
            )

        decisions = {
            (workbook["workbookDigest"], workbook["sheet"]): workbook["decisionId"]
            for workbook in run["workbooks"]
        }
        for row in family_rows:
            match = re.fullmatch(r"R([0-9]+)C([0-9]+)", str(row["source_cell"]))
            assert match is not None
            release_start = int(str(row["publication_vintage_date"])[:4]) - 1
            release = f"{release_start}-{str(release_start + 1)[-2:]}"
            cell = source_books[release][str(row["source_sheet"])].cell(
                row=int(match.group(1)), column=int(match.group(2))
            )
            assert cell.value == row["raw_value"]
            assert cell.data_type != "f"
            source_key = (
                str(row["source_workbook_digest"]),
                str(row["source_sheet"]),
                str(row["source_cell"]),
            )
            assert source_key not in source_cells
            source_cells.add(source_key)
            assert row["acceptance_decision_digest"] == decisions[source_key[:2]]
            assert row["reference_date"] == row["observation_period_id"]
            assert row["jurisdiction_id"] == "NT"
        rows.extend(family_rows)

    assert len(rows) == len(source_cells) == 16_931
    assert Counter(str(row["measure_id"]) for row in rows) == {
        "defendant-count": 16_067,
        "mean-case-duration": 216,
        "mean-defendant-age": 216,
        "median-case-duration": 216,
        "median-defendant-age": 216,
    }
    assert Counter(str(row["value_status"]) for row in rows) == {
        "observed": 16_794,
        "not_available": 88,
        "not_applicable": 49,
    }
    assert {
        (row["raw_value"], row["value_status"])
        for row in rows
        if row["value_status"] != "observed"
    } == {("..", "not_applicable"), ("na", "not_available")}
    assert sum(row["value"] == 0 for row in rows) == 2_913
    assert {str(row["classification_context_id"]) for row in rows} == {
        "ANZSOC_2011",
        "ANZSOC_2023",
        "MIXED_CONCORDED_ANZSOC_2011_AND_ANZSOC_2023",
    }
    assert warning_count == 10_424
    assert warning_sources == {
        "court_level": {
            "R55C2",
            "R61C2",
            "R62C2",
            "R104C2",
            "R117C2",
            "R118C2",
            "R153C2",
            "R173C2",
            "R174C2",
        },
        "observation_period": {"R28C2", "R29C2", "R30C2", "R31C2"},
    }

    nbsp_offence = "14\u00a0Offences against justice procedures and orders(c)"
    assert source_books["2024-25"]["Table 59"]["O5"].value == nbsp_offence
    assert any(row.get("raw_principal_offence") == nbsp_offence for row in rows)
    all_courts_contract = _load(
        FIXTURES / "acceptance" / f"{NORTHERN_TERRITORY_FAMILIES[0]}-v1.json"
    )
    assert (
        all_courts_contract["aliases"]["principal_offence"][nbsp_offence]
        == "OFFENCE_14_OFFENCES_AGAINST_JUSTICE_PROCEDURES_AND_ORDERS"
    )
    mixed_contract = _load(
        FIXTURES / "acceptance" / f"{NORTHERN_TERRITORY_FAMILIES[-1]}-v1.json"
    )
    mixed_sheet = source_books["2024-25"]["Table 57"]
    mixed_variants = {
        "A17": ("01 Homicide(e)", "CHAR_01_HOMICIDE"),
        "A20": (
            "04 Harm or endanger persons(f)",
            "CHAR_04_HARM_OR_ENDANGER_PERSONS",
        ),
        "A29": (
            "13 Traffic and vehicle offences(g)",
            "CHAR_13_TRAFFIC_AND_VEHICLE_OFFENCES",
        ),
        "A30": (
            "14 Offences against justice procedures and orders(h)",
            "CHAR_14_OFFENCES_AGAINST_JUSTICE_PROCEDURES_AND_ORDERS",
        ),
        "A34": (
            "Total finalised (excluding transfer to other court levels)(i)",
            "CHAR_TOTAL_FINALISED_EXCLUDING_TRANSFER_TO_OTHER_COURT_LEVELS",
        ),
        "A37": ("Mean (weeks)(k)", "CHAR_MEAN_WEEKS"),
        "A38": ("Median (weeks)(k)", "CHAR_MEDIAN_WEEKS"),
        "A55": ("Community service / work(t)", "CHAR_COMMUNITY_SERVICE_WORK"),
        "A56": (
            "Moderate penalty in the community(t)",
            "CHAR_MODERATE_PENALTY_IN_THE_COMMUNITY",
        ),
        "A57": ("Monetary penalties(u)", "CHAR_MONETARY_PENALTIES"),
        "A58": ("Fines(g)", "CHAR_FINES"),
        "A59": (
            "Good behaviour (incl. bonds)(t)",
            "CHAR_GOOD_BEHAVIOUR_INCL_BONDS",
        ),
        "A61": ("Total guilty outcome(v)", "CHAR_TOTAL_GUILTY_OUTCOME"),
    }
    for cell, (source_label, canonical_label) in mixed_variants.items():
        assert mixed_sheet[cell].value == source_label
        assert (
            mixed_contract["aliases"]["characteristic_category"][source_label]
            == canonical_label
        )
    assert mixed_sheet["A16"].value == "Principal offence (ANZSOC 2023)(d)"
    assert (
        mixed_contract["aliases"]["characteristic_group"][
            "Principal offence (ANZSOC 2023)(d)"
        ]
        == "GROUP_PRINCIPAL_OFFENCE_ANZSOC_2023_WITH_CONCORDED_ANZSOC_2011_SERIES"
    )
    assert mixed_sheet["A36"].value == "Duration(j)"
    assert (
        mixed_contract["aliases"]["characteristic_group"]["Duration(j)"]
        == "GROUP_DURATION"
    )
    assert not any(
        row.get("characteristic_group_id") == "GROUP_GUILTY_EX_PARTE" for row in rows
    )
    method_rows = [
        row
        for row in rows
        if row.get("characteristic_group_id") == "GROUP_METHOD_OF_FINALISATION"
    ]
    assert len(method_rows) == 5_372
    assert len({str(row["characteristic_category_id"]) for row in method_rows}) == 10
    assert (
        sum(
            row.get("characteristic_category_id") == "CHAR_GUILTY_EX_PARTE"
            for row in method_rows
        )
        == 551
    )
    assert Counter(
        str(row["method_of_finalisation_id"])
        for row in rows
        if "method_of_finalisation_id" in row
    ) == {
        "METHOD_ACQUITTED": 105,
        "METHOD_GUILTY_OUTCOME": 105,
        "METHOD_TOTAL": 105,
        "METHOD_TOTAL_ADJUDICATED": 105,
        "METHOD_TRANSFER_TO_OTHER_COURT_LEVELS": 105,
        "METHOD_WITHDRAWN_BY_PROSECUTION": 105,
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
