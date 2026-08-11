from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from tidy_orchestrator.artifacts import domain_digest, sha256_digest
from tidy_orchestrator.legacy_approvals import (
    ApprovalResolutionError,
    ApprovalTargetCandidate,
    ReviewerIdentityRegistry,
    create_legacy_approval_snapshot,
    create_recipe_digest_verification,
    create_reviewer_identity,
    resolve_approval,
)
from tidy_orchestrator.migration_import import (
    CommittedFilesystemBlobStore,
    MigrationRepository,
)

PROJECT = Path(__file__).parents[1]
CONTRACTS = PROJECT / "contracts/import/v1"
FIXED_TIME = "2026-08-10T09:00:00Z"
ACTOR = "phase-b-fixture-curator"


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _verifier_provenance(*, production: bool = True) -> dict:
    return {
        "verifier_configuration_digest": _digest("5"),
        "verifier_isolation_mode": (
            "macos-production" if production else "insecure-test-only"
        ),
        "network_isolation_enforced": production,
    }


def _reviewer():
    return create_reviewer_identity(
        display_name="Ian Moran",
        accepted_labels=["Ian Moran", "ian"],
        curated_by=ACTOR,
        recorded_at=FIXED_TIME,
    )


def _registry() -> ReviewerIdentityRegistry:
    return ReviewerIdentityRegistry([_reviewer()])


def _candidate(
    workbook: str = "a",
    *,
    sheet: str = "Table 1",
    recipe: str | None = None,
) -> ApprovalTargetCandidate:
    return ApprovalTargetCandidate(
        workbook_digest=_digest(workbook),
        sheet_name=sheet,
        binding_kind="exact-workbook-digest",
        recipe_digest=recipe,
        evidence_digests=(_digest("e"),),
    )


def _verification(*, declared: str = "b", computed: str = "b", production: bool = True):
    return create_recipe_digest_verification(
        declared_digest=_digest(declared),
        computed_digest=_digest(computed),
        recipe_content_digest=_digest("c"),
        source_snapshot_digest=_digest("3"),
        source_item_digest=_digest("6"),
        import_record_id=_digest("7"),
        migration_worker_output_record_id=_digest("8"),
        derivation_id=_digest("9"),
        configuration_digest=_digest("a"),
        producer_digests=[_digest("d"), _digest("e")],
        verifier_isolation_mode=(
            "macos-production" if production else "insecure-test-only"
        ),
        network_isolation_enforced=production,
    )


def _persisted_production_verification(
    tmp_path: Path, metadata: MigrationRepository
) -> tuple[dict, CommittedFilesystemBlobStore]:
    blobs = CommittedFilesystemBlobStore(tmp_path / "approval-worker-blobs")
    artifact_bytes = b"{}"
    output_digest = sha256_digest(artifact_bytes)
    blobs.publish_bytes(
        artifact_bytes,
        expected_digest=output_digest,
        expected_length=len(artifact_bytes),
    )
    derivation_semantic = {
        "operation": "parse-recipe-v01",
        "contractVersion": "tidy.migration-worker/v1",
        "orderedInputDigests": [_digest("c")],
        "configurationDigest": _digest("a"),
        "producerDigests": [_digest("d"), _digest("e")],
        "orderedOutputDigests": [output_digest],
    }
    derivation = {
        "schemaVersion": "tidy.migration-worker-derivation/v1",
        "derivationId": domain_digest("tidy.derivation/v1", derivation_semantic),
        **derivation_semantic,
    }
    reproduction_key = domain_digest(
        "tidy.reproduction-key/v1",
        {
            key: derivation_semantic[key]
            for key in (
                "operation",
                "contractVersion",
                "orderedInputDigests",
                "configurationDigest",
                "producerDigests",
            )
        },
    )
    fingerprint = domain_digest(
        "tidy.output-set/v1", [["recipe-revision.json", output_digest]]
    )
    output_semantic = {
        "schemaVersion": "tidy.migration-worker-output/v1",
        "operation": "parse-recipe-v01",
        "contractVersion": "tidy.migration-worker/v1",
        "source": {
            "sourceSnapshotDigest": _digest("3"),
            "sourceItemDigest": _digest("6"),
            "importRecordId": _digest("7"),
            "relativePath": "candidate.recipe.json",
            "sourceContentDigest": _digest("c"),
            "byteLength": 2,
        },
        "configurationDigest": _digest("a"),
        "producerDigest": _digest("d"),
        "derivationId": derivation["derivationId"],
        "reproductionKey": reproduction_key,
        "outputFingerprint": fingerprint,
        "outputIndex": 0,
        "name": "recipe-revision",
        "relativePath": "recipe-revision.json",
        "artifactSchemaVersion": "tidy.migration-recipe-revision/v1",
        "contentDigest": output_digest,
        "byteLength": len(artifact_bytes),
        "storageUri": blobs.storage_uri(output_digest),
        "isolationMode": "macos-production",
        "networkIsolationEnforced": True,
        "active": False,
        "trainingEligible": False,
    }
    output = {
        **output_semantic,
        "recordId": domain_digest("tidy.migration-worker-output/v1", output_semantic),
    }
    metadata.publish_migration_worker_bundle(
        outputs=[output],
        derivation=derivation,
        reproduction_key=reproduction_key,
        output_fingerprint=fingerprint,
        blob_store=blobs,
    )
    verification = create_recipe_digest_verification(
        declared_digest=_digest("b"),
        computed_digest=_digest("b"),
        recipe_content_digest=_digest("c"),
        source_snapshot_digest=_digest("3"),
        source_item_digest=_digest("6"),
        import_record_id=_digest("7"),
        migration_worker_output_record_id=output["recordId"],
        derivation_id=derivation["derivationId"],
        configuration_digest=_digest("a"),
        producer_digests=[_digest("d"), _digest("e")],
        verifier_isolation_mode="macos-production",
        network_isolation_enforced=True,
    )
    metadata.add_typed_record(
        record_id=verification["verificationId"],
        record_type=verification["schemaVersion"],
        record=verification,
    )
    return verification, blobs


def _rich_row(**updates):
    value = {
        "assetId": "asset-one",
        "sheetName": "Table 1",
        "approvedAt": FIXED_TIME,
        "approvedBy": "Ian Moran",
        "recipeDigest": _digest("b"),
        "harvest": {"workbookContentSha256": _digest("a")},
    }
    value.update(updates)
    return value


def _snapshot_for_row(row, *, production: bool = True):
    return create_legacy_approval_snapshot(
        source_bytes=json.dumps({"version": 1, "approvals": [row]}).encode(),
        source_record_digests=[_digest("f")],
        frozen_at=FIXED_TIME,
        source_snapshot_digest=_digest("3"),
        digest_verifier_digest=_digest("4"),
        **_verifier_provenance(production=production),
    )


def _resolve(
    row,
    *,
    candidates=None,
    verification=None,
    registry=None,
    metadata=None,
    blobs=None,
):
    return resolve_approval(
        approval_snapshot=_snapshot_for_row(row),
        source_row_index=0,
        candidates=(
            [_candidate(recipe=row.get("recipeDigest"))]
            if candidates is None
            else candidates
        ),
        reviewer_registry=_registry() if registry is None else registry,
        recipe_verification=(
            _verification()
            if verification is None and row.get("recipeDigest") == _digest("b")
            else verification
        ),
        recorded_at=FIXED_TIME,
        actor=ACTOR,
        metadata=metadata,
        blobs=blobs,
    )


def _schemas() -> tuple[dict[str, dict], Registry]:
    names = (
        "approval-resolution.schema.json",
        "digest-record-vectors.schema.json",
        "legacy-approval-snapshot.schema.json",
        "recipe-digest-verification.schema.json",
        "reviewer-identity.schema.json",
    )
    schemas = {name: json.loads((CONTRACTS / name).read_text()) for name in names}
    registry = Registry()
    for schema in schemas.values():
        validator_for(schema).check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return schemas, registry


def _validate(schema: dict, registry: Registry, value) -> None:
    validator_for(schema)(schema, registry=registry).validate(value)


def test_resolved_attributable_approval_requires_every_exact_binding(
    tmp_path: Path,
) -> None:
    row = _rich_row()
    reviewer = _reviewer()
    metadata = MigrationRepository(tmp_path / "approval-authority")
    verification, blobs = _persisted_production_verification(tmp_path, metadata)
    metadata.add_typed_record(
        record_id=reviewer["reviewerId"],
        record_type=reviewer["schemaVersion"],
        record=reviewer,
    )
    resolution = _resolve(
        row,
        verification=verification,
        metadata=metadata,
        blobs=blobs,
    )
    assert resolution["targetStatus"] == "resolved"
    assert resolution["reviewerStatus"] == "resolved"
    assert resolution["reviewerId"] == reviewer["reviewerId"]
    assert resolution["authorityState"] == "human_approved"
    assert resolution["conflictReasons"] == []
    assert resolution["incompleteReasons"] == []
    unpersisted = _resolve(row, verification=verification)
    assert unpersisted["authorityState"] == "incomplete_evidence"
    assert {
        "RECIPE_VERIFICATION_NOT_PERSISTED",
        "REVIEWER_IDENTITY_NOT_PERSISTED",
    }.issubset(unpersisted["incompleteReasons"])
    insecure = resolve_approval(
        approval_snapshot=_snapshot_for_row(row, production=False),
        source_row_index=0,
        candidates=[_candidate(recipe=_digest("b"))],
        reviewer_registry=_registry(),
        recipe_verification=verification,
        recorded_at=FIXED_TIME,
        actor=ACTOR,
    )
    assert insecure["authorityState"] == "inactive"
    assert "DIGEST_VERIFIER_ISOLATION_INSUFFICIENT" in insecure["incompleteReasons"]
    historical = _resolve(_rich_row(originalRecipeDigest=_digest("7")))
    assert historical["declaredRecipeDigest"] == _digest("b")
    assert historical["originalRecipeDigest"] == _digest("7")

    registry_bytes = json.dumps(
        {
            "version": 1,
            "approvals": [
                row,
                {"assetId": "asset-one", "sheetName": "Table 1", "approvedAt": ""},
            ],
        }
    ).encode()
    snapshot = create_legacy_approval_snapshot(
        source_bytes=registry_bytes,
        source_record_digests=[
            "sha256:e066f901e9cea168c0398213b98450414432542a15c34c97f7ee65ca36461712",
            "sha256:d4745ceb965818e2dd15c924193b7592199a75a0b781d4427aabe3e72537c6dd",
        ],
        frozen_at=FIXED_TIME,
        source_snapshot_digest=_digest("3"),
        digest_verifier_digest=_digest("4"),
        **_verifier_provenance(),
    )
    assert snapshot["historyCompleteness"] == "point-in-time-current-state-only"
    assert snapshot["digestAlgorithm"] == "tidycell-digest-record-v1"
    assert snapshot["digestSourceDigest"] == (
        "sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c"
    )
    assert snapshot["digestVerifierDigest"] == _digest("4")
    assert snapshot["rows"][0]["sourceRow"] == row

    schemas, registry = _schemas()
    vectors = json.loads(
        (PROJECT / "fixtures/migration/digest-record-v1.json").read_text()
    )
    _validate(schemas["digest-record-vectors.schema.json"], registry, vectors)
    assert len(vectors["vectors"]) == 18
    assert len({vector["id"] for vector in vectors["vectors"]}) == 18
    _validate(schemas["reviewer-identity.schema.json"], registry, reviewer)
    _validate(schemas["recipe-digest-verification.schema.json"], registry, verification)
    _validate(schemas["approval-resolution.schema.json"], registry, resolution)
    _validate(schemas["legacy-approval-snapshot.schema.json"], registry, snapshot)

    repository = MigrationRepository(tmp_path / "metadata")
    records = (
        (reviewer["reviewerId"], reviewer["schemaVersion"], reviewer),
        (
            verification["verificationId"],
            verification["schemaVersion"],
            verification,
        ),
        (resolution["resolutionId"], resolution["schemaVersion"], resolution),
        (snapshot["approvalSnapshotId"], snapshot["schemaVersion"], snapshot),
    )
    for record_id, record_type, record in records:
        repository.add_typed_record(
            record_id=record_id,
            record_type=record_type,
            record=record,
        )
        repository.add_typed_record(
            record_id=record_id,
            record_type=record_type,
            record=record,
        )
    assert len(repository.list_typed_records()) == 4
    assert (
        len(repository.list_typed_records(record_type="tidy.approval-resolution/v1"))
        == 1
    )

    conflicting = copy.deepcopy(resolution)
    conflicting["authorityState"] = "inactive"
    with pytest.raises(ValueError, match="identity digest differs"):
        repository.add_typed_record(
            record_id=resolution["resolutionId"],
            record_type=resolution["schemaVersion"],
            record=conflicting,
        )


def test_reviewer_labels_are_exact_and_simple_rows_remain_unattributed() -> None:
    typo = _resolve(_rich_row(approvedBy="ian "))
    assert typo["reviewerStatus"] == "unresolved"
    assert typo["authorityState"] == "legacy_approved_unattributed"

    case_changed = _resolve(_rich_row(approvedBy="IAN"))
    assert case_changed["reviewerStatus"] == "unresolved"

    simple = {"assetId": "simple", "sheetName": "Table 1", "approvedAt": ""}
    simple_resolution = _resolve(
        simple,
        candidates=[_candidate(recipe=None)],
        verification=None,
    )
    assert simple_resolution["targetStatus"] == "resolved"
    assert simple_resolution["reviewerStatus"] == "missing"
    assert simple_resolution["authorityState"] == "legacy_approved_unattributed"


def test_target_resolution_outcomes_and_conflicts_are_explicit() -> None:
    unresolved = _resolve(_rich_row(), candidates=[])
    assert unresolved["targetStatus"] == "unresolved"
    assert unresolved["authorityState"] == "inactive"

    ambiguous = _resolve(
        _rich_row(),
        candidates=[
            _candidate("a", recipe=_digest("b")),
            _candidate("9", recipe=_digest("b")),
        ],
    )
    assert ambiguous["targetStatus"] == "ambiguous"
    assert ambiguous["authorityState"] == "inactive"
    assert len(ambiguous["candidates"]) == 2

    digest_conflict = _resolve(
        _rich_row(),
        verification=_verification(declared="b", computed="8"),
    )
    assert digest_conflict["targetStatus"] == "conflict"
    assert "RECIPE_DIGEST_MISMATCH" in digest_conflict["conflictReasons"]

    sheet_conflict = _resolve(
        _rich_row(),
        candidates=[_candidate(sheet="Wrong sheet", recipe=_digest("b"))],
    )
    assert sheet_conflict["targetStatus"] == "conflict"
    assert "CANDIDATE_SHEET_MISMATCH" in sheet_conflict["conflictReasons"]


def test_missing_recipe_evidence_is_incomplete_not_human_approval() -> None:
    missing_time_row = _rich_row()
    del missing_time_row["approvedAt"]
    missing_time = _resolve(missing_time_row)
    assert missing_time["authorityState"] == "incomplete_evidence"
    assert "APPROVED_AT_MISSING_OR_INVALID" in missing_time["incompleteReasons"]

    missing_candidate_recipe = _resolve(
        _rich_row(),
        candidates=[_candidate(recipe=None)],
    )
    assert missing_candidate_recipe["targetStatus"] == "resolved"
    assert missing_candidate_recipe["authorityState"] == "incomplete_evidence"
    assert (
        "CANDIDATE_RECIPE_DIGEST_MISSING"
        in missing_candidate_recipe["incompleteReasons"]
    )

    row = _rich_row()
    unverified = resolve_approval(
        approval_snapshot=_snapshot_for_row(row),
        source_row_index=0,
        candidates=[_candidate(recipe=_digest("b"))],
        reviewer_registry=_registry(),
        recipe_verification=None,
        recorded_at=FIXED_TIME,
        actor=ACTOR,
    )
    assert unverified["targetStatus"] == "resolved"
    assert unverified["authorityState"] == "incomplete_evidence"
    assert "RECIPE_DIGEST_NOT_VERIFIED" in unverified["incompleteReasons"]


def test_snapshot_and_reviewer_registry_fail_closed() -> None:
    with pytest.raises(ApprovalResolutionError, match="strict UTF-8 JSON"):
        create_legacy_approval_snapshot(
            source_bytes=b'{"version":1,"version":1,"approvals":[]}',
            source_record_digests=[],
            frozen_at=FIXED_TIME,
            source_snapshot_digest=_digest("3"),
            digest_verifier_digest=_digest("4"),
            **_verifier_provenance(),
        )
    with pytest.raises(ApprovalResolutionError, match="Every approval row"):
        create_legacy_approval_snapshot(
            source_bytes=b'{"version":1,"approvals":[{"assetId":"a","sheetName":"s"}]}',
            source_record_digests=[],
            frozen_at=FIXED_TIME,
            source_snapshot_digest=_digest("3"),
            digest_verifier_digest=_digest("4"),
            **_verifier_provenance(),
        )

    first = create_reviewer_identity(
        display_name="First",
        accepted_labels=["shared"],
        curated_by=ACTOR,
        recorded_at=FIXED_TIME,
    )
    second = create_reviewer_identity(
        display_name="Second",
        accepted_labels=["shared"],
        curated_by=ACTOR,
        recorded_at=FIXED_TIME,
    )
    with pytest.raises(ApprovalResolutionError, match="assigned more than once"):
        ReviewerIdentityRegistry([first, second])
    with pytest.raises(ValueError, match="authoritative target basis"):
        ApprovalTargetCandidate(
            workbook_digest=_digest("a"),
            sheet_name="Table 1",
            binding_kind="display-name-heuristic",
            evidence_digests=(_digest("e"),),
        )

    snapshot = _snapshot_for_row(_rich_row())
    snapshot["rows"][0]["sourceRow"]["assetId"] = "substituted"
    with pytest.raises(ApprovalResolutionError, match="snapshot digest differs"):
        resolve_approval(
            approval_snapshot=snapshot,
            source_row_index=0,
            candidates=[_candidate(recipe=_digest("b"))],
            reviewer_registry=_registry(),
            recipe_verification=_verification(),
            recorded_at=FIXED_TIME,
            actor=ACTOR,
        )


def test_approval_resolution_schema_rejects_unknown_fields() -> None:
    resolution = _resolve(_rich_row())
    schemas, registry = _schemas()
    invalid = copy.deepcopy(resolution)
    invalid["unexpected"] = True
    with pytest.raises(ValidationError):
        _validate(schemas["approval-resolution.schema.json"], registry, invalid)
