#!/usr/bin/env python3
"""Remove exact, digest-bound spreadsheet artifacts before safe format trimming."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", MAIN)
ET.register_namespace("r", DOC_REL)

# Each correction is accepted only for the exact reviewed source bytes and
# exact cell identity, style, scalar value, and absence of a formula. The
# original source workbook remains committed. Replacements additionally bind
# the shared-string cell type and exact old/new displayed values. Geometry-only
# corrections bind exact worksheet XML plus independently reviewed cell,
# formula, merge, and retained-range facts before the trim script may run.
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
    "319a19845565441e74073d62a6dcd9cf46491611e45c0ff9081ab2be94966cf7": {
        "byteLength": 108_775,
        "id": "criminal-courts-act-2021-22-period-header-v1",
        "reason": (
            "Correct the impossible Table 51 terminal period header "
            "2022\N{EN DASH}22 to 2021\N{EN DASH}22; the publication title "
            "and adjacent series establish "
            "the intended period, while preserving the exact source separately."
        ),
        "replacedCells": [
            {
                "sheet": "Table 51",
                "cell": "M5",
                "expectedStyle": "7",
                "expectedType": "s",
                "expectedValue": "2022\N{EN DASH}22",
                "replacementValue": "2021\N{EN DASH}22",
                "insideRetainedRange": True,
            }
        ],
    },
    "f5780d562b078756add08d13afe3a27413c1dd1c9eb9d188d77596f6b6c43a73": {
        "byteLength": 85_082,
        "id": "criminal-courts-fdv-2023-24-duplicate-footnote-v1",
        "reason": (
            "Remove the duplicate far-right Table 16 footnote at XEX59 before "
            "format trimming; preserve the identical retained footnote at A58 "
            "and the exact source workbook separately."
        ),
        "cells": [
            {
                "sheet": "FDV Table 16",
                "cell": "XEX59",
                "expectedStyle": "67",
                "expectedType": "s",
                "expectedValue": (
                    "(f) Includes defendants for whom method of finalisation could "
                    "not be determined, defendants deceased or unfit to plead, "
                    "transfers to non-court agencies and other non-adjudicated "
                    "finalisations n.e.c. "
                ),
                "expectedMerge": "XEX59:XFD59",
                "insideRetainedRange": False,
                "retainedRange": "A1:G63",
                "duplicateOf": {
                    "cell": "A58",
                    "expectedStyle": "67",
                    "expectedType": "s",
                    "expectedValue": (
                        "(f) Includes defendants for whom method of finalisation could "
                        "not be determined, defendants deceased or unfit to plead, "
                        "transfers to non-court agencies and other non-adjudicated "
                        "finalisations n.e.c. "
                    ),
                    "expectedMerge": "A58:G58",
                },
            }
        ],
    },
    "65e4e00dc4062415fb33e6716135b5f18751a1b6589ed01af1943542c5b59815": {
        "byteLength": 413_928,
        "id": "criminal-courts-fdv-offence-2023-24-geometry-v1",
        "reason": (
            "Validate the exact empty far-right Table 8 merge geometry and the "
            "full-width Table 13 title merge before format trimming; preserve "
            "the legitimate Table 8 A2:L2 title merge and exact source workbook."
        ),
        "trimGuards": [
            {
                "sheet": "FDV Table 8",
                "retainedRange": "A1:L256",
                "expectedSheetDigest": (
                    "5829d8d36d84a76eab3d34f24e5a014aa557bd7438962cba0c9704cf8dc20ca7"
                ),
                "expectedDimension": "A1:XFD256",
                "expectedCellCount": 35_552,
                "expectedValuedCellCount": 2_040,
                "expectedFormulaCount": 0,
                "expectedOutOfRangeCellCount": 32_744,
                "expectedOutOfRangeValuedCellCount": 0,
                "expectedMergeCount": 4_697,
                "expectedRetainedMergeCount": 17,
                "expectedRetainedMergeDigest": (
                    "1f48cea330dacb894a04410a6022d24782bbf0e92c402f59861a899412b4a088"
                ),
                "expectedRemovedMergeCount": 4_680,
                "expectedRemovedMergeDigest": (
                    "db11301c90f1ff90c226aaf0daa186375e0926908a3cb70c5939763cde410e26"
                ),
            },
            {
                "sheet": "FDV Table 13",
                "retainedRange": "A1:K261",
                "expectedSheetDigest": (
                    "8d60d3553172e8576f599a34617a2143790afbe8dde8a735e416d38e2a9aaf39"
                ),
                "expectedDimension": "A1:AT261",
                "expectedCellCount": 2_896,
                "expectedValuedCellCount": 2_045,
                "expectedFormulaCount": 0,
                "expectedOutOfRangeCellCount": 35,
                "expectedOutOfRangeValuedCellCount": 0,
                "expectedMergeCount": 24,
                "expectedRetainedMergeCount": 23,
                "expectedRetainedMergeDigest": (
                    "64640f23d331823d0e705280a5dc685d339bae7ed06ea0dd80a9822b5e821e08"
                ),
                "expectedRemovedMergeCount": 1,
                "expectedRemovedMergeDigest": (
                    "a6b604395e7a58579c5654f026de5ed1507c32b78d5a8480ed738c5444e7fd58"
                ),
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


def cell_in_range(address: str, retained_range: str) -> bool:
    def coordinate(value: str) -> tuple[int, int]:
        match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", value)
        if match is None:
            raise ValueError(f"Invalid cell address: {value}")
        column = 0
        for character in match.group(1):
            column = column * 26 + ord(character) - ord("A") + 1
        return int(match.group(2)), column

    start, separator, end = retained_range.partition(":")
    if not separator:
        raise ValueError(f"Invalid retained range: {retained_range}")
    row, column = coordinate(address)
    start_row, start_column = coordinate(start)
    end_row, end_column = coordinate(end)
    return start_row <= row <= end_row and start_column <= column <= end_column


def cell_has_content(cell: ET.Element) -> bool:
    return any(
        descendant.tag.rsplit("}", 1)[-1] == "f"
        or (
            descendant.tag.rsplit("}", 1)[-1] in {"v", "t"}
            and descendant.text not in {None, ""}
        )
        for descendant in cell.iter()
    )


def merge_is_within(merge: str, retained_range: str) -> bool:
    addresses = merge.split(":")
    if len(addresses) not in {1, 2}:
        raise ValueError(f"Invalid merge range: {merge}")
    return all(cell_in_range(address, retained_range) for address in addresses)


def sequence_digest(values: list[str]) -> str:
    payload = "\n".join(sorted(values)) + "\n"
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_trim_guard(
    archive: zipfile.ZipFile,
    targets: dict[str, str],
    declaration_id: str,
    guard: dict[str, object],
) -> dict[str, object]:
    sheet = str(guard["sheet"])
    retained_range = str(guard["retainedRange"])
    target = targets.get(sheet)
    if target is None:
        raise ValueError(f"Workbook is missing {sheet}")
    sheet_bytes = archive.read(target)
    root = ET.fromstring(sheet_bytes)
    dimension = root.find(f"{{{MAIN}}}dimension")
    cells = root.findall(f".//{{{MAIN}}}c")
    valued_cells = [cell for cell in cells if cell_has_content(cell)]
    formulas = root.findall(f".//{{{MAIN}}}f")
    outside_cells = [
        cell for cell in cells if not cell_in_range(str(cell.get("r")), retained_range)
    ]
    outside_valued_cells = [cell for cell in outside_cells if cell_has_content(cell)]
    merges = [
        str(merge.get("ref")) for merge in root.findall(f".//{{{MAIN}}}mergeCell")
    ]
    retained_merges = [
        merge for merge in merges if merge_is_within(merge, retained_range)
    ]
    removed_merges = [
        merge for merge in merges if not merge_is_within(merge, retained_range)
    ]
    actual = {
        "expectedSheetDigest": hashlib.sha256(sheet_bytes).hexdigest(),
        "expectedDimension": dimension.get("ref") if dimension is not None else None,
        "expectedCellCount": len(cells),
        "expectedValuedCellCount": len(valued_cells),
        "expectedFormulaCount": len(formulas),
        "expectedOutOfRangeCellCount": len(outside_cells),
        "expectedOutOfRangeValuedCellCount": len(outside_valued_cells),
        "expectedMergeCount": len(merges),
        "expectedRetainedMergeCount": len(retained_merges),
        "expectedRetainedMergeDigest": sequence_digest(retained_merges),
        "expectedRemovedMergeCount": len(removed_merges),
        "expectedRemovedMergeDigest": sequence_digest(removed_merges),
    }
    if any(actual[key] != guard.get(key) for key in actual):
        raise ValueError(f"{sheet} no longer matches {declaration_id} trim guard")
    return {
        "sheet": sheet,
        "retainedRange": retained_range,
        "removedMergeCount": actual["expectedRemovedMergeCount"],
        "removedMergeDigest": actual["expectedRemovedMergeDigest"],
    }


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
        validated_trim = [
            validate_trim_guard(
                archive,
                targets,
                str(declaration["id"]),
                guard,
            )
            for guard in declaration.get("trimGuards", [])
        ]
        replacements: dict[str, bytes] = {}
        shared_values: list[str] | None = None
        for artifact in declaration.get("cells", []):
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
            expected_type = artifact.get("expectedType")
            if expected_type is None:
                matches_declaration = (
                    formula is None
                    and cell.get("s") == artifact["expectedStyle"]
                    and cell.get("t") is None
                    and value is not None
                    and value.text == artifact["expectedValue"]
                )
            elif expected_type == "s" and artifact.get("duplicateOf") is not None:
                if shared_values is None:
                    shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    shared_values = [
                        "".join(text.text or "" for text in item.iter(f"{{{MAIN}}}t"))
                        for item in shared_root.findall(f"{{{MAIN}}}si")
                    ]
                try:
                    shared_index = int(value.text) if value is not None else -1
                except (TypeError, ValueError):
                    shared_index = -1
                duplicate = artifact["duplicateOf"]
                duplicate_address = str(duplicate["cell"])
                duplicate_matches = [
                    candidate
                    for candidate in root.findall(f".//{{{MAIN}}}c")
                    if candidate.get("r") == duplicate_address
                ]
                duplicate_cell = (
                    duplicate_matches[0] if len(duplicate_matches) == 1 else None
                )
                duplicate_value = (
                    duplicate_cell.find(f"{{{MAIN}}}v")
                    if duplicate_cell is not None
                    else None
                )
                merges = {
                    merge.get("ref")
                    for merge in root.findall(f".//{{{MAIN}}}mergeCell")
                }
                matches_declaration = (
                    formula is None
                    and cell.get("s") == artifact["expectedStyle"]
                    and cell.get("t") == expected_type
                    and 0 <= shared_index < len(shared_values)
                    and shared_values[shared_index] == artifact["expectedValue"]
                    and artifact["expectedMerge"] in merges
                    and artifact["expectedMerge"].split(":", 1)[0] == address
                    and not cell_in_range(address, artifact["retainedRange"])
                    and cell_in_range(duplicate_address, artifact["retainedRange"])
                    and duplicate_cell is not None
                    and duplicate_cell.find(f"{{{MAIN}}}f") is None
                    and duplicate_cell.get("s") == duplicate["expectedStyle"]
                    and duplicate_cell.get("t") == duplicate["expectedType"]
                    and duplicate_value is not None
                    and duplicate_value.text == value.text
                    and shared_values[int(duplicate_value.text)]
                    == duplicate["expectedValue"]
                    and duplicate["expectedMerge"] in merges
                    and duplicate["expectedMerge"].split(":", 1)[0] == duplicate_address
                )
            else:
                matches_declaration = False
            if not matches_declaration:
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

        replaced_cells = declaration.get("replacedCells", [])
        if replaced_cells:
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_values = [
                "".join(text.text or "" for text in item.iter(f"{{{MAIN}}}t"))
                for item in shared_root.findall(f"{{{MAIN}}}si")
            ]
            for artifact in replaced_cells:
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
                try:
                    old_index = int(value.text) if value is not None else -1
                except (TypeError, ValueError):
                    old_index = -1
                if (
                    formula is not None
                    or cell.get("s") != artifact["expectedStyle"]
                    or cell.get("t") != artifact["expectedType"]
                    or old_index < 0
                    or old_index >= len(shared_values)
                    or shared_values[old_index] != artifact["expectedValue"]
                ):
                    raise ValueError(
                        f"{sheet}!{address} no longer matches {declaration['id']}"
                    )
                new_indices = [
                    index
                    for index, displayed in enumerate(shared_values)
                    if displayed == artifact["replacementValue"]
                ]
                if len(new_indices) != 1:
                    raise ValueError(
                        f"Replacement shared string for {sheet}!{address} is not unique"
                    )
                assert value is not None
                value.text = str(new_indices[0])
                replacements[target] = ET.tostring(
                    root, encoding="utf-8", xml_declaration=True
                )

        if validated_trim and not replacements and not replaced_cells:
            output.write_bytes(source_bytes)
        else:
            with zipfile.ZipFile(output, "w") as destination:
                for entry in archive.infolist():
                    destination.writestr(
                        copy.copy(entry),
                        replacements.get(entry.filename, archive.read(entry.filename)),
                    )
    receipt = {"id": declaration["id"], "reason": declaration["reason"]}
    if replaced_cells:
        receipt["replacedCells"] = replaced_cells
    elif validated_trim:
        receipt["validatedTrim"] = validated_trim
    else:
        receipt["removedCells"] = [
            {
                key: artifact[key]
                for key in (
                    "sheet",
                    "cell",
                    "expectedStyle",
                    "expectedValue",
                    "insideRetainedRange",
                )
            }
            for artifact in declaration["cells"]
        ]
    return receipt


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
