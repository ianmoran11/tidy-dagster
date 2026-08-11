import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from tidy_orchestrator.artifacts import canonical_json_bytes, domain_digest
from tidy_orchestrator.reviewer_confirmation import (
    DECISION_VERSION,
    LABEL_EVIDENCE_VERSION,
    SCHEMA_VERSION,
    ReviewerConfirmationError,
    create_reviewer_confirmation_decision,
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


def test_decision_confirms_only_selected_exact_labels(tmp_path: Path) -> None:
    snapshot, source = _fixture(tmp_path)
    request = freeze_reviewer_confirmation_request(
        snapshot_path=snapshot,
        source_root=source,
        frozen_at=FIXED_TIME,
    )
    decision = create_reviewer_confirmation_decision(
        request=request,
        display_name="Ian Moran",
        confirmed_labels=["Ian", "lan"],
        curated_by="Ian Moran via interactive confirmation",
        selected_answer="Ian and lan",
        recorded_at="2026-08-12T04:35:00Z",
    )
    assert decision["reviewerIdentity"]["acceptedLabels"] == ["Ian", "lan"]
    assert [entry["decision"] for entry in decision["decisions"]] == [
        "left-unattributed",
        "confirmed-human-identity",
        "confirmed-human-identity",
    ]
    assert decision["reviewerIdentityAuthorized"] is True
    assert decision["approvalAuthorityCreated"] is False
    digest = decision.pop("decisionDigest")
    assert domain_digest(DECISION_VERSION, decision) == digest
    with pytest.raises(ReviewerConfirmationError, match="exact labels"):
        create_reviewer_confirmation_decision(
            request=request,
            display_name="Ian Moran",
            confirmed_labels=["ian"],
            curated_by="Ian Moran via interactive confirmation",
            selected_answer="invalid typo-normalized label",
            recorded_at="2026-08-12T04:35:00Z",
        )


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


def test_frozen_interactive_decision_confirms_all_three_exact_labels() -> None:
    decision = json.loads(
        (
            ROOT / "fixtures/reviewer-confirmation/ian-moran-label-decision-v1.json"
        ).read_text()
    )
    schema = json.loads(
        (
            ROOT
            / "contracts/import/v1/reviewer-label-confirmation-decision.schema.json"
        ).read_text()
    )
    identity_schema = json.loads(
        (ROOT / "contracts/import/v1/reviewer-identity.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(decision)
    jsonschema.Draft202012Validator(
        identity_schema, format_checker=jsonschema.FormatChecker()
    ).validate(decision["reviewerIdentity"])
    digest = decision.pop("decisionDigest")
    assert digest == (
        "sha256:c3d06cb56ddf2d955f7e016b3166abca4b7c8db24ca979106d05d3ec62a73a61"
    )
    assert domain_digest(DECISION_VERSION, decision) == digest
    assert decision["requestDigest"] == (
        "sha256:b6fca8497fcdaf2050be62b0b5322fa2aed970f4d34e8e43a89fd7148fe04df5"
    )
    assert decision["reviewerIdentity"]["acceptedLabels"] == ["Good", "Ian", "lan"]
    assert decision["reviewerIdentity"]["reviewerId"] == (
        "sha256:497aeb26fa36b5116cd3bedb7e1c1f2ed89b4825c0ed087bcc62de039794d3a8"
    )
    assert all(
        entry["decision"] == "confirmed-human-identity"
        for entry in decision["decisions"]
    )
    assert decision["confirmation"]["selectedAnswer"] == "All three labels"
    assert decision["reviewerIdentityAuthorized"] is True
    assert decision["approvalAuthorityCreated"] is False
    assert decision["activationAuthorized"] is False
    assert decision["trainingAuthorized"] is False


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
