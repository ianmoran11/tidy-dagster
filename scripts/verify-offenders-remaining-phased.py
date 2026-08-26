#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
from typing import Any

ROOT = Path.cwd().resolve()
EXPECTED_SUMMARY = {"compiled": 152, "refused": 18, "rows": 196316, "changedFields": 49628, "providerCalls": 0}
EXPECTED_RUNTIME_SOURCES = sorted([
    "apps/domain-worker/src/address.ts",
    "apps/domain-worker/src/catalog/cell-role-sketch-v02.ts",
    "apps/domain-worker/src/catalog/compiler-v02.ts",
    "apps/domain-worker/src/catalog/format-aware-region-catalog-v2.ts",
    "apps/domain-worker/src/catalog/geometry-v02.ts",
    "apps/domain-worker/src/catalog/role-aware-region-catalog-v5.ts",
    "apps/domain-worker/src/catalog/semantic-gold-schema.ts",
    "apps/domain-worker/src/catalog/semantic-map-v1.ts",
    "apps/domain-worker/src/catalog/semantic-map-v2.ts",
    "apps/domain-worker/src/catalog/types.ts",
    "apps/domain-worker/src/context/compactContext.ts",
    "apps/domain-worker/src/executor/directions.ts",
    "apps/domain-worker/src/executor/executeRecipe.ts",
    "apps/domain-worker/src/executor/relationshipResolution.ts",
    "apps/domain-worker/src/executor/types.ts",
    "apps/domain-worker/src/recipe/resolveSelectors.ts",
    "apps/domain-worker/src/recipe/schema.ts",
    "apps/domain-worker/src/recipe/styleFingerprint.ts",
    "apps/domain-worker/src/recipe/types.ts",
    "apps/domain-worker/src/workbook/parseWorkbook.ts",
    "apps/domain-worker/src/workbook/types.ts",
    "scripts/compile-offenders-remaining.ts",
    "scripts/offenders-phased-safety.ts",
])

def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

def canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()

def files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AssertionError(f"symlink forbidden: {path}")
        if path.is_file():
            found.append(path.relative_to(root))
    return sorted(found)

def unique_records(records: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in records:
        assert set(item) == {"path", "byteLength", "sha256"}, (label, item)
        path = item["path"]
        assert isinstance(path, str) and path and path not in result, (label, path)
        result[path] = item
    return result

def contained_repo_file(value: str) -> Path:
    path = Path(value)
    assert not path.is_absolute() and ".." not in path.parts, value
    resolved = (ROOT / path).resolve()
    assert resolved != ROOT and ROOT in resolved.parents, value
    assert resolved.is_file() and not resolved.is_symlink(), value
    return resolved

def verify_records(records: list[dict[str, Any]], base: Path | None, label: str) -> dict[str, dict[str, Any]]:
    indexed = unique_records(records, label)
    for rel, item in indexed.items():
        if base is None:
            path = contained_repo_file(rel)
        else:
            candidate = Path(rel)
            assert not candidate.is_absolute() and ".." not in candidate.parts, (label, rel)
            path = (base / candidate).resolve()
            assert path != base.resolve() and base.resolve() in path.parents, (label, rel)
            assert path.is_file() and not path.is_symlink(), (label, rel)
        assert path.stat().st_size == item["byteLength"] and digest(path) == item["sha256"], path
    return indexed

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--routed", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--authorization-digest", required=True)
    parser.add_argument("--capability-pin", type=Path, required=True)
    parser.add_argument("--capability-pin-digest", required=True)
    parser.add_argument("--attestation-out", type=Path)
    args = parser.parse_args()
    assert digest(args.authorization) == args.authorization_digest
    assert digest(args.capability_pin) == args.capability_pin_digest
    authorization = json.loads(args.authorization.read_text())
    capability = json.loads(args.capability_pin.read_text())
    assert authorization["authorizedForVersionedMapGeneration"] is True
    assert authorization["acceptanceAuthority"] is False
    assert authorization["reviewStatus"] == "pending-independent-review"
    assert capability["semanticGenerationAuthorizationSha256"] == args.authorization_digest
    assert capability["acceptanceAuthority"] is False
    runtime = unique_records(authorization["runtimeSourceClosure"], "runtimeSourceClosure")
    assert sorted(runtime) == EXPECTED_RUNTIME_SOURCES
    authorization_inputs = unique_records(authorization["inputs"], "authorizationInputs")
    for path, pin in runtime.items():
        assert authorization_inputs.get(path) == pin
    verify_records(list(runtime.values()), None, "runtimeSourceClosure")

    fa, fb = files(args.run_a), files(args.run_b)
    assert fa == fb
    for rel in fa:
        assert (args.run_a / rel).read_bytes() == (args.run_b / rel).read_bytes(), rel
    manifest = json.loads((args.run_a / "manifest.json").read_text())
    verify_records(manifest["inputFiles"], None, "runInputs")
    listed = verify_records(manifest["outputFiles"], args.run_a.resolve(), "runOutputs")
    actual = {str(rel) for rel in fa if str(rel) != "manifest.json"}
    assert set(listed) == actual

    routing_path = args.run_a / "routing-manifest.json"
    assert digest(routing_path) == capability["routingManifest"]["sha256"]
    routing = json.loads(routing_path.read_text())
    identities = [(item["familyId"], item["year"]) for item in routing["members"]]
    assert len(identities) == len(set(identities)) == 170
    routes = {(item["familyId"], item["year"]): item for item in capability["members"]}
    assert len(routes) == 170 and set(routes) == set(identities)
    for item in routing["members"]:
        expected = routes[(item["familyId"], item["year"])]
        for field in ("status", "mode", "rows", "failure", "mapDigest", "recipeDigest", "trustedEnvelopeDigest", "memberArtifactDigest"):
            assert item.get(field) == expected.get(field), (item["familyId"], item["year"], field)
    assert sum(item.get("mode") == "semantic-map-v1" for item in routing["members"]) == 14
    assert sum(item.get("mode") == "semantic-table-map-v2-recipe-v1" for item in routing["members"]) == 138
    assert sum(item["status"] == "target-scoped-required" for item in routing["members"]) == 18
    assert routing["summary"]["capableRows"] == 196316
    assert routing["summary"]["targetScopedRequiredRows"] == 28681
    assert routing["summary"]["capableAuthorizedFieldChanges"] == 49628

    routed_manifest_path = args.routed / "manifest.json"
    routed_manifest = json.loads(routed_manifest_path.read_text())
    assert routed_manifest["externalPins"] == {
        "authorization": args.authorization_digest,
        "capability": args.capability_pin_digest,
        "routing": capability["routingManifest"]["sha256"],
    }
    assert routed_manifest["summary"] == EXPECTED_SUMMARY
    routed_inputs = verify_records(routed_manifest["inputFiles"], None, "routedInputs")
    for required in [str(args.authorization), str(args.capability_pin), str(routing_path), *EXPECTED_RUNTIME_SOURCES]:
        assert required in routed_inputs, required
    routed_outputs = verify_records(routed_manifest["outputFiles"], args.routed.resolve(), "routedOutputs")
    routed_actual = {str(rel) for rel in files(args.routed) if str(rel) != "manifest.json"}
    assert set(routed_outputs) == routed_actual

    result = {
        "schemaVersion": "tidy.offenders-phased-reproduction-attestation/v1",
        "authoritative": False,
        "productionAcceptance": False,
        "runA": str(args.run_a),
        "runB": str(args.run_b),
        "routed": str(args.routed),
        "byteIdentical": True,
        "runFiles": len(fa),
        "inputFiles": len(manifest["inputFiles"]),
        "generatedFiles": len(manifest["outputFiles"]),
        "routingDigest": digest(routing_path),
        "manifestDigest": digest(args.run_a / "manifest.json"),
        "summaryDigest": digest(args.run_a / "summary.json"),
        "outputRootDigest": manifest["outputRootDigest"],
        "routedManifestDigest": digest(routed_manifest_path),
        "routedOutputRootDigest": routed_manifest["outputRootDigest"],
        **EXPECTED_SUMMARY,
    }
    if args.attestation_out:
        args.attestation_out.parent.mkdir(parents=True, exist_ok=True)
        data = canonical(result)
        temporary = args.attestation_out.with_suffix(args.attestation_out.suffix + f".tmp-{os.getpid()}")
        temporary.write_bytes(data)
        os.replace(temporary, args.attestation_out)
        assert args.attestation_out.read_bytes() == data
        assert json.loads(args.attestation_out.read_text()) == result
    print(json.dumps(result, separators=(",", ":")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
