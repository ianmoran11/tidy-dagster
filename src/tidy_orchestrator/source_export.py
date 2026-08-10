"""Read-only, deterministic source-estate inventory and freeze contracts."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest

_POLICY_VERSION = "tidy.source-export-policy/v1"
_INVENTORY_VERSION = "tidy.source-export-inventory/v1"
_REPORT_VERSION = "tidy.source-export-report/v1"
_SNAPSHOT_VERSION = "tidy.source-export-snapshot/v1"
_NAS_COMMIT_VERSION = "tidy.nas-snapshot-commit/v1"
_EXPORTER_VERSION = "tidy.source-exporter/v1"
_CANONICALIZATION = "tidy-python-sorted-json-v1"
_GIB = 1024**3
_READ_CHUNK = 1024 * 1024
_GIT_TIMEOUT_SECONDS = 120
_MAX_GIT_OUTPUT_BYTES = 100 * 1024 * 1024
_MAX_EXPORT_WIRE_BYTES = 1024 * 1024 * 1024
_ALLOWED_DISPOSITIONS = frozenset(("import", "exclude", "quarantine"))
_ALLOWED_ENTRY_TYPES = frozenset(("file", "directory", "symlink"))
_PROTECTED_JSON_CLASSES = frozenset(
    (
        "approval-registry",
        "catalog-evidence",
        "generation-json-evidence",
        "harvest-evidence",
        "recipe-evidence",
        "workbook-estate-evidence",
    )
)
_RECIPE_KEYS = frozenset(
    (
        "candidateRecipe",
        "candidate_recipe",
        "normalizedRecipe",
        "normalized_recipe",
        "originalRecipe",
        "original_recipe",
        "recipe",
        "recipeV01",
    )
)
_PROMPT_KEYS = frozenset(
    (
        "messages",
        "prompt",
        "renderedMessages",
        "rendered_messages",
        "systemPrompt",
        "system_prompt",
    )
)
_RESPONSE_KEYS = frozenset(
    (
        "providerResponse",
        "provider_response",
        "rawResponse",
        "raw_response",
        "response",
    )
)


class SourceExportError(RuntimeError):
    """Base error for inventory and freeze failures."""


class PolicyError(SourceExportError):
    """The source-export policy was not strict or internally consistent."""


class SourceSafetyError(SourceExportError):
    """The source tree contained an unsafe object or path transition."""


class SourceMutationError(SourceExportError):
    """Source bytes or directory membership changed during inventory."""


class SourceLimitError(SourceExportError):
    """A configured source-estate bound was exceeded."""


class HeadroomError(SourceExportError):
    """The selected destination cannot safely hold a frozen export."""


class _DuplicateJsonKey(ValueError):
    pass


@dataclass(frozen=True)
class PolicyLimits:
    max_entries: int
    max_file_bytes: int
    max_json_scan_bytes: int
    max_json_depth: int
    max_embedded_records_per_file: int


@dataclass(frozen=True)
class SourceExportRule:
    rule_id: str
    priority: int
    entry_types: frozenset[str]
    disposition: str
    artifact_class: str
    path_prefixes: tuple[str, ...] = ()
    exact_paths: frozenset[str] = frozenset()
    suffixes: tuple[str, ...] = ()
    basename_globs: tuple[str, ...] = ()
    directory_names: frozenset[str] = frozenset()

    def matches(self, relative_path: str, entry_type: str) -> bool:
        if entry_type not in self.entry_types:
            return False
        path = PurePosixPath(relative_path)
        if self.path_prefixes and not any(
            relative_path == prefix or relative_path.startswith(f"{prefix}/")
            for prefix in self.path_prefixes
        ):
            return False
        if self.exact_paths and relative_path not in self.exact_paths:
            return False
        if self.suffixes and not relative_path.lower().endswith(self.suffixes):
            return False
        if self.basename_globs and not any(
            fnmatch.fnmatchcase(path.name, pattern) for pattern in self.basename_globs
        ):
            return False
        return not self.directory_names or path.name in self.directory_names


@dataclass(frozen=True)
class SourceExportPolicy:
    schema_version: str
    policy_id: str
    source_system: str
    limits: PolicyLimits
    rules: tuple[SourceExportRule, ...]
    fallback_rule_id: str
    fallback_disposition: str
    fallback_artifact_class: str
    content_digest: str

    def classify(
        self,
        relative_path: str,
        entry_type: Literal["file", "directory", "symlink"],
    ) -> tuple[str, str, str] | None:
        matches = [
            rule for rule in self.rules if rule.matches(relative_path, entry_type)
        ]
        if not matches:
            if entry_type in ("directory", "symlink"):
                return None
            return (
                self.fallback_rule_id,
                self.fallback_disposition,
                self.fallback_artifact_class,
            )
        maximum = max(rule.priority for rule in matches)
        winners = [rule for rule in matches if rule.priority == maximum]
        if len(winners) != 1:
            names = ", ".join(sorted(rule.rule_id for rule in winners))
            raise PolicyError(
                f"Conflicting source-export rules for {relative_path}: {names}"
            )
        winner = winners[0]
        return winner.rule_id, winner.disposition, winner.artifact_class


@dataclass(frozen=True)
class EmbeddedRecord:
    kind: str
    pointer: str
    value_type: str

    def wire(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "pointer": self.pointer,
            "valueType": self.value_type,
        }


@dataclass(frozen=True)
class ExportItem:
    relative_path: str
    entry_type: Literal["file", "excluded-subtree", "excluded-symlink"]
    artifact_class: str
    disposition: str
    rule_id: str
    source_mode: int
    byte_length: int
    content_digest: str | None
    git_state: str
    embedded_records: tuple[EmbeddedRecord, ...] = ()
    warnings: tuple[str, ...] = ()

    def wire(self) -> dict[str, Any]:
        return {
            "relativePath": self.relative_path,
            "entryType": self.entry_type,
            "artifactClass": self.artifact_class,
            "disposition": self.disposition,
            "ruleId": self.rule_id,
            "sourceMode": self.source_mode,
            "byteLength": self.byte_length,
            "contentDigest": self.content_digest,
            "gitState": self.git_state,
            "embeddedRecords": [item.wire() for item in self.embedded_records],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class StorageProbe:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    device_id: int


@dataclass(frozen=True)
class SourceExportResult:
    inventory: Mapping[str, Any]
    storage_assessment: Mapping[str, Any]

    def report_wire(self) -> dict[str, Any]:
        return {
            "schemaVersion": _REPORT_VERSION,
            "inventory": dict(self.inventory),
            "storageAssessment": dict(self.storage_assessment),
        }


@dataclass(frozen=True)
class _StatFingerprint:
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> _StatFingerprint:
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=value.st_mode,
            size=value.st_size,
            modified_ns=value.st_mtime_ns,
            changed_ns=value.st_ctime_ns,
        )


@dataclass(frozen=True)
class _ObservedEntry:
    relative_path: str
    fingerprint: _StatFingerprint
    entry_type: Literal["file", "symlink"]
    content_digest: str | None = None


_DirectorySignature = tuple[tuple[str, int, int, int, str], ...]


@dataclass(frozen=True)
class _ObservedDirectory:
    relative_path: str
    fingerprint: _StatFingerprint
    signature: _DirectorySignature


@dataclass(frozen=True)
class _GitEvidence:
    wire: Mapping[str, Any]
    states: Mapping[str, str]


EventHook = Callable[[str, Path], None]
StorageProbeFunction = Callable[[Path], StorageProbe]


def load_policy(path: Path) -> SourceExportPolicy:
    data = _read_regular_path(path, max_bytes=16 * 1024 * 1024)
    try:
        value = _strict_json_loads(data)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise PolicyError("Source-export policy must be strict UTF-8 JSON") from error
    root = _strict_object(
        value,
        required={
            "schemaVersion",
            "policyId",
            "sourceSystem",
            "limits",
            "rules",
            "fallbackFile",
        },
        context="policy",
    )
    if root["schemaVersion"] != _POLICY_VERSION:
        raise PolicyError("Unsupported source-export policy schema")
    policy_id = _bounded_text(root["policyId"], "policyId", 128)
    source_system = _bounded_text(root["sourceSystem"], "sourceSystem", 64)
    limits_value = _strict_object(
        root["limits"],
        required={
            "maxEntries",
            "maxFileBytes",
            "maxJsonScanBytes",
            "maxJsonDepth",
            "maxEmbeddedRecordsPerFile",
        },
        context="policy.limits",
    )
    limits = PolicyLimits(
        max_entries=_bounded_integer(
            limits_value["maxEntries"], "maxEntries", 1, 1_000_000
        ),
        max_file_bytes=_bounded_integer(
            limits_value["maxFileBytes"],
            "maxFileBytes",
            1,
            1024**4,
        ),
        max_json_scan_bytes=_bounded_integer(
            limits_value["maxJsonScanBytes"],
            "maxJsonScanBytes",
            0,
            256 * 1024 * 1024,
        ),
        max_json_depth=_bounded_integer(
            limits_value["maxJsonDepth"], "maxJsonDepth", 1, 256
        ),
        max_embedded_records_per_file=_bounded_integer(
            limits_value["maxEmbeddedRecordsPerFile"],
            "maxEmbeddedRecordsPerFile",
            0,
            100_000,
        ),
    )
    if not isinstance(root["rules"], list) or not root["rules"]:
        raise PolicyError("policy.rules must be a non-empty array")
    if len(root["rules"]) > 1000:
        raise PolicyError("policy.rules exceeds 1000 entries")
    rules = tuple(_parse_rule(item, index) for index, item in enumerate(root["rules"]))
    ids = [rule.rule_id for rule in rules]
    if len(ids) != len(set(ids)):
        raise PolicyError("Source-export rule IDs must be unique")
    fallback = _strict_object(
        root["fallbackFile"],
        required={"ruleId", "disposition", "artifactClass"},
        context="policy.fallbackFile",
    )
    fallback_rule_id = _bounded_text(fallback["ruleId"], "ruleId", 128)
    fallback_disposition = _disposition(fallback["disposition"])
    fallback_artifact_class = _bounded_text(
        fallback["artifactClass"], "artifactClass", 128
    )
    if fallback_rule_id in set(ids):
        raise PolicyError("fallback rule ID must not duplicate a rule ID")
    return SourceExportPolicy(
        schema_version=_POLICY_VERSION,
        policy_id=policy_id,
        source_system=source_system,
        limits=limits,
        rules=rules,
        fallback_rule_id=fallback_rule_id,
        fallback_disposition=fallback_disposition,
        fallback_artifact_class=fallback_artifact_class,
        content_digest=sha256_digest(data),
    )


def build_inventory(
    *,
    source_root: Path,
    source_root_id: str,
    destination_root: Path,
    destination_id: str,
    policy: SourceExportPolicy,
    event_hook: EventHook | None = None,
    storage_probe: StorageProbeFunction | None = None,
) -> SourceExportResult:
    source_root_id = _bounded_text(source_root_id, "sourceRootId", 256)
    destination_id = _bounded_text(destination_id, "destinationId", 256)
    source, source_fingerprint = _validated_directory(source_root, "source root")
    exporter_digest = _exporter_source_digest()
    destination = _prospective_path(destination_root)
    _require_separate_trees(source, destination)
    scanner = _SourceScanner(
        source,
        policy,
        expected_root=source_fingerprint,
        event_hook=event_hook,
    )
    items, git = scanner.scan()
    items = _assign_git_states(items, git.states)
    items = _assign_duplicate_aliases(items)
    summary = _inventory_summary(items)
    probe = (storage_probe or _default_storage_probe)(destination)
    storage = _storage_assessment(
        destination_id=destination_id,
        unique_import_bytes=summary["uniqueImportBytes"],
        probe=probe,
    )
    if _exporter_source_digest() != exporter_digest:
        raise SourceMutationError("Exporter source closure changed during inventory")
    item_wires = [item.wire() for item in items]
    item_manifest_digest = domain_digest(
        "tidy.export-item-manifest/v1",
        item_wires,
    )
    core: dict[str, Any] = {
        "schemaVersion": _INVENTORY_VERSION,
        "source": {
            "sourceSystem": policy.source_system,
            "sourceRootId": source_root_id,
            "filesystem": {
                "deviceId": source_fingerprint.device,
                "rootInode": source_fingerprint.inode,
                "rootMode": source_fingerprint.mode,
            },
            "git": dict(git.wire),
        },
        "policy": {
            "policyId": policy.policy_id,
            "contentDigest": policy.content_digest,
        },
        "exporter": {
            "version": _EXPORTER_VERSION,
            "sourceDigest": exporter_digest,
            "canonicalizationAlgorithm": _CANONICALIZATION,
        },
        "safety": {
            "pathPolicy": "relative-utf8-posix-no-dotdot-v1",
            "symlinkPolicy": "no-follow-explicit-exclusion-only-v1",
            "specialFilePolicy": "reject-v1",
            "mutationPolicy": "pre-post-final-and-git-repeat-v1",
        },
        "items": item_wires,
        "itemManifestDigest": item_manifest_digest,
        "summary": summary,
    }
    inventory_digest = domain_digest(_INVENTORY_VERSION, core)
    inventory = {**core, "inventoryDigest": inventory_digest}
    return SourceExportResult(inventory=inventory, storage_assessment=storage)


def freeze_snapshot(
    result: SourceExportResult,
    *,
    frozen_at: str,
) -> dict[str, Any]:
    normalized_time = _utc_timestamp(frozen_at)
    storage = dict(result.storage_assessment)
    if not storage["passes"]:
        raise HeadroomError(
            "Destination does not satisfy source-export headroom requirements"
        )
    storage_digest = domain_digest("tidy.storage-assessment/v1", storage)
    identity = {
        "completionStatus": "complete",
        "frozenAt": normalized_time,
        "inventoryDigest": result.inventory["inventoryDigest"],
        "storageAssessmentDigest": storage_digest,
    }
    return {
        "schemaVersion": _SNAPSHOT_VERSION,
        "completionStatus": "complete",
        "frozenAt": normalized_time,
        "inventory": dict(result.inventory),
        "storageAssessment": storage,
        "storageAssessmentDigest": storage_digest,
        "snapshotDigest": domain_digest(_SNAPSHOT_VERSION, identity),
    }


def load_and_verify_export(path: Path) -> tuple[dict[str, Any], str]:
    data = _read_regular_path(path, max_bytes=_MAX_EXPORT_WIRE_BYTES)
    try:
        value = _strict_json_loads(data)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceExportError(
            "Source-export wire must be strict UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise SourceExportError("Source-export wire must be an object")
    return value, verify_export_wire(value)


def verify_export_wire(value: Any) -> str:
    root = _wire_object(value, "source export")
    version = root.get("schemaVersion")
    if version == _REPORT_VERSION:
        _wire_exact_keys(
            root,
            {"schemaVersion", "inventory", "storageAssessment"},
            "source-export report",
        )
        inventory_digest = _verify_inventory_wire(root["inventory"])
        _verify_storage_wire(root["storageAssessment"])
        return inventory_digest
    if version == _SNAPSHOT_VERSION:
        _wire_exact_keys(
            root,
            {
                "schemaVersion",
                "completionStatus",
                "frozenAt",
                "inventory",
                "storageAssessment",
                "storageAssessmentDigest",
                "snapshotDigest",
            },
            "source-export snapshot",
        )
        if root["completionStatus"] != "complete":
            raise SourceExportError("Snapshot completion status must be complete")
        frozen_at = _utc_timestamp(_wire_text(root["frozenAt"], "frozenAt"))
        if root["frozenAt"] != frozen_at:
            raise SourceExportError("Snapshot frozenAt must use canonical UTC Z form")
        inventory_digest = _verify_inventory_wire(root["inventory"])
        storage = _verify_storage_wire(root["storageAssessment"])
        if not storage["passes"]:
            raise SourceExportError("Frozen snapshot cannot contain failed headroom")
        storage_digest = domain_digest("tidy.storage-assessment/v1", storage)
        if root["storageAssessmentDigest"] != storage_digest:
            raise SourceExportError("Storage-assessment digest mismatch")
        expected = domain_digest(
            _SNAPSHOT_VERSION,
            {
                "completionStatus": "complete",
                "frozenAt": frozen_at,
                "inventoryDigest": inventory_digest,
                "storageAssessmentDigest": storage_digest,
            },
        )
        if root["snapshotDigest"] != expected:
            raise SourceExportError("Source-export snapshot digest mismatch")
        return expected
    raise SourceExportError("Unsupported source-export wire schema")


def publish_snapshot_to_nas(
    *,
    snapshot_path: Path,
    destination_root: Path,
) -> tuple[Path, dict[str, Any], bool]:
    """Publish one verified snapshot behind a durable commit marker.

    SMB does not necessarily support hard links. Publication therefore creates
    an exclusive digest directory, writes and verifies the snapshot, and emits
    ``COMMITTED.json`` last. Consumers must ignore directories without a valid
    commit marker.
    """

    snapshot_data = _read_regular_path(
        snapshot_path,
        max_bytes=_MAX_EXPORT_WIRE_BYTES,
    )
    snapshot = _strict_export_json(snapshot_data)
    snapshot_digest = verify_export_wire(snapshot)
    if snapshot.get("schemaVersion") != _SNAPSHOT_VERSION:
        raise SourceExportError("Only frozen snapshots may be published")
    if snapshot["snapshotDigest"] != snapshot_digest:
        raise SourceExportError("Snapshot identity did not verify")

    root, _root_fingerprint = _validated_directory(
        destination_root,
        "NAS destination root",
    )
    parent = root / "source-snapshots"
    parent_created = False
    try:
        parent.mkdir(mode=0o700)
        parent_created = True
    except FileExistsError:
        pass
    parent, _parent_fingerprint = _validated_directory(
        parent,
        "NAS source-snapshots directory",
    )
    os.chmod(parent, 0o700)
    if parent_created:
        _fsync_directory(root)

    final = parent / snapshot_digest.replace(":", "-")
    try:
        final.mkdir(mode=0o700)
    except FileExistsError:
        commit = verify_nas_snapshot_publication(final)
        expected = _nas_commit_wire(snapshot, snapshot_data)
        if commit != expected:
            raise SourceExportError(
                "Existing NAS snapshot publication has conflicting evidence"
            ) from None
        return final, commit, False

    created = True
    try:
        os.chmod(final, 0o700)
        _fsync_directory(parent)
        _write_exclusive_fsynced(final / "snapshot.json", snapshot_data)
        observed = _read_regular_path(
            final / "snapshot.json",
            max_bytes=_MAX_EXPORT_WIRE_BYTES,
        )
        if sha256_digest(observed) != sha256_digest(snapshot_data):
            raise SourceExportError("NAS snapshot readback digest mismatch")
        commit = _nas_commit_wire(snapshot, snapshot_data)
        commit_payload = canonical_json_bytes(commit) + b"\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".COMMITTED.json.",
            suffix=".tmp",
            dir=final,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            stream = os.fdopen(descriptor, "wb", closefd=True)
            descriptor = -1
            with stream:
                stream.write(commit_payload)
                stream.flush()
                os.fsync(stream.fileno())
            if os.path.lexists(final / "COMMITTED.json"):
                raise SourceExportError("NAS commit marker already exists")
            os.rename(temporary, final / "COMMITTED.json")
            temporary = None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        os.chmod(final / "COMMITTED.json", 0o600)
        _fsync_directory(final)
        _fsync_directory(parent)
        verified = verify_nas_snapshot_publication(final)
        if verified != commit:
            raise SourceExportError("NAS publication verification mismatch")
        return final, commit, created
    except BaseException:
        shutil.rmtree(final, ignore_errors=True)
        _fsync_directory(parent)
        raise


def verify_nas_snapshot_publication(directory: Path) -> dict[str, Any]:
    publication, before = _validated_directory(
        directory,
        "NAS snapshot publication",
    )
    with os.scandir(publication) as entries:
        names = sorted(entry.name for entry in entries)
    if names != ["COMMITTED.json", "snapshot.json"]:
        raise SourceExportError("NAS snapshot publication has unexpected files")
    commit_data = _read_regular_path(
        publication / "COMMITTED.json",
        max_bytes=1024 * 1024,
    )
    try:
        commit = _strict_json_loads(commit_data)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceExportError(
            "NAS commit marker must be strict UTF-8 JSON"
        ) from error
    commit = _verify_nas_commit_wire(commit)
    if commit_data != canonical_json_bytes(commit) + b"\n":
        raise SourceExportError("NAS commit marker is not canonical JSON")

    snapshot_data = _read_regular_path(
        publication / "snapshot.json",
        max_bytes=_MAX_EXPORT_WIRE_BYTES,
    )
    snapshot = _strict_export_json(snapshot_data)
    digest = verify_export_wire(snapshot)
    if snapshot.get("schemaVersion") != _SNAPSHOT_VERSION:
        raise SourceExportError("NAS publication does not contain a snapshot")
    expected = _nas_commit_wire(snapshot, snapshot_data)
    if commit != expected:
        raise SourceExportError("NAS commit marker does not match snapshot bytes")
    for path in (
        publication,
        publication / "COMMITTED.json",
        publication / "snapshot.json",
    ):
        if path.lstat().st_mode & 0o077:
            raise SourceSafetyError("NAS snapshot publication is not private")
    if publication.name != digest.replace(":", "-"):
        raise SourceExportError("NAS publication directory does not match snapshot")
    _publication, after = _validated_directory(
        publication,
        "NAS snapshot publication",
    )
    if before != after:
        raise SourceMutationError(
            "NAS snapshot publication changed during verification"
        )
    return commit


def _strict_export_json(data: bytes) -> dict[str, Any]:
    try:
        value = _strict_json_loads(data)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SourceExportError(
            "Source-export wire must be strict UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise SourceExportError("Source-export wire must be an object")
    return value


def _nas_commit_wire(
    snapshot: Mapping[str, Any],
    snapshot_data: bytes,
) -> dict[str, Any]:
    return {
        "schemaVersion": _NAS_COMMIT_VERSION,
        "snapshotDigest": snapshot["snapshotDigest"],
        "inventoryDigest": snapshot["inventory"]["inventoryDigest"],
        "snapshotFileDigest": sha256_digest(snapshot_data),
        "snapshotFileBytes": len(snapshot_data),
        "frozenAt": snapshot["frozenAt"],
    }


def _verify_nas_commit_wire(value: Any) -> dict[str, Any]:
    commit = _wire_object(value, "NAS snapshot commit")
    _wire_exact_keys(
        commit,
        {
            "schemaVersion",
            "snapshotDigest",
            "inventoryDigest",
            "snapshotFileDigest",
            "snapshotFileBytes",
            "frozenAt",
        },
        "NAS snapshot commit",
    )
    if commit["schemaVersion"] != _NAS_COMMIT_VERSION:
        raise SourceExportError("Unsupported NAS snapshot commit schema")
    for name in ("snapshotDigest", "inventoryDigest", "snapshotFileDigest"):
        if not _is_digest(commit[name]):
            raise SourceExportError(f"Invalid NAS commit {name}")
    if not isinstance(commit["snapshotFileBytes"], int) or isinstance(
        commit["snapshotFileBytes"], bool
    ):
        raise SourceExportError("NAS commit snapshotFileBytes must be an integer")
    if not 0 <= commit["snapshotFileBytes"] <= _MAX_EXPORT_WIRE_BYTES:
        raise SourceExportError("NAS commit snapshotFileBytes is out of range")
    frozen_at = _utc_timestamp(_wire_text(commit["frozenAt"], "frozenAt"))
    if commit["frozenAt"] != frozen_at:
        raise SourceExportError("NAS commit frozenAt must use canonical UTC Z form")
    return dict(commit)


def _write_exclusive_fsynced(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("Short write while publishing NAS snapshot")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_inventory_wire(value: Any) -> str:
    inventory = _wire_object(value, "inventory")
    _wire_exact_keys(
        inventory,
        {
            "schemaVersion",
            "source",
            "policy",
            "exporter",
            "safety",
            "items",
            "itemManifestDigest",
            "summary",
            "inventoryDigest",
        },
        "inventory",
    )
    if inventory["schemaVersion"] != _INVENTORY_VERSION:
        raise SourceExportError("Unsupported inventory schema")
    source = _wire_object(inventory["source"], "inventory.source")
    _wire_exact_keys(
        source,
        {"sourceSystem", "sourceRootId", "filesystem", "git"},
        "source",
    )
    _wire_text(source["sourceSystem"], "sourceSystem")
    _wire_text(source["sourceRootId"], "sourceRootId")
    filesystem = _wire_object(source["filesystem"], "inventory.source.filesystem")
    _wire_exact_keys(
        filesystem,
        {"deviceId", "rootInode", "rootMode"},
        "source filesystem",
    )
    _wire_integer(filesystem["deviceId"], "source deviceId", signed=True)
    _wire_integer(filesystem["rootInode"], "source rootInode")
    root_mode = _wire_integer(filesystem["rootMode"], "source rootMode")
    if not stat.S_ISDIR(root_mode):
        raise SourceExportError("Source rootMode must identify a directory")
    git = _wire_object(source["git"], "inventory.source.git")
    _wire_exact_keys(
        git,
        {"available", "head", "tree", "trackedDirty", "trackedDirtyDigest"},
        "git evidence",
    )
    if not isinstance(git["available"], bool):
        raise SourceExportError("git.available must be boolean")
    for name in ("head", "tree"):
        if git[name] is not None and not isinstance(git[name], str):
            raise SourceExportError(f"git.{name} must be string or null")
    if git["trackedDirty"] is not None and not isinstance(git["trackedDirty"], bool):
        raise SourceExportError("git.trackedDirty must be boolean or null")
    if git["trackedDirtyDigest"] is not None and not _is_digest(
        git["trackedDirtyDigest"]
    ):
        raise SourceExportError("Invalid git tracked-dirty digest")
    if git["available"]:
        if not _is_git_object_id(git["head"]) or not _is_git_object_id(git["tree"]):
            raise SourceExportError("Available Git evidence needs HEAD and tree IDs")
        if (
            not isinstance(git["trackedDirty"], bool)
            or git["trackedDirtyDigest"] is None
        ):
            raise SourceExportError("Available Git evidence is incomplete")
    elif any(
        git[name] is not None
        for name in ("head", "tree", "trackedDirty", "trackedDirtyDigest")
    ):
        raise SourceExportError("Unavailable Git evidence must use null fields")
    policy = _wire_object(inventory["policy"], "inventory.policy")
    _wire_exact_keys(policy, {"policyId", "contentDigest"}, "policy evidence")
    _wire_text(policy["policyId"], "policyId")
    if not _is_digest(policy["contentDigest"]):
        raise SourceExportError("Invalid policy content digest")
    exporter = _wire_object(inventory["exporter"], "inventory.exporter")
    _wire_exact_keys(
        exporter,
        {"version", "sourceDigest", "canonicalizationAlgorithm"},
        "exporter evidence",
    )
    if exporter["version"] != _EXPORTER_VERSION:
        raise SourceExportError("Unsupported exporter version")
    if not _is_digest(exporter["sourceDigest"]):
        raise SourceExportError("Invalid exporter source digest")
    if exporter["canonicalizationAlgorithm"] != _CANONICALIZATION:
        raise SourceExportError("Unsupported inventory canonicalization")
    safety = _wire_object(inventory["safety"], "inventory.safety")
    expected_safety = {
        "pathPolicy": "relative-utf8-posix-no-dotdot-v1",
        "symlinkPolicy": "no-follow-explicit-exclusion-only-v1",
        "specialFilePolicy": "reject-v1",
        "mutationPolicy": "pre-post-final-and-git-repeat-v1",
    }
    if safety != expected_safety:
        raise SourceExportError("Unsupported source-export safety policy")
    items = inventory["items"]
    if not isinstance(items, list):
        raise SourceExportError("inventory.items must be an array")
    if len(items) > 1_000_000:
        raise SourceExportError("inventory.items exceeds its contract bound")
    paths: list[str] = []
    import_counts: Counter[str] = Counter()
    alias_counts: Counter[str] = Counter()
    for index, item_value in enumerate(items):
        item = _wire_object(item_value, f"inventory.items[{index}]")
        _wire_exact_keys(
            item,
            {
                "relativePath",
                "entryType",
                "artifactClass",
                "disposition",
                "ruleId",
                "sourceMode",
                "byteLength",
                "contentDigest",
                "gitState",
                "embeddedRecords",
                "warnings",
            },
            f"inventory.items[{index}]",
        )
        path = _wire_text(item["relativePath"], "relativePath")
        if (
            PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or "\\" in path
            or "\x00" in path
        ):
            raise SourceExportError("Inventory path is not safe and relative")
        paths.append(path)
        if item["entryType"] not in (
            "file",
            "excluded-subtree",
            "excluded-symlink",
        ):
            raise SourceExportError("Unsupported inventory entry type")
        _wire_text(item["artifactClass"], "artifactClass")
        _wire_text(item["ruleId"], "ruleId")
        if item["gitState"] not in ("tracked", "untracked", "ignored", "unknown"):
            raise SourceExportError("Unsupported inventory git state")
        if item["disposition"] not in (
            "import",
            "exclude",
            "quarantine",
            "duplicate-alias",
        ):
            raise SourceExportError("Unsupported inventory disposition")
        source_mode = _wire_integer(item["sourceMode"], "sourceMode")
        digest = item["contentDigest"]
        if digest is not None and not _is_digest(digest):
            raise SourceExportError("Invalid item content digest")
        if not isinstance(item["byteLength"], int) or isinstance(
            item["byteLength"], bool
        ):
            raise SourceExportError("Invalid item byte length")
        if item["byteLength"] < 0:
            raise SourceExportError("Invalid item byte length")
        if item["entryType"] == "excluded-subtree":
            if (
                item["disposition"] != "exclude"
                or item["byteLength"] != 0
                or digest is not None
                or not stat.S_ISDIR(source_mode)
            ):
                raise SourceExportError("Excluded subtree fields are inconsistent")
        elif item["entryType"] == "excluded-symlink":
            if (
                item["disposition"] != "exclude"
                or digest is None
                or not stat.S_ISLNK(source_mode)
            ):
                raise SourceExportError("Excluded symlink fields are inconsistent")
        elif digest is None or not stat.S_ISREG(source_mode):
            raise SourceExportError("Regular file evidence is incomplete")
        if item["disposition"] == "import" and digest is not None:
            import_counts[digest] += 1
        if item["disposition"] == "duplicate-alias" and digest is not None:
            alias_counts[digest] += 1
        if not isinstance(item["embeddedRecords"], list) or not isinstance(
            item["warnings"], list
        ):
            raise SourceExportError("Invalid item evidence arrays")
        for record_value in item["embeddedRecords"]:
            record = _wire_object(record_value, "embedded record")
            _wire_exact_keys(
                record, {"kind", "pointer", "valueType"}, "embedded record"
            )
            if record["kind"] not in (
                "recipe-document",
                "recipe-candidate",
                "prompt-evidence",
                "provider-response-evidence",
            ):
                raise SourceExportError("Unsupported embedded-record kind")
            if not isinstance(record["pointer"], str) or len(record["pointer"]) > 8192:
                raise SourceExportError("Embedded pointer is invalid")
            if record["valueType"] not in (
                "null",
                "boolean",
                "object",
                "array",
                "string",
                "number",
                "unknown",
            ):
                raise SourceExportError("Unsupported embedded valueType")
        if any(
            not isinstance(warning, str) or not warning for warning in item["warnings"]
        ):
            raise SourceExportError("Warnings must be non-empty strings")
        if len(item["warnings"]) != len(set(item["warnings"])):
            raise SourceExportError("Warnings must be unique")
        if any(len(warning) > 128 for warning in item["warnings"]):
            raise SourceExportError("Warning exceeds its contract bound")
    if any(count != 1 for count in import_counts.values()):
        raise SourceExportError("Each imported digest needs one primary item")
    if any(digest not in import_counts for digest in alias_counts):
        raise SourceExportError("Duplicate alias has no imported primary item")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise SourceExportError("Inventory paths must be unique and sorted")
    expected_item_manifest_digest = domain_digest(
        "tidy.export-item-manifest/v1",
        items,
    )
    if inventory["itemManifestDigest"] != expected_item_manifest_digest:
        raise SourceExportError("Export-item manifest digest mismatch")
    expected_summary = _summary_from_item_wires(items)
    summary = _wire_object(inventory["summary"], "inventory.summary")
    _wire_exact_keys(summary, set(expected_summary), "inventory summary")
    for key, summary_value in summary.items():
        if isinstance(summary_value, dict):
            if any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in summary_value.values()
            ):
                raise SourceExportError("Inventory summary map is invalid")
        elif isinstance(summary_value, bool) or not isinstance(summary_value, int):
            raise SourceExportError(f"Inventory summary {key} must be an integer")
    if summary != expected_summary:
        raise SourceExportError("Inventory summary mismatch")
    digest = inventory["inventoryDigest"]
    if not _is_digest(digest):
        raise SourceExportError("Invalid inventory digest")
    core = {key: item for key, item in inventory.items() if key != "inventoryDigest"}
    expected = domain_digest(_INVENTORY_VERSION, core)
    if digest != expected:
        raise SourceExportError("Inventory digest mismatch")
    return expected


def _verify_storage_wire(value: Any) -> dict[str, Any]:
    storage = _wire_object(value, "storage assessment")
    expected_keys = {
        "schemaVersion",
        "destinationId",
        "deviceId",
        "totalBytes",
        "usedBytes",
        "freeBytes",
        "estimatedUniqueImportBytes",
        "requiredFreeBytes",
        "projectedUtilizationBasisPoints",
        "maximumUtilizationBasisPoints",
        "freeSpacePasses",
        "utilizationPasses",
        "passes",
    }
    _wire_exact_keys(storage, expected_keys, "storage assessment")
    for name in ("freeSpacePasses", "utilizationPasses", "passes"):
        if not isinstance(storage[name], bool):
            raise SourceExportError(f"{name} must be boolean")
    for name in (
        "requiredFreeBytes",
        "projectedUtilizationBasisPoints",
        "maximumUtilizationBasisPoints",
    ):
        _wire_integer(storage[name], name)
    rebuilt = _storage_assessment(
        destination_id=_wire_text(storage["destinationId"], "destinationId"),
        unique_import_bytes=_wire_integer(
            storage["estimatedUniqueImportBytes"], "estimatedUniqueImportBytes"
        ),
        probe=StorageProbe(
            total_bytes=_wire_integer(storage["totalBytes"], "totalBytes"),
            used_bytes=_wire_integer(storage["usedBytes"], "usedBytes"),
            free_bytes=_wire_integer(storage["freeBytes"], "freeBytes"),
            device_id=_wire_integer(storage["deviceId"], "deviceId", signed=True),
        ),
    )
    if storage != rebuilt:
        raise SourceExportError("Storage assessment is internally inconsistent")
    return storage


def _summary_from_item_wires(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    dispositions = Counter(str(item["disposition"]) for item in items)
    artifact_classes = Counter(str(item["artifactClass"]) for item in items)
    git_states = Counter(str(item["gitState"]) for item in items)
    bytes_by_disposition: Counter[str] = Counter()
    unique_import: dict[str, int] = {}
    warning_count = 0
    embedded_count = 0
    for item in items:
        disposition = str(item["disposition"])
        byte_length = int(item["byteLength"])
        bytes_by_disposition[disposition] += byte_length
        warning_count += len(item["warnings"])
        embedded_count += len(item["embeddedRecords"])
        digest = item["contentDigest"]
        if disposition in ("import", "duplicate-alias") and digest is not None:
            unique_import.setdefault(str(digest), byte_length)
    return {
        "itemCount": len(items),
        "fileCount": sum(item["entryType"] == "file" for item in items),
        "excludedSubtreeCount": sum(
            item["entryType"] == "excluded-subtree" for item in items
        ),
        "excludedSymlinkCount": sum(
            item["entryType"] == "excluded-symlink" for item in items
        ),
        "dispositions": dict(sorted(dispositions.items())),
        "artifactClasses": dict(sorted(artifact_classes.items())),
        "gitStates": dict(sorted(git_states.items())),
        "bytesByDisposition": dict(sorted(bytes_by_disposition.items())),
        "uniqueImportObjects": len(unique_import),
        "uniqueImportBytes": sum(unique_import.values()),
        "embeddedRecordCount": embedded_count,
        "warningCount": warning_count,
    }


def _wire_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceExportError(f"{context} must be an object")
    return value


def _wire_exact_keys(
    value: Mapping[str, Any], expected: set[str], context: str
) -> None:
    if set(value) != expected:
        raise SourceExportError(f"{context} fields do not match the contract")


def _wire_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SourceExportError(f"{name} must be a non-empty string")
    return value


def _wire_integer(value: Any, name: str, *, signed: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SourceExportError(f"{name} must be an integer")
    if not signed and value < 0:
        raise SourceExportError(f"{name} must be non-negative")
    return value


def _is_git_object_id(value: Any) -> bool:
    if not isinstance(value, str) or len(value) not in (40, 64):
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _is_digest(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 71:
        return False
    if not value.startswith("sha256:"):
        return False
    try:
        int(value[7:], 16)
    except ValueError:
        return False
    return value[7:] == value[7:].lower()


class _SourceScanner:
    def __init__(
        self,
        source_root: Path,
        policy: SourceExportPolicy,
        *,
        expected_root: _StatFingerprint,
        event_hook: EventHook | None,
    ) -> None:
        self.source_root = source_root
        self.policy = policy
        self.expected_root = expected_root
        self.event_hook = event_hook
        self._observed: list[_ObservedEntry] = []
        self._directories: list[_ObservedDirectory] = []
        self._items: list[ExportItem] = []
        self._entry_count = 0

    def scan(self) -> tuple[tuple[ExportItem, ...], _GitEvidence]:
        flags = os.O_RDONLY | os.O_DIRECTORY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(self.source_root, flags)
        try:
            root_before = _StatFingerprint.from_stat(os.fstat(root_fd))
            if root_before != self.expected_root:
                raise SourceMutationError("Source root identity changed before scan")
            self._walk_directory(root_fd, ())
            root_after = _StatFingerprint.from_stat(os.fstat(root_fd))
            if root_before != root_after:
                raise SourceMutationError("Source root changed during inventory")
            if self.event_hook is not None:
                self.event_hook("before-final-verify", self.source_root)
            git = _git_evidence(self.source_root, self._items)
            self._verify_observed(root_fd)
            repeated_git = _git_evidence(self.source_root, self._items)
            self._verify_observed(root_fd)
            if git != repeated_git:
                raise SourceMutationError("Git evidence changed during inventory")
            return tuple(sorted(self._items, key=lambda item: item.relative_path)), git
        finally:
            os.close(root_fd)

    def _walk_directory(self, directory_fd: int, parts: tuple[str, ...]) -> None:
        before = _StatFingerprint.from_stat(os.fstat(directory_fd))
        entries, signature = _directory_entries(directory_fd)
        for name, fingerprint, entry_type in entries:
            relative_parts = (*parts, name)
            relative_path = PurePosixPath(*relative_parts).as_posix()
            self._count_entry()
            if entry_type == "symlink":
                classification = self.policy.classify(relative_path, "symlink")
                if classification is None or classification[1] != "exclude":
                    raise SourceSafetyError(
                        f"Symlink is not permitted in source scope: {relative_path}"
                    )
                rule_id, disposition, artifact_class = classification
                target_digest, target_length, observed = self._hash_symlink(
                    directory_fd,
                    name,
                    relative_path,
                    fingerprint,
                )
                self._observed.append(
                    _ObservedEntry(
                        relative_path=relative_path,
                        fingerprint=observed,
                        entry_type="symlink",
                        content_digest=target_digest,
                    )
                )
                self._items.append(
                    ExportItem(
                        relative_path=relative_path,
                        entry_type="excluded-symlink",
                        artifact_class=artifact_class,
                        disposition=disposition,
                        rule_id=rule_id,
                        source_mode=observed.mode,
                        byte_length=target_length,
                        content_digest=target_digest,
                        git_state="unknown",
                        warnings=("SYMLINK_NOT_FOLLOWED",),
                    )
                )
                continue
            if entry_type == "special":
                raise SourceSafetyError(
                    f"Special filesystem object is not permitted: {relative_path}"
                )
            if entry_type == "directory":
                classification = self.policy.classify(relative_path, "directory")
                if classification is not None:
                    rule_id, disposition, artifact_class = classification
                    if disposition != "exclude":
                        raise PolicyError(
                            "Directory rules may only exclude complete subtrees"
                        )
                    self._items.append(
                        ExportItem(
                            relative_path=relative_path,
                            entry_type="excluded-subtree",
                            artifact_class=artifact_class,
                            disposition="exclude",
                            rule_id=rule_id,
                            source_mode=fingerprint.mode,
                            byte_length=0,
                            content_digest=None,
                            git_state="unknown",
                        )
                    )
                    continue
                child_fd = _open_directory_at(directory_fd, name)
                try:
                    if _StatFingerprint.from_stat(os.fstat(child_fd)) != fingerprint:
                        raise SourceMutationError(
                            "Directory identity changed before traversal: "
                            f"{relative_path}"
                        )
                    self._walk_directory(child_fd, relative_parts)
                finally:
                    os.close(child_fd)
                continue
            self._scan_file(directory_fd, name, relative_path, fingerprint)
        after_entries, after_signature = _directory_entries(directory_fd)
        del after_entries
        after = _StatFingerprint.from_stat(os.fstat(directory_fd))
        directory = PurePosixPath(*parts).as_posix() if parts else "."
        if before != after or signature != after_signature:
            raise SourceMutationError(
                f"Directory membership changed during inventory: {directory}"
            )
        self._directories.append(
            _ObservedDirectory(
                relative_path=directory,
                fingerprint=after,
                signature=after_signature,
            )
        )

    def _scan_file(
        self,
        directory_fd: int,
        name: str,
        relative_path: str,
        expected: _StatFingerprint,
    ) -> None:
        classification = self.policy.classify(relative_path, "file")
        assert classification is not None
        rule_id, disposition, artifact_class = classification
        should_discover = disposition != "exclude"
        digest, data, prefix, observed = self._hash_file(
            directory_fd, name, relative_path, expected
        )
        self._observed.append(
            _ObservedEntry(
                relative_path=relative_path,
                fingerprint=observed,
                entry_type="file",
            )
        )
        embedded: tuple[EmbeddedRecord, ...] = ()
        warnings: tuple[str, ...] = ()
        if should_discover:
            embedded, warnings = _discover_embedded_records(
                relative_path=relative_path,
                artifact_class=artifact_class,
                data=data,
                byte_length=observed.size,
                limits=self.policy.limits,
            )
            if (
                any(
                    warning in warnings
                    for warning in ("JSON_PARSE_FAILED", "JSONL_PARSE_FAILED")
                )
                and artifact_class in _PROTECTED_JSON_CLASSES
            ):
                disposition = "quarantine"
        content_warnings, content_valid = _validate_content_signature(
            relative_path=relative_path,
            artifact_class=artifact_class,
            prefix=prefix,
        )
        warnings = tuple(dict.fromkeys((*warnings, *content_warnings)))
        if not content_valid and disposition != "exclude":
            disposition = "quarantine"
        self._items.append(
            ExportItem(
                relative_path=relative_path,
                entry_type="file",
                artifact_class=artifact_class,
                disposition=disposition,
                rule_id=rule_id,
                source_mode=observed.mode,
                byte_length=observed.size,
                content_digest=digest,
                git_state="unknown",
                embedded_records=embedded,
                warnings=warnings,
            )
        )

    def _hash_symlink(
        self,
        directory_fd: int,
        name: str,
        relative_path: str,
        expected: _StatFingerprint,
    ) -> tuple[str, int, _StatFingerprint]:
        before = _StatFingerprint.from_stat(
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        )
        if before != expected or not stat.S_ISLNK(before.mode):
            raise SourceMutationError(
                f"Symlink identity changed before read: {relative_path}"
            )
        target = os.readlink(os.fsencode(name), dir_fd=directory_fd)
        if not isinstance(target, bytes):
            raise SourceSafetyError("Symlink target did not preserve raw bytes")
        if self.event_hook is not None:
            self.event_hook("after-symlink-read", self.source_root / relative_path)
        after = _StatFingerprint.from_stat(
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        )
        if before != after or len(target) != before.size:
            raise SourceMutationError(f"Symlink changed while reading: {relative_path}")
        return sha256_digest(target), len(target), after

    def _hash_file(
        self,
        directory_fd: int,
        name: str,
        relative_path: str,
        expected: _StatFingerprint,
    ) -> tuple[str, bytes | None, bytes, _StatFingerprint]:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(name, flags, dir_fd=directory_fd)
        try:
            before = _StatFingerprint.from_stat(os.fstat(file_fd))
            if before != expected or not stat.S_ISREG(before.mode):
                raise SourceMutationError(
                    f"File identity changed before read: {relative_path}"
                )
            if before.size > self.policy.limits.max_file_bytes:
                raise SourceLimitError(f"File exceeds maxFileBytes: {relative_path}")
            digest = hashlib.sha256()
            retain = before.size <= self.policy.limits.max_json_scan_bytes
            retained = bytearray() if retain else None
            prefix = bytearray()
            count = 0
            while True:
                chunk = os.read(file_fd, _READ_CHUNK)
                if not chunk:
                    break
                count += len(chunk)
                if count > self.policy.limits.max_file_bytes:
                    raise SourceLimitError(
                        f"File exceeded maxFileBytes while reading: {relative_path}"
                    )
                digest.update(chunk)
                if len(prefix) < 16:
                    prefix.extend(chunk[: 16 - len(prefix)])
                if retained is not None:
                    retained.extend(chunk)
            if self.event_hook is not None:
                self.event_hook("after-file-read", self.source_root / relative_path)
            after = _StatFingerprint.from_stat(os.fstat(file_fd))
            if before != after or count != before.size:
                raise SourceMutationError(
                    f"File changed while reading: {relative_path}"
                )
            return (
                f"sha256:{digest.hexdigest()}",
                bytes(retained) if retained is not None else None,
                bytes(prefix),
                after,
            )
        finally:
            os.close(file_fd)

    def _verify_observed(self, root_fd: int) -> None:
        for observed in self._observed:
            parts = tuple(PurePosixPath(observed.relative_path).parts)
            if observed.entry_type == "symlink":
                parent = _open_relative_directory(root_fd, parts[:-1])
                try:
                    current = _StatFingerprint.from_stat(
                        os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                    )
                    target = os.readlink(os.fsencode(parts[-1]), dir_fd=parent)
                    current_digest = (
                        sha256_digest(target) if isinstance(target, bytes) else None
                    )
                finally:
                    os.close(parent)
                if (
                    current != observed.fingerprint
                    or current_digest != observed.content_digest
                ):
                    raise SourceMutationError(
                        "Source symlink changed before inventory finalization: "
                        f"{observed.relative_path}"
                    )
                continue
            descriptor = _open_relative_file(root_fd, parts)
            try:
                current = _StatFingerprint.from_stat(os.fstat(descriptor))
                if current != observed.fingerprint:
                    raise SourceMutationError(
                        "Source entry changed before inventory finalization: "
                        f"{observed.relative_path}"
                    )
            finally:
                os.close(descriptor)
        for observed in self._directories:
            parts = (
                ()
                if observed.relative_path == "."
                else tuple(PurePosixPath(observed.relative_path).parts)
            )
            descriptor = _open_relative_directory(root_fd, parts)
            try:
                current = _StatFingerprint.from_stat(os.fstat(descriptor))
                _, signature = _directory_entries(descriptor)
                if current != observed.fingerprint or signature != observed.signature:
                    raise SourceMutationError(
                        "Source directory changed before inventory finalization: "
                        f"{observed.relative_path}"
                    )
            finally:
                os.close(descriptor)

    def _count_entry(self) -> None:
        self._entry_count += 1
        if self._entry_count > self.policy.limits.max_entries:
            raise SourceLimitError("Source tree exceeds maxEntries")


def _parse_rule(value: Any, index: int) -> SourceExportRule:
    allowed = {
        "id",
        "priority",
        "entryTypes",
        "pathPrefixes",
        "exactPaths",
        "suffixes",
        "basenameGlobs",
        "directoryNames",
        "disposition",
        "artifactClass",
    }
    root = _strict_object(
        value,
        required={
            "id",
            "priority",
            "entryTypes",
            "disposition",
            "artifactClass",
        },
        optional=allowed
        - {"id", "priority", "entryTypes", "disposition", "artifactClass"},
        context=f"policy.rules[{index}]",
    )
    entry_types_value = root["entryTypes"]
    if not isinstance(entry_types_value, list) or not entry_types_value:
        raise PolicyError("entryTypes must be a non-empty array")
    entry_types = frozenset(entry_types_value)
    if (
        any(not isinstance(item, str) for item in entry_types_value)
        or not entry_types <= _ALLOWED_ENTRY_TYPES
    ):
        raise PolicyError("entryTypes contains an unsupported value")
    selectors = {
        "pathPrefixes": _path_list(root.get("pathPrefixes"), "pathPrefixes"),
        "exactPaths": _path_list(root.get("exactPaths"), "exactPaths"),
        "suffixes": _text_list(root.get("suffixes"), "suffixes", 64),
        "basenameGlobs": _text_list(root.get("basenameGlobs"), "basenameGlobs", 256),
        "directoryNames": _text_list(root.get("directoryNames"), "directoryNames", 256),
    }
    if not any(selectors.values()):
        raise PolicyError("Every source-export rule needs at least one selector")
    if selectors["directoryNames"] and entry_types != {"directory"}:
        raise PolicyError("directoryNames rules must target only directories")
    suffixes = tuple(item.lower() for item in selectors["suffixes"])
    return SourceExportRule(
        rule_id=_bounded_text(root["id"], "id", 128),
        priority=_bounded_integer(root["priority"], "priority", 0, 1_000_000),
        entry_types=entry_types,
        disposition=_disposition(root["disposition"]),
        artifact_class=_bounded_text(root["artifactClass"], "artifactClass", 128),
        path_prefixes=tuple(selectors["pathPrefixes"]),
        exact_paths=frozenset(selectors["exactPaths"]),
        suffixes=suffixes,
        basename_globs=tuple(selectors["basenameGlobs"]),
        directory_names=frozenset(selectors["directoryNames"]),
    )


def _strict_object(
    value: Any,
    *,
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PolicyError(f"{context} must be an object")
    keys = set(value)
    allowed = required | (optional or set())
    missing = required - keys
    unknown = keys - allowed
    if missing:
        raise PolicyError(f"{context} is missing fields: {sorted(missing)}")
    if unknown:
        raise PolicyError(f"{context} has unknown fields: {sorted(unknown)}")
    return value


def _bounded_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise PolicyError(f"{name} must be a non-empty string <= {maximum} chars")
    if "\x00" in value:
        raise PolicyError(f"{name} contains NUL")
    return value


def _bounded_integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise PolicyError(f"{name} is outside [{minimum}, {maximum}]")
    return value


def _text_list(value: Any, name: str, maximum: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise PolicyError(f"{name} must be a non-empty array when present")
    values = tuple(_bounded_text(item, name, maximum) for item in value)
    if len(values) != len(set(values)):
        raise PolicyError(f"{name} must not contain duplicates")
    return values


def _path_list(value: Any, name: str) -> tuple[str, ...]:
    values = _text_list(value, name, 4096)
    for item in values:
        path = PurePosixPath(item)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise PolicyError(f"{name} contains an unsafe relative path")
        if "\\" in item:
            raise PolicyError(f"{name} paths must use POSIX separators")
    return values


def _disposition(value: Any) -> str:
    if not isinstance(value, str) or value not in _ALLOWED_DISPOSITIONS:
        raise PolicyError("Unsupported source-export disposition")
    return value


def _read_regular_path(path: Path, *, max_bytes: int | None = None) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = _StatFingerprint.from_stat(os.fstat(descriptor))
        if not stat.S_ISREG(before.mode):
            raise PolicyError("Input must be a regular file")
        if max_bytes is not None and before.size > max_bytes:
            raise SourceLimitError("Input file exceeds its byte limit")
        data = bytearray()
        while True:
            chunk = os.read(descriptor, _READ_CHUNK)
            if not chunk:
                break
            data.extend(chunk)
            if max_bytes is not None and len(data) > max_bytes:
                raise SourceLimitError("Input file exceeded its byte limit")
        after = _StatFingerprint.from_stat(os.fstat(descriptor))
        if before != after or len(data) != before.size:
            raise PolicyError("Policy changed while reading")
        return bytes(data)
    finally:
        os.close(descriptor)


def _validated_directory(path: Path, label: str) -> tuple[Path, _StatFingerprint]:
    absolute = path.absolute()
    try:
        before = _StatFingerprint.from_stat(absolute.lstat())
    except FileNotFoundError as error:
        raise SourceSafetyError(f"{label} does not exist") from error
    if stat.S_ISLNK(before.mode) or not stat.S_ISDIR(before.mode):
        raise SourceSafetyError(f"{label} must be a non-symlink directory")
    resolved = absolute.resolve(strict=True)
    after = _StatFingerprint.from_stat(absolute.lstat())
    resolved_value = _StatFingerprint.from_stat(resolved.lstat())
    if before != after or before != resolved_value:
        raise SourceMutationError(f"{label} identity changed during validation")
    return resolved, before


def _prospective_path(path: Path) -> Path:
    absolute = path.absolute()
    current = absolute
    while not current.exists():
        if current.parent == current:
            raise SourceSafetyError("Destination has no existing parent")
        current = current.parent
    current_stat = current.lstat()
    if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
        raise SourceSafetyError("Destination parent must be a non-symlink directory")
    parent = current.resolve(strict=True)
    suffix = absolute.relative_to(current)
    return parent.joinpath(suffix)


def _require_separate_trees(source: Path, destination: Path) -> None:
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        raise SourceSafetyError("Destination must not be inside source root")
    try:
        source.relative_to(destination)
    except ValueError:
        return
    raise SourceSafetyError("Source root must not be inside destination")


def _directory_entries(
    directory_fd: int,
) -> tuple[
    tuple[tuple[str, _StatFingerprint, str], ...],
    _DirectorySignature,
]:
    values: list[tuple[str, _StatFingerprint, str]] = []
    with os.scandir(directory_fd) as iterator:
        entries = sorted(iterator, key=lambda item: item.name)
    for entry in entries:
        if "\x00" in entry.name or "\\" in entry.name or entry.name in (".", ".."):
            raise SourceSafetyError("Source contains an unsafe directory entry")
        try:
            entry.name.encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise SourceSafetyError("Source paths must be valid UTF-8") from error
        value = entry.stat(follow_symlinks=False)
        fingerprint = _StatFingerprint.from_stat(value)
        mode = value.st_mode
        if stat.S_ISLNK(mode):
            entry_type = "symlink"
        elif stat.S_ISDIR(mode):
            entry_type = "directory"
        elif stat.S_ISREG(mode):
            entry_type = "file"
        else:
            entry_type = "special"
        values.append((entry.name, fingerprint, entry_type))
    result = tuple(values)
    signature = tuple(
        (
            name,
            fingerprint.device,
            fingerprint.inode,
            fingerprint.mode,
            entry_type,
        )
        for name, fingerprint, entry_type in result
    )
    return result, signature


def _open_directory_at(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    return os.open(name, flags, dir_fd=parent_fd)


def _open_relative_directory(root_fd: int, parts: Sequence[str]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            next_descriptor = _open_directory_at(current, part)
            os.close(current)
            current = next_descriptor
        return current
    except BaseException:
        os.close(current)
        raise


def _open_relative_file(root_fd: int, parts: Sequence[str]) -> int:
    if not parts:
        raise SourceSafetyError("A file path cannot be empty")
    parent = _open_relative_directory(root_fd, parts[:-1])
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        return os.open(parts[-1], flags, dir_fd=parent)
    finally:
        os.close(parent)


def _validate_content_signature(
    *,
    relative_path: str,
    artifact_class: str,
    prefix: bytes,
) -> tuple[tuple[str, ...], bool]:
    if artifact_class != "workbook":
        return (), True
    suffix = PurePosixPath(relative_path).suffix.lower()
    is_zip = prefix[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    is_ole = prefix.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
    if suffix == ".xls":
        if is_ole:
            return (), True
        if is_zip:
            return ("WORKBOOK_EXTENSION_FORMAT_MISMATCH",), True
        return ("WORKBOOK_SIGNATURE_MISMATCH",), False
    if suffix in (".xlsx", ".xlsm", ".xlsb", ".ods") and is_zip:
        return (), True
    return ("WORKBOOK_SIGNATURE_MISMATCH",), False


def _discover_embedded_records(
    *,
    relative_path: str,
    artifact_class: str,
    data: bytes | None,
    byte_length: int,
    limits: PolicyLimits,
) -> tuple[tuple[EmbeddedRecord, ...], tuple[str, ...]]:
    lower = relative_path.lower()
    if not (lower.endswith(".json") or lower.endswith(".jsonl")):
        return (), ()
    if data is None:
        if byte_length > limits.max_json_scan_bytes:
            return (), ("EMBEDDED_SCAN_SKIPPED_SIZE",)
        return (), ()
    records: list[EmbeddedRecord] = []
    warnings: list[str] = []
    if lower.endswith(".jsonl"):
        for line_number, line in enumerate(data.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = _strict_json_loads(line)
            except (UnicodeDecodeError, ValueError, RecursionError):
                warnings.append("JSONL_PARSE_FAILED")
                break
            _walk_embedded(
                value,
                f"/lines/{line_number}",
                records,
                warnings,
                limits,
            )
            if len(records) >= limits.max_embedded_records_per_file:
                break
    else:
        try:
            value = _strict_json_loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return (), ("JSON_PARSE_FAILED",)
        if (
            artifact_class == "recipe-evidence"
            and limits.max_embedded_records_per_file > 0
        ):
            records.append(
                EmbeddedRecord(
                    kind="recipe-document",
                    pointer="",
                    value_type=_json_type(value),
                )
            )
        _walk_embedded(value, "", records, warnings, limits)
    unique = {
        (record.kind, record.pointer, record.value_type): record for record in records
    }
    ordered = tuple(unique[key] for key in sorted(unique))
    return ordered, tuple(sorted(set(warnings)))


def _strict_json_loads(value: str | bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise _DuplicateJsonKey(f"Duplicate JSON key: {key}")
            result[key] = item
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON constant: {value}")

    return json.loads(
        value,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


def _walk_embedded(
    value: Any,
    pointer: str,
    records: list[EmbeddedRecord],
    warnings: list[str],
    limits: PolicyLimits,
) -> None:
    stack: list[tuple[Any, str, int]] = [(value, pointer, 0)]
    while stack:
        current, current_pointer, depth = stack.pop()
        if depth > limits.max_json_depth:
            warnings.append("EMBEDDED_SCAN_DEPTH_LIMIT")
            continue
        if len(records) >= limits.max_embedded_records_per_file:
            warnings.append("EMBEDDED_SCAN_RECORD_LIMIT")
            return
        if isinstance(current, dict):
            for key in sorted(current, reverse=True):
                child = current[key]
                escaped = key.replace("~", "~0").replace("/", "~1")
                child_pointer = f"{current_pointer}/{escaped}"
                if len(child_pointer) > 8192:
                    warnings.append("EMBEDDED_SCAN_POINTER_LIMIT")
                    continue
                if key in _RECIPE_KEYS:
                    records.append(
                        EmbeddedRecord(
                            kind="recipe-candidate",
                            pointer=child_pointer,
                            value_type=_json_type(child),
                        )
                    )
                elif key in _PROMPT_KEYS:
                    records.append(
                        EmbeddedRecord(
                            kind="prompt-evidence",
                            pointer=child_pointer,
                            value_type=_json_type(child),
                        )
                    )
                elif key in _RESPONSE_KEYS:
                    records.append(
                        EmbeddedRecord(
                            kind="provider-response-evidence",
                            pointer=child_pointer,
                            value_type=_json_type(child),
                        )
                    )
                if len(records) >= limits.max_embedded_records_per_file:
                    warnings.append("EMBEDDED_SCAN_RECORD_LIMIT")
                    return
                if isinstance(child, dict | list):
                    stack.append((child, child_pointer, depth + 1))
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                child = current[index]
                child_pointer = f"{current_pointer}/{index}"
                if len(child_pointer) > 8192:
                    warnings.append("EMBEDDED_SCAN_POINTER_LIMIT")
                    continue
                if isinstance(child, dict | list):
                    stack.append((child, child_pointer, depth + 1))


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int | float):
        return "number"
    return "unknown"


def _git_evidence(source_root: Path, items: Sequence[ExportItem]) -> _GitEvidence:
    head = _run_git(source_root, ("rev-parse", "HEAD"), allow_not_repository=True)
    if head is None:
        git_marker = source_root / ".git"
        if git_marker.exists() or git_marker.is_symlink():
            raise SourceExportError("Git metadata exists but cannot be inspected")
        return _GitEvidence(
            wire={
                "available": False,
                "head": None,
                "tree": None,
                "trackedDirty": None,
                "trackedDirtyDigest": None,
            },
            states={item.relative_path: "unknown" for item in items},
        )
    tree = _run_git(source_root, ("rev-parse", "HEAD^{tree}"))
    tracked_raw = _run_git(source_root, ("ls-files", "-z"), binary=True)
    assert isinstance(tracked_raw, bytes)
    tracked = set(_nul_paths(tracked_raw))
    paths = [item.relative_path for item in items]
    check_input = b"".join(path.encode("utf-8") + b"\x00" for path in paths)
    ignored_raw = _run_git(
        source_root,
        ("check-ignore", "--stdin", "-z"),
        binary=True,
        input_data=check_input,
        allowed_codes=(0, 1),
    )
    assert isinstance(ignored_raw, bytes)
    ignored = set(_nul_paths(ignored_raw))
    states = {
        path: (
            "tracked"
            if path in tracked
            else "ignored"
            if path in ignored
            else "untracked"
        )
        for path in paths
    }
    dirty_raw = _run_git(
        source_root,
        ("status", "--porcelain=v1", "--untracked-files=no", "-z"),
        binary=True,
    )
    assert isinstance(dirty_raw, bytes)
    dirty_digest = sha256_digest(dirty_raw)
    return _GitEvidence(
        wire={
            "available": True,
            "head": str(head).strip(),
            "tree": str(tree).strip(),
            "trackedDirty": bool(dirty_raw),
            "trackedDirtyDigest": dirty_digest,
        },
        states=states,
    )


def _run_git(
    source_root: Path,
    arguments: tuple[str, ...],
    *,
    binary: bool = False,
    input_data: bytes | None = None,
    allowed_codes: tuple[int, ...] = (0,),
    allow_not_repository: bool = False,
) -> str | bytes | None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    result = subprocess.run(
        ["git", *arguments],
        cwd=source_root,
        env=environment,
        input=input_data,
        capture_output=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if len(result.stdout) > _MAX_GIT_OUTPUT_BYTES or len(result.stderr) > 1024 * 1024:
        raise SourceLimitError("Git evidence output exceeded its bound")
    if allow_not_repository and result.returncode != 0:
        return None
    if result.returncode not in allowed_codes:
        message = result.stderr.decode("utf-8", errors="replace")[:1024]
        raise SourceExportError(
            f"Git evidence command failed ({result.returncode}): {message}"
        )
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", errors="strict")


def _nul_paths(data: bytes) -> tuple[str, ...]:
    if not data:
        return ()
    return tuple(
        part.decode("utf-8", errors="strict")
        for part in data.rstrip(b"\x00").split(b"\x00")
        if part
    )


def _assign_git_states(
    items: Sequence[ExportItem], states: Mapping[str, str]
) -> tuple[ExportItem, ...]:
    return tuple(
        replace(item, git_state=states.get(item.relative_path, "unknown"))
        for item in items
    )


def _assign_duplicate_aliases(items: Sequence[ExportItem]) -> tuple[ExportItem, ...]:
    paths_by_digest: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item.disposition == "import" and item.content_digest is not None:
            paths_by_digest[item.content_digest].append(item.relative_path)
    aliases = {path for paths in paths_by_digest.values() for path in sorted(paths)[1:]}
    return tuple(
        replace(item, disposition="duplicate-alias")
        if item.relative_path in aliases
        else item
        for item in items
    )


def _inventory_summary(items: Sequence[ExportItem]) -> dict[str, Any]:
    dispositions = Counter(item.disposition for item in items)
    artifact_classes = Counter(item.artifact_class for item in items)
    git_states = Counter(item.git_state for item in items)
    bytes_by_disposition: Counter[str] = Counter()
    unique_import: dict[str, int] = {}
    warning_count = 0
    embedded_count = 0
    for item in items:
        bytes_by_disposition[item.disposition] += item.byte_length
        warning_count += len(item.warnings)
        embedded_count += len(item.embedded_records)
        if (
            item.disposition in ("import", "duplicate-alias")
            and item.content_digest is not None
        ):
            unique_import.setdefault(item.content_digest, item.byte_length)
    return {
        "itemCount": len(items),
        "fileCount": sum(item.entry_type == "file" for item in items),
        "excludedSubtreeCount": sum(
            item.entry_type == "excluded-subtree" for item in items
        ),
        "excludedSymlinkCount": sum(
            item.entry_type == "excluded-symlink" for item in items
        ),
        "dispositions": dict(sorted(dispositions.items())),
        "artifactClasses": dict(sorted(artifact_classes.items())),
        "gitStates": dict(sorted(git_states.items())),
        "bytesByDisposition": dict(sorted(bytes_by_disposition.items())),
        "uniqueImportObjects": len(unique_import),
        "uniqueImportBytes": sum(unique_import.values()),
        "embeddedRecordCount": embedded_count,
        "warningCount": warning_count,
    }


def _default_storage_probe(destination: Path) -> StorageProbe:
    current = destination
    while not current.exists():
        current = current.parent
    usage = shutil.disk_usage(current)
    return StorageProbe(
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        device_id=current.stat().st_dev,
    )


def _storage_assessment(
    *, destination_id: str, unique_import_bytes: int, probe: StorageProbe
) -> dict[str, Any]:
    if probe.total_bytes <= 0:
        raise SourceExportError("Storage total bytes must be positive")
    if min(probe.used_bytes, probe.free_bytes) < 0:
        raise SourceExportError("Storage byte counts must be non-negative")
    if probe.used_bytes + probe.free_bytes > probe.total_bytes:
        raise SourceExportError("Storage byte counts are internally inconsistent")
    required_free = unique_import_bytes * 2 + 10 * _GIB
    projected_used = probe.used_bytes + unique_import_bytes
    projected_basis_points = min(
        10000,
        (projected_used * 10000 + probe.total_bytes - 1) // probe.total_bytes,
    )
    free_pass = probe.free_bytes >= required_free
    utilization_pass = projected_basis_points <= 8500
    return {
        "schemaVersion": "tidy.storage-assessment/v1",
        "destinationId": destination_id,
        "deviceId": probe.device_id,
        "totalBytes": probe.total_bytes,
        "usedBytes": probe.used_bytes,
        "freeBytes": probe.free_bytes,
        "estimatedUniqueImportBytes": unique_import_bytes,
        "requiredFreeBytes": required_free,
        "projectedUtilizationBasisPoints": projected_basis_points,
        "maximumUtilizationBasisPoints": 8500,
        "freeSpacePasses": free_pass,
        "utilizationPasses": utilization_pass,
        "passes": free_pass and utilization_pass,
    }


def _exporter_source_digest() -> str:
    directory = Path(__file__).parent
    project_root = directory.parents[1]
    paths = [
        directory / "artifacts.py",
        directory / "source_export.py",
        directory / "source_export_cli.py",
        *sorted(
            (project_root / "contracts/migration/v1").glob("*.schema.json"),
            key=lambda path: path.name,
        ),
    ]
    files = []
    for path in paths:
        content = _read_regular_path(path, max_bytes=16 * 1024 * 1024)
        files.append(
            {
                "relativePath": path.relative_to(project_root).as_posix(),
                "contentDigest": sha256_digest(content),
            }
        )
    return domain_digest(
        "tidy.source-exporter-source-closure/v1",
        {"files": files},
    )


def _utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("frozen_at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("frozen_at must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
