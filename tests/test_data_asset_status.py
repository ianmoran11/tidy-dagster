from __future__ import annotations

import csv
import io
import json
import shutil
import threading
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from tidy_orchestrator.data_asset_status import (
    DEFAULT_REGISTRY,
    DataAssetStatusError,
    build_asset_csv_payloads,
    build_dashboard,
    make_status_server,
    render_dashboard,
    snapshot_matches,
)
from tidy_orchestrator.large_batch import load_large_batch_registry

PROJECT = Path(__file__).parents[1]


def test_current_dashboard_reports_publication_grouped_clean_sheet_assets() -> None:
    status = build_dashboard(PROJECT)
    assert status.title == "Tidy Data Asset Status"
    assert [
        (
            publication.publication_id,
            publication.period_format,
            len(publication.cohorts),
        )
        for publication in status.publications
    ] == [
        ("prisoners-australia", "calendar-year", 27),
        ("recorded-crime-offenders", "fiscal-year", 5),
        ("criminal-courts-australia", "fiscal-year", 80),
    ]
    assert len(status.cohorts) == 112
    assert len(status.assets) == 346
    assert status.physical_workbook_count == 51
    assert {asset.year for asset in status.assets} == set(range(2021, 2026))
    assert all(
        stage == "yes" for asset in status.assets for stage in asset.stages.values()
    )
    assert all(asset.checks_state == "pass" for asset in status.assets)
    assert all(not asset.issues for asset in status.assets)
    assert all(asset.csv_route for asset in status.assets)
    assert len({asset.csv_route for asset in status.assets}) == 346
    assert sum(asset.canonical_count or 0 for asset in status.assets) == 296910
    offenders = [
        asset
        for asset in status.assets
        if asset.publication_id == "recorded-crime-offenders"
    ]
    assert len(offenders) == 20
    assert sum(asset.canonical_count or 0 for asset in offenders) == 21268
    assert all(
        asset.publication_label == "Recorded Crime — Offenders" for asset in offenders
    )
    criminal_courts = [
        asset
        for asset in status.assets
        if asset.publication_id == "criminal-courts-australia"
    ]
    assert len(criminal_courts) == 192
    assert sum(asset.canonical_count or 0 for asset in criminal_courts) == 227610
    assert all(
        asset.publication_label == "Criminal Courts, Australia"
        for asset in criminal_courts
    )
    table_21 = [asset for asset in status.assets if "Table 21" in asset.cohort_label]
    table_22 = [asset for asset in status.assets if "Table 22" in asset.cohort_label]
    table_23 = [asset for asset in status.assets if "Table 23" in asset.cohort_label]
    table_30 = [asset for asset in status.assets if "Table 30" in asset.cohort_label]
    table_31 = [asset for asset in status.assets if "Table 31" in asset.cohort_label]
    assert [asset.canonical_count for asset in table_21] == [1053] * 5
    assert [asset.canonical_count for asset in table_22] == [340, 340, 350, 340, 339]
    assert [asset.canonical_count for asset in table_23] == [513, 513, 513, 531, 486]
    assert [asset.canonical_count for asset in table_30] == [243] * 5
    assert [asset.canonical_count for asset in table_31] == [522, 522, 522, 522, 450]
    assert sum(asset.excluded_count or 0 for asset in table_21) == 1467
    batch = load_large_batch_registry(PROJECT)
    for spec in batch.entries:
        cohort_id = json.loads((PROJECT / spec.cohort_path).read_text())["cohortId"]
        assets = [asset for asset in status.assets if asset.cohort_id == cohort_id]
        assert [asset.canonical_count for asset in assets] == list(
            reversed(spec.expected_year_counts)
        )
    normalized = [asset for asset in status.assets if asset.normalization]
    assert Counter(asset.year for asset in normalized) == {
        2021: 60,
        2022: 68,
        2023: 77,
        2024: 58,
        2025: 23,
    }
    live = [asset for asset in status.assets if asset.live_evidence_path]
    assert {(asset.year, asset.sheet) for asset in live} == {
        (2023, "Table_30"),
        (2024, "Table 30"),
        (2025, "Table 30"),
    }


def test_html_is_single_file_safe_and_interactive_without_dependencies() -> None:
    rendered = render_dashboard(build_dashboard(PROJECT)).decode()
    assert rendered.startswith("<!doctype html>")
    assert rendered.count('class="asset-pair"') == 346
    assert rendered.count('class="detail-toggle"') == 346
    assert rendered.count('class="button csv-link"') == 346
    assert rendered.count("Open CSV") == 346
    assert rendered.count('class="coverage-publication publication-group"') == 3
    assert rendered.count('class="assets-publication publication-group"') == 3
    assert rendered.count('class="coverage-row"') == 112
    assert rendered.count('class="coverage-cell coverage-complete"') == 346
    assert rendered.count('class="coverage-meter"') == 6
    assert rendered.count("<strong>346/346</strong>") == 6
    assert "max-height:min(54vh,620px)" in rendered
    assert "position:sticky" in rendered
    assert all(
        value in rendered
        for value in (
            'id="search"',
            'id="publication-filter"',
            'id="cohort-filter"',
            'id="year-filter"',
            'id="checks-filter"',
            'id="stage-filter"',
            'id="coverage-tab"',
            'id="assets-tab"',
            'id="coverage-panel"',
            'id="assets-panel"',
            'id="coverage-search"',
            'class="sort"',
            "Automated checks",
            "Flagged issues",
            "346 sheet-assets across 51 physical workbooks",
            "Registered asset coverage",
            "Recorded Crime — Offenders",
            "2021\u201322",
            "publication-grouped cohort-by-period view",
            "not completeness of the full spreadsheet estate",
            'activateTab("assets", true)',
            "product_prototype_age_replay",
            "product_prototype_country_replay",
            "product_prototype_offence_replay",
            "product_prototype_replay",
            "product_prototype_charge_replay",
        )
    )
    assert all(
        spec.dagster_asset in rendered
        for spec in load_large_batch_registry(PROJECT).entries
    )
    assert "/Users/" not in rendered
    assert "raw prompt" not in rendered.lower()
    assert "https://cdn" not in rendered
    assert "<script src=" not in rendered


def test_coverage_matrix_keeps_multiple_assets_in_one_year_compact() -> None:
    status = build_dashboard(PROJECT)
    cohort = status.cohorts[0]
    original = cohort.assets[0]
    duplicate = replace(
        original,
        asset_id=f"{original.asset_id}:second-sheet",
        sheet=f"{original.sheet} second sheet",
        csv_route="/csv/synthetic-second-sheet.csv",
    )
    expanded_cohort = replace(cohort, assets=(*cohort.assets, duplicate))
    expanded = replace(status, cohorts=(expanded_cohort, *status.cohorts[1:]))
    rendered = render_dashboard(expanded).decode()
    assert rendered.count('class="coverage-row"') == 112
    assert rendered.count("data-target-year=") == 346
    assert (
        rendered.count('class="coverage-cell coverage-complete coverage-multiple"') == 1
    )
    assert "<small>2</small>" in rendered
    assert "2 registered assets" in rendered
    assert "Select to view all 2 assets" in rendered
    assert rendered.count("<strong>347/347</strong>") == 6


def test_coverage_matrix_distinguishes_not_registered_cells() -> None:
    status = build_dashboard(PROJECT)
    cohort = status.cohorts[0]
    reduced_cohort = replace(cohort, assets=cohort.assets[1:])
    reduced = replace(status, cohorts=(reduced_cohort, *status.cohorts[1:]))
    rendered = render_dashboard(reduced).decode()
    assert rendered.count('class="coverage-cell coverage-absent"') == 130
    assert rendered.count('class="coverage-cell coverage-complete"') == 345
    assert "Not registered in this prototype scope" in rendered
    assert rendered.count("<strong>345/345</strong>") == 6


def test_each_asset_csv_route_contains_only_that_assets_rows() -> None:
    status = build_dashboard(PROJECT)
    payloads = build_asset_csv_payloads(PROJECT, status)
    assert len(payloads) == 346
    observed_rows = 0
    for asset in status.assets:
        assert asset.csv_route is not None
        reader = csv.DictReader(
            io.StringIO(payloads[asset.csv_route].decode(), newline="")
        )
        rows = list(reader)
        assert len(rows) == asset.canonical_count
        assert {row["source_workbook_digest"] for row in rows} == {asset.source_digest}
        assert {row["source_sheet"] for row in rows} == {asset.sheet}
        assert {
            row.get("publication_vintage_date") or row["reference_date"] for row in rows
        } == {asset.reference_date}
        observed_rows += len(rows)
    assert observed_rows == 296910


def test_committed_snapshot_matches_current_evidence() -> None:
    matches, output, expected, actual = snapshot_matches(PROJECT)
    assert matches
    assert output == PROJECT / "docs/data-asset-status/index.html"
    assert actual == expected


def _copy_table_30_status_project(destination: Path) -> None:
    fixture_root = destination / "fixtures/product-prototype"
    fixture_root.mkdir(parents=True)
    shutil.copy2(
        PROJECT / "fixtures/product-prototype/prisoners-table-30-2021-2025.json",
        fixture_root / "prisoners-table-30-2021-2025.json",
    )
    shutil.copytree(
        PROJECT / "fixtures/product-prototype/five-year-evidence",
        fixture_root / "five-year-evidence",
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
        "title": "Test status",
        "recordedAt": "2026-08-14T08:00:00+00:00",
        "outputPath": "docs/data-asset-status/index.html",
        "server": {
            "host": "127.0.0.1",
            "port": 3031,
            "tailnetHostname": "test.tailnet.example",
            "tailnetHttpsPort": 3031,
            "dagsterPort": 3030,
        },
        "cohorts": [
            {
                "cohortId": "prisoners-australia-table-30-2021-2025",
                "label": "Table 30 test",
                "cohortPath": (
                    "fixtures/product-prototype/prisoners-table-30-2021-2025.json"
                ),
                "evidenceManifestPath": (
                    "fixtures/product-prototype/five-year-evidence/manifest.json"
                ),
                "dagsterAsset": "product_prototype_replay",
            }
        ],
    }
    registry_path = destination / DEFAULT_REGISTRY
    registry_path.write_text(json.dumps(registry, indent=2) + "\n")


def test_current_custody_failure_does_not_erase_historical_stages(
    tmp_path: Path,
) -> None:
    _copy_table_30_status_project(tmp_path)
    source = (
        tmp_path / "fixtures/product-prototype/workbooks/prisoners-australia-2021.xlsx"
    )
    source.write_bytes(source.read_bytes() + b"changed")
    status = build_dashboard(tmp_path)
    asset = next(item for item in status.assets if item.year == 2021)
    assert asset.stages == {
        "identified": "yes",
        "on_disk": "failed",
        "tidied": "yes",
        "canonicalised": "yes",
        "integrated": "yes",
    }
    assert asset.checks_state == "issues"
    assert any("digest or byte length" in issue for issue in asset.issues)
    assert status.cohorts[0].checks_state == "issues"
    rendered = render_dashboard(status).decode()
    assert rendered.count('class="coverage-cell coverage-issues"') == 1
    assert rendered.count('class="coverage-cell coverage-complete"') == 4


def test_tampered_canonical_csv_is_not_exposed(tmp_path: Path) -> None:
    _copy_table_30_status_project(tmp_path)
    canonical_csv = (
        tmp_path
        / "fixtures/product-prototype/five-year-evidence/canonical-observations.csv"
    )
    canonical_csv.write_bytes(canonical_csv.read_bytes() + b"tampered\n")
    status = build_dashboard(tmp_path)
    assert all(asset.csv_route is None for asset in status.assets)
    assert all(asset.stages["canonicalised"] == "yes" for asset in status.assets)
    assert all(asset.checks_state == "issues" for asset in status.assets)
    assert build_asset_csv_payloads(tmp_path, status) == {}
    rendered = render_dashboard(status).decode()
    assert rendered.count("Select to view the asset; CSV is unavailable.") == 10
    assert rendered.count('class="coverage-cell coverage-issues"') == 5


def test_csv_changed_after_status_verification_is_not_served(tmp_path: Path) -> None:
    _copy_table_30_status_project(tmp_path)
    status = build_dashboard(tmp_path)
    assert all(asset.csv_route for asset in status.assets)
    canonical_csv = (
        tmp_path
        / "fixtures/product-prototype/five-year-evidence/canonical-observations.csv"
    )
    changed = bytearray(canonical_csv.read_bytes())
    index = next(
        offset
        for offset in range(len(changed) - 2, 0, -1)
        if changed[offset] not in {10, 13}
    )
    changed[index] = ord("X") if changed[index] != ord("X") else ord("Y")
    canonical_csv.write_bytes(changed)
    with pytest.raises(DataAssetStatusError, match="digest or length changed"):
        build_asset_csv_payloads(tmp_path, status)


def test_missing_evidence_is_distinct_from_failed_checks(tmp_path: Path) -> None:
    _copy_table_30_status_project(tmp_path)
    (tmp_path / "fixtures/product-prototype/five-year-evidence/manifest.json").unlink()
    status = build_dashboard(tmp_path)
    assert status.cohorts[0].checks_state == "issues"
    assert all(asset.stages["on_disk"] == "yes" for asset in status.assets)
    assert all(asset.stages["tidied"] == "no_evidence" for asset in status.assets)
    assert all(asset.checks_state == "no_evidence" for asset in status.assets)
    rendered = render_dashboard(status).decode()
    assert rendered.count('class="coverage-cell coverage-on-disk"') == 5


def test_legacy_registry_synthesizes_calendar_publication_group(tmp_path: Path) -> None:
    _copy_table_30_status_project(tmp_path)
    status = build_dashboard(tmp_path)
    assert len(status.publications) == 1
    publication = status.publications[0]
    assert publication.publication_id == "prisoners-australia"
    assert publication.period_format == "calendar-year"
    assert len(publication.cohorts) == 1


def test_registry_rejects_unresolved_publication_metadata(tmp_path: Path) -> None:
    _copy_table_30_status_project(tmp_path)
    registry_path = tmp_path / DEFAULT_REGISTRY
    registry = json.loads(registry_path.read_text())
    registry["publications"] = [
        {
            "publicationId": "different-publication",
            "label": "Different publication",
            "periodFormat": "calendar-year",
        }
    ]
    registry_path.write_text(json.dumps(registry))
    with pytest.raises(DataAssetStatusError, match="not configured"):
        build_dashboard(tmp_path)


def test_invalid_registry_shape_fails_instead_of_rendering(tmp_path: Path) -> None:
    registry = tmp_path / DEFAULT_REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schemaVersion": "tidy.data-asset-status-registry/v1",
                "title": "Broken",
                "recordedAt": "2026-08-14T08:00:00+00:00",
                "outputPath": "docs/data-asset-status/index.html",
                "server": {},
                "cohorts": [],
            }
        )
    )
    with pytest.raises(DataAssetStatusError, match="registry"):
        build_dashboard(tmp_path)


def test_server_exposes_only_page_health_and_declared_asset_csvs(
    tmp_path: Path,
) -> None:
    page = tmp_path / "index.html"
    page.write_text("<!doctype html><title>Status</title>")
    csv_body = b"year,value\n2025,42\n"
    server = make_status_server(
        "127.0.0.1", 0, page, {"/csv/example-asset.csv": csv_body}
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            assert response.status == 200
            assert response.read() == page.read_bytes()
            assert response.headers["Cache-Control"] == "no-store"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz") as response:
            assert response.read() == b'{"status":"ok"}\n'
        csv_url = f"http://127.0.0.1:{port}/csv/example-asset.csv"
        with urllib.request.urlopen(csv_url) as response:
            assert response.read() == csv_body
            assert response.headers["Content-Type"] == "text/plain; charset=utf-8"
            assert response.headers["Content-Disposition"] == (
                'inline; filename="example-asset.csv"'
            )
        head = urllib.request.Request(csv_url, method="HEAD")
        with urllib.request.urlopen(head) as response:
            assert response.read() == b""
            assert int(response.headers["Content-Length"]) == len(csv_body)
        with pytest.raises(urllib.error.HTTPError) as undeclared_csv:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/csv/other.csv")
        assert undeclared_csv.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as traversal:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/csv/%2e%2e/index.html")
        assert traversal.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/anything")
        assert missing.value.code == 404
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/", data=b"no", method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as method:
            urllib.request.urlopen(request)
        assert method.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
