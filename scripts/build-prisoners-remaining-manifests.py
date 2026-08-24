# ruff: noqa
from __future__ import annotations
import json, re, hashlib, sys
from pathlib import Path
from collections import defaultdict
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures/product-prototype"
CAT = ROOT / ".product-prototype/prisoners-remaining-phase1/catalogs"
sys.path.insert(0, str(ROOT / "src"))
from tidy_orchestrator.artifacts import canonical_json_bytes, sha256_digest

FIDS = {
    "national-selected-characteristics-time-series",
    "national-offence-charge-time-series",
    "national-indigenous-offence-charge-by-legal-status-prior-imprisonment",
    "national-offence-charge-by-legal-status-sex",
    "national-sentenced-indigenous-offence-by-aggregate-sentence",
    "national-sentenced-indigenous-offence-by-expected-time",
    "national-sentenced-sex-by-offence-time-series",
    "national-unsentenced-indigenous-charge-by-time-on-remand",
    "national-indigenous-status-by-sex-time-series",
    "federal-prisoners-parolees-selected-characteristics",
    "federal-prisoners-selected-characteristics-time-series",
    "federal-parolees-selected-characteristics-time-series",
    "federal-prisoners-country-of-birth",
    "state-indigenous-sex-prisoner-count-time-series",
    "state-indigenous-sex-crude-rate-time-series",
    "state-indigenous-sex-age-standardised-rate-time-series",
    "preliminary-anzsoc-2023-table-1",
    "preliminary-anzsoc-2023-table-2",
    "preliminary-anzsoc-2023-table-3",
    "preliminary-anzsoc-2023-table-4",
    "preliminary-anzsoc-2023-table-5",
}
mem = json.load(open(FIX / "prisoners-release-family-membership-v1.json"))
families = {
    f["familyId"]: f["members"] for f in mem["families"] if f["familyId"] in FIDS
}


def catfile(m):
    return (
        CAT / f"{m['year']}-{m['downloadOrdinal']}-{m['sheet'].replace(' ', '_')}.json"
    )


def cand(d, *, kind=None, any_sample=None, all_sample=None, seg=None, exact_kind=False):
    out = []
    for c in d["catalog"]["candidates"]:
        ks = c["kinds"]
        sm = " ".join(map(str, c.get("sample", [])))
        sg = ";".join(c["segments"])
        if kind and not ((kind in ks) if exact_kind else any(kind in k for k in ks)):
            continue
        if any_sample and not re.search(any_sample, sm, re.I):
            continue
        if all_sample and any(
            not re.search(all_sample, str(x), re.I) for x in c.get("sample", [])
        ):
            continue
        if seg and not re.search(seg, sg):
            continue
        out.append(c)
    return out


def ids(cs):
    return [c["id"] for c in cs]


def one(*args, **kwargs):
    x = cand(*args, **kwargs)
    if len(x) != 1:
        raise RuntimeError(
            f"expected one got {len(x)} {kwargs} :: " + ",".join(c["id"] for c in x)
        )
    return x[0]["id"]


def obs_individual(d):
    cs = cand(d, kind="observation-panel", exact_kind=True)
    return [
        c
        for c in cs
        if not all(
            re.fullmatch(r"R\d+C\d+=20\d\d(?:\.0)?", str(v))
            for v in c.get("sample", [])
        )
    ]


def dims(entries):
    return [
        {
            "name": n.replace("_", " "),
            "memberRegions": r,
            "direction": di,
            "captionHints": [],
        }
        for n, r, di in entries
    ]


def map_for(fid, m, d):
    y = m["year"]
    values = []
    ds = []

    def title_candidate(c):
        starts = [int(re.match(r"R(\d+)C", s).group(1)) for s in c["segments"]]
        return starts and max(starts) <= 4

    direct = lambda pat: ids(
        [
            c
            for c in cand(d, kind="direct-row-projection-group", any_sample=pat)
            if not title_candidate(c) and "R5C1:R5C1" not in c["segments"]
        ]
    )
    all_direct = lambda: ids(
        [
            c
            for c in cand(d, kind="direct-row-projection-group")
            if not title_candidate(c) and "R5C1:R5C1" not in c["segments"]
        ]
    )
    single_format = lambda pat: ids(
        [
            c
            for c in cand(d, kind="format-header-group", any_sample=pat)
            if c["selectedCellCount"] == 1
        ]
    )
    top = lambda pat: ids(
        [
            c
            for c in cand(d, kind="top-header-level-group", any_sample=pat)
            if not title_candidate(c)
        ]
    )
    top_at_row = lambda row, pat: ids(
        [
            c
            for c in cand(d, kind="top-header-level-group", any_sample=pat)
            if all(re.match(rf"R{row}C", s) for s in c["segments"])
        ]
    )
    anchor = lambda pat: ids(
        [
            c
            for c in cand(d, kind="preceding-panel-anchor-group", any_sample=pat)
            if not title_candidate(c)
        ]
    )
    if fid == "national-selected-characteristics-time-series":
        values = [one(d, kind="all-observation-panels-trimmed-leading-label")]
        ds = [
            ("observation_period", direct(r"R\d+C1=20\d\d"), "W"),
            ("characteristic_category", top(r"Males.*Females|Imprisonment rate"), "N"),
            (
                "characteristic_group",
                top(r"Sex.*Indigenous|Prior imprisonment|Total"),
                "NNW",
            ),
            ("statistic_basis", top(r"NUMBER|Number|% change"), "WNW"),
        ]
    elif fid == "national-indigenous-status-by-sex-time-series":
        values = [one(d, kind="all-observation-panels-trimmed-leading-label")]
        ds = [
            ("observation_period", direct(r"20\d\d"), "W"),
            ("indigenous_status", top(r"Aboriginal.*Non-Indigenous"), "NNW"),
            ("sex", top(r"Males.*Females"), "N"),
            (
                "statistic_basis",
                top(r"Number.*Crude rate|Age standardised rate"),
                "WNW",
            ),
        ]
    elif fid == "national-offence-charge-time-series":
        panels = [c for c in obs_individual(d) if c["selectedCellCount"] > 20]
        values = ids(panels)
        years = [
            c
            for c in cand(d, kind="observation-panel", exact_kind=True)
            if all(re.search(r"=20\d\d", str(v)) for v in c.get("sample", []))
        ]
        year_regions = ids(years) + ids(
            [
                c
                for c in cand(d, kind="format-header-group", any_sample=r"20\d\d")
                if all(re.search(r"20\d\d", str(v)) for v in c.get("sample", []))
                and c["selectedCellCount"] == 1
                and any(re.match(r"R5C", s) for s in c["segments"])
            ]
        )
        ds = [
            ("observation_period", year_regions, "N"),
            ("most_serious_offence_or_charge", all_direct(), "W"),
            ("statistic_basis", top(r"NUMBER|Number|PROPORTION|Proportion"), "WNW"),
        ]
    elif fid == "national-offence-charge-by-legal-status-sex":
        values = [one(d, kind="observation-panel", exact_kind=True)]
        ds = [
            ("most_serious_offence_or_charge", all_direct(), "W"),
            ("sex", top(r"Males.*Females"), "N"),
            ("legal_status", top(r"Sentenced.*Unsentenced|Total"), "NNW"),
        ]
    elif fid == "national-indigenous-offence-charge-by-legal-status-prior-imprisonment":
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        ds = [
            ("most_serious_offence_or_charge", all_direct(), "W"),
            (
                "indigenous_status",
                anchor(
                    r"ABORIGINAL|Aboriginal|NON-INDIGENOUS|Non-Indigenous|TOTAL|Total"
                ),
                "WNW",
            ),
            (
                "legal_status",
                top_at_row(
                    5, r"Sentenced in.*Other sentenced|All sentenced|Unsentenced|Total"
                ),
                "NNW",
            ),
            ("prior_imprisonment_status", top(r"no\.|% prior"), "N"),
        ]
    elif fid == "national-sentenced-sex-by-offence-time-series":
        values = [one(d, kind="all-observation-panels-trimmed-leading-label")]
        stat = top(r"no\.|%")
        stat_direction = "N"
        if not stat:
            stat = [
                one(
                    d,
                    kind="merged-header-anchor",
                    any_sample=r"number and percentage of sentenced prisoners",
                )
            ]
            stat_direction = "NNW"
        ds = [
            ("observation_period", direct(r"20\d\d"), "W"),
            ("most_serious_offence", top(r"01 Homicide.*02 Acts|Total"), "NNW"),
            ("statistic_basis", stat, stat_direction),
            ("sex", top(r"Males|Females|Persons"), "WNW"),
        ]
    elif fid in {
        "national-sentenced-indigenous-offence-by-aggregate-sentence",
        "national-sentenced-indigenous-offence-by-expected-time",
    }:
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        length = (
            "aggregate_sentence_length"
            if "aggregate" in fid
            else "expected_time_to_serve"
        )
        ds = [
            ("most_serious_offence", all_direct(), "W"),
            ("indigenous_status", anchor(r"Aboriginal|Non-Indigenous|Total"), "WNW"),
            (length, top(r"Under 3 months|Mean \(years\)|Total \(%\)"), "N"),
        ]
    elif fid == "national-unsentenced-indigenous-charge-by-time-on-remand":
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        ds = [
            ("most_serious_charge", all_direct(), "W"),
            ("indigenous_status", anchor(r"Aboriginal|Non-Indigenous|Total"), "WNW"),
            ("time_on_remand", top(r"no\.|Mean \(months\)|90th Percentile|%"), "N"),
        ]
    elif fid == "federal-prisoners-parolees-selected-characteristics":
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        ds = [
            ("jurisdiction", top(r"NSW.*Vic|Qld.*SA"), "N"),
            (
                "prisoner_statistic",
                top(
                    r"Federal Prisoners|Federal Parolees|FEDERAL PRISONERS|FEDERAL PAROLEES"
                ),
                "WNW",
            ),
            (
                "characteristic_category",
                direct(
                    r"Total prisoners|Total parolees|Male|Female|Mean age|Indigenous|Aboriginal"
                ),
                "W",
            ),
        ]
    elif fid == "federal-prisoners-country-of-birth":
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        ds = [
            ("country_of_birth", all_direct(), "W"),
            (
                "jurisdiction",
                top(r"NEW SOUTH WALES|New South Wales|Victoria|Queensland|Australia"),
                "WNW",
            ),
        ]
    elif fid in {
        "federal-prisoners-selected-characteristics-time-series",
        "federal-parolees-selected-characteristics-time-series",
    }:
        panels = obs_individual(d)
        values = ids(panels)
        years = [
            c
            for c in cand(d, kind="observation-panel", exact_kind=True)
            if all(re.search(r"=20\d\d", str(v)) for v in c.get("sample", []))
        ]
        categories = direct(
            r"Total prisoners|Total parolees|Male|Female|Mean age|Indigenous|Aboriginal|Unknown"
        ) + single_format(r"Total prisoners|Total parolees")
        ds = [
            ("observation_period", ids(years), "N"),
            (
                "jurisdiction",
                top(r"NEW SOUTH WALES|New South Wales|Victoria|Queensland|Australia"),
                "WNW",
            ),
            ("characteristic_category", categories, "W"),
        ]
    elif fid.startswith("state-indigenous-sex-"):
        values = [one(d, kind="all-observation-panels-trimmed-leading-label")]
        ds = [
            ("observation_period", direct(r"20\d\d"), "W"),
            ("jurisdiction", top(r"NSW.*Vic"), "N"),
            ("indigenous_status", top(r"ABORIGINAL|NON-INDIGENOUS|TOTAL|RATIO"), "WNW"),
            ("sex", anchor(r"Males|Females|Persons"), "WNW"),
        ]
    elif fid == "preliminary-anzsoc-2023-table-1":
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        ds = [
            ("principal_offence", direct(r"01 Homicide|Total"), "W"),
            ("jurisdiction", top(r"NSW.*Qld"), "N"),
            ("statistic_basis", top(r"Number|Proportion"), "WNW"),
            (
                "classification_context",
                [
                    one(
                        d,
                        kind="format-header-group",
                        any_sample=r"Preliminary ANZSOC 2023 most serious offence/charge",
                        seg=r"R5C1:R5C1",
                    )
                ],
                "WNW",
            ),
        ]
    elif fid in {"preliminary-anzsoc-2023-table-2", "preliminary-anzsoc-2023-table-3"}:
        values = [one(d, kind="observation-panel", exact_kind=True)]
        offence = "principal_offence" if fid.endswith("2") else "most_serious_charge"
        ds = [
            (offence, direct(r"01 Homicide|Total"), "W"),
            ("jurisdiction", top(r"NSW.*Qld"), "N"),
            (
                "classification_context",
                [
                    one(
                        d,
                        kind="preceding-panel-anchor-group",
                        any_sample=r"Preliminary ANZSOC 2023",
                    )
                ],
                "WNW",
            ),
        ]
    elif fid == "preliminary-anzsoc-2023-table-4":
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        ds = [
            ("principal_offence", direct(r"01 Homicide|Total|Post-sentence"), "W"),
            ("jurisdiction", top(r"NSW.*Qld"), "N"),
            ("indigenous_status", top(r"Aboriginal|Non-Indigenous|Total"), "WNW"),
            (
                "classification_context",
                [
                    one(
                        d,
                        kind="format-header-group",
                        any_sample=r"Indigenous status and preliminary ANZSOC",
                        seg=r"R5C1:R5C1",
                    )
                ],
                "WNW",
            ),
        ]
    elif fid == "preliminary-anzsoc-2023-table-5":
        values = [one(d, kind="all-observation-panels", exact_kind=True)]
        ds = [
            ("principal_offence", direct(r"01 Homicide|Total"), "W"),
            (
                "principal_offence_anzsoc_2011",
                top(r"01 Homicide and related.*02 Acts|Total"),
                "N",
            ),
            (
                "jurisdiction",
                top(
                    r"New South Wales|Queensland|South Australia|Western Australia|Tasmania|Northern Territory|Capital"
                ),
                "WNW",
            ),
        ]
    else:
        raise KeyError(fid)
    # preserve order, remove duplicate region ids within each dimension
    clean = []
    for n, rs, di in ds:
        seen = []
        for r in rs:
            if r not in seen:
                seen.append(r)
        if not seen:
            raise RuntimeError(f"no regions {fid} {y} {n}")
        clean.append((n, seen, di))
    return {
        "version": "semantic-table-map-v1",
        "table": {
            "name": f"Prisoners in Australia — {fid} — {y}",
            "values": {"name": "published value", "regions": values},
            "dimensions": dims(clean),
        },
    }


def norm(s):
    return " ".join(str(s).strip().split())


def code(s):
    t = re.sub(r"[^A-Z0-9]+", "_", norm(s).upper()).strip("_") or "VALUE"
    return t[:80] + "_" + hashlib.sha256(norm(s).encode()).hexdigest()[:8]


def all_aliases(path):
    wb = openpyxl.load_workbook(path, data_only=False, read_only=False)
    out = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None and not (
                    isinstance(c.value, str) and c.value.startswith("=")
                ):
                    s = norm(c.value)
                    if s:
                        out[s] = code(s)
    wb.close()
    return out


plan = {
    "schemaVersion": "tidy.prisoners-remaining-semantic-map-plan/v1",
    "recordedAt": "2026-08-25T12:00:00+00:00",
    "acceptanceAuthority": False,
    "trainingEligibility": False,
    "families": [],
}
for fid, members in families.items():
    work = []
    pm = []
    dims_names = None
    for m in members:
        d = json.load(open(catfile(m)))
        mp = map_for(fid, m, d)
        mb = canonical_json_bytes(mp) + b"\n"
        replay = f"replay/prisoners-australia-{m['cubeId']}-{m['physicalTableNumber']}-{m['year']}.response.txt"
        (FIX / replay).write_bytes(mb)
        source = FIX / m["sourcePath"]
        execution = source
        normalization = None
        if (
            m["year"] == 2025
            and m["cubeId"] == "national"
            and m["physicalTableNumber"] in {10, 11, 12, 13, 14}
        ):
            execution = (
                FIX
                / "workbooks/prisoners-australia-2025-national-remaining-bounded.xlsx"
            )
            normalization = "trim-pathological-full-width-formatting-merge-v1"
        elif (
            m["year"] == 2024
            and m["cubeId"] == "federal"
            and m["physicalTableNumber"] in {38, 39}
        ):
            execution = (
                FIX
                / "workbooks/prisoners-australia-2024-federal-remaining-bounded.xlsx"
            )
            normalization = "isolate-repeated-total-label-formatting-v1"
        elif m["year"] == 2025 and m["cubeId"] == "federal":
            execution = (
                FIX
                / "workbooks/prisoners-australia-2025-federal-remaining-bounded.xlsx"
            )
            normalization = (
                "trim-table-37-and-isolate-repeated-total-label-formatting-v1"
            )
        b = execution.read_bytes()
        ent = {
            "year": m["year"],
            "referenceDate": f"{m['year']}-06-30",
            "path": execution.relative_to(FIX).as_posix(),
            "contentDigest": sha256_digest(b),
            "byteLength": len(b),
            "sheet": m["sheet"],
            "replayResponse": {
                "path": replay,
                "contentDigest": sha256_digest(mb),
                "byteLength": len(mb),
                "historicalModel": "human-authored/deterministic-geometry-v1",
                "acceptanceAuthority": False,
            },
        }
        if normalization:
            ent["normalization"] = normalization
        work.append(ent)
        pm.append(
            {
                "year": m["year"],
                "sheet": m["sheet"],
                "sourcePath": m["sourcePath"],
                "sourceDigest": m["sourceDigest"],
                "executionPath": ent["path"],
                "executionDigest": ent["contentDigest"],
                "semanticMap": mp,
            }
        )
        dn = [x["name"].replace(" ", "_") for x in mp["table"]["dimensions"]]
        dims_names = dims_names or dn
        if dims_names != dn:
            raise RuntimeError(f"dim mismatch {fid}")
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
            "maximumCalls": 2 * len(work),
            "maximumCostUsd": 2.0,
            "correctionPolicy": "one-pre-execution-compilation-correction-only",
        },
        "acceptanceContract": f"acceptance/prisoners-{fid}-v1.json",
        "workbooks": work,
    }
    if (
        fid.startswith("state-indigenous-sex-")
        or fid == "preliminary-anzsoc-2023-table-5"
    ):
        cohort["workerLimits"] = {"maxWarnings": 100000}
    (FIX / f"prisoners-{fid}.json").write_text(
        json.dumps(cohort, indent=2, ensure_ascii=False) + "\n"
    )
    aliases = {n: {} for n in dims_names}
    # bootstrap with all raw strings from each execution workbook
    for e in work:
        for raw, c in all_aliases(FIX / e["path"]).items():
            for n in dims_names:
                aliases[n][raw] = c
    expected = {
        "minimumRows": 1,
        "maximumRows": 100000,
        "sourceColumns": {"minimum": 1, "maximum": 200},
    }
    field = {
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
        "observation_period": "observationPeriods",
        "expected_time_to_serve": "expectedTimesToServe",
        "prior_imprisonment_status": "priorImprisonmentStatuses",
        "time_on_remand": "timesOnRemand",
        "prisoner_statistic": "prisonerStatistics",
    }
    for n in dims_names:
        expected[field[n]] = sorted(set(aliases[n].values()))
    contract = {
        "schemaVersion": "tidy.table-family-acceptance/v1",
        "contractId": f"prisoners-{fid}-v1",
        "tableFamilyId": fid,
        "measures": [
            {
                "id": "published-value",
                "unitId": "published-unit",
                "numeric": True,
                "minimum": 0,
                "missingValues": {
                    "n.a.": "not_applicable",
                    "na": "not_available",
                    "n.p.": "suppressed",
                    "np": "suppressed",
                    "..": "not_available",
                },
            }
        ],
        "requiredDimensions": dims_names,
        "dimensionHeaders": {n: [n.replace("_", " ")] for n in dims_names},
        "aliases": aliases,
        "strictAliasMatching": True,
        "uniqueKey": ["reference_date"]
        + [
            {
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
                "observation_period": "observation_period_id",
                "expected_time_to_serve": "expected_time_to_serve_id",
                "prior_imprisonment_status": "prior_imprisonment_status_id",
                "time_on_remand": "time_on_remand_id",
                "prisoner_statistic": "prisoner_statistic_id",
            }[n]
            for n in dims_names
        ]
        + ["measure_id"],
        "expected": expected,
        "allowedExecutionWarnings": [],
        "totalEquations": [],
        "totalValidation": "not_applicable",
        "automaticAcceptance": True,
        "trainingEligibility": False,
        "preserveRawValueText": True,
    }
    (FIX / f"acceptance/prisoners-{fid}-v1.json").write_text(
        json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
    )
    plan["families"].append({"familyId": fid, "members": pm})
(FIX / "prisoners-remaining-semantic-map-plan-v1.json").write_text(
    json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
)
print(
    json.dumps({"families": len(families), "members": sum(map(len, families.values()))})
)
