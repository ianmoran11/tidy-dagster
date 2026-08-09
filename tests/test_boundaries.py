from pathlib import Path

from tidy_orchestrator.boundaries import scan_file, scan_roots


def test_python_boundary_scan_covers_production_sources() -> None:
    assert scan_roots((Path("src"), Path("scripts"))) == []


def test_python_boundary_scan_rejects_sibling_import_and_absolute_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "bad.py"
    source.write_text(
        "import tidycell\nfrom pathlib import Path\n"
        "Path('/Users/example/source').read_text()\n"
    )
    failures = scan_file(source)
    assert any("forbidden sibling import" in item for item in failures)
    assert any("absolute workstation path" in item for item in failures)
