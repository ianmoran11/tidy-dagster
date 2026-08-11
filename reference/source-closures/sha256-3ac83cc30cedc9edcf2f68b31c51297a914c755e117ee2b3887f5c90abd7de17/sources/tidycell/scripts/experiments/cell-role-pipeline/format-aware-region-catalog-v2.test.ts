// @vitest-environment node

import { describe, expect, it } from "vitest";
import type { ParsedSheet } from "../../../src/lib/workbook/types";
import {
  buildCompactContextSnapshot,
  parseCompactContext,
} from "./compact-context";
import {
  buildFormatAwareSemanticRegionCatalog,
  buildSemanticCellFormattingFacts,
  compileFormatAwareSemanticTableMap,
  formatSignatureForPrompt,
  renderFormatAwareSemanticRegionCatalog,
} from "./format-aware-region-catalog-v2";

function formattedSheet(femaleIndent = 1): ParsedSheet {
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R4C3",
    rowCount: 4,
    columnCount: 3,
    nonEmptyCellCount: 10,
    merges: [],
    cells: [
      cell("R1C1", 1, 1, "People", { bold: true }),
      cell("R2C1", 2, 1, "Male", { italic: true, fontIndent: 1 }),
      cell("R2C2", 2, 2, 10),
      cell("R2C3", 2, 3, 11),
      cell("R3C1", 3, 1, "Female", {
        italic: true,
        fontIndent: femaleIndent,
      }),
      cell("R3C2", 3, 2, 12),
      cell("R3C3", 3, 3, 13),
      cell("R4C1", 4, 1, "Total", { bold: true }),
      cell("R4C2", 4, 2, 22),
      cell("R4C3", 4, 3, 24),
    ],
  };
}

function cell(
  address: string,
  row: number,
  col: number,
  value: string | number,
  style?: ParsedSheet["cells"][number]["style"],
): ParsedSheet["cells"][number] {
  return {
    sheet: "Sheet 1",
    address,
    row,
    col,
    value,
    data_type: typeof value === "number" ? "numeric" : "string",
    ...(style ? { style } : {}),
  };
}

function setup(femaleIndent = 1) {
  const sheet = formattedSheet(femaleIndent);
  const snapshot = buildCompactContextSnapshot(sheet);
  const context = parseCompactContext(snapshot.serialized);
  const catalog = buildFormatAwareSemanticRegionCatalog(context, {
    formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
  });
  return { snapshot, context, catalog };
}

describe("format-aware semantic region catalog v2", () => {
  it("groups contiguous header members that share italic and indentation formatting", () => {
    const { catalog } = setup();
    const candidate = catalog.candidates.find(
      (entry) => entry.range === "R2C1:R3C1",
    );

    expect(candidate).toMatchObject({
      kinds: expect.arrayContaining(["format-block", "format-column"]),
      formatSignatures: ["i|in1"],
      formatting: ["italic,indent=1"],
      nonblankCount: 2,
      valueLikeCount: 0,
    });
    expect(renderFormatAwareSemanticRegionCatalog(catalog)).toContain(
      "formatting=italic,indent=1",
    );
  });

  it("keeps otherwise similar headers separate when indentation differs", () => {
    const { catalog } = setup(2);

    expect(
      catalog.candidates.some((entry) => entry.range === "R2C1:R3C1"),
    ).toBe(false);
    expect(
      catalog.candidates.some(
        (entry) =>
          entry.range === "R2C1:R2C1" &&
          entry.formatSignatures.includes("i|in1"),
      ),
    ).toBe(true);
    expect(
      catalog.candidates.some(
        (entry) =>
          entry.range === "R3C1:R3C1" &&
          entry.formatSignatures.includes("i|in2"),
      ),
    ).toBe(true);
  });

  it("does not globally join unrelated cells solely because both are bold", () => {
    const { catalog } = setup();

    expect(
      catalog.candidates.some(
        (entry) =>
          entry.kinds.some((kind) => kind.startsWith("format-")) &&
          entry.range === "R1C1:R4C1",
      ),
    ).toBe(false);
  });

  it("keeps the existing semantic-map schema and deterministic compiler", () => {
    const { context, catalog } = setup();
    const values = catalog.candidates.find(
      (entry) => entry.range === "R2C2:R4C3",
    );
    const memberBand = catalog.candidates.find(
      (entry) => entry.range === "R2C1:R3C1",
    );
    const totalMember = catalog.candidates.find(
      (entry) => entry.range === "R4C1:R4C1",
    );
    expect(values).toBeDefined();
    expect(memberBand).toBeDefined();
    expect(totalMember).toBeDefined();

    const result = compileFormatAwareSemanticTableMap({
      map: {
        version: "semantic-table-map-v1",
        table: {
          name: "People",
          values: { name: "Count", regions: [values!.id] },
          dimensions: [
            {
              name: "Category",
              memberRegions: [memberBand!.id, totalMember!.id],
              direction: "W",
            },
          ],
        },
      },
      catalog,
      context,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.recipe.tables).toHaveLength(1);
    expect(result.recipe.tables[0].headers[0]).toMatchObject({
      name: "Category",
      direction: "W",
    });
  });

  it("renders all captured formatting properties in plain language", () => {
    expect(
      formatSignatureForPrompt(
        "b|i|u|s12|fcFF000000|bgFFFFFFFF|in2|hleft|vmiddle|bb",
      ),
    ).toBe(
      "bold,italic,underline,font-size=12,font-color=FF000000,fill-color=FFFFFFFF,indent=2,horizontal=left,vertical=middle,border-bottom",
    );
  });
});
