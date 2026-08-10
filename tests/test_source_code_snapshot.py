from __future__ import annotations

import copy
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from tidy_orchestrator.source_code_snapshot import (
    FixtureSourceCodeAuthorization,
    SourceCodeSnapshotAuthorizationError,
    SourceCodeSnapshotError,
    SourceCodeSnapshotMutation,
    freeze_fixture_source_code_snapshot,
    verify_fixture_source_code_snapshot,
)

PROJECT = Path(__file__).parents[1]
SCHEMA_PATH = PROJECT / "contracts/migration/v1/source-code-snapshot.schema.json"
FROZEN_AT = "2026-08-11T00:00:00Z"
SELECTION = {
    "LICENSE": "license",
    "fixtures/summary.json": "fixture",
    "package-lock.json": "lockfile",
    "src/summary.ts": "source",
}


def _git(root: Path, *arguments: str) -> None:
    executable = shutil.which("git")
    assert executable is not None
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-08-11T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-08-11T00:00:00Z",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }
    subprocess.run(
        [executable, *arguments],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "source-repository"
    (root / "src").mkdir(parents=True)
    (root / "fixtures").mkdir()
    (root / "LICENSE").write_text("MIT fixture license\n")
    (root / "NOTICE").write_text("fixture notice\n")
    (root / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (root / "src/summary.ts").write_text("export const summary = 'fixture';\n")
    (root / "fixtures/summary.json").write_text('{"summary":"fixture"}\n')
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Fixture Curator")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "add", "--all")
    _git(root, "commit", "-q", "-m", "fixture source closure")
    return root


def _freeze(root: Path, **overrides):
    arguments = {
        "source_root": root,
        "source_root_id": "phase-c-source-fixture",
        "closure_id": "summary-closure-fixture-v1",
        "selected_roles": SELECTION,
        "license_relative_path": "LICENSE",
        "license_spdx_id": "MIT",
        "frozen_at": FROZEN_AT,
        "authorization": FixtureSourceCodeAuthorization.create(source_root=root),
    }
    arguments.update(overrides)
    return freeze_fixture_source_code_snapshot(**arguments)


def _validate_schema(snapshot) -> None:
    import json

    schema = json.loads(SCHEMA_PATH.read_text())
    validator_for(schema).check_schema(schema)
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    validator_for(schema)(schema, registry=registry).validate(snapshot)


def test_fixture_source_code_closure_is_deterministic_verified_and_no_copy(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    before = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if ".git" not in path.parts
    )
    authorization = FixtureSourceCodeAuthorization.create(source_root=root)
    snapshot = _freeze(root, authorization=authorization)
    assert snapshot == _freeze(root, authorization=authorization)
    verify_fixture_source_code_snapshot(
        snapshot=snapshot,
        source_root=root,
        authorization=authorization,
    )
    _validate_schema(snapshot)

    assert snapshot["source"]["sourceSystem"] == "phase-c-fixture"
    assert snapshot["source"]["git"]["available"] is True
    assert snapshot["source"]["git"]["trackedDirty"] is False
    assert [item["relativePath"] for item in snapshot["selection"]["items"]] == sorted(
        SELECTION
    )
    license_item = next(
        item
        for item in snapshot["selection"]["items"]
        if item["relativePath"] == "LICENSE"
    )
    assert snapshot["license"]["contentDigest"] == license_item["contentDigest"]
    after = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if ".git" not in path.parts
    )
    assert after == before
    assert not any(path.name.startswith("snapshot") for path in root.rglob("*"))


def test_verification_detects_selected_and_unselected_tracked_mutation(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    authorization = FixtureSourceCodeAuthorization.create(source_root=root)
    snapshot = _freeze(root, authorization=authorization)

    (root / "NOTICE").write_text("changed unselected tracked bytes\n")
    with pytest.raises(SourceCodeSnapshotMutation, match="differs"):
        verify_fixture_source_code_snapshot(
            snapshot=snapshot,
            source_root=root,
            authorization=authorization,
        )
    dirty_snapshot = _freeze(root, authorization=authorization)
    assert dirty_snapshot["source"]["git"]["trackedDirty"] is True
    assert dirty_snapshot["snapshotDigest"] != snapshot["snapshotDigest"]

    tampered = copy.deepcopy(dirty_snapshot)
    tampered["source"]["sourceRootId"] = "substituted-root"
    with pytest.raises(SourceCodeSnapshotMutation, match="differs"):
        verify_fixture_source_code_snapshot(
            snapshot=tampered,
            source_root=root,
            authorization=authorization,
        )


def test_source_mutation_and_symlink_selection_fail_closed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    authorization = FixtureSourceCodeAuthorization.create(source_root=root)
    fired = False

    def mutate(point: str) -> None:
        nonlocal fired
        if point == "after-item:src/summary.ts" and not fired:
            fired = True
            (root / "src/summary.ts").write_text("changed during freeze\n")

    with pytest.raises(SourceCodeSnapshotMutation, match="changed"):
        _freeze(root, authorization=authorization, fault_injector=mutate)

    second = _repository(tmp_path / "symlink-case")
    target = second / "outside.ts"
    target.write_text("outside\n")
    selected = second / "src/summary.ts"
    selected.unlink()
    selected.symlink_to(target)
    _git(second, "add", "--all")
    _git(second, "commit", "-q", "-m", "track selected symlink")
    with pytest.raises(SourceCodeSnapshotError, match="opened safely"):
        _freeze(second)


def test_fixture_authorization_and_selection_bounds_fail_closed(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    authorization = FixtureSourceCodeAuthorization.create(source_root=root)
    with pytest.raises(
        SourceCodeSnapshotAuthorizationError, match="non-fixture source system"
    ):
        _freeze(
            root,
            authorization=authorization,
            source_system="other-source-system",
        )
    one_file = FixtureSourceCodeAuthorization.create(source_root=root, max_files=1)
    with pytest.raises(SourceCodeSnapshotAuthorizationError, match="file bound"):
        _freeze(root, authorization=one_file)
    with pytest.raises(SourceCodeSnapshotError, match="Unsafe source-code path"):
        _freeze(
            root,
            authorization=authorization,
            selected_roles={"../LICENSE": "license"},
            license_relative_path="../LICENSE",
        )

    (root / "untracked.ts").write_text("untracked\n")
    with pytest.raises(SourceCodeSnapshotError, match="untracked paths"):
        _freeze(
            root,
            authorization=authorization,
            selected_roles={"LICENSE": "license", "untracked.ts": "source"},
        )
