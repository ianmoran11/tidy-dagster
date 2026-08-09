from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from dagster import DagsterInstance, Definitions, build_sensor_context

from tidy_orchestrator.artifacts import LocalArtifactRepository, domain_digest
from tidy_orchestrator.dagster_defs import (
    EXPECTED_CATALOG_TAG,
    EXPECTED_RECIPE_TAG,
    WORK_UNIT_PARTITIONS,
    TidyRuntimeResource,
    active_work_unit_projection,
    build_definitions,
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
