from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

PROJECT = Path(__file__).parents[1]
CONTRACTS = PROJECT / "contracts/migration-worker/v1"
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
DIGEST_C = f"sha256:{'c' * 64}"
DIGEST_D = f"sha256:{'d' * 64}"


def _schemas():
    values = {
        path.name: json.loads(path.read_text())
        for path in sorted(CONTRACTS.glob("*.schema.json"))
    }
    registry = Registry()
    for schema in values.values():
        validator_for(schema).check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return values, registry


def _validate(schema, registry, value) -> None:
    validator_for(schema)(schema, registry=registry).validate(value)


def _limits():
    return {
        "maxInputBytes": 1024,
        "maxOutputBytes": 4096,
        "maxJsonDepth": 32,
        "maxJsonNodes": 1000,
        "maxRecords": 100,
    }


def _source():
    return {
        "sourceSnapshotDigest": DIGEST_A,
        "sourceItemDigest": DIGEST_B,
        "importRecordId": DIGEST_C,
        "relativePath": "recipes/example.json",
    }


def test_migration_worker_contracts_are_strict_and_self_consistent() -> None:
    schemas, registry = _schemas()
    recipe_request = {
        "protocolVersion": "tidy.migration-worker/v1",
        "requestId": "fixture-request",
        "operation": "parse-recipe-v01",
        "inputs": [
            {
                "name": "recipe",
                "relativePath": "source.json",
                "contentDigest": DIGEST_D,
                "byteLength": 256,
            }
        ],
        "parameters": {
            "source": _source(),
            "declaredRecipeDigest": DIGEST_D,
        },
        "limits": _limits(),
    }
    approval_request = copy.deepcopy(recipe_request)
    approval_request["operation"] = "digest-legacy-approval-registry-v1"
    approval_request["inputs"][0]["name"] = "registry"
    approval_request["parameters"].pop("declaredRecipeDigest")
    generation_request = copy.deepcopy(recipe_request)
    generation_request["operation"] = "profile-generation-evidence-v1"
    generation_request["inputs"][0]["name"] = "generation"
    generation_request["parameters"].pop("declaredRecipeDigest")
    health_request = {
        "protocolVersion": "tidy.migration-worker/v1",
        "requestId": "health",
        "operation": "health",
        "inputs": [],
        "parameters": {},
        "limits": _limits(),
    }
    for request in (
        recipe_request,
        approval_request,
        generation_request,
        health_request,
    ):
        _validate(schemas["request.schema.json"], registry, request)

    invalid = copy.deepcopy(recipe_request)
    invalid["parameters"]["unreviewed"] = True
    with pytest.raises(ValidationError):
        _validate(schemas["request.schema.json"], registry, invalid)
    invalid = copy.deepcopy(approval_request)
    invalid["inputs"][0]["name"] = "recipe"
    with pytest.raises(ValidationError):
        _validate(schemas["request.schema.json"], registry, invalid)

    success = {
        "protocolVersion": "tidy.migration-worker/v1",
        "requestId": "fixture-request",
        "ok": True,
        "outputs": [
            {
                "name": "recipe-revision",
                "relativePath": "recipe-revision.json",
                "contentDigest": DIGEST_A,
                "byteLength": 512,
            }
        ],
        "warnings": [],
    }
    error = {
        "protocolVersion": "tidy.migration-worker/v1",
        "requestId": "fixture-request",
        "ok": False,
        "error": {
            "code": "INVALID_RECIPE",
            "stage": "recipe",
            "message": "Recipe did not validate.",
        },
    }
    _validate(schemas["success.schema.json"], registry, success)
    _validate(schemas["error.schema.json"], registry, error)


def test_migration_worker_artifact_contracts_preserve_non_authority() -> None:
    schemas, registry = _schemas()
    source = {
        **_source(),
        "sourceContentDigest": DIGEST_D,
        "byteLength": 256,
    }
    approval_digests = {
        "schemaVersion": "tidy.migration-approval-row-digests/v1",
        "source": source,
        "algorithm": "tidycell-digest-record-v1",
        "algorithmSourceDigest": (
            "sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c"
        ),
        "recordCount": 1,
        "records": [{"index": 0, "sourceRecordDigest": DIGEST_A}],
    }
    revision = {
        "schemaVersion": "tidy.migration-recipe-revision/v1",
        "source": source,
        "recipeSchemaVersion": "0.1",
        "historicalDigestAlgorithm": "tidycell-digest-record-v1",
        "historicalDigestSourceDigest": (
            "sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c"
        ),
        "historicalRecipeDigest": DIGEST_A,
        "declaredRecipeDigest": None,
        "digestMatches": None,
        "sheetName": "Data",
        "tableCount": 1,
        "lifecycleState": "schema_valid",
        "active": False,
        "trainingEligible": False,
        "normalizedRecipe": {
            "version": "0.1",
            "sheet": "Data",
            "tables": [
                {
                    "name": "counts",
                    "values": {"name": "value", "cells": ["R2C2"]},
                    "headers": [],
                }
            ],
        },
    }
    generation_profile = {
        "schemaVersion": "tidy.migration-generation-evidence-profile/v1",
        "source": source,
        "historicalDigestAlgorithm": "tidycell-digest-record-v1",
        "historicalDigestSourceDigest": (
            "sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c"
        ),
        "structuralValueDigest": DIGEST_A,
        "interpretationStatus": "parsed-recognized",
        "restrictedElements": [
            {
                "pointer": "/prompt",
                "kind": "restricted-prompt",
                "valueType": "string",
                "valueDigest": DIGEST_B,
                "canonicalByteLength": 42,
            }
        ],
        "recipeCandidates": [],
        "safeMetadata": [
            {"pointer": "/provider", "key": "provider", "value": "fixture"}
        ],
        "totalVisitedNodes": 3,
        "unclassifiedLeafCount": 0,
        "rawEvidenceRestricted": True,
        "providerDispatchAuthorized": False,
        "retryAuthorized": False,
        "approvalAuthorityCreated": False,
        "activationAuthorized": False,
        "trainingEligible": False,
    }
    _validate(schemas["approval-row-digests.schema.json"], registry, approval_digests)
    _validate(schemas["recipe-revision.schema.json"], registry, revision)
    _validate(
        schemas["generation-evidence-profile.schema.json"],
        registry,
        generation_profile,
    )
    unsafe_generation = copy.deepcopy(generation_profile)
    unsafe_generation["rawPrompt"] = "must never be emitted"
    with pytest.raises(ValidationError):
        _validate(
            schemas["generation-evidence-profile.schema.json"],
            registry,
            unsafe_generation,
        )

    unsafe = copy.deepcopy(revision)
    unsafe["active"] = True
    with pytest.raises(ValidationError):
        _validate(schemas["recipe-revision.schema.json"], registry, unsafe)
    unsafe = copy.deepcopy(revision)
    unsafe["trainingEligible"] = True
    with pytest.raises(ValidationError):
        _validate(schemas["recipe-revision.schema.json"], registry, unsafe)
