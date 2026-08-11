"""Sandboxed Python authority for the one-time TypeScript migration worker.

The gateway reads only already imported, digest-bound CAS bytes. It verifies the
worker bundle and response, publishes output blobs durably, and then commits
output custody, derivation, and reproduction authority in one SQLite
transaction. It never activates recipes or grants training authority.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema.validators import validator_for

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .legacy_approvals import (
    create_recipe_digest_verification,
    persist_fixture_legacy_approval_snapshot,
)
from .migration_import import (
    BlobIntegrityError,
    CommittedFilesystemBlobStore,
    MigrationImportError,
    MigrationRepository,
)
from .worker import (
    GatewayConfig,
    GatewayInput,
    WorkerDomainFailure,
    WorkerGateway,
    WorkerGatewayError,
    _read_regular_file,
    _safe_relative,
    _write_private,
)

_PROTOCOL_VERSION = "tidy.migration-worker/v1"
_HISTORICAL_DIGEST_ALGORITHM = "tidycell-digest-record-v1"
_HISTORICAL_DIGEST_SOURCE = (
    "sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c"
)
_OUTPUT_RECORD_VERSION = "tidy.migration-worker-output/v1"
_DERIVATION_VERSION = "tidy.migration-worker-derivation/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT = Path(__file__).parents[2]
_CONTRACTS = _PROJECT / "contracts/migration-worker/v1"
_IMPORT_CONTRACTS = _PROJECT / "contracts/import/v1"
_OPERATIONS = frozenset(
    (
        "health",
        "capabilities",
        "digest-legacy-approval-registry-v1",
        "parse-recipe-v01",
    )
)
_INTERPRETATIONS = frozenset(("digest-legacy-approval-registry-v1", "parse-recipe-v01"))
_OPERATION_INPUTS = {
    "health": None,
    "capabilities": None,
    "digest-legacy-approval-registry-v1": ("registry", "approval-registry"),
    "parse-recipe-v01": ("recipe", "recipe-evidence"),
}
_OPERATION_OUTPUTS = {
    "health": ("health", "health.json", "tidy.migration-worker-health/v1"),
    "capabilities": (
        "capabilities",
        "capabilities.json",
        "tidy.migration-worker-capabilities/v1",
    ),
    "digest-legacy-approval-registry-v1": (
        "approval-row-digests",
        "approval-row-digests.json",
        "tidy.migration-approval-row-digests/v1",
    ),
    "parse-recipe-v01": (
        "recipe-revision",
        "recipe-revision.json",
        "tidy.migration-recipe-revision/v1",
    ),
}
_MAX_LIMITS = {
    "maxInputBytes": 8 * 1024 * 1024,
    "maxOutputBytes": 8 * 1024 * 1024,
    "maxJsonDepth": 128,
    "maxJsonNodes": 1_000_000,
    "maxRecords": 100_000,
}
_DEFAULT_LIMITS = dict(_MAX_LIMITS)


@dataclass(frozen=True)
class MigrationSourceBinding:
    source_snapshot_digest: str
    source_item_digest: str
    import_record_id: str
    relative_path: str

    def __post_init__(self) -> None:
        for value in (
            self.source_snapshot_digest,
            self.source_item_digest,
            self.import_record_id,
        ):
            if not _DIGEST.fullmatch(value):
                raise ValueError("Migration source binding digest is invalid")
        if len(self.relative_path) > 4096:
            raise ValueError("Migration source path exceeds 4096 characters")
        _safe_relative(self.relative_path)

    @classmethod
    def from_import_record(
        cls, import_record: Mapping[str, Any]
    ) -> MigrationSourceBinding:
        return cls(
            source_snapshot_digest=str(import_record["snapshotDigest"]),
            source_item_digest=str(import_record["sourceItemDigest"]),
            import_record_id=str(import_record["recordId"]),
            relative_path=str(import_record["relativePath"]),
        )

    def wire(self) -> dict[str, str]:
        return {
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "sourceItemDigest": self.source_item_digest,
            "importRecordId": self.import_record_id,
            "relativePath": self.relative_path,
        }


@dataclass(frozen=True)
class MigrationGatewayOutput:
    record: Mapping[str, Any]
    artifact: Mapping[str, Any]

    @property
    def content_digest(self) -> str:
        return str(self.record["contentDigest"])


@dataclass(frozen=True)
class MigrationGatewayExecution:
    request_id: str
    operation: str
    outputs: tuple[MigrationGatewayOutput, ...]
    derivation: Mapping[str, Any]
    producer_digest: str
    gateway_digest: str
    reproduction_key: str
    output_fingerprint: str


@dataclass(frozen=True)
class LegacyApprovalGatewayResult:
    execution: MigrationGatewayExecution
    approval_snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class RecipeVerificationGatewayResult:
    execution: MigrationGatewayExecution
    verification: Mapping[str, Any]


class MigrationWorkerGateway(WorkerGateway):
    """Execute one bounded migration interpretation from imported CAS bytes."""

    def __init__(
        self,
        metadata: MigrationRepository,
        blobs: CommittedFilesystemBlobStore,
        config: GatewayConfig,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        # WorkerGateway's low-level process, output, and Seatbelt methods are
        # deliberately reused; its domain-worker execute/publication path is not.
        if os.name != "posix":
            raise RuntimeError("Migration worker process guarantees are POSIX-only")
        if config.cwd.resolve() != _PROJECT.resolve():
            raise MigrationImportError(
                "Migration worker cwd must be the project root that owns contracts"
            )
        self.repository = metadata
        self.metadata = metadata
        self.blobs = blobs
        self.config = config
        self._fault = fault_injector
        metadata_root = metadata.root.resolve()
        blob_root = blobs.root.resolve()
        if _paths_overlap(metadata_root, blob_root):
            raise MigrationImportError(
                "Migration metadata and blob roots must not overlap"
            )
        self.staging = metadata.root / "migration-worker-staging"
        self.staging.mkdir(mode=0o700, exist_ok=True)
        staging_info = self.staging.lstat()
        if stat.S_ISLNK(staging_info.st_mode) or not stat.S_ISDIR(staging_info.st_mode):
            raise MigrationImportError("Migration worker staging root is unsafe")
        self.staging.chmod(0o700)

    def digest_imported_approval_registry(
        self, import_record: Mapping[str, Any]
    ) -> MigrationGatewayExecution:
        item, source = _gateway_input_from_import_record(import_record, "registry")
        return self.execute(
            operation="digest-legacy-approval-registry-v1",
            inputs=[item],
            source=source,
        )

    def parse_imported_recipe(
        self,
        import_record: Mapping[str, Any],
        *,
        declared_recipe_digest: str | None = None,
    ) -> MigrationGatewayExecution:
        item, source = _gateway_input_from_import_record(import_record, "recipe")
        return self.execute(
            operation="parse-recipe-v01",
            inputs=[item],
            source=source,
            declared_recipe_digest=declared_recipe_digest,
        )

    def execute(
        self,
        *,
        operation: str,
        inputs: Sequence[GatewayInput] = (),
        source: MigrationSourceBinding | None = None,
        declared_recipe_digest: str | None = None,
        limits: Mapping[str, int] | None = None,
    ) -> MigrationGatewayExecution:
        if operation not in _OPERATIONS:
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Unknown migration operation"
            )
        expected_input = _OPERATION_INPUTS[operation]
        if expected_input is None:
            if inputs or source is not None or declared_recipe_digest is not None:
                raise WorkerGatewayError(
                    "INPUT_INVALID",
                    "INPUT_INVALID",
                    "Probe operations accept no source, input, or recipe digest",
                )
        else:
            if len(inputs) != 1 or source is None:
                raise WorkerGatewayError(
                    "INPUT_INVALID",
                    "INPUT_INVALID",
                    "Migration interpretation requires one input and source binding",
                )
            if inputs[0].name != expected_input[0]:
                raise WorkerGatewayError(
                    "INPUT_INVALID", "INPUT_INVALID", "Unexpected migration input name"
                )
            if declared_recipe_digest is not None and operation != "parse-recipe-v01":
                raise WorkerGatewayError(
                    "INPUT_INVALID",
                    "INPUT_INVALID",
                    "Only RecipeV01 parsing accepts a declared recipe digest",
                )
        if declared_recipe_digest is not None and not _DIGEST.fullmatch(
            declared_recipe_digest
        ):
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Declared recipe digest is invalid"
            )
        effective_limits = self._effective_limits(limits)
        admitted, source_wire = self._admit_input(
            operation=operation,
            inputs=inputs,
            source=source,
            max_input_bytes=effective_limits["maxInputBytes"],
        )
        request_id = str(uuid.uuid4())
        run_root = Path(tempfile.mkdtemp(prefix="run-", dir=self.staging))
        run_root.chmod(0o700)
        input_root = run_root / "inputs"
        output_root = run_root / "outputs"
        home = run_root / "home"
        temporary = run_root / "tmp"
        for directory in (input_root, output_root, home, temporary):
            directory.mkdir(mode=0o700)
        stdout_path = run_root / "stdout.bin"
        stderr_path = run_root / "stderr.bin"
        try:
            request_inputs: list[dict[str, Any]] = []
            ordered_input_digests: list[str] = []
            if admitted is not None:
                item, relative, data = admitted
                destination = input_root / relative
                destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                _write_private(destination, data, mode=0o400)
                request_inputs.append(
                    {
                        "name": item.name,
                        "relativePath": relative.as_posix(),
                        "contentDigest": item.content_digest,
                        "byteLength": len(data),
                    }
                )
                ordered_input_digests.append(item.content_digest)
            parameters: dict[str, Any] = {}
            if source_wire is not None:
                parameters["source"] = {
                    key: source_wire[key]
                    for key in (
                        "sourceSnapshotDigest",
                        "sourceItemDigest",
                        "importRecordId",
                        "relativePath",
                    )
                }
            if declared_recipe_digest is not None:
                parameters["declaredRecipeDigest"] = declared_recipe_digest
            request = {
                "protocolVersion": _PROTOCOL_VERSION,
                "requestId": request_id,
                "operation": operation,
                "inputs": request_inputs,
                "parameters": parameters,
                "limits": effective_limits,
            }
            request_path = run_root / "request.json"
            _write_private(request_path, canonical_json_bytes(request), mode=0o400)
            command = [
                *self.config.command,
                "--request",
                str(request_path),
                "--input-root",
                str(input_root),
                "--output-root",
                str(output_root),
            ]
            producer_before = self._producer_manifest_bytes()
            gateway_before = _gateway_source_digest()
            environment = self._minimal_environment(home, temporary)
            launch_command, sandbox_profile_digest = self._sandbox_command(
                command, run_root
            )
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    launch_command,
                    cwd=self.config.cwd,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    close_fds=True,
                    start_new_session=True,
                    preexec_fn=self._apply_limits,
                )
                return_code = self._wait_bounded(
                    process, output_root, stdout_path, stderr_path
                )
            producer_after = self._producer_manifest_bytes()
            gateway_after = _gateway_source_digest()
            if producer_before != producer_after or gateway_before != gateway_after:
                raise WorkerGatewayError(
                    "PRODUCER_DRIFT",
                    "INTEGRITY_VIOLATION",
                    "Migration worker producer changed during execution",
                )
            self._check_stream_sizes(stdout_path, stderr_path)
            stdout_bytes = stdout_path.read_bytes()
            if not stdout_bytes and stderr_path.stat().st_size:
                preview = stderr_path.read_bytes()[:512].decode(
                    "utf-8", errors="replace"
                )
                raise WorkerGatewayError(
                    "MALFORMED_STDOUT",
                    "TOOL_INCOMPATIBLE",
                    f"Migration worker emitted no response: {preview}",
                )
            response = _parse_migration_response(
                stdout_bytes,
                request_id=request_id,
                max_json_depth=effective_limits["maxJsonDepth"],
                max_json_nodes=effective_limits["maxJsonNodes"],
            )
            if response["ok"] is False:
                if return_code != 1:
                    raise WorkerGatewayError(
                        "STATUS_EXIT_MISMATCH",
                        "TOOL_INCOMPATIBLE",
                        "Migration worker error did not use exit code 1",
                    )
                self._assert_output_root_empty(output_root)
                raise WorkerDomainFailure(response["error"])
            if return_code != 0:
                preview = stderr_path.read_bytes()[:512].decode(
                    "utf-8", errors="replace"
                )
                raise WorkerGatewayError(
                    "WORKER_NONZERO_EXIT",
                    "INFRA_TRANSIENT",
                    f"Migration worker exited with code {return_code}: {preview}",
                )
            verified = self._verify_outputs(output_root, response["outputs"])
            if (
                sum(len(data) for _descriptor, data in verified)
                > effective_limits["maxOutputBytes"]
            ):
                raise WorkerGatewayError(
                    "OUTPUT_SIZE_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    "Migration outputs exceed the declared aggregate limit",
                )
            artifacts = self._validate_artifacts(
                operation=operation,
                verified=verified,
                source_wire=source_wire,
                declared_recipe_digest=declared_recipe_digest,
                max_json_depth=effective_limits["maxJsonDepth"],
                max_json_nodes=effective_limits["maxJsonNodes"],
                max_records=effective_limits["maxRecords"],
            )
            producer_final = self._producer_manifest_bytes()
            gateway_final = _gateway_source_digest()
            if producer_final != producer_before or gateway_final != gateway_before:
                raise WorkerGatewayError(
                    "PRODUCER_DRIFT",
                    "INTEGRITY_VIOLATION",
                    "Migration producer changed while validating outputs",
                )
            # Reconcile source authority and immutable CAS bytes again after the
            # untrusted process has exited and before publishing any authority.
            if source is not None:
                self._admit_input(
                    operation=operation,
                    inputs=inputs,
                    source=source,
                    max_input_bytes=effective_limits["maxInputBytes"],
                )
            configuration_digest = domain_digest(
                "tidy.migration-worker-configuration/v1",
                {
                    "operation": operation,
                    "parameters": parameters,
                    "limits": effective_limits,
                    "sandboxMode": self.config.sandbox_mode,
                    "networkIsolationEnforced": self.config.network_isolation_enforced,
                    "sandboxProfileDigest": sandbox_profile_digest,
                },
            )
            producer_digest = domain_digest(
                "tidy.producer-manifest/v1", json.loads(producer_final)
            )
            gateway_digest = gateway_final
            producer_digests = [producer_digest, gateway_digest]
            ordered_output_digests = [
                str(descriptor["contentDigest"]) for descriptor, _data in verified
            ]
            reproduction_key = domain_digest(
                "tidy.reproduction-key/v1",
                {
                    "operation": operation,
                    "contractVersion": _PROTOCOL_VERSION,
                    "orderedInputDigests": ordered_input_digests,
                    "configurationDigest": configuration_digest,
                    "producerDigests": producer_digests,
                },
            )
            output_fingerprint = domain_digest(
                "tidy.output-set/v1",
                [
                    [descriptor["relativePath"], descriptor["contentDigest"]]
                    for descriptor, _data in verified
                ],
            )
            derivation_semantic = {
                "operation": operation,
                "contractVersion": _PROTOCOL_VERSION,
                "orderedInputDigests": ordered_input_digests,
                "configurationDigest": configuration_digest,
                "producerDigests": producer_digests,
                "orderedOutputDigests": ordered_output_digests,
            }
            derivation = {
                "schemaVersion": _DERIVATION_VERSION,
                "derivationId": domain_digest(
                    "tidy.derivation/v1", derivation_semantic
                ),
                **derivation_semantic,
            }
            output_records: list[dict[str, Any]] = []
            for output_index, ((descriptor, data), artifact) in enumerate(
                zip(verified, artifacts, strict=True)
            ):
                self.blobs.publish_bytes(
                    data,
                    expected_digest=str(descriptor["contentDigest"]),
                    expected_length=int(descriptor["byteLength"]),
                )
                semantic = {
                    "schemaVersion": _OUTPUT_RECORD_VERSION,
                    "operation": operation,
                    "contractVersion": _PROTOCOL_VERSION,
                    "source": source_wire,
                    "configurationDigest": configuration_digest,
                    "producerDigest": producer_digest,
                    "derivationId": derivation["derivationId"],
                    "reproductionKey": reproduction_key,
                    "outputFingerprint": output_fingerprint,
                    "outputIndex": output_index,
                    "name": descriptor["name"],
                    "relativePath": descriptor["relativePath"],
                    "artifactSchemaVersion": _artifact_schema_version(
                        operation, artifact
                    ),
                    "contentDigest": descriptor["contentDigest"],
                    "byteLength": descriptor["byteLength"],
                    "storageUri": self.blobs.storage_uri(
                        str(descriptor["contentDigest"])
                    ),
                    "isolationMode": self.config.sandbox_mode,
                    "networkIsolationEnforced": (
                        self.config.network_isolation_enforced
                    ),
                    "active": False,
                    "trainingEligible": False,
                }
                output_records.append(
                    {
                        **semantic,
                        "recordId": domain_digest(_OUTPUT_RECORD_VERSION, semantic),
                    }
                )
            self._inject("after_output_blobs_before_metadata")
            published = self.metadata.publish_migration_worker_bundle(
                outputs=output_records,
                derivation=derivation,
                reproduction_key=reproduction_key,
                output_fingerprint=output_fingerprint,
                blob_store=self.blobs,
            )
            return MigrationGatewayExecution(
                request_id=request_id,
                operation=operation,
                outputs=tuple(
                    MigrationGatewayOutput(record=record, artifact=artifact)
                    for record, artifact in zip(published, artifacts, strict=True)
                ),
                derivation=derivation,
                producer_digest=producer_digest,
                gateway_digest=gateway_digest,
                reproduction_key=reproduction_key,
                output_fingerprint=output_fingerprint,
            )
        except BlobIntegrityError as error:
            raise WorkerGatewayError(
                "BLOB_INTEGRITY_VIOLATION",
                "INTEGRITY_VIOLATION",
                str(error),
            ) from error
        finally:
            shutil.rmtree(run_root, ignore_errors=True)

    def _effective_limits(self, supplied: Mapping[str, int] | None) -> dict[str, int]:
        values = dict(_DEFAULT_LIMITS)
        if supplied:
            if set(supplied) - set(values):
                raise WorkerGatewayError(
                    "INPUT_INVALID", "INPUT_INVALID", "Unknown migration limit"
                )
            for name, value in supplied.items():
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value <= 0
                    or value > _MAX_LIMITS[name]
                ):
                    raise WorkerGatewayError(
                        "INPUT_INVALID",
                        "INPUT_INVALID",
                        "Migration limits must be positive and may not widen maxima",
                    )
                values[name] = value
        values["maxOutputBytes"] = min(
            values["maxOutputBytes"], self.config.max_output_bytes
        )
        return values

    def _admit_input(
        self,
        *,
        operation: str,
        inputs: Sequence[GatewayInput],
        source: MigrationSourceBinding | None,
        max_input_bytes: int,
    ) -> tuple[
        tuple[GatewayInput, PurePosixPath, bytes] | None,
        dict[str, Any] | None,
    ]:
        if source is None:
            return None, None
        item = inputs[0]
        relative = _safe_relative(item.relative_path)
        import_record = self.metadata.get_item(
            source.source_snapshot_digest, source.relative_path
        )
        if import_record is None:
            raise WorkerGatewayError(
                "SOURCE_BINDING_MISMATCH",
                "INTEGRITY_VIOLATION",
                "Migration source import record was not found",
            )
        expected = _OPERATION_INPUTS[operation]
        assert expected is not None
        if (
            import_record.get("snapshotDigest") != source.source_snapshot_digest
            or import_record.get("sourceItemDigest") != source.source_item_digest
            or import_record.get("recordId") != source.import_record_id
            or import_record.get("relativePath") != source.relative_path
            or import_record.get("artifactClass") != expected[1]
            or import_record.get("finalState") not in {"imported", "duplicate-alias"}
            or import_record.get("blobStored") is not True
            or import_record.get("contentDigest") != item.content_digest
        ):
            raise WorkerGatewayError(
                "SOURCE_BINDING_MISMATCH",
                "INTEGRITY_VIOLATION",
                "Migration input does not match its imported source authority",
            )
        byte_length = int(import_record["byteLength"])
        if byte_length > max_input_bytes or (
            item.declared_byte_length is not None
            and item.declared_byte_length != byte_length
        ):
            raise WorkerGatewayError(
                "INPUT_SIZE_LIMIT_EXCEEDED",
                "INPUT_INVALID",
                "Migration input length differs or exceeds its limit",
            )
        data = self.blobs.read_verified(item.content_digest, byte_length)
        source_wire = {
            **source.wire(),
            "sourceContentDigest": item.content_digest,
            "byteLength": byte_length,
        }
        return (item, relative, data), source_wire

    def _validate_artifacts(
        self,
        *,
        operation: str,
        verified: Sequence[tuple[Mapping[str, Any], bytes]],
        source_wire: Mapping[str, Any] | None,
        declared_recipe_digest: str | None,
        max_json_depth: int,
        max_json_nodes: int,
        max_records: int,
    ) -> tuple[dict[str, Any], ...]:
        expected_name, expected_path, _schema_version = _OPERATION_OUTPUTS[operation]
        if len(verified) != 1:
            raise WorkerGatewayError(
                "INVALID_RESPONSE",
                "TOOL_INCOMPATIBLE",
                "Migration operation must publish exactly one output",
            )
        descriptor, data = verified[0]
        if (
            descriptor["name"] != expected_name
            or descriptor["relativePath"] != expected_path
        ):
            raise WorkerGatewayError(
                "INVALID_RESPONSE",
                "TOOL_INCOMPATIBLE",
                "Migration output name or path is not canonical",
            )
        artifact = _strict_json_bytes(
            data,
            "migration output",
            max_json_depth=max_json_depth,
            max_json_nodes=max_json_nodes,
        )
        if not isinstance(artifact, dict):
            raise WorkerGatewayError(
                "INVALID_OUTPUT_ARTIFACT",
                "TOOL_INCOMPATIBLE",
                "Migration output is not a JSON object",
            )
        _validate_artifact_schema(operation, artifact)
        if operation in _INTERPRETATIONS and artifact.get("source") != source_wire:
            raise WorkerGatewayError(
                "SOURCE_BINDING_MISMATCH",
                "INTEGRITY_VIOLATION",
                "Migration output does not retain the exact source binding",
            )
        if operation == "parse-recipe-v01":
            if artifact["declaredRecipeDigest"] != declared_recipe_digest:
                raise WorkerGatewayError(
                    "INVALID_OUTPUT_ARTIFACT",
                    "INTEGRITY_VIOLATION",
                    "Migration output did not retain the declared recipe digest",
                )
            expected_match = (
                None
                if declared_recipe_digest is None
                else artifact["historicalRecipeDigest"] == declared_recipe_digest
            )
            if artifact["digestMatches"] is not expected_match:
                raise WorkerGatewayError(
                    "INVALID_OUTPUT_ARTIFACT",
                    "INTEGRITY_VIOLATION",
                    "Migration recipe digest comparison is inconsistent",
                )
        if operation == "digest-legacy-approval-registry-v1":
            records = artifact["records"]
            if len(records) > max_records:
                raise WorkerGatewayError(
                    "RECORD_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    "Approval row digests exceed the declared record limit",
                )
            if artifact["recordCount"] != len(records) or [
                record["index"] for record in records
            ] != list(range(len(records))):
                raise WorkerGatewayError(
                    "INVALID_OUTPUT_ARTIFACT",
                    "TOOL_INCOMPATIBLE",
                    "Approval row digest indexes are not complete and ordered",
                )
        return (artifact,)

    def _check_stream_sizes(self, stdout: Path, stderr: Path) -> None:
        if stdout.stat().st_size > min(self.config.max_stdout_bytes, 1_000_000):
            raise WorkerGatewayError(
                "STDOUT_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Migration worker stdout exceeded its byte cap",
            )
        if stderr.stat().st_size > self.config.max_stderr_bytes:
            raise WorkerGatewayError(
                "STDERR_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Migration worker stderr exceeded its byte cap",
            )

    def _producer_manifest_bytes(self) -> bytes:
        cwd = self.config.cwd.resolve()
        files: dict[str, str] = {}

        def add_file(label: str, path: Path) -> None:
            files[label] = sha256_digest(_read_regular_file(path.resolve()))

        executable = Path(self.config.command[0]).resolve()
        add_file("resolved-executable", executable)
        arguments: list[dict[str, str]] = []
        for index, raw in enumerate(self.config.command[1:], start=1):
            candidate = Path(raw)
            resolved_candidate = (
                candidate.resolve()
                if candidate.is_absolute()
                else (cwd / candidate).resolve()
            )
            if resolved_candidate.is_file():
                try:
                    logical = resolved_candidate.relative_to(cwd).as_posix()
                except ValueError:
                    logical = f"external-file-{index}:{resolved_candidate.name}"
                label = f"command-file-{index}:{logical}"
                add_file(label, resolved_candidate)
                arguments.append({"kind": "file", "label": label})
            elif candidate.is_absolute():
                arguments.append({"kind": "external-path", "index": str(index)})
            else:
                arguments.append({"kind": "literal", "value": raw})
        required_sources = (
            cwd / "package-lock.json",
            cwd / "package.json",
            cwd / ".node-version",
            cwd / "tsconfig.json",
            cwd / "apps/migration-worker/src/cli.ts",
            cwd / "apps/migration-worker/src/protocol.ts",
            cwd / "apps/domain-worker/src/migration/historicalDigestRecord.ts",
            cwd / "apps/domain-worker/src/recipe/schema.ts",
            cwd / "apps/domain-worker/src/address.ts",
            cwd / "fixtures/migration/digest-record-v1.json",
        )
        if any(not path.is_file() for path in required_sources):
            raise WorkerGatewayError(
                "PRODUCER_IDENTITY_FAILED",
                "INTEGRITY_VIOLATION",
                "Migration worker source closure is incomplete",
            )
        for path in required_sources:
            add_file(path.relative_to(cwd).as_posix(), path)
        contract_root = cwd / "contracts/migration-worker/v1"
        contract_paths = sorted(
            (item for item in contract_root.rglob("*") if item.is_file()),
            key=lambda item: item.as_posix(),
        )
        if not contract_paths:
            raise WorkerGatewayError(
                "PRODUCER_IDENTITY_FAILED",
                "INTEGRITY_VIOLATION",
                "Migration worker contract closure is incomplete",
            )
        for path in contract_paths:
            add_file(path.relative_to(cwd).as_posix(), path)
        try:
            version = subprocess.run(
                [str(executable), "--version"],
                check=True,
                capture_output=True,
                timeout=5,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise WorkerGatewayError(
                "PRODUCER_IDENTITY_FAILED",
                "INTEGRITY_VIOLATION",
                "Could not capture migration worker runtime identity",
            ) from error
        runtime_version = (
            (version.stdout + version.stderr).decode("utf-8", errors="strict").strip()
        )
        if not runtime_version or len(runtime_version) > 256:
            raise WorkerGatewayError(
                "PRODUCER_IDENTITY_FAILED",
                "INTEGRITY_VIOLATION",
                "Migration worker runtime version is invalid",
            )
        return canonical_json_bytes(
            {
                "schemaVersion": "tidy.producer-manifest/v1",
                "commandArguments": arguments,
                "runtime": {
                    "version": runtime_version,
                    "platform": platform.system(),
                    "release": platform.release(),
                    "machine": platform.machine(),
                },
                "files": [
                    {"logicalPath": label, "contentDigest": files[label]}
                    for label in sorted(files)
                ],
            }
        )

    def _inject(self, point: str) -> None:
        if self._fault is not None:
            self._fault(point)


def persist_imported_legacy_approval_snapshot(
    *,
    gateway: MigrationWorkerGateway,
    source_item: Mapping[str, Any],
    import_record: Mapping[str, Any],
    frozen_at: str,
) -> LegacyApprovalGatewayResult:
    """Run the executable digest path and persist its exact point-in-time rows."""

    execution = gateway.digest_imported_approval_registry(import_record)
    if len(execution.outputs) != 1:
        raise WorkerGatewayError(
            "INVALID_OUTPUT_ARTIFACT",
            "TOOL_INCOMPATIBLE",
            "Approval interpretation did not yield one artifact",
        )
    artifact = execution.outputs[0].artifact
    records = artifact.get("records")
    if not isinstance(records, list):
        raise WorkerGatewayError(
            "INVALID_OUTPUT_ARTIFACT",
            "TOOL_INCOMPATIBLE",
            "Approval interpretation omitted row digests",
        )
    verifier_digest = domain_digest(
        "tidy.migration-digest-verifier/v1",
        execution.derivation["producerDigests"],
    )
    snapshot = persist_fixture_legacy_approval_snapshot(
        source_item=source_item,
        import_record=import_record,
        source_record_digests=[str(record["sourceRecordDigest"]) for record in records],
        digest_verifier_digest=verifier_digest,
        verifier_configuration_digest=str(
            execution.outputs[0].record["configurationDigest"]
        ),
        verifier_isolation_mode=str(execution.outputs[0].record["isolationMode"]),
        network_isolation_enforced=bool(
            execution.outputs[0].record["networkIsolationEnforced"]
        ),
        frozen_at=frozen_at,
        metadata=gateway.metadata,
        blobs=gateway.blobs,
    )
    return LegacyApprovalGatewayResult(
        execution=execution,
        approval_snapshot=snapshot,
    )


def persist_imported_recipe_digest_verification(
    *,
    gateway: MigrationWorkerGateway,
    import_record: Mapping[str, Any],
    declared_recipe_digest: str,
) -> RecipeVerificationGatewayResult:
    """Persist a source/output/producer-bound historical recipe verification."""

    if not _DIGEST.fullmatch(declared_recipe_digest):
        raise WorkerGatewayError(
            "INPUT_INVALID", "INPUT_INVALID", "Declared recipe digest is invalid"
        )
    execution = gateway.parse_imported_recipe(
        import_record,
        declared_recipe_digest=declared_recipe_digest,
    )
    if len(execution.outputs) != 1:
        raise WorkerGatewayError(
            "INVALID_OUTPUT_ARTIFACT",
            "TOOL_INCOMPATIBLE",
            "Recipe interpretation did not yield one artifact",
        )
    output = execution.outputs[0]
    artifact = output.artifact
    source = artifact.get("source")
    if not isinstance(source, dict):
        raise WorkerGatewayError(
            "SOURCE_BINDING_MISMATCH",
            "INTEGRITY_VIOLATION",
            "Recipe revision omitted source authority",
        )
    verification = create_recipe_digest_verification(
        declared_digest=declared_recipe_digest,
        computed_digest=str(artifact["historicalRecipeDigest"]),
        recipe_content_digest=str(source["sourceContentDigest"]),
        source_snapshot_digest=str(source["sourceSnapshotDigest"]),
        source_item_digest=str(source["sourceItemDigest"]),
        import_record_id=str(source["importRecordId"]),
        migration_worker_output_record_id=str(output.record["recordId"]),
        derivation_id=str(execution.derivation["derivationId"]),
        configuration_digest=str(output.record["configurationDigest"]),
        producer_digests=[
            str(value) for value in execution.derivation["producerDigests"]
        ],
        verifier_isolation_mode=str(output.record["isolationMode"]),
        network_isolation_enforced=(output.record["networkIsolationEnforced"] is True),
    )
    gateway.metadata.add_typed_record(
        record_id=verification["verificationId"],
        record_type=verification["schemaVersion"],
        record=verification,
    )
    return RecipeVerificationGatewayResult(
        execution=execution,
        verification=verification,
    )


def _gateway_input_from_import_record(
    import_record: Mapping[str, Any], name: str
) -> tuple[GatewayInput, MigrationSourceBinding]:
    content_digest = import_record.get("contentDigest")
    byte_length = import_record.get("byteLength")
    if (
        not isinstance(content_digest, str)
        or not _DIGEST.fullmatch(content_digest)
        or not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or byte_length < 0
    ):
        raise WorkerGatewayError(
            "SOURCE_BINDING_MISMATCH",
            "INTEGRITY_VIOLATION",
            "Imported source record has no usable content binding",
        )
    return (
        GatewayInput(
            name=name,
            content_digest=content_digest,
            relative_path="source.json",
            declared_byte_length=byte_length,
        ),
        MigrationSourceBinding.from_import_record(import_record),
    )


def actual_migration_worker_gateway(
    metadata: MigrationRepository,
    blobs: CommittedFilesystemBlobStore,
    project_root: Path,
) -> MigrationWorkerGateway:
    """Construct the only production-authorized migration-worker launcher."""

    node = shutil.which("node")
    worker = project_root / "dist" / "tidy-migration-worker.cjs"
    if node is None or not worker.is_file():
        raise RuntimeError("Build the migration worker with `npm run build` first")
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise RuntimeError(
            "Production migration execution requires macOS /usr/bin/sandbox-exec"
        )
    resolved_node = Path(node).resolve()
    read_roots = [
        (project_root / "dist").resolve(),
        *_node_runtime_read_roots(resolved_node),
    ]
    openssl_configuration = Path("/opt/homebrew/etc/openssl@3")
    if openssl_configuration.is_dir():
        read_roots.append(openssl_configuration)
    return MigrationWorkerGateway(
        metadata,
        blobs,
        GatewayConfig(
            command=(str(resolved_node), str(worker.resolve())),
            cwd=project_root.resolve(),
            sandbox_mode="macos-production",
            sandbox_read_roots=tuple(read_roots),
            max_output_files=4,
            max_output_file_bytes=8 * 1024 * 1024,
            max_output_bytes=8 * 1024 * 1024,
        ),
    )


def _node_runtime_read_roots(node: Path) -> tuple[Path, ...]:
    roots = {node.parent.parent.resolve()}
    completed = subprocess.run(
        ["/usr/bin/otool", "-L", str(node)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    for line in completed.stdout.splitlines()[1:]:
        raw = line.strip().split(" ", 1)[0]
        if raw.startswith("/opt/homebrew/"):
            roots.add(Path(raw).parent)
            roots.add(Path(raw).resolve().parent)
    return tuple(sorted(roots, key=str))


def _parse_migration_response(
    data: bytes,
    *,
    request_id: str,
    max_json_depth: int,
    max_json_nodes: int,
) -> dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise WorkerGatewayError(
            "MALFORMED_STDOUT", "TOOL_INCOMPATIBLE", "Worker stdout is not UTF-8"
        ) from error
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0]:
        raise WorkerGatewayError(
            "MALFORMED_STDOUT",
            "TOOL_INCOMPATIBLE",
            "Migration worker must emit exactly one JSON line",
        )
    value = _strict_json_bytes(
        lines[0].encode(),
        "migration response",
        max_json_depth=max_json_depth,
        max_json_nodes=max_json_nodes,
    )
    if not isinstance(value, dict):
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Response is not an object"
        )
    if value.get("protocolVersion") != _PROTOCOL_VERSION:
        raise WorkerGatewayError(
            "UNKNOWN_PROTOCOL", "TOOL_INCOMPATIBLE", "Unknown migration protocol"
        )
    if value.get("requestId") != request_id:
        raise WorkerGatewayError(
            "REQUEST_ID_MISMATCH", "TOOL_INCOMPATIBLE", "Request ID mismatch"
        )
    if value.get("ok") is True:
        if (
            set(value)
            != {
                "protocolVersion",
                "requestId",
                "ok",
                "outputs",
                "warnings",
            }
            or value.get("warnings") != []
        ):
            raise WorkerGatewayError(
                "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid success envelope"
            )
        outputs = value.get("outputs")
        if not isinstance(outputs, list) or len(outputs) > 4:
            raise WorkerGatewayError(
                "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid output descriptors"
            )
        names: set[str] = set()
        for descriptor in outputs:
            if not isinstance(descriptor, dict) or set(descriptor) != {
                "name",
                "relativePath",
                "contentDigest",
                "byteLength",
            }:
                raise WorkerGatewayError(
                    "INVALID_RESPONSE",
                    "TOOL_INCOMPATIBLE",
                    "Invalid migration output descriptor",
                )
            if (
                not isinstance(descriptor["name"], str)
                or not 1 <= len(descriptor["name"]) <= 64
                or descriptor["name"] in names
                or not isinstance(descriptor["relativePath"], str)
                or not _DIGEST.fullmatch(str(descriptor["contentDigest"]))
                or isinstance(descriptor["byteLength"], bool)
                or not isinstance(descriptor["byteLength"], int)
                or not 0 <= descriptor["byteLength"] <= 8 * 1024 * 1024
            ):
                raise WorkerGatewayError(
                    "INVALID_RESPONSE",
                    "TOOL_INCOMPATIBLE",
                    "Invalid migration output descriptor fields",
                )
            _safe_relative(descriptor["relativePath"], category="TOOL_INCOMPATIBLE")
            names.add(descriptor["name"])
    elif value.get("ok") is False:
        if set(value) != {"protocolVersion", "requestId", "ok", "error"}:
            raise WorkerGatewayError(
                "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid error envelope"
            )
        error = value.get("error")
        if (
            not isinstance(error, dict)
            or set(error) - {"code", "stage", "message", "details"}
            or not {"code", "stage", "message"} <= set(error)
            or not isinstance(error["code"], str)
            or not 1 <= len(error["code"]) <= 64
            or error["stage"]
            not in {"protocol", "input", "parse", "recipe", "limit", "output"}
            or not isinstance(error["message"], str)
            or len(error["message"]) > 1024
        ):
            raise WorkerGatewayError(
                "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid worker error"
            )
    else:
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid ok discriminator"
        )
    return value


def _strict_json_bytes(
    data: bytes,
    label: str,
    *,
    max_json_depth: int,
    max_json_nodes: int,
) -> Any:
    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as error:
        raise WorkerGatewayError(
            "MALFORMED_JSON", "TOOL_INCOMPATIBLE", f"{label} is not strict JSON"
        ) from error
    _assert_json_limits(
        value,
        label=label,
        max_depth=max_json_depth,
        max_nodes=max_json_nodes,
    )
    return value


def _assert_json_limits(
    value: Any, *, label: str, max_depth: int, max_nodes: int
) -> None:
    pending: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > max_nodes:
            raise WorkerGatewayError(
                "JSON_NODE_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                f"{label} exceeds its JSON node limit",
            )
        if depth > max_depth:
            raise WorkerGatewayError(
                "JSON_DEPTH_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                f"{label} exceeds its JSON depth limit",
            )
        if isinstance(current, list):
            pending.extend((entry, depth + 1) for entry in current)
        elif isinstance(current, dict):
            nodes += len(current)
            if nodes > max_nodes:
                raise WorkerGatewayError(
                    "JSON_NODE_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    f"{label} exceeds its JSON node limit",
                )
            pending.extend((entry, depth + 1) for entry in current.values())


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError(f"duplicate key: {key}")
        value[key] = entry
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _artifact_schema(operation: str) -> dict[str, Any] | None:
    filename = {
        "digest-legacy-approval-registry-v1": "approval-row-digests.schema.json",
        "parse-recipe-v01": "recipe-revision.schema.json",
    }.get(operation)
    if filename is None:
        return None
    path = _CONTRACTS / filename
    data = _read_regular_file(path, maximum=1024 * 1024)
    schema = _strict_json_bytes(
        data,
        f"{filename} contract",
        max_json_depth=64,
        max_json_nodes=100_000,
    )
    if not isinstance(schema, dict):
        raise WorkerGatewayError(
            "INVALID_CONTRACT",
            "INTEGRITY_VIOLATION",
            "Migration artifact contract is not an object",
        )
    validator_for(schema).check_schema(schema)
    return schema


def _validate_artifact_schema(operation: str, artifact: Mapping[str, Any]) -> None:
    schema = _artifact_schema(operation)
    if schema is not None:
        try:
            validator_for(schema)(schema).validate(artifact)
        except Exception as error:
            raise WorkerGatewayError(
                "INVALID_OUTPUT_ARTIFACT",
                "TOOL_INCOMPATIBLE",
                "Migration output does not match its strict artifact contract",
            ) from error
        return
    if operation == "health":
        expected = {"status": "ok", "protocolVersion": _PROTOCOL_VERSION}
        if artifact != expected:
            raise WorkerGatewayError(
                "INVALID_OUTPUT_ARTIFACT",
                "TOOL_INCOMPATIBLE",
                "Invalid health artifact",
            )
    elif (
        set(artifact)
        != {
            "protocolVersion",
            "operations",
            "historicalDigest",
            "networkRequired",
            "modelExecutionSupported",
        }
        or artifact.get("protocolVersion") != _PROTOCOL_VERSION
        or artifact.get("operations")
        != [
            "health",
            "capabilities",
            "digest-legacy-approval-registry-v1",
            "parse-recipe-v01",
        ]
        or artifact.get("historicalDigest")
        != {
            "algorithm": _HISTORICAL_DIGEST_ALGORITHM,
            "sourceDigest": _HISTORICAL_DIGEST_SOURCE,
        }
        or artifact.get("networkRequired") is not False
        or artifact.get("modelExecutionSupported") is not False
    ):
        raise WorkerGatewayError(
            "INVALID_OUTPUT_ARTIFACT",
            "TOOL_INCOMPATIBLE",
            "Invalid capabilities artifact",
        )


def _artifact_schema_version(operation: str, artifact: Mapping[str, Any]) -> str:
    value = artifact.get("schemaVersion")
    if isinstance(value, str):
        return value
    return _OPERATION_OUTPUTS[operation][2]


def _gateway_source_digest() -> str:
    files = []
    for path in (
        Path(__file__),
        Path(__file__).with_name("migration_import.py"),
        Path(__file__).with_name("worker.py"),
        Path(__file__).with_name("artifacts.py"),
        Path(__file__).with_name("legacy_approvals.py"),
        Path(__file__).with_name("source_export.py"),
        _IMPORT_CONTRACTS / "migration-worker-output.schema.json",
        _IMPORT_CONTRACTS / "migration-worker-derivation.schema.json",
        _IMPORT_CONTRACTS / "recipe-digest-verification.schema.json",
        _IMPORT_CONTRACTS / "legacy-approval-snapshot.schema.json",
        _CONTRACTS / "approval-row-digests.schema.json",
        _CONTRACTS / "recipe-revision.schema.json",
    ):
        files.append(
            {
                "relativePath": path.relative_to(_PROJECT).as_posix(),
                "contentDigest": sha256_digest(_read_regular_file(path)),
            }
        )
    return domain_digest("tidy.migration-gateway-source-closure/v1", {"files": files})


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents
