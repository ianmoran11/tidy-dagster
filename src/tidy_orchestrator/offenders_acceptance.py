"""Provider-free acceptance adapter for fixed remaining-Offenders C4 routes."""

from __future__ import annotations

import ast
import contextvars
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import (
    DecisionRecord,
    canonical_json_bytes,
    domain_digest,
    sha256_digest,
)
from .product_prototype import (
    ACCEPTANCE_SCHEMA_V2,
    RUN_SCHEMA,
    _acceptance_decision_payload,
    _build_collation_report,
    _canonical_csv,
    _cross_year_issues,
    _validate_contract,
    evaluate_execution_for_acceptance,
)

RECORDED_AT = "2026-08-25T12:00:00+00:00"
REPLAY_ENGINE = "offenders-remaining-c4-v1"
AUTHORITY_ENV = "TIDY_C4_AUTHORITY_SHA256"
AUTHORITY_SCHEMA = "tidy.offenders-c4-acceptance-authorization/v1"
REVIEW_SCHEMA = "tidy.offenders-c4-review-decision/v1"
PROPOSAL_SCOPE = (47, 170, 224997)
TOOLCHAIN_PATHS = {
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "pyproject.toml",
    "uv.lock",
}
TOOLCHAIN_PACKAGE_ROOTS = (
    "node_modules/tsx",
    "node_modules/esbuild",
    "node_modules/get-tsconfig",
    "node_modules/resolve-pkg-maps",
    "node_modules/@esbuild/darwin-arm64",
)


class OffendersAcceptanceError(RuntimeError):
    pass


_ACCESS_STATE: contextvars.ContextVar[tuple[Path, str] | None] = contextvars.ContextVar(
    "c4_access_state", default=None
)


def _safe_access_descriptor(root: Path) -> int:
    product = root / ".product-prototype"
    if root.is_symlink() or not root.is_dir() or root.resolve() != root.absolute():
        raise OffendersAcceptanceError("C4_ACCESS_ROOT_UNSAFE")
    if not product.exists() and not product.is_symlink():
        with suppress(FileExistsError):
            product.mkdir(mode=0o700)
        root_descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(root_descriptor)
        finally:
            os.close(root_descriptor)
    if (
        product.is_symlink()
        or not product.is_dir()
        or product.resolve() != product.absolute()
    ):
        raise OffendersAcceptanceError("C4_ACCESS_ROOT_UNSAFE")
    path = product / "offenders-c4-access.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise OffendersAcceptanceError("C4_ACCESS_ROOT_UNSAFE") from error
    info = os.fstat(descriptor)
    try:
        path_info = os.lstat(path)
    except OSError as error:
        os.close(descriptor)
        raise OffendersAcceptanceError("C4_ACCESS_ROOT_UNSAFE") from error
    parent_descriptor = os.open(product, os.O_RDONLY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino)
        or path.is_symlink()
        or path.resolve() != path.absolute()
    ):
        os.close(descriptor)
        raise OffendersAcceptanceError("C4_ACCESS_ROOT_UNSAFE")
    return descriptor


@contextmanager
def _c4_access(project_root: Path, mode: str) -> Iterator[None]:
    root = project_root.resolve()
    active = _ACCESS_STATE.get()
    if active is not None:
        if active[0] != root or (active[1] == "shared" and mode == "exclusive"):
            raise OffendersAcceptanceError("C4_ACCESS_NESTING_INVALID")
        yield
        return
    descriptor = _safe_access_descriptor(root)
    operation = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
    try:
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError as error:
            code = (
                "C4_READERS_ACTIVE" if mode == "exclusive" else "C4_INSTALL_IN_PROGRESS"
            )
            raise OffendersAcceptanceError(code) from error
        assert_no_foreign_c4_install(root)
        generation_raw = os.pread(descriptor, 64, 0).strip()
        generation = int(generation_raw or b"0")
        if mode == "exclusive":
            generation += 1
            os.ftruncate(descriptor, 0)
            os.pwrite(descriptor, f"{generation}\n".encode(), 0)
            os.fsync(descriptor)
        token = _ACCESS_STATE.set((root, mode))
        try:
            yield
            if mode == "shared":
                observed = int(os.pread(descriptor, 64, 0).strip() or b"0")
                if observed != generation:
                    raise OffendersAcceptanceError("C4_ACCESS_GENERATION_CHANGED")
        finally:
            _ACCESS_STATE.reset(token)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def c4_shared_access(project_root: Path) -> Iterator[None]:
    """Hold a process-safe shared lease for a complete C4-aware read."""
    with _c4_access(project_root, "shared"):
        yield


@contextmanager
def c4_exclusive_access(project_root: Path) -> Iterator[None]:
    """Hold exclusive access while an installer owns the multi-file tree."""
    with _c4_access(project_root, "exclusive"):
        yield


def assert_no_foreign_c4_install(project_root: Path) -> None:
    root = project_root.resolve()
    lock = root / ".product-prototype/offenders-c4-install-transactions/install.lock"
    if not lock.exists() and not lock.is_symlink():
        return
    if lock.is_symlink() or not lock.is_file():
        raise OffendersAcceptanceError("C4_INSTALL_LOCK_UNSAFE")
    try:
        owner = json.loads(lock.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise OffendersAcceptanceError("C4_INSTALL_LOCK_INVALID") from error
    if (
        not isinstance(owner, dict)
        or set(owner) != {"token", "pid", "proposal"}
        or owner.get("token") != os.environ.get("TIDY_C4_INSTALL_OWNER")
    ):
        raise OffendersAcceptanceError("C4_INSTALL_IN_PROGRESS")


def _canonical_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise OffendersAcceptanceError("C4_AUTHORITY_PIN_PATH")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or pure.as_posix() != value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise OffendersAcceptanceError("C4_AUTHORITY_PIN_PATH")
    return pure


def _safe_pinned_file(root: Path, pin: Any, *, required: bool = True) -> bytes | None:
    if not isinstance(pin, dict) or set(pin) != {"path", "byteLength", "sha256"}:
        raise OffendersAcceptanceError("C4_AUTHORITY_PIN_SHAPE")
    pure = _canonical_relative_path(pin["path"])
    if (
        isinstance(pin.get("byteLength"), bool)
        or not isinstance(pin.get("byteLength"), int)
        or pin["byteLength"] < 0
        or not isinstance(pin.get("sha256"), str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", pin["sha256"]) is None
    ):
        raise OffendersAcceptanceError("C4_AUTHORITY_PIN_SHAPE")
    target = root.joinpath(*pure.parts)
    if not required:
        return None
    cursor = root
    for part in pure.parts:
        cursor /= part
        if cursor.is_symlink():
            raise OffendersAcceptanceError("C4_AUTHORITY_PIN_PATH")
    if not target.is_file():
        raise OffendersAcceptanceError("C4_AUTHORITY_PIN_MISSING")
    if target.resolve() != target.absolute():
        raise OffendersAcceptanceError("C4_AUTHORITY_PIN_PATH")
    data = target.read_bytes()
    if len(data) != pin["byteLength"] or sha256_digest(data) != pin["sha256"]:
        raise OffendersAcceptanceError("C4_AUTHORITY_PIN_DRIFT")
    return data


def _python_runtime_closure(root: Path) -> set[str]:
    package = root / "src/tidy_orchestrator"
    pending = [
        root / "scripts/register-offenders-remaining.py",
        root / "scripts/dagster-ui",
        package / "offenders_acceptance.py",
        package / "large_batch_cli.py",
        package / "dagster_defs.py",
        package / "definitions.py",
        package / "data_asset_status_cli.py",
    ]
    found: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in found:
            continue
        found.add(path)
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError) as error:
            raise OffendersAcceptanceError("C4_RUNTIME_SOURCE_UNREADABLE") from error
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = path.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    module = node.module.replace(".", "/") if node.module else ""
                    candidate = base / f"{module}.py" if module else None
                    if candidate is not None and candidate.is_file():
                        pending.append(candidate)
                    continue
                if node.module:
                    modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if not module.startswith("tidy_orchestrator"):
                    continue
                relative = module.replace(".", "/")
                candidate = root / "src" / f"{relative}.py"
                if candidate.is_file() and (
                    candidate == package or package in candidate.parents
                ):
                    pending.append(candidate)
    return {path.relative_to(root).as_posix() for path in found}


def _typescript_runtime_closure(root: Path) -> set[str]:
    pending = [root / "scripts/replay-offenders-remaining-accepted.ts"]
    found: set[Path] = set()
    pattern = re.compile(r'from\s+["\'](\.[^"\']+)["\']')
    while pending:
        path = pending.pop()
        if path in found:
            continue
        found.add(path)
        try:
            source = path.read_text()
        except OSError as error:
            raise OffendersAcceptanceError("C4_RUNTIME_SOURCE_UNREADABLE") from error
        for relative in pattern.findall(source):
            base = path.parent / relative
            candidates = [
                base,
                base.with_suffix(".ts"),
                Path(str(base).removesuffix(".js") + ".ts"),
                base / "index.ts",
            ]
            candidate = next((item for item in candidates if item.is_file()), None)
            if candidate is None:
                raise OffendersAcceptanceError("C4_RUNTIME_SOURCE_CLOSURE")
            if root not in candidate.resolve().parents:
                raise OffendersAcceptanceError("C4_RUNTIME_SOURCE_CLOSURE")
            pending.append(candidate.resolve())
    return {path.relative_to(root).as_posix() for path in found}


def required_c4_runtime_paths(project_root: Path) -> set[str]:
    root = project_root.resolve()
    launchers = {
        "scripts/tidy-prototype-batch",
        "scripts/tidy-data-status",
        "scripts/run-dagster-ui-foreground",
    }
    for relative in launchers:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise OffendersAcceptanceError("C4_RUNTIME_LAUNCHER_MISSING")
    return _python_runtime_closure(root) | _typescript_runtime_closure(root) | launchers


def required_c4_toolchain_paths(project_root: Path) -> set[str]:
    root = project_root.resolve()
    paths = set(TOOLCHAIN_PATHS)
    for relative in TOOLCHAIN_PACKAGE_ROOTS:
        package = root / relative
        if package.is_symlink() or not package.is_dir():
            raise OffendersAcceptanceError("C4_TOOLCHAIN_PACKAGE_MISSING")
        paths.update(
            path.relative_to(root).as_posix()
            for path in package.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
    return paths


def _git_head_entries(root: Path) -> dict[str, tuple[str, str]]:
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "HEAD"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OffendersAcceptanceError("C4_GIT_TRACKING_UNAVAILABLE") from error
    entries = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        if kind == "blob":
            entries[path.decode()] = (mode, object_id)
    return entries


def _git_index_entries(root: Path) -> dict[str, tuple[str, str] | None]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--stage", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OffendersAcceptanceError("C4_GIT_TRACKING_UNAVAILABLE") from error
    entries: dict[str, tuple[str, str] | None] = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, path_raw = record.split(b"\t", 1)
        mode, object_id, stage = metadata.decode().split()
        path = path_raw.decode()
        entries[path] = (mode, object_id) if stage == "0" else None
    return entries


def validate_c4_clean_checkout_tracking(root: Path, paths: set[str]) -> list[str]:
    """Return prerequisites absent from the current HEAD commit tree."""
    return sorted(paths - set(_git_head_entries(root)))


def _validate_clean_prerequisite_index(root: Path, paths: set[str]) -> None:
    head = _git_head_entries(root)
    index = _git_index_entries(root)
    if any(index.get(path) != head.get(path) for path in paths):
        raise OffendersAcceptanceError("C4_CLEAN_INDEX_DRIFT")


def _head_blob(root: Path, relative: str) -> bytes:
    _canonical_relative_path(relative)
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OffendersAcceptanceError("C4_COMMITTED_CUSTODY_MISSING") from error
    return result.stdout


def _validate_committed_custody(
    root: Path,
    pins: list[dict[str, Any]],
    authority_path: str,
    authority_raw: bytes,
) -> None:
    required_paths = {authority_path, *(pin["path"] for pin in pins)}
    _validate_clean_prerequisite_index(root, required_paths)
    if _head_blob(root, authority_path) != authority_raw:
        raise OffendersAcceptanceError("C4_COMMITTED_CUSTODY_DRIFT")
    for pin in pins:
        committed = _head_blob(root, pin["path"])
        if (
            len(committed) != pin["byteLength"]
            or sha256_digest(committed) != pin["sha256"]
        ):
            raise OffendersAcceptanceError("C4_COMMITTED_CUSTODY_DRIFT")


def _validate_pin_closure(
    root: Path,
    pins: Any,
    expected_paths: set[str],
    *,
    require_files: bool,
) -> None:
    if not isinstance(pins, list) or not pins:
        raise OffendersAcceptanceError("C4_AUTHORITY_CLOSURE_EMPTY")
    observed = []
    for pin in pins:
        _safe_pinned_file(root, pin, required=require_files)
        observed.append(pin["path"])
    if (
        observed != sorted(observed)
        or len(observed) != len(set(observed))
        or set(observed) != expected_paths
    ):
        raise OffendersAcceptanceError("C4_AUTHORITY_CLOSURE_MISMATCH")


def _validate_installed_input_paths(
    root: Path, paths: set[str], *, derive_from_route: bool
) -> None:
    registries = {
        "fixtures/product-prototype/offenders-remaining-c4-route-manifest-v1.json",
        "fixtures/product-prototype/offenders-remaining-workbook-normalization-v1.json",
        "fixtures/product-prototype/large-batch-assets-v1.json",
        "fixtures/product-prototype/data-asset-status-v1.json",
    }
    if not derive_from_route:
        evidence = [path for path in paths if "-evidence/" in path]
        cohorts = [
            path
            for path in paths
            if path.startswith("fixtures/product-prototype/recorded-crime-offenders-")
            and path.endswith(".json")
            and "-evidence/" not in path
        ]
        replays = [
            path
            for path in paths
            if path.startswith("fixtures/product-prototype/replay/")
            and path.endswith(".response.txt")
        ]
        workbooks = [
            path
            for path in paths
            if path.startswith("fixtures/product-prototype/workbooks/")
            and path.endswith(".xlsx")
        ]
        contracts = [
            path
            for path in paths
            if path.startswith("fixtures/product-prototype/acceptance/")
            and path.endswith("-v1.json")
        ]
        if not (
            len(cohorts) == 47
            and len(replays) == 170
            and len(workbooks) == 23
            and len(contracts) == 47
            and len(evidence) == 329
            and registries <= paths
        ):
            raise OffendersAcceptanceError("C4_INSTALLED_INPUT_CLOSURE")
        return
    route_path = root / (
        "fixtures/product-prototype/offenders-remaining-c4-route-manifest-v1.json"
    )
    try:
        route = json.loads(route_path.read_bytes())
        members = route["members"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as error:
        raise OffendersAcceptanceError("C4_INSTALLED_ROUTE_CLOSURE") from error
    if not isinstance(members, list) or len(members) != 170:
        raise OffendersAcceptanceError("C4_INSTALLED_ROUTE_CLOSURE")
    cohorts = {member.get("cohortPath") for member in members}
    maps = {member.get("mapPath") for member in members}
    workbooks = {member.get("workbookPath") for member in members}
    if len(cohorts) != 47 or len(maps) != 170 or len(workbooks) != 23:
        raise OffendersAcceptanceError("C4_INSTALLED_ROUTE_CLOSURE")
    families = {member.get("familyId") for member in members}
    expected = set(registries) | cohorts | maps | workbooks
    for family in families:
        if not isinstance(family, str):
            raise OffendersAcceptanceError("C4_INSTALLED_ROUTE_CLOSURE")
        expected.add(
            "fixtures/product-prototype/acceptance/"
            f"recorded-crime-offenders-{family}-v1.json"
        )
        expected.update(
            "fixtures/product-prototype/"
            f"recorded-crime-offenders-{family}-evidence/{name}"
            for name in {
                "README.md",
                "canonical-observations.csv",
                "canonical-observations.json",
                "collation-report.json",
                "exceptions.json",
                "manifest.json",
                "run.json",
            }
        )
    if paths != expected or len(expected) != 620:
        raise OffendersAcceptanceError("C4_INSTALLED_INPUT_CLOSURE")


def _tsx_command(root: Path, *arguments: str) -> list[str]:
    return [
        "node",
        str(root / "node_modules/tsx/dist/cli.mjs"),
        *arguments,
    ]


def _executable_proofs(root: Path) -> dict[str, str]:
    commands = {
        "python": [sys.executable, "--version"],
        "node": ["node", "--version"],
        "tsx": _tsx_command(root, "--version"),
    }
    proofs = {}
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "NODE_OPTIONS",
            "PYTHONPATH",
            "PYTHONHOME",
            "LD_PRELOAD",
            "DYLD_INSERT_LIBRARIES",
        }
    }
    for name, command in commands.items():
        try:
            result = subprocess.run(
                command,
                cwd=root,
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise OffendersAcceptanceError("C4_TOOLCHAIN_EXECUTABLE_PROOF") from error
        proofs[name] = (result.stdout or result.stderr).strip()
    return proofs


def _validate_review_decision(raw: bytes, proposal: dict[str, Any]) -> None:
    try:
        decision = json.loads(raw)
    except json.JSONDecodeError as error:
        raise OffendersAcceptanceError("C4_REVIEW_DECISION_INVALID") from error
    required = {
        "schemaVersion",
        "decisionId",
        "campaignId",
        "decision",
        "reviewedAt",
        "reviewer",
        "proposal",
        "findingsDigest",
    }
    reviewer = decision.get("reviewer")
    semantic = dict(decision)
    decision_id = semantic.pop("decisionId", None)
    if (
        set(decision) != required
        or decision.get("schemaVersion") != REVIEW_SCHEMA
        or decision.get("campaignId") != "offenders-remaining-c4"
        or decision.get("decision") != "approve-c4-acceptance"
        or not isinstance(decision.get("reviewedAt"), str)
        or not decision["reviewedAt"]
        or not isinstance(reviewer, dict)
        or set(reviewer) != {"id", "organization", "role", "independent"}
        or reviewer.get("independent") is not True
        or any(
            not isinstance(reviewer.get(key), str) or not reviewer[key]
            for key in ("id", "organization", "role")
        )
        or decision.get("proposal") != proposal
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(decision.get("findingsDigest")))
        is None
        or decision_id != domain_digest(REVIEW_SCHEMA, semantic)
    ):
        raise OffendersAcceptanceError("C4_REVIEW_DECISION_INVALID")


def verify_c4_acceptance_authority(
    project_root: Path,
    authority_digest: str | None = None,
    *,
    verify_installed_inputs: bool = True,
) -> dict[str, Any]:
    """Verify external authority, positive review, and exact runtime/input closure."""
    root = project_root.resolve()
    path = root / (
        "fixtures/product-prototype/"
        "offenders-remaining-c4-acceptance-authorization-v1.json"
    )
    if path.is_symlink() or not path.is_file():
        raise OffendersAcceptanceError("C4_ACCEPTANCE_AUTHORIZATION_REQUIRED")
    raw = path.read_bytes()
    expected_authority_digest = authority_digest or os.environ.get(AUTHORITY_ENV)
    if (
        not isinstance(expected_authority_digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_authority_digest) is None
        or sha256_digest(raw) != expected_authority_digest
    ):
        raise OffendersAcceptanceError("C4_EXTERNAL_AUTHORITY_DIGEST_REQUIRED")
    value = json.loads(raw)
    required = {
        "schemaVersion",
        "authorizedForAtomicAcceptance",
        "acceptanceAuthority",
        "trainingEligibility",
        "productionAcceptance",
        "promotionAuthorization",
        "reviewDecision",
        "proposal",
        "runtimeSourceClosure",
        "toolchainClosure",
        "installedInputClosure",
        "generatedOutputClosure",
        "executableProofs",
    }
    if (
        set(value) != required
        or value.get("schemaVersion") != AUTHORITY_SCHEMA
        or value.get("authorizedForAtomicAcceptance") is not True
        or value.get("acceptanceAuthority") is not True
        or value.get("trainingEligibility") is not False
        or value.get("productionAcceptance") is not True
        or value.get("promotionAuthorization") is not True
    ):
        raise OffendersAcceptanceError("C4_ACCEPTANCE_AUTHORIZATION_INVALID")
    proposal = value.get("proposal")
    if (
        not isinstance(proposal, dict)
        or set(proposal)
        != {
            "families",
            "members",
            "rows",
            "payloadRootDigest",
            "outputRootDigest",
        }
        or (proposal["families"], proposal["members"], proposal["rows"])
        != PROPOSAL_SCOPE
    ):
        raise OffendersAcceptanceError("C4_AUTHORITY_SCOPE")
    review_pin = value["reviewDecision"]
    review_path = _canonical_relative_path(review_pin.get("path"))
    if (
        review_path.parts[:3] != ("fixtures", "product-prototype", "reviews")
        or "c3" in review_path.as_posix().lower()
    ):
        raise OffendersAcceptanceError("C4_REVIEW_DECISION_INVALID")
    review_raw = _safe_pinned_file(root, review_pin)
    assert review_raw is not None
    _validate_review_decision(review_raw, proposal)
    _validate_pin_closure(
        root,
        value["runtimeSourceClosure"],
        required_c4_runtime_paths(root),
        require_files=True,
    )
    _validate_pin_closure(
        root,
        value["toolchainClosure"],
        required_c4_toolchain_paths(root),
        require_files=True,
    )
    installed_paths = {
        pin.get("path")
        for pin in value.get("installedInputClosure", [])
        if isinstance(pin, dict)
    }
    if len(installed_paths) != 620:
        raise OffendersAcceptanceError("C4_INSTALLED_INPUT_CLOSURE")
    _validate_installed_input_paths(
        root, installed_paths, derive_from_route=verify_installed_inputs
    )
    _validate_pin_closure(
        root,
        value["installedInputClosure"],
        installed_paths,
        require_files=verify_installed_inputs,
    )
    if not verify_installed_inputs:
        for pin in value["installedInputClosure"]:
            if pin["path"].startswith("fixtures/product-prototype/workbooks/"):
                _safe_pinned_file(root, pin, required=True)
    _validate_pin_closure(
        root,
        value["generatedOutputClosure"],
        {"docs/data-asset-status/index.html"},
        require_files=verify_installed_inputs,
    )
    if value.get("executableProofs") != _executable_proofs(root):
        raise OffendersAcceptanceError("C4_TOOLCHAIN_EXECUTABLE_DRIFT")
    authority_relative = path.relative_to(root).as_posix()
    committed_pins = [
        review_pin,
        *value["runtimeSourceClosure"],
        *value["toolchainClosure"],
        *value["installedInputClosure"],
        *value["generatedOutputClosure"],
    ]
    tracked_required = {authority_relative, *(pin["path"] for pin in committed_pins)}
    if validate_c4_clean_checkout_tracking(root, tracked_required):
        raise OffendersAcceptanceError("C4_CLEAN_CHECKOUT_PREREQUISITES_UNTRACKED")
    _validate_committed_custody(root, committed_pins, authority_relative, raw)
    return value


def validate_offenders_remaining_cohort(cohort: dict[str, Any]) -> None:
    allowed = {
        "schemaVersion",
        "cohortId",
        "publicationId",
        "tableFamilyId",
        "generation",
        "acceptanceContract",
        "workerLimits",
        "workbooks",
    }
    if (
        set(cohort) != allowed
        or cohort.get("schemaVersion") != "tidy.product-prototype-cohort/v1"
        or cohort.get("publicationId") != "recorded-crime-offenders"
        or not isinstance(cohort.get("workbooks"), list)
        or not cohort["workbooks"]
    ):
        raise OffendersAcceptanceError("C4_COHORT_SCHEMA")
    years = set()
    for entry in cohort["workbooks"]:
        year = entry.get("year")
        replay = entry.get("replayResponse")
        if (
            year in years
            or not isinstance(year, int)
            or not isinstance(replay, dict)
            or replay.get("acceptanceAuthority") is not False
            or replay.get("recipeProtocol")
            not in {"RecipeV01", "TargetScopedRecipeV02"}
            or not str(replay.get("historicalModel", "")).startswith(
                "provider-free/offenders-c4/"
            )
        ):
            raise OffendersAcceptanceError("C4_COHORT_MEMBER")
        years.add(year)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise OffendersAcceptanceError(f"object required: {path}")
    return value


def _write(path: Path, value: Any) -> bytes:
    data = canonical_json_bytes(value) + b"\n"
    path.write_bytes(data)
    return data


def build_offenders_family_run(
    *,
    cohort_path: Path,
    contract_path: Path,
    execution_root: Path,
    output_root: Path,
    recorded_at: str = RECORDED_AT,
) -> dict[str, Any]:
    """Evaluate exact preverified route executions and write standard run outputs."""
    cohort_bytes = cohort_path.read_bytes()
    cohort = json.loads(cohort_bytes)
    contract_bytes = contract_path.read_bytes()
    contract = json.loads(contract_bytes)
    if (
        cohort.get("publicationId") != "recorded-crime-offenders"
        or contract.get("schemaVersion") != ACCEPTANCE_SCHEMA_V2
    ):
        raise OffendersAcceptanceError("C4 cohort/contract identity")
    _validate_contract(contract, cohort)
    output_root.mkdir(parents=True, exist_ok=False)
    policy_digest = sha256_digest(contract_bytes)
    reports = []
    accepted = []
    for entry in cohort["workbooks"]:
        year = int(entry["year"])
        root = execution_root / "members" / cohort["tableFamilyId"] / str(year)
        execution_bytes = (root / "execution.json").read_bytes()
        recipe_bytes = (root / "normalized-recipe.json").read_bytes()
        proof_bytes = (root / "route-proof.json").read_bytes()
        execution = json.loads(execution_bytes)
        recipe = json.loads(recipe_bytes)
        proof = json.loads(proof_bytes)
        protocol = proof["recipeProtocol"]
        recipe_digest = sha256_digest(recipe_bytes)
        if (
            proof.get("familyId"),
            proof.get("year"),
            proof.get("workbookDigest"),
            proof.get("physicalSheet"),
            proof.get("mapDigest"),
            proof.get("rowTraceDigest"),
            proof.get("providerCalls"),
            proof.get("warnings"),
            proof.get("deterministic"),
        ) != (
            cohort["tableFamilyId"],
            year,
            entry["contentDigest"],
            entry["sheet"],
            contract["expectedReplayMapDigestsByYear"][str(year)],
            contract["expectedC3RowTraceDigestsByYear"][str(year)],
            0,
            0,
            True,
        ):
            raise OffendersAcceptanceError(f"route proof mismatch {year}")
        rows, issues, checks = evaluate_execution_for_acceptance(
            execution=execution,
            recipe=recipe,
            contract=contract,
            entry=entry,
            recipe_digest=recipe_digest,
            recipe_protocol=protocol,
            deterministic=True,
        )
        checks = {
            **checks,
            "c3Proof": True,
            "routeProtocol": True,
            "sourceCustody": True,
        }
        if issues or not rows or any(value is not True for value in checks.values()):
            raise OffendersAcceptanceError(f"acceptance failed {year}: {issues}")
        payload = _acceptance_decision_payload(
            contract=contract,
            acceptance_policy_version=ACCEPTANCE_SCHEMA_V2,
            acceptance_policy_digest=policy_digest,
            year=year,
            workbook_digest=entry["contentDigest"],
            sheet=entry["sheet"],
            reference_date=entry["referenceDate"],
            checks=checks,
            issues=[],
        )
        decision = DecisionRecord.create(
            subject_id=recipe_digest,
            decision_type="prototype_auto_accepted",
            payload=payload,
            actor="tidy.product-prototype-policy/v1",
            recorded_at=recorded_at,
        )
        provenance = {
            "publication_id": "recorded-crime-offenders",
            "execution_digest": sha256_digest(execution_bytes),
            "acceptance_policy_version": ACCEPTANCE_SCHEMA_V2,
            "acceptance_policy_digest": policy_digest,
            "acceptance_decision_digest": decision.decision_id,
            "prompt_package_digest": proof["mapDigest"],
            "generation_model": f"provider-free/{REPLAY_ENGINE}/{proof['route']}",
            "generation_attempt_id": f"replay:{proof['mapDigest']}",
            "recipe_protocol": protocol,
            "replay_map_digest": proof["mapDigest"],
            "c3_row_trace_digest": proof["rowTraceDigest"],
        }
        observations = [{**row, **provenance} for row in rows]
        accepted.extend(observations)
        reports.append(
            {
                "year": year,
                "referenceDate": entry["referenceDate"],
                "workbookDigest": entry["contentDigest"],
                "sheet": entry["sheet"],
                "prepareDerivationId": domain_digest(
                    "tidy.offenders-c4-prepare/v1",
                    {
                        "workbookDigest": entry["contentDigest"],
                        "sheet": entry["sheet"],
                        "mapDigest": proof["mapDigest"],
                    },
                ),
                "interpretDerivationId": domain_digest(
                    "tidy.offenders-c4-interpret/v1",
                    {
                        "executionDigest": sha256_digest(execution_bytes),
                        "recipeDigest": recipe_digest,
                        "protocol": protocol,
                    },
                ),
                "decision": "prototype_auto_accepted",
                "decisionId": decision.decision_id,
                "rawObservationCount": len(rows),
                "excludedObservationCount": 0,
                "observationCount": len(rows),
                "executionWarningCount": 0,
                "recipeProtocol": protocol,
                "replayMapDigest": proof["mapDigest"],
                "c3RowTraceDigest": proof["rowTraceDigest"],
                "checks": checks,
                "issues": [],
            }
        )

    canonical = sorted(
        accepted, key=lambda row: tuple(str(row[k]) for k in contract["uniqueKey"])
    )
    cross = _cross_year_issues(canonical, contract)
    if cross:
        raise OffendersAcceptanceError(f"cross-year issues: {cross[:1]}")
    csv_bytes = _canonical_csv(canonical, contract)
    json_bytes = canonical_json_bytes(canonical) + b"\n"
    collation = _build_collation_report(
        workbooks=reports, rows=canonical, contract=contract, cross_year_issues=[]
    )
    collation_bytes = canonical_json_bytes(collation) + b"\n"
    (output_root / "canonical-observations.csv").write_bytes(csv_bytes)
    (output_root / "canonical-observations.json").write_bytes(json_bytes)
    (output_root / "collation-report.json").write_bytes(collation_bytes)
    _write(output_root / "exceptions.json", [])
    semantic = {
        "schemaVersion": RUN_SCHEMA,
        "mode": "replay",
        "providerCalls": 0,
        "freshLunaGeneration": False,
        "cohortDigest": sha256_digest(cohort_bytes),
        "acceptanceContractDigest": policy_digest,
        "modelReservedForLiveMode": "openai-codex/gpt-5.6-luna",
        "replayEngine": REPLAY_ENGINE,
        "workbooks": reports,
        "acceptedWorkbookCount": len(reports),
        "exceptionWorkbookCount": 0,
        "canonicalObservationCount": len(canonical),
        "canonicalCsvDigest": sha256_digest(csv_bytes),
        "canonicalJsonDigest": sha256_digest(json_bytes),
        "collationReportDigest": sha256_digest(collation_bytes),
        "crossYearIssues": [],
        "historicalReplayIsAcceptanceAuthority": False,
        "liveAttempts": None,
        "trainingEligibility": False,
    }
    run = {**semantic, "runDigest": domain_digest(RUN_SCHEMA, semantic)}
    _write(output_root / "run.json", run)
    return run


def _safe_runtime_directory(project: Path) -> Path:
    product = project / ".product-prototype"
    if (
        product.is_symlink()
        or not product.is_dir()
        or product.resolve() != product.absolute()
    ):
        raise OffendersAcceptanceError("C4_RUNTIME_ROOT_UNSAFE")
    runtime = product / "offenders-remaining-c4-runtime"
    if runtime.exists() or runtime.is_symlink():
        if (
            runtime.is_symlink()
            or not runtime.is_dir()
            or runtime.resolve() != runtime.absolute()
        ):
            raise OffendersAcceptanceError("C4_RUNTIME_ROOT_UNSAFE")
    else:
        runtime.mkdir(mode=0o700)
    return runtime


def _safe_candidate(project: Path, candidate: Path, token: str) -> None:
    try:
        relative = candidate.absolute().relative_to(project)
    except ValueError as error:
        raise OffendersAcceptanceError("C4_OUTPUT_PATH_ESCAPE") from error
    if token not in candidate.name:
        raise OffendersAcceptanceError("C4_OUTPUT_TOKEN_MISMATCH")
    cursor = project
    for part in relative.parts[:-1]:
        cursor /= part
        if (
            cursor.is_symlink()
            or not cursor.is_dir()
            or cursor.resolve() != cursor.absolute()
        ):
            raise OffendersAcceptanceError("C4_OUTPUT_ANCESTOR_UNSAFE")
    if candidate.exists() or candidate.is_symlink():
        raise OffendersAcceptanceError("C4_OUTPUT_CANDIDATE_OCCUPIED")


def _run_offenders_remaining_family_unlocked(
    *,
    project_root: Path,
    cohort_path: Path,
    output_root: Path,
    recorded_at: str = RECORDED_AT,
) -> dict[str, Any]:
    """Run the authority-gated ``offenders-remaining-c4-v1`` replay engine."""
    project = project_root.resolve()
    verify_c4_acceptance_authority(project)
    cohort = _load(cohort_path)
    family = cohort.get("tableFamilyId")
    if not isinstance(family, str):
        raise OffendersAcceptanceError("C4_FAMILY_ID")
    runtime = _safe_runtime_directory(project)
    token = uuid.uuid4().hex
    execution = runtime / f"run-{token}"
    candidate = output_root.with_name(f".{output_root.name}.c4-{token}")
    _safe_candidate(project, candidate, token)
    if output_root.is_symlink():
        raise OffendersAcceptanceError("C4_OUTPUT_ANCESTOR_UNSAFE")
    lease = output_root.with_name(f".{output_root.name}.c4-lease")
    try:
        lease_descriptor = os.open(lease, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise OffendersAcceptanceError("C4_OUTPUT_ALREADY_OWNED") from error
    os.write(lease_descriptor, f"{token} {os.getpid()}\n".encode())
    os.fsync(lease_descriptor)
    os.close(lease_descriptor)
    try:
        subprocess.run(
            [
                *_tsx_command(
                    project, "scripts/replay-offenders-remaining-accepted.ts"
                ),
                "--routes",
                "fixtures/product-prototype/offenders-remaining-c4-route-manifest-v1.json",
                "--family",
                family,
                "--out",
                str(execution.relative_to(project)),
            ],
            cwd=project,
            check=True,
            env={
                **{
                    k: v
                    for k, v in os.environ.items()
                    if k
                    not in {
                        "NODE_OPTIONS",
                        "PYTHONPATH",
                        "PYTHONHOME",
                        "LD_PRELOAD",
                        "DYLD_INSERT_LIBRARIES",
                    }
                },
                "NODE_OPTIONS": "--max-old-space-size=2048",
            },
            stdout=subprocess.DEVNULL,
            timeout=600,
        )
        verify_c4_acceptance_authority(project)
        contract = cohort_path.parent / str(cohort["acceptanceContract"])
        report = build_offenders_family_run(
            cohort_path=cohort_path,
            contract_path=contract,
            execution_root=execution,
            output_root=candidate,
            recorded_at=recorded_at,
        )
        verify_c4_acceptance_authority(project)
        backup = output_root.with_name(f".{output_root.name}.backup-{token}")
        had = output_root.exists()
        os.replace(output_root, backup) if had else None
        try:
            os.replace(candidate, output_root)
            shutil.rmtree(backup, ignore_errors=True)
        except BaseException:
            shutil.rmtree(output_root, ignore_errors=True)
            if had and backup.exists():
                os.replace(backup, output_root)
            raise
        return report
    finally:
        shutil.rmtree(execution, ignore_errors=True)
        shutil.rmtree(candidate, ignore_errors=True)
        lease.unlink(missing_ok=True)


def run_offenders_remaining_family(
    *,
    project_root: Path,
    cohort_path: Path,
    output_root: Path,
    recorded_at: str = RECORDED_AT,
) -> dict[str, Any]:
    """Run C4 replay while holding shared access to all installed inputs."""
    with c4_shared_access(project_root):
        return _run_offenders_remaining_family_unlocked(
            project_root=project_root,
            cohort_path=cohort_path,
            output_root=output_root,
            recorded_at=recorded_at,
        )
