from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts/product-prototype/v1"
FIXTURES = ROOT / "fixtures/product-prototype"
MANIFEST = FIXTURES / "federal-defendants-source-coordinate-semantic-oracle-v1.json"
SHARDS = FIXTURES / "federal-defendants-source-coordinate-semantic-oracle-v1"
AUTHORITY = FIXTURES / "federal-defendants-semantic-plan-v1.json"
EXPECTED_ROOT_DIGEST = (
    "sha256:25934d26d9769f6929868386d627163e4f2f2b2fc7107003b16b1baa9a4e28b3"
)


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def stable_hashes(root: Path = FIXTURES) -> dict[str, str]:
    manifest = root / MANIFEST.name
    shards = root / SHARDS.name
    paths = [
        manifest,
        *sorted(shards.glob("*.json"), key=lambda item: item.name.encode()),
    ]
    return {str(path.relative_to(root)): digest(path) for path in paths}


def validate(schema_name: str, document: Path) -> None:
    schema = json.loads((CONTRACTS / schema_name).read_text())
    instance = json.loads(document.read_text())
    jsonschema.Draft202012Validator(schema).validate(instance)


def load_verifier(name: str) -> ModuleType:
    path = ROOT / "scripts/verify-federal-defendants-semantic-oracle.py"
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def load_builder(name: str) -> ModuleType:
    path = ROOT / "scripts/build-federal-defendants-semantic-oracle.py"
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def canonical(module: ModuleType, value: object) -> bytes:
    return module.canonical_blob(value)


def install_mutated_reads(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    shard_path: str | None = None,
    shard_mutator: Callable[[dict[str, Any]], None] | None = None,
    authority_mutator: Callable[[dict[str, Any]], None] | None = None,
    evidence_name: str | None = None,
    evidence_mutator: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    manifest = json.loads(MANIFEST.read_text())
    project_overrides: dict[str, bytes] = {}
    artifact_overrides: dict[str, bytes] = {}
    authority = json.loads(AUTHORITY.read_text())
    if evidence_name is not None:
        assert evidence_mutator is not None
        descriptor = authority["evidence"][evidence_name]
        evidence = json.loads((ROOT / descriptor["path"]).read_text())
        evidence_mutator(evidence)
        evidence_blob = canonical(module, evidence)
        project_overrides[descriptor["path"]] = evidence_blob
        replacement = {
            "path": descriptor["path"],
            "digest": module.checksum(evidence_blob),
            "byteLength": len(evidence_blob),
        }
        authority["evidence"][evidence_name] = replacement
        manifest["evidence"][evidence_name] = replacement
    if authority_mutator is not None:
        authority_mutator(authority)
    if evidence_name is not None or authority_mutator is not None:
        authority_blob = canonical(module, authority)
        project_overrides[manifest["authority"]["path"]] = authority_blob
        manifest["authority"] = {
            "path": manifest["authority"]["path"],
            "digest": module.checksum(authority_blob),
            "byteLength": len(authority_blob),
        }
    if shard_path is not None:
        assert shard_mutator is not None
        shard = json.loads((ROOT / shard_path).read_text())
        shard_mutator(shard)
        shard_blob = canonical(module, shard)
        artifact_overrides[shard_path] = shard_blob
        descriptor = next(
            item for item in manifest["shards"] if item["path"] == shard_path
        )
        descriptor["digest"] = module.checksum(shard_blob)
        descriptor["byteLength"] = len(shard_blob)
    manifest_blob = canonical(module, manifest)
    artifact_overrides[module.MANIFEST_NAME] = manifest_blob
    original_vetted = module.vetted_read
    original_artifact = module.artifact_read

    def mutated_vetted(relative: str, maximum: int = module.MAX_EVIDENCE_BYTES):
        if relative in project_overrides:
            return ROOT / relative, project_overrides[relative]
        return original_vetted(relative, maximum)

    def mutated_artifact(relative: str, maximum: int):
        if relative in artifact_overrides:
            return ROOT / relative, artifact_overrides[relative]
        return original_artifact(relative, maximum)

    monkeypatch.setattr(module, "vetted_read", mutated_vetted)
    monkeypatch.setattr(module, "artifact_read", mutated_artifact)
    return module.checksum(manifest_blob)


def test_boundary_one_schemas_and_exact_closure() -> None:
    validate("federal-defendants-semantic-plan.schema.json", AUTHORITY)
    validate(
        "federal-defendants-controlled-vocabulary.schema.json",
        FIXTURES / "federal-defendants-controlled-vocabulary-v1.json",
    )
    validate(
        "federal-defendants-methodology-evidence.schema.json",
        FIXTURES / "federal-defendants-methodology-evidence-v1.json",
    )
    validate(
        "federal-defendants-source-coordinate-semantic-oracle.schema.json", MANIFEST
    )
    member_schema = json.loads(
        (
            CONTRACTS
            / "federal-defendants-source-coordinate-semantic-oracle-member.schema.json"
        ).read_text()
    )
    member_validator = jsonschema.Draft202012Validator(member_schema)
    shard_paths = sorted(SHARDS.glob("*.json"), key=lambda item: item.name.encode())
    assert len(shard_paths) == 36
    totals = {
        "targetCount": 0,
        "notPublishedCount": 0,
        "zeroCount": 0,
        "formulaCount": 0,
    }
    exact_comments: list[str] = []
    for path in shard_paths:
        shard = json.loads(path.read_text())
        member_validator.validate(shard)
        coordinates = [
            record["sourceIdentity"]["address"] for record in shard["records"]
        ]
        coordinate_digest = digest_bytes(("\n".join(coordinates) + "\n").encode())
        assert shard["targetCoordinateCount"] == len(coordinates)
        assert shard["targetCoordinateDigest"] == coordinate_digest
        for key in totals:
            totals[key] += shard["counts"][key]
        for record in shard["records"]:
            if record["valueState"]["markerSource"] == "cell-comment":
                exact_comments.append(
                    f"{shard['memberId']}!{record['sourceIdentity']['address']}"
                )
    assert totals == {
        "targetCount": 18_793,
        "notPublishedCount": 54,
        "zeroCount": 3_378,
        "formulaCount": 0,
    }
    assert exact_comments == [
        f"2022-23-federal-offence-group-table-7!{cell}"
        for cell in ("F19", "G19", "F24", "G24", "F28", "G28", "F52", "G52")
    ]
    assert digest(MANIFEST) == EXPECTED_ROOT_DIGEST


def test_genuine_notes_and_structural_headings_are_disjoint() -> None:
    authority = json.loads(AUTHORITY.read_text())
    note_cells = {
        (member["memberId"], note["sourceAddress"], note["exactText"])
        for member in authority["members"]
        for block in member["blocks"]
        for note in block["noteDefinitions"]
        if note["sourceKind"] == "note-cell"
    }
    source_comments = {
        (member["memberId"], note["sourceAddress"], note["exactText"])
        for member in authority["members"]
        for block in member["blocks"]
        for note in block["noteDefinitions"]
        if note["sourceKind"] == "comment"
    }
    headings = {
        (member["memberId"], assertion["sourceAddress"], assertion["rawValue"])
        for member in authority["members"]
        for assertion in member["layoutAssertions"]
    }
    assert len(note_cells) == 135
    assert len(source_comments) == 231
    assert len(headings) == 9
    assert all(text != "Footnotes" for _, _, text in note_cells)
    assert {text for _, _, text in headings} == {"Footnotes"}
    heading_note_ids = {
        "note-cell:153af8f4ca03b5b6e9fa20b8f909d575253c1d13cbe3d76048aec54d4f0e760f",
        "note-cell:eae76cc3513ca9374ad5c23a004b9e636a5c5366b3bb9eed7cfdc37bed6f1875",
        "note-cell:382873c227255630f0a6404d766cd10b48aaa4d36405b4dbeed99680cc097f40",
        "note-cell:7b7bdcc028b650fc79b79c2c4445f69af376f4f5b26c27c0ad35507f32f4eb4a",
        "note-cell:efa1336ecc3e68d0fb3d9e8c432fb018fc0821418b61bb78e5b19f286e5f48f3",
        "note-cell:ea3653e5b003ed967cf3c1d9a08adae3e25b13d88d0c9e90d28e94bcd1458357",
        "note-cell:4956de5f1fcba20542ca20904723842032a2df4a1b515e9b6c1bc20264659d81",
        "note-cell:c11a11c869ff69ba88223e86fced38e5916d56993f33fa33c6e17c3da6b1a615",
        "note-cell:f9a56caa029e68b2efc9485362f9a47954e6e7692553c3e6fb955210938a7beb",
    }
    assert not any(
        heading_note_ids.intersection(record["canonical"]["footnoteReferenceSet"])
        for path in SHARDS.glob("*.json")
        for record in json.loads(path.read_text())["records"]
    )


def test_pre_2024_federal_offence_group_anzsoc_is_coherent() -> None:
    for path in SHARDS.glob("*.json"):
        shard = json.loads(path.read_text())
        if (
            "federal-offence-group" not in shard["memberId"]
            or shard["releaseId"] == "2024-25"
        ):
            continue
        for record in shard["records"]:
            canonical_fields = record["canonical"]
            assert canonical_fields["principalOffenceClassificationId"] == "anzsoc-2011"
            assert canonical_fields["classificationTreatmentId"] == "anzsoc-2011-native"
            assert canonical_fields["federalOffenceGroupVersionId"] == (
                f"abs-federal-offence-group-release-{shard['releaseId']}"
            )


def test_independent_verifier_requires_external_literal_pin() -> None:
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "scripts/verify-federal-defendants-semantic-oracle.py",
        "--expected-root-digest",
        EXPECTED_ROOT_DIGEST,
    ]
    result = subprocess.run(
        command, cwd=ROOT, check=True, capture_output=True, text=True, timeout=180
    )
    report = json.loads(result.stdout)
    assert report == {
        "attachableTailNoteCellCount": 135,
        "blockCount": 148,
        "commentStatusCount": 8,
        "familyCount": 23,
        "formulaCount": 0,
        "manifestDigest": EXPECTED_ROOT_DIGEST,
        "memberCount": 36,
        "notPublishedCount": 54,
        "sourceCommentNoteCount": 231,
        "sourceExclusionCount": 1041,
        "sourceLayoutHeadingCount": 9,
        "targetCount": 18_793,
        "totalShardBytes": 98_648_284,
        "zeroCount": 3_378,
    }
    missing = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "scripts/verify-federal-defendants-semantic-oracle.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert missing.returncode != 0
    assert "--expected-root-digest" in missing.stderr


def test_external_root_mismatch_fails_before_manifest_trust() -> None:
    module = load_verifier("fd_oracle_external_mismatch")
    with pytest.raises(AssertionError, match="FD_ORACLE_EXTERNAL_ROOT_MISMATCH"):
        module.verify("sha256:" + "0" * 64)


def test_oracle_builder_uses_fresh_isolated_a_b_roots(
    tmp_path: Path,
) -> None:
    before = stable_hashes()
    outputs: list[dict[str, str]] = []
    reports: list[dict[str, Any]] = []
    for name in ("a", "b"):
        output = tmp_path / name
        output.mkdir()
        built = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "scripts/build-federal-defendants-semantic-oracle.py",
                "--output-root",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        report = json.loads(built.stdout)
        assert report["rootDigest"] == EXPECTED_ROOT_DIGEST
        subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                "scripts/verify-federal-defendants-semantic-oracle.py",
                "--expected-root-digest",
                EXPECTED_ROOT_DIGEST,
                "--artifact-root",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
        outputs.append(stable_hashes(output))
        reports.append(report)
    assert outputs[0] == outputs[1]
    assert reports[0] == reports[1]
    assert stable_hashes() == before


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("source", "FD_ORACLE_RECORD_SOURCE_BINDINGS"),
        ("rule", "FD_ORACLE_RECORD_RULE_BINDINGS"),
        ("coordinate-count", "FD_ORACLE_MEMBER_COORDINATE_DESCRIPTOR"),
        ("coordinate-digest", "FD_ORACLE_MEMBER_COORDINATE_DESCRIPTOR"),
        ("np-state", "FD_ORACLE_COMPLETE_VALUE_STATE"),
    ],
)
def test_shard_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch, mutation: str, code: str
) -> None:
    module = load_verifier(f"fd_oracle_shard_{mutation}")
    relative = (
        "fixtures/product-prototype/federal-defendants-source-coordinate-semantic-oracle-v1/"
        + (
            "2024-25-federal-offence-group-table-7.json"
            if mutation == "np-state"
            else "2022-23-federal-offence-group-table-7.json"
        )
    )

    def mutate(shard: dict[str, Any]) -> None:
        if mutation == "source":
            shard["records"][0]["sourceBindings"]["row"]["indent"] += 1
        elif mutation == "rule":
            shard["records"][0]["ruleBindings"]["rowRuleId"] += "-stale"
        elif mutation == "coordinate-count":
            shard["targetCoordinateCount"] += 1
        elif mutation == "coordinate-digest":
            shard["targetCoordinateDigest"] = "sha256:" + "0" * 64
        else:
            record = next(
                record
                for record in shard["records"]
                if record["sourceProof"]["rawValue"] == "np"
            )
            record["valueState"]["sourceComment"] = "not source-authored"

    expected = install_mutated_reads(
        monkeypatch, module, shard_path=relative, shard_mutator=mutate
    )
    with pytest.raises((AssertionError, jsonschema.ValidationError), match=code):
        module.verify(expected)


@pytest.mark.parametrize(
    ("proof_kind", "code"),
    [
        ("source-assertion", "FD_ORACLE_SOURCE_ASSERTION"),
        ("axis-indent", "FD_ORACLE_AXIS_ASSERTION"),
        ("axis-style", "FD_ORACLE_AXIS_ASSERTION"),
        ("parent-indent", "FD_ORACLE_PARENT_ASSERTION"),
    ],
)
def test_exact_source_style_indent_and_parent_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch, proof_kind: str, code: str
) -> None:
    module = load_verifier(f"fd_oracle_assertion_{proof_kind}")

    def mutate(authority: dict[str, Any]) -> None:
        if proof_kind == "source-assertion":
            authority["members"][0]["blocks"][0]["sourceAssertions"][0]["rawValue"] += (
                " stale"
            )
        elif proof_kind == "axis-indent":
            authority["members"][0]["blocks"][0]["rowRules"][0]["indent"] += 1
        elif proof_kind == "axis-style":
            authority["members"][0]["blocks"][0]["rowRules"][0]["styleIndex"] += 1
        else:
            column = next(
                column
                for member in authority["members"]
                for block in member["blocks"]
                for column in block["columnRules"]
                if column["parentAddress"] is not None
            )
            column["parentIndent"] += 1

    expected = install_mutated_reads(monkeypatch, module, authority_mutator=mutate)
    with pytest.raises(AssertionError, match=code):
        module.verify(expected)


def test_family_membership_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier("fd_oracle_membership")

    def mutate(membership: dict[str, Any]) -> None:
        membership["families"][0]["members"][0]["publishedTitle"] += " stale"

    expected = install_mutated_reads(
        monkeypatch,
        module,
        evidence_name="familyMembership",
        evidence_mutator=mutate,
    )
    with pytest.raises(AssertionError, match="FD_ORACLE_FAMILY_CUSTODY_MEMBERS"):
        module.verify(expected)


def test_block_count_and_range_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier("fd_oracle_block_count")

    def remove_block(authority: dict[str, Any]) -> None:
        authority["members"][0]["blocks"].pop()

    expected = install_mutated_reads(
        monkeypatch, module, authority_mutator=remove_block
    )
    with pytest.raises(AssertionError, match="FD_ORACLE_BLOCK_COUNT"):
        module.verify(expected)

    monkeypatch.undo()
    module = load_verifier("fd_oracle_range")

    def shrink_range(authority: dict[str, Any]) -> None:
        authority["members"][0]["blocks"][0]["rowHeaderRange"] = "Z999:Z999"

    expected = install_mutated_reads(
        monkeypatch, module, authority_mutator=shrink_range
    )
    with pytest.raises(AssertionError, match="FD_ORACLE_AUTHORITATIVE_RANGE"):
        module.verify(expected)


@pytest.mark.parametrize("kind", ["panel-key", "tail-note", "merged-source"])
def test_all_authority_coordinates_reject_out_of_range_repins(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    module = load_verifier(f"fd_oracle_authority_range_{kind}")
    target_identity: str | None = None
    target_requested: str | None = None

    def mutate(authority: dict[str, Any]) -> None:
        nonlocal target_identity, target_requested
        if kind == "panel-key":
            member = authority["members"][0]
            member["blocks"][0]["panelKeyAddress"] = "A999"
            return
        if kind == "tail-note":
            member = next(
                item for item in authority["members"] if item["tailNoteRange"]
            )
            member["tailNoteRange"] = "A999:A999"
            return
        member = authority["members"][0]
        assertion = member["blocks"][0]["sourceAssertions"][0]
        target_identity = member["memberId"]
        target_requested = assertion["requestedAddress"]
        assertion["address"] = "A999"
        assertion["sourceAddress"] = "A999"

    expected = install_mutated_reads(monkeypatch, module, authority_mutator=mutate)
    if kind == "merged-source":
        assert target_identity and target_requested
        original_sheet = module.IndependentSheet

        class SheetWithOutOfRangeMergedSource(original_sheet):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(*args, **kwargs)
                self._test_identity = str(args[3])

            def cell(self, requested: str, merged: bool = False):
                result = super().cell(requested, merged)
                if (
                    merged
                    and self._test_identity == target_identity
                    and requested == target_requested
                ):
                    result["sourceAddress"] = "A999"
                return result

        monkeypatch.setattr(module, "IndependentSheet", SheetWithOutOfRangeMergedSource)
    with pytest.raises(AssertionError, match="FD_ORACLE_AUTHORITATIVE_RANGE"):
        module.verify(expected)


def test_exclusion_ledger_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier("fd_oracle_exclusion")

    def mutate(ledger: dict[str, Any]) -> None:
        ledger["sheets"][0]["excludedNonblankCells"][0]["value"] += " stale"

    expected = install_mutated_reads(
        monkeypatch,
        module,
        evidence_name="boundedExclusions",
        evidence_mutator=mutate,
    )
    with pytest.raises(AssertionError, match="FD_ORACLE_EXCLUSION_CELL_CLOSURE"):
        module.verify(expected)


@pytest.mark.parametrize("kind", ["comment", "tail-note"])
def test_source_comment_and_tail_note_omissions_fail_closed(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    module = load_verifier(f"fd_oracle_note_omission_{kind}")

    def mutate(authority: dict[str, Any]) -> None:
        member = next(
            member
            for member in authority["members"]
            if any(
                note["sourceKind"] == ("comment" if kind == "comment" else "note-cell")
                for block in member["blocks"]
                for note in block["noteDefinitions"]
            )
        )
        target = next(
            note
            for note in member["blocks"][0]["noteDefinitions"]
            if note["sourceKind"] == ("comment" if kind == "comment" else "note-cell")
        )
        note_id = target["noteBindingId"]
        for block in member["blocks"]:
            block["noteDefinitions"] = [
                note
                for note in block["noteDefinitions"]
                if note["noteBindingId"] != note_id
            ]
            block["blockNoteBindingIds"] = [
                value for value in block["blockNoteBindingIds"] if value != note_id
            ]
            for rule in [*block["rowRules"], *block["columnRules"], block["panelRule"]]:
                rule["noteBindingIds"] = [
                    value for value in rule["noteBindingIds"] if value != note_id
                ]

    expected = install_mutated_reads(monkeypatch, module, authority_mutator=mutate)
    with pytest.raises(
        AssertionError, match="FD_ORACLE_RECORD_(RULE_BINDINGS|CANONICAL)"
    ):
        module.verify(expected)


def test_raw_comment_set_rejects_unbound_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier("fd_oracle_raw_comment_set")
    original_sheet = module.IndependentSheet

    class SheetWithExtraComment(original_sheet):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            cell = self.cells.setdefault("B1", self.blank("B1"))
            cell["comment"] = "unbound source comment"

    monkeypatch.setattr(module, "IndependentSheet", SheetWithExtraComment)
    with pytest.raises(AssertionError, match="FD_ORACLE_RAW_COMMENT_SET"):
        module.verify(EXPECTED_ROOT_DIGEST)


def test_raw_tail_note_set_rejects_unbound_cell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier("fd_oracle_raw_tail_set")
    authority = json.loads(AUTHORITY.read_text())
    target = next(member for member in authority["members"] if member["tailNoteRange"])
    last = int(target["tailNoteRange"].split(":")[1][1:])
    extra_address = f"A{last + 1}"

    def mutate(mutated_authority: dict[str, Any]) -> None:
        member = next(
            item
            for item in mutated_authority["members"]
            if item["memberId"] == target["memberId"]
        )
        first = member["tailNoteRange"].split(":")[0]
        member["tailNoteRange"] = f"{first}:{extra_address}"

    expected = install_mutated_reads(monkeypatch, module, authority_mutator=mutate)
    original_sheet = module.IndependentSheet

    class SheetWithExtraTailCell(original_sheet):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            identity = str(args[3])
            if identity == target["memberId"]:
                cell = self.blank(extra_address)
                cell.update(
                    rawValue="unbound tail note",
                    rawSemanticScalar="unbound tail note",
                    dataType="string",
                )
                self.cells[extra_address] = cell

    monkeypatch.setattr(module, "IndependentSheet", SheetWithExtraTailCell)
    with pytest.raises(AssertionError, match="FD_ORACLE_TAIL_NOTE_SET"):
        module.verify(expected)


def test_schema_rejects_synthetic_semantic_key_fields() -> None:
    schema = json.loads(
        (
            CONTRACTS
            / "federal-defendants-source-coordinate-semantic-oracle-member.schema.json"
        ).read_text()
    )
    shard = json.loads((SHARDS / "2021-22-national-table-1.json").read_text())
    for forbidden in (
        "sourceDigest",
        "cellProofDigest",
        "memberId",
        "sourcePath",
        "blockId",
        "tableRuleId",
        "rowOrdinal",
        "aliasHash",
        "referenceDate",
    ):
        mutated = json.loads(json.dumps(shard))
        mutated["records"][0]["semanticKey"][forbidden] = "forbidden"
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(mutated)


def test_all_input_budgets_fail_at_one_over(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_verifier("fd_oracle_budgets")
    authority_size = AUTHORITY.stat().st_size
    monkeypatch.setattr(module, "MAX_AUTHORITY_BYTES", authority_size - 1)
    with pytest.raises(AssertionError, match="FD_ORACLE_INPUT_BYTE_LIMIT"):
        module.verify(EXPECTED_ROOT_DIGEST)
    monkeypatch.undo()

    module = load_verifier("fd_oracle_shard_budget")
    total = sum(
        item["byteLength"] for item in json.loads(MANIFEST.read_text())["shards"]
    )
    monkeypatch.setattr(module, "MAX_TOTAL_SHARD_BYTES", total - 1)
    with pytest.raises(AssertionError, match="FD_ORACLE_SHARD_BYTE_BUDGET"):
        module.verify(EXPECTED_ROOT_DIGEST)
    monkeypatch.undo()

    module = load_verifier("fd_oracle_node_budget")
    value = {"a": 1}
    nodes = module.count_json_nodes(value)
    monkeypatch.setattr(module, "MAX_JSON_NODES", nodes - 1)
    with pytest.raises(AssertionError, match="FD_ORACLE_JSON_NODE_LIMIT"):
        module.decode_json(b'{"a":1}', "one-over", 100)
    monkeypatch.undo()

    module = load_verifier("fd_oracle_path_budget")
    monkeypatch.setattr(module, "MAX_PATH_BYTES", len("a.json") - 1)
    with pytest.raises(AssertionError, match="FD_ORACLE_PATH_LENGTH"):
        module.lexical_relative("a.json")


@pytest.mark.parametrize("absolute", [False, True])
def test_descriptor_traversal_rejects_parent_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, absolute: bool
) -> None:
    module = load_verifier(f"fd_oracle_openat_parent_swap_{absolute}")
    base = tmp_path / "base"
    parent = base / "race-parent"
    parked = base / "parked-parent"
    parent.mkdir(parents=True)
    (parent / "value.txt").write_bytes(b"trusted")
    original_open = module.os.open
    swapped = False

    def racing_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        descriptor = original_open(path, flags, *args, **kwargs)
        if path == "race-parent" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            parent.rename(parked)
            parent.mkdir()
            (parent / "value.txt").write_bytes(b"redirected")
        return descriptor

    monkeypatch.setattr(module.os, "open", racing_open)
    with pytest.raises(AssertionError, match="FD_ORACLE_PATH_INODE"):
        if absolute:
            module.read_absolute(parent / "value.txt", 100)
        else:
            module.read_under(base, "race-parent/value.txt", 100)
    assert swapped


def test_builder_and_verifier_use_descriptor_relative_traversal() -> None:
    for module in (
        load_builder("fd_oracle_builder_openat"),
        load_verifier("fd_oracle_verifier_openat"),
    ):
        source = Path(module.__file__).read_text()
        assert "dir_fd=current" in source
        assert "O_DIRECTORY" in source
        assert "O_NOFOLLOW" in source
        assert "follow_symlinks=False" in source


def test_acceptance_scripts_pin_complete_stdlib_trees() -> None:
    manifest = json.loads(MANIFEST.read_text())
    runtime = manifest["runtime"]
    assert runtime["distributions"] == []
    assert len(runtime["files"]) == 2
    assert {item["identity"] for item in runtime["files"]} == {
        "cpython-executable",
        "python-shared-library",
    }
    assert len(runtime["trees"]) in {1, 2}
    assert {role for tree in runtime["trees"] for role in tree["roles"]} == {
        "stdlib",
        "platstdlib",
    }
    for tree in runtime["trees"]:
        assert tree["regularFileCount"] > 1_000
        assert tree["regularFileByteLength"] > 10_000_000
        assert tree["symlinkCount"] >= 0
        assert tree["contentDigest"].startswith("sha256:")
        assert "site-packages" not in tree["path"]
        assert "dist-packages" not in tree["path"]
    assert not any(
        "site-packages" in item or "dist-packages" in item
        for item in runtime["allowedImportPaths"]
    )
    for path in (
        ROOT / "scripts/build-federal-defendants-semantic-oracle.py",
        ROOT / "scripts/verify-federal-defendants-semantic-oracle.py",
    ):
        source = path.read_text()
        assert "jsonschema" not in source
        assert "importlib.metadata" not in source
        assert "RUNTIME_MODULES" not in source
        assert "inventory_runtime_tree" in source
        assert "audit_all_loaded_modules" in source
        assert "require_acceptance_cli_flags" in source
        assert "RUNTIME_DISTRIBUTIONS: tuple[str, ...] = ()" in source


@pytest.mark.parametrize(
    "script",
    [
        "scripts/build-federal-defendants-semantic-oracle.py",
        "scripts/verify-federal-defendants-semantic-oracle.py",
    ],
)
def test_acceptance_cli_rejects_missing_isolation_flags(script: str) -> None:
    command = [sys.executable, script]
    if "verify" in script:
        command.extend(["--expected-root-digest", EXPECTED_ROOT_DIGEST])
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=30
    )
    assert result.returncode != 0
    assert "RUNTIME_FLAGS" in result.stderr
    assert "-I -S -B" in result.stderr


def test_isolated_sys_path_ignores_pythonpath_and_has_no_site_entries() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = "/tmp/not-authorized/site-packages"
    code = (
        "import json,sys; print(json.dumps({"
        "'flags':[sys.flags.isolated,sys.flags.no_site,"
        "sys.flags.dont_write_bytecode,sys.flags.ignore_environment],"
        "'path':sys.path}))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observed = json.loads(result.stdout)
    assert observed["flags"] == [1, 1, 1, 1]
    assert not any(
        "site-packages" in item
        or "dist-packages" in item
        or item.startswith("/tmp/not-authorized")
        for item in observed["path"]
    )


def test_transitive_stdlib_source_cache_and_extensions_are_tree_covered() -> None:
    module = load_verifier("fd_oracle_stdlib_tree_coverage")
    runtime, covered = module.bootstrap_runtime_snapshot()
    imported = (
        "json",
        "json.decoder",
        "json.encoder",
        "json.scanner",
        "_json",
        "hashlib",
        "_hashlib",
        "zipfile",
        "shutil",
        "struct",
        "threading",
        "bz2",
        "lzma",
        "xml.etree.ElementTree",
        "pathlib",
    )
    for name in imported:
        __import__(name)
        loaded = sys.modules[name]
        for attribute in ("__file__", "__cached__"):
            value = getattr(loaded, attribute, None)
            if value and Path(value).exists():
                assert str(Path(value).absolute()) in covered, (name, attribute, value)
    assert runtime["trees"] == json.loads(MANIFEST.read_text())["runtime"]["trees"]


def test_all_module_audit_rejects_preloaded_uncovered_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_verifier("fd_oracle_all_module_audit")
    runtime, covered = module.bootstrap_runtime_snapshot()
    foreign = tmp_path / "preloaded.py"
    foreign.write_text("raise RuntimeError('must not execute')\n")
    fake = ModuleType("fd_uncovered_preloaded")
    fake.__file__ = str(foreign)
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    with pytest.raises(AssertionError, match="FD_ORACLE_RUNTIME_MODULE_UNCOVERED"):
        module.audit_all_loaded_modules(runtime, covered)


def test_runtime_tree_content_digest_binds_file_and_symlink_bytes(
    tmp_path: Path,
) -> None:
    module = load_verifier("fd_oracle_runtime_tree_content")
    tree = tmp_path / "stdlib"
    tree.mkdir()
    source = tree / "decoder.py"
    source.write_bytes(b"first\n")
    link = tree / "libpython.dylib"
    link.symlink_to("first-target")
    first, _ = module.inventory_runtime_tree(tree, ["stdlib"])
    source.write_bytes(b"second\n")
    second, _ = module.inventory_runtime_tree(tree, ["stdlib"])
    assert second["contentDigest"] != first["contentDigest"]
    source.write_bytes(b"first\n")
    link.unlink()
    link.symlink_to("second-target")
    third, _ = module.inventory_runtime_tree(tree, ["stdlib"])
    assert third["contentDigest"] != first["contentDigest"]
    assert third["symlinkCount"] == 1


@pytest.mark.parametrize(
    "mutation", ["regularFileCount", "symlinkCount", "contentDigest"]
)
def test_stdlib_tree_descriptor_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    module = load_verifier(f"fd_oracle_stdlib_tree_mutation_{mutation}")
    original = module.bootstrap_runtime_snapshot

    def mutated_snapshot():
        runtime, covered = original()
        runtime = json.loads(json.dumps(runtime))
        tree = runtime["trees"][0]
        if mutation == "contentDigest":
            tree[mutation] = "sha256:" + "0" * 64
        else:
            tree[mutation] += 1
        return runtime, covered

    monkeypatch.setattr(module, "bootstrap_runtime_snapshot", mutated_snapshot)
    with pytest.raises(AssertionError, match="FD_ORACLE_RUNTIME_PIN"):
        module.verify(EXPECTED_ROOT_DIGEST)


def _committed_schema_instances() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    names = (
        (
            "federal-defendants-controlled-vocabulary.schema.json",
            FIXTURES / "federal-defendants-controlled-vocabulary-v1.json",
        ),
        (
            "federal-defendants-methodology-evidence.schema.json",
            FIXTURES / "federal-defendants-methodology-evidence-v1.json",
        ),
        ("federal-defendants-semantic-plan.schema.json", AUTHORITY),
        ("federal-defendants-source-coordinate-semantic-oracle.schema.json", MANIFEST),
    )
    for schema_name, instance_path in names:
        pairs.append(
            (
                json.loads((CONTRACTS / schema_name).read_text()),
                json.loads(instance_path.read_text()),
            )
        )
    member_schema = json.loads(
        (
            CONTRACTS
            / "federal-defendants-source-coordinate-semantic-oracle-member.schema.json"
        ).read_text()
    )
    for shard in sorted(SHARDS.glob("*.json"), key=lambda item: item.name.encode()):
        pairs.append((member_schema, json.loads(shard.read_text())))
    return pairs


def test_stdlib_validator_agrees_with_draft202012_on_committed_instances() -> None:
    builder = load_builder("fd_oracle_builder_schema_agreement")
    verifier = load_verifier("fd_oracle_verifier_schema_agreement")
    for schema, instance in _committed_schema_instances():
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).validate(instance)
        builder.validate_schema_subset(instance, schema, "agreement")
        verifier.validate_schema_subset(instance, schema, "agreement")


def test_stdlib_validator_rejects_representative_schema_mutations() -> None:
    modules = (
        load_builder("fd_oracle_builder_schema_mutations"),
        load_verifier("fd_oracle_verifier_schema_mutations"),
    )
    root_schema = json.loads(
        (
            CONTRACTS
            / "federal-defendants-source-coordinate-semantic-oracle.schema.json"
        ).read_text()
    )
    root = json.loads(MANIFEST.read_text())
    authority_schema = json.loads(
        (CONTRACTS / "federal-defendants-semantic-plan.schema.json").read_text()
    )
    authority = json.loads(AUTHORITY.read_text())
    member_schema = json.loads(
        (
            CONTRACTS
            / "federal-defendants-source-coordinate-semantic-oracle-member.schema.json"
        ).read_text()
    )
    shard = json.loads((SHARDS / "2021-22-national-table-1.json").read_text())
    cases: list[tuple[dict[str, Any], dict[str, Any]]] = []
    mutated = json.loads(json.dumps(root))
    mutated["unexpected"] = True
    cases.append((root_schema, mutated))
    mutated = json.loads(json.dumps(root))
    mutated["expected"]["targetCount"] = True
    cases.append((root_schema, mutated))
    mutated = json.loads(json.dumps(authority))
    mutated["members"][0]["publicationVintageDate"] = "2023-02-29"
    cases.append((authority_schema, mutated))
    mutated = json.loads(json.dumps(authority))
    mutated["familyPolicies"][0]["memberIds"].append(
        mutated["familyPolicies"][0]["memberIds"][0]
    )
    cases.append((authority_schema, mutated))
    mutated = json.loads(json.dumps(shard))
    mutated["records"][0]["sourceIdentity"]["address"] = "bad"
    cases.append((member_schema, mutated))
    for schema, instance in cases:
        external = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        assert not external.is_valid(instance)
        for module in modules:
            with pytest.raises(module.SchemaSubsetError):
                module.validate_schema_subset(instance, schema, "mutation")


def test_stdlib_validator_rejects_unsupported_keywords_and_bounds() -> None:
    unsupported = (
        "not",
        "else",
        "dependentRequired",
        "patternProperties",
        "contains",
        "prefixItems",
        "unevaluatedProperties",
    )
    for module in (
        load_builder("fd_oracle_builder_schema_unsupported"),
        load_verifier("fd_oracle_verifier_schema_unsupported"),
    ):
        for keyword in unsupported:
            with pytest.raises(module.SchemaSubsetError, match="UNSUPPORTED_KEYWORD"):
                module.validate_schema_subset({}, {keyword: {}}, keyword)
        with pytest.raises(module.SchemaSubsetError, match="UNSUPPORTED_REF"):
            module.validate_schema_subset(
                {}, {"$ref": "https://example.invalid/x"}, "ref"
            )
        for keyword in ("items", "additionalProperties", "if", "then"):
            with pytest.raises(module.SchemaSubsetError, match="SHAPE"):
                module.validate_schema_subset({}, {keyword: "unsupported"}, keyword)
        nested: dict[str, Any] = {"type": "object"}
        for _ in range(module.MAX_SCHEMA_DEPTH + 1):
            nested = {"properties": {"x": nested}}
        with pytest.raises(module.SchemaSubsetError, match="DEPTH_LIMIT"):
            module.validate_schema_subset({}, nested, "depth")


def test_ooxml_parser_uses_vetted_buffer_not_reopened_path(tmp_path: Path) -> None:
    module = load_verifier("fd_oracle_vetted_buffer")
    source = (
        FIXTURES / "workbooks/federal-defendants-australia-2021-22-national-source.xlsx"
    )
    copied = tmp_path / "book.xlsx"
    shutil.copyfile(source, copied)
    _, vetted_blob = module.read_under(tmp_path, "book.xlsx", 25_000_000)
    copied.write_bytes(b"path changed after vetted read")
    sheet = module.IndependentSheet(vetted_blob, "Table 1", "A1:M64", "buffer-test")
    assert sheet.cell("A4")["rawValue"].startswith(
        "Table 1 Federal defendants finalised"
    )
    source_code = (
        ROOT / "scripts/build-federal-defendants-semantic-oracle.py"
    ).read_text() + (
        ROOT / "scripts/verify-federal-defendants-semantic-oracle.py"
    ).read_text()
    assert "zipfile.ZipFile(workbook_path)" not in source_code
    assert "zipfile.ZipFile(io.BytesIO(" in source_code


def test_boundary_one_does_not_change_rejected_proposal_sources() -> None:
    expected = {
        "scripts/build-federal-defendants-proposal.ts": (
            "sha256:ae6edaeac6465aef4ee1eb1e112e715ca08c1a501e8d91ef5d3d74aec26a3402"
        ),
        "scripts/verify-federal-defendants-proposal.py": (
            "sha256:b7f01f829aee6001345eb5e95afc4ee105779abf4d844049b9cf7d0b227b3567"
        ),
        "tests/test_federal_defendants_proposal.py": (
            "sha256:b3d6a3c63e590cae4be152ecd10affc55c68e6ef85f27cc98d0220eba2849799"
        ),
    }
    assert {relative: digest(ROOT / relative) for relative in expected} == expected


def test_boundary_one_has_no_semantic_inference_or_scope_widening() -> None:
    builder = (ROOT / "scripts/build-federal-defendants-semantic-oracle.py").read_text()
    verifier = (
        ROOT / "scripts/verify-federal-defendants-semantic-oracle.py"
    ).read_text()
    for forbidden in (
        "profileFor",
        "aliasCode",
        "published-value",
        "proofText",
        ".lower()",
    ):
        assert forbidden not in builder
    assert "fieldOwners" in builder
    assert "sourceAssertions" in verifier
    assert "sourceBindings" in verifier
    assert "ruleBindings" in verifier
    assert "indent" in verifier
    assert "--expected-root-digest" in verifier
    inventory = (
        ROOT / "docs/federal-defendants-semantic-rule-inventory.md"
    ).read_text()
    assert "not a single cross-path filesystem transaction" in inventory
    assert "does not claim whole-corpus transactional publication" in inventory
