/* Source-derived from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb (MIT). */
import { describe, expect, it } from "vitest";
import { recipeV01Schema, validateRecipe } from "../src/recipe/schema.js";

const sampleRecipe = {
  version: "0.1",
  sheet: "Sheet1",
  tables: [
    {
      name: "main_table",
      values: {
        name: "value",
        cells: {
          range: "R3C4:R8C7",
          where: { data_type: ["numeric", "blank"] },
        },
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
          cells: ["R1C4", "R1C6"],
          fill: "right",
        },
        {
          name: "country",
          direction: "WNW",
          cells: ["R3C2", "R6C2"],
          fill: "down",
        },
        {
          name: "state",
          direction: "W",
          cells: ["R4C3", "R5C3", "R7C3", "R8C3"],
        },
      ],
    },
  ],
} as const;

const validRecipes = [
  sampleRecipe,
  {
    version: "0.1",
    sheet: "Sheet1",
    tables: [
      {
        name: "population_counts",
        values: {
          name: "count",
          cells: { range: "R3C4:R8C7", where: { data_type: ["numeric"] } },
        },
        headers: [
          { name: "unit", direction: "N", cells: ["R2C4", "R2C5"] },
          { name: "state", direction: "W", cells: ["R4C3", "R5C3"] },
        ],
      },
      {
        name: "footnote_counts",
        values: {
          name: "count",
          cells: { range: "R14C4:R18C6", where: { data_type: ["numeric"] } },
        },
        headers: [
          { name: "category", direction: "W", cells: ["R14C3", "R15C3"] },
          { name: "year", direction: "N", cells: ["R13C4", "R13C5"] },
        ],
      },
    ],
  },
  {
    version: "0.1",
    sheet: "Booleans",
    options: {
      include_blank_values: true,
      preserve_source_address: false,
      preserve_formatted_value: true,
      preserve_non_table_cells: true,
      include_blank_non_table_cells: false,
    },
    tables: [
      {
        name: "flags",
        values: { name: "flag", cells: ["R2C2", "R3C2"] },
        headers: [
          { name: "label", direction: "W", cells: { cells: ["R2C1", "R3C1"] } },
        ],
        options: { preserve_source_address: true },
      },
    ],
  },
  {
    version: "0.1",
    sheet: "Sparse",
    tables: [
      {
        name: "filled_headers",
        values: {
          name: "amount",
          cells: { range: "R4C2:R5C5", where: { non_blank: true } },
        },
        headers: [
          {
            name: "quarter",
            direction: "NNW",
            fill: "right",
            cells: ["R3C2", "R3C4"],
          },
          { name: "region", direction: "WNW", fill: "down", cells: ["R4C1"] },
        ],
      },
    ],
  },
  {
    version: "0.1",
    sheet: "Comments",
    tables: [
      {
        name: "commented_values",
        values: {
          name: "value",
          cells: {
            cells: ["R2C2", "R3C2"],
            where: {
              data_type: ["numeric", "date"],
              has_formula: false,
              has_comment: true,
              style_id: ["style_a"],
            },
          },
        },
        headers: [
          { name: "metric", direction: "N", cells: ["R1C2"], required: true },
        ],
      },
    ],
  },
] as const;

describe("recipe schema v0.1", () => {
  it.each(validRecipes)("validates valid recipes %#", (recipe) => {
    expect(recipeV01Schema.safeParse(recipe).success).toBe(true);
  });

  it("accepts per-cell header direction overrides", () => {
    const result = recipeV01Schema.safeParse({
      version: "0.1",
      sheet: "Sheet1",
      tables: [
        {
          name: "mixed_directions",
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
    });

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.tables[0].headers[0].direction_overrides).toEqual({
        R2C3: "NNW",
      });
    }
  });

  it("normalizes legacy selector strings and strips diagnostic fields", () => {
    const result = recipeV01Schema.safeParse({
      version: "0.1",
      sheet: "Sheet1",
      tables: [
        {
          name: "legacy",
          values: { name: "value", cells: "R2C2:R3C3", ".values": [1, 2] },
          headers: [
            {
              name: "state",
              direction: "N",
              cells: "R1C2:R1C3",
              ".values": ["NSW", "Vic."],
            },
          ],
        },
      ],
    });

    expect(result.success).toBe(true);

    if (result.success) {
      expect(result.data.tables[0].values.cells).toEqual({
        range: "R2C2:R3C3",
      });
      expect(result.data.tables[0].headers[0].cells).toEqual({
        range: "R1C2:R1C3",
      });
      expect(result.data.tables[0].headers[0]).not.toHaveProperty(".values");
    }
  });

  it("returns structured validation errors", () => {
    const result = validateRecipe({ version: "0.1", sheet: "Sheet1" });

    expect(result.success).toBe(false);
    expect(result.errors?.[0]).toMatchObject({
      path: "tables",
      message: expect.any(String),
    });
  });

  it("rejects ranges that exceed the expansion cell budget", () => {
    const result = validateRecipe({
      version: "0.1",
      sheet: "Sheet1",
      tables: [
        {
          name: "huge",
          values: { name: "value", cells: "R1C1:R1048576C16384" },
          headers: [],
        },
      ],
    });

    expect(result.success).toBe(false);
    expect(result.errors?.some((error) => /exceeds/.test(error.message))).toBe(
      true,
    );
  });

  it.each([
    ["header colliding with values name", "value"],
    ["header colliding with _source", "_source"],
    ["header colliding with generated source column", "value_source"],
  ])("rejects output column collisions: %s", (_label, headerName) => {
    const result = validateRecipe({
      version: "0.1",
      sheet: "Sheet1",
      tables: [
        {
          name: "collisions",
          values: { name: "value", cells: "R2C2" },
          headers: [
            {
              name: headerName,
              direction: "N",
              cells: "R1C2",
            },
          ],
        },
      ],
    });

    expect(result.success).toBe(false);
  });

  it.each([
    [
      "value instead of values",
      {
        ...sampleRecipe,
        tables: [
          {
            ...sampleRecipe.tables[0],
            values: undefined,
            value: sampleRecipe.tables[0].values,
          },
        ],
      },
      "tables.0.values",
    ],
    ["missing tables", { version: "0.1", sheet: "Sheet1" }, "tables"],
    ["empty tables", { version: "0.1", sheet: "Sheet1", tables: [] }, "tables"],
    [
      "duplicate table names",
      {
        version: "0.1",
        sheet: "Sheet1",
        tables: [sampleRecipe.tables[0], sampleRecipe.tables[0]],
      },
      "tables.1.name",
    ],
    [
      "duplicate header names",
      {
        ...sampleRecipe,
        tables: [
          {
            ...sampleRecipe.tables[0],
            headers: [
              sampleRecipe.tables[0].headers[0],
              {
                ...sampleRecipe.tables[0].headers[1],
                name: sampleRecipe.tables[0].headers[0].name,
              },
            ],
          },
        ],
      },
      "tables.0.headers.1.name",
    ],
    [
      "unsupported direction",
      {
        ...sampleRecipe,
        tables: [
          {
            ...sampleRecipe.tables[0],
            headers: [{ ...sampleRecipe.tables[0].headers[0], direction: "S" }],
          },
        ],
      },
      "tables.0.headers.0.direction",
    ],
    ["unsupported version", { ...sampleRecipe, version: "0.2" }, "version"],
    [
      "invalid cell address",
      {
        ...sampleRecipe,
        tables: [
          {
            ...sampleRecipe.tables[0],
            headers: [{ ...sampleRecipe.tables[0].headers[0], cells: ["A1"] }],
          },
        ],
      },
      "tables.0.headers.0.cells",
    ],
    [
      "invalid range",
      {
        ...sampleRecipe,
        tables: [
          {
            ...sampleRecipe.tables[0],
            values: { name: "value", cells: { range: "R3C4:R2C4" } },
          },
        ],
      },
      "tables.0.values.cells",
    ],
    [
      "invalid non-table option",
      { ...sampleRecipe, options: { preserve_non_table_cells: "yes" } },
      "options.preserve_non_table_cells",
    ],
    [
      "unknown option key",
      {
        ...sampleRecipe,
        options: { preserve_non_table_cells: true, archive_original: true },
      },
      "options",
    ],
    [
      "unsupported fill",
      {
        ...sampleRecipe,
        tables: [
          {
            ...sampleRecipe.tables[0],
            headers: [{ ...sampleRecipe.tables[0].headers[0], fill: "left" }],
          },
        ],
      },
      "tables.0.headers.0.fill",
    ],
  ])("rejects invalid recipe: %s", (_name, recipe, expectedPath) => {
    const result = validateRecipe(recipe);

    expect(result.success).toBe(false);
    expect(
      result.errors?.some((error) => error.path.startsWith(expectedPath)),
    ).toBe(true);
  });
});
