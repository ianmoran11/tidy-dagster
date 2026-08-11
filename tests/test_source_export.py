from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

import tidy_orchestrator.source_export as source_export_module
from tidy_orchestrator.artifacts import canonical_json_bytes, sha256_digest
from tidy_orchestrator.source_export import (
    HeadroomError,
    PolicyError,
    SourceExportError,
    SourceLimitError,
    SourceMutationError,
    SourceSafetyError,
    StorageProbe,
    build_inventory,
    freeze_snapshot,
    load_policy,
    publish_snapshot_to_nas,
    verify_export_wire,
    verify_nas_snapshot_publication,
)
from tidy_orchestrator.source_export_cli import main as source_export_main

PROJECT = Path(__file__).parents[1]
POLICY = PROJECT / "contracts/migration/v1/tidycell-source-policy.json"


def _policy_value(*, conflicting: bool = False) -> dict:
    rules = [
        {
            "id": "excluded-dependencies",
            "priority": 100,
            "entryTypes": ["directory"],
            "directoryNames": [".git", "node_modules"],
            "disposition": "exclude",
            "artifactClass": "development-subtree",
        },
        {
            "id": "workbook",
            "priority": 90,
            "entryTypes": ["file"],
            "suffixes": [".xlsx"],
            "disposition": "import",
            "artifactClass": "test-workbook",
        },
        {
            "id": "excluded-generated-symlink",
            "priority": 95,
            "entryTypes": ["symlink"],
            "basenameGlobs": ["ltmain.sh"],
            "disposition": "exclude",
            "artifactClass": "generated-symlink",
        },
        {
            "id": "recipe",
            "priority": 80,
            "entryTypes": ["file"],
            "basenameGlobs": ["*recipe*.json", "*.recipe.*"],
            "disposition": "import",
            "artifactClass": "recipe-evidence",
        },
    ]
    if conflicting:
        rules.append(
            {
                "id": "conflicting-workbook",
                "priority": 90,
                "entryTypes": ["file"],
                "suffixes": [".xlsx"],
                "disposition": "quarantine",
                "artifactClass": "conflict",
            }
        )
    return {
        "schemaVersion": "tidy.source-export-policy/v1",
        "policyId": "test-policy",
        "sourceSystem": "test-source",
        "limits": {
            "maxEntries": 1000,
            "maxFileBytes": 1024 * 1024,
            "maxJsonScanBytes": 1024 * 1024,
            "maxJsonDepth": 16,
            "maxEmbeddedRecordsPerFile": 100,
        },
        "rules": rules,
        "fallbackFile": {
            "ruleId": "fallback",
            "disposition": "exclude",
            "artifactClass": "unselected",
        },
    }


def _write_policy(tmp_path: Path, *, conflicting: bool = False) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(_policy_value(conflicting=conflicting)))
    return path


def _storage(*, passes: bool = True) -> StorageProbe:
    total = 100 * 1024**3
    if passes:
        return StorageProbe(
            total_bytes=total,
            used_bytes=10 * 1024**3,
            free_bytes=90 * 1024**3,
            device_id=7,
        )
    return StorageProbe(
        total_bytes=total,
        used_bytes=95 * 1024**3,
        free_bytes=5 * 1024**3,
        device_id=7,
    )


def _scan(
    tmp_path: Path,
    source: Path,
    *,
    event_hook=None,
    passes: bool = True,
):
    destination = tmp_path / "destination"
    policy = load_policy(_write_policy(tmp_path))
    return build_inventory(
        source_root=source,
        source_root_id="test-source-root",
        destination_root=destination,
        destination_id="test-destination",
        policy=policy,
        event_hook=event_hook,
        storage_probe=lambda _path: _storage(passes=passes),
    )


def _items(result) -> dict[str, dict]:
    return {item["relativePath"]: item for item in result.inventory["items"]}


def test_checked_in_policy_is_strict_and_loadable() -> None:
    policy = load_policy(POLICY)
    assert policy.policy_id == "tidycell-canonical-estate-2026-08-09"
    assert policy.source_system == "tidycell"
    assert len(policy.rules) == 18
    expected_schemas = {
        "export-item.schema.json": "ExportItemV1",
        "import-disposition.schema.json": "ImportDispositionV1",
        "inventory.schema.json": "TidyCellExportReportV1",
        "nas-commit.schema.json": "NasSnapshotCommitV1",
        "policy.schema.json": "tidy.source-export-policy/v1",
        "snapshot.schema.json": "TidyCellExportSnapshotV1",
        "source-closure-copy-commit.schema.json": "SourceClosureCopyCommitV1",
        "source-closure-discovery.schema.json": "SourceClosureDiscoveryV1",
        "source-closure-replay.schema.json": "SourceClosureReplayV1",
        "source-closure-review.schema.json": "SourceClosureSelfReviewV1",
        "source-code-snapshot.schema.json": "SourceCodeExportSnapshotV1",
    }
    assert {path.name for path in POLICY.parent.glob("*.schema.json")} == set(
        expected_schemas
    )
    for name, title in expected_schemas.items():
        value = json.loads((POLICY.parent / name).read_text())
        assert value["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert value["title"] == title


def test_migration_schemas_resolve_and_validate_strict_examples() -> None:
    schemas = {
        path.name: json.loads(path.read_text())
        for path in POLICY.parent.glob("*.schema.json")
    }
    registry = Registry()
    for schema in schemas.values():
        validator_for(schema).check_schema(schema)
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema),
        )

    policy_value = json.loads(POLICY.read_text())
    validator_for(schemas["policy.schema.json"])(
        schemas["policy.schema.json"],
        registry=registry,
    ).validate(policy_value)
    disposition_validator = validator_for(schemas["import-disposition.schema.json"])(
        schemas["import-disposition.schema.json"],
        registry=registry,
    )
    disposition_validator.validate("import")
    with pytest.raises(ValidationError):
        disposition_validator.validate("approved")

    digest = f"sha256:{'0' * 64}"
    export_item = {
        "relativePath": "book.xlsx",
        "entryType": "file",
        "artifactClass": "workbook",
        "disposition": "import",
        "ruleId": "workbook",
        "sourceMode": stat.S_IFREG | 0o600,
        "byteLength": 1,
        "contentDigest": digest,
        "gitState": "tracked",
        "embeddedRecords": [],
        "warnings": [],
    }
    export_item_validator = validator_for(schemas["export-item.schema.json"])(
        schemas["export-item.schema.json"],
        registry=registry,
    )
    export_item_validator.validate(export_item)
    invalid_item = copy.deepcopy(export_item)
    invalid_item["contentDigest"] = None
    with pytest.raises(ValidationError):
        export_item_validator.validate(invalid_item)

    source_code_snapshot = {
        "schemaVersion": "tidy.source-code-export-snapshot/v1",
        "completionStatus": "complete",
        "frozenAt": "2026-08-09T00:00:00Z",
        "source": {
            "sourceSystem": "tidybank",
            "sourceRootId": "tidybank-summary-closure",
            "filesystem": {
                "deviceId": 1,
                "rootInode": 2,
                "rootMode": stat.S_IFDIR | 0o700,
            },
            "git": {
                "available": False,
                "head": None,
                "tree": None,
                "trackedDirty": None,
                "trackedDirtyDigest": None,
            },
        },
        "selection": {
            "closureId": "summary-v1",
            "items": [
                {
                    "relativePath": "LICENSE",
                    "role": "license",
                    "sourceMode": stat.S_IFREG | 0o644,
                    "byteLength": 1,
                    "contentDigest": digest,
                }
            ],
        },
        "license": {"spdxId": "MIT", "contentDigest": digest},
        "exporter": {
            "version": "test-exporter/v1",
            "sourceDigest": digest,
            "canonicalizationAlgorithm": "tidy-python-sorted-json-v1",
        },
        "itemManifestDigest": digest,
        "snapshotDigest": digest,
    }
    source_code_validator = validator_for(schemas["source-code-snapshot.schema.json"])(
        schemas["source-code-snapshot.schema.json"],
        registry=registry,
    )
    source_code_validator.validate(source_code_snapshot)
    invalid = copy.deepcopy(source_code_snapshot)
    invalid["unexpected"] = True
    with pytest.raises(ValidationError):
        source_code_validator.validate(invalid)
    invalid_git = copy.deepcopy(source_code_snapshot)
    invalid_git["source"]["git"]["head"] = "0" * 40
    with pytest.raises(ValidationError):
        source_code_validator.validate(invalid_git)


def test_checked_in_policy_classifies_required_estate_paths() -> None:
    policy = load_policy(POLICY)
    assert policy.classify("approvals.json", "file") == (
        "approval-registry",
        "import",
        "approval-registry",
    )
    assert policy.classify("xlsx-examples/book.xlsx", "file")[2] == "workbook"
    assert (
        policy.classify(
            "scripts/experiments/cell-role-pipeline/prompts-v13.ts", "file"
        )[2]
        == "generation-source-code"
    )
    assert policy.classify("src/lib/summary/build.ts", "file")[2] == (
        "generation-source-code"
    )
    assert policy.classify("src/lib/ontology/codelist.ts", "file")[2] == (
        "generation-source-code"
    )
    assert policy.classify("node_modules", "directory")[1] == "exclude"
    assert policy.classify("ltmain.sh", "symlink")[1] == "exclude"
    assert policy.classify("operations/run/ltmain.sh", "symlink")[1] == "exclude"
    assert policy.classify("abs-spreadsheets/.DS_Store", "file")[1] == "exclude"
    assert policy.classify("unrelated.txt", "file") == (
        "not-approved-domain",
        "exclude",
        "unselected-source-file",
    )


def test_policy_rejects_unknown_fields_unsafe_paths_and_conflicts(
    tmp_path: Path,
) -> None:
    value = _policy_value()
    value["unknown"] = True
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(value))
    with pytest.raises(PolicyError, match="unknown fields"):
        load_policy(path)

    value = _policy_value()
    value["rules"][0]["pathPrefixes"] = ["../outside"]
    path.write_text(json.dumps(value))
    with pytest.raises(PolicyError, match="unsafe relative path"):
        load_policy(path)

    duplicate = json.dumps(_policy_value()).replace(
        '"policyId": "test-policy"',
        '"policyId": "first", "policyId": "second"',
    )
    path.write_text(duplicate)
    with pytest.raises(PolicyError, match="strict UTF-8 JSON"):
        load_policy(path)

    policy = load_policy(_write_policy(tmp_path, conflicting=True))
    with pytest.raises(PolicyError, match="Conflicting"):
        policy.classify("book.xlsx", "file")


def test_inventory_is_deterministic_deduplicated_and_discovers_embedded_records(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "node_modules").mkdir()
    (source / "a.xlsx").write_bytes(b"same-workbook")
    (source / "nested/b.xlsx").write_bytes(b"same-workbook")
    (source / "candidate.recipe.json").write_text(
        json.dumps(
            {
                "recipe": {"version": "RecipeV01"},
                "messages": [{"role": "user", "content": "prompt"}],
                "raw_response": "response",
            }
        )
    )
    (source / "notes.txt").write_text("excluded")
    (source / "node_modules/ignored.txt").write_text("not traversed")

    first = _scan(tmp_path, source)
    second = _scan(tmp_path, source)
    assert first.inventory == second.inventory
    assert first.inventory["inventoryDigest"] == second.inventory["inventoryDigest"]
    assert first.inventory["itemManifestDigest"].startswith("sha256:")
    assert first.inventory["safety"]["symlinkPolicy"] == (
        "no-follow-explicit-exclusion-only-v1"
    )
    items = _items(first)
    assert items["a.xlsx"]["disposition"] == "import"
    assert items["nested/b.xlsx"]["disposition"] == "duplicate-alias"
    assert items["notes.txt"]["disposition"] == "exclude"
    assert items["notes.txt"]["contentDigest"] == sha256_digest(b"excluded")
    assert stat.S_ISREG(items["notes.txt"]["sourceMode"])
    assert items["node_modules"]["entryType"] == "excluded-subtree"
    assert stat.S_ISDIR(items["node_modules"]["sourceMode"])
    assert "node_modules/ignored.txt" not in items
    embedded = items["candidate.recipe.json"]["embeddedRecords"]
    assert {item["kind"] for item in embedded} == {
        "recipe-document",
        "recipe-candidate",
        "prompt-evidence",
        "provider-response-evidence",
    }
    assert first.inventory["summary"]["uniqueImportObjects"] == 2
    filesystem = first.inventory["source"]["filesystem"]
    assert filesystem["deviceId"] == source.stat().st_dev
    assert filesystem["rootInode"] == source.stat().st_ino
    assert stat.S_ISDIR(filesystem["rootMode"])
    assert first.storage_assessment["passes"] is True


def test_malformed_protected_json_is_quarantined(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "candidate.recipe.json").write_text("{not-json")
    (source / "candidate.recipe.jsonl").write_text("{not-jsonl\n")
    result = _scan(tmp_path, source)
    item = _items(result)["candidate.recipe.json"]
    assert item["disposition"] == "quarantine"
    assert item["warnings"] == ["JSON_PARSE_FAILED"]
    jsonl = _items(result)["candidate.recipe.jsonl"]
    assert jsonl["disposition"] == "quarantine"
    assert jsonl["warnings"] == ["JSONL_PARSE_FAILED"]


def test_workbook_content_signatures_quarantine_invalid_and_disclose_conversion(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "legacy.xls").write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy")
    (source / "converted.xls").write_bytes(b"PK\x03\x04converted")
    (source / "invalid.xlsx").write_bytes(b"not-a-workbook")
    value = _policy_value()
    workbook_rule = next(rule for rule in value["rules"] if rule["id"] == "workbook")
    workbook_rule["artifactClass"] = "workbook"
    workbook_rule["suffixes"] = [".xls", ".xlsx"]
    policy_path = tmp_path / "workbook-policy.json"
    policy_path.write_text(json.dumps(value))
    result = build_inventory(
        source_root=source,
        source_root_id="test-source",
        destination_root=tmp_path / "destination",
        destination_id="test-destination",
        policy=load_policy(policy_path),
        storage_probe=lambda _path: _storage(),
    )
    items = _items(result)
    assert items["legacy.xls"]["disposition"] == "import"
    assert items["legacy.xls"]["warnings"] == []
    assert items["converted.xls"]["disposition"] == "import"
    assert items["converted.xls"]["warnings"] == ["WORKBOOK_EXTENSION_FORMAT_MISMATCH"]
    assert items["invalid.xlsx"]["disposition"] == "quarantine"
    assert items["invalid.xlsx"]["warnings"] == ["WORKBOOK_SIGNATURE_MISMATCH"]


def test_entry_and_file_limits_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"too-large")
    value = _policy_value()
    value["limits"]["maxFileBytes"] = 4
    policy_path = tmp_path / "small-file-policy.json"
    policy_path.write_text(json.dumps(value))
    with pytest.raises(SourceLimitError, match="maxFileBytes"):
        build_inventory(
            source_root=source,
            source_root_id="test-source",
            destination_root=tmp_path / "destination",
            destination_id="test-destination",
            policy=load_policy(policy_path),
            storage_probe=lambda _path: _storage(),
        )

    value["limits"]["maxFileBytes"] = 1024
    value["limits"]["maxEntries"] = 1
    policy_path.write_text(json.dumps(value))
    (source / "second.txt").write_text("second")
    with pytest.raises(SourceLimitError, match="maxEntries"):
        build_inventory(
            source_root=source,
            source_root_id="test-source",
            destination_root=tmp_path / "destination",
            destination_id="test-destination",
            policy=load_policy(policy_path),
            storage_probe=lambda _path: _storage(),
        )


def test_source_root_symlink_and_overlapping_destination_are_rejected(
    tmp_path: Path,
) -> None:
    real_source = tmp_path / "real-source"
    real_source.mkdir()
    linked_source = tmp_path / "linked-source"
    linked_source.symlink_to(real_source, target_is_directory=True)
    policy = load_policy(_write_policy(tmp_path))
    with pytest.raises(SourceSafetyError, match="non-symlink"):
        build_inventory(
            source_root=linked_source,
            source_root_id="test-source",
            destination_root=tmp_path / "destination",
            destination_id="test-destination",
            policy=policy,
            storage_probe=lambda _path: _storage(),
        )
    with pytest.raises(SourceSafetyError, match="inside source"):
        build_inventory(
            source_root=real_source,
            source_root_id="test-source",
            destination_root=real_source / "destination",
            destination_id="test-destination",
            policy=policy,
            storage_probe=lambda _path: _storage(),
        )


def test_symlink_and_special_file_fail_closed_without_following(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    victim = tmp_path / "victim.xlsx"
    victim.write_bytes(b"do-not-read-as-source")
    (source / "linked.xlsx").symlink_to(victim)
    with pytest.raises(SourceSafetyError, match="Symlink"):
        _scan(tmp_path, source)
    assert victim.read_bytes() == b"do-not-read-as-source"

    (source / "linked.xlsx").unlink()
    fifo = source / "pipe"
    os.mkfifo(fifo)
    try:
        with pytest.raises(SourceSafetyError, match="Special"):
            _scan(tmp_path, source)
    finally:
        fifo.unlink()


def test_explicitly_excluded_symlink_binds_target_without_following(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    link = source / "ltmain.sh"
    link.symlink_to("generated/missing-tool")
    result = _scan(tmp_path, source)
    item = _items(result)["ltmain.sh"]
    target = b"generated/missing-tool"
    assert item["entryType"] == "excluded-symlink"
    assert item["byteLength"] == len(target)
    assert item["contentDigest"] == sha256_digest(target)
    assert stat.S_ISLNK(item["sourceMode"])

    changed = False

    def mutate_symlink(event: str, path: Path) -> None:
        nonlocal changed
        if event == "after-symlink-read" and not changed:
            changed = True
            path.unlink()
            path.symlink_to("different-target")

    with pytest.raises(SourceMutationError, match="Symlink changed while reading"):
        _scan(tmp_path, source, event_hook=mutate_symlink)


def test_unreadable_in_scope_file_fails_closed(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"workbook")
    real_open = os.open

    def deny_book(path, flags, *args, **kwargs):
        if path == "book.xlsx" and kwargs.get("dir_fd") is not None:
            raise PermissionError("denied fixture")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr("tidy_orchestrator.source_export.os.open", deny_book)
    with pytest.raises(PermissionError, match="denied fixture"):
        _scan(tmp_path, source)


def test_file_and_directory_mutation_are_detected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    workbook = source / "book.xlsx"
    workbook.write_bytes(b"before")
    mutated = False

    def mutate_file(event: str, path: Path) -> None:
        nonlocal mutated
        if event == "after-file-read" and path.name == "book.xlsx" and not mutated:
            mutated = True
            path.write_bytes(b"different-size")

    with pytest.raises(SourceMutationError, match="changed while reading"):
        _scan(tmp_path, source, event_hook=mutate_file)

    workbook.write_bytes(b"stable")
    added = False

    def mutate_directory(event: str, _path: Path) -> None:
        nonlocal added
        if event == "before-final-verify" and not added:
            added = True
            (source / "late.txt").write_text("late")

    with pytest.raises(SourceMutationError, match="directory changed"):
        _scan(tmp_path, source, event_hook=mutate_directory)


def test_exporter_source_closure_mutation_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"workbook")
    digests = iter((f"sha256:{'1' * 64}", f"sha256:{'2' * 64}"))
    monkeypatch.setattr(
        source_export_module,
        "_exporter_source_digest",
        lambda: next(digests),
    )
    with pytest.raises(SourceMutationError, match="Exporter source closure changed"):
        _scan(tmp_path, source)


def test_excluded_subtree_is_opaque(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dependency = source / "node_modules"
    dependency.mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.write_text("safe")
    (dependency / "link").symlink_to(victim)
    result = _scan(tmp_path, source)
    assert _items(result)["node_modules"]["disposition"] == "exclude"
    assert victim.read_text() == "safe"


def test_git_evidence_distinguishes_tracked_untracked_and_ignored(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    (source / ".gitignore").write_text("ignored.xlsx\n")
    (source / "tracked.xlsx").write_bytes(b"tracked")
    subprocess.run(["git", "add", ".gitignore", "tracked.xlsx"], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=source,
        check=True,
    )
    (source / "ignored.xlsx").write_bytes(b"ignored")
    (source / "untracked.xlsx").write_bytes(b"untracked")
    result = _scan(tmp_path, source)
    items = _items(result)
    assert items["tracked.xlsx"]["gitState"] == "tracked"
    assert items["ignored.xlsx"]["gitState"] == "ignored"
    assert items["untracked.xlsx"]["gitState"] == "untracked"
    assert items[".git"]["entryType"] == "excluded-subtree"
    assert result.inventory["source"]["git"]["available"] is True
    assert result.inventory["source"]["git"]["trackedDirty"] is False


def test_export_verifier_rejects_tamper_and_unknown_fields(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"workbook")
    result = _scan(tmp_path, source)
    report = result.report_wire()
    assert verify_export_wire(report) == result.inventory["inventoryDigest"]

    tampered = copy.deepcopy(report)
    tampered["inventory"]["items"][0]["byteLength"] += 1
    with pytest.raises(SourceExportError, match="manifest digest mismatch"):
        verify_export_wire(tampered)

    unknown = copy.deepcopy(report)
    unknown["unexpected"] = True
    with pytest.raises(SourceExportError, match="fields"):
        verify_export_wire(unknown)


def test_headroom_assessment_and_freeze_gate(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"workbook")
    failed = _scan(tmp_path, source, passes=False)
    assert failed.storage_assessment["passes"] is False
    with pytest.raises(HeadroomError):
        freeze_snapshot(failed, frozen_at="2026-08-09T00:00:00Z")

    passed = _scan(tmp_path, source, passes=True)
    snapshot = freeze_snapshot(passed, frozen_at="2026-08-09T10:00:00+10:00")
    assert snapshot["completionStatus"] == "complete"
    assert snapshot["frozenAt"] == "2026-08-09T00:00:00Z"
    assert snapshot["inventory"] == passed.inventory
    assert snapshot["storageAssessmentDigest"].startswith("sha256:")
    assert snapshot["snapshotDigest"].startswith("sha256:")
    assert verify_export_wire(snapshot) == snapshot["snapshotDigest"]


def test_cli_writes_private_atomic_inventory_without_source_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    workbook = source / "book.xlsx"
    workbook.write_bytes(b"workbook")
    policy = _write_policy(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o755)
    reports.chmod(0o755)
    output = reports / "inventory.json"
    before = workbook.stat()
    arguments = [
        "inventory",
        "--source-root",
        str(source),
        "--source-root-id",
        "fixture-source",
        "--destination-root",
        str(tmp_path / "destination"),
        "--destination-id",
        "fixture-destination",
        "--policy",
        str(policy),
        "--output",
        str(output),
    ]
    assert source_export_main(arguments) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is True
    assert json.loads(output.read_text())["schemaVersion"] == (
        "tidy.source-export-report/v1"
    )
    assert output.stat().st_mode & 0o077 == 0
    assert reports.stat().st_mode & 0o777 == 0o755
    after = workbook.stat()
    assert (before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    assert source_export_main(arguments) == 1
    capsys.readouterr()
    assert source_export_main([*arguments, "--replace"]) == 0
    capsys.readouterr()
    assert source_export_main(["verify", "--input", str(output)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["verifiedDigest"].startswith("sha256:")


def test_nas_snapshot_publication_is_committed_idempotent_and_verified(
    tmp_path: Path,
    capsys,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"workbook")
    result = _scan(tmp_path, source)
    snapshot = freeze_snapshot(result, frozen_at="2026-08-09T00:00:00Z")
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(canonical_json_bytes(snapshot) + b"\n")
    destination = tmp_path / "nas"
    destination.mkdir()

    directory, commit, created = publish_snapshot_to_nas(
        snapshot_path=snapshot_path,
        destination_root=destination,
    )
    assert created is True
    assert sorted(path.name for path in directory.iterdir()) == [
        "COMMITTED.json",
        "snapshot.json",
    ]
    assert commit["snapshotDigest"] == snapshot["snapshotDigest"]
    assert commit["snapshotFileBytes"] == snapshot_path.stat().st_size
    assert verify_nas_snapshot_publication(directory) == commit
    assert directory.stat().st_mode & 0o077 == 0
    assert (directory / "snapshot.json").stat().st_mode & 0o077 == 0

    repeated_directory, repeated_commit, repeated_created = publish_snapshot_to_nas(
        snapshot_path=snapshot_path,
        destination_root=destination,
    )
    assert repeated_directory == directory
    assert repeated_commit == commit
    assert repeated_created is False

    assert (
        source_export_main(
            [
                "publish",
                "--input",
                str(snapshot_path),
                "--destination-root",
                str(destination),
            ]
        )
        == 0
    )
    published = json.loads(capsys.readouterr().out)
    assert published["created"] is False
    assert (
        source_export_main(["verify-publication", "--directory", str(directory)]) == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["snapshotDigest"] == snapshot["snapshotDigest"]

    commit_path = directory / "COMMITTED.json"
    commit_path.chmod(0o644)
    with pytest.raises(SourceSafetyError, match="not private"):
        verify_nas_snapshot_publication(directory)
    commit_path.chmod(0o600)


def test_nas_snapshot_publication_rejects_tamper_and_incomplete_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"workbook")
    snapshot = freeze_snapshot(
        _scan(tmp_path, source),
        frozen_at="2026-08-09T00:00:00Z",
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(canonical_json_bytes(snapshot) + b"\n")
    destination = tmp_path / "nas"
    destination.mkdir()
    directory, _commit, _created = publish_snapshot_to_nas(
        snapshot_path=snapshot_path,
        destination_root=destination,
    )
    (directory / "snapshot.json").write_bytes(b"{}\n")
    with pytest.raises(SourceExportError, match="Unsupported source-export"):
        verify_nas_snapshot_publication(directory)

    second = tmp_path / "second-nas"
    second.mkdir()
    incomplete = (
        second / "source-snapshots" / snapshot["snapshotDigest"].replace(":", "-")
    )
    incomplete.mkdir(parents=True)
    with pytest.raises(SourceExportError, match="unexpected files"):
        publish_snapshot_to_nas(
            snapshot_path=snapshot_path,
            destination_root=second,
        )
    assert incomplete.exists()


def test_nas_snapshot_publication_removes_failed_new_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "book.xlsx").write_bytes(b"workbook")
    snapshot = freeze_snapshot(
        _scan(tmp_path, source),
        frozen_at="2026-08-09T00:00:00Z",
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(canonical_json_bytes(snapshot) + b"\n")
    destination = tmp_path / "nas"
    destination.mkdir()
    original_rename = os.rename

    def fail_commit(source_path, destination_path, *args, **kwargs):
        if Path(destination_path).name == "COMMITTED.json":
            raise OSError("injected commit failure")
        return original_rename(source_path, destination_path, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_commit)
    with pytest.raises(OSError, match="injected commit failure"):
        publish_snapshot_to_nas(
            snapshot_path=snapshot_path,
            destination_root=destination,
        )
    final = (
        destination / "source-snapshots" / snapshot["snapshotDigest"].replace(":", "-")
    )
    assert not final.exists()


def test_cli_rejects_output_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    policy = _write_policy(tmp_path)
    assert (
        source_export_main(
            [
                "inventory",
                "--source-root",
                str(source),
                "--source-root-id",
                "fixture-source",
                "--destination-root",
                str(tmp_path / "destination"),
                "--destination-id",
                "fixture-destination",
                "--policy",
                str(policy),
                "--output",
                str(source / "inventory.json"),
            ]
        )
        == 1
    )
