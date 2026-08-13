from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tidy_orchestrator.artifacts import LocalArtifactRepository, sha256_digest
from tidy_orchestrator.product_prototype import (
    ProductPrototypeError,
    _cross_year_issues,
    evaluate_execution_for_acceptance,
    run_product_prototype,
    verify_live_evidence,
)
from tidy_orchestrator.worker import GatewayConfig, WorkerGateway

PROJECT = Path(__file__).parents[1]
COHORT = (
    PROJECT / "fixtures" / "product-prototype" / "prisoners-table-30-2023-2025.json"
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
    assert json.loads((tmp_path / "output" / "exceptions.json").read_text()) == []
    decisions = repository.list_decisions()
    assert len(decisions) == 3
    assert {item.decision_type for item in decisions} == {"prototype_auto_accepted"}


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
