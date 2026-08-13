from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tidy_orchestrator.artifacts import canonical_json_bytes, domain_digest
from tidy_orchestrator.canary_mvp import (
    CanaryImportAuthorization,
    CanaryMvpError,
    build_canary_snapshot,
    verify_canary_snapshot,
)
from tidy_orchestrator.migration_import import ImportAuthorizationError

CANARY_DIGEST = (
    "sha256:ee072650751fa76d456ba8cf034878a2a48137b02e6e7d459cb7945cb9474139"
)
SOURCE_DIGEST = (
    "sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d"
)
TIME = "2026-08-12T10:00:00Z"


def _source_item(index: int) -> dict:
    data = f"item-{index}".encode()
    return {
        "relativePath": f"items/{index:02d}.json",
        "entryType": "file",
        "artifactClass": "generation-json-evidence",
        "disposition": "import",
        "ruleId": "fixture-generation",
        "sourceMode": 0o100600,
        "byteLength": len(data),
        "contentDigest": f"sha256:{index:064x}",
        "gitState": "tracked",
        "embeddedRecords": [],
        "warnings": [],
    }


def _source_snapshot(source: Path) -> dict:
    items = [_source_item(index) for index in range(1, 64)]
    inventory = {
        "source": {
            "sourceSystem": "tidycell",
            "sourceRootId": "phase-a-root",
            "filesystem": {
                "deviceId": source.lstat().st_dev,
                "rootInode": source.lstat().st_ino,
                "rootMode": source.lstat().st_mode,
            },
        },
        "policy": {},
        "exporter": {},
        "safety": {},
        "items": items,
        "itemManifestDigest": domain_digest("tidy.export-item-manifest/v1", items),
        "summary": {},
    }
    inventory["inventoryDigest"] = domain_digest(
        "tidy.source-export-inventory/v1",
        {key: value for key, value in inventory.items() if key != "inventoryDigest"},
    )
    return {"snapshotDigest": SOURCE_DIGEST, "inventory": inventory}


def _capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tidy_orchestrator.canary_mvp.os.statvfs",
        lambda _path: type(
            "Capacity",
            (),
            {"f_blocks": 100_000_000, "f_frsize": 4096, "f_bavail": 90_000_000},
        )(),
    )


def _manifest(snapshot: dict) -> dict:
    selected = []
    for item in snapshot["inventory"]["items"]:
        selected.append(
            {
                "relativePath": item["relativePath"],
                "entryType": item["entryType"],
                "artifactClass": item["artifactClass"],
                "disposition": item["disposition"],
                "sourceMode": item["sourceMode"],
                "byteLength": item["byteLength"],
                "contentDigest": item["contentDigest"],
                "sourceItemDigest": domain_digest("tidy.export-item/v1", item),
            }
        )
    return {
        "manifestDigest": CANARY_DIGEST,
        "sourceSnapshot": {
            "snapshotDigest": SOURCE_DIGEST,
            "inventoryDigest": snapshot["inventory"]["inventoryDigest"],
            "itemManifestDigest": snapshot["inventory"]["itemManifestDigest"],
        },
        "selectedItemSetDigest": domain_digest(
            "tidy.migration-canary-item-set/v1", selected
        ),
        "selectedItems": selected,
        "coverage": {
            "itemCount": 63,
            "sourceReadBytes": sum(item["byteLength"] for item in selected),
            "uniqueCopyBytes": sum(item["byteLength"] for item in selected),
        },
    }


def test_canary_snapshot_is_exact_and_authority_is_narrow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    blobs = tmp_path / "blobs"
    source.mkdir()
    blobs.mkdir()
    _capacity(monkeypatch)
    snapshot = _source_snapshot(source)
    manifest = _manifest(snapshot)
    monkeypatch.setattr(
        "tidy_orchestrator.canary_mvp.canonical_manifest_digest",
        lambda value: value["manifestDigest"],
    )
    canary = build_canary_snapshot(
        source_snapshot=snapshot,
        manifest=manifest,
        source_root=source,
        blob_root=blobs,
        frozen_at=TIME,
    )
    assert verify_canary_snapshot(canary) == canary["snapshotDigest"]
    assert canary["canary"] == {
        "manifestDigest": CANARY_DIGEST,
        "sourceSnapshotDigest": SOURCE_DIGEST,
        "selectedItemSetDigest": manifest["selectedItemSetDigest"],
        "disposableLocalBlobData": True,
        "nasRequired": False,
        "fullImportAuthorized": False,
        "providerDispatchAuthorized": False,
        "activationAuthorized": False,
        "trainingAuthorized": False,
    }
    assert canary["inventory"]["summary"]["itemCount"] == 63
    authorization = CanaryImportAuthorization.create(
        manifest=manifest,
        snapshot=canary,
        source_root=source,
    )
    authorization.validate(canary, source)
    altered = copy.deepcopy(canary)
    altered["inventory"]["items"].append(
        copy.deepcopy(altered["inventory"]["items"][0])
    )
    with pytest.raises(ImportAuthorizationError, match="bounds"):
        authorization.validate(altered, source)


def test_canary_snapshot_rejects_authority_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    blobs = tmp_path / "blobs"
    source.mkdir()
    blobs.mkdir()
    _capacity(monkeypatch)
    snapshot = _source_snapshot(source)
    manifest = _manifest(snapshot)
    monkeypatch.setattr(
        "tidy_orchestrator.canary_mvp.canonical_manifest_digest",
        lambda value: value["manifestDigest"],
    )
    canary = build_canary_snapshot(
        source_snapshot=snapshot,
        manifest=manifest,
        source_root=source,
        blob_root=blobs,
        frozen_at=TIME,
    )
    tampered = copy.deepcopy(canary)
    tampered["canary"]["fullImportAuthorized"] = True
    with pytest.raises(CanaryMvpError, match="authority"):
        verify_canary_snapshot(tampered)
    assert b"fullImportAuthorized" in canonical_json_bytes(canary)
