"""Strict, evidence-driven legacy approval snapshots and resolution.

No name/path heuristic may create approval authority. Historical TidyCell
``digestRecord`` values must be supplied by the independently vectored TypeScript
implementation; Python stores and checks those results but does not reimplement it.
"""

from __future__ import annotations

import json
import platform
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest

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
) -> dict[str, Any]:
    _require_digest(source_snapshot_digest)
    _require_utc_timestamp(frozen_at)
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


def create_recipe_digest_verification(
    *,
    declared_digest: str,
    computed_digest: str,
    recipe_content_digest: str,
    verifier_digest: str,
) -> dict[str, Any]:
    declared = _require_digest(declared_digest)
    computed = _require_digest(computed_digest)
    semantic = {
        "schemaVersion": "tidy.recipe-digest-verification/v1",
        "algorithm": _DIGEST_RECORD_ALGORITHM,
        "sourceDigest": _DIGEST_RECORD_SOURCE_DIGEST,
        "declaredDigest": declared,
        "computedDigest": computed,
        "matches": declared == computed,
        "recipeContentDigest": _require_digest(recipe_content_digest),
        "verifierDigest": _require_digest(verifier_digest),
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

    if target_status != "resolved":
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


def _validate_approval_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "sourceSnapshotDigest",
        "sourceContentDigest",
        "sourceVersion",
        "digestAlgorithm",
        "digestSourceDigest",
        "digestVerifierDigest",
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
    ):
        _require_digest(value[name])
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
        "verifierDigest",
    ):
        _require_digest(value[name])
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


@lru_cache(maxsize=1)
def _resolver_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = [project / "pyproject.toml", project / "uv.lock", Path(__file__)]
    paths.extend(
        sorted(
            (project / "contracts/import/v1").glob("*approval*.schema.json"),
            key=lambda path: path.name,
        )
    )
    paths.extend(
        sorted(
            (project / "contracts/import/v1").glob("*reviewer*.schema.json"),
            key=lambda path: path.name,
        )
    )
    paths.append(project / "contracts/import/v1/recipe-digest-verification.schema.json")
    paths.append(project / "contracts/import/v1/digest-record-vectors.schema.json")
    paths.append(project / "fixtures/migration/digest-record-v1.json")

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
