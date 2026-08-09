from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from dagster import (
    AssetCheckEvaluation,
    AssetCheckKey,
    AssetKey,
    AssetMaterialization,
    DagsterInstance,
    Definitions,
)

from tidy_orchestrator.artifacts import LocalArtifactRepository
from tidy_orchestrator.dagster_defs import (
    EXPECTED_CATALOG_TAG,
    EXPECTED_RECIPE_TAG,
    WORK_UNIT_PARTITIONS,
    build_definitions,
)
from tidy_orchestrator.work_units import (
    GATE_NAMES,
    discover_work_units,
    get_gate_result,
    reconstruct_projection,
)

PROJECT = Path(__file__).parents[1]


@contextmanager
def persistent_instance(home: Path):
    home.mkdir(parents=True, exist_ok=True)
    shutil.copy(PROJECT / ".dagster/dagster.yaml.example", home / "dagster.yaml")
    previous = os.environ.get("DAGSTER_HOME")
    os.environ["DAGSTER_HOME"] = str(home)
    instance = DagsterInstance.get()
    try:
        assert instance.is_persistent
        yield instance
    finally:
        instance.dispose()
        if previous is None:
            os.environ.pop("DAGSTER_HOME", None)
        else:
            os.environ["DAGSTER_HOME"] = previous


@pytest.mark.persistent
def test_all_units_persist_and_reconstruct_after_dagster_metadata_deletion(
    tmp_path: Path,
) -> None:
    home = tmp_path / "dagster-home"
    repository_root = tmp_path / "authoritative-repository"
    catalog = discover_work_units(PROJECT)
    definitions = build_definitions(
        project_root=PROJECT, repository_root=repository_root
    )
    Definitions.validate_loadable(definitions)
    job = definitions.resolve_job_def("project_provider_free_work_unit")
    run_ids: list[str] = []

    with persistent_instance(home) as instance:
        keys = [unit.work_unit_id for unit in catalog.units]
        instance.add_dynamic_partitions(WORK_UNIT_PARTITIONS.name, keys)
        for unit in catalog.units:
            result = job.execute_in_process(
                instance=instance,
                partition_key=unit.work_unit_id,
                tags={
                    EXPECTED_RECIPE_TAG: unit.recipe_digest,
                    EXPECTED_CATALOG_TAG: catalog.catalog_digest,
                },
            )
            assert result.success
            assert len(result.get_asset_check_evaluations()) == 3
            assert all(item.passed for item in result.get_asset_check_evaluations())
            run_ids.append(result.run_id)

    repository = LocalArtifactRepository(repository_root)
    catalog_pointer = repository.get_pointer("m4/active-catalog")
    assert catalog_pointer is not None
    before: dict[str, dict[str, str]] = {}
    for unit in catalog.units:
        projection = reconstruct_projection(repository, unit.work_unit_id)
        execution_pointer = repository.get_pointer(f"m4/execution/{unit.work_unit_id}")
        assert execution_pointer is not None
        execution = json.loads(
            repository.read_bytes_verified(execution_pointer.target_id)
        )
        before[unit.work_unit_id] = {
            "projection": projection.content_digest,
            "execution": execution_pointer.target_id,
            "derivation": execution["derivationId"],
            "fingerprint": execution["outputFingerprint"],
        }
        assert all(
            get_gate_result(
                repository, gate, unit.work_unit_id, unit.recipe_digest
            ).passed
            for gate in GATE_NAMES
        )

    with persistent_instance(home) as reopened:
        assert all(
            reopened.has_dynamic_partition(WORK_UNIT_PARTITIONS.name, unit.work_unit_id)
            for unit in catalog.units
        )
        assert all(reopened.get_run_by_id(run_id) is not None for run_id in run_ids)
        for asset_name in (
            "source_catalog_snapshot",
            "verified_fixture_inputs_index",
            "recipe_execution_evidence_index",
            "active_work_unit_projection",
        ):
            assert reopened.get_latest_materialization_event(AssetKey(asset_name))

    shutil.rmtree(home)
    with persistent_instance(home) as reconstructed:
        keys = [unit.work_unit_id for unit in catalog.units]
        assert reconstructed.get_dynamic_partitions(WORK_UNIT_PARTITIONS.name) == []
        reconstructed.add_dynamic_partitions(WORK_UNIT_PARTITIONS.name, keys)
        reconstructed.report_runless_asset_event(
            AssetMaterialization(
                asset_key=AssetKey("source_catalog_snapshot"),
                metadata={
                    "index_digest": catalog_pointer.target_id,
                    "status": "reconstructed-from-authoritative-repository",
                },
            )
        )
        for unit in catalog.units:
            pointers = {
                "verified_fixture_inputs_index": repository.get_pointer(
                    f"m4/inputs/{unit.work_unit_id}"
                ),
                "recipe_execution_evidence_index": repository.get_pointer(
                    f"m4/execution/{unit.work_unit_id}"
                ),
                "active_work_unit_projection": repository.get_pointer(
                    f"m4/projection/{unit.work_unit_id}"
                ),
            }
            assert all(pointer is not None for pointer in pointers.values())
            for asset_name, pointer in pointers.items():
                assert pointer is not None
                reconstructed.report_runless_asset_event(
                    AssetMaterialization(
                        asset_key=AssetKey(asset_name),
                        partition=unit.work_unit_id,
                        metadata={
                            "index_digest": pointer.target_id,
                            "status": "reconstructed-from-authoritative-repository",
                        },
                    )
                )
            check_specs = (
                (
                    "verified_fixture_inputs_index",
                    "content_hash_and_provenance",
                    "input-provenance",
                ),
                (
                    "recipe_execution_evidence_index",
                    "frozen_reference_parity",
                    "frozen-reference-execution",
                ),
                (
                    "active_work_unit_projection",
                    "authoritative_reconstruction",
                    "authoritative-reconstruction",
                ),
            )
            for asset_name, check_name, gate_name in check_specs:
                gate = get_gate_result(
                    repository,
                    gate_name,
                    unit.work_unit_id,
                    unit.recipe_digest,
                )
                reconstructed.report_runless_asset_event(
                    AssetCheckEvaluation(
                        asset_key=AssetKey(asset_name),
                        check_name=check_name,
                        partition=unit.work_unit_id,
                        passed=gate.passed,
                        metadata={
                            "gate_digest": gate.content_digest,
                            "subject_digest": gate.subject_digest,
                            "status": "mirrored-from-authoritative-gate",
                        },
                    )
                )
                latest = reconstructed.get_latest_asset_check_evaluation_record(
                    AssetCheckKey(AssetKey(asset_name), check_name)
                )
                assert latest is not None
                assert latest.event.asset_check_evaluation is not None
                assert latest.event.asset_check_evaluation.passed

    assert sorted(
        reconstructed_key.work_unit_id
        for reconstructed_key in (
            reconstruct_projection(repository, unit.work_unit_id)
            for unit in catalog.units
        )
    ) == sorted(unit.work_unit_id for unit in catalog.units)
    for unit in catalog.units:
        projection = reconstruct_projection(repository, unit.work_unit_id)
        execution_pointer = repository.get_pointer(f"m4/execution/{unit.work_unit_id}")
        assert execution_pointer is not None
        execution = json.loads(
            repository.read_bytes_verified(execution_pointer.target_id)
        )
        assert projection.content_digest == before[unit.work_unit_id]["projection"]
        assert execution_pointer.target_id == before[unit.work_unit_id]["execution"]
        assert execution["derivationId"] == before[unit.work_unit_id]["derivation"]
        assert (
            execution["outputFingerprint"] == before[unit.work_unit_id]["fingerprint"]
        )
