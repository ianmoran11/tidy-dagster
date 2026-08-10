from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from tidy_orchestrator.artifacts import canonical_json_bytes, domain_digest
from tidy_orchestrator.migration_evidence import (
    MigrationEvidenceError,
    create_typed_evidence_records,
)
from tidy_orchestrator.migration_import import MigrationRepository

PROJECT = Path(__file__).parents[1]
CONTRACTS = PROJECT / "contracts/import/v1"
TIME = "2026-08-10T10:00:00Z"
ACTOR = "phase-b-fixture-interpreter"
CONTENT = "sha256:" + "a" * 64
SNAPSHOT = "sha256:" + "b" * 64
IMPORTER = "sha256:" + "c" * 64


def _item(
    path: str,
    artifact: str,
    *,
    disposition: str = "import",
    embedded=None,
    warnings=None,
):
    return {
        "relativePath": path,
        "entryType": "file",
        "artifactClass": artifact,
        "disposition": disposition,
        "ruleId": "fixture-rule",
        "sourceMode": 0o100600,
        "byteLength": 10,
        "contentDigest": CONTENT,
        "gitState": "untracked",
        "embeddedRecords": embedded or [],
        "warnings": warnings or [],
    }


def _import(item, state=None):
    if state is None:
        state = {
            "import": "imported",
            "duplicate-alias": "duplicate-alias",
            "exclude": "excluded",
            "quarantine": "quarantined",
        }[item["disposition"]]
    blob_stored = item["disposition"] != "exclude"
    semantic = {
        "schemaVersion": "tidy.migration-import-item/v1",
        "snapshotDigest": SNAPSHOT,
        "importerDigest": IMPORTER,
        "relativePath": item["relativePath"],
        "entryType": "file",
        "artifactClass": item["artifactClass"],
        "classification": "restricted",
        "proposedDisposition": item["disposition"],
        "finalState": state,
        "sourceMode": item["sourceMode"],
        "byteLength": item["byteLength"],
        "sourceItemDigest": domain_digest("tidy.export-item/v1", item),
        "sourceContentDigest": CONTENT,
        "contentDigest": CONTENT if blob_stored else None,
        "blobStored": blob_stored,
        "storageUri": f"cas+sha256://{CONTENT}" if blob_stored else None,
        "recordedAt": TIME,
        "actor": ACTOR,
    }
    return {
        **semantic,
        "recordId": domain_digest("tidy.migration-import-item/v1", semantic),
    }


def _validate(name: str, value) -> None:
    schema = json.loads((CONTRACTS / name).read_text())
    validator_for(schema).check_schema(schema)
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    validator_for(schema)(schema, registry=registry).validate(value)


def test_typed_evidence_is_stored_but_never_activated(tmp_path: Path) -> None:
    recipe_item = _item(
        "candidate.recipe.json", "recipe-evidence", disposition="quarantine"
    )
    recipe = create_typed_evidence_records(
        source_item=recipe_item,
        import_record=_import(recipe_item, "quarantined"),
        recorded_at=TIME,
        actor=ACTOR,
    )[0]
    assert (recipe["lifecycleState"], recipe["active"]) == (
        "incomplete_evidence",
        False,
    )
    assert recipe["trainingEligible"] is False
    assert recipe["reason"] == "SOURCE_QUARANTINED"
    _validate("recipe-evidence-import.schema.json", recipe)

    model_item = _item("legacy.pkl", "model-binary")
    model = create_typed_evidence_records(
        source_item=model_item,
        import_record=_import(model_item),
        recorded_at=TIME,
        actor=ACTOR,
    )[0]
    assert model["eligibility"] == "archival-unreviewed"
    assert model["deserializationStatus"] == "not-attempted"
    assert model["runnable"] is model["trainingEligible"] is False
    _validate("model-package-disposition.schema.json", model)

    embedded = [
        {"kind": "prompt-evidence", "pointer": "/prompt", "valueType": "string"},
        {
            "kind": "provider-response-evidence",
            "pointer": "/response",
            "valueType": "string",
        },
    ]
    generation_item = _item(
        "provider-result.json", "generation-json-evidence", embedded=embedded
    )
    generation = create_typed_evidence_records(
        source_item=generation_item,
        import_record=_import(generation_item),
        recorded_at=TIME,
        actor=ACTOR,
    )[0]
    assert generation["rawEvidenceRestricted"] is True
    assert generation["interpretationStatus"] == "not-run"
    assert "restricted prompt" not in json.dumps(generation)
    _validate("generation-evidence.schema.json", generation)

    repository = MigrationRepository(tmp_path / "metadata")
    for record in (recipe, model, generation):
        repository.add_typed_record(
            record_id=record["recordId"],
            record_type=record["schemaVersion"],
            record=record,
        )
    assert len(repository.list_typed_records()) == 3
    with pytest.raises(ValueError, match="schemaVersion"):
        repository.add_typed_record(
            record_id=model["recordId"],
            record_type="wrong-type",
            record=model,
        )
    with pytest.raises(ValueError, match="does not bind"):
        repository.add_typed_record(
            record_id="sha256:" + "9" * 64,
            record_type=model["schemaVersion"],
            record=model,
        )
    tampered = dict(model)
    tampered["reason"] = "TAMPERED"
    with sqlite3.connect(repository.database) as connection:
        connection.execute(
            "UPDATE typed_records SET record_json=? WHERE record_id=?",
            (canonical_json_bytes(tampered), model["recordId"]),
        )
        connection.commit()
    with pytest.raises(ValueError, match="identity digest differs"):
        repository.list_typed_records()


def test_source_and_import_binding_fails_closed() -> None:
    item = _item("legacy.pkl", "model-binary")
    tampered = _import(item)
    tampered["relativePath"] = "other.pkl"
    with pytest.raises(MigrationEvidenceError, match="does not bind"):
        create_typed_evidence_records(
            source_item=item,
            import_record=tampered,
            recorded_at=TIME,
            actor=ACTOR,
        )
    unstored = _import(item)
    unstored["blobStored"] = False
    unstored["contentDigest"] = None
    unstored["storageUri"] = None
    unstored_semantic = dict(unstored)
    del unstored_semantic["recordId"]
    unstored["recordId"] = domain_digest(
        "tidy.migration-import-item/v1", unstored_semantic
    )
    with pytest.raises(MigrationEvidenceError, match="not bound to stored bytes"):
        create_typed_evidence_records(
            source_item=item,
            import_record=unstored,
            recorded_at=TIME,
            actor=ACTOR,
        )

    excluded_item = _item(
        "excluded.recipe.json", "recipe-evidence", disposition="exclude"
    )
    excluded = create_typed_evidence_records(
        source_item=excluded_item,
        import_record=_import(excluded_item),
        recorded_at=TIME,
        actor=ACTOR,
    )[0]
    assert excluded["reason"] == "SOURCE_EXCLUDED"
    assert excluded["sourceFinalState"] == "excluded"
    assert excluded["blobStored"] is False
    _validate("recipe-evidence-import.schema.json", excluded)

    ordinary = _item("ordinary.bin", "other")
    assert (
        create_typed_evidence_records(
            source_item=ordinary,
            import_record=_import(ordinary),
            recorded_at=TIME,
            actor=ACTOR,
        )
        == ()
    )


def test_typed_evidence_contract_rejects_unknown_fields() -> None:
    item = _item("legacy.pkl", "model-binary")
    model = create_typed_evidence_records(
        source_item=item,
        import_record=_import(item),
        recorded_at=TIME,
        actor=ACTOR,
    )[0]
    invalid = copy.deepcopy(model)
    invalid["unexpected"] = True
    with pytest.raises(ValidationError):
        _validate("model-package-disposition.schema.json", invalid)
