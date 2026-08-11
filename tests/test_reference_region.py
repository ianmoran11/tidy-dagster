import hashlib
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parents[1]
REFERENCE_SCHEMA = "tidy.historical-source-region-catalog-reference/v1"
CASE_SCHEMA = "tidy.historical-source-region-catalog-reference-case/v1"
PARITY_SCHEMA = "tidy.candidate-region-catalog-parity/v1"
SOURCE_DOMAIN = "tidy.candidate-region-catalog-source-closure/v1"
REFERENCE_DIGEST = (
    "sha256:7632516d91c47855105d72b072df7368bf67b2167c0e74a4ab4833f6b5a954df"
)
PARITY_DIGEST = (
    "sha256:1ff8c4be2c785745f1e2c8fbd839160da659f56c6a571911368526047b76c0a1"
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _domain_digest(domain: str, value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(domain.encode() + b"\0" + _canonical(value)).hexdigest()
    )


def _load(name: str) -> dict:
    return json.loads((ROOT / "fixtures/reference-region" / name).read_text())


def _schema(name: str) -> dict:
    return json.loads((ROOT / "contracts/reference-region/v1" / name).read_text())


def test_historical_region_reference_is_strict_non_candidate_evidence() -> None:
    record = _load("historical-v1.json")
    jsonschema.Draft202012Validator(
        _schema("reference.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    ).validate(record)
    digest = record.pop("referenceDigest")
    assert _domain_digest(REFERENCE_SCHEMA, record) == digest == REFERENCE_DIGEST
    assert record["candidateImplementationUsed"] is False
    assert record["parityEstablished"] is False
    assert record["independentReview"] is False
    assert record["sourceTreeDigestBefore"] == record["sourceTreeDigestAfter"]
    assert sum(case["catalogCount"] for case in record["cases"]) == 4
    for case in record["cases"]:
        case_digest = case["caseDigest"]
        semantic = {key: value for key, value in case.items() if key != "caseDigest"}
        assert _domain_digest(CASE_SCHEMA, semantic) == case_digest


def test_region_candidate_parity_binds_current_sources() -> None:
    record = _load("candidate-parity-v1.json")
    jsonschema.Draft202012Validator(
        _schema("parity.schema.json"),
        format_checker=jsonschema.FormatChecker(),
    ).validate(record)
    digest = record.pop("parityDigest")
    assert _domain_digest(PARITY_SCHEMA, record) == digest == PARITY_DIGEST
    files = []
    for entry in record["candidateFiles"]:
        content = (ROOT / entry["relativePath"]).read_bytes()
        content_digest = "sha256:" + hashlib.sha256(content).hexdigest()
        assert content_digest == entry["contentDigest"]
        files.append(
            {
                "relativePath": entry["relativePath"],
                "contentDigest": content_digest,
            }
        )
    assert _domain_digest(SOURCE_DOMAIN, files) == record["candidateSourceDigest"]
    assert record["referenceDigest"] == REFERENCE_DIGEST
    assert record["matchedCatalogCount"] == 4
    assert record["mismatchCount"] == 0
    assert record["scope"]["scopeParityEstablished"] is True
    assert record["scope"]["fullPhaseCParityEstablished"] is False
    assert record["review"]["independent"] is False
