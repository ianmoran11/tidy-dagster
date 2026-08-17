from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from tidy_orchestrator.ml_gateway import (
    DIRECTION_DIGEST,
    MANIFEST_SHA256,
    ROLE_DIGEST,
)

PROJECT = Path(__file__).parents[1]
PACKAGE = PROJECT / "vendor/tidycell-ml/all-approved-gold-exclusion-v1"
CONVERTER = PROJECT / "scripts/convert_tidycell_ml_models.py"


def test_vendored_package_hashes_closure_and_decoded_label_parity() -> None:
    manifest_bytes = (PACKAGE / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256
    manifest = json.loads(manifest_bytes)
    assert {
        path.name for path in PACKAGE.iterdir() if path.name != "manifest.json"
    } == {item["path"] for item in manifest["files"]}
    for item in manifest["files"]:
        data = (PACKAGE / item["path"]).read_bytes()
        assert len(data) == item["byteLength"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
    assert "sha256:" + manifest["models"]["cell-role"]["nativeSha256"] == ROLE_DIGEST
    assert (
        "sha256:" + manifest["models"]["header-direction"]["nativeSha256"]
        == DIRECTION_DIGEST
    )
    receipt = json.loads((PACKAGE / "conversion-receipt.json").read_text())
    assert receipt["sandbox"] == {
        "attestation": "active-denial-probes-v1",
        "executable": "/usr/bin/sandbox-exec",
        "forkDenied": True,
        "networkDenied": True,
        "required": True,
    }
    for model in receipt["models"].values():
        assert model["decodedLabelIdentity"] is True
        assert model["probabilityArgmaxIdentity"] is True
        assert model["maximumAbsoluteProbabilityError"] <= 1e-7


def test_plain_unsandboxed_conversion_child_cannot_create_receipt(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(CONVERTER),
            "--source-models",
            str(PACKAGE),
            "--tidycell-ml",
            str(PROJECT),
            "--output",
            str(tmp_path / "output"),
            "--_sandboxed-child",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "lacks enforced network/fork denial" in completed.stderr
    assert not (tmp_path / "output" / "conversion-receipt.json").exists()


def test_runtime_modules_do_not_deserialize_custody_pickles() -> None:
    for name in ("ml_gateway.py", "ml_inference_runner.py", "ml_contract.py"):
        text = (PROJECT / "src/tidy_orchestrator" / name).read_text()
        assert "import pickle" not in text
        assert "joblib" not in text
