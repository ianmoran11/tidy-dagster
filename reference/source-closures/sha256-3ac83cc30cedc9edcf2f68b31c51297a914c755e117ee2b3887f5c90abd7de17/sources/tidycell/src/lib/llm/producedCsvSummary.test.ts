import { describe, expect, it } from "vitest";
import type { ExecutionResult } from "@/lib/executor/types";
import type { RecipeV01 } from "@/lib/recipe/types";
import {
  buildProducedCsvColumnSummary,
  buildProducedCsvReviewArtifacts,
} from "@/lib/llm/producedCsvSummary";

describe("buildProducedCsvColumnSummary", () => {
  it("summarizes non-empty unique values for each produced CSV column", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Population",
      tables: [
        {
          name: "population_counts",
          values: { name: "value", cells: ["R2C3", "R3C3", "R4C3"] },
          headers: [
            { name: "state", direction: "W", cells: ["R2C1", "R3C1", "R4C1"] },
            { name: "sex", direction: "W", cells: ["R2C2", "R3C2", "R4C2"] },
          ],
        },
      ],
    };
    const execution: ExecutionResult = {
      sheet: "Population",
      warnings: [],
      tables: [
        {
          table: "population_counts",
          sheet: "Population",
          warnings: [],
          trace: { value_cells: [] },
          rows: [
            {
              _source: { sheet: "Population", address: "R2C3", row: 2, col: 3 },
              state: "NSW",
              sex: "Male",
              value: 10,
            },
            {
              _source: { sheet: "Population", address: "R3C3", row: 3, col: 3 },
              state: "NSW",
              sex: "Female",
              value: 12,
            },
            {
              _source: { sheet: "Population", address: "R4C3", row: 4, col: 3 },
              state: "NSW",
              sex: "Persons",
              value: 22,
            },
          ],
        },
      ],
    };

    const summary = buildProducedCsvColumnSummary(recipe, execution, {
      maxValuesPerColumn: 2,
    });
    const state = summary[0].columns.find((column) => column.name === "state");
    const sex = summary[0].columns.find((column) => column.name === "sex");
    const value = summary[0].columns.find((column) => column.name === ".value");

    expect(summary[0]).toMatchObject({
      row_count: 3,
      unique_row_key_count: 3,
      duplicate_header_key_count: 0,
      duplicate_header_row_count: 0,
      duplicate_header_key_share: 0,
      column_pair_overlap: [],
    });
    expect(state).toMatchObject({
      unique_count: 1,
      empty_count: 0,
      missing_share: 0,
      high_missing_share: false,
      numeric_parse_share: 0,
      values: ["NSW"],
      truncated: false,
    });
    expect(sex).toMatchObject({
      unique_count: 3,
      empty_count: 0,
      missing_share: 0,
      high_missing_share: false,
      numeric_parse_share: 0,
      values: ["Male", "Female"],
      truncated: true,
    });
    expect(value).toMatchObject({
      unique_count: 3,
      numeric_parse_share: 1,
    });
  });

  it("flags columns with high missing shares", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Population",
      tables: [
        {
          name: "population_counts",
          values: { name: "value", cells: ["R2C3", "R3C3", "R4C3", "R5C3"] },
          headers: [
            {
              name: "age_group",
              direction: "W",
              cells: ["R2C1", "R3C1", "R4C1", "R5C1"],
            },
          ],
        },
      ],
    };
    const execution: ExecutionResult = {
      sheet: "Population",
      warnings: [],
      tables: [
        {
          table: "population_counts",
          sheet: "Population",
          warnings: [],
          trace: { value_cells: [] },
          rows: [
            {
              _source: { sheet: "Population", address: "R2C3", row: 2, col: 3 },
              age_group: "0-4",
              note: "estimated",
              value: 10,
            },
            {
              _source: { sheet: "Population", address: "R3C3", row: 3, col: 3 },
              age_group: "5-9",
              note: null,
              value: 12,
            },
            {
              _source: { sheet: "Population", address: "R4C3", row: 4, col: 3 },
              age_group: "10-14",
              note: null,
              value: 14,
            },
            {
              _source: { sheet: "Population", address: "R5C3", row: 5, col: 3 },
              age_group: "15-19",
              note: null,
              value: 16,
            },
          ],
        },
      ],
    };

    const summary = buildProducedCsvColumnSummary(recipe, execution);
    const note = summary[0].columns.find((column) => column.name === "note");

    expect(note).toMatchObject({
      unique_count: 1,
      empty_count: 3,
      missing_share: 0.75,
      high_missing_share: true,
      numeric_parse_share: 0,
      values: ["estimated"],
    });
  });

  it("reports duplicate header keys and complementary sparse column pairs", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Population",
      tables: [
        {
          name: "population_counts",
          values: {
            name: "value",
            cells: ["R2C3", "R3C3", "R4C3", "R5C3"],
          },
          headers: [
            {
              name: "region",
              direction: "W",
              cells: ["R2C1", "R3C1", "R4C1", "R5C1"],
            },
          ],
        },
      ],
    };
    const execution: ExecutionResult = {
      sheet: "Population",
      warnings: [],
      tables: [
        {
          table: "population_counts",
          sheet: "Population",
          warnings: [],
          trace: { value_cells: [] },
          rows: [
            {
              _source: { sheet: "Population", address: "R2C3", row: 2, col: 3 },
              region: "NSW",
              male: "Male",
              female: null,
              value: 10,
            },
            {
              _source: { sheet: "Population", address: "R3C3", row: 3, col: 3 },
              region: "NSW",
              male: null,
              female: "Female",
              value: 12,
            },
            {
              _source: { sheet: "Population", address: "R4C3", row: 4, col: 3 },
              region: "VIC",
              male: "Male",
              female: null,
              value: 20,
            },
            {
              _source: { sheet: "Population", address: "R5C3", row: 5, col: 3 },
              region: "VIC",
              male: null,
              female: "Female",
              value: 22,
            },
          ],
        },
      ],
    };

    const summary = buildProducedCsvColumnSummary(recipe, execution);

    expect(summary[0]).toMatchObject({
      row_count: 4,
      unique_row_key_count: 4,
      duplicate_header_key_count: 0,
      duplicate_header_key_share: 0,
      column_pair_overlap: [
        {
          columns: ["male", "female"],
          both_present_share: 0,
          left_only_share: 0.5,
          right_only_share: 0.5,
          neither_present_share: 0,
          complementary_missing_share: 1,
        },
      ],
    });
  });

  it("reports duplicate header keys when row keys repeat with different values", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Population",
      tables: [
        {
          name: "population_counts",
          values: { name: "value", cells: ["R2C3", "R3C3"] },
          headers: [{ name: "state", direction: "W", cells: ["R2C1", "R3C1"] }],
        },
      ],
    };
    const execution: ExecutionResult = {
      sheet: "Population",
      warnings: [],
      tables: [
        {
          table: "population_counts",
          sheet: "Population",
          warnings: [],
          trace: { value_cells: [] },
          rows: [
            {
              _source: { sheet: "Population", address: "R2C3", row: 2, col: 3 },
              state: "NSW",
              value: 10,
            },
            {
              _source: { sheet: "Population", address: "R3C3", row: 3, col: 3 },
              state: "NSW",
              value: 12,
            },
          ],
        },
      ],
    };

    const summary = buildProducedCsvColumnSummary(recipe, execution);

    expect(summary[0]).toMatchObject({
      row_count: 2,
      unique_row_key_count: 1,
      duplicate_header_key_count: 1,
      duplicate_header_row_count: 2,
      duplicate_header_key_share: 1,
    });
  });

  it("keeps the full produced CSV sample when it is small", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Population",
      tables: [
        {
          name: "population_counts",
          values: { name: "value", cells: ["R2C3"] },
          headers: [{ name: "state", direction: "W", cells: ["R2C1"] }],
        },
      ],
    };
    const execution: ExecutionResult = {
      sheet: "Population",
      warnings: [],
      tables: [
        {
          table: "population_counts",
          sheet: "Population",
          warnings: [],
          trace: { value_cells: [] },
          rows: [
            {
              _source: { sheet: "Population", address: "R2C3", row: 2, col: 3 },
              state: "NSW",
              value: 10,
            },
          ],
        },
      ],
    };
    const producedCsv = "row,col,address,.value,state\n2,3,R2C3,10,NSW\n";

    const artifacts = buildProducedCsvReviewArtifacts(
      recipe,
      execution,
      producedCsv,
    );

    expect(artifacts.producedCsvSample).toBe(producedCsv);
    expect(artifacts.producedCsvSuspiciousRows).toEqual({
      duplicate_header_keys: [],
      low_numeric_value_rows: [],
      high_missing_column_rows: [],
      sparse_column_pair_rows: [],
    });
  });

  it("uses excerpts and targeted suspicious rows when the produced CSV is large", () => {
    const recipe: RecipeV01 = {
      version: "0.1",
      sheet: "Population",
      tables: [
        {
          name: "population_counts",
          values: { name: "value", cells: { range: "R2C3:R31C3" } },
          headers: [
            { name: "state", direction: "W", cells: { range: "R2C1:R31C1" } },
          ],
        },
      ],
    };
    const rows = Array.from({ length: 30 }, (_, index) => {
      const row = index + 2;
      return {
        _source: { sheet: "Population", address: `R${row}C3`, row, col: 3 },
        state: index < 15 ? "NSW" : "VIC",
        male: index % 2 === 0 ? "Male" : null,
        female: index % 2 === 1 ? "Female" : null,
        note: index === 0 ? "estimated" : null,
        value: index === 5 ? "not available" : 100 + index,
      };
    });
    const execution: ExecutionResult = {
      sheet: "Population",
      warnings: [],
      tables: [
        {
          table: "population_counts",
          sheet: "Population",
          warnings: [],
          trace: { value_cells: [] },
          rows,
        },
      ],
    };
    const producedCsv = [
      "row,col,address,.value,state,male,female,note",
      ...rows.map((row) =>
        [
          row._source.row,
          row._source.col,
          row._source.address,
          row.value,
          row.state,
          row.male ?? "",
          row.female ?? "",
          row.note ?? "",
        ].join(","),
      ),
      "",
    ].join("\n");

    const artifacts = buildProducedCsvReviewArtifacts(
      recipe,
      execution,
      producedCsv,
      {
        fullCsvCharLimit: 200,
        excerptHeadRows: 2,
        excerptTailRows: 2,
        excerptStratifiedRows: 2,
      },
    );

    expect(artifacts.producedCsvSample).toContain("full CSV omitted");
    expect(artifacts.producedCsvSample).toContain("R2C3");
    expect(artifacts.producedCsvSample).toContain("R31C3");
    expect(
      artifacts.producedCsvSuspiciousRows.low_numeric_value_rows[0],
    ).toMatchObject({
      column: ".value",
      rows: [expect.objectContaining({ ".value": "not available" })],
    });
    expect(
      artifacts.producedCsvSuspiciousRows.high_missing_column_rows[0],
    ).toMatchObject({
      column: "note",
      rows: [expect.objectContaining({ note: "estimated" })],
    });
    expect(
      artifacts.producedCsvSuspiciousRows.sparse_column_pair_rows[0],
    ).toMatchObject({
      columns: ["male", "female"],
    });
  });
});
