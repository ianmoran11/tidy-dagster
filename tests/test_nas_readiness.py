from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema.validators import validator_for

from tidy_orchestrator.nas_readiness import (
    CommandResult,
    NasReadinessError,
    _snapshot_observation,
    canonical_report_digest,
    inspect_nas_readiness,
    write_report,
)

PROJECT = Path(__file__).parents[1]
SCHEMA = PROJECT / "contracts/nas-readiness/v1/report.schema.json"
CHECKED_REPORT = PROJECT / "fixtures/nas-readiness/phase-b-current-v1.json"
INSPECTED_AT = "2026-08-11T21:00:00Z"


def _runner(
    mount_path: Path,
    *,
    server_requires_signing: bool = False,
    snapshots: CommandResult | None = None,
):
    share = {
        "SMB_VERSION": "SMB_3.1.1",
        "SIGNING_SUPPORTED": True,
        "SMB_CURR_SIGN_ALGORITHM": "AES-128-CMAC",
        "SIGNING_REQUIRED": server_requires_signing,
        "CLIENT_REQUIRES_SIGNING": False,
        "ENCRYPTION_REQUIRED": False,
        "SMB_CURR_ENCRYPT_ALGORITHM": None,
        "SMB_NEGOTIATE": ["SMBV_NEG_SMB1_ENABLED", "SMBV_NEG_SMB3_ENABLED"],
    }
    values = {
        "/sbin/mount": CommandResult(
            0,
            f"//fixture@server/share on {mount_path} (smbfs, nodev, nosuid)\n",
            "",
        ),
        "/usr/bin/smbutil statshares": CommandResult(0, json.dumps([share]), ""),
        "/usr/bin/smbutil snapshot": snapshots
        or CommandResult(1, "{}", "Resource busy"),
    }

    def run(arguments):
        key = (
            " ".join(arguments[:2])
            if arguments[0].endswith("smbutil")
            else arguments[0]
        )
        return values[key]

    return run


def test_read_only_inspection_is_sanitized_and_fail_closed(tmp_path: Path) -> None:
    mount = tmp_path / "nas"
    metadata = tmp_path / "metadata"
    mount.mkdir()
    metadata.mkdir()
    report = inspect_nas_readiness(
        mount_path=mount,
        metadata_root=metadata,
        inspected_at=INSPECTED_AT,
        command_runner=_runner(mount),
    )
    assert canonical_report_digest(report) == report["reportDigest"]
    assert report["observations"]["smb"]["smb3Current"] is True
    assert report["observations"]["smb"]["signingActiveObserved"] is True
    assert report["observations"]["smb"]["signingRequiredGatePass"] is False
    assert report["gates"]["canaryImportReady"] is False
    assert "smb-signing-not-required" in report["blockers"]
    assert "fixture" not in json.dumps(report)
    assert str(tmp_path) not in json.dumps(report)
    assert report["configurationChanged"] is False
    assert report["rawCommandOutputStored"] is False

    output = tmp_path / "report.json"
    write_report(output, report)
    with pytest.raises(NasReadinessError, match="already exists"):
        write_report(output, report)


def test_signing_requirement_and_snapshot_observations(tmp_path: Path) -> None:
    mount = tmp_path / "nas"
    metadata = tmp_path / "metadata"
    mount.mkdir()
    metadata.mkdir()
    report = inspect_nas_readiness(
        mount_path=mount,
        metadata_root=metadata,
        inspected_at=INSPECTED_AT,
        command_runner=_runner(
            mount,
            server_requires_signing=True,
            snapshots=CommandResult(0, json.dumps({"mount": ["snapshot-1"]}), ""),
        ),
    )
    assert report["gates"]["smbSigningRequired"] is True
    assert report["gates"]["nasSnapshotsAvailable"] is True
    assert "smb-signing-not-required" not in report["blockers"]
    assert "nas-snapshots-unverified" not in report["blockers"]
    assert report["gates"]["canaryImportReady"] is False

    assert _snapshot_observation(CommandResult(1, "", "Resource busy")) == (
        "failed",
        "resource-busy",
        None,
    )
    assert _snapshot_observation(CommandResult(0, "not-json", "")) == (
        "failed",
        "invalid-json",
        None,
    )


def test_report_identity_rejects_authority_tamper(tmp_path: Path) -> None:
    mount = tmp_path / "nas"
    metadata = tmp_path / "metadata"
    mount.mkdir()
    metadata.mkdir()
    report = inspect_nas_readiness(
        mount_path=mount,
        metadata_root=metadata,
        inspected_at=INSPECTED_AT,
        command_runner=_runner(mount),
    )
    tampered = copy.deepcopy(report)
    tampered["gates"]["canaryImportReady"] = True
    with pytest.raises(NasReadinessError, match="identity differs"):
        canonical_report_digest(tampered)


def test_checked_current_report_is_strict_and_blocked() -> None:
    report = json.loads(CHECKED_REPORT.read_text())
    schema = json.loads(SCHEMA.read_text())
    validator = validator_for(schema)
    validator.check_schema(schema)
    validator(schema, format_checker=validator.FORMAT_CHECKER).validate(report)
    assert canonical_report_digest(report) == (
        "sha256:0515d6b98ded8206170ecba7cc2188ba58f7828c21726f500724106f34607053"
    )
    assert report["observations"]["smb"] == {
        "inspectionSucceeded": True,
        "currentVersion": "SMB_3.1.1",
        "smb3Current": True,
        "signingSupported": True,
        "signingActiveObserved": True,
        "currentSigningAlgorithm": "AES-128-CMAC",
        "serverSigningRequired": False,
        "clientSigningRequired": False,
        "signingRequiredGatePass": False,
        "encryptionRequired": False,
        "currentEncryptionAlgorithm": None,
        "legacySmb1NegotiationAdvertised": True,
    }
    assert report["gates"] == {
        "smb3Current": True,
        "smbSigningRequired": False,
        "dedicatedNonAdminServiceIdentity": False,
        "nasSnapshotsAvailable": False,
        "restoreDrillPassed": False,
        "sqliteLocal": True,
        "commitMarkerAdapterVerified": False,
        "canaryImportReady": False,
    }
    assert report["configurationChanged"] is False
    assert report["rawCommandOutputStored"] is False
