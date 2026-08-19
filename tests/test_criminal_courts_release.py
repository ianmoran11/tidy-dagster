from __future__ import annotations

import copy
import csv
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from openpyxl import load_workbook

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
        "registeredMemberCount": 126,
        "pendingSemanticContractCount": 304,
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
        == 126
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
    assert json.loads(cli.stdout)["registeredMemberCount"] == 126
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
