"""Conservative typed dispositions for imported recipe/model/generation evidence."""

from __future__ import annotations

import platform
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .artifacts import domain_digest, sha256_digest
from .migration_import import IncompleteMigration, MigrationRepository

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
    if artifact_class == "recipe-evidence":
        reason = {
            "excluded": "SOURCE_EXCLUDED",
            "quarantined": "SOURCE_QUARANTINED",
        }.get(import_record["finalState"], "TYPED_RECIPE_PARSE_NOT_RUN")
        semantic = {
            "schemaVersion": "tidy.recipe-evidence-import/v1",
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
                "recordId": domain_digest("tidy.recipe-evidence-import/v1", semantic),
            }
        )
    if artifact_class == "model-binary":
        semantic = {
            "schemaVersion": "tidy.model-package-disposition/v1",
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
                "recordId": domain_digest(
                    "tidy.model-package-disposition/v1", semantic
                ),
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
            "schemaVersion": "tidy.generation-evidence-import/v1",
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
                "recordId": domain_digest(
                    "tidy.generation-evidence-import/v1", semantic
                ),
            }
        )
    return tuple(records)


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
        "generation-evidence.schema.json",
        "import-item.schema.json",
        "model-package-disposition.schema.json",
        "recipe-evidence-import.schema.json",
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
