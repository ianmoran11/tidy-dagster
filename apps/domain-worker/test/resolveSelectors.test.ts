/* Source-derived from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb (MIT). */
import { describe, expect, it } from "vitest";
import {
  resolveRecipeSelectors,
  resolveSelector,
} from "../src/recipe/resolveSelectors.js";
import type { RecipeV01 } from "../src/recipe/types.js";
import { hashString, stableJson } from "../src/recipe/styleFingerprint.js";
import type { ParsedSheet, TidyCell } from "../src/workbook/types.js";

const sheet = makeSheet([
  cell("R1C1", 1, 1, "Title", "string"),
  cell("R1C2", 1, 2, "Q1", "string"),
  cell("R1C4", 1, 4, "Q2", "string"),
  cell("R2C1", 2, 1, "North", "string"),
  cell("R2C2", 2, 2, 10, "numeric"),
  cell("R2C3", 2, 3, 11, "numeric"),
  cell("R2C4", 2, 4, null, "blank"),
  cell("R3C1", 3, 1, "South", "string"),
  cell("R3C2", 3, 2, 20, "numeric"),
  cell("R3C3", 3, 3, "n/a", "string"),
  cell("R3C4", 3, 4, 22, "numeric", { formula: "B3+2" }),
  cell("R4C1", 4, 1, "Comment", "string", { comment: "Important" }),
]);

describe("resolveSelector", () => {
  it("resolves explicit cell arrays", () => {
    const result = resolveSelector(["R1C1", "R1C2"], sheet);

    expect(result.addresses).toEqual(["R1C1", "R1C2"]);
    expect(result.warnings).toEqual([]);
  });

  it("resolves rectangular ranges", () => {
    const result = resolveSelector({ range: "R1C1:R2C2" }, sheet);

    expect(result.addresses).toEqual(["R1C1", "R1C2", "R2C1", "R2C2"]);
  });

  it("filters by data_type", () => {
    const result = resolveSelector(
      { range: "R2C2:R3C4", where: { data_type: ["numeric"] } },
      sheet,
    );

    expect(result.addresses).toEqual(["R2C2", "R2C3", "R3C2", "R3C4"]);
  });

  it("filters by non_blank", () => {
    const result = resolveSelector(
      { range: "R2C2:R2C4", where: { non_blank: true } },
      sheet,
    );

    expect(result.addresses).toEqual(["R2C2", "R2C3"]);
  });

  it("de-duplicates and sorts addresses", () => {
    const result = resolveSelector(
      { cells: ["R3C2", "R2C2", "R2C2"], range: "R2C3:R2C3" },
      sheet,
    );

    expect(result.addresses).toEqual(["R2C2", "R2C3", "R3C2"]);
  });

  it("warns about out-of-used-range cells", () => {
    const result = resolveSelector(["R1C1", "R8C8"], sheet, "manual");

    expect(result.addresses).toEqual(["R1C1", "R8C8"]);
    expect(result.warnings).toContainEqual(
      expect.objectContaining({
        code: "OUT_OF_USED_RANGE",
        selector: "manual",
        address: "R8C8",
      }),
    );
  });

  it("warns about empty selections", () => {
    const result = resolveSelector(
      { range: "R1C1:R1C1", where: { data_type: ["numeric"] } },
      sheet,
      "numeric-title",
    );

    expect(result.addresses).toEqual([]);
    expect(result.warnings.map((warning) => warning.code)).toEqual([
      "PREDICATE_FILTERED_ALL",
      "EMPTY_SELECTION",
    ]);
  });

  it("supports formula and comment predicates", () => {
    expect(
      resolveSelector(
        { range: "R3C2:R3C4", where: { has_formula: true } },
        sheet,
      ).addresses,
    ).toEqual(["R3C4"]);
    expect(
      resolveSelector(
        { range: "R4C1:R4C1", where: { has_comment: true } },
        sheet,
      ).addresses,
    ).toEqual(["R4C1"]);
  });

  it("supports style_id predicates", () => {
    const styleSheet = makeSheet([
      cell("R1C1", 1, 1, "Styled", "string", { style: { bold: true } }),
      cell("R1C2", 1, 2, "Unstyled", "string"),
      cell("R1C3", 1, 3, "Styled Differently", "string", {
        style: { italic: true },
      }),
    ]);

    const boldStyleId = `s_${hashString(stableJson({ bold: true }))}`;
    const italicStyleId = `s_${hashString(stableJson({ italic: true }))}`;

    const boldResult = resolveSelector(
      { range: "R1C1:R1C3", where: { style_id: [boldStyleId] } },
      styleSheet,
    );
    expect(boldResult.addresses).toEqual(["R1C1"]);

    const italicResult = resolveSelector(
      { range: "R1C1:R1C3", where: { style_id: [italicStyleId] } },
      styleSheet,
    );
    expect(italicResult.addresses).toEqual(["R1C3"]);

    const noneResult = resolveSelector(
      { range: "R1C1:R1C3", where: { style_id: ["s_nonexistent"] } },
      styleSheet,
    );
    expect(noneResult.addresses).toEqual([]);
  });

  it("resolves raw string range selectors", () => {
    const result = resolveSelector("R1C1:R2C2", sheet);
    expect(result.addresses).toEqual(["R1C1", "R1C2", "R2C1", "R2C2"]);
  });

  it("resolves raw single cell string selectors", () => {
    const result = resolveSelector("R1C1", sheet);
    expect(result.addresses).toEqual(["R1C1"]);
  });
});

describe("resolveRecipeSelectors", () => {
  it("resolves multi-table recipes without mixing selectors", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Fixture",
      tables: [
        {
          name: "first",
          values: {
            name: "value",
            cells: { range: "R2C2:R2C4", where: { data_type: ["numeric"] } },
          },
          headers: [{ name: "region", direction: "W", cells: ["R2C1"] }],
        },
        {
          name: "second",
          values: {
            name: "value",
            cells: { range: "R3C2:R3C4", where: { data_type: ["numeric"] } },
          },
          headers: [{ name: "region", direction: "W", cells: ["R3C1"] }],
        },
      ],
    };

    const result = resolveRecipeSelectors(recipe, sheet);

    expect(result.tables[0].values.addresses).toEqual(["R2C2", "R2C3"]);
    expect(result.tables[0].headers[0].result.addresses).toEqual(["R2C1"]);
    expect(result.tables[1].values.addresses).toEqual(["R3C2", "R3C4"]);
    expect(result.tables[1].headers[0].result.addresses).toEqual(["R3C1"]);
    expect(result.warnings).toEqual([]);
  });
});

function makeSheet(cells: TidyCell[]): ParsedSheet {
  return {
    name: "Fixture",
    usedRange: "R1C1:R4C4",
    rowCount: 4,
    columnCount: 4,
    nonEmptyCellCount: cells.filter(
      (candidate) => candidate.data_type !== "blank",
    ).length,
    cells,
    merges: [],
  };
}

function cell(
  address: string,
  row: number,
  col: number,
  value: TidyCell["value"],
  dataType: TidyCell["data_type"],
  extra: Partial<TidyCell> = {},
): TidyCell {
  return {
    sheet: "Fixture",
    address,
    row,
    col,
    value,
    data_type: dataType,
    ...extra,
  };
}
