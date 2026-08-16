#!/usr/bin/env python3
"""Generate the checked Prisoners state/territory replay and acceptance inputs.

The geometry and acceptance models below are deliberately separate. Geometry only
names source regions. Acceptance expectations are built from reviewed semantic
combinations and never from replay or execution output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tidy_orchestrator.artifacts import (  # noqa: E402
    canonical_json_bytes,
    domain_digest,
    sha256_digest,
)
from tidy_orchestrator.product_prototype import (  # noqa: E402
    COMBINATION_COVERAGE_SCHEMA,
)

FIX = ROOT / "fixtures/product-prototype"
RECORDED_AT = "2026-08-17T09:00:00+00:00"
JUR = ["ACT", "AUS", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"]
SEX = ["FEMALE", "MALE", "PERSONS"]
STATUS = ["INDIGENOUS", "NON_INDIGENOUS", "TOTAL"]
WORKBOOKS = {
    2021: (
        "workbooks/prisoners-australia-2021-batch-normalized.xlsx",
        "sha256:9a5be165da58005a2a31634568491645192785a96f27d9eee3c17e45175d1710",
        309532,
        True,
    ),
    2022: (
        "workbooks/prisoners-australia-2022-batch-normalized.xlsx",
        "sha256:a16a47e574d8da8d851f904f8ee60324cac870a89e76f4ea9114680bdde40a2b",
        327530,
        True,
    ),
    2023: (
        "workbooks/prisoners-australia-2023-batch-normalized.xlsx",
        "sha256:61366170db7a4da717332a3ad1ca9e11f884d95905bb4556f5f44ce51d31c66f",
        302509,
        True,
    ),
    2024: (
        "workbooks/prisoners-australia-2024.xlsx",
        "sha256:609a96a96e2e359ae3e534252bcb1a6b6a329eb91fcf289834d1014dc61273d1",
        279279,
        False,
    ),
    2025: (
        "workbooks/prisoners-australia-2025-batch-normalized.xlsx",
        "sha256:007a1c21fc2a2b256cbde672405a4710edcac85eff035949f403ca3fbed6ab6e",
        169355,
        True,
    ),
}

FAMILIES = {
    "state-selected-characteristics-time-series": {
        "tableFamilyId": "state-selected-characteristics-time-series",
        "years": [2021, 2022, 2023, 2024, 2025],
        "sheets": {
            2021: "Table_15",
            2022: "Table_15",
            2023: "Table_15",
            2024: "Table 15",
            2025: "Table 16",
        },
        "yearCounts": [792, 792, 792, 792, 900],
        "values": {
            2021: "region-010",
            2022: "region-010",
            2023: "region-010",
            2024: "region-010",
            2025: "region-010",
        },
        "dimensions": {
            2021: [
                ("reference period", ["region-030"], "W"),
                ("state or territory", ["region-031"], "WNW"),
                ("prisoner statistic", ["region-032"], "N"),
                ("statistic basis", ["region-033"], "N"),
            ],
            2022: [
                ("reference period", ["region-030"], "W"),
                ("state or territory", ["region-031"], "WNW"),
                ("prisoner statistic", ["region-032"], "N"),
                ("statistic basis", ["region-033"], "N"),
            ],
            2023: [
                ("reference period", ["region-030"], "W"),
                ("state or territory", ["region-031"], "WNW"),
                ("prisoner statistic", ["region-032"], "N"),
                ("statistic basis", ["region-033"], "N"),
            ],
            2024: [
                ("reference period", ["region-030"], "W"),
                ("state or territory", ["region-031"], "WNW"),
                ("prisoner statistic", ["region-032"], "N"),
                ("statistic basis", ["region-033"], "N"),
            ],
            2025: [
                ("reference period", ["region-030"], "W"),
                ("state or territory", ["region-031"], "WNW"),
                (
                    "prisoner statistic",
                    [
                        "region-062",
                        "region-063",
                        "region-064",
                        "region-065",
                        "region-066",
                        "region-067",
                        "region-068",
                        "region-040",
                        "region-041",
                        "region-042",
                    ],
                    "N",
                ),
                ("statistic basis", ["region-061"], "N"),
            ],
        },
        "valueBands": {
            2021: [
                "B8:I18",
                "B20:I30",
                "B32:I42",
                "B44:I54",
                "B56:I66",
                "B68:I78",
                "B80:I90",
                "B92:I102",
                "B104:I114",
            ],
            2022: [
                "B8:I18",
                "B20:I30",
                "B32:I42",
                "B44:I54",
                "B56:I66",
                "B68:I78",
                "B80:I90",
                "B92:I102",
                "B104:I114",
            ],
            2023: [
                "B8:I18",
                "B20:I30",
                "B32:I42",
                "B44:I54",
                "B56:I66",
                "B68:I78",
                "B80:I90",
                "B92:I102",
                "B104:I114",
            ],
            2024: [
                "B8:I18",
                "B20:I30",
                "B32:I42",
                "B44:I54",
                "B56:I66",
                "B68:I78",
                "B80:I90",
                "B92:I102",
                "B104:I114",
            ],
            2025: [
                "B8:K17",
                "B19:K28",
                "B30:K39",
                "B41:K50",
                "B52:K61",
                "B63:K72",
                "B74:K83",
                "B85:K94",
                "B96:K105",
            ],
        },
    },
    "state-sex-by-indigenous-status": {
        "tableFamilyId": "state-sex-by-indigenous-status",
        "years": [2021, 2022, 2023, 2024, 2025],
        "sheets": {
            2021: "Table_17",
            2022: "Table_17",
            2023: "Table_17",
            2024: "Table 17",
            2025: "Table 17",
        },
        "yearCounts": [189, 189, 189, 189, 270],
        "values": {y: "region-001" for y in range(2021, 2026)},
        "dimensions": {
            2021: [
                ("indigenous status", ["region-011", "region-014", "region-015"], "W"),
                ("rate basis", ["region-011", "region-014", "region-015"], "W"),
                ("state or territory", ["region-012"], "N"),
                ("sex", ["region-016", "region-017"], "WNW"),
                ("statistic basis", ["region-013"], "WNW"),
            ],
            2022: [
                ("indigenous status", ["region-011", "region-014", "region-015"], "W"),
                ("rate basis", ["region-011", "region-014", "region-015"], "W"),
                ("state or territory", ["region-012"], "N"),
                ("sex", ["region-016", "region-017"], "WNW"),
                ("statistic basis", ["region-013"], "WNW"),
            ],
            2023: [
                ("indigenous status", ["region-011", "region-014", "region-015"], "W"),
                ("rate basis", ["region-011", "region-014", "region-015"], "W"),
                ("state or territory", ["region-012"], "N"),
                ("sex", ["region-016", "region-017"], "WNW"),
                ("statistic basis", ["region-013"], "WNW"),
            ],
            2024: [
                ("indigenous status", ["region-011"], "W"),
                ("rate basis", ["region-011"], "W"),
                ("state or territory", ["region-012"], "N"),
                ("sex", ["region-018", "region-019"], "WNW"),
                ("statistic basis", ["region-013"], "WNW"),
            ],
            2025: [
                ("indigenous status", ["region-014"], "W"),
                ("rate basis", ["region-014"], "W"),
                ("state or territory", ["region-015"], "N"),
                ("sex", ["region-017", "region-018", "region-019"], "WNW"),
                ("statistic basis", ["region-016"], "WNW"),
            ],
        },
        "valueBands": {
            2021: [
                "B8:J10",
                "B13:J15",
                "B18:J20",
                "B23:J24",
                "B27:J28",
                "B31:J32",
                "B35:J36",
                "B39:J40",
                "B43:J44",
            ],
            2022: [
                "B8:J10",
                "B13:J15",
                "B18:J20",
                "B23:J24",
                "B27:J28",
                "B31:J32",
                "B35:J36",
                "B39:J40",
                "B43:J44",
            ],
            2023: [
                "B8:J10",
                "B13:J15",
                "B18:J20",
                "B23:J24",
                "B27:J28",
                "B31:J32",
                "B35:J36",
                "B39:J40",
                "B43:J44",
            ],
            2024: [
                "B8:J10",
                "B12:J14",
                "B16:J18",
                "B21:J22",
                "B24:J25",
                "B27:J28",
                "B31:J32",
                "B34:J35",
                "B37:J38",
            ],
            2025: [
                "B8:J10",
                "B12:J14",
                "B16:J18",
                "B21:J23",
                "B25:J27",
                "B29:J31",
                "B34:J35",
                "B37:J38",
                "B40:J41",
                "B44:J45",
                "B47:J48",
                "B50:J51",
            ],
        },
    },
    "state-age-standardised-rate-by-indigenous-status": {
        "tableFamilyId": "state-age-standardised-rate-by-indigenous-status",
        "years": [2021, 2022, 2023, 2024, 2025],
        "sheets": {
            2021: "Table_18",
            2022: "Table_18",
            2023: "Table_18",
            2024: "Table 18",
            2025: "Table 19",
        },
        "yearCounts": [297, 297, 297, 297, 270],
    },
    "state-crude-imprisonment-rate": {
        "tableFamilyId": "state-crude-imprisonment-rate",
        "years": [2021, 2022, 2023, 2024],
        "sheets": {
            2021: "Table_19",
            2022: "Table_19",
            2023: "Table_19",
            2024: "Table 19",
        },
        "yearCounts": [99, 99, 99, 99],
    },
    "state-crude-rate-by-indigenous-status": {
        "tableFamilyId": "state-crude-rate-by-indigenous-status",
        "years": [2021, 2022, 2023, 2024, 2025],
        "sheets": {
            2021: "Table_20",
            2022: "Table_20",
            2023: "Table_20",
            2024: "Table 20",
            2025: "Table 18",
        },
        "yearCounts": [297, 297, 297, 297, 270],
    },
}
for family in (
    "state-age-standardised-rate-by-indigenous-status",
    "state-crude-rate-by-indigenous-status",
):
    f = FAMILIES[family]
    f["values"] = {y: "region-004" for y in f["years"]}
    f["dimensions"] = {}
    f["valueBands"] = {}
    for y in f["years"]:
        if y == 2025 and family == "state-crude-rate-by-indigenous-status":
            ids = ("region-017", "region-018", "region-019")
        else:
            ids = ("region-012", "region-013", "region-014")
        f["dimensions"][y] = [
            ("reference period", [ids[0]], "W"),
            ("state or territory", [ids[1]], "N"),
            ("indigenous status", [ids[2]], "WNW"),
            ("rate basis", [ids[2]], "WNW"),
        ]
        f["valueBands"][y] = (
            ["B7:J17", "B19:J29", "B31:J41"]
            if y < 2025
            else (["B7:J16", "B18:J27", "B29:J38"])
        )
f = FAMILIES["state-crude-imprisonment-rate"]
f["values"] = {y: "region-001" for y in f["years"]}
f["dimensions"] = {
    y: [
        ("reference period", ["region-003"], "W"),
        ("state or territory", ["region-004"], "N"),
    ]
    for y in f["years"]
}
f["valueBands"] = {y: ["B6:J16"] for y in f["years"]}

JUR_ALIASES = {
    "NSW": "NSW",
    "New South Wales": "NSW",
    "NEW SOUTH WALES": "NSW",
    "Vic.": "VIC",
    "Vic": "VIC",
    "Victoria": "VIC",
    "VICTORIA": "VIC",
    "Qld": "QLD",
    "Qld.": "QLD",
    "Queensland": "QLD",
    "QUEENSLAND": "QLD",
    "SA": "SA",
    "South Australia": "SA",
    "SOUTH AUSTRALIA": "SA",
    "WA": "WA",
    "Western Australia": "WA",
    "WESTERN AUSTRALIA": "WA",
    "Tas.": "TAS",
    "Tasmania": "TAS",
    "TASMANIA": "TAS",
    "NT": "NT",
    "Northern Territory": "NT",
    "NORTHERN TERRITORY": "NT",
    "ACT": "ACT",
    "Australian Capital Territory": "ACT",
    "AUSTRALIAN CAPITAL TERRITORY": "ACT",
    "Aust.": "AUS",
    "Australia": "AUS",
    "AUSTRALIA": "AUS",
}
STATUS_ALIASES = {
    "ABORIGINAL AND TORRES STRAIT ISLANDER": "INDIGENOUS",
    "Aboriginal and Torres Strait Islander": "INDIGENOUS",
    "NON-INDIGENOUS": "NON_INDIGENOUS",
    "Non-Indigenous": "NON_INDIGENOUS",
    "Total": "TOTAL",
    "TOTAL": "TOTAL",
    "Crude": "TOTAL",
    "Age-standardised": "TOTAL",
    "RATIO OF ABORIGINAL AND TORRES STRAIT ISLANDER TO NON-INDIGENOUS": "TOTAL",
    "Ratio of Aboriginal and Torres Strait Islander to non-Indigenous": "TOTAL",
}
PERIOD_ALIASES = {str(y): f"{y}-06-30" for y in range(2011, 2026)}
SEX_ALIASES = {
    "Males": "MALE",
    "Male": "MALE",
    "Females": "FEMALE",
    "Female": "FEMALE",
    "Persons": "PERSONS",
}


def digest_combinations(dimensions: list[str], combos: list[tuple[str, ...]]) -> str:
    return domain_digest(
        COMBINATION_COVERAGE_SCHEMA,
        {"dimensions": dimensions, "combinations": sorted([list(c) for c in combos])},
    )


def measure(
    mid: str,
    unit: str,
    dims: list[str],
    yearly: dict[int, list[tuple[str, ...]]],
    selection: dict[str, list[str]] | None = None,
    missing: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {"id": mid, "unitId": unit, "numeric": True, "minimum": 0}
    if selection is not None:
        item["selection"] = {"conditions": selection, "dimensionOverrides": {}}
    years = sorted(yearly)
    if set(years) != set(CURRENT_YEARS):
        item["applicableYears"] = [str(y) for y in years]
    item["expectedCombinationCountsByYear"] = {str(y): len(yearly[y]) for y in years}
    item["expectedDimensionsByYear"] = {
        str(y): {d: sorted({c[i] for c in yearly[y]}) for i, d in enumerate(dims)}
        for y in years
    }
    item["expectedCombinationDigestsByYear"] = {
        str(y): digest_combinations(dims, yearly[y]) for y in years
    }
    if missing:
        item["missingValues"] = {
            "n.p.": "suppressed",
            "np": "suppressed",
            "n.a.": "not_applicable",
            "n.a": "not_applicable",
            "na": "not_applicable",
        }
    return item


def base_contract(
    fid: str,
    dims: list[str],
    aliases: dict[str, dict[str, str]],
    measures: list[dict[str, Any]],
    years: list[int],
    counts: list[int],
    vintage: bool,
) -> dict[str, Any]:
    expected: dict[str, Any] = {
        "minimumRows": min(counts),
        "maximumRows": max(counts),
        "sourceColumns": {
            "minimum": 8 if fid.startswith("state-selected") else 9,
            "maximum": 10 if fid.startswith("state-selected") else 9,
        },
    }
    field = {
        "jurisdiction": "jurisdictions",
        "observation_period": "observationPeriods",
        "prisoner_statistic": "prisonerStatistics",
        "statistic_basis": "statisticBases",
        "sex": "sexes",
        "indigenous_status": "indigenousStatuses",
        "rate_basis": "rateBases",
    }
    for i, d in enumerate(dims):
        vals = {
            str(y): sorted(
                {
                    combo[i]
                    for m in measures
                    for yy, combos in ((int(k), v) for k, v in _year_combos(m).items())
                    if yy == y
                    for combo in combos
                }
            )
            for y in years
        }
        expected[field[d] + "ByYear"] = vals
    unique = ["publication_vintage_date"] if vintage else []
    unique += (
        ["reference_date"]
        + [
            {
                "jurisdiction": "jurisdiction_id",
                "observation_period": "observation_period_id",
                "prisoner_statistic": "prisoner_statistic_id",
                "statistic_basis": "statistic_basis_id",
                "sex": "sex_id",
                "indigenous_status": "indigenous_status_id",
                "rate_basis": "rate_basis_id",
            }[d]
            for d in dims
            if not (vintage and d == "observation_period")
        ]
        + ["measure_id"]
    )
    out = {
        "schemaVersion": "tidy.table-family-acceptance/v1",
        "contractId": f"prisoners-{fid}-v1",
        "tableFamilyId": fid,
        "measures": measures,
        "requiredDimensions": dims,
        "dimensionHeaders": {
            d: [
                {
                    "jurisdiction": "state or territory",
                    "observation_period": "reference period",
                    "prisoner_statistic": "prisoner statistic",
                    "statistic_basis": "statistic basis",
                    "sex": "sex",
                    "indigenous_status": "indigenous status",
                    "rate_basis": "rate basis",
                }[d]
            ]
            for d in dims
        },
        "aliases": aliases,
        "uniqueKey": unique,
        "expected": expected,
        "allowedExecutionWarnings": [],
        "totalEquations": [],
        "totalValidation": "not_applicable",
        "automaticAcceptance": True,
        "trainingEligibility": False,
    }
    if vintage:
        out.update(
            {
                "referenceDateDimension": "observation_period",
                "preservePublicationVintage": True,
            }
        )
    return out


def _year_combos(m: dict[str, Any]) -> dict[str, list[tuple[str, ...]]]:
    return m.pop("__combos") if "__combos" in m else COMBO_CACHE[id(m)]


COMBO_CACHE: dict[int, dict[str, list[tuple[str, ...]]]] = {}


def remember(
    m: dict[str, Any], yearly: dict[int, list[tuple[str, ...]]]
) -> dict[str, Any]:
    COMBO_CACHE[id(m)] = {str(k): v for k, v in yearly.items()}
    return m


def contract_selected() -> dict[str, Any]:
    global CURRENT_YEARS
    CURRENT_YEARS = [2021, 2022, 2023, 2024, 2025]
    dims = [
        "jurisdiction",
        "observation_period",
        "prisoner_statistic",
        "statistic_basis",
    ]
    stats_old = {
        "TOTAL_PRISONERS": "NUMBER_OR_RATE",
        "MALE_RATE": "NUMBER_OR_RATE",
        "FEMALE_RATE": "NUMBER_OR_RATE",
        "MEAN_AGE": "YEARS",
        "MEDIAN_AGE": "YEARS",
        "INDIGENOUS": "PROPORTION",
        "KNOWN_PRIOR_IMPRISONMENT": "PROPORTION",
        "UNSENTENCED": "PROPORTION",
    }
    stats_new = {
        "TOTAL_PRISONERS": "NUMBER",
        "MALE": "NUMBER",
        "FEMALE": "NUMBER",
        "INDIGENOUS": "NUMBER",
        "NON_INDIGENOUS": "NUMBER",
        "KNOWN_PRIOR_IMPRISONMENT": "PROPORTION",
        "UNSENTENCED": "PROPORTION",
        "MALE_RATE": "RATE",
        "FEMALE_RATE": "RATE",
        "TOTAL_RATE": "RATE",
    }
    periods = {y: list(range(y - 10, y + 1)) for y in range(2021, 2025)}
    periods[2025] = list(range(2016, 2026))
    allc = {
        y: [
            (j, f"{p}-06-30", s, b)
            for j in JUR
            for p in periods[y]
            for s, b in (stats_new if y == 2025 else stats_old).items()
        ]
        for y in CURRENT_YEARS
    }

    def pick(wanted: set[str], basis: set[str] | None = None, years=CURRENT_YEARS):
        return {
            y: [
                c
                for c in allc[y]
                if c[2] in wanted and (basis is None or c[3] in basis)
            ]
            for y in years
        }

    defs = [
        (
            "prisoner-count",
            "person",
            {"TOTAL_PRISONERS", "MALE", "FEMALE", "INDIGENOUS", "NON_INDIGENOUS"},
            {"NUMBER_OR_RATE", "NUMBER"},
            CURRENT_YEARS,
        ),
        (
            "imprisonment-rate",
            "persons-per-100000-adult-population",
            {"MALE_RATE", "FEMALE_RATE", "TOTAL_RATE"},
            None,
            CURRENT_YEARS,
        ),
        ("mean-age", "year", {"MEAN_AGE"}, None, [2021, 2022, 2023, 2024]),
        ("median-age", "year", {"MEDIAN_AGE"}, None, [2021, 2022, 2023, 2024]),
        (
            "prisoner-proportion",
            "percent",
            {"INDIGENOUS", "KNOWN_PRIOR_IMPRISONMENT", "UNSENTENCED"},
            {"PROPORTION"},
            CURRENT_YEARS,
        ),
    ]
    ms = []
    for mid, u, w, b, ys in defs:
        yc = pick(w, b, ys)
        sel = {"prisoner_statistic": sorted(w)}
        if b:
            sel["statistic_basis"] = sorted(b)
        ms.append(remember(measure(mid, u, dims, yc, sel), yc))
    stat_alias = {
        "Total prisoners": "TOTAL_PRISONERS",
        "Total prisoners (d)": "TOTAL_PRISONERS",
        "Male imprisonment rate": "MALE_RATE",
        "Male imprisonment rate (e)": "MALE_RATE",
        "Female imprisonment rate": "FEMALE_RATE",
        "Female imprisonment rate (e)": "FEMALE_RATE",
        "Total imprisonment rate (e)": "TOTAL_RATE",
        "Mean age": "MEAN_AGE",
        "Median age": "MEDIAN_AGE",
        "Aboriginal and Torres Strait Islander": "INDIGENOUS",
        "Known prior imprisonment": "KNOWN_PRIOR_IMPRISONMENT",
        "Unsentenced": "UNSENTENCED",
        "Males": "MALE",
        "Females": "FEMALE",
        "Non-Indigenous": "NON_INDIGENOUS",
    }
    basis = {
        "no.": "NUMBER_OR_RATE",
        "years": "YEARS",
        "%": "PROPORTION",
        "Number": "NUMBER",
        "Total prisoners": "NUMBER",
        "Males": "NUMBER",
        "Females": "NUMBER",
        "Aboriginal and Torres Strait Islander": "NUMBER",
        "Non-Indigenous": "NUMBER",
        "Proportion (%)": "PROPORTION",
        "Known prior imprisonment": "PROPORTION",
        "Unsentenced": "PROPORTION",
        "Male imprisonment rate (e)": "RATE",
        "Female imprisonment rate (e)": "RATE",
        "Total imprisonment rate (e)": "RATE",
    }
    return base_contract(
        FAMILIES["state-selected-characteristics-time-series"]["tableFamilyId"],
        dims,
        {
            "jurisdiction": JUR_ALIASES,
            "observation_period": PERIOD_ALIASES,
            "prisoner_statistic": stat_alias,
            "statistic_basis": basis,
        },
        ms,
        CURRENT_YEARS,
        FAMILIES["state-selected-characteristics-time-series"]["yearCounts"],
        True,
    )


def contract_sex_status() -> dict[str, Any]:
    global CURRENT_YEARS
    CURRENT_YEARS = [2021, 2022, 2023, 2024, 2025]
    dims = ["jurisdiction", "sex", "indigenous_status", "statistic_basis", "rate_basis"]
    yearly: dict[str, dict[int, list[tuple[str, ...]]]] = {
        k: {} for k in ("count", "crude", "age", "ratio")
    }
    for y in CURRENT_YEARS:
        if y == 2025:
            yearly["count"][y] = [
                (j, s, i, "COUNT", "NOT_APPLICABLE")
                for j in JUR
                for s in SEX
                for i in STATUS
            ]
        yearly["crude"][y] = [
            (j, s, i, "CRUDE", "NOT_APPLICABLE")
            for j in JUR
            for s in SEX
            for i in STATUS
        ]
        yearly["age"][y] = [
            (j, s, i, "AGE_STANDARDISED", "NOT_APPLICABLE")
            for j in JUR
            for s in SEX
            for i in STATUS[:2]
        ]
        yearly["ratio"][y] = [
            (j, s, "TOTAL", "RATE_RATIO", b)
            for j in JUR
            for s in SEX
            for b in ("CRUDE", "AGE_STANDARDISED")
        ]
    defs = [
        ("prisoner-count", "person", "count"),
        ("crude-imprisonment-rate", "persons-per-100000-adult-population", "crude"),
        (
            "age-standardised-imprisonment-rate",
            "persons-per-100000-adult-population",
            "age",
        ),
        ("indigenous-to-non-indigenous-rate-ratio", "ratio", "ratio"),
    ]
    codes = {
        "count": "COUNT",
        "crude": "CRUDE",
        "age": "AGE_STANDARDISED",
        "ratio": "RATE_RATIO",
    }
    ms = []
    for mid, u, k in defs:
        yc = yearly[k]
        m = measure(mid, u, dims, yc, {"statistic_basis": [codes[k]]}, missing=True)
        ms.append(remember(m, yc))
    stat = {
        "CRUDE RATE": "CRUDE",
        "Crude rate": "CRUDE",
        "Crude rate (d)": "CRUDE",
        "AGE STANDARDISED RATE": "AGE_STANDARDISED",
        "AGE STANDARDISED RATE ": "AGE_STANDARDISED",
        "Age standardised rate": "AGE_STANDARDISED",
        "Age standardised rate (e)(f)": "AGE_STANDARDISED",
        "RATIO OF ABORIGINAL AND TORRES STRAIT ISLANDER RATES TO NON-INDIGENOUS RATES": "RATE_RATIO",  # noqa: E501
        "Ratio of Aboriginal and Torres Strait Islander rates to non-Indigenous rates": "RATE_RATIO",  # noqa: E501
        "Number": "COUNT",
    }
    rb = {
        "Aboriginal and Torres Strait Islander": "NOT_APPLICABLE",
        "Non-Indigenous": "NOT_APPLICABLE",
        "Total": "NOT_APPLICABLE",
        "Crude": "CRUDE",
        "Age-standardised": "AGE_STANDARDISED",
    }
    contract = base_contract(
        FAMILIES["state-sex-by-indigenous-status"]["tableFamilyId"],
        dims,
        {
            "jurisdiction": JUR_ALIASES,
            "sex": SEX_ALIASES,
            "indigenous_status": STATUS_ALIASES,
            "statistic_basis": stat,
            "rate_basis": rb,
        },
        ms,
        CURRENT_YEARS,
        FAMILIES["state-sex-by-indigenous-status"]["yearCounts"],
        False,
    )
    contract["preserveRawValueText"] = True
    return contract


def contract_status_series(fid: str, basis: str) -> dict[str, Any]:
    global CURRENT_YEARS
    CURRENT_YEARS = [2021, 2022, 2023, 2024, 2025]
    dims = ["jurisdiction", "observation_period", "indigenous_status", "rate_basis"]
    periods = {y: list(range(y - 10, y + 1)) for y in range(2021, 2025)}
    periods[2025] = list(range(2016, 2026))
    rate = {
        y: [
            (j, f"{p}-06-30", i, basis)
            for j in JUR
            for p in periods[y]
            for i in STATUS[:2]
        ]
        for y in CURRENT_YEARS
    }
    ratio = {
        y: [(j, f"{p}-06-30", "TOTAL", "RATE_RATIO") for j in JUR for p in periods[y]]
        for y in CURRENT_YEARS
    }
    rate_id = (
        "age-standardised-imprisonment-rate"
        if basis == "AGE_STANDARDISED"
        else "crude-imprisonment-rate"
    )
    m1 = remember(
        measure(
            rate_id,
            "persons-per-100000-adult-population",
            dims,
            rate,
            {"rate_basis": [basis]},
        ),
        rate,
    )
    m2 = remember(
        measure(
            "indigenous-to-non-indigenous-rate-ratio",
            "ratio",
            dims,
            ratio,
            {"rate_basis": ["RATE_RATIO"]},
        ),
        ratio,
    )
    rb = {
        "ABORIGINAL AND TORRES STRAIT ISLANDER": basis,
        "Aboriginal and Torres Strait Islander": basis,
        "NON-INDIGENOUS": basis,
        "Non-Indigenous": basis,
        "RATIO OF ABORIGINAL AND TORRES STRAIT ISLANDER TO NON-INDIGENOUS": "RATE_RATIO",  # noqa: E501
        "Ratio of Aboriginal and Torres Strait Islander to non-Indigenous": "RATE_RATIO",  # noqa: E501
    }
    return base_contract(
        fid,
        dims,
        {
            "jurisdiction": JUR_ALIASES,
            "observation_period": PERIOD_ALIASES,
            "indigenous_status": STATUS_ALIASES,
            "rate_basis": rb,
        },
        [m1, m2],
        CURRENT_YEARS,
        FAMILIES[fid]["yearCounts"],
        True,
    )


def contract_crude() -> dict[str, Any]:
    global CURRENT_YEARS
    CURRENT_YEARS = [2021, 2022, 2023, 2024]
    dims = ["jurisdiction", "observation_period"]
    yc = {
        y: [(j, f"{p}-06-30") for j in JUR for p in range(y - 10, y + 1)]
        for y in CURRENT_YEARS
    }
    m = remember(
        measure(
            "crude-imprisonment-rate", "persons-per-100000-adult-population", dims, yc
        ),
        yc,
    )
    return base_contract(
        "state-crude-imprisonment-rate",
        dims,
        {"jurisdiction": JUR_ALIASES, "observation_period": PERIOD_ALIASES},
        [m],
        CURRENT_YEARS,
        [99] * 4,
        True,
    )


def write(path: Path, data: bytes, check: bool, changed: list[str]):
    if check:
        if not path.is_file() or path.read_bytes() != data:
            changed.append(path.relative_to(ROOT).as_posix())
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    changed = []
    geometry = {
        "schemaVersion": "tidy.prisoners-state-cluster-geometry/v1",
        "recordedAt": RECORDED_AT,
        "authority": "human-authored-reviewed-physical-geometry",
        "families": [],
    }
    audit = {
        "schemaVersion": "tidy.prisoners-state-cluster-acceptance-audit/v1",
        "recordedAt": RECORDED_AT,
        "authority": "independent-of-replay-output",
        "sourceAuthority": "committed-workbook-cells",
        "handoffCorrection": {
            "year": 2025,
            "sheet": "Table 16",
            "publishedGrid": "B:K",
            "publishedColumns": 10,
            "expectedRows": 900,
            "familyRows": 4068,
            "clusterRows": 8406,
            "reason": (
                "The published 2025 grid replaces mean/median age and Indigenous "
                "proportion with five count, two proportion, and three rate columns."
            ),
        },
        "families": [],
    }
    contracts = {
        "state-selected-characteristics-time-series": contract_selected(),
        "state-sex-by-indigenous-status": contract_sex_status(),
        "state-age-standardised-rate-by-indigenous-status": contract_status_series(
            "state-age-standardised-rate-by-indigenous-status", "AGE_STANDARDISED"
        ),
        "state-crude-imprisonment-rate": contract_crude(),
        "state-crude-rate-by-indigenous-status": contract_status_series(
            "state-crude-rate-by-indigenous-status", "CRUDE"
        ),
    }
    for fid, f in FAMILIES.items():
        years = f["years"]
        geom_members = []
        cohort = []
        for y in years:
            map_obj = {
                "version": "semantic-table-map-v1",
                "table": {
                    "name": f"Prisoners in Australia — {fid} — {y}",
                    "values": {"name": "published value", "regions": [f["values"][y]]},
                    "dimensions": [
                        {
                            "name": n,
                            "memberRegions": r,
                            "direction": d,
                            "captionHints": [],
                        }
                        for n, r, d in f["dimensions"][y]
                    ],
                },
            }
            map_bytes = canonical_json_bytes(map_obj) + b"\n"
            physical = (
                f["sheets"][y].replace("Table_", "table-").replace("Table ", "table-")
            )
            replay = f"replay/prisoners-australia-{physical}-{y}.response.txt"
            write(FIX / replay, map_bytes, a.check, changed)
            wp, wd, wl, norm = WORKBOOKS[y]
            entry = {
                "year": y,
                "referenceDate": f"{y}-06-30",
                "path": wp,
                "contentDigest": wd,
                "byteLength": wl,
                "sheet": f["sheets"][y],
                "replayResponse": {
                    "path": replay,
                    "contentDigest": sha256_digest(map_bytes),
                    "byteLength": len(map_bytes),
                    "historicalModel": "human-authored/deterministic-geometry-v1",
                    "acceptanceAuthority": False,
                },
            }
            if norm:
                entry["normalization"] = "trim-pathological-styled-blank-cells-v1"
            cohort.append(entry)
            geom_members.append(
                {
                    "year": y,
                    "workbookPath": wp,
                    "workbookDigest": wd,
                    "sheet": f["sheets"][y],
                    "valueBands": f["valueBands"][y],
                    "semanticMap": map_obj,
                }
            )
        cohort_obj = {
            "schemaVersion": "tidy.product-prototype-cohort/v1",
            "cohortId": f"prisoners-australia-{fid}",
            "publicationId": "prisoners-australia",
            "tableFamilyId": f["tableFamilyId"],
            "generation": {
                "provider": "openai-codex",
                "model": "openai-codex/gpt-5.6-luna",
                "reasoning": "high",
                "promptContract": "cell-role-semantic-map-v13-adjacent-year-aware",
                "maximumCalls": 2 * len(years),
                "maximumCostUsd": 2.0,
                "correctionPolicy": "one-pre-execution-compilation-correction-only",
            },
            "acceptanceContract": f"acceptance/prisoners-{fid}-v1.json",
            "workbooks": cohort,
        }
        write(
            FIX / f"prisoners-{fid}.json",
            json.dumps(cohort_obj, indent=2, ensure_ascii=False).encode() + b"\n",
            a.check,
            changed,
        )
        write(
            FIX / f"acceptance/prisoners-{fid}-v1.json",
            json.dumps(contracts[fid], indent=2, ensure_ascii=False).encode() + b"\n",
            a.check,
            changed,
        )
        geometry["families"].append({"familyId": fid, "members": geom_members})
        audit["families"].append(
            {
                "familyId": fid,
                "years": years,
                "expectedYearCounts": f["yearCounts"],
                "expectedCanonicalCount": sum(f["yearCounts"]),
                "totalValidation": "not_applicable",
                "preservePublicationVintage": fid != "state-sex-by-indigenous-status",
                "measureCounts": {
                    m["id"]: sum(m["expectedCombinationCountsByYear"].values())
                    for m in contracts[fid]["measures"]
                },
            }
        )
    write(
        FIX / "prisoners-state-cluster-geometry-v1.json",
        json.dumps(geometry, indent=2, ensure_ascii=False).encode() + b"\n",
        a.check,
        changed,
    )
    write(
        FIX / "prisoners-state-cluster-acceptance-audit-v1.json",
        json.dumps(audit, indent=2, ensure_ascii=False).encode() + b"\n",
        a.check,
        changed,
    )
    if changed:
        print("generated artifacts differ:\n" + "\n".join(changed))
        return 1
    print("checked" if a.check else "generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
