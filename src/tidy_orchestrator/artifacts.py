"""Authoritative local content, derivation, custody, decision, and CAS storage."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCHEMA_VERSION = 1


class RepositoryError(RuntimeError):
    """Base repository error."""


class IntegrityViolation(RepositoryError):
    """Bytes or immutable metadata did not match their declared identity."""


class RecordConflict(RepositoryError):
    """An immutable identity already exists with different content."""


class PointerConflict(RepositoryError):
    """A compare-and-swap pointer revision was stale."""


class RecordNotFound(RepositoryError):
    """Authoritative metadata was not found."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def domain_digest(domain: str, value: Any) -> str:
    payload = domain.encode("utf-8") + b"\x00" + canonical_json_bytes(value)
    return sha256_digest(payload)


def _require_digest(value: str) -> str:
    if not _DIGEST.fullmatch(value):
        raise ValueError(f"Invalid SHA-256 digest: {value!r}")
    return value


@dataclass(frozen=True)
class ContentDescriptor:
    kind: str
    schema_version: str
    media_type: str
    byte_length: int
    content_digest: str
    canonicalization_algorithm: str | None = None

    def __post_init__(self) -> None:
        _require_digest(self.content_digest)
        if self.byte_length < 0:
            raise ValueError("byte_length must be non-negative")


@dataclass(frozen=True)
class DerivationRecord:
    derivation_id: str
    operation: str
    contract_version: str
    ordered_input_digests: tuple[str, ...]
    configuration_digest: str
    producer_digests: tuple[str, ...]
    ordered_output_digests: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        operation: str,
        contract_version: str,
        ordered_input_digests: Sequence[str],
        configuration_digest: str,
        producer_digests: Sequence[str],
        ordered_output_digests: Sequence[str],
        context: Mapping[str, Any] | None = None,
    ) -> DerivationRecord:
        """Create from semantic fields, ignoring contextual paths and times."""
        del context
        inputs = tuple(map(_require_digest, ordered_input_digests))
        producers = tuple(map(_require_digest, producer_digests))
        outputs = tuple(map(_require_digest, ordered_output_digests))
        _require_digest(configuration_digest)
        identity = {
            "operation": operation,
            "contractVersion": contract_version,
            "orderedInputDigests": inputs,
            "configurationDigest": configuration_digest,
            "producerDigests": producers,
            "orderedOutputDigests": outputs,
        }
        return cls(
            derivation_id=domain_digest("tidy.derivation/v1", identity),
            operation=operation,
            contract_version=contract_version,
            ordered_input_digests=inputs,
            configuration_digest=configuration_digest,
            producer_digests=producers,
            ordered_output_digests=outputs,
        )


@dataclass(frozen=True)
class CustodyReceipt:
    receipt_id: str
    content_digest: str
    storage_uri: str
    observed_at: str
    actor: str
    source_locator: str | None = None
    retrieval_metadata: Mapping[str, Any] | None = None
    classification: str | None = None

    @classmethod
    def create(
        cls,
        *,
        content_digest: str,
        storage_uri: str,
        observed_at: str,
        actor: str,
        source_locator: str | None = None,
        retrieval_metadata: Mapping[str, Any] | None = None,
        classification: str | None = None,
        receipt_id: str | None = None,
    ) -> CustodyReceipt:
        _require_digest(content_digest)
        identity = {
            "contentDigest": content_digest,
            "storageUri": storage_uri,
            "observedAt": observed_at,
            "actor": actor,
            "sourceLocator": source_locator,
            "retrievalMetadata": retrieval_metadata,
            "classification": classification,
        }
        return cls(
            receipt_id=receipt_id or domain_digest("tidy.custody/v1", identity),
            content_digest=content_digest,
            storage_uri=storage_uri,
            observed_at=observed_at,
            actor=actor,
            source_locator=source_locator,
            retrieval_metadata=retrieval_metadata,
            classification=classification,
        )


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    subject_id: str
    decision_type: str
    payload: Mapping[str, Any]
    actor: str
    recorded_at: str

    @classmethod
    def create(
        cls,
        *,
        subject_id: str,
        decision_type: str,
        payload: Mapping[str, Any],
        actor: str,
        recorded_at: str,
        decision_id: str | None = None,
    ) -> DecisionRecord:
        identity = {
            "subjectId": subject_id,
            "decisionType": decision_type,
            "payload": payload,
            "actor": actor,
            "recordedAt": recorded_at,
        }
        return cls(
            decision_id=decision_id or domain_digest("tidy.decision/v1", identity),
            subject_id=subject_id,
            decision_type=decision_type,
            payload=payload,
            actor=actor,
            recorded_at=recorded_at,
        )


@dataclass(frozen=True)
class PointerRevision:
    name: str
    revision: int
    target_id: str


class LocalArtifactRepository:
    """Filesystem blobs plus SQLite authority; blobs publish before metadata."""

    def __init__(
        self,
        root: Path | str,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.blobs = self.root / "blobs" / "sha256"
        self.staging = self.root / "staging"
        self.quarantine = self.root / "quarantine"
        self.database = self.root / "metadata.sqlite3"
        self._fault = fault_injector
        for directory in (self.root, self.blobs, self.staging, self.quarantine):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
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
                "version INTEGER PRIMARY KEY, "
                "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
            if current > _SCHEMA_VERSION:
                raise RepositoryError(f"Unsupported repository schema {current}")
            if current < 1:
                statements = (
                    "CREATE TABLE contents ("
                    "content_digest TEXT PRIMARY KEY, "
                    "byte_length INTEGER NOT NULL CHECK (byte_length >= 0), "
                    "record_json BLOB NOT NULL)",
                    "CREATE TABLE derivations ("
                    "derivation_id TEXT PRIMARY KEY, record_json BLOB NOT NULL)",
                    "CREATE TABLE custody ("
                    "receipt_id TEXT PRIMARY KEY, "
                    "content_digest TEXT NOT NULL REFERENCES contents(content_digest), "
                    "record_json BLOB NOT NULL)",
                    "CREATE TABLE decisions ("
                    "decision_id TEXT PRIMARY KEY, record_json BLOB NOT NULL)",
                    "CREATE TABLE pointers ("
                    "name TEXT PRIMARY KEY, "
                    "revision INTEGER NOT NULL CHECK (revision >= 1), "
                    "target_id TEXT NOT NULL)",
                    "CREATE TABLE reproductions ("
                    "reproduction_key TEXT PRIMARY KEY, "
                    "output_fingerprint TEXT NOT NULL)",
                    "INSERT INTO schema_migrations(version) VALUES (1)",
                )
                for statement in statements:
                    connection.execute(statement)
            connection.commit()
        os.chmod(self.database, 0o600)

    def blob_path(self, digest: str) -> Path:
        hexadecimal = _require_digest(digest).split(":", 1)[1]
        return self.blobs / hexadecimal[:2] / hexadecimal[2:]

    def put_bytes(
        self,
        data: bytes,
        *,
        kind: str,
        schema_version: str,
        media_type: str,
        canonicalization_algorithm: str | None = None,
        declared_digest: str | None = None,
        declared_length: int | None = None,
    ) -> ContentDescriptor:
        digest = sha256_digest(data)
        if declared_digest is not None and _require_digest(declared_digest) != digest:
            self._quarantine_bytes(data, "digest-mismatch")
            raise IntegrityViolation("Declared content digest does not match bytes")
        if declared_length is not None and declared_length != len(data):
            self._quarantine_bytes(data, "length-mismatch")
            raise IntegrityViolation("Declared byte length does not match bytes")
        descriptor = ContentDescriptor(
            kind=kind,
            schema_version=schema_version,
            media_type=media_type,
            byte_length=len(data),
            content_digest=digest,
            canonicalization_algorithm=canonicalization_algorithm,
        )
        self._publish_blob(data, digest, len(data))
        self._inject("after_blob_before_metadata")
        record = canonical_json_bytes(_content_wire(descriptor))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_immutable(
                connection,
                table="contents",
                id_column="content_digest",
                identity=digest,
                record=record,
                extra=("byte_length", len(data)),
            )
            self._inject("before_metadata_commit")
            connection.commit()
        return descriptor

    def get_content(self, digest: str) -> ContentDescriptor:
        _require_digest(digest)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM contents WHERE content_digest=?", (digest,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(f"No authoritative content record for {digest}")
        value = json.loads(row[0])
        return ContentDescriptor(
            kind=value["kind"],
            schema_version=value["schemaVersion"],
            media_type=value["mediaType"],
            byte_length=value["byteLength"],
            content_digest=value["contentDigest"],
            canonicalization_algorithm=value.get("canonicalizationAlgorithm"),
        )

    def read_bytes_verified(self, digest: str) -> bytes:
        descriptor = self.get_content(digest)
        path = self.blob_path(digest)
        try:
            data = self._read_regular_no_follow(path, descriptor.byte_length)
        except FileNotFoundError as error:
            raise IntegrityViolation(
                f"Authoritative blob is missing: {digest}"
            ) from error
        except (OSError, IntegrityViolation) as error:
            raise IntegrityViolation(
                f"Authoritative blob is not a safe regular file: {digest}"
            ) from error
        if len(data) != descriptor.byte_length or sha256_digest(data) != digest:
            self._quarantine_bytes(data, "tampered-blob")
            raise IntegrityViolation(
                f"Authoritative blob failed verification: {digest}"
            )
        return data

    @contextlib.contextmanager
    def open_verified(self, digest: str) -> Iterator[io.BytesIO]:
        handle = io.BytesIO(self.read_bytes_verified(digest))
        try:
            yield handle
        finally:
            handle.close()

    def add_derivation(self, record: DerivationRecord) -> DerivationRecord:
        expected = DerivationRecord.create(
            operation=record.operation,
            contract_version=record.contract_version,
            ordered_input_digests=record.ordered_input_digests,
            configuration_digest=record.configuration_digest,
            producer_digests=record.producer_digests,
            ordered_output_digests=record.ordered_output_digests,
        )
        if expected.derivation_id != record.derivation_id:
            raise IntegrityViolation(
                "Derivation identity does not match semantic fields"
            )
        for digest in (*record.ordered_input_digests, *record.ordered_output_digests):
            self.get_content(digest)
        wire = canonical_json_bytes(_derivation_wire(record))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_immutable(
                connection,
                table="derivations",
                id_column="derivation_id",
                identity=record.derivation_id,
                record=wire,
            )
            connection.commit()
        return record

    def get_derivation(self, derivation_id: str) -> DerivationRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM derivations WHERE derivation_id=?",
                (derivation_id,),
            ).fetchone()
        if row is None:
            raise RecordNotFound(derivation_id)
        value = json.loads(row[0])
        return DerivationRecord(
            derivation_id=value["derivationId"],
            operation=value["operation"],
            contract_version=value["contractVersion"],
            ordered_input_digests=tuple(value["orderedInputDigests"]),
            configuration_digest=value["configurationDigest"],
            producer_digests=tuple(value["producerDigests"]),
            ordered_output_digests=tuple(value["orderedOutputDigests"]),
        )

    def add_custody(self, receipt: CustodyReceipt) -> CustodyReceipt:
        self.get_content(receipt.content_digest)
        wire = canonical_json_bytes(_custody_wire(receipt))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_immutable(
                connection,
                table="custody",
                id_column="receipt_id",
                identity=receipt.receipt_id,
                record=wire,
                extra=("content_digest", receipt.content_digest),
            )
            connection.commit()
        return receipt

    def get_custody(self, receipt_id: str) -> CustodyReceipt:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM custody WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(receipt_id)
        return _custody_from_wire(json.loads(row[0]))

    def list_custody(
        self, *, content_digest: str | None = None
    ) -> tuple[CustodyReceipt, ...]:
        if content_digest is not None:
            _require_digest(content_digest)
        query = "SELECT record_json FROM custody"
        parameters: tuple[str, ...] = ()
        if content_digest is not None:
            query += " WHERE content_digest=?"
            parameters = (content_digest,)
        query += " ORDER BY receipt_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(_custody_from_wire(json.loads(row[0])) for row in rows)

    def append_decision(self, record: DecisionRecord) -> DecisionRecord:
        wire = canonical_json_bytes(_decision_wire(record))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_immutable(
                connection,
                table="decisions",
                id_column="decision_id",
                identity=record.decision_id,
                record=wire,
            )
            connection.commit()
        return record

    def get_decision(self, decision_id: str) -> DecisionRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
        if row is None:
            raise RecordNotFound(decision_id)
        return _decision_from_wire(json.loads(row[0]))

    def list_decisions(
        self, *, subject_id: str | None = None
    ) -> tuple[DecisionRecord, ...]:
        query = "SELECT record_json FROM decisions"
        parameters: tuple[str, ...] = ()
        if subject_id is not None:
            query += " WHERE json_extract(record_json, '$.subjectId')=?"
            parameters = (subject_id,)
        query += " ORDER BY decision_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(_decision_from_wire(json.loads(row[0])) for row in rows)

    def compare_and_swap_pointer(
        self, name: str, expected_revision: int | None, target_id: str
    ) -> PointerRevision:
        if not name or len(name) > 256:
            raise ValueError("Pointer name is invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision, target_id FROM pointers WHERE name=?", (name,)
            ).fetchone()
            actual = None if row is None else int(row["revision"])
            if actual != expected_revision:
                connection.rollback()
                raise PointerConflict(
                    f"Pointer {name!r} expected revision "
                    f"{expected_revision}, got {actual}"
                )
            revision = 1 if actual is None else actual + 1
            if actual is None:
                connection.execute(
                    "INSERT INTO pointers(name, revision, target_id) VALUES (?, ?, ?)",
                    (name, revision, target_id),
                )
            else:
                changed = connection.execute(
                    "UPDATE pointers SET revision=?, target_id=? "
                    "WHERE name=? AND revision=?",
                    (revision, target_id, name, actual),
                ).rowcount
                if changed != 1:
                    connection.rollback()
                    raise PointerConflict(f"Pointer {name!r} changed concurrently")
            connection.commit()
        return PointerRevision(name=name, revision=revision, target_id=target_id)

    def get_pointer(self, name: str) -> PointerRevision | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision, target_id FROM pointers WHERE name=?", (name,)
            ).fetchone()
        return (
            None
            if row is None
            else PointerRevision(name, int(row["revision"]), row["target_id"])
        )

    def publish_worker_bundle(
        self,
        *,
        outputs: Sequence[tuple[ContentDescriptor, bytes, CustodyReceipt]],
        reproduction_key: str,
        output_fingerprint: str,
        derivation: DerivationRecord,
    ) -> tuple[ContentDescriptor, ...]:
        """Publish one verified worker output set with one authority transaction.

        Blob pathnames are made durable first. Any later conflict or injected fault
        rolls back every content, custody, reproduction, and derivation row, so the
        only permitted residue is unreferenced content-addressed bytes.
        """
        _require_digest(reproduction_key)
        _require_digest(output_fingerprint)
        expected_derivation = DerivationRecord.create(
            operation=derivation.operation,
            contract_version=derivation.contract_version,
            ordered_input_digests=derivation.ordered_input_digests,
            configuration_digest=derivation.configuration_digest,
            producer_digests=derivation.producer_digests,
            ordered_output_digests=derivation.ordered_output_digests,
        )
        if expected_derivation != derivation:
            raise IntegrityViolation(
                "Derivation identity does not match semantic fields"
            )
        descriptors = tuple(item[0] for item in outputs)
        if tuple(item.content_digest for item in descriptors) != (
            derivation.ordered_output_digests
        ):
            raise IntegrityViolation("Bundle outputs differ from derivation outputs")
        seen_receipts: set[str] = set()
        for descriptor, data, receipt in outputs:
            if (
                len(data) != descriptor.byte_length
                or sha256_digest(data) != descriptor.content_digest
            ):
                self._quarantine_bytes(data, "bundle-integrity")
                raise IntegrityViolation("Bundle descriptor differs from output bytes")
            if receipt.content_digest != descriptor.content_digest:
                raise IntegrityViolation("Custody receipt differs from bundle content")
            if receipt.receipt_id in seen_receipts:
                raise IntegrityViolation("Bundle contains a duplicate custody receipt")
            seen_receipts.add(receipt.receipt_id)

        for descriptor, data, _receipt in outputs:
            self._publish_blob(data, descriptor.content_digest, descriptor.byte_length)
        self._inject("bundle_after_blobs_before_transaction")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for digest in derivation.ordered_input_digests:
                    if (
                        connection.execute(
                            "SELECT 1 FROM contents WHERE content_digest=?", (digest,)
                        ).fetchone()
                        is None
                    ):
                        raise RecordNotFound(digest)
                existing = connection.execute(
                    "SELECT output_fingerprint FROM reproductions "
                    "WHERE reproduction_key=?",
                    (reproduction_key,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO reproductions("
                        "reproduction_key, output_fingerprint) VALUES (?, ?)",
                        (reproduction_key, output_fingerprint),
                    )
                elif existing[0] != output_fingerprint:
                    raise RecordConflict("Deterministic reproduction changed outputs")
                for descriptor, _data, receipt in outputs:
                    self._insert_immutable(
                        connection,
                        table="contents",
                        id_column="content_digest",
                        identity=descriptor.content_digest,
                        record=canonical_json_bytes(_content_wire(descriptor)),
                        extra=("byte_length", descriptor.byte_length),
                    )
                    self._insert_immutable(
                        connection,
                        table="custody",
                        id_column="receipt_id",
                        identity=receipt.receipt_id,
                        record=canonical_json_bytes(_custody_wire(receipt)),
                        extra=("content_digest", receipt.content_digest),
                    )
                self._insert_immutable(
                    connection,
                    table="derivations",
                    id_column="derivation_id",
                    identity=derivation.derivation_id,
                    record=canonical_json_bytes(_derivation_wire(derivation)),
                )
                self._inject("bundle_before_commit")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return descriptors

    def record_reproduction(
        self, reproduction_key: str, output_fingerprint: str
    ) -> None:
        _require_digest(reproduction_key)
        _require_digest(output_fingerprint)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT output_fingerprint FROM reproductions WHERE reproduction_key=?",
                (reproduction_key,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO reproductions(reproduction_key, output_fingerprint) "
                    "VALUES (?, ?)",
                    (reproduction_key, output_fingerprint),
                )
            elif existing[0] != output_fingerprint:
                connection.rollback()
                raise RecordConflict("Deterministic reproduction changed outputs")
            connection.commit()

    def _insert_immutable(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        id_column: str,
        identity: str,
        record: bytes,
        extra: tuple[str, Any] | None = None,
    ) -> None:
        row = connection.execute(
            f"SELECT record_json FROM {table} WHERE {id_column}=?", (identity,)
        ).fetchone()
        if row is not None:
            if bytes(row[0]) != record:
                raise RecordConflict(f"Conflicting immutable record {identity}")
            return
        columns = [id_column, "record_json"]
        values: list[Any] = [identity, record]
        if extra is not None:
            columns.insert(1, extra[0])
            values.insert(1, extra[1])
        placeholders = ",".join("?" for _ in values)
        connection.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})", values
        )

    def _publish_blob(self, data: bytes, digest: str, length: int) -> None:
        target = self.blob_path(digest)
        self._ensure_digest_shard(target.parent)
        fd, stage_name = tempfile.mkstemp(prefix="blob-", dir=self.staging)
        stage = Path(stage_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            self._inject("after_staging")
            try:
                os.link(stage, target, follow_symlinks=False)
                self._fsync_directory(target.parent)
            except FileExistsError:
                self._verify_blob(target, digest, length)
            stage.unlink(missing_ok=True)
        finally:
            stage.unlink(missing_ok=True)

    def _ensure_digest_shard(self, shard: Path) -> None:
        created = False
        try:
            shard.mkdir(mode=0o700)
            created = True
        except FileExistsError:
            pass
        info = shard.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise IntegrityViolation("Digest shard is not a safe directory")
        if created:
            os.chmod(shard, 0o700)
            self._fsync_directory(shard)
            self._fsync_directory(self.blobs)

    def _verify_blob(self, path: Path, digest: str, length: int) -> None:
        try:
            data = self._read_regular_no_follow(path, length)
        except (OSError, IntegrityViolation) as error:
            raise IntegrityViolation(
                f"Existing blob target is not a safe regular file: {digest}"
            ) from error
        if len(data) != length or sha256_digest(data) != digest:
            self._quarantine_bytes(data, "tampered-blob")
            raise IntegrityViolation(f"Existing blob conflicts with {digest}")

    @staticmethod
    def _read_regular_no_follow(path: Path, expected_length: int) -> bytes:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise IntegrityViolation("Blob target is not a regular file")
            if before.st_size > expected_length:
                maximum = expected_length + 1
            else:
                maximum = expected_length
            chunks: list[bytes] = []
            remaining = maximum
            while remaining:
                chunk = os.read(descriptor, min(1_048_576, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
            ):
                raise IntegrityViolation("Blob changed while being read")
            return data
        finally:
            os.close(descriptor)

    def _quarantine_bytes(self, data: bytes, reason: str) -> None:
        fd, name = tempfile.mkstemp(prefix=f"{reason}-", dir=self.quarantine)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        self._fsync_directory(self.quarantine)

    def _inject(self, point: str) -> None:
        if self._fault is not None:
            self._fault(point)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _content_wire(value: ContentDescriptor) -> dict[str, Any]:
    result = {
        "kind": value.kind,
        "schemaVersion": value.schema_version,
        "mediaType": value.media_type,
        "byteLength": value.byte_length,
        "contentDigest": value.content_digest,
    }
    if value.canonicalization_algorithm is not None:
        result["canonicalizationAlgorithm"] = value.canonicalization_algorithm
    return result


def _derivation_wire(value: DerivationRecord) -> dict[str, Any]:
    return {
        "derivationId": value.derivation_id,
        "operation": value.operation,
        "contractVersion": value.contract_version,
        "orderedInputDigests": value.ordered_input_digests,
        "configurationDigest": value.configuration_digest,
        "producerDigests": value.producer_digests,
        "orderedOutputDigests": value.ordered_output_digests,
    }


def _custody_wire(value: CustodyReceipt) -> dict[str, Any]:
    result = {
        "receiptId": value.receipt_id,
        "contentDigest": value.content_digest,
        "storageUri": value.storage_uri,
        "observedAt": value.observed_at,
        "actor": value.actor,
        "sourceLocator": value.source_locator,
        "retrievalMetadata": value.retrieval_metadata,
        "classification": value.classification,
    }
    return result


def _decision_wire(value: DecisionRecord) -> dict[str, Any]:
    return {
        "decisionId": value.decision_id,
        "subjectId": value.subject_id,
        "decisionType": value.decision_type,
        "payload": value.payload,
        "actor": value.actor,
        "recordedAt": value.recorded_at,
    }


def _custody_from_wire(value: Mapping[str, Any]) -> CustodyReceipt:
    return CustodyReceipt(
        receipt_id=value["receiptId"],
        content_digest=value["contentDigest"],
        storage_uri=value["storageUri"],
        observed_at=value["observedAt"],
        actor=value["actor"],
        source_locator=value.get("sourceLocator"),
        retrieval_metadata=value.get("retrievalMetadata"),
        classification=value.get("classification"),
    )


def _decision_from_wire(value: Mapping[str, Any]) -> DecisionRecord:
    return DecisionRecord(
        decision_id=value["decisionId"],
        subject_id=value["subjectId"],
        decision_type=value["decisionType"],
        payload=value["payload"],
        actor=value["actor"],
        recorded_at=value["recordedAt"],
    )
