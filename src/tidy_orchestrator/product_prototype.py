"""Replay-first end-to-end spreadsheet product prototype."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .application import actual_worker_gateway
from .artifacts import (
    ContentDescriptor,
    CustodyReceipt,
    DecisionRecord,
    LocalArtifactRepository,
    canonical_json_bytes,
    domain_digest,
    sha256_digest,
)
from .provider_gateway import AuthorizedPiProvider
from .worker import GatewayExecution, GatewayInput, WorkerGateway

COHORT_SCHEMA = "tidy.product-prototype-cohort/v1"
ACCEPTANCE_SCHEMA = "tidy.table-family-acceptance/v1"
RUN_SCHEMA = "tidy.product-prototype-run/v1"
MODEL = "openai-codex/gpt-5.6-luna"
PROMPT_CONTRACT = "cell-role-semantic-map-v13-adjacent-year-aware"


class ProductPrototypeError(RuntimeError):
    """The cohort or prototype run failed closed."""


@dataclass(frozen=True)
class PrototypeRun:
    run: ContentDescriptor
    report: dict[str, Any]


@dataclass(frozen=True)
class _PreparedWorkbook:
    entry: dict[str, Any]
    workbook: ContentDescriptor
    response: ContentDescriptor
    prepare: GatewayExecution
    provider_attempt: dict[str, Any] | None = None


@dataclass(frozen=True)
class _AcceptedWorkbook:
    entry: dict[str, Any]
    prepared: _PreparedWorkbook
    interpret: GatewayExecution
    decision: dict[str, Any]
    observations: tuple[dict[str, Any], ...]


def verify_live_evidence(
    project_root: Path,
    *,
    gateway: WorkerGateway | None = None,
    repository: LocalArtifactRepository | None = None,
) -> dict[str, Any]:
    project = project_root.resolve()
    root = project / "fixtures" / "product-prototype" / "live-evidence"
    manifest = _load_object((root / "manifest.json").read_bytes(), "live evidence")
    semantic = dict(manifest)
    identity = semantic.pop("manifestDigest", None)
    if identity != domain_digest("tidy.product-prototype-live-evidence/v1", semantic):
        raise ProductPrototypeError("Live evidence manifest digest is invalid")
    if (
        manifest.get("schemaVersion") != "tidy.product-prototype-live-evidence/v1"
        or manifest.get("model") != MODEL
        or manifest.get("reasoning") != "high"
        or manifest.get("providerCalls") != 3
        or manifest.get("acceptedWorkbookCount") != 3
        or manifest.get("exceptionWorkbookCount") != 0
        or manifest.get("canonicalObservationCount") != 729
        or manifest.get("rawPromptResponseIncluded") is not False
    ):
        raise ProductPrototypeError("Live evidence completion claims are invalid")
    cohort_path = (
        project / "fixtures" / "product-prototype" / "prisoners-table-30-2023-2025.json"
    )
    cohort = _load_object(cohort_path.read_bytes(), "checked cohort")
    contract_path = _safe_join(
        cohort_path.parent, str(cohort.get("acceptanceContract", ""))
    )
    if manifest.get("cohortDigest") != sha256_digest(
        cohort_path.read_bytes()
    ) or manifest.get("acceptanceContractDigest") != sha256_digest(
        contract_path.read_bytes()
    ):
        raise ProductPrototypeError("Live evidence is not bound to current contracts")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 16:
        raise ProductPrototypeError("Live evidence file closure is invalid")
    declared_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ProductPrototypeError("Live evidence file entry is invalid")
        relative = str(entry.get("path", ""))
        path = _safe_join(root, relative)
        _assert_declared_bytes(path.read_bytes(), entry, relative)
        declared_paths.add(relative)
    actual_paths = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    }
    if actual_paths != declared_paths:
        raise ProductPrototypeError("Live evidence contains undeclared files")
    run = _load_object((root / "run.json").read_bytes(), "live run")
    attempts = _load_object((root / "attempts.json").read_bytes(), "live attempts")
    campaign = _load_object(
        (root / "campaign-evidence.json").read_bytes(), "live campaign evidence"
    )
    campaign_semantic = dict(campaign)
    campaign_identity = campaign_semantic.pop("campaignDigest", None)
    authorized_cohort_path = _safe_join(
        root, str(campaign.get("authorizedCohortPath", ""))
    )
    authorization_path = _safe_join(
        root, str(campaign.get("authorizationEvidencePath", ""))
    )
    envelope_index_path = _safe_join(
        root, str(campaign.get("restrictedEnvelopeIndexPath", ""))
    )
    authorized_cohort_bytes = authorized_cohort_path.read_bytes()
    authorized_cohort = _load_object(authorized_cohort_bytes, "authorized cohort")
    authorization = _load_object(authorization_path.read_bytes(), "authorization")
    envelope_index = _load_object(
        envelope_index_path.read_bytes(), "restricted envelope index"
    )
    if (
        campaign_identity
        != domain_digest(
            "tidy.product-prototype-live-campaign-evidence/v1", campaign_semantic
        )
        or campaign.get("currentCohortDigest") != manifest.get("cohortDigest")
        or campaign.get("model") != MODEL
        or campaign.get("reasoning") != "high"
        or campaign.get("maximumCalls") != 6
        or campaign.get("maximumCostUsd") != 2.0
        or campaign.get("attempts") != attempts
        or sha256_digest(authorized_cohort_bytes)
        != campaign.get("authorizedCohortDigest")
        or authorization.get("authorizationDigest")
        != campaign.get("authorizationDigest")
        or authorization.get("cohortDigest") != campaign.get("authorizedCohortDigest")
        or authorization.get("promptContractDigest")
        != campaign.get("promptContractDigest")
        or authorization.get("piExecutableDigest") != campaign.get("piExecutableDigest")
        or envelope_index.keys() != attempts.keys()
    ):
        raise ProductPrototypeError("Live campaign evidence is invalid")
    _verify_authorized_cohort_transition(
        authorized=authorized_cohort,
        current=cohort,
        attempts=attempts,
    )
    for workbook in run.get("workbooks", []):
        year = str(workbook.get("year"))
        attempt = attempts.get(year)
        if (
            not isinstance(attempt, dict)
            or attempt.get("responseDigest")
            != run.get("liveAttempts", {}).get(year, {}).get("responseDigest")
            or attempt.get("semanticMapDigest")
            != sha256_digest((root / year / "semantic-map.json").read_bytes())
            or attempt.get("normalizedRecipeDigest")
            != sha256_digest((root / year / "normalized-recipe.json").read_bytes())
            or attempt.get("workbookDigest") != workbook.get("workbookDigest")
            or attempt.get("interpretationOperation") != "interpret-semantic-map-v13"
            or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(attempt.get("promptDigest"))
            )
            or not re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                str(attempt.get("responseEnvelopeDigest")),
            )
            or attempt.get("ledgerState") != "settled"
            or attempt.get("reservedCostUsd") != 0.5
            or envelope_index.get(year, {}).get("attemptId") != attempt.get("attemptId")
            or envelope_index.get(year, {}).get("promptDigest")
            != attempt.get("promptDigest")
            or envelope_index.get(year, {}).get("responseEnvelopeDigest")
            != attempt.get("responseEnvelopeDigest")
        ):
            raise ProductPrototypeError("Live attempt binding is invalid")
    canonical_json_data = (root / "canonical-observations.json").read_bytes()
    canonical_csv_data = (root / "canonical-observations.csv").read_bytes()
    rows = json.loads(canonical_json_data)
    if (
        run.get("runDigest") != manifest.get("runDigest")
        or run.get("mode") != "live"
        or run.get("freshLunaGeneration") is not True
        or run.get("providerCalls") != 3
        or run.get("canonicalJsonDigest") != sha256_digest(canonical_json_data)
        or run.get("canonicalCsvDigest") != sha256_digest(canonical_csv_data)
        or not isinstance(rows, list)
        or len(rows) != 729
        or json.loads((root / "exceptions.json").read_bytes()) != []
    ):
        raise ProductPrototypeError("Live evidence artifacts disagree")
    if gateway is not None:
        if repository is None:
            raise ProductPrototypeError("Live replay verification needs a repository")
        _verify_checked_live_recipes(
            project=project,
            root=root,
            cohort=cohort,
            contract=_load_object(contract_path.read_bytes(), "acceptance contract"),
            committed_rows=rows,
            committed_csv=canonical_csv_data,
            run=run,
            manifest=manifest,
            attempts=attempts,
            gateway=gateway,
            repository=repository,
        )
    return manifest


def _verify_authorized_cohort_transition(
    *,
    authorized: dict[str, Any],
    current: dict[str, Any],
    attempts: dict[str, Any],
) -> None:
    stable_top_level = (
        "cohortId",
        "publicationId",
        "tableFamilyId",
        "generation",
        "acceptanceContract",
    )
    if any(authorized.get(key) != current.get(key) for key in stable_top_level):
        raise ProductPrototypeError("Authorized cohort semantics changed")
    old_by_year = {str(item["year"]): item for item in authorized.get("workbooks", [])}
    new_by_year = {str(item["year"]): item for item in current.get("workbooks", [])}
    if (
        old_by_year.keys() != new_by_year.keys()
        or old_by_year.keys() != attempts.keys()
    ):
        raise ProductPrototypeError("Authorized cohort workbook set changed")
    for year, old in old_by_year.items():
        new = new_by_year[year]
        stable_fields = ("year", "referenceDate", "path", "sheet")
        if any(old.get(key) != new.get(key) for key in stable_fields):
            raise ProductPrototypeError(
                f"Authorized workbook semantics changed for {year}"
            )
        if year != "2025":
            for key in ("contentDigest", "byteLength"):
                if old.get(key) != new.get(key):
                    raise ProductPrototypeError(
                        f"Authorized workbook bytes changed for {year}"
                    )
        else:
            original_2025 = "sha256:" + (
                "f326cef55f707ca0d15f8fa489cadc839c498c1b8e6fa696e0c15f39ec4c8549"
            )
            normalized_2025 = "sha256:" + (
                "464f80e73901ae9010d2dbbf1fc1bf37222711a3ccacc44efdbe99953aa3d263"
            )
            if (
                new.get("normalization")
                != "trim-pathological-full-width-formatting-merge-v1"
                or old.get("contentDigest") != original_2025
                or new.get("contentDigest") != normalized_2025
            ):
                raise ProductPrototypeError("2025 normalization transition is invalid")
        if attempts[year].get("workbookDigest") != new.get("contentDigest"):
            raise ProductPrototypeError(f"Live attempt workbook differs for {year}")


def _verify_checked_live_recipes(
    *,
    project: Path,
    root: Path,
    cohort: dict[str, Any],
    contract: dict[str, Any],
    committed_rows: list[Any],
    committed_csv: bytes,
    run: dict[str, Any],
    manifest: dict[str, Any],
    attempts: dict[str, Any],
    gateway: WorkerGateway,
    repository: LocalArtifactRepository,
) -> None:
    base = project / "fixtures" / "product-prototype"
    recomputed: list[dict[str, Any]] = []
    for entry in cohort["workbooks"]:
        workbook_path = _safe_join(base, str(entry["path"]))
        workbook_bytes = workbook_path.read_bytes()
        _assert_declared_bytes(workbook_bytes, entry, f"workbook {entry['year']}")
        workbook = repository.put_bytes(
            workbook_bytes,
            kind="prototype-workbook",
            schema_version="xlsx/v1",
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        recipe_path = root / str(entry["year"]) / "normalized-recipe.json"
        recipe_bytes = recipe_path.read_bytes()
        recipe = repository.put_bytes(
            recipe_bytes,
            kind="worker-output",
            schema_version="tidy.worker-output/v1",
            media_type="application/json",
        )
        semantic_map_path = root / str(entry["year"]) / "semantic-map.json"
        semantic_map_bytes = semantic_map_path.read_bytes()
        semantic_map = repository.put_bytes(
            semantic_map_bytes,
            kind="worker-output",
            schema_version="tidy.worker-output/v1",
            media_type="application/json",
        )
        execution = gateway.execute(
            operation="interpret-semantic-map-v13",
            inputs=(
                GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),
                GatewayInput(
                    "semantic-map", semantic_map.content_digest, "semantic-map.json"
                ),
            ),
            parameters={"sheet": entry["sheet"]},
            limits={"maxWarnings": 10_000},
        )
        execution_json = _output_json(repository, execution, "execution.json")
        if _output_digest(execution, "normalized-recipe.json") != recipe.content_digest:
            raise ProductPrototypeError(
                f"Checked live recipe identity changed for {entry['year']}"
            )
        recipe_json = _load_object(recipe_bytes, "checked live recipe")
        observations, issues, _checks = _validate_execution(
            execution=execution_json,
            recipe=recipe_json,
            contract=contract,
            entry=entry,
            recipe_digest=recipe.content_digest,
            deterministic=True,
        )
        run_workbook = next(
            item for item in run["workbooks"] if item["year"] == entry["year"]
        )
        if (
            run_workbook.get("workbookDigest") != entry["contentDigest"]
            or run_workbook.get("sheet") != entry["sheet"]
        ):
            raise ProductPrototypeError(
                f"Live run workbook binding changed for {entry['year']}"
            )
        if issues or len(observations) != 243:
            raise ProductPrototypeError(
                f"Checked live recipe no longer passes for {entry['year']}: {issues!r}"
            )
        attempt = attempts[str(entry["year"])]
        provenance = {
            "publication_id": cohort["publicationId"],
            "execution_digest": _output_digest(execution, "execution.json"),
            "acceptance_policy_version": ACCEPTANCE_SCHEMA,
            "acceptance_policy_digest": sha256_digest(canonical_json_bytes(contract)),
            "acceptance_decision_digest": run_workbook["decisionId"],
            "prompt_package_digest": attempts[str(entry["year"])]["promptDigest"],
            "generation_model": attempt["model"],
            "generation_attempt_id": attempt["attemptId"],
        }
        recomputed.extend({**row, **provenance} for row in observations)
    ordered = sorted(
        recomputed,
        key=lambda row: tuple(str(row[key]) for key in contract["uniqueKey"]),
    )
    if ordered != committed_rows or _canonical_csv(ordered) != committed_csv:
        raise ProductPrototypeError(
            "Committed canonical dataset differs from checked live recipe replay"
        )
    settled_cost = sum(float(item["apiEquivalentUsd"]) for item in attempts.values())
    if (
        settled_cost != float(manifest["apiEquivalentUsd"])
        or settled_cost > 2.0
        or run.get("providerCalls")
        != sum(int(item["providerCallCount"]) for item in attempts.values())
    ):
        raise ProductPrototypeError("Checked live provider budget evidence disagrees")


def run_product_prototype(
    *,
    repository: LocalArtifactRepository,
    project_root: Path,
    cohort_path: Path,
    output_root: Path,
    mode: str = "replay",
    gateway: WorkerGateway | None = None,
    recorded_at: str | None = None,
    live_response_root: Path | None = None,
    live_attempts: dict[int | str, dict[str, Any]] | None = None,
    provider: AuthorizedPiProvider | None = None,
    acceptance_execution_mutator: Any | None = None,
) -> PrototypeRun:
    """Run the exact cohort from saved replay or freshly dispatched responses."""
    if mode not in {"replay", "live"}:
        raise ProductPrototypeError("Prototype mode must be replay or live")
    if mode == "live" and provider is None and live_response_root is None:
        raise ProductPrototypeError(
            "Live mode requires an authorized provider or restricted responses"
        )
    if mode == "live" and provider is None and live_attempts is None:
        raise ProductPrototypeError(
            "Stored live responses require digest-bound attempt evidence"
        )
    project = project_root.resolve()
    cohort_file = cohort_path.resolve()
    output = output_root.resolve()
    if not _is_within(cohort_file, project):
        raise ProductPrototypeError("Cohort manifest must be inside the project root")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    cohort_bytes = cohort_file.read_bytes()
    cohort = _load_object(cohort_bytes, "cohort")
    _validate_cohort(cohort)
    base = cohort_file.parent
    contract_path = _safe_join(base, str(cohort["acceptanceContract"]))
    contract_bytes = contract_path.read_bytes()
    contract = _load_object(contract_bytes, "acceptance contract")
    _validate_contract(contract, cohort)
    timestamp = recorded_at or datetime.now(UTC).isoformat()

    cohort_descriptor = _store_source(
        repository,
        cohort_bytes,
        kind="product-prototype-cohort",
        schema_version=COHORT_SCHEMA,
        source=cohort_file,
        project=project,
        timestamp=timestamp,
    )
    contract_descriptor = _store_source(
        repository,
        contract_bytes,
        kind="table-family-acceptance-contract",
        schema_version=ACCEPTANCE_SCHEMA,
        source=contract_path,
        project=project,
        timestamp=timestamp,
    )
    active_gateway = gateway or actual_worker_gateway(repository, project)
    if gateway is None and not active_gateway.config.network_isolation_enforced:
        raise ProductPrototypeError(
            "Production prototype execution requires enforced network isolation"
        )

    accepted: list[_AcceptedWorkbook] = []
    workbook_reports: list[dict[str, Any]] = []
    provider_attempts: dict[str, dict[str, Any]] = {}
    for workbook_index, entry in enumerate(cohort["workbooks"]):
        prepared = _prepare_one(
            repository=repository,
            gateway=active_gateway,
            project=project,
            base=base,
            entry=entry,
            timestamp=timestamp,
            mode=mode,
            live_response_root=live_response_root,
            provider=provider,
            live_attempt=_attempt_for_year(live_attempts, int(entry["year"])),
            dispatch_ordinal=2 * workbook_index + 1,
        )
        report = _interpret_accept_one(
            repository=repository,
            gateway=active_gateway,
            contract=contract,
            prepared=prepared,
            timestamp=timestamp,
            execution_mutator=acceptance_execution_mutator,
        )
        workbook_reports.append(report[0])
        if prepared.provider_attempt is not None:
            provider_attempts[str(entry["year"])] = prepared.provider_attempt
        if report[1] is not None:
            accepted.append(report[1])

    if mode == "live":
        total_calls = sum(
            int(item["providerCallCount"]) for item in provider_attempts.values()
        )
        total_cost = sum(
            float(item["apiEquivalentUsd"]) for item in provider_attempts.values()
        )
        generation = cohort["generation"]
        if (
            set(provider_attempts)
            != {str(item["year"]) for item in cohort["workbooks"]}
            or total_calls > int(generation["maximumCalls"])
            or total_cost > float(generation["maximumCostUsd"])
        ):
            raise ProductPrototypeError("Live attempt evidence exceeds campaign policy")

    canonical_rows = sorted(
        (row for item in accepted for row in item.observations),
        key=lambda row: tuple(str(row[key]) for key in contract["uniqueKey"]),
    )
    cross_year_issues = _cross_year_issues(canonical_rows, contract)
    combined_csv = _canonical_csv(canonical_rows)
    combined_json = canonical_json_bytes(canonical_rows) + b"\n"
    collation_report = _build_collation_report(
        workbooks=workbook_reports,
        rows=canonical_rows,
        contract=contract,
        cross_year_issues=cross_year_issues,
    )
    csv_descriptor = repository.put_bytes(
        combined_csv,
        kind="canonical-collated-csv",
        schema_version="tidy.canonical-observations/v1",
        media_type="text/csv",
    )
    json_descriptor = repository.put_bytes(
        combined_json,
        kind="canonical-collated-json",
        schema_version="tidy.canonical-observations/v1",
        media_type="application/json",
    )
    _write_output(output / "canonical-observations.csv", combined_csv)
    _write_output(output / "canonical-observations.json", combined_json)
    collation_bytes = canonical_json_bytes(collation_report) + b"\n"
    collation_descriptor = repository.put_bytes(
        collation_bytes,
        kind="product-prototype-collation-report",
        schema_version="tidy.product-prototype-collation/v1",
        media_type="application/json",
    )
    _write_output(output / "collation-report.json", collation_bytes)

    semantic = {
        "schemaVersion": RUN_SCHEMA,
        "mode": mode,
        "providerCalls": (
            0
            if mode == "replay"
            else sum(
                int(item["providerCallCount"]) for item in provider_attempts.values()
            )
        ),
        "freshLunaGeneration": mode == "live",
        "cohortDigest": cohort_descriptor.content_digest,
        "acceptanceContractDigest": contract_descriptor.content_digest,
        "modelReservedForLiveMode": MODEL,
        "workbooks": workbook_reports,
        "acceptedWorkbookCount": len(accepted),
        "exceptionWorkbookCount": len(workbook_reports) - len(accepted),
        "canonicalObservationCount": len(canonical_rows),
        "canonicalCsvDigest": csv_descriptor.content_digest,
        "canonicalJsonDigest": json_descriptor.content_digest,
        "collationReportDigest": collation_descriptor.content_digest,
        "crossYearIssues": cross_year_issues,
        "historicalReplayIsAcceptanceAuthority": False,
        "liveAttempts": provider_attempts if mode == "live" else None,
        "trainingEligibility": False,
    }
    run_record = {
        **semantic,
        "runDigest": domain_digest(RUN_SCHEMA, semantic),
    }
    run_bytes = canonical_json_bytes(run_record) + b"\n"
    run_descriptor = repository.put_bytes(
        run_bytes,
        kind="product-prototype-run",
        schema_version=RUN_SCHEMA,
        media_type="application/json",
    )
    _write_output(output / "run.json", run_bytes)
    _write_output(
        output / "exceptions.json",
        canonical_json_bytes(
            [
                item
                for item in workbook_reports
                if item["decision"] == "exception_required"
            ]
        )
        + b"\n",
    )
    return PrototypeRun(run=run_descriptor, report=run_record)


def _prepare_one(
    *,
    repository: LocalArtifactRepository,
    gateway: WorkerGateway,
    project: Path,
    base: Path,
    entry: dict[str, Any],
    timestamp: str,
    mode: str,
    live_response_root: Path | None,
    provider: AuthorizedPiProvider | None,
    live_attempt: dict[str, Any] | None,
    dispatch_ordinal: int,
) -> _PreparedWorkbook:
    workbook_path = _safe_join(base, str(entry["path"]))
    workbook_bytes = workbook_path.read_bytes()
    _assert_declared_bytes(workbook_bytes, entry, f"workbook {entry['year']}")
    replay = entry["replayResponse"]
    provider_attempt: dict[str, Any] | None = None
    if mode == "replay":
        response_path = _safe_join(base, str(replay["path"]))
        response_bytes = response_path.read_bytes()
        _assert_declared_bytes(
            response_bytes, replay, f"replay response {entry['year']}"
        )
        response_classification = (
            "restricted-historical-replay-not-acceptance-authority"
        )
    elif provider is not None:
        response_path = provider.restricted_root / str(entry["year"]) / "response.txt"
        response_bytes = b""
        response_classification = "restricted-fresh-luna-response"
    else:
        if live_response_root is None:
            raise ProductPrototypeError("Live response root is required")
        response_path = (
            live_response_root.resolve() / str(entry["year"]) / "response.txt"
        )
        if not _is_within(response_path, live_response_root.resolve()):
            raise ProductPrototypeError("Live response path escapes its root")
        if response_path.is_symlink() or not response_path.is_file():
            raise ProductPrototypeError(
                f"Fresh response is missing for {entry['year']}"
            )
        response_bytes = response_path.read_bytes()
        provider_attempt = _validate_live_attempt(
            live_attempt,
            year=int(entry["year"]),
            response_bytes=response_bytes,
        )
        response_classification = "restricted-fresh-luna-response"
    workbook = _store_source(
        repository,
        workbook_bytes,
        kind="prototype-workbook",
        schema_version="xlsx/v1",
        source=workbook_path,
        project=project,
        timestamp=timestamp,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    prepare = gateway.execute(
        operation="prepare-semantic-map-v13",
        inputs=(GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),),
        parameters={"sheet": entry["sheet"]},
        limits={"maxWarnings": 10_000},
    )
    if provider is not None:
        prompt = repository.read_bytes_verified(
            _output_digest(prepare, "prompt.txt")
        ).decode("utf-8")
        dispatched = provider.dispatch(
            prompt=prompt,
            work_unit_id=str(entry["year"]),
            ordinal=dispatch_ordinal,
        )
        response_bytes = dispatched.content.encode("utf-8")
        response_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_output(response_path, response_bytes)
        provider_attempt = {
            "attemptId": dispatched.attempt_id,
            "providerCallCount": 1,
            "apiEquivalentUsd": dispatched.api_equivalent_usd,
            "responseDigest": dispatched.response_digest,
            "correctionAttempted": False,
            "correctionSuccessful": False,
            "model": MODEL,
            "reasoning": "high",
        }
    response = _store_source(
        repository,
        response_bytes,
        kind="worker-output",
        schema_version="tidy.worker-output/v1",
        source=response_path,
        project=project,
        timestamp=timestamp,
        media_type="application/json",
        classification=response_classification,
    )
    return _PreparedWorkbook(entry, workbook, response, prepare, provider_attempt)


def _interpret_accept_one(
    *,
    repository: LocalArtifactRepository,
    gateway: WorkerGateway,
    contract: dict[str, Any],
    prepared: _PreparedWorkbook,
    timestamp: str,
    execution_mutator: Any | None = None,
) -> tuple[dict[str, Any], _AcceptedWorkbook | None]:
    entry = prepared.entry
    year = int(entry["year"])
    try:
        first = gateway.execute(
            operation="interpret-semantic-map-v13",
            inputs=(
                GatewayInput(
                    "workbook", prepared.workbook.content_digest, "workbook.xlsx"
                ),
                GatewayInput(
                    "semantic-map",
                    prepared.response.content_digest,
                    "semantic-map.json",
                ),
            ),
            parameters={"sheet": entry["sheet"]},
            limits={"maxWarnings": 10_000},
        )
        second = gateway.execute(
            operation="interpret-semantic-map-v13",
            inputs=(
                GatewayInput(
                    "workbook", prepared.workbook.content_digest, "workbook.xlsx"
                ),
                GatewayInput(
                    "semantic-map",
                    prepared.response.content_digest,
                    "semantic-map.json",
                ),
            ),
            parameters={"sheet": entry["sheet"]},
            limits={"maxWarnings": 10_000},
        )
        deterministic = _execution_identity(first) == _execution_identity(second)
        execution = _output_json(repository, first, "execution.json")
        recipe = _output_json(repository, first, "normalized-recipe.json")
        if execution_mutator is not None:
            execution, recipe, deterministic = execution_mutator(
                year, execution, recipe, deterministic
            )
        recipe_digest = _output_digest(first, "normalized-recipe.json")
        execution_digest = _output_digest(first, "execution.json")
        observations, issues, checks = _validate_execution(
            execution=execution,
            recipe=recipe,
            contract=contract,
            entry=entry,
            recipe_digest=recipe_digest,
            deterministic=deterministic,
        )
    except Exception as error:
        observations = ()
        issues = [
            {
                "code": getattr(error, "code", "INTERPRETATION_FAILED"),
                "message": str(error),
            }
        ]
        checks = {"interpretation": False, "deterministicReplay": False}
        first = None
        recipe_digest = None
        execution_digest = None

    decision = "prototype_auto_accepted" if not issues else "exception_required"
    subject_id = (
        _output_digest(first, "normalized-recipe.json")
        if first is not None
        else prepared.response.content_digest
    )
    decision_record = DecisionRecord.create(
        subject_id=subject_id,
        decision_type=decision,
        payload={
            "year": year,
            "workbookDigest": prepared.workbook.content_digest,
            "sheet": entry["sheet"],
            "checks": checks,
            "issues": issues,
            "acceptanceSource": "human-authored-table-family-contract",
            "historicalReplayIsAuthority": False,
            "trainingEligibility": False,
        },
        actor="tidy.product-prototype-policy/v1",
        recorded_at=timestamp,
    )
    repository.append_decision(decision_record)
    if first is not None and not issues:
        provenance = {
            "publication_id": "prisoners-in-australia",
            "execution_digest": execution_digest,
            "acceptance_policy_version": ACCEPTANCE_SCHEMA,
            "acceptance_policy_digest": sha256_digest(canonical_json_bytes(contract)),
            "acceptance_decision_digest": decision_record.decision_id,
            "prompt_package_digest": _output_digest(prepared.prepare, "prompt.txt"),
            "generation_model": (
                prepared.provider_attempt["model"]
                if prepared.provider_attempt is not None
                else (
                    MODEL
                    if entry["replayResponse"]["historicalModel"]
                    == "checked-live-semantic-map-replay-fixture"
                    else entry["replayResponse"]["historicalModel"]
                )
            ),
            "generation_attempt_id": (
                prepared.provider_attempt["attemptId"]
                if prepared.provider_attempt is not None
                else f"replay:{prepared.response.content_digest}"
            ),
        }
        observations = tuple({**row, **provenance} for row in observations)
    report = {
        "year": year,
        "referenceDate": entry["referenceDate"],
        "workbookDigest": prepared.workbook.content_digest,
        "sheet": entry["sheet"],
        "prepareDerivationId": prepared.prepare.derivation.derivation_id,
        "interpretDerivationId": (
            first.derivation.derivation_id if first is not None else None
        ),
        "decision": decision,
        "decisionId": decision_record.decision_id,
        "observationCount": len(observations),
        "checks": checks,
        "issues": issues,
    }
    accepted = (
        _AcceptedWorkbook(entry, prepared, first, report, observations)
        if first is not None and not issues
        else None
    )
    return report, accepted


def evaluate_execution_for_acceptance(
    *,
    execution: dict[str, Any],
    recipe: dict[str, Any],
    contract: dict[str, Any],
    entry: dict[str, Any],
    recipe_digest: str,
    deterministic: bool = True,
    extra_issues: list[dict[str, Any]] | None = None,
) -> tuple[tuple[dict[str, Any], ...], list[dict[str, Any]], dict[str, bool]]:
    """Public pure acceptance evaluator used by negative contract tests."""
    rows, issues, checks = _validate_execution(
        execution=execution,
        recipe=recipe,
        contract=contract,
        entry=entry,
        recipe_digest=recipe_digest,
        deterministic=deterministic,
    )
    injected = list(extra_issues or [])
    if injected:
        issues.extend(injected)
    return rows, _deduplicate_issues(issues), checks


def _validate_execution(
    *,
    execution: dict[str, Any],
    recipe: dict[str, Any],
    contract: dict[str, Any],
    entry: dict[str, Any],
    recipe_digest: str,
    deterministic: bool,
) -> tuple[tuple[dict[str, Any], ...], list[dict[str, Any]], dict[str, bool]]:
    issues: list[dict[str, Any]] = []
    checks: dict[str, bool] = {
        "interpretation": True,
        "deterministicReplay": deterministic,
        "nonEmpty": False,
        "rowBounds": False,
        "requiredDimensions": False,
        "codelists": False,
        "uniqueKeys": False,
        "sourceCellUniqueness": False,
        "totalEquations": False,
        "warningAllowlist": False,
    }
    if not deterministic:
        issues.append(_issue("NONDETERMINISTIC_REPLAY", "Repeated outputs differ."))
    tables = execution.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        issues.append(_issue("TABLE_COUNT_INVALID", "Expected exactly one table."))
        return (), issues, checks
    table = tables[0]
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list) or not rows:
        issues.append(_issue("EMPTY_OUTPUT", "Execution produced no observations."))
        return (), issues, checks
    checks["nonEmpty"] = True
    minimum = int(contract["expected"]["minimumRows"])
    maximum = int(contract["expected"]["maximumRows"])
    checks["rowBounds"] = minimum <= len(rows) <= maximum
    if not checks["rowBounds"]:
        issues.append(_issue("ROW_COUNT_OUT_OF_BOUNDS", f"Observed {len(rows)} rows."))

    names = _resolve_output_names(recipe, contract)
    checks["requiredDimensions"] = len(names) == 5
    if not checks["requiredDimensions"]:
        issues.append(
            _issue(
                "REQUIRED_DIMENSION_MISSING",
                "Recipe output names do not unambiguously cover all required "
                "dimensions.",
            )
        )
        return (), issues, checks

    canonical: list[dict[str, Any]] = []
    keys: set[tuple[str, ...]] = set()
    source_cells: set[str] = set()
    codelists_ok = True
    keys_ok = True
    source_ok = True
    for row in rows:
        if not isinstance(row, dict):
            codelists_ok = False
            continue
        source = row.get("_source")
        address = source.get("address") if isinstance(source, dict) else None
        if not isinstance(address, str) or address in source_cells:
            source_ok = False
        elif address:
            source_cells.add(address)
        mapped: dict[str, str] = {}
        for dimension in contract["requiredDimensions"]:
            raw = row.get(names[dimension])
            code = _map_alias(contract, dimension, raw)
            if code is None:
                codelists_ok = False
                issues.append(
                    _issue(
                        "UNKNOWN_CODE",
                        f"{dimension} value {raw!r} is not in the pinned code list.",
                    )
                )
                code = "UNKNOWN"
            mapped[dimension] = code
        value = row.get(names["measure"])
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            codelists_ok = False
            issues.append(_issue("VALUE_INVALID", f"Invalid count value {value!r}."))
        observation = {
            "reference_date": entry["referenceDate"],
            "jurisdiction_id": mapped["jurisdiction"],
            "indigenous_status_id": mapped["indigenous_status"],
            "sex_id": mapped["sex"],
            "legal_status_id": mapped["legal_status"],
            "measure_id": contract["measure"]["id"],
            "unit_id": contract["measure"]["unitId"],
            "value": value,
            "value_status": "observed",
            "source_workbook_digest": entry["contentDigest"],
            "source_sheet": entry["sheet"],
            "source_cell": address,
            "recipe_digest": recipe_digest,
            "raw_jurisdiction": row.get(names["jurisdiction"]),
            "raw_indigenous_status": row.get(names["indigenous_status"]),
            "raw_sex": row.get(names["sex"]),
            "raw_legal_status": row.get(names["legal_status"]),
        }
        key = tuple(str(observation[field]) for field in contract["uniqueKey"])
        if key in keys:
            keys_ok = False
            issues.append(_issue("DUPLICATE_OBSERVATION_KEY", repr(key)))
        keys.add(key)
        canonical.append(observation)
    coverage_issues = _validate_expected_coverage(canonical, contract)
    checks["coverage"] = not coverage_issues
    issues.extend(coverage_issues)
    checks["codelists"] = codelists_ok
    checks["uniqueKeys"] = keys_ok
    checks["sourceCellUniqueness"] = source_ok
    if not source_ok:
        issues.append(
            _issue("SOURCE_CELL_REUSE", "A source value cell was missing or reused.")
        )
    total_issues = _validate_totals(canonical, contract)
    checks["totalEquations"] = not total_issues
    issues.extend(total_issues)
    allowed_rules = contract["allowedExecutionWarnings"]
    warnings = execution.get("warnings", [])
    warning_issues = _validate_warning_rules(
        warnings if isinstance(warnings, list) else [],
        allowed_rules if isinstance(allowed_rules, list) else [],
        rows,
        names,
        contract,
    )
    checks["warningAllowlist"] = not warning_issues
    issues.extend(warning_issues)
    return tuple(canonical), _deduplicate_issues(issues), checks


def _resolve_output_names(
    recipe: dict[str, Any], contract: dict[str, Any]
) -> dict[str, str]:
    try:
        table = recipe["tables"][0]
        headers = [str(item["name"]) for item in table["headers"]]
        value = str(table["values"]["name"])
    except (KeyError, IndexError, TypeError):
        return {}
    resolved: dict[str, str] = {"measure": value}
    patterns = {
        "jurisdiction": re.compile(r"state|territory|jurisdiction", re.I),
        "indigenous_status": re.compile(r"indigenous", re.I),
        "sex": re.compile(r"\bsex\b", re.I),
        "legal_status": re.compile(r"legal status", re.I),
    }
    for dimension, pattern in patterns.items():
        matches = [name for name in headers if pattern.search(name)]
        if len(matches) != 1:
            return {}
        resolved[dimension] = matches[0]
    if set(contract["requiredDimensions"]) - set(resolved):
        return {}
    return resolved


def _map_alias(contract: dict[str, Any], dimension: str, raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    normalized = " ".join(raw.strip().split())
    aliases = contract["aliases"][dimension]
    return aliases.get(normalized)


def _validate_expected_coverage(
    rows: list[dict[str, Any]], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    expected = contract["expected"]
    required = {
        "jurisdiction_id": set(expected["jurisdictions"]),
        "indigenous_status_id": set(expected["indigenousStatuses"]),
        "sex_id": set(expected["sexes"]),
        "legal_status_id": set(expected["legalStatuses"]),
    }
    issues: list[dict[str, Any]] = []
    for field, wanted in required.items():
        observed = {str(row[field]) for row in rows}
        if observed != wanted:
            issues.append(
                _issue(
                    "EXPECTED_CATEGORY_COVERAGE_MISSING",
                    f"{field}: missing={sorted(wanted - observed)!r}; "
                    f"unexpected={sorted(observed - wanted)!r}",
                )
            )
    expected_count = 1
    for values in required.values():
        expected_count *= len(values)
    if len(rows) != expected_count:
        issues.append(
            _issue(
                "EXPECTED_COMBINATION_COVERAGE_MISSING",
                f"Expected {expected_count} category combinations; got {len(rows)}.",
            )
        )
    return issues


def _validate_warning_rules(
    warnings: list[Any],
    rules: list[Any],
    rows: list[Any],
    names: dict[str, str],
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    by_address = {
        row.get("_source", {}).get("address"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("_source"), dict)
    }
    for warning in warnings:
        if not isinstance(warning, dict):
            issues.append(_issue("UNALLOWLISTED_WARNING", "Malformed warning."))
            continue
        matching = [
            rule
            for rule in rules
            if isinstance(rule, dict) and rule.get("code") == warning.get("code")
        ]
        if len(matching) != 1:
            issues.append(_issue("UNALLOWLISTED_WARNING", str(warning.get("code"))))
            continue
        rule = matching[0]
        dimension = rule.get("dimension")
        if rule.get("requireCanonicalOutputEquivalence") is not True or not isinstance(
            dimension, str
        ):
            issues.append(_issue("WARNING_RULE_INVALID", repr(rule)))
            continue
        row = by_address.get(warning.get("address"))
        raw = row.get(names.get(dimension, "")) if isinstance(row, dict) else None
        if _map_alias(contract, dimension, raw) is None:
            issues.append(
                _issue(
                    "AMBIGUOUS_WARNING_OUTPUT_UNRESOLVED",
                    f"{dimension} output {raw!r} is not canonical at "
                    f"{warning.get('address')!r}.",
                )
            )
    return issues


def _validate_totals(
    rows: list[dict[str, Any]], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    field_by_dimension = {
        "jurisdiction": "jurisdiction_id",
        "indigenous_status": "indigenous_status_id",
        "sex": "sex_id",
        "legal_status": "legal_status_id",
    }
    dimensions = tuple(field_by_dimension)
    for equation in contract["totalEquations"]:
        dimension = equation["dimension"]
        field = field_by_dimension[dimension]
        others = [field_by_dimension[item] for item in dimensions if item != dimension]
        groups: dict[tuple[Any, ...], dict[str, float]] = {}
        for row in rows:
            key = tuple(row[item] for item in others)
            groups.setdefault(key, {})[str(row[field])] = float(row["value"])
        for key, values in groups.items():
            total_code = equation["totalCode"]
            components = equation["componentCodes"]
            if total_code not in values or any(
                code not in values for code in components
            ):
                issues.append(
                    _issue(
                        "TOTAL_COMPONENT_MISSING",
                        f"{dimension} group {key!r} lacks a required total "
                        "or component.",
                    )
                )
                continue
            expected = sum(values[code] for code in components)
            residual = values[total_code] - expected
            if residual < -float(
                equation["componentExcessTolerance"]
            ) or residual > float(equation["maximumUnmodelledResidual"]):
                issues.append(
                    _issue(
                        "TOTAL_MISMATCH",
                        f"{dimension} group {key!r}: residual={residual}.",
                    )
                )
    return issues


def _build_collation_report(
    *,
    workbooks: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    cross_year_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    included = [
        {
            "year": item["year"],
            "workbookDigest": item["workbookDigest"],
            "rowCount": item["observationCount"],
            "decisionId": item["decisionId"],
        }
        for item in workbooks
        if item["decision"] == "prototype_auto_accepted"
    ]
    excluded = [item for item in workbooks if item["decision"] == "exception_required"]
    issue_codes = {
        issue["code"]
        for item in workbooks
        for issue in item.get("issues", [])
        if isinstance(issue, dict) and isinstance(issue.get("code"), str)
    }
    return {
        "schemaVersion": "tidy.product-prototype-collation/v1",
        "includedWorkbooks": included,
        "excludedExceptions": excluded,
        "rowCount": len(rows),
        "duplicateCanonicalKeys": [
            item
            for item in cross_year_issues
            if item["code"] == "CROSS_WORKBOOK_DUPLICATE"
        ],
        "conflictingValues": [
            item
            for item in cross_year_issues
            if item["code"] == "CROSS_WORKBOOK_CONFLICT"
        ],
        "unmappedLabels": sorted(
            code for code in issue_codes if code == "UNKNOWN_CODE"
        ),
        "missingExpectedCategories": sorted(
            code for code in issue_codes if "COVERAGE_MISSING" in code
        ),
        "schemaFailures": sorted(
            code
            for code in issue_codes
            if code
            in {
                "TABLE_COUNT_INVALID",
                "REQUIRED_DIMENSION_MISSING",
                "ROW_COUNT_OUT_OF_BOUNDS",
            }
        ),
        "codeListFailures": sorted(
            code for code in issue_codes if code in {"UNKNOWN_CODE", "VALUE_INVALID"}
        ),
        "uniqueKey": contract["uniqueKey"],
    }


def _cross_year_issues(
    rows: list[dict[str, Any]], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    seen: dict[tuple[str, ...], Any] = {}
    issues: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(str(row[field]) for field in contract["uniqueKey"])
        if key in seen:
            code = (
                "CROSS_WORKBOOK_CONFLICT"
                if seen[key] != row["value"]
                else "CROSS_WORKBOOK_DUPLICATE"
            )
            issues.append(_issue(code, repr(key)))
        seen[key] = row["value"]
    return _deduplicate_issues(issues)


def _canonical_csv(rows: list[dict[str, Any]]) -> bytes:
    fields = [
        "reference_date",
        "jurisdiction_id",
        "indigenous_status_id",
        "sex_id",
        "legal_status_id",
        "measure_id",
        "unit_id",
        "value",
        "value_status",
        "source_workbook_digest",
        "source_sheet",
        "source_cell",
        "recipe_digest",
        "publication_id",
        "execution_digest",
        "acceptance_policy_version",
        "acceptance_policy_digest",
        "acceptance_decision_digest",
        "prompt_package_digest",
        "generation_model",
        "generation_attempt_id",
        "raw_jurisdiction",
        "raw_indigenous_status",
        "raw_sex",
        "raw_legal_status",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(
        {
            key: value.rstrip() if isinstance(value, str) else value
            for key, value in row.items()
        }
        for row in rows
    )
    return output.getvalue().encode("utf-8")


def _execution_identity(execution: GatewayExecution) -> tuple[Any, ...]:
    return (
        execution.output_paths,
        tuple(item.content_digest for item in execution.outputs),
        execution.output_fingerprint,
    )


def _output_digest(execution: GatewayExecution, path: str) -> str:
    for relative, descriptor in zip(
        execution.output_paths, execution.outputs, strict=True
    ):
        if relative == path:
            return descriptor.content_digest
    raise ProductPrototypeError(f"Worker output is missing {path}")


def _output_json(
    repository: LocalArtifactRepository, execution: GatewayExecution, path: str
) -> dict[str, Any]:
    value = json.loads(repository.read_bytes_verified(_output_digest(execution, path)))
    if not isinstance(value, dict):
        raise ProductPrototypeError(f"Worker output {path} is not an object")
    return value


def _attempt_for_year(
    attempts: dict[int | str, dict[str, Any]] | None, year: int
) -> dict[str, Any] | None:
    if attempts is None:
        return None
    return attempts.get(year) or attempts.get(str(year))


def _validate_live_attempt(
    value: dict[str, Any] | None, *, year: int, response_bytes: bytes
) -> dict[str, Any]:
    required = {
        "attemptId",
        "providerCallCount",
        "apiEquivalentUsd",
        "responseDigest",
        "correctionAttempted",
        "correctionSuccessful",
        "model",
        "reasoning",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("providerCallCount") != 1
        or isinstance(value.get("apiEquivalentUsd"), bool)
        or not isinstance(value.get("apiEquivalentUsd"), int | float)
        or not 0 <= float(value["apiEquivalentUsd"]) <= 2.0
        or value.get("responseDigest") != sha256_digest(response_bytes)
        or value.get("correctionAttempted") is not False
        or value.get("correctionSuccessful") is not False
        or value.get("model") != MODEL
        or value.get("reasoning") != "high"
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("attemptId")))
    ):
        raise ProductPrototypeError(
            f"Stored live attempt evidence is invalid for {year}"
        )
    return dict(value)


def _load_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProductPrototypeError(f"Invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise ProductPrototypeError(f"{label} must be an object")
    return value


def _validate_cohort(value: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "cohortId",
        "publicationId",
        "tableFamilyId",
        "generation",
        "acceptanceContract",
        "workbooks",
    }
    if set(value) != required or value.get("schemaVersion") != COHORT_SCHEMA:
        raise ProductPrototypeError("Cohort manifest shape/version is invalid")
    workbooks = value.get("workbooks")
    if not isinstance(workbooks, list) or not 2 <= len(workbooks) <= 12:
        raise ProductPrototypeError("Cohort must bind between two and twelve workbooks")
    years = [item.get("year") for item in workbooks if isinstance(item, dict)]
    if (
        len(years) != len(workbooks)
        or any(not isinstance(year, int) for year in years)
        or years != sorted(set(years))
    ):
        raise ProductPrototypeError("Cohort years must be unique and increasing")
    generation = value.get("generation")
    if not isinstance(generation, dict) or (
        generation.get("provider") != "openai-codex"
        or generation.get("model") != MODEL
        or generation.get("reasoning") != "high"
        or generation.get("promptContract") != PROMPT_CONTRACT
        or generation.get("maximumCalls") != 2 * len(workbooks)
        or generation.get("maximumCostUsd") != 2.0
        or generation.get("correctionPolicy")
        != "one-pre-execution-compilation-correction-only"
    ):
        raise ProductPrototypeError("Generation policy is not the pinned Luna policy")
    for entry in workbooks:
        if not isinstance(entry, dict) or set(entry) not in (
            {
                "year",
                "referenceDate",
                "path",
                "contentDigest",
                "byteLength",
                "sheet",
                "replayResponse",
            },
            {
                "year",
                "referenceDate",
                "path",
                "contentDigest",
                "byteLength",
                "sheet",
                "normalization",
                "replayResponse",
            },
        ):
            raise ProductPrototypeError("Workbook manifest entry is invalid")
        normalization = entry.get("normalization")
        if normalization not in {
            None,
            "trim-pathological-full-width-formatting-merge-v1",
        }:
            raise ProductPrototypeError("Workbook normalization is invalid")
        replay = entry.get("replayResponse")
        if (
            not isinstance(replay, dict)
            or set(replay)
            != {
                "path",
                "contentDigest",
                "byteLength",
                "historicalModel",
                "acceptanceAuthority",
            }
            or not isinstance(replay.get("historicalModel"), str)
            or not replay["historicalModel"]
            or replay.get("acceptanceAuthority") is not False
        ):
            raise ProductPrototypeError("Replay response must be non-authoritative")


def _validate_contract(value: dict[str, Any], cohort: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "contractId",
        "tableFamilyId",
        "measure",
        "requiredDimensions",
        "uniqueKey",
        "expected",
        "aliases",
        "totalEquations",
        "allowedExecutionWarnings",
        "automaticAcceptance",
        "trainingEligibility",
    }
    dimensions = ["jurisdiction", "indigenous_status", "sex", "legal_status"]
    expected = value.get("expected")
    aliases = value.get("aliases")
    equations = value.get("totalEquations")
    if (
        set(value) != required
        or value.get("schemaVersion") != ACCEPTANCE_SCHEMA
        or value.get("tableFamilyId") != cohort.get("tableFamilyId")
        or value.get("automaticAcceptance") is not True
        or value.get("trainingEligibility") is not False
        or value.get("requiredDimensions") != dimensions
        or not isinstance(value.get("uniqueKey"), list)
        or not isinstance(expected, dict)
        or not isinstance(aliases, dict)
        or set(aliases) != set(dimensions)
        or not all(isinstance(aliases[item], dict) for item in dimensions)
        or not isinstance(equations, list)
        or not equations
        or any(
            not isinstance(item, dict)
            or item.get("dimension") not in dimensions
            or item.get("check") != "components-must-not-exceed-total-beyond-rounding"
            or not isinstance(item.get("componentExcessTolerance"), int | float)
            or not isinstance(item.get("maximumUnmodelledResidual"), int | float)
            for item in equations
        )
        or set(expected)
        != {
            "minimumRows",
            "maximumRows",
            "sourceColumns",
            "jurisdictions",
            "indigenousStatuses",
            "sexes",
            "legalStatuses",
        }
    ):
        raise ProductPrototypeError("Acceptance contract is incompatible")


def _assert_declared_bytes(data: bytes, entry: dict[str, Any], label: str) -> None:
    if len(data) != entry.get("byteLength") or sha256_digest(data) != entry.get(
        "contentDigest"
    ):
        raise ProductPrototypeError(f"Digest/length mismatch for {label}")


def _store_source(
    repository: LocalArtifactRepository,
    data: bytes,
    *,
    kind: str,
    schema_version: str,
    source: Path,
    project: Path,
    timestamp: str,
    media_type: str = "application/json",
    classification: str = "product-prototype-input",
) -> ContentDescriptor:
    descriptor = repository.put_bytes(
        data,
        kind=kind,
        schema_version=schema_version,
        media_type=media_type,
    )
    locator = (
        source.relative_to(project).as_posix()
        if _is_within(source, project)
        else source.name
    )
    repository.add_custody(
        CustodyReceipt.create(
            content_digest=descriptor.content_digest,
            storage_uri=f"prototype-source://{locator}",
            observed_at=timestamp,
            actor="tidy.product-prototype/v1",
            source_locator=locator,
            classification=classification,
        )
    )
    return descriptor


def _safe_join(base: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ProductPrototypeError("Manifest path is not a safe relative path")
    target = base.joinpath(*pure.parts).resolve()
    if not _is_within(target, base.resolve()):
        raise ProductPrototypeError("Manifest path escapes its fixture root")
    if target.is_symlink() or not target.is_file():
        raise ProductPrototypeError(f"Manifest input is not a regular file: {relative}")
    return target


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _write_output(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.chmod(0o600)
    temporary.replace(path)


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def _deduplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in issues:
        key = (str(item["code"]), str(item["message"]))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
