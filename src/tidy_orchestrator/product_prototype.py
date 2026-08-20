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
from .ml_gateway import (
    MlGateway,
    MlUnavailable,
    actual_ml_gateway,
)
from .provider_gateway import AuthorizedPiProvider
from .worker import (
    GatewayExecution,
    GatewayInput,
    WorkerDomainFailure,
    WorkerGateway,
)

COHORT_SCHEMA = "tidy.product-prototype-cohort/v1"
ACCEPTANCE_SCHEMA = "tidy.table-family-acceptance/v1"
ACCEPTANCE_SCHEMA_V2 = "tidy.table-family-acceptance/v2"
ACCEPTANCE_SCHEMAS = frozenset({ACCEPTANCE_SCHEMA, ACCEPTANCE_SCHEMA_V2})
BASE_ACCEPTANCE_CHECK_KEYS = frozenset(
    {
        "interpretation",
        "deterministicReplay",
        "nonEmpty",
        "rowBounds",
        "requiredDimensions",
        "rowSelection",
        "codelists",
        "uniqueKeys",
        "sourceCellUniqueness",
        "totalEquations",
        "warningAllowlist",
        "coverage",
    }
)
RUN_SCHEMA = "tidy.product-prototype-run/v1"
MODEL = "openai-codex/gpt-5.6-luna"
PROMPT_CONTRACT = "cell-role-semantic-map-v13-adjacent-year-aware"
DEFAULT_PROTOTYPE_MAX_WARNINGS = 10_000
COMBINATION_COVERAGE_SCHEMA = "tidy.product-prototype-dimension-combinations/v1"
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_DIMENSION_FIELDS = {
    "jurisdiction": "jurisdiction_id",
    "indigenous_status": "indigenous_status_id",
    "sex": "sex_id",
    "legal_status": "legal_status_id",
    "age_group": "age_group_id",
    "country_of_birth": "country_of_birth_id",
    "most_serious_offence": "most_serious_offence_id",
    "most_serious_charge": "most_serious_charge_id",
    "principal_offence": "principal_offence_id",
    "principal_offence_anzsoc_2011": "principal_offence_anzsoc_2011_id",
    "classification_context": "classification_context_id",
    "statistic_basis": "statistic_basis_id",
    "rate_basis": "rate_basis_id",
    "characteristic_group": "characteristic_group_id",
    "characteristic_category": "characteristic_category_id",
    "most_serious_offence_or_charge": "most_serious_offence_or_charge_id",
    "sentence_statistic": "sentence_statistic_id",
    "aggregate_sentence_length": "aggregate_sentence_length_id",
    "fine_amount": "fine_amount_id",
    "observation_period": "observation_period_id",
    "expected_time_to_serve": "expected_time_to_serve_id",
    "prior_imprisonment_status": "prior_imprisonment_status_id",
    "time_on_remand": "time_on_remand_id",
    "security_classification": "security_classification_id",
    "prison_location": "prison_location_id",
    "court_level": "court_level_id",
    "method_of_finalisation": "method_of_finalisation_id",
    "prisoner_statistic": "prisoner_statistic_id",
}
_EXPECTED_CATEGORY_FIELDS = {
    "jurisdiction": "jurisdictions",
    "indigenous_status": "indigenousStatuses",
    "sex": "sexes",
    "legal_status": "legalStatuses",
    "age_group": "ageGroups",
    "country_of_birth": "countriesOfBirth",
    "most_serious_offence": "mostSeriousOffences",
    "most_serious_charge": "mostSeriousCharges",
    "principal_offence": "principalOffences",
    "principal_offence_anzsoc_2011": "principalOffencesAnzsoc2011",
    "classification_context": "classificationContexts",
    "statistic_basis": "statisticBases",
    "rate_basis": "rateBases",
    "characteristic_group": "characteristicGroups",
    "characteristic_category": "characteristicCategories",
    "most_serious_offence_or_charge": "mostSeriousOffencesOrCharges",
    "sentence_statistic": "sentenceStatistics",
    "aggregate_sentence_length": "aggregateSentenceLengths",
    "fine_amount": "fineAmounts",
    "observation_period": "observationPeriods",
    "expected_time_to_serve": "expectedTimesToServe",
    "prior_imprisonment_status": "priorImprisonmentStatuses",
    "time_on_remand": "timesOnRemand",
    "security_classification": "securityClassifications",
    "prison_location": "prisonLocations",
    "court_level": "courtLevels",
    "method_of_finalisation": "methodsOfFinalisation",
    "prisoner_statistic": "prisonerStatistics",
}
_DIMENSION_HEADER_PATTERNS = {
    "jurisdiction": re.compile(r"state|territory|jurisdiction|reporting column", re.I),
    "indigenous_status": re.compile(r"indigenous", re.I),
    "sex": re.compile(r"\bsex\b", re.I),
    "legal_status": re.compile(r"legal status", re.I),
    "age_group": re.compile(r"\bage\b", re.I),
    "country_of_birth": re.compile(r"country.{0,8}birth|birthplace", re.I),
    "most_serious_offence": re.compile(r"most serious offence", re.I),
    "most_serious_charge": re.compile(r"most serious (?:charge|offence)", re.I),
    "principal_offence": re.compile(r"principal offence", re.I),
    "classification_context": re.compile(r"classification context", re.I),
    "statistic_basis": re.compile(r"basis|measure(?:ment)? type|section", re.I),
    "rate_basis": re.compile(r"rate|basis|measure|statistic", re.I),
    "characteristic_group": re.compile(r"characteristic group|statistic", re.I),
    "characteristic_category": re.compile(r"characteristic|member", re.I),
    "most_serious_offence_or_charge": re.compile(
        r"most serious offence or charge", re.I
    ),
    "sentence_statistic": re.compile(r"measure|statistic", re.I),
    "aggregate_sentence_length": re.compile(r"aggregate sentence length", re.I),
    "fine_amount": re.compile(r"fine amount|value of fine", re.I),
    "observation_period": re.compile(r"reference (?:year|period)", re.I),
    "expected_time_to_serve": re.compile(r"expected time to serve", re.I),
    "prior_imprisonment_status": re.compile(r"prior imprisonment", re.I),
    "time_on_remand": re.compile(r"time on remand", re.I),
    "security_classification": re.compile(r"security classification", re.I),
    "prison_location": re.compile(r"prison location", re.I),
    "court_level": re.compile(r"court level", re.I),
    "method_of_finalisation": re.compile(r"method of finalisation", re.I),
    "prisoner_statistic": re.compile(r"prisoner|statistic|measure", re.I),
}


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
        observations, issues, _checks, _selection = _validate_execution(
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
    if ordered != committed_rows or _canonical_csv(ordered, contract) != committed_csv:
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
    ml_gateway: MlGateway | None = None,
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
    acceptance_policy_version = str(contract["schemaVersion"])
    contract_file_digest = sha256_digest(contract_bytes)
    acceptance_policy_digest = (
        contract_file_digest
        if acceptance_policy_version == ACCEPTANCE_SCHEMA_V2
        else sha256_digest(canonical_json_bytes(contract))
    )
    worker_limits = _cohort_worker_limits(cohort)
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
        schema_version=acceptance_policy_version,
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
            ml_gateway=ml_gateway,
            live_attempt=_attempt_for_year(live_attempts, int(entry["year"])),
            dispatch_ordinal=2 * workbook_index + 1,
            worker_limits=worker_limits,
        )
        report = _interpret_accept_one(
            repository=repository,
            gateway=active_gateway,
            contract=contract,
            acceptance_policy_version=acceptance_policy_version,
            acceptance_policy_digest=acceptance_policy_digest,
            prepared=prepared,
            publication_id=(
                "prisoners-in-australia"
                if cohort["publicationId"] == "prisoners-australia"
                else cohort["publicationId"]
            ),
            timestamp=timestamp,
            execution_mutator=acceptance_execution_mutator,
            worker_limits=worker_limits,
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
    combined_csv = _canonical_csv(canonical_rows, contract)
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
    ml_gateway: MlGateway | None,
    live_attempt: dict[str, Any] | None,
    dispatch_ordinal: int,
    worker_limits: dict[str, int],
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
    ml_record: dict[str, Any] | None = None
    if provider is not None:
        prepare, ml_record = _prepare_fresh_live_with_ml(
            repository=repository,
            gateway=gateway,
            ml_gateway=ml_gateway or actual_ml_gateway(project),
            workbook=workbook,
            sheet=str(entry["sheet"]),
            worker_limits=worker_limits,
        )
    else:
        # Replay and checked stored-live responses retain their exact historical
        # one-input derivation and prompt bytes and never construct an ML gateway.
        prepare = gateway.execute(
            operation="prepare-semantic-map-v13",
            inputs=(
                GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),
            ),
            parameters={"sheet": entry["sheet"]},
            limits=worker_limits,
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
            "ml": ml_record,
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


def _prepare_fresh_live_with_ml(
    *,
    repository: LocalArtifactRepository,
    gateway: WorkerGateway,
    ml_gateway: MlGateway,
    workbook: ContentDescriptor,
    sheet: str,
    worker_limits: dict[str, int],
) -> tuple[GatewayExecution, dict[str, Any]]:
    try:
        extracted = gateway.execute(
            operation="extract-ml-features-v1",
            inputs=(
                GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),
            ),
            parameters={"sheet": sheet},
            limits=worker_limits,
        )
    except WorkerDomainFailure as error:
        if error.code != "ML_CELL_LIMIT_EXCEEDED":
            raise
        baseline = gateway.execute(
            operation="prepare-semantic-map-v13",
            inputs=(
                GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),
            ),
            parameters={"sheet": sheet},
            limits=worker_limits,
        )
        return baseline, {
            "schemaVersion": "tidy.live-ml-provenance/v1",
            "status": "availability-fallback",
            "code": error.code,
            "featureBatchDigest": None,
            "workbookDigest": workbook.content_digest,
            "sheet": sheet,
            "providerCallsAdded": 0,
        }
    feature_digest = _output_digest(extracted, "ml-features.json")
    feature_bytes = repository.read_bytes_verified(feature_digest)
    feature_batch = _load_object(feature_bytes, "ML feature batch")
    try:
        hints = ml_gateway.infer(feature_bytes)
    except MlUnavailable as error:
        baseline = gateway.execute(
            operation="prepare-semantic-map-v13",
            inputs=(
                GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),
            ),
            parameters={"sheet": sheet},
            limits=worker_limits,
        )
        return baseline, {
            "schemaVersion": "tidy.live-ml-provenance/v1",
            "status": "availability-fallback",
            "code": error.code,
            "featureBatchDigest": feature_batch.get("featureBatchDigest"),
            "workbookDigest": workbook.content_digest,
            "sheet": sheet,
            "providerCallsAdded": 0,
        }
    hint_bytes = canonical_json_bytes(hints)
    hint_descriptor = repository.put_bytes(
        hint_bytes,
        kind="local-ml-hints",
        schema_version="tidy.ml-hints/v1",
        media_type="application/json",
    )
    prepared = gateway.execute(
        operation="prepare-semantic-map-v13",
        inputs=(
            GatewayInput("workbook", workbook.content_digest, "workbook.xlsx"),
            GatewayInput("ml-features", feature_digest, "ml-features.json"),
            GatewayInput("ml-hints", hint_descriptor.content_digest, "ml-hints.json"),
        ),
        parameters={"sheet": sheet},
        limits=worker_limits,
    )
    return prepared, {
        "schemaVersion": "tidy.live-ml-provenance/v1",
        "status": "hinted",
        "packageId": hints.get("packageId"),
        "packageManifestDigest": hints.get("packageManifestDigest"),
        "sourceCohortSha256": hints.get("sourceCohortSha256"),
        "models": hints.get("models"),
        "featureBatchDigest": hints.get("featureBatchDigest"),
        "hintDigest": hints.get("hintDigest"),
        "workbookDigest": workbook.content_digest,
        "sheet": sheet,
        "providerCallsAdded": 0,
    }


def _interpret_accept_one(
    *,
    repository: LocalArtifactRepository,
    gateway: WorkerGateway,
    contract: dict[str, Any],
    acceptance_policy_version: str,
    acceptance_policy_digest: str,
    prepared: _PreparedWorkbook,
    publication_id: str,
    timestamp: str,
    execution_mutator: Any | None = None,
    worker_limits: dict[str, int] | None = None,
) -> tuple[dict[str, Any], _AcceptedWorkbook | None]:
    entry = prepared.entry
    year = int(entry["year"])
    execution_warning_count: int | None = None
    try:
        effective_limits = worker_limits or {
            "maxWarnings": DEFAULT_PROTOTYPE_MAX_WARNINGS
        }
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
            limits=effective_limits,
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
            limits=effective_limits,
        )
        deterministic = _execution_identity(first) == _execution_identity(second)
        execution = _output_json(repository, first, "execution.json")
        recipe = _output_json(repository, first, "normalized-recipe.json")
        if execution_mutator is not None:
            execution, recipe, deterministic = execution_mutator(
                year, execution, recipe, deterministic
            )
        raw_warnings = execution.get("warnings")
        execution_warning_count = (
            len(raw_warnings) if isinstance(raw_warnings, list) else None
        )
        recipe_digest = _output_digest(first, "normalized-recipe.json")
        execution_digest = _output_digest(first, "execution.json")
        observations, issues, checks, selection = _validate_execution(
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
        selection = {"rawRowCount": 0, "excludedRowCount": 0}
        first = None
        recipe_digest = None
        execution_digest = None

    decision = "prototype_auto_accepted" if not issues else "exception_required"
    subject_id = (
        contract["expectedRecipeDigestsByYear"][str(year)]
        if acceptance_policy_version == ACCEPTANCE_SCHEMA_V2
        else (
            _output_digest(first, "normalized-recipe.json")
            if first is not None
            else prepared.response.content_digest
        )
    )
    decision_payload = {
        "year": year,
        "workbookDigest": prepared.workbook.content_digest,
        "sheet": entry["sheet"],
        "checks": checks,
        "issues": issues,
        "acceptanceSource": "human-authored-table-family-contract",
        "historicalReplayIsAuthority": False,
        "trainingEligibility": False,
    }
    if acceptance_policy_version == ACCEPTANCE_SCHEMA_V2:
        decision_payload.update(
            {
                "acceptancePolicyVersion": acceptance_policy_version,
                "acceptancePolicyDigest": acceptance_policy_digest,
            }
        )
    decision_record = DecisionRecord.create(
        subject_id=subject_id,
        decision_type=decision,
        payload=decision_payload,
        actor="tidy.product-prototype-policy/v1",
        recorded_at=timestamp,
    )
    repository.append_decision(decision_record)
    if first is not None and not issues:
        provenance = {
            "publication_id": publication_id,
            "execution_digest": execution_digest,
            "acceptance_policy_version": acceptance_policy_version,
            "acceptance_policy_digest": acceptance_policy_digest,
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
        "rawObservationCount": selection["rawRowCount"],
        "excludedObservationCount": selection["excludedRowCount"],
        "observationCount": len(observations),
        "checks": checks,
        "issues": issues,
    }
    if "expectedWarningCountsByYear" in contract:
        report["executionWarningCount"] = execution_warning_count
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
    rows, issues, checks, _selection = _validate_execution(
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
) -> tuple[
    tuple[dict[str, Any], ...],
    list[dict[str, Any]],
    dict[str, bool],
    dict[str, int],
]:
    issues: list[dict[str, Any]] = []
    checks: dict[str, bool] = {
        "interpretation": True,
        "deterministicReplay": deterministic,
        "nonEmpty": False,
        "rowBounds": False,
        "requiredDimensions": False,
        "rowSelection": False,
        "codelists": False,
        "uniqueKeys": False,
        "sourceCellUniqueness": False,
        "totalEquations": False,
        "warningAllowlist": False,
        "coverage": False,
    }
    selection = {"rawRowCount": 0, "excludedRowCount": 0}
    if contract.get("schemaVersion") == ACCEPTANCE_SCHEMA_V2:
        expected_recipe_digest = contract["expectedRecipeDigestsByYear"][
            str(entry["year"])
        ]
        if recipe_digest != expected_recipe_digest:
            issues.append(
                _issue(
                    "RECIPE_DIGEST_MISMATCH",
                    "Generated recipe does not match the v2 contract digest pin.",
                )
            )
    if not deterministic:
        issues.append(_issue("NONDETERMINISTIC_REPLAY", "Repeated outputs differ."))
    tables = execution.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        issues.append(_issue("TABLE_COUNT_INVALID", "Expected exactly one table."))
        return (), issues, checks, selection
    table = tables[0]
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list) or not rows:
        issues.append(_issue("EMPTY_OUTPUT", "Execution produced no observations."))
        return (), issues, checks, selection
    selection["rawRowCount"] = len(rows)
    checks["nonEmpty"] = True
    minimum = int(contract["expected"]["minimumRows"])
    maximum = int(contract["expected"]["maximumRows"])
    checks["rowBounds"] = minimum <= len(rows) <= maximum
    if not checks["rowBounds"]:
        issues.append(_issue("ROW_COUNT_OUT_OF_BOUNDS", f"Observed {len(rows)} rows."))

    names = _resolve_output_names(recipe, contract)
    checks["requiredDimensions"] = set(names) == {
        "measure",
        *contract["requiredDimensions"],
    }
    if not checks["requiredDimensions"]:
        issues.append(
            _issue(
                "REQUIRED_DIMENSION_MISSING",
                "Recipe output names do not unambiguously cover all required "
                "dimensions.",
            )
        )
        return (), issues, checks, selection

    canonical: list[dict[str, Any]] = []
    keys: set[tuple[str, ...]] = set()
    source_cells: set[str] = set()
    codelists_ok = True
    keys_ok = True
    source_ok = True
    excluded_codes = {
        dimension: set(codes)
        for dimension, codes in contract.get("excludedDimensionCodes", {}).items()
    }
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
        raw_dimensions: dict[str, Any] = {}
        for dimension in contract["requiredDimensions"]:
            raw = _output_dimension_value(row, names[dimension])
            raw_dimensions[dimension] = raw
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
        if any(
            mapped.get(dimension) in codes
            for dimension, codes in excluded_codes.items()
        ):
            selection["excludedRowCount"] += 1
            continue
        measure = _select_measure(contract, mapped)
        if measure is None:
            codelists_ok = False
            issues.append(
                _issue(
                    "MEASURE_SELECTION_INVALID",
                    f"No unique measure rule accepts mapped dimensions {mapped!r}.",
                )
            )
            continue
        selection_rule = measure.get("selection", {})
        for dimension, code in selection_rule.get("dimensionOverrides", {}).items():
            mapped[dimension] = code
        normalized_value, value_status = _normalize_measure_value(value, measure)
        if value_status is None:
            codelists_ok = False
            issues.append(_issue("VALUE_INVALID", f"Invalid measure value {value!r}."))
            continue
        if value_status != "observed" and measure.get("excludeMissingValues") is True:
            selection["excludedRowCount"] += 1
            continue
        reference_dimension = contract.get("referenceDateDimension")
        reference_date = (
            mapped[reference_dimension]
            if isinstance(reference_dimension, str)
            else entry["referenceDate"]
        )
        observation = {
            "reference_date": reference_date,
            "measure_id": measure["id"],
            "unit_id": measure["unitId"],
            "value": normalized_value,
            "value_status": value_status,
            "source_workbook_digest": entry["contentDigest"],
            "source_sheet": entry["sheet"],
            "source_cell": address,
            "recipe_digest": recipe_digest,
        }
        if contract.get("preservePublicationVintage") is True:
            observation["publication_vintage_date"] = entry["referenceDate"]
        if contract.get("preserveRawValueText") is True:
            observation["raw_value"] = value
        for dimension in contract["requiredDimensions"]:
            observation[_DIMENSION_FIELDS[dimension]] = mapped[dimension]
            observation[f"raw_{dimension}"] = raw_dimensions[dimension]
        key = tuple(str(observation[field]) for field in contract["uniqueKey"])
        if key in keys:
            keys_ok = False
            issues.append(_issue("DUPLICATE_OBSERVATION_KEY", repr(key)))
        keys.add(key)
        canonical.append(observation)
    expected = contract["expected"]
    minimum_excluded = int(expected.get("minimumExcludedRows", 0))
    maximum_excluded = int(expected.get("maximumExcludedRows", 0))
    checks["rowSelection"] = (
        minimum_excluded <= selection["excludedRowCount"] <= maximum_excluded
    )
    if not checks["rowSelection"]:
        issues.append(
            _issue(
                "ROW_SELECTION_OUT_OF_BOUNDS",
                f"Excluded {selection['excludedRowCount']} auxiliary rows.",
            )
        )
    coverage_issues = _validate_expected_coverage(canonical, contract, entry)
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
    raw_warnings = execution.get("warnings", [])
    warnings = raw_warnings if isinstance(raw_warnings, list) else []
    warning_issues = (
        _validate_warning_rules(
            warnings,
            allowed_rules if isinstance(allowed_rules, list) else [],
            rows,
            names,
            contract,
            year=int(entry["year"]),
        )
        if isinstance(raw_warnings, list)
        else [
            _issue(
                "MALFORMED_EXECUTION_WARNINGS",
                "Execution warnings must be a list.",
            )
        ]
    )
    checks["warningAllowlist"] = not warning_issues
    issues.extend(warning_issues)
    expected_warning_counts = contract.get("expectedWarningCountsByYear")
    if isinstance(expected_warning_counts, dict):
        expected_warning_count = expected_warning_counts.get(str(entry["year"]))
        warning_count_matches = (
            isinstance(expected_warning_count, int)
            and not isinstance(expected_warning_count, bool)
            and len(warnings) == expected_warning_count
        )
        checks["warningCount"] = warning_count_matches
        if not warning_count_matches:
            issues.append(
                _issue(
                    "WARNING_COUNT_MISMATCH",
                    f"Expected {expected_warning_count} execution warnings; "
                    f"got {len(warnings)}.",
                )
            )
    return tuple(canonical), _deduplicate_issues(issues), checks, selection


def _resolve_output_names(
    recipe: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    try:
        table = recipe["tables"][0]
        headers = [str(item["name"]) for item in table["headers"]]
        value = str(table["values"]["name"])
    except (KeyError, IndexError, TypeError):
        return {}
    resolved: dict[str, Any] = {"measure": value}
    configured = contract.get("dimensionHeaders", {})
    for dimension in contract["requiredDimensions"]:
        patterns = configured.get(dimension)
        if patterns is not None:
            matches: list[str] = []
            for raw_pattern in patterns:
                pattern = re.compile(raw_pattern, re.I)
                for name in headers:
                    if pattern.fullmatch(name) and name not in matches:
                        matches.append(name)
            if not matches:
                return {}
            resolved[dimension] = matches[0] if len(matches) == 1 else tuple(matches)
            continue
        pattern = _DIMENSION_HEADER_PATTERNS.get(dimension)
        if pattern is None:
            return {}
        matches = [name for name in headers if pattern.search(name)]
        if len(matches) != 1:
            return {}
        resolved[dimension] = matches[0]
    return resolved


def _output_dimension_value(row: dict[str, Any], names: Any) -> Any:
    candidates = names if isinstance(names, tuple) else (names,)
    for name in candidates:
        value = row.get(name)
        if isinstance(value, str) and value.strip():
            return value
        if value is not None:
            return value
    return None


def _contract_measures(contract: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    single = contract.get("measure")
    if isinstance(single, dict):
        return (single,)
    measures = contract.get("measures")
    if not isinstance(measures, list):
        return ()
    return tuple(item for item in measures if isinstance(item, dict))


def _selection_conditions(selection: dict[str, Any]) -> dict[str, list[str]]:
    configured = selection.get("conditions")
    if isinstance(configured, dict):
        return configured
    dimension = selection.get("dimension")
    codes = selection.get("codes")
    return (
        {dimension: codes}
        if isinstance(dimension, str) and isinstance(codes, list)
        else {}
    )


def _selection_is_valid(
    selection: Any,
    dimensions: list[str],
    alias_codes: dict[str, set[str]],
) -> bool:
    if not isinstance(selection, dict):
        return False
    keys = set(selection)
    if keys not in (
        {"dimension", "codes", "dimensionOverrides"},
        {"conditions", "dimensionOverrides"},
    ):
        return False
    conditions = _selection_conditions(selection)
    overrides = selection.get("dimensionOverrides")
    return (
        bool(conditions)
        and set(conditions) <= set(dimensions)
        and all(
            _valid_string_list(codes) and set(codes) <= alias_codes[dimension]
            for dimension, codes in conditions.items()
        )
        and isinstance(overrides, dict)
        and set(overrides) <= set(dimensions)
        and all(
            isinstance(code, str) and code in alias_codes[dimension]
            for dimension, code in overrides.items()
        )
    )


def _selections_overlap(
    left: dict[str, Any],
    right: dict[str, Any],
    alias_codes: dict[str, set[str]],
) -> bool:
    left_conditions = _selection_conditions(left)
    right_conditions = _selection_conditions(right)
    dimensions = set(left_conditions) | set(right_conditions)
    return all(
        set(left_conditions.get(dimension, alias_codes[dimension]))
        & set(right_conditions.get(dimension, alias_codes[dimension]))
        for dimension in dimensions
    )


def _select_measure(
    contract: dict[str, Any], mapped: dict[str, str]
) -> dict[str, Any] | None:
    measures = _contract_measures(contract)
    if len(measures) == 1 and "selection" not in measures[0]:
        return measures[0]
    matches = []
    for measure in measures:
        selection = measure.get("selection")
        if not isinstance(selection, dict):
            continue
        conditions = _selection_conditions(selection)
        if conditions and all(
            mapped.get(dimension) in codes for dimension, codes in conditions.items()
        ):
            matches.append(measure)
    return matches[0] if len(matches) == 1 else None


def _normalize_measure_value(
    value: Any, measure: dict[str, Any]
) -> tuple[int | float | None, str | None]:
    if (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and value >= float(measure["minimum"])
    ):
        return value, "observed"
    if isinstance(value, str):
        normalized = " ".join(value.strip().split())
        status = measure.get("missingValues", {}).get(normalized)
        if isinstance(status, str):
            return None, status
    return None, None


def _map_alias(contract: dict[str, Any], dimension: str, raw: Any) -> str | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        raw = str(raw)
    elif isinstance(raw, float) and raw.is_integer():
        raw = str(int(raw))
    if not isinstance(raw, str):
        return None
    normalized = " ".join(raw.strip().split())
    aliases = contract["aliases"][dimension]
    exact = aliases.get(normalized)
    if exact is not None or contract.get("strictAliasMatching") is True:
        return exact
    without_footnotes = re.sub(r"(?:\s*\([a-z]\))+$", "", normalized, flags=re.I)
    return aliases.get(without_footnotes)


def _expected_categories(
    contract: dict[str, Any], dimension: str, year: int
) -> set[str]:
    expected = contract["expected"]
    field = _EXPECTED_CATEGORY_FIELDS[dimension]
    by_year = expected.get(f"{field}ByYear")
    values = by_year[str(year)] if isinstance(by_year, dict) else expected[field]
    return set(values)


def _measure_expected_categories(
    measure: dict[str, Any], dimension: str, year: int, fallback: set[str]
) -> set[str]:
    by_year = measure.get("expectedDimensionsByYear", {})
    year_value = by_year.get(str(year), {}) if isinstance(by_year, dict) else {}
    if isinstance(year_value, dict) and dimension in year_value:
        return set(year_value[dimension])
    configured = measure.get("expectedDimensions", {})
    if isinstance(configured, dict) and dimension in configured:
        return set(configured[dimension])
    return fallback


def _validate_expected_coverage(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    entry: dict[str, Any],
) -> list[dict[str, Any]]:
    year = int(entry["year"])
    required = {
        dimension: _expected_categories(contract, dimension, year)
        for dimension in contract["requiredDimensions"]
    }
    issues: list[dict[str, Any]] = []
    for dimension, wanted in required.items():
        field = _DIMENSION_FIELDS[dimension]
        observed = {str(row[field]) for row in rows}
        if observed != wanted:
            issues.append(
                _issue(
                    "EXPECTED_CATEGORY_COVERAGE_MISSING",
                    f"{field}: missing={sorted(wanted - observed)!r}; "
                    f"unexpected={sorted(observed - wanted)!r}",
                )
            )
    measures = _contract_measures(contract)
    wanted_measure_ids = {
        measure["id"]
        for measure in measures
        if str(year) in measure.get("applicableYears", [str(year)])
    }
    observed_measure_ids = {str(row["measure_id"]) for row in rows}
    if observed_measure_ids != wanted_measure_ids:
        issues.append(
            _issue(
                "EXPECTED_MEASURE_COVERAGE_MISSING",
                "measure_id: "
                f"missing={sorted(wanted_measure_ids - observed_measure_ids)!r}; "
                f"unexpected={sorted(observed_measure_ids - wanted_measure_ids)!r}",
            )
        )
    for measure in measures:
        measure_rows = [row for row in rows if row["measure_id"] == measure["id"]]
        if str(year) not in measure.get("applicableYears", [str(year)]):
            if measure_rows:
                issues.append(
                    _issue(
                        "UNEXPECTED_MEASURE_FOR_YEAR",
                        f"{measure['id']} is not applicable in {year}.",
                    )
                )
            continue
        expected_count = 1
        for dimension, fallback in required.items():
            wanted = _measure_expected_categories(measure, dimension, year, fallback)
            field = _DIMENSION_FIELDS[dimension]
            observed = {str(row[field]) for row in measure_rows}
            if observed != wanted:
                issues.append(
                    _issue(
                        "EXPECTED_MEASURE_CATEGORY_COVERAGE_MISSING",
                        f"{measure['id']} {field}: "
                        f"missing={sorted(wanted - observed)!r}; "
                        f"unexpected={sorted(observed - wanted)!r}",
                    )
                )
            expected_count *= len(wanted)
        expected_count = int(
            measure.get("expectedCombinationCountsByYear", {}).get(
                str(year), expected_count
            )
        )
        if len(measure_rows) != expected_count:
            issues.append(
                _issue(
                    "EXPECTED_COMBINATION_COVERAGE_MISSING",
                    f"{measure['id']}: expected {expected_count} category "
                    f"combinations; got {len(measure_rows)}.",
                )
            )
        expected_digest = measure.get("expectedCombinationDigestsByYear", {}).get(
            str(year)
        )
        if isinstance(expected_digest, str):
            combinations = sorted(
                [str(row[_DIMENSION_FIELDS[dimension]]) for dimension in required]
                for row in measure_rows
            )
            actual_digest = domain_digest(
                COMBINATION_COVERAGE_SCHEMA,
                {
                    "dimensions": list(required),
                    "combinations": combinations,
                },
            )
            if actual_digest != expected_digest:
                issues.append(
                    _issue(
                        "EXPECTED_COMBINATION_SET_MISMATCH",
                        f"{measure['id']}: reviewed combinations differ.",
                    )
                )
    return issues


def _validate_warning_rules(
    warnings: list[Any],
    rules: list[Any],
    rows: list[Any],
    names: dict[str, Any],
    contract: dict[str, Any],
    *,
    year: int,
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
        warning_header = warning.get("header")
        matching = [
            rule
            for rule in rules
            if isinstance(warning_header, str)
            and warning_header
            and isinstance(rule, dict)
            and rule.get("code") == warning.get("code")
            and isinstance(rule.get("dimension"), str)
            and (
                names.get(rule["dimension"]) == warning_header
                or (
                    isinstance(names.get(rule["dimension"]), tuple)
                    and warning_header in names[rule["dimension"]]
                )
            )
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
        raw = (
            _output_dimension_value(row, names.get(dimension, ""))
            if isinstance(row, dict)
            else None
        )
        canonical = _map_alias(contract, dimension, raw)
        if canonical is None:
            issues.append(
                _issue(
                    "AMBIGUOUS_WARNING_OUTPUT_UNRESOLVED",
                    f"{dimension} output {raw!r} is not canonical at "
                    f"{warning.get('address')!r}.",
                )
            )
            continue
        # Canonical output equivalence means the deterministic execution's selected
        # output resolves to a pinned code from this reviewed exact header source. It
        # does not equate competing candidate values: AMBIGUOUS_HEADER records their
        # difference, while the workbook and replay bytes are digest-bound upstream.
        expected_sources_by_year = rule.get("expectedHeaderSourcesByYear")
        if expected_sources_by_year is not None:
            configured = (
                expected_sources_by_year.get(str(year), {})
                if isinstance(expected_sources_by_year, dict)
                else {}
            )
            wanted = configured.get(canonical) if isinstance(configured, dict) else None
            header_name = names.get(dimension)
            source = (
                row.get(f"{header_name}_source")
                if isinstance(row, dict) and isinstance(header_name, str)
                else None
            )
            if (
                not isinstance(wanted, list)
                or not wanted
                or any(not isinstance(item, str) or not item for item in wanted)
                or source not in wanted
            ):
                issues.append(
                    _issue(
                        "AMBIGUOUS_WARNING_HEADER_SOURCE_MISMATCH",
                        f"{dimension} output {canonical!r} used header source "
                        f"{source!r} at {warning.get('address')!r}.",
                    )
                )
    return issues


def _validate_totals(
    rows: list[dict[str, Any]], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    field_by_dimension = {
        dimension: _DIMENSION_FIELDS[dimension]
        for dimension in contract["requiredDimensions"]
    }
    dimensions = tuple(contract["requiredDimensions"])
    all_measure_ids = {measure["id"] for measure in _contract_measures(contract)}
    for equation in contract["totalEquations"]:
        dimension = equation["dimension"]
        field = field_by_dimension[dimension]
        others = [
            *[field_by_dimension[item] for item in dimensions if item != dimension],
            "measure_id",
        ]
        measure_ids = set(equation.get("measureIds", all_measure_ids))
        groups: dict[tuple[Any, ...], dict[str, float]] = {}
        for row in rows:
            if row["measure_id"] not in measure_ids or not isinstance(
                row["value"], int | float
            ):
                continue
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
            "rawRowCount": item.get("rawObservationCount", item["observationCount"]),
            "excludedRowCount": item.get("excludedObservationCount", 0),
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
        "excludedDimensionCodes": contract.get("excludedDimensionCodes", {}),
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
                "ROW_SELECTION_OUT_OF_BOUNDS",
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


def _canonical_csv(rows: list[dict[str, Any]], contract: dict[str, Any]) -> bytes:
    dimensions = list(contract["requiredDimensions"])
    fields = [
        *(
            ["publication_vintage_date"]
            if contract.get("preservePublicationVintage") is True
            else []
        ),
        "reference_date",
        *[_DIMENSION_FIELDS[dimension] for dimension in dimensions],
        "measure_id",
        "unit_id",
        "value",
        "value_status",
        *(["raw_value"] if contract.get("preserveRawValueText") is True else []),
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
        *[f"raw_{dimension}" for dimension in dimensions],
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    # Physical worksheet names are source identities and may legitimately end in
    # spaces (for example the official Criminal Courts `Table 80 ` worksheet).
    # Keep that field byte-faithful while retaining the established CSV text
    # normalization for non-identity fields.
    writer.writerows(
        {
            key: (
                value.rstrip()
                if isinstance(value, str) and key != "source_sheet"
                else value
            )
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
    if (
        not required <= set(value) <= required | {"workerLimits"}
        or value.get("schemaVersion") != COHORT_SCHEMA
    ):
        raise ProductPrototypeError("Cohort manifest shape/version is invalid")
    _cohort_worker_limits(value)
    workbooks = value.get("workbooks")
    if not isinstance(workbooks, list) or not 1 <= len(workbooks) <= 12:
        raise ProductPrototypeError("Cohort must bind between one and twelve workbooks")
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
            "trim-pathological-styled-blank-cells-v1",
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


def _cohort_worker_limits(cohort: dict[str, Any]) -> dict[str, int]:
    raw = cohort.get("workerLimits", {})
    if not isinstance(raw, dict) or set(raw) - {"maxWarnings"}:
        raise ProductPrototypeError("Cohort worker limits are invalid")
    maximum_warnings = raw.get("maxWarnings", DEFAULT_PROTOTYPE_MAX_WARNINGS)
    if (
        isinstance(maximum_warnings, bool)
        or not isinstance(maximum_warnings, int)
        or not 1 <= maximum_warnings <= 100_000
    ):
        raise ProductPrototypeError("Cohort maxWarnings is outside protocol bounds")
    return {"maxWarnings": maximum_warnings}


def _valid_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value))
    )


def _validate_contract(value: dict[str, Any], cohort: dict[str, Any]) -> None:
    required = {
        "schemaVersion",
        "contractId",
        "tableFamilyId",
        "requiredDimensions",
        "uniqueKey",
        "expected",
        "aliases",
        "totalEquations",
        "allowedExecutionWarnings",
        "automaticAcceptance",
        "trainingEligibility",
    }
    optional = {
        "measure",
        "measures",
        "expectedWarningCountsByYear",
        "expectedRecipeDigestsByYear",
        "excludedDimensionCodes",
        "dimensionHeaders",
        "referenceDateDimension",
        "preservePublicationVintage",
        "preserveRawValueText",
        "strictAliasMatching",
        "totalValidation",
    }
    dimensions = value.get("requiredDimensions")
    expected = value.get("expected")
    aliases = value.get("aliases")
    equations = value.get("totalEquations")
    exclusions = value.get("excludedDimensionCodes", {})
    headers = value.get("dimensionHeaders", {})
    reference_dimension = value.get("referenceDateDimension")
    preserve_vintage = value.get("preservePublicationVintage")
    total_validation = value.get("totalValidation", "equations")
    preserve_vintage_enabled = preserve_vintage is True
    reference_dimension_enabled = (
        isinstance(reference_dimension, str)
        and isinstance(dimensions, list)
        and reference_dimension in dimensions
    )
    unique_dimensions = (
        [item for item in dimensions if item != reference_dimension]
        if reference_dimension_enabled
        else dimensions
    )
    expected_unique_key = (
        [
            *(["publication_vintage_date"] if preserve_vintage_enabled else []),
            "reference_date",
            *[_DIMENSION_FIELDS[item] for item in unique_dimensions],
            "measure_id",
        ]
        if isinstance(unique_dimensions, list)
        and all(item in _DIMENSION_FIELDS for item in unique_dimensions)
        else None
    )
    keys = set(value)
    if (
        not required <= keys <= required | optional
        or ("measure" in value) == ("measures" in value)
        or value.get("schemaVersion") not in ACCEPTANCE_SCHEMAS
        or value.get("tableFamilyId") != cohort.get("tableFamilyId")
        or value.get("automaticAcceptance") is not True
        or value.get("trainingEligibility") is not False
        or (
            "preserveRawValueText" in value
            and value.get("preserveRawValueText") is not True
        )
        or (
            "strictAliasMatching" in value
            and value.get("strictAliasMatching") is not True
        )
        or total_validation not in {"equations", "not_applicable"}
        or not isinstance(dimensions, list)
        or not dimensions
        or len(dimensions) != len(set(dimensions))
        or any(item not in _DIMENSION_FIELDS for item in dimensions)
        or ("preservePublicationVintage" in value and not preserve_vintage_enabled)
        or (
            "referenceDateDimension" in value
            and (not preserve_vintage_enabled or not reference_dimension_enabled)
        )
        or value.get("uniqueKey") != expected_unique_key
        or not isinstance(expected, dict)
        or not isinstance(aliases, dict)
        or set(aliases) != set(dimensions)
        or not all(
            isinstance(aliases[item], dict)
            and aliases[item]
            and all(
                isinstance(raw, str) and raw and isinstance(code, str) and code
                for raw, code in aliases[item].items()
            )
            for item in dimensions
        )
        or not isinstance(headers, dict)
        or not set(headers) <= set(dimensions)
        or any(not _valid_string_list(patterns) for patterns in headers.values())
        or not isinstance(exclusions, dict)
        or not set(exclusions) <= set(dimensions)
        or any(
            not _valid_string_list(codes)
            or not set(codes) <= set(aliases[dimension].values())
            for dimension, codes in exclusions.items()
        )
        or not isinstance(value.get("allowedExecutionWarnings"), list)
    ):
        raise ProductPrototypeError("Acceptance contract is incompatible")
    if reference_dimension_enabled and any(
        re.fullmatch(r"(?:19|20)[0-9]{2}-[0-9]{2}-[0-9]{2}", code) is None
        for code in aliases[reference_dimension].values()
    ):
        raise ProductPrototypeError("Reference-date dimension codes are invalid")
    try:
        for patterns in headers.values():
            for pattern in patterns:
                re.compile(pattern, re.I)
    except re.error as error:
        raise ProductPrototypeError(
            "Acceptance contract has an invalid dimension-header pattern"
        ) from error

    measures = _contract_measures(value)
    configured_measures = value.get("measures")
    if "measures" in value and (
        not isinstance(configured_measures, list)
        or len(measures) != len(configured_measures)
    ):
        raise ProductPrototypeError("Acceptance contract measures are invalid")
    allowed_measure_keys = {
        "id",
        "unitId",
        "numeric",
        "minimum",
        "selection",
        "expectedDimensions",
        "expectedDimensionsByYear",
        "expectedCombinationCountsByYear",
        "expectedCombinationDigestsByYear",
        "applicableYears",
        "missingValues",
        "excludeMissingValues",
    }
    years = {str(item["year"]) for item in cohort["workbooks"]}
    recipe_digests = value.get("expectedRecipeDigestsByYear")
    if (value.get("schemaVersion") == ACCEPTANCE_SCHEMA_V2) != (
        recipe_digests is not None
    ) or (
        recipe_digests is not None
        and (
            not isinstance(recipe_digests, dict)
            or set(recipe_digests) != years
            or any(
                not isinstance(year, str)
                or not isinstance(digest, str)
                or _SHA256_DIGEST.fullmatch(digest) is None
                for year, digest in recipe_digests.items()
            )
        )
    ):
        raise ProductPrototypeError("Acceptance recipe digest pins are invalid")
    warning_counts = value.get("expectedWarningCountsByYear")
    if warning_counts is not None and (
        not isinstance(warning_counts, dict)
        or set(warning_counts) != years
        or any(
            not isinstance(year, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for year, count in warning_counts.items()
        )
    ):
        raise ProductPrototypeError("Acceptance warning counts are invalid")
    alias_codes = {
        dimension: set(aliases[dimension].values()) for dimension in dimensions
    }
    raw_measure_ids = [measure.get("id") for measure in measures]
    if (
        not measures
        or not all(isinstance(item, str) for item in raw_measure_ids)
        or len(set(raw_measure_ids)) != len(measures)
        or any(
            not isinstance(measure, dict)
            or not {"id", "unitId", "numeric", "minimum"}
            <= set(measure)
            <= allowed_measure_keys
            or not isinstance(measure.get("id"), str)
            or not measure["id"]
            or not isinstance(measure.get("unitId"), str)
            or not measure["unitId"]
            or measure.get("numeric") is not True
            or (
                "excludeMissingValues" in measure
                and measure.get("excludeMissingValues") is not True
            )
            or isinstance(measure.get("minimum"), bool)
            or not isinstance(measure.get("minimum"), int | float)
            or measure["minimum"] < 0
            for measure in measures
        )
    ):
        raise ProductPrototypeError("Acceptance contract measures are invalid")
    allowed_missing_statuses = {"not_applicable", "not_available", "suppressed"}
    for measure in measures:
        missing = measure.get("missingValues", {})
        expected_dimensions = measure.get("expectedDimensions", {})
        expected_by_year = measure.get("expectedDimensionsByYear", {})
        combination_counts = measure.get("expectedCombinationCountsByYear", {})
        combination_digests = measure.get("expectedCombinationDigestsByYear", {})
        applicable_years = measure.get("applicableYears", sorted(years))
        if (
            not isinstance(missing, dict)
            or any(
                not isinstance(raw, str)
                or not raw
                or status not in allowed_missing_statuses
                for raw, status in missing.items()
            )
            or not isinstance(expected_dimensions, dict)
            or not set(expected_dimensions) <= set(dimensions)
            or any(
                not _valid_string_list(codes)
                or not set(codes) <= alias_codes[dimension]
                for dimension, codes in expected_dimensions.items()
            )
            or not isinstance(expected_by_year, dict)
            or not set(expected_by_year) <= years
            or not _valid_string_list(applicable_years)
            or not set(applicable_years) <= years
            or not isinstance(combination_counts, dict)
            or not set(combination_counts) <= set(applicable_years)
            or any(
                isinstance(count, bool) or not isinstance(count, int) or count <= 0
                for count in combination_counts.values()
            )
            or not isinstance(combination_digests, dict)
            or set(combination_digests) != set(combination_counts)
            or any(
                re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
                for digest in combination_digests.values()
                if isinstance(digest, str)
            )
            or any(
                not isinstance(digest, str) for digest in combination_digests.values()
            )
        ):
            raise ProductPrototypeError("Acceptance measure coverage is invalid")
        for year, configured in expected_by_year.items():
            if (
                year not in years
                or not isinstance(configured, dict)
                or not set(configured) <= set(dimensions)
                or any(
                    not _valid_string_list(codes)
                    or not set(codes) <= alias_codes[dimension]
                    for dimension, codes in configured.items()
                )
            ):
                raise ProductPrototypeError("Acceptance measure coverage is invalid")

    if len(measures) > 1:
        selections = [measure.get("selection") for measure in measures]
        if any(
            not _selection_is_valid(selection, dimensions, alias_codes)
            for selection in selections
        ):
            raise ProductPrototypeError("Acceptance measure selection is invalid")
        if any(
            _selections_overlap(left, right, alias_codes)
            for index, left in enumerate(selections)
            for right in selections[index + 1 :]
        ):
            raise ProductPrototypeError("Acceptance measure selection overlaps")
    elif "selection" in measures[0]:
        raise ProductPrototypeError("A single measure must not need selection")

    measure_ids = {measure["id"] for measure in measures}
    if (
        not isinstance(equations, list)
        or (not equations and total_validation != "not_applicable")
        or (equations and total_validation != "equations")
        or any(
            not isinstance(item, dict)
            or not {
                "dimension",
                "totalCode",
                "componentCodes",
                "check",
                "componentExcessTolerance",
                "maximumUnmodelledResidual",
            }
            <= set(item)
            <= {
                "dimension",
                "totalCode",
                "componentCodes",
                "check",
                "componentExcessTolerance",
                "maximumUnmodelledResidual",
                "measureIds",
            }
            or item.get("dimension") not in dimensions
            or item.get("check") != "components-must-not-exceed-total-beyond-rounding"
            or item.get("totalCode")
            not in alias_codes.get(item.get("dimension"), set())
            or not _valid_string_list(item.get("componentCodes"))
            or not set(item["componentCodes"])
            <= alias_codes.get(item["dimension"], set())
            or isinstance(item.get("componentExcessTolerance"), bool)
            or not isinstance(item.get("componentExcessTolerance"), int | float)
            or isinstance(item.get("maximumUnmodelledResidual"), bool)
            or not isinstance(item.get("maximumUnmodelledResidual"), int | float)
            or (
                "measureIds" in item
                and (
                    not _valid_string_list(item["measureIds"])
                    or not set(item["measureIds"]) <= measure_ids
                )
            )
            for item in equations
        )
    ):
        raise ProductPrototypeError("Acceptance total equations are invalid")

    expected_keys = {"minimumRows", "maximumRows", "sourceColumns"}
    for dimension in dimensions:
        field = _EXPECTED_CATEGORY_FIELDS[dimension]
        present = [key for key in (field, f"{field}ByYear") if key in expected]
        if len(present) != 1:
            raise ProductPrototypeError("Acceptance category coverage is invalid")
        expected_keys.add(present[0])
        configured = expected[present[0]]
        if present[0].endswith("ByYear"):
            if (
                not isinstance(configured, dict)
                or set(configured) != years
                or any(
                    not _valid_string_list(codes)
                    or not set(codes) <= alias_codes[dimension]
                    for codes in configured.values()
                )
            ):
                raise ProductPrototypeError("Acceptance category coverage is invalid")
        elif (
            not _valid_string_list(configured)
            or not set(configured) <= alias_codes[dimension]
        ):
            raise ProductPrototypeError("Acceptance category coverage is invalid")
    has_excluded_rows = bool(exclusions) or any(
        measure.get("excludeMissingValues") is True for measure in measures
    )
    if has_excluded_rows:
        expected_keys |= {"minimumExcludedRows", "maximumExcludedRows"}
    source_columns = expected.get("sourceColumns")
    if (
        set(expected) != expected_keys
        or isinstance(expected.get("minimumRows"), bool)
        or not isinstance(expected.get("minimumRows"), int)
        or isinstance(expected.get("maximumRows"), bool)
        or not isinstance(expected.get("maximumRows"), int)
        or not 0 < expected["minimumRows"] <= expected["maximumRows"]
        or not isinstance(source_columns, dict)
        or set(source_columns) != {"minimum", "maximum"}
        or any(
            isinstance(source_columns.get(key), bool)
            or not isinstance(source_columns.get(key), int)
            for key in ("minimum", "maximum")
        )
        or not 1 <= source_columns["minimum"] <= source_columns["maximum"]
        or (
            has_excluded_rows
            and (
                isinstance(expected.get("minimumExcludedRows"), bool)
                or not isinstance(expected.get("minimumExcludedRows"), int)
                or isinstance(expected.get("maximumExcludedRows"), bool)
                or not isinstance(expected.get("maximumExcludedRows"), int)
                or not 0
                <= expected["minimumExcludedRows"]
                <= expected["maximumExcludedRows"]
            )
        )
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
