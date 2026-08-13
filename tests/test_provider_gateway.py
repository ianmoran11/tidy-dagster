from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tidy_orchestrator.artifacts import domain_digest, sha256_digest
from tidy_orchestrator.provider_gateway import (
    AUTHORIZATION_SCHEMA,
    BudgetLedger,
    ProviderGatewayError,
    _extract_pi_json_lines,
    _usage_cost,
    verify_live_authorization,
)


def test_budget_ledger_reserves_concurrently_without_overspend(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "budget.sqlite3", maximum_calls=6, maximum_cost=2)

    def reserve(number: int) -> str:
        try:
            ledger.reserve(f"attempt-{number}", 0.5)
            return "reserved"
        except ProviderGatewayError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(reserve, range(8)))
    assert outcomes.count("reserved") == 4
    assert outcomes.count("PROVIDER_COST_BUDGET_EXHAUSTED") == 4
    summary = ledger.summary()
    assert summary["attemptCount"] == 4
    assert summary["outstandingMaximumUsd"] == 2


def test_ambiguous_attempt_cannot_be_retried_or_reused(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "budget.sqlite3", maximum_calls=6, maximum_cost=2)
    ledger.reserve("attempt", 0.25)
    ledger.mark_dispatched("attempt")
    ledger.mark_ambiguous("attempt")
    with pytest.raises(ProviderGatewayError, match="already recorded"):
        ledger.reserve("attempt", 0.25)
    with pytest.raises(ProviderGatewayError, match="not dispatched"):
        ledger.mark_ambiguous("attempt")
    assert ledger.summary()["states"] == {"ambiguous": 1}


def test_settlement_keeps_observed_cost_and_response_digest(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "budget.sqlite3", maximum_calls=6, maximum_cost=2)
    ledger.reserve("attempt", 0.5)
    ledger.mark_dispatched("attempt")
    ledger.settle("attempt", 0.1, "sha256:" + "a" * 64)
    assert ledger.summary() == {
        "maximumCalls": 6,
        "maximumCostUsd": 2,
        "attemptCount": 1,
        "settledCostUsd": 0.1,
        "outstandingMaximumUsd": 0,
        "states": {"settled": 1},
    }


def authorization(executable: Path, *, cohort: str, prompt: str) -> dict[str, object]:
    semantic: dict[str, object] = {
        "schemaVersion": AUTHORIZATION_SCHEMA,
        "cohortDigest": cohort,
        "promptContractDigest": prompt,
        "provider": "openai-codex",
        "model": "openai-codex/gpt-5.6-luna",
        "reasoning": "high",
        "maximumCalls": 6,
        "maximumCostUsd": 2.0,
        "maximumAttemptCostUsd": 0.5,
        "timeoutSeconds": 300,
        "piExecutable": str(executable),
        "piExecutableDigest": sha256_digest(executable.read_bytes()),
        "workUnits": ["2023", "2024", "2025"],
        "expiresAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "approvedBy": "test-reviewer",
    }
    return {
        **semantic,
        "authorizationDigest": domain_digest(AUTHORIZATION_SCHEMA, semantic),
    }


def test_live_authorization_binds_luna_cohort_prompt_and_executable(
    tmp_path: Path,
) -> None:
    executable = (tmp_path / "pi").resolve()
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)
    cohort = "sha256:" + "1" * 64
    prompt = "sha256:" + "2" * 64
    value = authorization(executable, cohort=cohort, prompt=prompt)
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(value))
    verified = verify_live_authorization(
        path, cohort_digest=cohort, prompt_contract_digest=prompt
    )
    assert verified["model"] == "openai-codex/gpt-5.6-luna"

    value["model"] = "openai-codex/gpt-5.6-sol"
    path.write_text(json.dumps(value))
    with pytest.raises(ProviderGatewayError, match="digest"):
        verify_live_authorization(
            path, cohort_digest=cohort, prompt_contract_digest=prompt
        )


def test_pi_json_lines_extracts_only_final_assistant_text_and_cost() -> None:
    events = [
        {"type": "session", "id": "ignored"},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "restricted"},
                    {"type": "text", "text": '{"ok":true}'},
                ],
                "usage": {"cost": {"total": 0.01}},
            },
        },
    ]
    content, usage = _extract_pi_json_lines(
        ("\n".join(json.dumps(item) for item in events) + "\n").encode()
    )
    assert content == '{"ok":true}'
    assert usage == {"cost": {"total": 0.01}}


def test_missing_provider_cost_fails_closed() -> None:
    with pytest.raises(ProviderGatewayError, match="cost evidence"):
        _usage_cost(None)
    with pytest.raises(ProviderGatewayError, match="cost evidence"):
        _usage_cost({"input": 1})


def test_live_authorization_rejects_expiry(tmp_path: Path) -> None:
    executable = (tmp_path / "pi").resolve()
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o700)
    cohort = "sha256:" + "1" * 64
    prompt = "sha256:" + "2" * 64
    value = authorization(executable, cohort=cohort, prompt=prompt)
    semantic = dict(value)
    semantic.pop("authorizationDigest")
    semantic["expiresAt"] = "2020-01-01T00:00:00+00:00"
    value = {
        **semantic,
        "authorizationDigest": domain_digest(AUTHORIZATION_SCHEMA, semantic),
    }
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ProviderGatewayError, match="expired"):
        verify_live_authorization(
            path,
            cohort_digest=cohort,
            prompt_contract_digest=prompt,
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
