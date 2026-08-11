import { describe, expect, it } from "vitest";
import {
  assertPromptContractNoLeakage,
  buildCompactContextSnapshot,
  collectRecipeTargetNames,
  MAX_COMPACT_CONTEXT_CHARACTERS,
  MAX_COMPACT_CONTEXT_ROWS,
  parseCompactContext,
} from "../src/context/compactContext.js";
import type { RecipeV01 } from "../src/recipe/types.js";
import type { ParsedSheet } from "../src/workbook/types.js";

function sheet(overrides: Partial<ParsedSheet> = {}): ParsedSheet {
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R2C3",
    rowCount: 2,
    columnCount: 3,
    nonEmptyCellCount: 2,
    cells: [
      {
        sheet: "Sheet 1",
        address: "R1C1",
        row: 1,
        col: 1,
        value: "Header",
        data_type: "string",
        style: { bold: true, fillColor: "FFFF00" },
      },
      {
        sheet: "Sheet 1",
        address: "R2C3",
        row: 2,
        col: 3,
        value: 42,
        data_type: "numeric",
      },
    ],
    merges: [{ parent: "R1C1", range: "R1C1:R1C2" }],
    ...overrides,
  };
}

describe("compact complete semantic context", () => {
  it("serializes deterministically with explicit row-major blanks", () => {
    const first = buildCompactContextSnapshot(sheet());
    const second = buildCompactContextSnapshot(
      sheet({ cells: [...sheet().cells].reverse() }),
    );
    expect(second).toEqual(first);
    const parsed = parseCompactContext(first.serialized);
    expect(parsed).toMatchObject({
      schemaVersion: "cell-role-compact-context-v1",
      sheet: "Sheet 1",
      dimensions: { rows: 2, columns: 3 },
      usedRange: "R1C1:R2C3",
      merges: [{ parent: "R1C1", range: "R1C1:R1C2" }],
      blankBands: { rows: [], columns: [[2, 2]] },
      grid: {
        encoding: "row-major-r1c1-json-v1",
        rows: [
          { range: "R1C1:R1C3", values: ["Header", null, null] },
          { range: "R2C1:R2C3", values: [null, null, 42] },
        ],
      },
    });
    expect(parsed.styleBoundaries).toEqual([
      { row: 1, startColumn: 1, endColumn: 1, style: "b|bgFFFF00" },
    ]);
    expect(first.addressValueEntries).toBe(6);
    expect(first.duplicateAddressValueRepresentations).toBe(0);
    expect(first.characters).toBe(first.serialized.length);
    expect(first.digest).toMatch(/^[a-f0-9]{64}$/);
  });

  it("fails closed on row, character, duplicate, and incomplete-grid violations", () => {
    expect(() =>
      buildCompactContextSnapshot(
        sheet({
          usedRange: null,
          rowCount: MAX_COMPACT_CONTEXT_ROWS + 1,
          columnCount: 1,
          cells: [],
          merges: [],
        }),
      ),
    ).toThrow(/COMPACT_CONTEXT_ROW_LIMIT_EXCEEDED/);
    expect(() =>
      buildCompactContextSnapshot(
        sheet({
          usedRange: "R1C1:R1C1",
          rowCount: 1,
          columnCount: 1,
          cells: [
            {
              sheet: "Sheet 1",
              address: "R1C1",
              row: 1,
              col: 1,
              value: "x".repeat(MAX_COMPACT_CONTEXT_CHARACTERS),
              data_type: "string",
            },
          ],
          merges: [],
        }),
      ),
    ).toThrow(/COMPACT_CONTEXT_TOO_LARGE/);
    expect(() =>
      buildCompactContextSnapshot(
        sheet({ cells: [sheet().cells[0], sheet().cells[0]] }),
      ),
    ).toThrow(/COMPACT_CONTEXT_DUPLICATE_CELL/);
    const incomplete = JSON.parse(
      buildCompactContextSnapshot(sheet()).serialized,
    );
    incomplete.grid.rows[0].values.pop();
    expect(() => parseCompactContext(JSON.stringify(incomplete))).toThrow(
      /COMPACT_CONTEXT_INCOMPLETE_ROW/,
    );
  });

  it("rejects target, expected-output, benchmark, path, and context leakage", () => {
    const context = buildCompactContextSnapshot(sheet()).serialized;
    const base = {
      context,
      baselinePrompt: `baseline\n${context}`,
      semanticsPrompt: `semantics\n${context}`,
      forbiddenPaths: [] as string[],
      targetNames: [] as string[],
      expectedCsvContents: [] as string[],
    };
    expect(() => assertPromptContractNoLeakage(base)).not.toThrow();
    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        baselinePrompt: `${base.baselinePrompt}\nfixtures/target.json`,
        forbiddenPaths: ["fixtures/target.json"],
      }),
    ).toThrow(/LEAKAGE_PATH/);
    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        semanticsPrompt: `${base.semanticsPrompt}\nUse Final Measure`,
        targetNames: ["Final Measure"],
      }),
    ).toThrow(/LEAKAGE_TARGET_NAME/);
    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        baselinePrompt: `${base.baselinePrompt}\nR2C3,42\nR3C3,43`,
        expectedCsvContents: ["address,value\nR2C3,42\nR3C3,43"],
      }),
    ).toThrow(/LEAKAGE_EXPECTED_CSV/);
    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        semanticsPrompt: `${base.semanticsPrompt}\nbenchmark score: 0.95`,
      }),
    ).toThrow(/LEAKAGE_FORBIDDEN_EVIDENCE/);
    expect(() =>
      assertPromptContractNoLeakage({ ...base, baselinePrompt: "missing" }),
    ).toThrow(/CONTEXT_BINDING_MISMATCH/);
  });

  it("collects recipe target names for leakage filtering", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Sheet 1",
      tables: [
        {
          name: "Population Counts",
          values: { name: "value", cells: ["R2C3"] },
          headers: [{ name: "State Name", cells: ["R1C3"], direction: "N" }],
        },
      ],
    };
    expect(collectRecipeTargetNames(recipe)).toEqual([
      "Population Counts",
      "value",
      "State Name",
    ]);
  });
});
