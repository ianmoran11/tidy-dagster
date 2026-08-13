"""Restricted, authorization-gated Pi/Luna provider dispatch for the prototype."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import domain_digest, sha256_digest

MODEL = "openai-codex/gpt-5.6-luna"
PROVIDER = "openai-codex"
REASONING = "high"
AUTHORIZATION_SCHEMA = "tidy.product-prototype-live-authorization/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProviderGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProviderResponse:
    attempt_id: str
    content: str
    response_digest: str
    api_equivalent_usd: float
    usage: dict[str, Any] | None


class BudgetLedger:
    """SQLite reservation ledger that prevents concurrent overspend."""

    def __init__(self, database: Path, *, maximum_calls: int, maximum_cost: float):
        if maximum_calls <= 0 or maximum_cost <= 0:
            raise ValueError("Budget limits must be positive")
        self.database = database.resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.maximum_calls = maximum_calls
        self.maximum_cost = maximum_cost
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS attempts(
                    attempt_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    reserved_cost REAL NOT NULL,
                    settled_cost REAL,
                    response_digest TEXT
                );
                """
            )

    def reserve(self, attempt_id: str, maximum_attempt_cost: float) -> None:
        if maximum_attempt_cost <= 0:
            raise ValueError("Maximum attempt cost must be positive")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT state FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if existing is not None:
                raise ProviderGatewayError(
                    "ATTEMPT_ALREADY_EXISTS", "Attempt identity is already recorded"
                )
            count, committed, reserved = connection.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(COALESCE(settled_cost, 0)), 0),
                       COALESCE(SUM(CASE WHEN settled_cost IS NULL
                                         THEN reserved_cost ELSE 0 END), 0)
                FROM attempts
                """
            ).fetchone()
            if count >= self.maximum_calls:
                raise ProviderGatewayError(
                    "PROVIDER_CALL_BUDGET_EXHAUSTED", "Provider call budget exhausted"
                )
            if committed + reserved + maximum_attempt_cost > self.maximum_cost:
                raise ProviderGatewayError(
                    "PROVIDER_COST_BUDGET_EXHAUSTED", "Provider cost budget exhausted"
                )
            connection.execute(
                "INSERT INTO attempts VALUES (?, 'reserved', ?, NULL, NULL)",
                (attempt_id, maximum_attempt_cost),
            )
            connection.commit()

    def mark_dispatched(self, attempt_id: str) -> None:
        self._transition(attempt_id, "reserved", "dispatched")

    def settle(
        self, attempt_id: str, observed_cost: float, response_digest: str
    ) -> None:
        if observed_cost < 0 or not _DIGEST.fullmatch(response_digest):
            raise ValueError("Settlement fields are invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state, reserved_cost FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None or row[0] != "dispatched":
                raise ProviderGatewayError(
                    "ATTEMPT_STATE_INVALID", "Attempt is not dispatched"
                )
            charged = max(observed_cost, 0.0)
            if charged > float(row[1]):
                connection.rollback()
                raise ProviderGatewayError(
                    "PROVIDER_COST_EXCEEDED_RESERVATION",
                    "Observed provider cost exceeded the reserved maximum",
                )
            connection.execute(
                """UPDATE attempts SET state='settled', settled_cost=?,
                       response_digest=? WHERE attempt_id=?""",
                (charged, response_digest, attempt_id),
            )
            connection.commit()

    def mark_ambiguous(self, attempt_id: str) -> None:
        self._transition(attempt_id, "dispatched", "ambiguous")

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT state, reserved_cost, settled_cost FROM attempts"
            ).fetchall()
        return {
            "maximumCalls": self.maximum_calls,
            "maximumCostUsd": self.maximum_cost,
            "attemptCount": len(rows),
            "settledCostUsd": sum(row[2] or 0 for row in rows),
            "outstandingMaximumUsd": sum(row[1] for row in rows if row[2] is None),
            "states": {
                state: sum(1 for row in rows if row[0] == state)
                for state in sorted({row[0] for row in rows})
            },
        }

    def _transition(self, attempt_id: str, expected: str, target: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE attempts SET state=? WHERE attempt_id=? AND state=?",
                (target, attempt_id, expected),
            ).rowcount
            if changed != 1:
                raise ProviderGatewayError(
                    "ATTEMPT_STATE_INVALID", f"Attempt is not {expected}"
                )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, isolation_level=None, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection


class AuthorizedPiProvider:
    """One-shot Pi JSON gateway. No retry exists in this class."""

    def __init__(
        self,
        *,
        authorization_path: Path,
        cohort_digest: str,
        prompt_contract_digest: str,
        ledger: BudgetLedger,
        restricted_root: Path,
    ) -> None:
        self.authorization = verify_live_authorization(
            authorization_path,
            cohort_digest=cohort_digest,
            prompt_contract_digest=prompt_contract_digest,
        )
        self.ledger = ledger
        self.restricted_root = restricted_root.resolve()
        self.restricted_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.executable = Path(self.authorization["piExecutable"]).resolve()

    def dispatch(
        self,
        *,
        prompt: str,
        work_unit_id: str,
        ordinal: int,
        correction: bool = False,
    ) -> ProviderResponse:
        allowed = self.authorization["workUnits"]
        if work_unit_id not in allowed:
            raise ProviderGatewayError(
                "WORK_UNIT_NOT_AUTHORIZED", "Work unit is not authorized"
            )
        if correction and ordinal not in {2, 4, 6}:
            raise ProviderGatewayError(
                "CORRECTION_ORDINAL_INVALID", "Correction must use its reserved slot"
            )
        if not correction and ordinal not in {1, 3, 5}:
            raise ProviderGatewayError(
                "GENERATION_ORDINAL_INVALID", "Generation must use its reserved slot"
            )
        attempt_id = domain_digest(
            "tidy.product-prototype-provider-attempt/v1",
            {
                "authorizationDigest": self.authorization["authorizationDigest"],
                "workUnitId": work_unit_id,
                "ordinal": ordinal,
                "promptDigest": sha256_digest(prompt.encode()),
            },
        )
        self.ledger.reserve(
            attempt_id, float(self.authorization["maximumAttemptCostUsd"])
        )
        attempt_dir = self.restricted_root / attempt_id.split(":", 1)[1]
        attempt_dir.mkdir(mode=0o700)
        (attempt_dir / "prompt.txt").write_text(prompt)
        (attempt_dir / "prompt.txt").chmod(0o600)
        self.ledger.mark_dispatched(attempt_id)
        args = [
            str(self.executable),
            "--mode",
            "json",
            "--no-tools",
            "--no-session",
            "--no-context-files",
            "--provider",
            PROVIDER,
            "--model",
            MODEL,
            "--thinking",
            REASONING,
            prompt,
        ]
        try:
            completed = subprocess.run(
                args,
                cwd=tempfile.mkdtemp(prefix="tidy-provider-cwd-"),
                env=_allowlisted_environment(),
                input=b"",
                capture_output=True,
                timeout=int(self.authorization["timeoutSeconds"]),
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as error:
            self.ledger.mark_ambiguous(attempt_id)
            raise ProviderGatewayError(
                "AMBIGUOUS_DISPATCH", "Call may have reached the provider; do not retry"
            ) from error
        (attempt_dir / "response-envelope.json").write_bytes(completed.stdout)
        (attempt_dir / "response-envelope.json").chmod(0o600)
        if completed.returncode != 0:
            self.ledger.mark_ambiguous(attempt_id)
            raise ProviderGatewayError(
                "AMBIGUOUS_DISPATCH", "Pi did not return an unambiguous success"
            )
        try:
            content, usage = _extract_pi_json_lines(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            self.ledger.mark_ambiguous(attempt_id)
            raise ProviderGatewayError(
                "AMBIGUOUS_DISPATCH", "Pi success envelope was not understood"
            ) from error
        cost = _usage_cost(usage)
        digest = sha256_digest(content.encode())
        self.ledger.settle(attempt_id, cost, digest)
        return ProviderResponse(attempt_id, content, digest, cost, usage)


def verify_live_authorization(
    path: Path,
    *,
    cohort_digest: str,
    prompt_contract_digest: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Live authorization could not be read"
        ) from error
    if not isinstance(value, dict):
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Live authorization is not an object"
        )
    semantic = dict(value)
    identity = semantic.pop("authorizationDigest", None)
    if identity != domain_digest(AUTHORIZATION_SCHEMA, semantic):
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Authorization digest is invalid"
        )
    required = {
        "schemaVersion",
        "cohortDigest",
        "promptContractDigest",
        "provider",
        "model",
        "reasoning",
        "maximumCalls",
        "maximumCostUsd",
        "maximumAttemptCostUsd",
        "timeoutSeconds",
        "piExecutable",
        "piExecutableDigest",
        "workUnits",
        "expiresAt",
        "approvedBy",
    }
    if set(semantic) != required or (
        semantic.get("schemaVersion") != AUTHORIZATION_SCHEMA
        or semantic.get("cohortDigest") != cohort_digest
        or semantic.get("promptContractDigest") != prompt_contract_digest
        or semantic.get("provider") != PROVIDER
        or semantic.get("model") != MODEL
        or semantic.get("reasoning") != REASONING
        or semantic.get("maximumCalls") != 6
        or semantic.get("maximumCostUsd") != 2.0
    ):
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Authorization policy does not match"
        )
    instant = now or datetime.now(UTC)
    try:
        expiry = datetime.fromisoformat(
            str(semantic["expiresAt"]).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Authorization expiry is invalid"
        ) from error
    if expiry <= instant:
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_EXPIRED", "Live authorization has expired"
        )
    executable = Path(str(semantic["piExecutable"]))
    if not executable.is_absolute() or executable.resolve() != executable:
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Pi path must be absolute and canonical"
        )
    if not executable.is_file() or executable.is_symlink():
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Pi executable is not a regular file"
        )
    if sha256_digest(executable.read_bytes()) != semantic["piExecutableDigest"]:
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Pi executable identity differs"
        )
    if not semantic.get("approvedBy") or not semantic.get("workUnits"):
        raise ProviderGatewayError(
            "LIVE_AUTHORIZATION_INVALID", "Human approval and work units are required"
        )
    return value


def _extract_pi_json_lines(data: bytes) -> tuple[str, dict[str, Any] | None]:
    assistant: dict[str, Any] | None = None
    for raw_line in data.decode("utf-8").splitlines():
        if not raw_line.strip():
            continue
        event = json.loads(raw_line)
        if (
            isinstance(event, dict)
            and event.get("type") == "message_end"
            and isinstance(event.get("message"), dict)
            and event["message"].get("role") == "assistant"
        ):
            assistant = event["message"]
    if assistant is None:
        raise KeyError("assistant message_end")
    content = assistant.get("content")
    if not isinstance(content, list):
        raise TypeError("assistant content")
    text = "".join(
        item["text"]
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    )
    if not text:
        raise KeyError("assistant text")
    usage = assistant.get("usage")
    return text, usage if isinstance(usage, dict) else None


def _usage_cost(usage: dict[str, Any] | None) -> float:
    if not usage:
        raise ProviderGatewayError(
            "PROVIDER_USAGE_MISSING", "Provider usage/cost evidence is missing"
        )
    direct = usage.get("apiEquivalentUsd")
    if isinstance(direct, int | float) and not isinstance(direct, bool):
        return float(direct)
    cost = usage.get("cost")
    if isinstance(cost, dict):
        total = cost.get("total")
        if isinstance(total, int | float) and not isinstance(total, bool):
            return float(total)
    raise ProviderGatewayError(
        "PROVIDER_USAGE_MISSING", "Provider cost evidence is missing"
    )


def _allowlisted_environment() -> dict[str, str]:
    allowed = {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "TERM"}
    return {key: value for key, value in os.environ.items() if key in allowed}
