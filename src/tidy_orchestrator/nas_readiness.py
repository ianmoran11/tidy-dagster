"""Sanitized, read-only inspection of NAS controls required by ADR 0005."""

from __future__ import annotations

import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest

_SCHEMA_VERSION = "tidy.nas-readiness-inspection/v1"
_INSPECTION_ID = "phase-b-canary-nas-readiness-v1"
_PRODUCER_VERSION = "tidy-nas-readiness-inspector/v1"
_MAX_OUTPUT = 2 * 1024 * 1024
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class NasReadinessError(RuntimeError):
    """The read-only NAS observation could not be represented safely."""


@dataclass(frozen=True)
class CommandResult:
    status: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], CommandResult]


def inspect_nas_readiness(
    *,
    mount_path: Path,
    metadata_root: Path,
    inspected_at: str,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Inspect only client-visible state; never write to or configure the NAS."""

    inspected_at = _canonical_timestamp(inspected_at)
    runner = command_runner or _run_command
    mount_path = mount_path.resolve()
    metadata_root = metadata_root.resolve()
    mount_result = runner(("/sbin/mount",))
    mount_line = _find_mount_line(mount_result.stdout, mount_path)
    mount_present = mount_result.status == 0 and mount_line is not None
    filesystem = "smbfs" if mount_line and "(smbfs," in mount_line else "unknown"
    read_only = bool(
        mount_line
        and any(
            token in mount_line.rsplit("(", 1)[-1].lower().split(", ")
            for token in ("read-only", "readonly", "ro")
        )
    )
    total_bytes = 0
    free_bytes = 0
    utilization = 0
    mount_device: int | None = None
    if mount_present:
        info = mount_path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise NasReadinessError("NAS mount target is not a safe directory")
        capacity = os.statvfs(mount_path)
        total_bytes = capacity.f_blocks * capacity.f_frsize
        free_bytes = capacity.f_bavail * capacity.f_frsize
        if total_bytes > 0:
            utilization = ((total_bytes - free_bytes) * 10_000) // total_bytes
        mount_device = info.st_dev

    share_result = runner(
        ("/usr/bin/smbutil", "statshares", "-m", str(mount_path), "-f", "JSON")
    )
    share = _parse_share(share_result)
    current_version = _optional_text(share.get("SMB_VERSION"), 64)
    signing_algorithm = _optional_text(share.get("SMB_CURR_SIGN_ALGORITHM"), 64)
    encryption_algorithm = _optional_text(share.get("SMB_CURR_ENCRYPT_ALGORITHM"), 64)
    server_signing_required = share.get("SIGNING_REQUIRED") is True
    client_signing_required = share.get("CLIENT_REQUIRES_SIGNING") is True
    signing_active = signing_algorithm is not None
    signing_gate = signing_active and (
        server_signing_required or client_signing_required
    )
    negotiate = share.get("SMB_NEGOTIATE")
    legacy_smb1 = isinstance(negotiate, list) and ("SMBV_NEG_SMB1_ENABLED" in negotiate)
    smb3_current = isinstance(current_version, str) and current_version.startswith(
        "SMB_3"
    )

    network_label = _mount_network_label(mount_line)
    local_label = pwd.getpwuid(os.getuid()).pw_name
    identity_matches_local = network_label is not None and network_label == local_label

    snapshot_result = runner(
        ("/usr/bin/smbutil", "snapshot", "-m", str(mount_path), "-f", "JSON")
    )
    snapshot_status, snapshot_failure, snapshot_count = _snapshot_observation(
        snapshot_result
    )
    snapshots_verified = snapshot_status == "succeeded" and bool(snapshot_count)

    metadata_present = metadata_root.is_dir() and not metadata_root.is_symlink()
    metadata_on_nas = False
    if metadata_present and mount_device is not None:
        metadata_on_nas = metadata_root.lstat().st_dev == mount_device or _is_within(
            metadata_root, mount_path
        )
    sqlite_on_nas = metadata_on_nas
    sqlite_gate = metadata_present and not sqlite_on_nas

    project = Path(__file__).parents[2]
    importer = project / "src/tidy_orchestrator/migration_import.py"
    importer_tests = project / "tests/test_migration_import.py"
    implementation_present = importer.is_file()
    test_text = importer_tests.read_text() if importer_tests.is_file() else ""
    integrity_coverage = "tamper" in test_text and "BlobIntegrityError" in test_text
    restart_coverage = "idempot" in test_text and "partial" in test_text
    recovery_coverage = "orphan" in test_text and "recovered" in test_text
    # The prior disposable real-SMB probe is recorded in the committed Phase B
    # evidence. This observation does not upgrade it into the formal gate.
    real_probe_documented = True

    blockers: list[str] = []
    if not mount_present:
        blockers.append("mount-unavailable")
    if not smb3_current:
        blockers.append("smb3-not-current")
    if not signing_gate:
        blockers.append("smb-signing-not-required")
    blockers.append("dedicated-service-identity-unverified")
    if not snapshots_verified:
        blockers.append("nas-snapshots-unverified")
    blockers.append("restore-drill-unverified")
    if sqlite_on_nas:
        blockers.append("sqlite-on-nas")
    blockers.append("commit-marker-adapter-gate-incomplete")
    blockers = sorted(set(blockers))

    producer_before = _producer_source_digest()
    producer_after = _producer_source_digest()
    if producer_before != producer_after:
        raise NasReadinessError("NAS readiness producer changed during inspection")
    semantic = {
        "schemaVersion": _SCHEMA_VERSION,
        "inspectionId": _INSPECTION_ID,
        "inspectedAt": inspected_at,
        "inspectionMode": "read-only-no-configuration",
        "reviewKind": "implementing-agent-self-review",
        "independentReview": False,
        "targets": {
            "blobRootId": "phase-b-nas-blob-root-v1",
            "metadataRootId": "tidy-dagster-local-metadata-root-v1",
        },
        "observations": {
            "mount": {
                "present": mount_present,
                "filesystem": filesystem,
                "readOnly": read_only,
                "totalBytes": total_bytes,
                "freeBytes": free_bytes,
                "utilizationBasisPoints": utilization,
            },
            "smb": {
                "inspectionSucceeded": bool(share),
                "currentVersion": current_version,
                "smb3Current": smb3_current,
                "signingSupported": share.get("SIGNING_SUPPORTED") is True,
                "signingActiveObserved": signing_active,
                "currentSigningAlgorithm": signing_algorithm,
                "serverSigningRequired": server_signing_required,
                "clientSigningRequired": client_signing_required,
                "signingRequiredGatePass": signing_gate,
                "encryptionRequired": share.get("ENCRYPTION_REQUIRED") is True,
                "currentEncryptionAlgorithm": encryption_algorithm,
                "legacySmb1NegotiationAdvertised": legacy_smb1,
            },
            "identity": {
                "networkLabelObserved": network_label is not None,
                "networkLabelMatchesLocalInteractiveUser": identity_matches_local,
                "dedicatedServiceIdentityAttested": False,
                "nonAdminAttested": False,
                "subtreeRestrictionAttested": False,
                "gatePass": False,
            },
            "snapshots": {
                "enumerationStatus": snapshot_status,
                "sanitizedFailure": snapshot_failure,
                "snapshotCount": snapshot_count,
                "availabilityVerified": snapshots_verified,
            },
            "restore": {
                "evidenceStatus": "not-provided",
                "procedureVerified": False,
                "drillPassed": False,
            },
            "sqlite": {
                "metadataRootPresent": metadata_present,
                "metadataRootOnNasDevice": metadata_on_nas,
                "sqliteOnNas": sqlite_on_nas,
                "gatePass": sqlite_gate,
            },
            "commitMarkerAdapter": {
                "implementationPresent": implementation_present,
                "integrityTestCoveragePresent": integrity_coverage,
                "restartTestCoveragePresent": restart_coverage,
                "recoveryTestCoveragePresent": recovery_coverage,
                "successfulRealProbeDocumented": real_probe_documented,
                "formalCanaryGateEvidenceComplete": False,
                "gatePass": False,
            },
        },
        "gates": {
            "smb3Current": smb3_current,
            "smbSigningRequired": signing_gate,
            "dedicatedNonAdminServiceIdentity": False,
            "nasSnapshotsAvailable": snapshots_verified,
            "restoreDrillPassed": False,
            "sqliteLocal": sqlite_gate,
            "commitMarkerAdapterVerified": False,
            "canaryImportReady": False,
        },
        "blockers": blockers,
        "configurationChanged": False,
        "rawCommandOutputStored": False,
        "limitations": [
            (
                "Client-visible state cannot prove NAS group membership or "
                "non-admin status."
            ),
            "Snapshot enumeration failure does not prove snapshots are absent.",
            "No restore procedure or completed restore drill evidence was provided.",
            (
                "Static test coverage and a prior probe are not a formal current "
                "adapter gate."
            ),
            "No NAS setting, identity, permission, snapshot, or file was changed.",
        ],
        "producer": {
            "version": _PRODUCER_VERSION,
            "sourceDigest": producer_after,
            "canonicalizationAlgorithm": "tidy-python-sorted-json-v1",
        },
    }
    return {**semantic, "reportDigest": domain_digest(_SCHEMA_VERSION, semantic)}


def canonical_report_digest(report: Mapping[str, Any]) -> str:
    semantic = dict(report)
    digest = semantic.pop("reportDigest", None)
    if digest != domain_digest(_SCHEMA_VERSION, semantic):
        raise NasReadinessError("NAS readiness report identity differs")
    if semantic.get("configurationChanged") is not False:
        raise NasReadinessError("NAS readiness report claims a configuration change")
    gates = semantic.get("gates")
    if not isinstance(gates, dict) or gates.get("canaryImportReady") is not False:
        raise NasReadinessError("NAS readiness report grants canary import authority")
    return str(digest)


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    canonical_report_digest(report)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise NasReadinessError("NAS readiness output already exists")
    payload = canonical_json_bytes(dict(report)) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as error:
            raise NasReadinessError("NAS readiness output already exists") from error
        temporary.unlink()
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _run_command(arguments: Sequence[str]) -> CommandResult:
    try:
        result = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=60,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "C",
                "LC_ALL": "C",
                "TZ": "UTC",
            },
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise NasReadinessError("Read-only NAS inspection command failed") from error
    if (
        len(result.stdout.encode()) > _MAX_OUTPUT
        or len(result.stderr.encode()) > _MAX_OUTPUT
    ):
        raise NasReadinessError("Read-only NAS inspection output exceeded its bound")
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _find_mount_line(output: str, mount_path: Path) -> str | None:
    marker = f" on {mount_path} ("
    matches = [line for line in output.splitlines() if marker in line]
    if len(matches) > 1:
        raise NasReadinessError("NAS mount observation is ambiguous")
    return matches[0] if matches else None


def _mount_network_label(mount_line: str | None) -> str | None:
    if not mount_line or not mount_line.startswith("//"):
        return None
    authority = mount_line[2:].split("/", 1)[0]
    if "@" not in authority:
        return None
    label = authority.rsplit("@", 1)[0]
    if ";" in label:
        label = label.rsplit(";", 1)[-1]
    return label or None


def _parse_share(result: CommandResult) -> dict[str, Any]:
    if result.status != 0:
        return {}
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, RecursionError):
        return {}
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return {}
    return value[0]


def _snapshot_observation(result: CommandResult) -> tuple[str, str, int | None]:
    if result.status != 0:
        failure = (
            "resource-busy"
            if "Resource busy" in result.stderr or "Resource busy" in result.stdout
            else "command-failed"
        )
        return "failed", failure, None
    try:
        value = json.loads(result.stdout)
    except (json.JSONDecodeError, RecursionError):
        return "failed", "invalid-json", None
    return "succeeded", "none", _count_snapshot_values(value)


def _count_snapshot_values(value: Any) -> int:
    if isinstance(value, list):
        return sum(_count_snapshot_values(entry) for entry in value)
    if isinstance(value, dict):
        return sum(_count_snapshot_values(entry) for entry in value.values())
    if isinstance(value, str) and value:
        return 1
    return 0


def _optional_text(value: Any, maximum: int) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= maximum else None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _producer_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = (
        Path(__file__),
        Path(__file__).with_name("nas_readiness_cli.py"),
        Path(__file__).with_name("artifacts.py"),
        project / "contracts/nas-readiness/v1/report.schema.json",
        project / "src/tidy_orchestrator/migration_import.py",
        project / "tests/test_migration_import.py",
    )

    def capture() -> list[dict[str, Any]]:
        return [
            {
                "relativePath": path.relative_to(project).as_posix(),
                "byteLength": path.stat().st_size,
                "contentDigest": sha256_digest(path.read_bytes()),
            }
            for path in paths
        ]

    before = capture()
    after = capture()
    if before != after:
        raise NasReadinessError("NAS readiness source closure changed while hashing")
    return domain_digest(
        "tidy.nas-readiness-inspector-source-closure/v1",
        {
            "version": _PRODUCER_VERSION,
            "files": before,
            "pythonImplementation": sys.implementation.name,
            "pythonVersion": list(sys.version_info[:3]),
        },
    )


def _canonical_timestamp(value: str) -> str:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise NasReadinessError("Inspection time must be canonical UTC seconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise NasReadinessError("Inspection time is invalid") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise NasReadinessError("Inspection time is not canonical")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
