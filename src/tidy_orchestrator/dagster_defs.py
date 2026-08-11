"""Replaceable Dagster projection for the provider-free authoritative runtime."""

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

from .artifacts import LocalArtifactRepository
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
            source_catalog_snapshot,
            verified_fixture_inputs_index,
            recipe_execution_evidence_index,
            active_work_unit_projection,
        ],
        asset_checks=[
            verified_fixture_inputs_check,
            recipe_execution_check,
            active_projection_check,
        ],
        jobs=[project_work_unit_job],
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
