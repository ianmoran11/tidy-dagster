#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tidy_orchestrator.artifacts import LocalArtifactRepository  # noqa: E402
from tidy_orchestrator.product_prototype import run_product_prototype  # noqa: E402

FIX = ROOT / "fixtures" / "product-prototype"
OUT = ROOT / ".product-prototype" / "prisoners-remaining-phase1" / "scratch"
RECORDED_AT = "2026-08-25T12:00:00+00:00"


def main() -> int:
    plan = json.loads(
        (FIX / "prisoners-remaining-semantic-map-plan-v1.json").read_text()
    )
    shutil.rmtree(OUT, ignore_errors=True)
    results = []
    for family in plan["families"]:
        family_id = family["familyId"]
        output = OUT / family_id
        try:
            run = run_product_prototype(
                repository=LocalArtifactRepository(output / "repository"),
                project_root=ROOT,
                cohort_path=FIX / f"prisoners-{family_id}.json",
                output_root=output,
                mode="replay",
                recorded_at=RECORDED_AT,
            )
            report = run.report
            result = {
                "family": family_id,
                "ok": True,
                "accepted": report["acceptedWorkbookCount"],
                "exceptions": report["exceptionWorkbookCount"],
                "rows": report["canonicalObservationCount"],
                "providerCalls": report["providerCalls"],
                "crossYearIssues": report["crossYearIssues"],
                "workbooks": report["workbooks"],
            }
            results.append(result)
        except Exception as error:
            result = {
                "family": family_id,
                "ok": False,
                "error": repr(error),
                "trace": traceback.format_exc()[-2000:],
            }
            results.append(result)
        print(
            json.dumps(
                {
                    "family": family_id,
                    "ok": result["ok"],
                    "accepted": result.get("accepted", 0),
                    "rows": result.get("rows", 0),
                },
                separators=(",", ":"),
            ),
            file=sys.stderr,
            flush=True,
        )
    results.sort(key=lambda item: item["family"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase1-run-summary.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n"
    )
    accepted = sum(item.get("accepted", 0) for item in results)
    exceptions = sum(item.get("exceptions", 0) for item in results)
    rows = sum(item.get("rows", 0) for item in results)
    providers = sum(item.get("providerCalls", 0) for item in results)
    issues = sum(
        len(workbook.get("issues", []))
        for item in results
        for workbook in item.get("workbooks", [])
    )
    warnings = sum(
        workbook.get("executionWarningCount", 0)
        for item in results
        for workbook in item.get("workbooks", [])
    )
    raw = sum(
        workbook.get("rawObservationCount", 0)
        for item in results
        for workbook in item.get("workbooks", [])
    )
    excluded = sum(
        workbook.get("excludedObservationCount", 0)
        for item in results
        for workbook in item.get("workbooks", [])
    )
    failures = [item["family"] for item in results if not item["ok"]]
    cross_year = sum(len(item.get("crossYearIssues", [])) for item in results)
    summary = {
        "families": len(results),
        "members": sum(len(family["members"]) for family in plan["families"]),
        "runtimeOk": len(results) - len(failures),
        "accepted": accepted,
        "exceptions": exceptions,
        "rawRows": raw,
        "excludedRows": excluded,
        "canonicalRows": rows,
        "issues": issues,
        "warnings": warnings,
        "providerCalls": providers,
        "retries": 0 if providers == 0 else None,
        "crossYearIssues": cross_year,
        "failed": failures,
    }
    print(json.dumps(summary, separators=(",", ":")))
    expected = {
        "families": 21,
        "members": 69,
        "runtimeOk": 21,
        "accepted": 69,
        "exceptions": 0,
        "rawRows": 34837,
        "excludedRows": 0,
        "canonicalRows": 34837,
        "issues": 0,
        "warnings": 0,
        "providerCalls": 0,
        "retries": 0,
        "crossYearIssues": 0,
        "failed": [],
    }
    if summary != expected:
        raise SystemExit("remaining Prisoners closure mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
