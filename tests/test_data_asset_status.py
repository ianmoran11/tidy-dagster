from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tidy_orchestrator.data_asset_status import (
    DEFAULT_REGISTRY,
    DataAssetStatusError,
    build_dashboard,
    make_status_server,
    render_dashboard,
    snapshot_matches,
)

PROJECT = Path(__file__).parents[1]


def test_current_dashboard_reports_ten_clean_sheet_assets() -> None:
    status = build_dashboard(PROJECT)
    assert status.title == "Tidy Data Asset Status"
    assert len(status.cohorts) == 2
    assert len(status.assets) == 10
    assert status.physical_workbook_count == 5
    assert {asset.year for asset in status.assets} == set(range(2021, 2026))
    assert all(
        stage == "yes" for asset in status.assets for stage in asset.stages.values()
    )
    assert all(asset.checks_state == "pass" for asset in status.assets)
    assert all(not asset.issues for asset in status.assets)
    assert sum(asset.canonical_count or 0 for asset in status.assets) == 6480
    table_21 = [asset for asset in status.assets if "Table 21" in asset.cohort_label]
    table_30 = [asset for asset in status.assets if "Table 30" in asset.cohort_label]
    assert [asset.canonical_count for asset in table_21] == [1053] * 5
    assert [asset.canonical_count for asset in table_30] == [243] * 5
    assert sum(asset.excluded_count or 0 for asset in table_21) == 1467
    normalized = [asset for asset in status.assets if asset.normalization]
    assert {(asset.year, asset.sheet) for asset in normalized} == {
        (2025, "Table 21"),
        (2025, "Table 30"),
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
    assert rendered.count('class="asset-pair"') == 10
    assert rendered.count('class="detail-toggle"') == 10
    assert all(
        value in rendered
        for value in (
            'id="search"',
            'id="cohort-filter"',
            'id="year-filter"',
            'id="checks-filter"',
            'id="stage-filter"',
            'class="sort"',
            "Automated checks",
            "Flagged issues",
            "10 sheet-assets across 5 physical workbooks",
            "product_prototype_age_replay",
            "product_prototype_replay",
        )
    )
    assert "/Users/" not in rendered
    assert "raw prompt" not in rendered.lower()
    assert "https://cdn" not in rendered
    assert "<script src=" not in rendered


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


def test_missing_evidence_is_distinct_from_failed_checks(tmp_path: Path) -> None:
    _copy_table_30_status_project(tmp_path)
    (tmp_path / "fixtures/product-prototype/five-year-evidence/manifest.json").unlink()
    status = build_dashboard(tmp_path)
    assert status.cohorts[0].checks_state == "issues"
    assert all(asset.stages["on_disk"] == "yes" for asset in status.assets)
    assert all(asset.stages["tidied"] == "no_evidence" for asset in status.assets)
    assert all(asset.checks_state == "no_evidence" for asset in status.assets)


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


def test_server_exposes_only_page_and_health(tmp_path: Path) -> None:
    page = tmp_path / "index.html"
    page.write_text("<!doctype html><title>Status</title>")
    server = make_status_server("127.0.0.1", 0, page)
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
