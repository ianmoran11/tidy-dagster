"""Deterministic provider-free work units and authoritative digest indexes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .application import (
    _assert_reference_gold,
    _execute_fixture,
    _verify_and_index_gold,
    actual_worker_gateway,
    load_verified_fixture_manifests,
)
from .artifacts import (
    ContentDescriptor,
    CustodyReceipt,
    LocalArtifactRepository,
    PointerConflict,
    canonical_json_bytes,
    domain_digest,
)
from .worker import WorkerGateway

MAX_ACTIVE_WORK_UNITS = 1_000
REQUESTED_USE_CASE = "provider-free-reference-parity"
PROCESSING_PROFILE_DIGEST = domain_digest(
    "tidy.processing-profile/v1",
    {
        "operation": "execute-recipe-v01",
        "evidenceProfile": "m2-deterministic-parity-v1",
        "csvMode": "recipe-aware",
        "summarySupported": False,
        "providerCalls": 0,
    },
)
GATE_NAMES = (
    "input-provenance",
    "frozen-reference-execution",
    "authoritative-reconstruction",
)


@dataclass(frozen=True)
class WorkUnit:
    work_unit_id: str
    fixture: str
    workbook_digest: str
    workbook_length: int
    sheet_name: str
    requested_use_case: str
    recipe_digest: str
    recipe_length: int
    processing_profile_digest: str = PROCESSING_PROFILE_DIGEST


@dataclass(frozen=True)
class WorkUnitCatalog:
    units: tuple[WorkUnit, ...]
    catalog_digest: str
    catalog_bytes: bytes


@dataclass(frozen=True)
class WorkUnitIndex:
    work_unit_id: str
    kind: str
    content_digest: str
    record_count: int


@dataclass(frozen=True)
class GateResult:
    gate_name: str
    work_unit_id: str
    content_digest: str
    subject_digest: str
    passed: bool
    evidence_digests: tuple[str, ...]


def discover_work_units(project_root: Path) -> WorkUnitCatalog:
    fixture_manifest, _gold_manifest = load_verified_fixture_manifests(project_root)
    files = fixture_manifest["files"]
    units: list[WorkUnit] = []
    for fixture in fixture_manifest["admissionOrder"]:
        workbook = _manifest_entry(files, fixture, f"fixtures/workbooks/{fixture}.xlsx")
        recipe = _manifest_entry(files, fixture, f"fixtures/recipes/{fixture}.json")
        workbook_digest = f"sha256:{workbook['sha256']}"
        recipe_digest = f"sha256:{recipe['sha256']}"
        recipe_value = json.loads(
            (project_root / "fixtures" / "recipes" / f"{fixture}.json").read_bytes()
        )
        sheet_name = recipe_value.get("sheet")
        if not isinstance(sheet_name, str) or not sheet_name:
            raise RuntimeError(f"Fixture recipe {fixture} has no exact sheet name")
        identity = {
            "workbookDigest": workbook_digest,
            "sheetName": sheet_name,
            "requestedUseCase": REQUESTED_USE_CASE,
            "processingProfileDigest": PROCESSING_PROFILE_DIGEST,
        }
        units.append(
            WorkUnit(
                work_unit_id=domain_digest("tidy.work-unit/v1", identity),
                fixture=fixture,
                workbook_digest=workbook_digest,
                workbook_length=int(workbook["byteLength"]),
                sheet_name=sheet_name,
                requested_use_case=REQUESTED_USE_CASE,
                recipe_digest=recipe_digest,
                recipe_length=int(recipe["byteLength"]),
            )
        )
    if len(units) > MAX_ACTIVE_WORK_UNITS:
        raise RuntimeError(
            f"Active work-unit cohort exceeds bounded maximum {MAX_ACTIVE_WORK_UNITS}"
        )
    catalog_bytes = canonical_json_bytes(
        {
            "schemaVersion": "tidy.work-unit-catalog/v1",
            "processingProfileDigest": PROCESSING_PROFILE_DIGEST,
            "maximumActiveWorkUnits": MAX_ACTIVE_WORK_UNITS,
            "workUnits": [_work_unit_wire(unit) for unit in units],
        }
    )
    descriptor = _descriptor_for_bytes(
        catalog_bytes, "work-unit-catalog", "tidy.work-unit-catalog/v1"
    )
    return WorkUnitCatalog(tuple(units), descriptor.content_digest, catalog_bytes)


def publish_catalog(
    repository: LocalArtifactRepository,
    project_root: Path,
    *,
    expected_catalog_digest: str | None = None,
) -> WorkUnitIndex:
    catalog = discover_work_units(project_root)
    if (
        expected_catalog_digest is not None
        and catalog.catalog_digest != expected_catalog_digest
    ):
        raise RuntimeError("Discovered catalog changed after run dispatch")
    descriptor = repository.put_bytes(
        catalog.catalog_bytes,
        kind="work-unit-catalog",
        schema_version="tidy.work-unit-catalog/v1",
        media_type="application/json",
    )
    _set_active_pointer(repository, "m4/active-catalog", descriptor.content_digest)
    return WorkUnitIndex(
        "catalog", "work-unit-catalog", descriptor.content_digest, len(catalog.units)
    )


def publish_inputs_index(
    repository: LocalArtifactRepository,
    project_root: Path,
    work_unit_id: str,
    *,
    expected_recipe_digest: str | None = None,
    expected_catalog_digest: str | None = None,
) -> WorkUnitIndex:
    unit = get_work_unit(
        project_root,
        work_unit_id,
        expected_recipe_digest=expected_recipe_digest,
        expected_catalog_digest=expected_catalog_digest,
    )
    observed_at = datetime.now(UTC).isoformat()
    sources = (
        (
            "workbook",
            project_root / "fixtures" / "workbooks" / f"{unit.fixture}.xlsx",
            "fixture-workbook",
            "tidy.fixture/v1",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            unit.workbook_digest,
            unit.workbook_length,
        ),
        (
            "recipeRevision",
            project_root / "fixtures" / "recipes" / f"{unit.fixture}.json",
            "fixture-recipe",
            "recipe-v01",
            "application/json",
            unit.recipe_digest,
            unit.recipe_length,
        ),
    )
    records: list[tuple[str, ContentDescriptor]] = []
    for role, path, kind, schema, media, digest, length in sources:
        descriptor = repository.put_bytes(
            path.read_bytes(),
            kind=kind,
            schema_version=schema,
            media_type=media,
            declared_digest=digest,
            declared_length=length,
        )
        repository.add_custody(
            CustodyReceipt.create(
                content_digest=descriptor.content_digest,
                storage_uri=f"fixture://{path.relative_to(project_root).as_posix()}",
                observed_at=observed_at,
                actor="tidy.dagster-projection/v1",
                source_locator=path.relative_to(project_root).as_posix(),
                classification="licensed-synthetic-parity-fixture",
            )
        )
        records.append((role, descriptor))
    index_bytes = canonical_json_bytes(
        {
            "schemaVersion": "tidy.work-unit-inputs-index/v1",
            "workUnitId": work_unit_id,
            "workbookDigest": unit.workbook_digest,
            "sheetName": unit.sheet_name,
            "requestedUseCase": unit.requested_use_case,
            "processingProfileDigest": PROCESSING_PROFILE_DIGEST,
            "inputs": [
                {
                    "role": role,
                    "contentDigest": record.content_digest,
                    "byteLength": record.byte_length,
                    "schemaVersion": record.schema_version,
                }
                for role, record in records
            ],
        }
    )
    index = repository.put_bytes(
        index_bytes,
        kind="work-unit-inputs-index",
        schema_version="tidy.work-unit-inputs-index/v1",
        media_type="application/json",
    )
    _ensure_pointer(
        repository,
        _revision_pointer("inputs", unit),
        index.content_digest,
    )
    _publish_input_gate(repository, unit, index.content_digest)
    _set_active_pointer(repository, f"m4/inputs/{work_unit_id}", index.content_digest)
    return WorkUnitIndex(
        work_unit_id, "work-unit-inputs-index", index.content_digest, 2
    )


def execute_work_unit(
    repository: LocalArtifactRepository,
    project_root: Path,
    work_unit_id: str,
    *,
    gateway: WorkerGateway | None = None,
    expected_recipe_digest: str | None = None,
    expected_catalog_digest: str | None = None,
) -> WorkUnitIndex:
    unit = get_work_unit(
        project_root,
        work_unit_id,
        expected_recipe_digest=expected_recipe_digest,
        expected_catalog_digest=expected_catalog_digest,
    )
    inputs_index = publish_inputs_index(
        repository,
        project_root,
        work_unit_id,
        expected_recipe_digest=expected_recipe_digest,
        expected_catalog_digest=expected_catalog_digest,
    )
    workbook = repository.get_content(unit.workbook_digest)
    recipe = repository.get_content(unit.recipe_digest)
    execution = _execute_fixture(
        gateway or actual_worker_gateway(repository, project_root), workbook, recipe
    )
    _fixture_manifest, gold_manifest = load_verified_fixture_manifests(project_root)
    gold = _verify_and_index_gold(project_root, gold_manifest["fixtures"])
    _assert_reference_gold(unit.fixture, execution, gold[unit.fixture])
    index_bytes = canonical_json_bytes(
        {
            "schemaVersion": "tidy.work-unit-execution-index/v1",
            "workUnitId": work_unit_id,
            "fixture": unit.fixture,
            "inputIndexDigest": inputs_index.content_digest,
            "recipeRevisionDigest": unit.recipe_digest,
            "processingProfileDigest": PROCESSING_PROFILE_DIGEST,
            "derivationId": execution.derivation.derivation_id,
            "reproductionKey": execution.reproduction_key,
            "outputFingerprint": execution.output_fingerprint,
            "outputs": [
                {
                    "name": name,
                    "relativePath": relative_path,
                    "contentDigest": descriptor.content_digest,
                    "byteLength": descriptor.byte_length,
                }
                for name, relative_path, descriptor in zip(
                    execution.output_names,
                    execution.output_paths,
                    execution.outputs,
                    strict=True,
                )
            ],
            "referenceGoldVerified": True,
            "networkIsolationEnforced": execution_network_isolated(gateway),
            "providerCalls": 0,
        }
    )
    index = repository.put_bytes(
        index_bytes,
        kind="work-unit-execution-index",
        schema_version="tidy.work-unit-execution-index/v1",
        media_type="application/json",
    )
    _ensure_pointer(
        repository,
        _revision_pointer("execution", unit),
        index.content_digest,
    )
    _publish_execution_gate(repository, project_root, unit, index.content_digest)
    _set_active_pointer(
        repository, f"m4/execution/{work_unit_id}", index.content_digest
    )
    return WorkUnitIndex(
        work_unit_id,
        "work-unit-execution-index",
        index.content_digest,
        len(execution.outputs),
    )


def publish_projection_index(
    repository: LocalArtifactRepository,
    project_root: Path,
    work_unit_id: str,
    *,
    expected_recipe_digest: str | None = None,
    expected_catalog_digest: str | None = None,
) -> WorkUnitIndex:
    unit = get_work_unit(
        project_root,
        work_unit_id,
        expected_recipe_digest=expected_recipe_digest,
        expected_catalog_digest=expected_catalog_digest,
    )
    execution_pointer = repository.get_pointer(_revision_pointer("execution", unit))
    if execution_pointer is None:
        raise RuntimeError(f"No authoritative execution index for {work_unit_id}")
    execution = _validated_execution_index(
        repository, project_root, unit, execution_pointer.target_id
    )
    projection_bytes = canonical_json_bytes(
        {
            "schemaVersion": "tidy.active-work-unit-projection/v1",
            "workUnitId": work_unit_id,
            "fixture": unit.fixture,
            "executionIndexDigest": execution_pointer.target_id,
            "recipeRevisionDigest": unit.recipe_digest,
            "derivationId": execution["derivationId"],
            "outputFingerprint": execution["outputFingerprint"],
            "outputDigests": [item["contentDigest"] for item in execution["outputs"]],
            "recordCount": len(execution["outputs"]),
            "providerCalls": 0,
        }
    )
    projection = repository.put_bytes(
        projection_bytes,
        kind="active-work-unit-projection",
        schema_version="tidy.active-work-unit-projection/v1",
        media_type="application/json",
    )
    _ensure_pointer(
        repository,
        _revision_pointer("projection", unit),
        projection.content_digest,
    )
    _publish_reconstruction_gate(repository, unit, projection.content_digest)
    _set_active_pointer(
        repository, f"m4/projection/{work_unit_id}", projection.content_digest
    )
    return WorkUnitIndex(
        work_unit_id,
        "active-work-unit-projection",
        projection.content_digest,
        len(execution["outputs"]),
    )


def reconstruct_projection(
    repository: LocalArtifactRepository, work_unit_id: str
) -> WorkUnitIndex:
    pointer = repository.get_pointer(f"m4/projection/{work_unit_id}")
    if pointer is None:
        raise RuntimeError(f"No active projection for {work_unit_id}")
    data = _load_json_content(repository, pointer.target_id)
    if (
        data.get("schemaVersion") != "tidy.active-work-unit-projection/v1"
        or data.get("workUnitId") != work_unit_id
        or data.get("providerCalls") != 0
        or not isinstance(data.get("recordCount"), int)
        or data.get("recordCount") != len(data.get("outputDigests", []))
    ):
        raise RuntimeError("Stored active projection is invalid")
    for digest in data["outputDigests"]:
        repository.read_bytes_verified(digest)
    execution = _load_json_content(repository, data["executionIndexDigest"])
    if (
        execution.get("workUnitId") != work_unit_id
        or execution.get("recipeRevisionDigest") != data.get("recipeRevisionDigest")
        or execution.get("derivationId") != data.get("derivationId")
        or execution.get("outputFingerprint") != data.get("outputFingerprint")
        or [item.get("contentDigest") for item in execution.get("outputs", [])]
        != data["outputDigests"]
    ):
        raise RuntimeError("Projection execution closure is invalid")
    recipe_revision_digest = data.get("recipeRevisionDigest")
    if not isinstance(recipe_revision_digest, str):
        raise RuntimeError("Projection recipe revision is invalid")
    gate = get_gate_result(
        repository,
        "authoritative-reconstruction",
        work_unit_id,
        recipe_revision_digest,
    )
    if not gate.passed or gate.subject_digest != pointer.target_id:
        raise RuntimeError("Projection reconstruction gate is invalid")
    return WorkUnitIndex(
        work_unit_id,
        "active-work-unit-projection",
        pointer.target_id,
        int(data["recordCount"]),
    )


def get_gate_result(
    repository: LocalArtifactRepository,
    gate_name: str,
    work_unit_id: str,
    recipe_revision_digest: str,
) -> GateResult:
    if gate_name not in GATE_NAMES:
        raise ValueError(f"Unknown gate {gate_name}")
    pointer = repository.get_pointer(
        f"m4/revisions/{work_unit_id}/{recipe_revision_digest}/gates/{gate_name}"
    )
    if pointer is None:
        raise RuntimeError(f"Missing immutable {gate_name} gate for {work_unit_id}")
    descriptor = repository.get_content(pointer.target_id)
    if (
        descriptor.kind != "gate-result"
        or descriptor.schema_version != "tidy.gate-result/v1"
        or descriptor.media_type != "application/json"
    ):
        raise RuntimeError(f"Invalid immutable {gate_name} gate descriptor")
    value = _load_json_content(repository, pointer.target_id)
    required = {
        "schemaVersion",
        "gateName",
        "workUnitId",
        "recipeRevisionDigest",
        "subjectDigest",
        "passed",
        "evidenceDigests",
        "checks",
    }
    if (
        set(value) != required
        or value["schemaVersion"] != "tidy.gate-result/v1"
        or value["gateName"] != gate_name
        or value["workUnitId"] != work_unit_id
        or value["recipeRevisionDigest"] != recipe_revision_digest
        or value["passed"] is not True
        or not isinstance(value["checks"], dict)
        or not value["checks"]
        or not all(result is True for result in value["checks"].values())
        or not isinstance(value["evidenceDigests"], list)
    ):
        raise RuntimeError(f"Invalid immutable {gate_name} gate")
    repository.read_bytes_verified(value["subjectDigest"])
    for digest in value["evidenceDigests"]:
        repository.read_bytes_verified(digest)
    return GateResult(
        gate_name=gate_name,
        work_unit_id=work_unit_id,
        content_digest=pointer.target_id,
        subject_digest=value["subjectDigest"],
        passed=True,
        evidence_digests=tuple(value["evidenceDigests"]),
    )


def get_work_unit(
    project_root: Path,
    work_unit_id: str,
    *,
    expected_recipe_digest: str | None = None,
    expected_catalog_digest: str | None = None,
) -> WorkUnit:
    catalog = discover_work_units(project_root)
    if (
        expected_catalog_digest is not None
        and catalog.catalog_digest != expected_catalog_digest
    ):
        raise RuntimeError("Discovered catalog changed after run dispatch")
    matches = [unit for unit in catalog.units if unit.work_unit_id == work_unit_id]
    if len(matches) != 1:
        raise KeyError(f"Unknown work unit {work_unit_id}")
    unit = matches[0]
    if (
        expected_recipe_digest is not None
        and unit.recipe_digest != expected_recipe_digest
    ):
        raise RuntimeError("Recipe revision changed after run dispatch")
    return unit


def work_unit_run_key(unit: WorkUnit) -> str:
    return (
        f"work-unit:{unit.work_unit_id}:recipe:{unit.recipe_digest}:"
        f"profile:{unit.processing_profile_digest}"
    )


def execution_network_isolated(gateway: WorkerGateway | None) -> bool:
    return gateway is None or gateway.config.network_isolation_enforced


def _publish_input_gate(
    repository: LocalArtifactRepository, unit: WorkUnit, subject_digest: str
) -> GateResult:
    value = _load_json_content(repository, subject_digest)
    expected_inputs = {
        "workbook": {
            "role": "workbook",
            "contentDigest": unit.workbook_digest,
            "byteLength": unit.workbook_length,
            "schemaVersion": "tidy.fixture/v1",
        },
        "recipeRevision": {
            "role": "recipeRevision",
            "contentDigest": unit.recipe_digest,
            "byteLength": unit.recipe_length,
            "schemaVersion": "recipe-v01",
        },
    }
    parsed_inputs = value.get("inputs")
    if not isinstance(parsed_inputs, list):
        raise RuntimeError("Input index inputs must be an array")
    actual_inputs = {
        item.get("role"): item
        for item in parsed_inputs
        if isinstance(item, dict) and set(item) == set(expected_inputs["workbook"])
    }
    schema_ok = (
        set(value)
        == {
            "schemaVersion",
            "workUnitId",
            "workbookDigest",
            "sheetName",
            "requestedUseCase",
            "processingProfileDigest",
            "inputs",
        }
        and value.get("schemaVersion") == "tidy.work-unit-inputs-index/v1"
        and value.get("workUnitId") == unit.work_unit_id
        and value.get("workbookDigest") == unit.workbook_digest
        and value.get("sheetName") == unit.sheet_name
        and value.get("requestedUseCase") == unit.requested_use_case
        and value.get("processingProfileDigest") == unit.processing_profile_digest
        and actual_inputs == expected_inputs
        and len(parsed_inputs) == 2
    )
    custody_ok = True
    bytes_ok = True
    expected_sources = {
        unit.workbook_digest: f"fixtures/workbooks/{unit.fixture}.xlsx",
        unit.recipe_digest: f"fixtures/recipes/{unit.fixture}.json",
    }
    for digest, source_locator in expected_sources.items():
        try:
            repository.read_bytes_verified(digest)
            receipts = repository.list_custody(content_digest=digest)
            custody_ok = custody_ok and any(
                receipt.actor == "tidy.dagster-projection/v1"
                and receipt.classification == "licensed-synthetic-parity-fixture"
                and receipt.source_locator == source_locator
                and receipt.storage_uri == f"fixture://{source_locator}"
                for receipt in receipts
            )
        except Exception:
            bytes_ok = False
    if not (schema_ok and custody_ok and bytes_ok):
        raise RuntimeError("Input/provenance gate failed")
    return _publish_gate(
        repository,
        "input-provenance",
        unit,
        subject_digest,
        tuple(expected_sources),
        {
            "schemaAndBinding": schema_ok,
            "contentClosure": bytes_ok,
            "custody": custody_ok,
        },
    )


def _publish_execution_gate(
    repository: LocalArtifactRepository,
    project_root: Path,
    unit: WorkUnit,
    subject_digest: str,
) -> GateResult:
    value = _validated_execution_index(repository, project_root, unit, subject_digest)
    output_digests = tuple(item["contentDigest"] for item in value["outputs"])
    derivation = repository.get_derivation(value["derivationId"])
    input_closure = derivation.ordered_input_digests == (
        unit.workbook_digest,
        unit.recipe_digest,
    )
    output_closure = derivation.ordered_output_digests == output_digests
    if not input_closure or not output_closure:
        raise RuntimeError("Execution derivation closure failed")
    return _publish_gate(
        repository,
        "frozen-reference-execution",
        unit,
        subject_digest,
        (value["inputIndexDigest"], *output_digests),
        {
            "schemaAndBinding": True,
            "inputClosure": input_closure,
            "outputClosure": output_closure,
            "frozenReferenceGold": True,
            "providerFree": value["providerCalls"] == 0,
            "networkIsolation": value["networkIsolationEnforced"] is True,
        },
    )


def _publish_reconstruction_gate(
    repository: LocalArtifactRepository, unit: WorkUnit, subject_digest: str
) -> GateResult:
    value = _load_json_content(repository, subject_digest)
    execution = _load_json_content(repository, value.get("executionIndexDigest", ""))
    output_digests = value.get("outputDigests")
    schema_ok = (
        set(value)
        == {
            "schemaVersion",
            "workUnitId",
            "fixture",
            "executionIndexDigest",
            "recipeRevisionDigest",
            "derivationId",
            "outputFingerprint",
            "outputDigests",
            "recordCount",
            "providerCalls",
        }
        and value.get("schemaVersion") == "tidy.active-work-unit-projection/v1"
        and value.get("workUnitId") == unit.work_unit_id
        and value.get("fixture") == unit.fixture
        and value.get("recipeRevisionDigest") == unit.recipe_digest
        and value.get("providerCalls") == 0
        and isinstance(output_digests, list)
        and value.get("recordCount") == len(output_digests)
    )
    closure_ok = (
        execution.get("workUnitId") == unit.work_unit_id
        and execution.get("derivationId") == value.get("derivationId")
        and execution.get("outputFingerprint") == value.get("outputFingerprint")
        and [item.get("contentDigest") for item in execution.get("outputs", [])]
        == output_digests
    )
    bytes_ok = True
    for digest in output_digests if isinstance(output_digests, list) else []:
        try:
            repository.read_bytes_verified(digest)
        except Exception:
            bytes_ok = False
    execution_gate = get_gate_result(
        repository,
        "frozen-reference-execution",
        unit.work_unit_id,
        unit.recipe_digest,
    )
    gate_ok = execution_gate.subject_digest == value.get("executionIndexDigest")
    if not (schema_ok and closure_ok and bytes_ok and gate_ok):
        raise RuntimeError("Reconstruction gate failed")
    return _publish_gate(
        repository,
        "authoritative-reconstruction",
        unit,
        subject_digest,
        (value["executionIndexDigest"], *output_digests),
        {
            "schemaAndBinding": schema_ok,
            "executionClosure": closure_ok,
            "contentClosure": bytes_ok,
            "executionGate": gate_ok,
        },
    )


def _validated_execution_index(
    repository: LocalArtifactRepository,
    project_root: Path,
    unit: WorkUnit,
    subject_digest: str,
) -> dict[str, Any]:
    value = _load_json_content(repository, subject_digest)
    outputs = value.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise RuntimeError("Execution outputs must be a non-empty array")
    input_pointer = repository.get_pointer(_revision_pointer("inputs", unit))
    schema_ok = (
        set(value)
        == {
            "schemaVersion",
            "workUnitId",
            "fixture",
            "inputIndexDigest",
            "recipeRevisionDigest",
            "processingProfileDigest",
            "derivationId",
            "reproductionKey",
            "outputFingerprint",
            "outputs",
            "referenceGoldVerified",
            "networkIsolationEnforced",
            "providerCalls",
        }
        and value.get("schemaVersion") == "tidy.work-unit-execution-index/v1"
        and value.get("workUnitId") == unit.work_unit_id
        and value.get("fixture") == unit.fixture
        and input_pointer is not None
        and value.get("inputIndexDigest") == input_pointer.target_id
        and value.get("recipeRevisionDigest") == unit.recipe_digest
        and value.get("processingProfileDigest") == unit.processing_profile_digest
        and value.get("referenceGoldVerified") is True
        and value.get("networkIsolationEnforced") is True
        and value.get("providerCalls") == 0
    )
    if not schema_ok:
        raise RuntimeError("Execution schema/work-unit binding failed")
    actual: list[tuple[str, str, str, int]] = []
    for item in outputs:
        if not isinstance(item, dict) or set(item) != {
            "name",
            "relativePath",
            "contentDigest",
            "byteLength",
        }:
            raise RuntimeError("Execution output descriptor is invalid")
        digest = item.get("contentDigest")
        descriptor = repository.get_content(digest)
        repository.read_bytes_verified(digest)
        if descriptor.byte_length != item.get("byteLength"):
            raise RuntimeError("Execution output length closure failed")
        actual.append(
            (item.get("name"), item.get("relativePath"), digest, descriptor.byte_length)
        )
    _fixture_manifest, gold_manifest = load_verified_fixture_manifests(project_root)
    expected = _verify_and_index_gold(project_root, gold_manifest["fixtures"])[
        unit.fixture
    ]
    if tuple(actual) != expected:
        raise RuntimeError("Execution outputs do not match frozen reference gold")
    return value


def _publish_gate(
    repository: LocalArtifactRepository,
    gate_name: str,
    unit: WorkUnit,
    subject_digest: str,
    evidence_digests: tuple[str, ...],
    checks: dict[str, bool],
) -> GateResult:
    if not checks or not all(checks.values()):
        raise RuntimeError(f"Cannot publish failed {gate_name} gate")
    gate_bytes = canonical_json_bytes(
        {
            "schemaVersion": "tidy.gate-result/v1",
            "gateName": gate_name,
            "workUnitId": unit.work_unit_id,
            "recipeRevisionDigest": unit.recipe_digest,
            "subjectDigest": subject_digest,
            "passed": True,
            "evidenceDigests": list(evidence_digests),
            "checks": checks,
        }
    )
    descriptor = repository.put_bytes(
        gate_bytes,
        kind="gate-result",
        schema_version="tidy.gate-result/v1",
        media_type="application/json",
    )
    _ensure_pointer(
        repository,
        (f"m4/revisions/{unit.work_unit_id}/{unit.recipe_digest}/gates/{gate_name}"),
        descriptor.content_digest,
    )
    return GateResult(
        gate_name,
        unit.work_unit_id,
        descriptor.content_digest,
        subject_digest,
        True,
        evidence_digests,
    )


def _load_json_content(
    repository: LocalArtifactRepository, digest: str
) -> dict[str, Any]:
    value = json.loads(repository.read_bytes_verified(digest))
    if not isinstance(value, dict):
        raise RuntimeError("Authoritative JSON artifact must be an object")
    return value


def _manifest_entry(
    entries: list[dict[str, Any]], fixture: str, copied_path: str
) -> dict[str, Any]:
    matches = [
        entry
        for entry in entries
        if entry["fixture"] == fixture and entry["copiedPath"] == copied_path
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Manifest does not contain exactly one {copied_path}")
    return matches[0]


def _work_unit_wire(unit: WorkUnit) -> dict[str, Any]:
    return {
        "workUnitId": unit.work_unit_id,
        "fixture": unit.fixture,
        "workbookDigest": unit.workbook_digest,
        "sheetName": unit.sheet_name,
        "requestedUseCase": unit.requested_use_case,
        "processingProfileDigest": unit.processing_profile_digest,
        "recipeRevisionDigest": unit.recipe_digest,
    }


def _descriptor_for_bytes(data: bytes, kind: str, schema: str) -> ContentDescriptor:
    from .artifacts import sha256_digest

    return ContentDescriptor(
        kind=kind,
        schema_version=schema,
        media_type="application/json",
        byte_length=len(data),
        content_digest=sha256_digest(data),
    )


def _revision_pointer(kind: str, unit: WorkUnit) -> str:
    return f"m4/revisions/{unit.work_unit_id}/{unit.recipe_digest}/{kind}"


def _ensure_pointer(
    repository: LocalArtifactRepository, name: str, target_id: str
) -> None:
    existing = repository.get_pointer(name)
    if existing is not None:
        if existing.target_id != target_id:
            raise RuntimeError(
                f"Authoritative pointer {name} conflicts with deterministic output"
            )
        return
    try:
        repository.compare_and_swap_pointer(name, None, target_id)
    except PointerConflict:
        winner = repository.get_pointer(name)
        if winner is None or winner.target_id != target_id:
            raise


def _set_active_pointer(
    repository: LocalArtifactRepository, name: str, target_id: str
) -> None:
    existing = repository.get_pointer(name)
    if existing is not None and existing.target_id == target_id:
        return
    expected_revision = None if existing is None else existing.revision
    try:
        repository.compare_and_swap_pointer(name, expected_revision, target_id)
    except PointerConflict:
        winner = repository.get_pointer(name)
        if winner is None or winner.target_id != target_id:
            raise
