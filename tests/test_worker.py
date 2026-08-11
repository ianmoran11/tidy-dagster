from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

import pytest

from tidy_orchestrator.artifacts import (
    LocalArtifactRepository,
    RecordConflict,
    sha256_digest,
)
from tidy_orchestrator.worker import (
    GatewayConfig,
    GatewayInput,
    WorkerDomainFailure,
    WorkerGateway,
    WorkerGatewayError,
)

FAKE = Path(__file__).parent / "fixtures" / "fake_worker.py"
PROJECT = Path(__file__).parents[1]


def setup(tmp_path: Path, scenario: str, *extra: str, **overrides):
    repo = LocalArtifactRepository(tmp_path / "repository")
    content = repo.put_bytes(
        b"input",
        kind="test-input",
        schema_version="test/v1",
        media_type="application/octet-stream",
    )
    config = GatewayConfig(
        command=(sys.executable, str(FAKE), scenario, *extra),
        cwd=PROJECT,
        sandbox_mode="insecure-test-only",
        **overrides,
    )
    gateway = WorkerGateway(repo, config)
    item = GatewayInput("input", content.content_digest, "input.bin")
    return repo, gateway, item


def test_gateway_success_publishes_only_verified_set(tmp_path: Path) -> None:
    repo, gateway, item = setup(tmp_path, "success")
    result = gateway.execute(inputs=[item], parameters={})
    assert result.output_paths == ("result.json",)
    assert (
        repo.read_bytes_verified(result.outputs[0].content_digest)
        == b"provider-free-output"
    )
    assert repo.get_derivation(result.derivation.derivation_id) == result.derivation
    repeated = gateway.execute(inputs=[item], parameters={})
    assert repeated.derivation.derivation_id == result.derivation.derivation_id
    assert repeated.output_fingerprint == result.output_fingerprint


def test_compact_context_parameter_is_strictly_typed(tmp_path: Path) -> None:
    marker = tmp_path / "started"
    _, gateway, item = setup(tmp_path, "mark-success", "--marker", str(marker))
    with pytest.raises(WorkerGatewayError, match="Invalid includeCompactContext"):
        gateway.execute(inputs=[item], parameters={"includeCompactContext": "yes"})
    assert not marker.exists()


def test_input_mismatch_fails_before_launch(tmp_path: Path) -> None:
    marker = tmp_path / "started"
    _, gateway, item = setup(tmp_path, "mark-success", "--marker", str(marker))
    invalid = GatewayInput(
        item.name, item.content_digest, item.relative_path, declared_byte_length=99
    )
    with pytest.raises(WorkerGatewayError, match="Declared input length") as error:
        gateway.execute(inputs=[invalid])
    assert error.value.code == "INPUT_INVALID"
    assert not marker.exists()


@pytest.mark.parametrize(
    ("scenario", "code", "overrides"),
    [
        ("malformed", "MALFORMED_STDOUT", {}),
        ("stdout-large", "STDOUT_LIMIT_EXCEEDED", {"max_stdout_bytes": 1024}),
        ("stderr-large", "STDERR_LIMIT_EXCEEDED", {"max_stderr_bytes": 1024}),
        ("unknown-protocol", "UNKNOWN_PROTOCOL", {}),
        ("unknown-field", "UNKNOWN_RESPONSE_FIELD", {}),
    ],
)
def test_protocol_and_stream_failures(
    tmp_path: Path, scenario: str, code: str, overrides: dict
) -> None:
    _, gateway, item = setup(tmp_path, scenario, **overrides)
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(inputs=[item])
    assert error.value.code == code


@pytest.mark.parametrize(
    ("scenario", "code"),
    [
        ("path-traversal", "UNSAFE_PATH"),
        ("absolute-path", "UNSAFE_PATH"),
        ("symlink", "OUTPUT_SYMLINK"),
        ("undeclared", "UNDECLARED_OUTPUT"),
        ("digest-mismatch", "OUTPUT_DIGEST_MISMATCH"),
        ("length-mismatch", "OUTPUT_LENGTH_MISMATCH"),
    ],
)
def test_output_confinement_and_integrity(
    tmp_path: Path, scenario: str, code: str
) -> None:
    repo, gateway, item = setup(tmp_path, scenario)
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(inputs=[item])
    assert error.value.code == code
    with repo._connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM contents WHERE record_json LIKE '%worker-output%'"
        ).fetchone()[0]
    assert count == 0


def test_output_count_and_size_limits(tmp_path: Path) -> None:
    _, count_gateway, item = setup(
        tmp_path / "count", "output-count", max_output_files=1
    )
    with pytest.raises(WorkerGatewayError) as count_error:
        count_gateway.execute(inputs=[item])
    assert count_error.value.code == "OUTPUT_FILE_LIMIT_EXCEEDED"

    _, size_gateway, size_item = setup(
        tmp_path / "size", "output-size", max_output_file_bytes=1000
    )
    with pytest.raises(WorkerGatewayError) as size_error:
        size_gateway.execute(inputs=[size_item])
    assert size_error.value.code == "OUTPUT_FILE_SIZE_LIMIT_EXCEEDED"


def test_nonzero_and_domain_failure_classification(tmp_path: Path) -> None:
    _, gateway, item = setup(tmp_path / "exit", "nonzero")
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(inputs=[item])
    assert error.value.code == "WORKER_NONZERO_EXIT"
    assert error.value.category == "INFRA_TRANSIENT"

    _, domain_gateway, domain_item = setup(tmp_path / "domain", "domain-error")
    with pytest.raises(WorkerDomainFailure) as domain_error:
        domain_gateway.execute(inputs=[domain_item])
    assert domain_error.value.code == "SYNTHETIC"


def test_timeout_terminates_worker(tmp_path: Path) -> None:
    _, gateway, item = setup(
        tmp_path, "timeout", wall_timeout_seconds=0.2, termination_grace_seconds=0.1
    )
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(inputs=[item])
    assert error.value.code == "WORKER_TIMEOUT"


def test_timeout_terminates_spawned_grandchild(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    _, gateway, item = setup(
        tmp_path / "run",
        "grandchild",
        "--pid-file",
        str(pid_file),
        wall_timeout_seconds=0.4,
        termination_grace_seconds=0.1,
    )
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(inputs=[item])
    assert error.value.code == "WORKER_TIMEOUT"
    pid = int(pid_file.read_text())
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"grandchild process {pid} survived process-group termination")


def _worker_authority_counts(
    repo: LocalArtifactRepository,
) -> tuple[int, int, int, int]:
    with repo._connect() as connection:
        counts = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("custody", "derivations", "reproductions")
        ]
        counts.append(
            connection.execute(
                "SELECT COUNT(*) FROM contents WHERE record_json LIKE '%worker-output%'"
            ).fetchone()[0]
        )
    return tuple(counts)  # type: ignore[return-value]


@pytest.mark.parametrize(
    "fault_point",
    ["bundle_after_blobs_before_transaction", "bundle_before_commit"],
)
def test_bundle_faults_leave_no_authoritative_prefix(
    tmp_path: Path, fault_point: str
) -> None:
    repo, gateway, item = setup(tmp_path, "output-count")

    def fail(point: str) -> None:
        if point == fault_point:
            raise RuntimeError("injected publication crash")

    repo._fault = fail
    with pytest.raises(RuntimeError, match="publication crash"):
        gateway.execute(inputs=[item])
    assert _worker_authority_counts(repo) == (0, 0, 0, 0)
    assert sum(1 for path in repo.blobs.rglob("*") if path.is_file()) >= 3


def test_gateway_fault_before_bundle_leaves_no_output_authority(tmp_path: Path) -> None:
    repo, original, item = setup(tmp_path, "success")

    def fail(point: str) -> None:
        if point == "before_bundle_publication":
            raise RuntimeError("gateway crash")

    gateway = WorkerGateway(repo, original.config, fault_injector=fail)
    with pytest.raises(RuntimeError, match="gateway crash"):
        gateway.execute(inputs=[item])
    assert _worker_authority_counts(repo) == (0, 0, 0, 0)


def test_reproduction_conflict_rolls_back_divergent_bundle(tmp_path: Path) -> None:
    repo, gateway, item = setup(tmp_path, "drift-output")
    first = gateway.execute(inputs=[item])
    before = _worker_authority_counts(repo)
    with pytest.raises(RecordConflict, match="changed outputs"):
        gateway.execute(inputs=[item])
    assert _worker_authority_counts(repo) == before == (1, 1, 1, 1)
    assert repo.get_derivation(first.derivation.derivation_id) == first.derivation


def test_success_with_grandchild_is_killed_and_rejected(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    _, gateway, item = setup(
        tmp_path / "run", "success-grandchild", "--pid-file", str(pid_file)
    )
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(inputs=[item])
    assert error.value.code == "DESCENDANT_PROCESS_LEAK"
    pid = int(pid_file.read_text())
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"leaked grandchild process {pid} was not terminated")


@pytest.mark.parametrize("scenario", ["duplicate-json-key", "nonfinite-json"])
def test_strict_json_rejects_duplicates_and_nonfinite(
    tmp_path: Path, scenario: str
) -> None:
    _, gateway, item = setup(tmp_path, scenario)
    with pytest.raises(WorkerGatewayError) as error:
        gateway.execute(inputs=[item])
    assert error.value.code == "MALFORMED_STDOUT"


def test_warning_limit_and_aggregate_input_limit(tmp_path: Path) -> None:
    _, gateway, item = setup(tmp_path / "warnings", "warning-overflow")
    with pytest.raises(WorkerGatewayError) as warning_error:
        gateway.execute(inputs=[item], limits={"maxWarnings": 1})
    assert warning_error.value.code == "WARNING_LIMIT_EXCEEDED"

    marker = tmp_path / "started"
    _, input_gateway, input_item = setup(
        tmp_path / "inputs", "mark-success", "--marker", str(marker)
    )
    with pytest.raises(WorkerGatewayError) as input_error:
        input_gateway.execute(inputs=[input_item], limits={"maxInputBytes": 4})
    assert input_error.value.code == "INPUT_SIZE_LIMIT_EXCEEDED"
    assert not marker.exists()

    with pytest.raises(WorkerGatewayError) as widened_error:
        input_gateway.execute(
            inputs=[input_item],
            limits={"maxCells": 1_000_001},
        )
    assert widened_error.value.code == "INPUT_INVALID"
    assert not marker.exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt acceptance probe")
def test_production_sandbox_denies_repository_write_and_detached_fork(
    tmp_path: Path,
) -> None:
    repo = LocalArtifactRepository(tmp_path / "repository")
    content = repo.put_bytes(
        b"input",
        kind="input",
        schema_version="v1",
        media_type="application/octet-stream",
    )
    item = GatewayInput("input", content.content_digest, "input.bin")
    poison = repo.root / "sandbox-poison"
    write_config = GatewayConfig(
        command=(sys.executable, str(FAKE), "mark-success", "--marker", str(poison)),
        cwd=PROJECT,
        sandbox_mode="macos-production",
        sandbox_read_roots=(PROJECT, Path(sys.executable).resolve().parent),
    )
    with pytest.raises(WorkerGatewayError):
        WorkerGateway(repo, write_config).execute(inputs=[item])
    assert not poison.exists()

    pid_file = repo.root / "detached.pid"
    fork_config = GatewayConfig(
        command=(
            sys.executable,
            str(FAKE),
            "detached-probe",
            "--pid-file",
            str(pid_file),
        ),
        cwd=PROJECT,
        sandbox_mode="macos-production",
        sandbox_read_roots=(PROJECT, Path(sys.executable).resolve().parent),
    )
    with pytest.raises(WorkerGatewayError):
        WorkerGateway(repo, fork_config).execute(inputs=[item])
    assert not pid_file.exists()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(0.2)
        port = listener.getsockname()[1]
        network_config = GatewayConfig(
            command=(
                sys.executable,
                str(FAKE),
                "network-probe",
                "--port",
                str(port),
            ),
            cwd=PROJECT,
            sandbox_mode="macos-production",
            sandbox_read_roots=(PROJECT, Path(sys.executable).resolve().parent),
        )
        with pytest.raises(WorkerGatewayError):
            WorkerGateway(repo, network_config).execute(inputs=[item])
        with pytest.raises(TimeoutError):
            listener.accept()

    assert sha256_digest(b"input") == content.content_digest
