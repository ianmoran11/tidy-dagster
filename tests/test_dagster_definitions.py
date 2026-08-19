from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from dagster import DagsterInstance, Definitions, build_sensor_context

import tidy_orchestrator.dagster_defs as dagster_defs_module
from tidy_orchestrator.artifacts import LocalArtifactRepository, domain_digest
from tidy_orchestrator.dagster_defs import (
    EXPECTED_CATALOG_TAG,
    EXPECTED_RECIPE_TAG,
    LARGE_BATCH_ASSETS,
    LARGE_BATCH_CHECKS,
    LARGE_BATCH_JOBS,
    LARGE_BATCH_REGISTRY,
    WORK_UNIT_PARTITIONS,
    TidyRuntimeResource,
    _check_large_batch_cohort,
    active_work_unit_projection,
    build_definitions,
    product_prototype_age_replay,
    product_prototype_age_replay_check,
    product_prototype_charge_replay,
    product_prototype_charge_replay_check,
    product_prototype_country_replay,
    product_prototype_country_replay_check,
    product_prototype_live_evidence,
    product_prototype_live_evidence_check,
    product_prototype_offence_replay,
    product_prototype_offence_replay_check,
    product_prototype_replay,
    product_prototype_replay_check,
    product_prototype_stage_projection,
    product_prototype_stage_projection_check,
    provider_free_work_unit_sensor,
    recipe_execution_evidence_index,
    verified_fixture_inputs_index,
)
from tidy_orchestrator.work_units import (
    GATE_NAMES,
    MAX_ACTIVE_WORK_UNITS,
    REQUESTED_USE_CASE,
    _ensure_pointer,
    _revision_pointer,
    _set_active_pointer,
    discover_work_units,
    execute_work_unit,
    get_gate_result,
    publish_catalog,
    publish_inputs_index,
    publish_projection_index,
    work_unit_run_key,
)

PROJECT = Path(__file__).parents[1]


def test_definitions_include_provider_free_product_prototype_projection(
    tmp_path: Path,
) -> None:
    definitions = build_definitions(
        project_root=PROJECT, repository_root=tmp_path / "repository"
    )
    Definitions.validate_loadable(definitions)
    assert product_prototype_replay.key.to_user_string() == "product_prototype_replay"
    assert product_prototype_age_replay.key.to_user_string() == (
        "product_prototype_age_replay"
    )
    assert product_prototype_age_replay_check.check_key.name == (
        "age_acceptance_and_collation"
    )
    assert product_prototype_country_replay.key.to_user_string() == (
        "product_prototype_country_replay"
    )
    assert product_prototype_country_replay_check.check_key.name == (
        "country_measure_acceptance_and_collation"
    )
    assert product_prototype_offence_replay.key.to_user_string() == (
        "product_prototype_offence_replay"
    )
    assert product_prototype_offence_replay_check.check_key.name == (
        "offence_acceptance_and_collation"
    )
    assert product_prototype_charge_replay.key.to_user_string() == (
        "product_prototype_charge_replay"
    )
    assert product_prototype_charge_replay_check.check_key.name == (
        "charge_acceptance_and_collation"
    )
    assert product_prototype_stage_projection.key.to_user_string() == (
        "product_prototype_stage_projection"
    )
    assert product_prototype_stage_projection_check.check_key.name == (
        "all_stages_projected"
    )
    assert product_prototype_live_evidence.key.to_user_string() == (
        "product_prototype_live_evidence"
    )
    assert product_prototype_live_evidence_check.check_key.name == (
        "fresh_luna_completion"
    )
    assert product_prototype_replay_check.check_key.name == (
        "automatic_acceptance_and_collation"
    )
    assert definitions.metadata["product_prototype_replay_supported"].value is True
    assert definitions.metadata["product_prototype_replay_scope"].value == (
        "prisoners-table-30-2021-2025"
    )
    assert definitions.metadata["product_prototype_age_replay_supported"].value
    assert definitions.metadata["product_prototype_age_replay_scope"].value == (
        "prisoners-table-21-2021-2025"
    )
    assert definitions.metadata["product_prototype_country_replay_supported"].value
    assert definitions.metadata["product_prototype_country_replay_scope"].value == (
        "prisoners-table-22-2021-2025"
    )
    assert definitions.metadata["product_prototype_offence_replay_supported"].value
    assert definitions.metadata["product_prototype_offence_replay_scope"].value == (
        "prisoners-table-23-2021-2025"
    )
    assert definitions.metadata["product_prototype_charge_replay_supported"].value
    assert definitions.metadata["product_prototype_charge_replay_scope"].value == (
        "prisoners-table-31-2021-2025"
    )
    assert definitions.metadata["product_prototype_live_evidence_supported"].value
    assert definitions.metadata["product_prototype_stage_projection_supported"].value
    assert (
        definitions.metadata["product_prototype_live_generation_authorized"].value
        is False
    )


def test_definitions_include_321_worksheet_cross_publication_batch() -> None:
    definitions = build_definitions(project_root=PROJECT)
    Definitions.validate_loadable(definitions)
    assert LARGE_BATCH_REGISTRY.worksheet_count == 321
    assert len(LARGE_BATCH_REGISTRY.entries) == 107
    assert len(LARGE_BATCH_ASSETS) == 107
    assert len(LARGE_BATCH_CHECKS) == 107
    assert len(LARGE_BATCH_JOBS) == 107
    assert definitions.metadata["product_prototype_large_batch_supported"].value
    assert definitions.metadata["product_prototype_large_batch_worksheets"].value == 321
    assert {
        spec.family_id
        for spec in LARGE_BATCH_REGISTRY.entries
        if spec.family_id.startswith("offenders-table-")
    } == {f"offenders-table-{table}" for table in range(1, 6)}
    assert (
        sum(
            spec.family_id.startswith("criminal-courts-")
            for spec in LARGE_BATCH_REGISTRY.entries
        )
        == 80
    )
    assert {asset.key.to_user_string() for asset in LARGE_BATCH_ASSETS} == {
        spec.dagster_asset for spec in LARGE_BATCH_REGISTRY.entries
    }
    assert {
        definitions.resolve_job_def(spec.dagster_job).name
        for spec in LARGE_BATCH_REGISTRY.entries
    } == {spec.dagster_job for spec in LARGE_BATCH_REGISTRY.entries}
    assert (
        definitions.resolve_job_def("product_prototype_large_batch_replay_job").name
        == "product_prototype_large_batch_replay_job"
    )


def test_build_definitions_uses_requested_project_registry(tmp_path: Path) -> None:
    registry_path = tmp_path / "fixtures/product-prototype/large-batch-assets-v1.json"
    registry_path.parent.mkdir(parents=True)
    registry = json.loads(
        (PROJECT / "fixtures/product-prototype/large-batch-assets-v1.json").read_text()
    )
    registry["batchId"] = "alternate-three-hundred-twenty-one-worksheets-v1"
    registry_path.write_text(json.dumps(registry))
    definitions = build_definitions(project_root=tmp_path)
    assert (
        definitions.metadata["product_prototype_large_batch_id"].value
        == "alternate-three-hundred-twenty-one-worksheets-v1"
    )
    assert definitions.metadata["product_prototype_large_batch_worksheets"].value == 321


def test_definitions_load_identity_and_share_one_partition_definition(
    tmp_path: Path,
) -> None:
    definitions = build_definitions(
        project_root=PROJECT, repository_root=tmp_path / "repository"
    )
    Definitions.validate_loadable(definitions)
    partitioned = (
        verified_fixture_inputs_index,
        recipe_execution_evidence_index,
        active_work_unit_projection,
    )
    assert all(asset.partitions_def is WORK_UNIT_PARTITIONS for asset in partitioned)
    assert WORK_UNIT_PARTITIONS.name == "provider_free_work_units_v1"
    catalog = discover_work_units(PROJECT)
    assert len(catalog.units) == 3
    for unit in catalog.units:
        assert unit.requested_use_case == REQUESTED_USE_CASE
        assert unit.work_unit_id == domain_digest(
            "tidy.work-unit/v1",
            {
                "workbookDigest": unit.workbook_digest,
                "sheetName": unit.sheet_name,
                "requestedUseCase": "provider-free-reference-parity",
                "processingProfileDigest": unit.processing_profile_digest,
            },
        )
        assert unit.recipe_digest not in unit.work_unit_id


def test_recipe_revision_changes_run_and_revision_keys_not_work_unit(
    tmp_path: Path,
) -> None:
    unit = discover_work_units(PROJECT).units[0]
    revision = replace(
        unit,
        recipe_digest=domain_digest("test.recipe-revision/v1", {"revision": 2}),
    )
    assert revision.work_unit_id == unit.work_unit_id
    assert work_unit_run_key(revision) != work_unit_run_key(unit)
    assert _revision_pointer("execution", revision) != _revision_pointer(
        "execution", unit
    )

    repository = LocalArtifactRepository(tmp_path / "repository")
    target_a = repository.put_bytes(
        b"revision-a",
        kind="test-index",
        schema_version="test/v1",
        media_type="application/octet-stream",
    ).content_digest
    target_b = repository.put_bytes(
        b"revision-b",
        kind="test-index",
        schema_version="test/v1",
        media_type="application/octet-stream",
    ).content_digest
    pointer_a = _revision_pointer("execution", unit)
    pointer_b = _revision_pointer("execution", revision)
    _ensure_pointer(repository, pointer_a, target_a)
    _set_active_pointer(repository, f"m4/execution/{unit.work_unit_id}", target_a)
    _ensure_pointer(repository, pointer_b, target_b)
    _set_active_pointer(repository, f"m4/execution/{unit.work_unit_id}", target_b)
    assert repository.get_pointer(pointer_a).target_id == target_a
    assert repository.get_pointer(pointer_b).target_id == target_b
    assert (
        repository.get_pointer(f"m4/execution/{unit.work_unit_id}").target_id
        == target_b
    )


def test_identical_concurrent_pointer_publication_is_idempotent(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    target = repository.put_bytes(
        b"index",
        kind="test-index",
        schema_version="test/v1",
        media_type="application/octet-stream",
    ).content_digest

    def publish(_ordinal: int) -> None:
        _ensure_pointer(repository, "m4/test/immutable", target)
        _set_active_pointer(repository, "m4/test/active", target)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(publish, range(32)))
    assert repository.get_pointer("m4/test/immutable").target_id == target
    assert repository.get_pointer("m4/test/active").target_id == target


def test_identical_concurrent_catalog_and_input_stage_publication(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    catalog = discover_work_units(PROJECT)
    unit = catalog.units[0]

    def publish(_ordinal: int) -> tuple[str, str]:
        catalog_index = publish_catalog(
            repository,
            PROJECT,
            expected_catalog_digest=catalog.catalog_digest,
        )
        input_index = publish_inputs_index(
            repository,
            PROJECT,
            unit.work_unit_id,
            expected_recipe_digest=unit.recipe_digest,
            expected_catalog_digest=catalog.catalog_digest,
        )
        return catalog_index.content_digest, input_index.content_digest

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(publish, range(8)))
    assert len(set(results)) == 1
    assert repository.get_pointer("m4/active-catalog").target_id == results[0][0]
    assert (
        repository.get_pointer(f"m4/inputs/{unit.work_unit_id}").target_id
        == results[0][1]
    )


def test_identical_concurrent_execution_and_projection_publication(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["npm", "run", "build"], cwd=PROJECT, check=True, capture_output=True
    )
    repository = LocalArtifactRepository(tmp_path / "repository")
    catalog = discover_work_units(PROJECT)
    unit = catalog.units[0]

    def publish(_ordinal: int) -> tuple[str, str]:
        execution = execute_work_unit(
            repository,
            PROJECT,
            unit.work_unit_id,
            expected_recipe_digest=unit.recipe_digest,
            expected_catalog_digest=catalog.catalog_digest,
        )
        projection = publish_projection_index(
            repository,
            PROJECT,
            unit.work_unit_id,
            expected_recipe_digest=unit.recipe_digest,
            expected_catalog_digest=catalog.catalog_digest,
        )
        return execution.content_digest, projection.content_digest

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, range(2)))
    assert results[0] == results[1]
    assert all(
        get_gate_result(
            repository,
            gate_name,
            unit.work_unit_id,
            unit.recipe_digest,
        ).passed
        for gate_name in GATE_NAMES
    )


def test_sensor_returns_atomic_add_plus_stable_runs_and_cursor(tmp_path: Path) -> None:
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    resource = TidyRuntimeResource(
        project_root=str(PROJECT), repository_root=str(tmp_path / "repository")
    )
    with DagsterInstance.local_temp(str(instance_dir)) as instance:
        context = build_sensor_context(
            instance=instance, resources={"runtime": resource}
        )
        first = provider_free_work_unit_sensor._raw_fn(context)
        assert len(first.dynamic_partitions_requests) == 1
        assert len(first.run_requests) == 3
        assert first.cursor == discover_work_units(PROJECT).catalog_digest
        request = first.dynamic_partitions_requests[0]
        assert request.partitions_def_name == WORK_UNIT_PARTITIONS.name
        assert set(request.partition_keys) == {
            run.partition_key for run in first.run_requests
        }
        first_keys = [run.run_key for run in first.run_requests]
        repeated = provider_free_work_unit_sensor._raw_fn(context)
        assert [run.run_key for run in repeated.run_requests] == first_keys
        instance.add_dynamic_partitions(
            request.partitions_def_name, request.partition_keys
        )
        without_adds = provider_free_work_unit_sensor._raw_fn(context)
        assert without_adds.dynamic_partitions_requests == []
        assert [run.run_key for run in without_adds.run_requests] == first_keys
        committed = build_sensor_context(
            instance=instance, cursor=first.cursor, resources={"runtime": resource}
        )
        no_change = provider_free_work_unit_sensor._raw_fn(committed)
        assert (
            no_change.skip_message
            == "Identity-pinned catalog is already fully requested."
        )


def test_sensor_rejects_union_over_one_thousand_existing_keys(tmp_path: Path) -> None:
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    resource = TidyRuntimeResource(
        project_root=str(PROJECT), repository_root=str(tmp_path / "repository")
    )
    with DagsterInstance.local_temp(str(instance_dir)) as instance:
        instance.add_dynamic_partitions(
            WORK_UNIT_PARTITIONS.name,
            [f"legacy-{number:04d}" for number in range(MAX_ACTIVE_WORK_UNITS)],
        )
        context = build_sensor_context(
            instance=instance, resources={"runtime": resource}
        )
        with pytest.raises(RuntimeError, match="Existing plus discovered"):
            provider_free_work_unit_sensor._raw_fn(context)


def test_product_prototype_stage_projection_dagster_job_passes() -> None:
    definitions = build_definitions(project_root=PROJECT)
    result = definitions.resolve_job_def(
        "product_prototype_stage_projection_job"
    ).execute_in_process()
    assert result.success
    assert {
        event.asset_key.to_user_string()
        for event in result.get_asset_materialization_events()
    } == {"product_prototype_stage_projection"}
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].passed
    materialization = result.get_asset_materialization_events()[0]
    metadata = materialization.event_specific_data.materialization.metadata
    stage_names = metadata["stage_names"].value
    assert stage_names == [
        "prepare",
        "generation",
        "interpretation",
        "execution",
        "validation",
        "decision",
        "exception",
        "collation",
    ]
    stages = metadata["workbook_stages"].data
    assert len(stages) == 3
    assert all(stage["validation"]["status"] == "passed" for stage in stages)
    assert all(
        stage["decision"]["status"] == "prototype_auto_accepted" for stage in stages
    )
    assert all(
        stage["exception"] == {"required": False, "issues": []} for stage in stages
    )
    assert metadata["collation_report"].data["rowCount"] == 729


def test_product_prototype_live_evidence_dagster_job_passes() -> None:
    definitions = build_definitions(project_root=PROJECT)
    result = definitions.resolve_job_def(
        "product_prototype_live_evidence_job"
    ).execute_in_process()
    assert result.success
    assert {
        event.asset_key.to_user_string()
        for event in result.get_asset_materialization_events()
    } == {"product_prototype_live_evidence"}
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].passed


def test_product_prototype_dagster_job_materializes_and_passes_check(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["npm", "run", "build"], cwd=PROJECT, check=True, capture_output=True
    )
    definitions = build_definitions(
        project_root=PROJECT, repository_root=tmp_path / "repository"
    )
    result = definitions.resolve_job_def(
        "product_prototype_replay_job"
    ).execute_in_process()
    assert result.success
    materializations = result.get_asset_materialization_events()
    assert {event.asset_key.to_user_string() for event in materializations} == {
        "product_prototype_replay"
    }
    metadata = materializations[0].event_specific_data.materialization.metadata
    assert metadata["accepted_workbooks"].value == 5
    assert metadata["exception_workbooks"].value == 0
    assert metadata["canonical_observations"].value == 1215
    assert len(metadata["workbooks"].data) == 5
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].passed


def test_product_prototype_age_dagster_job_materializes_and_passes_check(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["npm", "run", "build"], cwd=PROJECT, check=True, capture_output=True
    )
    definitions = build_definitions(
        project_root=PROJECT, repository_root=tmp_path / "repository"
    )
    result = definitions.resolve_job_def(
        "product_prototype_age_replay_job"
    ).execute_in_process()
    assert result.success
    materializations = result.get_asset_materialization_events()
    assert {event.asset_key.to_user_string() for event in materializations} == {
        "product_prototype_age_replay"
    }
    metadata = materializations[0].event_specific_data.materialization.metadata
    assert metadata["accepted_workbooks"].value == 5
    assert metadata["exception_workbooks"].value == 0
    assert metadata["raw_observations"].value == 6732
    assert metadata["excluded_auxiliary_observations"].value == 1467
    assert metadata["canonical_observations"].value == 5265
    assert len(metadata["workbooks"].data) == 5
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].passed


def test_product_prototype_country_dagster_job_materializes_and_passes_check(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["npm", "run", "build"], cwd=PROJECT, check=True, capture_output=True
    )
    definitions = build_definitions(
        project_root=PROJECT, repository_root=tmp_path / "repository"
    )
    result = definitions.resolve_job_def(
        "product_prototype_country_replay_job"
    ).execute_in_process()
    assert result.success
    materializations = result.get_asset_materialization_events()
    assert {event.asset_key.to_user_string() for event in materializations} == {
        "product_prototype_country_replay"
    }
    metadata = materializations[0].event_specific_data.materialization.metadata
    assert metadata["accepted_workbooks"].value == 5
    assert metadata["exception_workbooks"].value == 0
    assert metadata["raw_observations"].value == 1709
    assert metadata["canonical_observations"].value == 1709
    assert metadata["prisoner_count_observations"].value == 1539
    assert metadata["imprisonment_rate_observations"].value == 170
    assert len(metadata["workbooks"].data) == 5
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].passed


@pytest.mark.parametrize(
    ("asset", "expected_count"),
    [
        ("offence", 2556),
        ("charge", 2538),
    ],
)
def test_product_prototype_offence_pair_dagster_jobs_materialize_and_pass_checks(
    tmp_path: Path,
    asset: str,
    expected_count: int,
) -> None:
    subprocess.run(
        ["npm", "run", "build"], cwd=PROJECT, check=True, capture_output=True
    )
    definitions = build_definitions(
        project_root=PROJECT, repository_root=tmp_path / "repository"
    )
    result = definitions.resolve_job_def(
        f"product_prototype_{asset}_replay_job"
    ).execute_in_process()
    assert result.success
    materializations = result.get_asset_materialization_events()
    assert {event.asset_key.to_user_string() for event in materializations} == {
        f"product_prototype_{asset}_replay"
    }
    metadata = materializations[0].event_specific_data.materialization.metadata
    assert metadata["accepted_workbooks"].value == 5
    assert metadata["exception_workbooks"].value == 0
    assert metadata["raw_observations"].value == expected_count
    assert metadata["canonical_observations"].value == expected_count
    assert metadata["published_total_observations"].value == 45
    assert len(metadata["workbooks"].data) == 5
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].passed


@pytest.mark.timeout(120)
def test_large_batch_dagster_asset_materializes_and_passes_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(
        ["npm", "run", "build"], cwd=PROJECT, check=True, capture_output=True
    )
    spec = next(
        item for item in LARGE_BATCH_REGISTRY.entries if item.family_id == "table-32"
    )
    definitions = build_definitions(
        project_root=PROJECT, repository_root=tmp_path / "repository"
    )
    result = definitions.resolve_job_def(spec.dagster_job).execute_in_process()
    assert result.success
    materializations = result.get_asset_materialization_events()
    assert {event.asset_key.to_user_string() for event in materializations} == {
        spec.dagster_asset
    }
    metadata = materializations[0].event_specific_data.materialization.metadata
    assert metadata["batch_id"].value == LARGE_BATCH_REGISTRY.batch_id
    assert metadata["accepted_workbooks"].value == 5
    assert metadata["exception_workbooks"].value == 0
    assert metadata["canonical_observations"].value == 693
    assert metadata["provider_calls"].value == 0
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].passed

    output_root = PROJECT / ".product-prototype" / spec.output_directory
    run_path = output_root / "run.json"
    original_run = run_path.read_bytes()
    runtime = TidyRuntimeResource(
        project_root=str(PROJECT),
        repository_root=str(tmp_path / "repository"),
    )
    monkeypatch.setattr(
        dagster_defs_module,
        "verify_large_batch_reproduction",
        lambda *_args: {},
    )
    try:
        for flag in (
            "historicalReplayIsAcceptanceAuthority",
            "trainingEligibility",
        ):
            unsafe_run = json.loads(original_run)
            unsafe_run[flag] = True
            run_path.write_text(json.dumps(unsafe_run))
            assert not _check_large_batch_cohort(
                runtime, spec, LARGE_BATCH_REGISTRY.batch_id
            ).passed
    finally:
        run_path.write_bytes(original_run)


def test_run_rejects_recipe_revision_changed_after_dispatch(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    definitions = build_definitions(
        project_root=PROJECT, repository_root=repository_root
    )
    catalog = discover_work_units(PROJECT)
    unit = catalog.units[0]
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    with DagsterInstance.local_temp(str(instance_dir)) as instance:
        instance.add_dynamic_partitions(WORK_UNIT_PARTITIONS.name, [unit.work_unit_id])
        with pytest.raises(Exception, match="Recipe revision changed"):
            definitions.resolve_job_def(
                "project_provider_free_work_unit"
            ).execute_in_process(
                instance=instance,
                partition_key=unit.work_unit_id,
                tags={
                    EXPECTED_RECIPE_TAG: domain_digest(
                        "test.recipe-revision/v1", {"revision": "stale"}
                    ),
                    EXPECTED_CATALOG_TAG: catalog.catalog_digest,
                },
            )
    repository = LocalArtifactRepository(repository_root)
    assert repository.get_pointer(f"m4/inputs/{unit.work_unit_id}") is None


def test_job_materializes_catalog_and_executes_all_immutable_gate_checks(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    definitions = build_definitions(
        project_root=PROJECT, repository_root=repository_root
    )
    unit = discover_work_units(PROJECT).units[0]
    instance_dir = tmp_path / "instance"
    instance_dir.mkdir()
    with DagsterInstance.local_temp(str(instance_dir)) as instance:
        instance.add_dynamic_partitions(WORK_UNIT_PARTITIONS.name, [unit.work_unit_id])
        catalog = discover_work_units(PROJECT)
        result = definitions.resolve_job_def(
            "project_provider_free_work_unit"
        ).execute_in_process(
            instance=instance,
            partition_key=unit.work_unit_id,
            tags={
                EXPECTED_RECIPE_TAG: unit.recipe_digest,
                EXPECTED_CATALOG_TAG: catalog.catalog_digest,
            },
        )
    assert result.success
    materialized = {
        event.asset_key.to_user_string()
        for event in result.get_asset_materialization_events()
    }
    assert "source_catalog_snapshot" in materialized
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 3
    assert all(evaluation.passed for evaluation in evaluations)
    repository = LocalArtifactRepository(repository_root)
    gates = [
        get_gate_result(repository, name, unit.work_unit_id, unit.recipe_digest)
        for name in GATE_NAMES
    ]
    assert all(gate.passed for gate in gates)
    assert len({gate.content_digest for gate in gates}) == 3
