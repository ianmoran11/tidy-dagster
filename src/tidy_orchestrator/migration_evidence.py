"""Conservative typed dispositions for imported recipe/model/generation evidence."""

from __future__ import annotations

import platform
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .artifacts import domain_digest, sha256_digest
from .migration_import import IncompleteMigration, MigrationRepository

_APPROVAL_RECORD = "tidy.approval-registry-evidence-import/v1"
_GENERATION_RECORD = "tidy.generation-evidence-import/v1"
_MODEL_RECORD = "tidy.model-package-disposition/v1"
_RECIPE_RECORD = "tidy.recipe-evidence-import/v1"
_SEMANTIC_RECONCILIATION = "tidy.semantic-import-reconciliation/v1"
_CONSERVATIVE_RECORD_TYPES = frozenset(
    (_APPROVAL_RECORD, _GENERATION_RECORD, _MODEL_RECORD, _RECIPE_RECORD)
)
_GENERATION_CLASSES = frozenset(
    (
        "catalog-evidence",
        "generation-json-evidence",
        "harvest-evidence",
        "ml-evidence",
        "research-evidence",
    )
)


class MigrationEvidenceError(RuntimeError):
    """Source/import evidence could not be bound conservatively."""


def persist_conservative_evidence_dispositions(
    *,
    snapshot: Mapping[str, Any],
    metadata: MigrationRepository,
    recorded_at: str,
    actor: str,
) -> dict[str, int]:
    """Persist fixture-safe typed dispositions after every core item exists."""

    counts: dict[str, int] = {}
    snapshot_digest = snapshot["snapshotDigest"]
    registration = metadata.get_snapshot_registration(snapshot_digest)
    if (
        registration.get("inventoryDigest") != snapshot["inventory"]["inventoryDigest"]
        or registration.get("itemManifestDigest")
        != snapshot["inventory"]["itemManifestDigest"]
        or registration.get("itemCount") != len(snapshot["inventory"]["items"])
    ):
        raise MigrationEvidenceError(
            "Snapshot registration does not bind the inventory"
        )
    for source_item in snapshot["inventory"]["items"]:
        import_record = metadata.get_item(snapshot_digest, source_item["relativePath"])
        if import_record is None:
            raise IncompleteMigration(
                "Conservative evidence disposition requires complete core import"
            )
        if import_record.get("snapshotDigest") != snapshot_digest:
            raise MigrationEvidenceError("Import record binds a different snapshot")
        for record in create_typed_evidence_records(
            source_item=source_item,
            import_record=import_record,
            recorded_at=recorded_at,
            actor=actor,
        ):
            metadata.add_typed_record(
                record_id=record["recordId"],
                record_type=record["schemaVersion"],
                record=record,
            )
            counts[record["schemaVersion"]] = counts.get(record["schemaVersion"], 0) + 1
    return dict(sorted(counts.items()))


def reconcile_conservative_evidence(
    *,
    snapshot: Mapping[str, Any],
    metadata: MigrationRepository,
    core_reconciliation: Mapping[str, Any],
    recorded_at: str,
    actor: str,
) -> dict[str, Any]:
    """Bind every source item to this pass without claiming semantic completion."""

    if not isinstance(actor, str) or not actor or len(actor) > 256:
        raise MigrationEvidenceError("Evidence actor is invalid")
    if (
        not isinstance(recorded_at, str)
        or not recorded_at.endswith("Z")
        or "T" not in recorded_at
    ):
        raise MigrationEvidenceError("recorded_at must be a canonical UTC timestamp")
    _validate_core_reconciliation(snapshot, metadata, core_reconciliation)
    producer_digest = _producer_source_digest()
    current_records = tuple(
        record
        for record in metadata.list_typed_records()
        if record["schemaVersion"] in _CONSERVATIVE_RECORD_TYPES
        and record.get("sourceSnapshotDigest") == snapshot["snapshotDigest"]
        and record.get("producerDigest") == producer_digest
        and record.get("recordedAt") == recorded_at
        and record.get("actor") == actor
    )
    records_by_item: dict[str, list[dict[str, Any]]] = {}
    for record in current_records:
        source_item_digest = record.get("sourceItemDigest")
        if not isinstance(source_item_digest, str):
            raise MigrationEvidenceError("Typed evidence lacks a source item digest")
        records_by_item.setdefault(source_item_digest, []).append(record)

    core_by_path = {
        mapping["relativePath"]: mapping for mapping in core_reconciliation["mappings"]
    }
    source_items = snapshot["inventory"]["items"]
    paths = [item["relativePath"] for item in source_items]
    if paths != sorted(paths) or set(core_by_path) != set(paths):
        raise MigrationEvidenceError("Core reconciliation paths differ from snapshot")

    mappings: list[dict[str, Any]] = []
    typed_record_counts: dict[str, int] = {}
    outcome_counts = {
        "conservative-typed-records": 0,
        "core-content-only": 0,
    }
    expected_source_digests: set[str] = set()
    for source_item in source_items:
        relative_path = source_item["relativePath"]
        import_record = metadata.get_item(snapshot["snapshotDigest"], relative_path)
        if import_record is None:
            raise IncompleteMigration(
                "Semantic reconciliation requires complete core import"
            )
        source_item_digest = _validate_source_import_binding(source_item, import_record)
        expected_source_digests.add(source_item_digest)
        core_mapping = core_by_path[relative_path]
        if (
            core_mapping.get("sourceItemDigest") != source_item_digest
            or core_mapping.get("recordId") != import_record["recordId"]
        ):
            raise MigrationEvidenceError(
                "Core reconciliation does not bind the import checkpoint"
            )
        expected_types = _expected_record_types(source_item)
        records = sorted(
            records_by_item.get(source_item_digest, []),
            key=lambda record: (record["schemaVersion"], record["recordId"]),
        )
        actual_types = [record["schemaVersion"] for record in records]
        if len(actual_types) != len(set(actual_types)) or set(actual_types) != set(
            expected_types
        ):
            raise IncompleteMigration(
                f"Typed evidence differs for source item {relative_path}"
            )
        for record_type in actual_types:
            typed_record_counts[record_type] = (
                typed_record_counts.get(record_type, 0) + 1
            )
        outcome = "conservative-typed-records" if records else "core-content-only"
        outcome_counts[outcome] += 1
        mappings.append(
            {
                "relativePath": relative_path,
                "sourceItemDigest": source_item_digest,
                "importRecordId": import_record["recordId"],
                "artifactClass": source_item["artifactClass"],
                "outcome": outcome,
                "typedRecordIds": [record["recordId"] for record in records],
            }
        )
    if not set(records_by_item).issubset(expected_source_digests):
        raise MigrationEvidenceError("Typed evidence references an unknown source item")

    semantic = {
        "schemaVersion": _SEMANTIC_RECONCILIATION,
        "snapshotDigest": snapshot["snapshotDigest"],
        "inventoryDigest": snapshot["inventory"]["inventoryDigest"],
        "itemManifestDigest": snapshot["inventory"]["itemManifestDigest"],
        "coreReconciliationDigest": core_reconciliation["reportDigest"],
        "producerDigest": producer_digest,
        "status": ("conservative-dispositions-complete-full-semantic-import-pending"),
        "sourceItemCount": len(source_items),
        "typedSourceItemCount": outcome_counts["conservative-typed-records"],
        "typedRecordCount": sum(typed_record_counts.values()),
        "outcomeCounts": outcome_counts,
        "typedRecordCounts": dict(sorted(typed_record_counts.items())),
        "mappings": mappings,
        "limitations": [
            "typed RecipeV01 parsing has not run",
            "approval rows and reviewer identities have not been resolved",
            "generation evidence has not been interpreted",
            "model packages have not been deserialized or promoted",
            "no effective recipe pointer was read or changed",
        ],
        "recordedAt": recorded_at,
        "actor": actor,
    }
    report = {
        **semantic,
        "recordId": domain_digest(_SEMANTIC_RECONCILIATION, semantic),
    }
    metadata.add_typed_record(
        record_id=report["recordId"],
        record_type=report["schemaVersion"],
        record=report,
    )
    return report


def create_typed_evidence_records(
    *,
    source_item: Mapping[str, Any],
    import_record: Mapping[str, Any],
    recorded_at: str,
    actor: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(actor, str) or not actor or len(actor) > 256:
        raise MigrationEvidenceError("Evidence actor is invalid")
    if (
        not isinstance(recorded_at, str)
        or not recorded_at.endswith("Z")
        or "T" not in recorded_at
    ):
        raise MigrationEvidenceError("recorded_at must be a canonical UTC timestamp")
    expected_item_digest = _validate_source_import_binding(source_item, import_record)
    producer_digest = _producer_source_digest()
    records: list[dict[str, Any]] = []
    artifact_class = source_item["artifactClass"]
    if artifact_class == "approval-registry":
        reason = {
            "excluded": "SOURCE_EXCLUDED",
            "quarantined": "SOURCE_QUARANTINED",
        }.get(import_record["finalState"], "TYPED_APPROVAL_PARSE_NOT_RUN")
        semantic = {
            "schemaVersion": _APPROVAL_RECORD,
            "sourceSnapshotDigest": import_record["snapshotDigest"],
            "sourceItemDigest": expected_item_digest,
            "sourceContentDigest": source_item["contentDigest"],
            "relativePath": source_item["relativePath"],
            "sourceFinalState": import_record["finalState"],
            "blobStored": import_record["blobStored"],
            "historyCompleteness": "point-in-time-current-state-only",
            "interpretationStatus": "not-run",
            "approvalAuthorityCreated": False,
            "active": False,
            "trainingEligible": False,
            "reason": reason,
            "producerDigest": producer_digest,
            "recordedAt": recorded_at,
            "actor": actor,
        }
        records.append(
            {
                **semantic,
                "recordId": domain_digest(_APPROVAL_RECORD, semantic),
            }
        )
    if artifact_class == "recipe-evidence":
        reason = {
            "excluded": "SOURCE_EXCLUDED",
            "quarantined": "SOURCE_QUARANTINED",
        }.get(import_record["finalState"], "TYPED_RECIPE_PARSE_NOT_RUN")
        semantic = {
            "schemaVersion": _RECIPE_RECORD,
            "sourceSnapshotDigest": import_record["snapshotDigest"],
            "sourceItemDigest": expected_item_digest,
            "sourceContentDigest": source_item["contentDigest"],
            "relativePath": source_item["relativePath"],
            "sourceFinalState": import_record["finalState"],
            "blobStored": import_record["blobStored"],
            "lifecycleState": "incomplete_evidence",
            "active": False,
            "trainingEligible": False,
            "reason": reason,
            "producerDigest": producer_digest,
            "recordedAt": recorded_at,
            "actor": actor,
        }
        records.append(
            {
                **semantic,
                "recordId": domain_digest(_RECIPE_RECORD, semantic),
            }
        )
    if artifact_class == "model-binary":
        semantic = {
            "schemaVersion": _MODEL_RECORD,
            "sourceSnapshotDigest": import_record["snapshotDigest"],
            "sourceItemDigest": expected_item_digest,
            "sourceContentDigest": source_item["contentDigest"],
            "relativePath": source_item["relativePath"],
            "sourceFinalState": import_record["finalState"],
            "blobStored": import_record["blobStored"],
            "eligibility": "archival-unreviewed",
            "runnable": False,
            "trainingEligible": False,
            "deserializationStatus": "not-attempted",
            "reason": "UNREVIEWED_MODEL_PACKAGE",
            "producerDigest": producer_digest,
            "recordedAt": recorded_at,
            "actor": actor,
        }
        records.append(
            {
                **semantic,
                "recordId": domain_digest(_MODEL_RECORD, semantic),
            }
        )
    embedded = source_item.get("embeddedRecords", [])
    if artifact_class in _GENERATION_CLASSES or embedded:
        pointers = [
            {
                "kind": record["kind"],
                "pointer": record["pointer"],
                "valueType": record["valueType"],
            }
            for record in embedded
        ]
        restricted = artifact_class in _GENERATION_CLASSES or any(
            record["kind"] in ("prompt-evidence", "provider-response-evidence")
            for record in pointers
        )
        semantic = {
            "schemaVersion": _GENERATION_RECORD,
            "sourceSnapshotDigest": import_record["snapshotDigest"],
            "sourceItemDigest": expected_item_digest,
            "sourceContentDigest": source_item["contentDigest"],
            "relativePath": source_item["relativePath"],
            "sourceFinalState": import_record["finalState"],
            "blobStored": import_record["blobStored"],
            "artifactClass": artifact_class,
            "interpretationStatus": "not-run",
            "rawEvidenceRestricted": restricted,
            "embeddedRecords": pointers,
            "warnings": source_item.get("warnings", []),
            "producerDigest": producer_digest,
            "recordedAt": recorded_at,
            "actor": actor,
        }
        records.append(
            {
                **semantic,
                "recordId": domain_digest(_GENERATION_RECORD, semantic),
            }
        )
    return tuple(records)


def _expected_record_types(source_item: Mapping[str, Any]) -> tuple[str, ...]:
    artifact_class = source_item.get("artifactClass")
    values: set[str] = set()
    if artifact_class == "approval-registry":
        values.add(_APPROVAL_RECORD)
    if artifact_class == "recipe-evidence":
        values.add(_RECIPE_RECORD)
    if artifact_class == "model-binary":
        values.add(_MODEL_RECORD)
    if artifact_class in _GENERATION_CLASSES or source_item.get("embeddedRecords"):
        values.add(_GENERATION_RECORD)
    return tuple(sorted(values))


def _validate_core_reconciliation(
    snapshot: Mapping[str, Any],
    metadata: MigrationRepository,
    report: Mapping[str, Any],
) -> None:
    if (
        report.get("schemaVersion") != "tidy.migration-reconciliation/v1"
        or report.get("snapshotDigest") != snapshot["snapshotDigest"]
        or report.get("inventoryDigest") != snapshot["inventory"]["inventoryDigest"]
        or report.get("itemManifestDigest")
        != snapshot["inventory"]["itemManifestDigest"]
        or report.get("contentReconciliationStatus") != "complete"
        or report.get("phaseBStatus") != "core-content-complete-semantic-import-pending"
        or report.get("sourceItemCount") != len(snapshot["inventory"]["items"])
        or not isinstance(report.get("mappings"), list)
        or len(report["mappings"]) != len(snapshot["inventory"]["items"])
    ):
        raise MigrationEvidenceError("Core reconciliation fields are invalid")
    semantic = dict(report)
    report_digest = semantic.pop("reportDigest", None)
    if report_digest != domain_digest("tidy.migration-reconciliation/v1", semantic):
        raise MigrationEvidenceError("Core reconciliation digest differs")
    if metadata.get_reconciliation(report_digest) != dict(report):
        raise MigrationEvidenceError("Stored core reconciliation differs")
    registration = metadata.get_snapshot_registration(snapshot["snapshotDigest"])
    if (
        registration.get("inventoryDigest") != snapshot["inventory"]["inventoryDigest"]
        or registration.get("itemManifestDigest")
        != snapshot["inventory"]["itemManifestDigest"]
        or registration.get("itemCount") != len(snapshot["inventory"]["items"])
    ):
        raise MigrationEvidenceError(
            "Snapshot registration does not bind semantic reconciliation"
        )


def _validate_source_import_binding(
    source_item: Mapping[str, Any], import_record: Mapping[str, Any]
) -> str:
    expected_item_digest = domain_digest("tidy.export-item/v1", source_item)
    matching_fields = (
        ("relativePath", "relativePath"),
        ("entryType", "entryType"),
        ("artifactClass", "artifactClass"),
        ("disposition", "proposedDisposition"),
        ("sourceMode", "sourceMode"),
        ("byteLength", "byteLength"),
        ("contentDigest", "sourceContentDigest"),
    )
    if (
        import_record.get("schemaVersion") != "tidy.migration-import-item/v1"
        or import_record.get("sourceItemDigest") != expected_item_digest
        or any(
            source_item.get(source_name) != import_record.get(import_name)
            for source_name, import_name in matching_fields
        )
    ):
        raise MigrationEvidenceError("Import record does not bind the source item")
    import_semantic = dict(import_record)
    import_record_id = import_semantic.pop("recordId", None)
    if import_record_id != domain_digest(
        "tidy.migration-import-item/v1", import_semantic
    ):
        raise MigrationEvidenceError("Import record identity digest differs")
    final_state = {
        "import": "imported",
        "duplicate-alias": "duplicate-alias",
        "exclude": "excluded",
        "quarantine": "quarantined",
    }.get(source_item.get("disposition"))
    if import_record.get("finalState") != final_state:
        raise MigrationEvidenceError("Import final state differs from disposition")
    artifact_class = source_item.get("artifactClass")
    is_typed = artifact_class in _GENERATION_CLASSES or artifact_class in (
        "approval-registry",
        "model-binary",
        "recipe-evidence",
    )
    if is_typed and source_item.get("entryType") != "file":
        raise MigrationEvidenceError("Typed evidence must be a regular source file")
    if is_typed and import_record.get("classification") != "restricted":
        raise MigrationEvidenceError("Typed evidence is not restricted")
    should_store = is_typed and source_item.get("disposition") != "exclude"
    expected_uri = (
        f"cas+sha256://{source_item.get('contentDigest')}" if should_store else None
    )
    if is_typed and (
        import_record.get("blobStored") is not should_store
        or import_record.get("contentDigest")
        != (source_item.get("contentDigest") if should_store else None)
        or import_record.get("storageUri") != expected_uri
    ):
        raise MigrationEvidenceError("Typed evidence is not bound to stored bytes")
    return expected_item_digest


@lru_cache(maxsize=1)
def _producer_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = [
        project / "pyproject.toml",
        project / "uv.lock",
        Path(__file__),
        Path(__file__).with_name("migration_import.py"),
    ]
    for name in (
        "approval-registry-evidence.schema.json",
        "generation-evidence.schema.json",
        "import-item.schema.json",
        "model-package-disposition.schema.json",
        "recipe-evidence-import.schema.json",
        "reconciliation.schema.json",
        "semantic-reconciliation.schema.json",
    ):
        paths.append(project / "contracts/import/v1" / name)

    def capture() -> list[dict[str, str]]:
        return [
            {
                "relativePath": path.relative_to(project).as_posix(),
                "contentDigest": sha256_digest(path.read_bytes()),
            }
            for path in paths
        ]

    files = capture()
    if capture() != files:
        raise MigrationEvidenceError("Evidence producer closure changed while hashing")
    return domain_digest(
        "tidy.migration-evidence-source-closure/v1",
        {
            "files": files,
            "runtime": {
                "pythonImplementation": platform.python_implementation(),
                "pythonVersion": platform.python_version(),
            },
        },
    )
