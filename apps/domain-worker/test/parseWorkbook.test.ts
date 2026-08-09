/* Source-derived from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb (MIT). */
import ExcelJS from "exceljs";
import { describe, expect, it } from "vitest";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";
import type { ParsedSheet, TidyCell } from "../src/workbook/types.js";

describe("parseWorkbook", () => {
  it("parses workbook sheets and tidy cell metadata", async () => {
    const buffer = await buildFixtureWorkbook();
    const result = await parseWorkbook(buffer);

    expect(result.ok).toBe(true);

    if (!result.ok) {
      throw new Error("Expected workbook parsing to succeed.");
    }

    expect(result.workbook.sheets.map((sheet) => sheet.name)).toEqual([
      "Data",
      "Notes",
    ]);

    const data = getSheet(result.workbook.sheets, "Data");
    expect(data.usedRange).toBe("R1C1:R6C8");
    expect(data.rowCount).toBeGreaterThanOrEqual(6);
    expect(data.columnCount).toBeGreaterThanOrEqual(8);
    expect(data.merges).toEqual([{ parent: "R5C1", range: "R5C1:R5C2" }]);

    expect(getCell(data, "R1C1")).toMatchObject({
      value: "Population estimates",
      data_type: "string",
      style: {
        bold: true,
        fillColor: "FFCCE5FF",
      },
    });
    expect(getCell(data, "R3C2")).toMatchObject({
      value: 123,
      data_type: "numeric",
    });
    expect(getCell(data, "R3C3")).toMatchObject({
      value: true,
      data_type: "boolean",
    });
    expect(getCell(data, "R3C4")).toMatchObject({ data_type: "date" });
    expect(getCell(data, "R3C5")).toMatchObject({
      value: 246,
      data_type: "numeric",
      formula: "B3*2",
    });
    expect(getCell(data, "R3C6")).toMatchObject({
      value: null,
      data_type: "blank",
      comment: "Styled blank separator",
      style: { fillColor: "FFFFF2CC" },
    });
    expect(getCell(data, "R3C7")).toMatchObject({
      value: "#DIV/0!",
      data_type: "error",
    });
    expect(getCell(data, "R5C1")).toMatchObject({
      value: "Merged note",
      merge: { parent: "R5C1", range: "R5C1:R5C2", role: "parent" },
    });
    expect(getCell(data, "R5C2")).toMatchObject({
      value: null,
      data_type: "blank",
      merge: { parent: "R5C1", range: "R5C1:R5C2", role: "child" },
    });
    expect(getCell(data, "R6C1")).toMatchObject({
      value: "Source",
      hyperlink: "https://example.test/source",
    });

    const notes = getSheet(result.workbook.sheets, "Notes");
    expect(getCell(notes, "R1C1")).toMatchObject({
      value: "Second sheet",
      data_type: "string",
    });
  });

  it("returns structured errors for invalid workbook bytes", async () => {
    const result = await parseWorkbook(new Uint8Array([1, 2, 3, 4]));

    expect(result.ok).toBe(false);

    if (result.ok) {
      throw new Error("Expected invalid workbook parsing to fail.");
    }

    expect(result.errors[0]).toMatchObject({
      code: "INVALID_WORKBOOK",
      message: expect.any(String),
    });
  });
});

async function buildFixtureWorkbook(): Promise<Uint8Array> {
  const workbook = new ExcelJS.Workbook();
  const data = workbook.addWorksheet("Data");

  data.getCell("A1").value = "Population estimates";
  data.getCell("A1").font = { bold: true };
  data.getCell("A1").fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: "FFCCE5FF" },
  };

  data.getRow(2).values = [
    "",
    "State",
    "Count",
    "Active",
    "Date",
    "Double",
    "Spacer",
    "Error",
  ];
  data.getCell("A3").value = "NSW";
  data.getCell("B3").value = 123;
  data.getCell("C3").value = true;
  data.getCell("D3").value = new Date(Date.UTC(2024, 0, 1));
  data.getCell("E3").value = { formula: "B3*2", result: 246 };
  data.getCell("F3").value = null;
  data.getCell("F3").note = "Styled blank separator";
  data.getCell("F3").fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: "FFFFF2CC" },
  };
  data.getCell("G3").value = { error: "#DIV/0!" };

  data.mergeCells("A5:B5");
  data.getCell("A5").value = "Merged note";
  data.getCell("A6").value = {
    text: "Source",
    hyperlink: "https://example.test/source",
  };

  const notes = workbook.addWorksheet("Notes");
  notes.getCell("A1").value = "Second sheet";

  const buffer = await workbook.xlsx.writeBuffer();
  return buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
}

function getSheet(sheets: ParsedSheet[], name: string): ParsedSheet {
  const sheet = sheets.find((candidate) => candidate.name === name);

  if (!sheet) {
    throw new Error(`Expected sheet ${name} to exist.`);
  }

  return sheet;
}

function getCell(sheet: ParsedSheet, address: string): TidyCell {
  const cell = sheet.cells.find((candidate) => candidate.address === address);

  if (!cell) {
    throw new Error(`Expected cell ${address} to exist.`);
  }

  return cell;
}
