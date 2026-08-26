#!/usr/bin/env python3
"""Build a non-authoritative, installable-only-after-review C4 proposal tree."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tidy_orchestrator.artifacts import (  # noqa: E402
    canonical_json_bytes,
    domain_digest,
    sha256_digest,
)
from tidy_orchestrator.data_asset_status import build_dashboard  # noqa: E402
from tidy_orchestrator.offenders_acceptance import (  # noqa: E402
    RECORDED_AT,
    REPLAY_ENGINE,
    build_offenders_family_run,
)

FIX = ROOT / "fixtures/product-prototype"
PLAN = FIX / "offenders-remaining-semantic-map-plan-v1.json"
EVIDENCE = {
    "README.md",
    "canonical-observations.csv",
    "canonical-observations.json",
    "collation-report.json",
    "exceptions.json",
    "manifest.json",
    "run.json",
}


def load(p: Path) -> Any:
    return json.loads(p.read_text())


def write(path: Path, v: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(v) + b"\n")


def title(fid: str) -> str:
    s = " ".join(
        x.upper() if x in {"anzsoc", "fdv", "act", "nsw"} else x for x in fid.split("-")
    )
    return s[:1].upper() + s[1:]


def evidence_manifest(
    fid: str, bundle: Path, cohort: Path, contract: Path
) -> dict[str, Any]:
    run = load(bundle / "run.json")
    rows = load(bundle / "canonical-observations.json")
    files = []
    for name in sorted(EVIDENCE - {"manifest.json"}):
        data = (bundle / name).read_bytes()
        files.append(
            {
                "path": name,
                "contentDigest": sha256_digest(data),
                "byteLength": len(data),
            }
        )
    return {
        "schemaVersion": "tidy.product-prototype-large-batch-evidence/v1",
        "familyId": fid,
        "cohortPath": f"fixtures/product-prototype/recorded-crime-offenders-{fid}.json",
        "cohortDigest": sha256_digest(cohort.read_bytes()),
        "acceptanceContractPath": (
            "fixtures/product-prototype/acceptance/"
            f"recorded-crime-offenders-{fid}-v1.json"
        ),
        "acceptanceContractDigest": sha256_digest(contract.read_bytes()),
        "recordedAt": RECORDED_AT,
        "mode": "replay",
        "replayEngine": REPLAY_ENGINE,
        "providerCalls": 0,
        "acceptedWorkbookCount": run["acceptedWorkbookCount"],
        "exceptionWorkbookCount": 0,
        "rawObservationCount": sum(x["rawObservationCount"] for x in run["workbooks"]),
        "excludedObservationCount": 0,
        "canonicalObservationCount": len(rows),
        "measureCounts": dict(sorted(Counter(x["measure_id"] for x in rows).items())),
        "valueStatusCounts": dict(
            sorted(Counter(x["value_status"] for x in rows).items())
        ),
        "warningCountsByYear": {str(x["year"]): 0 for x in run["workbooks"]},
        "manualReplayYears": [],
        "publicationVintagePreserved": all(
            "publication_vintage_date" in x for x in rows
        ),
        "runDigest": run["runDigest"],
        "files": files,
    }


def normalization() -> dict[str, Any]:
    path = ROOT / "scripts/generate-offenders-remaining-workbooks.py"
    spec = importlib.util.spec_from_file_location("offenders_workbooks", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entries = []
    for source_name, item in sorted(module.SPECS.items()):
        source = FIX / "workbooks" / source_name
        output = FIX / "workbooks" / item["output"]
        sb = source.read_bytes()
        ob = output.read_bytes()
        if hashlib.sha256(sb).hexdigest() != item["digest"]:
            raise RuntimeError("normalization source drift")
        entries.append(
            {
                "normalization": "digest-pinned-bounded-offenders-remaining-v1",
                "sourcePath": f"fixtures/product-prototype/workbooks/{source_name}",
                "sourceDigest": sha256_digest(sb),
                "sourceByteLength": len(sb),
                "outputPath": f"fixtures/product-prototype/workbooks/{item['output']}",
                "outputDigest": sha256_digest(ob),
                "outputByteLength": len(ob),
                "retainedRanges": item["ranges"],
                "reviewedArtifacts": item["artifacts"],
                "coordinateValueFormulaParity": True,
            }
        )
    value = {
        "schemaVersion": "tidy.offenders-remaining-workbook-normalization/v1",
        "recordedAt": RECORDED_AT,
        "generatorPath": "scripts/generate-offenders-remaining-workbooks.py",
        "generatorDigest": sha256_digest(path.read_bytes()),
        "entries": entries,
    }
    value["manifestDigest"] = domain_digest(value["schemaVersion"], value)
    return value


def large_entry(fid: str, bundle: Path, cohort: dict[str, Any]) -> dict[str, Any]:
    manifest = load(bundle / "manifest.json")
    run = load(bundle / "run.json")
    years = [x["year"] for x in cohort["workbooks"]]
    slug = fid.replace("-", "_")
    return {
        "familyId": fid,
        "label": f"Recorded Crime — Offenders — {title(fid)}",
        "cohortPath": f"fixtures/product-prototype/recorded-crime-offenders-{fid}.json",
        "evidenceManifestPath": (
            "fixtures/product-prototype/"
            f"recorded-crime-offenders-{fid}-evidence/manifest.json"
        ),
        "dagsterAsset": f"product_prototype_offenders_remaining_{slug}_replay",
        "dagsterJob": f"product_prototype_offenders_remaining_{slug}_replay_job",
        "outputDirectory": f"dagster-offenders-remaining-{fid}-replay",
        "expectedYears": years,
        "expectedYearCounts": [x["observationCount"] for x in run["workbooks"]],
        "expectedCanonicalCount": manifest["canonicalObservationCount"],
        "expectedMeasureCounts": manifest["measureCounts"],
        "expectedValueStatusCounts": manifest["valueStatusCounts"],
        "expectedManualReplayYears": [],
        "preservesPublicationVintage": True,
        "expectedExcludedObservationCount": 0,
        "expectedExcludedObservationCountsByYear": {str(y): 0 for y in years},
        "acceptancePolicyVersion": "tidy.table-family-acceptance/v2",
        "replayRecordedAt": RECORDED_AT,
        "replayEngine": REPLAY_ENGINE,
    }


def build(route_input: Path, executions: Path, out: Path) -> dict[str, Any]:
    payload = out / "payload"
    shutil.copytree(route_input / "fixtures", payload / "fixtures", symlinks=False)
    staged_fix = payload / "fixtures/product-prototype"
    contracts = out / "contracts-work"
    subprocess_run = [
        sys.executable,
        str(ROOT / "scripts/finalize-offenders-remaining-contracts.py"),
        "--executions",
        str(executions),
        "--cohort-root",
        str(staged_fix),
        "--out",
        str(contracts),
    ]
    subprocess.run(subprocess_run, check=True, stdout=subprocess.DEVNULL)
    acceptance = staged_fix / "acceptance"
    acceptance.mkdir(exist_ok=True)
    for p in contracts.iterdir():
        shutil.copyfile(p, acceptance / p.name)
    plan = load(PLAN)
    families = [x["familyId"] for x in plan["families"]]
    bundles = []
    members = rows = 0
    for fid in families:
        cohort_path = staged_fix / f"recorded-crime-offenders-{fid}.json"
        contract_path = acceptance / f"recorded-crime-offenders-{fid}-v1.json"
        bundle = staged_fix / f"recorded-crime-offenders-{fid}-evidence"
        scratch = out / "evidence-work" / fid
        run = build_offenders_family_run(
            cohort_path=cohort_path,
            contract_path=contract_path,
            execution_root=executions,
            output_root=scratch,
        )
        bundle.mkdir()
        for name in EVIDENCE - {"README.md", "manifest.json"}:
            shutil.copyfile(scratch / name, bundle / name)
        readme = (
            "# Checked proposal evidence: Recorded Crime — Offenders — "
            f"{title(fid)}\n\n"
            "This non-authoritative C4 proposal freezes provider-free replay "
            f"evidence for `{fid}`. It cannot be installed without a separately "
            "reviewed C4 authorization. C3 remains immutable evidence rather than "
            "acceptance authority. RecipeV01 and TargetScopedRecipeV02 identities "
            "remain distinct and training eligibility is false.\n"
        )
        (bundle / "README.md").write_text(readme)
        write(
            bundle / "manifest.json",
            evidence_manifest(fid, bundle, cohort_path, contract_path),
        )
        bundles.append((fid, bundle, load(cohort_path)))
        members += run["acceptedWorkbookCount"]
        rows += run["canonicalObservationCount"]
    if len(families) != 47 or members != 170 or rows != 224997:
        raise RuntimeError("evidence closure")
    norm = normalization()
    write(staged_fix / "offenders-remaining-workbook-normalization-v1.json", norm)
    large = load(FIX / "large-batch-assets-v1.json")
    ids = set(families)
    retained = [x for x in large["entries"] if x["familyId"] not in ids]
    campaign = [large_entry(fid, bundle, cohort) for fid, bundle, cohort in bundles]
    large["entries"] = retained + campaign
    large["batchId"] = "justice-seven-hundred-ninety-eight-worksheets-v1"
    large["recordedAt"] = RECORDED_AT
    large["worksheetCount"] = sum(len(x["expectedYears"]) for x in large["entries"])
    if (
        len(large["entries"]) != 288
        or large["worksheetCount"] != 798
        or sum(x["expectedCanonicalCount"] for x in large["entries"]) != 737954
    ):
        raise RuntimeError("large registry closure")
    write(staged_fix / "large-batch-assets-v1.json", large)
    baseline_dashboard = build_dashboard(ROOT)
    if (
        len(baseline_dashboard.cohorts) != 246
        or len(baseline_dashboard.assets) != 653
        or sum(asset.canonical_count or 0 for asset in baseline_dashboard.assets)
        != 526240
    ):
        raise RuntimeError("status baseline drift")
    status = load(FIX / "data-asset-status-v1.json")
    cohort_ids = {f"recorded-crime-offenders-{x}" for x in families}
    status["cohorts"] = [
        x for x in status["cohorts"] if x["cohortId"] not in cohort_ids
    ] + [
        {
            "cohortId": f"recorded-crime-offenders-{fid}",
            "label": entry["label"],
            "cohortPath": entry["cohortPath"],
            "evidenceManifestPath": entry["evidenceManifestPath"],
            "dagsterAsset": entry["dagsterAsset"],
        }
        for (fid, _b, _c), entry in zip(bundles, campaign, strict=True)
    ]
    status["recordedAt"] = RECORDED_AT
    proposed_assets = len(baseline_dashboard.assets) + members
    proposed_rows = (
        sum(asset.canonical_count or 0 for asset in baseline_dashboard.assets) + rows
    )
    if (
        len(status["cohorts"]) != 293
        or proposed_assets != 823
        or proposed_rows != 751237
    ):
        raise RuntimeError("status closure")
    write(staged_fix / "data-asset-status-v1.json", status)
    shutil.rmtree(out / "contracts-work")
    shutil.rmtree(out / "evidence-work")
    records = []
    for path in sorted(payload.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise RuntimeError("unsafe payload entry")
        if path.is_file():
            data = path.read_bytes()
            records.append(
                {
                    "path": path.relative_to(payload).as_posix(),
                    "byteLength": len(data),
                    "sha256": sha256_digest(data),
                }
            )
    manifest = {
        "schemaVersion": "tidy.offenders-c4-proposal/v1",
        "acceptanceAuthority": False,
        "trainingEligibility": False,
        "productionAcceptance": False,
        "promotionAuthorization": False,
        "recordedAt": RECORDED_AT,
        "families": 47,
        "members": 170,
        "rows": 224997,
        "providerCalls": 0,
        "files": records,
        "payloadRootDigest": domain_digest(
            "tidy.offenders-c4-proposal-payload/v1", records
        ),
    }
    write(out / "manifest.json", manifest)
    manifest["outputRootDigest"] = domain_digest(
        "tidy.offenders-c4-proposal-output/v1", manifest
    )
    write(out / "manifest.json", manifest)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route-input", required=True)
    ap.add_argument("--executions", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = (ROOT / a.out).resolve()
    allowed = (
        ROOT / ".product-prototype/offenders-remaining-phase1/c4-proposal"
    ).resolve()
    if out.parent != allowed or out.name not in {"run-a", "run-b"}:
        raise SystemExit("unsafe proposal output")
    temp = out.with_name(out.name + f".tmp-{os.getpid()}")
    backup = out.with_name(out.name + f".backup-{os.getpid()}")
    shutil.rmtree(temp, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    temp.mkdir(parents=True)
    try:
        result = build(Path(a.route_input), Path(a.executions), temp)
        had = out.exists()
        os.replace(out, backup) if had else None
        os.replace(temp, out)
        shutil.rmtree(backup, ignore_errors=True)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        if backup.exists() and not out.exists():
            os.replace(backup, out)
        raise
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "families",
                    "members",
                    "rows",
                    "providerCalls",
                    "payloadRootDigest",
                    "outputRootDigest",
                )
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
