from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tidy_orchestrator.artifacts import LocalArtifactRepository, sha256_digest
from tidy_orchestrator.product_prototype import (
    ProductPrototypeError,
    _cross_year_issues,
    _validate_cohort,
    _validate_contract,
    evaluate_execution_for_acceptance,
    run_product_prototype,
    verify_live_evidence,
)
from tidy_orchestrator.worker import GatewayConfig, WorkerGateway

PROJECT = Path(__file__).parents[1]
COHORT = (
    PROJECT / "fixtures" / "product-prototype" / "prisoners-table-30-2023-2025.json"
)
EXPANDED_COHORT = (
    PROJECT / "fixtures" / "product-prototype" / "prisoners-table-30-2021-2025.json"
)
AGE_COHORT = (
    PROJECT / "fixtures" / "product-prototype" / "prisoners-table-21-2021-2025.json"
)
COUNTRY_COHORT = (
    PROJECT / "fixtures" / "product-prototype" / "prisoners-table-22-2021-2025.json"
)
CONTRACT = json.loads(
    (
        PROJECT
        / "fixtures"
        / "product-prototype"
        / "acceptance"
        / "prisoners-table-30-v1.json"
    ).read_text()
)


def fake_gateway(repository: LocalArtifactRepository) -> WorkerGateway:
    return WorkerGateway(
        repository,
        GatewayConfig(
            command=(
                str(Path(shutil.which("node") or "").resolve()),
                str(PROJECT / "dist" / "tidy-domain-worker.cjs"),
            ),
            cwd=PROJECT,
            sandbox_mode="insecure-test-only",
        ),
    )


def test_checked_live_evidence_binds_three_fresh_luna_results(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "live-verification")
    manifest = verify_live_evidence(
        PROJECT,
        gateway=fake_gateway(repository),
        repository=repository,
    )
    assert manifest["model"] == "openai-codex/gpt-5.6-luna"
    assert manifest["providerCalls"] == 3
    assert manifest["apiEquivalentUsd"] < manifest.get("maximumCostUsd", 2.0)
    assert manifest["acceptedWorkbookCount"] == 3
    assert manifest["canonicalObservationCount"] == 729
    assert manifest["rawPromptResponseIncluded"] is False
    campaign = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "live-evidence"
            / "campaign-evidence.json"
        ).read_text()
    )
    assert campaign["authorizedCohortDigest"] == (
        "sha256:77c770fca86b691e2c94e658ec0f4c0027a5494628805a2d9da201cf47f32f63"
    )
    assert campaign["currentCohortDigest"] == manifest["cohortDigest"]
    authorized_cohort = (
        PROJECT
        / "fixtures"
        / "product-prototype"
        / "live-evidence"
        / campaign["authorizedCohortPath"]
    )
    assert (
        sha256_digest(authorized_cohort.read_bytes())
        == campaign["authorizedCohortDigest"]
    )
    assert {item["ledgerState"] for item in campaign["attempts"].values()} == {
        "settled"
    }
    assert all(
        item["prompt_package_digest"]
        == campaign["attempts"][item["reference_date"][:4]]["promptDigest"]
        for item in json.loads(
            (
                PROJECT
                / "fixtures"
                / "product-prototype"
                / "live-evidence"
                / "canonical-observations.json"
            ).read_text()
        )
    )


def test_replay_runs_three_real_workbooks_and_collates(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=COHORT,
        output_root=tmp_path / "output",
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-13T21:30:00+00:00",
    )
    report = result.report
    assert report["providerCalls"] == 0
    assert report["freshLunaGeneration"] is False
    assert report["historicalReplayIsAcceptanceAuthority"] is False
    assert report["acceptedWorkbookCount"] == 3
    assert report["exceptionWorkbookCount"] == 0
    assert report["canonicalObservationCount"] == 729
    assert report["crossYearIssues"] == []
    assert [item["decision"] for item in report["workbooks"]] == [
        "prototype_auto_accepted"
    ] * 3
    assert all(item["observationCount"] == 243 for item in report["workbooks"])
    assert (tmp_path / "output" / "canonical-observations.csv").is_file()
    assert (tmp_path / "output" / "canonical-observations.json").is_file()
    rows = json.loads((tmp_path / "output" / "canonical-observations.json").read_text())
    required_provenance = {
        "publication_id",
        "execution_digest",
        "acceptance_policy_version",
        "acceptance_policy_digest",
        "acceptance_decision_digest",
        "prompt_package_digest",
        "generation_model",
        "generation_attempt_id",
    }
    assert required_provenance <= set(rows[0])
    assert {row["generation_model"] for row in rows} == {"openai-codex/gpt-5.6-luna"}
    collation = json.loads((tmp_path / "output" / "collation-report.json").read_text())
    assert len(collation["includedWorkbooks"]) == 3
    assert collation["excludedExceptions"] == []
    assert collation["duplicateCanonicalKeys"] == []
    assert collation["conflictingValues"] == []
    assert collation["unmappedLabels"] == []
    assert collation["missingExpectedCategories"] == []
    assert collation["schemaFailures"] == []
    assert collation["codeListFailures"] == []
    assert json.loads((tmp_path / "output" / "exceptions.json").read_text()) == []
    decisions = repository.list_decisions()
    assert len(decisions) == 3
    assert {item.decision_type for item in decisions} == {"prototype_auto_accepted"}


def test_replay_extends_table_30_to_five_years(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=EXPANDED_COHORT,
        output_root=tmp_path / "output",
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-14T03:00:00+00:00",
    )
    report = result.report
    assert report["providerCalls"] == 0
    assert report["acceptedWorkbookCount"] == 5
    assert report["exceptionWorkbookCount"] == 0
    assert report["canonicalObservationCount"] == 1215
    assert report["crossYearIssues"] == []
    assert [item["year"] for item in report["workbooks"]] == list(range(2021, 2026))
    assert all(item["observationCount"] == 243 for item in report["workbooks"])
    rows = json.loads((tmp_path / "output" / "canonical-observations.json").read_text())
    assert {row["reference_date"] for row in rows} == {
        f"{year}-06-30" for year in range(2021, 2026)
    }
    assert {row["generation_model"] for row in rows} == {
        "openai-codex/gpt-5.6-sol",
        "openai-codex/gpt-5.6-luna",
    }
    collation = json.loads((tmp_path / "output" / "collation-report.json").read_text())
    assert len(collation["includedWorkbooks"]) == 5
    assert collation["rowCount"] == 1215
    assert collation["excludedExceptions"] == []


def test_replay_tidies_table_21_age_counts_for_five_years(tmp_path: Path) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=AGE_COHORT,
        output_root=tmp_path / "output",
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-14T06:00:00+00:00",
    )
    report = result.report
    assert report["providerCalls"] == 0
    assert report["acceptedWorkbookCount"] == 5
    assert report["exceptionWorkbookCount"] == 0
    assert report["canonicalObservationCount"] == 5265
    assert report["crossYearIssues"] == []
    assert [item["rawObservationCount"] for item in report["workbooks"]] == [
        1332,
        1350,
        1350,
        1350,
        1350,
    ]
    assert [item["excludedObservationCount"] for item in report["workbooks"]] == [
        279,
        297,
        297,
        297,
        297,
    ]
    assert all(item["observationCount"] == 1053 for item in report["workbooks"])
    assert all(
        item["decision"] == "prototype_auto_accepted" for item in report["workbooks"]
    )
    assert all(all(item["checks"].values()) for item in report["workbooks"])
    rows = json.loads((tmp_path / "output" / "canonical-observations.json").read_text())
    assert len(rows) == 5265
    assert {row["age_group_id"] for row in rows} == {
        "AGE_18_OR_YOUNGER",
        "AGE_19",
        "AGE_20_24",
        "AGE_25_29",
        "AGE_30_34",
        "AGE_35_39",
        "AGE_40_44",
        "AGE_45_49",
        "AGE_50_54",
        "AGE_55_59",
        "AGE_60_64",
        "AGE_65_PLUS",
        "TOTAL",
    }
    assert all("legal_status_id" not in row for row in rows)
    assert {row["generation_model"] for row in rows} == {"openai-codex/gpt-5.6-sol"}
    assert all(
        row["raw_jurisdiction"] not in {"Imprisonment rate", "Imprisonment rate (b)"}
        and row["raw_age_group"] not in {"Mean age (years)", "Median age (years)"}
        for row in rows
    )
    collation = json.loads((tmp_path / "output" / "collation-report.json").read_text())
    assert collation["rowCount"] == 5265
    assert collation["excludedDimensionCodes"] == {
        "jurisdiction": ["IMPRISONMENT_RATE"],
        "age_group": ["MEAN_AGE", "MEDIAN_AGE"],
    }
    assert collation["excludedExceptions"] == []


def test_replay_tidies_table_22_counts_and_rates_for_five_years(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=COUNTRY_COHORT,
        output_root=tmp_path / "output",
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-15T04:00:00+00:00",
    )
    report = result.report
    assert report["providerCalls"] == 0
    assert report["acceptedWorkbookCount"] == 5
    assert report["exceptionWorkbookCount"] == 0
    assert report["canonicalObservationCount"] == 1709
    assert report["crossYearIssues"] == []
    assert [item["rawObservationCount"] for item in report["workbooks"]] == [
        339,
        340,
        350,
        340,
        340,
    ]
    assert all(item["excludedObservationCount"] == 0 for item in report["workbooks"])
    assert all(all(item["checks"].values()) for item in report["workbooks"])
    rows = json.loads((tmp_path / "output" / "canonical-observations.json").read_text())
    assert Counter(row["measure_id"] for row in rows) == {
        "prisoner-count": 1539,
        "imprisonment-rate-country-of-birth": 170,
    }
    assert {(row["measure_id"], row["unit_id"]) for row in rows} == {
        ("prisoner-count", "person"),
        (
            "imprisonment-rate-country-of-birth",
            "persons-per-100000-adult-population-country-of-birth",
        ),
    }
    rate_rows = [
        row for row in rows if row["measure_id"] == "imprisonment-rate-country-of-birth"
    ]
    assert {row["jurisdiction_id"] for row in rate_rows} == {"AUS"}
    not_applicable = [row for row in rate_rows if row["value_status"] != "observed"]
    assert {
        (
            row["reference_date"][:4],
            row["country_of_birth_id"],
            row["value"],
            row["value_status"],
        )
        for row in not_applicable
    } == {
        ("2022", "OTHER", None, "not_applicable"),
        ("2023", "OTHER", None, "not_applicable"),
        ("2024", "OTHER", None, "not_applicable"),
        ("2025", "OTHER", None, "not_applicable"),
    }
    assert not any(
        row["reference_date"].startswith("2021")
        and row["country_of_birth_id"] == "OTHER"
        for row in rate_rows
    )
    assert {row["generation_model"] for row in rows} == {"openai-codex/gpt-5.6-sol"}
    assert all(
        "age_group_id" not in row and "legal_status_id" not in row for row in rows
    )
    collation = json.loads((tmp_path / "output" / "collation-report.json").read_text())
    assert collation["rowCount"] == 1709
    assert collation["excludedExceptions"] == []
    assert collation["duplicateCanonicalKeys"] == []
    assert collation["conflictingValues"] == []


def test_table_22_measure_rules_are_disjoint() -> None:
    cohort = json.loads(COUNTRY_COHORT.read_text())
    contract_path = (
        PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-22-v1.json"
    )
    contract = json.loads(contract_path.read_text())
    _validate_contract(contract, cohort)
    contract["measures"][1]["selection"]["codes"] = ["AUS"]
    with pytest.raises(ProductPrototypeError, match="selection overlaps"):
        _validate_contract(contract, cohort)


def test_cohort_requires_increasing_years_and_matching_call_ceiling() -> None:
    cohort = json.loads(EXPANDED_COHORT.read_text())
    _validate_cohort(cohort)
    duplicate = json.loads(EXPANDED_COHORT.read_text())
    duplicate["workbooks"][1]["year"] = 2021
    with pytest.raises(ProductPrototypeError, match="unique and increasing"):
        _validate_cohort(duplicate)
    wrong_ceiling = json.loads(EXPANDED_COHORT.read_text())
    wrong_ceiling["generation"]["maximumCalls"] = 6
    with pytest.raises(ProductPrototypeError, match="pinned Luna policy"):
        _validate_cohort(wrong_ceiling)
    age_cohort = json.loads(AGE_COHORT.read_text())
    _validate_cohort(age_cohort)
    age_cohort["workerLimits"]["maxWarnings"] = 20_001
    with pytest.raises(ProductPrototypeError, match="outside protocol bounds"):
        _validate_cohort(age_cohort)


def test_five_year_evidence_manifest_binds_committed_outputs() -> None:
    cohort = json.loads(EXPANDED_COHORT.read_text())
    cohort_schema = json.loads(
        (
            PROJECT / "contracts" / "product-prototype" / "v1" / "cohort.schema.json"
        ).read_text()
    )
    jsonschema.Draft202012Validator(
        cohort_schema,
        format_checker=jsonschema.FormatChecker(),
    ).validate(cohort)
    root = PROJECT / "fixtures" / "product-prototype" / "five-year-evidence"
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["cohortDigest"] == sha256_digest(EXPANDED_COHORT.read_bytes())
    for item in manifest["files"]:
        content = (root / item["path"]).read_bytes()
        assert len(content) == item["byteLength"]
        assert sha256_digest(content) == item["contentDigest"]
    run = json.loads((root / "run.json").read_text())
    assert run["runDigest"] == manifest["runDigest"]
    assert run["acceptedWorkbookCount"] == 5
    assert run["exceptionWorkbookCount"] == 0
    assert run["canonicalObservationCount"] == 1215
    assert run["crossYearIssues"] == []
    assert json.loads((root / "exceptions.json").read_text()) == []


def test_table_21_evidence_manifest_binds_committed_outputs() -> None:
    cohort = json.loads(AGE_COHORT.read_text())
    cohort_schema = json.loads(
        (
            PROJECT / "contracts" / "product-prototype" / "v1" / "cohort.schema.json"
        ).read_text()
    )
    jsonschema.Draft202012Validator(
        cohort_schema,
        format_checker=jsonschema.FormatChecker(),
    ).validate(cohort)
    root = PROJECT / "fixtures" / "product-prototype" / "table-21-five-year-evidence"
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["cohortDigest"] == sha256_digest(AGE_COHORT.read_bytes())
    for item in manifest["files"]:
        content = (root / item["path"]).read_bytes()
        assert len(content) == item["byteLength"]
        assert sha256_digest(content) == item["contentDigest"]
    run = json.loads((root / "run.json").read_text())
    assert run["runDigest"] == manifest["runDigest"]
    assert run["acceptedWorkbookCount"] == 5
    assert run["exceptionWorkbookCount"] == 0
    assert run["canonicalObservationCount"] == 5265
    assert run["crossYearIssues"] == []
    assert sum(item["rawObservationCount"] for item in run["workbooks"]) == 6732
    assert sum(item["excludedObservationCount"] for item in run["workbooks"]) == 1467
    assert json.loads((root / "exceptions.json").read_text()) == []


def test_table_22_evidence_manifest_binds_committed_outputs() -> None:
    cohort = json.loads(COUNTRY_COHORT.read_text())
    cohort_schema = json.loads(
        (
            PROJECT / "contracts" / "product-prototype" / "v1" / "cohort.schema.json"
        ).read_text()
    )
    jsonschema.Draft202012Validator(
        cohort_schema,
        format_checker=jsonschema.FormatChecker(),
    ).validate(cohort)
    root = PROJECT / "fixtures/product-prototype/table-22-five-year-evidence"
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["cohortDigest"] == sha256_digest(COUNTRY_COHORT.read_bytes())
    for item in manifest["files"]:
        content = (root / item["path"]).read_bytes()
        assert len(content) == item["byteLength"]
        assert sha256_digest(content) == item["contentDigest"]
    run = json.loads((root / "run.json").read_text())
    contract = (
        PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-22-v1.json"
    )
    assert run["runDigest"] == manifest["runDigest"]
    assert run["acceptanceContractDigest"] == sha256_digest(contract.read_bytes())
    assert run["acceptedWorkbookCount"] == 5
    assert run["exceptionWorkbookCount"] == 0
    assert run["canonicalObservationCount"] == 1709
    assert run["crossYearIssues"] == []
    rows = json.loads((root / "canonical-observations.json").read_text())
    assert sum(row["measure_id"] == "prisoner-count" for row in rows) == 1539
    assert (
        sum(row["measure_id"] == "imprisonment-rate-country-of-birth" for row in rows)
        == 170
    )
    assert sum(row["value_status"] == "not_applicable" for row in rows) == 4
    assert json.loads((root / "exceptions.json").read_text()) == []


def test_replay_is_byte_deterministic(tmp_path: Path) -> None:
    outputs = []
    for name in ("one", "two"):
        repository = LocalArtifactRepository(tmp_path / name / "repository")
        result = run_product_prototype(
            repository=repository,
            project_root=PROJECT,
            cohort_path=COHORT,
            output_root=tmp_path / name / "output",
            mode="replay",
            gateway=fake_gateway(repository),
            recorded_at="2026-08-13T21:30:00+00:00",
        )
        outputs.append(
            (
                result.report["runDigest"],
                (tmp_path / name / "output" / "run.json").read_bytes(),
                (
                    tmp_path / name / "output" / "canonical-observations.csv"
                ).read_bytes(),
            )
        )
    assert outputs[0] == outputs[1]


def test_stored_live_attempt_must_match_response_digest(tmp_path: Path) -> None:
    response_root = tmp_path / "responses"
    for year in (2023, 2024, 2025):
        target = response_root / str(year) / "response.txt"
        target.parent.mkdir(parents=True)
        target.write_text("{}")
    attempts = {
        str(year): {
            "attemptId": "sha256:" + str(year % 10) * 64,
            "providerCallCount": 1,
            "apiEquivalentUsd": 0.01,
            "responseDigest": sha256_digest(b"different"),
            "correctionAttempted": False,
            "correctionSuccessful": False,
            "model": "openai-codex/gpt-5.6-luna",
            "reasoning": "high",
        }
        for year in (2023, 2024, 2025)
    }
    repository = LocalArtifactRepository(tmp_path / "repository")
    with pytest.raises(ProductPrototypeError, match="attempt evidence"):
        run_product_prototype(
            repository=repository,
            project_root=PROJECT,
            cohort_path=COHORT,
            output_root=tmp_path / "output",
            mode="live",
            gateway=fake_gateway(repository),
            recorded_at="2026-08-13T21:30:00+00:00",
            live_response_root=response_root,
            live_attempts=attempts,
        )


def test_live_mode_fails_closed_without_restricted_responses(tmp_path: Path) -> None:
    with pytest.raises(ProductPrototypeError, match="restricted responses"):
        run_product_prototype(
            repository=LocalArtifactRepository(tmp_path / "repository"),
            project_root=PROJECT,
            cohort_path=COHORT,
            output_root=tmp_path / "output",
            mode="live",
            recorded_at="2026-08-13T21:30:00+00:00",
        )


def valid_execution() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    recipe = {
        "version": "0.1",
        "sheet": "Table 30",
        "tables": [
            {
                "name": "counts",
                "values": {"name": "count", "cells": ["R1C1"]},
                "headers": [
                    {"name": "jurisdiction", "direction": "N", "cells": ["R1C1"]},
                    {
                        "name": "Indigenous status",
                        "direction": "W",
                        "cells": ["R1C1"],
                    },
                    {"name": "sex", "direction": "W", "cells": ["R1C1"]},
                    {"name": "legal status", "direction": "W", "cells": ["R1C1"]},
                ],
            }
        ],
    }
    rows = []
    address = 0
    for jurisdiction in CONTRACT["expected"]["jurisdictions"]:
        raw_jurisdiction = next(
            raw
            for raw, canonical in CONTRACT["aliases"]["jurisdiction"].items()
            if canonical == jurisdiction
        )
        for indigenous in CONTRACT["expected"]["indigenousStatuses"]:
            raw_indigenous = next(
                raw
                for raw, canonical in CONTRACT["aliases"]["indigenous_status"].items()
                if canonical == indigenous
            )
            for sex in CONTRACT["expected"]["sexes"]:
                raw_sex = next(
                    raw
                    for raw, canonical in CONTRACT["aliases"]["sex"].items()
                    if canonical == sex
                )
                values = {"SENTENCED": 10, "UNSENTENCED": 5, "TOTAL": 15}
                for legal in CONTRACT["expected"]["legalStatuses"]:
                    address += 1
                    raw_legal = next(
                        raw
                        for raw, canonical in CONTRACT["aliases"][
                            "legal_status"
                        ].items()
                        if canonical == legal
                    )
                    rows.append(
                        {
                            "count": values[legal],
                            "jurisdiction": raw_jurisdiction,
                            "Indigenous status": raw_indigenous,
                            "sex": raw_sex,
                            "legal status": raw_legal,
                            "_source": {
                                "sheet": "Table 30",
                                "address": f"R{address}C1",
                                "row": address,
                                "col": 1,
                            },
                        }
                    )
    # Uniform components make all declared equations true after recalculating totals.
    for row in rows:
        if CONTRACT["aliases"]["sex"][row["sex"]] == "PERSONS":
            row["count"] *= 2
        if (
            CONTRACT["aliases"]["indigenous_status"][row["Indigenous status"]]
            == "TOTAL"
        ):
            row["count"] *= 2
    execution = {"tables": [{"rows": rows}], "warnings": []}
    entry = {
        "year": 2025,
        "referenceDate": "2025-06-30",
        "sheet": "Table 30",
        "contentDigest": "sha256:" + "1" * 64,
    }
    return execution, recipe, entry


def codes_for(
    execution: dict[str, Any], recipe: dict[str, Any], entry: dict[str, Any]
) -> set[str]:
    _rows, issues, _checks = evaluate_execution_for_acceptance(
        execution=execution,
        recipe=recipe,
        contract=CONTRACT,
        entry=entry,
        recipe_digest="sha256:" + "2" * 64,
    )
    return {item["code"] for item in issues}


def test_negative_unknown_code_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    execution["tables"][0]["rows"][0]["legal status"] = "Unknown status"
    assert "UNKNOWN_CODE" in codes_for(execution, recipe, entry)


def test_negative_duplicate_key_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    duplicate = dict(execution["tables"][0]["rows"][0])
    duplicate["_source"] = {
        "sheet": "Table 30",
        "address": "R999C1",
        "row": 999,
        "col": 1,
    }
    execution["tables"][0]["rows"].append(duplicate)
    assert "DUPLICATE_OBSERVATION_KEY" in codes_for(execution, recipe, entry)


def test_negative_missing_dimension_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    recipe["tables"][0]["headers"] = recipe["tables"][0]["headers"][:-1]
    assert "REQUIRED_DIMENSION_MISSING" in codes_for(execution, recipe, entry)


def test_negative_inconsistent_total_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    execution["tables"][0]["rows"][2]["count"] = 9999
    assert "TOTAL_MISMATCH" in codes_for(execution, recipe, entry)


def test_total_component_excess_boundary_is_enforced() -> None:
    execution, recipe, entry = valid_execution()
    execution["tables"][0]["rows"][0]["count"] += 11
    assert "TOTAL_MISMATCH" in codes_for(execution, recipe, entry)


def test_negative_source_cell_reuse_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    execution["tables"][0]["rows"][1]["_source"] = execution["tables"][0]["rows"][0][
        "_source"
    ]
    assert "SOURCE_CELL_REUSE" in codes_for(execution, recipe, entry)


def test_negative_missing_category_coverage_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    execution["tables"][0]["rows"] = [
        row for row in execution["tables"][0]["rows"] if row["jurisdiction"] != "NSW"
    ]
    assert "EXPECTED_CATEGORY_COVERAGE_MISSING" in codes_for(execution, recipe, entry)


def test_negative_empty_output_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    execution["tables"][0]["rows"] = []
    assert "EMPTY_OUTPUT" in codes_for(execution, recipe, entry)


def test_negative_nondeterminism_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    _rows, issues, _checks = evaluate_execution_for_acceptance(
        execution=execution,
        recipe=recipe,
        contract=CONTRACT,
        entry=entry,
        recipe_digest="sha256:" + "2" * 64,
        deterministic=False,
    )
    assert "NONDETERMINISTIC_REPLAY" in {item["code"] for item in issues}


def test_negative_allowed_warning_with_unmapped_output_routes_to_exception() -> None:
    execution, recipe, entry = valid_execution()
    first = execution["tables"][0]["rows"][0]
    first["Indigenous status"] = "Unknown status"
    execution["warnings"] = [
        {
            "code": "AMBIGUOUS_HEADER",
            "address": first["_source"]["address"],
            "message": "Multiple candidates.",
        }
    ]
    found = codes_for(execution, recipe, entry)
    assert "AMBIGUOUS_WARNING_OUTPUT_UNRESOLVED" in found


def test_end_to_end_malformed_response_creates_exception_and_is_excluded(
    tmp_path: Path,
) -> None:
    fixture_root = PROJECT / ".product-prototype" / f"test-{tmp_path.name}"
    shutil.rmtree(fixture_root, ignore_errors=True)
    shutil.copytree(COHORT.parent, fixture_root)
    cohort_path = fixture_root / COHORT.name
    cohort = json.loads(cohort_path.read_text())
    malformed = fixture_root / cohort["workbooks"][0]["replayResponse"]["path"]
    malformed.write_text("not json")
    cohort["workbooks"][0]["replayResponse"]["contentDigest"] = sha256_digest(
        malformed.read_bytes()
    )
    cohort["workbooks"][0]["replayResponse"]["byteLength"] = len(malformed.read_bytes())
    cohort_path.write_text(json.dumps(cohort, indent=2) + "\n")
    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=cohort_path,
        output_root=tmp_path / "output",
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-13T21:30:00+00:00",
    )
    assert result.report["acceptedWorkbookCount"] == 2
    assert result.report["exceptionWorkbookCount"] == 1
    assert result.report["canonicalObservationCount"] == 486
    exceptions = json.loads((tmp_path / "output" / "exceptions.json").read_text())
    assert len(exceptions) == 1
    assert exceptions[0]["year"] == 2023
    assert exceptions[0]["decision"] == "exception_required"


def _mutate_pipeline_result(
    defect: str,
):
    def mutate(
        year: int,
        execution: dict[str, Any],
        recipe: dict[str, Any],
        deterministic: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        if year != 2023:
            return execution, recipe, deterministic
        rows = execution["tables"][0]["rows"]
        if defect == "unknown-code":
            rows[0]["Legal status"] = "Unknown status"
        elif defect == "duplicate-key":
            duplicate = json.loads(json.dumps(rows[0]))
            duplicate["_source"]["address"] = "R999C1"
            rows.append(duplicate)
        elif defect == "missing-dimension":
            recipe["tables"][0]["headers"] = [
                item
                for item in recipe["tables"][0]["headers"]
                if "legal status" not in item["name"].lower()
            ]
        elif defect == "inconsistent-total":
            rows[2][recipe["tables"][0]["values"]["name"]] = 999999
        elif defect == "source-reuse":
            rows[1]["_source"] = json.loads(json.dumps(rows[0]["_source"]))
        elif defect == "ambiguous-mapping":
            indigenous = next(
                item["name"]
                for item in recipe["tables"][0]["headers"]
                if "indigenous" in item["name"].lower()
            )
            rows[0][indigenous] = "Unknown status"
            execution["warnings"] = [
                {
                    "code": "AMBIGUOUS_HEADER",
                    "address": rows[0]["_source"]["address"],
                    "message": "Multiple candidates.",
                }
            ]
        elif defect == "empty-output":
            execution["tables"][0]["rows"] = []
        elif defect == "nondeterministic":
            deterministic = False
        else:
            raise AssertionError(defect)
        return execution, recipe, deterministic

    return mutate


@pytest.mark.parametrize(
    ("defect", "code"),
    [
        ("unknown-code", "UNKNOWN_CODE"),
        ("duplicate-key", "DUPLICATE_OBSERVATION_KEY"),
        ("missing-dimension", "REQUIRED_DIMENSION_MISSING"),
        ("inconsistent-total", "TOTAL_MISMATCH"),
        ("source-reuse", "SOURCE_CELL_REUSE"),
        ("ambiguous-mapping", "AMBIGUOUS_WARNING_OUTPUT_UNRESOLVED"),
        ("empty-output", "EMPTY_OUTPUT"),
        ("nondeterministic", "NONDETERMINISTIC_REPLAY"),
    ],
)
def test_each_acceptance_negative_creates_end_to_end_exception_and_exclusion(
    tmp_path: Path, defect: str, code: str
) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=COHORT,
        output_root=tmp_path / "output",
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-13T21:30:00+00:00",
        acceptance_execution_mutator=_mutate_pipeline_result(defect),
    )
    assert result.report["acceptedWorkbookCount"] == 2
    assert result.report["exceptionWorkbookCount"] == 1
    assert result.report["canonicalObservationCount"] == 486
    exceptions = json.loads((tmp_path / "output" / "exceptions.json").read_text())
    assert exceptions[0]["decision"] == "exception_required"
    assert code in {item["code"] for item in exceptions[0]["issues"]}
    collation = json.loads((tmp_path / "output" / "collation-report.json").read_text())
    assert len(collation["includedWorkbooks"]) == 2
    assert len(collation["excludedExceptions"]) == 1


def test_cross_workbook_conflict_is_reported() -> None:
    first = {
        "reference_date": "2025-06-30",
        "jurisdiction_id": "NSW",
        "indigenous_status_id": "TOTAL",
        "sex_id": "PERSONS",
        "legal_status_id": "TOTAL",
        "measure_id": "prisoner-count",
        "value": 1,
    }
    second = {**first, "value": 2}
    issues = _cross_year_issues([first, second], CONTRACT)
    assert [item["code"] for item in issues] == ["CROSS_WORKBOOK_CONFLICT"]
