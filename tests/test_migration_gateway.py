from __future__ import annotations

import copy
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema.validators import validator_for

from tidy_orchestrator.artifacts import (
    canonical_json_bytes,
    domain_digest,
    sha256_digest,
)
from tidy_orchestrator.migration_gateway import (
    MigrationSourceBinding,
    MigrationWorkerGateway,
    _strict_json_bytes,
    actual_migration_worker_gateway,
    persist_imported_legacy_approval_snapshot,
    persist_imported_recipe_digest_verification,
)
from tidy_orchestrator.migration_import import (
    CommittedFilesystemBlobStore,
    FixtureImportAuthorization,
    MigrationImporter,
    MigrationRecordConflict,
    MigrationRepository,
)
from tidy_orchestrator.source_export import (
    StorageProbe,
    build_inventory,
    freeze_snapshot,
    load_policy,
)
from tidy_orchestrator.worker import GatewayConfig, GatewayInput, WorkerGatewayError

PROJECT = Path(__file__).parents[1]
FIXED_TIME = "2026-08-11T15:00:00Z"


def _policy(tmp_path: Path) -> Path:
    value = {
        "schemaVersion": "tidy.source-export-policy/v1",
        "policyId": "migration-gateway-fixture-policy",
        "sourceSystem": "phase-b-fixture",
        "limits": {
            "maxEntries": 10,
            "maxFileBytes": 1024 * 1024,
            "maxJsonScanBytes": 1024 * 1024,
            "maxJsonDepth": 32,
            "maxEmbeddedRecordsPerFile": 100,
        },
        "rules": [
            {
                "id": "approval-registry",
                "priority": 100,
                "entryTypes": ["file"],
                "basenameGlobs": ["approvals.json"],
                "disposition": "import",
                "artifactClass": "approval-registry",
            },
            {
                "id": "recipe",
                "priority": 90,
                "entryTypes": ["file"],
                "basenameGlobs": ["*.recipe.json"],
                "disposition": "import",
                "artifactClass": "recipe-evidence",
            },
        ],
        "fallbackFile": {
            "ruleId": "fixture-excluded",
            "disposition": "exclude",
            "artifactClass": "unselected-source-file",
        },
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(value))
    return path


def _fixture(
    tmp_path: Path, *, repository_fault=None
) -> tuple[
    dict,
    CommittedFilesystemBlobStore,
    MigrationRepository,
    dict[str, dict],
]:
    source = tmp_path / "source"
    source.mkdir(parents=True)
    (source / "approvals.json").write_text(
        json.dumps(
            {
                "version": 1,
                "approvals": [
                    {
                        "assetId": "asset-one",
                        "sheetName": "Table 1",
                        "approvedAt": "2026-01-01T00:00:00.000Z",
                    }
                ],
            }
        )
    )
    (source / "candidate.recipe.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "sheet": "Table 1",
                "tables": [
                    {
                        "name": "table_1",
                        "values": {
                            "name": "value",
                            "cells": {"range": "R2C2:R3C3"},
                        },
                        "headers": [
                            {
                                "name": "row",
                                "direction": "W",
                                "cells": {"range": "R2C1:R3C1"},
                            }
                        ],
                    }
                ],
            }
        )
    )
    policy = load_policy(_policy(tmp_path))
    inventory = build_inventory(
        source_root=source,
        source_root_id="migration-gateway-fixture-source",
        destination_root=tmp_path / "capacity-target",
        destination_id="migration-gateway-fixture-cas",
        policy=policy,
        storage_probe=lambda _path: StorageProbe(
            total_bytes=100 * 1024**3,
            used_bytes=10 * 1024**3,
            free_bytes=90 * 1024**3,
            device_id=42,
        ),
    )
    snapshot = freeze_snapshot(inventory, frozen_at=FIXED_TIME)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(canonical_json_bytes(snapshot) + b"\n")
    snapshot_path.chmod(0o600)
    blobs = CommittedFilesystemBlobStore(tmp_path / "blobs")
    metadata = MigrationRepository(
        tmp_path / "metadata", fault_injector=repository_fault
    )
    importer = MigrationImporter(
        snapshot_path=snapshot_path,
        source_root=source,
        metadata=metadata,
        blobs=blobs,
        authorization=FixtureImportAuthorization.create(
            snapshot=snapshot, source_root=source
        ),
        recorded_at=FIXED_TIME,
    )
    assert importer.run().complete is True
    items = {item["relativePath"]: item for item in snapshot["inventory"]["items"]}
    return snapshot, blobs, metadata, items


@pytest.fixture(scope="session")
def migration_command() -> tuple[str, str]:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node is required for migration gateway executable tests")
    bundle = PROJECT / "dist/tidy-migration-worker.cjs"
    if not bundle.is_file():
        subprocess.run(
            ["npm", "run", "build"],
            cwd=PROJECT,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    assert bundle.is_file()
    return str(Path(node).resolve()), str(bundle.resolve())


def _gateway(
    metadata: MigrationRepository,
    blobs: CommittedFilesystemBlobStore,
    migration_command: tuple[str, str],
    *,
    sandbox_mode: str = "insecure-test-only",
    fault_injector=None,
) -> MigrationWorkerGateway:
    node = Path(migration_command[0])
    return MigrationWorkerGateway(
        metadata,
        blobs,
        GatewayConfig(
            command=migration_command,
            cwd=PROJECT,
            sandbox_mode=sandbox_mode,
            sandbox_read_roots=(PROJECT, node.parent)
            if sandbox_mode == "macos-production"
            else (),
            wall_timeout_seconds=15,
            max_output_bytes=8 * 1024 * 1024,
            max_output_file_bytes=8 * 1024 * 1024,
            max_output_files=4,
        ),
        fault_injector=fault_injector,
    )


def _input_and_binding(
    metadata: MigrationRepository,
    snapshot_digest: str,
    path: str,
    name: str,
) -> tuple[GatewayInput, MigrationSourceBinding, dict]:
    record = metadata.get_item(snapshot_digest, path)
    assert record is not None
    item = GatewayInput(
        name=name,
        content_digest=record["contentDigest"],
        relative_path=Path(path).name,
        declared_byte_length=record["byteLength"],
    )
    return item, MigrationSourceBinding.from_import_record(record), record


def _validate_contract(filename: str, value: dict) -> None:
    schema = json.loads((PROJECT / "contracts/import/v1" / filename).read_text())
    validator_for(schema).check_schema(schema)
    validator_for(schema)(schema).validate(value)


def test_actual_gateway_persists_approval_digests_and_recipe_revision(
    tmp_path: Path, migration_command: tuple[str, str]
) -> None:
    snapshot, blobs, metadata, source_items = _fixture(tmp_path)
    gateway = _gateway(metadata, blobs, migration_command)
    producer = json.loads(gateway._producer_manifest_bytes())
    logical_paths = {entry["logicalPath"] for entry in producer["files"]}
    assert {
        "command-file-1:dist/tidy-migration-worker.cjs",
        "apps/migration-worker/src/cli.ts",
        "apps/migration-worker/src/protocol.ts",
        "apps/domain-worker/src/migration/historicalDigestRecord.ts",
        "apps/domain-worker/src/recipe/schema.ts",
        "apps/domain-worker/src/address.ts",
        "contracts/migration-worker/v1/request.schema.json",
        "fixtures/migration/digest-record-v1.json",
        "package-lock.json",
        "package.json",
        "tsconfig.json",
    }.issubset(logical_paths)
    assert producer["runtime"]["version"] == "v24.7.0"
    snapshot_digest = snapshot["snapshotDigest"]

    _approval_input, _approval_binding, approval_import = _input_and_binding(
        metadata, snapshot_digest, "approvals.json", "registry"
    )
    approval_result = persist_imported_legacy_approval_snapshot(
        gateway=gateway,
        source_item=source_items["approvals.json"],
        import_record=approval_import,
        frozen_at=FIXED_TIME,
    )
    approval = approval_result.execution
    approval_artifact = approval.outputs[0].artifact
    assert approval_artifact["recordCount"] == 1
    assert approval_artifact["source"]["importRecordId"] == approval_import["recordId"]
    blobs.verify(
        approval.outputs[0].content_digest,
        approval.outputs[0].record["byteLength"],
    )
    approval_snapshot = approval_result.approval_snapshot
    assert approval_snapshot["verifierIsolationMode"] == "insecure-test-only"
    assert approval_snapshot["networkIsolationEnforced"] is False
    assert (
        approval_snapshot["rows"][0]["sourceRecordDigest"]
        == (approval_artifact["records"][0]["sourceRecordDigest"])
    )

    _recipe_input, _recipe_binding, recipe_import = _input_and_binding(
        metadata, snapshot_digest, "candidate.recipe.json", "recipe"
    )
    recipe_result = persist_imported_recipe_digest_verification(
        gateway=gateway,
        import_record=recipe_import,
        declared_recipe_digest="sha256:" + "0" * 64,
    )
    recipe = recipe_result.execution
    artifact = recipe.outputs[0].artifact
    assert artifact["sheetName"] == "Table 1"
    assert artifact["digestMatches"] is False
    assert artifact["active"] is False
    assert artifact["trainingEligible"] is False
    assert recipe.outputs[0].record["active"] is False
    assert recipe.outputs[0].record["trainingEligible"] is False
    assert recipe.outputs[0].record["networkIsolationEnforced"] is False
    assert recipe_result.verification["verificationAuthority"] == (
        "fixture-non-authoritative"
    )
    assert (
        metadata.get_typed_record(
            record_id=recipe_result.verification["verificationId"],
            record_type=recipe_result.verification["schemaVersion"],
        )
        == recipe_result.verification
    )

    repeated = gateway.parse_imported_recipe(
        recipe_import,
        declared_recipe_digest="sha256:" + "0" * 64,
    )
    assert repeated.reproduction_key == recipe.reproduction_key
    assert repeated.output_fingerprint == recipe.output_fingerprint
    assert repeated.derivation == recipe.derivation

    outputs = metadata.list_migration_worker_outputs(blob_store=blobs)
    assert len(outputs) == 2
    for output in outputs:
        _validate_contract("migration-worker-output.schema.json", output)
    for execution in (approval, recipe):
        derivation = metadata.get_migration_worker_derivation(
            execution.derivation["derivationId"]
        )
        _validate_contract("migration-worker-derivation.schema.json", derivation)
        assert metadata.get_migration_worker_reproduction(
            execution.reproduction_key
        ) == {
            "reproductionKey": execution.reproduction_key,
            "outputFingerprint": execution.output_fingerprint,
            "derivationId": execution.derivation["derivationId"],
        }

    divergent_bytes = b"{}"
    divergent_digest = sha256_digest(divergent_bytes)
    blobs.publish_bytes(
        divergent_bytes,
        expected_digest=divergent_digest,
        expected_length=len(divergent_bytes),
    )
    divergent_semantic = {
        key: value
        for key, value in recipe.derivation.items()
        if key not in {"schemaVersion", "derivationId", "orderedOutputDigests"}
    }
    divergent_semantic["orderedOutputDigests"] = [divergent_digest]
    divergent_derivation = {
        "schemaVersion": "tidy.migration-worker-derivation/v1",
        "derivationId": domain_digest("tidy.derivation/v1", divergent_semantic),
        **divergent_semantic,
    }
    divergent_fingerprint = domain_digest(
        "tidy.output-set/v1", [["recipe-revision.json", divergent_digest]]
    )
    divergent_record_semantic = {
        **{
            key: value
            for key, value in recipe.outputs[0].record.items()
            if key
            not in {
                "recordId",
                "derivationId",
                "outputFingerprint",
                "contentDigest",
                "byteLength",
                "storageUri",
            }
        },
        "derivationId": divergent_derivation["derivationId"],
        "outputFingerprint": divergent_fingerprint,
        "contentDigest": divergent_digest,
        "byteLength": len(divergent_bytes),
        "storageUri": blobs.storage_uri(divergent_digest),
    }
    divergent_record = {
        **divergent_record_semantic,
        "recordId": domain_digest(
            "tidy.migration-worker-output/v1", divergent_record_semantic
        ),
    }
    with pytest.raises(MigrationRecordConflict, match="changed outputs"):
        metadata.publish_migration_worker_bundle(
            outputs=[divergent_record],
            derivation=divergent_derivation,
            reproduction_key=recipe.reproduction_key,
            output_fingerprint=divergent_fingerprint,
            blob_store=blobs,
        )
    assert len(metadata.list_migration_worker_outputs(blob_store=blobs)) == 2

    with sqlite3.connect(metadata.database) as connection:
        row = connection.execute(
            "SELECT record_id, record_json FROM migration_worker_outputs "
            "ORDER BY record_id LIMIT 1"
        ).fetchone()
        tampered = json.loads(row[1])
        tampered["active"] = True
        connection.execute(
            "UPDATE migration_worker_outputs SET record_json=? WHERE record_id=?",
            (canonical_json_bytes(tampered), row[0]),
        )
        connection.commit()
    with pytest.raises(ValueError, match="active authority"):
        metadata.list_migration_worker_outputs(blob_store=blobs)


def test_gateway_rejects_schema_valid_dishonest_recipe_digest_claims(
    tmp_path: Path, migration_command: tuple[str, str]
) -> None:
    snapshot, blobs, metadata, _items = _fixture(tmp_path)
    gateway = _gateway(metadata, blobs, migration_command)
    _input, _binding, import_record = _input_and_binding(
        metadata, snapshot["snapshotDigest"], "candidate.recipe.json", "recipe"
    )
    declared = "sha256:" + "0" * 64
    execution = gateway.parse_imported_recipe(
        import_record, declared_recipe_digest=declared
    )
    honest = execution.outputs[0].artifact
    dishonest_values = []
    dropped = copy.deepcopy(honest)
    dropped["declaredRecipeDigest"] = None
    dropped["digestMatches"] = None
    dishonest_values.append(dropped)
    false_match = copy.deepcopy(honest)
    false_match["digestMatches"] = True
    dishonest_values.append(false_match)
    for artifact in dishonest_values:
        data = json.dumps(artifact, separators=(",", ":")).encode()
        descriptor = {
            "name": "recipe-revision",
            "relativePath": "recipe-revision.json",
            "contentDigest": sha256_digest(data),
            "byteLength": len(data),
        }
        with pytest.raises(WorkerGatewayError) as error:
            gateway._validate_artifacts(
                operation="parse-recipe-v01",
                verified=[(descriptor, data)],
                source_wire=honest["source"],
                declared_recipe_digest=declared,
                max_json_depth=128,
                max_json_nodes=1_000_000,
                max_records=100_000,
            )
        assert error.value.code == "INVALID_OUTPUT_ARTIFACT"
        assert error.value.category == "INTEGRITY_VIOLATION"


def test_gateway_json_parser_enforces_depth_and_catches_recursion() -> None:
    nested = b"[" * 200 + b"0" + b"]" * 200
    with pytest.raises(WorkerGatewayError) as depth_error:
        _strict_json_bytes(
            nested,
            "deep fixture",
            max_json_depth=64,
            max_json_nodes=1_000,
        )
    assert depth_error.value.code == "JSON_DEPTH_LIMIT_EXCEEDED"

    recursive = b"[" * 5_000 + b"0" + b"]" * 5_000
    with pytest.raises(WorkerGatewayError) as recursion_error:
        _strict_json_bytes(
            recursive,
            "recursive fixture",
            max_json_depth=128,
            max_json_nodes=10_000,
        )
    assert recursion_error.value.code in {
        "MALFORMED_JSON",
        "JSON_DEPTH_LIMIT_EXCEEDED",
    }


def test_gateway_rejects_source_mismatch_before_worker_authority(
    tmp_path: Path, migration_command: tuple[str, str]
) -> None:
    snapshot, blobs, metadata, _items = _fixture(tmp_path)
    gateway = _gateway(metadata, blobs, migration_command)
    item, binding, _record = _input_and_binding(
        metadata, snapshot["snapshotDigest"], "candidate.recipe.json", "recipe"
    )
    wrong = MigrationSourceBinding(
        source_snapshot_digest=binding.source_snapshot_digest,
        source_item_digest="sha256:" + "1" * 64,
        import_record_id=binding.import_record_id,
        relative_path=binding.relative_path,
    )
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(operation="parse-recipe-v01", inputs=[item], source=wrong)
    assert error.value.code == "SOURCE_BINDING_MISMATCH"
    assert metadata.list_migration_worker_outputs(blob_store=blobs) == ()


def test_bundle_metadata_is_atomic_after_durable_output_blob(
    tmp_path: Path, migration_command: tuple[str, str]
) -> None:
    def fail(point: str) -> None:
        if point == "before_migration_worker_bundle_commit":
            raise RuntimeError("injected metadata crash")

    snapshot, blobs, metadata, _items = _fixture(tmp_path, repository_fault=fail)
    gateway = _gateway(metadata, blobs, migration_command)
    item, binding, _record = _input_and_binding(
        metadata, snapshot["snapshotDigest"], "candidate.recipe.json", "recipe"
    )
    with pytest.raises(RuntimeError, match="metadata crash"):
        gateway.execute(operation="parse-recipe-v01", inputs=[item], source=binding)
    assert metadata.list_migration_worker_outputs(blob_store=blobs) == ()
    with sqlite3.connect(metadata.database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM migration_worker_derivations"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM migration_worker_reproductions"
            ).fetchone()[0]
            == 0
        )
    # Blobs intentionally precede authority, so a harmless unreferenced output
    # object remains recoverable after the injected transaction failure.
    assert len(blobs.committed_digests()) == 4


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt acceptance")
def test_actual_migration_gateway_runs_under_production_seatbelt(
    tmp_path: Path, migration_command: tuple[str, str]
) -> None:
    snapshot, blobs, metadata, items = _fixture(tmp_path)
    gateway = actual_migration_worker_gateway(metadata, blobs, PROJECT)
    result = gateway.execute(operation="health")
    assert result.outputs[0].artifact == {
        "status": "ok",
        "protocolVersion": "tidy.migration-worker/v1",
    }
    assert result.outputs[0].record["isolationMode"] == "macos-production"
    assert result.outputs[0].record["networkIsolationEnforced"] is True
    import_record = metadata.get_item(snapshot["snapshotDigest"], "approvals.json")
    assert import_record is not None
    approval = persist_imported_legacy_approval_snapshot(
        gateway=gateway,
        source_item=items["approvals.json"],
        import_record=import_record,
        frozen_at=FIXED_TIME,
    )
    assert approval.approval_snapshot["verifierIsolationMode"] == ("macos-production")
    assert approval.approval_snapshot["networkIsolationEnforced"] is True
    recipe_import = metadata.get_item(
        snapshot["snapshotDigest"], "candidate.recipe.json"
    )
    assert recipe_import is not None
    recipe = persist_imported_recipe_digest_verification(
        gateway=gateway,
        import_record=recipe_import,
        declared_recipe_digest="sha256:" + "0" * 64,
    )
    assert recipe.verification["verificationAuthority"] == "gateway-production"
    assert recipe.verification["networkIsolationEnforced"] is True
