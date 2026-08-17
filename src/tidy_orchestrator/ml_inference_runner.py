"""Isolated native-XGBoost inference runner; loads native JSON models only."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from ml_contract import canonical_digest_v1

MAX_CELLS = 25_000
FEATURE_SCHEMA = "tidy.ml-feature-batch/v1"
HINT_SCHEMA = "tidy.ml-hints/v1"
PACKAGE_ID = "tidycell-all-approved-gold-exclusion-xgboost-v1"
PACKAGE_MANIFEST = (
    "sha256:75361df90d525c9c723f016f246ef141814ef693fe9579dbcf9f5ca7a253365a"
)
COHORT = "sha256:4afece250764eaf8c9acb57e491c894a0599d468b0005a760076153dccdd9d53"
ROLE_NATIVE = "sha256:280973a12874d7d44457c96f8d6a4bec90297b6ae07f017494dab425950811bc"
DIRECTION_NATIVE = (
    "sha256:c95a62171ba86a757b2848e69374fc58facf52d5b4d6ee4b4c64bf4e5e6bd720"
)
_ADDRESS = re.compile(r"^R[1-9][0-9]{0,6}C[1-9][0-9]{0,6}$")


class InputIntegrityError(ValueError):
    pass


class PackageIntegrityError(RuntimeError):
    pass


class CleanPredictionError(RuntimeError):
    pass


def load_request(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > 15_000_000:
        raise InputIntegrityError("feature request exceeds 15 MB")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise InputIntegrityError("feature request is not strict JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "workbookDigest",
        "sheet",
        "packageId",
        "cells",
        "featureBatchDigest",
    }:
        raise InputIntegrityError("feature request fields are invalid")
    semantic = dict(value)
    identity = semantic.pop("featureBatchDigest")
    if (
        value["schemaVersion"] != FEATURE_SCHEMA
        or value["packageId"] != PACKAGE_ID
        or not valid_digest(value["workbookDigest"])
        or not isinstance(value["sheet"], str)
        or not 0 < len(value["sheet"]) <= 200
        or identity != canonical_digest_v1(semantic)
        or not isinstance(value["cells"], list)
        or len(value["cells"]) > MAX_CELLS
    ):
        raise InputIntegrityError("feature request binding is invalid")
    addresses: set[str] = set()
    for cell in value["cells"]:
        if not isinstance(cell, dict) or set(cell) != {
            "address",
            "roleVector",
            "directionVector",
        }:
            raise InputIntegrityError("feature cell fields are invalid")
        if (
            not isinstance(cell["address"], str)
            or not _ADDRESS.fullmatch(cell["address"])
            or cell["address"] in addresses
            or not valid_vector(cell["roleVector"], 56)
            or not valid_vector(cell["directionVector"], 54)
        ):
            raise InputIntegrityError("feature cell is invalid")
        addresses.add(cell["address"])
    return value


def valid_vector(value: Any, width: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == width
        and all(
            isinstance(item, int | float)
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            and abs(float(item)) <= 1_000_000_000
            for item in value
        )
    )


def valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
    )


def _read_verified(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if "sha256:" + hashlib.sha256(data).hexdigest() != expected:
        raise PackageIntegrityError("snapshot file digest differs")
    return data


def run(request_path: Path, package: Path) -> dict[str, Any]:
    request = load_request(request_path)
    manifest_bytes = _read_verified(package / "manifest.json", PACKAGE_MANIFEST)
    try:
        manifest = json.loads(manifest_bytes, object_pairs_hook=_strict_object)
        role = manifest["models"]["cell-role"]
        direction = manifest["models"]["header-direction"]
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as error:
        raise PackageIntegrityError("snapshot manifest is invalid") from error
    if (
        manifest.get("packageId") != PACKAGE_ID
        or "sha256:" + role.get("nativeSha256", "") != ROLE_NATIVE
        or "sha256:" + direction.get("nativeSha256", "") != DIRECTION_NATIVE
        or manifest.get("sourceCohortSha256") != COHORT.removeprefix("sha256:")
    ):
        raise PackageIntegrityError("snapshot identities differ")
    role_path = package / role["nativePath"]
    direction_path = package / direction["nativePath"]
    _read_verified(role_path, ROLE_NATIVE)
    _read_verified(direction_path, DIRECTION_NATIVE)

    try:
        import numpy as np
        import xgboost as xgb
    except ImportError:
        return {"ok": False, "category": "availability", "code": "ML_RUNTIME_MISSING"}

    role_booster = xgb.Booster(params={"nthread": 1})
    direction_booster = xgb.Booster(params={"nthread": 1})
    role_booster.load_model(role_path)
    direction_booster.load_model(direction_path)
    role_booster.set_param({"nthread": 1})
    direction_booster.set_param({"nthread": 1})
    cells = request["cells"]
    try:
        if cells:
            role_matrix = np.asarray(
                [cell["roleVector"] for cell in cells], dtype=np.float32
            )
            direction_matrix = np.asarray(
                [cell["directionVector"] for cell in cells], dtype=np.float32
            )
            role_probabilities = role_booster.predict(
                xgb.DMatrix(role_matrix), validate_features=True
            )
            direction_probabilities = direction_booster.predict(
                xgb.DMatrix(direction_matrix), validate_features=True
            )
        else:
            role_probabilities = []
            direction_probabilities = []
    except xgb.core.XGBoostError as error:
        raise CleanPredictionError("native prediction failed cleanly") from error

    predictions = []
    for index, cell in enumerate(cells):
        role_row = role_probabilities[index]
        direction_row = direction_probabilities[index]
        role_index = int(np.argmax(role_row))
        direction_index = int(np.argmax(direction_row))
        predictions.append(
            {
                "address": cell["address"],
                "role": role["labels"][role_index],
                "direction": direction["labels"][direction_index],
                "roleConfidence": round(float(role_row[role_index]), 8),
                "directionConfidence": round(float(direction_row[direction_index]), 8),
            }
        )
    semantic = {
        "schemaVersion": HINT_SCHEMA,
        "workbookDigest": request["workbookDigest"],
        "sheet": request["sheet"],
        "featureBatchDigest": request["featureBatchDigest"],
        "packageId": PACKAGE_ID,
        "packageManifestDigest": PACKAGE_MANIFEST,
        "sourceCohortSha256": COHORT,
        "models": {"cellRole": ROLE_NATIVE, "headerDirection": DIRECTION_NATIVE},
        "predictions": predictions,
    }
    return {
        "ok": True,
        "hints": {**semantic, "hintDigest": canonical_digest_v1(semantic)},
    }


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[1] != "--request" or sys.argv[3] != "--package":
        return 2
    try:
        result = run(Path(sys.argv[2]), Path(sys.argv[4]))
    except InputIntegrityError:
        result = {"ok": False, "category": "integrity", "code": "ML_INPUT_INVALID"}
    except CleanPredictionError:
        result = {"ok": False, "category": "inference", "code": "ML_PREDICTION_FAILED"}
    except Exception:
        result = {"ok": False, "category": "integrity", "code": "ML_UNKNOWN_INTEGRITY"}
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


if __name__ == "__main__":
    raise SystemExit(main())
