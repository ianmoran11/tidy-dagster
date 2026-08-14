"""Replaceable Dagster projection for the provider-free authoritative runtime."""

import json
import os
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
from .product_prototype import run_product_prototype, verify_live_evidence
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
    return Definitions(
        assets=[
            product_prototype_stage_projection,
            product_prototype_live_evidence,
            product_prototype_replay,
            source_catalog_snapshot,
            verified_fixture_inputs_index,
            recipe_execution_evidence_index,
            active_work_unit_projection,
        ],
        asset_checks=[
            product_prototype_stage_projection_check,
            product_prototype_live_evidence_check,
            product_prototype_replay_check,
            verified_fixture_inputs_check,
            recipe_execution_check,
            active_projection_check,
        ],
        jobs=[
            product_prototype_stage_projection_job,
            product_prototype_live_evidence_job,
            product_prototype_replay_job,
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
    return Path(os.environ.get("TIDY_PROJECT_ROOT", Path(__file__).parents[2]))


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
