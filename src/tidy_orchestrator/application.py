"""Dagster-independent provider-free fixture application service."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import (
    ContentDescriptor,
    CustodyReceipt,
    LocalArtifactRepository,
    canonical_json_bytes,
    sha256_digest,
)
from .worker import GatewayConfig, GatewayExecution, GatewayInput, WorkerGateway

_SOURCE_MANIFEST_DIGEST = (
    "sha256:e0a37a53d7e031336938c417f4eb65f8dffdd8ba33cb2f7cfcc1df2fef5285e1"
)
_GOLD_MANIFEST_DIGEST = (
    "sha256:ff82511a94b5e9a420b7d9c3c675ea0e6d256cc47afea97702284c0ad3267a98"
)
_REFERENCE_COMMIT = "1be6c995fa931e9860468e40490433161b0121cb"
_REFERENCE_TREE = "96a76a1cbc6f2da3facd31d7cdae5b05926361d3"
_REFERENCE_RUNNER_DIGEST = (
    "sha256:1d8261c98fc13764a215a2f8440c482b0a9a957a19504e7f61fe3e35f1c4e46f"
)
_FIXTURE_ORDER = ("simple-crosstab", "sparse-headers", "multi-table")


@dataclass(frozen=True)
class FixtureReplay:
    fixture: str
    derivation_id: str
    reproduction_key: str
    output_fingerprint: str
    output_digests: tuple[str, ...]


@dataclass(frozen=True)
class SuiteReplay:
    fixtures: tuple[FixtureReplay, ...]
    index: ContentDescriptor
    network_isolation_enforced: bool


def actual_worker_gateway(
    repository: LocalArtifactRepository, project_root: Path
) -> WorkerGateway:
    node = shutil.which("node")
    worker = project_root / "dist" / "tidy-domain-worker.cjs"
    if node is None or not worker.is_file():
        raise RuntimeError("Build the TypeScript worker with `npm run build` first")
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError(
            "Production worker execution requires macOS /usr/bin/sandbox-exec; "
            "tests must construct an explicit insecure-test-only GatewayConfig"
        )
    resolved_node = Path(node).resolve()
    read_roots = [
        (project_root / "dist").resolve(),
        *_node_runtime_read_roots(resolved_node),
    ]
    openssl_configuration = Path("/opt/homebrew/etc/openssl@3")
    if openssl_configuration.is_dir():
        read_roots.append(openssl_configuration)
    return WorkerGateway(
        repository,
        GatewayConfig(
            command=(str(resolved_node), str(worker)),
            cwd=project_root.resolve(),
            sandbox_mode="macos-production",
            sandbox_read_roots=tuple(read_roots),
        ),
    )


def _node_runtime_read_roots(node: Path) -> tuple[Path, ...]:
    roots = {node.parent.parent.resolve()}
    completed = subprocess.run(
        ["/usr/bin/otool", "-L", str(node)],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    for line in completed.stdout.splitlines()[1:]:
        raw = line.strip().split(" ", 1)[0]
        if raw.startswith("/opt/homebrew/"):
            roots.add(Path(raw).parent)
            roots.add(Path(raw).resolve().parent)
    return tuple(sorted(roots, key=str))


def load_verified_fixture_manifests(
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load only the two identity-pinned fixture manifests and verify their closure."""
    project_root = project_root.resolve()
    fixture_manifest_path = (
        project_root / "fixtures" / "parity" / "source-manifest.json"
    )
    fixture_manifest_bytes = fixture_manifest_path.read_bytes()
    if sha256_digest(fixture_manifest_bytes) != _SOURCE_MANIFEST_DIGEST:
        raise RuntimeError("Fixture source-manifest identity is not approved")
    fixture_manifest = json.loads(fixture_manifest_bytes)
    _verify_source_manifest_provenance(fixture_manifest)
    _verify_manifest_files(project_root, fixture_manifest["files"])

    gold_manifest_path = project_root / "fixtures" / "gold" / "manifest.json"
    gold_manifest_bytes = gold_manifest_path.read_bytes()
    if sha256_digest(gold_manifest_bytes) != _GOLD_MANIFEST_DIGEST:
        raise RuntimeError("Frozen reference-gold manifest identity is not approved")
    gold_manifest = json.loads(gold_manifest_bytes)
    _verify_gold_provenance(project_root, gold_manifest)
    _verify_and_index_gold(project_root, gold_manifest["fixtures"])
    return fixture_manifest, gold_manifest


def run_fixture_suite(
    *,
    repository: LocalArtifactRepository,
    project_root: Path,
    gateway: WorkerGateway | None = None,
) -> SuiteReplay:
    project_root = project_root.resolve()
    fixture_manifest, gold_manifest = load_verified_fixture_manifests(project_root)
    gold = _verify_and_index_gold(project_root, gold_manifest["fixtures"])
    names = list(_FIXTURE_ORDER)
    active_gateway = gateway or actual_worker_gateway(repository, project_root)
    observed_at = datetime.now(UTC).isoformat()
    replays: list[FixtureReplay] = []
    for name in names:
        workbook_path = project_root / "fixtures" / "workbooks" / f"{name}.xlsx"
        recipe_path = project_root / "fixtures" / "recipes" / f"{name}.json"
        workbook = repository.put_bytes(
            workbook_path.read_bytes(),
            kind="fixture-workbook",
            schema_version="tidy.fixture/v1",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        recipe = repository.put_bytes(
            recipe_path.read_bytes(),
            kind="fixture-recipe",
            schema_version="recipe-v01",
            media_type="application/json",
        )
        for descriptor, source in ((workbook, workbook_path), (recipe, recipe_path)):
            repository.add_custody(
                CustodyReceipt.create(
                    content_digest=descriptor.content_digest,
                    storage_uri=f"fixture://{source.relative_to(project_root).as_posix()}",
                    observed_at=observed_at,
                    actor="tidy.provider-free-demo/v1",
                    source_locator=source.relative_to(project_root).as_posix(),
                    classification="licensed-synthetic-parity-fixture",
                )
            )
        executions = [
            _execute_fixture(active_gateway, workbook, recipe) for _ in range(2)
        ]
        first, second = executions
        first_signature = _execution_signature(first)
        second_signature = _execution_signature(second)
        if first_signature != second_signature:
            raise RuntimeError(f"{name}: run-twice fingerprints diverged")
        _assert_reference_gold(name, first, gold[name])
        _assert_reference_gold(name, second, gold[name])
        replays.append(
            FixtureReplay(
                fixture=name,
                derivation_id=first.derivation.derivation_id,
                reproduction_key=first.reproduction_key,
                output_fingerprint=first.output_fingerprint,
                output_digests=tuple(item.content_digest for item in first.outputs),
            )
        )
    index_bytes = canonical_json_bytes(
        {
            "schemaVersion": "tidy.provider-free-suite/v1",
            "fixtures": [
                {
                    "fixture": item.fixture,
                    "derivationId": item.derivation_id,
                    "reproductionKey": item.reproduction_key,
                    "outputFingerprint": item.output_fingerprint,
                    "outputDigests": item.output_digests,
                }
                for item in replays
            ],
            "networkIsolationEnforced": (
                active_gateway.config.network_isolation_enforced
            ),
            "referenceGoldVerified": True,
            "providerCalls": 0,
        }
    )
    index = repository.put_bytes(
        index_bytes,
        kind="provider-free-suite-index",
        schema_version="tidy.provider-free-suite/v1",
        media_type="application/json",
    )
    return SuiteReplay(
        fixtures=tuple(replays),
        index=index,
        network_isolation_enforced=active_gateway.config.network_isolation_enforced,
    )


def suite_wire(result: SuiteReplay) -> dict[str, Any]:
    return {
        "schemaVersion": "tidy.provider-free-demo-result/v1",
        "providerCalls": 0,
        "networkIsolationEnforced": result.network_isolation_enforced,
        "referenceGoldVerified": True,
        "indexDigest": result.index.content_digest,
        "fixtures": [
            {
                "fixture": item.fixture,
                "derivationId": item.derivation_id,
                "reproductionKey": item.reproduction_key,
                "outputFingerprint": item.output_fingerprint,
                "outputDigests": item.output_digests,
            }
            for item in result.fixtures
        ],
    }


def _verify_source_manifest_provenance(manifest: dict[str, Any]) -> None:
    if (
        manifest.get("schemaVersion") != "tidy.fixture-source-manifest/v1"
        or manifest.get("sourceRepository")
        != "https://github.com/ianmoran11/tidycell.git"
        or manifest.get("sourceCommit") != _REFERENCE_COMMIT
        or tuple(manifest.get("admissionOrder", ())) != _FIXTURE_ORDER
        or manifest.get("license", {}).get("spdx") != "MIT"
    ):
        raise RuntimeError("Fixture source-manifest provenance is invalid")


def _verify_gold_provenance(project_root: Path, manifest: dict[str, Any]) -> None:
    reference = manifest.get("reference", {})
    runner = manifest.get("runner", {})
    toolchain = manifest.get("toolchain", {})
    if (
        manifest.get("schemaVersion") != "tidy.reference-gold/v1"
        or manifest.get("classification") != "independent-pinned-reference-bytes"
        or reference.get("commit") != _REFERENCE_COMMIT
        or reference.get("tree") != _REFERENCE_TREE
        or runner.get("contentDigest") != _REFERENCE_RUNNER_DIGEST
        or toolchain.get("node") != "24.7.0"
        or toolchain.get("npm") != "11.5.1"
        or tuple(item.get("name") for item in manifest.get("fixtures", ()))
        != _FIXTURE_ORDER
    ):
        raise RuntimeError("Frozen reference-gold provenance is invalid")
    runner_path = project_root / str(runner.get("path", ""))
    if sha256_digest(runner_path.read_bytes()) != _REFERENCE_RUNNER_DIGEST:
        raise RuntimeError("Reference runner identity is invalid")


def _verify_manifest_files(project_root: Path, files: list[dict[str, Any]]) -> None:
    for entry in files:
        path = project_root / entry["copiedPath"]
        data = path.read_bytes()
        expected_digest = f"sha256:{entry['sha256']}"
        if len(data) != entry["byteLength"] or sha256_digest(data) != expected_digest:
            raise RuntimeError(
                f"Fixture source-manifest mismatch: {entry['copiedPath']}"
            )


def _verify_and_index_gold(
    project_root: Path, fixtures: list[dict[str, Any]]
) -> dict[str, tuple[tuple[str, str, str, int], ...]]:
    result: dict[str, tuple[tuple[str, str, str, int], ...]] = {}
    for fixture in fixtures:
        expected: list[tuple[str, str, str, int]] = []
        for descriptor in fixture["outputs"]:
            path = (
                project_root
                / "fixtures"
                / "gold"
                / fixture["name"]
                / descriptor["relativePath"]
            )
            data = path.read_bytes()
            if (
                len(data) != descriptor["byteLength"]
                or sha256_digest(data) != descriptor["contentDigest"]
            ):
                raise RuntimeError(f"Frozen reference gold mismatch: {path}")
            expected.append(
                (
                    descriptor["name"],
                    descriptor["relativePath"],
                    descriptor["contentDigest"],
                    descriptor["byteLength"],
                )
            )
        result[fixture["name"]] = tuple(expected)
    return result


def _assert_reference_gold(
    fixture: str,
    execution: GatewayExecution,
    expected: tuple[tuple[str, str, str, int], ...],
) -> None:
    actual = tuple(
        (
            name,
            path,
            descriptor.content_digest,
            descriptor.byte_length,
        )
        for name, path, descriptor in zip(
            execution.output_names,
            execution.output_paths,
            execution.outputs,
            strict=True,
        )
    )
    if actual != expected:
        raise RuntimeError(
            f"{fixture}: worker outputs differ from frozen reference gold"
        )


def _execute_fixture(
    gateway: WorkerGateway,
    workbook: ContentDescriptor,
    recipe: ContentDescriptor,
) -> GatewayExecution:
    return gateway.execute(
        inputs=(
            GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),
            GatewayInput("recipe", recipe.content_digest, "recipe.json"),
        ),
        parameters={
            "evidenceProfile": "m2-deterministic-parity-v1",
            "csvMode": "recipe-aware",
        },
    )


def _execution_signature(execution: GatewayExecution) -> tuple[Any, ...]:
    return (
        execution.derivation.derivation_id,
        execution.reproduction_key,
        execution.output_fingerprint,
        execution.output_paths,
        tuple(item.content_digest for item in execution.outputs),
    )
