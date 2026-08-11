/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import { describe, expect, it } from "vitest";
import type { CompactSemanticContext } from "../src/context/compactContext.js";
import {
  buildSemanticRegionCatalog,
  compileSemanticTableMap,
  formatCorrectionDiagnostics,
  isCorrectionEligible,
  type SemanticRegionCatalog,
  type SemanticTableMapV1,
} from "../src/catalog/semantic-map-v1.js";

function context(
  rows: Array<Array<string | number | boolean | null>>,
): CompactSemanticContext {
  const columns = Math.max(...rows.map((row) => row.length));
  const padded = rows.map((row) => [
    ...row,
    ...Array.from({ length: columns - row.length }, () => null),
  ]);
  return {
    schemaVersion: "cell-role-compact-context-v1",
    sheet: "Sheet 1",
    dimensions: { rows: padded.length, columns },
    usedRange: `R1C1:R${padded.length}C${columns}`,
    merges: [],
    blankBands: { rows: [], columns: [] },
    styleBoundaries: [],
    grid: {
      encoding: "row-major-r1c1-json-v1",
      rows: padded.map((values, index) => ({
        range: `R${index + 1}C1:R${index + 1}C${columns}`,
        values,
      })),
    },
  };
}

function catalog(entries: Array<[string, string]>): SemanticRegionCatalog {
  return {
    version: "semantic-region-catalog-v1",
    sheet: "Sheet 1",
    omittedCandidateCount: 0,
    candidates: entries.map(([id, range]) => ({
      id,
      range,
      kinds: ["test"],
      nonblankCount: 1,
      valueLikeCount: 1,
      sample: [],
    })),
  };
}

function map(
  values: string[],
  dimensions: SemanticTableMapV1["table"]["dimensions"],
): SemanticTableMapV1 {
  return {
    version: "semantic-table-map-v1",
    table: {
      name: "observations",
      values: { name: "value", regions: values },
      dimensions,
    },
  };
}

describe("semantic table map v1", () => {
  it("builds structural candidates without assigning semantic roles", () => {
    const result = buildSemanticRegionCatalog(
      context([
        [null, "2023", "2024"],
        ["A", 1, 2],
        ["B", 3, 4],
      ]),
    );

    expect(result.candidates.some((entry) => entry.range === "R2C2:R3C3")).toBe(
      true,
    );
    expect(result.candidates.some((entry) => entry.range === "R1C2:R1C3")).toBe(
      true,
    );
    expect(result.candidates.some((entry) => entry.range === "R2C1:R3C1")).toBe(
      true,
    );
  });

  it("compiles semantic choices deterministically and strips caption hints", () => {
    const sheet = context([
      [null, "2023", "2024"],
      ["A", 1, 2],
      ["B", 3, 4],
    ]);
    const regions = catalog([
      ["values", "R2C2:R3C3"],
      ["years", "R1C2:R1C3"],
      ["categories", "R2C1:R3C1"],
    ]);
    const result = compileSemanticTableMap({
      context: sheet,
      catalog: regions,
      map: map(
        ["values"],
        [
          {
            name: "year",
            memberRegions: ["years"],
            direction: "N",
            captionHints: ["reasoning-only-and-not-a-real-region"],
          },
          {
            name: "category",
            memberRegions: ["categories"],
            direction: "W",
          },
        ],
      ),
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(
      result.recipe.tables[0].headers.map((header) => header.direction),
    ).toEqual(["N", "W"]);
    expect(result.captionHints).toEqual([
      {
        dimension: "year",
        hints: ["reasoning-only-and-not-a-real-region"],
      },
    ]);
    expect(result.canonicalXml).not.toContain("reasoning-only");
    expect(JSON.stringify(result.recipe)).not.toContain("caption");
  });

  it("expands several selected regions to one exact RecipeV01 address union", () => {
    const sheet = context([
      [null, "2023", "2024"],
      ["A", 1, 2],
      [null, null, null],
      ["B", 3, 4],
    ]);
    const result = compileSemanticTableMap({
      context: sheet,
      catalog: catalog([
        ["values-1", "R2C2:R2C3"],
        ["values-2", "R4C2:R4C3"],
        ["years", "R1C2:R1C3"],
        ["categories-1", "R2C1:R2C1"],
        ["categories-2", "R4C1:R4C1"],
      ]),
      map: map(
        ["values-1", "values-2"],
        [
          { name: "year", memberRegions: ["years"], direction: "N" },
          {
            name: "category",
            memberRegions: ["categories-1", "categories-2"],
            direction: "W",
          },
        ],
      ),
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.recipe.tables[0].values.cells).toEqual({
      cells: ["R2C2", "R2C3", "R4C2", "R4C3"],
    });
    expect(result.normalizations.values).toMatchObject({
      selectedCellCount: 4,
      representation: "addresses",
    });
  });

  it("returns factual geometry diagnostics without changing the LLM direction", () => {
    const sheet = context([
      ["Period", "2023", "2024"],
      ["A", 1, 2],
      ["B", 3, 4],
    ]);
    const result = compileSemanticTableMap({
      context: sheet,
      catalog: catalog([
        ["values", "R2C2:R3C3"],
        ["caption", "R1C1:R1C1"],
      ]),
      map: map(
        ["values"],
        [
          {
            name: "period",
            memberRegions: ["caption"],
            direction: "W",
          },
        ],
      ),
    });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.code).toBe("UNATTACHED_HEADER");
    expect(isCorrectionEligible(result)).toBe(true);
    expect(formatCorrectionDiagnostics(result)).toContain(
      "chosenRelationship=direct-row",
    );
  });

  it("rejects role overlap rather than silently repairing semantics", () => {
    const sheet = context([
      [null, "2023", "2024"],
      ["A", 1, 2],
    ]);
    const result = compileSemanticTableMap({
      context: sheet,
      catalog: catalog([
        ["values", "R2C2:R2C3"],
        ["overlap", "R2C2:R2C2"],
      ]),
      map: map(
        ["values"],
        [{ name: "wrong header", memberRegions: ["overlap"], direction: "N" }],
      ),
    });

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("ROLE_CELL_OVERLAP");
  });
});
