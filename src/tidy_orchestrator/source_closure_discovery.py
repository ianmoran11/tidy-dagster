"""Read-only, no-copy discovery of exact TypeScript source closures."""

from __future__ import annotations

import contextlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .source_export import verify_export_wire

_SCHEMA_VERSION = "tidy.source-closure-discovery/v1"
_REQUEST_VERSION = "tidy.source-closure-discovery-request/v1"
_PRODUCER_VERSION = "tidy-source-closure-discovery/v1"
_ALGORITHM = "literal-typescript-import-closure-v1"
_MAX_FILES = 1_000
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_MAX_FILE_BYTES = 8 * 1024 * 1024
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_MAX_GIT_OUTPUT_BYTES = 64 * 1024 * 1024
_MAX_JSON_DEPTH = 128
_MAX_JSON_NODES = 10_000_000
_GIT_TIMEOUT_SECONDS = 60
_READ_CHUNK = 1024 * 1024
_ROLES = frozenset(("source", "fixture", "license", "manifest", "lockfile", "notice"))
_SOURCE_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".json")
_IMPORT_PATTERN = re.compile(
    r"""
    (?:
      \b(?:import|export)\s+(?:type\s+)?(?:[^\"';]*?\s+from\s+)?
      |\b(?:import|require)\s*\(\s*
    )
    [\"']([^\"']+)[\"']
    """,
    re.MULTILINE | re.VERBOSE,
)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class SourceClosureDiscoveryError(RuntimeError):
    """The requested closure could not be discovered without ambiguity."""


class SourceClosureSourceMismatch(SourceClosureDiscoveryError):
    """Observed source bytes did not match their frozen authority."""


def discover_source_closure(request: Mapping[str, Any]) -> dict[str, Any]:
    """Discover an exact import closure and return hashes without source bytes."""

    producer_before = _producer_source_digest()
    root = _strict_mapping(request, "request")
    _require_exact_keys(
        root,
        {
            "schemaVersion",
            "closureId",
            "frozenAt",
            "maxFiles",
            "maxTotalBytes",
            "sources",
        },
        "request",
    )
    if root["schemaVersion"] != _REQUEST_VERSION:
        raise SourceClosureDiscoveryError("Unsupported discovery request version")
    closure_id = _require_text(root["closureId"], "closureId", 256)
    frozen_at = _require_utc_timestamp(root["frozenAt"])
    max_files = _bounded_int(root["maxFiles"], "maxFiles", 1, _MAX_FILES)
    max_total_bytes = _bounded_int(
        root["maxTotalBytes"], "maxTotalBytes", 1, _MAX_TOTAL_BYTES
    )
    source_requests = root["sources"]
    if not isinstance(source_requests, list) or len(source_requests) != 2:
        raise SourceClosureDiscoveryError(
            "Exactly one TidyCell and one Tidybank source are required"
        )

    sources: list[dict[str, Any]] = []
    seen_systems: set[str] = set()
    for value in source_requests:
        source_request = _strict_mapping(value, "source request")
        source_system = _require_text(
            source_request.get("sourceSystem"), "sourceSystem", 64
        )
        if source_system in seen_systems:
            raise SourceClosureDiscoveryError("Duplicate source system")
        seen_systems.add(source_system)
        if source_request.get("readMode") == "phase-a-filesystem":
            source = _discover_phase_a_source(
                source_request,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
        elif source_request.get("readMode") == "git-object":
            source = _discover_git_source(
                source_request,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
        else:
            raise SourceClosureDiscoveryError("Unsupported source read mode")
        sources.append(source)
    if seen_systems != {"tidycell", "tidybank"}:
        raise SourceClosureDiscoveryError(
            "Source systems must be tidycell and tidybank"
        )
    sources.sort(key=lambda value: value["sourceSystem"])

    item_count = sum(source["itemCount"] for source in sources)
    total_bytes = sum(source["totalBytes"] for source in sources)
    if item_count > max_files or total_bytes > max_total_bytes:
        raise SourceClosureDiscoveryError(
            "Combined source closure exceeds request bounds"
        )
    producer_after = _producer_source_digest()
    if producer_before != producer_after:
        raise SourceClosureSourceMismatch(
            "Source-closure producer changed during discovery"
        )
    semantic = {
        "schemaVersion": _SCHEMA_VERSION,
        "completionStatus": "complete-no-copy",
        "closureId": closure_id,
        "frozenAt": frozen_at,
        "selectionPolicy": {
            "algorithm": _ALGORITHM,
            "sourceBytesCopied": False,
            "runtimeSiblingDependencyAllowed": False,
            "unresolvedRelativeImportCount": 0,
        },
        "sources": sources,
        "totals": {
            "sourceCount": 2,
            "itemCount": item_count,
            "byteLength": total_bytes,
        },
        "producer": {
            "version": _PRODUCER_VERSION,
            "sourceDigest": producer_after,
            "canonicalizationAlgorithm": "tidy-python-sorted-json-v1",
        },
    }
    return {
        **semantic,
        "manifestDigest": domain_digest(_SCHEMA_VERSION, semantic),
    }


def verify_source_closure(
    *, manifest: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    rebuilt = discover_source_closure(request)
    if dict(manifest) != rebuilt:
        raise SourceClosureSourceMismatch(
            "Source closure manifest differs from current authorized observations"
        )


def load_discovery_request(path: Path) -> dict[str, Any]:
    return _read_json_file(path, _MAX_CONFIG_BYTES, "discovery request")


def load_discovery_manifest(path: Path) -> dict[str, Any]:
    return _read_json_file(path, _MAX_CONFIG_BYTES * 8, "discovery manifest")


def _discover_phase_a_source(
    request: Mapping[str, Any], *, max_files: int, max_total_bytes: int
) -> dict[str, Any]:
    _require_exact_keys(
        request,
        {
            "sourceSystem",
            "readMode",
            "sourceRoot",
            "sourceRootId",
            "phaseASnapshotPath",
            "expectedSnapshotDigest",
            "entrypoints",
            "metadata",
        },
        "phase-a source request",
    )
    if request["sourceSystem"] != "tidycell":
        raise SourceClosureDiscoveryError(
            "phase-a-filesystem mode is restricted to tidycell"
        )
    source_root = _validated_directory(Path(request["sourceRoot"]), "sourceRoot")
    snapshot = _read_json_file(
        Path(request["phaseASnapshotPath"]),
        _MAX_SNAPSHOT_BYTES,
        "Phase A snapshot",
    )
    snapshot_digest = verify_export_wire(snapshot)
    expected_snapshot_digest = _require_digest(request["expectedSnapshotDigest"])
    if snapshot_digest != expected_snapshot_digest:
        raise SourceClosureSourceMismatch("Phase A snapshot identity differs")
    source = snapshot["inventory"]["source"]
    source_root_id = _require_text(request["sourceRootId"], "sourceRootId", 256)
    if (
        source.get("sourceSystem") != "tidycell"
        or source.get("sourceRootId") != source_root_id
    ):
        raise SourceClosureSourceMismatch("Phase A source identity differs")
    git = source.get("git")
    if not isinstance(git, dict) or git.get("available") is not True:
        raise SourceClosureDiscoveryError("Phase A Git evidence is unavailable")
    current_head = _git(source_root, ("rev-parse", "HEAD")).decode().strip()
    current_tree = _git(source_root, ("rev-parse", "HEAD^{tree}")).decode().strip()
    if current_head != git.get("head") or current_tree != git.get("tree"):
        raise SourceClosureSourceMismatch("Current TidyCell Git identity differs")

    inventory_items = {
        item["relativePath"]: item for item in snapshot["inventory"]["items"]
    }
    entrypoints, roles = _parse_selection(request, inventory_items.keys())

    def read_source(relative_path: str) -> bytes:
        item = inventory_items.get(relative_path)
        if (
            not isinstance(item, dict)
            or item.get("entryType") != "file"
            or item.get("disposition") not in {"import", "duplicate-alias"}
        ):
            raise SourceClosureSourceMismatch(
                f"Selected TidyCell source is not admitted by Phase A: {relative_path}"
            )
        first, mode = _read_no_follow(source_root, relative_path)
        second, second_mode = _read_no_follow(source_root, relative_path)
        if first != second or mode != second_mode:
            raise SourceClosureSourceMismatch(
                f"Selected TidyCell source changed while reading: {relative_path}"
            )
        if (
            len(first) != item.get("byteLength")
            or sha256_digest(first) != item.get("contentDigest")
            or mode != item.get("sourceMode")
        ):
            raise SourceClosureSourceMismatch(
                f"Selected TidyCell bytes differ from Phase A: {relative_path}"
            )
        return first

    available = frozenset(inventory_items)
    discovered, external = _walk_imports(
        entrypoints=entrypoints,
        initial_roles=roles,
        available=available,
        read_source=read_source,
        max_files=max_files,
    )
    items, total_bytes = _phase_a_items(
        discovered,
        inventory_items,
        read_source,
        max_total_bytes=max_total_bytes,
    )
    return _source_manifest(
        source_system="tidycell",
        source_root_id=source_root_id,
        read_mode="phase-a-filesystem",
        authority={
            "phaseASnapshotDigest": snapshot_digest,
            "gitHead": git["head"],
            "gitTree": git["tree"],
            "trackedDirty": git["trackedDirty"],
            "trackedDirtyDigest": git["trackedDirtyDigest"],
            "selectedBytesMatchAuthority": True,
        },
        entrypoints=entrypoints,
        items=items,
        total_bytes=total_bytes,
        external_imports=external,
    )


def _discover_git_source(
    request: Mapping[str, Any], *, max_files: int, max_total_bytes: int
) -> dict[str, Any]:
    _require_exact_keys(
        request,
        {
            "sourceSystem",
            "readMode",
            "sourceRoot",
            "sourceRootId",
            "commit",
            "entrypoints",
            "metadata",
        },
        "git source request",
    )
    if request["sourceSystem"] != "tidybank":
        raise SourceClosureDiscoveryError("git-object mode is restricted to tidybank")
    source_root = _validated_directory(Path(request["sourceRoot"]), "sourceRoot")
    source_root_id = _require_text(request["sourceRootId"], "sourceRootId", 256)
    commit = _require_git_object(request["commit"], "commit")
    resolved_commit = (
        _git(source_root, ("rev-parse", f"{commit}^{{commit}}")).decode().strip()
    )
    if resolved_commit != commit:
        raise SourceClosureSourceMismatch("Pinned Tidybank commit differs")
    tree = _git(source_root, ("rev-parse", f"{commit}^{{tree}}")).decode().strip()
    _require_git_object(tree, "tree")
    tree_entries = _git_tree(source_root, commit)
    entrypoints, roles = _parse_selection(request, tree_entries.keys())

    cache: dict[str, bytes] = {}

    def read_source(relative_path: str) -> bytes:
        if relative_path not in tree_entries:
            raise SourceClosureSourceMismatch(
                f"Selected Tidybank path is absent from pinned commit: {relative_path}"
            )
        if relative_path not in cache:
            cache[relative_path] = _git(
                source_root,
                ("cat-file", "blob", f"{commit}:{relative_path}"),
                max_output=_MAX_FILE_BYTES,
            )
        return cache[relative_path]

    discovered, external = _walk_imports(
        entrypoints=entrypoints,
        initial_roles=roles,
        available=frozenset(tree_entries),
        read_source=read_source,
        max_files=max_files,
    )
    items: list[dict[str, Any]] = []
    total_bytes = 0
    for relative_path, role in sorted(discovered.items()):
        mode, object_id = tree_entries[relative_path]
        content = read_source(relative_path)
        total_bytes += len(content)
        if len(content) > _MAX_FILE_BYTES or total_bytes > max_total_bytes:
            raise SourceClosureDiscoveryError("Tidybank closure exceeds byte bounds")
        items.append(
            {
                "relativePath": relative_path,
                "role": role,
                "sourceMode": int(mode, 8),
                "byteLength": len(content),
                "contentDigest": sha256_digest(content),
                "gitBlobId": object_id,
                "phaseADisposition": None,
            }
        )
    return _source_manifest(
        source_system="tidybank",
        source_root_id=source_root_id,
        read_mode="git-object",
        authority={
            "phaseASnapshotDigest": None,
            "gitHead": commit,
            "gitTree": tree,
            "trackedDirty": None,
            "trackedDirtyDigest": None,
            "selectedBytesMatchAuthority": True,
        },
        entrypoints=entrypoints,
        items=items,
        total_bytes=total_bytes,
        external_imports=external,
    )


def _parse_selection(
    request: Mapping[str, Any], available_paths: Sequence[str] | set[str] | Any
) -> tuple[list[dict[str, str]], dict[str, str]]:
    available = frozenset(available_paths)
    roles: dict[str, str] = {}
    entrypoints: list[dict[str, str]] = []
    for field in ("entrypoints", "metadata"):
        values = request[field]
        if not isinstance(values, list) or not values:
            raise SourceClosureDiscoveryError(f"{field} must be a non-empty list")
        for value in values:
            item = _strict_mapping(value, field)
            _require_exact_keys(item, {"relativePath", "role"}, field)
            relative_path = _safe_relative_path(item["relativePath"])
            role = item["role"]
            if role not in _ROLES:
                raise SourceClosureDiscoveryError(f"Unsupported closure role: {role!r}")
            if relative_path not in available:
                raise SourceClosureSourceMismatch(
                    f"Selected path is absent from source authority: {relative_path}"
                )
            previous = roles.get(relative_path)
            if previous is not None and previous != role:
                raise SourceClosureDiscoveryError(
                    f"Selected path has conflicting roles: {relative_path}"
                )
            roles[relative_path] = role
            if field == "entrypoints":
                entrypoints.append({"relativePath": relative_path, "role": role})
    if sum(role == "license" for role in roles.values()) != 1:
        raise SourceClosureDiscoveryError(
            "Each source selection requires exactly one license"
        )
    if not any(role == "lockfile" for role in roles.values()):
        raise SourceClosureDiscoveryError("Each source selection requires a lockfile")
    return sorted(entrypoints, key=lambda value: value["relativePath"]), roles


def _walk_imports(
    *,
    entrypoints: Sequence[Mapping[str, str]],
    initial_roles: Mapping[str, str],
    available: frozenset[str],
    read_source: Any,
    max_files: int,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    roles = dict(initial_roles)
    queue = deque(item["relativePath"] for item in entrypoints)
    visited: set[str] = set()
    external: dict[str, set[str]] = defaultdict(set)
    while queue:
        relative_path = queue.popleft()
        if relative_path in visited:
            continue
        visited.add(relative_path)
        if len(roles) > max_files:
            raise SourceClosureDiscoveryError("Source closure exceeds file bound")
        if not relative_path.endswith(
            (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs")
        ):
            continue
        content = read_source(relative_path)
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise SourceClosureDiscoveryError(
                f"Source is not UTF-8: {relative_path}"
            ) from error
        for specifier in sorted(set(_IMPORT_PATTERN.findall(text))):
            resolved = _resolve_import(relative_path, specifier, available)
            if resolved is None:
                if specifier.startswith((".", "@/")):
                    raise SourceClosureDiscoveryError(
                        f"Unresolved relative import {specifier!r} from {relative_path}"
                    )
                external[specifier].add(relative_path)
                continue
            if resolved not in roles:
                roles[resolved] = "source"
            if resolved not in visited:
                queue.append(resolved)
    return roles, [
        {"specifier": specifier, "importedBy": sorted(imported_by)}
        for specifier, imported_by in sorted(external.items())
    ]


def _resolve_import(
    importing_path: str, specifier: str, available: frozenset[str]
) -> str | None:
    if specifier.startswith("@/"):
        base = f"src/{specifier[2:]}"
    elif specifier.startswith("."):
        parent = PurePosixPath(importing_path).parent
        base = (parent / specifier).as_posix()
    else:
        return None
    normalized = posixpath.normpath(base)
    if normalized.startswith("../") or normalized == "..":
        raise SourceClosureDiscoveryError(
            f"Import escapes source root: {specifier!r} from {importing_path}"
        )
    candidates = [normalized]
    suffix = PurePosixPath(normalized).suffix
    if suffix == ".js":
        candidates.extend((normalized[:-3] + ".ts", normalized[:-3] + ".tsx"))
    if suffix not in _SOURCE_EXTENSIONS:
        candidates.extend(normalized + extension for extension in _SOURCE_EXTENSIONS)
        candidates.extend(
            f"{normalized}/index{extension}" for extension in _SOURCE_EXTENSIONS
        )
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None


def _phase_a_items(
    discovered: Mapping[str, str],
    inventory_items: Mapping[str, Mapping[str, Any]],
    read_source: Any,
    *,
    max_total_bytes: int,
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    total_bytes = 0
    for relative_path, role in sorted(discovered.items()):
        source_item = inventory_items[relative_path]
        content = read_source(relative_path)
        total_bytes += len(content)
        if len(content) > _MAX_FILE_BYTES or total_bytes > max_total_bytes:
            raise SourceClosureDiscoveryError("TidyCell closure exceeds byte bounds")
        items.append(
            {
                "relativePath": relative_path,
                "role": role,
                "sourceMode": source_item["sourceMode"],
                "byteLength": len(content),
                "contentDigest": source_item["contentDigest"],
                "gitBlobId": None,
                "phaseADisposition": source_item["disposition"],
            }
        )
    return items, total_bytes


def _source_manifest(
    *,
    source_system: str,
    source_root_id: str,
    read_mode: str,
    authority: Mapping[str, Any],
    entrypoints: Sequence[Mapping[str, str]],
    items: Sequence[Mapping[str, Any]],
    total_bytes: int,
    external_imports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    license_items = [item for item in items if item["role"] == "license"]
    lock_items = [item for item in items if item["role"] == "lockfile"]
    if len(license_items) != 1 or not lock_items:
        raise SourceClosureDiscoveryError("Discovered custody metadata is incomplete")
    item_values = [dict(item) for item in items]
    semantic = {
        "sourceSystem": source_system,
        "sourceRootId": source_root_id,
        "readMode": read_mode,
        "authority": dict(authority),
        "entrypoints": [dict(value) for value in entrypoints],
        "items": item_values,
        "externalImports": [dict(value) for value in external_imports],
        "licenseDigest": license_items[0]["contentDigest"],
        "lockfileDigests": [item["contentDigest"] for item in lock_items],
        "itemCount": len(item_values),
        "totalBytes": total_bytes,
        "itemManifestDigest": domain_digest(
            "tidy.source-closure-items/v1", item_values
        ),
    }
    return semantic


def _git_tree(root: Path, commit: str) -> dict[str, tuple[str, str]]:
    raw = _git(root, ("ls-tree", "-r", "-z", commit))
    result: dict[str, tuple[str, str]] = {}
    for entry in raw.rstrip(b"\0").split(b"\0") if raw else ():
        metadata, path_bytes = entry.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
        relative_path = path_bytes.decode("utf-8", errors="strict")
        if object_type != "blob":
            continue
        _safe_relative_path(relative_path)
        _require_git_object(object_id, "blob")
        result[relative_path] = (mode, object_id)
    return result


def _git(
    root: Path,
    arguments: Sequence[str],
    *,
    max_output: int = _MAX_GIT_OUTPUT_BYTES,
) -> bytes:
    executable = _git_executable()
    environment = {
        "PATH": f"{executable.parent}:/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    result = subprocess.run(
        [str(executable), *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if len(result.stdout) > max_output or len(result.stderr) > 1024 * 1024:
        raise SourceClosureDiscoveryError("Git output exceeds its bound")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[:1024]
        raise SourceClosureDiscoveryError(
            f"Git command failed ({result.returncode}): {detail}"
        )
    return result.stdout


def _read_no_follow(
    root: Path, relative_path: str, *, max_bytes: int = _MAX_FILE_BYTES
) -> tuple[bytes, int]:
    safe = _safe_relative_path(relative_path)
    root_descriptor = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    parent = root_descriptor
    try:
        parts = safe.split("/")
        for part in parts[:-1]:
            child = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent,
            )
            if parent != root_descriptor:
                os.close(parent)
            parent = child
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise SourceClosureDiscoveryError(
                    f"Selected path is not a bounded regular file: {safe}"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, _READ_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise SourceClosureDiscoveryError(
                        f"Selected source exceeds file bound: {safe}"
                    )
                chunks.append(chunk)
            after = os.fstat(descriptor)
            if (
                _stat_identity(before) != _stat_identity(after)
                or total != before.st_size
            ):
                raise SourceClosureSourceMismatch(
                    f"Selected source changed while reading: {safe}"
                )
            return b"".join(chunks), before.st_mode
        finally:
            os.close(descriptor)
    except OSError as error:
        raise SourceClosureDiscoveryError(
            f"Selected source could not be opened safely: {safe}"
        ) from error
    finally:
        if parent != root_descriptor:
            os.close(parent)
        os.close(root_descriptor)


def _read_json_file(path: Path, max_bytes: int, label: str) -> dict[str, Any]:
    parent = _validated_directory(path.parent, f"{label} parent")
    data, _mode = _read_no_follow(parent, path.name, max_bytes=max_bytes)
    if len(data) > max_bytes:
        raise SourceClosureDiscoveryError(f"{label} exceeds its byte bound")
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
        raise SourceClosureDiscoveryError(f"{label} is not strict JSON") from error
    _assert_json_limits(value, label)
    return _strict_mapping(value, label)


def _validated_directory(path: Path, label: str) -> Path:
    if not isinstance(path, Path):
        raise SourceClosureDiscoveryError(f"{label} must be a Path")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SourceClosureDiscoveryError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise SourceClosureDiscoveryError("Source path is invalid")
    if "\x00" in value or "\\" in value or ":" in value:
        raise SourceClosureDiscoveryError("Source path is not portable")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SourceClosureDiscoveryError("Source path escapes or is not normalized")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = entry
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _assert_json_limits(value: Any, label: str) -> None:
    pending: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise SourceClosureDiscoveryError(f"{label} exceeds its JSON node limit")
        if depth > _MAX_JSON_DEPTH:
            raise SourceClosureDiscoveryError(f"{label} exceeds its JSON depth limit")
        if isinstance(current, list):
            pending.extend((entry, depth + 1) for entry in current)
        elif isinstance(current, dict):
            nodes += len(current)
            if nodes > _MAX_JSON_NODES:
                raise SourceClosureDiscoveryError(
                    f"{label} exceeds its JSON node limit"
                )
            pending.extend((entry, depth + 1) for entry in current.values())


def _strict_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceClosureDiscoveryError(f"{label} must be an object")
    return dict(value)


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise SourceClosureDiscoveryError(f"{label} fields differ")


def _require_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SourceClosureDiscoveryError(f"{label} is invalid")
    return value


def _require_digest(value: Any) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise SourceClosureDiscoveryError("Digest is invalid")
    return value


def _require_git_object(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _GIT_OBJECT.fullmatch(value):
        raise SourceClosureDiscoveryError(f"{label} Git object is invalid")
    return value


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise SourceClosureDiscoveryError(f"{label} is outside its bound")
    return value


def _require_utc_timestamp(value: Any) -> str:
    text = _require_text(value, "frozenAt", 64)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z", text):
        raise SourceClosureDiscoveryError("frozenAt must be a canonical UTC timestamp")
    return text


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )


def _git_executable() -> Path:
    raw = shutil.which("git")
    if raw is None:
        raise SourceClosureDiscoveryError("Git executable is unavailable")
    executable = Path(raw).resolve(strict=True)
    info = executable.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SourceClosureDiscoveryError("Git executable is not a regular file")
    return executable


def _git_producer_identity() -> dict[str, str]:
    executable = _git_executable()
    data, _mode = _read_no_follow(
        _validated_directory(executable.parent, "Git executable parent"),
        executable.name,
        max_bytes=64 * 1024 * 1024,
    )
    result = subprocess.run(
        [str(executable), "--version"],
        env={"PATH": f"{executable.parent}:/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or result.stderr or not result.stdout:
        raise SourceClosureDiscoveryError("Git runtime identity is unavailable")
    try:
        version = result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise SourceClosureDiscoveryError("Git version is not UTF-8") from error
    if not version or len(version) > 256:
        raise SourceClosureDiscoveryError("Git version is invalid")
    return {
        "executableDigest": sha256_digest(data),
        "version": version,
    }


def _producer_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = (
        Path(__file__),
        Path(__file__).with_name("source_export.py"),
        Path(__file__).with_name("artifacts.py"),
        project / "contracts/migration/v1/source-closure-discovery.schema.json",
        project / "contracts/migration/v1/source-closure-review.schema.json",
        project / "pyproject.toml",
        project / "uv.lock",
    )

    def capture() -> dict[str, Any]:
        files: list[dict[str, str]] = []
        for path in paths:
            data, _mode = _read_no_follow(
                _validated_directory(path.parent, "producer source parent"),
                path.name,
                max_bytes=16 * 1024 * 1024,
            )
            files.append(
                {
                    "relativePath": path.relative_to(project).as_posix(),
                    "contentDigest": sha256_digest(data),
                }
            )
        return {"files": files, "git": _git_producer_identity()}

    first = capture()
    if capture() != first:
        raise SourceClosureSourceMismatch(
            "Source-closure producer changed while hashing"
        )
    return domain_digest("tidy.source-closure-producer/v1", first)


def write_manifest_atomic(path: Path, manifest: Mapping[str, Any]) -> None:
    parent = _validated_directory(path.parent, "manifest output parent")
    payload = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    temporary = parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, parent / path.name)
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def canonical_manifest_digest(manifest: Mapping[str, Any]) -> str:
    semantic = dict(manifest)
    identity = semantic.pop("manifestDigest", None)
    expected = domain_digest(_SCHEMA_VERSION, semantic)
    if identity != expected:
        raise SourceClosureDiscoveryError("Manifest digest differs")
    if canonical_json_bytes(semantic) != canonical_json_bytes(dict(semantic)):
        raise AssertionError("Canonical manifest encoding is unstable")
    return expected
