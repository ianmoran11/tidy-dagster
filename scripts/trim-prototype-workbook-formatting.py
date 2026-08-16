#!/usr/bin/env python3
"""Trim pathological out-of-range worksheet formatting without removing values."""

from __future__ import annotations

import argparse
import copy
import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", MAIN)
ET.register_namespace("r", DOC_REL)

CELL = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
RANGE = re.compile(r"^([A-Z]+[1-9][0-9]*):([A-Z]+[1-9][0-9]*)$")


def column_number(label: str) -> int:
    value = 0
    for character in label:
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def parse_cell(address: str) -> tuple[int, int]:
    match = CELL.fullmatch(address)
    if match is None:
        raise ValueError(f"Invalid cell address: {address}")
    return int(match.group(2)), column_number(match.group(1))


def parse_range(value: str) -> tuple[int, int]:
    match = RANGE.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid worksheet range: {value}")
    start_row, start_column = parse_cell(match.group(1))
    end_row, end_column = parse_cell(match.group(2))
    if (start_row, start_column) != (1, 1):
        raise ValueError("Trim ranges must start at A1")
    return end_row, end_column


def merge_is_within(value: str, max_row: int, max_column: int) -> bool:
    addresses = value.split(":")
    return all(
        (row <= max_row and column <= max_column)
        for row, column in (parse_cell(address) for address in addresses)
    )


def cell_has_content(cell: ET.Element) -> bool:
    for descendant in cell.iter():
        local_name = descendant.tag.rsplit("}", 1)[-1]
        if local_name == "f":
            return True
        if local_name in {"v", "t"} and descendant.text not in {None, ""}:
            return True
    return False


def trim_sheet(data: bytes, declared_range: str) -> bytes:
    max_row, max_column = parse_range(declared_range)
    root = ET.fromstring(data)
    dimension = root.find(f"{{{MAIN}}}dimension")
    if dimension is not None:
        dimension.set("ref", declared_range)

    sheet_data = root.find(f"{{{MAIN}}}sheetData")
    if sheet_data is None:
        raise ValueError("Worksheet has no sheetData")
    for row in list(sheet_data):
        row_number = int(row.get("r", "0"))
        if row_number > max_row:
            if any(cell_has_content(cell) for cell in row):
                raise ValueError(
                    f"Refusing to remove a valued cell below {declared_range}"
                )
            sheet_data.remove(row)
            continue
        row.attrib.pop("spans", None)
        for cell in list(row):
            address = cell.get("r")
            if address is None or parse_cell(address)[1] > max_column:
                if cell_has_content(cell):
                    raise ValueError(
                        f"Refusing to remove a valued cell right of {declared_range}"
                    )
                row.remove(cell)

    columns = root.find(f"{{{MAIN}}}cols")
    if columns is not None:
        for column in list(columns):
            minimum = int(column.get("min", "0"))
            maximum = int(column.get("max", "0"))
            if minimum > max_column:
                columns.remove(column)
            elif maximum > max_column:
                column.set("max", str(max_column))
        if not list(columns):
            root.remove(columns)

    merges = root.find(f"{{{MAIN}}}mergeCells")
    if merges is not None:
        for merge in list(merges):
            if not merge_is_within(merge.get("ref", ""), max_row, max_column):
                merges.remove(merge)
        if list(merges):
            merges.set("count", str(len(list(merges))))
        else:
            root.remove(merges)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def sheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relationship.get("Id"): relationship.get("Target")
        for relationship in relationships.findall(f"{{{PKG_REL}}}Relationship")
    }
    resolved: dict[str, str] = {}
    sheets = workbook.find(f"{{{MAIN}}}sheets")
    if sheets is None:
        return resolved
    for sheet in sheets:
        name = sheet.get("name")
        relationship_id = sheet.get(f"{{{DOC_REL}}}id")
        target = targets.get(relationship_id)
        if name is None or target is None:
            continue
        normalized = PurePosixPath("xl") / PurePosixPath(target)
        resolved[name] = normalized.as_posix()
    return resolved


def trim_workbook(source: Path, output: Path, ranges: dict[str, str]) -> None:
    if source.resolve() == output.resolve():
        raise ValueError("Output must differ from input")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "r") as archive:
        targets = sheet_targets(archive)
        missing = sorted(set(ranges) - set(targets))
        if missing:
            raise ValueError(f"Workbook is missing sheets: {missing}")
        replacements = {
            targets[name]: trim_sheet(archive.read(targets[name]), declared_range)
            for name, declared_range in ranges.items()
        }
        with zipfile.ZipFile(output, "w") as destination:
            for entry in archive.infolist():
                info = copy.copy(entry)
                destination.writestr(
                    info,
                    replacements.get(entry.filename, archive.read(entry.filename)),
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--sheet",
        action="append",
        default=[],
        metavar="NAME=A1:REF",
        help="Worksheet name and retained logical range; repeat as needed.",
    )
    arguments = parser.parse_args()
    ranges: dict[str, str] = {}
    for item in arguments.sheet:
        name, separator, declared_range = item.partition("=")
        if not separator or not name or name in ranges:
            raise ValueError(f"Invalid or duplicate --sheet value: {item}")
        parse_range(declared_range)
        ranges[name] = declared_range
    if not ranges:
        raise ValueError("At least one --sheet value is required")
    trim_workbook(arguments.input, arguments.output, ranges)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
