from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import stat
from pathlib import Path
from typing import Any

import pytest

from tidy_orchestrator.data_asset_status import DEFAULT_REGISTRY, sha256_digest
from tidy_orchestrator.sqlite_export import (
    MAX_RELEASE_BYTES,
    SQLiteExportError,
    build_export,
    check_export,
    package_checked_export,
)
from tidy_orchestrator.sqlite_export_cli import main as sqlite_export_main

PROJECT = Path(__file__).parents[1]
COHORT = Path("fixtures/product-prototype/prisoners-table-30-2021-2025.json")
EVIDENCE = Path("fixtures/product-prototype/five-year-evidence")
FAKE_DIGEST = "sha256:" + "1" * 64
PUBLIC_SCHEMA_VERSION = "tidy.sqlite-data-asset-export/v1"
PUBLIC_TABLE_COLUMNS = {
    "export_metadata": (
        "export_id",
        "schema_version",
        "registry_recorded_at",
        "registry_path",
        "registry_sha256",
        "registry_byte_length",
        "publication_count",
        "cohort_count",
        "asset_count",
        "observation_count",
        "physical_workbook_count",
        "logical_content_sha256",
        "acceptance_authority",
        "training_eligibility",
        "provider_calls",
    ),
    "publication": (
        "publication_id",
        "publication_ordinal",
        "label",
        "period_format",
    ),
    "cohort": (
        "cohort_id",
        "cohort_ordinal",
        "publication_id",
        "label",
        "dagster_asset",
        "checks_state",
        "evidence_recorded_at",
        "asset_count",
        "observation_count",
    ),
    "asset": (
        "asset_id",
        "asset_ordinal",
        "cohort_id",
        "publication_id",
        "year",
        "reference_date",
        "sheet",
        "source_path",
        "source_digest",
        "source_byte_length",
        "identified_status",
        "on_disk_status",
        "tidied_status",
        "canonicalised_status",
        "integrated_status",
        "checks_state",
        "canonical_count",
        "raw_count",
        "excluded_count",
        "decision",
        "decision_id",
        "prepare_derivation_id",
        "interpret_derivation_id",
        "replay_model",
        "evidence_recorded_at",
        "normalization",
        "live_evidence_path",
    ),
    "asset_check": ("asset_id", "check_name", "passed"),
    "provenance_file": (
        "provenance_ordinal",
        "cohort_id",
        "role",
        "path",
        "sha256",
        "byte_length",
    ),
    "observation": (
        "observation_id",
        "asset_id",
        "asset_row_ordinal",
        "cohort_id",
        "publication_id",
        "canonical_publication_id",
        "publication_vintage_date",
        "reference_date",
        "observation_period_id",
        "measure_id",
        "unit_id",
        "value_status",
        "value_type",
        "value_integer",
        "value_real",
        "raw_value_type",
        "raw_value_text",
        "raw_value_integer",
        "raw_value_real",
        "source_workbook_digest",
        "source_sheet",
        "source_cell",
        "acceptance_decision_digest",
        "acceptance_policy_digest",
        "acceptance_policy_version",
        "recipe_digest",
        "execution_digest",
        "prompt_package_digest",
        "generation_attempt_id",
        "generation_model",
        "canonical_json",
    ),
}
PUBLIC_TABLE_SET = frozenset(
    {
        "export_metadata",
        "publication",
        "cohort",
        "asset",
        "asset_check",
        "provenance_file",
        "observation",
    }
)


def _copy_export_project(destination: Path) -> None:
    fixture_root = destination / "fixtures/product-prototype"
    fixture_root.mkdir(parents=True)
    shutil.copy2(PROJECT / COHORT, destination / COHORT)
    shutil.copytree(PROJECT / EVIDENCE, destination / EVIDENCE)
    acceptance = fixture_root / "acceptance"
    acceptance.mkdir()
    shutil.copy2(
        PROJECT / "fixtures/product-prototype/acceptance/prisoners-table-30-v1.json",
        acceptance / "prisoners-table-30-v1.json",
    )
    source_workbooks = PROJECT / "fixtures/product-prototype/workbooks"
    target_workbooks = fixture_root / "workbooks"
    target_workbooks.mkdir()
    for year in range(2021, 2026):
        shutil.copy2(
            source_workbooks / f"prisoners-australia-{year}.xlsx",
            target_workbooks / f"prisoners-australia-{year}.xlsx",
        )
    registry = {
        "schemaVersion": "tidy.data-asset-status-registry/v1",
        "title": "SQLite export test",
        "recordedAt": "2026-08-14T08:00:00+00:00",
        "outputPath": "docs/data-asset-status/index.html",
        "server": {
            "host": "127.0.0.1",
            "port": 3031,
            "tailnetHostname": "test.tailnet.example",
            "tailnetHttpsPort": 3031,
            "dagsterPort": 3030,
        },
        "publications": [
            {
                "publicationId": "prisoners-australia",
                "label": "Prisoners in Australia",
                "periodFormat": "calendar-year",
            }
        ],
        "cohorts": [
            {
                "cohortId": "prisoners-australia-table-30-2021-2025",
                "label": "Table 30 test",
                "cohortPath": COHORT.as_posix(),
                "evidenceManifestPath": (EVIDENCE / "manifest.json").as_posix(),
                "dagsterAsset": "product_prototype_replay",
            }
        ],
    }
    registry_path = destination / DEFAULT_REGISTRY
    registry_path.write_text(json.dumps(registry, indent=2) + "\n")


def _manifest(destination: Path) -> tuple[Path, dict[str, Any]]:
    path = destination / EVIDENCE / "manifest.json"
    return path, json.loads(path.read_text())


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def _redeclare_file(manifest: dict[str, Any], name: str, data: bytes) -> None:
    declaration = next(item for item in manifest["files"] if item["path"] == name)
    declaration["contentDigest"] = sha256_digest(data)
    declaration["byteLength"] = len(data)


def _rewrite_run(destination: Path, mutate: Any) -> None:
    run_path = destination / EVIDENCE / "run.json"
    run = json.loads(run_path.read_text())
    mutate(run)
    data = (json.dumps(run, sort_keys=True, separators=(",", ":")) + "\n").encode()
    run_path.write_bytes(data)
    manifest_path, manifest = _manifest(destination)
    _redeclare_file(manifest, "run.json", data)
    _write_manifest(manifest_path, manifest)


def _rewrite_run_and_manifest_count(
    destination: Path, field: str, run_value: object, manifest_value: object
) -> None:
    _rewrite_run(destination, lambda run: run.__setitem__(field, run_value))
    manifest_path, manifest = _manifest(destination)
    manifest[field] = manifest_value
    _write_manifest(manifest_path, manifest)


def _rewrite_canonical(destination: Path, mutate: Any) -> list[dict[str, Any]]:
    canonical = destination / EVIDENCE / "canonical-observations.json"
    rows = json.loads(canonical.read_text())
    mutate(rows)
    data = (json.dumps(rows, indent=2, ensure_ascii=False) + "\n").encode()
    canonical.write_bytes(data)
    manifest_path, manifest = _manifest(destination)
    _redeclare_file(manifest, "canonical-observations.json", data)
    _write_manifest(manifest_path, manifest)
    return rows


def _build_checked(destination: Path) -> tuple[Path, dict[str, Any]]:
    database = destination / "export.sqlite3"
    build_export(destination, output=database)
    return database, check_export(destination, database=database)


def test_build_and_check_exact_registered_projection(tmp_path: Path) -> None:
    _copy_export_project(tmp_path)
    database, checked = _build_checked(tmp_path)
    assert checked["schemaVersion"] == PUBLIC_SCHEMA_VERSION
    assert checked["observations"] == 1215
    assert checked["assets"] == 5
    assert checked["acceptanceAuthority"] is False
    assert checked["trainingEligibility"] is False
    assert checked["providerCalls"] == 0
    assert checked["integrityCheck"] == "ok"
    assert checked["foreignKeyViolations"] == 0
    assert checked["provenance"] == "matches-current-registered-evidence"
    assert stat.S_IMODE(database.stat().st_mode) == 0o644
    assert all(
        not Path(str(database) + suffix).exists()
        for suffix in ("-wal", "-shm", "-journal")
    )

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        public_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert public_tables == PUBLIC_TABLE_SET
        for table, expected_columns in PUBLIC_TABLE_COLUMNS.items():
            assert (
                tuple(
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                )
                == expected_columns
            )
        metadata = connection.execute(
            "SELECT schema_version, acceptance_authority, training_eligibility, "
            "provider_calls FROM export_metadata"
        ).fetchone()
        assert metadata == (PUBLIC_SCHEMA_VERSION, 0, 0, 0)
        identities = connection.execute(
            "SELECT publication_id, canonical_publication_id FROM observation LIMIT 1"
        ).fetchone()
        assert identities == ("prisoners-australia", "prisoners-in-australia")
        assert connection.execute(
            "SELECT count(*) FROM provenance_file"
        ).fetchone() == (7,)


def test_heterogeneous_scalars_are_semantically_lossless_and_logically_stable(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    values = [True, None, "np", 1.25]

    def mutate(rows: list[dict[str, Any]]) -> None:
        for row, value in zip(rows[:4], values, strict=True):
            row["raw_value"] = value
            row["heterogeneous_scalar"] = value

    rows = _rewrite_canonical(tmp_path, mutate)
    first = tmp_path / "first.sqlite3"
    second = tmp_path / "second.sqlite3"
    first_result = build_export(tmp_path, output=first)
    second_result = build_export(tmp_path, output=second)
    assert first_result["logicalContentSha256"] == second_result["logicalContentSha256"]
    with sqlite3.connect(first) as connection:
        exported = connection.execute(
            "SELECT canonical_json, raw_value_type, raw_value_text, "
            "raw_value_integer, raw_value_real FROM observation "
            "ORDER BY observation_id LIMIT 4"
        ).fetchall()
    assert [json.loads(item[0]) for item in exported] == rows[:4]
    assert [item[1] for item in exported] == ["boolean", "null", "string", "real"]
    assert exported[0][3] == 1
    assert exported[2][2] == "np"
    assert exported[3][4] == 1.25


@pytest.mark.parametrize("location", ["manifest", "run"])
@pytest.mark.parametrize("value", ["missing", False, 0.0, 1])
def test_provider_calls_must_be_cross_file_literal_integer_zero(
    tmp_path: Path, location: str, value: object
) -> None:
    _copy_export_project(tmp_path)
    if location == "manifest":
        manifest_path, manifest = _manifest(tmp_path)
        if value == "missing":
            manifest.pop("providerCalls")
        else:
            manifest["providerCalls"] = value
        _write_manifest(manifest_path, manifest)
    else:

        def mutate(run: dict[str, Any]) -> None:
            if value == "missing":
                run.pop("providerCalls")
            else:
                run["providerCalls"] = value

        _rewrite_run(tmp_path, mutate)
    with pytest.raises(SQLiteExportError, match="providerCalls.*integer 0"):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("acceptedWorkbookCount", "missing"),
        ("acceptedWorkbookCount", False),
        ("acceptedWorkbookCount", 5.0),
        ("exceptionWorkbookCount", 1),
        ("canonicalObservationCount", 1216),
    ],
)
def test_manifest_aggregate_counts_are_strict_and_cross_file(
    tmp_path: Path, field: str, value: object
) -> None:
    _copy_export_project(tmp_path)
    manifest_path, manifest = _manifest(tmp_path)
    if value == "missing":
        manifest.pop(field)
    else:
        manifest[field] = value
    _write_manifest(manifest_path, manifest)
    with pytest.raises(SQLiteExportError, match=field):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")


@pytest.mark.parametrize("value", ["missing", False, 5.0])
def test_run_required_aggregate_count_is_strict(tmp_path: Path, value: object) -> None:
    _copy_export_project(tmp_path)

    def mutate(run: dict[str, Any]) -> None:
        if value == "missing":
            run.pop("acceptedWorkbookCount")
        else:
            run["acceptedWorkbookCount"] = value

    _rewrite_run(tmp_path, mutate)
    with pytest.raises(SQLiteExportError, match="Run acceptedWorkbookCount"):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("canonicalObservationCount", 1216),
        ("rawObservationCount", False),
        ("rawObservationCount", 1215.0),
        ("rawObservationCount", 1216),
        ("excludedObservationCount", 1),
    ],
)
def test_coherently_redeclared_run_manifest_counts_must_match_derived_totals(
    tmp_path: Path, field: str, value: object
) -> None:
    _copy_export_project(tmp_path)
    _rewrite_run_and_manifest_count(tmp_path, field, value, value)
    with pytest.raises(SQLiteExportError, match=field):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")


def test_declared_raw_count_cross_file_mismatch_is_rejected(tmp_path: Path) -> None:
    _copy_export_project(tmp_path)
    _rewrite_run_and_manifest_count(tmp_path, "rawObservationCount", 1216, 1215)
    with pytest.raises(SQLiteExportError, match="Manifest/run rawObservationCount"):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")


def test_aggregate_mutation_rejects_build_check_and_cli_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _copy_export_project(tmp_path)
    database, _checked = _build_checked(tmp_path)
    package = tmp_path / "victim.sqlite3.gz"
    package.write_bytes(b"package-victim")
    manifest_path, manifest = _manifest(tmp_path)
    manifest["canonicalObservationCount"] = 1216
    _write_manifest(manifest_path, manifest)
    with pytest.raises(SQLiteExportError, match="canonicalObservationCount"):
        build_export(tmp_path, output=tmp_path / "new.sqlite3")
    with pytest.raises(SQLiteExportError, match="canonicalObservationCount"):
        check_export(tmp_path, database=database)
    assert (
        sqlite_export_main(
            [
                "--project-root",
                str(tmp_path),
                "package",
                "--database",
                str(database),
                "--output",
                str(package),
            ]
        )
        == 2
    )
    assert "canonicalObservationCount" in capsys.readouterr().err
    assert package.read_bytes() == b"package-victim"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("historicalReplayIsAcceptanceAuthority", "missing"),
        ("historicalReplayIsAcceptanceAuthority", 0),
        ("historicalReplayIsAcceptanceAuthority", True),
        ("trainingEligibility", "missing"),
        ("trainingEligibility", 0),
        ("trainingEligibility", True),
    ],
)
def test_run_non_authority_fields_must_be_literal_false(
    tmp_path: Path, field: str, value: object
) -> None:
    _copy_export_project(tmp_path)

    def mutate(run: dict[str, Any]) -> None:
        if value == "missing":
            run.pop(field)
        else:
            run[field] = value

    _rewrite_run(tmp_path, mutate)
    with pytest.raises(SQLiteExportError, match=f"{field} must be literal false"):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")


def test_coherently_redeclared_decision_and_policy_mutations_are_rejected(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    _rewrite_canonical(
        tmp_path,
        lambda rows: rows[0].__setitem__("acceptance_decision_digest", FAKE_DIGEST),
    )
    with pytest.raises(SQLiteExportError, match="decision does not match"):
        build_export(tmp_path, output=tmp_path / "decision.sqlite3")

    _copy_export_project(tmp_path / "policy")
    _rewrite_canonical(
        tmp_path / "policy",
        lambda rows: rows[0].__setitem__("acceptance_policy_digest", FAKE_DIGEST),
    )
    with pytest.raises(SQLiteExportError, match="policy does not match contract"):
        build_export(tmp_path / "policy", output=tmp_path / "policy.sqlite3")


def test_malformed_row_digest_is_rejected_after_coherent_redeclaration(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    _rewrite_canonical(
        tmp_path,
        lambda rows: rows[0].__setitem__("acceptance_decision_digest", "not-a-digest"),
    )
    with pytest.raises(SQLiteExportError, match="literal sha256 digest"):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")


def test_coherently_redeclared_manifest_run_contract_mutation_is_rejected(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    _rewrite_run(
        tmp_path,
        lambda run: run.__setitem__("acceptanceContractDigest", FAKE_DIGEST),
    )
    manifest_path, manifest = _manifest(tmp_path)
    manifest["acceptanceContractDigest"] = FAKE_DIGEST
    _write_manifest(manifest_path, manifest)
    with pytest.raises(SQLiteExportError, match="does not match cohort"):
        build_export(tmp_path, output=tmp_path / "rejected.sqlite3")

    _copy_export_project(tmp_path / "mismatch")
    manifest_path, manifest = _manifest(tmp_path / "mismatch")
    manifest["acceptanceContractDigest"] = FAKE_DIGEST
    _write_manifest(manifest_path, manifest)
    with pytest.raises(SQLiteExportError, match="Manifest/run.*mismatch"):
        build_export(tmp_path / "mismatch", output=tmp_path / "mismatch.sqlite3")


@pytest.mark.parametrize(
    "victim_relative",
    [
        DEFAULT_REGISTRY,
        COHORT,
        EVIDENCE / "manifest.json",
        Path("fixtures/product-prototype/acceptance/prisoners-table-30-v1.json"),
        EVIDENCE / "canonical-observations.json",
        Path("fixtures/product-prototype/workbooks/prisoners-australia-2021.xlsx"),
    ],
)
def test_build_rejects_registered_input_targets_without_changing_victim(
    tmp_path: Path, victim_relative: Path
) -> None:
    _copy_export_project(tmp_path)
    victim = tmp_path / victim_relative
    original = victim.read_bytes()
    with pytest.raises(SQLiteExportError, match="registered input"):
        build_export(tmp_path, output=victim)
    assert victim.read_bytes() == original


def test_build_rejects_registered_input_hardlink_without_changing_victim(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    victim = tmp_path / EVIDENCE / "canonical-observations.json"
    output = tmp_path / "hardlink.sqlite3"
    output.hardlink_to(victim)
    before = (victim.read_bytes(), victim.stat().st_ino, victim.stat().st_nlink)
    with pytest.raises(
        SQLiteExportError, match="filesystem identity.*registered input"
    ):
        build_export(tmp_path, output=output)
    assert output.samefile(victim)
    assert (victim.read_bytes(), victim.stat().st_ino, victim.stat().st_nlink) == before


def test_samefile_filesystem_errors_are_controlled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_export_project(tmp_path)
    output = tmp_path / "existing.sqlite3"
    output.write_bytes(b"victim")

    def fail_samefile(_self: Path, _other: Path) -> bool:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "samefile", fail_samefile)
    with pytest.raises(SQLiteExportError, match="Cannot verify filesystem identity"):
        build_export(tmp_path, output=output)
    assert output.read_bytes() == b"victim"


def test_build_rejects_output_symlink_without_changing_victim(tmp_path: Path) -> None:
    _copy_export_project(tmp_path)
    victim = tmp_path / "victim.sqlite3"
    victim.write_bytes(b"victim")
    output = tmp_path / "export.sqlite3"
    output.symlink_to(victim)
    with pytest.raises(SQLiteExportError, match="must not be a symlink"):
        build_export(tmp_path, output=output)
    assert victim.read_bytes() == b"victim"


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_build_and_check_reject_existing_sidecars_without_unlinking(
    tmp_path: Path, suffix: str
) -> None:
    _copy_export_project(tmp_path)
    target = tmp_path / "export.sqlite3"
    target.write_bytes(b"victim")
    sidecar = Path(str(target) + suffix)
    sidecar.write_bytes(b"sidecar-victim")
    with pytest.raises(SQLiteExportError, match="sidecar"):
        build_export(tmp_path, output=target)
    assert target.read_bytes() == b"victim"
    assert sidecar.read_bytes() == b"sidecar-victim"

    sidecar.unlink()
    build_export(tmp_path, output=target)
    sidecar.write_bytes(b"sidecar-victim")
    with pytest.raises(SQLiteExportError, match="sidecar"):
        check_export(tmp_path, database=target)
    assert sidecar.read_bytes() == b"sidecar-victim"


def test_strict_schema_rejects_discriminator_and_hierarchy_tampering(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    database, _checked = _build_checked(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE observation SET value_real=1.0 WHERE value_type='integer'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE observation SET raw_value_type='boolean', "
                "raw_value_text=NULL, raw_value_integer=NULL, raw_value_real=NULL "
                "WHERE observation_id=1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE observation SET cohort_id='wrong' WHERE observation_id=1"
            )

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute(
            "UPDATE sqlite_schema SET sql=replace(sql, "
            "'registry_path TEXT NOT NULL', 'registry_path TEXT') "
            "WHERE name='export_metadata'"
        )
    with pytest.raises(SQLiteExportError, match="DDL does not match"):
        check_export(tmp_path, database=database)


def test_checked_packaging_is_deterministic_and_verifies_decompression(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    database, checked = _build_checked(tmp_path)
    first = tmp_path / "first.sqlite3.gz"
    second = tmp_path / "second.sqlite3.gz"
    first_result = package_checked_export(database, checked, first)
    package_checked_export(database, checked, second)
    assert first.read_bytes() == second.read_bytes()
    assert gzip.decompress(first.read_bytes()) == database.read_bytes()
    assert first_result["decompressedSourceVerified"] is True
    assert first_result["validatedAgainstEvidence"] is True
    assert first_result["maximumByteLengthExclusive"] == MAX_RELEASE_BYTES
    assert first_result["sha256"] == sha256_digest(first.read_bytes())
    with pytest.raises(SQLiteExportError, match="strictly smaller"):
        package_checked_export(
            database, checked, tmp_path / "too-large.gz", max_bytes=1
        )
    assert not (tmp_path / "too-large.gz").exists()


def test_packaging_refuses_same_path_symlink_and_changed_source_preserving_victims(
    tmp_path: Path,
) -> None:
    _copy_export_project(tmp_path)
    database, checked = _build_checked(tmp_path)
    original = database.read_bytes()
    with pytest.raises(SQLiteExportError, match="differ from the source"):
        package_checked_export(database, checked, database)
    assert database.read_bytes() == original

    hardlink = tmp_path / "hardlink.gz"
    hardlink.hardlink_to(database)
    before = (database.read_bytes(), database.stat().st_ino, database.stat().st_nlink)
    with pytest.raises(SQLiteExportError, match="filesystem identity.*differ"):
        package_checked_export(database, checked, hardlink)
    assert hardlink.samefile(database)
    assert (
        database.read_bytes(),
        database.stat().st_ino,
        database.stat().st_nlink,
    ) == before
    hardlink.unlink()

    symlink_target = tmp_path / "symlink-victim.gz"
    symlink_target.write_bytes(b"package-victim")
    symlink = tmp_path / "package.gz"
    symlink.symlink_to(symlink_target)
    with pytest.raises(SQLiteExportError, match="must not be a symlink"):
        package_checked_export(database, checked, symlink)
    assert symlink_target.read_bytes() == b"package-victim"

    output = tmp_path / "existing.gz"
    output.write_bytes(b"existing-package")
    database.write_bytes(original + b"changed")
    changed = database.read_bytes()
    with pytest.raises(SQLiteExportError, match="changed after validation"):
        package_checked_export(database, checked, output)
    assert database.read_bytes() == changed
    assert output.read_bytes() == b"existing-package"


def test_cli_build_check_package_success_and_error_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _copy_export_project(tmp_path)
    database = tmp_path / "cli.sqlite3"
    package = tmp_path / "cli.sqlite3.gz"
    prefix = ["--project-root", str(tmp_path)]
    assert sqlite_export_main([*prefix, "build", "--output", str(database)]) == 0
    built = json.loads(capsys.readouterr().out)
    assert built["schemaVersion"] == PUBLIC_SCHEMA_VERSION
    assert sqlite_export_main([*prefix, "check", "--database", str(database)]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["provenance"] == "matches-current-registered-evidence"
    assert (
        sqlite_export_main(
            [
                *prefix,
                "package",
                "--database",
                str(database),
                "--output",
                str(package),
            ]
        )
        == 0
    )
    packaged = json.loads(capsys.readouterr().out)
    assert packaged["validatedAgainstEvidence"] is True
    assert packaged["decompressedSourceVerified"] is True
    assert gzip.decompress(package.read_bytes()) == database.read_bytes()

    assert (
        sqlite_export_main(
            [
                *prefix,
                "package",
                "--database",
                str(database),
                "--output",
                str(database),
            ]
        )
        == 2
    )
    assert "sqlite export error:" in capsys.readouterr().err
    victim = tmp_path / "cli-symlink-victim.gz"
    victim.write_bytes(b"victim")
    symlink = tmp_path / "cli-symlink.gz"
    symlink.symlink_to(victim)
    assert (
        sqlite_export_main(
            [
                *prefix,
                "package",
                "--database",
                str(database),
                "--output",
                str(symlink),
            ]
        )
        == 2
    )
    assert "symlink" in capsys.readouterr().err
    assert victim.read_bytes() == b"victim"


def test_cli_provider_type_error_is_code_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _copy_export_project(tmp_path)
    manifest_path, manifest = _manifest(tmp_path)
    manifest["providerCalls"] = False
    _write_manifest(manifest_path, manifest)
    assert (
        sqlite_export_main(
            [
                "--project-root",
                str(tmp_path),
                "build",
                "--output",
                str(tmp_path / "rejected.sqlite3"),
            ]
        )
        == 2
    )
    assert "providerCalls" in capsys.readouterr().err
