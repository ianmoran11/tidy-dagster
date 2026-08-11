from __future__ import annotations

import json
from pathlib import Path

from jsonschema.validators import validator_for

from tidy_orchestrator.artifacts import domain_digest, sha256_digest

PROJECT = Path(__file__).parents[1]
SCHEMA = PROJECT / "contracts/reference-summary/v1/reference.schema.json"
PARITY_SCHEMA = PROJECT / "contracts/reference-summary/v1/parity.schema.json"
REFERENCE = PROJECT / "fixtures/reference-summary/historical-v1.json"
PARITY = PROJECT / "fixtures/reference-summary/candidate-parity-v1.json"
BUNDLE = (
    PROJECT
    / "reference/source-closures"
    / "sha256-3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17"
)
REFERENCE_DIGEST = (
    "sha256:0d0dca23d4f08204cbf02d6cc841fbd5ba15df32aeab92da77a0f91f5ff49c70"
)


def test_historical_summary_reference_is_strict_bound_and_non_authoritative() -> None:
    schema = json.loads(SCHEMA.read_text())
    reference = json.loads(REFERENCE.read_text())
    validator = validator_for(schema)
    validator.check_schema(schema)
    validator(schema, format_checker=validator.FORMAT_CHECKER).validate(reference)

    semantic = dict(reference)
    reference_digest = semantic.pop("referenceDigest")
    assert reference_digest == REFERENCE_DIGEST
    assert reference_digest == domain_digest(
        "tidy.historical-source-summary-reference/v1", semantic
    )
    commit = json.loads((BUNDLE / "COMMITTED.json").read_text())
    discovery = json.loads((BUNDLE / "DISCOVERY.json").read_text())
    assert reference["closureManifestDigest"] == discovery["manifestDigest"]
    assert reference["copyCommitDigest"] == commit["commitDigest"]
    assert reference["sourceTreeDigestBefore"] == reference["sourceTreeDigestAfter"]
    assert reference["bundleVerifiedBefore"] is True
    assert reference["bundleVerifiedAfter"] is True
    assert reference["runtimeSiblingDependencyUsed"] is False
    assert reference["networkIsolationEnforced"] is True
    assert reference["candidateImplementationUsed"] is False
    assert reference["independentReview"] is False
    assert reference["parityEstablished"] is False

    manifest_items = {
        item["relativePath"]: item
        for source in discovery["sources"]
        if source["sourceSystem"] == "tidycell"
        for item in source["items"]
    }
    assert [case["caseId"] for case in reference["cases"]] == [
        "multi-table",
        "simple-crosstab",
        "sparse-headers",
    ]
    assert sum(case["sheetCount"] for case in reference["cases"]) == 4
    for case in reference["cases"]:
        case_semantic = dict(case)
        case_digest = case_semantic.pop("caseDigest")
        assert case_digest == domain_digest(
            "tidy.historical-source-summary-reference-case/v1", case_semantic
        )
        source_item = manifest_items[case["workbookRelativePath"]]
        assert source_item["role"] == "fixture"
        assert case["workbookContentDigest"] == source_item["contentDigest"]
        local_bytes = (PROJECT / case["workbookRelativePath"]).read_bytes()
        assert sha256_digest(local_bytes) == case["workbookContentDigest"]
        assert case["sheetCount"] == len(case["summaries"])

    raw = REFERENCE.read_text()
    assert "/Users/" not in raw
    assert "/Volumes/" not in raw


def test_candidate_summary_parity_record_binds_current_source() -> None:
    schema = json.loads(PARITY_SCHEMA.read_text())
    parity = json.loads(PARITY.read_text())
    validator = validator_for(schema)
    validator.check_schema(schema)
    validator(schema, format_checker=validator.FORMAT_CHECKER).validate(parity)
    semantic = dict(parity)
    parity_digest = semantic.pop("parityDigest")
    assert parity_digest == (
        "sha256:06cf9377e773ffe1164c1ea1f866a74072badf296a24f6e0457974c3cce24ff1"
    )
    assert parity_digest == domain_digest("tidy.candidate-summary-parity/v1", semantic)
    reference = json.loads(REFERENCE.read_text())
    assert parity["referenceDigest"] == reference["referenceDigest"]
    assert parity["referenceCaseDigests"] == [
        case["caseDigest"] for case in reference["cases"]
    ]
    current_files = []
    for file in parity["candidateFiles"]:
        digest = sha256_digest((PROJECT / file["relativePath"]).read_bytes())
        assert digest == file["contentDigest"]
        current_files.append(
            {"relativePath": file["relativePath"], "contentDigest": digest}
        )
    assert parity["candidateSourceDigest"] == domain_digest(
        "tidy.candidate-summary-source-closure/v1", current_files
    )
    assert parity["comparison"]["matchedSheetCount"] == 4
    assert parity["scope"]["scopeParityEstablished"] is True
    assert parity["scope"]["fullPhaseCParityEstablished"] is False
    assert parity["review"]["independentReview"] is False
