"""Replaceable Dagster projection for the provider-free authoritative runtime."""

import json
import os
from collections import Counter
from pathlib import Path

from dagster import (
    AssetCheckExecutionContext,
    AssetCheckResult,
    AssetExecutionContext,
    AssetSelection,
    ConfigurableResource,
    DataVersion,
    DefaultSensorStatus,
    Definitions,
    DynamicPartitionsDefinition,
    MaterializeResult,
    RunRequest,
    SensorEvaluationContext,
    SensorResult,
    SkipReason,
    asset,
    asset_check,
    define_asset_job,
    sensor,
)

from .application import actual_worker_gateway
from .artifacts import LocalArtifactRepository, domain_digest
from .large_batch import (
    REGISTRY_PATH,
    LargeBatchRegistry,
    LargeBatchSpec,
    _run_authority_claims_are_safe,
    load_large_batch_registry,
    verify_large_batch_reproduction,
)
from .product_prototype import run_product_prototype, verify_live_evidence
from .offenders_acceptance import run_offenders_remaining_family
from .work_units import (
    MAX_ACTIVE_WORK_UNITS,
    PROCESSING_PROFILE_DIGEST,
    discover_work_units,
    execute_work_unit,
    get_gate_result,
    get_work_unit,
    publish_catalog,
    publish_inputs_index,
    publish_projection_index,
    work_unit_run_key,
)

WORK_UNIT_PARTITIONS = DynamicPartitionsDefinition(name="provider_free_work_units_v1")
EXPECTED_RECIPE_TAG = "tidy/expected_recipe_revision_digest"
EXPECTED_CATALOG_TAG = "tidy/expected_work_unit_catalog_digest"
_DEFAULT_PROJECT_ROOT = Path(__file__).parents[2].resolve()


class TidyRuntimeResource(ConfigurableResource):
    """Paths/capabilities only; no evidence bytes or business transitions."""

    project_root: str
    repository_root: str

    def repository(self) -> LocalArtifactRepository:
        return LocalArtifactRepository(Path(self.repository_root))

    def project(self) -> Path:
        return Path(self.project_root).resolve()


@asset(
    name="product_prototype_live_evidence",
    description=(
        "Checked safe projection of the three fresh Luna generations and accepted "
        "canonical 2023-2025 dataset; raw restricted provider evidence is omitted."
    ),
    group_name="product_prototype",
    code_version="tidy.product-prototype-live-evidence/v1",
)
def product_prototype_live_evidence(
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    repository = runtime.repository()
    manifest = verify_live_evidence(
        runtime.project(),
        gateway=actual_worker_gateway(repository, runtime.project()),
        repository=repository,
    )
    return MaterializeResult(
        metadata={
            "manifest_digest": manifest["manifestDigest"],
            "run_digest": manifest["runDigest"],
            "provider_calls": manifest["providerCalls"],
            "api_equivalent_usd": manifest["apiEquivalentUsd"],
            "accepted_workbooks": manifest["acceptedWorkbookCount"],
            "canonical_observations": manifest["canonicalObservationCount"],
            "raw_prompt_response_included": False,
        },
        data_version=DataVersion(manifest["manifestDigest"]),
    )


@asset_check(asset=product_prototype_live_evidence, name="fresh_luna_completion")
def product_prototype_live_evidence_check(
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    repository = runtime.repository()
    manifest = verify_live_evidence(
        runtime.project(),
        gateway=actual_worker_gateway(repository, runtime.project()),
        repository=repository,
    )
    return AssetCheckResult(
        passed=(
            manifest["providerCalls"] == 3
            and manifest["acceptedWorkbookCount"] == 3
            and manifest["exceptionWorkbookCount"] == 0
            and manifest["canonicalObservationCount"] == 729
            and manifest["rawPromptResponseIncluded"] is False
        ),
        metadata={
            "manifest_digest": manifest["manifestDigest"],
            "run_digest": manifest["runDigest"],
            "model": manifest["model"],
            "reasoning": manifest["reasoning"],
            "provider_calls": manifest["providerCalls"],
        },
    )


@asset(
    name="product_prototype_stage_projection",
    description=(
        "Per-workbook prepare, generation, interpretation, execution, validation, "
        "decision, exception, and collation state from checked authoritative evidence."
    ),
    group_name="product_prototype",
    code_version="tidy.product-prototype-stage-projection/v1",
)
def product_prototype_stage_projection(
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    root = runtime.project() / "fixtures" / "product-prototype" / "live-evidence"
    run = json.loads((root / "run.json").read_text())
    collation = json.loads((root / "collation-report.json").read_text())
    attempts = json.loads((root / "attempts.json").read_text())
    stages = []
    for workbook in run["workbooks"]:
        year = str(workbook["year"])
        stages.append(
            {
                "year": workbook["year"],
                "prepare": {
                    "status": "complete",
                    "derivationId": workbook["prepareDerivationId"],
                },
                "generation": {
                    "status": "complete",
                    "attemptId": attempts[year]["attemptId"],
                    "model": attempts[year]["model"],
                },
                "interpretation": {
                    "status": "complete",
                    "derivationId": workbook["interpretDerivationId"],
                },
                "execution": {
                    "status": "complete",
                    "observationCount": workbook["observationCount"],
                },
                "validation": {
                    "status": "passed"
                    if all(workbook["checks"].values())
                    else "failed",
                    "checks": workbook["checks"],
                },
                "decision": {
                    "status": workbook["decision"],
                    "decisionId": workbook["decisionId"],
                },
                "exception": {
                    "required": workbook["decision"] == "exception_required",
                    "issues": workbook["issues"],
                },
            }
        )
    projection = {
        "schemaVersion": "tidy.product-prototype-stage-projection/v1",
        "stages": stages,
        "collation": collation,
        "runDigest": run["runDigest"],
    }
    projection_digest = domain_digest(
        "tidy.product-prototype-stage-projection/v1", projection
    )
    return MaterializeResult(
        metadata={
            "projection_digest": projection_digest,
            "run_digest": run["runDigest"],
            "projection": projection,
            "workbook_stages": stages,
            "collation_report": collation,
            "workbook_stage_count": len(stages),
            "exception_count": len(collation["excludedExceptions"]),
            "collated_rows": collation["rowCount"],
            "stage_names": [
                "prepare",
                "generation",
                "interpretation",
                "execution",
                "validation",
                "decision",
                "exception",
                "collation",
            ],
        },
        data_version=DataVersion(projection_digest),
    )


@asset_check(asset=product_prototype_stage_projection, name="all_stages_projected")
def product_prototype_stage_projection_check(
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    root = runtime.project() / "fixtures" / "product-prototype" / "live-evidence"
    run = json.loads((root / "run.json").read_text())
    passed = all(
        item["prepareDerivationId"]
        and item["interpretDerivationId"]
        and all(item["checks"].values())
        and item["decision"] in {"prototype_auto_accepted", "exception_required"}
        for item in run["workbooks"]
    )
    return AssetCheckResult(
        passed=passed,
        metadata={"workbook_stage_count": len(run["workbooks"])},
    )


@asset(
    name="product_prototype_replay",
    description=(
        "Provider-free replay of the five-workbook 2021-2025 Table 30 cohort, "
        "including automatic acceptance, exceptions, and canonical collation."
    ),
    group_name="product_prototype",
    code_version="tidy.product-prototype-run/v2",
)
def product_prototype_replay(
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    output_root = runtime.project() / ".product-prototype" / "dagster-five-year-replay"
    result = run_product_prototype(
        repository=runtime.repository(),
        project_root=runtime.project(),
        cohort_path=(
            runtime.project()
            / "fixtures"
            / "product-prototype"
            / "prisoners-table-30-2021-2025.json"
        ),
        output_root=output_root,
        mode="replay",
    )
    report = result.report
    return MaterializeResult(
        metadata={
            "run_digest": report["runDigest"],
            "mode": report["mode"],
            "provider_calls": report["providerCalls"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "canonical_observations": report["canonicalObservationCount"],
            "workbooks": report["workbooks"],
            "collation_report_path": str(output_root / "collation-report.json"),
            "artifact_uri": f"artifact://{result.run.content_digest}",
        },
        data_version=DataVersion(result.run.content_digest),
    )


@asset_check(asset=product_prototype_replay, name="automatic_acceptance_and_collation")
def product_prototype_replay_check(
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    output_root = runtime.project() / ".product-prototype" / "dagster-five-year-replay"
    try:
        report = json.loads((output_root / "run.json").read_text())
        collation = json.loads((output_root / "collation-report.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        return AssetCheckResult(
            passed=False,
            metadata={"error": f"Expanded replay evidence is unavailable: {error}"},
        )
    clean_collation_fields = (
        "excludedExceptions",
        "duplicateCanonicalKeys",
        "conflictingValues",
        "unmappedLabels",
        "missingExpectedCategories",
        "schemaFailures",
        "codeListFailures",
    )
    passed = (
        report["acceptedWorkbookCount"] == 5
        and report["exceptionWorkbookCount"] == 0
        and report["canonicalObservationCount"] == 1215
        and report["crossYearIssues"] == []
        and report["providerCalls"] == 0
        and [item["year"] for item in report["workbooks"]] == list(range(2021, 2026))
        and all(
            item["decision"] == "prototype_auto_accepted"
            and all(item["checks"].values())
            for item in report["workbooks"]
        )
        and collation["rowCount"] == 1215
        and all(collation[field] == [] for field in clean_collation_fields)
    )
    return AssetCheckResult(
        passed=passed,
        metadata={
            "run_digest": report["runDigest"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "canonical_observations": report["canonicalObservationCount"],
            "provider_calls": report["providerCalls"],
        },
    )


@asset(
    name="product_prototype_age_replay",
    description=(
        "Provider-free replay of the five-workbook 2021-2025 Table 21 cohort, "
        "producing canonical prisoner counts by jurisdiction, Indigenous status, "
        "sex, and age group."
    ),
    group_name="product_prototype",
    code_version="tidy.product-prototype-age-run/v1",
)
def product_prototype_age_replay(
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    output_root = (
        runtime.project() / ".product-prototype" / "dagster-table-21-five-year-replay"
    )
    result = run_product_prototype(
        repository=runtime.repository(),
        project_root=runtime.project(),
        cohort_path=(
            runtime.project()
            / "fixtures"
            / "product-prototype"
            / "prisoners-table-21-2021-2025.json"
        ),
        output_root=output_root,
        mode="replay",
    )
    report = result.report
    return MaterializeResult(
        metadata={
            "run_digest": report["runDigest"],
            "mode": report["mode"],
            "provider_calls": report["providerCalls"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "raw_observations": sum(
                item["rawObservationCount"] for item in report["workbooks"]
            ),
            "excluded_auxiliary_observations": sum(
                item["excludedObservationCount"] for item in report["workbooks"]
            ),
            "canonical_observations": report["canonicalObservationCount"],
            "workbooks": report["workbooks"],
            "collation_report_path": str(output_root / "collation-report.json"),
            "artifact_uri": f"artifact://{result.run.content_digest}",
        },
        data_version=DataVersion(result.run.content_digest),
    )


@asset_check(asset=product_prototype_age_replay, name="age_acceptance_and_collation")
def product_prototype_age_replay_check(
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    output_root = (
        runtime.project() / ".product-prototype" / "dagster-table-21-five-year-replay"
    )
    try:
        report = json.loads((output_root / "run.json").read_text())
        collation = json.loads((output_root / "collation-report.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        return AssetCheckResult(
            passed=False,
            metadata={"error": f"Table 21 replay evidence is unavailable: {error}"},
        )
    clean_collation_fields = (
        "excludedExceptions",
        "duplicateCanonicalKeys",
        "conflictingValues",
        "unmappedLabels",
        "missingExpectedCategories",
        "schemaFailures",
        "codeListFailures",
    )
    passed = (
        report["acceptedWorkbookCount"] == 5
        and report["exceptionWorkbookCount"] == 0
        and report["canonicalObservationCount"] == 5265
        and report["crossYearIssues"] == []
        and report["providerCalls"] == 0
        and [item["year"] for item in report["workbooks"]] == list(range(2021, 2026))
        and sum(item["rawObservationCount"] for item in report["workbooks"]) == 6732
        and sum(item["excludedObservationCount"] for item in report["workbooks"])
        == 1467
        and all(
            item["decision"] == "prototype_auto_accepted"
            and item["observationCount"] == 1053
            and all(item["checks"].values())
            for item in report["workbooks"]
        )
        and collation["rowCount"] == 5265
        and all(collation[field] == [] for field in clean_collation_fields)
    )
    return AssetCheckResult(
        passed=passed,
        metadata={
            "run_digest": report["runDigest"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "canonical_observations": report["canonicalObservationCount"],
            "provider_calls": report["providerCalls"],
        },
    )


@asset(
    name="product_prototype_country_replay",
    description=(
        "Provider-free replay of the five-workbook 2021-2025 Table 22 cohort, "
        "keeping prisoner counts and country-of-birth imprisonment rates as "
        "separate canonical measures."
    ),
    group_name="product_prototype",
    code_version="tidy.product-prototype-country-run/v1",
)
def product_prototype_country_replay(
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    output_root = (
        runtime.project() / ".product-prototype" / "dagster-table-22-five-year-replay"
    )
    result = run_product_prototype(
        repository=runtime.repository(),
        project_root=runtime.project(),
        cohort_path=(
            runtime.project()
            / "fixtures"
            / "product-prototype"
            / "prisoners-table-22-2021-2025.json"
        ),
        output_root=output_root,
        mode="replay",
    )
    report = result.report
    rows = json.loads((output_root / "canonical-observations.json").read_text())
    count_rows = sum(item["measure_id"] == "prisoner-count" for item in rows)
    rate_rows = sum(
        item["measure_id"] == "imprisonment-rate-country-of-birth" for item in rows
    )
    return MaterializeResult(
        metadata={
            "run_digest": report["runDigest"],
            "mode": report["mode"],
            "provider_calls": report["providerCalls"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "raw_observations": sum(
                item["rawObservationCount"] for item in report["workbooks"]
            ),
            "canonical_observations": report["canonicalObservationCount"],
            "prisoner_count_observations": count_rows,
            "imprisonment_rate_observations": rate_rows,
            "workbooks": report["workbooks"],
            "collation_report_path": str(output_root / "collation-report.json"),
            "artifact_uri": f"artifact://{result.run.content_digest}",
        },
        data_version=DataVersion(result.run.content_digest),
    )


@asset_check(
    asset=product_prototype_country_replay,
    name="country_measure_acceptance_and_collation",
)
def product_prototype_country_replay_check(
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    output_root = (
        runtime.project() / ".product-prototype" / "dagster-table-22-five-year-replay"
    )
    try:
        report = json.loads((output_root / "run.json").read_text())
        collation = json.loads((output_root / "collation-report.json").read_text())
        rows = json.loads((output_root / "canonical-observations.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        return AssetCheckResult(
            passed=False,
            metadata={"error": f"Table 22 replay evidence is unavailable: {error}"},
        )
    clean_collation_fields = (
        "excludedExceptions",
        "duplicateCanonicalKeys",
        "conflictingValues",
        "unmappedLabels",
        "missingExpectedCategories",
        "schemaFailures",
        "codeListFailures",
    )
    count_rows = sum(item["measure_id"] == "prisoner-count" for item in rows)
    rate_rows = sum(
        item["measure_id"] == "imprisonment-rate-country-of-birth" for item in rows
    )
    not_applicable = sum(item["value_status"] == "not_applicable" for item in rows)
    passed = (
        report["acceptedWorkbookCount"] == 5
        and report["exceptionWorkbookCount"] == 0
        and report["canonicalObservationCount"] == 1709
        and report["crossYearIssues"] == []
        and report["providerCalls"] == 0
        and [item["year"] for item in report["workbooks"]] == list(range(2021, 2026))
        and sum(item["rawObservationCount"] for item in report["workbooks"]) == 1709
        and sum(item["excludedObservationCount"] for item in report["workbooks"]) == 0
        and all(
            item["decision"] == "prototype_auto_accepted"
            and all(item["checks"].values())
            for item in report["workbooks"]
        )
        and count_rows == 1539
        and rate_rows == 170
        and not_applicable == 4
        and collation["rowCount"] == 1709
        and all(collation[field] == [] for field in clean_collation_fields)
    )
    return AssetCheckResult(
        passed=passed,
        metadata={
            "run_digest": report["runDigest"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "canonical_observations": report["canonicalObservationCount"],
            "prisoner_count_observations": count_rows,
            "imprisonment_rate_observations": rate_rows,
            "not_applicable_observations": not_applicable,
            "provider_calls": report["providerCalls"],
        },
    )


_OFFENCE_COHORT_SPECS = {
    23: {
        "output": "dagster-table-23-five-year-replay",
        "cohort": "prisoners-table-23-2021-2025.json",
        "dimension": "most_serious_offence_id",
        "other_dimension": "most_serious_charge_id",
        "year_counts": [486, 531, 513, 513, 513],
        "canonical_count": 2556,
    },
    31: {
        "output": "dagster-table-31-five-year-replay",
        "cohort": "prisoners-table-31-2021-2025.json",
        "dimension": "most_serious_charge_id",
        "other_dimension": "most_serious_offence_id",
        "year_counts": [450, 522, 522, 522, 522],
        "canonical_count": 2538,
    },
}


def _materialize_offence_cohort(
    runtime: TidyRuntimeResource,
    *,
    table: int,
) -> MaterializeResult:
    spec = _OFFENCE_COHORT_SPECS[table]
    output_root = runtime.project() / ".product-prototype" / str(spec["output"])
    result = run_product_prototype(
        repository=runtime.repository(),
        project_root=runtime.project(),
        cohort_path=(
            runtime.project() / "fixtures" / "product-prototype" / str(spec["cohort"])
        ),
        output_root=output_root,
        mode="replay",
    )
    report = result.report
    rows = json.loads((output_root / "canonical-observations.json").read_text())
    return MaterializeResult(
        metadata={
            "run_digest": report["runDigest"],
            "mode": report["mode"],
            "provider_calls": report["providerCalls"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "raw_observations": sum(
                item["rawObservationCount"] for item in report["workbooks"]
            ),
            "canonical_observations": report["canonicalObservationCount"],
            "published_total_observations": sum(
                item[str(spec["dimension"])] == "TOTAL" for item in rows
            ),
            "workbooks": report["workbooks"],
            "collation_report_path": str(output_root / "collation-report.json"),
            "artifact_uri": f"artifact://{result.run.content_digest}",
        },
        data_version=DataVersion(result.run.content_digest),
    )


def _check_offence_cohort(
    runtime: TidyRuntimeResource,
    *,
    table: int,
) -> AssetCheckResult:
    spec = _OFFENCE_COHORT_SPECS[table]
    output_root = runtime.project() / ".product-prototype" / str(spec["output"])
    try:
        report = json.loads((output_root / "run.json").read_text())
        collation = json.loads((output_root / "collation-report.json").read_text())
        rows = json.loads((output_root / "canonical-observations.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        return AssetCheckResult(
            passed=False,
            metadata={
                "error": f"Table {table} replay evidence is unavailable: {error}"
            },
        )
    clean_collation_fields = (
        "excludedExceptions",
        "duplicateCanonicalKeys",
        "conflictingValues",
        "unmappedLabels",
        "missingExpectedCategories",
        "schemaFailures",
        "codeListFailures",
    )
    dimension = str(spec["dimension"])
    other_dimension = str(spec["other_dimension"])
    canonical_count = int(spec["canonical_count"])
    passed = (
        report["acceptedWorkbookCount"] == 5
        and report["exceptionWorkbookCount"] == 0
        and report["canonicalObservationCount"] == canonical_count
        and report["crossYearIssues"] == []
        and report["providerCalls"] == 0
        and [item["year"] for item in report["workbooks"]] == list(range(2021, 2026))
        and [item["rawObservationCount"] for item in report["workbooks"]]
        == spec["year_counts"]
        and [item["observationCount"] for item in report["workbooks"]]
        == spec["year_counts"]
        and all(
            item["decision"] == "prototype_auto_accepted"
            and item["excludedObservationCount"] == 0
            and all(item["checks"].values())
            for item in report["workbooks"]
        )
        and len(rows) == canonical_count
        and sum(item[dimension] == "TOTAL" for item in rows) == 45
        and all(dimension in item and other_dimension not in item for item in rows)
        and collation["rowCount"] == canonical_count
        and all(collation[field] == [] for field in clean_collation_fields)
    )
    return AssetCheckResult(
        passed=passed,
        metadata={
            "run_digest": report["runDigest"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "canonical_observations": report["canonicalObservationCount"],
            "published_total_observations": sum(
                item.get(dimension) == "TOTAL" for item in rows
            ),
            "provider_calls": report["providerCalls"],
        },
    )


@asset(
    name="product_prototype_offence_replay",
    description=(
        "Provider-free replay of the 2021-2025 Table 23 cohort, producing "
        "sentenced prisoner counts by selected most serious offence and jurisdiction."
    ),
    group_name="product_prototype",
    code_version="tidy.product-prototype-offence-run/v1",
)
def product_prototype_offence_replay(
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    return _materialize_offence_cohort(runtime, table=23)


@asset_check(
    asset=product_prototype_offence_replay,
    name="offence_acceptance_and_collation",
)
def product_prototype_offence_replay_check(
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    return _check_offence_cohort(runtime, table=23)


@asset(
    name="product_prototype_charge_replay",
    description=(
        "Provider-free replay of the 2021-2025 Table 31 cohort, producing "
        "unsentenced prisoner counts by selected most serious charge and jurisdiction."
    ),
    group_name="product_prototype",
    code_version="tidy.product-prototype-charge-run/v1",
)
def product_prototype_charge_replay(
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    return _materialize_offence_cohort(runtime, table=31)


@asset_check(
    asset=product_prototype_charge_replay,
    name="charge_acceptance_and_collation",
)
def product_prototype_charge_replay_check(
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    return _check_offence_cohort(runtime, table=31)


def _materialize_large_batch_cohort(
    runtime: TidyRuntimeResource,
    spec: LargeBatchSpec,
    batch_id: str,
    recorded_at: str,
) -> MaterializeResult:
    output_root = runtime.project() / ".product-prototype" / spec.output_directory
    if spec.replay_engine == "offenders-remaining-c4-v1":
        report = run_offenders_remaining_family(
            project_root=runtime.project(),
            cohort_path=runtime.project() / spec.cohort_path,
            output_root=output_root,
            recorded_at=recorded_at,
        )
        run_content_digest = report["runDigest"]
    else:
        result = run_product_prototype(
            repository=runtime.repository(),
            project_root=runtime.project(),
            cohort_path=runtime.project() / spec.cohort_path,
            output_root=output_root,
            mode="replay",
            recorded_at=recorded_at,
        )
        report = result.report
        run_content_digest = result.run.content_digest
    rows = json.loads((output_root / "canonical-observations.json").read_text())
    return MaterializeResult(
        metadata={
            "batch_id": batch_id,
            "family_id": spec.family_id,
            "run_digest": report["runDigest"],
            "mode": report["mode"],
            "provider_calls": report["providerCalls"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "raw_observations": sum(
                item["rawObservationCount"] for item in report["workbooks"]
            ),
            "canonical_observations": report["canonicalObservationCount"],
            "measure_counts": dict(Counter(item["measure_id"] for item in rows)),
            "value_status_counts": dict(Counter(item["value_status"] for item in rows)),
            "preserves_publication_vintage": spec.preserves_publication_vintage,
            "manual_replay_years": list(spec.expected_manual_replay_years),
            "workbooks": report["workbooks"],
            "collation_report_path": str(output_root / "collation-report.json"),
            "artifact_uri": f"artifact://{run_content_digest}",
        },
        data_version=DataVersion(run_content_digest),
    )


def _check_large_batch_cohort(
    runtime: TidyRuntimeResource,
    spec: LargeBatchSpec,
    batch_id: str,
) -> AssetCheckResult:
    output_root = runtime.project() / ".product-prototype" / spec.output_directory
    try:
        report = json.loads((output_root / "run.json").read_text())
        rows = json.loads((output_root / "canonical-observations.json").read_text())
        collation = json.loads((output_root / "collation-report.json").read_text())
        verify_large_batch_reproduction(runtime.project(), spec, output_root)
    except (OSError, json.JSONDecodeError, RuntimeError) as error:
        return AssetCheckResult(
            passed=False,
            metadata={"error": f"{spec.family_id} evidence is unavailable: {error}"},
        )
    clean_fields = (
        "excludedExceptions",
        "duplicateCanonicalKeys",
        "conflictingValues",
        "unmappedLabels",
        "missingExpectedCategories",
        "schemaFailures",
        "codeListFailures",
    )
    measure_counts = dict(sorted(Counter(item["measure_id"] for item in rows).items()))
    status_counts = dict(sorted(Counter(item["value_status"] for item in rows).items()))
    vintage_present = all("publication_vintage_date" in item for item in rows)
    passed = (
        report["acceptedWorkbookCount"] == len(spec.expected_years)
        and report["exceptionWorkbookCount"] == 0
        and report["canonicalObservationCount"] == spec.expected_canonical_count
        and report["crossYearIssues"] == []
        and report["providerCalls"] == 0
        and _run_authority_claims_are_safe(report)
        and [item["year"] for item in report["workbooks"]] == list(spec.expected_years)
        and [item["rawObservationCount"] for item in report["workbooks"]]
        == list(spec.expected_year_counts)
        and [item["observationCount"] for item in report["workbooks"]]
        == list(spec.expected_year_counts)
        and all(
            item["decision"] == "prototype_auto_accepted"
            and item["excludedObservationCount"] == 0
            and item["issues"] == []
            and all(item["checks"].values())
            for item in report["workbooks"]
        )
        and len(rows) == spec.expected_canonical_count
        and measure_counts == spec.expected_measure_counts
        and status_counts == spec.expected_value_status_counts
        and vintage_present == spec.preserves_publication_vintage
        and collation["rowCount"] == spec.expected_canonical_count
        and all(collation[field] == [] for field in clean_fields)
    )
    return AssetCheckResult(
        passed=passed,
        metadata={
            "batch_id": batch_id,
            "family_id": spec.family_id,
            "run_digest": report["runDigest"],
            "accepted_workbooks": report["acceptedWorkbookCount"],
            "exception_workbooks": report["exceptionWorkbookCount"],
            "canonical_observations": report["canonicalObservationCount"],
            "measure_counts": measure_counts,
            "value_status_counts": status_counts,
            "provider_calls": report["providerCalls"],
        },
    )


def _build_large_batch_asset(
    spec: LargeBatchSpec,
    batch_id: str,
    recorded_at: str,
):
    def materialize(runtime: TidyRuntimeResource) -> MaterializeResult:
        return _materialize_large_batch_cohort(runtime, spec, batch_id, recorded_at)

    materialize.__name__ = spec.dagster_asset
    return asset(
        name=spec.dagster_asset,
        description=(
            f"Provider-free {len(spec.expected_years)}-workbook replay for "
            f"{spec.label}; part of {batch_id}."
        ),
        group_name="product_prototype_large_batch",
        code_version="tidy.product-prototype-large-batch-run/v1",
    )(materialize)


def _build_large_batch_check(
    spec: LargeBatchSpec,
    cohort_asset,
    batch_id: str,
):
    def check(runtime: TidyRuntimeResource) -> AssetCheckResult:
        return _check_large_batch_cohort(runtime, spec, batch_id)

    check.__name__ = f"{spec.dagster_asset}_check"
    return asset_check(
        asset=cohort_asset,
        name="automatic_acceptance_and_collation",
    )(check)


def _build_large_batch_definitions(registry: LargeBatchRegistry):
    assets = tuple(
        _build_large_batch_asset(
            spec,
            registry.batch_id,
            spec.replay_recorded_at or registry.replay_recorded_at,
        )
        for spec in registry.entries
    )
    checks = tuple(
        _build_large_batch_check(spec, cohort_asset, registry.batch_id)
        for spec, cohort_asset in zip(registry.entries, assets, strict=True)
    )
    jobs = tuple(
        define_asset_job(
            spec.dagster_job,
            selection=AssetSelection.assets(cohort_asset),
            description=(
                f"Provider-free {len(spec.expected_years)}-release replay for "
                f"{spec.label}."
            ),
            tags={
                "provider_calls": "0",
                "mode": "replay",
                "years": ",".join(str(year) for year in spec.expected_years),
                "batch": registry.batch_id,
                "family": spec.family_id,
            },
        )
        for spec, cohort_asset in zip(registry.entries, assets, strict=True)
    )
    aggregate_years = sorted(
        {year for spec in registry.entries for year in spec.expected_years}
    )
    aggregate_job = define_asset_job(
        "product_prototype_large_batch_replay_job",
        selection=AssetSelection.assets(*assets),
        description=(
            f"Provider-free isolated replay of {len(registry.entries)} registered "
            f"families and {registry.worksheet_count} worksheets across publications."
        ),
        tags={
            "provider_calls": "0",
            "mode": "replay",
            "years": ",".join(str(year) for year in aggregate_years),
            "batch": registry.batch_id,
            "worksheet_count": str(registry.worksheet_count),
        },
    )
    return assets, checks, jobs, aggregate_job


if (_DEFAULT_PROJECT_ROOT / REGISTRY_PATH).is_file():
    LARGE_BATCH_REGISTRY: LargeBatchRegistry | None = load_large_batch_registry(
        _DEFAULT_PROJECT_ROOT
    )
    (
        LARGE_BATCH_ASSETS,
        LARGE_BATCH_CHECKS,
        LARGE_BATCH_JOBS,
        product_prototype_large_batch_replay_job,
    ) = _build_large_batch_definitions(LARGE_BATCH_REGISTRY)
else:
    LARGE_BATCH_REGISTRY = None
    LARGE_BATCH_ASSETS = ()
    LARGE_BATCH_CHECKS = ()
    LARGE_BATCH_JOBS = ()
    product_prototype_large_batch_replay_job = None


@asset(
    name="source_catalog_snapshot",
    description=(
        "Unpartitioned observation of the identity-pinned active fixture catalog."
    ),
    group_name="provider_free_m4",
    code_version="tidy.source-catalog-snapshot/v1",
)
def source_catalog_snapshot(
    context: AssetExecutionContext,
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    _expected_recipe, expected_catalog = _dispatch_binding(context)
    index = publish_catalog(
        runtime.repository(),
        runtime.project(),
        expected_catalog_digest=expected_catalog,
    )
    return _materialize(index.content_digest, index.record_count, index.kind, "catalog")


@asset(
    partitions_def=WORK_UNIT_PARTITIONS,
    deps=[source_catalog_snapshot],
    group_name="provider_free_m4",
    code_version="tidy.verified-fixture-inputs-index/v1",
)
def verified_fixture_inputs_index(
    context: AssetExecutionContext,
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    expected_recipe, expected_catalog = _dispatch_binding(context)
    index = publish_inputs_index(
        runtime.repository(),
        runtime.project(),
        context.partition_key,
        expected_recipe_digest=expected_recipe,
        expected_catalog_digest=expected_catalog,
    )
    return _materialize(
        index.content_digest, index.record_count, index.kind, context.partition_key
    )


@asset(
    partitions_def=WORK_UNIT_PARTITIONS,
    deps=[verified_fixture_inputs_index],
    group_name="provider_free_m4",
    code_version="tidy.recipe-execution-evidence-index/v1",
    pool="provider_free_worker",
)
def recipe_execution_evidence_index(
    context: AssetExecutionContext,
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    expected_recipe, expected_catalog = _dispatch_binding(context)
    index = execute_work_unit(
        runtime.repository(),
        runtime.project(),
        context.partition_key,
        expected_recipe_digest=expected_recipe,
        expected_catalog_digest=expected_catalog,
    )
    return _materialize(
        index.content_digest, index.record_count, index.kind, context.partition_key
    )


@asset(
    partitions_def=WORK_UNIT_PARTITIONS,
    deps=[recipe_execution_evidence_index],
    group_name="provider_free_m4",
    code_version="tidy.active-work-unit-projection/v1",
)
def active_work_unit_projection(
    context: AssetExecutionContext,
    runtime: TidyRuntimeResource,
) -> MaterializeResult:
    expected_recipe, expected_catalog = _dispatch_binding(context)
    index = publish_projection_index(
        runtime.repository(),
        runtime.project(),
        context.partition_key,
        expected_recipe_digest=expected_recipe,
        expected_catalog_digest=expected_catalog,
    )
    return _materialize(
        index.content_digest, index.record_count, index.kind, context.partition_key
    )


@asset_check(
    asset=verified_fixture_inputs_index,
    name="content_hash_and_provenance",
)
def verified_fixture_inputs_check(
    context: AssetCheckExecutionContext,
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    expected_recipe, expected_catalog = _dispatch_binding(context)
    unit = get_work_unit(
        runtime.project(),
        context.partition_key,
        expected_recipe_digest=expected_recipe,
        expected_catalog_digest=expected_catalog,
    )
    gate = get_gate_result(
        runtime.repository(),
        "input-provenance",
        context.partition_key,
        unit.recipe_digest,
    )
    return AssetCheckResult(
        passed=gate.passed,
        metadata={
            "status": "verified",
            "work_unit_id": context.partition_key,
            "gate_digest": gate.content_digest,
            "subject_digest": gate.subject_digest,
        },
    )


@asset_check(
    asset=recipe_execution_evidence_index,
    name="frozen_reference_parity",
)
def recipe_execution_check(
    context: AssetCheckExecutionContext,
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    expected_recipe, expected_catalog = _dispatch_binding(context)
    unit = get_work_unit(
        runtime.project(),
        context.partition_key,
        expected_recipe_digest=expected_recipe,
        expected_catalog_digest=expected_catalog,
    )
    gate = get_gate_result(
        runtime.repository(),
        "frozen-reference-execution",
        context.partition_key,
        unit.recipe_digest,
    )
    return AssetCheckResult(
        passed=gate.passed,
        metadata={
            "status": "reference-parity-verified",
            "work_unit_id": context.partition_key,
            "gate_digest": gate.content_digest,
            "subject_digest": gate.subject_digest,
        },
    )


@asset_check(
    asset=active_work_unit_projection,
    name="authoritative_reconstruction",
)
def active_projection_check(
    context: AssetCheckExecutionContext,
    runtime: TidyRuntimeResource,
) -> AssetCheckResult:
    expected_recipe, expected_catalog = _dispatch_binding(context)
    unit = get_work_unit(
        runtime.project(),
        context.partition_key,
        expected_recipe_digest=expected_recipe,
        expected_catalog_digest=expected_catalog,
    )
    gate = get_gate_result(
        runtime.repository(),
        "authoritative-reconstruction",
        context.partition_key,
        unit.recipe_digest,
    )
    return AssetCheckResult(
        passed=gate.passed,
        metadata={
            "status": "reconstructable",
            "work_unit_id": context.partition_key,
            "gate_digest": gate.content_digest,
            "subject_digest": gate.subject_digest,
        },
    )


product_prototype_stage_projection_job = define_asset_job(
    "product_prototype_stage_projection_job",
    selection=AssetSelection.assets(product_prototype_stage_projection),
    description="Project every product-prototype stage and exception state.",
    tags={"mode": "checked-stage-projection"},
)


product_prototype_live_evidence_job = define_asset_job(
    "product_prototype_live_evidence_job",
    selection=AssetSelection.assets(product_prototype_live_evidence),
    description="Verify and project the checked fresh-Luna product evidence.",
    tags={"provider_calls": "3", "mode": "checked-live-evidence"},
)


product_prototype_replay_job = define_asset_job(
    "product_prototype_replay_job",
    selection=AssetSelection.assets(product_prototype_replay),
    description=(
        "Provider-free end-to-end replay, automatic acceptance, exception routing, "
        "and canonical collation for the five-workbook 2021-2025 cohort."
    ),
    tags={"provider_calls": "0", "mode": "replay", "years": "2021-2025"},
)


product_prototype_age_replay_job = define_asset_job(
    "product_prototype_age_replay_job",
    selection=AssetSelection.assets(product_prototype_age_replay),
    description=(
        "Provider-free Table 21 replay and canonical prisoner-count collation by "
        "jurisdiction, Indigenous status, sex, and age group for 2021-2025."
    ),
    tags={
        "provider_calls": "0",
        "mode": "replay",
        "years": "2021-2025",
        "table": "21",
    },
)


product_prototype_country_replay_job = define_asset_job(
    "product_prototype_country_replay_job",
    selection=AssetSelection.assets(product_prototype_country_replay),
    description=(
        "Provider-free Table 22 replay with separate prisoner-count and "
        "country-of-birth imprisonment-rate measures for 2021-2025."
    ),
    tags={
        "provider_calls": "0",
        "mode": "replay",
        "years": "2021-2025",
        "table": "22",
    },
)


product_prototype_offence_replay_job = define_asset_job(
    "product_prototype_offence_replay_job",
    selection=AssetSelection.assets(product_prototype_offence_replay),
    description=(
        "Provider-free Table 23 sentenced-prisoner replay by selected most "
        "serious offence and jurisdiction for 2021-2025."
    ),
    tags={
        "provider_calls": "0",
        "mode": "replay",
        "years": "2021-2025",
        "table": "23",
    },
)


product_prototype_charge_replay_job = define_asset_job(
    "product_prototype_charge_replay_job",
    selection=AssetSelection.assets(product_prototype_charge_replay),
    description=(
        "Provider-free Table 31 unsentenced-prisoner replay by selected most "
        "serious charge and jurisdiction for 2021-2025."
    ),
    tags={
        "provider_calls": "0",
        "mode": "replay",
        "years": "2021-2025",
        "table": "31",
    },
)


project_work_unit_job = define_asset_job(
    "project_provider_free_work_unit",
    selection=AssetSelection.assets(
        source_catalog_snapshot,
        verified_fixture_inputs_index,
        recipe_execution_evidence_index,
        active_work_unit_projection,
    ),
    description="Provider-free projection from authoritative indexes; no providers.",
    tags={"provider_calls": "0", "authority": "external-artifact-repository"},
)


@sensor(
    job=project_work_unit_job,
    name="provider_free_work_unit_sensor",
    default_status=DefaultSensorStatus.RUNNING,
    minimum_interval_seconds=1,
    required_resource_keys={"runtime"},
)
def provider_free_work_unit_sensor(
    context: SensorEvaluationContext,
) -> SensorResult | SkipReason:
    runtime = context.resources.runtime
    catalog = discover_work_units(Path(runtime.project_root))
    keys = [unit.work_unit_id for unit in catalog.units]
    existing = set(context.instance.get_dynamic_partitions(WORK_UNIT_PARTITIONS.name))
    active_union = existing | set(keys)
    if len(active_union) > MAX_ACTIVE_WORK_UNITS:
        raise RuntimeError(
            "Existing plus discovered work-unit partitions exceed bounded maximum "
            f"{MAX_ACTIVE_WORK_UNITS}"
        )
    if context.cursor == catalog.catalog_digest:
        return SkipReason("Identity-pinned catalog is already fully requested.")
    additions = [key for key in keys if key not in existing]
    requests = [
        RunRequest(
            run_key=work_unit_run_key(unit),
            partition_key=unit.work_unit_id,
            tags={
                "work_unit_id": unit.work_unit_id,
                "processing_profile_digest": PROCESSING_PROFILE_DIGEST,
                EXPECTED_RECIPE_TAG: unit.recipe_digest,
                EXPECTED_CATALOG_TAG: catalog.catalog_digest,
                "provider_calls": "0",
            },
        )
        for unit in catalog.units
    ]
    return SensorResult(
        dynamic_partitions_requests=(
            [WORK_UNIT_PARTITIONS.build_add_request(additions)] if additions else []
        ),
        run_requests=requests,
        cursor=catalog.catalog_digest,
    )


def build_definitions(
    *, project_root: Path | None = None, repository_root: Path | None = None
) -> Definitions:
    project = (project_root or _default_project_root()).resolve()
    repository = (
        repository_root
        or Path(os.environ.get("TIDY_ARTIFACT_ROOT", project / ".local-repository"))
    ).resolve()
    if project == _DEFAULT_PROJECT_ROOT and LARGE_BATCH_REGISTRY is not None:
        batch_registry = LARGE_BATCH_REGISTRY
        batch_assets = LARGE_BATCH_ASSETS
        batch_checks = LARGE_BATCH_CHECKS
        batch_jobs = LARGE_BATCH_JOBS
        batch_aggregate_job = product_prototype_large_batch_replay_job
    else:
        batch_registry = load_large_batch_registry(project)
        (
            batch_assets,
            batch_checks,
            batch_jobs,
            batch_aggregate_job,
        ) = _build_large_batch_definitions(batch_registry)
    return Definitions(
        assets=[
            product_prototype_stage_projection,
            product_prototype_live_evidence,
            product_prototype_replay,
            product_prototype_age_replay,
            product_prototype_country_replay,
            product_prototype_offence_replay,
            product_prototype_charge_replay,
            *batch_assets,
            source_catalog_snapshot,
            verified_fixture_inputs_index,
            recipe_execution_evidence_index,
            active_work_unit_projection,
        ],
        asset_checks=[
            product_prototype_stage_projection_check,
            product_prototype_live_evidence_check,
            product_prototype_replay_check,
            product_prototype_age_replay_check,
            product_prototype_country_replay_check,
            product_prototype_offence_replay_check,
            product_prototype_charge_replay_check,
            *batch_checks,
            verified_fixture_inputs_check,
            recipe_execution_check,
            active_projection_check,
        ],
        jobs=[
            product_prototype_stage_projection_job,
            product_prototype_live_evidence_job,
            product_prototype_replay_job,
            product_prototype_age_replay_job,
            product_prototype_country_replay_job,
            product_prototype_offence_replay_job,
            product_prototype_charge_replay_job,
            *batch_jobs,
            batch_aggregate_job,
            project_work_unit_job,
        ],
        sensors=[provider_free_work_unit_sensor],
        resources={
            "runtime": TidyRuntimeResource(
                project_root=str(project), repository_root=str(repository)
            )
        },
        metadata={
            "provider_calls": 0,
            "authority": "external-content-derivation-custody-repository",
            "summary_supported": True,
            "summary_scope": "historical-default-fixture-parity-v1",
            "compact_context_supported": True,
            "compact_context_scope": "historical-complete-fixture-parity-v1",
            "region_catalog_supported": True,
            "region_catalog_scope": "historical-default-four-catalog-parity-v1",
            "prompt_assembly_supported": True,
            "prompt_scope": "source-owned-fourteen-snapshot-cases-v1",
            "prompt_output_exposed": False,
            "product_prototype_replay_supported": True,
            "product_prototype_replay_scope": "prisoners-table-30-2021-2025",
            "product_prototype_age_replay_supported": True,
            "product_prototype_age_replay_scope": "prisoners-table-21-2021-2025",
            "product_prototype_country_replay_supported": True,
            "product_prototype_country_replay_scope": "prisoners-table-22-2021-2025",
            "product_prototype_offence_replay_supported": True,
            "product_prototype_offence_replay_scope": "prisoners-table-23-2021-2025",
            "product_prototype_charge_replay_supported": True,
            "product_prototype_charge_replay_scope": "prisoners-table-31-2021-2025",
            "product_prototype_large_batch_supported": True,
            "product_prototype_large_batch_id": batch_registry.batch_id,
            "product_prototype_large_batch_cohorts": len(batch_registry.entries),
            "product_prototype_large_batch_worksheets": batch_registry.worksheet_count,
            "product_prototype_live_evidence_supported": True,
            "product_prototype_stage_projection_supported": True,
            "product_prototype_live_generation_authorized": False,
        },
    )


def _dispatch_binding(
    context: AssetExecutionContext | AssetCheckExecutionContext,
) -> tuple[str, str]:
    recipe = context.run.tags.get(EXPECTED_RECIPE_TAG)
    catalog = context.run.tags.get(EXPECTED_CATALOG_TAG)
    if not recipe or not catalog:
        raise RuntimeError(
            "Work-unit runs require sensor-pinned recipe and catalog digests"
        )
    return recipe, catalog


def _default_project_root() -> Path:
    configured = os.environ.get("TIDY_PROJECT_ROOT")
    if configured:
        return Path(configured)
    working_directory = Path.cwd()
    if (working_directory / REGISTRY_PATH).is_file():
        return working_directory
    return _DEFAULT_PROJECT_ROOT


def _materialize(
    digest: str, record_count: int, kind: str, work_unit_id: str
) -> MaterializeResult:
    return MaterializeResult(
        metadata={
            "index_digest": digest,
            "record_count": record_count,
            "index_kind": kind,
            "work_unit_id": work_unit_id,
            "artifact_uri": f"artifact://{digest}",
            "provider_calls": 0,
        },
        data_version=DataVersion(digest),
    )
