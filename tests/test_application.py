from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tidy_orchestrator.application import run_fixture_suite
from tidy_orchestrator.artifacts import LocalArtifactRepository
from tidy_orchestrator.worker import GatewayConfig, WorkerGateway

PROJECT = Path(__file__).parents[1]
FAKE = Path(__file__).parent / "fixtures" / "fake_worker.py"


def test_actual_worker_provider_free_suite_runs_twice_identically(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["npm", "run", "build"], cwd=PROJECT, check=True, capture_output=True
    )
    repository = LocalArtifactRepository(tmp_path / "repository")
    first = run_fixture_suite(repository=repository, project_root=PROJECT)
    second = run_fixture_suite(repository=repository, project_root=PROJECT)
    assert first.index.content_digest == second.index.content_digest
    assert len(first.fixtures) == 3
    assert [item.fixture for item in first.fixtures] == [
        "simple-crosstab",
        "sparse-headers",
        "multi-table",
    ]
    assert [item.derivation_id for item in first.fixtures] == [
        item.derivation_id for item in second.fixtures
    ]
    assert [item.output_fingerprint for item in first.fixtures] == [
        item.output_fingerprint for item in second.fixtures
    ]
    assert first.network_isolation_enforced is True


def _fake_gateway(repository: LocalArtifactRepository, project: Path) -> WorkerGateway:
    return WorkerGateway(
        repository,
        GatewayConfig(
            command=(sys.executable, str(FAKE), "success"),
            cwd=project,
            sandbox_mode="insecure-test-only",
        ),
    )


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("workbooks/simple-crosstab.xlsx", "source-manifest mismatch"),
        ("gold/simple-crosstab/execution.json", "reference gold mismatch"),
        ("parity/source-manifest.json", "source-manifest identity"),
        ("gold/manifest.json", "reference-gold manifest identity"),
    ],
)
def test_suite_rejects_corrupted_fixture_and_gold_before_index(
    tmp_path: Path, relative: str, message: str
) -> None:
    project = tmp_path / "project"
    shutil.copytree(PROJECT / "fixtures", project / "fixtures")
    shutil.copytree(PROJECT / "tools", project / "tools")
    target = project / "fixtures" / relative
    target.write_bytes(target.read_bytes() + b"corrupt")
    repository = LocalArtifactRepository(tmp_path / "repository")
    with pytest.raises(RuntimeError, match=message):
        run_fixture_suite(
            repository=repository,
            project_root=project,
            gateway=_fake_gateway(repository, project),
        )
    with repository._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM contents "
                "WHERE record_json LIKE '%provider-free-suite-index%'"
            ).fetchone()[0]
            == 0
        )


def test_deterministically_wrong_worker_cannot_create_suite_index(
    tmp_path: Path,
) -> None:
    repository = LocalArtifactRepository(tmp_path / "repository")
    gateway = _fake_gateway(repository, PROJECT)
    with pytest.raises(RuntimeError, match="frozen reference gold"):
        run_fixture_suite(
            repository=repository,
            project_root=PROJECT,
            gateway=gateway,
        )
    with repository._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM contents "
                "WHERE record_json LIKE '%provider-free-suite-index%'"
            ).fetchone()[0]
            == 0
        )
