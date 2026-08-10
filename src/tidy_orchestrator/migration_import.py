"""Provider-free Phase B import/reconciliation with split metadata and blob roots.

The module intentionally exposes fixture-test authorization only. It can prove the
restart, idempotence, custody, and reconciliation protocol without authorizing the
real TidyCell export or placing SQLite on SMB.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import stat
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .artifacts import canonical_json_bytes, domain_digest, sha256_digest
from .source_export import load_and_verify_export

_IMPORT_ITEM_VERSION = "tidy.migration-import-item/v1"
_RECONCILIATION_VERSION = "tidy.migration-reconciliation/v1"
_SNAPSHOT_REGISTRATION_VERSION = "tidy.migration-snapshot-registration/v1"
_BLOB_COMMIT_VERSION = "tidy.committed-blob/v1"
_IMPORTER_VERSION = "tidy.migration-importer/v1"
_SCHEMA_VERSION = 2
_READ_CHUNK = 1024 * 1024
_MAX_SNAPSHOT_BYTES = 1024 * 1024 * 1024
_DIGEST_PREFIX = "sha256:"
_COPY_DISPOSITIONS = frozenset(("import", "duplicate-alias", "quarantine"))
_TYPED_ID_FIELDS = {
    "tidy.approval-registry-evidence-import/v1": "recordId",
    "tidy.approval-resolution/v1": "resolutionId",
    "tidy.generation-evidence-import/v1": "recordId",
    "tidy.legacy-approval-snapshot/v1": "approvalSnapshotId",
    "tidy.model-package-disposition/v1": "recordId",
    "tidy.recipe-digest-verification/v1": "verificationId",
    "tidy.recipe-evidence-import/v1": "recordId",
    "tidy.reviewer-identity/v1": "reviewerId",
    "tidy.semantic-import-reconciliation/v1": "recordId",
}
_RESTRICTED_CLASSES = frozenset(
    (
        "approval-registry",
        "catalog-evidence",
        "generation-json-evidence",
        "harvest-evidence",
        "ml-evidence",
        "model-binary",
        "research-evidence",
        "recipe-evidence",
    )
)


class MigrationImportError(RuntimeError):
    """Base error for the provider-free migration importer."""


class ImportAuthorizationError(MigrationImportError):
    """The caller did not hold a bounded fixture-only authorization."""


class SourceItemMismatch(MigrationImportError):
    """Source bytes or filesystem identity differed from the frozen snapshot."""


class BlobIntegrityError(MigrationImportError):
    """A committed content-addressed blob was unsafe or inconsistent."""


class MigrationRecordConflict(MigrationImportError):
    """An immutable migration record already existed with different bytes."""


class IncompleteMigration(MigrationImportError):
    """Reconciliation was attempted before every source item was recorded."""


@dataclass(frozen=True)
class FixtureImportAuthorization:
    """Bounded authority that cannot cover the real Phase A estate."""

    snapshot_digest: str
    source_device_id: int
    source_root_inode: int
    max_items: int = 1000
    max_source_bytes: int = 64 * 1024 * 1024
    mode: Literal["fixture-test-only"] = "fixture-test-only"

    def __post_init__(self) -> None:
        if not 1 <= self.max_items <= 1000:
            raise ValueError("Fixture authorization max_items is out of range")
        if not 1 <= self.max_source_bytes <= 64 * 1024 * 1024:
            raise ValueError("Fixture authorization max_source_bytes is out of range")

    @classmethod
    def create(
        cls,
        *,
        snapshot: Mapping[str, Any],
        source_root: Path,
        max_items: int = 1000,
        max_source_bytes: int = 64 * 1024 * 1024,
    ) -> FixtureImportAuthorization:
        root = _validated_directory(source_root, "fixture source root")
        info = root.lstat()
        return cls(
            snapshot_digest=_require_digest(str(snapshot["snapshotDigest"])),
            source_device_id=info.st_dev,
            source_root_inode=info.st_ino,
            max_items=max_items,
            max_source_bytes=max_source_bytes,
        )

    def validate(self, snapshot: Mapping[str, Any], source_root: Path) -> None:
        if self.mode != "fixture-test-only":
            raise ImportAuthorizationError("Only fixture-test import is implemented")
        if snapshot["snapshotDigest"] != self.snapshot_digest:
            raise ImportAuthorizationError("Authorization binds a different snapshot")
        source = snapshot["inventory"]["source"]
        if source["sourceSystem"] != "phase-b-fixture":
            raise ImportAuthorizationError(
                "Fixture authorization cannot import a non-fixture source system"
            )
        filesystem = source["filesystem"]
        root = _validated_directory(source_root, "fixture source root")
        info = root.lstat()
        if (info.st_dev, info.st_ino) != (
            self.source_device_id,
            self.source_root_inode,
        ):
            raise ImportAuthorizationError(
                "Authorization binds a different source root"
            )
        if (info.st_dev, info.st_ino, info.st_mode) != (
            filesystem["deviceId"],
            filesystem["rootInode"],
            filesystem["rootMode"],
        ):
            raise ImportAuthorizationError("Source root differs from snapshot identity")
        items = snapshot["inventory"]["items"]
        source_bytes = sum(
            int(item["byteLength"]) for item in items if item["entryType"] == "file"
        )
        if len(items) > self.max_items or source_bytes > self.max_source_bytes:
            raise ImportAuthorizationError(
                "Snapshot exceeds fixture-only item or byte authorization"
            )


@dataclass(frozen=True)
class ImportProgress:
    run_id: str
    snapshot_digest: str
    recorded_items: int
    total_items: int
    complete: bool


class CommittedFilesystemBlobStore:
    """Content-addressed files published with a commit marker, without hard links."""

    def __init__(self, root: Path | str) -> None:
        self.root = _ensure_private_directory(Path(root), "blob-store root")
        self.objects = _ensure_private_directory(self.root / "objects", "objects")
        self.staging = _ensure_private_directory(self.root / "staging", "staging")
        self.orphaned = _ensure_private_directory(self.root / "orphaned", "orphaned")

    @property
    def store_id(self) -> str:
        return "committed-filesystem-sha256-v1"

    def object_directory(self, digest: str) -> Path:
        hexadecimal = _require_digest(digest).split(":", 1)[1]
        return self.objects / hexadecimal[:2] / hexadecimal[2:]

    def storage_uri(self, digest: str) -> str:
        _require_digest(digest)
        return f"cas+sha256://{digest}"

    def publish_from_descriptor(
        self,
        descriptor: int,
        *,
        expected_digest: str,
        expected_length: int,
    ) -> bool:
        """Verify source bytes and publish once. Return True only for a new object."""

        _require_digest(expected_digest)
        if expected_length < 0:
            raise ValueError("expected_length must be non-negative")
        target = self.object_directory(expected_digest)
        self._ensure_shard(target.parent)
        if os.path.lexists(target):
            if self._is_committed(target):
                self._hash_source_descriptor(
                    descriptor,
                    expected_digest=expected_digest,
                    expected_length=expected_length,
                )
                self.verify(expected_digest, expected_length)
                return False
            self._move_incomplete_to_orphaned(target, expected_digest)

        stage = self.staging / f"stage-{uuid.uuid4().hex}"
        stage.mkdir(mode=0o700)
        os.chmod(stage, 0o700)
        stage_blob = stage / "blob"
        created_target = False
        try:
            self._copy_source_to_stage(
                descriptor,
                stage_blob,
                expected_digest=expected_digest,
                expected_length=expected_length,
            )
            try:
                target.mkdir(mode=0o700)
                created_target = True
            except FileExistsError:
                if not self._is_committed(target):
                    raise BlobIntegrityError(
                        "Concurrent blob publication left an incomplete target"
                    ) from None
                self.verify(expected_digest, expected_length)
                return False
            os.chmod(target, 0o700)
            _fsync_directory(target.parent)
            os.rename(stage_blob, target / "blob")
            commit = {
                "schemaVersion": _BLOB_COMMIT_VERSION,
                "contentDigest": expected_digest,
                "byteLength": expected_length,
            }
            _write_commit_marker(target, commit)
            _fsync_directory(target)
            _fsync_directory(target.parent)
            self.verify(expected_digest, expected_length)
            return True
        except BaseException:
            if created_target and target.exists():
                self._move_incomplete_to_orphaned(target, expected_digest)
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            _fsync_directory(self.staging)

    def verify(self, digest: str, expected_length: int) -> None:
        target = self.object_directory(digest)
        target = _validated_directory(target, "committed blob")
        names = sorted(path.name for path in target.iterdir())
        if names != ["COMMITTED.json", "blob"]:
            raise BlobIntegrityError("Committed blob directory has unexpected files")
        commit_data = _read_regular(target / "COMMITTED.json", maximum=1024 * 1024)
        commit = _strict_json(commit_data, "blob commit marker")
        expected = {
            "schemaVersion": _BLOB_COMMIT_VERSION,
            "contentDigest": _require_digest(digest),
            "byteLength": expected_length,
        }
        if commit != expected or commit_data != canonical_json_bytes(expected) + b"\n":
            raise BlobIntegrityError("Blob commit marker is invalid")
        info = (target / "blob").lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise BlobIntegrityError("Committed blob is not a regular file")
        if info.st_mode & 0o077 or target.lstat().st_mode & 0o077:
            raise BlobIntegrityError("Committed blob is not private")
        if info.st_size != expected_length:
            raise BlobIntegrityError("Committed blob length differs")
        digest_value, length = _hash_regular_path(target / "blob", expected_length)
        if digest_value != digest or length != expected_length:
            raise BlobIntegrityError("Committed blob digest differs")
        expected_name = digest.split(":", 1)[1][2:]
        if target.name != expected_name:
            raise BlobIntegrityError("Committed blob directory has wrong identity")

    def read_verified(self, digest: str, expected_length: int) -> bytes:
        self.verify(digest, expected_length)
        return _read_regular(
            self.object_directory(digest) / "blob", maximum=expected_length
        )

    def committed_digests(self) -> tuple[str, ...]:
        values: list[str] = []
        for shard in sorted(self.objects.iterdir()):
            if not shard.is_dir() or shard.is_symlink() or len(shard.name) != 2:
                raise BlobIntegrityError("Blob store contains an invalid shard")
            for target in sorted(shard.iterdir()):
                digest = f"sha256:{shard.name}{target.name}"
                if self._is_committed(target):
                    values.append(_require_digest(digest))
                else:
                    raise BlobIntegrityError("Blob store contains incomplete content")
        return tuple(values)

    def _is_committed(self, target: Path) -> bool:
        if target.is_symlink() or not target.is_dir():
            return False
        return (target / "COMMITTED.json").is_file()

    def _ensure_shard(self, shard: Path) -> None:
        with suppress(FileExistsError):
            shard.mkdir(mode=0o700)
        _validated_directory(shard, "blob shard")
        os.chmod(shard, 0o700)
        _fsync_directory(self.objects)

    def _move_incomplete_to_orphaned(self, target: Path, digest: str) -> None:
        if target.is_symlink() or not target.is_dir():
            raise BlobIntegrityError("Incomplete blob target is unsafe")
        name = f"{digest.split(':', 1)[1]}-{uuid.uuid4().hex}"
        destination = self.orphaned / name
        os.rename(target, destination)
        _fsync_directory(target.parent)
        _fsync_directory(self.orphaned)

    @staticmethod
    def _hash_source_descriptor(
        descriptor: int,
        *,
        expected_digest: str,
        expected_length: int,
    ) -> None:
        digest = hashlib.sha256()
        length = 0
        while True:
            chunk = os.read(descriptor, _READ_CHUNK)
            if not chunk:
                break
            length += len(chunk)
            if length > expected_length:
                raise SourceItemMismatch("Source file exceeded frozen byte length")
            digest.update(chunk)
        if (
            length != expected_length
            or f"sha256:{digest.hexdigest()}" != expected_digest
        ):
            raise SourceItemMismatch("Source bytes differ from frozen snapshot")

    @staticmethod
    def _copy_source_to_stage(
        descriptor: int,
        stage: Path,
        *,
        expected_digest: str,
        expected_length: int,
    ) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        target = os.open(stage, flags, 0o600)
        digest = hashlib.sha256()
        length = 0
        try:
            os.fchmod(target, 0o600)
            while True:
                chunk = os.read(descriptor, _READ_CHUNK)
                if not chunk:
                    break
                length += len(chunk)
                if length > expected_length:
                    raise SourceItemMismatch("Source file exceeded frozen byte length")
                digest.update(chunk)
                _write_all(target, chunk)
            os.fsync(target)
        finally:
            os.close(target)
        if (
            length != expected_length
            or f"sha256:{digest.hexdigest()}" != expected_digest
        ):
            stage.unlink(missing_ok=True)
            raise SourceItemMismatch("Source bytes differ from frozen snapshot")


class MigrationRepository:
    """Local SQLite authority for import records; it never owns large blobs."""

    def __init__(
        self,
        root: Path | str,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.root = _ensure_private_directory(Path(root), "migration metadata root")
        self.database = self.root / "migration.sqlite3"
        self._fault = fault_injector
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL "
                "DEFAULT CURRENT_TIMESTAMP)"
            )
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
            if current > _SCHEMA_VERSION:
                raise MigrationImportError(f"Unsupported migration schema {current}")
            if current < 1:
                statements = (
                    "CREATE TABLE snapshots (snapshot_digest TEXT PRIMARY KEY, "
                    "inventory_digest TEXT NOT NULL, "
                    "item_manifest_digest TEXT NOT NULL, "
                    "snapshot_file_digest TEXT NOT NULL, storage_uri TEXT NOT NULL, "
                    "record_json BLOB NOT NULL)",
                    "CREATE TABLE contents (content_digest TEXT PRIMARY KEY, "
                    "byte_length INTEGER NOT NULL CHECK(byte_length >= 0), "
                    "storage_uri TEXT NOT NULL, record_json BLOB NOT NULL)",
                    "CREATE TABLE import_items (snapshot_digest TEXT NOT NULL "
                    "REFERENCES snapshots(snapshot_digest), "
                    "relative_path TEXT NOT NULL, final_state TEXT NOT NULL, "
                    "content_digest TEXT, record_json BLOB NOT NULL, "
                    "PRIMARY KEY(snapshot_digest, relative_path))",
                    "CREATE TABLE aliases (alias_id TEXT PRIMARY KEY, "
                    "snapshot_digest TEXT NOT NULL, relative_path TEXT NOT NULL, "
                    "content_digest TEXT, record_json BLOB NOT NULL)",
                    "CREATE TABLE reconciliations (report_digest TEXT PRIMARY KEY, "
                    "snapshot_digest TEXT NOT NULL, record_json BLOB NOT NULL)",
                    "INSERT INTO schema_migrations(version) VALUES (1)",
                )
                for statement in statements:
                    connection.execute(statement)
            if current < 2:
                connection.execute(
                    "CREATE TABLE typed_records (record_id TEXT PRIMARY KEY, "
                    "record_type TEXT NOT NULL, record_json BLOB NOT NULL)"
                )
                connection.execute("INSERT INTO schema_migrations(version) VALUES (2)")
            connection.commit()
        os.chmod(self.database, 0o600)

    def register_snapshot(
        self,
        *,
        snapshot: Mapping[str, Any],
        snapshot_file_digest: str,
        storage_uri: str,
        importer_digest: str,
    ) -> None:
        record = {
            "schemaVersion": _SNAPSHOT_REGISTRATION_VERSION,
            "snapshotDigest": snapshot["snapshotDigest"],
            "inventoryDigest": snapshot["inventory"]["inventoryDigest"],
            "itemManifestDigest": snapshot["inventory"]["itemManifestDigest"],
            "snapshotFileDigest": _require_digest(snapshot_file_digest),
            "storageUri": storage_uri,
            "importerDigest": _require_digest(importer_digest),
            "sourceRootId": snapshot["inventory"]["source"]["sourceRootId"],
            "itemCount": snapshot["inventory"]["summary"]["itemCount"],
        }
        wire = canonical_json_bytes(record)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_immutable(
                connection,
                "snapshots",
                "snapshot_digest",
                snapshot["snapshotDigest"],
                wire,
                (
                    ("inventory_digest", snapshot["inventory"]["inventoryDigest"]),
                    (
                        "item_manifest_digest",
                        snapshot["inventory"]["itemManifestDigest"],
                    ),
                    ("snapshot_file_digest", snapshot_file_digest),
                    ("storage_uri", storage_uri),
                ),
            )
            connection.commit()

    def record_item(
        self,
        *,
        record: Mapping[str, Any],
        content_record: Mapping[str, Any] | None,
        alias_record: Mapping[str, Any],
    ) -> None:
        snapshot_digest = str(record["snapshotDigest"])
        relative_path = str(record["relativePath"])
        wire = canonical_json_bytes(record)
        alias_wire = canonical_json_bytes(alias_record)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if content_record is not None:
                    content_wire = canonical_json_bytes(content_record)
                    self._insert_immutable(
                        connection,
                        "contents",
                        "content_digest",
                        str(content_record["contentDigest"]),
                        content_wire,
                        (
                            ("byte_length", int(content_record["byteLength"])),
                            ("storage_uri", str(content_record["storageUri"])),
                        ),
                    )
                self._insert_composite_item(
                    connection,
                    snapshot_digest=snapshot_digest,
                    relative_path=relative_path,
                    final_state=str(record["finalState"]),
                    content_digest=record.get("contentDigest"),
                    wire=wire,
                )
                self._insert_immutable(
                    connection,
                    "aliases",
                    "alias_id",
                    str(alias_record["aliasId"]),
                    alias_wire,
                    (
                        ("snapshot_digest", snapshot_digest),
                        ("relative_path", relative_path),
                        ("content_digest", alias_record.get("contentDigest")),
                    ),
                )
                self._inject("before_item_commit")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def get_snapshot_registration(self, snapshot_digest: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM snapshots WHERE snapshot_digest=?",
                (_require_digest(snapshot_digest),),
            ).fetchone()
        if row is None:
            raise MigrationImportError("Snapshot registration was not found")
        return json.loads(row[0])

    def get_item(
        self, snapshot_digest: str, relative_path: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM import_items WHERE snapshot_digest=? "
                "AND relative_path=?",
                (snapshot_digest, relative_path),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def list_items(self, snapshot_digest: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM import_items WHERE snapshot_digest=? "
                "ORDER BY relative_path",
                (snapshot_digest,),
            ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def list_aliases(self, snapshot_digest: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM aliases WHERE snapshot_digest=? "
                "ORDER BY relative_path",
                (_require_digest(snapshot_digest),),
            ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def list_contents(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM contents ORDER BY content_digest"
            ).fetchall()
        return tuple(json.loads(row[0]) for row in rows)

    def add_typed_record(
        self,
        *,
        record_id: str,
        record_type: str,
        record: Mapping[str, Any],
    ) -> None:
        if (
            not isinstance(record_type, str)
            or not record_type
            or len(record_type) > 128
            or record.get("schemaVersion") != record_type
        ):
            raise ValueError("record_type must equal the record schemaVersion")
        identity = _validate_typed_record_identity(
            record_id=record_id,
            record_type=record_type,
            record=record,
        )
        wire = canonical_json_bytes(record)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_immutable(
                connection,
                "typed_records",
                "record_id",
                identity,
                wire,
                (("record_type", record_type),),
            )
            connection.commit()

    def list_typed_records(
        self,
        *,
        record_type: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        query = "SELECT record_id, record_type, record_json FROM typed_records"
        parameters: tuple[str, ...] = ()
        if record_type is not None:
            query += " WHERE record_type=?"
            parameters = (record_type,)
        query += " ORDER BY record_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            record = json.loads(row[2])
            _validate_typed_record_identity(
                record_id=row[0],
                record_type=row[1],
                record=record,
            )
            records.append(record)
        return tuple(records)

    def add_reconciliation(self, report: Mapping[str, Any]) -> None:
        wire = canonical_json_bytes(report)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_immutable(
                connection,
                "reconciliations",
                "report_digest",
                str(report["reportDigest"]),
                wire,
                (("snapshot_digest", str(report["snapshotDigest"])),),
            )
            connection.commit()

    def get_reconciliation(self, report_digest: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM reconciliations WHERE report_digest=?",
                (_require_digest(report_digest),),
            ).fetchone()
        if row is None:
            raise MigrationImportError("Reconciliation report was not found")
        return json.loads(row[0])

    @staticmethod
    def _insert_immutable(
        connection: sqlite3.Connection,
        table: str,
        id_column: str,
        identity: str,
        wire: bytes,
        extras: Sequence[tuple[str, Any]],
    ) -> None:
        row = connection.execute(
            f"SELECT record_json FROM {table} WHERE {id_column}=?",
            (identity,),
        ).fetchone()
        if row is not None:
            if bytes(row[0]) != wire:
                raise MigrationRecordConflict(f"Conflicting {table} record {identity}")
            return
        columns = [id_column, *(name for name, _value in extras), "record_json"]
        values = [identity, *(value for _name, value in extras), wire]
        placeholders = ",".join("?" for _value in values)
        connection.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",
            values,
        )

    @staticmethod
    def _insert_composite_item(
        connection: sqlite3.Connection,
        *,
        snapshot_digest: str,
        relative_path: str,
        final_state: str,
        content_digest: Any,
        wire: bytes,
    ) -> None:
        row = connection.execute(
            "SELECT record_json FROM import_items WHERE snapshot_digest=? "
            "AND relative_path=?",
            (snapshot_digest, relative_path),
        ).fetchone()
        if row is not None:
            if bytes(row[0]) != wire:
                raise MigrationRecordConflict(
                    f"Conflicting import item {snapshot_digest}:{relative_path}"
                )
            return
        connection.execute(
            "INSERT INTO import_items(snapshot_digest, relative_path, final_state, "
            "content_digest, record_json) VALUES (?, ?, ?, ?, ?)",
            (snapshot_digest, relative_path, final_state, content_digest, wire),
        )

    def _inject(self, point: str) -> None:
        if self._fault is not None:
            self._fault(point)


class MigrationImporter:
    """Restartable item importer with fixture-only execution authority."""

    def __init__(
        self,
        *,
        snapshot_path: Path,
        source_root: Path,
        metadata: MigrationRepository,
        blobs: CommittedFilesystemBlobStore,
        authorization: FixtureImportAuthorization,
        recorded_at: str,
        actor: str = "phase-b-fixture-importer",
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        snapshot, digest = load_and_verify_export(snapshot_path)
        if snapshot["schemaVersion"] != "tidy.source-export-snapshot/v1":
            raise MigrationImportError("Importer requires a frozen source snapshot")
        if digest != snapshot["snapshotDigest"]:
            raise MigrationImportError("Snapshot identity did not verify")
        authorization.validate(snapshot, source_root)
        _require_separate_trees(
            metadata.root,
            blobs.root,
            "metadata and blob roots",
        )
        validated_source_root = _validated_directory(source_root, "fixture source root")
        _require_separate_trees(
            validated_source_root,
            metadata.root,
            "source and metadata roots",
        )
        if validated_source_root.lstat().st_dev != metadata.root.lstat().st_dev:
            raise MigrationImportError(
                "SQLite metadata must share the fixture source's local filesystem"
            )
        _require_separate_trees(
            validated_source_root,
            blobs.root,
            "source and blob roots",
        )
        snapshot_bytes = _read_regular(snapshot_path, maximum=_MAX_SNAPSHOT_BYTES)
        if _strict_json(snapshot_bytes, "source snapshot") != snapshot:
            raise MigrationImportError("Snapshot changed between verification reads")
        self.snapshot = snapshot
        self.snapshot_path = snapshot_path
        self.snapshot_file_digest = sha256_digest(snapshot_bytes)
        self.snapshot_file_length = len(snapshot_bytes)
        self.source_root = validated_source_root
        self.metadata = metadata
        self.blobs = blobs
        self.authorization = authorization
        self.recorded_at = _require_utc_timestamp(recorded_at)
        if not isinstance(actor, str) or not actor or len(actor) > 256:
            raise MigrationImportError("Import actor is invalid")
        self.actor = actor
        self._fault = fault_injector
        self.importer_digest = _importer_source_digest()
        self.run_id = domain_digest(
            "tidy.migration-run/v1",
            {
                "snapshotDigest": snapshot["snapshotDigest"],
                "snapshotFileDigest": self.snapshot_file_digest,
                "importerDigest": self.importer_digest,
                "blobStoreId": blobs.store_id,
                "recordedAt": recorded_at,
                "actor": actor,
                "authorizationMode": authorization.mode,
            },
        )

    def run(self, *, max_new_items: int | None = None) -> ImportProgress:
        if max_new_items is not None and max_new_items < 0:
            raise ValueError("max_new_items must not be negative")
        snapshot_bytes = _read_regular(self.snapshot_path, maximum=_MAX_SNAPSHOT_BYTES)
        snapshot_file_digest = sha256_digest(snapshot_bytes)
        if (
            snapshot_file_digest != self.snapshot_file_digest
            or len(snapshot_bytes) != self.snapshot_file_length
        ):
            raise MigrationImportError("Snapshot changed before import")
        with _open_regular_descriptor(self.snapshot_path) as descriptor:
            self.blobs.publish_from_descriptor(
                descriptor,
                expected_digest=snapshot_file_digest,
                expected_length=len(snapshot_bytes),
            )
        self._inject("after_snapshot_blob_before_metadata")
        self.metadata.register_snapshot(
            snapshot=self.snapshot,
            snapshot_file_digest=snapshot_file_digest,
            storage_uri=self.blobs.storage_uri(snapshot_file_digest),
            importer_digest=self.importer_digest,
        )

        added = 0
        verified_blobs: set[str] = set()
        items = self.snapshot["inventory"]["items"]
        with _SourceTree(self.source_root, self.snapshot) as source:
            for item in items:
                existing = self.metadata.get_item(
                    self.snapshot["snapshotDigest"], item["relativePath"]
                )
                if existing is not None:
                    content_digest = existing.get("contentDigest")
                    verify_blob = not (
                        existing.get("blobStored") is True
                        and isinstance(content_digest, str)
                        and content_digest in verified_blobs
                    )
                    self._verify_existing_item(existing, item, verify_blob=verify_blob)
                    if existing.get("blobStored") is True:
                        verified_blobs.add(str(content_digest))
                    continue
                if max_new_items is not None and added >= max_new_items:
                    break
                record, content_record, alias_record = self._process_item(source, item)
                self._inject("after_blob_before_metadata")
                self.metadata.record_item(
                    record=record,
                    content_record=content_record,
                    alias_record=alias_record,
                )
                added += 1

        recorded = len(self.metadata.list_items(self.snapshot["snapshotDigest"]))
        return ImportProgress(
            run_id=self.run_id,
            snapshot_digest=self.snapshot["snapshotDigest"],
            recorded_items=recorded,
            total_items=len(items),
            complete=recorded == len(items),
        )

    def reconcile(self) -> dict[str, Any]:
        snapshot_digest = self.snapshot["snapshotDigest"]
        items = self.metadata.list_items(snapshot_digest)
        expected = self.snapshot["inventory"]["items"]
        if len(items) != len(expected):
            raise IncompleteMigration(
                f"Only {len(items)} of {len(expected)} source items are recorded"
            )
        expected_paths = [item["relativePath"] for item in expected]
        actual_paths = [item["relativePath"] for item in items]
        aliases = self.metadata.list_aliases(snapshot_digest)
        alias_paths = [alias["relativePath"] for alias in aliases]
        if actual_paths != expected_paths or alias_paths != expected_paths:
            raise IncompleteMigration("Item-level reconciliation paths differ")
        expected_registration = {
            "schemaVersion": _SNAPSHOT_REGISTRATION_VERSION,
            "snapshotDigest": snapshot_digest,
            "inventoryDigest": self.snapshot["inventory"]["inventoryDigest"],
            "itemManifestDigest": self.snapshot["inventory"]["itemManifestDigest"],
            "snapshotFileDigest": self.snapshot_file_digest,
            "storageUri": self.blobs.storage_uri(self.snapshot_file_digest),
            "importerDigest": self.importer_digest,
            "sourceRootId": self.snapshot["inventory"]["source"]["sourceRootId"],
            "itemCount": len(expected),
        }
        if (
            self.metadata.get_snapshot_registration(snapshot_digest)
            != expected_registration
        ):
            raise MigrationRecordConflict("Snapshot registration conflicts")
        self.blobs.verify(self.snapshot_file_digest, self.snapshot_file_length)
        content_records = {
            record["contentDigest"]: record for record in self.metadata.list_contents()
        }

        mappings: list[dict[str, Any]] = []
        stored: dict[str, int] = {}
        state_counts: Counter[str] = Counter()
        state_bytes: Counter[str] = Counter()
        for source_item, record, alias in zip(expected, items, aliases, strict=True):
            self._verify_existing_item(record, source_item, verify_blob=False)
            _expected_record, expected_alias = self._build_item_records(source_item)
            if alias != expected_alias:
                raise MigrationRecordConflict("Source alias checkpoint conflicts")
            state = str(record["finalState"])
            state_counts[state] += 1
            state_bytes[state] += int(source_item["byteLength"])
            if record["blobStored"]:
                digest = str(record["contentDigest"])
                length = int(record["byteLength"])
                if digest not in stored:
                    self.blobs.verify(digest, length)
                    expected_content = {
                        "schemaVersion": "tidy.imported-content/v1",
                        "contentDigest": digest,
                        "byteLength": length,
                        "storageUri": self.blobs.storage_uri(digest),
                    }
                    if content_records.get(digest) != expected_content:
                        raise MigrationRecordConflict(
                            "Imported content record conflicts"
                        )
                    stored[digest] = length
                elif stored[digest] != length:
                    raise MigrationRecordConflict("Duplicate content length conflicts")
            mappings.append(
                {
                    "relativePath": record["relativePath"],
                    "sourceItemDigest": record["sourceItemDigest"],
                    "proposedDisposition": record["proposedDisposition"],
                    "finalState": state,
                    "sourceContentDigest": record["sourceContentDigest"],
                    "contentDigest": record["contentDigest"],
                    "blobStored": record["blobStored"],
                    "recordId": record["recordId"],
                }
            )
        mapping_digest = domain_digest(
            "tidy.migration-item-mapping/v1",
            mappings,
        )
        core = {
            "schemaVersion": _RECONCILIATION_VERSION,
            "snapshotDigest": snapshot_digest,
            "inventoryDigest": self.snapshot["inventory"]["inventoryDigest"],
            "itemManifestDigest": self.snapshot["inventory"]["itemManifestDigest"],
            "importerDigest": self.importer_digest,
            "blobStoreId": self.blobs.store_id,
            "contentReconciliationStatus": "complete",
            "phaseBStatus": "core-content-complete-semantic-import-pending",
            "sourceItemCount": len(expected),
            "sourceItemBytes": sum(int(item["byteLength"]) for item in expected),
            "stateCounts": dict(sorted(state_counts.items())),
            "stateBytes": dict(sorted(state_bytes.items())),
            "uniqueStoredObjects": len(stored),
            "uniqueStoredBytes": sum(stored.values()),
            "mappingDigest": mapping_digest,
            "mappings": mappings,
            "limitations": [
                "approval history overwritten before the snapshot is unrecoverable",
                "core reconciliation does not cover approval, reviewer, or "
                "digestRecord interpretation",
                "core reconciliation does not establish complete recipe, "
                "generation, prompt/response, or model typed import",
                "no effective recipe pointer was read or changed",
            ],
        }
        report = {
            **core,
            "reportDigest": domain_digest(_RECONCILIATION_VERSION, core),
        }
        self.metadata.add_reconciliation(report)
        return report

    def _process_item(
        self,
        source: _SourceTree,
        item: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
        disposition = str(item["disposition"])
        entry_type = str(item["entryType"])
        content_digest = item["contentDigest"]
        blob_stored = disposition in _COPY_DISPOSITIONS and entry_type == "file"
        storage_uri: str | None = None
        content_record: dict[str, Any] | None = None

        if entry_type == "file":
            with source.open_regular(item) as descriptor:
                if blob_stored:
                    self.blobs.publish_from_descriptor(
                        descriptor,
                        expected_digest=str(content_digest),
                        expected_length=int(item["byteLength"]),
                    )
                    storage_uri = self.blobs.storage_uri(str(content_digest))
                    content_record = {
                        "schemaVersion": "tidy.imported-content/v1",
                        "contentDigest": content_digest,
                        "byteLength": item["byteLength"],
                        "storageUri": storage_uri,
                    }
                else:
                    _hash_descriptor(
                        descriptor,
                        expected_digest=str(content_digest),
                        expected_length=int(item["byteLength"]),
                    )
        elif entry_type == "excluded-symlink":
            source.verify_symlink(item)
        elif entry_type == "excluded-subtree":
            source.verify_excluded_directory(item)
        else:
            raise MigrationImportError(f"Unsupported source entry type {entry_type}")

        record, alias_record = self._build_item_records(item)
        return record, content_record, alias_record

    def _build_item_records(
        self, item: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        disposition = str(item["disposition"])
        entry_type = str(item["entryType"])
        content_digest = item["contentDigest"]
        blob_stored = disposition in _COPY_DISPOSITIONS and entry_type == "file"
        storage_uri = (
            self.blobs.storage_uri(str(content_digest)) if blob_stored else None
        )
        final_state = {
            "import": "imported",
            "duplicate-alias": "duplicate-alias",
            "exclude": "excluded",
            "quarantine": "quarantined",
        }[disposition]
        has_restricted_embedded_evidence = any(
            record.get("kind") in ("prompt-evidence", "provider-response-evidence")
            for record in item.get("embeddedRecords", [])
        )
        classification = (
            "restricted"
            if item["artifactClass"] in _RESTRICTED_CLASSES
            or has_restricted_embedded_evidence
            else "source-evidence"
        )
        semantic = {
            "schemaVersion": _IMPORT_ITEM_VERSION,
            "snapshotDigest": self.snapshot["snapshotDigest"],
            "importerDigest": self.importer_digest,
            "relativePath": item["relativePath"],
            "entryType": entry_type,
            "artifactClass": item["artifactClass"],
            "classification": classification,
            "proposedDisposition": disposition,
            "finalState": final_state,
            "sourceMode": item["sourceMode"],
            "byteLength": item["byteLength"],
            "sourceItemDigest": domain_digest("tidy.export-item/v1", item),
            "sourceContentDigest": content_digest,
            "contentDigest": content_digest if blob_stored else None,
            "blobStored": blob_stored,
            "storageUri": storage_uri,
            "recordedAt": self.recorded_at,
            "actor": self.actor,
        }
        record = {
            **semantic,
            "recordId": domain_digest(_IMPORT_ITEM_VERSION, semantic),
        }
        alias_semantic = {
            "schemaVersion": "tidy.source-alias/v1",
            "snapshotDigest": self.snapshot["snapshotDigest"],
            "importerDigest": self.importer_digest,
            "relativePath": item["relativePath"],
            "contentDigest": content_digest,
            "finalState": final_state,
            "recordedAt": self.recorded_at,
            "actor": self.actor,
        }
        alias_record = {
            **alias_semantic,
            "aliasId": domain_digest("tidy.source-alias/v1", alias_semantic),
        }
        return record, alias_record

    def _verify_existing_item(
        self,
        existing: Mapping[str, Any],
        source_item: Mapping[str, Any],
        *,
        verify_blob: bool = True,
    ) -> None:
        expected, _alias = self._build_item_records(source_item)
        if dict(existing) != expected:
            raise MigrationRecordConflict("Existing import checkpoint conflicts")
        if verify_blob and existing["blobStored"]:
            self.blobs.verify(
                str(existing["contentDigest"]),
                int(existing["byteLength"]),
            )

    def _inject(self, point: str) -> None:
        if self._fault is not None:
            self._fault(point)


class _SourceTree:
    def __init__(self, root: Path, snapshot: Mapping[str, Any]) -> None:
        self.root = root
        self.snapshot = snapshot
        self.descriptor = -1

    def __enter__(self) -> _SourceTree:
        self.descriptor = os.open(
            self.root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        expected = self.snapshot["inventory"]["source"]["filesystem"]
        info = os.fstat(self.descriptor)
        if (info.st_dev, info.st_ino, info.st_mode) != (
            expected["deviceId"],
            expected["rootInode"],
            expected["rootMode"],
        ):
            os.close(self.descriptor)
            self.descriptor = -1
            raise SourceItemMismatch("Source root identity changed")
        return self

    def __exit__(self, *_args: object) -> None:
        if self.descriptor >= 0:
            expected = self.snapshot["inventory"]["source"]["filesystem"]
            info = os.fstat(self.descriptor)
            os.close(self.descriptor)
            self.descriptor = -1
            if (info.st_dev, info.st_ino, info.st_mode) != (
                expected["deviceId"],
                expected["rootInode"],
                expected["rootMode"],
            ):
                raise SourceItemMismatch("Source root changed during import")

    @contextmanager
    def open_regular(self, item: Mapping[str, Any]) -> Iterator[int]:
        try:
            descriptor = _open_relative_file(self.descriptor, str(item["relativePath"]))
        except OSError as error:
            raise SourceItemMismatch(
                "Source file could not be opened safely"
            ) from error
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_mode != item["sourceMode"]
                or before.st_size != item["byteLength"]
            ):
                raise SourceItemMismatch("Source file metadata differs from snapshot")
            try:
                yield descriptor
            finally:
                after = os.fstat(descriptor)
                if _stat_identity(before) != _stat_identity(after):
                    raise SourceItemMismatch("Source file changed during import")
        finally:
            os.close(descriptor)

    def verify_symlink(self, item: Mapping[str, Any]) -> None:
        parent, name = _open_relative_parent(self.descriptor, str(item["relativePath"]))
        try:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISLNK(before.st_mode) or before.st_mode != item["sourceMode"]:
                raise SourceItemMismatch("Source symlink differs from snapshot")
            target = os.readlink(os.fsencode(name), dir_fd=parent)
            after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(parent)
        if not isinstance(target, bytes):
            raise SourceItemMismatch("Source symlink target was not raw bytes")
        if (
            _stat_identity(before) != _stat_identity(after)
            or len(target) != item["byteLength"]
            or sha256_digest(target) != item["contentDigest"]
        ):
            raise SourceItemMismatch("Source symlink target differs from snapshot")

    def verify_excluded_directory(self, item: Mapping[str, Any]) -> None:
        parent, name = _open_relative_parent(self.descriptor, str(item["relativePath"]))
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(parent)
        if not stat.S_ISDIR(info.st_mode) or info.st_mode != item["sourceMode"]:
            raise SourceItemMismatch("Excluded source directory differs from snapshot")


def _importer_source_digest() -> str:
    project = Path(__file__).parents[2]
    paths = [
        project / "pyproject.toml",
        project / "uv.lock",
        project / "src/tidy_orchestrator/artifacts.py",
        project / "src/tidy_orchestrator/source_export.py",
        Path(__file__),
    ]
    contracts = project / "contracts/import/v1"
    paths.extend(
        contracts / name
        for name in (
            "blob-commit.schema.json",
            "import-item.schema.json",
            "reconciliation.schema.json",
            "snapshot-registration.schema.json",
            "source-alias.schema.json",
        )
    )

    def capture() -> list[dict[str, str]]:
        return [
            {
                "relativePath": path.relative_to(project).as_posix(),
                "contentDigest": sha256_digest(
                    _read_regular(path, maximum=16 * 1024 * 1024)
                ),
            }
            for path in paths
        ]

    files = capture()
    if capture() != files:
        raise MigrationImportError("Importer source closure changed while hashing")
    return domain_digest(
        "tidy.migration-importer-source-closure/v1",
        {
            "files": files,
            "runtime": {
                "pythonImplementation": platform.python_implementation(),
                "pythonVersion": platform.python_version(),
                "sqliteVersion": sqlite3.sqlite_version,
            },
        },
    )


def _require_separate_trees(first: Path, second: Path, label: str) -> None:
    first = first.resolve(strict=True)
    second = second.resolve(strict=True)
    if first == second or first.is_relative_to(second) or second.is_relative_to(first):
        raise MigrationImportError(f"{label} must not overlap")


def _ensure_private_directory(path: Path, label: str) -> Path:
    absolute = path.absolute()
    if os.path.lexists(absolute):
        directory = _validated_directory(absolute, label)
    else:
        parent = _validated_directory(absolute.parent, f"{label} parent")
        parent.joinpath(absolute.name).mkdir(mode=0o700)
        directory = _validated_directory(absolute, label)
        _fsync_directory(parent)
    os.chmod(directory, 0o700)
    return directory


def _validated_directory(path: Path, label: str) -> Path:
    absolute = path.absolute()
    before = absolute.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise MigrationImportError(f"{label} must be a non-symlink directory")
    resolved = absolute.resolve(strict=True)
    after = absolute.lstat()
    resolved_info = resolved.lstat()
    if _stat_identity(before) != _stat_identity(after) or _stat_identity(
        before
    ) != _stat_identity(resolved_info):
        raise MigrationImportError(f"{label} identity changed")
    return resolved


def _open_relative_file(root_descriptor: int, relative_path: str) -> int:
    parent, name = _open_relative_parent(root_descriptor, relative_path)
    try:
        return os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent,
        )
    finally:
        os.close(parent)


def _open_relative_parent(root_descriptor: int, relative_path: str) -> tuple[int, str]:
    path = PurePosixPath(relative_path)
    if (
        path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or "\\" in relative_path
        or "\x00" in relative_path
    ):
        raise MigrationImportError("Source path is unsafe")
    current = os.dup(root_descriptor)
    try:
        for part in path.parts[:-1]:
            next_descriptor = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            os.close(current)
            current = next_descriptor
        return current, path.parts[-1]
    except BaseException:
        os.close(current)
        raise


@contextmanager
def _open_regular_descriptor(path: Path) -> Iterator[int]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise MigrationImportError("Input must be a regular file")
        yield descriptor
    finally:
        os.close(descriptor)


def _read_regular(path: Path, *, maximum: int) -> bytes:
    with _open_regular_descriptor(path) as descriptor:
        before = os.fstat(descriptor)
        if before.st_size > maximum:
            raise MigrationImportError("Input exceeds its byte limit")
        data = bytearray()
        while True:
            chunk = os.read(descriptor, _READ_CHUNK)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > maximum:
                raise MigrationImportError("Input exceeded its byte limit")
        after = os.fstat(descriptor)
        if (
            _stat_identity(before) != _stat_identity(after)
            or len(data) != before.st_size
        ):
            raise MigrationImportError("Input changed while reading")
        return bytes(data)


def _hash_regular_path(path: Path, maximum: int) -> tuple[str, int]:
    with _open_regular_descriptor(path) as descriptor:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        length = 0
        while True:
            chunk = os.read(descriptor, _READ_CHUNK)
            if not chunk:
                break
            length += len(chunk)
            if length > maximum:
                raise BlobIntegrityError("Blob exceeded committed length")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            raise BlobIntegrityError("Blob changed while being verified")
        return f"sha256:{digest.hexdigest()}", length


def _hash_descriptor(
    descriptor: int,
    *,
    expected_digest: str,
    expected_length: int,
) -> None:
    digest = hashlib.sha256()
    length = 0
    while True:
        chunk = os.read(descriptor, _READ_CHUNK)
        if not chunk:
            break
        length += len(chunk)
        if length > expected_length:
            raise SourceItemMismatch("Source file exceeded frozen length")
        digest.update(chunk)
    if length != expected_length or f"sha256:{digest.hexdigest()}" != expected_digest:
        raise SourceItemMismatch("Source bytes differ from frozen snapshot")


def _write_commit_marker(directory: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    descriptor, name = tempfile.mkstemp(
        prefix=".COMMITTED.json.", suffix=".tmp", dir=directory
    )
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.path.lexists(directory / "COMMITTED.json"):
            raise BlobIntegrityError("Commit marker already exists")
        os.rename(temporary, directory / "COMMITTED.json")
        temporary = None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    os.chmod(directory / "COMMITTED.json", 0o600)


def _strict_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            data,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise BlobIntegrityError(f"{label} must be strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise BlobIntegrityError(f"{label} must be an object")
    return value


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            raise OSError("Short write")
        written += count


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _validate_typed_record_identity(
    *,
    record_id: str,
    record_type: str,
    record: Mapping[str, Any],
) -> str:
    identity = _require_digest(record_id)
    if record.get("schemaVersion") != record_type:
        raise ValueError("record_type must equal the record schemaVersion")
    identity_field = _TYPED_ID_FIELDS.get(record_type, "recordId")
    if record.get(identity_field) != identity:
        raise ValueError("record_id does not bind the typed record")
    if record_type in _TYPED_ID_FIELDS:
        semantic = dict(record)
        del semantic[identity_field]
        if domain_digest(record_type, semantic) != identity:
            raise ValueError("typed record identity digest differs")
    return identity


def _require_utc_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise MigrationImportError(f"Invalid canonical UTC timestamp {value!r}")
    return value


def _require_digest(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(_DIGEST_PREFIX)
        or len(value) != 71
    ):
        raise ValueError(f"Invalid digest {value!r}")
    hexadecimal = value.split(":", 1)[1]
    if any(character not in "0123456789abcdef" for character in hexadecimal):
        raise ValueError(f"Invalid digest {value!r}")
    return value
