from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from tidy_orchestrator.ml_contract import canonical_digest_v1, canonical_json_v1
from tidy_orchestrator.ml_gateway import (
    DIRECTION_DIGEST,
    MANIFEST_SHA256,
    ROLE_DIGEST,
    MlGateway,
    MlGatewayConfig,
    MlIntegrityError,
    MlUnavailable,
    actual_ml_gateway,
)

PROJECT = Path(__file__).parents[1]
PACKAGE = PROJECT / "vendor/tidycell-ml/all-approved-gold-exclusion-v1"
RUNNER = PROJECT / "src/tidy_orchestrator/ml_inference_runner.py"


def features(
    *, sheet: str = "Données_日本", addresses: tuple[str, ...] = ("R1C1",)
) -> bytes:
    semantic = {
        "schemaVersion": "tidy.ml-feature-batch/v1",
        "workbookDigest": "sha256:" + "1" * 64,
        "sheet": sheet,
        "packageId": "tidycell-all-approved-gold-exclusion-xgboost-v1",
        "cells": [
            {
                "address": address,
                "roleVector": [1.25e-12, *([0.0] * 55)],
                "directionVector": [-3.5e8, *([0.0] * 53)],
            }
            for address in addresses
        ],
    }
    return json.dumps(
        {**semantic, "featureBatchDigest": canonical_digest_v1(semantic)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def gateway(
    *,
    runner: Path = RUNNER,
    timeout: float = 8,
    output: int = 5_000_000,
    stderr: int = 64_000,
    package: Path = PACKAGE,
) -> MlGateway:
    return MlGateway(
        MlGatewayConfig(
            python=Path(sys.executable),
            runner=runner,
            package=package,
            sandbox_mode="insecure-test-only",
            timeout_seconds=timeout,
            max_output_bytes=output,
            max_stderr_bytes=stderr,
        )
    )


def fake_runner(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "runner.py"
    path.write_text(source)
    return path


def test_shared_canonical_vectors_match_python() -> None:
    vectors = json.loads(
        (PROJECT / "contracts/ml/v1/canonical-vectors.json").read_text()
    )
    for vector in vectors["positive"]:
        assert canonical_json_v1(vector["value"]).decode() == vector["canonicalUtf8"]
        assert canonical_digest_v1(vector["value"]) == vector["digest"]
    for vector in vectors["negative"]:
        assert canonical_digest_v1(vector["value"]) != vector["digest"]


def test_native_runner_success_is_strict_and_deterministic() -> None:
    pytest.importorskip("xgboost")
    first = gateway().infer(features())
    second = gateway().infer(features())
    assert first == second
    assert first["sheet"] == "Données_日本"
    assert first["packageManifestDigest"] == "sha256:" + MANIFEST_SHA256
    assert first["models"] == {
        "cellRole": ROLE_DIGEST,
        "headerDirection": DIRECTION_DIGEST,
    }
    assert [item["address"] for item in first["predictions"]] == ["R1C1"]


def test_gateway_rejects_digest_mismatch_before_runtime() -> None:
    value = json.loads(features())
    value["featureBatchDigest"] = "sha256:" + "9" * 64
    with pytest.raises(MlIntegrityError, match="binding"):
        gateway().infer(json.dumps(value).encode())


def test_gateway_rejects_malformed_extra_and_unknown_output(tmp_path: Path) -> None:
    extra = fake_runner(tmp_path, 'print("{}")\nprint("extra")\n')
    with pytest.raises(MlIntegrityError, match="extra or missing"):
        gateway(runner=extra).infer(features())
    unknown = fake_runner(
        tmp_path,
        'print(\'{"ok":false,"category":"inference","code":"UNKNOWN"}\')\n',
    )
    with pytest.raises(MlIntegrityError, match="integrity failure"):
        gateway(runner=unknown).infer(features())


def test_gateway_types_invalid_utf8_and_truthy_nonlist_predictions(
    tmp_path: Path,
) -> None:
    invalid_utf8 = fake_runner(
        tmp_path,
        "import os\nos.write(1, b'\\xff')\n",
    )
    with pytest.raises(MlIntegrityError, match="not UTF-8"):
        gateway(runner=invalid_utf8).infer(features())

    malformed_item = {
        "address": "R1C1",
        "role": [],
        "direction": "N",
        "roleConfidence": 0.5,
        "directionConfidence": 0.5,
    }
    for predictions in (
        {"truthy": "not-a-list"},
        ["truthy-nondict-item"],
        [malformed_item],
    ):
        malformed_hints = {
            "schemaVersion": "tidy.ml-hints/v1",
            "workbookDigest": "sha256:" + "1" * 64,
            "sheet": "Données_日本",
            "featureBatchDigest": "sha256:" + "2" * 64,
            "packageId": "tidycell-all-approved-gold-exclusion-xgboost-v1",
            "packageManifestDigest": "sha256:" + MANIFEST_SHA256,
            "sourceCohortSha256": "sha256:" + "3" * 64,
            "models": {
                "cellRole": ROLE_DIGEST,
                "headerDirection": DIRECTION_DIGEST,
            },
            "predictions": predictions,
            "hintDigest": "sha256:" + "4" * 64,
        }
        malformed_predictions = fake_runner(
            tmp_path,
            "import json\n"
            f"print(json.dumps({{'ok': True, 'hints': {malformed_hints!r}}}))\n",
        )
        with pytest.raises(MlIntegrityError, match="strict validation"):
            gateway(runner=malformed_predictions).infer(features())


def assert_process_gone(pid: int) -> None:
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    pytest.fail(f"process {pid} survived gateway termination")


def test_timeout_terminates_complete_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    runner = fake_runner(
        tmp_path,
        "import subprocess,time\nfrom pathlib import Path\n"
        f"p=subprocess.Popen(['/bin/sleep','30']);Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        "time.sleep(30)\n",
    )
    with pytest.raises(MlUnavailable, match="timed out"):
        gateway(runner=runner, timeout=0.1).infer(features())
    assert_process_gone(int(pid_file.read_text()))


def test_exited_parent_cannot_leave_sigterm_ignoring_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "ignoring-descendant.pid"
    child = (
        "import signal,time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(pid_file)!r}).write_text(str(__import__('os').getpid()))\n"
        "time.sleep(30)\n"
    )
    runner = fake_runner(
        tmp_path,
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        f"p=Path({str(pid_file)!r})\n"
        "while not p.exists(): time.sleep(0.005)\n",
    )
    with pytest.raises(MlIntegrityError, match="descendant"):
        gateway(runner=runner).infer(features())
    assert_process_gone(int(pid_file.read_text()))


def test_fast_exit_stdout_and_stderr_caps_are_operational_failures(
    tmp_path: Path,
) -> None:
    stdout = fake_runner(tmp_path, "import os\nos.write(1, b'x' * 100000)\n")
    with pytest.raises(MlUnavailable, match="stdout"):
        gateway(runner=stdout, output=1000).infer(features())
    stderr = fake_runner(tmp_path, "import os\nos.write(2, b'x' * 100000)\n")
    with pytest.raises(MlUnavailable, match="stderr"):
        gateway(runner=stderr, stderr=1000).infer(features())


@pytest.mark.parametrize("entry_kind", ["file", "directory", "symlink"])
def test_package_rejects_undeclared_or_nonregular_entries(
    tmp_path: Path, entry_kind: str
) -> None:
    package = tmp_path / "package"
    shutil.copytree(PACKAGE, package)
    target = package / "undeclared"
    if entry_kind == "file":
        target.write_text("x")
    elif entry_kind == "directory":
        target.mkdir()
        (target / "nested").write_text("x")
    else:
        target.symlink_to(package / "manifest.json")
    with pytest.raises(MlIntegrityError, match="package integrity"):
        gateway(package=package).infer(features())


def test_declared_file_symlink_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "package"
    shutil.copytree(PACKAGE, package)
    model = package / "xgboost-cell-role-all-approved-excl.json"
    copy = tmp_path / "model.json"
    copy.write_bytes(model.read_bytes())
    model.unlink()
    model.symlink_to(copy)
    with pytest.raises(MlIntegrityError, match="package integrity"):
        gateway(package=package).infer(features())


def test_malicious_runner_snapshot_mutation_fails_closed(tmp_path: Path) -> None:
    runner = fake_runner(
        tmp_path,
        "import os,sys\nfrom pathlib import Path\n"
        "snapshot=Path(sys.argv[4])\n"
        "os.chmod(snapshot, 0o700)\n"
        "(snapshot/'manifest.json').unlink()\n"
        'print(\'{"ok":false,"category":"availability","code":"ML_RUNTIME_MISSING"}\')\n',
    )
    with pytest.raises(MlIntegrityError, match="Snapshot closure changed"):
        gateway(runner=runner).infer(features())


def test_runner_uses_private_snapshot_after_source_model_mutation(
    tmp_path: Path,
) -> None:
    pytest.importorskip("xgboost")
    package = tmp_path / "package"
    shutil.copytree(PACKAGE, package)
    source_model = package / "xgboost-cell-role-all-approved-excl.json"
    wrapper = fake_runner(
        tmp_path,
        "import runpy\nfrom pathlib import Path\n"
        f"Path({str(source_model)!r}).write_text('mutated after snapshot')\n"
        f"runpy.run_path({str(RUNNER)!r},run_name='__main__')\n",
    )
    result = gateway(runner=wrapper, package=package).infer(features())
    assert result["predictions"][0]["address"] == "R1C1"
    assert source_model.read_text() == "mutated after snapshot"


def test_insecure_mode_is_only_explicit_constructor_configuration() -> None:
    with pytest.raises(ValueError, match="sandbox mode"):
        MlGatewayConfig(
            python=Path(sys.executable),
            runner=RUNNER,
            package=PACKAGE,
            sandbox_mode="environment-selected",
        )


def test_production_gateway_construction_rejects_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="production ML"):
        MlGatewayConfig(
            python=Path(sys.executable),
            runner=RUNNER,
            package=PACKAGE,
            sandbox_mode="macos-production",
            runtime_read_roots=(Path(sys.base_prefix),),
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt acceptance")
def test_production_sandbox_runs_native_models_and_denies_fork() -> None:
    pytest.importorskip("xgboost")
    result = actual_ml_gateway(PROJECT).infer(features())
    assert result["predictions"][0]["address"] == "R1C1"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt acceptance")
def test_production_snapshot_is_read_only_to_runner(tmp_path: Path) -> None:
    runner = fake_runner(
        tmp_path,
        "import os,sys\nfrom pathlib import Path\n"
        "snapshot=Path(sys.argv[4])\n"
        "manifest=snapshot/'manifest.json'\n"
        "replacement=Path.cwd()/'replacement'\n"
        "replacement.write_text('replacement')\n"
        "denied=[]\n"
        "for name, action in [\n"
        " ('write', lambda: manifest.write_text('changed')),\n"
        " ('unlink', manifest.unlink),\n"
        " ('replace', lambda: os.replace(replacement, manifest)),\n"
        " ('chmod', lambda: os.chmod(snapshot, 0o700)),\n"
        "]:\n"
        " try: action()\n"
        " except PermissionError: denied.append(name)\n"
        "assert denied == ['write','unlink','replace','chmod'], denied\n"
        'print(\'{"ok":false,"category":"availability","code":"ML_RUNTIME_MISSING"}\')\n',
    )
    base = actual_ml_gateway(PROJECT).config
    hardened = MlGateway(
        MlGatewayConfig(
            python=base.python,
            runner=runner,
            package=base.package,
            sandbox_mode="macos-production",
            runtime_read_roots=base.runtime_read_roots,
            python_path=base.python_path,
        )
    )
    with pytest.raises(MlUnavailable, match="unavailable"):
        hardened.infer(features())


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt acceptance")
def test_production_denies_network_fork_and_custody_reads(tmp_path: Path) -> None:
    custody = PACKAGE / "xgboost-cell-role-all-approved-excl.pkl"
    runner = fake_runner(
        tmp_path,
        "import os,socket\nfrom pathlib import Path\n"
        "denied=[]\n"
        "s=socket.socket()\n"
        "try:s.bind(('127.0.0.1',0))\n"
        "except PermissionError:denied.append('network')\n"
        "try:pid=os.fork()\n"
        "except PermissionError:denied.append('fork')\n"
        "else:\n"
        "  os._exit(97) if pid == 0 else os.waitpid(pid,0)\n"
        f"try:Path({str(custody)!r}).read_bytes()\n"
        "except PermissionError:denied.append('custody')\n"
        "assert denied == ['network','fork','custody'], denied\n"
        'print(\'{"ok":false,"category":"availability","code":"ML_RUNTIME_MISSING"}\')\n',
    )
    base = actual_ml_gateway(PROJECT).config
    hardened = MlGateway(
        MlGatewayConfig(
            python=base.python,
            runner=runner,
            package=base.package,
            sandbox_mode="macos-production",
            runtime_read_roots=base.runtime_read_roots,
            python_path=base.python_path,
        )
    )
    with pytest.raises(MlUnavailable, match="unavailable"):
        hardened.infer(features())
