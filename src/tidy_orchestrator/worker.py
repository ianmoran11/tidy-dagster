"""Hardened POSIX process gateway for the TypeScript domain worker."""

from __future__ import annotations

import contextlib
import json
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import (
    ContentDescriptor,
    CustodyReceipt,
    DerivationRecord,
    IntegrityViolation,
    LocalArtifactRepository,
    RecordNotFound,
    canonical_json_bytes,
    domain_digest,
    sha256_digest,
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class WorkerGatewayError(RuntimeError):
    def __init__(self, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.category = category


class WorkerDomainFailure(WorkerGatewayError):
    def __init__(self, worker_error: Mapping[str, Any]) -> None:
        super().__init__(
            str(worker_error["code"]),
            "DOMAIN_FAILURE",
            str(worker_error["message"]),
        )
        self.worker_error = dict(worker_error)


@dataclass(frozen=True)
class GatewayInput:
    name: str
    content_digest: str
    relative_path: str
    declared_byte_length: int | None = None


@dataclass(frozen=True)
class GatewayConfig:
    command: tuple[str, ...]
    cwd: Path
    sandbox_mode: str
    sandbox_read_roots: tuple[Path, ...] = ()
    sandbox_read_files: tuple[Path, ...] = ()
    wall_timeout_seconds: float = 30.0
    termination_grace_seconds: float = 1.0
    max_stdout_bytes: int = 1_000_000
    max_stderr_bytes: int = 1_000_000
    max_output_files: int = 1_000
    max_output_file_bytes: int = 50_000_000
    max_output_bytes: int = 50_000_000
    address_space_bytes: int = 4_000_000_000
    cpu_seconds: int = 60
    max_file_descriptors: int = 128

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("Worker command may not be empty")
        if self.sandbox_mode not in {"macos-production", "insecure-test-only"}:
            raise ValueError(
                "sandbox_mode must explicitly be 'macos-production' or "
                "'insecure-test-only'"
            )
        if self.sandbox_mode == "macos-production":
            if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
                raise ValueError(
                    "macos-production requires Darwin and /usr/bin/sandbox-exec"
                )
            if not self.sandbox_read_roots:
                raise ValueError(
                    "macos-production requires explicit sandbox read roots"
                )

    @property
    def network_isolation_enforced(self) -> bool:
        return self.sandbox_mode == "macos-production"


@dataclass(frozen=True)
class GatewayExecution:
    request_id: str
    outputs: tuple[ContentDescriptor, ...]
    output_names: tuple[str, ...]
    output_paths: tuple[str, ...]
    warnings: tuple[Mapping[str, Any], ...]
    derivation: DerivationRecord
    reproduction_key: str
    output_fingerprint: str


_PROTOCOL_MAX_LIMITS: dict[str, int] = {
    "timeoutMs": 300_000,
    "maxInputBytes": 50_000_000,
    "maxOutputBytes": 50_000_000,
    "maxOutputFiles": 10_000,
    "maxWarnings": 10_000,
    "maxWorkbookCompressedBytes": 25_000_000,
    "maxZipEntries": 10_000,
    "maxZipEntryUncompressedBytes": 50_000_000,
    "maxZipTotalUncompressedBytes": 200_000_000,
    "maxSheets": 256,
    "maxCells": 1_000_000,
    "maxMerges": 100_000,
    "maxMergeExpansionCells": 1_000_000,
    "maxSelectorCells": 1_000_000,
    "maxOutputRows": 1_000_000,
}

_DEFAULT_LIMITS: dict[str, int] = {
    "timeoutMs": 30_000,
    "maxInputBytes": 50_000_000,
    "maxOutputBytes": 50_000_000,
    "maxOutputFiles": 1_000,
    "maxWarnings": 1_000,
    "maxWorkbookCompressedBytes": 25_000_000,
    "maxZipEntries": 10_000,
    "maxZipEntryUncompressedBytes": 50_000_000,
    "maxZipTotalUncompressedBytes": 200_000_000,
    "maxSheets": 256,
    "maxCells": 1_000_000,
    "maxMerges": 100_000,
    "maxMergeExpansionCells": 1_000_000,
    "maxSelectorCells": 1_000_000,
    "maxOutputRows": 1_000_000,
}


class WorkerGateway:
    """Launch and verify one worker request before authoritative publication.

    Production mode is currently macOS-only: Seatbelt denies network, process
    forks, and writes outside the private run root. The explicitly named
    insecure test mode provides only POSIX process-group and rlimit controls.
    """

    def __init__(
        self,
        repository: LocalArtifactRepository,
        config: GatewayConfig,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if os.name != "posix":
            raise RuntimeError("WorkerGateway process-tree guarantees are POSIX-only")
        self.repository = repository
        self.config = config
        self._fault = fault_injector

    def execute(
        self,
        *,
        inputs: Sequence[GatewayInput],
        operation: str = "execute-recipe-v01",
        parameters: Mapping[str, Any] | None = None,
        limits: Mapping[str, int] | None = None,
    ) -> GatewayExecution:
        if operation not in {"health", "capabilities", "execute-recipe-v01"}:
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Unknown worker operation"
            )
        minimum_inputs = 1 if operation == "execute-recipe-v01" else 0
        if len(inputs) < minimum_inputs or len(inputs) > 8:
            raise WorkerGatewayError(
                "INPUT_INVALID",
                "INPUT_INVALID",
                "Input count is outside protocol bounds",
            )
        allowed_parameters = {"evidenceProfile", "includeSummary", "csvMode"}
        supplied_parameters = dict(parameters or {})
        if set(supplied_parameters) - allowed_parameters:
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Unknown worker parameter"
            )
        if "evidenceProfile" in supplied_parameters and supplied_parameters[
            "evidenceProfile"
        ] not in {"m1-simple-v1", "m2-deterministic-parity-v1"}:
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Invalid evidence profile"
            )
        if "includeSummary" in supplied_parameters and not isinstance(
            supplied_parameters["includeSummary"], bool
        ):
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Invalid includeSummary"
            )
        if (
            "csvMode" in supplied_parameters
            and supplied_parameters["csvMode"] != "recipe-aware"
        ):
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Invalid csvMode"
            )
        if len({item.name for item in inputs}) != len(inputs):
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Duplicate input names"
            )
        if len({item.relative_path for item in inputs}) != len(inputs):
            raise WorkerGatewayError(
                "INPUT_INVALID", "INPUT_INVALID", "Duplicate input paths"
            )
        if any(not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", item.name) for item in inputs):
            raise WorkerGatewayError(
                "INPUT_INVALID",
                "INPUT_INVALID",
                "Input name is outside protocol bounds",
            )
        effective_limits = dict(_DEFAULT_LIMITS)
        if limits:
            unknown = set(limits) - set(effective_limits)
            if unknown:
                raise WorkerGatewayError(
                    "INPUT_INVALID", "INPUT_INVALID", f"Unknown limits: {unknown}"
                )
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in limits.values()
            ):
                raise WorkerGatewayError(
                    "INPUT_INVALID",
                    "INPUT_INVALID",
                    "Worker limits must be positive integers",
                )
            if any(
                value > _PROTOCOL_MAX_LIMITS[name] for name, value in limits.items()
            ):
                raise WorkerGatewayError(
                    "INPUT_INVALID",
                    "INPUT_INVALID",
                    "Worker limits may not exceed tidy.worker/v1 maxima",
                )
            effective_limits.update(limits)
        effective_limits["timeoutMs"] = min(
            effective_limits["timeoutMs"], int(self.config.wall_timeout_seconds * 1000)
        )
        effective_limits["maxOutputFiles"] = min(
            effective_limits["maxOutputFiles"], self.config.max_output_files
        )
        effective_limits["maxOutputBytes"] = min(
            effective_limits["maxOutputBytes"], self.config.max_output_bytes
        )
        request_id = str(uuid.uuid4())
        run_root = Path(
            tempfile.mkdtemp(prefix="worker-run-", dir=self.repository.staging)
        )
        os.chmod(run_root, 0o700)
        input_root = run_root / "inputs"
        output_root = run_root / "outputs"
        home = run_root / "home"
        temporary = run_root / "tmp"
        for directory in (input_root, output_root, home, temporary):
            directory.mkdir(mode=0o700)
        stdout_path = run_root / "stdout.bin"
        stderr_path = run_root / "stderr.bin"
        try:
            manifest_inputs = []
            ordered_input_digests: list[str] = []
            admitted: list[tuple[GatewayInput, PurePosixPath, ContentDescriptor]] = []
            aggregate_input_bytes = 0
            for item in inputs:
                relative = _safe_relative(item.relative_path)
                if len(item.relative_path) > 512:
                    raise WorkerGatewayError(
                        "INPUT_INVALID", "INPUT_INVALID", "Input path is too long"
                    )
                try:
                    descriptor = self.repository.get_content(item.content_digest)
                except RecordNotFound as error:
                    raise WorkerGatewayError(
                        "INPUT_INVALID",
                        "INPUT_INVALID",
                        f"Unknown input content for {item.name}",
                    ) from error
                if (
                    item.declared_byte_length is not None
                    and item.declared_byte_length != descriptor.byte_length
                ):
                    raise WorkerGatewayError(
                        "INPUT_INVALID",
                        "INPUT_INVALID",
                        f"Declared input length differs for {item.name}",
                    )
                aggregate_input_bytes += descriptor.byte_length
                if aggregate_input_bytes > effective_limits["maxInputBytes"]:
                    raise WorkerGatewayError(
                        "INPUT_SIZE_LIMIT_EXCEEDED",
                        "INPUT_INVALID",
                        "Aggregate inputs exceed maxInputBytes",
                    )
                admitted.append((item, relative, descriptor))
            for item, relative, descriptor in admitted:
                data = self.repository.read_bytes_verified(item.content_digest)
                destination = input_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                _write_private(destination, data, mode=0o400)
                manifest_inputs.append(
                    {
                        "name": item.name,
                        "relativePath": relative.as_posix(),
                        "contentDigest": descriptor.content_digest,
                        "byteLength": descriptor.byte_length,
                    }
                )
                ordered_input_digests.append(descriptor.content_digest)
            request = {
                "protocolVersion": "tidy.worker/v1",
                "requestId": request_id,
                "operation": operation,
                "inputs": manifest_inputs,
                "parameters": supplied_parameters,
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
            environment = self._minimal_environment(home, temporary)
            producer_before = self._producer_manifest_bytes()
            launch_command = self._sandbox_command(command, run_root)
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
            if producer_before != producer_after:
                raise WorkerGatewayError(
                    "PRODUCER_DRIFT",
                    "INTEGRITY_VIOLATION",
                    "Producer identity changed during worker execution",
                )
            stdout_size = stdout_path.stat().st_size
            stderr_size = stderr_path.stat().st_size
            if stdout_size > self.config.max_stdout_bytes:
                raise WorkerGatewayError(
                    "STDOUT_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    "Worker stdout exceeded its byte cap",
                )
            if stderr_size > self.config.max_stderr_bytes:
                raise WorkerGatewayError(
                    "STDERR_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    "Worker stderr exceeded its byte cap",
                )
            if return_code not in (0, 1):
                stderr_preview = stderr_path.read_bytes()[:512].decode(
                    "utf-8", errors="replace"
                )
                raise WorkerGatewayError(
                    "WORKER_NONZERO_EXIT",
                    "INFRA_TRANSIENT",
                    f"Worker exited with code {return_code}: {stderr_preview}",
                )
            stdout_bytes = stdout_path.read_bytes()
            if not stdout_bytes and stderr_size:
                stderr_preview = stderr_path.read_bytes()[:512].decode(
                    "utf-8", errors="replace"
                )
                raise WorkerGatewayError(
                    "MALFORMED_STDOUT",
                    "TOOL_INCOMPATIBLE",
                    f"Worker emitted no response: {stderr_preview}",
                )
            response = _parse_response(
                stdout_bytes,
                request_id,
                max_outputs=effective_limits["maxOutputFiles"],
                max_warnings=effective_limits["maxWarnings"],
            )
            if response["ok"] is False:
                if return_code != 1:
                    raise WorkerGatewayError(
                        "STATUS_EXIT_MISMATCH",
                        "TOOL_INCOMPATIBLE",
                        "Worker error envelope did not use exit code 1",
                    )
                self._assert_output_root_empty(output_root)
                raise WorkerDomainFailure(response["error"])
            if return_code != 0:
                raise WorkerGatewayError(
                    "STATUS_EXIT_MISMATCH",
                    "TOOL_INCOMPATIBLE",
                    "Worker success envelope did not use exit code 0",
                )
            verified = self._verify_outputs(output_root, response["outputs"])
            configuration_digest = domain_digest(
                "tidy.worker-configuration/v1",
                {
                    "operation": operation,
                    "parameters": supplied_parameters,
                    "limits": effective_limits,
                },
            )
            producer_digests = (
                domain_digest("tidy.producer-manifest/v1", json.loads(producer_after)),
            )
            output_names = tuple(item["name"] for item in response["outputs"])
            output_paths = tuple(item["relativePath"] for item in response["outputs"])
            ordered_output_digests = tuple(
                item["contentDigest"] for item in response["outputs"]
            )
            reproduction_key = domain_digest(
                "tidy.reproduction-key/v1",
                {
                    "operation": operation,
                    "contractVersion": "tidy.worker/v1",
                    "orderedInputDigests": ordered_input_digests,
                    "configurationDigest": configuration_digest,
                    "producerDigests": producer_digests,
                },
            )
            output_fingerprint = domain_digest(
                "tidy.output-set/v1",
                list(zip(output_paths, ordered_output_digests, strict=True)),
            )
            observed_at = datetime.now(UTC).isoformat()
            bundle = []
            for descriptor, data in verified:
                content = ContentDescriptor(
                    kind="worker-output",
                    schema_version="tidy.worker-output/v1",
                    media_type=_media_type(descriptor["relativePath"]),
                    byte_length=descriptor["byteLength"],
                    content_digest=descriptor["contentDigest"],
                )
                receipt = CustodyReceipt.create(
                    content_digest=content.content_digest,
                    storage_uri=(
                        f"worker-run://{request_id}/{descriptor['relativePath']}"
                    ),
                    observed_at=observed_at,
                    actor="tidy.worker-gateway/v1",
                    classification="provider-free-derived-evidence",
                )
                bundle.append((content, data, receipt))
            derivation = DerivationRecord.create(
                operation=operation,
                contract_version="tidy.worker/v1",
                ordered_input_digests=ordered_input_digests,
                configuration_digest=configuration_digest,
                producer_digests=producer_digests,
                ordered_output_digests=ordered_output_digests,
            )
            self._inject("before_bundle_publication")
            published = self.repository.publish_worker_bundle(
                outputs=bundle,
                reproduction_key=reproduction_key,
                output_fingerprint=output_fingerprint,
                derivation=derivation,
            )
            return GatewayExecution(
                request_id=request_id,
                outputs=published,
                output_names=output_names,
                output_paths=output_paths,
                warnings=tuple(response["warnings"]),
                derivation=derivation,
                reproduction_key=reproduction_key,
                output_fingerprint=output_fingerprint,
            )
        except IntegrityViolation as error:
            raise WorkerGatewayError(
                "INTEGRITY_VIOLATION", "INTEGRITY_VIOLATION", str(error)
            ) from error
        finally:
            shutil.rmtree(run_root, ignore_errors=True)

    def _wait_bounded(
        self,
        process: subprocess.Popen[bytes],
        output_root: Path,
        stdout_path: Path,
        stderr_path: Path,
    ) -> int:
        deadline = time.monotonic() + self.config.wall_timeout_seconds
        while True:
            return_code = process.poll()
            violation = self._live_resource_violation(
                output_root, stdout_path, stderr_path
            )
            if violation is not None:
                _terminate_process_group(process, self.config.termination_grace_seconds)
                raise violation
            if return_code is not None:
                if _process_group_exists(process.pid):
                    _terminate_process_group(
                        process, self.config.termination_grace_seconds
                    )
                    raise WorkerGatewayError(
                        "DESCENDANT_PROCESS_LEAK",
                        "TOOL_INCOMPATIBLE",
                        "Worker exited while same-process-group descendants remained",
                    )
                return return_code
            if time.monotonic() >= deadline:
                _terminate_process_group(process, self.config.termination_grace_seconds)
                raise WorkerGatewayError(
                    "WORKER_TIMEOUT",
                    "INFRA_TRANSIENT",
                    "Worker exceeded its wall-clock limit; process group terminated",
                )
            time.sleep(0.02)

    def _live_resource_violation(
        self, output_root: Path, stdout_path: Path, stderr_path: Path
    ) -> WorkerGatewayError | None:
        if stdout_path.stat().st_size > self.config.max_stdout_bytes:
            return WorkerGatewayError(
                "STDOUT_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Worker stdout exceeded its byte cap",
            )
        if stderr_path.stat().st_size > self.config.max_stderr_bytes:
            return WorkerGatewayError(
                "STDERR_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Worker stderr exceeded its byte cap",
            )
        try:
            entries = _scan_output_entries(
                output_root, max_entries=self.config.max_output_files
            )
        except WorkerGatewayError as error:
            return error
        total = 0
        for _path, (kind, size) in entries.items():
            if kind != "file":
                continue
            total += size
            if size > self.config.max_output_file_bytes:
                return WorkerGatewayError(
                    "OUTPUT_FILE_SIZE_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    "Worker output exceeded the per-file cap",
                )
            if total > self.config.max_output_bytes:
                return WorkerGatewayError(
                    "OUTPUT_SIZE_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    "Worker outputs exceeded the aggregate cap",
                )
        return None

    def _minimal_environment(self, home: Path, temporary: Path) -> dict[str, str]:
        command_directory = str(Path(self.config.command[0]).resolve().parent)
        return {
            "PATH": f"{command_directory}:/usr/bin:/bin",
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "TZ": "UTC",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NODE_OPTIONS": "--max-old-space-size=768 --disable-proto=throw",
        }

    def _apply_limits(self) -> None:
        limits = [
            (resource.RLIMIT_AS, self.config.address_space_bytes),
            (resource.RLIMIT_CPU, self.config.cpu_seconds),
            (resource.RLIMIT_NOFILE, self.config.max_file_descriptors),
            (
                resource.RLIMIT_FSIZE,
                max(
                    self.config.max_stdout_bytes,
                    self.config.max_stderr_bytes,
                    self.config.max_output_file_bytes,
                ),
            ),
        ]
        for limit, value in limits:
            try:
                soft, hard = resource.getrlimit(limit)
                effective = (
                    value if hard == resource.RLIM_INFINITY else min(value, hard)
                )
                resource.setrlimit(limit, (effective, effective))
            except (OSError, ValueError):
                continue

    def _verify_outputs(
        self, root: Path, descriptors: Sequence[Mapping[str, Any]]
    ) -> list[tuple[Mapping[str, Any], bytes]]:
        if len(descriptors) > self.config.max_output_files:
            raise WorkerGatewayError(
                "OUTPUT_FILE_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Worker declared too many outputs",
            )
        declared_paths: set[str] = set()
        verified: list[tuple[Mapping[str, Any], bytes]] = []
        total = 0
        for descriptor in descriptors:
            relative = _safe_relative(
                str(descriptor["relativePath"]), category="TOOL_INCOMPATIBLE"
            )
            portable = relative.as_posix()
            if portable in declared_paths:
                raise WorkerGatewayError(
                    "DUPLICATE_OUTPUT", "TOOL_INCOMPATIBLE", portable
                )
            declared_paths.add(portable)
            target = root / relative
            _assert_regular_without_symlinks(root, relative)
            data = _read_regular_file(target, maximum=self.config.max_output_file_bytes)
            if len(data) > self.config.max_output_file_bytes:
                raise WorkerGatewayError(
                    "OUTPUT_FILE_SIZE_LIMIT_EXCEEDED",
                    "TOOL_INCOMPATIBLE",
                    portable,
                )
            total += len(data)
            if total > self.config.max_output_bytes:
                raise WorkerGatewayError(
                    "OUTPUT_SIZE_LIMIT_EXCEEDED", "TOOL_INCOMPATIBLE", portable
                )
            if len(data) != descriptor["byteLength"]:
                raise WorkerGatewayError(
                    "OUTPUT_LENGTH_MISMATCH", "INTEGRITY_VIOLATION", portable
                )
            if sha256_digest(data) != descriptor["contentDigest"]:
                raise WorkerGatewayError(
                    "OUTPUT_DIGEST_MISMATCH", "INTEGRITY_VIOLATION", portable
                )
            verified.append((descriptor, data))
        actual = _list_output_files(root, max_entries=self.config.max_output_files)
        if actual != declared_paths:
            raise WorkerGatewayError(
                "UNDECLARED_OUTPUT",
                "TOOL_INCOMPATIBLE",
                f"Declared {sorted(declared_paths)!r}; actual {sorted(actual)!r}",
            )
        return verified

    @staticmethod
    def _assert_output_root_empty(root: Path) -> None:
        if _list_output_files(root, max_entries=1_000):
            raise WorkerGatewayError(
                "UNDECLARED_OUTPUT",
                "TOOL_INCOMPATIBLE",
                "Failed worker published output files",
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
            if candidate.is_file():
                resolved = candidate.resolve()
                try:
                    logical = resolved.relative_to(cwd).as_posix()
                except ValueError:
                    logical = f"external-file-{index}:{resolved.name}"
                label = f"command-file-{index}:{logical}"
                add_file(label, resolved)
                arguments.append({"kind": "file", "label": label})
            elif candidate.is_absolute():
                arguments.append({"kind": "external-path", "index": str(index)})
            else:
                arguments.append({"kind": "literal", "value": raw})

        dist = cwd / "dist" / "apps" / "domain-worker" / "src"
        if dist.is_dir():
            for path in sorted(dist.rglob("*.js"), key=lambda item: item.as_posix()):
                add_file(f"dist/{path.relative_to(dist).as_posix()}", path)
        metadata = (
            cwd / "package-lock.json",
            cwd / "package.json",
            cwd / ".node-version",
        )
        for path in metadata:
            if path.is_file():
                add_file(path.relative_to(cwd).as_posix(), path)
        contract = cwd / "contracts" / "worker" / "v1"
        if contract.is_dir():
            for path in sorted(
                (item for item in contract.rglob("*") if item.is_file()),
                key=lambda item: item.as_posix(),
            ):
                add_file(
                    f"contracts/worker/v1/{path.relative_to(contract).as_posix()}",
                    path,
                )
        return canonical_json_bytes(
            {
                "schemaVersion": "tidy.producer-manifest/v1",
                "commandArguments": arguments,
                "files": [
                    {"logicalPath": label, "contentDigest": files[label]}
                    for label in sorted(files)
                ],
            }
        )

    def _sandbox_command(self, command: list[str], run_root: Path) -> list[str]:
        if self.config.sandbox_mode == "insecure-test-only":
            return command
        profile = run_root / "sandbox.sb"
        read_roots = {
            Path("/System"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/Library"),
            Path("/private/etc"),
            Path("/private/var/db"),
            Path("/dev"),
            run_root.resolve(),
            *(Path(os.path.abspath(path)) for path in self.config.sandbox_read_roots),
        }
        existing_roots = {path for path in read_roots if path.exists()}
        clauses = "\n".join(
            f'  (subpath "{_sandbox_quote(str(path))}")'
            for path in sorted(existing_roots, key=str)
        )
        read_files = {
            path.resolve() for path in self.config.sandbox_read_files if path.is_file()
        }
        ancestors = {
            parent
            for root in (*existing_roots, *read_files, self.config.cwd.resolve())
            for parent in root.parents
            if parent != Path("/")
        } | {self.config.cwd.resolve()}
        metadata_clauses = "\n".join(
            f'  (literal "{_sandbox_quote(str(path))}")'
            for path in sorted(ancestors, key=str)
        )
        file_clauses = "\n".join(
            f'  (literal "{_sandbox_quote(str(path))}")'
            for path in sorted(read_files, key=str)
        )
        profile_text = f"""(version 1)
(deny default)
(import \"system.sb\")
(allow process-exec)
(deny process-fork)
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow mach-lookup)
(allow file-read-metadata
{metadata_clauses})
(allow file-read*
{clauses}
{file_clauses})
(allow file-write* (subpath \"{_sandbox_quote(str(run_root.resolve()))}\"))
(deny network*)
"""
        _write_private(profile, profile_text.encode(), mode=0o400)
        return ["/usr/bin/sandbox-exec", "-f", str(profile), *command]

    def _inject(self, point: str) -> None:
        if self._fault is not None:
            self._fault(point)


def _parse_response(
    data: bytes,
    request_id: str,
    *,
    max_outputs: int,
    max_warnings: int,
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
            "Worker must emit exactly one JSON line",
        )
    try:
        value = json.loads(
            lines[0],
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise WorkerGatewayError(
            "MALFORMED_STDOUT", "TOOL_INCOMPATIBLE", "Worker stdout is not JSON"
        ) from error
    if not isinstance(value, dict):
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Response is not an object"
        )
    common = {"protocolVersion", "requestId", "ok"}
    if value.get("protocolVersion") != "tidy.worker/v1":
        raise WorkerGatewayError(
            "UNKNOWN_PROTOCOL", "TOOL_INCOMPATIBLE", "Unknown worker protocol"
        )
    if value.get("requestId") != request_id:
        raise WorkerGatewayError(
            "REQUEST_ID_MISMATCH", "TOOL_INCOMPATIBLE", "Request ID mismatch"
        )
    if value.get("ok") is True:
        if set(value) != common | {"outputs", "warnings"}:
            raise WorkerGatewayError(
                "UNKNOWN_RESPONSE_FIELD", "TOOL_INCOMPATIBLE", "Unknown success field"
            )
        if not isinstance(value["outputs"], list) or not isinstance(
            value["warnings"], list
        ):
            raise WorkerGatewayError(
                "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid success arrays"
            )
        if len(value["outputs"]) > min(max_outputs, 10_000):
            raise WorkerGatewayError(
                "OUTPUT_FILE_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Worker declared too many outputs",
            )
        if len(value["warnings"]) > min(max_warnings, 10_000):
            raise WorkerGatewayError(
                "WARNING_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Worker emitted too many warnings",
            )
        output_names: set[str] = set()
        for descriptor in value["outputs"]:
            _validate_output_descriptor(descriptor)
            if descriptor["name"] in output_names:
                raise WorkerGatewayError(
                    "DUPLICATE_OUTPUT", "TOOL_INCOMPATIBLE", descriptor["name"]
                )
            output_names.add(descriptor["name"])
        for warning in value["warnings"]:
            if (
                not isinstance(warning, dict)
                or not set(warning) <= {"code", "message", "path"}
                or not {"code", "message"} <= set(warning)
                or not _bounded_string(warning["code"], minimum=1, maximum=64)
                or not _bounded_string(warning["message"], minimum=0, maximum=1024)
                or (
                    "path" in warning
                    and not _bounded_string(warning["path"], minimum=0, maximum=512)
                )
            ):
                raise WorkerGatewayError(
                    "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid warning"
                )
    elif value.get("ok") is False:
        if set(value) != common | {"error"}:
            raise WorkerGatewayError(
                "UNKNOWN_RESPONSE_FIELD", "TOOL_INCOMPATIBLE", "Unknown error field"
            )
        error = value.get("error")
        if (
            not isinstance(error, dict)
            or set(error) - {"code", "stage", "message", "details"}
            or not {"code", "stage", "message"} <= set(error)
            or not _bounded_string(error["code"], minimum=1, maximum=64)
            or error["stage"]
            not in {
                "protocol",
                "input",
                "parse",
                "recipe",
                "execute",
                "export",
                "limit",
            }
            or not _bounded_string(error["message"], minimum=0, maximum=1024)
        ):
            raise WorkerGatewayError(
                "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid worker error"
            )
    else:
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid ok discriminator"
        )
    return value


def _validate_output_descriptor(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "name",
        "relativePath",
        "contentDigest",
        "byteLength",
    }:
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid output descriptor"
        )
    if not _bounded_string(value["name"], minimum=1, maximum=512) or not (
        _bounded_string(value["relativePath"], minimum=1, maximum=512)
    ):
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid output path"
        )
    if not isinstance(value["contentDigest"], str) or not _DIGEST.fullmatch(
        value["contentDigest"]
    ):
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid output digest"
        )
    if (
        isinstance(value["byteLength"], bool)
        or not isinstance(value["byteLength"], int)
        or not 0 <= value["byteLength"] <= 50_000_000
    ):
        raise WorkerGatewayError(
            "INVALID_RESPONSE", "TOOL_INCOMPATIBLE", "Invalid output length"
        )


def _safe_relative(raw: str, *, category: str = "INPUT_INVALID") -> PurePosixPath:
    if not raw or "\\" in raw or "\x00" in raw:
        raise WorkerGatewayError("UNSAFE_PATH", category, raw)
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise WorkerGatewayError("UNSAFE_PATH", category, raw)
    if path.as_posix() != raw:
        raise WorkerGatewayError("UNSAFE_PATH", category, raw)
    return path


def _assert_regular_without_symlinks(root: Path, relative: PurePosixPath) -> None:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError as error:
            raise WorkerGatewayError(
                "OUTPUT_MISSING", "TOOL_INCOMPATIBLE", relative.as_posix()
            ) from error
        if stat.S_ISLNK(info.st_mode):
            raise WorkerGatewayError(
                "OUTPUT_SYMLINK", "TOOL_INCOMPATIBLE", relative.as_posix()
            )
    final = current.lstat()
    if not stat.S_ISREG(final.st_mode):
        raise WorkerGatewayError(
            "OUTPUT_NOT_REGULAR", "TOOL_INCOMPATIBLE", relative.as_posix()
        )


def _scan_output_entries(
    root: Path, *, max_entries: int, max_depth: int = 32
) -> dict[str, tuple[str, int]]:
    entries: dict[str, tuple[str, int]] = {}
    pending: list[tuple[Path, int]] = [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        if depth > max_depth:
            raise WorkerGatewayError(
                "OUTPUT_FILE_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Worker output directory nesting is too deep",
            )
        try:
            iterator = os.scandir(directory)
        except FileNotFoundError:
            # The worker publishes with a same-parent directory rename. A live
            # scan may observe the short interval where the old root is absent.
            continue
        except OSError as error:
            raise WorkerGatewayError(
                "OUTPUT_SCAN_FAILED", "TOOL_INCOMPATIBLE", str(error)
            ) from error
        with iterator:
            for entry in iterator:
                relative = Path(entry.path).relative_to(root).as_posix()
                if len(relative) > 512:
                    raise WorkerGatewayError(
                        "UNSAFE_PATH", "TOOL_INCOMPATIBLE", "Output path is too long"
                    )
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if entry.is_symlink():
                    kind = "symlink"
                elif stat.S_ISDIR(info.st_mode):
                    kind = "directory"
                    pending.append((Path(entry.path), depth + 1))
                elif stat.S_ISREG(info.st_mode):
                    kind = "file"
                else:
                    kind = "other"
                entries[relative] = (kind, info.st_size)
                if len(entries) > max_entries:
                    raise WorkerGatewayError(
                        "OUTPUT_FILE_LIMIT_EXCEEDED",
                        "TOOL_INCOMPATIBLE",
                        "Worker created too many output entries",
                    )
    return entries


def _list_output_files(root: Path, *, max_entries: int) -> set[str]:
    entries = _scan_output_entries(root, max_entries=max_entries)
    return {
        path
        for path, (kind, _size) in entries.items()
        if kind in {"file", "symlink", "other"}
    }


def _read_regular_file(path: Path, maximum: int | None = None) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("not a regular file")
        if maximum is not None and info.st_size > maximum:
            raise WorkerGatewayError(
                "OUTPUT_FILE_SIZE_LIMIT_EXCEEDED",
                "TOOL_INCOMPATIBLE",
                "Output exceeded the per-file cap",
            )
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (info.st_dev, info.st_ino, info.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise OSError("file changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _bounded_string(value: Any, *, minimum: int, maximum: int) -> bool:
    return isinstance(value, str) and minimum <= len(value) <= maximum


def _sandbox_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_private(path: Path, data: bytes, *, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, mode)


def _terminate_process_group(process: subprocess.Popen[bytes], grace: float) -> None:
    process_group = process.pid
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process_group, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        process.poll()
        if not _process_group_exists(process_group):
            break
        time.sleep(0.02)
    if _process_group_exists(process_group):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process_group, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=max(grace, 1.0))


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS can report EPERM while only terminated/zombie members remain.
        # Treat the group as present so the caller still attempts SIGKILL.
        return True
    return True


def _media_type(relative_path: str) -> str:
    if relative_path.endswith(".json"):
        return "application/json"
    if relative_path.endswith(".csv"):
        return "text/csv"
    return "application/octet-stream"
