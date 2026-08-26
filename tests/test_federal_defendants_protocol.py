from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from tidy_orchestrator.artifacts import LocalArtifactRepository
from tidy_orchestrator.product_prototype import (
    ProductPrototypeError,
    _validate_cohort,
    _validate_contract,
    evaluate_execution_for_acceptance,
    run_product_prototype,
)

PROJECT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (PROJECT / "contracts/product-prototype/v1/cohort.schema.json").read_text()
)
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.FormatChecker()
)
DIGEST = "sha256:" + "1" * 64
FEDERAL_PROTOCOL = "FederalDefendantsGroupedRecipeV1"
FEDERAL_MODEL = "provider-free/federal-defendants/grouped-recipe-v1"
# Paired with the valid compiled W-axis coordinated-shrink case in the
# TypeScript protocol suite. The unchanged external policy pin must reject it.
BASELINE_W_GEOMETRY_AUTHORITY_DIGEST = (
    "sha256:e6b205f6a31d517d526782d1884933b7b866ec11463372a6e934f351208b1c0d"
)
COORDINATED_W_SHRINK_GEOMETRY_DIGEST = (
    "sha256:808048d3541a36a41351d03695f88e59de56b2e0c4d4fe0ef061147c2b10beaf"
)
INVENTORY = json.loads(
    (
        PROJECT / "fixtures/product-prototype/"
        "federal-defendants-release-source-inventory-v1.json"
    ).read_text()
)


def cohort(
    release_id: str = "2024-25",
    ordinal: int = 1,
    sheet_name: str = "Table 1",
) -> dict:
    download = next(
        entry
        for entry in INVENTORY["downloads"]
        if entry["releaseId"] == release_id and entry["downloadOrdinal"] == ordinal
    )
    sheet = next(entry for entry in download["sheets"] if entry["name"] == sheet_name)
    assert sheet["classification"] == "numbered-data"
    release_dates = {
        "2021-22": "2023-05-04",
        "2022-23": "2024-05-09",
        "2023-24": "2025-05-01",
        "2024-25": "2026-04-30",
    }
    return {
        "schemaVersion": "tidy.product-prototype-cohort/v1",
        "cohortId": "federal-defendants-canary",
        "publicationId": "federal-defendants-australia",
        "tableFamilyId": "federal-defendants-canary",
        "generation": {
            "provider": "openai-codex",
            "model": "openai-codex/gpt-5.6-luna",
            "reasoning": "high",
            "promptContract": "cell-role-semantic-map-v13-adjacent-year-aware",
            "maximumCalls": 2,
            "maximumCostUsd": 2.0,
            "correctionPolicy": "one-pre-execution-compilation-correction-only",
        },
        "acceptanceContract": "acceptance/federal-defendants-canary-v1.json",
        "workbooks": [
            {
                "year": int(release_id.split("-")[0]),
                "referenceDate": release_dates[release_id],
                "path": download["path"],
                "contentDigest": download["contentDigest"],
                "byteLength": download["byteLength"],
                "sheet": sheet_name,
                "releaseId": release_id,
                "downloadOrdinal": ordinal,
                "cubeId": download["cubeId"],
                "tableNamespace": sheet["tableNamespace"],
                "replayResponse": {
                    "path": "replay/federal-defendants-canary.response.txt",
                    "contentDigest": DIGEST,
                    "byteLength": 1,
                    "historicalModel": FEDERAL_MODEL,
                    "acceptanceAuthority": False,
                    "recipeProtocol": FEDERAL_PROTOCOL,
                },
            }
        ],
    }


def federal_source(entry: dict) -> dict:
    custody = next(
        sheet
        for download in INVENTORY["downloads"]
        if download.get("releaseId") == entry["releaseId"]
        and download.get("downloadOrdinal") == entry["downloadOrdinal"]
        for sheet in download.get("sheets", [])
        if sheet.get("name") == entry["sheet"]
    )
    authority = custody.get("authoritativeRange")
    if authority is None:
        authority = (
            f"A1:{chr(ord('A') + custody['semanticMaxColumn'] - 1)}"
            f"{custody['semanticMaxRow']}"
        )
    match = __import__("re").fullmatch(r"A1:([A-Z]+)(\d+)", authority)
    assert match is not None
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    return {
        "version": "federal-defendants-source-context/v1",
        "sourceWorkbookDigest": entry["contentDigest"],
        "executionWorkbookDigest": entry["contentDigest"],
        "physicalSheet": entry["sheet"],
        "authoritativeRange": f"R1C1:R{int(match.group(2))}C{column}",
    }


def assert_schema_rejects(value: dict) -> None:
    assert list(VALIDATOR.iter_errors(value))


def assert_runtime_rejects(value: dict) -> None:
    with pytest.raises(ProductPrototypeError):
        _validate_cohort(value)


def test_federal_grouped_cohort_schema_and_runtime_accept_exact_namespace() -> None:
    value = cohort()
    VALIDATOR.validate(value)
    _validate_cohort(value)


@pytest.mark.parametrize(
    ("release_id", "ordinal", "sheet_name"),
    [
        ("2021-22", 1, "Table 1"),
        ("2021-22", 2, "Table 5"),
        ("2022-23", 1, "Table 1"),
        ("2022-23", 2, "Table 6"),
        ("2023-24", 1, "Table 1"),
        ("2023-24", 2, "Table 6"),
        ("2024-25", 1, "Table 1"),
        ("2024-25", 2, "Table 6"),
    ],
)
def test_all_eight_release_cube_identities_bind_exact_custody(
    release_id: str, ordinal: int, sheet_name: str
) -> None:
    value = cohort(release_id, ordinal, sheet_name)
    VALIDATOR.validate(value)
    _validate_cohort(value)


def test_all_36_numbered_members_bind_exact_custody() -> None:
    seen = 0
    for download in INVENTORY["downloads"]:
        if download.get("kind") != "cube":
            continue
        for sheet in download["sheets"]:
            if sheet.get("classification") != "numbered-data":
                continue
            value = cohort(
                download["releaseId"], download["downloadOrdinal"], sheet["name"]
            )
            VALIDATOR.validate(value)
            _validate_cohort(value)
            seen += 1
    assert seen == 36


@pytest.mark.parametrize("field", ["path", "contentDigest", "byteLength", "sheet"])
def test_federal_runtime_rejects_self_consistent_non_custody_metadata(
    field: str,
) -> None:
    value = cohort()
    workbook = value["workbooks"][0]
    if field == "path":
        workbook[field] = (
            "workbooks/federal-defendants-australia-2024-25-"
            "federal-offence-group-source.xlsx"
        )
    elif field == "contentDigest":
        workbook[field] = DIGEST
    elif field == "byteLength":
        workbook[field] += 1
    else:
        workbook[field] = "Table 99"
    with pytest.raises(ProductPrototypeError, match="metadata"):
        _validate_cohort(value)


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign-publication",
        "wrong-model",
        "downgrade-protocol",
        "missing-protocol",
        "legacy-recipe-masquerade",
        "wrong-cube",
        "wrong-ordinal",
        "wrong-reference-date",
        "offenders-normalization",
    ],
)
def test_federal_grouped_cohort_rejects_downgrade_and_cross_namespace(
    mutation: str,
) -> None:
    value = cohort()
    workbook = value["workbooks"][0]
    replay = workbook["replayResponse"]
    if mutation == "foreign-publication":
        value["publicationId"] = "recorded-crime-offenders"
    elif mutation == "wrong-model":
        replay["historicalModel"] = (
            "provider-free/offenders-c4/semantic-map-v2-recipe-v01"
        )
    elif mutation == "downgrade-protocol":
        replay["recipeProtocol"] = "RecipeV01"
    elif mutation == "missing-protocol":
        replay.pop("recipeProtocol")
    elif mutation == "legacy-recipe-masquerade":
        replay.pop("recipeProtocol")
        replay["historicalModel"] = "human-authored/deterministic-map-v1"
        for field in ("releaseId", "downloadOrdinal", "cubeId", "tableNamespace"):
            workbook.pop(field)
    elif mutation == "wrong-cube":
        workbook["cubeId"] = "federal-offence-group"
    elif mutation == "wrong-ordinal":
        workbook["downloadOrdinal"] = 2
    elif mutation == "wrong-reference-date":
        workbook["referenceDate"] = "2025-06-30"
    elif mutation == "offenders-normalization":
        workbook["normalization"] = "digest-pinned-bounded-offenders-remaining-v1"
    else:  # pragma: no cover - parametrization is closed
        raise AssertionError(mutation)
    assert_schema_rejects(value)
    assert_runtime_rejects(value)


def test_malformed_federal_replay_fails_with_domain_error() -> None:
    value = cohort()
    value["workbooks"][0]["replayResponse"] = "x"
    assert_schema_rejects(value)
    with pytest.raises(ProductPrototypeError) as error:
        _validate_cohort(value)
    assert "attribute" not in str(error.value).lower()


def test_federal_recipe_declaration_cannot_masquerade_over_legacy_execution() -> None:
    contract = {
        "schemaVersion": "tidy.table-family-acceptance/v2",
        "expectedRecipeDigestsByYear": {"2024": DIGEST},
        "expectedRecipeProtocolsByYear": {"2024": FEDERAL_PROTOCOL},
        "expectedFederalGeometryAuthorityDigestsByYear": {"2024": DIGEST},
    }
    entry = cohort()["workbooks"][0]
    _, issues, _ = evaluate_execution_for_acceptance(
        execution={"tables": []},
        recipe={"version": "RecipeV01"},
        contract=contract,
        entry=entry,
        recipe_digest=DIGEST,
        recipe_protocol=FEDERAL_PROTOCOL,
    )
    codes = {issue["code"] for issue in issues}
    assert "RECIPE_PROTOCOL_DECLARATION_MISMATCH" in codes
    assert "FEDERAL_EXECUTION_AUTHORITY_INVALID" in codes


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "wrong-execution/v1"),
        ("recipeProtocol", "RecipeV01"),
        ("providerCalls", 1),
        ("providerCalls", True),
        ("acceptanceAuthority", True),
        ("trainingEligibility", True),
    ],
)
def test_federal_acceptance_rejects_execution_authority_mutations(
    field: str, value: object
) -> None:
    entry = cohort()["workbooks"][0]
    source = federal_source(entry)
    execution = {
        "version": "federal-defendants-grouped-logical-execution/v1",
        "recipeProtocol": FEDERAL_PROTOCOL,
        "source": source,
        "geometryAuthorityDigest": DIGEST,
        "sheet": entry["sheet"],
        "providerCalls": 0,
        "acceptanceAuthority": False,
        "trainingEligibility": False,
        "tables": [],
    }
    execution[field] = value
    contract = {
        "schemaVersion": "tidy.table-family-acceptance/v2",
        "expectedRecipeDigestsByYear": {"2024": DIGEST},
        "expectedRecipeProtocolsByYear": {"2024": FEDERAL_PROTOCOL},
        "expectedFederalGeometryAuthorityDigestsByYear": {"2024": DIGEST},
    }
    _, issues, _ = evaluate_execution_for_acceptance(
        execution=execution,
        recipe={
            "version": FEDERAL_PROTOCOL,
            "source": source,
            "geometryAuthorityDigest": DIGEST,
        },
        contract=contract,
        entry=entry,
        recipe_digest=DIGEST,
        recipe_protocol=FEDERAL_PROTOCOL,
    )
    assert "FEDERAL_EXECUTION_AUTHORITY_INVALID" in {issue["code"] for issue in issues}


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("missing-version", None),
        ("wrong-version", "wrong-source-context/v1"),
        ("missing-source-digest", None),
        ("wrong-source-digest", DIGEST),
        ("missing-execution-digest", None),
        ("wrong-execution-digest", DIGEST),
        ("missing-sheet", None),
        ("wrong-sheet", "Table 99"),
        ("missing-range", None),
        ("wrong-range", "R1C1:R1C1"),
        ("extra-source-key", "x"),
        ("missing-execution-sheet", None),
        ("wrong-execution-sheet", "Table 99"),
    ],
)
def test_federal_acceptance_requires_closed_source_context(
    mutation: str, value: object
) -> None:
    entry = cohort()["workbooks"][0]
    source = federal_source(entry)
    execution = {
        "version": "federal-defendants-grouped-logical-execution/v1",
        "recipeProtocol": FEDERAL_PROTOCOL,
        "source": copy.deepcopy(source),
        "geometryAuthorityDigest": DIGEST,
        "sheet": entry["sheet"],
        "providerCalls": 0,
        "acceptanceAuthority": False,
        "trainingEligibility": False,
        "tables": [],
    }
    recipe = {
        "version": FEDERAL_PROTOCOL,
        "source": copy.deepcopy(source),
        "geometryAuthorityDigest": DIGEST,
    }
    source_mutations = {
        "missing-version": "version",
        "wrong-version": "version",
        "missing-source-digest": "sourceWorkbookDigest",
        "wrong-source-digest": "sourceWorkbookDigest",
        "missing-execution-digest": "executionWorkbookDigest",
        "wrong-execution-digest": "executionWorkbookDigest",
        "missing-sheet": "physicalSheet",
        "wrong-sheet": "physicalSheet",
        "missing-range": "authoritativeRange",
        "wrong-range": "authoritativeRange",
    }
    if mutation in source_mutations:
        field = source_mutations[mutation]
        if mutation.startswith("missing-"):
            execution["source"].pop(field)
        else:
            execution["source"][field] = value
        recipe["source"] = copy.deepcopy(execution["source"])
    elif mutation == "extra-source-key":
        execution["source"]["extra"] = value
        recipe["source"] = copy.deepcopy(execution["source"])
    elif mutation == "missing-execution-sheet":
        execution.pop("sheet")
    else:
        execution["sheet"] = value
    contract = {
        "schemaVersion": "tidy.table-family-acceptance/v2",
        "expectedRecipeDigestsByYear": {"2024": DIGEST},
        "expectedRecipeProtocolsByYear": {"2024": FEDERAL_PROTOCOL},
        "expectedFederalGeometryAuthorityDigestsByYear": {"2024": DIGEST},
    }
    _, issues, _ = evaluate_execution_for_acceptance(
        execution=execution,
        recipe=recipe,
        contract=contract,
        entry=entry,
        recipe_digest=DIGEST,
        recipe_protocol=FEDERAL_PROTOCOL,
    )
    assert "FEDERAL_EXECUTION_AUTHORITY_INVALID" in {issue["code"] for issue in issues}


def test_valid_coordinated_geometry_shrink_requires_updated_external_policy_pin() -> (
    None
):
    entry = cohort()["workbooks"][0]
    source = federal_source(entry)
    changed_digest = COORDINATED_W_SHRINK_GEOMETRY_DIGEST
    assert changed_digest != BASELINE_W_GEOMETRY_AUTHORITY_DIGEST
    execution = {
        "version": "federal-defendants-grouped-logical-execution/v1",
        "recipeProtocol": FEDERAL_PROTOCOL,
        "source": source,
        "geometryAuthorityDigest": changed_digest,
        "sheet": entry["sheet"],
        "providerCalls": 0,
        "acceptanceAuthority": False,
        "trainingEligibility": False,
        "tables": [],
    }
    contract = {
        "schemaVersion": "tidy.table-family-acceptance/v2",
        "expectedRecipeDigestsByYear": {"2024": DIGEST},
        "expectedRecipeProtocolsByYear": {"2024": FEDERAL_PROTOCOL},
        "expectedFederalGeometryAuthorityDigestsByYear": {
            "2024": BASELINE_W_GEOMETRY_AUTHORITY_DIGEST
        },
    }
    _, issues, _ = evaluate_execution_for_acceptance(
        execution=execution,
        recipe={
            "version": FEDERAL_PROTOCOL,
            "source": source,
            "geometryAuthorityDigest": changed_digest,
        },
        contract=contract,
        entry=entry,
        recipe_digest=DIGEST,
        recipe_protocol=FEDERAL_PROTOCOL,
    )
    assert "FEDERAL_GEOMETRY_AUTHORITY_MISMATCH" in {issue["code"] for issue in issues}


def test_federal_live_mode_is_rejected_before_provider_dispatch(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    cohort_path = project / "cohort.json"
    cohort_path.write_text(json.dumps(cohort()) + "\n")
    with pytest.raises(ProductPrototypeError, match="provider-free replay only"):
        run_product_prototype(
            repository=LocalArtifactRepository(tmp_path / "repository"),
            project_root=project,
            cohort_path=cohort_path,
            output_root=tmp_path / "output",
            mode="live",
            live_response_root=tmp_path / "live",
            live_attempts={},
        )


def test_existing_offenders_c4_protocol_still_validates() -> None:
    path = PROJECT / (
        "fixtures/product-prototype/recorded-crime-offenders-fdv-breach-order-"
        "offenders-by-jurisdiction-time-series.json"
    )
    value = json.loads(path.read_text())
    VALIDATOR.validate(value)
    _validate_cohort(value)


def test_acceptance_protocol_pin_is_federal_only_and_mandatory() -> None:
    cohort_path = PROJECT / (
        "fixtures/product-prototype/recorded-crime-offenders-fdv-breach-order-"
        "offenders-by-jurisdiction-time-series.json"
    )
    offenders_cohort = json.loads(cohort_path.read_text())
    contract_path = (
        PROJECT / "fixtures/product-prototype" / offenders_cohort["acceptanceContract"]
    )
    contract = json.loads(contract_path.read_text())
    _validate_contract(contract, offenders_cohort)

    wrong_publication_contract = copy.deepcopy(contract)
    wrong_publication_contract["expectedRecipeProtocolsByYear"] = {
        year: FEDERAL_PROTOCOL
        for year in wrong_publication_contract["expectedRecipeProtocolsByYear"]
    }
    with pytest.raises(ProductPrototypeError):
        _validate_contract(wrong_publication_contract, offenders_cohort)

    federal_cohort = copy.deepcopy(offenders_cohort)
    federal_cohort["publicationId"] = "federal-defendants-australia"
    with pytest.raises(ProductPrototypeError):
        _validate_contract(contract, federal_cohort)

    federal_contract = copy.deepcopy(contract)
    federal_contract["expectedRecipeProtocolsByYear"] = {
        year: FEDERAL_PROTOCOL
        for year in federal_contract["expectedRecipeProtocolsByYear"]
    }
    federal_contract["expectedFederalGeometryAuthorityDigestsByYear"] = {
        year: DIGEST for year in federal_contract["expectedRecipeProtocolsByYear"]
    }
    _validate_contract(federal_contract, federal_cohort)

    wrong_publication_contract["expectedFederalGeometryAuthorityDigestsByYear"] = {
        year: DIGEST
        for year in wrong_publication_contract["expectedRecipeProtocolsByYear"]
    }
    with pytest.raises(ProductPrototypeError):
        _validate_contract(wrong_publication_contract, offenders_cohort)
