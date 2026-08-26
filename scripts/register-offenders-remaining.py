#!/usr/bin/env python3
"""Authority-gated, journaled atomic installer for a reviewed C4 proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tidy_orchestrator.artifacts import domain_digest  # noqa: E402
from tidy_orchestrator.data_asset_status import (  # noqa: E402
    build_dashboard,
    render_dashboard,
    snapshot_matches,
)
from tidy_orchestrator.large_batch import (  # noqa: E402
    load_large_batch_registry,
    verify_batch_normalization,
    verify_large_batch_evidence,
)
from tidy_orchestrator.offenders_acceptance import (  # noqa: E402
    c4_exclusive_access,
    required_c4_runtime_paths,
    required_c4_toolchain_paths,
    validate_c4_clean_checkout_tracking,
    verify_c4_acceptance_authority,
)
from tidy_orchestrator.offenders_release import verify_offenders_release  # noqa: E402

EXPECTED = (47, 170, 224997)
EXPECTED_PAYLOAD_FILES = 597
EXPECTED_CATEGORIES = {
    "cohort": 47,
    "replay": 170,
    "contract": 47,
    "evidence": 47,
    "registry": 4,
}
EVIDENCE_FILES = {
    "README.md",
    "canonical-observations.csv",
    "canonical-observations.json",
    "collation-report.json",
    "exceptions.json",
    "manifest.json",
    "run.json",
}
EXPECTED_MANIFEST_KEYS = {
    "schemaVersion",
    "acceptanceAuthority",
    "trainingEligibility",
    "productionAcceptance",
    "promotionAuthorization",
    "recordedAt",
    "families",
    "members",
    "rows",
    "providerCalls",
    "files",
    "payloadRootDigest",
    "outputRootDigest",
}
EXPECTED_RECORD_KEYS = {"path", "byteLength", "sha256"}
TX_ROOT = ROOT / ".product-prototype/offenders-c4-install-transactions"
TX_LOCK = TX_ROOT / "install.lock"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"object required: {path}")
    return value


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_durable(path: Path, value: Any) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _write_raw_durable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _create_lock_durable(owner: dict[str, Any]) -> None:
    temporary = TX_ROOT / f".install.lock.tmp-{owner['token']}"
    _write_raw_durable(temporary, (json.dumps(owner, sort_keys=True) + "\n").encode())
    try:
        os.link(temporary, TX_LOCK, follow_symlinks=False)
    except FileExistsError as error:
        raise RuntimeError("C4 install transaction already owned") from error
    finally:
        temporary.unlink(missing_ok=True)
        _fsync_directory(TX_ROOT)


def compare(left_root: Path, right_root: Path) -> None:
    left = {
        path.relative_to(left_root)
        for path in left_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    right = {
        path.relative_to(right_root)
        for path in right_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if left != right or any(
        (left_root / path).is_symlink()
        or (right_root / path).is_symlink()
        or (left_root / path).read_bytes() != (right_root / path).read_bytes()
        for path in left
    ):
        raise RuntimeError("proposal runs differ")


def validate_manifest(run: Path) -> dict[str, Any]:
    manifest_path = run / "manifest.json"
    payload = run / "payload"
    if run.is_symlink() or manifest_path.is_symlink() or payload.is_symlink():
        raise RuntimeError("unsafe proposal root")
    manifest = load(manifest_path)
    if (
        set(manifest) != EXPECTED_MANIFEST_KEYS
        or manifest.get("schemaVersion") != "tidy.offenders-c4-proposal/v1"
        or manifest.get("acceptanceAuthority") is not False
        or manifest.get("trainingEligibility") is not False
        or manifest.get("productionAcceptance") is not False
        or manifest.get("promotionAuthorization") is not False
        or manifest.get("providerCalls") != 0
        or manifest.get("recordedAt") != "2026-08-25T12:00:00+00:00"
        or not isinstance(manifest.get("files"), list)
        or len(manifest["files"]) != EXPECTED_PAYLOAD_FILES
    ):
        raise RuntimeError("proposal manifest shape")
    records = []
    record_paths = []
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != EXPECTED_RECORD_KEYS:
            raise RuntimeError("proposal file record shape")
        relative = PurePosixPath(item.get("path", ""))
        if (
            not item.get("path")
            or relative.is_absolute()
            or relative.as_posix() != item["path"]
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise RuntimeError("proposal file path escape")
        path = payload.joinpath(*relative.parts)
        data = path.read_bytes()
        if (
            path.is_symlink()
            or path.resolve() != path.absolute()
            or isinstance(item.get("byteLength"), bool)
            or len(data) != item.get("byteLength")
            or _sha(data) != item.get("sha256")
        ):
            raise RuntimeError("proposal file drift")
        records.append(item)
        record_paths.append(relative)
    actual = {
        PurePosixPath(path.relative_to(payload).as_posix())
        for path in payload.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if (
        record_paths != sorted(record_paths)
        or len(record_paths) != len(set(record_paths))
        or actual != set(record_paths)
    ):
        raise RuntimeError("proposal file closure drift")
    if (
        domain_digest("tidy.offenders-c4-proposal-payload/v1", records)
        != manifest["payloadRootDigest"]
        or (manifest["families"], manifest["members"], manifest["rows"]) != EXPECTED
    ):
        raise RuntimeError("proposal manifest drift")
    semantic = dict(manifest)
    output = semantic.pop("outputRootDigest")
    if domain_digest("tidy.offenders-c4-proposal-output/v1", semantic) != output:
        raise RuntimeError("proposal output root drift")
    return manifest


def _safe_destination(path: Path) -> None:
    try:
        relative = path.relative_to(ROOT)
    except ValueError as error:
        raise RuntimeError("destination escapes repository") from error
    cursor = ROOT
    if cursor.is_symlink() or cursor.resolve() != cursor.absolute():
        raise RuntimeError("unsafe repository root")
    for part in relative.parts[:-1]:
        cursor /= part
        if (
            cursor.is_symlink()
            or not cursor.is_dir()
            or cursor.resolve() != cursor.absolute()
        ):
            raise RuntimeError(f"unsafe destination ancestor: {cursor}")
    if path.is_symlink():
        raise RuntimeError(f"unsafe destination leaf: {path}")


def _replacement_items(payload: Path) -> list[tuple[str, Path, Path]]:
    fix = payload / "fixtures/product-prototype"
    groups: dict[str, list[Path]] = {
        "cohort": sorted(fix.glob("recorded-crime-offenders-*.json")),
        "replay": sorted(
            (fix / "replay").glob("recorded-crime-offenders-*.response.txt")
        ),
        "contract": sorted(
            (fix / "acceptance").glob("recorded-crime-offenders-*-v1.json")
        ),
        "evidence": sorted(fix.glob("recorded-crime-offenders-*-evidence")),
    }
    if {key: len(value) for key, value in groups.items()} != {
        key: EXPECTED_CATEGORIES[key] for key in groups
    }:
        raise RuntimeError("replacement category closure")
    for directory in groups["evidence"]:
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or {path.name for path in directory.iterdir()} != EVIDENCE_FILES
            or any(
                not path.is_file() or path.is_symlink() for path in directory.iterdir()
            )
        ):
            raise RuntimeError("evidence seven-file closure")
    items = []
    for source in groups["cohort"]:
        items.append(
            ("cohort", source, ROOT / "fixtures/product-prototype" / source.name)
        )
    for source in groups["replay"]:
        items.append(
            ("replay", source, ROOT / "fixtures/product-prototype/replay" / source.name)
        )
    for source in groups["contract"]:
        items.append(
            (
                "contract",
                source,
                ROOT / "fixtures/product-prototype/acceptance" / source.name,
            )
        )
    for source in groups["evidence"]:
        items.append(
            ("evidence", source, ROOT / "fixtures/product-prototype" / source.name)
        )
    for name in (
        "offenders-remaining-c4-route-manifest-v1.json",
        "offenders-remaining-workbook-normalization-v1.json",
        "large-batch-assets-v1.json",
        "data-asset-status-v1.json",
    ):
        items.append(
            ("registry", fix / name, ROOT / "fixtures/product-prototype" / name)
        )
    counts = Counter(kind for kind, _source, _destination in items)
    if counts != EXPECTED_CATEGORIES or len(items) != 315:
        raise RuntimeError("replacement closure")
    represented = set()
    for _kind, source, destination in items:
        _safe_destination(destination)
        paths = source.rglob("*") if source.is_dir() else (source,)
        represented.update(
            path.relative_to(payload).as_posix()
            for path in paths
            if path.is_file() or path.is_symlink()
        )
    payload_files = {
        path.relative_to(payload).as_posix()
        for path in payload.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if represented != payload_files or len(payload_files) != EXPECTED_PAYLOAD_FILES:
        raise RuntimeError("replacement-to-manifest closure")
    return items


def transaction_hook_names(payload_count: int = 315) -> set[str]:
    return {
        *(f"before-backup-{index}" for index in range(payload_count + 1)),
        *(f"after-backup-{index}" for index in range(payload_count + 1)),
        *(f"before-install-{index}" for index in range(payload_count)),
        *(f"after-install-{index}" for index in range(payload_count)),
        "generated-status",
        "post-swap-validation",
        "rollback-interruption",
    }


def _inject_hook(
    inject: Callable[[str, Path], None] | None,
    name: str,
    destination: Path,
) -> None:
    if name not in transaction_hook_names():
        raise RuntimeError(f"unknown C4 transaction hook: {name}")
    if inject:
        inject(name, destination)


def _expected_destination_paths(manifest: dict[str, Any]) -> list[str]:
    records = manifest.get("files")
    if (
        set(manifest) != EXPECTED_MANIFEST_KEYS
        or not isinstance(records, list)
        or len(records) != EXPECTED_PAYLOAD_FILES
        or any(
            not isinstance(item, dict) or set(item) != EXPECTED_RECORD_KEYS
            for item in records
        )
        or (manifest.get("families"), manifest.get("members"), manifest.get("rows"))
        != EXPECTED
        or domain_digest("tidy.offenders-c4-proposal-payload/v1", records)
        != manifest.get("payloadRootDigest")
    ):
        raise RuntimeError("expected C4 manifest closure drift")
    semantic = dict(manifest)
    output = semantic.pop("outputRootDigest", None)
    if domain_digest("tidy.offenders-c4-proposal-output/v1", semantic) != output:
        raise RuntimeError("expected C4 manifest output drift")
    paths = [item["path"] for item in records]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise RuntimeError("expected C4 manifest path drift")
    cohorts = sorted(
        path
        for path in paths
        if path.startswith("fixtures/product-prototype/recorded-crime-offenders-")
        and path.endswith(".json")
        and "-evidence/" not in path
    )
    replays = sorted(
        path
        for path in paths
        if path.startswith("fixtures/product-prototype/replay/")
        and path.endswith(".response.txt")
    )
    contracts = sorted(
        path
        for path in paths
        if path.startswith("fixtures/product-prototype/acceptance/")
        and path.endswith("-v1.json")
    )
    evidence_paths = sorted(
        {
            PurePosixPath(path).parent.as_posix()
            for path in paths
            if path.startswith("fixtures/product-prototype/") and "-evidence/" in path
        }
    )
    registries = [
        f"fixtures/product-prototype/{name}"
        for name in (
            "offenders-remaining-c4-route-manifest-v1.json",
            "offenders-remaining-workbook-normalization-v1.json",
            "large-batch-assets-v1.json",
            "data-asset-status-v1.json",
        )
    ]
    result = [
        *cohorts,
        *replays,
        *contracts,
        *evidence_paths,
        *registries,
        "docs/data-asset-status/index.html",
    ]
    if (
        len(cohorts) != 47
        or len(replays) != 170
        or len(contracts) != 47
        or len(evidence_paths) != 47
        or len(result) != 316
        or len(result) != len(set(result))
    ):
        raise RuntimeError("expected C4 destination closure drift")
    return result


def _authorized_installed_pins(
    manifest: dict[str, Any], payload: Path
) -> list[dict[str, Any]]:
    pins = {
        item["path"]: {
            "path": item["path"],
            "byteLength": item["byteLength"],
            "sha256": item["sha256"],
        }
        for item in manifest["files"]
    }
    route = load(
        payload / "fixtures/product-prototype/"
        "offenders-remaining-c4-route-manifest-v1.json"
    )
    for member in route.get("members", []):
        path = member.get("workbookPath")
        pin = {
            "path": path,
            "byteLength": member.get("workbookBytes"),
            "sha256": member.get("workbookDigest"),
        }
        if not isinstance(path, str) or (path in pins and pins[path] != pin):
            raise RuntimeError("authorized workbook input closure drift")
        pins[path] = pin
    if len(pins) != 620:
        raise RuntimeError("authorized installed/input closure count")
    return [pins[path] for path in sorted(pins)]


def _verify_installed(manifest: dict[str, Any]) -> None:
    for item in manifest["files"]:
        path = ROOT.joinpath(*PurePosixPath(item["path"]).parts)
        _safe_destination(path)
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"installed proposal file missing: {item['path']}")
        data = path.read_bytes()
        if len(data) != item["byteLength"] or _sha(data) != item["sha256"]:
            raise RuntimeError(f"installed proposal file drift: {item['path']}")


@contextmanager
def _blocked_signals() -> Iterator[None]:
    signals = {signal.SIGINT, signal.SIGTERM}
    if not hasattr(signal, "pthread_sigmask"):
        yield
        return
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _durable_remove(path: Path) -> None:
    _remove(path)
    _fsync_directory(path.parent)


def _durable_replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)
    _fsync_directory(source.parent)
    if destination.parent != source.parent:
        _fsync_directory(destination.parent)


def _rollback(
    items: list[tuple[str, Path, Path]],
    backups: Path,
    existed: dict[str, bool],
) -> list[str]:
    errors = []
    for index in reversed(range(len(items))):
        _kind, source, destination = items[index]
        backup = backups / f"{index:03d}"
        try:
            if backup.exists() or backup.is_symlink():
                if destination.exists() or destination.is_symlink():
                    _durable_remove(destination)
                _durable_replace(backup, destination)
            elif not existed[str(destination)]:
                if destination.exists() or destination.is_symlink():
                    _durable_remove(destination)
            elif not destination.exists() and not source.exists():
                errors.append(f"missing sole backup for {destination}")
        except BaseException as error:  # preserve all other backups for recovery
            errors.append(f"{destination}: {type(error).__name__}: {error}")
    return errors


def _install_unlocked(
    run: Path,
    authority_digest: str,
    inject: Callable[[str, Path], None] | None = None,
) -> None:
    authority = verify_c4_acceptance_authority(
        ROOT, authority_digest, verify_installed_inputs=False
    )
    manifest = validate_manifest(run)
    if authority["proposal"] != {
        "families": manifest["families"],
        "members": manifest["members"],
        "rows": manifest["rows"],
        "payloadRootDigest": manifest["payloadRootDigest"],
        "outputRootDigest": manifest["outputRootDigest"],
    } or authority["installedInputClosure"] != _authorized_installed_pins(
        manifest, run / "payload"
    ):
        raise RuntimeError("proposal or installed-input closure not authorized")

    product_root = ROOT / ".product-prototype"
    if (
        product_root.is_symlink()
        or not product_root.is_dir()
        or product_root.resolve() != product_root.absolute()
    ):
        raise RuntimeError("unsafe C4 transaction parent")
    if TX_ROOT.exists() or TX_ROOT.is_symlink():
        if (
            TX_ROOT.is_symlink()
            or not TX_ROOT.is_dir()
            or TX_ROOT.resolve() != TX_ROOT.absolute()
        ):
            raise RuntimeError("unsafe C4 transaction root")
    else:
        TX_ROOT.mkdir(mode=0o700)
        _fsync_directory(product_root)
    token = uuid.uuid4().hex
    transaction = TX_ROOT / f"transaction-{token}"
    transaction.mkdir(mode=0o700)
    _fsync_directory(TX_ROOT)
    journal_path = transaction / "journal.json"
    owner = {
        "token": token,
        "pid": os.getpid(),
        "proposal": manifest["outputRootDigest"],
    }
    prior_owner = os.environ.get("TIDY_C4_INSTALL_OWNER")
    journal: dict[str, Any] = {
        **owner,
        "phase": "staging",
        "operation": None,
        "items": [],
        "existed": {},
    }
    try:
        _write_durable(transaction / "owner.json", owner)
        _write_durable(journal_path, journal)
    except BaseException:
        shutil.rmtree(transaction, ignore_errors=True)
        _fsync_directory(TX_ROOT)
        raise
    completed = False
    lock_owned = False
    rollback_errors: list[str] = []
    try:
        staged_run = transaction / "proposal"
        staged_run.mkdir()
        shutil.copytree(run / "payload", staged_run / "payload")
        shutil.copyfile(run / "manifest.json", staged_run / "manifest.json")
        staged_manifest = validate_manifest(staged_run)
        if staged_manifest != manifest:
            raise RuntimeError("staged immutable proposal drift")
        payload_items = _replacement_items(staged_run / "payload")
        generated_snapshot = transaction / "generated/data-asset-status-index.html"
        snapshot_destination = ROOT / "docs/data-asset-status/index.html"
        _safe_destination(snapshot_destination)
        items = [
            *payload_items,
            ("generated-status", generated_snapshot, snapshot_destination),
        ]
        if [
            destination.relative_to(ROOT).as_posix()
            for _kind, _source, destination in items
        ] != _expected_destination_paths(manifest):
            raise RuntimeError("transaction destination closure drift")
        backups = transaction / "backups"
        backups.mkdir()
        _fsync_directory(transaction)
        existed = {
            str(destination): destination.exists() for _, _, destination in items
        }
        journal.update(
            {
                "phase": "ready",
                "items": [
                    str(destination.relative_to(ROOT)) for _, _, destination in items
                ],
                "existed": existed,
            }
        )
        _write_durable(journal_path, journal)
        try:
            _create_lock_durable(owner)
        except BaseException:
            try:
                lock_owned = load(TX_LOCK) == owner
            except (OSError, json.JSONDecodeError, RuntimeError):
                lock_owned = False
            raise
        lock_owned = True
        os.environ["TIDY_C4_INSTALL_OWNER"] = token
        journal["phase"] = "swapping"
        _write_durable(journal_path, journal)
        with _blocked_signals():
            try:
                for index, (_kind, _source, destination) in enumerate(items):
                    journal["operation"] = {"kind": "backup", "index": index}
                    _write_durable(journal_path, journal)
                    _inject_hook(inject, f"before-backup-{index}", destination)
                    if existed[str(destination)]:
                        _durable_replace(destination, backups / f"{index:03d}")
                    _inject_hook(inject, f"after-backup-{index}", destination)
                for index, (kind, source, destination) in enumerate(payload_items):
                    journal["operation"] = {"kind": "install", "index": index}
                    _write_durable(journal_path, journal)
                    _inject_hook(inject, f"before-install-{index}", destination)
                    _durable_replace(source, destination)
                    if inject:
                        inject(kind, destination)
                    _inject_hook(inject, f"after-install-{index}", destination)
                journal.update({"phase": "validating", "operation": None})
                _write_durable(journal_path, journal)
                _verify_installed(manifest)
                report = verify_offenders_release(ROOT)
                if (
                    report["registeredMemberCount"] != 190
                    or report["pendingSemanticContractCount"] != 0
                ):
                    raise RuntimeError("Offenders registration did not close")
                registry = load_large_batch_registry(ROOT)
                if len(registry.entries) != 288 or registry.worksheet_count != 798:
                    raise RuntimeError("registry did not close")
                verify_batch_normalization(ROOT, registry)
                for spec in registry.entries:
                    if spec.replay_engine == "offenders-remaining-c4-v1":
                        verify_large_batch_evidence(ROOT, spec)
                dashboard = build_dashboard(ROOT)
                if (
                    len(dashboard.cohorts) != 293
                    or len(dashboard.assets) != 823
                    or sum(asset.canonical_count or 0 for asset in dashboard.assets)
                    != 751237
                ):
                    raise RuntimeError("C4 status dashboard closure did not close")
                snapshot_bytes = render_dashboard(dashboard)
                snapshot_pin = authority["generatedOutputClosure"][0]
                if (
                    snapshot_pin["path"] != "docs/data-asset-status/index.html"
                    or snapshot_pin["byteLength"] != len(snapshot_bytes)
                    or snapshot_pin["sha256"] != _sha(snapshot_bytes)
                ):
                    raise RuntimeError("generated status snapshot is not authorized")
                _write_raw_durable(generated_snapshot, snapshot_bytes)
                generated_index = len(payload_items)
                journal["operation"] = {
                    "kind": "install-generated-status",
                    "index": generated_index,
                }
                _write_durable(journal_path, journal)
                _durable_replace(generated_snapshot, snapshot_destination)
                _inject_hook(inject, "generated-status", snapshot_destination)
                verify_c4_acceptance_authority(
                    ROOT, authority_digest, verify_installed_inputs=True
                )
                matches, _output, _expected, _actual = snapshot_matches(ROOT)
                if not matches:
                    raise RuntimeError("generated status snapshot did not close")
                _inject_hook(inject, "post-swap-validation", ROOT)
            except BaseException:
                journal_write_errors: list[str] = []
                journal.update({"phase": "rolling-back", "operation": None})
                try:
                    _write_durable(journal_path, journal)
                except BaseException as error:
                    journal_write_errors.append(
                        f"rolling-back journal: {type(error).__name__}: {error}"
                    )
                try:
                    _inject_hook(inject, "rollback-interruption", ROOT)
                except BaseException as error:
                    journal_write_errors.append(
                        f"rollback hook: {type(error).__name__}: {error}"
                    )
                rollback_errors = _rollback(items, backups, existed)
                journal.update(
                    {
                        "phase": "rollback-failed"
                        if rollback_errors or journal_write_errors
                        else "rolled-back",
                        "rollbackErrors": [*rollback_errors, *journal_write_errors],
                    }
                )
                try:
                    _write_durable(journal_path, journal)
                except BaseException as error:
                    journal_write_errors.append(
                        f"rollback result journal: {type(error).__name__}: {error}"
                    )
                rollback_errors.extend(journal_write_errors)
                raise
            journal.update({"phase": "committed", "operation": None})
            _write_durable(journal_path, journal)
            _durable_remove(backups)
            completed = True
    finally:
        resolved = (
            not lock_owned
            or completed
            or (
                journal.get("phase") in {"staging", "swapping", "rolled-back"}
                and not rollback_errors
            )
        )
        if resolved:
            _durable_remove(transaction)
            if lock_owned:
                TX_LOCK.unlink(missing_ok=True)
                _fsync_directory(TX_ROOT)
            if prior_owner is None:
                os.environ.pop("TIDY_C4_INSTALL_OWNER", None)
            else:
                os.environ["TIDY_C4_INSTALL_OWNER"] = prior_owner
        if rollback_errors:
            raise RuntimeError(
                "C4 rollback incomplete; lock and transaction retained for "
                "owner-aware recovery: " + "; ".join(rollback_errors)
            )


def install(
    run: Path,
    authority_digest: str,
    inject: Callable[[str, Path], None] | None = None,
) -> None:
    with c4_exclusive_access(ROOT), _blocked_signals():
        _install_unlocked(run, authority_digest, inject)


def recover(
    recovery_token: str,
    action: str,
    authority_digest: str | None = None,
) -> None:
    """Resolve only the exact durable transaction owned by ``recovery_token``."""
    if not re.fullmatch(r"[0-9a-f]{32}", recovery_token):
        raise RuntimeError("invalid C4 recovery token")
    lock = load(TX_LOCK)
    if lock.get("token") != recovery_token:
        raise RuntimeError("C4 recovery token does not own install lock")
    transaction = TX_ROOT / f"transaction-{recovery_token}"
    owner = load(transaction / "owner.json")
    journal_path = transaction / "journal.json"
    journal = load(journal_path)
    if owner != lock or any(journal.get(key) != value for key, value in owner.items()):
        raise RuntimeError("C4 recovery ownership drift")
    previous = os.environ.get("TIDY_C4_INSTALL_OWNER")
    os.environ["TIDY_C4_INSTALL_OWNER"] = recovery_token
    resolved = False
    try:
        with c4_exclusive_access(ROOT):
            if action == "finalize":
                if journal.get("phase") != "committed" or not authority_digest:
                    raise RuntimeError(
                        "only a committed authorized transaction can finalize"
                    )
                verify_c4_acceptance_authority(
                    ROOT, authority_digest, verify_installed_inputs=True
                )
            elif action == "rollback":
                phase = journal.get("phase")
                if phase == "committed":
                    raise RuntimeError(
                        "committed transaction requires finalize recovery"
                    )
                relative_items = journal.get("items")
                existed = journal.get("existed")
                backups = transaction / "backups"
                if phase == "staging":
                    if (
                        relative_items != []
                        or existed != {}
                        or (backups.exists() and any(backups.iterdir()))
                    ):
                        raise RuntimeError("C4 staging recovery closure drift")
                    errors: list[str] = []
                else:
                    if phase not in {
                        "ready",
                        "swapping",
                        "validating",
                        "rolling-back",
                        "rollback-failed",
                        "rolled-back",
                    }:
                        raise RuntimeError("C4 recovery phase is invalid")
                    manifest = load(transaction / "proposal/manifest.json")
                    if manifest.get("outputRootDigest") != owner["proposal"]:
                        raise RuntimeError("C4 recovery proposal ownership drift")
                    expected_paths = _expected_destination_paths(manifest)
                    if (
                        relative_items != expected_paths
                        or len(relative_items) != 316
                        or len(set(relative_items)) != 316
                        or not isinstance(existed, dict)
                    ):
                        raise RuntimeError(
                            "C4 recovery journal destination closure drift"
                        )
                    items = []
                    for relative in relative_items:
                        pure = PurePosixPath(relative)
                        destination = ROOT.joinpath(*pure.parts)
                        _safe_destination(destination)
                        items.append(("recovery", transaction / "unused", destination))
                    if set(existed) != {str(item[2]) for item in items} or any(
                        type(value) is not bool for value in existed.values()
                    ):
                        raise RuntimeError("C4 recovery existence closure drift")
                    errors = _rollback(items, backups, existed)
                journal.update(
                    {
                        "phase": "rollback-failed" if errors else "rolled-back",
                        "operation": None,
                        "rollbackErrors": errors,
                    }
                )
                _write_durable(journal_path, journal)
                if errors:
                    raise RuntimeError(
                        "C4 recovery incomplete; ownership retained: "
                        + "; ".join(errors)
                    )
            else:
                raise RuntimeError("unknown C4 recovery action")
            _durable_remove(transaction)
            TX_LOCK.unlink()
            _fsync_directory(TX_ROOT)
            resolved = True
    finally:
        if resolved:
            if previous is None:
                os.environ.pop("TIDY_C4_INSTALL_OWNER", None)
            else:
                os.environ["TIDY_C4_INSTALL_OWNER"] = previous


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check-proposal", action="store_true")
    parser.add_argument(
        "--run",
        default=".product-prototype/offenders-remaining-phase1/c4-proposal/run-a",
    )
    parser.add_argument("--compare")
    parser.add_argument("--authority-digest")
    parser.add_argument("--recover", choices=("rollback", "finalize"))
    parser.add_argument("--recovery-token")
    args = parser.parse_args()
    modes = int(args.write) + int(args.check_proposal) + int(args.recover is not None)
    if modes != 1:
        parser.error("choose exactly one mode")
    if args.recover:
        if not args.recovery_token:
            raise SystemExit("--recovery-token is required for --recover")
        recover(args.recovery_token, args.recover, args.authority_digest)
        print(json.dumps({"recovered": args.recover}, separators=(",", ":")))
        return 0
    run = (ROOT / args.run).resolve()
    manifest = validate_manifest(run)
    if args.compare:
        compare(run, (ROOT / args.compare).resolve())
    if args.write:
        if not args.authority_digest:
            raise SystemExit("--authority-digest is required for --write")
        install(run, args.authority_digest)
    future_paths = {
        *(
            item["path"]
            for item in _authorized_installed_pins(manifest, run / "payload")
        ),
        *required_c4_runtime_paths(ROOT),
        *required_c4_toolchain_paths(ROOT),
        "fixtures/product-prototype/reviews/offenders-remaining-c4-review-decision-v1.json",
        "fixtures/product-prototype/offenders-remaining-c4-acceptance-authorization-v1.json",
        "docs/data-asset-status/index.html",
    }
    untracked = validate_c4_clean_checkout_tracking(ROOT, future_paths)
    print(
        json.dumps(
            {
                "families": manifest["families"],
                "members": manifest["members"],
                "rows": manifest["rows"],
                "payloadRootDigest": manifest["payloadRootDigest"],
                "outputRootDigest": manifest["outputRootDigest"],
                "installed": args.write,
                "futureTracking": {
                    "required": len(future_paths),
                    "untracked": len(untracked),
                    "untrackedPaths": untracked,
                },
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
