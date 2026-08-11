// @vitest-environment node

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { parseRecipe } from "../../../src/lib/recipe/schema";
import { findRecipeSheet } from "../../../src/lib/workbook/findRecipeSheet";
import type { ParsedSheet } from "../../../src/lib/workbook/types";
import { parseWorkbook } from "../../../src/lib/workbook/parseWorkbook";
import {
  assertPromptContractNoLeakage,
  buildCompactContextSnapshot,
  collectRecipeTargetNames,
  MAX_COMPACT_CONTEXT_CHARACTERS,
  MAX_COMPACT_CONTEXT_ROWS,
  parseCompactContext,
} from "./compact-context";
import { buildContextComparisonReport } from "./context-comparison";
import { parseExperimentPlan } from "./plan";
import {
  buildCompactBaselinePrompt,
  buildSemanticsPrompt,
  SEMANTICS_PROMPT_VERSION,
} from "./prompts";

const repoRoot = process.cwd();

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
  it("serializes deterministically in row-major order with explicit blanks and minimal structure", () => {
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
    expect(first.serialized).not.toMatch(
      /"(?:cells|contextCells|header_list|candidateBlocks|candidateRegions|styleFingerprints)"/,
    );
  });

  it("fails closed on row, cell, character, duplicate, and incomplete-grid violations", () => {
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
    const snapshot = buildCompactContextSnapshot(sheet());
    const incomplete = JSON.parse(snapshot.serialized);
    incomplete.grid.rows[0].values.pop();
    expect(() => parseCompactContext(JSON.stringify(incomplete))).toThrow(
      /COMPACT_CONTEXT_INCOMPLETE_ROW/,
    );
  });

  it("builds both arms over one byte-identical digest-bound evidence section without Stage 1 leakage", () => {
    const context = buildCompactContextSnapshot(sheet());
    const baseline = buildCompactBaselinePrompt(context);
    const semantics = buildSemanticsPrompt(context);
    expect(baseline.split(context.serialized)).toHaveLength(2);
    expect(semantics.split(context.serialized)).toHaveLength(2);
    expect(baseline).toContain(`context digest: ${context.digest}`);
    expect(semantics).toContain(`context digest: ${context.digest}`);
    expect(semantics).toContain(SEMANTICS_PROMPT_VERSION);
    expect(semantics).toContain("hierarchy levels");
    expect(semantics).toContain("typed Uncertainty");
    expect(semantics).not.toContain('"direction":"N"');
    expect(semantics).not.toContain('"version":"0.1"');
    expect(semantics).not.toContain("physicalExtent=");
    expect(semantics).not.toContain("selectorBounds");
  });

  it("rejects class-level path, target, expected-output, and benchmark leakage outside shared evidence", () => {
    const context = buildCompactContextSnapshot(sheet());
    const baseline = buildCompactBaselinePrompt(context);
    const semantics = buildSemanticsPrompt(context);
    const expectedCsv = "address,value\r\nR2C3,42\r\nR3C3,43\r\nR4C3,44";
    const base = {
      context: context.serialized,
      baselinePrompt: baseline,
      semanticsPrompt: semantics,
      forbiddenPaths: [] as string[],
      targetNames: [] as string[],
      expectedCsvContents: [] as string[],
    };
    expect(() => assertPromptContractNoLeakage(base)).not.toThrow();

    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        baselinePrompt: `${baseline}\nfixtures/recipes/target.recipe.json`,
        forbiddenPaths: ["fixtures/recipes/target.recipe.json"],
      }),
    ).toThrow(/LEAKAGE_PATH/);

    for (const [leaked, targetName] of [
      ["Use Final Measure", "Final Measure"],
      ['The required output name is "Final Measure"', "Final Measure"],
      ["Emit indigenous_status", "indigenous_status"],
      ["Emit Indigenous Status", "indigenous_status"],
      ["Use value", "value"],
    ] as const) {
      expect(() =>
        assertPromptContractNoLeakage({
          ...base,
          semanticsPrompt: `${semantics}\n${leaked}`,
          targetNames: [targetName],
        }),
      ).toThrow(/LEAKAGE_TARGET_NAME/);
    }

    for (const leaked of [
      expectedCsv,
      "Expected row: R2C3,42",
      "R3C3,43",
      "R2C3,42\nR3C3,43",
      "R3C3,43   R4C3,44",
    ]) {
      expect(() =>
        assertPromptContractNoLeakage({
          ...base,
          baselinePrompt: `${baseline}\n${leaked}`,
          expectedCsvContents: [expectedCsv],
        }),
      ).toThrow(/LEAKAGE_EXPECTED_CSV/);
    }

    for (const leaked of [
      "semantic-gold/review.json",
      "benchmark score: 0.95",
      "graph score = 0.8",
      "exact CSV match 95%",
      "F1 = 0.84",
      "accuracy: 88%",
      "precision 0.7",
      "recall=0.6",
      "similarity: 0.5",
      "match rate 75%",
      "benchmark_score=0.95",
      "exact_csv_match:1",
    ]) {
      expect(() =>
        assertPromptContractNoLeakage({
          ...base,
          semanticsPrompt: `${semantics}\n${leaked}`,
        }),
      ).toThrow(/LEAKAGE_FORBIDDEN_EVIDENCE/);
    }

    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        baselinePrompt: "missing shared context",
      }),
    ).toThrow(/CONTEXT_BINDING_MISMATCH/);
    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        baselinePrompt: `${baseline}\n${context.serialized}`,
      }),
    ).toThrow(/CONTEXT_BINDING_MISMATCH/);

    const workbookOnly =
      '{"evidence":"Final Measure R2C3,42 benchmark score: 0.95"}';
    expect(() =>
      assertPromptContractNoLeakage({
        context: workbookOnly,
        baselinePrompt: `baseline instructions\n${workbookOnly}`,
        semanticsPrompt: `semantic instructions\n${workbookOnly}`,
        forbiddenPaths: [],
        targetNames: ["Final Measure"],
        expectedCsvContents: [expectedCsv],
      }),
    ).not.toThrow();
    expect(() =>
      assertPromptContractNoLeakage({
        ...base,
        targetNames: ["value", "state", "unit", "statistic", "variables"],
      }),
    ).not.toThrow();
  });

  it("covers every coordinate and decisive late evidence for all eight smoke assets", async () => {
    const historical = parseExperimentPlan(
      JSON.parse(
        await readFile(
          path.join(
            repoRoot,
            "operations/cell-role-pipeline-luna-smoke-v2.plan.json",
          ),
          "utf8",
        ),
      ),
    );
    expect(historical.units).toHaveLength(8);
    for (const unit of historical.units) {
      const parsedWorkbook = await parseWorkbook(
        await readFile(path.join(repoRoot, unit.assetSnapshot.xlsx)),
      );
      if (!parsedWorkbook.ok) throw new Error(unit.asset);
      const parsedSheet = findRecipeSheet(parsedWorkbook.workbook, unit.sheet);
      if (!parsedSheet) throw new Error(unit.asset);
      const snapshot = buildCompactContextSnapshot(parsedSheet);
      const context = parseCompactContext(snapshot.serialized);
      expect(context.grid.rows, unit.asset).toHaveLength(parsedSheet.rowCount);
      expect(
        context.grid.rows.every(
          (row) => row.values.length === parsedSheet.columnCount,
        ),
        unit.asset,
      ).toBe(true);
      expect(snapshot.addressValueEntries, unit.asset).toBe(
        parsedSheet.rowCount * parsedSheet.columnCount,
      );
      for (const cell of parsedSheet.cells) {
        expect(
          context.grid.rows[cell.row - 1].values[cell.col - 1],
          `${unit.asset}:${cell.address}`,
        ).toEqual(cell.value);
      }
      const lateCell = [...parsedSheet.cells]
        .filter((cell) => cell.value !== null)
        .sort((left, right) => right.row - left.row || right.col - left.col)[0];
      expect(lateCell, unit.asset).toBeDefined();
      expect(
        context.grid.rows[lateCell.row - 1].values[lateCell.col - 1],
        `${unit.asset}:decisive-late:${lateCell.address}`,
      ).toEqual(lateCell.value);
      expect(snapshot, unit.asset).toEqual(
        buildCompactContextSnapshot(parsedSheet),
      );
      const baselinePrompt = buildCompactBaselinePrompt(snapshot);
      const semanticsPrompt = buildSemanticsPrompt(snapshot);
      const promptBytes = `${baselinePrompt}\n${semanticsPrompt}`;
      const approvedRecipe = parseRecipe(
        JSON.parse(
          await readFile(
            path.join(repoRoot, unit.assetSnapshot.recipe),
            "utf8",
          ),
        ),
      );
      const expectedPaths = [
        unit.assetSnapshot.expected_csv,
        ...Object.values(unit.assetSnapshot.expected_csvs ?? {}),
      ].filter((value): value is string => Boolean(value));
      const expectedCsvContents = await Promise.all(
        expectedPaths.map((expectedPath) =>
          readFile(path.join(repoRoot, expectedPath), "utf8"),
        ),
      );
      expect(() =>
        assertPromptContractNoLeakage({
          context: snapshot.serialized,
          baselinePrompt,
          semanticsPrompt,
          forbiddenPaths: [
            unit.assetSnapshot.recipe,
            ...expectedPaths,
            unit.assetSnapshot.expected_overlay ?? "",
            unit.assetSnapshot.metadata ?? "",
          ],
          targetNames: collectRecipeTargetNames(approvedRecipe),
          expectedCsvContents,
        }),
      ).not.toThrow();
      for (const forbidden of [
        "semantic-gold-v1",
        "pending_human_review",
        "candidateBlocks",
        "candidateRegions",
        "header_list",
        "contextCells",
        "styleFingerprints",
        "indigenous_status",
        "legal_status",
        "summary_label",
        "fraud_method",
        "drug_use_context",
        "treatment_type",
        "corrections_population",
        "sentence_type",
        "defendant_dimensions",
      ]) {
        expect(promptBytes, `${unit.asset}:${forbidden}`).not.toContain(
          forbidden,
        );
      }
      expect(snapshot.characters, unit.asset).toBeLessThan(
        JSON.stringify("summary" in unit ? unit.summary : {}).length,
      );
      expect(buildSemanticsPrompt(snapshot).length, unit.asset).toBeLessThan(
        unit.semanticsPrompt.length,
      );
    }
  }, 60_000);

  it("reports provider-free v1/v2/compact size and duplicate-address comparisons", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const report = await buildContextComparisonReport(repoRoot);
    expect(report.providerFree).toBe(true);
    expect(report.assets).toHaveLength(8);
    expect(report.totals.compactToV2CharacterRatio).toBeLessThan(0.5);
    expect(report.totals.compact.characters).toBeLessThan(
      report.totals.v2.characters,
    );
    expect(report.totals.compact.duplicateAddressValueRepresentations).toBe(0);
    expect(report.totals.compact.duplicatedAddressOccurrences).toBeLessThan(
      report.totals.v2.duplicatedAddressOccurrences,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
    expect(
      report.assets.every(
        (asset) =>
          asset.compactToV2CharacterRatio < 0.5 &&
          asset.compact.duplicatedAddressOccurrences <
            asset.v2.duplicatedAddressOccurrences,
      ),
    ).toBe(true);
  }, 60_000);
});
