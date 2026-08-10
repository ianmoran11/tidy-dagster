"""Fixture-only, no-copy source-code closure snapshots for Phase C scaffolding."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import domain_digest, sha256_digest

_SCHEMA_VERSION = "tidy.source-code-export-snapshot/v1"
_EXPORTER_VERSION = "tidy-source-code-fixture-exporter/v1"
_FIXTURE_SOURCE_SYSTEM = "phase-c-fixture"
_MAX_FILES = 100
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
_GIT_TIMEOUT_SECONDS = 30
_READ_CHUNK = 1024 * 1024
_ROLES = frozenset(("source", "fixture", "license", "manifest", "lockfile", "notice"))


class SourceCodeSnapshotError(RuntimeError):
    """The source-code closure could not be frozen or verified safely."""


class SourceCodeSnapshotAuthorizationError(SourceCodeSnapshotError):
    """The requested closure exceeds fixture-only authority."""


class SourceCodeSnapshotMutation(SourceCodeSnapshotError):
    """The source repository changed while the closure was observed."""


@dataclass(frozen=True)
class FixtureSourceCodeAuthorization:
    source_device_id: int
    source_root_inode: int
    max_files: int = _MAX_FILES
    max_total_bytes: int = _MAX_TOTAL_BYTES
    mode: str = "phase-c-fixture-only"

    def __post_init__(self) -> None:
        if not 1 <= self.max_files <= _MAX_FILES:
            raise ValueError("max_files exceeds the fixture-only bound")
        if not 1 <= self.max_total_bytes <= _MAX_TOTAL_BYTES:
            raise ValueError("max_total_bytes exceeds the fixture-only bound")
        if self.mode != "phase-c-fixture-only":
            raise ValueError("unsupported source-code authorization mode")

    @classmethod
    def create(
        cls,
        *,
        source_root: Path,
        max_files: int = _MAX_FILES,
        max_total_bytes: int = _MAX_TOTAL_BYTES,
    ) -> FixtureSourceCodeAuthorization:
        root = _validated_directory(source_root)
        info = root.lstat()
        return cls(
            source_device_id=info.st_dev,
            source_root_inode=info.st_ino,
            max_files=max_files,
            max_total_bytes=max_total_bytes,
        )

    def validate(self, source_root: Path, source_system: str) -> Path:
        if source_system != _FIXTURE_SOURCE_SYSTEM:
            raise SourceCodeSnapshotAuthorizationError(
                "Fixture authority cannot snapshot a non-fixture source system"
            )
        root = _validated_directory(source_root)
        info = root.lstat()
        if (info.st_dev, info.st_ino) != (
            self.source_device_id,
            self.source_root_inode,
        ):
            raise SourceCodeSnapshotAuthorizationError(
                "Source-code authority binds a different root"
            )
        return root


def freeze_fixture_source_code_snapshot(
    *,
    source_root: Path,
    source_root_id: str,
    closure_id: str,
    selected_roles: Mapping[str, str],
    license_relative_path: str,
    license_spdx_id: str,
    frozen_at: str,
    authorization: FixtureSourceCodeAuthorization,
    source_system: str = _FIXTURE_SOURCE_SYSTEM,
    fault_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Hash an explicit tracked fixture closure; copy no source bytes."""

    root = authorization.validate(source_root, source_system)
    _require_text(source_root_id, "source_root_id", 256)
    _require_text(closure_id, "closure_id", 256)
    _require_text(license_spdx_id, "license_spdx_id", 64)
    _require_utc_timestamp(frozen_at)
    selection = _validated_selection(selected_roles, authorization.max_files)
    if license_relative_path not in selection:
        raise SourceCodeSnapshotError("Selected closure omits its license file")
    if selection[license_relative_path] != "license":
        raise SourceCodeSnapshotError("License file must have role=license")

    root_before = _root_identity(root)
    git_before, tracked = _git_evidence(root)
    if not set(selection).issubset(tracked):
        missing = sorted(set(selection).difference(tracked))
        raise SourceCodeSnapshotError(
            f"Selected closure contains untracked paths: {missing[:3]}"
        )

    descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        items = _read_items(
            descriptor,
            selection,
            max_total_bytes=authorization.max_total_bytes,
            fault_injector=fault_injector,
        )
        second = _read_items(
            descriptor,
            selection,
            max_total_bytes=authorization.max_total_bytes,
            fault_injector=None,
        )
        if second != items:
            raise SourceCodeSnapshotMutation(
                "Selected source bytes changed during closure freeze"
            )
        descriptor_info = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    git_after, tracked_after = _git_evidence(root)
    root_after = _root_identity(root)
    if (
        root_before != root_after
        or _stat_identity(descriptor_info) != root_after
        or git_before != git_after
        or tracked != tracked_after
    ):
        raise SourceCodeSnapshotMutation(
            "Source repository changed during closure freeze"
        )

    item_manifest_digest = domain_digest("tidy.source-code-export-items/v1", items)
    license_item = next(
        item for item in items if item["relativePath"] == license_relative_path
    )
    semantic = {
        "schemaVersion": _SCHEMA_VERSION,
        "completionStatus": "complete",
        "frozenAt": frozen_at,
        "source": {
            "sourceSystem": source_system,
            "sourceRootId": source_root_id,
            "filesystem": {
                "deviceId": root_before[0],
                "rootInode": root_before[1],
                "rootMode": root_before[2],
            },
            "git": git_before,
        },
        "selection": {"closureId": closure_id, "items": items},
        "license": {
            "spdxId": license_spdx_id,
            "contentDigest": license_item["contentDigest"],
        },
        "exporter": {
            "version": _EXPORTER_VERSION,
            "sourceDigest": _exporter_source_digest(),
            "canonicalizationAlgorithm": "tidy-python-sorted-json-v1",
        },
        "itemManifestDigest": item_manifest_digest,
    }
    return {
        **semantic,
        "snapshotDigest": domain_digest(_SCHEMA_VERSION, semantic),
    }


def verify_fixture_source_code_snapshot(
    *,
    snapshot: Mapping[str, Any],
    source_root: Path,
    authorization: FixtureSourceCodeAuthorization,
) -> None:
    """Rebuild a fixture snapshot from source and require byte-for-byte equality."""

    if snapshot.get("schemaVersion") != _SCHEMA_VERSION:
        raise SourceCodeSnapshotError("Unsupported source-code snapshot version")
    source = snapshot.get("source")
    selection = snapshot.get("selection")
    license = snapshot.get("license")
    if not all(isinstance(value, Mapping) for value in (source, selection, license)):
        raise SourceCodeSnapshotError("Source-code snapshot fields are invalid")
    items = selection.get("items")
    if not isinstance(items, list):
        raise SourceCodeSnapshotError("Source-code snapshot items are invalid")
    selected_roles: dict[str, str] = {}
    item_digests: dict[str, str] = {}
    required_item_fields = {
        "relativePath",
        "role",
        "sourceMode",
        "byteLength",
        "contentDigest",
    }
    for item in items:
        if not isinstance(item, Mapping) or set(item) != required_item_fields:
            raise SourceCodeSnapshotError("Source-code snapshot item is invalid")
        path = item.get("relativePath")
        role = item.get("role")
        content_digest = item.get("contentDigest")
        if (
            not isinstance(path, str)
            or not isinstance(role, str)
            or not _is_digest(content_digest)
            or path in selected_roles
        ):
            raise SourceCodeSnapshotError("Source-code snapshot selection is invalid")
        selected_roles[path] = role
        item_digests[path] = content_digest
    license_digest = license.get("contentDigest")
    license_paths = [
        path
        for path, role in selected_roles.items()
        if role == "license" and item_digests[path] == license_digest
    ]
    if len(license_paths) != 1:
        raise SourceCodeSnapshotError("Source-code snapshot license is ambiguous")
    rebuilt = freeze_fixture_source_code_snapshot(
        source_root=source_root,
        source_root_id=source.get("sourceRootId"),
        closure_id=selection.get("closureId"),
        selected_roles=selected_roles,
        license_relative_path=license_paths[0],
        license_spdx_id=license.get("spdxId"),
        frozen_at=snapshot.get("frozenAt"),
        authorization=authorization,
        source_system=source.get("sourceSystem"),
    )
    if rebuilt != dict(snapshot):
        raise SourceCodeSnapshotMutation(
            "Source-code snapshot differs from the current explicit closure"
        )


def _validated_selection(
    selected_roles: Mapping[str, str], max_files: int
) -> dict[str, str]:
    if not selected_roles or len(selected_roles) > max_files:
        raise SourceCodeSnapshotAuthorizationError(
            "Selected closure exceeds its fixture file bound"
        )
    result: dict[str, str] = {}
    for relative_path, role in selected_roles.items():
        path = _safe_relative_path(relative_path)
        if role not in _ROLES:
            raise SourceCodeSnapshotError(f"Unsupported source-code role {role!r}")
        if path in result:
            raise SourceCodeSnapshotError("Selected closure contains duplicate paths")
        result[path] = role
    return dict(sorted(result.items()))


def _read_items(
    root_descriptor: int,
    selection: Mapping[str, str],
    *,
    max_total_bytes: int,
    fault_injector: Callable[[str], None] | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    total = 0
    for relative_path, role in selection.items():
        descriptor = _open_relative_file(root_descriptor, relative_path)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_FILE_BYTES:
                raise SourceCodeSnapshotError(
                    f"Selected source is not a bounded regular file: {relative_path}"
                )
            digest = hashlib.sha256()
            length = 0
            while True:
                chunk = os.read(descriptor, _READ_CHUNK)
                if not chunk:
                    break
                length += len(chunk)
                total += len(chunk)
                if length > _MAX_FILE_BYTES or total > max_total_bytes:
                    raise SourceCodeSnapshotAuthorizationError(
                        "Selected closure exceeds its fixture byte bound"
                    )
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (
                _stat_identity(before) != _stat_identity(after)
                or length != before.st_size
            ):
                raise SourceCodeSnapshotMutation(
                    f"Selected source changed while reading: {relative_path}"
                )
        finally:
            os.close(descriptor)
        items.append(
            {
                "relativePath": relative_path,
                "role": role,
                "sourceMode": before.st_mode,
                "byteLength": length,
                "contentDigest": f"sha256:{digest.hexdigest()}",
            }
        )
        if fault_injector is not None:
            fault_injector(f"after-item:{relative_path}")
    return items


def _git_evidence(root: Path) -> tuple[dict[str, Any], frozenset[str]]:
    head = _git(root, ("rev-parse", "HEAD")).decode("ascii").strip()
    tree = _git(root, ("rev-parse", "HEAD^{tree}")).decode("ascii").strip()
    if not _is_git_object(head) or not _is_git_object(tree):
        raise SourceCodeSnapshotError("Git HEAD or tree identity is invalid")
    tracked_raw = _git(root, ("ls-files", "-z"))
    tracked = frozenset(_nul_paths(tracked_raw))
    dirty_raw = _git(root, ("status", "--porcelain=v1", "--untracked-files=no", "-z"))
    tracked_diff = _git(root, ("diff", "--no-ext-diff", "--binary", "HEAD", "--"))
    dirty_digest = domain_digest(
        "tidy.source-code-tracked-dirty/v1",
        {
            "statusDigest": sha256_digest(dirty_raw),
            "diffDigest": sha256_digest(tracked_diff),
        },
    )
    return (
        {
            "available": True,
            "head": head,
            "tree": tree,
            "trackedDirty": bool(dirty_raw),
            "trackedDirtyDigest": dirty_digest,
        },
        tracked,
    )


def _git(root: Path, arguments: Sequence[str]) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise SourceCodeSnapshotError("Git executable is unavailable")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    result = subprocess.run(
        [executable, *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if len(result.stdout) > _MAX_GIT_OUTPUT_BYTES or len(result.stderr) > 1024 * 1024:
        raise SourceCodeSnapshotError("Git evidence exceeds its output bound")
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace")[:1024]
        raise SourceCodeSnapshotError(
            f"Git evidence command failed ({result.returncode}): {message}"
        )
    return result.stdout


def _nul_paths(value: bytes) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        part.decode("utf-8", errors="strict")
        for part in value.rstrip(b"\x00").split(b"\x00")
        if part
    )


def _open_relative_file(root_descriptor: int, relative_path: str) -> int:
    parts = relative_path.split("/")
    parent = os.dup(root_descriptor)
    try:
        for part in parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
            os.close(parent)
            parent = child
        return os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
    except OSError as error:
        raise SourceCodeSnapshotError(
            f"Selected source could not be opened safely: {relative_path}"
        ) from error
    finally:
        os.close(parent)


def _safe_relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
    ):
        raise SourceCodeSnapshotError(f"Unsafe source-code path {value!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise SourceCodeSnapshotError(f"Unsafe source-code path {value!r}")
    if PurePosixPath(value).as_posix() != value:
        raise SourceCodeSnapshotError(f"Non-canonical source-code path {value!r}")
    return value


def _validated_directory(path: Path) -> Path:
    absolute = path.absolute()
    before = absolute.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise SourceCodeSnapshotError(
            "Source-code root must be a non-symlink directory"
        )
    resolved = absolute.resolve(strict=True)
    after = absolute.lstat()
    resolved_info = resolved.lstat()
    if _stat_identity(before) != _stat_identity(after) or _stat_identity(
        before
    ) != _stat_identity(resolved_info):
        raise SourceCodeSnapshotMutation("Source-code root identity changed")
    return resolved


def _root_identity(path: Path) -> tuple[int, int, int, int, int, int]:
    return _stat_identity(path.lstat())


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _is_git_object(value: str) -> bool:
    return len(value) in (40, 64) and all(
        character in "0123456789abcdef" for character in value
    )


def _require_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SourceCodeSnapshotError(f"{label} is invalid")
    return value


def _require_utc_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise SourceCodeSnapshotError("frozen_at must be a canonical UTC timestamp")
    return value


def _exporter_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = (
        project / "pyproject.toml",
        project / "uv.lock",
        project / "src/tidy_orchestrator/artifacts.py",
        Path(__file__),
        project / "contracts/migration/v1/source-code-snapshot.schema.json",
    )

    def capture() -> list[dict[str, str]]:
        return [
            {
                "relativePath": path.relative_to(project).as_posix(),
                "contentDigest": sha256_digest(path.read_bytes()),
            }
            for path in paths
        ]

    files = capture()
    if capture() != files:
        raise SourceCodeSnapshotMutation(
            "Source-code exporter closure changed while hashing"
        )
    return domain_digest(
        "tidy.source-code-exporter-closure/v1",
        {
            "files": files,
            "runtime": {
                "pythonImplementation": platform.python_implementation(),
                "pythonVersion": platform.python_version(),
            },
        },
    )
