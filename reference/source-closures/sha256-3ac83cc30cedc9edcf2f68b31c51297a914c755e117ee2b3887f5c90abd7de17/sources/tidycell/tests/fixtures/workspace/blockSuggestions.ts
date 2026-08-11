import type { RecipeV01 } from "../../../src/lib/recipe/types";
import type {
  ParsedSheet,
  ParsedWorkbook,
  TidyCell,
} from "../../../src/lib/workbook/types";

export const BLOCK_SUGGESTION_SHEET = "Striped blocks";
export const BLOCK_SUGGESTION_VALUE_RANGE = "R7C2:R37C19";
export const BLOCK_SUGGESTION_LABEL_RANGE = "R7C1:R37C1";
export const STRUCTURE_SUGGESTION_SHEET = "Year observations";
export const STRUCTURE_SUGGESTION_YEAR_RANGE = "R1C2:R1C4";
export const STRUCTURE_SUGGESTION_VALUE_RANGE = "R2C2:R4C4";
export const RECORDED_SUGGESTION_SHEET = "Recorded year blocks";
export const RECORDED_SUGGESTION_YEAR_RANGES = [
  "R8C1:R18C1",
  "R20C1:R30C1",
  "R32C1:R42C1",
] as const;
export const RECORDED_SUGGESTION_FALSE_YEAR_RANGE = "R44C1:R45C1";
export const FACTOR_VARIANT_YEAR_RANGES = ["R1C1:R3C1", "R5C1:R7C1"] as const;

export function createBlockSuggestionRecipe(): RecipeV01 {
  return {
    version: "0.1",
    sheet: BLOCK_SUGGESTION_SHEET,
    tables: [
      {
        name: "striped_values",
        values: { name: "value", cells: { range: "R7C2:R7C2" } },
        headers: [
          {
            name: "row_label",
            direction: "W",
            cells: { range: BLOCK_SUGGESTION_LABEL_RANGE },
          },
        ],
      },
    ],
  };
}

export function createBlockSuggestionSheet(): ParsedSheet {
  const cells: TidyCell[] = [];
  for (let row = 7; row <= 37; row += 1) {
    const fillColor = row % 2 === 0 ? "D9EAF7" : "EEF5FB";
    cells.push(
      fixtureCell(row, 1, `Region ${row - 6}`, "string", {
        bold: true,
        fillColor,
      }),
    );
    for (let col = 2; col <= 19; col += 1) {
      cells.push(
        fixtureCell(row, col, 10_000 + row * 100 + col, "numeric", {
          fillColor,
        }),
      );
    }
  }
  return {
    name: BLOCK_SUGGESTION_SHEET,
    usedRange: "R7C1:R37C19",
    rowCount: 37,
    columnCount: 19,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

export function createBlockSuggestionWorkbook(): ParsedWorkbook {
  return { sheets: [createBlockSuggestionSheet()] };
}

export function createStructureAwareSuggestionSheet(): ParsedSheet {
  const cells = [
    fixtureCell(1, 1, "Region", "string", { bold: true }),
    fixtureCell(1, 2, 2017, "numeric", { bold: true }),
    fixtureCell(1, 3, 2018, "numeric", { bold: true }),
    fixtureCell(1, 4, 2019, "numeric", { bold: true }),
    fixtureCell(2, 1, "North", "string", {}),
    fixtureCell(3, 1, "South", "string", {}),
    fixtureCell(4, 1, "West", "string", {}),
    ...[2, 3, 4].flatMap((row) =>
      [2, 3, 4].map((col) =>
        fixtureCell(row, col, row * 100 + col, "numeric", {}),
      ),
    ),
  ];
  return {
    name: STRUCTURE_SUGGESTION_SHEET,
    usedRange: "R1C1:R4C4",
    rowCount: 4,
    columnCount: 4,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

export function createRecordedSuggestionSheet(): ParsedSheet {
  const cells: TidyCell[] = [
    fixtureCell(7, 1, "Year", "string", { bold: true }),
    fixtureCell(7, 2, "Count", "string", { bold: true }),
    fixtureCell(7, 3, "Percentage", "string", { bold: true }),
  ];
  for (const [blockIndex, range] of RECORDED_SUGGESTION_YEAR_RANGES.entries()) {
    const startRow = Number(range.match(/^R(\d+)C/)?.[1]);
    for (let offset = 0; offset < 11; offset += 1) {
      const row = startRow + offset;
      cells.push(
        fixtureCell(
          row,
          1,
          2010 + offset,
          "numeric",
          blockIndex === 1 ? { bold: true } : {},
        ),
      );
      cells.push(
        fixtureCell(row, 2, 100 + blockIndex * 20 + offset, "numeric", {}),
      );
      cells.push(
        fixtureCell(
          row,
          3,
          (blockIndex + 1) / 10 + offset / 100,
          "numeric",
          {},
        ),
      );
    }
  }
  cells.push(fixtureCell(44, 1, 1970, "numeric", {}));
  cells.push(fixtureCell(45, 1, 1888, "numeric", {}));
  cells.push(fixtureCell(44, 2, 42, "numeric", {}));
  cells.push(fixtureCell(45, 2, 43, "numeric", {}));
  return {
    name: RECORDED_SUGGESTION_SHEET,
    usedRange: "R7C1:R45C3",
    rowCount: 45,
    columnCount: 3,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

export function createFactorVariantYearSuggestionSheet(): ParsedSheet {
  const cells: TidyCell[] = [];
  for (const [startRow, adjacentBody] of [
    [1, false],
    [5, true],
  ] as const) {
    for (let offset = 0; offset < 3; offset += 1) {
      const row = startRow + offset;
      cells.push(fixtureCell(row, 1, 2020 - offset * 5, "numeric", {}));
      if (adjacentBody) {
        cells.push(fixtureCell(row, 2, 100 + offset, "numeric", {}));
      }
    }
  }
  return {
    name: "Factor-varied year blocks",
    usedRange: "R1C1:R7C2",
    rowCount: 7,
    columnCount: 2,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

function fixtureCell(
  row: number,
  col: number,
  value: TidyCell["value"],
  dataType: TidyCell["data_type"],
  style: NonNullable<TidyCell["style"]>,
): TidyCell {
  return {
    sheet: BLOCK_SUGGESTION_SHEET,
    address: `R${row}C${col}`,
    row,
    col,
    value,
    data_type: dataType,
    formula: null,
    formatted: value === null ? null : String(value),
    comment: null,
    hyperlink: null,
    style,
    merge: null,
  };
}
