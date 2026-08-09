from __future__ import annotations

import dataclasses
import multiprocessing
import os
import threading
from pathlib import Path

import pytest

from tidy_orchestrator.artifacts import (
    CustodyReceipt,
    DecisionRecord,
    DerivationRecord,
    IntegrityViolation,
    LocalArtifactRepository,
    PointerConflict,
    RecordConflict,
    RecordNotFound,
    domain_digest,
    sha256_digest,
)


def _crash_after_blob(root: str) -> None:
    def crash(point: str) -> None:
        if point == "after_blob_before_metadata":
            os._exit(77)

    LocalArtifactRepository(Path(root), fault_injector=crash).put_bytes(
        b"process-orphan",
        kind="test",
        schema_version="v1",
        media_type="application/octet-stream",
    )


def repository(tmp_path: Path) -> LocalArtifactRepository:
    return LocalArtifactRepository(tmp_path / "repository")


def put(repo: LocalArtifactRepository, data: bytes = b"content"):
    return repo.put_bytes(
        data,
        kind="test",
        schema_version="test/v1",
        media_type="application/octet-stream",
    )


def test_content_put_get_idempotence_permissions_and_tamper(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    first = put(repo)
    second = put(repo)
    assert first == second
    assert repo.read_bytes_verified(first.content_digest) == b"content"
    assert repo.root.stat().st_mode & 0o077 == 0
    assert repo.database.stat().st_mode & 0o077 == 0

    blob = repo.blob_path(first.content_digest)
    blob.write_bytes(b"tampered")
    with pytest.raises(IntegrityViolation):
        repo.read_bytes_verified(first.content_digest)
    assert any(repo.quarantine.iterdir())


def test_custody_movement_does_not_change_content_identity(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    content = put(repo)
    receipts = [
        CustodyReceipt.create(
            content_digest=content.content_digest,
            storage_uri=location,
            observed_at=f"2026-01-0{index}T00:00:00+00:00",
            actor="test",
        )
        for index, location in enumerate(("file:///one", "file:///two"), start=1)
    ]
    for receipt in receipts:
        assert repo.add_custody(receipt) == receipt
    assert receipts[0].receipt_id != receipts[1].receipt_id
    assert repo.get_content(content.content_digest) == content


def test_derivation_determinism_order_and_context_exclusion(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    inputs = [put(repo, b"a"), put(repo, b"b")]
    outputs = [put(repo, b"x"), put(repo, b"y")]
    configuration = domain_digest("configuration", {"mode": "test"})
    producer = sha256_digest(b"producer")
    first = DerivationRecord.create(
        operation="execute",
        contract_version="v1",
        ordered_input_digests=[item.content_digest for item in inputs],
        configuration_digest=configuration,
        producer_digests=[producer],
        ordered_output_digests=[item.content_digest for item in outputs],
        context={"path": "/first", "timestamp": "one", "dagsterRunId": "a"},
    )
    second = DerivationRecord.create(
        operation="execute",
        contract_version="v1",
        ordered_input_digests=[item.content_digest for item in inputs],
        configuration_digest=configuration,
        producer_digests=[producer],
        ordered_output_digests=[item.content_digest for item in outputs],
        context={"path": "/moved", "timestamp": "two", "dagsterRunId": "b"},
    )
    assert first == second
    repo.add_derivation(first)
    repo.add_derivation(second)
    assert repo.get_derivation(first.derivation_id) == first
    reversed_outputs = DerivationRecord.create(
        operation="execute",
        contract_version="v1",
        ordered_input_digests=[item.content_digest for item in inputs],
        configuration_digest=configuration,
        producer_digests=[producer],
        ordered_output_digests=[item.content_digest for item in reversed(outputs)],
    )
    assert reversed_outputs.derivation_id != first.derivation_id
    invalid = dataclasses.replace(first, operation="different")
    with pytest.raises(IntegrityViolation):
        repo.add_derivation(invalid)


def test_append_only_decision_conflict_and_cas_staleness(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    decision = DecisionRecord.create(
        decision_id="decision-1",
        subject_id="subject",
        decision_type="synthetic",
        payload={"value": 1},
        actor="tester",
        recorded_at="2026-01-01T00:00:00Z",
    )
    repo.append_decision(decision)
    repo.append_decision(decision)
    with pytest.raises(RecordConflict):
        repo.append_decision(dataclasses.replace(decision, payload={"value": 2}))

    first = repo.compare_and_swap_pointer("active", None, "decision-1")
    assert first.revision == 1
    second = repo.compare_and_swap_pointer("active", 1, "decision-2")
    assert second.revision == 2
    with pytest.raises(PointerConflict):
        repo.compare_and_swap_pointer("active", 1, "stale")
    assert repo.get_pointer("active") == second


def test_crash_points_orphan_safety_and_replay(tmp_path: Path) -> None:
    root = tmp_path / "repository"

    def after_staging(point: str) -> None:
        if point == "after_staging":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        put(LocalArtifactRepository(root, fault_injector=after_staging), b"staged")
    staged_digest = sha256_digest(b"staged")
    assert not LocalArtifactRepository(root).blob_path(staged_digest).exists()

    def after_blob(point: str) -> None:
        if point == "after_blob_before_metadata":
            raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        put(LocalArtifactRepository(root, fault_injector=after_blob), b"orphan")
    orphan_digest = sha256_digest(b"orphan")
    recovered = LocalArtifactRepository(root)
    assert recovered.blob_path(orphan_digest).exists()
    with pytest.raises(RecordNotFound):
        recovered.get_content(orphan_digest)
    descriptor = put(recovered, b"orphan")
    assert descriptor.content_digest == orphan_digest
    assert recovered.read_bytes_verified(orphan_digest) == b"orphan"


def test_declared_integrity_mismatch_is_quarantined(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    with pytest.raises(IntegrityViolation):
        repo.put_bytes(
            b"bytes",
            kind="test",
            schema_version="v1",
            media_type="application/octet-stream",
            declared_digest=sha256_digest(b"different"),
        )
    assert any(repo.quarantine.iterdir())


def test_blob_symlink_poison_is_rejected_without_following(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    data = b"symlink-target-content"
    digest = sha256_digest(data)
    target = repo.blob_path(digest)
    target.parent.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_bytes(b"do-not-touch")
    target.symlink_to(victim)

    with pytest.raises(IntegrityViolation, match="safe regular file"):
        put(repo, data)
    assert target.is_symlink()
    assert victim.read_bytes() == b"do-not-touch"
    with pytest.raises(RecordNotFound):
        repo.get_content(digest)


def test_process_crash_leaves_only_orphan_blob(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_after_blob, args=(str(root),)
    )
    process.start()
    process.join(10)
    assert process.exitcode == 77
    repo = LocalArtifactRepository(root)
    digest = sha256_digest(b"process-orphan")
    assert repo.blob_path(digest).is_file()
    with pytest.raises(RecordNotFound):
        repo.get_content(digest)


def test_actual_concurrent_compare_and_swap_has_one_winner(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    repo = LocalArtifactRepository(root)
    repo.compare_and_swap_pointer("active", None, "initial")
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def contender(target: str) -> None:
        candidate = LocalArtifactRepository(root)
        barrier.wait()
        try:
            candidate.compare_and_swap_pointer("active", 1, target)
            outcomes.append(f"won:{target}")
        except PointerConflict:
            outcomes.append(f"lost:{target}")

    threads = [
        threading.Thread(target=contender, args=(target,)) for target in ("one", "two")
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(10)
    assert sorted(item.split(":", 1)[0] for item in outcomes) == ["lost", "won"]
    assert repo.get_pointer("active").revision == 2


def test_custody_and_decision_retrieval_apis(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    content = put(repo)
    receipt = CustodyReceipt.create(
        content_digest=content.content_digest,
        storage_uri="fixture://one",
        observed_at="2026-01-01T00:00:00Z",
        actor="test",
    )
    decision = DecisionRecord.create(
        subject_id="subject",
        decision_type="accept",
        payload={"accepted": True},
        actor="test",
        recorded_at="2026-01-01T00:00:00Z",
    )
    repo.add_custody(receipt)
    repo.append_decision(decision)
    assert repo.get_custody(receipt.receipt_id) == receipt
    assert repo.list_custody(content_digest=content.content_digest) == (receipt,)
    assert repo.get_decision(decision.decision_id) == decision
    assert repo.list_decisions(subject_id="subject") == (decision,)
