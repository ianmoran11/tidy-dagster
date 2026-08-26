#!/usr/bin/env python3
"""Build digest-pinned bounded workbooks for remaining Offenders sheets."""

from __future__ import annotations

import argparse
import copy
import hashlib
import re
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
CELL = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")

SPECS = {
    "recorded-crime-offenders-2022-23-cube-4-source.xlsx": {
        "digest": "1d6e22d911ee5eb24ece4dd07bc7bc5f5d7f6953b39bae273de8ad7e0b8a347f",
        "output": "recorded-crime-offenders-2022-23-cube-4-remaining-bounded.xlsx",
        "ranges": {"Table 28": "A1:M317"},
        "artifacts": {},
    },
    "recorded-crime-offenders-2023-24-cube-2-source.xlsx": {
        "digest": "6374ac85db181a77d903a5c93de0f05de86acb66df89b866553ff3a5543a750d",
        "output": "recorded-crime-offenders-2023-24-cube-2-remaining-bounded.xlsx",
        "ranges": {"Table 6": "A1:Q143", "Table 15": "A1:Q131"},
        "artifacts": {
            "Table 6": {"row": 123, "firstColumn": 18, "lastColumn": 16384, "count": 16367, "style": "125", "valuePrefix": "For Victoria, subdivision 021 may be understated"},
            "Table 15": {"row": 26, "firstColumn": 18, "lastColumn": 16384, "count": 16367, "style": "92", "value": "na"},
        },
    },
    "recorded-crime-offenders-2023-24-cube-3-source.xlsx": {
        "digest": "65495615d51c2eb8291246d7df0f45e7eac14590d7a57f0afb04e71a82021fa0",
        "output": "recorded-crime-offenders-2023-24-cube-3-remaining-bounded.xlsx",
        "ranges": {"Table 21": "A1:K179"},
        "artifacts": {
            "Table 21": {"row": 161, "firstColumn": 12, "lastColumn": 16384, "count": 16373, "style": "55", "valuePrefix": "The minimum age of criminal responsibility increased"},
        },
    },
    "recorded-crime-offenders-2024-25-cube-3-source.xlsx": {
        "digest": "416c3bd67e9535c2ab93e080eadabaf453f7bb599a3dc7c77a420294855cf2b9",
        "output": "recorded-crime-offenders-2024-25-cube-3-remaining-bounded.xlsx",
        "ranges": {"Table 21": "A1:K181"},
        "artifacts": {},
    },
    "recorded-crime-offenders-2023-24-cube-7-source.xlsx": {
        "digest": "cfae55220aff8c11bbba2ab08c6cf97484c54c6ea5579cd693004b8877e08605",
        "output": "recorded-crime-offenders-2023-24-cube-7-remaining-bounded.xlsx",
        "ranges": {"Table 1": "A1:H45"},
        "artifacts": {},
    },
    "recorded-crime-offenders-2024-25-cube-7-source.xlsx": {
        "digest": "1d6a9558d807a8a7d51e834b9e3679d9a076622c8e173f6eba5a6f19bc40edde",
        "output": "recorded-crime-offenders-2024-25-cube-7-remaining-bounded.xlsx",
        "ranges": {"Table 1": "A1:H46"},
        "artifacts": {},
    },
}


def column_number(label: str) -> int:
    value = 0
    for character in label:
        value = value * 26 + ord(character) - 64
    return value


def coordinate(address: str) -> tuple[int, int]:
    match = CELL.fullmatch(address)
    if match is None:
        raise RuntimeError(f"invalid cell address: {address}")
    return int(match.group(2)), column_number(match.group(1))


def limits(reference: str) -> tuple[int, int]:
    _start, end = reference.split(":")
    return coordinate(end)


def targets(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rels = {item.get("Id"): item.get("Target") for item in relationships.findall(f"{{{PKG}}}Relationship")}
    return {
        str(sheet.get("name")): (PurePosixPath("xl") / PurePosixPath(str(rels[sheet.get(f"{{{DOC}}}id")]))).as_posix()
        for sheet in workbook.find(f"{{{MAIN}}}sheets") or []
    }


def shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(text.text or "" for text in item.iter(f"{{{MAIN}}}t")) for item in root.findall(f"{{{MAIN}}}si")]


def cell_value(cell: ET.Element, shared: list[str]) -> str | None:
    value = cell.find(f"{{{MAIN}}}v")
    if value is None or value.text is None:
        return None
    return shared[int(value.text)] if cell.get("t") == "s" else value.text


def has_content(cell: ET.Element) -> bool:
    return cell.find(f"{{{MAIN}}}f") is not None or cell_value(cell, []) is not None if cell.get("t") != "s" else cell.find(f"{{{MAIN}}}v") is not None


def trim_sheet(data: bytes, reference: str, artifact: dict[str, object] | None, shared: list[str]) -> bytes:
    max_row, max_column = limits(reference)
    root = ET.fromstring(data)
    dimension = root.find(f"{{{MAIN}}}dimension")
    if dimension is not None:
        dimension.set("ref", reference)
    sheet_data = root.find(f"{{{MAIN}}}sheetData")
    if sheet_data is None:
        raise RuntimeError("worksheet has no sheetData")
    removed: list[ET.Element] = []
    for row in list(sheet_data):
        row_number = int(row.get("r", "0"))
        if row_number > max_row:
            valued = [cell for cell in row if has_content(cell)]
            if valued:
                raise RuntimeError(f"valued cell below {reference}")
            sheet_data.remove(row)
            continue
        row.attrib.pop("spans", None)
        for cell in list(row):
            address = cell.get("r")
            if address is None or coordinate(address)[1] > max_column:
                if has_content(cell):
                    removed.append(cell)
                row.remove(cell)
    if artifact is None:
        if removed:
            raise RuntimeError(f"unreviewed valued cells right of {reference}")
    else:
        cells = sorted(removed, key=lambda cell: coordinate(str(cell.get("r")))[1])
        columns = [coordinate(str(cell.get("r")))[1] for cell in cells]
        if (
            len(cells) != artifact["count"]
            or columns != list(range(int(artifact["firstColumn"]), int(artifact["lastColumn"]) + 1))
            or any(coordinate(str(cell.get("r")))[0] != artifact["row"] for cell in cells)
            or any(cell.get("s") != artifact["style"] for cell in cells)
            or any(cell.find(f"{{{MAIN}}}f") is not None for cell in cells)
        ):
            raise RuntimeError("digest-pinned artifact coordinates/styles changed")
        values = [cell_value(cell, shared) for cell in cells]
        if "value" in artifact and any(value != artifact["value"] for value in values):
            raise RuntimeError("digest-pinned artifact value changed")
        if "valuePrefix" in artifact and any(not isinstance(value, str) or not value.startswith(str(artifact["valuePrefix"])) for value in values):
            raise RuntimeError("digest-pinned artifact text changed")
    columns_node = root.find(f"{{{MAIN}}}cols")
    if columns_node is not None:
        for column in list(columns_node):
            minimum, maximum = int(column.get("min", "0")), int(column.get("max", "0"))
            if minimum > max_column:
                columns_node.remove(column)
            elif maximum > max_column:
                column.set("max", str(max_column))
        if not list(columns_node):
            root.remove(columns_node)
    merges = root.find(f"{{{MAIN}}}mergeCells")
    if merges is not None:
        for merge in list(merges):
            if any(coordinate(address)[0] > max_row or coordinate(address)[1] > max_column for address in str(merge.get("ref")).split(":")):
                merges.remove(merge)
        if list(merges):
            merges.set("count", str(len(list(merges))))
        else:
            root.remove(merges)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build(destination: Path) -> dict[str, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for source_name, spec in SPECS.items():
        source = FIX / source_name
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != spec["digest"]:
            raise RuntimeError(f"source digest changed: {source_name}")
        output = destination / str(spec["output"])
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(output, "w") as generated:
            sheet_targets = targets(archive)
            shared = shared_strings(archive)
            replacements = {
                sheet_targets[sheet]: trim_sheet(
                    archive.read(sheet_targets[sheet]),
                    reference,
                    spec["artifacts"].get(sheet),
                    shared,
                )
                for sheet, reference in spec["ranges"].items()
            }
            for entry in archive.infolist():
                generated.writestr(copy.copy(entry), replacements.get(entry.filename, archive.read(entry.filename)))
        outputs[source_name] = output
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="offenders-remaining-workbooks-") as temporary:
            outputs = build(Path(temporary))
            for path in outputs.values():
                expected = FIX / path.name
                if not expected.is_file() or path.read_bytes() != expected.read_bytes():
                    raise SystemExit(f"generated workbook drift: {path.name}")
    else:
        build(FIX)
    print(("verified" if args.check else "generated") + f" {len(SPECS)} bounded Offenders workbooks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
