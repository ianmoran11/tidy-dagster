from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "product-prototype"
DIRECT = ROOT / ".product-prototype" / "prisoners-remaining-phase1" / "direct"
sys.path.insert(0, str(ROOT / "src"))
from tidy_orchestrator.artifacts import domain_digest  # noqa: E402
from tidy_orchestrator.product_prototype import (  # noqa: E402
    _DIMENSION_FIELDS,
    _EXPECTED_CATEGORY_FIELDS,
    COMBINATION_COVERAGE_SCHEMA,
)


def normalized_raw(value: Any) -> str:
    if isinstance(value, bool):
        raise RuntimeError("boolean dimension value")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if not isinstance(value, str):
        raise RuntimeError(f"invalid dimension value {value!r}")
    return " ".join(value.strip().split())


def code(value: str) -> str:
    semantic = re.sub(r"(?:\s*\([a-z]\))+$", "", value, flags=re.I)
    canonical = " ".join(semantic.upper().split())
    slug = re.sub(r"[^A-Z0-9]+", "_", canonical).strip("_") or "VALUE"
    return slug[:80] + "_" + hashlib.sha256(canonical.encode()).hexdigest()[:8]


plan = json.loads((FIX / "prisoners-remaining-semantic-map-plan-v1.json").read_text())
summary: list[dict[str, Any]] = []
contracts: list[tuple[Path, str]] = []
for family in plan["families"]:
    family_id = family["familyId"]
    cohort_path = FIX / f"prisoners-{family_id}.json"
    cohort = json.loads(cohort_path.read_text())
    years = [str(item["year"]) for item in cohort["workbooks"]]
    direct_by_year: dict[str, list[dict[str, Any]]] = {}
    required: list[str] | None = None
    aliases: dict[str, dict[str, str]] = {}
    numeric_values: list[int | float] = []
    row_counts: dict[str, int] = {}
    for year in years:
        direct = json.loads((DIRECT / family_id / f"{year}.json").read_text())
        table = direct["execution"]["tables"]
        if len(table) != 1 or direct["execution"].get("warnings"):
            raise RuntimeError(f"non-closed direct execution {family_id} {year}")
        rows = table[0]["rows"]
        dimensions = [
            header["name"].replace(" ", "_")
            for header in direct["recipe"]["tables"][0]["headers"]
        ]
        if required is None:
            required = dimensions
            aliases = {dimension: {} for dimension in required}
        if dimensions != required:
            raise RuntimeError(f"dimension drift {family_id} {year}")
        keys: set[tuple[str, ...]] = set()
        for row in rows:
            key: list[str] = []
            for dimension in required:
                raw = normalized_raw(row[dimension.replace("_", " ")])
                aliases[dimension][raw] = code(raw)
                key.append(raw)
            if tuple(key) in keys:
                raise RuntimeError(
                    f"duplicate declared key {family_id} {year}: {key!r}"
                )
            keys.add(tuple(key))
            value = row["published value"]
            if isinstance(value, int | float) and not isinstance(value, bool):
                numeric_values.append(value)
        direct_by_year[year] = rows
        row_counts[year] = len(rows)
    assert required is not None

    expected_by_dimension: dict[str, dict[str, list[str]]] = {
        dimension: {} for dimension in required
    }
    combination_digests: dict[str, str] = {}
    recipe_digests: dict[str, str] = {}
    for year, rows in direct_by_year.items():
        combinations: list[list[str]] = []
        for row in rows:
            combination: list[str] = []
            for dimension in required:
                raw = normalized_raw(row[dimension.replace("_", " ")])
                canonical = aliases[dimension][raw]
                combination.append(canonical)
            combinations.append(combination)
        combinations.sort()
        for index, dimension in enumerate(required):
            expected_by_dimension[dimension][year] = sorted(
                {item[index] for item in combinations}
            )
        combination_digests[year] = domain_digest(
            COMBINATION_COVERAGE_SCHEMA,
            {"dimensions": required, "combinations": combinations},
        )
        direct = json.loads((DIRECT / family_id / f"{year}.json").read_text())
        recipe_bytes = (
            json.dumps(direct["recipe"], indent=2, ensure_ascii=False) + "\n"
        ).encode()
        recipe_digests[year] = "sha256:" + hashlib.sha256(recipe_bytes).hexdigest()

    minimum = min(numeric_values) if numeric_values else 0
    measure = {
        "id": "published-value",
        "unitId": "published-unit",
        "numeric": True,
        "minimum": minimum,
        "expectedCombinationCountsByYear": row_counts,
        "expectedDimensionsByYear": {
            year: {
                dimension: expected_by_dimension[dimension][year]
                for dimension in required
            }
            for year in years
        },
        "expectedCombinationDigestsByYear": combination_digests,
        "missingValues": {
            "n.a.": "not_applicable",
            "na": "not_available",
            "n.p.": "suppressed",
            "np": "suppressed",
            "..": "not_available",
        },
    }
    if minimum < 0:
        measure["allowNegative"] = True
    expected: dict[str, Any] = {
        "minimumRows": min(row_counts.values()),
        "maximumRows": max(row_counts.values()),
        "sourceColumns": {"minimum": 1, "maximum": 200},
    }
    for dimension in required:
        expected[f"{_EXPECTED_CATEGORY_FIELDS[dimension]}ByYear"] = (
            expected_by_dimension[dimension]
        )
    contract = {
        "schemaVersion": "tidy.table-family-acceptance/v2",
        "contractId": f"prisoners-{family_id}-v1",
        "tableFamilyId": family_id,
        "measures": [measure],
        "requiredDimensions": required,
        "dimensionHeaders": {
            dimension: [dimension.replace("_", " ")] for dimension in required
        },
        "aliases": aliases,
        "strictAliasMatching": True,
        "decisionIdentityVersion": "v2-reference-date-v1",
        "expectedRecipeDigestsByYear": recipe_digests,
        "expectedWarningCountsByYear": {year: 0 for year in years},
        "uniqueKey": [
            "reference_date",
            *[_DIMENSION_FIELDS[d] for d in required],
            "measure_id",
        ],
        "expected": expected,
        "allowedExecutionWarnings": [],
        "totalEquations": [],
        "totalValidation": "not_applicable",
        "automaticAcceptance": True,
        "trainingEligibility": False,
    }
    target = FIX / "acceptance" / f"prisoners-{family_id}-v1.json"
    contracts.append(
        (target, json.dumps(contract, indent=2, ensure_ascii=False) + "\n")
    )
    summary.append(
        {
            "familyId": family_id,
            "members": len(years),
            "rows": sum(row_counts.values()),
            "aliases": sum(len(value) for value in aliases.values()),
            "minimum": minimum,
        }
    )
family_count = len(summary)
member_count = sum(item["members"] for item in summary)
if family_count != 21 or member_count != 69 or len(contracts) != family_count:
    raise RuntimeError(
        f"incomplete contract finalization: {family_count} families, "
        f"{member_count} members, {len(contracts)} contracts"
    )

# Do not replace any bootstrap contract until all 21 final contracts have been
# derived successfully. Per-file replacement keeps repeated completed runs
# deterministic and prevents readers from observing partially written JSON.
for target, rendered in contracts:
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(rendered)
    temporary.replace(target)

print(
    json.dumps(
        {
            "families": family_count,
            "members": member_count,
            "rows": sum(x["rows"] for x in summary),
            "aliases": sum(x["aliases"] for x in summary),
            "minimumNumericValue": min(x["minimum"] for x in summary),
        }
    )
)
