"""Bounded live import for the frozen disposable hobby-project canary."""

from __future__ import annotations

import os
import stat
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .artifacts import canonical_json_bytes, domain_digest
from .migration_canary import canonical_manifest_digest, load_canary_manifest
from .migration_evidence import (
    persist_conservative_evidence_dispositions,
    reconcile_conservative_evidence,
)
from .migration_gateway import (
    actual_migration_worker_gateway,
    persist_imported_legacy_approval_snapshot,
)
from .migration_import import (
    CommittedFilesystemBlobStore,
    ImportAuthorizationError,
    MigrationImporter,
    MigrationRepository,
)
from .source_export import load_and_verify_export

_CANARY_MANIFEST_DIGEST = (
    "sha256:ee072650751fa76d456ba8cf034878a2a48137b02e6e7d459cb7945cb9474139"
)
_SOURCE_SNAPSHOT_DIGEST = (
    "sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d"
)
_CANARY_SNAPSHOT_VERSION = "tidy.canary-import-snapshot/v1"
_AUTHORIZATION_VERSION = "tidy.canary-import-authorization/v1"
_REPORT_VERSION = "tidy.canary-mvp-report/v1"
_MAX_ITEMS = 63
_MAX_SOURCE_READ_BYTES = 64 * 1024 * 1024
_MAX_UNIQUE_COPY_BYTES = 64 * 1024 * 1024


class CanaryMvpError(RuntimeError):
    """The frozen live canary could not be executed without expanding authority."""


@dataclass(frozen=True)
class CanaryImportAuthorization:
    """Exact one-canary authority; it cannot authorize the full Phase A snapshot."""

    canary_manifest_digest: str
    snapshot_digest: str
    source_device_id: int
    source_root_inode: int
    max_items: int = _MAX_ITEMS
    max_source_bytes: int = _MAX_SOURCE_READ_BYTES
    mode: Literal["frozen-canary-only"] = "frozen-canary-only"

    @classmethod
    def create(
        cls,
        *,
        manifest: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        source_root: Path,
    ) -> CanaryImportAuthorization:
        if canonical_manifest_digest(manifest) != _CANARY_MANIFEST_DIGEST:
            raise CanaryMvpError("Canary manifest digest differs from authorization")
        verify_canary_snapshot(snapshot)
        if snapshot["canary"]["selectedItemSetDigest"] != manifest.get(
            "selectedItemSetDigest"
        ):
            raise CanaryMvpError("Canary selected item set differs")
        root = _safe_directory(source_root, "source root")
        info = root.lstat()
        return cls(
            canary_manifest_digest=_CANARY_MANIFEST_DIGEST,
            snapshot_digest=str(snapshot["snapshotDigest"]),
            source_device_id=info.st_dev,
            source_root_inode=info.st_ino,
        )

    def validate(self, snapshot: Mapping[str, Any], source_root: Path) -> None:
        if self.mode != "frozen-canary-only":
            raise ImportAuthorizationError("Only the frozen canary is authorized")
        if snapshot.get("schemaVersion") != _CANARY_SNAPSHOT_VERSION:
            raise ImportAuthorizationError("Authorization requires a canary snapshot")
        if snapshot.get("snapshotDigest") != self.snapshot_digest:
            raise ImportAuthorizationError(
                "Authorization binds another canary snapshot"
            )
        canary = snapshot.get("canary")
        if not isinstance(canary, dict) or (
            canary.get("manifestDigest") != self.canary_manifest_digest
            or canary.get("sourceSnapshotDigest") != _SOURCE_SNAPSHOT_DIGEST
        ):
            raise ImportAuthorizationError("Canary authority chain differs")
        root = _safe_directory(source_root, "source root")
        info = root.lstat()
        if (info.st_dev, info.st_ino) != (
            self.source_device_id,
            self.source_root_inode,
        ):
            raise ImportAuthorizationError("Authorization binds another source root")
        filesystem = snapshot["inventory"]["source"]["filesystem"]
        if (info.st_dev, info.st_ino, info.st_mode) != (
            filesystem["deviceId"],
            filesystem["rootInode"],
            filesystem["rootMode"],
        ):
            raise ImportAuthorizationError("Source root differs from canary identity")
        items = snapshot["inventory"]["items"]
        source_bytes = sum(
            int(item["byteLength"]) for item in items if item["entryType"] == "file"
        )
        if len(items) != self.max_items or source_bytes > self.max_source_bytes:
            raise ImportAuthorizationError("Canary exceeds its exact execution bounds")


def build_canary_snapshot(
    *,
    source_snapshot: Mapping[str, Any],
    manifest: Mapping[str, Any],
    source_root: Path,
    blob_root: Path,
    frozen_at: str,
) -> dict[str, Any]:
    """Derive an importer-compatible snapshot containing exactly 63 frozen items."""

    _validate_manifest_snapshot(manifest, source_snapshot)
    source_root = _safe_directory(source_root, "source root")
    blob_root = _safe_directory(blob_root, "blob root")
    selected = manifest["selectedItems"]
    source_by_path = {
        item["relativePath"]: item for item in source_snapshot["inventory"]["items"]
    }
    items: list[dict[str, Any]] = []
    for selection in selected:
        path = selection["relativePath"]
        source_item = source_by_path.get(path)
        if source_item is None:
            raise CanaryMvpError(f"Selected source path is absent: {path}")
        expected = _source_item_digest(source_item)
        if expected != selection["sourceItemDigest"]:
            raise CanaryMvpError(f"Selected source item digest differs: {path}")
        for name in (
            "entryType",
            "artifactClass",
            "disposition",
            "sourceMode",
            "byteLength",
            "contentDigest",
        ):
            if source_item.get(name) != selection.get(name):
                raise CanaryMvpError(f"Selected source metadata differs: {path}:{name}")
        items.append(dict(source_item))
    if len(items) != _MAX_ITEMS or [item["relativePath"] for item in items] != sorted(
        item["relativePath"] for item in items
    ):
        raise CanaryMvpError("Canary item set is not the canonical 63-item order")

    summary = _summary(items)
    item_manifest_digest = domain_digest("tidy.export-item-manifest/v1", items)
    source = dict(source_snapshot["inventory"]["source"])
    source["sourceRootId"] = "tidycell-frozen-phase-b-canary-v1"
    source["sourceSystem"] = "tidycell-frozen-canary"
    root_info = source_root.lstat()
    source["filesystem"] = {
        "deviceId": root_info.st_dev,
        "rootInode": root_info.st_ino,
        "rootMode": root_info.st_mode,
    }
    inventory_core = {
        "source": source,
        "policy": dict(source_snapshot["inventory"]["policy"]),
        "exporter": dict(source_snapshot["inventory"]["exporter"]),
        "safety": dict(source_snapshot["inventory"]["safety"]),
        "items": items,
        "itemManifestDigest": item_manifest_digest,
        "summary": summary,
    }
    inventory = {
        **inventory_core,
        "inventoryDigest": domain_digest(
            "tidy.source-export-inventory/v1", inventory_core
        ),
    }
    storage = _storage_assessment(items, blob_root)
    storage_digest = domain_digest("tidy.storage-assessment/v1", storage)
    canary = {
        "manifestDigest": _CANARY_MANIFEST_DIGEST,
        "sourceSnapshotDigest": _SOURCE_SNAPSHOT_DIGEST,
        "selectedItemSetDigest": manifest["selectedItemSetDigest"],
        "disposableLocalBlobData": True,
        "nasRequired": False,
        "fullImportAuthorized": False,
        "providerDispatchAuthorized": False,
        "activationAuthorized": False,
        "trainingAuthorized": False,
    }
    identity = {
        "completionStatus": "complete",
        "frozenAt": frozen_at,
        "inventoryDigest": inventory["inventoryDigest"],
        "storageAssessmentDigest": storage_digest,
        "canary": canary,
    }
    return {
        "schemaVersion": _CANARY_SNAPSHOT_VERSION,
        "completionStatus": "complete",
        "frozenAt": frozen_at,
        "inventory": inventory,
        "storageAssessment": storage,
        "storageAssessmentDigest": storage_digest,
        "canary": canary,
        "snapshotDigest": domain_digest(_CANARY_SNAPSHOT_VERSION, identity),
    }


def verify_canary_snapshot(snapshot: Mapping[str, Any]) -> str:
    """Validate identity and return the canary snapshot digest."""

    required = {
        "schemaVersion",
        "completionStatus",
        "frozenAt",
        "inventory",
        "storageAssessment",
        "storageAssessmentDigest",
        "canary",
        "snapshotDigest",
    }
    if (
        set(snapshot) != required
        or snapshot.get("schemaVersion") != _CANARY_SNAPSHOT_VERSION
    ):
        raise CanaryMvpError("Canary snapshot fields are invalid")
    inventory = snapshot["inventory"]
    if not isinstance(inventory, dict):
        raise CanaryMvpError("Canary inventory is invalid")
    inventory_core = dict(inventory)
    inventory_digest = inventory_core.pop("inventoryDigest", None)
    if inventory_digest != domain_digest(
        "tidy.source-export-inventory/v1", inventory_core
    ):
        raise CanaryMvpError("Canary inventory digest differs")
    items = inventory.get("items")
    if not isinstance(items, list) or len(items) != _MAX_ITEMS:
        raise CanaryMvpError("Canary snapshot does not contain exactly 63 items")
    if inventory.get("itemManifestDigest") != domain_digest(
        "tidy.export-item-manifest/v1", items
    ):
        raise CanaryMvpError("Canary item manifest digest differs")
    if inventory.get("summary") != _summary(items):
        raise CanaryMvpError("Canary inventory summary differs")
    storage = snapshot["storageAssessment"]
    if (
        snapshot.get("storageAssessmentDigest")
        != domain_digest("tidy.storage-assessment/v1", storage)
        or storage.get("passes") is not True
    ):
        raise CanaryMvpError("Canary storage assessment differs")
    canary = snapshot.get("canary")
    if not isinstance(canary, dict) or canary != {
        "manifestDigest": _CANARY_MANIFEST_DIGEST,
        "sourceSnapshotDigest": _SOURCE_SNAPSHOT_DIGEST,
        "selectedItemSetDigest": canary.get("selectedItemSetDigest"),
        "disposableLocalBlobData": True,
        "nasRequired": False,
        "fullImportAuthorized": False,
        "providerDispatchAuthorized": False,
        "activationAuthorized": False,
        "trainingAuthorized": False,
    }:
        raise CanaryMvpError("Canary authority fields differ")
    identity = {
        "completionStatus": snapshot["completionStatus"],
        "frozenAt": snapshot["frozenAt"],
        "inventoryDigest": inventory_digest,
        "storageAssessmentDigest": snapshot["storageAssessmentDigest"],
        "canary": canary,
    }
    expected = domain_digest(_CANARY_SNAPSHOT_VERSION, identity)
    if snapshot.get("snapshotDigest") != expected:
        raise CanaryMvpError("Canary snapshot identity differs")
    return expected


def run_canary_mvp(
    *,
    source_snapshot_path: Path,
    manifest_path: Path,
    source_root: Path,
    metadata_root: Path,
    blob_root: Path,
    output_root: Path,
    recorded_at: str,
) -> dict[str, Any]:
    """Import, conservatively type, reconcile, verify, and report the canary."""

    source_snapshot, source_digest = load_and_verify_export(source_snapshot_path)
    if source_digest != _SOURCE_SNAPSHOT_DIGEST:
        raise CanaryMvpError("Source snapshot is not the frozen Phase A authority")
    manifest = load_canary_manifest(manifest_path)
    canonical_manifest_digest(manifest)
    source_root = _safe_directory(source_root, "source root")
    metadata_root = _safe_directory(metadata_root, "metadata root")
    blob_root = _safe_directory(blob_root, "blob root")
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_root = _safe_directory(output_root, "output root")
    local_device = source_root.lstat().st_dev
    if (
        metadata_root.lstat().st_dev != local_device
        or blob_root.lstat().st_dev != local_device
        or output_root.lstat().st_dev != local_device
    ):
        raise CanaryMvpError("Canary storage must remain on the local workstation")
    if any(
        _overlap(left, right)
        for index, left in enumerate(
            (source_root, metadata_root, blob_root, output_root)
        )
        for right in (source_root, metadata_root, blob_root, output_root)[index + 1 :]
    ):
        raise CanaryMvpError("Canary source, authority, blob, and output trees overlap")

    snapshot = build_canary_snapshot(
        source_snapshot=source_snapshot,
        manifest=manifest,
        source_root=source_root,
        blob_root=blob_root,
        frozen_at=recorded_at,
    )
    verify_canary_snapshot(snapshot)
    snapshot_path = output_root / "canary-import-snapshot.json"
    _write_once(snapshot_path, canonical_json_bytes(snapshot) + b"\n")
    metadata = MigrationRepository(metadata_root)
    blobs = CommittedFilesystemBlobStore(blob_root)
    authorization = CanaryImportAuthorization.create(
        manifest=manifest,
        snapshot=snapshot,
        source_root=source_root,
    )
    importer = MigrationImporter(
        snapshot_path=snapshot_path,
        source_root=source_root,
        metadata=metadata,
        blobs=blobs,
        authorization=authorization,
        recorded_at=recorded_at,
        actor="tidy-canary-mvp-importer",
    )
    progress = importer.run()
    if not progress.complete:
        raise CanaryMvpError("Canary core import did not complete")
    core = importer.reconcile()
    typed_counts = persist_conservative_evidence_dispositions(
        snapshot=snapshot,
        metadata=metadata,
        recorded_at=recorded_at,
        actor="tidy-canary-mvp-interpreter",
    )
    interpretations = _interpret_available_evidence(
        snapshot=snapshot,
        metadata=metadata,
        blobs=blobs,
        recorded_at=recorded_at,
    )
    semantic = reconcile_conservative_evidence(
        snapshot=snapshot,
        metadata=metadata,
        core_reconciliation=core,
        recorded_at=recorded_at,
        actor="tidy-canary-mvp-interpreter",
        completed_interpretations=interpretations["eligibleSourceCounts"],
    )
    # A second exact run is the restart/idempotence check over real NAS blobs.
    repeated = importer.run()
    repeated_core = importer.reconcile()
    if not repeated.complete or repeated_core != core:
        raise CanaryMvpError("Canary rerun was not idempotent")

    report_semantic = {
        "schemaVersion": _REPORT_VERSION,
        "recordedAt": recorded_at,
        "canaryManifestDigest": _CANARY_MANIFEST_DIGEST,
        "sourceSnapshotDigest": _SOURCE_SNAPSHOT_DIGEST,
        "canarySnapshotDigest": snapshot["snapshotDigest"],
        "coreReconciliationDigest": core["reportDigest"],
        "semanticReconciliationId": semantic["recordId"],
        "itemCount": core["sourceItemCount"],
        "sourceReadBytes": snapshot["inventory"]["summary"]["sourceReadBytes"],
        "itemOutcomeBytes": core["sourceItemBytes"],
        "failureCount": 0,
        "failures": [],
        "stateCounts": core["stateCounts"],
        "stateBytes": core["stateBytes"],
        "uniqueStoredObjects": core["uniqueStoredObjects"],
        "uniqueStoredBytes": core["uniqueStoredBytes"],
        "typedRecordCounts": typed_counts,
        "typedSourceItemCount": semantic["typedSourceItemCount"],
        "typedRecordCount": semantic["typedRecordCount"],
        "interpretations": interpretations,
        "idempotentReplayVerified": True,
        "localBlobDataDisposable": True,
        "sqliteLocal": True,
        "nasRequired": False,
        "automaticActivationAuthorized": False,
        "providerDispatchAuthorized": False,
        "trainingAuthorized": False,
        "fullImportAuthorized": False,
        "manualInspectionRequired": True,
        "retainedLimitations": [
            "recipe parsing establishes schema-valid inactive revisions, not approval",
            (
                "approval rows were digested but targets and unresolved reviewers "
                "remain unresolved"
            ),
            "generation profiling emits bounded metadata and no raw restricted text",
            "model packages were archived without deserialization or promotion",
            "no effective recipe pointer was read or changed",
        ],
        "rebuild": {
            "deleteOnly": (
                "Delete only the dedicated local blob root contents; retain the "
                "separate metadata root when preserving the audit trail."
            ),
            "rerun": "uv run python -m tidy_orchestrator.canary_mvp_cli run",
        },
    }
    report = {
        **report_semantic,
        "reportDigest": domain_digest(_REPORT_VERSION, report_semantic),
    }
    _write_once(
        output_root / "canary-report.json", canonical_json_bytes(report) + b"\n"
    )
    _write_once(
        output_root / "core-reconciliation.json",
        canonical_json_bytes(core) + b"\n",
    )
    _write_once(
        output_root / "semantic-reconciliation.json",
        canonical_json_bytes(semantic) + b"\n",
    )
    return report


def _interpret_available_evidence(
    *,
    snapshot: Mapping[str, Any],
    metadata: MigrationRepository,
    blobs: CommittedFilesystemBlobStore,
    recorded_at: str,
) -> dict[str, Any]:
    eligible = [
        item
        for item in snapshot["inventory"]["items"]
        if item["disposition"] in ("import", "duplicate-alias")
        and item["artifactClass"]
        in ("approval-registry", "recipe-evidence", "generation-json-evidence")
    ]
    gateway = actual_migration_worker_gateway(
        metadata, blobs, Path(__file__).parents[2]
    )
    approval_rows = 0
    approval_output_digests: list[str] = []
    approval_snapshot_digests: list[str] = []
    recipe_output_digests: list[str] = []
    valid_recipes = 0
    generation_output_digests: list[str] = []
    restricted_count = 0
    recipe_candidate_count = 0
    for item in eligible:
        import_record = metadata.get_item(
            snapshot["snapshotDigest"], item["relativePath"]
        )
        if import_record is None:
            raise CanaryMvpError("Interpretation source import is missing")
        artifact_class = item["artifactClass"]
        if artifact_class == "approval-registry":
            result = persist_imported_legacy_approval_snapshot(
                gateway=gateway,
                source_item=item,
                import_record=import_record,
                frozen_at=recorded_at,
            )
            approval_snapshot_digests.append(
                str(result.approval_snapshot["sourceContentDigest"])
            )
            approval_output_digests.append(
                str(result.execution.outputs[0].record["contentDigest"])
            )
            approval_rows += len(result.approval_snapshot["rows"])
        elif artifact_class == "recipe-evidence":
            execution = gateway.parse_imported_recipe(import_record)
            if len(execution.outputs) != 1:
                raise CanaryMvpError("Recipe parse produced an unexpected output set")
            recipe_output_digests.append(
                str(execution.outputs[0].record["contentDigest"])
            )
            valid_recipes += execution.outputs[0].artifact["lifecycleState"] == (
                "schema_valid"
            )
        else:
            execution = gateway.profile_imported_generation_evidence(import_record)
            if len(execution.outputs) != 1:
                raise CanaryMvpError(
                    "Generation profile produced an unexpected output set"
                )
            output = execution.outputs[0]
            artifact = output.artifact
            generation_output_digests.append(str(output.record["contentDigest"]))
            restricted_count += len(artifact["restrictedElements"])
            recipe_candidate_count += len(artifact["recipeCandidates"])
    counts = Counter(item["artifactClass"] for item in eligible)
    return {
        "eligibleSourceCounts": dict(sorted(counts.items())),
        "approvalRegistry": {
            "interpretedSourceCount": len(approval_snapshot_digests),
            "rowCount": approval_rows,
            "sourceContentDigests": approval_snapshot_digests,
            "workerOutputContentDigests": approval_output_digests,
            "approvalAuthorityCreated": False,
            "targetsResolved": False,
        },
        "recipes": {
            "interpretedSourceCount": len(recipe_output_digests),
            "schemaValidCount": valid_recipes,
            "workerOutputContentDigests": recipe_output_digests,
            "active": False,
            "trainingEligible": False,
        },
        "generationProfiles": {
            "profiledSourceCount": len(generation_output_digests),
            "workerOutputContentDigests": generation_output_digests,
            "restrictedElementCount": restricted_count,
            "strictRecipeCandidateCount": recipe_candidate_count,
            "rawRestrictedTextEmitted": False,
        },
        "providerDispatchAuthorized": False,
        "retryAuthorized": False,
        "activationAuthorized": False,
        "trainingEligible": False,
    }


def _validate_manifest_snapshot(
    manifest: Mapping[str, Any], source_snapshot: Mapping[str, Any]
) -> None:
    if canonical_manifest_digest(manifest) != _CANARY_MANIFEST_DIGEST:
        raise CanaryMvpError("Canary manifest digest differs from authorization")
    if source_snapshot.get("snapshotDigest") != _SOURCE_SNAPSHOT_DIGEST:
        raise CanaryMvpError("Source snapshot digest differs from authorization")
    source = manifest.get("sourceSnapshot")
    if not isinstance(source, dict) or (
        source.get("snapshotDigest") != _SOURCE_SNAPSHOT_DIGEST
        or source.get("inventoryDigest")
        != source_snapshot["inventory"]["inventoryDigest"]
        or source.get("itemManifestDigest")
        != source_snapshot["inventory"]["itemManifestDigest"]
    ):
        raise CanaryMvpError("Canary manifest does not bind the source snapshot")
    coverage = manifest.get("coverage")
    if not isinstance(coverage, dict) or (
        coverage.get("itemCount") != _MAX_ITEMS
        or coverage.get("sourceReadBytes") > _MAX_SOURCE_READ_BYTES
        or coverage.get("uniqueCopyBytes") > _MAX_UNIQUE_COPY_BYTES
    ):
        raise CanaryMvpError("Canary coverage exceeds the live MVP bounds")


def _source_item_digest(item: Mapping[str, Any]) -> str:
    return domain_digest("tidy.export-item/v1", item)


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    file_items = [item for item in items if item["entryType"] == "file"]
    copy_items = [
        item
        for item in file_items
        if item["disposition"] in ("import", "duplicate-alias", "quarantine")
    ]
    unique: dict[str, int] = {}
    for item in copy_items:
        unique.setdefault(str(item["contentDigest"]), int(item["byteLength"]))
    return {
        "itemCount": len(items),
        "fileCount": len(file_items),
        "sourceReadBytes": sum(int(item["byteLength"]) for item in file_items),
        "copyEligibleItemCount": len(copy_items),
        "uniqueCopyObjectCount": len(unique),
        "uniqueCopyBytes": sum(unique.values()),
        "countsByDisposition": dict(
            sorted(Counter(item["disposition"] for item in items).items())
        ),
        "countsByArtifactClass": dict(
            sorted(Counter(item["artifactClass"] for item in items).items())
        ),
        "countsByEntryType": dict(
            sorted(Counter(item["entryType"] for item in items).items())
        ),
        "git": {
            "trackedCount": sum(item["gitState"] == "tracked" for item in items),
            "ignoredCount": sum(item["gitState"] == "ignored" for item in items),
            "untrackedCount": sum(item["gitState"] == "untracked" for item in items),
        },
        "duplicateAliasCount": sum(
            item["disposition"] == "duplicate-alias" for item in items
        ),
        "warningCounts": dict(
            sorted(
                Counter(
                    warning for item in items for warning in item.get("warnings", [])
                ).items()
            )
        ),
        "embeddedRecordCount": sum(
            len(item.get("embeddedRecords", [])) for item in items
        ),
        "embeddedKindCounts": dict(
            sorted(
                Counter(
                    record["kind"]
                    for item in items
                    for record in item.get("embeddedRecords", [])
                ).items()
            )
        ),
    }


def _storage_assessment(items: list[dict[str, Any]], blob_root: Path) -> dict[str, Any]:
    statvfs = os.statvfs(blob_root)
    free = statvfs.f_bavail * statvfs.f_frsize
    required = _summary(items)["uniqueCopyBytes"]
    reserve = 10 * 1024**3
    required_free = required * 2 + reserve
    passes = free >= required_free
    # Volatile free-space counters are checked before effects but intentionally
    # excluded from the frozen snapshot identity, so identical source bytes and
    # policy rebuild to identical authority records on the same workstation.
    return {
        "destinationId": "tidy-dagster-disposable-local-canary-v1",
        "uniqueCopyBytes": required,
        "requiredFreeBytes": required_free,
        "passesAllocationGate": passes,
        "passes": passes,
    }


def _safe_directory(path: Path, label: str) -> Path:
    resolved = path.resolve()
    info = resolved.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CanaryMvpError(f"{label} is not a safe directory")
    return resolved


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise CanaryMvpError(f"Conflicting immutable output: {path.name}")
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
