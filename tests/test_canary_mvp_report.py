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
    assert report["sourceReadBytes"] == 44_084_669
    assert report["itemOutcomeBytes"] == sum(report["stateBytes"].values())
    assert report["itemOutcomeBytes"] - report["sourceReadBytes"] == 68
    assert report["failureCount"] == len(report["failures"]) == 0
    assert report["uniqueStoredBytes"] <= report["sourceReadBytes"]
    interpretations = report["interpretations"]
    assert interpretations["eligibleSourceCounts"] == {
        "approval-registry": 1,
        "generation-json-evidence": 2,
        "recipe-evidence": 4,
    }
    assert interpretations["approvalRegistry"]["interpretedSourceCount"] == 1
    assert interpretations["approvalRegistry"]["rowCount"] == 331
    assert len(interpretations["approvalRegistry"]["sourceContentDigests"]) == 1
    assert len(interpretations["approvalRegistry"]["workerOutputContentDigests"]) == 1
    assert interpretations["approvalRegistry"]["approvalAuthorityCreated"] is False
    assert interpretations["approvalRegistry"]["targetsResolved"] is False
    assert interpretations["recipes"]["interpretedSourceCount"] == 4
    assert interpretations["recipes"]["schemaValidCount"] == 4
    assert len(interpretations["recipes"]["workerOutputContentDigests"]) == 4
    assert interpretations["recipes"]["active"] is False
    assert interpretations["generationProfiles"]["profiledSourceCount"] == 2
    assert len(interpretations["generationProfiles"]["workerOutputContentDigests"]) == 2
    assert interpretations["generationProfiles"]["rawRestrictedTextEmitted"] is False
    assert interpretations["providerDispatchAuthorized"] is False
    assert interpretations["retryAuthorized"] is False
    assert interpretations["activationAuthorized"] is False
    assert interpretations["trainingEligible"] is False
    assert report["localBlobDataDisposable"] is True
    assert report["sqliteLocal"] is True
    assert report["nasRequired"] is False
    assert report["automaticActivationAuthorized"] is False
    assert report["providerDispatchAuthorized"] is False
    assert report["trainingAuthorized"] is False
    assert report["fullImportAuthorized"] is False
    assert report["manualInspectionRequired"] is True
