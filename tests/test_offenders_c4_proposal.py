from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tidy_orchestrator import large_batch_cli, offenders_acceptance
from tidy_orchestrator.artifacts import domain_digest, sha256_digest
from tidy_orchestrator.data_asset_status import _validate_cohort
from tidy_orchestrator.offenders_acceptance import (
    OffendersAcceptanceError,
    _executable_proofs,
    _tsx_command,
    _validate_committed_custody,
    _validate_pin_closure,
    assert_no_foreign_c4_install,
    c4_exclusive_access,
    c4_shared_access,
    required_c4_runtime_paths,
    required_c4_toolchain_paths,
    validate_c4_clean_checkout_tracking,
    verify_c4_acceptance_authority,
)
from tidy_orchestrator.product_prototype import evaluate_execution_for_acceptance


def contract() -> dict:
    return {
        "schemaVersion": "tidy.table-family-acceptance/v2",
        "tableFamilyId": "x",
        "contractId": "x-v1",
        "requiredDimensions": ["sex"],
        "dimensionHeaders": {"sex": ["sex"]},
        "aliases": {"sex": {"Male": "MALE"}},
        "strictAliasMatching": True,
        "measures": [
            {
                "id": "published-value",
                "unitId": "published-unit",
                "numeric": True,
                "minimum": 0,
                "expectedCombinationCountsByYear": {"2024": 1},
                "expectedDimensionsByYear": {"2024": {"sex": ["MALE"]}},
                "expectedCombinationDigestsByYear": {},
                "missingValues": {},
            }
        ],
        "expectedRecipeDigestsByYear": {"2024": "sha256:" + "1" * 64},
        "expectedRecipeProtocolsByYear": {"2024": "TargetScopedRecipeV02"},
        "expectedReplayMapDigestsByYear": {"2024": "sha256:" + "2" * 64},
        "expectedC3RowTraceDigestsByYear": {"2024": "sha256:" + "3" * 64},
        "expectedWarningCountsByYear": {"2024": 0},
        "uniqueKey": [
            "publication_vintage_date",
            "reference_date",
            "sex_id",
            "measure_id",
        ],
        "expected": {
            "minimumRows": 1,
            "maximumRows": 1,
            "sourceColumns": {"minimum": 1, "maximum": 2},
            "sexesByYear": {"2024": ["MALE"]},
        },
        "allowedExecutionWarnings": [],
        "totalEquations": [],
        "totalValidation": "not_applicable",
        "automaticAcceptance": True,
        "trainingEligibility": False,
        "preservePublicationVintage": True,
        "preserveRawValueText": True,
    }


def execution() -> dict:
    return {
        "sheet": "Table 1",
        "tables": [
            {
                "table": "x",
                "sheet": "Table 1",
                "rows": [
                    {
                        "published value": 1,
                        "sex": "Male",
                        "_source": {
                            "sheet": "Table 1",
                            "address": "R1C1",
                            "row": 1,
                            "col": 1,
                        },
                    }
                ],
            }
        ],
        "warnings": [],
    }


def recipe() -> dict:
    return {
        "version": "TargetScopedRecipeV02",
        "sheet": "Table 1",
        "table": {"id": "x", "name": "x", "valuesName": "published value"},
        "dimensions": [{"id": "d1", "name": "sex"}],
        "sourceUniverses": [],
        "attachments": [],
        "vectors": [],
        "targets": [],
    }


def test_target_scoped_recipe_names_and_protocol_are_accepted() -> None:
    rows, issues, checks = evaluate_execution_for_acceptance(
        execution=execution(),
        recipe=recipe(),
        contract=contract(),
        entry={
            "year": 2024,
            "referenceDate": "2025-06-30",
            "contentDigest": "sha256:" + "4" * 64,
            "sheet": "Table 1",
        },
        recipe_digest="sha256:" + "1" * 64,
        recipe_protocol="TargetScopedRecipeV02",
    )
    assert not issues
    assert len(rows) == 1 and rows[0]["recipe_protocol"] == "TargetScopedRecipeV02"
    assert all(checks.values())


def test_target_scoped_contract_rejects_recipe_v01_substitution() -> None:
    _rows, issues, _checks = evaluate_execution_for_acceptance(
        execution=execution(),
        recipe=recipe(),
        contract=contract(),
        entry={
            "year": 2024,
            "referenceDate": "2025-06-30",
            "contentDigest": "sha256:" + "4" * 64,
            "sheet": "Table 1",
        },
        recipe_digest="sha256:" + "1" * 64,
        recipe_protocol="RecipeV01",
    )
    assert "RECIPE_PROTOCOL_MISMATCH" in {x["code"] for x in issues}


def _pin(path: Path, root: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "byteLength": len(data),
        "sha256": sha256_digest(data),
    }


def _proposal() -> dict:
    return {
        "families": 47,
        "members": 170,
        "rows": 224997,
        "payloadRootDigest": "sha256:" + "a" * 64,
        "outputRootDigest": "sha256:" + "b" * 64,
    }


def _authority(review_pin: dict, *, runtime: list | None = None) -> dict:
    return {
        "schemaVersion": "tidy.offenders-c4-acceptance-authorization/v1",
        "authorizedForAtomicAcceptance": True,
        "acceptanceAuthority": True,
        "trainingEligibility": False,
        "productionAcceptance": True,
        "promotionAuthorization": True,
        "reviewDecision": review_pin,
        "proposal": _proposal(),
        "runtimeSourceClosure": [] if runtime is None else runtime,
        "toolchainClosure": [],
        "installedInputClosure": [],
        "generatedOutputClosure": [],
        "executableProofs": {},
    }


def _write_authority(root: Path, value: dict) -> str:
    path = (
        root / "fixtures/product-prototype/"
        "offenders-remaining-c4-acceptance-authorization-v1.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return sha256_digest(path.read_bytes())


def test_registration_authority_is_separate_and_absent(tmp_path: Path) -> None:
    with pytest.raises(
        OffendersAcceptanceError, match="C4_ACCEPTANCE_AUTHORIZATION_REQUIRED"
    ):
        verify_c4_acceptance_authority(tmp_path)


def test_authority_requires_independently_supplied_digest(tmp_path: Path) -> None:
    review = tmp_path / "fixtures/product-prototype/reviews/c4.json"
    review.parent.mkdir(parents=True)
    review.write_text("{}")
    _write_authority(tmp_path, _authority(_pin(review, tmp_path)))
    with pytest.raises(
        OffendersAcceptanceError, match="C4_EXTERNAL_AUTHORITY_DIGEST_REQUIRED"
    ):
        verify_c4_acceptance_authority(tmp_path)


def test_c3_or_arbitrary_review_decision_cannot_authorize(tmp_path: Path) -> None:
    c3 = tmp_path / "fixtures/product-prototype/offenders-c3-authorization.json"
    c3.parent.mkdir(parents=True)
    c3.write_text("{}")
    digest = _write_authority(tmp_path, _authority(_pin(c3, tmp_path)))
    with pytest.raises(OffendersAcceptanceError, match="C4_REVIEW_DECISION_INVALID"):
        verify_c4_acceptance_authority(tmp_path, digest)

    arbitrary = tmp_path / "fixtures/product-prototype/reviews/arbitrary.json"
    arbitrary.parent.mkdir(parents=True)
    arbitrary.write_text('{"schemaVersion":"arbitrary"}')
    digest = _write_authority(tmp_path, _authority(_pin(arbitrary, tmp_path)))
    with pytest.raises(OffendersAcceptanceError, match="C4_REVIEW_DECISION_INVALID"):
        verify_c4_acceptance_authority(tmp_path, digest)


@pytest.mark.parametrize(
    "mutation",
    [
        {"decision": "reject"},
        {"proposal": {**_proposal(), "rows": 1}},
        {
            "reviewer": {
                "id": "reviewer-1",
                "organization": "external",
                "role": "acceptance-reviewer",
                "independent": False,
            }
        },
    ],
)
def test_review_decision_rejects_false_scope_or_nonindependent_reviewer(
    tmp_path: Path, mutation: dict
) -> None:
    decision = {
        "schemaVersion": "tidy.offenders-c4-review-decision/v1",
        "campaignId": "offenders-remaining-c4",
        "decision": "approve-c4-acceptance",
        "reviewedAt": "2026-08-26T12:00:00+00:00",
        "reviewer": {
            "id": "reviewer-1",
            "organization": "external",
            "role": "acceptance-reviewer",
            "independent": True,
        },
        "proposal": _proposal(),
        "findingsDigest": "sha256:" + "c" * 64,
        **mutation,
    }
    decision["decisionId"] = domain_digest(decision["schemaVersion"], decision)
    review = tmp_path / "fixtures/product-prototype/reviews/c4.json"
    review.parent.mkdir(parents=True)
    review.write_text(json.dumps(decision))
    digest = _write_authority(tmp_path, _authority(_pin(review, tmp_path)))
    with pytest.raises(OffendersAcceptanceError, match="C4_REVIEW_DECISION_INVALID"):
        verify_c4_acceptance_authority(tmp_path, digest)


def test_positive_review_still_rejects_empty_runtime_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decision = {
        "schemaVersion": "tidy.offenders-c4-review-decision/v1",
        "campaignId": "offenders-remaining-c4",
        "decision": "approve-c4-acceptance",
        "reviewedAt": "2026-08-26T12:00:00+00:00",
        "reviewer": {
            "id": "reviewer-1",
            "organization": "independent-review",
            "role": "acceptance-reviewer",
            "independent": True,
        },
        "proposal": _proposal(),
        "findingsDigest": "sha256:" + "c" * 64,
    }
    decision["decisionId"] = domain_digest(decision["schemaVersion"], decision)
    review = tmp_path / "fixtures/product-prototype/reviews/c4.json"
    review.parent.mkdir(parents=True)
    review.write_text(json.dumps(decision))
    digest = _write_authority(tmp_path, _authority(_pin(review, tmp_path)))
    monkeypatch.setattr(
        offenders_acceptance, "required_c4_runtime_paths", lambda _root: set()
    )
    with pytest.raises(OffendersAcceptanceError, match="C4_AUTHORITY_CLOSURE_EMPTY"):
        verify_c4_acceptance_authority(tmp_path, digest)


def test_authority_pin_closure_rejects_missing_duplicate_extra_and_drift(
    tmp_path: Path,
) -> None:
    first = tmp_path / "runtime/first.py"
    second = tmp_path / "runtime/second.py"
    first.parent.mkdir()
    first.write_text("first")
    second.write_text("second")
    first_pin = _pin(first, tmp_path)
    second_pin = _pin(second, tmp_path)
    _validate_pin_closure(
        tmp_path, [first_pin], {"runtime/first.py"}, require_files=True
    )
    invalid = [
        [],
        [first_pin, first_pin],
        [first_pin, second_pin],
        [{**first_pin, "sha256": "sha256:" + "0" * 64}],
    ]
    for pins in invalid:
        with pytest.raises(OffendersAcceptanceError):
            _validate_pin_closure(
                tmp_path, pins, {"runtime/first.py"}, require_files=True
            )


def test_authority_pin_closure_rejects_absolute_traversal_and_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target/file.py"
    target.parent.mkdir()
    target.write_text("x")
    pin = _pin(target, tmp_path)
    for path in (str(target), "../file.py"):
        with pytest.raises(OffendersAcceptanceError, match="C4_AUTHORITY_PIN_PATH"):
            _validate_pin_closure(
                tmp_path, [{**pin, "path": path}], {path}, require_files=True
            )
    (tmp_path / "linked").symlink_to(target.parent, target_is_directory=True)
    linked = {**pin, "path": "linked/file.py"}
    with pytest.raises(OffendersAcceptanceError, match="C4_AUTHORITY_PIN_PATH"):
        _validate_pin_closure(
            tmp_path, [linked], {"linked/file.py"}, require_files=True
        )


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/register-offenders-remaining.py",
        "src/tidy_orchestrator/large_batch.py",
        "src/tidy_orchestrator/data_asset_status.py",
        "src/tidy_orchestrator/offenders_release.py",
        "src/tidy_orchestrator/large_batch_cli.py",
        "src/tidy_orchestrator/dagster_defs.py",
        "src/tidy_orchestrator/definitions.py",
        "src/tidy_orchestrator/data_asset_status_cli.py",
        "scripts/dagster-ui",
        "scripts/tidy-prototype-batch",
        "scripts/tidy-data-status",
        "scripts/run-dagster-ui-foreground",
    ],
)
def test_runtime_closure_binds_installer_only_authority_code(relative: str) -> None:
    root = Path(__file__).parents[1]
    closure = required_c4_runtime_paths(root)
    assert relative in closure
    pin = _pin(root / relative, root)
    _validate_pin_closure(root, [pin], {relative}, require_files=True)
    with pytest.raises(OffendersAcceptanceError, match="C4_AUTHORITY_PIN_DRIFT"):
        _validate_pin_closure(
            root,
            [{**pin, "sha256": "sha256:" + "0" * 64}],
            {relative},
            require_files=True,
        )


def test_pinned_tsx_cli_ignores_bin_wrapper_absence_and_symlink(
    tmp_path: Path,
) -> None:
    root = Path(__file__).parents[1]
    package = tmp_path / "node_modules/tsx"
    package.parent.mkdir(parents=True)
    shutil.copytree(root / "node_modules/tsx", package)
    assert not (tmp_path / "node_modules/.bin/tsx").exists()
    absent_proof = _executable_proofs(tmp_path)["tsx"]
    wrapper = tmp_path / "node_modules/.bin/tsx"
    wrapper.parent.mkdir()
    wrapper.symlink_to("/usr/bin/false")
    malicious_proof = _executable_proofs(tmp_path)["tsx"]
    assert absent_proof == malicious_proof
    command = _tsx_command(tmp_path, "script.ts")
    assert command == [
        "node",
        str(tmp_path / "node_modules/tsx/dist/cli.mjs"),
        "script.ts",
    ]
    assert str(wrapper) not in command
    assert "node_modules/.bin/tsx" not in required_c4_toolchain_paths(root)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    )


def test_committed_custody_rejects_intent_staged_only_and_worktree_drift(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "C4 test")
    authority = tmp_path / "authority.json"
    pinned = tmp_path / "pinned.txt"
    authority.write_text("authority")
    pinned.write_text("committed")
    _git(tmp_path, "add", "authority.json", "pinned.txt")
    _git(tmp_path, "commit", "-m", "custody")
    committed_pin = _pin(pinned, tmp_path)
    _validate_committed_custody(
        tmp_path, [committed_pin], "authority.json", authority.read_bytes()
    )

    intent = tmp_path / "intent.txt"
    intent.write_text("intent")
    _git(tmp_path, "add", "-N", "intent.txt")
    staged = tmp_path / "staged.txt"
    staged.write_text("staged")
    _git(tmp_path, "add", "staged.txt")
    assert validate_c4_clean_checkout_tracking(
        tmp_path, {"intent.txt", "staged.txt"}
    ) == ["intent.txt", "staged.txt"]

    pinned.write_text("staged replacement")
    _git(tmp_path, "add", "pinned.txt")
    _git(tmp_path, "restore", "--worktree", "--source=HEAD", "pinned.txt")
    with pytest.raises(OffendersAcceptanceError, match="C4_CLEAN_INDEX_DRIFT"):
        _validate_committed_custody(
            tmp_path, [_pin(pinned, tmp_path)], "authority.json", authority.read_bytes()
        )
    _git(tmp_path, "restore", "--staged", "--source=HEAD", "pinned.txt")
    pinned.write_text("worktree only")
    with pytest.raises(OffendersAcceptanceError, match="C4_COMMITTED_CUSTODY_DRIFT"):
        _validate_committed_custody(
            tmp_path, [_pin(pinned, tmp_path)], "authority.json", authority.read_bytes()
        )


def test_status_validator_accepts_only_strict_c4_metadata() -> None:
    cohort = {
        "schemaVersion": "tidy.product-prototype-cohort/v1",
        "cohortId": "recorded-crime-offenders-x",
        "publicationId": "recorded-crime-offenders",
        "tableFamilyId": "x",
        "generation": {},
        "acceptanceContract": "acceptance/x.json",
        "workbooks": [
            {
                "year": 2024,
                "referenceDate": "2025-06-30",
                "path": "workbooks/x.xlsx",
                "contentDigest": "sha256:" + "1" * 64,
                "byteLength": 1,
                "sheet": "Table 1",
                "releaseId": "2024-25",
                "downloadOrdinal": 1,
                "cubeId": "main",
                "tableNamespace": "main",
                "replayResponse": {
                    "path": "replay/x.response.txt",
                    "contentDigest": "sha256:" + "2" * 64,
                    "byteLength": 1,
                    "historicalModel": (
                        "provider-free/offenders-c4/semantic-map-v2-recipe-v01"
                    ),
                    "acceptanceAuthority": False,
                    "recipeProtocol": "RecipeV01",
                },
            }
        ],
    }
    _validate_cohort(cohort, cohort["cohortId"])
    cohort["workbooks"][0]["unexpected"] = True
    with pytest.raises(Exception, match="invalid workbook entry"):
        _validate_cohort(cohort, cohort["cohortId"])


def test_large_batch_cli_dispatches_only_c4_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = {
        "providerCalls": 0,
        "acceptedWorkbookCount": 1,
        "exceptionWorkbookCount": 0,
        "canonicalObservationCount": 1,
        "crossYearIssues": [],
        "runDigest": "sha256:" + "9" * 64,
        "workbooks": [
            {
                "observationCount": 1,
                "decision": "prototype_auto_accepted",
                "issues": [],
                "checks": {"c3Proof": True},
            }
        ],
    }
    calls = []

    def c4(**kwargs):
        calls.append(kwargs)
        return report

    monkeypatch.setattr(large_batch_cli, "run_offenders_remaining_family", c4)
    monkeypatch.setattr(
        large_batch_cli,
        "run_product_prototype",
        lambda **_kwargs: pytest.fail("generic replay must not handle C4"),
    )
    monkeypatch.setattr(
        large_batch_cli, "verify_large_batch_reproduction", lambda *_args: None
    )
    spec = SimpleNamespace(
        family_id="x",
        replay_engine="offenders-remaining-c4-v1",
        cohort_path="fixtures/product-prototype/x.json",
        expected_years=(2024,),
        expected_canonical_count=1,
        expected_year_counts=(1,),
    )
    result = large_batch_cli._run_one(
        tmp_path, tmp_path / "output", spec, "2026-08-25T12:00:00+00:00"
    )
    assert result["passed"] is True and len(calls) == 1


def _registration_module():
    path = Path(__file__).parents[1] / "scripts/register-offenders-remaining.py"
    spec = importlib.util.spec_from_file_location("c4_registration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _access_subprocess(root: Path, statement: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return subprocess.run(
        [sys.executable, "-c", statement, str(root)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_shared_and_exclusive_access_are_process_mutually_exclusive(
    tmp_path: Path,
) -> None:
    (tmp_path / ".product-prototype").mkdir()
    exclusive = (
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.offenders_acceptance import c4_exclusive_access; "
        "\nwith c4_exclusive_access(Path(sys.argv[1])): pass"
    )
    shared = (
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.offenders_acceptance import c4_shared_access; "
        "\nwith c4_shared_access(Path(sys.argv[1])): pass"
    )
    with c4_shared_access(tmp_path):
        blocked_writer = _access_subprocess(tmp_path, exclusive)
    assert blocked_writer.returncode != 0
    assert "C4_READERS_ACTIVE" in blocked_writer.stderr
    with c4_exclusive_access(tmp_path):
        blocked_reader = _access_subprocess(tmp_path, shared)
    assert blocked_reader.returncode != 0
    assert "C4_INSTALL_IN_PROGRESS" in blocked_reader.stderr


@pytest.mark.parametrize(
    "operation",
    ["verify-batch", "asset-csv-with-status"],
)
def test_public_multifile_reader_holds_shared_lease_until_return(
    tmp_path: Path, operation: str
) -> None:
    (tmp_path / ".product-prototype").mkdir()
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    if operation == "verify-batch":
        statement = """
from pathlib import Path
from types import SimpleNamespace
import sys, time
from tidy_orchestrator import large_batch_cli as module
root=Path(sys.argv[1]); ready=root/'ready'; release=root/'release'
def pause(_root):
 ready.write_text('ready')
 while not release.exists(): time.sleep(0.01)
 return SimpleNamespace(batch_id='x',worksheet_count=0,entries=())
module.load_large_batch_registry=pause
module.verify_batch_normalization=lambda *_args: None
module.verify_batch(root)
"""
    else:
        statement = """
from pathlib import Path
import sys, time
from tidy_orchestrator import data_asset_status as module
root=Path(sys.argv[1]); ready=root/'ready'; release=root/'release'
def pause(_root, _status):
 ready.write_text('ready')
 while not release.exists(): time.sleep(0.01)
 return {}
module._build_asset_csv_payloads_unlocked=pause
module.build_asset_csv_payloads(root, object())
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    child = subprocess.Popen(
        [sys.executable, "-c", statement, str(tmp_path)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.is_file()
        exclusive = (
            "from pathlib import Path; import sys; "
            "from tidy_orchestrator.offenders_acceptance import c4_exclusive_access; "
            "\nwith c4_exclusive_access(Path(sys.argv[1])): pass"
        )
        blocked = _access_subprocess(tmp_path, exclusive)
        assert blocked.returncode != 0 and "C4_READERS_ACTIVE" in blocked.stderr
        release.write_text("release")
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, (stdout, stderr)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_persistent_unresolved_owner_blocks_reader_replay_and_second_writer(
    tmp_path: Path,
) -> None:
    product = tmp_path / ".product-prototype"
    lock = product / "offenders-c4-install-transactions/install.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        json.dumps({"token": "a" * 32, "pid": 123, "proposal": "sha256:" + "b" * 64})
    )
    statements = (
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.large_batch import load_large_batch_registry; "
        "load_large_batch_registry(Path(sys.argv[1]))",
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.offenders_acceptance import "
        "run_offenders_remaining_family; "
        "p=Path(sys.argv[1]); run_offenders_remaining_family(project_root=p, "
        "cohort_path=p/'missing.json', output_root=p/'out')",
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.offenders_acceptance import c4_exclusive_access; "
        "p=Path(sys.argv[1]);\nwith c4_exclusive_access(p): pass",
    )
    for statement in statements:
        result = _access_subprocess(tmp_path, statement)
        assert result.returncode != 0
        assert "C4_INSTALL_IN_PROGRESS" in result.stderr
    assert lock.is_file()


def test_foreign_transaction_lock_blocks_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = (
        tmp_path / ".product-prototype/offenders-c4-install-transactions/install.lock"
    )
    lock.parent.mkdir(parents=True)
    lock.write_text(
        json.dumps(
            {"token": "owner-token", "pid": 123, "proposal": "sha256:" + "a" * 64}
        )
    )
    with pytest.raises(OffendersAcceptanceError, match="C4_INSTALL_IN_PROGRESS"):
        assert_no_foreign_c4_install(tmp_path)
    monkeypatch.setenv("TIDY_C4_INSTALL_OWNER", "owner-token")
    assert_no_foreign_c4_install(tmp_path)


def test_installer_rejects_symlinked_destination_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _registration_module()
    repository = tmp_path / "repository"
    outside = tmp_path / "outside"
    repository.mkdir()
    outside.mkdir()
    (repository / "fixtures").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(module, "ROOT", repository)
    with pytest.raises(RuntimeError, match="unsafe destination ancestor"):
        module._safe_destination(repository / "fixtures/product-prototype/x.json")
    assert list(outside.iterdir()) == []


def _matrix_harness(
    tmp_path: Path, event: str, signal_name: str
) -> subprocess.CompletedProcess[str]:
    root = tmp_path / f"{event}-{signal_name}"
    root.mkdir()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent / "offenders_c4_install_matrix_harness.py"),
            str(root),
            event,
            signal_name,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("event", ["initial-owner-failure", "initial-journal-failure"])
def test_initial_transaction_metadata_failure_exposes_no_lock(
    tmp_path: Path, event: str
) -> None:
    result = _matrix_harness(tmp_path, event, "exception")
    assert result.returncode == 0
    root = tmp_path / f"{event}-exception"
    state = json.loads((root / "matrix-state.json").read_text())
    assert state["lock"] is False and state["transactions"] == []
    assert not (
        root / ".product-prototype/offenders-c4-install-transactions/install.lock"
    ).exists()


@pytest.mark.parametrize("signal_name", ["SIGINT", "SIGTERM"])
def test_staging_signal_is_blocked_until_exact_resolution(
    tmp_path: Path, signal_name: str
) -> None:
    result = _matrix_harness(tmp_path, "staging-signal", signal_name)
    root = tmp_path / f"staging-signal-{signal_name}"
    values = [
        path.read_text() for path in sorted((root / "matrix-destinations").glob("*"))
    ]
    assert values == [f"new-{index}" for index in range(315)]
    assert not (
        root / ".product-prototype/offenders-c4-install-transactions/install.lock"
    ).exists()
    assert result.returncode in {0, -signal.SIGTERM}


@pytest.mark.parametrize(
    "event",
    [
        "before-backup-0",
        "after-backup-315",
        "before-install-0",
        "after-install-314",
        "generated-status",
        "post-swap-validation",
    ],
)
def test_actual_install_state_machine_exception_boundaries(
    tmp_path: Path, event: str
) -> None:
    result = _matrix_harness(tmp_path, event, "exception")
    assert result.returncode == 0
    state = json.loads((tmp_path / f"{event}-exception/matrix-state.json").read_text())
    assert state == {
        "prior": True,
        "complete": False,
        "lock": False,
        "transactions": [],
    }


@pytest.mark.parametrize("signal_name", ["SIGINT", "SIGTERM"])
@pytest.mark.parametrize(
    "event",
    [
        "before-backup-0",
        "after-backup-315",
        "before-install-0",
        "after-install-314",
        "generated-status",
        "post-swap-validation",
        "rollback-interruption",
    ],
)
def test_actual_install_signal_matrix_reaches_safe_or_durable_state(
    tmp_path: Path, event: str, signal_name: str
) -> None:
    result = _matrix_harness(tmp_path, event, signal_name)
    root = tmp_path / f"{event}-{signal_name}"
    state_path = root / "matrix-state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        assert state["prior"] != state["complete"]
        assert not state["lock"] or state["transactions"]
    else:
        values = [
            path.read_text()
            for path in sorted((root / "matrix-destinations").glob("*"))
        ]
        prior = values == [f"prior-{index}" for index in range(315)]
        complete = values == [f"new-{index}" for index in range(315)]
        assert prior != complete
        lock = (
            root / ".product-prototype/offenders-c4-install-transactions/install.lock"
        )
        transactions = list(lock.parent.glob("transaction-*"))
        if lock.is_file():
            assert len(transactions) == 1
            assert (transactions[0] / "owner.json").is_file()
            assert (transactions[0] / "journal.json").is_file()
        else:
            assert complete and transactions == []
    assert result.returncode in {0, -signal.SIGTERM}


def test_install_level_rollback_failure_retains_owner_and_blocks_operations(
    tmp_path: Path,
) -> None:
    result = _matrix_harness(tmp_path, "rollback-failure", "exception")
    assert result.returncode == 0
    root = tmp_path / "rollback-failure-exception"
    tx_root = root / ".product-prototype/offenders-c4-install-transactions"
    lock = tx_root / "install.lock"
    transactions = list(tx_root.glob("transaction-*"))
    assert lock.is_file() and len(transactions) == 1
    transaction = transactions[0]
    journal = json.loads((transaction / "journal.json").read_text())
    owner = json.loads((transaction / "owner.json").read_text())
    assert journal["phase"] == "rollback-failed"
    assert owner == json.loads(lock.read_text())
    assert len(list((transaction / "backups").iterdir())) == 315
    statements = (
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.large_batch import load_large_batch_registry; "
        "load_large_batch_registry(Path(sys.argv[1]))",
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.offenders_acceptance import "
        "run_offenders_remaining_family; p=Path(sys.argv[1]); "
        "run_offenders_remaining_family(project_root=p, "
        "cohort_path=p/'missing.json', output_root=p/'out')",
        "from pathlib import Path; import sys; "
        "from tidy_orchestrator.offenders_acceptance import c4_exclusive_access; "
        "p=Path(sys.argv[1]);\nwith c4_exclusive_access(p): pass",
    )
    for statement in statements:
        blocked = _access_subprocess(root, statement)
        assert blocked.returncode != 0
        assert "C4_INSTALL_IN_PROGRESS" in blocked.stderr
    assert lock.is_file() and transaction.is_dir()
    module = _registration_module()
    module.ROOT = root
    module.TX_ROOT = tx_root
    module.TX_LOCK = lock
    module._expected_destination_paths = lambda _manifest: [
        *(f"matrix-destinations/{index:03d}" for index in range(315)),
        "docs/data-asset-status/index.html",
    ]
    module.recover(owner["token"], "rollback")
    assert not lock.exists() and not transaction.exists()
    values = [
        path.read_text() for path in sorted((root / "matrix-destinations").iterdir())
    ]
    assert values == [f"prior-{index}" for index in range(315)]


def test_owner_recovery_clears_exact_no_swap_staging_state(tmp_path: Path) -> None:
    module = _registration_module()
    root = tmp_path / "repository"
    tx_root = root / ".product-prototype/offenders-c4-install-transactions"
    transaction = tx_root / ("transaction-" + "a" * 32)
    transaction.mkdir(parents=True)
    owner = {
        "token": "a" * 32,
        "pid": 123,
        "proposal": "sha256:" + "b" * 64,
    }
    (tx_root / "install.lock").write_text(json.dumps(owner))
    (transaction / "owner.json").write_text(json.dumps(owner))
    (transaction / "journal.json").write_text(
        json.dumps(
            {
                **owner,
                "phase": "staging",
                "operation": None,
                "items": [],
                "existed": {},
            }
        )
    )
    module.ROOT = root
    module.TX_ROOT = tx_root
    module.TX_LOCK = tx_root / "install.lock"
    module.recover(owner["token"], "rollback")
    assert not module.TX_LOCK.exists() and not transaction.exists()


@pytest.mark.parametrize("mutation", ["truncated", "duplicate", "extra"])
def test_recovery_rejects_nonexact_316_destination_journal(
    tmp_path: Path, mutation: str
) -> None:
    result = _matrix_harness(tmp_path, "rollback-failure", "exception")
    assert result.returncode == 0
    root = tmp_path / "rollback-failure-exception"
    tx_root = root / ".product-prototype/offenders-c4-install-transactions"
    lock = tx_root / "install.lock"
    transaction = next(tx_root.glob("transaction-*"))
    journal_path = transaction / "journal.json"
    journal = json.loads(journal_path.read_text())
    if mutation == "truncated":
        journal["items"].pop()
    elif mutation == "duplicate":
        journal["items"][-1] = journal["items"][0]
    else:
        journal["items"].append("fixtures/product-prototype/extra.json")
    journal_path.write_text(json.dumps(journal))
    module = _registration_module()
    module.ROOT = root
    module.TX_ROOT = tx_root
    module.TX_LOCK = lock
    module._expected_destination_paths = lambda _manifest: [
        *(f"matrix-destinations/{index:03d}" for index in range(315)),
        "docs/data-asset-status/index.html",
    ]
    owner = json.loads(lock.read_text())
    with pytest.raises(RuntimeError, match="destination closure"):
        module.recover(owner["token"], "rollback")
    assert lock.is_file() and transaction.is_dir()


def test_recovery_rejects_coherent_manifest_and_journal_rebinding(
    tmp_path: Path,
) -> None:
    result = _matrix_harness(tmp_path, "rollback-failure", "exception")
    assert result.returncode == 0
    root = tmp_path / "rollback-failure-exception"
    tx_root = root / ".product-prototype/offenders-c4-install-transactions"
    lock = tx_root / "install.lock"
    transaction = next(tx_root.glob("transaction-*"))
    module = _registration_module()
    manifest_path = transaction / "proposal/manifest.json"
    proposal_manifest = json.loads(manifest_path.read_text())
    owner = json.loads(lock.read_text())
    assert proposal_manifest["outputRootDigest"] == owner["proposal"]
    journal_path = transaction / "journal.json"
    journal = json.loads(journal_path.read_text())

    old_path = journal["items"][0]
    new_path = "matrix-destinations-mutated/000"
    proposal_manifest["outputRootDigest"] = "sha256:" + "c" * 64
    proposal_manifest["coherentDestinationMutation"] = {
        "old": old_path,
        "new": new_path,
    }
    journal["items"][0] = new_path
    journal["existed"][str(root / new_path)] = journal["existed"].pop(
        str(root / old_path)
    )
    (transaction / "proposal/manifest.json").write_text(json.dumps(proposal_manifest))
    journal_path.write_text(json.dumps(journal))
    module.ROOT = root
    module.TX_ROOT = tx_root
    module.TX_LOCK = lock
    with pytest.raises(RuntimeError, match="proposal ownership drift"):
        module.recover(owner["token"], "rollback")
    assert lock.is_file() and transaction.is_dir()


def test_exhaustive_transaction_hooks_are_mapped_and_reachable(
    tmp_path: Path,
) -> None:
    module = _registration_module()
    expected = module.transaction_hook_names()
    assert len(expected) == 1265
    normal = _matrix_harness(tmp_path, "record-hooks", "exception")
    rollback = _matrix_harness(tmp_path, "record-rollback-hooks", "exception")
    assert normal.returncode == rollback.returncode == 0
    observed = set(
        json.loads((tmp_path / "record-hooks-exception/matrix-hooks.json").read_text())
    ) | set(
        json.loads(
            (tmp_path / "record-rollback-hooks-exception/matrix-hooks.json").read_text()
        )
    )
    assert observed == expected


def test_durable_replace_and_remove_fsync_all_affected_parents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _registration_module()
    source = tmp_path / "source/item"
    destination = tmp_path / "destination/item"
    source.parent.mkdir()
    destination.parent.mkdir()
    source.write_text("value")
    fsynced: list[Path] = []
    monkeypatch.setattr(module, "_fsync_directory", fsynced.append)
    module._durable_replace(source, destination)
    assert fsynced == [source.parent, destination.parent]
    fsynced.clear()
    module._durable_remove(destination)
    assert fsynced == [destination.parent]


def test_durable_replace_fsync_fault_is_reported_by_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _registration_module()
    backups = tmp_path / "backups"
    backups.mkdir()
    destination = tmp_path / "destination"
    destination.write_text("installed")
    (backups / "000").write_text("prior")

    def fail_fsync(_path: Path) -> None:
        raise OSError("injected fsync fault")

    monkeypatch.setattr(module, "_fsync_directory", fail_fsync)
    errors = module._rollback(
        [("cohort", tmp_path / "source", destination)],
        backups,
        {str(destination): True},
    )
    assert errors and "injected fsync fault" in errors[0]


def test_rollback_restores_present_and_removes_absent_destinations(
    tmp_path: Path,
) -> None:
    module = _registration_module()
    backups = tmp_path / "backups"
    backups.mkdir()
    prior = tmp_path / "prior"
    new = tmp_path / "new"
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    prior.write_text("installed-a")
    new.write_text("installed-b")
    (backups / "000").write_text("prior-a")
    errors = module._rollback(
        [("cohort", source_a, prior), ("cohort", source_b, new)],
        backups,
        {str(prior): True, str(new): False},
    )
    assert errors == []
    assert prior.read_text() == "prior-a"
    assert not new.exists()


def test_rollback_aggregates_failure_and_preserves_sole_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _registration_module()
    backups = tmp_path / "backups"
    backups.mkdir()
    destination = tmp_path / "destination"
    destination.write_text("installed")
    backup = backups / "000"
    backup.write_text("prior")

    def fail_remove(_path: Path) -> None:
        raise KeyboardInterrupt("injected rollback failure")

    monkeypatch.setattr(module, "_remove", fail_remove)
    errors = module._rollback(
        [("cohort", tmp_path / "source", destination)],
        backups,
        {str(destination): True},
    )
    assert errors and backup.read_text() == "prior"
