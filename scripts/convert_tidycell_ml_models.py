#!/usr/bin/env python3
"""Reproducibly convert approved TidyCell custody pickles under Seatbelt.

The public command is a safe launcher. Only its structurally-attested child opens
pickle bytes. A direct child invocation fails both fork and network enforcement
probes before any pickle is opened.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

EXPECTED = {
    "cell-role": {
        "pickle": "xgboost-cell-role-all-approved-excl.pkl",
        "pickleSha256": (
            "b86816a5836c3f2cb3adcfcb69b3c216c95bb16a79ed81d613a0e6d1df3dc3e3"
        ),
        "metadata": "xgboost-cell-role-all-approved-excl.metadata.json",
        "metadataSha256": (
            "2112699cd6e4109fc8b8bdbb2be64a4d79b6ad585303165ac208a6c98812395c"
        ),
        "native": "xgboost-cell-role-all-approved-excl.json",
        "labelsKey": "roles",
        "labels": ["blank", "header", "unused", "value"],
        "features": 56,
    },
    "header-direction": {
        "pickle": "xgboost-header-direction-all-approved-excl.pkl",
        "pickleSha256": (
            "551a79b41ca0130f53e58786343c783af2a20fb97b7fc75c789ed461c9a78476"
        ),
        "metadata": "xgboost-header-direction-all-approved-excl.metadata.json",
        "metadataSha256": (
            "14a46b23aebeeee35f6db9a93391f81fe0dfda559dcb2813d790cf12407fa02f"
        ),
        "native": "xgboost-header-direction-all-approved-excl.json",
        "labelsKey": "directions",
        "labels": ["N", "NNW", "W", "WNW"],
        "features": 54,
    },
}
COHORT_SHA256 = "4afece250764eaf8c9acb57e491c894a0599d468b0005a760076153dccdd9d53"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-models", type=Path, required=True)
    parser.add_argument("--tidycell-ml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--_sandboxed-child", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args._sandboxed_child:
        _attest_sandbox()
        _convert(args.source_models, args.tidycell_ml, args.output)
        return
    _launch_sandboxed(args)


def _launch_sandboxed(args: argparse.Namespace) -> None:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise SystemExit("conversion requires macOS /usr/bin/sandbox-exec")
    requested_output = args.output.resolve()
    if args.check:
        generated = Path(tempfile.mkdtemp(prefix="tidy-ml-conversion-check-")).resolve()
    else:
        generated = requested_output
        if generated.exists() and any(generated.iterdir()):
            raise SystemExit("conversion output must be empty")
        generated.mkdir(parents=True, exist_ok=True)
    python = args.python.absolute()
    details = json.loads(
        subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import json,site,sys;print(json.dumps({"
                    "'base':sys._base_executable,'prefix':sys.base_prefix,"
                    "'sites':site.getsitepackages()}))"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    framework_executable = (
        Path(details["prefix"]) / "Resources/Python.app/Contents/MacOS/Python"
    ).resolve()
    executable = (
        framework_executable
        if framework_executable.is_file()
        else Path(details["base"]).resolve()
    )
    read_roots = {
        Path("/System"),
        Path("/usr"),
        Path("/Library"),
        Path(details["prefix"]).resolve(),
        python.parent.parent.resolve(),
        args.source_models.resolve(),
        args.tidycell_ml.resolve(),
        args.tidycell_ml.resolve().parent / "LICENSE",
        Path(__file__).resolve(),
        Path("/opt/homebrew/opt/libomp"),
        Path("/opt/homebrew/opt/libomp").resolve(),
        generated,
    }
    clauses = "\n".join(
        f'  (subpath "{_quote(str(path))}")'
        if path.is_dir()
        else f'  (literal "{_quote(str(path))}")'
        for path in sorted(read_roots, key=str)
        if path.exists()
    )
    ancestors = {
        parent
        for path in read_roots
        for parent in path.absolute().parents
        if parent != Path("/")
    }
    metadata_clauses = "\n".join(
        f'  (literal "{_quote(str(path))}")' for path in sorted(ancestors, key=str)
    )
    profile_text = (
        '(version 1)\n(deny default)\n(import "system.sb")\n'
        f'(allow process-exec (literal "{_quote(str(executable))}"))\n'
        "(deny process-fork)\n(deny network*)\n(allow sysctl-read)\n"
        f"(allow file-read-metadata\n{metadata_clauses})\n"
        "(allow mach-lookup\n"
        '  (global-name "com.apple.system.notification_center")\n'
        '  (global-name "com.apple.system.opendirectoryd.libinfo"))\n'
        f"(allow file-read*\n{clauses})\n"
        f'(allow file-write* (subpath "{_quote(str(generated))}"))\n'
    )
    profile = Path(tempfile.mkstemp(prefix="tidy-ml-convert-", suffix=".sb")[1])
    try:
        profile.write_text(profile_text)
        profile.chmod(0o400)
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(generated),
            "TMPDIR": str(generated),
            "TZ": "UTC",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "PYTHONPATH": os.pathsep.join(details["sites"]),
        }
        command = [
            "/usr/bin/sandbox-exec",
            "-f",
            str(profile),
            str(executable),
            str(Path(__file__).resolve()),
            "--source-models",
            str(args.source_models.resolve()),
            "--tidycell-ml",
            str(args.tidycell_ml.resolve()),
            "--output",
            str(generated),
            "--python",
            str(python),
            "--_sandboxed-child",
        ]
        subprocess.run(command, env=environment, check=True)
        if args.check:
            _compare_directories(generated, requested_output)
    finally:
        profile.unlink(missing_ok=True)
        if args.check:
            shutil.rmtree(generated, ignore_errors=True)


def _attest_sandbox() -> None:
    network_denied = False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
    except OSError as error:
        network_denied = error.errno in {errno.EPERM, errno.EACCES}
    finally:
        probe.close()
    fork_denied = False
    try:
        child = os.fork()
    except OSError as error:
        fork_denied = error.errno in {errno.EPERM, errno.EACCES}
    else:
        if child == 0:
            os._exit(97)
        os.waitpid(child, 0)
    if not network_denied or not fork_denied:
        raise SystemExit("unsafe conversion child lacks enforced network/fork denial")


def _convert(source_models: Path, tidycell_ml: Path, output: Path) -> None:
    import pickle

    source = source_models.resolve()
    tidycell_ml = tidycell_ml.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(tidycell_ml))
    from recipe_prepass.train_cell_classifier import register_pickle_classes

    register_pickle_classes()
    import numpy as np
    import sklearn
    import xgboost as xgb

    receipt_models: dict[str, Any] = {}
    manifest_models: dict[str, Any] = {}
    for task, expected in EXPECTED.items():
        pickle_path = source / expected["pickle"]
        metadata_path = source / expected["metadata"]
        if sha256(pickle_path) != expected["pickleSha256"]:
            raise SystemExit(f"{task} pickle identity mismatch")
        if sha256(metadata_path) != expected["metadataSha256"]:
            raise SystemExit(f"{task} metadata identity mismatch")
        metadata = json.loads(metadata_path.read_bytes())
        if len(metadata.get("featureNames", [])) != expected["features"]:
            raise SystemExit(f"{task} feature metadata mismatch")
        with pickle_path.open("rb") as handle:
            bundle = pickle.load(handle)
        estimator = bundle["estimator"]
        classifier = estimator.classifier
        labels = [str(value) for value in estimator.classes_]
        bundle_labels = [str(value) for value in bundle[expected["labelsKey"]]]
        metadata_labels = metadata.get(expected["labelsKey"], metadata.get("roles"))
        if (
            labels != expected["labels"]
            or labels != bundle_labels
            or labels != metadata_labels
        ):
            raise SystemExit(f"{task} fitted label mapping mismatch")
        booster = classifier.get_booster()
        booster.set_param({"nthread": 1})
        native_path = output / expected["native"]
        booster.save_model(native_path)
        width = expected["features"]
        rng = np.random.default_rng(20260814)
        vectors = np.vstack(
            [
                np.zeros((1, width), dtype=np.float32),
                np.ones((1, width), dtype=np.float32),
                np.linspace(-2.0, 2.0, width, dtype=np.float32).reshape(1, -1),
                rng.normal(0.0, 1.0, size=(13, width)).astype(np.float32),
            ]
        )
        wrapped = np.asarray(classifier.predict_proba(vectors), dtype=np.float64)
        decoded_wrapper = [str(value) for value in estimator.predict(vectors)]
        native_booster = xgb.Booster(params={"nthread": 1})
        native_booster.load_model(native_path)
        native = np.asarray(
            native_booster.predict(xgb.DMatrix(vectors), validate_features=True),
            dtype=np.float64,
        )
        decoded_native = [labels[int(index)] for index in np.argmax(native, axis=1)]
        maximum_error = float(np.max(np.abs(wrapped - native)))
        if (
            wrapped.shape != native.shape
            or maximum_error > 1e-7
            or decoded_wrapper != decoded_native
        ):
            raise SystemExit(f"{task} native probability/label parity mismatch")
        manifest_models[task] = {
            "task": metadata["task"],
            "modelFamily": metadata["modelFamily"],
            "modelVersion": metadata["modelVersion"],
            "nativePath": expected["native"],
            "nativeFormat": "xgboost-json",
            "nativeSha256": sha256(native_path),
            "sourcePicklePath": expected["pickle"],
            "sourcePickleSha256": expected["pickleSha256"],
            "sourceMetadataPath": expected["metadata"],
            "sourceMetadataSha256": expected["metadataSha256"],
            "labels": labels,
            "featureNames": metadata["featureNames"],
            "numericFeatures": metadata["numericFeatures"],
            "booleanFeatures": metadata["booleanFeatures"],
            "categoricalFeatures": metadata["categoricalFeatures"],
            "categoricalValues": metadata["categoricalValues"],
        }
        receipt_models[task] = {
            "nativeSha256": sha256(native_path),
            "parityVectorCount": int(vectors.shape[0]),
            "maximumAbsoluteProbabilityError": maximum_error,
            "probabilityArgmaxIdentity": True,
            "decodedLabelIdentity": True,
            "derivedLabels": labels,
        }
    for expected in EXPECTED.values():
        for key in ("pickle", "metadata"):
            source_path = source / expected[key]
            (output / expected[key]).write_bytes(source_path.read_bytes())
    license_path = tidycell_ml.parent / "LICENSE"
    (output / "TIDYCELL_LICENSE.txt").write_bytes(license_path.read_bytes())
    receipt = {
        "schemaVersion": "tidy.ml-native-conversion-receipt/v1",
        "sourcePackage": "TidyCell all-approved-gold exclusion models",
        "sourceCohortSha256": COHORT_SHA256,
        "conversionScriptSha256": sha256(Path(__file__).resolve()),
        "toolchain": {
            "python": ".".join(map(str, sys.version_info[:3])),
            "xgboost": xgb.__version__,
            "scikitLearn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "sandbox": {
            "attestation": "active-denial-probes-v1",
            "required": True,
            "executable": "/usr/bin/sandbox-exec",
            "networkDenied": True,
            "forkDenied": True,
        },
        "models": receipt_models,
    }
    (output / "conversion-receipt.json").write_bytes(canonical(receipt))
    package_files = [
        {"path": path.name, "byteLength": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(output.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.name != "manifest.json"
    ]
    manifest = {
        "schemaVersion": "tidy.ml-model-package/v1",
        "packageId": "tidycell-all-approved-gold-exclusion-xgboost-v1",
        "sourceRepository": "https://github.com/ianmoran11/tidycell",
        "license": "MIT",
        "sourceCohortSha256": COHORT_SHA256,
        "exactExclusionClaim": (
            "all-approved-gold cohort identified by exact source cohort SHA-256"
        ),
        "models": manifest_models,
        "files": package_files,
    }
    (output / "manifest.json").write_bytes(canonical(manifest))


def _compare_directories(generated: Path, expected: Path) -> None:
    generated_files = {path.name: path.read_bytes() for path in generated.iterdir()}
    expected_files = {path.name: path.read_bytes() for path in expected.iterdir()}
    if generated_files != expected_files:
        raise SystemExit("vendored package differs from sandboxed conversion output")


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


if __name__ == "__main__":
    main()
