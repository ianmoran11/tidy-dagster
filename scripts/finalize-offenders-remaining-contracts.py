#!/usr/bin/env python3
"""Pure policy-v2 contract builder for corrected C4 route executions.

This helper never reads direct/ and never installs acceptance contracts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tidy_orchestrator.artifacts import domain_digest, sha256_digest  # noqa:E402
from tidy_orchestrator.product_prototype import (  # noqa: E402
    _DIMENSION_FIELDS,
    _EXPECTED_CATEGORY_FIELDS,
    COMBINATION_COVERAGE_SCHEMA,
)

FIX = ROOT / "fixtures/product-prototype"
PLAN = FIX / "offenders-remaining-semantic-map-plan-v1.json"
MARKERS = {"na": "not_available", "np": "suppressed"}


def load(p: Path) -> Any:
    return json.loads(p.read_text())


def pretty(v: Any) -> bytes:
    return (json.dumps(v, indent=2, ensure_ascii=False) + "\n").encode()


def norm(v: Any) -> str:
    if isinstance(v, bool) or v is None:
        raise RuntimeError(f"invalid dimension {v!r}")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if not isinstance(v, str):
        raise RuntimeError(f"invalid dimension {v!r}")
    return " ".join(v.strip().split())


def code(v: str) -> str:
    semantic = re.sub(r"(?:\s*\([a-z]\))+$", "", v, flags=re.I)
    canonical = " ".join(semantic.upper().split())
    slug = re.sub(r"[^A-Z0-9]+", "_", canonical).strip("_") or "VALUE"
    return slug[:80] + "_" + hashlib.sha256(canonical.encode()).hexdigest()[:8]


def recipe_names(recipe: dict[str, Any]) -> tuple[list[str], str, str]:
    if recipe.get("version") == "TargetScopedRecipeV02":
        return (
            [x["name"] for x in recipe["dimensions"]],
            recipe["table"]["valuesName"],
            "TargetScopedRecipeV02",
        )
    table = recipe["tables"][0]
    return [x["name"] for x in table["headers"]], table["values"]["name"], "RecipeV01"


def build(executions: Path, cohort_root: Path, out: Path) -> dict[str, Any]:
    plan = load(PLAN)
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    observed = Counter()
    for family in plan["families"]:
        fid = family["familyId"]
        cohort = load(cohort_root / f"recorded-crime-offenders-{fid}.json")
        years = [str(x["year"]) for x in cohort["workbooks"]]
        rows_by_year = {}
        required = None
        headers_by_dimension = None
        value_name = None
        aliases = {}
        numeric = []
        row_counts = {}
        family_markers = Counter()
        recipe_digests = {}
        protocols = {}
        map_digests = {}
        trace_digests = {}
        for year in years:
            root = executions / f"members/{fid}/{year}"
            execution = load(root / "execution.json")
            recipe = load(root / "normalized-recipe.json")
            proof = load(root / "route-proof.json")
            headers, value, protocol = recipe_names(recipe)
            dims = [x.replace(" ", "_") for x in headers]
            mapping = dict(zip(dims, headers, strict=True))
            if required is None:
                required = dims
                headers_by_dimension = mapping
                value_name = value
                aliases = {x: {} for x in dims}
            if (
                dims != required
                or mapping != headers_by_dimension
                or value != value_name
                or proof["recipeProtocol"] != protocol
            ):
                raise RuntimeError(f"recipe drift {fid} {year}")
            rows = execution["tables"][0]["rows"]
            seen = set()
            for row in rows:
                raw = tuple(norm(row[headers_by_dimension[d]]) for d in required)
                if raw in seen:
                    raise RuntimeError(f"duplicate raw key {fid} {year}")
                seen.add(raw)
                for d, v in zip(required, raw, strict=True):
                    aliases[d][v] = code(v)
                value_raw = row[value_name]
                if isinstance(value_raw, int | float) and not isinstance(
                    value_raw, bool
                ):
                    numeric.append(value_raw)
                elif isinstance(value_raw, str) and value_raw in MARKERS:
                    family_markers[value_raw] += 1
                    observed[value_raw] += 1
                else:
                    raise RuntimeError(f"invalid value {fid} {year}: {value_raw!r}")
            rows_by_year[year] = rows
            row_counts[year] = len(rows)
            recipe_digests[year] = sha256_digest(
                (root / "normalized-recipe.json").read_bytes()
            )
            protocols[year] = protocol
            map_digests[year] = proof["mapDigest"]
            trace_digests[year] = proof["rowTraceDigest"]
        assert required is not None and value_name is not None
        expected_by = {d: {} for d in required}
        combination_digests = {}
        for year, rows in rows_by_year.items():
            combinations = []
            canonical_raw = {}
            for row in rows:
                raw = tuple(norm(row[headers_by_dimension[d]]) for d in required)
                canonical = tuple(aliases[d][raw[i]] for i, d in enumerate(required))
                prior = canonical_raw.get(canonical)
                if prior is not None and prior != raw:
                    raise RuntimeError(f"alias collision {fid} {year}")
                canonical_raw[canonical] = raw
                combinations.append(list(canonical))
            combinations.sort()
            for i, d in enumerate(required):
                expected_by[d][year] = sorted({x[i] for x in combinations})
            combination_digests[year] = domain_digest(
                COMBINATION_COVERAGE_SCHEMA,
                {"dimensions": required, "combinations": combinations},
            )
        minimum = min(numeric) if numeric else 0
        if minimum < 0:
            raise RuntimeError(f"negative value {fid}")
        measure = {
            "id": "published-value",
            "unitId": "published-unit",
            "numeric": True,
            "minimum": minimum,
            "expectedCombinationCountsByYear": row_counts,
            "expectedDimensionsByYear": {
                y: {d: expected_by[d][y] for d in required} for y in years
            },
            "expectedCombinationDigestsByYear": combination_digests,
            "missingValues": {m: MARKERS[m] for m in sorted(family_markers)},
        }
        expected = {
            "minimumRows": min(row_counts.values()),
            "maximumRows": max(row_counts.values()),
            "sourceColumns": {"minimum": 1, "maximum": 200},
        }
        for d in required:
            expected[f"{_EXPECTED_CATEGORY_FIELDS[d]}ByYear"] = expected_by[d]
        contract = {
            "schemaVersion": "tidy.table-family-acceptance/v2",
            "contractId": f"recorded-crime-offenders-{fid}-v1",
            "tableFamilyId": fid,
            "measures": [measure],
            "requiredDimensions": required,
            "dimensionHeaders": {
                d: [re.escape(headers_by_dimension[d])] for d in required
            },
            "aliases": aliases,
            "strictAliasMatching": True,
            "decisionIdentityVersion": "v2-reference-date-v1",
            "expectedRecipeDigestsByYear": recipe_digests,
            "expectedRecipeProtocolsByYear": protocols,
            "expectedReplayMapDigestsByYear": map_digests,
            "expectedC3RowTraceDigestsByYear": trace_digests,
            "expectedWarningCountsByYear": {y: 0 for y in years},
            "uniqueKey": [
                "publication_vintage_date",
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
            "preservePublicationVintage": True,
            "preserveRawValueText": True,
        }
        path = out / f"recorded-crime-offenders-{fid}-v1.json"
        path.write_bytes(pretty(contract))
        summaries.append(
            {
                "familyId": fid,
                "members": len(years),
                "rows": sum(row_counts.values()),
                "aliases": sum(map(len, aliases.values())),
            }
        )
    if (
        len(summaries) != 47
        or sum(x["members"] for x in summaries) != 170
        or sum(x["rows"] for x in summaries) != 224997
        or set(observed) != set(MARKERS)
    ):
        raise RuntimeError("contract closure")
    return {
        "families": 47,
        "members": 170,
        "rows": 224997,
        "aliases": sum(x["aliases"] for x in summaries),
        "markerCounts": dict(sorted(observed.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--executions", required=True)
    ap.add_argument("--cohort-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--check")
    a = ap.parse_args()
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    result = build(Path(a.executions), Path(a.cohort_root), out)
    if a.check:
        expected = Path(a.check)
        actual = {x.relative_to(out) for x in out.rglob("*") if x.is_file()}
        wanted = {x.relative_to(expected) for x in expected.rglob("*") if x.is_file()}
        if actual != wanted or any(
            (out / x).read_bytes() != (expected / x).read_bytes() for x in actual
        ):
            raise SystemExit("contract drift")
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
