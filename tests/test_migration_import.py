from __future__ import annotations

import copy
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from tidy_orchestrator.artifacts import canonical_json_bytes
from tidy_orchestrator.migration_evidence import (
    persist_conservative_evidence_dispositions,
    reconcile_conservative_evidence,
)
from tidy_orchestrator.migration_import import (
    BlobIntegrityError,
    CommittedFilesystemBlobStore,
    FixtureImportAuthorization,
    ImportAuthorizationError,
    IncompleteMigration,
    MigrationImporter,
    MigrationImportError,
    MigrationRecordConflict,
    MigrationRepository,
    SourceItemMismatch,
)
from tidy_orchestrator.source_export import (
    StorageProbe,
    build_inventory,
    freeze_snapshot,
    load_policy,
)

PROJECT = Path(__file__).parents[1]
CONTRACTS = PROJECT / "contracts/import/v1"
FIXED_TIME = "2026-08-10T08:00:00Z"


def _policy(tmp_path: Path) -> Path:
    value = {
        "schemaVersion": "tidy.source-export-policy/v1",
        "policyId": "phase-b-fixture-policy",
        "sourceSystem": "phase-b-fixture",
        "limits": {
            "maxEntries": 100,
            "maxFileBytes": 1024 * 1024,
            "maxJsonScanBytes": 1024 * 1024,
            "maxJsonDepth": 16,
            "maxEmbeddedRecordsPerFile": 100,
        },
        "rules": [
            {
                "id": "excluded-dependency",
                "priority": 100,
                "entryTypes": ["directory"],
                "directoryNames": ["node_modules"],
                "disposition": "exclude",
                "artifactClass": "development-subtree",
            },
            {
                "id": "excluded-generated-symlink",
                "priority": 95,
                "entryTypes": ["symlink"],
                "basenameGlobs": ["ltmain.sh"],
                "disposition": "exclude",
                "artifactClass": "generated-development-symlink",
            },
            {
                "id": "approval-registry",
                "priority": 92,
                "entryTypes": ["file"],
                "basenameGlobs": ["approvals.json"],
                "disposition": "import",
                "artifactClass": "approval-registry",
            },
            {
                "id": "workbook",
                "priority": 90,
                "entryTypes": ["file"],
                "suffixes": [".xlsx"],
                "disposition": "import",
                "artifactClass": "workbook",
            },
            {
                "id": "model",
                "priority": 85,
                "entryTypes": ["file"],
                "suffixes": [".pkl"],
                "disposition": "import",
                "artifactClass": "model-binary",
            },
            {
                "id": "generation-json",
                "priority": 82,
                "entryTypes": ["file"],
                "basenameGlobs": ["*result*.json"],
                "disposition": "import",
                "artifactClass": "generation-json-evidence",
            },
            {
                "id": "recipe",
                "priority": 80,
                "entryTypes": ["file"],
                "basenameGlobs": ["*recipe*.json"],
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


def _frozen_fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    source = tmp_path / "source"
    (source / "node_modules").mkdir(parents=True)
    shared = b"PK\x03\x04shared-workbook"
    (source / "a.xlsx").write_bytes(shared)
    (source / "approvals.json").write_text(
        json.dumps(
            {
                "version": 1,
                "approvals": [
                    {
                        "assetId": "fixture-asset",
                        "sheetName": "Table 1",
                        "approvedAt": "",
                    }
                ],
            }
        )
    )
    (source / "b.xlsx").write_bytes(shared)
    (source / "candidate.recipe.json").write_text("{malformed")
    (source / "legacy-model.pkl").write_bytes(b"not-loaded-pickle-evidence")
    (source / "provider-result.json").write_text(
        json.dumps({"prompt": "restricted prompt", "response": "restricted response"})
    )
    (source / "notes.txt").write_text("excluded but verified")
    (source / "node_modules/opaque.txt").write_text("not traversed")
    (source / "ltmain.sh").symlink_to("generated/missing-tool")
    policy = load_policy(_policy(tmp_path))
    result = build_inventory(
        source_root=source,
        source_root_id="phase-b-fixture-source",
        destination_root=tmp_path / "capacity-target",
        destination_id="phase-b-fixture-blob-store",
        policy=policy,
        storage_probe=lambda _path: StorageProbe(
            total_bytes=100 * 1024**3,
            used_bytes=10 * 1024**3,
            free_bytes=90 * 1024**3,
            device_id=42,
        ),
    )
    snapshot = freeze_snapshot(result, frozen_at=FIXED_TIME)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(canonical_json_bytes(snapshot) + b"\n")
    snapshot_path.chmod(0o600)
    return source, snapshot_path, snapshot


def _importer(
    tmp_path: Path,
    *,
    repository_fault=None,
    importer_fault=None,
    authorization_items: int = 1000,
):
    source, snapshot_path, snapshot = _frozen_fixture(tmp_path)
    blobs = CommittedFilesystemBlobStore(tmp_path / "blob-root")
    metadata = MigrationRepository(
        tmp_path / "metadata-root",
        fault_injector=repository_fault,
    )
    authorization = FixtureImportAuthorization.create(
        snapshot=snapshot,
        source_root=source,
        max_items=authorization_items,
    )
    importer = MigrationImporter(
        snapshot_path=snapshot_path,
        source_root=source,
        metadata=metadata,
        blobs=blobs,
        authorization=authorization,
        recorded_at=FIXED_TIME,
        fault_injector=importer_fault,
    )
    return source, snapshot_path, snapshot, blobs, metadata, importer


def _schemas() -> tuple[dict[str, dict], Registry]:
    schemas = {
        path.name: json.loads(path.read_text())
        for path in CONTRACTS.glob("*.schema.json")
    }
    registry = Registry()
    for schema in schemas.values():
        validator_for(schema).check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return schemas, registry


def _validate(schema: dict, registry: Registry, value) -> None:
    validator_for(schema)(schema, registry=registry).validate(value)


def test_fixture_import_is_split_idempotent_and_reconciled(tmp_path: Path) -> None:
    _source, _snapshot_path, snapshot, blobs, metadata, importer = _importer(tmp_path)
    assert metadata.database.parent != blobs.root
    partial = importer.run(max_new_items=1)
    assert partial.complete is False
    assert partial.recorded_items == 1
    with pytest.raises(IncompleteMigration):
        importer.reconcile()

    completed = importer.run()
    assert completed.complete is True
    assert completed.recorded_items == 9
    repeated = importer.run()
    assert repeated == completed

    items = metadata.list_items(snapshot["snapshotDigest"])
    aliases = metadata.list_aliases(snapshot["snapshotDigest"])
    contents = metadata.list_contents()
    assert [item["relativePath"] for item in items] == sorted(
        item["relativePath"] for item in items
    )
    assert len(items) == len(aliases) == 9
    assert Counter(item["finalState"] for item in items) == {
        "imported": 4,
        "duplicate-alias": 1,
        "quarantined": 1,
        "excluded": 3,
    }
    by_path = {item["relativePath"]: item for item in items}
    assert by_path["a.xlsx"]["contentDigest"] == by_path["b.xlsx"]["contentDigest"]
    assert by_path["a.xlsx"]["blobStored"] is True
    assert by_path["b.xlsx"]["blobStored"] is True
    assert by_path["approvals.json"]["classification"] == "restricted"
    assert by_path["candidate.recipe.json"]["classification"] == "restricted"
    assert by_path["legacy-model.pkl"]["classification"] == "restricted"
    assert by_path["provider-result.json"]["classification"] == "restricted"
    assert len(contents) == 5
    assert len(blobs.committed_digests()) == 6  # snapshot + five unique source objects

    report = importer.reconcile()
    assert report["contentReconciliationStatus"] == "complete"
    assert report["phaseBStatus"] == "core-content-complete-semantic-import-pending"
    assert report["stateCounts"] == {
        "duplicate-alias": 1,
        "excluded": 3,
        "imported": 4,
        "quarantined": 1,
    }
    assert report["uniqueStoredObjects"] == 5
    assert len(report["mappings"]) == 9
    assert metadata.get_reconciliation(report["reportDigest"]) == report
    with pytest.raises(IncompleteMigration, match="Typed evidence differs"):
        reconcile_conservative_evidence(
            snapshot=snapshot,
            metadata=metadata,
            core_reconciliation=report,
            recorded_at=FIXED_TIME,
            actor="phase-b-fixture-interpreter",
        )

    disposition_counts = persist_conservative_evidence_dispositions(
        snapshot=snapshot,
        metadata=metadata,
        recorded_at=FIXED_TIME,
        actor="phase-b-fixture-interpreter",
    )
    assert disposition_counts == {
        "tidy.approval-registry-evidence-import/v1": 1,
        "tidy.generation-evidence-import/v1": 1,
        "tidy.model-package-disposition/v1": 1,
        "tidy.recipe-evidence-import/v1": 1,
    }
    assert (
        persist_conservative_evidence_dispositions(
            snapshot=snapshot,
            metadata=metadata,
            recorded_at=FIXED_TIME,
            actor="phase-b-fixture-interpreter",
        )
        == disposition_counts
    )
    semantic_report = reconcile_conservative_evidence(
        snapshot=snapshot,
        metadata=metadata,
        core_reconciliation=report,
        recorded_at=FIXED_TIME,
        actor="phase-b-fixture-interpreter",
    )
    assert semantic_report["status"] == (
        "conservative-dispositions-complete-full-semantic-import-pending"
    )
    assert semantic_report["sourceItemCount"] == 9
    assert semantic_report["typedSourceItemCount"] == 4
    assert semantic_report["typedRecordCount"] == 4
    assert semantic_report["outcomeCounts"] == {
        "conservative-typed-records": 4,
        "core-content-only": 5,
    }
    assert len(semantic_report["mappings"]) == 9
    assert (
        reconcile_conservative_evidence(
            snapshot=snapshot,
            metadata=metadata,
            core_reconciliation=report,
            recorded_at=FIXED_TIME,
            actor="phase-b-fixture-interpreter",
        )
        == semantic_report
    )
    typed_records = metadata.list_typed_records()
    assert len(typed_records) == 5
    approval_record = next(
        record
        for record in typed_records
        if record["schemaVersion"] == "tidy.approval-registry-evidence-import/v1"
    )
    assert approval_record["approvalAuthorityCreated"] is False
    assert approval_record["interpretationStatus"] == "not-run"
    model_record = next(
        record
        for record in typed_records
        if record["schemaVersion"] == "tidy.model-package-disposition/v1"
    )
    assert model_record["deserializationStatus"] == "not-attempted"
    generation_record = next(
        record
        for record in typed_records
        if record["schemaVersion"] == "tidy.generation-evidence-import/v1"
    )
    assert generation_record["rawEvidenceRestricted"] is True
    assert {record["kind"] for record in generation_record["embeddedRecords"]} == {
        "prompt-evidence",
        "provider-response-evidence",
    }

    registration = metadata.get_snapshot_registration(snapshot["snapshotDigest"])
    schemas, registry = _schemas()
    _validate(schemas["snapshot-registration.schema.json"], registry, registration)
    _validate(schemas["reconciliation.schema.json"], registry, report)
    _validate(
        schemas["approval-registry-evidence.schema.json"],
        registry,
        approval_record,
    )
    _validate(
        schemas["semantic-reconciliation.schema.json"],
        registry,
        semantic_report,
    )
    for item in items:
        _validate(schemas["import-item.schema.json"], registry, item)
    for alias in aliases:
        _validate(schemas["source-alias.schema.json"], registry, alias)
    for digest in blobs.committed_digests():
        marker = json.loads(
            (blobs.object_directory(digest) / "COMMITTED.json").read_text()
        )
        _validate(schemas["blob-commit.schema.json"], registry, marker)

    invalid = copy.deepcopy(items[0])
    invalid["unexpected"] = True
    with pytest.raises(ValidationError):
        _validate(schemas["import-item.schema.json"], registry, invalid)

    with sqlite3.connect(metadata.database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "pointers" not in tables


def test_snapshot_blob_before_registration_fault_is_restartable(
    tmp_path: Path,
) -> None:
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "after_snapshot_blob_before_metadata" and not fired:
            fired = True
            raise RuntimeError("injected snapshot-registration fault")

    source, snapshot_path, snapshot, blobs, metadata, importer = _importer(
        tmp_path,
        importer_fault=fault,
    )
    with pytest.raises(RuntimeError, match="snapshot-registration"):
        importer.run()
    with pytest.raises(MigrationImportError, match="not found"):
        metadata.get_snapshot_registration(snapshot["snapshotDigest"])
    assert len(blobs.committed_digests()) == 1

    resumed = MigrationImporter(
        snapshot_path=snapshot_path,
        source_root=source,
        metadata=MigrationRepository(metadata.root),
        blobs=CommittedFilesystemBlobStore(blobs.root),
        authorization=FixtureImportAuthorization.create(
            snapshot=snapshot, source_root=source
        ),
        recorded_at=FIXED_TIME,
    )
    assert resumed.run().complete is True


def test_blob_before_metadata_fault_is_restartable(tmp_path: Path) -> None:
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "after_blob_before_metadata" and not fired:
            fired = True
            raise RuntimeError("injected after-blob fault")

    source, snapshot_path, snapshot, blobs, metadata, importer = _importer(
        tmp_path,
        importer_fault=fault,
    )
    with pytest.raises(RuntimeError, match="after-blob"):
        importer.run()
    assert metadata.list_items(snapshot["snapshotDigest"]) == ()
    assert len(blobs.committed_digests()) == 2  # snapshot and first source blob

    reopened = MigrationRepository(metadata.root)
    authorization = FixtureImportAuthorization.create(
        snapshot=snapshot,
        source_root=source,
    )
    resumed = MigrationImporter(
        snapshot_path=snapshot_path,
        source_root=source,
        metadata=reopened,
        blobs=CommittedFilesystemBlobStore(blobs.root),
        authorization=authorization,
        recorded_at=FIXED_TIME,
    )
    assert resumed.run().complete is True
    assert resumed.reconcile()["sourceItemCount"] == 9
    assert len(CommittedFilesystemBlobStore(blobs.root).committed_digests()) == 6


def test_metadata_transaction_fault_rolls_back_after_blob(tmp_path: Path) -> None:
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "before_item_commit" and not fired:
            fired = True
            raise RuntimeError("injected transaction fault")

    source, snapshot_path, snapshot, blobs, metadata, importer = _importer(
        tmp_path,
        repository_fault=fault,
    )
    with pytest.raises(RuntimeError, match="transaction"):
        importer.run()
    assert metadata.list_items(snapshot["snapshotDigest"]) == ()
    assert len(blobs.committed_digests()) == 2

    reopened = MigrationRepository(metadata.root)
    resumed = MigrationImporter(
        snapshot_path=snapshot_path,
        source_root=source,
        metadata=reopened,
        blobs=CommittedFilesystemBlobStore(blobs.root),
        authorization=FixtureImportAuthorization.create(
            snapshot=snapshot, source_root=source
        ),
        recorded_at=FIXED_TIME,
    )
    assert resumed.run().complete is True


def test_incomplete_blob_is_orphaned_and_recovered(tmp_path: Path) -> None:
    _source, _snapshot_path, snapshot, blobs, _metadata, importer = _importer(tmp_path)
    item = next(
        item
        for item in snapshot["inventory"]["items"]
        if item["relativePath"] == "a.xlsx"
    )
    target = blobs.object_directory(item["contentDigest"])
    target.parent.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    (target / "blob").write_bytes(b"partial")
    assert importer.run().complete is True
    assert len(tuple(blobs.orphaned.iterdir())) == 1
    blobs.verify(item["contentDigest"], item["byteLength"])


def test_source_mutation_and_symlink_swap_fail_closed(tmp_path: Path) -> None:
    source, _snapshot_path, snapshot, blobs, metadata, importer = _importer(tmp_path)
    original = (source / "a.xlsx").read_bytes()
    (source / "a.xlsx").write_bytes(b"X" * len(original))
    with pytest.raises(SourceItemMismatch, match="Source bytes differ"):
        importer.run()
    assert metadata.list_items(snapshot["snapshotDigest"]) == ()
    assert len(blobs.committed_digests()) == 1  # snapshot only

    second = tmp_path / "second"
    source, _snapshot_path, snapshot, _blobs, metadata, importer = _importer(second)
    outside = second / "outside.xlsx"
    outside.write_bytes((source / "a.xlsx").read_bytes())
    (source / "a.xlsx").unlink()
    (source / "a.xlsx").symlink_to(outside)
    with pytest.raises(SourceItemMismatch, match="opened safely"):
        importer.run()
    assert metadata.list_items(snapshot["snapshotDigest"]) == ()


def test_fixture_authorization_cannot_cover_larger_snapshot(tmp_path: Path) -> None:
    source, snapshot_path, snapshot = _frozen_fixture(tmp_path)
    with pytest.raises(ValueError, match="max_items"):
        FixtureImportAuthorization.create(
            snapshot=snapshot,
            source_root=source,
            max_items=1001,
        )
    fixture_authorization = FixtureImportAuthorization.create(
        snapshot=snapshot,
        source_root=source,
    )
    non_fixture = copy.deepcopy(snapshot)
    non_fixture["inventory"]["source"]["sourceSystem"] = "tidycell"
    with pytest.raises(ImportAuthorizationError, match="non-fixture"):
        fixture_authorization.validate(non_fixture, source)
    authorization = FixtureImportAuthorization.create(
        snapshot=snapshot,
        source_root=source,
        max_items=1,
    )
    with pytest.raises(ImportAuthorizationError, match="fixture-only"):
        MigrationImporter(
            snapshot_path=snapshot_path,
            source_root=source,
            metadata=MigrationRepository(tmp_path / "metadata"),
            blobs=CommittedFilesystemBlobStore(tmp_path / "blobs"),
            authorization=authorization,
            recorded_at=FIXED_TIME,
        )


def test_metadata_blob_and_source_roots_must_not_overlap(tmp_path: Path) -> None:
    source, snapshot_path, snapshot = _frozen_fixture(tmp_path)
    shared = tmp_path / "shared-root"
    metadata = MigrationRepository(shared)
    blobs = CommittedFilesystemBlobStore(shared)
    with pytest.raises(MigrationImportError, match="must not overlap"):
        MigrationImporter(
            snapshot_path=snapshot_path,
            source_root=source,
            metadata=metadata,
            blobs=blobs,
            authorization=FixtureImportAuthorization.create(
                snapshot=snapshot, source_root=source
            ),
            recorded_at=FIXED_TIME,
        )


def test_v1_metadata_repository_migrates_to_immutable_typed_records(
    tmp_path: Path,
) -> None:
    root = tmp_path / "metadata"
    repository = MigrationRepository(root)
    with sqlite3.connect(repository.database) as connection:
        connection.execute("DROP TABLE typed_records")
        connection.execute("DELETE FROM schema_migrations WHERE version=2")
        connection.commit()

    reopened = MigrationRepository(root)
    record_id = "sha256:" + "7" * 64
    reopened.add_typed_record(
        record_id=record_id,
        record_type="fixture-record",
        record={
            "schemaVersion": "fixture-record",
            "recordId": record_id,
            "fixture": True,
        },
    )
    assert reopened.list_typed_records() == (
        {
            "fixture": True,
            "recordId": record_id,
            "schemaVersion": "fixture-record",
        },
    )
    with sqlite3.connect(reopened.database) as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
    assert versions == [1, 2]


@pytest.mark.parametrize(
    ("target", "message"),
    (
        ("item", "import checkpoint"),
        ("alias", "alias checkpoint"),
        ("content", "content record"),
        ("snapshot", "Snapshot registration"),
    ),
)
def test_reconciliation_rejects_tampered_metadata_records(
    tmp_path: Path, target: str, message: str
) -> None:
    _source, _snapshot_path, snapshot, _blobs, metadata, importer = _importer(tmp_path)
    assert importer.run().complete is True
    with sqlite3.connect(metadata.database) as connection:
        if target == "item":
            table, where, parameters = (
                "import_items",
                "snapshot_digest=? AND relative_path=?",
                (snapshot["snapshotDigest"], "a.xlsx"),
            )
            identity = None
        elif target == "alias":
            table, where, parameters = (
                "aliases",
                "snapshot_digest=? AND relative_path=?",
                (snapshot["snapshotDigest"], "a.xlsx"),
            )
            identity = None
        elif target == "content":
            table, where, parameters = (
                "contents",
                "content_digest=?",
                (
                    next(
                        item["contentDigest"]
                        for item in snapshot["inventory"]["items"]
                        if item["relativePath"] == "a.xlsx"
                    ),
                ),
            )
            identity = "byteLength"
        else:
            table, where, parameters = (
                "snapshots",
                "snapshot_digest=?",
                (snapshot["snapshotDigest"],),
            )
            identity = "itemCount"
        record = json.loads(
            connection.execute(
                f"SELECT record_json FROM {table} WHERE {where}", parameters
            ).fetchone()[0]
        )
        if identity is None:
            record["finalState"] = "excluded"
        else:
            record[identity] += 1
        connection.execute(
            f"UPDATE {table} SET record_json=? WHERE {where}",
            (canonical_json_bytes(record), *parameters),
        )
        connection.commit()
    with pytest.raises(MigrationRecordConflict, match=message):
        importer.reconcile()


def test_tampered_committed_blob_is_rejected(tmp_path: Path) -> None:
    _source, _snapshot_path, snapshot, blobs, _metadata, importer = _importer(tmp_path)
    assert importer.run().complete is True
    item = next(
        item
        for item in snapshot["inventory"]["items"]
        if item["relativePath"] == "a.xlsx"
    )
    blob = blobs.object_directory(item["contentDigest"]) / "blob"
    blob.write_bytes(b"Z" * item["byteLength"])
    blob.chmod(0o600)
    with pytest.raises(BlobIntegrityError, match="digest differs"):
        blobs.verify(item["contentDigest"], item["byteLength"])
