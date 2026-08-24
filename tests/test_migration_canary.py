from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema.validators import validator_for

from tidy_orchestrator import migration_canary
from tidy_orchestrator.artifacts import domain_digest, sha256_digest
from tidy_orchestrator.migration_canary import (
    MigrationCanaryError,
    canonical_manifest_digest,
    load_canary_manifest,
    select_migration_canary,
    verify_migration_canary,
    write_canary_manifest,
)

PROJECT = Path(__file__).parents[1]
MANIFEST_SCHEMA = PROJECT / "contracts/migration-canary/v1/manifest.schema.json"
REVIEW_SCHEMA = PROJECT / "contracts/migration-canary/v1/review.schema.json"
CHECKED_MANIFEST = PROJECT / "fixtures/migration-canary/phase-b-canary-v1.json"
CHECKED_REVIEW = (
    PROJECT / "fixtures/migration-canary/phase-b-canary-v1.self-review.json"
)
CHECKED_SNAPSHOT = PROJECT / ".source-exports/tidycell-phase-a-snapshot-v1-final.json"
FROZEN_AT = "2026-08-11T20:00:00Z"
CURRENT_PRODUCER_DIGEST = (
    "sha256:5ed9f768dbb766c8c993cc64f81ea456d95a6d77730517889334dde27d0b9c41"
)


def _item(
    relative_path: str,
    *,
    artifact_class: str,
    disposition: str = "import",
    entry_type: str = "file",
    content: bytes | None = None,
    content_digest: str | None = None,
    byte_length: int | None = None,
    git_state: str = "tracked",
    warnings: tuple[str, ...] = (),
    embedded_kinds: tuple[str, ...] = (),
) -> dict:
    if entry_type == "excluded-subtree":
        digest = None
        length = 0
    elif entry_type == "excluded-symlink":
        payload = content or b"target"
        digest = content_digest or sha256_digest(payload)
        length = len(payload) if byte_length is None else byte_length
    else:
        payload = content if content is not None else relative_path.encode()
        digest = content_digest or sha256_digest(payload)
        length = len(payload) if byte_length is None else byte_length
    return {
        "relativePath": relative_path,
        "entryType": entry_type,
        "artifactClass": artifact_class,
        "disposition": disposition,
        "ruleId": f"rule-{artifact_class}",
        "sourceMode": 0o100600 if entry_type == "file" else 0o040700,
        "byteLength": length,
        "contentDigest": digest,
        "gitState": git_state,
        "embeddedRecords": [
            {"kind": kind, "pointer": f"/{index}", "valueType": "object"}
            for index, kind in enumerate(embedded_kinds)
        ],
        "warnings": list(warnings),
    }


def _group(
    prefix: str,
    size: int,
    *,
    canonical_class: str,
    alias_class: str | None = None,
) -> list[dict]:
    digest = sha256_digest(prefix.encode())
    return [
        _item(
            f"{prefix}/{index:02d}.json",
            artifact_class=(
                canonical_class if index == 0 else alias_class or canonical_class
            ),
            disposition="import" if index == 0 else "duplicate-alias",
            content_digest=digest,
            byte_length=len(prefix),
            git_state=("ignored" if index % 2 else "tracked"),
        )
        for index in range(size)
    ]


def _snapshot() -> dict:
    items = [
        *_group("pair", 2, canonical_class="research", alias_class="harvest"),
        *_group("small", 3, canonical_class="recipe"),
        *_group("large", 10, canonical_class="research"),
        _item(
            "approval.json",
            artifact_class="approval",
            embedded_kinds=(
                "recipe-document",
                "recipe-candidate",
                "prompt-evidence",
                "provider-response-evidence",
            ),
        ),
        _item(
            "empty.log",
            artifact_class="harvest",
            content=b"",
            git_state="untracked",
        ),
        _item(
            "large.json",
            artifact_class="ml",
            byte_length=2 * 1024 * 1024,
            warnings=("EMBEDDED_SCAN_SKIPPED_SIZE",),
        ),
        _item(
            "medium.json",
            artifact_class="catalog",
            byte_length=8192,
        ),
        _item(
            "record-limit.json",
            artifact_class="ml",
            warnings=("EMBEDDED_SCAN_RECORD_LIMIT",),
        ),
        _item(
            "format.xls",
            artifact_class="workbook",
            warnings=("WORKBOOK_EXTENSION_FORMAT_MISMATCH",),
        ),
        _item(
            "quarantine.json",
            artifact_class="recipe",
            disposition="quarantine",
        ),
        _item(
            "secret.env",
            artifact_class="secret",
            disposition="exclude",
        ),
        _item(
            "ignored-link",
            artifact_class="generated-link",
            disposition="exclude",
            entry_type="excluded-symlink",
            warnings=("SYMLINK_NOT_FOLLOWED",),
        ),
        _item(
            "ignored-tree",
            artifact_class="development-tree",
            disposition="exclude",
            entry_type="excluded-subtree",
        ),
    ]
    items.sort(key=lambda item: item["relativePath"])
    return {
        "schemaVersion": "tidy.source-export-snapshot/v1",
        "snapshotDigest": "sha256:" + "1" * 64,
        "inventory": {
            "inventoryDigest": "sha256:" + "2" * 64,
            "itemManifestDigest": "sha256:" + "3" * 64,
            "source": {
                "sourceSystem": "tidycell",
                "sourceRootId": "synthetic-source",
            },
            "items": items,
        },
    }


def _select(snapshot: dict | None = None) -> dict:
    return select_migration_canary(
        snapshot=snapshot or _snapshot(),
        snapshot_file_digest="sha256:" + "4" * 64,
        snapshot_file_bytes=1024,
        frozen_at=FROZEN_AT,
    )


def test_selector_is_deterministic_bounded_and_closes_duplicates(
    tmp_path: Path,
) -> None:
    first = _select()
    second = _select()
    assert first == second
    assert canonical_manifest_digest(first) == first["manifestDigest"]
    coverage = first["coverage"]
    limits = first["selector"]["limits"]
    assert coverage["itemCount"] <= limits["maximumItems"]
    assert coverage["sourceReadBytes"] <= limits["maximumSourceReadBytes"]
    assert coverage["uniqueCopyBytes"] <= limits["maximumUniqueCopyBytes"]
    assert coverage["embeddedRecordCount"] <= limits["maximumEmbeddedRecords"]
    assert set(coverage["countsByDisposition"]) == {
        "duplicate-alias",
        "exclude",
        "import",
        "quarantine",
    }
    assert set(coverage["warningCounts"]) == {
        "EMBEDDED_SCAN_RECORD_LIMIT",
        "EMBEDDED_SCAN_SKIPPED_SIZE",
        "SYMLINK_NOT_FOLLOWED",
        "WORKBOOK_EXTENSION_FORMAT_MISMATCH",
    }
    assert set(coverage["embeddedKindCounts"]) == {
        "recipe-document",
        "recipe-candidate",
        "prompt-evidence",
        "provider-response-evidence",
    }
    selected_paths = {item["relativePath"] for item in first["selectedItems"]}
    for item in first["selectedItems"]:
        if item["disposition"] == "duplicate-alias":
            assert item["canonicalImportPath"] in selected_paths
    assert all(req["status"] == "covered" for req in first["requirements"])

    output = tmp_path / "manifest.json"
    write_canary_manifest(output, first)
    assert load_canary_manifest(output) == first
    with pytest.raises(MigrationCanaryError, match="already exists"):
        write_canary_manifest(output, first)


def test_selector_rejects_unsorted_and_unselectable_snapshots() -> None:
    unsorted = _snapshot()
    unsorted["inventory"]["items"].reverse()
    with pytest.raises(MigrationCanaryError, match="uniquely sorted"):
        _select(unsorted)

    too_large = _snapshot()
    for item in too_large["inventory"]["items"]:
        if item["artifactClass"] == "approval":
            item["byteLength"] = 65 * 1024 * 1024
    with pytest.raises(MigrationCanaryError, match="hard bounds"):
        _select(too_large)


def test_manifest_digest_and_strict_json_reject_tamper(tmp_path: Path) -> None:
    manifest = _select()
    tampered = copy.deepcopy(manifest)
    tampered["gates"]["importAuthorized"] = True
    with pytest.raises(MigrationCanaryError, match="identity differs"):
        canonical_manifest_digest(tampered)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schemaVersion":"x","schemaVersion":"y"}')
    with pytest.raises(MigrationCanaryError, match="strict UTF-8 JSON"):
        load_canary_manifest(duplicate)


def test_checked_real_canary_and_self_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not CHECKED_SNAPSHOT.exists():
        pytest.skip("ignored Phase A snapshot is unavailable")
    manifest = json.loads(CHECKED_MANIFEST.read_text())
    schema = json.loads(MANIFEST_SCHEMA.read_text())
    validator = validator_for(schema)
    validator.check_schema(schema)
    validator(schema, format_checker=validator.FORMAT_CHECKER).validate(manifest)

    # The checked manifest is an authorization identity used by the executed
    # canary evidence chain. Its selection remains reproducible from the exact
    # Phase A snapshot, but unrelated, accepted dependency/CLI additions changed
    # the current producer-closure digest. Pin only that recorded producer input
    # while rebuilding every selected item and digest; separately bind the live
    # producer so this cannot become a blanket source-drift bypass.
    assert migration_canary._producer_source_digest() == CURRENT_PRODUCER_DIGEST
    recorded_producer_digest = manifest["selector"]["sourceDigest"]
    assert recorded_producer_digest != CURRENT_PRODUCER_DIGEST
    monkeypatch.setattr(
        migration_canary,
        "_producer_source_digest",
        lambda: recorded_producer_digest,
    )
    verify_migration_canary(manifest=manifest, snapshot_path=CHECKED_SNAPSHOT)
    assert manifest["manifestDigest"] == (
        "sha256:ee072650751fa76d456ba8cf034878a2a48137b02e6e7d459cb7945cb9474139"
    )
    assert manifest["coverage"]["itemCount"] == 63
    assert manifest["coverage"]["countsByArtifactClass"] == {
        "approval-registry": 1,
        "catalog-evidence": 2,
        "development-subtree": 1,
        "example-operation-evidence": 4,
        "generated-development-symlink": 1,
        "generation-json-evidence": 2,
        "generation-source-code": 5,
        "harvest-evidence": 7,
        "ml-evidence": 6,
        "model-binary": 2,
        "os-editor-metadata": 1,
        "recipe-evidence": 4,
        "research-evidence": 16,
        "secret-or-local-configuration": 1,
        "unselected-source-file": 1,
        "workbook": 5,
        "workbook-estate-evidence": 4,
    }
    assert [
        requirement["requirementId"]
        for requirement in manifest["requirements"]
        if requirement["status"] == "not-observed"
    ] == ["disposition:quarantine"]

    review = json.loads(CHECKED_REVIEW.read_text())
    review_schema = json.loads(REVIEW_SCHEMA.read_text())
    review_validator = validator_for(review_schema)
    review_validator.check_schema(review_schema)
    review_validator(
        review_schema, format_checker=review_validator.FORMAT_CHECKER
    ).validate(review)
    semantic = dict(review)
    review_digest = semantic.pop("reviewDigest")
    assert review_digest == domain_digest(
        "tidy.migration-canary-self-review/v1", semantic
    )
    assert review["canaryManifestDigest"] == manifest["manifestDigest"]
    assert review["independentReview"] is False
    assert review["authorizations"]["runCanaryImport"] is False
