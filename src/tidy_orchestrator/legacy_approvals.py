"""Strict, evidence-driven legacy approval snapshots and resolution.

No name/path heuristic may create approval authority. Historical TidyCell
``digestRecord`` values must be supplied by the independently vectored TypeScript
implementation; Python stores and checks those results but does not reimplement it.
"""

from __future__ import annotations

import json
import os
import platform
import stat
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .migration_import import (
    CommittedFilesystemBlobStore,
    MigrationImportError,
    MigrationRepository,
)

_DIGEST_RECORD_ALGORITHM = "tidycell-digest-record-v1"
_DIGEST_RECORD_SOURCE_DIGEST = (
    "sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c"
)
_DIGEST = "sha256:"
_MAX_APPROVAL_SNAPSHOT_BYTES = 64 * 1024 * 1024
_MAX_APPROVAL_ROWS = 100_000
_MAX_RESOLUTION_CANDIDATES = 10_000
_TARGET_BINDING_KINDS = frozenset(
    (
        "exact-workbook-digest",
        "conversion-provenance",
        "source-digest-chain",
        "explicit-human-binding",
    )
)


class ApprovalResolutionError(RuntimeError):
    """Approval evidence was malformed, conflicting, or non-deterministic."""


@dataclass(frozen=True)
class ApprovalTargetCandidate:
    workbook_digest: str
    sheet_name: str
    binding_kind: str
    evidence_digests: tuple[str, ...]
    recipe_digest: str | None = None

    def __post_init__(self) -> None:
        _require_digest(self.workbook_digest)
        if (
            not isinstance(self.sheet_name, str)
            or not self.sheet_name
            or len(self.sheet_name) > 4096
        ):
            raise ValueError("sheet_name is invalid")
        if self.binding_kind not in _TARGET_BINDING_KINDS:
            raise ValueError("binding_kind is not an authoritative target basis")
        if not self.evidence_digests:
            raise ValueError("evidence_digests must not be empty")
        for digest in self.evidence_digests:
            _require_digest(digest)
        if self.recipe_digest is not None:
            _require_digest(self.recipe_digest)

    def wire(self) -> dict[str, Any]:
        return {
            "workbookDigest": self.workbook_digest,
            "sheetName": self.sheet_name,
            "bindingKind": self.binding_kind,
            "recipeDigest": self.recipe_digest,
            "evidenceDigests": sorted(set(self.evidence_digests)),
        }


def create_reviewer_identity(
    *,
    display_name: str,
    accepted_labels: Sequence[str],
    curated_by: str,
    recorded_at: str,
) -> dict[str, Any]:
    if len(accepted_labels) > 100 or any(
        not isinstance(label, str) for label in accepted_labels
    ):
        raise ApprovalResolutionError("Reviewer identity labels are invalid")
    labels = sorted(set(accepted_labels))
    _require_utc_timestamp(recorded_at)
    if (
        not isinstance(display_name, str)
        or not display_name
        or not isinstance(curated_by, str)
        or not curated_by
        or len(display_name) > 256
        or len(curated_by) > 256
        or not labels
        or any(not label or len(label) > 256 for label in labels)
    ):
        raise ApprovalResolutionError("Reviewer identity fields must be non-empty")
    semantic = {
        "schemaVersion": "tidy.reviewer-identity/v1",
        "displayName": display_name,
        "acceptedLabels": labels,
        "curatedBy": curated_by,
        "recordedAt": recorded_at,
    }
    return {
        **semantic,
        "reviewerId": domain_digest("tidy.reviewer-identity/v1", semantic),
    }


class ReviewerIdentityRegistry:
    """Exact-label registry. It deliberately performs no case or typo repair."""

    def __init__(self, identities: Sequence[Mapping[str, Any]]) -> None:
        if len(identities) > 10_000:
            raise ApprovalResolutionError("Reviewer registry is too large")
        self._identities: dict[str, dict[str, Any]] = {}
        self._labels: dict[str, str] = {}
        for value in identities:
            identity = _validate_reviewer_identity(value)
            reviewer_id = identity["reviewerId"]
            existing = self._identities.get(reviewer_id)
            if existing is not None and existing != identity:
                raise ApprovalResolutionError("Conflicting reviewer identity")
            self._identities[reviewer_id] = identity
            for label in identity["acceptedLabels"]:
                owner = self._labels.get(label)
                if owner is not None and owner != reviewer_id:
                    raise ApprovalResolutionError(
                        f"Reviewer label {label!r} is assigned more than once"
                    )
                self._labels[label] = reviewer_id

    def resolve(self, label: str) -> dict[str, Any] | None:
        reviewer_id = self._labels.get(label)
        return None if reviewer_id is None else deepcopy(self._identities[reviewer_id])


def create_legacy_approval_snapshot(
    *,
    source_bytes: bytes,
    source_record_digests: Sequence[str],
    frozen_at: str,
    source_snapshot_digest: str,
    digest_verifier_digest: str,
    verifier_configuration_digest: str,
    verifier_isolation_mode: str,
    network_isolation_enforced: bool,
) -> dict[str, Any]:
    _require_digest(source_snapshot_digest)
    _require_digest(verifier_configuration_digest)
    _require_utc_timestamp(frozen_at)
    if verifier_isolation_mode not in {"macos-production", "insecure-test-only"}:
        raise ApprovalResolutionError("Approval verifier isolation mode is invalid")
    if not isinstance(
        network_isolation_enforced, bool
    ) or network_isolation_enforced is not (
        verifier_isolation_mode == "macos-production"
    ):
        raise ApprovalResolutionError("Approval verifier isolation claim is invalid")
    if len(source_bytes) > _MAX_APPROVAL_SNAPSHOT_BYTES:
        raise ApprovalResolutionError("Approval snapshot exceeds its byte limit")
    value = _strict_json(source_bytes)
    if set(value) != {"version", "approvals"}:
        raise ApprovalResolutionError("Approval registry fields do not match v1")
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["approvals"], list)
    ):
        raise ApprovalResolutionError("Approval registry version or rows are invalid")
    rows = value["approvals"]
    if len(rows) > _MAX_APPROVAL_ROWS:
        raise ApprovalResolutionError("Approval snapshot has too many rows")
    if len(rows) != len(source_record_digests):
        raise ApprovalResolutionError("Every approval row needs a digestRecord value")
    captured: list[dict[str, Any]] = []
    for index, (row, row_digest) in enumerate(
        zip(rows, source_record_digests, strict=True)
    ):
        _validate_source_row(row)
        captured.append(
            {
                "index": index,
                "sourceRecordDigest": _require_digest(row_digest),
                "sourceRow": row,
            }
        )
    semantic = {
        "schemaVersion": "tidy.legacy-approval-snapshot/v1",
        "sourceSnapshotDigest": source_snapshot_digest,
        "sourceContentDigest": sha256_digest(source_bytes),
        "sourceVersion": 1,
        "digestAlgorithm": _DIGEST_RECORD_ALGORITHM,
        "digestSourceDigest": _DIGEST_RECORD_SOURCE_DIGEST,
        "digestVerifierDigest": _require_digest(digest_verifier_digest),
        "verifierConfigurationDigest": verifier_configuration_digest,
        "verifierIsolationMode": verifier_isolation_mode,
        "networkIsolationEnforced": network_isolation_enforced,
        "frozenAt": frozen_at,
        "historyCompleteness": "point-in-time-current-state-only",
        "rows": captured,
    }
    return {
        **semantic,
        "approvalSnapshotId": domain_digest(
            "tidy.legacy-approval-snapshot/v1", semantic
        ),
    }


def persist_fixture_legacy_approval_snapshot(
    *,
    source_item: Mapping[str, Any],
    import_record: Mapping[str, Any],
    source_record_digests: Sequence[str],
    digest_verifier_digest: str,
    verifier_configuration_digest: str,
    verifier_isolation_mode: str,
    network_isolation_enforced: bool,
    frozen_at: str,
    metadata: MigrationRepository,
    blobs: CommittedFilesystemBlobStore,
) -> dict[str, Any]:
    """Bind one imported fixture registry to verified CAS bytes and store it."""

    _expected_item_digest, expected_content_digest = (
        _validate_imported_approval_binding(
            source_item=source_item,
            import_record=import_record,
            metadata=metadata,
        )
    )
    source_bytes = blobs.read_verified(
        _require_digest(expected_content_digest), int(source_item["byteLength"])
    )
    snapshot = create_legacy_approval_snapshot(
        source_bytes=source_bytes,
        source_record_digests=source_record_digests,
        frozen_at=frozen_at,
        source_snapshot_digest=import_record["snapshotDigest"],
        digest_verifier_digest=digest_verifier_digest,
        verifier_configuration_digest=verifier_configuration_digest,
        verifier_isolation_mode=verifier_isolation_mode,
        network_isolation_enforced=network_isolation_enforced,
    )
    metadata.add_typed_record(
        record_id=snapshot["approvalSnapshotId"],
        record_type=snapshot["schemaVersion"],
        record=snapshot,
    )
    return snapshot


def create_recipe_digest_verification(
    *,
    declared_digest: str,
    computed_digest: str,
    recipe_content_digest: str,
    source_snapshot_digest: str,
    source_item_digest: str,
    import_record_id: str,
    migration_worker_output_record_id: str,
    derivation_id: str,
    configuration_digest: str,
    producer_digests: Sequence[str],
    verifier_isolation_mode: str,
    network_isolation_enforced: bool,
) -> dict[str, Any]:
    declared = _require_digest(declared_digest)
    computed = _require_digest(computed_digest)
    producers = [_require_digest(value) for value in producer_digests]
    if not 1 <= len(producers) <= 4 or len(set(producers)) != len(producers):
        raise ApprovalResolutionError("Recipe verifier producers are invalid")
    if verifier_isolation_mode not in {"macos-production", "insecure-test-only"}:
        raise ApprovalResolutionError("Recipe verifier isolation mode is invalid")
    if network_isolation_enforced is not (
        verifier_isolation_mode == "macos-production"
    ):
        raise ApprovalResolutionError("Recipe verifier isolation claim is invalid")
    verifier_semantic = {
        "sourceSnapshotDigest": _require_digest(source_snapshot_digest),
        "sourceItemDigest": _require_digest(source_item_digest),
        "importRecordId": _require_digest(import_record_id),
        "migrationWorkerOutputRecordId": _require_digest(
            migration_worker_output_record_id
        ),
        "derivationId": _require_digest(derivation_id),
        "configurationDigest": _require_digest(configuration_digest),
        "producerDigests": producers,
        "verifierIsolationMode": verifier_isolation_mode,
        "networkIsolationEnforced": network_isolation_enforced,
    }
    semantic = {
        "schemaVersion": "tidy.recipe-digest-verification/v1",
        "algorithm": _DIGEST_RECORD_ALGORITHM,
        "sourceDigest": _DIGEST_RECORD_SOURCE_DIGEST,
        "declaredDigest": declared,
        "computedDigest": computed,
        "matches": declared == computed,
        "recipeContentDigest": _require_digest(recipe_content_digest),
        **verifier_semantic,
        "verificationAuthority": (
            "gateway-production"
            if network_isolation_enforced
            else "fixture-non-authoritative"
        ),
        "verifierDigest": domain_digest(
            "tidy.migration-recipe-digest-verifier/v1", verifier_semantic
        ),
    }
    return {
        **semantic,
        "verificationId": domain_digest("tidy.recipe-digest-verification/v1", semantic),
    }


def resolve_approval(
    *,
    approval_snapshot: Mapping[str, Any],
    source_row_index: int,
    candidates: Sequence[ApprovalTargetCandidate],
    reviewer_registry: ReviewerIdentityRegistry,
    recipe_verification: Mapping[str, Any] | None,
    recorded_at: str,
    metadata: MigrationRepository | None = None,
    blobs: CommittedFilesystemBlobStore | None = None,
    actor: str,
) -> dict[str, Any]:
    snapshot = _validate_approval_snapshot(approval_snapshot)
    if (
        not isinstance(source_row_index, int)
        or isinstance(source_row_index, bool)
        or not 0 <= source_row_index < len(snapshot["rows"])
    ):
        raise ApprovalResolutionError("Approval source row index is invalid")
    source = snapshot["rows"][source_row_index]
    if source["index"] != source_row_index:
        raise ApprovalResolutionError("Approval snapshot row order is invalid")
    source_row = source["sourceRow"]
    source_digest = source["sourceRecordDigest"]
    if len(candidates) > _MAX_RESOLUTION_CANDIDATES:
        raise ApprovalResolutionError("Approval has too many target candidates")
    if not isinstance(actor, str) or not actor or len(actor) > 256:
        raise ApprovalResolutionError("Resolution actor is invalid")
    _require_utc_timestamp(recorded_at)
    distinct_candidates = {
        canonical_json_bytes(candidate.wire()): candidate.wire()
        for candidate in candidates
    }
    candidate_wires = sorted(
        distinct_candidates.values(),
        key=lambda value: (
            value["workbookDigest"],
            value["sheetName"],
            value["recipeDigest"] or "",
            canonical_json_bytes(value),
        ),
    )
    unique_targets = sorted(
        {
            (candidate["workbookDigest"], candidate["sheetName"])
            for candidate in candidate_wires
        }
    )
    if not unique_targets:
        target_status = "unresolved"
    elif len(unique_targets) > 1:
        target_status = "ambiguous"
    else:
        target_status = "resolved"

    declared_recipe = source_row.get("recipeDigest")
    historical_original_recipe = source_row.get("originalRecipeDigest")
    verification = (
        None
        if recipe_verification is None
        else _validate_recipe_verification(recipe_verification)
    )
    conflict_reasons: list[str] = []
    incomplete_reasons: list[str] = []
    if snapshot["networkIsolationEnforced"] is not True:
        incomplete_reasons.append("DIGEST_VERIFIER_ISOLATION_INSUFFICIENT")
    approved_at = source_row.get("approvedAt")
    if (
        not isinstance(approved_at, str)
        or not approved_at.endswith("Z")
        or "T" not in approved_at
    ):
        incomplete_reasons.append("APPROVED_AT_MISSING_OR_INVALID")
    if any(
        candidate["sheetName"] != source_row["sheetName"]
        for candidate in candidate_wires
    ):
        conflict_reasons.append("CANDIDATE_SHEET_MISMATCH")
    harvest = source_row.get("harvest")
    if harvest is not None:
        if not isinstance(harvest, dict):
            conflict_reasons.append("INVALID_HARVEST_EVIDENCE")
        else:
            harvest_digest = harvest.get("workbookContentSha256")
            if not isinstance(harvest_digest, str):
                incomplete_reasons.append("HARVEST_WORKBOOK_DIGEST_MISSING")
            else:
                try:
                    _require_digest(harvest_digest)
                except ApprovalResolutionError:
                    conflict_reasons.append("INVALID_HARVEST_WORKBOOK_DIGEST")
                else:
                    if (
                        target_status == "resolved"
                        and harvest_digest != unique_targets[0][0]
                    ):
                        conflict_reasons.append("HARVEST_WORKBOOK_DIGEST_MISMATCH")
    if verification is not None:
        if verification["sourceSnapshotDigest"] != snapshot["sourceSnapshotDigest"]:
            conflict_reasons.append("RECIPE_VERIFICATION_SNAPSHOT_MISMATCH")
        if verification["verificationAuthority"] != "gateway-production":
            incomplete_reasons.append("RECIPE_VERIFIER_ISOLATION_INSUFFICIENT")
        if metadata is None:
            incomplete_reasons.append("RECIPE_VERIFICATION_NOT_PERSISTED")
        else:
            try:
                persisted_verification = metadata.get_typed_record(
                    record_id=verification["verificationId"],
                    record_type=verification["schemaVersion"],
                )
            except (MigrationImportError, ValueError):
                incomplete_reasons.append("RECIPE_VERIFICATION_NOT_PERSISTED")
            else:
                if persisted_verification != verification:
                    conflict_reasons.append("RECIPE_VERIFICATION_RECORD_MISMATCH")
                if blobs is None:
                    incomplete_reasons.append(
                        "RECIPE_WORKER_OUTPUT_CUSTODY_NOT_VERIFIED"
                    )
                    worker_output = None
                    worker_derivation = None
                else:
                    try:
                        worker_output = metadata.get_migration_worker_output(
                            verification["migrationWorkerOutputRecordId"],
                            blob_store=blobs,
                        )
                        worker_derivation = metadata.get_migration_worker_derivation(
                            verification["derivationId"]
                        )
                    except (MigrationImportError, ValueError):
                        incomplete_reasons.append("RECIPE_WORKER_OUTPUT_NOT_PERSISTED")
                        worker_output = None
                        worker_derivation = None
                if worker_output is not None and worker_derivation is not None:
                    expected_source = {
                        "sourceSnapshotDigest": verification["sourceSnapshotDigest"],
                        "sourceItemDigest": verification["sourceItemDigest"],
                        "importRecordId": verification["importRecordId"],
                        "sourceContentDigest": verification["recipeContentDigest"],
                    }
                    actual_source = worker_output.get("source")
                    if (
                        worker_output.get("operation") != "parse-recipe-v01"
                        or worker_output.get("derivationId")
                        != verification["derivationId"]
                        or worker_output.get("configurationDigest")
                        != verification["configurationDigest"]
                        or worker_output.get("isolationMode")
                        != verification["verifierIsolationMode"]
                        or worker_output.get("networkIsolationEnforced")
                        != verification["networkIsolationEnforced"]
                        or worker_derivation.get("producerDigests")
                        != verification["producerDigests"]
                        or not isinstance(actual_source, dict)
                        or any(
                            actual_source.get(key) != expected
                            for key, expected in expected_source.items()
                        )
                    ):
                        conflict_reasons.append("RECIPE_WORKER_OUTPUT_RECORD_MISMATCH")
    if isinstance(declared_recipe, str):
        if verification is None:
            incomplete_reasons.append("RECIPE_DIGEST_NOT_VERIFIED")
        elif (
            verification["declaredDigest"] != declared_recipe
            or not verification["matches"]
        ):
            conflict_reasons.append("RECIPE_DIGEST_MISMATCH")
        if target_status == "resolved":
            candidate_recipes = {
                candidate["recipeDigest"]
                for candidate in candidate_wires
                if candidate["recipeDigest"] is not None
            }
            if not candidate_recipes:
                incomplete_reasons.append("CANDIDATE_RECIPE_DIGEST_MISSING")
            elif candidate_recipes != {declared_recipe}:
                conflict_reasons.append("CANDIDATE_RECIPE_DIGEST_CONFLICT")
    elif verification is not None:
        conflict_reasons.append("UNDECLARED_RECIPE_DIGEST_VERIFICATION")
    if conflict_reasons:
        target_status = "conflict"

    approved_by = source_row.get("approvedBy")
    reviewer_identity = (
        reviewer_registry.resolve(approved_by)
        if isinstance(approved_by, str) and approved_by
        else None
    )
    if not isinstance(approved_by, str) or not approved_by:
        reviewer_status = "missing"
    elif reviewer_identity is None:
        reviewer_status = "unresolved"
    else:
        reviewer_status = "resolved"
        if metadata is None:
            incomplete_reasons.append("REVIEWER_IDENTITY_NOT_PERSISTED")
        else:
            try:
                persisted_reviewer = metadata.get_typed_record(
                    record_id=reviewer_identity["reviewerId"],
                    record_type=reviewer_identity["schemaVersion"],
                )
            except (MigrationImportError, ValueError):
                incomplete_reasons.append("REVIEWER_IDENTITY_NOT_PERSISTED")
            else:
                if persisted_reviewer != reviewer_identity:
                    conflict_reasons.append("REVIEWER_IDENTITY_RECORD_MISMATCH")

    if conflict_reasons:
        target_status = "conflict"
    if snapshot["networkIsolationEnforced"] is not True or target_status != "resolved":
        authority_state = "inactive"
    elif reviewer_status != "resolved":
        authority_state = "legacy_approved_unattributed"
    elif (
        not isinstance(declared_recipe, str)
        or verification is None
        or incomplete_reasons
    ):
        authority_state = "incomplete_evidence"
    elif not verification["matches"]:
        authority_state = "inactive"
    else:
        authority_state = "human_approved"

    target_digest = unique_targets[0][0] if target_status == "resolved" else None
    target_sheet = unique_targets[0][1] if target_status == "resolved" else None
    semantic = {
        "schemaVersion": "tidy.approval-resolution/v1",
        "approvalSnapshotId": snapshot["approvalSnapshotId"],
        "sourceRowIndex": source_row_index,
        "sourceRecordDigest": source_digest,
        "assetId": source_row["assetId"],
        "sheetName": source_row["sheetName"],
        "originalApprovedBy": approved_by if isinstance(approved_by, str) else None,
        "declaredRecipeDigest": (
            declared_recipe if isinstance(declared_recipe, str) else None
        ),
        "originalRecipeDigest": (
            historical_original_recipe
            if isinstance(historical_original_recipe, str)
            else None
        ),
        "targetStatus": target_status,
        "targetWorkbookDigest": target_digest,
        "targetSheetName": target_sheet,
        "candidates": candidate_wires,
        "conflictReasons": sorted(set(conflict_reasons)),
        "incompleteReasons": sorted(set(incomplete_reasons)),
        "reviewerStatus": reviewer_status,
        "reviewerId": (
            None if reviewer_identity is None else reviewer_identity["reviewerId"]
        ),
        "recipeVerificationId": (
            None if verification is None else verification["verificationId"]
        ),
        "authorityState": authority_state,
        "historyCompleteness": "point-in-time-current-state-only",
        "recordedAt": recorded_at,
        "actor": actor,
        "resolverDigest": _resolver_source_digest(),
    }
    return {
        **semantic,
        "resolutionId": domain_digest("tidy.approval-resolution/v1", semantic),
    }


def reconcile_fixture_approval_domain(
    *,
    source_item: Mapping[str, Any],
    import_record: Mapping[str, Any],
    approval_snapshot: Mapping[str, Any],
    resolutions: Sequence[Mapping[str, Any]],
    recorded_at: str,
    actor: str,
    metadata: MigrationRepository,
) -> dict[str, Any]:
    """Require one explicit resolution per observed fixture approval row."""

    if not isinstance(actor, str) or not actor or len(actor) > 256:
        raise ApprovalResolutionError("Approval reconciliation actor is invalid")
    _require_utc_timestamp(recorded_at)
    source_item_digest, source_content_digest = _validate_imported_approval_binding(
        source_item=source_item,
        import_record=import_record,
        metadata=metadata,
    )
    snapshot = _validate_approval_snapshot(approval_snapshot)
    if (
        snapshot["sourceSnapshotDigest"] != import_record["snapshotDigest"]
        or snapshot["sourceContentDigest"] != source_content_digest
    ):
        raise ApprovalResolutionError(
            "Approval snapshot does not bind the imported registry"
        )
    stored_snapshots = {
        record["approvalSnapshotId"]: record
        for record in metadata.list_typed_records(
            record_type="tidy.legacy-approval-snapshot/v1"
        )
    }
    if stored_snapshots.get(snapshot["approvalSnapshotId"]) != snapshot:
        raise ApprovalResolutionError("Stored approval snapshot differs")
    rows = snapshot["rows"]
    if len(resolutions) != len(rows):
        raise ApprovalResolutionError(
            "Every observed approval row requires one resolution"
        )
    stored_resolutions = {
        record["resolutionId"]: record
        for record in metadata.list_typed_records(
            record_type="tidy.approval-resolution/v1"
        )
    }
    by_index: dict[int, dict[str, Any]] = {}
    for value in resolutions:
        resolution = _validate_resolution_record(value)
        index = resolution["sourceRowIndex"]
        if (
            resolution["approvalSnapshotId"] != snapshot["approvalSnapshotId"]
            or not 0 <= index < len(rows)
            or index in by_index
        ):
            raise ApprovalResolutionError(
                "Approval resolution snapshot or row binding differs"
            )
        row = rows[index]
        source_row = row["sourceRow"]
        if (
            resolution["sourceRecordDigest"] != row["sourceRecordDigest"]
            or resolution["assetId"] != source_row["assetId"]
            or resolution["sheetName"] != source_row["sheetName"]
            or stored_resolutions.get(resolution["resolutionId"]) != resolution
        ):
            raise ApprovalResolutionError(
                "Approval resolution does not bind its observed row"
            )
        by_index[index] = resolution
    if set(by_index) != set(range(len(rows))):
        raise ApprovalResolutionError("Approval resolution row coverage differs")

    target_counts = {
        name: 0 for name in ("resolved", "ambiguous", "unresolved", "conflict")
    }
    reviewer_counts = {name: 0 for name in ("resolved", "unresolved", "missing")}
    authority_counts = {
        name: 0
        for name in (
            "human_approved",
            "legacy_approved_unattributed",
            "incomplete_evidence",
            "inactive",
        )
    }
    mappings: list[dict[str, Any]] = []
    for index in range(len(rows)):
        resolution = by_index[index]
        target_counts[resolution["targetStatus"]] += 1
        reviewer_counts[resolution["reviewerStatus"]] += 1
        authority_counts[resolution["authorityState"]] += 1
        mappings.append(
            {
                "sourceRowIndex": index,
                "sourceRecordDigest": rows[index]["sourceRecordDigest"],
                "resolutionId": resolution["resolutionId"],
                "targetStatus": resolution["targetStatus"],
                "reviewerStatus": resolution["reviewerStatus"],
                "authorityState": resolution["authorityState"],
            }
        )
    semantic = {
        "schemaVersion": "tidy.approval-domain-reconciliation/v1",
        "sourceSnapshotDigest": import_record["snapshotDigest"],
        "sourceItemDigest": source_item_digest,
        "sourceContentDigest": source_content_digest,
        "importRecordId": import_record["recordId"],
        "approvalSnapshotId": snapshot["approvalSnapshotId"],
        "producerDigest": _resolver_source_digest(),
        "status": "complete-for-observed-snapshot-no-activation-authority",
        "rowCount": len(rows),
        "resolutionCount": len(mappings),
        "targetStatusCounts": target_counts,
        "reviewerStatusCounts": reviewer_counts,
        "authorityStateCounts": authority_counts,
        "activationAuthorized": False,
        "trainingAuthorized": False,
        "mappings": mappings,
        "limitations": [
            "legacy registry history before this snapshot may be unrecoverable",
            "workbook acceptance manifests and output gates were not evaluated",
            "no effective recipe pointer was read or changed",
        ],
        "recordedAt": recorded_at,
        "actor": actor,
    }
    report = {
        **semantic,
        "recordId": domain_digest("tidy.approval-domain-reconciliation/v1", semantic),
    }
    metadata.add_typed_record(
        record_id=report["recordId"],
        record_type=report["schemaVersion"],
        record=report,
    )
    return report


def _validate_imported_approval_binding(
    *,
    source_item: Mapping[str, Any],
    import_record: Mapping[str, Any],
    metadata: MigrationRepository,
) -> tuple[str, str]:
    if source_item.get("artifactClass") != "approval-registry":
        raise ApprovalResolutionError("Source item is not an approval registry")
    expected_item_digest = domain_digest("tidy.export-item/v1", source_item)
    expected_final_state = {
        "import": "imported",
        "duplicate-alias": "duplicate-alias",
        "exclude": "excluded",
        "quarantine": "quarantined",
    }.get(source_item.get("disposition"))
    expected_content_digest = source_item.get("contentDigest")
    if (
        source_item.get("entryType") != "file"
        or expected_final_state is None
        or not isinstance(expected_content_digest, str)
        or import_record.get("schemaVersion") != "tidy.migration-import-item/v1"
        or import_record.get("snapshotDigest") is None
        or import_record.get("relativePath") != source_item.get("relativePath")
        or import_record.get("artifactClass") != "approval-registry"
        or import_record.get("classification") != "restricted"
        or import_record.get("sourceItemDigest") != expected_item_digest
        or import_record.get("sourceContentDigest") != expected_content_digest
        or import_record.get("byteLength") != source_item.get("byteLength")
        or import_record.get("sourceMode") != source_item.get("sourceMode")
        or import_record.get("proposedDisposition") != source_item.get("disposition")
        or import_record.get("finalState") != expected_final_state
        or import_record.get("blobStored") is not True
        or import_record.get("contentDigest") != expected_content_digest
        or import_record.get("storageUri") != f"cas+sha256://{expected_content_digest}"
    ):
        raise ApprovalResolutionError(
            "Imported approval registry does not bind its source item"
        )
    import_semantic = dict(import_record)
    import_record_id = import_semantic.pop("recordId", None)
    if import_record_id != domain_digest(
        "tidy.migration-import-item/v1", import_semantic
    ):
        raise ApprovalResolutionError("Imported approval registry digest differs")
    stored = metadata.get_item(
        import_record["snapshotDigest"], import_record["relativePath"]
    )
    if stored != dict(import_record):
        raise ApprovalResolutionError("Stored approval registry checkpoint differs")
    registration = metadata.get_snapshot_registration(import_record["snapshotDigest"])
    if registration.get("snapshotDigest") != import_record["snapshotDigest"]:
        raise ApprovalResolutionError("Approval registry snapshot is unregistered")
    return expected_item_digest, _require_digest(expected_content_digest)


def _validate_resolution_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schemaVersion") != "tidy.approval-resolution/v1":
        raise ApprovalResolutionError("Approval resolution version is invalid")
    identity = value.get("resolutionId")
    semantic = dict(value)
    semantic.pop("resolutionId", None)
    if identity != domain_digest("tidy.approval-resolution/v1", semantic):
        raise ApprovalResolutionError("Approval resolution digest differs")
    index = value.get("sourceRowIndex")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ApprovalResolutionError("Approval resolution row index is invalid")
    target_status = value.get("targetStatus")
    reviewer_status = value.get("reviewerStatus")
    authority_state = value.get("authorityState")
    if (
        target_status not in ("resolved", "ambiguous", "unresolved", "conflict")
        or reviewer_status not in ("resolved", "unresolved", "missing")
        or authority_state
        not in (
            "human_approved",
            "legacy_approved_unattributed",
            "incomplete_evidence",
            "inactive",
        )
    ):
        raise ApprovalResolutionError("Approval resolution outcome is invalid")
    if target_status == "resolved":
        _require_digest(value.get("targetWorkbookDigest"))
        if not isinstance(value.get("targetSheetName"), str):
            raise ApprovalResolutionError("Resolved approval target is invalid")
    elif (
        value.get("targetWorkbookDigest") is not None
        or value.get("targetSheetName") is not None
    ):
        raise ApprovalResolutionError("Unresolved approval target must be null")
    if authority_state == "human_approved" and (
        target_status != "resolved"
        or reviewer_status != "resolved"
        or value.get("conflictReasons")
        or value.get("incompleteReasons")
    ):
        raise ApprovalResolutionError("Human approval outcome is inconsistent")
    return dict(value)


def _validate_approval_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "sourceSnapshotDigest",
        "sourceContentDigest",
        "sourceVersion",
        "digestAlgorithm",
        "digestSourceDigest",
        "digestVerifierDigest",
        "verifierConfigurationDigest",
        "verifierIsolationMode",
        "networkIsolationEnforced",
        "frozenAt",
        "historyCompleteness",
        "rows",
        "approvalSnapshotId",
    }
    if (
        set(value) != required
        or value["schemaVersion"] != "tidy.legacy-approval-snapshot/v1"
        or type(value["sourceVersion"]) is not int
        or value["sourceVersion"] != 1
        or value["digestAlgorithm"] != _DIGEST_RECORD_ALGORITHM
        or value["digestSourceDigest"] != _DIGEST_RECORD_SOURCE_DIGEST
        or value["historyCompleteness"] != "point-in-time-current-state-only"
    ):
        raise ApprovalResolutionError("Legacy approval snapshot fields are invalid")
    for name in (
        "sourceSnapshotDigest",
        "sourceContentDigest",
        "digestVerifierDigest",
        "verifierConfigurationDigest",
    ):
        _require_digest(value[name])
    isolation_mode = value["verifierIsolationMode"]
    if isolation_mode not in {"macos-production", "insecure-test-only"} or value[
        "networkIsolationEnforced"
    ] is not (isolation_mode == "macos-production"):
        raise ApprovalResolutionError("Legacy approval isolation claim is invalid")
    _require_utc_timestamp(value["frozenAt"])
    rows = value["rows"]
    if not isinstance(rows, list) or len(rows) > _MAX_APPROVAL_ROWS:
        raise ApprovalResolutionError("Legacy approval snapshot rows are invalid")
    for expected_index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {
            "index",
            "sourceRecordDigest",
            "sourceRow",
        }:
            raise ApprovalResolutionError("Legacy approval snapshot row is invalid")
        if type(row["index"]) is not int or row["index"] != expected_index:
            raise ApprovalResolutionError("Legacy approval snapshot row order differs")
        _require_digest(row["sourceRecordDigest"])
        _validate_source_row(row["sourceRow"])
    semantic = dict(value)
    del semantic["approvalSnapshotId"]
    expected = domain_digest("tidy.legacy-approval-snapshot/v1", semantic)
    if value["approvalSnapshotId"] != expected:
        raise ApprovalResolutionError("Legacy approval snapshot digest differs")
    return deepcopy(dict(value))


def _validate_source_row(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApprovalResolutionError("Approval row must be an object")
    for name in ("assetId", "sheetName"):
        if (
            not isinstance(value.get(name), str)
            or not value[name]
            or len(value[name]) > 4096
        ):
            raise ApprovalResolutionError(f"Approval row {name} is invalid")
    for name in (
        "approvedAt",
        "approvedBy",
        "recipeDigest",
        "originalRecipeDigest",
    ):
        if name in value and not isinstance(value[name], str):
            raise ApprovalResolutionError(f"Approval row {name} must be a string")
    if isinstance(value.get("approvedBy"), str) and len(value["approvedBy"]) > 256:
        raise ApprovalResolutionError("Approval row approvedBy is too long")
    if isinstance(value.get("approvedAt"), str) and len(value["approvedAt"]) > 128:
        raise ApprovalResolutionError("Approval row approvedAt is too long")
    for name in ("recipeDigest", "originalRecipeDigest"):
        if isinstance(value.get(name), str):
            _require_digest(value[name])
    return value


def _validate_reviewer_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "displayName",
        "acceptedLabels",
        "curatedBy",
        "recordedAt",
        "reviewerId",
    }
    if set(value) != required or value["schemaVersion"] != "tidy.reviewer-identity/v1":
        raise ApprovalResolutionError("Reviewer identity fields are invalid")
    _require_utc_timestamp(value["recordedAt"])
    labels = value["acceptedLabels"]
    if (
        not isinstance(labels, list)
        or not labels
        or len(labels) > 100
        or any(
            not isinstance(label, str) or not label or len(label) > 256
            for label in labels
        )
        or not isinstance(value["displayName"], str)
        or not value["displayName"]
        or len(value["displayName"]) > 256
        or not isinstance(value["curatedBy"], str)
        or not value["curatedBy"]
        or len(value["curatedBy"]) > 256
    ):
        raise ApprovalResolutionError("Reviewer identity values are invalid")
    if labels != sorted(set(labels)):
        raise ApprovalResolutionError("Reviewer labels are not canonical")
    semantic = {key: value[key] for key in required if key != "reviewerId"}
    expected = domain_digest("tidy.reviewer-identity/v1", semantic)
    if value["reviewerId"] != expected:
        raise ApprovalResolutionError("Reviewer identity digest differs")
    return deepcopy(dict(value))


def _validate_recipe_verification(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "algorithm",
        "sourceDigest",
        "declaredDigest",
        "computedDigest",
        "matches",
        "recipeContentDigest",
        "sourceSnapshotDigest",
        "sourceItemDigest",
        "importRecordId",
        "migrationWorkerOutputRecordId",
        "derivationId",
        "configurationDigest",
        "producerDigests",
        "verifierIsolationMode",
        "networkIsolationEnforced",
        "verificationAuthority",
        "verifierDigest",
        "verificationId",
    }
    if (
        set(value) != required
        or value["schemaVersion"] != "tidy.recipe-digest-verification/v1"
        or value["algorithm"] != _DIGEST_RECORD_ALGORITHM
        or value["sourceDigest"] != _DIGEST_RECORD_SOURCE_DIGEST
    ):
        raise ApprovalResolutionError("Recipe verification fields are invalid")
    semantic = {key: value[key] for key in required if key != "verificationId"}
    for name in (
        "declaredDigest",
        "computedDigest",
        "recipeContentDigest",
        "sourceSnapshotDigest",
        "sourceItemDigest",
        "importRecordId",
        "migrationWorkerOutputRecordId",
        "derivationId",
        "configurationDigest",
        "verifierDigest",
    ):
        _require_digest(value[name])
    producers = value["producerDigests"]
    if (
        not isinstance(producers, list)
        or not 1 <= len(producers) <= 4
        or len(set(producers)) != len(producers)
    ):
        raise ApprovalResolutionError("Recipe verification producers are invalid")
    for producer in producers:
        _require_digest(producer)
    isolation_mode = value["verifierIsolationMode"]
    network_enforced = value["networkIsolationEnforced"]
    expected_authority = (
        "gateway-production"
        if isolation_mode == "macos-production" and network_enforced is True
        else "fixture-non-authoritative"
    )
    if (
        isolation_mode not in {"macos-production", "insecure-test-only"}
        or network_enforced is not (isolation_mode == "macos-production")
        or value["verificationAuthority"] != expected_authority
    ):
        raise ApprovalResolutionError("Recipe verification isolation differs")
    verifier_semantic = {
        "sourceSnapshotDigest": value["sourceSnapshotDigest"],
        "sourceItemDigest": value["sourceItemDigest"],
        "importRecordId": value["importRecordId"],
        "migrationWorkerOutputRecordId": value["migrationWorkerOutputRecordId"],
        "derivationId": value["derivationId"],
        "configurationDigest": value["configurationDigest"],
        "producerDigests": producers,
        "verifierIsolationMode": isolation_mode,
        "networkIsolationEnforced": network_enforced,
    }
    if value["verifierDigest"] != domain_digest(
        "tidy.migration-recipe-digest-verifier/v1", verifier_semantic
    ):
        raise ApprovalResolutionError("Recipe verifier evidence digest differs")
    if value["matches"] is not (value["declaredDigest"] == value["computedDigest"]):
        raise ApprovalResolutionError("Recipe verification match flag differs")
    expected = domain_digest("tidy.recipe-digest-verification/v1", semantic)
    if value["verificationId"] != expected:
        raise ApprovalResolutionError("Recipe verification digest differs")
    return dict(value)


def _strict_json(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            data,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ApprovalResolutionError(
            "Approval snapshot must be strict UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise ApprovalResolutionError("Approval snapshot must be an object")
    pending: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > 1_000_000 or depth > 128:
            raise ApprovalResolutionError(
                "Approval snapshot exceeds its JSON complexity limit"
            )
        if isinstance(current, list):
            pending.extend((entry, depth + 1) for entry in current)
        elif isinstance(current, dict):
            nodes += len(current)
            if nodes > 1_000_000:
                raise ApprovalResolutionError(
                    "Approval snapshot exceeds its JSON complexity limit"
                )
            pending.extend((entry, depth + 1) for entry in current.values())
    return value


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant {value}")


def _read_resolver_source(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 16 * 1024 * 1024:
            raise ApprovalResolutionError("Approval resolver source is not bounded")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
        ) or remaining:
            raise ApprovalResolutionError(
                "Approval resolver source changed while reading"
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _resolver_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = (
        project / "pyproject.toml",
        project / "uv.lock",
        Path(__file__),
        project / "contracts/import/v1/approval-domain-reconciliation.schema.json",
        project / "contracts/import/v1/approval-resolution.schema.json",
        project / "contracts/import/v1/legacy-approval-snapshot.schema.json",
        project / "contracts/import/v1/reviewer-identity.schema.json",
        project / "contracts/import/v1/recipe-digest-verification.schema.json",
        project / "contracts/import/v1/digest-record-vectors.schema.json",
        project / "fixtures/migration/digest-record-v1.json",
    )

    def capture() -> list[dict[str, str]]:
        return [
            {
                "relativePath": path.relative_to(project).as_posix(),
                "contentDigest": sha256_digest(_read_resolver_source(path)),
            }
            for path in paths
        ]

    files = capture()
    if capture() != files:
        raise ApprovalResolutionError("Approval resolver closure changed while hashing")
    return domain_digest(
        "tidy.approval-resolver-source-closure/v1",
        {
            "files": files,
            "runtime": {
                "pythonImplementation": platform.python_implementation(),
                "pythonVersion": platform.python_version(),
            },
        },
    )


def _require_utc_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise ApprovalResolutionError(f"Invalid canonical UTC timestamp {value!r}")
    return value


def _require_digest(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(_DIGEST) or len(value) != 71:
        raise ApprovalResolutionError(f"Invalid digest {value!r}")
    hexadecimal = value.split(":", 1)[1]
    if any(character not in "0123456789abcdef" for character in hexadecimal):
        raise ApprovalResolutionError(f"Invalid digest {value!r}")
    return value
