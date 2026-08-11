"""Freeze exact historical reviewer-label confirmation requests.

This is read-only evidence preparation. It binds one Phase A approval registry,
retains exact labels without normalization or identity inference, and grants no
reviewer, recipe, activation, or training authority.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections import defaultdict
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest

SCHEMA_VERSION = "tidy.reviewer-label-confirmation-request/v1"
LABEL_EVIDENCE_VERSION = "tidy.reviewer-label-evidence/v1"
MAX_REGISTRY_BYTES = 2 * 1024 * 1024
MAX_APPROVAL_ROWS = 100_000
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ReviewerConfirmationError(RuntimeError):
    """Reviewer confirmation evidence could not be frozen safely."""


def freeze_reviewer_confirmation_request(
    *,
    snapshot_path: Path,
    source_root: Path,
    frozen_at: str,
) -> dict[str, Any]:
    if not _TIMESTAMP.fullmatch(frozen_at):
        raise ReviewerConfirmationError("Frozen time must be UTC to whole seconds")
    snapshot = _load_json(snapshot_path, "Phase A snapshot")
    inventory = _object(snapshot.get("inventory"), "Phase A inventory")
    items = inventory.get("items")
    if not isinstance(items, list):
        raise ReviewerConfirmationError("Phase A inventory items are invalid")
    matches = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("relativePath") == "approvals.json"
        and item.get("artifactClass") == "approval-registry"
    ]
    if len(matches) != 1:
        raise ReviewerConfirmationError(
            "Phase A must identify exactly one approvals.json registry"
        )
    item = matches[0]
    expected_digest = _digest(item.get("contentDigest"), "approval registry")
    expected_bytes = item.get("byteLength")
    if (
        not isinstance(expected_bytes, int)
        or not 0 <= expected_bytes <= MAX_REGISTRY_BYTES
    ):
        raise ReviewerConfirmationError("Approval registry byte length is invalid")

    data = _read_source_file_stably(source_root, "approvals.json", MAX_REGISTRY_BYTES)
    if len(data) != expected_bytes or sha256_digest(data) != expected_digest:
        raise ReviewerConfirmationError(
            "Approval registry bytes do not match frozen Phase A evidence"
        )
    registry = _parse_json_bytes(data, "approval registry")
    if set(registry) != {"version", "approvals"}:
        raise ReviewerConfirmationError("Approval registry root fields are unexpected")
    if not isinstance(registry["version"], int):
        raise ReviewerConfirmationError("Approval registry version is invalid")
    approvals = registry["approvals"]
    if not isinstance(approvals, list) or len(approvals) > MAX_APPROVAL_ROWS:
        raise ReviewerConfirmationError("Approval registry rows are invalid")

    occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_label_count = 0
    non_string_label_count = 0
    for index, row in enumerate(approvals):
        if not isinstance(row, dict):
            raise ReviewerConfirmationError(f"Approval row {index} is not an object")
        label = row.get("approvedBy")
        if label is None or label == "":
            missing_label_count += 1
            continue
        if not isinstance(label, str):
            non_string_label_count += 1
            continue
        occurrences[label].append(
            {
                "rowIndex": index,
                "rowDigest": domain_digest("tidy.approval-row/v1", row),
            }
        )

    labels = []
    for label in sorted(occurrences):
        evidence = occurrences[label]
        semantic = {
            "schemaVersion": LABEL_EVIDENCE_VERSION,
            "exactLabel": label,
            "occurrenceCount": len(evidence),
            "firstRowIndex": evidence[0]["rowIndex"],
            "lastRowIndex": evidence[-1]["rowIndex"],
            "occurrenceEvidenceDigest": domain_digest(
                "tidy.reviewer-label-occurrences/v1", evidence
            ),
            "status": "pending-human-confirmation",
            "confirmedHumanIdentity": None,
            "humanDecisionDigest": None,
        }
        labels.append(
            {
                **semantic,
                "labelEvidenceDigest": domain_digest(LABEL_EVIDENCE_VERSION, semantic),
            }
        )

    semantic_record = {
        "schemaVersion": SCHEMA_VERSION,
        "source": {
            "sourceSnapshotDigest": _digest(snapshot.get("snapshotDigest"), "snapshot"),
            "inventoryDigest": _digest(inventory.get("inventoryDigest"), "inventory"),
            "relativePath": "approvals.json",
            "sourceContentDigest": expected_digest,
            "byteLength": expected_bytes,
            "registryVersion": registry["version"],
        },
        "approvalRowCount": len(approvals),
        "labelledRowCount": sum(len(value) for value in occurrences.values()),
        "missingLabelCount": missing_label_count,
        "nonStringLabelCount": non_string_label_count,
        "distinctExactLabelCount": len(labels),
        "labels": labels,
        "reviewMethod": "implementing-agent-read-only-freeze",
        "independentReview": False,
        "reviewerAuthorityCreated": False,
        "approvalAuthorityCreated": False,
        "activationAuthorized": False,
        "trainingAuthorized": False,
        "limitations": [
            "Exact historical labels are evidence, not verified human identities.",
            "Every identity mapping requires an explicit later human decision "
            "bound to this record.",
            "Rows without an exact string approvedBy label remain unattributed.",
        ],
        "frozenAt": frozen_at,
    }
    return {
        **semantic_record,
        "requestDigest": domain_digest(SCHEMA_VERSION, semantic_record),
    }


def write_confirmation_request(path: Path, record: dict[str, Any]) -> None:
    data = canonical_json_bytes(record) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_source_file_stably(root: Path, name: str, maximum: int) -> bytes:
    root_before = root.lstat()
    if not stat.S_ISDIR(root_before.st_mode) or stat.S_ISLNK(root_before.st_mode):
        raise ReviewerConfirmationError("Approval source root must be a real directory")
    root_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    root_descriptor = os.open(root, root_flags)
    descriptor = -1
    try:
        before = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ReviewerConfirmationError(
                "Approval registry must be a bounded regular file"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(name, flags, dir_fd=root_descriptor)
        opened = os.fstat(descriptor)
        if _file_identity(opened) != _file_identity(before):
            raise ReviewerConfirmationError("Approval registry identity changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ReviewerConfirmationError(
                    "Approval registry exceeds its byte limit"
                )
        after = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
        if _file_identity(before) != _file_identity(after):
            raise ReviewerConfirmationError("Approval registry changed during the read")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_descriptor)
    root_after = root.lstat()
    if _file_identity(root_before) != _file_identity(root_after):
        raise ReviewerConfirmationError("Approval source root changed during the read")
    return b"".join(chunks)


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ReviewerConfirmationError(
            f"{description} is not readable JSON"
        ) from error
    return _object(value, description)


def _parse_json_bytes(data: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewerConfirmationError(f"{description} is not valid JSON") from error
    return _object(value, description)


def _object(value: object, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewerConfirmationError(f"{description} must be an object")
    return value


def _digest(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ReviewerConfirmationError(f"{description} digest is invalid")
    return value
