import hashlib
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parents[1]
SCHEMA_VERSION = "tidy.source-owned-prompt-parity/v1"
SOURCE_DOMAIN = "tidy.candidate-prompt-source-closure/v1"
PARITY_DIGEST = (
    "sha256:8f96220e3d617ab61c315556d749ab28d57e2f1d4fd00167c2ea95dcc45e72c2"
)
SOURCE_SNAPSHOT_DIGEST = (
    "sha256:590b27f2e3f87bc6efcf614e9e9a1c5eb6590c640a5d518aad4596628dfd612e"
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


def test_source_owned_prompt_parity_binds_current_candidate() -> None:
    record = json.loads(
        (ROOT / "fixtures/reference-prompt/prompt-parity-v1.json").read_text()
    )
    schema = json.loads(
        (ROOT / "contracts/reference-prompt/v1/parity.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(record)
    digest = record.pop("parityDigest")
    assert _domain_digest(SCHEMA_VERSION, record) == digest == PARITY_DIGEST
    files = []
    for entry in record["candidateFiles"]:
        content_digest = (
            "sha256:"
            + hashlib.sha256((ROOT / entry["relativePath"]).read_bytes()).hexdigest()
        )
        assert content_digest == entry["contentDigest"]
        files.append(
            {
                "relativePath": entry["relativePath"],
                "contentDigest": content_digest,
            }
        )
    assert _domain_digest(SOURCE_DOMAIN, files) == record["candidateSourceDigest"]
    snapshot = (ROOT / record["candidateSnapshot"]["relativePath"]).read_bytes()
    snapshot_digest = "sha256:" + hashlib.sha256(snapshot).hexdigest()
    assert snapshot_digest == SOURCE_SNAPSHOT_DIGEST
    bundle_source = (
        ROOT
        / "reference/source-closures"
        / "sha256-3ac83cc30cedc9edcf2f68b31c51297a914c755e117ee2b3887f5c90abd7de17"
        / "sources/tidycell"
    )
    source_snapshot = (
        bundle_source / record["sourceSnapshot"]["relativePath"]
    ).read_bytes()
    assert source_snapshot == snapshot
    source_test_digest = (
        "sha256:"
        + hashlib.sha256(
            (bundle_source / record["sourceTest"]["relativePath"]).read_bytes()
        ).hexdigest()
    )
    assert source_test_digest == record["sourceTest"]["contentDigest"]
    assert record["candidateSnapshot"]["contentDigest"] == SOURCE_SNAPSHOT_DIGEST
    assert record["sourceSnapshot"]["contentDigest"] == SOURCE_SNAPSHOT_DIGEST
    assert record["matchedSnapshotBytes"] is True
    assert record["sourceTestCount"] == record["candidateTestCount"] == 14
    assert record["scope"]["scopeParityEstablished"] is True
    assert record["scope"]["fullPhaseCParityEstablished"] is False
    assert record["review"]["independent"] is False
