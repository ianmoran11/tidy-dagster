from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from tidy_orchestrator.artifacts import domain_digest
from tidy_orchestrator.source_closure_cli import main as source_closure_main
from tidy_orchestrator.source_closure_copy import (
    SourceClosureCopyConflict,
    copy_source_closure,
    verify_source_closure_copy,
)
from tidy_orchestrator.source_closure_discovery import (
    SourceClosureDiscoveryError,
    SourceClosureSourceMismatch,
    _producer_source_digest,
    canonical_manifest_digest,
    discover_source_closure,
    load_discovery_request,
    verify_source_closure,
)
from tidy_orchestrator.source_export import (
    StorageProbe,
    build_inventory,
    freeze_snapshot,
    load_policy,
)

PROJECT = Path(__file__).parents[1]
SCHEMA = PROJECT / "contracts/migration/v1/source-closure-discovery.schema.json"
REVIEW_SCHEMA = PROJECT / "contracts/migration/v1/source-closure-review.schema.json"
CHECKED_MANIFEST = (
    PROJECT / "fixtures/source-closure/summary-prompt-closure-v1.discovery.json"
)
CHECKED_REVIEW = (
    PROJECT / "fixtures/source-closure/summary-prompt-closure-v1.self-review.json"
)
CHECKED_COPY = (
    PROJECT
    / "reference/source-closures"
    / "sha256-3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17"
)
CHECKED_REPLAY = (
    PROJECT / "fixtures/source-closure/summary-prompt-closure-v1.replay.json"
)
FROZEN_AT = "2026-08-11T01:00:00Z"
CURRENT_MANIFEST_DIGEST = (
    "sha256:71535242ef44cb3a486c4fef7f1493b4e838b89a7d947b3a13a8ad0734f89a3d"
)
HISTORICAL_COPY_MANIFEST_DIGEST = (
    "sha256:3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17"
)
HISTORICAL_COPY_COMMIT_DIGEST = (
    "sha256:579ca12438a6a0a89bbf54fdbb7d9c2b4f506db9c98a5f65e9d8697192e92799"
)


def _git(root: Path, *arguments: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    result = subprocess.run(
        [executable, *arguments],
        cwd=root,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": FROZEN_AT,
            "GIT_COMMITTER_DATE": FROZEN_AT,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(root: Path, source_system: str) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "LICENSE").write_text("MIT fixture licence\n")
    (root / "package.json").write_text(
        json.dumps(
            {"name": f"{source_system}-fixture", "dependencies": {"zod": "1.0.0"}}
        )
    )
    (root / "package-lock.json").write_text(
        json.dumps({"name": f"{source_system}-fixture", "lockfileVersion": 3})
    )
    (root / "src/types.ts").write_text("export type Name = string;\n")
    (root / "src/helper.ts").write_text(
        'import type { Name } from "@/types";\n'
        "export const helper = (name: Name) => name;\n"
    )
    (root / "src/extra.ts").write_text("export const extra = 1;\n")
    (root / "src/main.ts").write_text(
        'import { z } from "zod";\n'
        'import { helper } from "@/helper";\n'
        'import { extra } from "./extra.js";\n'
        "export const summary = helper(z.string().parse(String(extra)));\n"
    )
    (root / "src/main.test.ts").write_text(
        'import { summary } from "./main";\nexport const expected = summary;\n'
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Fixture Curator")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "add", "--all")
    _git(root, "commit", "-q", "-m", "fixture source")
    return root


def _phase_a_snapshot(tmp_path: Path, source: Path) -> tuple[Path, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    policy_value = {
        "schemaVersion": "tidy.source-export-policy/v1",
        "policyId": "source-closure-test-policy",
        "sourceSystem": "tidycell",
        "limits": {
            "maxEntries": 1000,
            "maxFileBytes": 1024 * 1024,
            "maxJsonScanBytes": 1024 * 1024,
            "maxJsonDepth": 16,
            "maxEmbeddedRecordsPerFile": 100,
        },
        "rules": [
            {
                "id": "excluded-git",
                "priority": 100,
                "entryTypes": ["directory"],
                "directoryNames": [".git"],
                "disposition": "exclude",
                "artifactClass": "development-subtree",
            }
        ],
        "fallbackFile": {
            "ruleId": "source",
            "disposition": "import",
            "artifactClass": "generation-source-code",
        },
    }
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_value))
    result = build_inventory(
        source_root=source,
        source_root_id="tidycell-fixture-phase-a",
        destination_root=tmp_path / "destination",
        destination_id="fixture-destination",
        policy=load_policy(policy_path),
        storage_probe=lambda _path: StorageProbe(
            total_bytes=100 * 1024**3,
            used_bytes=10 * 1024**3,
            free_bytes=90 * 1024**3,
            device_id=7,
        ),
    )
    snapshot = freeze_snapshot(result, frozen_at=FROZEN_AT)
    path = tmp_path / "phase-a.json"
    path.write_text(json.dumps(snapshot))
    return path, snapshot


def _selection():
    return {
        "entrypoints": [
            {"relativePath": "src/main.ts", "role": "source"},
            {"relativePath": "src/main.test.ts", "role": "fixture"},
        ],
        "metadata": [
            {"relativePath": "LICENSE", "role": "license"},
            {"relativePath": "package.json", "role": "manifest"},
            {"relativePath": "package-lock.json", "role": "lockfile"},
        ],
    }


def _request(tmp_path: Path) -> tuple[dict, Path, Path]:
    tidycell = _repository(tmp_path / "tidycell", "tidycell")
    tidybank = _repository(tmp_path / "tidybank", "tidybank")
    snapshot_path, snapshot = _phase_a_snapshot(tmp_path, tidycell)
    selection = _selection()
    request = {
        "schemaVersion": "tidy.source-closure-discovery-request/v1",
        "closureId": "fixture-summary-prompt-closure-v1",
        "frozenAt": FROZEN_AT,
        "maxFiles": 100,
        "maxTotalBytes": 1024 * 1024,
        "sources": [
            {
                "sourceSystem": "tidycell",
                "readMode": "phase-a-filesystem",
                "sourceRoot": str(tidycell),
                "sourceRootId": "tidycell-fixture-phase-a",
                "phaseASnapshotPath": str(snapshot_path),
                "expectedSnapshotDigest": snapshot["snapshotDigest"],
                **selection,
            },
            {
                "sourceSystem": "tidybank",
                "readMode": "git-object",
                "sourceRoot": str(tidybank),
                "sourceRootId": "tidybank-fixture-commit",
                "commit": _git(tidybank, "rev-parse", "HEAD"),
                **selection,
            },
        ],
    }
    return request, tidycell, tidybank


def _validate_schema(manifest: dict) -> None:
    schema = json.loads(SCHEMA.read_text())
    validator_for(schema).check_schema(schema)
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    validator_for(schema)(schema, registry=registry).validate(manifest)


def test_discovers_exact_two_source_closure_without_copying(tmp_path: Path) -> None:
    request, tidycell, tidybank = _request(tmp_path)
    before = {
        root.name: sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if ".git" not in path.parts
        )
        for root in (tidycell, tidybank)
    }
    first = discover_source_closure(request)
    second = discover_source_closure(request)
    assert first == second
    verify_source_closure(manifest=first, request=request)
    assert canonical_manifest_digest(first) == first["manifestDigest"]
    _validate_schema(first)

    assert first["completionStatus"] == "complete-no-copy"
    assert first["selectionPolicy"]["sourceBytesCopied"] is False
    assert first["selectionPolicy"]["unresolvedRelativeImportCount"] == 0
    assert [source["sourceSystem"] for source in first["sources"]] == [
        "tidybank",
        "tidycell",
    ]
    for source in first["sources"]:
        paths = [item["relativePath"] for item in source["items"]]
        assert paths == sorted(
            [
                "LICENSE",
                "package-lock.json",
                "package.json",
                "src/extra.ts",
                "src/helper.ts",
                "src/main.test.ts",
                "src/main.ts",
                "src/types.ts",
            ]
        )
        assert source["externalImports"] == [
            {"specifier": "zod", "importedBy": ["src/main.ts"]}
        ]
        assert source["authority"]["selectedBytesMatchAuthority"] is True
    tidybank_manifest = first["sources"][0]
    assert all(item["gitBlobId"] for item in tidybank_manifest["items"])
    assert all(item["phaseADisposition"] is None for item in tidybank_manifest["items"])
    tidycell_manifest = first["sources"][1]
    assert all(item["gitBlobId"] is None for item in tidycell_manifest["items"])
    assert all(
        item["phaseADisposition"] in {"import", "duplicate-alias"}
        for item in tidycell_manifest["items"]
    )
    after = {
        root.name: sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if ".git" not in path.parts
        )
        for root in (tidycell, tidybank)
    }
    assert after == before


def test_phase_a_mutation_and_symlink_fail_while_git_object_ignores_worktree(
    tmp_path: Path,
) -> None:
    request, tidycell, tidybank = _request(tmp_path)
    original = discover_source_closure(request)
    (tidybank / "src/main.ts").write_text("dirty worktree is not authority\n")
    assert discover_source_closure(request) == original

    (tidycell / "src/main.ts").write_text("changed after Phase A\n")
    with pytest.raises(SourceClosureSourceMismatch, match="differ from Phase A"):
        discover_source_closure(request)
    (tidycell / "src/main.ts").unlink()
    (tidycell / "src/main.ts").symlink_to(tidycell / "src/helper.ts")
    with pytest.raises(SourceClosureDiscoveryError, match="opened safely"):
        discover_source_closure(request)


def test_unresolved_relative_import_and_bounds_fail_closed(tmp_path: Path) -> None:
    request, tidycell, _tidybank = _request(tmp_path)
    (tidycell / "src/main.ts").write_text('import "./missing";\n')
    # Re-freeze the fixture authority so this case reaches import resolution.
    snapshot_path, snapshot = _phase_a_snapshot(tmp_path / "second", tidycell)
    tidycell_request = next(
        source for source in request["sources"] if source["sourceSystem"] == "tidycell"
    )
    tidycell_request["phaseASnapshotPath"] = str(snapshot_path)
    tidycell_request["expectedSnapshotDigest"] = snapshot["snapshotDigest"]
    with pytest.raises(SourceClosureDiscoveryError, match="Unresolved relative import"):
        discover_source_closure(request)

    bounded = copy.deepcopy(request)
    bounded["maxFiles"] = 1
    with pytest.raises(SourceClosureDiscoveryError, match="file bound"):
        discover_source_closure(bounded)


def test_discovery_json_reader_rejects_duplicates_nonfinite_and_depth(
    tmp_path: Path,
) -> None:
    path = tmp_path / "request.json"
    for data, message in (
        (b'{"schemaVersion":"a","schemaVersion":"b"}', "strict JSON"),
        (b'{"value":NaN}', "strict JSON"),
        (b"[" * 200 + b"0" + b"]" * 200, "JSON depth limit"),
    ):
        path.write_bytes(data)
        with pytest.raises(SourceClosureDiscoveryError, match=message):
            load_discovery_request(path)


def test_reviewed_closure_copy_is_atomic_relocatable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    request, _tidycell, _tidybank = _request(tmp_path / "inputs")
    manifest = discover_source_closure(request)
    config_path = tmp_path / "request.json"
    manifest_path = tmp_path / "manifest.json"
    review_path = tmp_path / "review.json"
    config_path.write_text(json.dumps(request))
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    review_semantic = {
        "schemaVersion": "tidy.source-closure-self-review/v1",
        "closureManifestDigest": manifest["manifestDigest"],
        "reviewKind": "implementing-agent-self-review",
        "status": "accepted-for-bounded-copy-and-parity-work",
        "reviewedAt": FROZEN_AT,
        "reviewer": "tidy-dagster-implementing-agent",
        "checks": [
            {
                "id": f"fixture-review-{index}",
                "status": "pass",
                "evidence": [manifest["manifestDigest"]],
            }
            for index in range(6)
        ],
        "claims": {
            "independentReview": False,
            "parityEstablished": False,
            "runtimeSiblingDependencyAllowed": False,
            "sourceBytesCopied": False,
        },
        "limitations": [
            "fixture implementing-agent self-review",
            "fixture parity is not established",
            "fixture runtime is not authorized",
        ],
    }
    review = {
        **review_semantic,
        "reviewDigest": domain_digest(
            "tidy.source-closure-self-review/v1", review_semantic
        ),
    }
    review_path.write_text(json.dumps(review, sort_keys=True))
    destination_parent = tmp_path / "copies"
    destination_parent.mkdir()
    destination = destination_parent / "closure"
    commit = copy_source_closure(
        request_path=config_path,
        manifest_path=manifest_path,
        review_path=review_path,
        destination=destination,
        copied_at=FROZEN_AT,
    )
    assert commit["sourceBytesCopied"] is True
    assert commit["runtimeAuthorized"] is False
    assert commit["parityEstablished"] is False
    assert commit["itemCount"] == 16
    assert verify_source_closure_copy(destination) == commit
    assert not any(path.is_symlink() for path in destination.rglob("*"))
    with pytest.raises(SourceClosureCopyConflict, match="already exists"):
        copy_source_closure(
            request_path=config_path,
            manifest_path=manifest_path,
            review_path=review_path,
            destination=destination,
            copied_at=FROZEN_AT,
        )
    copied_source = destination / "sources/tidycell/src/main.ts"
    copied_source.write_text("tampered\n")
    with pytest.raises(SourceClosureCopyConflict, match="item differs"):
        verify_source_closure_copy(destination)


def test_checked_in_real_discovery_and_self_review_are_internally_verified() -> None:
    manifest = json.loads(CHECKED_MANIFEST.read_text())
    review = json.loads(CHECKED_REVIEW.read_text())
    _validate_schema(manifest)
    review_schema = json.loads(REVIEW_SCHEMA.read_text())
    validator_for(review_schema).check_schema(review_schema)
    validator_for(review_schema)(review_schema).validate(review)

    assert canonical_manifest_digest(manifest) == CURRENT_MANIFEST_DIGEST
    assert manifest["totals"] == {
        "sourceCount": 2,
        "itemCount": 140,
        "byteLength": 4_781_394,
    }
    assert manifest["producer"]["sourceDigest"] == _producer_source_digest()
    assert review["closureManifestDigest"] == manifest["manifestDigest"]
    semantic_review = dict(review)
    identity = semantic_review.pop("reviewDigest")
    assert identity == domain_digest(
        "tidy.source-closure-self-review/v1", semantic_review
    )
    assert review["claims"] == {
        "independentReview": False,
        "parityEstablished": False,
        "sourceBytesCopied": False,
        "runtimeSiblingDependencyAllowed": False,
    }
    sources = {source["sourceSystem"]: source for source in manifest["sources"]}
    assert sources["tidybank"]["authority"]["gitHead"] == (
        "c26e7f67091c414b411221af461b8ea3974c6320"
    )
    assert sources["tidybank"]["authority"]["gitTree"] == (
        "6b73f893f0d1a98432251f23cbdaab435ba8dacc"
    )
    assert sources["tidycell"]["authority"]["phaseASnapshotDigest"] == (
        "sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d"
    )
    copied = verify_source_closure_copy(CHECKED_COPY)
    copy_schema = json.loads(
        (
            PROJECT / "contracts/migration/v1/source-closure-copy-commit.schema.json"
        ).read_text()
    )
    validator_for(copy_schema).check_schema(copy_schema)
    validator_for(copy_schema)(copy_schema).validate(copied)
    # The copied custody bundle is immutable historical evidence. Refreshing
    # the no-copy discovery producer binding must not rewrite that executed
    # copy/replay lineage or pretend it was produced by the current checker.
    assert copied["closureManifestDigest"] == HISTORICAL_COPY_MANIFEST_DIGEST
    assert copied["commitDigest"] == HISTORICAL_COPY_COMMIT_DIGEST
    assert copied["runtimeAuthorized"] is False
    assert copied["parityEstablished"] is False

    replay = json.loads(CHECKED_REPLAY.read_text())
    replay_schema = json.loads(
        (
            PROJECT / "contracts/migration/v1/source-closure-replay.schema.json"
        ).read_text()
    )
    validator_for(replay_schema).check_schema(replay_schema)
    validator_for(replay_schema)(replay_schema).validate(replay)
    replay_semantic = dict(replay)
    replay_identity = replay_semantic.pop("replayDigest")
    assert replay_identity == domain_digest(
        "tidy.source-closure-replay/v1", replay_semantic
    )
    assert replay["closureManifestDigest"] == HISTORICAL_COPY_MANIFEST_DIGEST
    assert replay["copyCommitDigest"] == HISTORICAL_COPY_COMMIT_DIGEST
    assert replay["testFileCount"] == 13
    assert replay["testCount"] == replay["passedTestCount"] == 117
    assert replay["failedTestCount"] == replay["skippedTestCount"] == 0
    assert replay["sourceTreeDigestBefore"] == replay["sourceTreeDigestAfter"]
    assert replay["runtimeSiblingDependencyUsed"] is False
    assert replay["networkIsolationEnforced"] is True
    assert replay["parityEstablished"] is False
    manifest_tests = {
        item["relativePath"]: item["contentDigest"]
        for item in sources["tidycell"]["items"]
        if item["role"] == "fixture" and item["relativePath"].endswith(".test.ts")
    }
    assert {
        item["relativePath"]: item["contentDigest"] for item in replay["testFiles"]
    } == manifest_tests


def test_cli_writes_and_verifies_manifest(tmp_path: Path, capsys) -> None:
    request, _tidycell, _tidybank = _request(tmp_path)
    config = tmp_path / "request.json"
    output = tmp_path / "manifest.json"
    config.write_text(json.dumps(request))
    assert (
        source_closure_main(
            ["discover", "--config", str(config), "--output", str(output)]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["sourceBytesCopied"] is False
    assert result["itemCount"] == 16
    assert (
        source_closure_main(
            ["verify", "--config", str(config), "--manifest", str(output)]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True
