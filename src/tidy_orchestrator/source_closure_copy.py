"""Transactional repository-local custody for one reviewed source closure."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .source_closure_discovery import (
    SourceClosureSourceMismatch,
    canonical_manifest_digest,
    load_discovery_manifest,
    load_discovery_request,
    verify_source_closure,
)

_COMMIT_VERSION = "tidy.source-closure-copy-commit/v1"
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_REVIEW_BYTES = 1024 * 1024
_MAX_ITEM_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_READ_CHUNK = 1024 * 1024
_PROJECT = Path(__file__).parents[2]
_COMMIT_SCHEMA = (
    _PROJECT / "contracts/migration/v1/source-closure-copy-commit.schema.json"
)


class SourceClosureCopyError(RuntimeError):
    """Reviewed source bytes could not be copied or verified safely."""


class SourceClosureCopyConflict(SourceClosureCopyError):
    """An immutable destination already exists or differs."""


def copy_source_closure(
    *,
    request_path: Path,
    manifest_path: Path,
    review_path: Path,
    destination: Path,
    copied_at: str,
) -> dict[str, Any]:
    """Copy exactly one reviewed manifest into a new atomic reference bundle."""

    copied_at = _require_utc_timestamp(copied_at)
    request = load_discovery_request(request_path)
    manifest = load_discovery_manifest(manifest_path)
    verify_source_closure(manifest=manifest, request=request)
    manifest_bytes = _read_regular(manifest_path, _MAX_MANIFEST_BYTES)
    if json.loads(manifest_bytes) != manifest:
        raise SourceClosureCopyError("Discovery manifest changed while reading")
    review_bytes = _read_regular(review_path, _MAX_REVIEW_BYTES)
    review = _strict_json_object(review_bytes, "source-closure self-review")
    _validate_review(review, manifest)
    if destination.exists() or os.path.lexists(destination):
        raise SourceClosureCopyConflict("Source-closure destination already exists")
    parent = _validated_directory(destination.parent, "copy destination parent")
    producer_before = _copy_producer_digest()
    sources_by_system = {
        source["sourceSystem"]: source for source in manifest["sources"]
    }
    requests_by_system = {
        source["sourceSystem"]: source for source in request["sources"]
    }
    if set(sources_by_system) != {"tidycell", "tidybank"} or set(
        requests_by_system
    ) != set(sources_by_system):
        raise SourceClosureCopyError(
            "Source systems differ between request and manifest"
        )

    stage = parent / f".source-closure-stage-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    try:
        copied_items: list[dict[str, Any]] = []
        for source_system in sorted(sources_by_system):
            source_manifest = sources_by_system[source_system]
            source_request = requests_by_system[source_system]
            if source_request["sourceRootId"] != source_manifest["sourceRootId"]:
                raise SourceClosureCopyError("Source root identity differs")
            source_root = Path(source_request["sourceRoot"])
            for item in source_manifest["items"]:
                relative = _safe_relative(str(item["relativePath"]))
                if source_manifest["readMode"] == "phase-a-filesystem":
                    data = _read_source_relative(source_root, relative)
                elif source_manifest["readMode"] == "git-object":
                    data = _read_git_blob(source_root, str(item["gitBlobId"]))
                else:
                    raise SourceClosureCopyError("Unsupported source copy mode")
                if (
                    len(data) != item["byteLength"]
                    or sha256_digest(data) != item["contentDigest"]
                ):
                    raise SourceClosureSourceMismatch(
                        "Copied source differs from manifest: "
                        f"{source_system}/{relative}"
                    )
                target = stage / "sources" / source_system / relative
                target.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
                _write_file(target, data, mode=0o644)
                copied_items.append(
                    {
                        "sourceSystem": source_system,
                        "relativePath": relative.as_posix(),
                        "sourceMode": item["sourceMode"],
                        "byteLength": len(data),
                        "contentDigest": item["contentDigest"],
                    }
                )
        if (
            len(copied_items) != manifest["totals"]["itemCount"]
            or sum(item["byteLength"] for item in copied_items)
            != manifest["totals"]["byteLength"]
        ):
            raise SourceClosureCopyError("Copied source totals differ from manifest")
        if sum(item["byteLength"] for item in copied_items) > _MAX_TOTAL_BYTES:
            raise SourceClosureCopyError(
                "Copied source closure exceeds hard byte bound"
            )

        _write_file(stage / "DISCOVERY.json", manifest_bytes, mode=0o644)
        _write_file(stage / "SELF_REVIEW.json", review_bytes, mode=0o644)
        producer_after = _copy_producer_digest()
        if producer_before != producer_after:
            raise SourceClosureSourceMismatch(
                "Source-closure copy producer changed during publication"
            )
        semantic = {
            "schemaVersion": _COMMIT_VERSION,
            "closureManifestDigest": manifest["manifestDigest"],
            "closureManifestFileDigest": sha256_digest(manifest_bytes),
            "closureManifestFileBytes": len(manifest_bytes),
            "selfReviewDigest": review["reviewDigest"],
            "selfReviewFileDigest": sha256_digest(review_bytes),
            "selfReviewFileBytes": len(review_bytes),
            "copyProducerDigest": producer_after,
            "copiedAt": copied_at,
            "itemCount": len(copied_items),
            "byteLength": sum(item["byteLength"] for item in copied_items),
            "bundleContentDigest": domain_digest(
                "tidy.source-closure-copy-items/v1", copied_items
            ),
            "sourceBytesCopied": True,
            "runtimeAuthorized": False,
            "parityEstablished": False,
        }
        commit = {
            **semantic,
            "commitDigest": domain_digest(_COMMIT_VERSION, semantic),
        }
        _write_file(
            stage / "COMMITTED.json",
            canonical_json_bytes(commit) + b"\n",
            mode=0o644,
        )
        _fsync_tree_directories(stage)
        os.rename(stage, destination)
        _fsync_directory(parent)
        verify_source_closure_copy(destination)
        return commit
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def verify_source_closure_copy(destination: Path) -> dict[str, Any]:
    """Read-verify one immutable bundle without any sibling source dependency."""

    root = _validated_directory(destination, "source-closure copy")
    commit_bytes = _read_regular(root / "COMMITTED.json", 1024 * 1024)
    commit = _strict_json_object(commit_bytes, "source-closure commit")
    _validate_commit_fields(commit)
    semantic = dict(commit)
    identity = semantic.pop("commitDigest", None)
    if identity != domain_digest(_COMMIT_VERSION, semantic):
        raise SourceClosureCopyConflict("Source-closure commit identity differs")
    if (
        commit.get("schemaVersion") != _COMMIT_VERSION
        or commit.get("sourceBytesCopied") is not True
        or commit.get("runtimeAuthorized") is not False
        or commit.get("parityEstablished") is not False
        or commit_bytes != canonical_json_bytes(commit) + b"\n"
    ):
        raise SourceClosureCopyConflict("Source-closure commit fields differ")
    manifest_bytes = _read_regular(root / "DISCOVERY.json", _MAX_MANIFEST_BYTES)
    review_bytes = _read_regular(root / "SELF_REVIEW.json", _MAX_REVIEW_BYTES)
    if (
        sha256_digest(manifest_bytes) != commit["closureManifestFileDigest"]
        or len(manifest_bytes) != commit["closureManifestFileBytes"]
        or sha256_digest(review_bytes) != commit["selfReviewFileDigest"]
        or len(review_bytes) != commit["selfReviewFileBytes"]
    ):
        raise SourceClosureCopyConflict("Source-closure evidence file differs")
    manifest = _strict_json_object(manifest_bytes, "copied discovery manifest")
    review = _strict_json_object(review_bytes, "copied self-review")
    if manifest.get("manifestDigest") != commit[
        "closureManifestDigest"
    ] or canonical_manifest_digest(manifest) != manifest.get("manifestDigest"):
        raise SourceClosureCopyConflict("Copied discovery identity differs")
    _validate_review(review, manifest)
    if review["reviewDigest"] != commit["selfReviewDigest"]:
        raise SourceClosureCopyConflict("Copied self-review identity differs")

    copied_items: list[dict[str, Any]] = []
    expected_files = {"COMMITTED.json", "DISCOVERY.json", "SELF_REVIEW.json"}
    for source in manifest["sources"]:
        source_system = source["sourceSystem"]
        for item in source["items"]:
            relative = _safe_relative(str(item["relativePath"]))
            bundle_relative = Path("sources") / source_system / relative
            data = _read_regular(root / bundle_relative, _MAX_ITEM_BYTES)
            if (
                len(data) != item["byteLength"]
                or sha256_digest(data) != item["contentDigest"]
            ):
                raise SourceClosureCopyConflict(
                    f"Copied source item differs: {bundle_relative.as_posix()}"
                )
            expected_files.add(bundle_relative.as_posix())
            copied_items.append(
                {
                    "sourceSystem": source_system,
                    "relativePath": relative.as_posix(),
                    "sourceMode": item["sourceMode"],
                    "byteLength": len(data),
                    "contentDigest": item["contentDigest"],
                }
            )
    actual_files = _list_regular_files(root)
    if actual_files != expected_files:
        raise SourceClosureCopyConflict(
            "Source-closure copy has missing or undeclared files"
        )
    if (
        len(copied_items) != commit["itemCount"]
        or sum(item["byteLength"] for item in copied_items) != commit["byteLength"]
        or domain_digest("tidy.source-closure-copy-items/v1", copied_items)
        != commit["bundleContentDigest"]
    ):
        raise SourceClosureCopyConflict("Source-closure copied item identity differs")
    return commit


def _validate_commit_fields(commit: Mapping[str, Any]) -> None:
    required = {
        "schemaVersion",
        "closureManifestDigest",
        "closureManifestFileDigest",
        "closureManifestFileBytes",
        "selfReviewDigest",
        "selfReviewFileDigest",
        "selfReviewFileBytes",
        "copyProducerDigest",
        "copiedAt",
        "itemCount",
        "byteLength",
        "bundleContentDigest",
        "sourceBytesCopied",
        "runtimeAuthorized",
        "parityEstablished",
        "commitDigest",
    }
    if set(commit) != required or commit.get("schemaVersion") != _COMMIT_VERSION:
        raise SourceClosureCopyConflict("Source-closure commit fields differ")
    for name in (
        "closureManifestDigest",
        "closureManifestFileDigest",
        "selfReviewDigest",
        "selfReviewFileDigest",
        "copyProducerDigest",
        "bundleContentDigest",
        "commitDigest",
    ):
        _require_digest(commit.get(name))
    for name, maximum in (
        ("closureManifestFileBytes", _MAX_MANIFEST_BYTES),
        ("selfReviewFileBytes", _MAX_REVIEW_BYTES),
        ("itemCount", 1000),
        ("byteLength", _MAX_TOTAL_BYTES),
    ):
        value = commit.get(name)
        if type(value) is not int or not 1 <= value <= maximum:
            raise SourceClosureCopyConflict("Source-closure commit bound differs")
    _require_utc_timestamp(str(commit.get("copiedAt")))


def _validate_review(review: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    required = {
        "schemaVersion",
        "closureManifestDigest",
        "reviewKind",
        "status",
        "reviewedAt",
        "reviewer",
        "checks",
        "claims",
        "limitations",
        "reviewDigest",
    }
    if (
        set(review) != required
        or review.get("schemaVersion") != "tidy.source-closure-self-review/v1"
        or review.get("closureManifestDigest") != manifest.get("manifestDigest")
        or review.get("reviewKind") != "implementing-agent-self-review"
        or review.get("status") != "accepted-for-bounded-copy-and-parity-work"
        or review.get("reviewer") != "tidy-dagster-implementing-agent"
        or review.get("claims")
        != {
            "independentReview": False,
            "parityEstablished": False,
            "runtimeSiblingDependencyAllowed": False,
            "sourceBytesCopied": False,
        }
    ):
        raise SourceClosureCopyError("Self-review does not authorize bounded copying")
    _require_utc_timestamp(str(review.get("reviewedAt")))
    checks = review.get("checks")
    limitations = review.get("limitations")
    if (
        not isinstance(checks, list)
        or not 6 <= len(checks) <= 32
        or any(
            not isinstance(check, dict)
            or set(check) != {"id", "status", "evidence"}
            or not isinstance(check["id"], str)
            or not check["id"]
            or check["status"] != "pass"
            or not isinstance(check["evidence"], list)
            or not check["evidence"]
            or any(
                not isinstance(evidence, str) or not evidence
                for evidence in check["evidence"]
            )
            for check in checks
        )
        or not isinstance(limitations, list)
        or not 3 <= len(limitations) <= 16
        or any(not isinstance(value, str) or not value for value in limitations)
    ):
        raise SourceClosureCopyError("Self-review checks or limitations differ")
    semantic = dict(review)
    identity = semantic.pop("reviewDigest", None)
    if identity != domain_digest("tidy.source-closure-self-review/v1", semantic):
        raise SourceClosureCopyError("Self-review identity differs")


def _read_source_relative(root: Path, relative: PurePosixPath) -> bytes:
    validated = _validated_directory(root, "filesystem source root")
    root_fd = os.open(
        validated,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    current = root_fd
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            if current != root_fd:
                os.close(current)
            current = next_fd
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current,
        )
        try:
            return _read_descriptor(descriptor, _MAX_ITEM_BYTES)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise SourceClosureSourceMismatch(
            f"Source item could not be opened safely: {relative}"
        ) from error
    finally:
        if current != root_fd:
            os.close(current)
        os.close(root_fd)


def _read_git_blob(root: Path, object_id: str) -> bytes:
    if (
        not isinstance(object_id, str)
        or len(object_id) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in object_id)
    ):
        raise SourceClosureCopyError("Git blob identity is invalid")
    executable = _git_executable()
    result = subprocess.run(
        [str(executable), "cat-file", "blob", object_id],
        cwd=_validated_directory(root, "Git source root"),
        env={
            "PATH": f"{executable.parent}:/usr/bin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0 or result.stderr or len(result.stdout) > _MAX_ITEM_BYTES:
        raise SourceClosureSourceMismatch("Pinned Git blob could not be read")
    return result.stdout


def _copy_producer_digest() -> str:
    paths = (
        Path(__file__),
        Path(__file__).with_name("source_closure_discovery.py"),
        Path(__file__).with_name("artifacts.py"),
        _COMMIT_SCHEMA,
        _PROJECT / "pyproject.toml",
        _PROJECT / "uv.lock",
    )

    def capture() -> dict[str, Any]:
        return {
            "files": [
                {
                    "relativePath": path.relative_to(_PROJECT).as_posix(),
                    "contentDigest": sha256_digest(
                        _read_regular(path, 16 * 1024 * 1024)
                    ),
                }
                for path in paths
            ],
            "git": _git_identity(),
        }

    first = capture()
    if capture() != first:
        raise SourceClosureSourceMismatch("Copy producer changed while hashing")
    return domain_digest("tidy.source-closure-copy-producer/v1", first)


def _git_executable() -> Path:
    raw = shutil.which("git")
    if raw is None:
        raise SourceClosureCopyError("Git executable is unavailable")
    path = Path(raw).resolve(strict=True)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SourceClosureCopyError("Git executable is not a regular file")
    return path


def _git_identity() -> dict[str, str]:
    executable = _git_executable()
    result = subprocess.run(
        [str(executable), "--version"],
        env={"PATH": f"{executable.parent}:/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0 or result.stderr or not result.stdout:
        raise SourceClosureCopyError("Git runtime identity is unavailable")
    return {
        "executableDigest": sha256_digest(_read_regular(executable, 64 * 1024 * 1024)),
        "version": result.stdout.decode("utf-8", errors="strict").strip(),
    }


def _strict_json_object(data: bytes, label: str) -> dict[str, Any]:
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
        raise SourceClosureCopyError(f"{label} is not strict JSON") from error
    if not isinstance(value, dict):
        raise SourceClosureCopyError(f"{label} is not an object")
    return value


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError(f"duplicate key: {key}")
        value[key] = entry
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _read_regular(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        return _read_descriptor(descriptor, maximum)
    except OSError as error:
        raise SourceClosureCopyError(
            f"Could not read regular file: {path.name}"
        ) from error
    finally:
        os.close(descriptor)


def _read_descriptor(descriptor: int, maximum: int) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise SourceClosureCopyError("Source-closure file is not bounded and regular")
    chunks: list[bytes] = []
    remaining = before.st_size
    while remaining:
        chunk = os.read(descriptor, min(_READ_CHUNK, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    ) or remaining:
        raise SourceClosureSourceMismatch("Source-closure file changed while reading")
    return b"".join(chunks)


def _write_file(path: Path, data: bytes, *, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        view = memoryview(data)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("short write")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(mode)


def _list_regular_files(root: Path) -> set[str]:
    files: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink():
                    raise SourceClosureCopyConflict(
                        "Source-closure copy contains symlink"
                    )
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    files.add(Path(entry.path).relative_to(root).as_posix())
                else:
                    raise SourceClosureCopyConflict(
                        "Source-closure copy contains special file"
                    )
    return files


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 4096
        or "\\" in value
        or "\x00" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise SourceClosureCopyError("Source-closure relative path is unsafe")
    return path


def _validated_directory(path: Path, label: str) -> Path:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SourceClosureCopyError(f"{label} must be a real directory")
    return path.resolve(strict=True)


def _fsync_tree_directories(root: Path) -> None:
    directories = [path for path in root.rglob("*") if path.is_dir()]
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(path)
    _fsync_directory(root)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_digest(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise SourceClosureCopyError("Source-closure digest is invalid")
    return value


def _require_utc_timestamp(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or not value.endswith("Z")
        or "T" not in value
    ):
        raise SourceClosureCopyError("copied_at must be canonical UTC")
    return value
