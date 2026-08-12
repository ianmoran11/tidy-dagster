from __future__ import annotations

import json
from pathlib import Path

from jsonschema.validators import validator_for

from tidy_orchestrator.artifacts import domain_digest

PROJECT = Path(__file__).parents[1]
REPORT = PROJECT / "fixtures/canary-mvp/phase-b-63-item-report-v1.json"
SCHEMA = PROJECT / "contracts/canary-mvp/v1/report.schema.json"


def test_checked_canary_mvp_report_is_strict_and_non_authorizing() -> None:
    report = json.loads(REPORT.read_text())
    schema = json.loads(SCHEMA.read_text())
    validator_for(schema).check_schema(schema)
    validator_for(schema)(
        schema, format_checker=validator_for(schema).FORMAT_CHECKER
    ).validate(report)
    semantic = dict(report)
    digest = semantic.pop("reportDigest")
    assert digest == domain_digest("tidy.canary-mvp-report/v1", semantic)
    assert report["itemCount"] == sum(report["stateCounts"].values()) == 63
    assert report["sourceReadBytes"] == sum(report["stateBytes"].values())
    assert report["uniqueStoredBytes"] <= report["sourceReadBytes"]
    assert report["generationProfiles"] == {
        "eligibleSourceCount": 2,
        "profiledSourceCount": 2,
        "profileOutputRecordIds": [
            "sha256:388770a5409df19133d55de94b1b0dfc4db91a0a3e1568b807969b1c8c684398",
            "sha256:643f4f54407fc3b0d5bf38b3d45b3a7f8930e8015ff667824a9c913cf1561378",
        ],
        "restrictedElementCount": 0,
        "strictRecipeCandidateCount": 0,
        "rawRestrictedTextEmitted": False,
        "providerDispatchAuthorized": False,
        "retryAuthorized": False,
        "activationAuthorized": False,
        "trainingEligible": False,
    }
    assert report["automaticActivationAuthorized"] is False
    assert report["providerDispatchAuthorized"] is False
    assert report["trainingAuthorized"] is False
    assert report["fullImportAuthorized"] is False
    assert report["manualInspectionRequired"] is True
