#!/usr/bin/env python3
"""Remove exact, digest-bound spreadsheet artifacts before safe format trimming."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", MAIN)
ET.register_namespace("r", DOC_REL)

# Each removal is outside the publication's semantic data region and is
# accepted only for the exact reviewed source bytes, style, scalar value, and
# absence of a formula. The original source workbook remains committed.
CORRECTIONS = {
    "8dc16d0c7ac726e0eb8fc87a707f7616408f8be0cb009508afd6c737b1db692a": {
        "byteLength": 111_807,
        "id": "recorded-crime-offenders-2023-24-artifacts-v1",
        "reason": (
            "Remove a zero-valued cell outside the Table 5 semantic data region; "
            "preserve the exact source separately."
        ),
        "cells": [
            {
                "sheet": "Table 5",
                "cell": "AG1",
                "expectedStyle": "12",
                "expectedValue": "0",
                "insideRetainedRange": True,
            }
        ],
    },
    "80e2d07fe1d0106688537e8c4873dd736922da84608629d4295aa3f012cb8ea2": {
        "byteLength": 115_924,
        "id": "recorded-crime-offenders-2024-25-artifacts-v1",
        "reason": (
            "Remove isolated values outside the Tables 4 and 5 semantic data "
            "regions; preserve the exact source separately."
        ),
        "cells": [
            {
                "sheet": "Table 4",
                "cell": "XFC50",
                "expectedStyle": "77",
                "expectedValue": "3",
                "insideRetainedRange": False,
            },
            {
                "sheet": "Table 5",
                "cell": "AI1",
                "expectedStyle": "12",
                "expectedValue": "0",
                "insideRetainedRange": True,
            },
        ],
    },
}


def sheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {
        relationship.get("Id"): relationship.get("Target")
        for relationship in relationships.findall(f"{{{PKG_REL}}}Relationship")
    }
    sheets = workbook.find(f"{{{MAIN}}}sheets")
    if sheets is None:
        raise ValueError("Workbook has no sheets")
    result: dict[str, str] = {}
    for sheet in sheets:
        name = sheet.get("name")
        relationship_id = sheet.get(f"{{{DOC_REL}}}id")
        target = targets.get(relationship_id)
        if name is not None and target is not None:
            result[name] = (PurePosixPath("xl") / PurePosixPath(target)).as_posix()
    return result


def correct(source: Path, output: Path) -> dict[str, object]:
    source_bytes = source.read_bytes()
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    declaration = CORRECTIONS.get(source_digest)
    if declaration is None or len(source_bytes) != declaration["byteLength"]:
        raise ValueError("Input is not an exact reviewed correction source")
    if source.resolve() == output.resolve():
        raise ValueError("Output must differ from input")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "r") as archive:
        targets = sheet_targets(archive)
        replacements: dict[str, bytes] = {}
        for artifact in declaration["cells"]:
            sheet = str(artifact["sheet"])
            address = str(artifact["cell"])
            target = targets.get(sheet)
            if target is None:
                raise ValueError(f"Workbook is missing {sheet}")
            root = ET.fromstring(replacements.get(target, archive.read(target)))
            matches = [
                cell
                for cell in root.findall(f".//{{{MAIN}}}c")
                if cell.get("r") == address
            ]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one {sheet}!{address} cell")
            cell = matches[0]
            formula = cell.find(f"{{{MAIN}}}f")
            value = cell.find(f"{{{MAIN}}}v")
            if (
                formula is not None
                or cell.get("s") != artifact["expectedStyle"]
                or cell.get("t") is not None
                or value is None
                or value.text != artifact["expectedValue"]
            ):
                raise ValueError(
                    f"{sheet}!{address} no longer matches {declaration['id']}"
                )
            row = next(
                (
                    candidate
                    for candidate in root.findall(f".//{{{MAIN}}}row")
                    if cell in list(candidate)
                ),
                None,
            )
            if row is None:
                raise ValueError(
                    f"Could not locate the parent row for {sheet}!{address}"
                )
            row.remove(cell)
            replacements[target] = ET.tostring(
                root, encoding="utf-8", xml_declaration=True
            )
        with zipfile.ZipFile(output, "w") as destination:
            for entry in archive.infolist():
                destination.writestr(
                    copy.copy(entry),
                    replacements.get(entry.filename, archive.read(entry.filename)),
                )
    return {
        "id": declaration["id"],
        "removedCells": declaration["cells"],
        "reason": declaration["reason"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--receipt", type=Path)
    arguments = parser.parse_args()
    receipt = correct(arguments.input, arguments.output)
    if arguments.receipt is not None:
        arguments.receipt.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
