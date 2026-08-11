from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema.validators import validator_for

from tidy_orchestrator.artifacts import domain_digest, sha256_digest

PROJECT = Path(__file__).parents[1]
REFERENCE_SCHEMA = PROJECT / "contracts/reference-context/v1/reference.schema.json"
PARITY_SCHEMA = PROJECT / "contracts/reference-context/v1/parity.schema.json"
REFERENCE = PROJECT / "fixtures/reference-context/historical-v1.json"
PARITY = PROJECT / "fixtures/reference-context/candidate-parity-v1.json"
BUNDLE = (
    PROJECT
    / "reference/source-closures"
    / "sha256-3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17"
)
REFERENCE_DIGEST = (
    "sha256:1bf6352d8379cec115896e74642dd4cefaa4bf50c21540827815055164cd8cb9"
)
PARITY_DIGEST = (
    "sha256:d7cc5a3905e6cb3d78d379e27e76b02b936775e0da4d3e7c5c8e3e34e834636a"
)


def _validate(schema_path: Path, value: dict) -> None:
    schema = json.loads(schema_path.read_text())
    validator = validator_for(schema)
    validator.check_schema(schema)
    validator(schema, format_checker=validator.FORMAT_CHECKER).validate(value)


def test_historical_compact_context_reference_is_strict_and_bound() -> None:
    reference = json.loads(REFERENCE.read_text())
    _validate(REFERENCE_SCHEMA, reference)
    semantic = dict(reference)
    reference_digest = semantic.pop("referenceDigest")
    assert reference_digest == REFERENCE_DIGEST
    assert reference_digest == domain_digest(
        "tidy.historical-source-compact-context-reference/v1", semantic
    )
    discovery = json.loads((BUNDLE / "DISCOVERY.json").read_text())
    commit = json.loads((BUNDLE / "COMMITTED.json").read_text())
    assert reference["closureManifestDigest"] == discovery["manifestDigest"]
    assert reference["copyCommitDigest"] == commit["commitDigest"]
    assert reference["sourceTreeDigestBefore"] == reference["sourceTreeDigestAfter"]
    assert reference["runtimeSiblingDependencyUsed"] is False
    assert reference["networkIsolationEnforced"] is True
    assert reference["candidateImplementationUsed"] is False
    assert reference["independentReview"] is False
    assert reference["parityEstablished"] is False
    assert sum(case["contextCount"] for case in reference["cases"]) == 4
    for case in reference["cases"]:
        case_semantic = dict(case)
        case_digest = case_semantic.pop("caseDigest")
        assert case_digest == domain_digest(
            "tidy.historical-source-compact-context-reference-case/v1",
            case_semantic,
        )
        assert (
            sha256_digest((PROJECT / case["workbookRelativePath"]).read_bytes())
            == case["workbookContentDigest"]
        )
        assert case["contextCount"] == len(case["contexts"])
        for context in case["contexts"]:
            encoded = context["serialized"].encode()
            assert hashlib.sha256(encoded).hexdigest() == context["digest"]
            assert len(context["serialized"]) == context["characters"]
            assert len(encoded) == context["bytes"]
            parsed = json.loads(context["serialized"])
            assert parsed["schemaVersion"] == "cell-role-compact-context-v1"
    raw = REFERENCE.read_text()
    assert "/Users/" not in raw
    assert "/Volumes/" not in raw


def test_candidate_compact_context_parity_binds_current_source() -> None:
    parity = json.loads(PARITY.read_text())
    _validate(PARITY_SCHEMA, parity)
    semantic = dict(parity)
    parity_digest = semantic.pop("parityDigest")
    assert parity_digest == PARITY_DIGEST
    assert parity_digest == domain_digest(
        "tidy.candidate-compact-context-parity/v1", semantic
    )
    reference = json.loads(REFERENCE.read_text())
    assert parity["referenceDigest"] == reference["referenceDigest"]
    assert parity["referenceCaseDigests"] == [
        case["caseDigest"] for case in reference["cases"]
    ]
    files = []
    for file in parity["candidateFiles"]:
        digest = sha256_digest((PROJECT / file["relativePath"]).read_bytes())
        assert digest == file["contentDigest"]
        files.append({"relativePath": file["relativePath"], "contentDigest": digest})
    assert parity["candidateSourceDigest"] == domain_digest(
        "tidy.candidate-compact-context-source-closure/v1", files
    )
    assert parity["comparison"]["matchedContextCount"] == 4
    assert parity["scope"]["scopeParityEstablished"] is True
    assert parity["scope"]["fullPhaseCParityEstablished"] is False
    assert parity["review"]["independentReview"] is False
