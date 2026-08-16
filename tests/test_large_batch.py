from __future__ import annotations

import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from tidy_orchestrator.large_batch import (
    LargeBatchError,
    load_large_batch_registry,
    verify_batch_normalization,
    verify_large_batch_evidence,
)
from tidy_orchestrator.large_batch_cli import run_batch
from tidy_orchestrator.product_prototype import (
    ProductPrototypeError,
    _validate_cohort,
    _validate_contract,
    _validate_expected_coverage,
)

PROJECT = Path(__file__).parents[1]


@pytest.fixture(scope="module", autouse=True)
def ensure_domain_worker_is_built() -> None:
    worker = PROJECT / "dist/tidy-domain-worker.cjs"
    if not worker.is_file():
        subprocess.run(
            ["npm", "run", "build"],
            cwd=PROJECT,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )


def test_large_batch_registry_and_all_evidence_close() -> None:
    registry = load_large_batch_registry(PROJECT)
    assert registry.batch_id == "prisoners-australia-sixty-worksheets-v1"
    assert registry.worksheet_count == 60
    assert registry.provider_calls == 0
    assert len(registry.entries) == 12
    normalization = verify_batch_normalization(PROJECT, registry)
    assert len(normalization["entries"]) == 4
    assert normalization["inRangeValuesChanged"] is False
    manifests = [
        verify_large_batch_evidence(PROJECT, spec) for spec in registry.entries
    ]
    assert sum(item["acceptedWorkbookCount"] for item in manifests) == 60
    assert sum(item["exceptionWorkbookCount"] for item in manifests) == 0
    assert sum(item["canonicalObservationCount"] for item in manifests) == 19648
    assert sum(item["providerCalls"] for item in manifests) == 0
    assert {
        item["manualReplayYears"][0] for item in manifests if item["manualReplayYears"]
    } == {
        2023,
        2024,
    }


def test_large_batch_cohorts_and_contracts_validate() -> None:
    registry = load_large_batch_registry(PROJECT)
    cohort_schema = json.loads(
        (PROJECT / "contracts/product-prototype/v1/cohort.schema.json").read_text()
    )
    validator = jsonschema.Draft202012Validator(
        cohort_schema,
        format_checker=jsonschema.FormatChecker(),
    )
    for spec in registry.entries:
        cohort_path = PROJECT / spec.cohort_path
        cohort = json.loads(cohort_path.read_text())
        contract = json.loads(
            (cohort_path.parent / cohort["acceptanceContract"]).read_text()
        )
        validator.validate(cohort)
        _validate_cohort(cohort)
        _validate_contract(contract, cohort)
        assert [item["year"] for item in cohort["workbooks"]] == list(
            spec.expected_years
        )
        assert [item["sheet"] for item in cohort["workbooks"]]
        assert all(
            item["replayResponse"]["acceptanceAuthority"] is False
            for item in cohort["workbooks"]
        )


def test_registry_rejects_output_path_escape(tmp_path: Path) -> None:
    registry_path = tmp_path / "fixtures/product-prototype/large-batch-assets-v1.json"
    registry_path.parent.mkdir(parents=True)
    value = json.loads(
        (PROJECT / "fixtures/product-prototype/large-batch-assets-v1.json").read_text()
    )
    value["entries"][0]["outputDirectory"] = "../escape"
    registry_path.write_text(json.dumps(value))
    with pytest.raises(LargeBatchError, match="entry is invalid"):
        load_large_batch_registry(tmp_path)


def test_multi_condition_measure_selection_rejects_overlap() -> None:
    cohort_path = (
        PROJECT
        / "fixtures/product-prototype/prisoners-selected-characteristics-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "acceptance"
            / "prisoners-selected-characteristics-v1.json"
        ).read_text()
    )
    _validate_contract(contract, cohort)
    contract["measures"][2]["selection"]["conditions"] = {
        "statistic_basis": ["NUMBER"],
        "characteristic_group": ["SEX"],
    }
    with pytest.raises(ProductPrototypeError, match="selection overlaps"):
        _validate_contract(contract, cohort)


def test_empty_total_equations_require_explicit_not_applicable_policy() -> None:
    cohort_path = (
        PROJECT
        / "fixtures/product-prototype/prisoners-selected-characteristics-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "acceptance"
            / "prisoners-selected-characteristics-v1.json"
        ).read_text()
    )
    _validate_contract(contract, cohort)
    contract.pop("totalValidation")
    with pytest.raises(ProductPrototypeError, match="total equations"):
        _validate_contract(contract, cohort)


def test_reviewed_combination_digest_rejects_marginal_preserving_swap() -> None:
    cohort_path = (
        PROJECT / "fixtures/product-prototype/prisoners-table-34-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-34-v1.json"
        ).read_text()
    )
    rows = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "table-34-five-year-evidence"
            / "canonical-observations.json"
        ).read_text()
    )
    digest_2025 = next(
        item["contentDigest"] for item in cohort["workbooks"] if item["year"] == 2025
    )
    year_rows = [
        dict(row) for row in rows if row["source_workbook_digest"] == digest_2025
    ]
    assert _validate_expected_coverage(year_rows, contract, {"year": 2025}) == []
    candidates = [row for row in year_rows if row["measure_id"] == "prisoner-count"]
    left = candidates[0]
    right = next(
        row
        for row in candidates[1:]
        if row["jurisdiction_id"] != left["jurisdiction_id"]
        and row["prison_location_id"] != left["prison_location_id"]
    )
    left["prison_location_id"], right["prison_location_id"] = (
        right["prison_location_id"],
        left["prison_location_id"],
    )
    issues = _validate_expected_coverage(year_rows, contract, {"year": 2025})
    assert {item["code"] for item in issues} == {"EXPECTED_COMBINATION_SET_MISMATCH"}


def test_vintage_contract_requires_date_codes_and_two_time_axes() -> None:
    cohort_path = (
        PROJECT / "fixtures/product-prototype/prisoners-table-27-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-27-v1.json"
        ).read_text()
    )
    _validate_contract(contract, cohort)
    assert contract["referenceDateDimension"] == "observation_period"
    assert contract["preservePublicationVintage"] is True
    assert contract["uniqueKey"][:2] == [
        "publication_vintage_date",
        "reference_date",
    ]
    rows = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "table-27-five-year-evidence"
            / "canonical-observations.json"
        ).read_text()
    )
    assert all(row["reference_date"] == row["observation_period_id"] for row in rows)
    assert any(row["publication_vintage_date"] != row["reference_date"] for row in rows)
    invalid = json.loads(json.dumps(contract))
    invalid["aliases"]["observation_period"]["2011"] = "YEAR_2011"
    with pytest.raises(ProductPrototypeError, match="Reference-date dimension"):
        _validate_contract(invalid, cohort)


@pytest.mark.timeout(300)
def test_all_large_batch_cohorts_replay_cleanly(tmp_path: Path) -> None:
    report = run_batch(PROJECT, tmp_path / "batch", concurrency=3)
    assert report["passed"] is True
    assert report["providerCalls"] == 0
    assert report["acceptedWorksheetCount"] == 60
    assert report["exceptionWorksheetCount"] == 0
    assert report["canonicalObservationCount"] == 19648
    assert {item["familyId"] for item in report["cohorts"]} == {
        item.family_id for item in load_large_batch_registry(PROJECT).entries
    }
    assert all(
        item["passed"] is True
        and item["acceptedWorkbookCount"] == 5
        and item["exceptionWorkbookCount"] == 0
        and item["providerCalls"] == 0
        and item["crossYearIssues"] == []
        for item in report["cohorts"]
    )


def test_workbook_format_trim_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "normalized.xlsx"
    completed = subprocess.run(
        [
            str(PROJECT / "scripts/trim-prototype-workbook-formatting.py"),
            str(
                PROJECT
                / "fixtures/product-prototype/workbooks/prisoners-australia-2021.xlsx"
            ),
            str(output),
            "--sheet",
            "Table_34=A1:B190",
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert (
        output.read_bytes()
        == (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "workbooks"
            / "prisoners-australia-2021-batch-normalized.xlsx"
        ).read_bytes()
    )


def test_large_batch_cli_verifies_committed_evidence() -> None:
    completed = subprocess.run(
        [str(PROJECT / "scripts/tidy-prototype-batch"), "verify"],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report == {
        "batchId": "prisoners-australia-sixty-worksheets-v1",
        "worksheetCount": 60,
        "cohortCount": 12,
        "canonicalObservationCount": 19648,
        "providerCalls": 0,
        "verified": True,
    }
