import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from tidy_orchestrator.artifacts import canonical_json_bytes, domain_digest
from tidy_orchestrator.reviewer_confirmation import (
    LABEL_EVIDENCE_VERSION,
    SCHEMA_VERSION,
    ReviewerConfirmationError,
    freeze_reviewer_confirmation_request,
    write_confirmation_request,
)

ROOT = Path(__file__).parents[1]
FIXED_TIME = "2026-08-12T04:30:00Z"


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    registry = {
        "version": 1,
        "approvals": [
            {"assetId": "a", "sheetName": "S", "approvedBy": "Ian"},
            {"assetId": "b", "sheetName": "S", "approvedBy": "lan"},
            {"assetId": "c", "sheetName": "S", "approvedBy": "Ian"},
            {"assetId": "d", "sheetName": "S", "approvedBy": "Good"},
            {"assetId": "e", "sheetName": "S"},
        ],
    }
    data = canonical_json_bytes(registry)
    (source / "approvals.json").write_bytes(data)
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    snapshot = {
        "snapshotDigest": "sha256:" + "1" * 64,
        "inventory": {
            "inventoryDigest": "sha256:" + "2" * 64,
            "items": [
                {
                    "relativePath": "approvals.json",
                    "artifactClass": "approval-registry",
                    "contentDigest": digest,
                    "byteLength": len(data),
                }
            ],
        },
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(canonical_json_bytes(snapshot))
    return snapshot_path, source


def test_freezes_exact_labels_without_identity_inference(tmp_path: Path) -> None:
    snapshot, source = _fixture(tmp_path)
    record = freeze_reviewer_confirmation_request(
        snapshot_path=snapshot,
        source_root=source,
        frozen_at=FIXED_TIME,
    )
    assert record["approvalRowCount"] == 5
    assert record["labelledRowCount"] == 4
    assert record["missingLabelCount"] == 1
    assert record["nonStringLabelCount"] == 0
    assert [label["exactLabel"] for label in record["labels"]] == [
        "Good",
        "Ian",
        "lan",
    ]
    assert [label["occurrenceCount"] for label in record["labels"]] == [1, 2, 1]
    assert all(
        label["status"] == "pending-human-confirmation" for label in record["labels"]
    )
    assert all(label["confirmedHumanIdentity"] is None for label in record["labels"])
    for label in record["labels"]:
        digest = label["labelEvidenceDigest"]
        semantic = {
            key: value for key, value in label.items() if key != "labelEvidenceDigest"
        }
        assert domain_digest(LABEL_EVIDENCE_VERSION, semantic) == digest
    request_digest = record.pop("requestDigest")
    assert domain_digest(SCHEMA_VERSION, record) == request_digest
    assert record["reviewerAuthorityCreated"] is False
    assert record["activationAuthorized"] is False
    assert record["trainingAuthorized"] is False


def test_output_is_canonical_and_schema_valid(tmp_path: Path) -> None:
    snapshot, source = _fixture(tmp_path)
    record = freeze_reviewer_confirmation_request(
        snapshot_path=snapshot,
        source_root=source,
        frozen_at=FIXED_TIME,
    )
    output = tmp_path / "evidence/request.json"
    write_confirmation_request(output, record)
    assert output.read_bytes() == canonical_json_bytes(record) + b"\n"
    schema = json.loads(
        (
            ROOT / "contracts/import/v1/reviewer-label-confirmation-request.schema.json"
        ).read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(record)


def test_frozen_real_confirmation_request_is_non_authoritative() -> None:
    record = json.loads(
        (
            ROOT / "fixtures/reviewer-confirmation/historical-label-request-v1.json"
        ).read_text()
    )
    schema = json.loads(
        (
            ROOT / "contracts/import/v1/reviewer-label-confirmation-request.schema.json"
        ).read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(record)
    request_digest = record.pop("requestDigest")
    assert request_digest == (
        "sha256:b6fca8497fcdaf2050be62b0b5322fa2aed970f4d34e8e43a89fd7148fe04df5"
    )
    assert domain_digest(SCHEMA_VERSION, record) == request_digest
    assert record["approvalRowCount"] == 331
    assert record["labelledRowCount"] == 266
    assert record["missingLabelCount"] == 65
    assert [
        (entry["exactLabel"], entry["occurrenceCount"]) for entry in record["labels"]
    ] == [
        ("Good", 2),
        ("Ian", 260),
        ("lan", 4),
    ]
    assert all(
        entry["status"] == "pending-human-confirmation" for entry in record["labels"]
    )
    assert record["reviewerAuthorityCreated"] is False
    assert record["approvalAuthorityCreated"] is False
    assert record["activationAuthorized"] is False
    assert record["trainingAuthorized"] is False


def test_fails_closed_on_mutated_or_linked_registry(tmp_path: Path) -> None:
    snapshot, source = _fixture(tmp_path)
    (source / "approvals.json").write_text("{}")
    with pytest.raises(ReviewerConfirmationError, match="frozen Phase A"):
        freeze_reviewer_confirmation_request(
            snapshot_path=snapshot,
            source_root=source,
            frozen_at=FIXED_TIME,
        )

    (source / "approvals.json").unlink()
    target = tmp_path / "target.json"
    target.write_text("{}")
    (source / "approvals.json").symlink_to(target)
    with pytest.raises(ReviewerConfirmationError, match="regular file"):
        freeze_reviewer_confirmation_request(
            snapshot_path=snapshot,
            source_root=source,
            frozen_at=FIXED_TIME,
        )
