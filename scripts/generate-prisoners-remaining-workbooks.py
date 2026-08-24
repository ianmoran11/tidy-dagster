#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "product-prototype" / "workbooks"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", MAIN)
ET.register_namespace("r", DOC)


def trim(source: Path, output: Path, sheets: list[str]) -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "trim-prototype-workbook-formatting.py"),
            str(source),
            str(output),
            *[part for sheet in sheets for part in ("--sheet", sheet)],
        ],
        check=True,
        cwd=ROOT,
    )


def isolate_total_styles(
    source: Path, output: Path, sheet_cells: dict[str, list[str]]
) -> None:
    with zipfile.ZipFile(source) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relationship.get("Id"): relationship.get("Target")
            for relationship in relationships.findall(f"{{{PKG}}}Relationship")
        }
        sheet_targets = {
            sheet.get("name"): (
                PurePosixPath("xl") / PurePosixPath(targets[sheet.get(f"{{{DOC}}}id")])
            ).as_posix()
            for sheet in workbook.find(f"{{{MAIN}}}sheets")
        }
        replacements: dict[str, bytes] = {}
        for sheet_name, addresses in sheet_cells.items():
            target = sheet_targets[sheet_name]
            root = ET.fromstring(archive.read(target))
            cells = {cell.get("r"): cell for cell in root.iter(f"{{{MAIN}}}c")}
            title_style = cells["A3"].get("s")
            if title_style is None:
                raise RuntimeError(f"{sheet_name} A3 has no style")
            for address in addresses:
                cells[address].set("s", title_style)
            replacements[target] = ET.tostring(
                root, encoding="utf-8", xml_declaration=True
            )
        with zipfile.ZipFile(output, "w") as generated:
            for entry in archive.infolist():
                generated.writestr(
                    copy.copy(entry),
                    replacements.get(entry.filename, archive.read(entry.filename)),
                )


def build(destination: Path) -> dict[str, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    outputs = {
        "national": destination
        / "prisoners-australia-2025-national-remaining-bounded.xlsx",
        "federal-2024": destination
        / "prisoners-australia-2024-federal-remaining-bounded.xlsx",
        "federal-2025": destination
        / "prisoners-australia-2025-federal-remaining-bounded.xlsx",
    }
    trim(
        FIX / "prisoners-australia-2025-national-source.xlsx",
        outputs["national"],
        [
            "Table 10=A1:K69",
            "Table 11=A1:R48",
            "Table 12=A1:P69",
            "Table 13=A1:P69",
            "Table 14=A1:F67",
        ],
    )
    isolate_total_styles(
        FIX / "prisoners-australia-2024-federal-source.xlsx",
        outputs["federal-2024"],
        {
            "Table 38": ["A7", "A19", "A31", "A43", "A55", "A67", "A79", "A91", "A103"],
            "Table 39": ["A7", "A18", "A29", "A40", "A51", "A62", "A73"],
        },
    )
    with tempfile.TemporaryDirectory(prefix="prisoners-remaining-") as temporary:
        trimmed = Path(temporary) / "federal-2025-trimmed.xlsx"
        trim(
            FIX / "prisoners-australia-2025-federal-source.xlsx",
            trimmed,
            ["Table 37=A1:B108"],
        )
        isolate_total_styles(
            trimmed,
            outputs["federal-2025"],
            {
                "Table 39": ["A7", "A18", "A29", "A40", "A51", "A62", "A73"],
            },
        )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory(
            prefix="prisoners-remaining-check-"
        ) as temporary:
            generated = build(Path(temporary))
            for path in generated.values():
                expected = FIX / path.name
                if not expected.is_file() or path.read_bytes() != expected.read_bytes():
                    raise SystemExit(f"generated workbook drift: {path.name}")
    else:
        build(FIX)
    print(
        "verified 3 bounded Prisoners workbooks"
        if args.check
        else "generated 3 bounded Prisoners workbooks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
