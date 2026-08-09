/* Source-derived from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb (MIT). */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { executeRecipe } from "../src/executor/executeRecipe.js";
import { rowsToCsv } from "../src/export/formatters.js";
import { parseRecipe } from "../src/recipe/schema.js";
import type { RecipeV01 } from "../src/recipe/types.js";
import { findRecipeSheet } from "../src/workbook/findRecipeSheet.js";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";
import type { ParsedSheet, TidyCell } from "../src/workbook/types.js";

const fixtureRoot = path.join(process.cwd(), "fixtures");

describe("executeRecipe", () => {
  it("executes the PRM sample directions together", () => {
    const sheet = makeSheet("Sheet1", [
      cell("Sheet1", "R1C4", 1, 4, "Female", "string"),
      cell("Sheet1", "R1C6", 1, 6, "Male", "string"),
      cell("Sheet1", "R2C4", 2, 4, "Count", "string"),
      cell("Sheet1", "R2C5", 2, 5, "Count", "string"),
      cell("Sheet1", "R2C6", 2, 6, "Count", "string"),
      cell("Sheet1", "R2C7", 2, 7, "Count", "string"),
      cell("Sheet1", "R3C2", 3, 2, "Australia", "string"),
      cell("Sheet1", "R4C3", 4, 3, "NSW", "string"),
      cell("Sheet1", "R4C4", 4, 4, 123, "numeric"),
      cell("Sheet1", "R4C6", 4, 6, 88, "numeric"),
    ]);
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Sheet1",
      tables: [
        {
          name: "main_table",
          values: {
            name: "value",
            cells: { range: "R4C4:R4C6", where: { data_type: ["numeric"] } },
          },
          headers: [
            {
              name: "unit",
              direction: "N",
              cells: ["R2C4", "R2C5", "R2C6", "R2C7"],
            },
            {
              name: "gender",
              direction: "NNW",
              fill: "right",
              cells: ["R1C4", "R1C6"],
            },
            {
              name: "country",
              direction: "WNW",
              fill: "down",
              cells: ["R3C2"],
            },
            { name: "state", direction: "W", cells: ["R4C3"] },
          ],
        },
      ],
    };

    const result = executeRecipe(recipe, sheet);

    expect(result.tables[0].rows).toMatchObject([
      {
        unit: "Count",
        gender: "Female",
        country: "Australia",
        state: "NSW",
        value: 123,
      },
      {
        unit: "Count",
        gender: "Male",
        country: "Australia",
        state: "NSW",
        value: 88,
      },
    ]);
  });

  it("applies per-cell direction overrides without changing sibling headers", () => {
    const sheet = makeSheet("Sheet1", [
      cell("Sheet1", "R2C3", 2, 3, "Male", "string"),
      cell("Sheet1", "R3C3", 3, 3, 10, "numeric"),
      cell("Sheet1", "R5C2", 5, 2, "Female", "string"),
      cell("Sheet1", "R6C3", 6, 3, 20, "numeric"),
    ]);
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Sheet1",
      tables: [
        {
          name: "counts",
          values: { name: "value", cells: ["R3C3", "R6C3"] },
          headers: [
            {
              name: "sex",
              direction: "WNW",
              direction_overrides: { R2C3: "NNW" },
              cells: ["R2C3", "R5C2"],
            },
          ],
        },
      ],
    };

    const result = executeRecipe(recipe, sheet);

    expect(result.tables[0].rows).toMatchObject([
      { sex: "Male", value: 10 },
      { sex: "Female", value: 20 },
    ]);
    expect(
      result.tables[0].trace.value_cells.map((trace) =>
        trace.headers.map((header) => header.direction),
      ),
    ).toEqual([["NNW"], ["WNW"]]);
  });

  it.each(["simple-crosstab", "sparse-headers", "multi-table"])(
    "matches expected fixture output for %s",
    async (name) => {
      const recipe = readJson<RecipeV01>("recipes", name);
      const expected = readJson<{
        sheet: string;
        tables: Array<{ name: string; rows: unknown[] }>;
        non_table_cells: unknown[];
      }>("expected", name);
      const parsed = await parseWorkbook(
        readFileSync(path.join(fixtureRoot, "workbooks", `${name}.xlsx`)),
      );

      expect(parsed.ok).toBe(true);

      if (!parsed.ok) {
        throw new Error(`Could not parse fixture ${name}.`);
      }

      const sheet = findRecipeSheet(parsed.workbook, recipe.sheet);

      if (!sheet) {
        throw new Error(`Missing sheet ${recipe.sheet}.`);
      }

      const result = executeRecipe(recipe, sheet);

      expect(
        result.tables.map((table) => ({ name: table.table, rows: table.rows })),
      ).toEqual(expected.tables);
      expect(result.non_table_cells?.map(stripUndefined)).toEqual(
        expected.non_table_cells,
      );
    },
  );

  it.skipIf(!existsSync(path.join(process.cwd(), "json-examples")))(
    "matches the tidied CSV example for ABS_PRISONERS_2022_00_02_04",
    async () => {
      const assetName = "ABS_PRISONERS_2022_00_02_04";
      const exampleRoot = path.join(process.cwd(), "json-examples");

      const recipe = parseRecipe(
        JSON.parse(
          readFileSync(path.join(exampleRoot, `${assetName}.json`), "utf8"),
        ),
      );
      const expectedCsv = readFileSync(
        path.join(exampleRoot, `${assetName}.csv`),
        "utf8",
      );
      const expectedRows = parseCsv(expectedCsv);
      const parsed = await parseWorkbook(
        readFileSync(path.join(exampleRoot, `${assetName}.xlsx`)),
      );

      expect(parsed.ok).toBe(true);

      if (!parsed.ok) {
        throw new Error(`Could not parse example ${assetName}.`);
      }

      const sheet = findRecipeSheet(parsed.workbook, recipe.sheet);

      if (!sheet) {
        throw new Error(`Missing sheet ${recipe.sheet}.`);
      }

      const result = executeRecipe(recipe, sheet);
      const table = result.tables[0];

      expect(table.warnings).toEqual([]);
      expect(
        rowsToCsv(table.rows, { valueColumn: recipe.tables[0].values.name }),
      ).toBe(expectedCsv);
      expect(
        toCsvComparisonRows(table.rows, recipe.tables[0].values.name),
      ).toEqual(expectedRows);
    },
  );

  it("warns for missing, ambiguous, overlapping, and unused headers", () => {
    const sheet = makeSheet("Warnings", [
      cell("Warnings", "R1C2", 1, 2, "Old", "string"),
      cell("Warnings", "R2C2", 2, 2, "New", "string"),
      cell("Warnings", "R3C1", 3, 1, "Row", "string"),
      cell("Warnings", "R3C2", 3, 2, 10, "numeric"),
      cell("Warnings", "R5C5", 5, 5, "Unused", "string"),
    ]);
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Warnings",
      tables: [
        {
          name: "a",
          values: { name: "value", cells: ["R3C2"] },
          headers: [
            { name: "version", direction: "N", cells: ["R1C2", "R2C2"] },
            {
              name: "required",
              direction: "W",
              required: true,
              cells: ["R9C1"],
            },
            { name: "unused", direction: "N", cells: ["R5C5"] },
          ],
        },
        {
          name: "b",
          values: { name: "value", cells: ["R3C2"] },
          headers: [{ name: "row", direction: "W", cells: ["R3C1"] }],
        },
      ],
    };

    const result = executeRecipe(recipe, sheet);

    expect(result.warnings.map((warning) => warning.code)).toEqual(
      expect.arrayContaining([
        "AMBIGUOUS_HEADER",
        "MISSING_REQUIRED_HEADER",
        "UNUSED_HEADER",
        "OVERLAPPING_VALUE_CELL",
      ]),
    );
  });
});

function readJson<T>(kind: "recipes" | "expected", name: string): T {
  return JSON.parse(
    readFileSync(path.join(fixtureRoot, kind, `${name}.json`), "utf8"),
  );
}

function stripUndefined<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function toCsvComparisonRows(
  rows: Array<
    ReturnType<typeof executeRecipe>["tables"][number]["rows"][number]
  >,
  valueName: string,
): Record<string, string | number | null>[] {
  return rows.map((row) => {
    const source = row._source;

    if (!source) {
      throw new Error("CSV comparison requires preserved source addresses.");
    }

    return {
      row: source.row,
      col: source.col,
      address: source.address,
      ".value": csvComparableScalar(row[valueName]),
      ...Object.fromEntries(
        Object.entries(row)
          .filter(([key]) => key !== "_source" && key !== valueName)
          .map(([key, value]) => [key, csvComparableScalar(value)]),
      ),
    };
  });
}

function parseCsv(content: string): Record<string, string | number | null>[] {
  const records = parseCsvRecords(content.trimEnd());
  const [headers, ...rows] = records;

  return rows.map((row) =>
    Object.fromEntries(
      headers.map((header, index) => [
        header,
        header === "row" || header === "col"
          ? parseCsvNumeric(row[index] ?? "")
          : parseCsvText(row[index] ?? ""),
      ]),
    ),
  );
}

function parseCsvRecords(content: string): string[][] {
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let inQuotes = false;

  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];
    const next = content[index + 1];

    if (char === '"' && inQuotes && next === '"') {
      field += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      inQuotes = !inQuotes;
      continue;
    }

    if (char === "," && !inQuotes) {
      record.push(field);
      field = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") {
        index += 1;
      }

      record.push(field);
      records.push(record);
      record = [];
      field = "";
      continue;
    }

    field += char;
  }

  record.push(field);
  records.push(record);

  return records;
}

function parseCsvText(value: string): string | null {
  if (value === "") {
    return null;
  }

  return value;
}

function parseCsvNumeric(value: string): number | null {
  if (value === "") {
    return null;
  }

  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function csvComparableScalar(value: unknown): string | number | null {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === "number") {
    return String(value);
  }

  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "boolean") {
    return String(value);
  }

  throw new Error("Unexpected non-scalar CSV comparison value.");
}

function makeSheet(name: string, cells: TidyCell[]): ParsedSheet {
  return {
    name,
    usedRange: "R1C1:R10C10",
    rowCount: 10,
    columnCount: 10,
    nonEmptyCellCount: cells.filter(
      (candidate) => candidate.data_type !== "blank",
    ).length,
    cells,
    merges: [],
  };
}

function cell(
  sheet: string,
  address: string,
  row: number,
  col: number,
  value: TidyCell["value"],
  dataType: TidyCell["data_type"],
): TidyCell {
  return {
    sheet,
    address,
    row,
    col,
    value,
    data_type: dataType,
  };
}
