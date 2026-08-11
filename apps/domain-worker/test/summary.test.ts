/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  buildSheetSummary,
  buildWorkbookSummaries,
} from "../src/summary/buildSheetSummary.js";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";

const fixtureRoot = path.join(process.cwd(), "fixtures", "workbooks");

describe("buildSheetSummary", () => {
  it("summarizes fixture sheet dimensions, cells, styles, context, and regions", async () => {
    const sheet = await parseFixtureSheet("simple-crosstab", "Population");
    const summary = buildSheetSummary(sheet, {
      checked: true,
      intent: "Extract population counts.",
    });

    expect(summary).toMatchObject({
      sheet: "Population",
      checked: true,
      usedRange: "R1C1:R6C4",
      intent: "Extract population counts.",
      dataTypes: {
        numeric: 4,
        string: 6,
      },
    });
    expect(
      summary.cells.some(
        (cell) => cell.address === "R3C3" && cell.value === 123,
      ),
    ).toBe(true);
    expect(Object.keys(summary.styleFingerprints).length).toBeGreaterThan(0);
    expect(summary.contextCells.map((cell) => cell.address)).toEqual(
      expect.arrayContaining(["R1C1", "R6C1"]),
    );
    expect(summary.header_list).toEqual(
      expect.arrayContaining([
        { value: "Population counts", addresses: "R1C1" },
        { value: "NSW", addresses: "R3C2" },
      ]),
    );
    expect(summary.table_context_format).toBe("markdown_compact");
    expect(summary.table_markdown).toContain(
      "[R1C1|s:14] **Population counts**",
    );
    expect(summary.table_markdown).toContain("[R3C3] 123");
    expect(summary.html_table).toBe("");
    expect(summary.candidateRegions).toEqual([
      {
        range: "R3C3:R4C4",
        rowCount: 2,
        columnCount: 2,
        numericCellCount: 4,
      },
    ]);
    expect(summary.candidateBlocks?.length).toBeGreaterThan(0);
    expect(summary.candidateBlocks?.length).toBeLessThanOrEqual(16);
    expect(summary.candidateBlockEvidence).toMatchObject({
      detector_version: "tidybank-candidate-blocks-v1",
      role_hypotheses_are_authoritative: false,
    });
  });

  it("includes merge ranges and blank bands", async () => {
    const parsed = await parseWorkbook(
      readFileSync(path.join(fixtureRoot, "multi-table.xlsx")),
    );

    expect(parsed.ok).toBe(true);

    if (!parsed.ok) {
      throw new Error("Expected fixture parse to succeed.");
    }

    const sheet = parsed.workbook.sheets[0];
    const summary = buildSheetSummary(sheet);

    expect(summary.blankRows).toEqual(
      expect.arrayContaining([{ start: 2, end: 2 }]),
    );
    expect(summary.blankColumns.length).toBeGreaterThanOrEqual(0);
    expect(summary.merges).toEqual([]);
  });

  it("caps summary size while preserving candidate-region cells", async () => {
    const sheet = await parseFixtureSheet("sparse-headers", "Revenue");
    const uncapped = buildSheetSummary(sheet, { maxChars: 100_000 });
    const capped = buildSheetSummary(sheet, { maxChars: 1_400 });

    expect(uncapped.sizeChars).toBeGreaterThan(capped.sizeChars);
    expect(capped.truncated).toBe(true);
    expect(capped.cells.some((cell) => cell.address === "R3C2")).toBe(true);
    expect(capped.table_markdown.length).toBeGreaterThan(0);
  });

  it("builds browser prompt header lists and compact Markdown context", async () => {
    const sheet = await parseFixtureSheet("multi-table", "Mixed");
    const summary = buildSheetSummary(sheet, { maxChars: 100_000 });
    const stateCandidate = summary.header_list.find(
      (candidate) => candidate.value === "State",
    );

    expect(stateCandidate?.addresses).toBe("R3C2");
    expect(summary.table_markdown).toContain("| [R1C1]");
    expect(summary.table_markdown).toContain("[R3C3]");
    expect(summary.table_markdown).toContain("|---|");
    expect(summary.html_table).toBe("");
  });

  it("builds expanded HTML context when requested", async () => {
    const sheet = await parseFixtureSheet("multi-table", "Mixed");
    const summary = buildSheetSummary(sheet, {
      maxChars: 100_000,
      tableContextMode: "html_expanded",
    });

    expect(summary.table_context_format).toBe("html_expanded");
    expect(summary.html_table).toContain('<table data-sheet="Mixed">');
    expect(summary.html_table).toContain('data-r1c1="R3C3"');
    expect(summary.html_table).toContain('title="R3C3"');
    expect(summary.html_table).toContain("<td");
  });

  it("summarizes sparse far-apart numeric cells without expanding the full range", () => {
    const summary = buildSheetSummary(
      {
        name: "Sparse",
        usedRange: "R1C1:R100000C10000",
        rowCount: 100_000,
        columnCount: 10_000,
        nonEmptyCellCount: 3,
        merges: [],
        cells: [
          {
            sheet: "Sparse",
            address: "R1C1",
            row: 1,
            col: 1,
            value: "Title",
            data_type: "string",
          },
          {
            sheet: "Sparse",
            address: "R3C3",
            row: 3,
            col: 3,
            value: 1,
            data_type: "numeric",
          },
          {
            sheet: "Sparse",
            address: "R100000C10000",
            row: 100_000,
            col: 10_000,
            value: 2,
            data_type: "numeric",
          },
        ],
      },
      { maxChars: 1_000_000, tableContextMode: "html_expanded" },
    );

    expect(summary.candidateRegions[0]).toMatchObject({
      range: "R3C3:R100000C10000",
      numericCellCount: 2,
    });
    expect(summary.cells.map((cell) => cell.address)).toEqual(
      expect.arrayContaining(["R3C3", "R100000C10000"]),
    );
    expect(summary.table_markdown).toContain("Table context truncated");
    expect(summary.html_table).toContain("Table context truncated");
  });

  it("optionally derives bounded candidate regions from numeric strings", () => {
    const cells = [
      { address: "R1C2", row: 1, col: 2, value: "2" },
      { address: "R1C3", row: 1, col: 3, value: "3" },
      { address: "R8C2", row: 8, col: 2, value: "10" },
      { address: "R8C3", row: 8, col: 3, value: "20" },
      { address: "R9C2", row: 9, col: 2, value: "30" },
      { address: "R9C3", row: 9, col: 3, value: "40" },
    ].map((cell) => ({
      ...cell,
      sheet: "StringNumbers",
      data_type: "string" as const,
    }));
    const sheet = {
      name: "StringNumbers",
      usedRange: "R1C1:R9C3",
      rowCount: 9,
      columnCount: 3,
      nonEmptyCellCount: cells.length,
      merges: [],
      cells,
    };

    expect(buildSheetSummary(sheet).candidateRegions).toEqual([]);
    const withHints = buildSheetSummary(sheet, {
      includeNumericStringCandidateRegions: true,
    });

    expect(withHints.candidateRegions).toEqual([]);
    expect(withHints.dataRangeHintRegions).toEqual([
      {
        range: "R8C2:R9C3",
        rowCount: 2,
        columnCount: 2,
        numericCellCount: 4,
      },
    ]);
  });

  it("retains numeric-string hint regions on mixed-type sheets", () => {
    const summary = buildSheetSummary(
      {
        name: "MixedNumbers",
        usedRange: "R3C2:R9C5",
        rowCount: 9,
        columnCount: 5,
        nonEmptyCellCount: 5,
        merges: [],
        cells: [
          {
            sheet: "MixedNumbers",
            address: "R3C5",
            row: 3,
            col: 5,
            value: 99,
            data_type: "numeric",
          },
          ...[
            ["R8C2", 8, 2, "10"],
            ["R8C3", 8, 3, "20"],
            ["R9C2", 9, 2, "30"],
            ["R9C3", 9, 3, "40"],
          ].map(([address, row, col, value]) => ({
            sheet: "MixedNumbers",
            address: String(address),
            row: Number(row),
            col: Number(col),
            value: String(value),
            data_type: "string" as const,
          })),
        ],
      },
      { includeNumericStringCandidateRegions: true },
    );

    expect(summary.candidateRegions).toEqual([
      expect.objectContaining({ range: "R3C5:R3C5", numericCellCount: 1 }),
    ]);
    expect(summary.dataRangeHintRegions).toEqual([
      expect.objectContaining({ range: "R8C2:R9C3", numericCellCount: 4 }),
    ]);
  });

  it("builds one bounded summary per checked sheet", async () => {
    const parsed = await parseWorkbook(
      readFileSync(path.join(fixtureRoot, "multi-table.xlsx")),
    );

    expect(parsed.ok).toBe(true);

    if (!parsed.ok) {
      throw new Error("Expected fixture parse to succeed.");
    }

    const summaries = buildWorkbookSummaries(
      parsed.workbook.sheets,
      ["Mixed"],
      {
        maxChars: 2_000,
      },
    );

    expect(summaries).toHaveLength(1);
    expect(summaries[0]).toMatchObject({ sheet: "Mixed", checked: true });
    expect(summaries[0].sizeChars).toBeLessThanOrEqual(2_000);
  });
});

async function parseFixtureSheet(workbookName: string, sheetName: string) {
  const parsed = await parseWorkbook(
    readFileSync(path.join(fixtureRoot, `${workbookName}.xlsx`)),
  );

  expect(parsed.ok).toBe(true);

  if (!parsed.ok) {
    throw new Error("Expected fixture parse to succeed.");
  }

  const sheet = parsed.workbook.sheets.find(
    (candidate) => candidate.name === sheetName,
  );

  if (!sheet) {
    throw new Error(`Missing sheet ${sheetName}.`);
  }

  return sheet;
}
