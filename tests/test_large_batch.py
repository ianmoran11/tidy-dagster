from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

import tidy_orchestrator.large_batch as large_batch_module
from tidy_orchestrator.artifacts import domain_digest
from tidy_orchestrator.large_batch import (
    LargeBatchError,
    load_large_batch_registry,
    verify_batch_normalization,
    verify_large_batch_evidence,
)
from tidy_orchestrator.large_batch_cli import run_batch
from tidy_orchestrator.product_prototype import (
    RUN_SCHEMA,
    ProductPrototypeError,
    _validate_cohort,
    _validate_contract,
    _validate_expected_coverage,
)

PROJECT = Path(__file__).parents[1]


@pytest.fixture(scope="module", autouse=True)
def ensure_domain_worker_is_built() -> None:
    worker = PROJECT / "dist/tidy-domain-worker.cjs"
    if not worker.is_file():
        subprocess.run(
            ["npm", "run", "build"],
            cwd=PROJECT,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )


def test_large_batch_registry_and_all_evidence_close() -> None:
    registry = load_large_batch_registry(PROJECT)
    assert registry.batch_id == "justice-two-hundred-seventy-seven-worksheets-v1"
    assert registry.worksheet_count == 277
    assert registry.provider_calls == 0
    assert len(registry.entries) == 89
    normalization = verify_batch_normalization(PROJECT, registry)
    assert len(normalization["entries"]) == 33
    assert "normalization" not in normalization
    assert Counter(entry["normalization"] for entry in normalization["entries"]) == {
        "trim-pathological-styled-blank-cells-v1": 32,
        "trim-pathological-full-width-formatting-merge-v1": 1,
    }
    assert normalization["inRangeValuesChanged"] is True
    removed_cells = [
        cell
        for entry in normalization["entries"]
        if entry["correction"] is not None
        for cell in entry["correction"]["removedCells"]
    ]
    assert sum(cell["insideRetainedRange"] for cell in removed_cells) == 2
    assert sum(not cell["insideRetainedRange"] for cell in removed_cells) == 1
    manifests = [
        verify_large_batch_evidence(PROJECT, spec) for spec in registry.entries
    ]
    assert sum(item["acceptedWorkbookCount"] for item in manifests) == 277
    assert sum(item["exceptionWorkbookCount"] for item in manifests) == 0
    assert sum(item["canonicalObservationCount"] for item in manifests) == 248688
    assert sum(item["providerCalls"] for item in manifests) == 0
    offender_manifests = [
        item for item in manifests if item["familyId"].startswith("offenders-table-")
    ]
    assert len(offender_manifests) == 5
    assert all(
        item["manualReplayYears"] == [2021, 2022, 2023, 2024]
        and item["publicationVintagePreserved"] is True
        for item in offender_manifests
    )


def test_large_batch_cohorts_and_contracts_validate() -> None:
    registry = load_large_batch_registry(PROJECT)
    cohort_schema = json.loads(
        (PROJECT / "contracts/product-prototype/v1/cohort.schema.json").read_text()
    )
    validator = jsonschema.Draft202012Validator(
        cohort_schema,
        format_checker=jsonschema.FormatChecker(),
    )
    for spec in registry.entries:
        cohort_path = PROJECT / spec.cohort_path
        cohort = json.loads(cohort_path.read_text())
        contract = json.loads(
            (cohort_path.parent / cohort["acceptanceContract"]).read_text()
        )
        validator.validate(cohort)
        _validate_cohort(cohort)
        _validate_contract(contract, cohort)
        assert [item["year"] for item in cohort["workbooks"]] == list(
            spec.expected_years
        )
        assert [item["sheet"] for item in cohort["workbooks"]]
        assert all(
            item["replayResponse"]["acceptanceAuthority"] is False
            for item in cohort["workbooks"]
        )


def _write_registry(tmp_path: Path, value: dict[str, object]) -> None:
    registry_path = tmp_path / "fixtures/product-prototype/large-batch-assets-v1.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(json.dumps(value))


def _registry_value() -> dict[str, object]:
    return json.loads(
        (PROJECT / "fixtures/product-prototype/large-batch-assets-v1.json").read_text()
    )


def test_registry_pins_exact_exclusions_for_every_year() -> None:
    registry = load_large_batch_registry(PROJECT)
    for spec in registry.entries:
        assert set(spec.expected_excluded_observation_counts_by_year) == set(
            spec.expected_years
        )
        expected = (
            {2021: 0, 2022: 36, 2023: 37, 2024: 37, 2025: 38}
            if spec.family_id == "national-selected-characteristics-by-offence-charge"
            else {year: 0 for year in spec.expected_years}
        )
        assert spec.expected_excluded_observation_counts_by_year == expected
        assert sum(expected.values()) == spec.expected_excluded_observation_count


def test_registry_rejects_output_path_escape(tmp_path: Path) -> None:
    value = _registry_value()
    value["entries"][0]["outputDirectory"] = "../escape"
    _write_registry(tmp_path, value)
    with pytest.raises(LargeBatchError, match="entry is invalid"):
        load_large_batch_registry(tmp_path)


def test_registry_rejects_uncustodied_family_separator(tmp_path: Path) -> None:
    value = _registry_value()
    value["entries"][0]["familyId"] = "invalid---family"
    _write_registry(tmp_path, value)
    with pytest.raises(LargeBatchError, match="entry is invalid"):
        load_large_batch_registry(tmp_path)


@pytest.mark.parametrize("invalid_count", [-1, "0", True])
def test_registry_rejects_invalid_per_year_exclusion_types(
    tmp_path: Path, invalid_count: object
) -> None:
    value = _registry_value()
    value["entries"][0]["expectedExcludedObservationCountsByYear"]["2021"] = (
        invalid_count
    )
    _write_registry(tmp_path, value)
    with pytest.raises(LargeBatchError, match="entry is invalid"):
        load_large_batch_registry(tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_registry_rejects_missing_or_extra_exclusion_year(
    tmp_path: Path, mutation: str
) -> None:
    value = _registry_value()
    counts = value["entries"][0]["expectedExcludedObservationCountsByYear"]
    if mutation == "missing":
        counts.pop("2021")
    else:
        counts["2099"] = 0
    _write_registry(tmp_path, value)
    with pytest.raises(LargeBatchError, match="entry is invalid"):
        load_large_batch_registry(tmp_path)


def _normalization_manifest() -> dict[str, object]:
    return json.loads(
        (
            PROJECT / "fixtures/product-prototype/batch-workbook-normalization-v1.json"
        ).read_text()
    )


def _bind_normalization_manifest(manifest: dict[str, object]) -> None:
    semantic = {
        key: value for key, value in manifest.items() if key != "manifestDigest"
    }
    manifest["manifestDigest"] = domain_digest(
        large_batch_module.NORMALIZATION_SCHEMA, semantic
    )


def test_normalization_manifest_rejects_missing_entry_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_large_batch_registry(PROJECT)
    manifest = _normalization_manifest()
    manifest["entries"][0].pop("normalization")
    _bind_normalization_manifest(manifest)
    original_load = large_batch_module._load_object

    def load(path: Path, label: str) -> dict[str, object]:
        if label == "normalization manifest":
            return manifest
        return original_load(path, label)

    monkeypatch.setattr(large_batch_module, "_load_object", load)
    with pytest.raises(LargeBatchError, match="manifest entry is invalid"):
        verify_batch_normalization(PROJECT, registry)


def test_normalization_manifest_rejects_relabelled_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_large_batch_registry(PROJECT)
    manifest = _normalization_manifest()
    manifest["entries"][0]["normalization"] = (
        "trim-pathological-full-width-formatting-merge-v1"
    )
    _bind_normalization_manifest(manifest)
    original_load = large_batch_module._load_object

    def load(path: Path, label: str) -> dict[str, object]:
        if label == "normalization manifest":
            return manifest
        return original_load(path, label)

    monkeypatch.setattr(large_batch_module, "_load_object", load)
    with pytest.raises(LargeBatchError, match="does not match normalization manifest"):
        verify_batch_normalization(PROJECT, registry)


def test_normalization_manifest_rejects_wrong_cohort_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_large_batch_registry(PROJECT)
    spec = registry.entries[0]
    cohort_path = (PROJECT / spec.cohort_path).resolve()
    cohort = json.loads(cohort_path.read_text())
    normalized = next(
        workbook for workbook in cohort["workbooks"] if "normalization" in workbook
    )
    normalized["normalization"] = "wrong-normalization-v1"
    original_load = large_batch_module._load_object

    def load(path: Path, label: str) -> dict[str, object]:
        if label == "large-batch cohort" and path == cohort_path:
            return cohort
        return original_load(path, label)

    monkeypatch.setattr(large_batch_module, "_load_object", load)
    with pytest.raises(LargeBatchError, match="does not match normalization manifest"):
        verify_batch_normalization(PROJECT, registry)


def test_evidence_rejects_redistributed_per_year_exclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_large_batch_registry(PROJECT)
    spec = next(
        item
        for item in registry.entries
        if item.family_id == "national-selected-characteristics-by-offence-charge"
    )
    manifest_path = (PROJECT / spec.evidence_manifest_path).resolve()
    evidence_root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    run = json.loads((evidence_root / "run.json").read_text())
    run["workbooks"][0]["excludedObservationCount"] = 1
    run["workbooks"][1]["excludedObservationCount"] = 35
    semantic = dict(run)
    semantic.pop("runDigest")
    run["runDigest"] = domain_digest(RUN_SCHEMA, semantic)
    manifest["runDigest"] = run["runDigest"]
    original_load = large_batch_module._load_object

    def load(path: Path, label: str) -> dict[str, object]:
        if path == manifest_path:
            return manifest
        if path == evidence_root / "run.json":
            return run
        return original_load(path, label)

    monkeypatch.setattr(large_batch_module, "_load_object", load)
    with pytest.raises(LargeBatchError, match="Run evidence is invalid"):
        verify_large_batch_evidence(PROJECT, spec)


def test_evidence_rejects_warning_count_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_large_batch_registry(PROJECT)
    spec = next(
        item
        for item in registry.entries
        if item.family_id.endswith("new-south-wales-and-99870bae7c")
    )
    manifest_path = (PROJECT / spec.evidence_manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    manifest["warningCountsByYear"]["2024"] += 1
    original_load = large_batch_module._load_object

    def load(path: Path, label: str) -> dict[str, object]:
        if path == manifest_path:
            return manifest
        return original_load(path, label)

    monkeypatch.setattr(large_batch_module, "_load_object", load)
    with pytest.raises(LargeBatchError, match="warning counts do not match"):
        verify_large_batch_evidence(PROJECT, spec)


def test_multi_condition_measure_selection_rejects_overlap() -> None:
    cohort_path = (
        PROJECT
        / "fixtures/product-prototype/prisoners-selected-characteristics-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "acceptance"
            / "prisoners-selected-characteristics-v1.json"
        ).read_text()
    )
    _validate_contract(contract, cohort)
    contract["measures"][2]["selection"]["conditions"] = {
        "statistic_basis": ["NUMBER"],
        "characteristic_group": ["SEX"],
    }
    with pytest.raises(ProductPrototypeError, match="selection overlaps"):
        _validate_contract(contract, cohort)


def test_empty_total_equations_require_explicit_not_applicable_policy() -> None:
    cohort_path = (
        PROJECT
        / "fixtures/product-prototype/prisoners-selected-characteristics-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "acceptance"
            / "prisoners-selected-characteristics-v1.json"
        ).read_text()
    )
    _validate_contract(contract, cohort)
    contract.pop("totalValidation")
    with pytest.raises(ProductPrototypeError, match="total equations"):
        _validate_contract(contract, cohort)


def test_reviewed_combination_digest_rejects_marginal_preserving_swap() -> None:
    cohort_path = (
        PROJECT / "fixtures/product-prototype/prisoners-table-34-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-34-v1.json"
        ).read_text()
    )
    rows = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "table-34-five-year-evidence"
            / "canonical-observations.json"
        ).read_text()
    )
    digest_2025 = next(
        item["contentDigest"] for item in cohort["workbooks"] if item["year"] == 2025
    )
    year_rows = [
        dict(row) for row in rows if row["source_workbook_digest"] == digest_2025
    ]
    assert _validate_expected_coverage(year_rows, contract, {"year": 2025}) == []
    candidates = [row for row in year_rows if row["measure_id"] == "prisoner-count"]
    left = candidates[0]
    right = next(
        row
        for row in candidates[1:]
        if row["jurisdiction_id"] != left["jurisdiction_id"]
        and row["prison_location_id"] != left["prison_location_id"]
    )
    left["prison_location_id"], right["prison_location_id"] = (
        right["prison_location_id"],
        left["prison_location_id"],
    )
    issues = _validate_expected_coverage(year_rows, contract, {"year": 2025})
    assert {item["code"] for item in issues} == {"EXPECTED_COMBINATION_SET_MISMATCH"}


def test_vintage_contract_requires_date_codes_and_two_time_axes() -> None:
    cohort_path = (
        PROJECT / "fixtures/product-prototype/prisoners-table-27-2021-2025.json"
    )
    cohort = json.loads(cohort_path.read_text())
    contract = json.loads(
        (
            PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-27-v1.json"
        ).read_text()
    )
    _validate_contract(contract, cohort)
    assert contract["referenceDateDimension"] == "observation_period"
    assert contract["preservePublicationVintage"] is True
    assert contract["uniqueKey"][:2] == [
        "publication_vintage_date",
        "reference_date",
    ]
    rows = json.loads(
        (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "table-27-five-year-evidence"
            / "canonical-observations.json"
        ).read_text()
    )
    assert all(row["reference_date"] == row["observation_period_id"] for row in rows)
    assert any(row["publication_vintage_date"] != row["reference_date"] for row in rows)
    invalid = json.loads(json.dumps(contract))
    invalid["aliases"]["observation_period"]["2011"] = "YEAR_2011"
    with pytest.raises(ProductPrototypeError, match="Reference-date dimension"):
        _validate_contract(invalid, cohort)


@pytest.mark.timeout(900)
def test_all_large_batch_cohorts_replay_cleanly(tmp_path: Path) -> None:
    report = run_batch(PROJECT, tmp_path / "batch", concurrency=3)
    assert report["passed"] is True
    assert report["providerCalls"] == 0
    assert report["acceptedWorksheetCount"] == 277
    assert report["exceptionWorksheetCount"] == 0
    assert report["canonicalObservationCount"] == 248688
    assert {item["familyId"] for item in report["cohorts"]} == {
        item.family_id for item in load_large_batch_registry(PROJECT).entries
    }
    expected_workbooks = {
        item.family_id: len(item.expected_years)
        for item in load_large_batch_registry(PROJECT).entries
    }
    assert all(
        item["passed"] is True
        and item["acceptedWorkbookCount"] == expected_workbooks[item["familyId"]]
        and item["exceptionWorkbookCount"] == 0
        and item["providerCalls"] == 0
        and item["crossYearIssues"] == []
        for item in report["cohorts"]
    )


def test_workbook_format_trim_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "normalized.xlsx"
    completed = subprocess.run(
        [
            str(PROJECT / "scripts/trim-prototype-workbook-formatting.py"),
            str(
                PROJECT
                / "fixtures/product-prototype/workbooks/prisoners-australia-2021.xlsx"
            ),
            str(output),
            "--sheet",
            "Table_34=A1:B190",
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert (
        output.read_bytes()
        == (
            PROJECT
            / "fixtures"
            / "product-prototype"
            / "workbooks"
            / "prisoners-australia-2021-batch-normalized.xlsx"
        ).read_bytes()
    )


def test_digest_bound_correction_emits_manifest_matching_receipt(
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        (
            PROJECT / "fixtures/product-prototype/batch-workbook-normalization-v1.json"
        ).read_text()
    )
    entry = next(
        item
        for item in manifest["entries"]
        if item["year"] == 2024 and item["correction"] is not None
    )
    output = tmp_path / "corrected.xlsx"
    receipt = tmp_path / "receipt.json"
    completed = subprocess.run(
        [
            str(PROJECT / manifest["correctionScriptPath"]),
            str(PROJECT / entry["sourcePath"]),
            str(output),
            "--receipt",
            str(receipt),
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(receipt.read_text()) == entry["correction"]


def _source_cell(address: str) -> str:
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", address)
    assert match is not None
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    return f"R{match.group(2)}C{column}"


def test_prisoners_state_cluster_geometry_and_acceptance_are_independent() -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(PROJECT / "scripts/generate-prisoners-state-cluster.py"),
            "--check",
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    geometry = json.loads(
        (
            PROJECT
            / "fixtures/product-prototype/prisoners-state-cluster-geometry-v1.json"
        ).read_text()
    )
    audit = json.loads(
        (
            PROJECT
            / "fixtures/product-prototype"
            / "prisoners-state-cluster-acceptance-audit-v1.json"
        ).read_text()
    )
    assert geometry["authority"] == "human-authored-reviewed-physical-geometry"
    assert audit["authority"] == "independent-of-replay-output"
    assert audit["handoffCorrection"] == {
        "year": 2025,
        "sheet": "Table 16",
        "publishedGrid": "B:K",
        "publishedColumns": 10,
        "expectedRows": 900,
        "familyRows": 4068,
        "clusterRows": 8406,
        "reason": audit["handoffCorrection"]["reason"],
    }
    assert sum(item["expectedCanonicalCount"] for item in audit["families"]) == 8406
    assert sum(len(item["members"]) for item in geometry["families"]) == 24

    geometry_by_family = {item["familyId"]: item for item in geometry["families"]}
    crosswalk = json.loads(
        (
            PROJECT
            / "fixtures/product-prototype/prisoners-release-family-crosswalk-v1.json"
        ).read_text()
    )
    crosswalk_by_family = {
        item["familyId"]: item["members"] for item in crosswalk["families"]
    }
    expected_workbook_digests = {
        2021: "sha256:9a5be165da58005a2a31634568491645192785a96f27d9eee3c17e45175d1710",
        2022: "sha256:a16a47e574d8da8d851f904f8ee60324cac870a89e76f4ea9114680bdde40a2b",
        2023: "sha256:61366170db7a4da717332a3ad1ca9e11f884d95905bb4556f5f44ce51d31c66f",
        2024: "sha256:609a96a96e2e359ae3e534252bcb1a6b6a329eb91fcf289834d1014dc61273d1",
        2025: "sha256:007a1c21fc2a2b256cbde672405a4710edcac85eff035949f403ca3fbed6ab6e",
    }
    for family in audit["families"]:
        evidence = json.loads(
            (
                PROJECT
                / "fixtures/product-prototype"
                / f"{family['familyId']}-five-year-evidence/canonical-observations.json"
            ).read_text()
        )
        assert len(evidence) == family["expectedCanonicalCount"]
        assert (
            dict(sorted(Counter(row["measure_id"] for row in evidence).items()))
            == family["measureCounts"]
        )
        cohort = json.loads(
            (
                PROJECT
                / "fixtures/product-prototype"
                / f"prisoners-{family['familyId']}.json"
            ).read_text()
        )
        reviewed_members = crosswalk_by_family[family["familyId"]]
        assert all(item["cube"] == 2 for item in reviewed_members)
        assert [(item["year"], item["sheet"]) for item in reviewed_members] == [
            (item["year"], item["sheet"]) for item in cohort["workbooks"]
        ]
        assert all(
            item["contentDigest"] == expected_workbook_digests[item["year"]]
            for item in cohort["workbooks"]
        )
        assert {
            item["year"] for item in cohort["workbooks"] if "normalization" in item
        } == ({2021, 2022, 2023, 2025} & set(family["years"]))
        rows_by_digest = {
            workbook["contentDigest"]: [
                row
                for row in evidence
                if row["source_workbook_digest"] == workbook["contentDigest"]
            ]
            for workbook in cohort["workbooks"]
        }
        assert [
            len(rows_by_digest[item["contentDigest"]]) for item in cohort["workbooks"]
        ] == family["expectedYearCounts"]
        for member, workbook in zip(
            geometry_by_family[family["familyId"]]["members"],
            cohort["workbooks"],
            strict=True,
        ):
            cells = {
                row["source_cell"] for row in rows_by_digest[workbook["contentDigest"]]
            }
            for band in member["valueBands"]:
                first, last = band.split(":")
                assert {_source_cell(first), _source_cell(last)} <= cells


def test_prisoners_state_cluster_retains_vintages_totals_and_null_markers() -> None:
    base = PROJECT / "fixtures/product-prototype"
    crude = json.loads(
        (base / "prisoners-state-crude-imprisonment-rate.json").read_text()
    )
    assert [item["year"] for item in crude["workbooks"]] == [2021, 2022, 2023, 2024]
    assert all(
        item["sheet"].replace("_", " ") == "Table 19" for item in crude["workbooks"]
    )

    selected = json.loads(
        (
            base
            / "state-selected-characteristics-time-series-five-year-evidence"
            / "canonical-observations.json"
        ).read_text()
    )
    assert all(
        row["reference_date"] == row["observation_period_id"] for row in selected
    )
    assert any(
        row["publication_vintage_date"] != row["reference_date"] for row in selected
    )
    vintages_by_period: dict[str, set[str]] = {}
    for row in selected:
        vintages_by_period.setdefault(row["reference_date"], set()).add(
            row["publication_vintage_date"]
        )
    assert any(len(vintages) > 1 for vintages in vintages_by_period.values())

    sex_status = json.loads(
        (
            base
            / "state-sex-by-indigenous-status-five-year-evidence"
            / "canonical-observations.json"
        ).read_text()
    )
    markers = Counter(
        (row["raw_value"], row["value_status"])
        for row in sex_status
        if row["value_status"] != "observed"
    )
    assert set(markers) == {
        ("n.p.", "suppressed"),
        ("np", "suppressed"),
        ("n.a.", "not_applicable"),
        ("n.a", "not_applicable"),
        ("na", "not_applicable"),
    }
    assert all(
        row["value"] is None for row in sex_status if row["value_status"] != "observed"
    )
    count_rows = [row for row in sex_status if row["measure_id"] == "prisoner-count"]
    assert len(count_rows) == 81
    assert {row["source_workbook_digest"] for row in count_rows} == {
        "sha256:007a1c21fc2a2b256cbde672405a4710edcac85eff035949f403ca3fbed6ab6e"
    }
    assert all(row["unit_id"] == "person" for row in count_rows)
    assert {"AUS"} <= {row["jurisdiction_id"] for row in sex_status}
    assert {"PERSONS"} <= {row["sex_id"] for row in sex_status}
    assert {"TOTAL"} <= {row["indigenous_status_id"] for row in sex_status}
    assert any(
        row["measure_id"] == "indigenous-to-non-indigenous-rate-ratio"
        and row["statistic_basis_id"] == "RATE_RATIO"
        and row["rate_basis_id"] in {"CRUDE", "AGE_STANDARDISED"}
        for row in sex_status
    )
    for family in (
        "state-selected-characteristics-time-series",
        "state-sex-by-indigenous-status",
        "state-age-standardised-rate-by-indigenous-status",
        "state-crude-imprisonment-rate",
        "state-crude-rate-by-indigenous-status",
    ):
        contract = json.loads(
            (base / f"acceptance/prisoners-{family}-v1.json").read_text()
        )
        assert contract["totalValidation"] == "not_applicable"
        assert contract["totalEquations"] == []


@pytest.mark.timeout(180)
def test_large_batch_cli_verifies_committed_evidence() -> None:
    completed = subprocess.run(
        [str(PROJECT / "scripts/tidy-prototype-batch"), "verify"],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report == {
        "batchId": "justice-two-hundred-seventy-seven-worksheets-v1",
        "worksheetCount": 277,
        "cohortCount": 89,
        "canonicalObservationCount": 248688,
        "providerCalls": 0,
        "verified": True,
    }
