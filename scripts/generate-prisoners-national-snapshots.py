#!/usr/bin/env python3
"""Generate reviewed national Prisoners snapshot maps and acceptance inputs.

Physical geometry and acceptance combinations are intentionally built independently.
The 2025 Table 7/8 workbook derivative is formatting-only and bounded to A:R.
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
YEARS = list(range(2021, 2026))
SOURCE_DIGESTS = {
    2021: "sha256:264b018d9ab5584ebc44774cf349283c072b0eb1304a0b865dadffe40d5d2d7a",
    2022: "sha256:0b6f14ccf90fded702181e26e023262afbb01016986c630e8bf27648fd7828be",
    2023: "sha256:6e640bf65399eaa405e48acda86be9403bc2b8196ff2ccd926906a2e76527e2b",
    2024: "sha256:23f0677e705e9bf88bf4cffed42d1f263772dd38bd2409d2a000d1f9fc79667e",
    2025: "sha256:28af3897513142d7080f02a0cee4a21d763f1b633aaf8e0cee9e53561f0a317c",
}
SOURCE_LENGTHS = {2021: 195239, 2022: 212754, 2023: 209379, 2024: 180975, 2025: 125447}
BOUNDED_2025 = (
    "workbooks/prisoners-australia-2025-national-snapshots-bounded.xlsx",
    "sha256:d6e2f3e3e2a7a86b990fd89066e8f5f3d4bea5d2d217925083d27eb3a36a021a",
    115314,
)
OFFENCES = [f"ANZSOC_{i:02d}" for i in range(1, 17)]
OFFENCES_TOTAL = [*OFFENCES, "TOTAL"]
OFFENCES_TABLE1 = [*OFFENCES, "POST_SENTENCE", "TOTAL"]
AGES = (
    ["AGE_18_OR_YOUNGER", "AGE_19"]
    + [f"AGE_{a}_{a + 4}" for a in range(20, 65, 5)]
    + ["AGE_65_PLUS", "TOTAL"]
)
SEXES = ["FEMALE", "MALE", "PERSONS"]
STAT = ["NUMBER", "PROPORTION"]
STATUS = ["INDIGENOUS", "NON_INDIGENOUS", "TOTAL"]

FAMILIES: dict[str, dict[str, Any]] = {
    "national-selected-characteristics-by-offence-charge": {
        "tables": {y: 1 for y in YEARS},
        "counts": [450, 450, 449, 449, 538],
        "valueBands": {
            **{
                y: [
                    "B7:S7",
                    "B9:S10",
                    "B12:S14",
                    "B16:S18",
                    "B20:S21",
                    "B23:S27",
                    "B30:S31",
                    "B33:S35",
                    "B37:S39",
                    "B41:S43",
                ]
                for y in range(2021, 2025)
            },
            2025: [
                "B7:S7",
                "B9:S10",
                "B12:S14",
                "B16:S18",
                "B20:S21",
                "B23:S27",
                "B29:S33",
                "B36:S37",
                "B39:S41",
                "B43:S45",
                "B47:S49",
            ],
        },
        "maps": {
            2021: (
                "region-001",
                [
                    (
                        "most serious offence or charge",
                        ["region-023", "region-024"],
                        "N",
                    ),
                    ("statistic basis", ["region-026"], "WNW"),
                    ("characteristic group", ["region-029", "region-027"], "WNW"),
                    (
                        "characteristic category",
                        ["region-022", "region-027", "region-028"],
                        "W",
                    ),
                ],
            ),
            2022: (
                "region-001",
                [
                    ("most serious offence or charge", ["region-013"], "N"),
                    ("statistic basis", ["region-014"], "WNW"),
                    ("characteristic group", ["region-017", "region-015"], "WNW"),
                    (
                        "characteristic category",
                        ["region-012", "region-015", "region-016"],
                        "W",
                    ),
                ],
            ),
            2023: (
                "region-001",
                [
                    ("most serious offence or charge", ["region-013"], "N"),
                    ("statistic basis", ["region-014"], "WNW"),
                    ("characteristic group", ["region-017", "region-015"], "WNW"),
                    (
                        "characteristic category",
                        ["region-012", "region-015", "region-016"],
                        "W",
                    ),
                ],
            ),
            2024: (
                "region-001",
                [
                    (
                        "most serious offence or charge",
                        ["region-013", "region-014"],
                        "N",
                    ),
                    ("statistic basis", ["region-015"], "WNW"),
                    (
                        "characteristic group",
                        ["region-022", "region-023", "region-016"],
                        "WNW",
                    ),
                    (
                        "characteristic category",
                        ["region-012", "region-016", "region-017"],
                        "W",
                    ),
                ],
            ),
            2025: (
                "region-001",
                [
                    (
                        "most serious offence or charge",
                        ["region-014", "region-016"],
                        "N",
                    ),
                    ("statistic basis", ["region-017"], "WNW"),
                    (
                        "characteristic group",
                        ["region-015", "region-020", "region-018", "region-026"],
                        "WNW",
                    ),
                    (
                        "characteristic category",
                        ["region-013", "region-018", "region-019"],
                        "W",
                    ),
                ],
            ),
        },
    },
    "national-age-by-sex": {
        "tables": {y: 4 for y in YEARS},
        "counts": [117] * 5,
        "valueBands": {y: ["B7:J19"] for y in YEARS},
        "maps": {
            2021: (
                "region-001",
                [
                    ("sex", ["region-004"], "NNW"),
                    ("age group", ["region-002", "region-005"], "W"),
                    ("statistic basis", ["region-003"], "N"),
                ],
            ),
            2022: (
                "region-001",
                [
                    ("sex", ["region-004"], "NNW"),
                    ("age group", ["region-002", "region-005", "region-006"], "W"),
                    ("statistic basis", ["region-003"], "N"),
                ],
            ),
            2023: (
                "region-001",
                [
                    ("sex", ["region-004"], "NNW"),
                    ("age group", ["region-002", "region-005", "region-006"], "W"),
                    ("statistic basis", ["region-003"], "N"),
                ],
            ),
            2024: (
                "region-001",
                [
                    ("sex", ["region-005"], "NNW"),
                    (
                        "age group",
                        ["region-003", "region-004", "region-007", "region-012"],
                        "W",
                    ),
                    ("statistic basis", ["region-002", "region-006"], "N"),
                ],
            ),
            2025: (
                "region-001",
                [
                    ("sex", ["region-005"], "NNW"),
                    (
                        "age group",
                        ["region-003", "region-004", "region-007", "region-012"],
                        "W",
                    ),
                    ("statistic basis", ["region-002", "region-006"], "N"),
                ],
            ),
        },
    },
    "national-sex-offence-charge-by-indigenous-status": {
        "tables": {2021: 5, 2022: 5, 2023: 5, 2024: 5, 2025: 6},
        "counts": [306] * 5,
        "valueBands": {y: ["B8:G24", "B26:G42", "B44:G60"] for y in YEARS},
        "maps": {
            **{
                y: (
                    "region-001",
                    [
                        ("sex", ["region-008"], "WNW"),
                        (
                            "most serious offence or charge",
                            ["region-005", "region-009"],
                            "W",
                        ),
                        ("indigenous status", ["region-007"], "NNW"),
                        ("statistic basis", ["region-006"], "N"),
                    ],
                )
                for y in range(2021, 2024)
            },
            2024: (
                "region-001",
                [
                    ("sex", ["region-009", "region-014"], "WNW"),
                    (
                        "most serious offence or charge",
                        ["region-005", "region-008"],
                        "W",
                    ),
                    ("indigenous status", ["region-007"], "NNW"),
                    ("statistic basis", ["region-006"], "N"),
                ],
            ),
            2025: (
                "region-001",
                [
                    ("sex", ["region-009", "region-014"], "WNW"),
                    (
                        "most serious offence or charge",
                        ["region-005", "region-008"],
                        "W",
                    ),
                    ("indigenous status", ["region-007"], "NNW"),
                    ("statistic basis", ["region-006"], "N"),
                ],
            ),
        },
    },
    "national-age-by-offence-charge": {
        "tables": {2021: 6, 2022: 6, 2023: 6, 2024: 6, 2025: 7},
        "counts": [221] * 5,
        "valueBands": {y: ["B6:R18"] for y in YEARS},
        "maps": {
            **{
                y: (
                    "region-001",
                    [
                        ("age group", ["region-002", "region-005"], "W"),
                        (
                            "most serious offence or charge",
                            ["region-003", "region-004"],
                            "N",
                        ),
                    ],
                )
                for y in range(2021, 2024)
            },
            2024: (
                "region-001",
                [
                    ("age group", ["region-003", "region-004"], "W"),
                    ("most serious offence or charge", ["region-002"], "N"),
                ],
            ),
            2025: (
                "region-001",
                [
                    ("age group", ["region-003", "region-004"], "W"),
                    ("most serious offence or charge", ["region-002"], "N"),
                ],
            ),
        },
    },
    "national-country-of-birth-by-offence-charge": {
        "tables": {2021: 7, 2022: 7, 2023: 7, 2024: 7, 2025: 8},
        "counts": [221, 238, 221, 221, 238],
        "valueBands": {
            2021: ["B6:R18"],
            2022: ["B6:R19"],
            2023: ["B6:R18"],
            2024: ["B6:R18"],
            2025: ["B6:R19"],
        },
        "maps": {
            2021: (
                "region-001",
                [
                    ("country of birth", ["region-002", "region-005"], "W"),
                    (
                        "most serious offence or charge",
                        ["region-003", "region-004"],
                        "N",
                    ),
                ],
            ),
            2022: (
                "region-001",
                [
                    ("country of birth", ["region-002", "region-005"], "W"),
                    (
                        "most serious offence or charge",
                        ["region-003", "region-004"],
                        "N",
                    ),
                ],
            ),
            2023: (
                "region-001",
                [
                    ("country of birth", ["region-002", "region-005"], "W"),
                    (
                        "most serious offence or charge",
                        ["region-003", "region-004"],
                        "N",
                    ),
                ],
            ),
            2024: (
                "region-001",
                [
                    (
                        "country of birth",
                        ["region-003", "region-004", "region-009"],
                        "W",
                    ),
                    ("most serious offence or charge", ["region-002"], "N"),
                ],
            ),
            2025: (
                "region-001",
                [
                    (
                        "country of birth",
                        ["region-003", "region-008", "region-009"],
                        "W",
                    ),
                    ("most serious offence or charge", ["region-002"], "N"),
                ],
            ),
        },
    },
}

OFFENCE_ALIASES = {
    "01 Homicide and related offences": "ANZSOC_01",
    "02 Acts intended to cause injury": "ANZSOC_02",
    "03 Sexual assault and related offences": "ANZSOC_03",
    "04 Dangerous/ negligent acts": "ANZSOC_04",
    "04 Dangerous/negligent acts": "ANZSOC_04",
    "05 Abduction/ harassment": "ANZSOC_05",
    "05 Abduction/harassment": "ANZSOC_05",
    "06 Robbery/ extortion": "ANZSOC_06",
    "06 Robbery/extortion": "ANZSOC_06",
    "07 Unlawful entry with intent": "ANZSOC_07",
    "08 Theft": "ANZSOC_08",
    "09 Fraud/ deception": "ANZSOC_09",
    "09 Fraud/deception": "ANZSOC_09",
    "10 Illicit drug offences": "ANZSOC_10",
    "11 Weapons/ explosives": "ANZSOC_11",
    "11 Weapons/explosives": "ANZSOC_11",
    "12 Property damage and environmental pollution": "ANZSOC_12",
    "13 Public order offences": "ANZSOC_13",
    "14 Traffic and vehicle regulatory offences": "ANZSOC_14",
    "15 Offences against justice": "ANZSOC_15",
    "16 Miscellaneous offences": "ANZSOC_16",
    "Post-sentence detention": "POST_SENTENCE",
    "Post-sentence detention (d)": "POST_SENTENCE",
    "Total": "TOTAL",
    "TOTAL": "TOTAL",
    "Total (d)": "TOTAL",
    "Total (e)": "TOTAL",
    "Total (f)": "TOTAL",
    "Total (g)": "TOTAL",
}
AGE_ALIASES = {
    "18 years": "AGE_18_OR_YOUNGER",
    "18 years (d)": "AGE_18_OR_YOUNGER",
    "18 years (e)": "AGE_18_OR_YOUNGER",
    "19 years": "AGE_19",
    **{
        f"{a}–{a + 4} years": f"AGE_{a}_{a + 4}"  # noqa: RUF001 - source alias
        for a in range(20, 65, 5)
    },
    "65 years and over": "AGE_65_PLUS",
    "Total": "TOTAL",
    "TOTAL": "TOTAL",
    "Total (e)": "TOTAL",
    "Total (f)": "TOTAL",
}
SEX_ALIASES = {
    "MALES": "MALE",
    "Males": "MALE",
    "FEMALES": "FEMALE",
    "Females": "FEMALE",
    "PERSONS": "PERSONS",
    "Persons": "PERSONS",
    "Persons (b)": "PERSONS",
    "Persons (f)": "PERSONS",
}
STAT_ALIASES = {
    "NUMBER": "NUMBER",
    "Number": "NUMBER",
    "no.": "NUMBER",
    "%": "PROPORTION",
    "PROPORTION (%)": "PROPORTION",
    "Proportion (%)": "PROPORTION",
    "Imprisonment rate": "RATE",
    "Imprisonment rate (c)": "RATE",
}
STATUS_ALIASES = {
    "Aboriginal & Torres Strait Islander": "INDIGENOUS",
    "Aboriginal and Torres Strait Islander": "INDIGENOUS",
    "Non-Indigenous": "NON_INDIGENOUS",
    "Total": "TOTAL",
    "TOTAL": "TOTAL",
    "Total (d)": "TOTAL",
}
COUNTRY_ALIASES = {
    x.replace("_", " ").title(): x
    for x in [
        "AUSTRALIA",
        "NEW_ZEALAND",
        "VIETNAM",
        "UNITED_KINGDOM",
        "SUDAN",
        "CHINA",
        "LEBANON",
        "MALAYSIA",
        "INDIA",
        "IRAN",
        "IRAQ",
        "PHILIPPINES",
        "OTHER",
    ]
}
COUNTRY_ALIASES.update(
    {
        "United Kingdom": "UNITED_KINGDOM",
        "United Kingdom (e)": "UNITED_KINGDOM",
        "New Zealand": "NEW_ZEALAND",
        "Sudan (f)": "SUDAN",
        "China (g)": "CHINA",
        "Total overseas born": "OVERSEAS_BORN_TOTAL",
        "Total": "TOTAL",
        "Total (h)": "TOTAL",
    }
)
GROUP_ALIASES = {
    "Sex": "SEX",
    "Indigenous status": "INDIGENOUS_STATUS",
    "Legal status": "LEGAL_STATUS",
    "Prior imprisonment status": "PRIOR_IMPRISONMENT_STATUS",
    "Prior imprisonment status (f)": "PRIOR_IMPRISONMENT_STATUS",
    "Mean age (years)": "MEAN_AGE",
    "Median age (years)": "MEDIAN_AGE",
    "Total prisoners": "TOTAL",
    "Total prisoners (e)": "TOTAL",
}
CATEGORY_ALIASES = {
    "Males": "MALE",
    "Females": "FEMALE",
    "Persons": "PERSONS",
    "Aboriginal and Torres Strait Islander": "INDIGENOUS",
    "Non-Indigenous": "NON_INDIGENOUS",
    "Unknown": "UNKNOWN",
    "Sentenced": "SENTENCED",
    "Unsentenced": "UNSENTENCED",
    "Post-sentence": "POST_SENTENCE",
    "Post-sentence (d)": "POST_SENTENCE",
    "Prior imprisonment": "PRIOR_IMPRISONMENT",
    "No prior imprisonment": "NO_PRIOR_IMPRISONMENT",
    "Total prisoners": "TOTAL_PRISONERS",
    "Total prisoners (e)": "TOTAL_PRISONERS",
}


def digest_combos(dims: list[str], combos: list[tuple[str, ...]]) -> str:
    return domain_digest(
        COMBINATION_COVERAGE_SCHEMA,
        {"dimensions": dims, "combinations": sorted([list(c) for c in combos])},
    )


def measure(
    mid: str,
    unit: str,
    dims: list[str],
    yearly: dict[int, list[tuple[str, ...]]],
    selection: dict[str, list[str]] | None = None,
    missing: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {"id": mid, "unitId": unit, "numeric": True, "minimum": 0}
    if selection:
        out["selection"] = {"conditions": selection, "dimensionOverrides": {}}
    if set(yearly) != set(YEARS):
        out["applicableYears"] = [str(y) for y in sorted(yearly)]
    out["expectedCombinationCountsByYear"] = {str(y): len(v) for y, v in yearly.items()}
    out["expectedDimensionsByYear"] = {
        str(y): {d: sorted({c[i] for c in v}) for i, d in enumerate(dims)}
        for y, v in yearly.items()
    }
    out["expectedCombinationDigestsByYear"] = {
        str(y): digest_combos(dims, v) for y, v in yearly.items()
    }
    if missing:
        out["missingValues"] = {
            "n.a.": "not_applicable",
            "n.p.": "suppressed",
            "na": "not_applicable",
            "np": "suppressed",
        }
        out["excludeMissingValues"] = True
    return out


def contract(fid: str) -> dict[str, Any]:
    if fid.endswith("selected-characteristics-by-offence-charge"):
        dims = [
            "most_serious_offence_or_charge",
            "statistic_basis",
            "characteristic_group",
            "characteristic_category",
        ]
        groups = {
            "TOTAL": ["TOTAL_PRISONERS"],
            "SEX": ["MALE", "FEMALE"],
            "INDIGENOUS_STATUS": ["INDIGENOUS", "NON_INDIGENOUS", "UNKNOWN"],
            "LEGAL_STATUS": ["SENTENCED", "UNSENTENCED", "POST_SENTENCE"],
            "PRIOR_IMPRISONMENT_STATUS": [
                "PRIOR_IMPRISONMENT",
                "NO_PRIOR_IMPRISONMENT",
            ],
        }

        def standard(basis: str) -> list[tuple[str, ...]]:
            return [
                (o, basis, g, c)
                for g, cats in groups.items()
                for c in cats
                for o in OFFENCES_TABLE1
                if not (
                    g == "LEGAL_STATUS"
                    and o != "TOTAL"
                    and ((c == "POST_SENTENCE") != (o == "POST_SENTENCE"))
                )
            ]

        age = [
            (o, "NUMBER", g, c)
            for o in OFFENCES_TABLE1
            for c in ["MALE", "FEMALE", "INDIGENOUS", "NON_INDIGENOUS", "PERSONS"]
            for g in ["MEDIAN_AGE"]
        ]
        age_np = [c for c in age if not (c[0] == "POST_SENTENCE" and c[3] == "FEMALE")]
        mean_np = [
            (o, "NUMBER", "MEAN_AGE", c)
            for o in OFFENCES_TABLE1
            for c in ["MALE", "FEMALE", "INDIGENOUS", "NON_INDIGENOUS", "PERSONS"]
            if not (o == "POST_SENTENCE" and c == "FEMALE")
        ]
        measures = [
            measure(
                "prisoner-count",
                "person",
                dims,
                {y: standard("NUMBER") for y in YEARS},
                {"statistic_basis": ["NUMBER"], "characteristic_group": list(groups)},
                True,
            ),
            measure(
                "prisoner-proportion",
                "percent",
                dims,
                {y: standard("PROPORTION") for y in YEARS},
                {"statistic_basis": ["PROPORTION"]},
                True,
            ),
            measure(
                "median-age",
                "year",
                dims,
                {2021: age, 2022: age, 2023: age_np, 2024: age_np, 2025: age_np},
                {"statistic_basis": ["NUMBER"], "characteristic_group": ["MEDIAN_AGE"]},
                True,
            ),
            measure(
                "mean-age",
                "year",
                dims,
                {2025: mean_np},
                {"statistic_basis": ["NUMBER"], "characteristic_group": ["MEAN_AGE"]},
                True,
            ),
        ]
        aliases = {
            "most_serious_offence_or_charge": OFFENCE_ALIASES,
            "statistic_basis": STAT_ALIASES,
            "characteristic_group": GROUP_ALIASES,
            "characteristic_category": CATEGORY_ALIASES,
        }
    elif fid.endswith("age-by-sex"):
        dims = ["sex", "age_group", "statistic_basis"]
        definitions = [
            ("prisoner-count", "person", "NUMBER"),
            ("prisoner-proportion", "percent", "PROPORTION"),
            ("imprisonment-rate", "persons-per-100000-adult-population", "RATE"),
        ]
        measures = [
            measure(
                mid,
                unit,
                dims,
                {y: [(s, a, b) for s in SEXES for a in AGES] for y in YEARS},
                {"statistic_basis": [b]},
            )
            for mid, unit, b in definitions
        ]
        aliases = {
            "sex": SEX_ALIASES,
            "age_group": AGE_ALIASES,
            "statistic_basis": STAT_ALIASES,
        }
    elif fid.endswith("sex-offence-charge-by-indigenous-status"):
        dims = [
            "sex",
            "most_serious_offence_or_charge",
            "indigenous_status",
            "statistic_basis",
        ]
        measures = [
            measure(
                "prisoner-count",
                "person",
                dims,
                {
                    y: [
                        (s, o, i, "NUMBER")
                        for s in SEXES
                        for o in OFFENCES_TOTAL
                        for i in STATUS
                    ]
                    for y in YEARS
                },
                {"statistic_basis": ["NUMBER"]},
            ),
            measure(
                "prisoner-proportion",
                "percent",
                dims,
                {
                    y: [
                        (s, o, i, "PROPORTION")
                        for s in SEXES
                        for o in OFFENCES_TOTAL
                        for i in STATUS
                    ]
                    for y in YEARS
                },
                {"statistic_basis": ["PROPORTION"]},
            ),
        ]
        aliases = {
            "sex": SEX_ALIASES,
            "most_serious_offence_or_charge": OFFENCE_ALIASES,
            "indigenous_status": STATUS_ALIASES,
            "statistic_basis": STAT_ALIASES,
        }
    elif fid.endswith("age-by-offence-charge"):
        dims = ["age_group", "most_serious_offence_or_charge"]
        combos = [(a, o) for a in AGES for o in OFFENCES_TOTAL]
        measures = [
            measure("prisoner-count", "person", dims, {y: combos for y in YEARS})
        ]
        aliases = {
            "age_group": AGE_ALIASES,
            "most_serious_offence_or_charge": OFFENCE_ALIASES,
        }
    else:
        dims = ["country_of_birth", "most_serious_offence_or_charge"]
        countries = {
            2021: [
                "AUSTRALIA",
                "NEW_ZEALAND",
                "VIETNAM",
                "UNITED_KINGDOM",
                "SUDAN",
                "CHINA",
                "LEBANON",
                "MALAYSIA",
                "INDIA",
                "IRAN",
                "PHILIPPINES",
                "OTHER",
                "TOTAL",
            ],
            2022: [
                "AUSTRALIA",
                "NEW_ZEALAND",
                "VIETNAM",
                "UNITED_KINGDOM",
                "SUDAN",
                "CHINA",
                "MALAYSIA",
                "LEBANON",
                "IRAN",
                "INDIA",
                "IRAQ",
                "PHILIPPINES",
                "OTHER",
                "TOTAL",
            ],
            2023: [
                "AUSTRALIA",
                "NEW_ZEALAND",
                "VIETNAM",
                "UNITED_KINGDOM",
                "SUDAN",
                "CHINA",
                "MALAYSIA",
                "LEBANON",
                "IRAN",
                "INDIA",
                "IRAQ",
                "OTHER",
                "TOTAL",
            ],
            2024: [
                "AUSTRALIA",
                "NEW_ZEALAND",
                "UNITED_KINGDOM",
                "VIETNAM",
                "SUDAN",
                "CHINA",
                "INDIA",
                "MALAYSIA",
                "LEBANON",
                "IRAN",
                "IRAQ",
                "OTHER",
                "TOTAL",
            ],
            2025: [
                "AUSTRALIA",
                "NEW_ZEALAND",
                "UNITED_KINGDOM",
                "VIETNAM",
                "SUDAN",
                "CHINA",
                "INDIA",
                "IRAQ",
                "LEBANON",
                "IRAN",
                "PHILIPPINES",
                "OTHER",
                "OVERSEAS_BORN_TOTAL",
                "TOTAL",
            ],
        }
        measures = [
            measure(
                "prisoner-count",
                "person",
                dims,
                {
                    y: [(c, o) for c in countries[y] for o in OFFENCES_TOTAL]
                    for y in YEARS
                },
            )
        ]
        aliases = {
            "country_of_birth": COUNTRY_ALIASES,
            "most_serious_offence_or_charge": OFFENCE_ALIASES,
        }
    raw_counts = (
        [450, 486, 486, 486, 576]
        if fid.endswith("selected-characteristics-by-offence-charge")
        else FAMILIES[fid]["counts"]
    )
    expected: dict[str, Any] = {
        "minimumRows": min(raw_counts),
        "maximumRows": max(raw_counts),
        "sourceColumns": {
            "minimum": 6
            if "sex-offence" in fid
            else (
                9
                if fid.endswith("age-by-sex")
                else (17 if "selected-characteristics" not in fid else 18)
            ),
            "maximum": 6
            if "sex-offence" in fid
            else (
                9
                if fid.endswith("age-by-sex")
                else (17 if "selected-characteristics" not in fid else 18)
            ),
        },
    }
    if fid.endswith("selected-characteristics-by-offence-charge"):
        expected.update({"minimumExcludedRows": 0, "maximumExcludedRows": 38})
    fields = {
        "sex": "sexes",
        "age_group": "ageGroups",
        "statistic_basis": "statisticBases",
        "most_serious_offence_or_charge": "mostSeriousOffencesOrCharges",
        "indigenous_status": "indigenousStatuses",
        "country_of_birth": "countriesOfBirth",
        "characteristic_group": "characteristicGroups",
        "characteristic_category": "characteristicCategories",
    }
    for d in dims:
        vals = {
            str(y): sorted(
                {
                    code
                    for m in measures
                    for code in m["expectedDimensionsByYear"].get(str(y), {}).get(d, [])
                }
            )
            for y in YEARS
        }
        if len({tuple(v) for v in vals.values()}) == 1:
            expected[fields[d]] = next(iter(vals.values()))
        else:
            expected[fields[d] + "ByYear"] = vals
    equations: list[dict[str, Any]] = []
    if fid.endswith("age-by-sex"):
        equations = [
            {
                "dimension": "sex",
                "totalCode": "PERSONS",
                "componentCodes": ["MALE", "FEMALE"],
                "check": "components-must-not-exceed-total-beyond-rounding",
                "componentExcessTolerance": 30,
                "maximumUnmodelledResidual": 30,
                "measureIds": ["prisoner-count"],
            },
            {
                "dimension": "age_group",
                "totalCode": "TOTAL",
                "componentCodes": AGES[:-1],
                "check": "components-must-not-exceed-total-beyond-rounding",
                "componentExcessTolerance": 30,
                "maximumUnmodelledResidual": 30,
                "measureIds": ["prisoner-count"],
            },
        ]
    elif fid.endswith("sex-offence-charge-by-indigenous-status"):
        equations = [
            {
                "dimension": "indigenous_status",
                "totalCode": "TOTAL",
                "componentCodes": ["INDIGENOUS", "NON_INDIGENOUS"],
                "check": "components-must-not-exceed-total-beyond-rounding",
                "componentExcessTolerance": 30,
                "maximumUnmodelledResidual": 500,
                "measureIds": ["prisoner-count"],
            },
            {
                "dimension": "sex",
                "totalCode": "PERSONS",
                "componentCodes": ["MALE", "FEMALE"],
                "check": "components-must-not-exceed-total-beyond-rounding",
                "componentExcessTolerance": 30,
                "maximumUnmodelledResidual": 30,
                "measureIds": ["prisoner-count"],
            },
        ]
    elif fid.endswith("age-by-offence-charge"):
        equations = [
            {
                "dimension": "age_group",
                "totalCode": "TOTAL",
                "componentCodes": AGES[:-1],
                "check": "components-must-not-exceed-total-beyond-rounding",
                "componentExcessTolerance": 30,
                "maximumUnmodelledResidual": 30,
                "measureIds": ["prisoner-count"],
            },
            {
                "dimension": "most_serious_offence_or_charge",
                "totalCode": "TOTAL",
                "componentCodes": OFFENCES,
                "check": "components-must-not-exceed-total-beyond-rounding",
                "componentExcessTolerance": 30,
                "maximumUnmodelledResidual": 500,
                "measureIds": ["prisoner-count"],
            },
        ]
    return {
        "schemaVersion": "tidy.table-family-acceptance/v1",
        "contractId": f"prisoners-{fid}-v1",
        "tableFamilyId": fid,
        "measures": measures,
        "requiredDimensions": dims,
        "dimensionHeaders": {d: [d.replace("_", " ")] for d in dims},
        "aliases": aliases,
        "strictAliasMatching": True,
        "uniqueKey": ["reference_date"]
        + [
            {
                "sex": "sex_id",
                "age_group": "age_group_id",
                "statistic_basis": "statistic_basis_id",
                "most_serious_offence_or_charge": "most_serious_offence_or_charge_id",
                "indigenous_status": "indigenous_status_id",
                "country_of_birth": "country_of_birth_id",
                "characteristic_group": "characteristic_group_id",
                "characteristic_category": "characteristic_category_id",
            }[d]
            for d in dims
        ]
        + ["measure_id"],
        "expected": expected,
        "allowedExecutionWarnings": [],
        "totalEquations": equations,
        "totalValidation": "equations" if equations else "not_applicable",
        "automaticAcceptance": True,
        "trainingEligibility": False,
    }


def write(path: Path, data: bytes, check: bool, changed: list[str]) -> None:
    if check:
        if not path.is_file() or path.read_bytes() != data:
            changed.append(path.relative_to(ROOT).as_posix())
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed: list[str] = []
    geometry = {
        "schemaVersion": "tidy.prisoners-national-snapshots-geometry/v1",
        "recordedAt": RECORDED_AT,
        "authority": "human-authored-reviewed-physical-geometry",
        "boundedNormalization": {
            "year": 2025,
            "sheets": {"Table 7": "A1:R25", "Table 8": "A1:R28"},
            "sourcePath": "workbooks/prisoners-australia-2025-national-source.xlsx",
            "sourceDigest": SOURCE_DIGESTS[2025],
            "derivativePath": BOUNDED_2025[0],
            "derivativeDigest": BOUNDED_2025[1],
            "nonblankAndFormulaPayloadParity": True,
        },
        "families": [],
    }
    audit = {
        "schemaVersion": "tidy.prisoners-national-snapshots-acceptance-audit/v1",
        "recordedAt": RECORDED_AT,
        "authority": "independent-of-replay-output",
        "sourceAuthority": "committed-workbook-cells",
        "expectedCanonicalCount": 6695,
        "families": [],
    }
    for fid, f in FAMILIES.items():
        con = contract(fid)
        members = []
        workbooks = []
        for y in YEARS:
            table = f["tables"][y]
            sheet = f"Table_{table}" if y < 2024 else f"Table {table}"
            value_region, dimensions = f["maps"][y]
            map_obj = {
                "version": "semantic-table-map-v1",
                "table": {
                    "name": f"Prisoners in Australia — {fid} — {y}",
                    "values": {"name": "published value", "regions": [value_region]},
                    "dimensions": [
                        {
                            "name": n,
                            "memberRegions": r,
                            "direction": d,
                            "captionHints": [],
                        }
                        for n, r, d in dimensions
                    ],
                },
            }
            map_bytes = canonical_json_bytes(map_obj) + b"\n"
            replay = (
                f"replay/prisoners-australia-national-table-{table}-{y}.response.txt"
            )
            write(FIX / replay, map_bytes, args.check, changed)
            if y == 2025 and table in {7, 8}:
                path, digest, length = BOUNDED_2025
            else:
                path, digest, length = (
                    f"workbooks/prisoners-australia-{y}-national-source.xlsx",
                    SOURCE_DIGESTS[y],
                    SOURCE_LENGTHS[y],
                )
            entry = {
                "year": y,
                "referenceDate": f"{y}-06-30",
                "path": path,
                "contentDigest": digest,
                "byteLength": length,
                "sheet": sheet,
                "replayResponse": {
                    "path": replay,
                    "contentDigest": sha256_digest(map_bytes),
                    "byteLength": len(map_bytes),
                    "historicalModel": "human-authored/deterministic-geometry-v1",
                    "acceptanceAuthority": False,
                },
            }
            if y == 2025 and table in {7, 8}:
                entry["normalization"] = (
                    "trim-pathological-full-width-formatting-merge-v1"
                )
            workbooks.append(entry)
            members.append(
                {
                    "year": y,
                    "sourceWorkbookPath": (
                        f"workbooks/prisoners-australia-{y}-national-source.xlsx"
                    ),
                    "sourceWorkbookDigest": SOURCE_DIGESTS[y],
                    "executionWorkbookPath": path,
                    "executionWorkbookDigest": digest,
                    "sheet": sheet,
                    "semanticExtent": f["valueBands"][y],
                    "semanticMaximumColumn": "R" if table in {7, 8} else None,
                    "semanticMap": map_obj,
                }
            )
        cohort = {
            "schemaVersion": "tidy.product-prototype-cohort/v1",
            "cohortId": f"prisoners-australia-{fid}",
            "publicationId": "prisoners-australia",
            "tableFamilyId": fid,
            "generation": {
                "provider": "openai-codex",
                "model": "openai-codex/gpt-5.6-luna",
                "reasoning": "high",
                "promptContract": "cell-role-semantic-map-v13-adjacent-year-aware",
                "maximumCalls": 10,
                "maximumCostUsd": 2.0,
                "correctionPolicy": "one-pre-execution-compilation-correction-only",
            },
            "acceptanceContract": f"acceptance/prisoners-{fid}-v1.json",
            "workbooks": workbooks,
        }
        write(
            FIX / f"prisoners-{fid}.json",
            json.dumps(cohort, indent=2, ensure_ascii=False).encode() + b"\n",
            args.check,
            changed,
        )
        write(
            FIX / f"acceptance/prisoners-{fid}-v1.json",
            json.dumps(con, indent=2, ensure_ascii=False).encode() + b"\n",
            args.check,
            changed,
        )
        geometry["families"].append({"familyId": fid, "members": members})
        audit["families"].append(
            {
                "familyId": fid,
                "years": YEARS,
                "expectedYearCounts": f["counts"],
                "expectedCanonicalCount": sum(f["counts"]),
                "measureCounts": {
                    m["id"]: sum(m["expectedCombinationCountsByYear"].values())
                    for m in con["measures"]
                },
                "totalValidation": con["totalValidation"],
                "ANZSOCVersion": "2011",
            }
        )
    write(
        FIX / "prisoners-national-snapshots-geometry-v1.json",
        json.dumps(geometry, indent=2, ensure_ascii=False).encode() + b"\n",
        args.check,
        changed,
    )
    write(
        FIX / "prisoners-national-snapshots-acceptance-audit-v1.json",
        json.dumps(audit, indent=2, ensure_ascii=False).encode() + b"\n",
        args.check,
        changed,
    )
    if changed:
        print("generated artifacts differ:\n" + "\n".join(changed))
        return 1
    print("checked" if args.check else "generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
