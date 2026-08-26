#!/usr/bin/env python3
"""Build the non-authoritative C4 route/replay/cohort proposal inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures/product-prototype"
C3 = ROOT / ".product-prototype/offenders-remaining-phase1/all-170-replay/run-a"
B2 = (
    ROOT
    / ".product-prototype/offenders-remaining-phase1/multi-panel-b2a/run-e-phased/maps"
)
C2 = ROOT / ".product-prototype/offenders-remaining-phase1/target-scoped-c2/run-a/maps"
PLAN = FIX / "offenders-remaining-semantic-map-plan-v1.json"
CAP = FIX / "offenders-remaining-capability-routing-pin-v1.json"
AUTH = FIX / "offenders-remaining-all-replay-authorization-v1.json"
EXPECTED = {
    "semantic-map-v1-recipe-v01": 14,
    "semantic-map-v2-recipe-v01": 138,
    "target-scoped-recipe-v02": 18,
}


def load(p: Path) -> Any:
    return json.loads(p.read_text())


def sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def pretty(v: Any) -> bytes:
    return (json.dumps(v, indent=2, ensure_ascii=False) + "\n").encode()


def regular(p: Path, label: str) -> bytes:
    if p.is_symlink() or not p.is_file() or p.resolve() != p.absolute():
        raise RuntimeError(f"unsafe {label}: {p}")
    return p.read_bytes()


def build(out: Path) -> dict[str, Any]:
    if out.is_symlink():
        raise RuntimeError("symlink output")
    plan = load(PLAN)
    cap = load(CAP)
    auth_bytes = regular(AUTH, "C3 auth")
    capability = {(x["familyId"], x["year"]): x for x in cap["members"]}
    if len(capability) != 170:
        raise RuntimeError("capability closure")
    members = []
    counts = {k: 0 for k in EXPECTED}
    rows = 0
    families = set()
    destinations = set()
    staged_fix = out / "fixtures/product-prototype"
    (staged_fix / "replay").mkdir(parents=True, exist_ok=True)
    (staged_fix / "acceptance").mkdir(parents=True, exist_ok=True)
    for fam in plan["families"]:
        fid = fam["familyId"]
        families.add(fid)
        cohort_path = FIX / f"recorded-crime-offenders-{fid}.json"
        cohort = load(cohort_path)
        by_year = {x["year"]: x for x in cohort["workbooks"]}
        for raw in fam["members"]:
            year = int(raw["releaseId"][:4])
            key = (fid, year)
            capability_member = capability[key]
            c3_path = C3 / f"members/{fid}/{year}.json"
            c3_bytes = regular(c3_path, "C3 member")
            c3 = load(c3_path)
            if c3["route"] == "v1":
                protocol = "semantic-map-v1-recipe-v01"
            elif c3["route"] == "b1":
                protocol = "semantic-map-v2-recipe-v01"
            elif c3["route"] == "c2":
                protocol = "target-scoped-recipe-v02"
            else:
                raise RuntimeError("unknown C3 route")
            expected_mode = {
                "semantic-map-v1-recipe-v01": "semantic-map-v1",
                "semantic-map-v2-recipe-v01": "semantic-table-map-v2-recipe-v1",
                "target-scoped-recipe-v02": None,
            }[protocol]
            expected_status = (
                "target-scoped-required"
                if protocol == "target-scoped-recipe-v02"
                else "multi-table-v1-capable"
            )
            if (
                capability_member.get("releaseId") != raw["releaseId"]
                or capability_member.get("status") != expected_status
                or capability_member.get("mode") != expected_mode
                or capability_member.get("rows") != c3["rows"]
            ):
                raise RuntimeError(f"capability route drift {key}")
            entry = by_year[year]
            relative = entry["replayResponse"]["path"]
            final_map = f"fixtures/product-prototype/{relative}"
            source = (
                C2 / f"{fid}/{year}.json"
                if protocol == "target-scoped-recipe-v02"
                else B2 / relative
            )
            map_bytes = regular(source, "approved map")
            target = out / final_map
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(map_bytes)
            destinations.add(final_map)
            map_obj = json.loads(map_bytes)
            expected_version = {
                "semantic-map-v1-recipe-v01": "semantic-table-map-v1",
                "semantic-map-v2-recipe-v01": "semantic-table-map-v2",
                "target-scoped-recipe-v02": "target-scoped-semantic-map-v1",
            }[protocol]
            if map_obj.get("version") != expected_version:
                raise RuntimeError(f"route schema {key}")
            member = {
                "familyId": fid,
                "year": year,
                "releaseId": raw["releaseId"],
                "route": protocol,
                "cohortPath": f"fixtures/product-prototype/{cohort_path.name}",
                "workbookPath": f"fixtures/product-prototype/{entry['path']}",
                "workbookDigest": entry["contentDigest"],
                "workbookBytes": entry["byteLength"],
                "physicalSheet": entry["sheet"],
                "mapPath": final_map,
                "mapDigest": sha(map_bytes),
                "mapBytes": len(map_bytes),
                "rows": c3["rows"],
                "dimensions": c3["dimensions"],
                "orderedAddressDigest": c3["orderedAddressDigest"],
                "rowTraceDigest": c3["rowTraceDigest"],
                "c3MemberPath": (
                    ".product-prototype/offenders-remaining-phase1/all-170-replay/"
                    f"run-a/members/{fid}/{year}.json"
                ),
                "c3MemberDigest": sha(c3_bytes),
            }
            members.append(member)
            counts[protocol] += 1
            rows += c3["rows"]
            entry["replayResponse"] = {
                **entry["replayResponse"],
                "contentDigest": sha(map_bytes),
                "byteLength": len(map_bytes),
                "historicalModel": f"provider-free/offenders-c4/{protocol}",
                "acceptanceAuthority": False,
                "recipeProtocol": (
                    "TargetScopedRecipeV02"
                    if protocol == "target-scoped-recipe-v02"
                    else "RecipeV01"
                ),
            }
        staged_cohort = staged_fix / cohort_path.name
        staged_cohort.write_bytes(pretty(cohort))
        destinations.add(f"fixtures/product-prototype/{cohort_path.name}")
    if (
        counts != EXPECTED
        or len(families) != 47
        or len(members) != 170
        or rows != 224997
        or len(destinations) != 217
    ):
        detail = (counts, len(families), len(members), rows, len(destinations))
        raise RuntimeError(f"closure {detail}")
    members.sort(key=lambda x: (x["familyId"], x["year"]))
    manifest = {
        "schemaVersion": "tidy.offenders-c4-route-manifest/v1",
        "acceptanceAuthority": False,
        "trainingEligibility": False,
        "productionAcceptance": False,
        "promotionAuthorization": False,
        "c3AuthorizationDigest": sha(auth_bytes),
        "members": members,
        "summary": {
            "families": 47,
            "members": 170,
            "rows": 224997,
            "routes": counts,
            "providerCalls": 0,
        },
    }
    route_path = staged_fix / "offenders-remaining-c4-route-manifest-v1.json"
    route_path.write_bytes(pretty(manifest))
    destinations.add(
        "fixtures/product-prototype/offenders-remaining-c4-route-manifest-v1.json"
    )
    summary = {
        "families": 47,
        "members": 170,
        "rows": 224997,
        "routes": counts,
        "candidateDestinations": len(destinations),
        "routeManifestPath": (
            "fixtures/product-prototype/offenders-remaining-c4-route-manifest-v1.json"
        ),
        "routeManifestDigest": sha(route_path.read_bytes()),
    }
    (out / "route-build-summary.json").write_bytes(pretty(summary))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve()
    allowed = (
        ROOT / ".product-prototype/offenders-remaining-phase1/c4-proposal"
    ).resolve()
    if out.parent != allowed or not out.name.startswith("route-input-"):
        raise SystemExit("unsafe output")
    temp = out.with_name(out.name + f".tmp-{os.getpid()}")
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    try:
        result = build(temp)
        prior = out.with_name(out.name + f".backup-{os.getpid()}")
        shutil.rmtree(prior, ignore_errors=True)
        exists = out.exists()
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    if exists:
        os.replace(out, prior)
    try:
        os.replace(temp, out)
        shutil.rmtree(prior, ignore_errors=True)
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        if exists and prior.exists():
            os.replace(prior, out)
        raise
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
