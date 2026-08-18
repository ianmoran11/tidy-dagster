from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest

from tidy_orchestrator.artifacts import LocalArtifactRepository, sha256_digest
from tidy_orchestrator.ml_contract import canonical_digest_v1
from tidy_orchestrator.ml_gateway import (
    COHORT_DIGEST,
    DIRECTION_DIGEST,
    MANIFEST_SHA256,
    PACKAGE_ID,
    ROLE_DIGEST,
    MlIntegrityError,
    MlUnavailable,
)
from tidy_orchestrator.product_prototype import (
    ProductPrototypeError,
    _cross_year_issues,
    _prepare_fresh_live_with_ml,
    _validate_cohort,
    _validate_contract,
    _validate_warning_rules,
    evaluate_execution_for_acceptance,
    run_product_prototype,
    verify_live_evidence,
)
from tidy_orchestrator.worker import (
    GatewayConfig,
    GatewayInput,
    WorkerDomainFailure,
    WorkerGateway,
)

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
OFFENCE_COHORT = (
    PROJECT / "fixtures" / "product-prototype" / "prisoners-table-23-2021-2025.json"
)
CHARGE_COHORT = (
    PROJECT / "fixtures" / "product-prototype" / "prisoners-table-31-2021-2025.json"
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


class BombMl:
    def infer(self, _features: bytes) -> dict[str, Any]:
        raise AssertionError("ML must not be called")


class SuccessfulMl:
    def __init__(self) -> None:
        self.calls = 0

    def infer(self, feature_bytes: bytes) -> dict[str, Any]:
        self.calls += 1
        features = json.loads(feature_bytes)
        semantic = {
            "schemaVersion": "tidy.ml-hints/v1",
            "workbookDigest": features["workbookDigest"],
            "sheet": features["sheet"],
            "featureBatchDigest": features["featureBatchDigest"],
            "packageId": PACKAGE_ID,
            "packageManifestDigest": "sha256:" + MANIFEST_SHA256,
            "sourceCohortSha256": COHORT_DIGEST,
            "models": {
                "cellRole": ROLE_DIGEST,
                "headerDirection": DIRECTION_DIGEST,
            },
            "predictions": [
                {
                    "address": cell["address"],
                    "role": "unused",
                    "direction": "N",
                    "roleConfidence": 0.75,
                    "directionConfidence": 0.75,
                }
                for cell in features["cells"]
            ],
        }
        return {**semantic, "hintDigest": canonical_digest_v1(semantic)}


class UnavailableMl:
    def infer(self, _features: bytes) -> dict[str, Any]:
        raise MlUnavailable("ML_TIMEOUT", "availability", "test timeout")


class IntegrityMl:
    def infer(self, _features: bytes) -> dict[str, Any]:
        raise MlIntegrityError("ML_PACKAGE_INTEGRITY", "integrity", "test drift")


class FixtureProvider:
    def __init__(self, restricted_root: Path) -> None:
        self.restricted_root = restricted_root
        self.prompts: list[str] = []
        cohort = json.loads(COHORT.read_text())
        base = COHORT.parent
        self.responses = {
            str(entry["year"]): (base / entry["replayResponse"]["path"]).read_text()
            for entry in cohort["workbooks"]
        }

    def dispatch(
        self, *, prompt: str, work_unit_id: str, ordinal: int, correction: bool = False
    ) -> SimpleNamespace:
        del ordinal, correction
        self.prompts.append(prompt)
        content = self.responses[work_unit_id]
        return SimpleNamespace(
            content=content,
            attempt_id=sha256_digest(f"attempt:{work_unit_id}".encode()),
            api_equivalent_usd=0.01,
            response_digest=sha256_digest(content.encode()),
            usage={"apiEquivalentUsd": 0.01},
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


def test_replay_runs_when_unix_resource_module_is_unavailable(tmp_path: Path) -> None:
    script = f"""
import builtins
from pathlib import Path
real_import = builtins.__import__
def import_without_resource(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'resource':
        raise ModuleNotFoundError("No module named 'resource'", name='resource')
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = import_without_resource
from tidy_orchestrator.artifacts import LocalArtifactRepository
from tidy_orchestrator.product_prototype import run_product_prototype
from tidy_orchestrator.worker import GatewayConfig, WorkerGateway
project = Path({str(PROJECT)!r})
repository = LocalArtifactRepository(Path({str(tmp_path / "portable-repository")!r}))
node = {str(Path(shutil.which("node") or "").resolve())!r}
gateway = WorkerGateway(repository, GatewayConfig(
    command=(node, str(project / 'dist/tidy-domain-worker.cjs')),
    cwd=project,
    sandbox_mode='insecure-test-only',
))
result = run_product_prototype(
    repository=repository,
    project_root=project,
    cohort_path=Path({str(COHORT)!r}),
    output_root=Path({str(tmp_path / "portable-output")!r}),
    mode='replay',
    gateway=gateway,
    recorded_at='2026-08-13T21:30:00+00:00',
)
assert result.report['providerCalls'] == 0
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


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
        ml_gateway=BombMl(),
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


def test_stored_checked_live_responses_never_invoke_ml(tmp_path: Path) -> None:
    cohort = json.loads(COHORT.read_text())
    response_root = tmp_path / "stored"
    attempts: dict[str, dict[str, Any]] = {}
    for entry in cohort["workbooks"]:
        year = str(entry["year"])
        data = (COHORT.parent / entry["replayResponse"]["path"]).read_bytes()
        target = response_root / year / "response.txt"
        target.parent.mkdir(parents=True)
        target.write_bytes(data)
        attempts[year] = {
            "attemptId": sha256_digest(f"stored:{year}".encode()),
            "providerCallCount": 1,
            "apiEquivalentUsd": 0.01,
            "responseDigest": sha256_digest(data),
            "correctionAttempted": False,
            "correctionSuccessful": False,
            "model": "openai-codex/gpt-5.6-luna",
            "reasoning": "high",
        }
    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=COHORT,
        output_root=tmp_path / "output",
        mode="live",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-13T21:30:00+00:00",
        live_response_root=response_root,
        live_attempts=attempts,
        ml_gateway=BombMl(),
    )
    assert result.report["providerCalls"] == 3
    assert result.report["acceptedWorkbookCount"] == 3


def test_fresh_live_hints_fallback_integrity_and_downstream_identity(
    tmp_path: Path,
) -> None:
    def run(name: str, ml: Any, provider: FixtureProvider):
        repository = LocalArtifactRepository(tmp_path / name / "repository")
        result = run_product_prototype(
            repository=repository,
            project_root=PROJECT,
            cohort_path=COHORT,
            output_root=tmp_path / name / "output",
            mode="live",
            gateway=fake_gateway(repository),
            recorded_at="2026-08-13T21:30:00+00:00",
            provider=provider,
            ml_gateway=ml,
        )
        return result, repository

    success_ml = SuccessfulMl()
    success_provider = FixtureProvider(tmp_path / "success" / "restricted")
    success, _ = run("success", success_ml, success_provider)
    fallback_provider = FixtureProvider(tmp_path / "fallback" / "restricted")
    fallback, fallback_repository = run("fallback", UnavailableMl(), fallback_provider)

    assert success_ml.calls == 3
    assert len(success_provider.prompts) == len(fallback_provider.prompts) == 3
    assert all(
        "BEGIN_LOCAL_ML_HINT_EXTENSION" in prompt for prompt in success_provider.prompts
    )
    assert all(
        "BEGIN_LOCAL_ML_HINT_EXTENSION" not in prompt
        for prompt in fallback_provider.prompts
    )
    assert success.report["providerCalls"] == fallback.report["providerCalls"] == 3
    assert [
        item["ml"]["status"] for item in success.report["liveAttempts"].values()
    ] == ["hinted"] * 3
    assert [
        item["ml"]["status"] for item in fallback.report["liveAttempts"].values()
    ] == ["availability-fallback"] * 3

    # The fallback prompt is exactly the ordinary one-input worker prompt.
    baseline_prompts = []
    cohort = json.loads(COHORT.read_text())
    for entry in cohort["workbooks"]:
        workbook_bytes = (COHORT.parent / entry["path"]).read_bytes()
        descriptor = fallback_repository.get_content(sha256_digest(workbook_bytes))
        execution = fake_gateway(fallback_repository).execute(
            operation="prepare-semantic-map-v13",
            inputs=(
                GatewayInput("workbook", descriptor.content_digest, "workbook.xlsx"),
            ),
            parameters={"sheet": entry["sheet"]},
        )
        digest = execution.outputs[
            execution.output_paths.index("prompt.txt")
        ].content_digest
        baseline_prompts.append(
            fallback_repository.read_bytes_verified(digest).decode()
        )
    assert fallback_provider.prompts == baseline_prompts

    for hinted, unhinted in zip(
        success.report["workbooks"], fallback.report["workbooks"], strict=True
    ):
        assert hinted["interpretDerivationId"] == unhinted["interpretDerivationId"]
        assert hinted["decisionId"] == unhinted["decisionId"]
        assert hinted["checks"] == unhinted["checks"]
        assert hinted["observationCount"] == unhinted["observationCount"]

    integrity_provider = FixtureProvider(tmp_path / "integrity" / "restricted")
    with pytest.raises(MlIntegrityError, match="test drift"):
        run("integrity", IntegrityMl(), integrity_provider)
    assert integrity_provider.prompts == []


def test_ml_cell_limit_falls_back_before_provider_dispatch(tmp_path: Path) -> None:
    baseline = object()

    class LimitGateway:
        def __init__(self) -> None:
            self.operations: list[str] = []

        def execute(self, *, operation: str, **_kwargs: Any) -> Any:
            self.operations.append(operation)
            if operation == "extract-ml-features-v1":
                raise WorkerDomainFailure(
                    {
                        "code": "ML_CELL_LIMIT_EXCEEDED",
                        "stage": "limit",
                        "message": "reviewed ML boundary",
                    }
                )
            assert operation == "prepare-semantic-map-v13"
            return baseline

    gateway = LimitGateway()
    prepared, record = _prepare_fresh_live_with_ml(
        repository=LocalArtifactRepository(tmp_path / "repository"),
        gateway=gateway,  # type: ignore[arg-type]
        ml_gateway=BombMl(),  # type: ignore[arg-type]
        workbook=SimpleNamespace(content_digest="sha256:" + "1" * 64),
        sheet="Data",
        worker_limits={},
    )
    assert prepared is baseline
    assert record["status"] == "availability-fallback"
    assert record["code"] == "ML_CELL_LIMIT_EXCEEDED"
    assert gateway.operations == [
        "extract-ml-features-v1",
        "prepare-semantic-map-v13",
    ]


def test_ml_fields_cannot_satisfy_or_suppress_acceptance_checks() -> None:
    execution, recipe, entry = valid_execution()
    invalid = {**execution, "tables": [], "mlHintsAccepted": True, "mlConfidence": 1}
    rows, issues, checks = evaluate_execution_for_acceptance(
        execution=invalid,
        recipe={**recipe, "mlHintsAccepted": True},
        contract=CONTRACT,
        entry=entry,
        recipe_digest="sha256:" + "1" * 64,
    )
    assert rows == ()
    assert issues
    assert checks["interpretation"] is True


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


@pytest.mark.parametrize(
    ("cohort_path", "table", "dimension", "other_dimension", "year_counts"),
    [
        (
            OFFENCE_COHORT,
            23,
            "most_serious_offence",
            "most_serious_charge",
            [486, 531, 513, 513, 513],
        ),
        (
            CHARGE_COHORT,
            31,
            "most_serious_charge",
            "most_serious_offence",
            [450, 522, 522, 522, 522],
        ),
    ],
)
def test_replay_tidies_separate_offence_and_charge_cohorts(
    tmp_path: Path,
    cohort_path: Path,
    table: int,
    dimension: str,
    other_dimension: str,
    year_counts: list[int],
) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    output = tmp_path / "output"
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=cohort_path,
        output_root=output,
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-15T06:00:00+00:00",
    )
    report = result.report
    expected_total = sum(year_counts)
    assert report["providerCalls"] == 0
    assert report["acceptedWorkbookCount"] == 5
    assert report["exceptionWorkbookCount"] == 0
    assert report["canonicalObservationCount"] == expected_total
    assert report["crossYearIssues"] == []
    assert [item["rawObservationCount"] for item in report["workbooks"]] == (
        year_counts
    )
    assert [item["observationCount"] for item in report["workbooks"]] == year_counts
    assert all(item["excludedObservationCount"] == 0 for item in report["workbooks"])
    assert all(all(item["checks"].values()) for item in report["workbooks"])

    rows = json.loads((output / "canonical-observations.json").read_text())
    dimension_field = f"{dimension}_id"
    raw_dimension_field = f"raw_{dimension}"
    assert len(rows) == expected_total
    assert all(
        dimension_field in row
        and raw_dimension_field in row
        and f"{other_dimension}_id" not in row
        for row in rows
    )
    assert {row["measure_id"] for row in rows} == {"prisoner-count"}
    assert {row["unit_id"] for row in rows} == {"person"}
    assert {row["value_status"] for row in rows} == {"observed"}
    assert {row["generation_model"] for row in rows} == {"openai-codex/gpt-5.6-sol"}
    assert all(
        row[dimension_field] == "TOTAL"
        for row in rows
        if "Total" in row[raw_dimension_field]
    )
    assert sum(row[dimension_field] == "TOTAL" for row in rows) == 45
    assert all(
        row[dimension_field] == "TOTAL" or row[dimension_field].startswith("ANZSOC_")
        for row in rows
    )
    expected_category_counts = (
        [54, 59, 57, 57, 57] if table == 23 else [50, 58, 58, 58, 58]
    )
    assert [
        len(
            {
                row[dimension_field]
                for row in rows
                if row["reference_date"].startswith(str(year))
            }
        )
        for year in range(2021, 2026)
    ] == expected_category_counts
    collation = json.loads((output / "collation-report.json").read_text())
    assert collation["rowCount"] == expected_total
    assert collation["excludedExceptions"] == []
    assert collation["duplicateCanonicalKeys"] == []
    assert collation["conflictingValues"] == []
    assert collation["unmappedLabels"] == []
    assert collation["missingExpectedCategories"] == []


def test_table_23_unknown_offence_is_routed_to_exception(tmp_path: Path) -> None:
    def mutate_execution(
        year: int,
        execution: dict[str, Any],
        recipe: dict[str, Any],
        deterministic: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        if year == 2025:
            row = execution["tables"][0]["rows"][0]
            category = next(
                key
                for key in row
                if "offence category" in key.lower() and not key.endswith("_source")
            )
            row[category] = "99 Invented offence"
        return execution, recipe, deterministic

    repository = LocalArtifactRepository(tmp_path / "repository")
    result = run_product_prototype(
        repository=repository,
        project_root=PROJECT,
        cohort_path=OFFENCE_COHORT,
        output_root=tmp_path / "output",
        mode="replay",
        gateway=fake_gateway(repository),
        recorded_at="2026-08-15T06:00:00+00:00",
        acceptance_execution_mutator=mutate_execution,
    )
    assert result.report["acceptedWorkbookCount"] == 4
    assert result.report["exceptionWorkbookCount"] == 1
    failed = result.report["workbooks"][-1]
    assert failed["decision"] == "exception_required"
    assert "UNKNOWN_CODE" in {item["code"] for item in failed["issues"]}


def test_offence_and_charge_contracts_keep_source_concepts_separate() -> None:
    offence_cohort = json.loads(OFFENCE_COHORT.read_text())
    charge_cohort = json.loads(CHARGE_COHORT.read_text())
    offence_contract = json.loads(
        (
            PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-23-v1.json"
        ).read_text()
    )
    charge_contract = json.loads(
        (
            PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-31-v1.json"
        ).read_text()
    )
    _validate_contract(offence_contract, offence_cohort)
    _validate_contract(charge_contract, charge_cohort)
    assert offence_contract["requiredDimensions"] == [
        "jurisdiction",
        "most_serious_offence",
    ]
    assert charge_contract["requiredDimensions"] == [
        "jurisdiction",
        "most_serious_charge",
    ]
    assert offence_contract["uniqueKey"] != charge_contract["uniqueKey"]


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


@pytest.mark.parametrize(
    ("table", "cohort_path", "expected_count", "expected_run_digest"),
    [
        (
            23,
            OFFENCE_COHORT,
            2556,
            "sha256:000e694bffb36909951b6f3c54266d768cb45a2300d8829c9853a58f509edfd0",
        ),
        (
            31,
            CHARGE_COHORT,
            2538,
            "sha256:86c0d0a8254394e51677f63a110641aaebd78caab098fa0c2ee5e3d32e46ce5f",
        ),
    ],
)
def test_offence_pair_evidence_manifests_bind_committed_outputs(
    table: int,
    cohort_path: Path,
    expected_count: int,
    expected_run_digest: str,
) -> None:
    cohort = json.loads(cohort_path.read_text())
    cohort_schema = json.loads(
        (PROJECT / "contracts/product-prototype/v1/cohort.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(
        cohort_schema,
        format_checker=jsonschema.FormatChecker(),
    ).validate(cohort)
    root = PROJECT / f"fixtures/product-prototype/table-{table}-five-year-evidence"
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["cohortDigest"] == sha256_digest(cohort_path.read_bytes())
    assert manifest["canonicalObservationCount"] == expected_count
    assert manifest["classificationMigrationCautionRecorded"] is True
    declared_paths = {item["path"] for item in manifest["files"]}
    assert "README.md" in declared_paths
    readme_text = " ".join((root / "README.md").read_text().split())
    assert (
        "migration to ANZSOC 2023 may have changed the coding of earlier ANZSOC 2011"
        in readme_text
    )
    for item in manifest["files"]:
        content = (root / item["path"]).read_bytes()
        assert len(content) == item["byteLength"]
        assert sha256_digest(content) == item["contentDigest"]
    run = json.loads((root / "run.json").read_text())
    contract = cohort_path.parent / cohort["acceptanceContract"]
    assert run["runDigest"] == manifest["runDigest"] == expected_run_digest
    assert run["acceptanceContractDigest"] == sha256_digest(contract.read_bytes())
    assert run["acceptedWorkbookCount"] == 5
    assert run["exceptionWorkbookCount"] == 0
    assert run["canonicalObservationCount"] == expected_count
    assert run["crossYearIssues"] == []
    assert json.loads((root / "exceptions.json").read_text()) == []


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
    age_cohort["workerLimits"]["maxWarnings"] = 100_001
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


def test_ambiguous_warning_can_pin_the_exact_selected_header_source() -> None:
    warning = {
        "code": "AMBIGUOUS_HEADER",
        "address": "R8C2",
        "message": "Multiple candidates.",
    }
    rows = [
        {
            "_source": {"address": "R8C2"},
            "court level": "All Courts",
            "court level_source": "R6C2",
        }
    ]
    rule = {
        "code": "AMBIGUOUS_HEADER",
        "dimension": "court_level",
        "requireCanonicalOutputEquivalence": True,
        "expectedHeaderSourcesByYear": {"2024": {"ALL_COURTS": ["R6C2"]}},
    }
    contract = {"aliases": {"court_level": {"All Courts": "ALL_COURTS"}}}
    assert (
        _validate_warning_rules(
            [warning],
            [rule],
            rows,
            {"court_level": "court level"},
            contract,
            year=2024,
        )
        == []
    )

    rule["expectedHeaderSourcesByYear"]["2024"]["ALL_COURTS"] = ["R7C2"]
    issues = _validate_warning_rules(
        [warning],
        [rule],
        rows,
        {"court_level": "court level"},
        contract,
        year=2024,
    )
    assert {issue["code"] for issue in issues} == {
        "AMBIGUOUS_WARNING_HEADER_SOURCE_MISMATCH"
    }


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
