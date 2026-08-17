"""Narrow sandboxed gateway for optional local native-XGBoost hints."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - exercised in an isolated import test
    resource = None  # type: ignore[assignment]

from .ml_contract import canonical_digest_v1

PACKAGE_RELATIVE = Path("vendor/tidycell-ml/all-approved-gold-exclusion-v1")
MANIFEST_SHA256 = "75361df90d525c9c723f016f246ef141814ef693fe9579dbcf9f5ca7a253365a"
PACKAGE_ID = "tidycell-all-approved-gold-exclusion-xgboost-v1"
COHORT_DIGEST = (
    "sha256:4afece250764eaf8c9acb57e491c894a0599d468b0005a760076153dccdd9d53"
)
ROLE_DIGEST = "sha256:280973a12874d7d44457c96f8d6a4bec90297b6ae07f017494dab425950811bc"
DIRECTION_DIGEST = (
    "sha256:c95a62171ba86a757b2848e69374fc58facf52d5b4d6ee4b4c64bf4e5e6bd720"
)
MAX_REQUEST_BYTES = 15_000_000
MAX_OUTPUT_BYTES = 5_000_000
MAX_STDERR_BYTES = 64_000
_ADDRESS = re.compile(r"^R[1-9][0-9]{0,6}C[1-9][0-9]{0,6}$")


class MlGatewayError(RuntimeError):
    def __init__(self, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.category = category


class MlUnavailable(MlGatewayError):
    pass


class MlIntegrityError(MlGatewayError):
    pass


@dataclass(frozen=True)
class MlGatewayConfig:
    python: Path
    runner: Path
    package: Path
    sandbox_mode: str
    timeout_seconds: float = 8.0
    max_output_bytes: int = MAX_OUTPUT_BYTES
    max_stderr_bytes: int = MAX_STDERR_BYTES
    runtime_read_roots: tuple[Path, ...] = ()
    python_path: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        if self.sandbox_mode not in {"macos-production", "insecure-test-only"}:
            raise ValueError("invalid ML sandbox mode")
        if self.sandbox_mode == "macos-production":
            if (
                sys.platform != "darwin"
                or resource is None
                or not Path("/usr/bin/sandbox-exec").is_file()
            ):
                raise ValueError("production ML requires /usr/bin/sandbox-exec")
            if not self.runtime_read_roots:
                raise ValueError("production ML requires explicit runtime read roots")


@dataclass(frozen=True)
class _PackageIdentity:
    manifest_digest: str
    role_path: str
    direction_path: str


class MlGateway:
    def __init__(self, config: MlGatewayConfig) -> None:
        self.config = config

    def infer(self, feature_bytes: bytes) -> dict[str, Any]:
        expected = _validate_feature_request(feature_bytes)
        root = Path(tempfile.mkdtemp(prefix="tidy-ml-"))
        os.chmod(root, 0o700)
        process: subprocess.Popen[bytes] | None = None
        try:
            snapshot_root = root / "snapshot"
            snapshot_root.mkdir(mode=0o700)
            package_snapshot, identity = self._snapshot_verified_package(snapshot_root)
            os.chmod(package_snapshot, 0o500)
            os.chmod(snapshot_root, 0o500)
            run_root = root / "run"
            run_root.mkdir(mode=0o700)
            runtime = run_root / "runtime"
            runtime.mkdir(mode=0o700)
            runner = runtime / "ml_inference_runner.py"
            contract = runtime / "ml_contract.py"
            _copy_regular(self.config.runner, runner)
            _copy_regular(Path(__file__).with_name("ml_contract.py"), contract)
            request = run_root / "request.json"
            _write_exclusive(request, feature_bytes, 0o400)
            stdout = run_root / "stdout.bin"
            stderr = run_root / "stderr.bin"
            command = [
                str(self.config.python),
                str(runner),
                "--request",
                str(request),
                "--package",
                str(package_snapshot),
            ]
            launch = self._sandbox_command(
                command,
                root,
                run_root,
                snapshot_root,
                runner,
                contract,
            )
            environment = self._environment(run_root)
            try:
                with stdout.open("xb") as out, stderr.open("xb") as err:
                    process = subprocess.Popen(
                        launch,
                        cwd=run_root,
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=out,
                        stderr=err,
                        close_fds=True,
                        start_new_session=True,
                        preexec_fn=self._apply_limits,
                    )
                    return_code = self._wait_bounded(process, stdout, stderr)
            except FileNotFoundError as error:
                raise MlUnavailable(
                    "ML_RUNTIME_MISSING", "availability", "ML runtime is absent"
                ) from error
            except subprocess.SubprocessError as error:
                raise MlIntegrityError(
                    "ML_LIMIT_SETUP_FAILED",
                    "integrity",
                    "ML process security setup failed",
                ) from error
            except OSError as error:
                raise MlIntegrityError(
                    "ML_LAUNCH_INTEGRITY", "integrity", "ML launch failed unexpectedly"
                ) from error

            if return_code != 0:
                if return_code in {-signal.SIGXCPU, -signal.SIGXFSZ, -signal.SIGKILL}:
                    raise MlUnavailable(
                        "ML_RESOURCE_LIMIT", "availability", "ML resource limit reached"
                    )
                preview = stderr.read_bytes()[:512].decode("utf-8", errors="replace")
                raise MlIntegrityError(
                    "ML_RUNNER_NONZERO",
                    "integrity",
                    f"ML runner exited unexpectedly: {preview}",
                )
            try:
                lines = (
                    stdout.read_bytes().decode("utf-8", errors="strict").splitlines()
                )
            except UnicodeDecodeError as error:
                raise MlIntegrityError(
                    "ML_MALFORMED_OUTPUT", "integrity", "ML output is not UTF-8"
                ) from error
            if len(lines) != 1 or not lines[0]:
                raise MlIntegrityError(
                    "ML_MALFORMED_OUTPUT",
                    "integrity",
                    "ML emitted extra or missing output",
                )
            try:
                value = json.loads(lines[0], object_pairs_hook=_strict_object)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                raise MlIntegrityError(
                    "ML_MALFORMED_OUTPUT", "integrity", "ML output is malformed"
                ) from error
            if not isinstance(value, dict) or set(value) not in (
                {"ok", "hints"},
                {"ok", "category", "code"},
            ):
                raise MlIntegrityError(
                    "ML_MALFORMED_OUTPUT", "integrity", "ML envelope fields are invalid"
                )
            try:
                self._reverify_snapshot(package_snapshot, identity)
            except OSError as error:
                raise MlIntegrityError(
                    "ML_SNAPSHOT_INTEGRITY",
                    "integrity",
                    "Snapshot became unreadable",
                ) from error
            if value.get("ok") is False:
                code = value.get("code")
                category = value.get("category")
                if (category, code) in {
                    ("availability", "ML_RUNTIME_MISSING"),
                    ("inference", "ML_PREDICTION_FAILED"),
                }:
                    raise MlUnavailable(str(code), "availability", "ML is unavailable")
                preview = stderr.read_bytes()[:512].decode("utf-8", errors="replace")
                raise MlIntegrityError(
                    str(code),
                    "integrity",
                    f"ML runner reported an integrity failure: {preview}",
                )
            if value.get("ok") is not True or not isinstance(value.get("hints"), dict):
                raise MlIntegrityError(
                    "ML_MALFORMED_OUTPUT", "integrity", "ML success is invalid"
                )
            _validate_hints(value["hints"], expected, identity)
            return value["hints"]
        finally:
            if process is not None and process.poll() is None:
                _terminate_group(process)
            shutil.rmtree(root, ignore_errors=True)

    def _snapshot_verified_package(self, root: Path) -> tuple[Path, _PackageIdentity]:
        package = self.config.package
        try:
            root_info = package.lstat()
            if not stat.S_ISDIR(root_info.st_mode) or package.is_symlink():
                raise ValueError("package root is not a real directory")
            manifest_path = package / "manifest.json"
            manifest_bytes = _read_regular(manifest_path)
            manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
            if manifest_digest != "sha256:" + MANIFEST_SHA256:
                raise ValueError("manifest digest")
            manifest = json.loads(manifest_bytes, object_pairs_hook=_strict_object)
            if (
                not isinstance(manifest, dict)
                or manifest.get("packageId") != PACKAGE_ID
            ):
                raise ValueError("manifest identity")
            files = manifest.get("files")
            if not isinstance(files, list):
                raise ValueError("manifest files")
            declared: dict[str, dict[str, Any]] = {}
            for item in files:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"path", "byteLength", "sha256"}
                    or not isinstance(item.get("path"), str)
                    or Path(item["path"]).name != item["path"]
                    or "/" in item["path"]
                    or "\\" in item["path"]
                    or item["path"] in declared
                ):
                    raise ValueError("unsafe package declaration")
                declared[item["path"]] = item
            actual: set[str] = set()
            with os.scandir(package) as entries:
                for entry in entries:
                    if entry.name == "manifest.json":
                        if not entry.is_file(follow_symlinks=False):
                            raise ValueError("manifest is not regular")
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise ValueError("package contains non-regular entry")
                    actual.add(entry.name)
            if actual != set(declared):
                raise ValueError("package closure")
            verified: dict[str, bytes] = {}
            for name, item in declared.items():
                data = _read_regular(package / name)
                if (
                    not isinstance(item["byteLength"], int)
                    or item["byteLength"] != len(data)
                    or item["sha256"] != hashlib.sha256(data).hexdigest()
                ):
                    raise ValueError("package file digest")
                verified[name] = data
            role = manifest["models"]["cell-role"]
            direction = manifest["models"]["header-direction"]
            role_path = role["nativePath"]
            direction_path = direction["nativePath"]
            if (
                role_path not in verified
                or direction_path not in verified
                or "sha256:" + role["nativeSha256"] != ROLE_DIGEST
                or "sha256:" + direction["nativeSha256"] != DIRECTION_DIGEST
                or manifest.get("sourceCohortSha256")
                != COHORT_DIGEST.removeprefix("sha256:")
            ):
                raise ValueError("model identities")
            snapshot = root / "models"
            snapshot.mkdir(mode=0o700)
            _write_exclusive(snapshot / "manifest.json", manifest_bytes, 0o400)
            _write_exclusive(snapshot / role_path, verified[role_path], 0o400)
            _write_exclusive(snapshot / direction_path, verified[direction_path], 0o400)
            identity = _PackageIdentity(manifest_digest, role_path, direction_path)
            self._reverify_snapshot(snapshot, identity)
            return snapshot, identity
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise MlIntegrityError(
                "ML_PACKAGE_INTEGRITY",
                "integrity",
                "Vendored ML package integrity failed",
            ) from error

    @staticmethod
    def _reverify_snapshot(snapshot: Path, identity: _PackageIdentity) -> None:
        expected = {"manifest.json", identity.role_path, identity.direction_path}
        actual: set[str] = set()
        with os.scandir(snapshot) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    raise MlIntegrityError(
                        "ML_SNAPSHOT_INTEGRITY", "integrity", "Snapshot entry changed"
                    )
                actual.add(entry.name)
        if actual != expected:
            raise MlIntegrityError(
                "ML_SNAPSHOT_INTEGRITY", "integrity", "Snapshot closure changed"
            )
        if (
            "sha256:"
            + hashlib.sha256(_read_regular(snapshot / "manifest.json")).hexdigest()
            != identity.manifest_digest
        ):
            raise MlIntegrityError(
                "ML_SNAPSHOT_INTEGRITY", "integrity", "Snapshot manifest changed"
            )
        for path, expected_digest in (
            (identity.role_path, ROLE_DIGEST),
            (identity.direction_path, DIRECTION_DIGEST),
        ):
            if (
                "sha256:" + hashlib.sha256(_read_regular(snapshot / path)).hexdigest()
                != expected_digest
            ):
                raise MlIntegrityError(
                    "ML_SNAPSHOT_INTEGRITY", "integrity", "Snapshot model changed"
                )

    def _environment(self, root: Path) -> dict[str, str]:
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(root / "home"),
            "TMPDIR": str(root / "tmp"),
            "TZ": "UTC",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
        }
        (root / "home").mkdir(mode=0o700)
        (root / "tmp").mkdir(mode=0o700)
        if self.config.python_path:
            environment["PYTHONPATH"] = os.pathsep.join(
                str(path) for path in self.config.python_path
            )
        return environment

    def _sandbox_command(
        self,
        command: list[str],
        root: Path,
        run_root: Path,
        snapshot_root: Path,
        runner: Path,
        contract: Path,
    ) -> list[str]:
        del runner, contract
        if self.config.sandbox_mode == "insecure-test-only":
            return command
        profile = root / "sandbox.sb"
        read_roots = tuple(
            path.absolute() for path in self.config.runtime_read_roots if path.exists()
        )
        clauses = "\n".join(
            f'  (subpath "{_quote(str(path))}")'
            if path.is_dir()
            else f'  (literal "{_quote(str(path))}")'
            for path in read_roots
        )
        ancestors = {
            parent
            for path in (
                *read_roots,
                root.resolve(),
                run_root.resolve(),
                snapshot_root.resolve(),
            )
            for parent in path.parents
            if parent != Path("/")
        }
        metadata_clauses = "\n".join(
            f'  (literal "{_quote(str(path))}")' for path in sorted(ancestors, key=str)
        )
        executable = _quote(str(self.config.python.resolve()))
        writable_root = _quote(str(run_root.resolve()))
        readonly_snapshot = _quote(str(snapshot_root.resolve()))
        profile_text = (
            "(version 1)\n"
            "(deny default)\n"
            '(import "system.sb")\n'
            f'(allow process-exec (literal "{executable}"))\n'
            "(deny process-fork)\n"
            "(deny network*)\n"
            "(allow sysctl-read)\n"
            f"(allow file-read-metadata\n{metadata_clauses})\n"
            "(allow mach-lookup\n"
            '  (global-name "com.apple.system.notification_center")\n'
            '  (global-name "com.apple.system.opendirectoryd.libinfo"))\n'
            f"(allow file-read*\n{clauses}\n"
            f'  (subpath "{writable_root}")\n'
            f'  (subpath "{readonly_snapshot}"))\n'
            f'(allow file-write* (subpath "{writable_root}"))\n'
        )
        _write_exclusive(profile, profile_text.encode(), 0o400)
        return ["/usr/bin/sandbox-exec", "-f", str(profile), *command]

    def _apply_limits(self) -> None:
        if resource is None:
            raise RuntimeError("resource limits are unavailable")
        for kind, limit in (
            (resource.RLIMIT_CPU, 8),
            (resource.RLIMIT_NOFILE, 64),
            (
                resource.RLIMIT_FSIZE,
                max(self.config.max_output_bytes, self.config.max_stderr_bytes),
            ),
        ):
            _, hard = resource.getrlimit(kind)
            value = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
            resource.setrlimit(kind, (value, value))

    def _wait_bounded(
        self,
        process: subprocess.Popen[bytes],
        stdout: Path,
        stderr: Path,
    ) -> int:
        deadline = time.monotonic() + self.config.timeout_seconds
        while True:
            if stdout.stat().st_size > self.config.max_output_bytes:
                _terminate_group(process)
                raise MlUnavailable(
                    "ML_OUTPUT_LIMIT", "availability", "ML stdout exceeded limit"
                )
            if stderr.stat().st_size > self.config.max_stderr_bytes:
                _terminate_group(process)
                raise MlUnavailable(
                    "ML_STDERR_LIMIT", "availability", "ML stderr exceeded limit"
                )
            return_code = process.poll()
            if return_code is not None:
                if stdout.stat().st_size > self.config.max_output_bytes:
                    _terminate_group(process)
                    raise MlUnavailable(
                        "ML_OUTPUT_LIMIT", "availability", "ML stdout exceeded limit"
                    )
                if stderr.stat().st_size > self.config.max_stderr_bytes:
                    _terminate_group(process)
                    raise MlUnavailable(
                        "ML_STDERR_LIMIT", "availability", "ML stderr exceeded limit"
                    )
                if _group_exists(process.pid):
                    _terminate_group(process)
                    raise MlIntegrityError(
                        "ML_DESCENDANT_LEAK",
                        "integrity",
                        "ML runner left a descendant process",
                    )
                return return_code
            if time.monotonic() >= deadline:
                _terminate_group(process)
                raise MlUnavailable(
                    "ML_TIMEOUT", "availability", "ML inference timed out"
                )
            time.sleep(0.01)


def actual_ml_gateway(project_root: Path) -> MlGateway:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise MlIntegrityError(
            "ML_SANDBOX_REQUIRED", "integrity", "Production ML sandbox is unavailable"
        )
    framework_python = (
        Path(sys.base_prefix) / "Resources/Python.app/Contents/MacOS/Python"
    ).resolve()
    python = (
        framework_python
        if framework_python.is_file()
        else Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    )
    paths = sysconfig.get_paths()
    python_path = tuple(
        dict.fromkeys(
            Path(value).resolve()
            for key, value in paths.items()
            if key in {"purelib", "platlib"} and Path(value).is_dir()
        )
    )
    runtime_roots = tuple(
        dict.fromkeys(
            [
                Path(sys.base_prefix).resolve(),
                *python_path,
                Path("/System/Library"),
                Path("/usr/lib"),
                Path("/Library/Apple"),
                Path("/opt/homebrew/opt/libomp"),
                Path("/opt/homebrew/opt/libomp").resolve(),
            ]
        )
    )
    return MlGateway(
        MlGatewayConfig(
            python=python,
            runner=(
                project_root / "src/tidy_orchestrator/ml_inference_runner.py"
            ).resolve(),
            package=(project_root / PACKAGE_RELATIVE).resolve(),
            sandbox_mode="macos-production",
            runtime_read_roots=runtime_roots,
            python_path=python_path,
        )
    )


def _validate_feature_request(feature_bytes: bytes) -> dict[str, Any]:
    if len(feature_bytes) > MAX_REQUEST_BYTES:
        raise MlIntegrityError(
            "ML_INPUT_LIMIT", "integrity", "ML features exceed limit"
        )
    try:
        value = json.loads(feature_bytes, object_pairs_hook=_strict_object)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        raise MlIntegrityError(
            "ML_INPUT_INVALID", "integrity", "ML input is invalid"
        ) from error
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "workbookDigest",
        "sheet",
        "packageId",
        "cells",
        "featureBatchDigest",
    }:
        raise MlIntegrityError(
            "ML_INPUT_INVALID", "integrity", "ML input fields differ"
        )
    semantic = dict(value)
    identity = semantic.pop("featureBatchDigest", None)
    cells = value.get("cells")
    if (
        value.get("schemaVersion") != "tidy.ml-feature-batch/v1"
        or value.get("packageId") != PACKAGE_ID
        or not _valid_digest(value.get("workbookDigest"))
        or not isinstance(value.get("sheet"), str)
        or not isinstance(cells, list)
        or len(cells) > 25_000
        or identity != canonical_digest_v1(semantic)
    ):
        raise MlIntegrityError(
            "ML_INPUT_INVALID", "integrity", "ML input binding differs"
        )
    addresses: list[str] = []
    for cell in cells:
        if (
            not isinstance(cell, dict)
            or set(cell) != {"address", "roleVector", "directionVector"}
            or not isinstance(cell.get("address"), str)
            or not _ADDRESS.fullmatch(cell["address"])
            or not _valid_vector(cell.get("roleVector"), 56)
            or not _valid_vector(cell.get("directionVector"), 54)
        ):
            raise MlIntegrityError(
                "ML_INPUT_INVALID", "integrity", "ML cell is invalid"
            )
        addresses.append(cell["address"])
    if len(addresses) != len(set(addresses)):
        raise MlIntegrityError("ML_INPUT_INVALID", "integrity", "ML addresses repeat")
    return {
        "workbookDigest": value["workbookDigest"],
        "sheet": value["sheet"],
        "featureBatchDigest": identity,
        "addresses": addresses,
    }


def _validate_hints(
    hints: dict[str, Any],
    expected_request: dict[str, Any],
    identity: _PackageIdentity,
) -> None:
    required = {
        "schemaVersion",
        "workbookDigest",
        "sheet",
        "featureBatchDigest",
        "packageId",
        "packageManifestDigest",
        "sourceCohortSha256",
        "models",
        "predictions",
        "hintDigest",
    }
    semantic = dict(hints)
    hint_digest = semantic.pop("hintDigest", None)
    predictions = hints.get("predictions")
    valid_predictions = isinstance(predictions, list) and all(
        _valid_prediction(item) for item in predictions
    )
    addresses = [item["address"] for item in predictions] if valid_predictions else None
    if (
        set(hints) != required
        or hints.get("schemaVersion") != "tidy.ml-hints/v1"
        or hints.get("packageId") != PACKAGE_ID
        or hints.get("packageManifestDigest") != identity.manifest_digest
        or hints.get("sourceCohortSha256") != COHORT_DIGEST
        or hints.get("models")
        != {"cellRole": ROLE_DIGEST, "headerDirection": DIRECTION_DIGEST}
        or hints.get("workbookDigest") != expected_request["workbookDigest"]
        or hints.get("sheet") != expected_request["sheet"]
        or hints.get("featureBatchDigest") != expected_request["featureBatchDigest"]
        or addresses != expected_request["addresses"]
        or not valid_predictions
        or hint_digest != canonical_digest_v1(semantic)
    ):
        raise MlIntegrityError(
            "ML_OUTPUT_INTEGRITY", "integrity", "ML hints failed strict validation"
        )


def _valid_prediction(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and set(item)
        == {
            "address",
            "role",
            "direction",
            "roleConfidence",
            "directionConfidence",
        }
        and isinstance(item["address"], str)
        and _ADDRESS.fullmatch(item["address"]) is not None
        and isinstance(item["role"], str)
        and item["role"] in {"blank", "header", "unused", "value"}
        and isinstance(item["direction"], str)
        and item["direction"] in {"N", "NNW", "W", "WNW"}
        and all(
            isinstance(item[key], int | float)
            and not isinstance(item[key], bool)
            and 0 <= float(item[key]) <= 1
            for key in ("roleConfidence", "directionConfidence")
        )
    )


def _valid_vector(value: Any, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(
            isinstance(item, int | float)
            and not isinstance(item, bool)
            and abs(float(item)) <= 1_000_000_000
            and float(item) not in {float("inf"), float("-inf")}
            and float(item) == float(item)
            for item in value
        )
    )


def _valid_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
    )


def _read_regular(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("not regular")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1_048_576)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _copy_regular(source: Path, destination: Path) -> None:
    _write_exclusive(destination, _read_regular(source), 0o400)


def _write_exclusive(path: Path, data: bytes, mode: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(path, mode)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline and _group_exists(process.pid):
        process.poll()
        time.sleep(0.01)
    # The group can outlive an already-reaped leader. Always target the group
    # with SIGKILL after the grace period; ESRCH means the group is already gone.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1)
    kill_deadline = time.monotonic() + 1
    while time.monotonic() < kill_deadline and _group_exists(process.pid):
        time.sleep(0.01)
    if _group_exists(process.pid):
        raise MlIntegrityError(
            "ML_GROUP_TERMINATION_FAILED",
            "integrity",
            "ML process group survived SIGKILL",
        )


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
