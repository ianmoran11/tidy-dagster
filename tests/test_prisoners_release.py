from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tidy_orchestrator.prisoners_release import (
    PrisonersReleaseError,
    _registered_members,
    build_family_membership,
    build_source_inventory,
    inspect_workbook,
    semantic_cells,
    verify_prisoners_release,
)
from tidy_orchestrator.product_prototype import (
    ProductPrototypeError,
    _validate_cohort,
)

PROJECT = Path(__file__).parents[1]
FIXTURES = PROJECT / "fixtures" / "product-prototype"
EXPANDED_COHORT = FIXTURES / "prisoners-table-30-2021-2025.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_release_verifier_proves_exact_custody_and_membership() -> None:
    report = verify_prisoners_release(PROJECT)

    assert report == {
        "verified": True,
        "releaseCount": 5,
        "downloadCount": 22,
        "substantiveCubeCount": 17,
        "numberedDataSheetCount": 203,
        "familyCount": 48,
        "registeredMemberCount": 134,
        "pendingSemanticContractCount": 69,
        "providerCalls": 0,
        "inventoryDigest": report["inventoryDigest"],
        "membershipDigest": report["membershipDigest"],
    }

    inventory = _load(FIXTURES / "prisoners-release-source-inventory-v1.json")
    downloads = inventory["downloads"]
    assert inventory["releaseCounts"] == {
        "2021": 42,
        "2022": 39,
        "2023": 39,
        "2024": 39,
        "2025": 44,
    }
    assert sum(item["kind"] == "guide" for item in downloads) == 5
    assert sum(item["kind"] == "cube" for item in downloads) == 17
    assert (
        sum(
            sheet["classification"] == "non-data"
            for item in downloads
            for sheet in item["sheets"]
        )
        == 29
    )
    assert all(
        sheet["state"] in {"visible", "hidden", "veryHidden"}
        and sheet["title"] is not None
        for item in downloads
        for sheet in item["sheets"]
        if sheet["classification"] == "numbered-data"
    )


def test_2025_current_state_source_has_distinct_bytes_and_exact_cell_parity() -> None:
    workbooks = FIXTURES / "workbooks"
    current = workbooks / "prisoners-australia-2025-states-current-source.xlsx"
    historical = workbooks / "prisoners-australia-2025.xlsx"

    assert current.read_bytes() != historical.read_bytes()
    assert semantic_cells(current) == semantic_cells(historical)
    assert [(item["name"], item["state"]) for item in inspect_workbook(current)] == [
        (item["name"], item["state"]) for item in inspect_workbook(historical)
    ]


def test_generator_check_and_cli_are_cwd_independent(tmp_path: Path) -> None:
    generator = PROJECT / "scripts" / "generate-prisoners-release-inventory.py"
    generated = subprocess.run(
        [str(generator), "--check"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert generated.stdout == ""
    assert generated.stderr == ""

    cli = subprocess.run(
        [str(PROJECT / "scripts" / "tidy-prisoners-release"), "verify"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(cli.stdout)["verified"] is True
    assert json.loads(cli.stdout)["providerCalls"] == 0


def test_membership_rejects_duplicate_and_fabricated_availability(
    tmp_path: Path,
) -> None:
    inventory = build_source_inventory(PROJECT)
    fixture_root = tmp_path / "fixtures" / "product-prototype"
    fixture_root.mkdir(parents=True)
    source = FIXTURES / "prisoners-release-family-crosswalk-v1.json"
    crosswalk = _load(source)

    duplicate = copy.deepcopy(crosswalk)
    duplicate["families"][0]["members"].append(
        copy.deepcopy(duplicate["families"][0]["members"][0])
    )
    (fixture_root / source.name).write_text(json.dumps(duplicate))
    with pytest.raises(PrisonersReleaseError, match="duplicates"):
        build_family_membership(tmp_path, inventory)

    fabricated = copy.deepcopy(crosswalk)
    moved = fabricated["families"][0]["members"].pop(1)
    fabricated["families"][-1]["members"] = [moved]
    (fixture_root / source.name).write_text(json.dumps(fabricated))
    with pytest.raises(PrisonersReleaseError, match="fabricated availability"):
        build_family_membership(tmp_path, inventory)


def test_registered_member_must_match_its_semantic_family(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixtures" / "product-prototype"
    fixture_root.mkdir(parents=True)
    cohort_path = fixture_root / "wrong-family.json"
    cohort_path.write_text(
        json.dumps(
            {
                "publicationId": "prisoners-australia",
                "tableFamilyId": "wrong-family",
                "workbooks": [{"year": 2021, "sheet": "Table_1"}],
            }
        )
    )
    (fixture_root / "data-asset-status-v1.json").write_text(
        json.dumps(
            {"cohorts": [{"cohortPath": cohort_path.relative_to(tmp_path).as_posix()}]}
        )
    )
    membership = {
        "families": [
            {
                "familyId": "right-family",
                "members": [
                    {
                        "year": 2021,
                        "downloadOrdinal": 1,
                        "sheet": "Table_1",
                    }
                ],
            }
        ]
    }
    with pytest.raises(PrisonersReleaseError, match="wrong family"):
        _registered_members(tmp_path, membership)


def test_cohort_runtime_accepts_2021_and_2025_singletons() -> None:
    cohort = _load(EXPANDED_COHORT)
    for index in (0, -1):
        singleton = copy.deepcopy(cohort)
        singleton["workbooks"] = [copy.deepcopy(cohort["workbooks"][index])]
        singleton["generation"]["maximumCalls"] = 2
        _validate_cohort(singleton)


def test_cohort_runtime_rejects_empty_and_duplicate_availability() -> None:
    cohort = _load(EXPANDED_COHORT)
    empty = copy.deepcopy(cohort)
    empty["workbooks"] = []
    empty["generation"]["maximumCalls"] = 0
    with pytest.raises(ProductPrototypeError, match="one and twelve"):
        _validate_cohort(empty)

    duplicate = copy.deepcopy(cohort)
    duplicate["workbooks"] = [
        copy.deepcopy(cohort["workbooks"][0]),
        copy.deepcopy(cohort["workbooks"][0]),
    ]
    duplicate["generation"]["maximumCalls"] = 4
    with pytest.raises(ProductPrototypeError, match="unique and increasing"):
        _validate_cohort(duplicate)
