/* Source-derived raw-export vectors from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb (MIT). */
import { describe, expect, it } from "vitest";
import { rowsToCsv, rowsToTableData } from "../src/export/formatters.js";
import type { TidyOutputRow } from "../src/executor/types.js";

const rows: TidyOutputRow[] = [
  {
    state: "NSW",
    note: 'comma, quote " and\nnewline',
    count: 123,
    _source: { sheet: "Mixed", address: "R4C3", row: 4, col: 3 },
  },
];

describe("raw export formatters", () => {
  it("preserves first-seen columns, exact escaping, LF and final newline", () => {
    expect(rowsToCsv(rows)).toBe(
      'state,note,count,_source.sheet,_source.address,_source.row,_source.col\nNSW,"comma, quote "" and\nnewline",123,Mixed,R4C3,4,3\n',
    );
  });

  it("formats recipe-aware source columns and value", () => {
    expect(rowsToCsv(rows, { valueColumn: "count" })).toBe(
      'row,col,address,.value,state,note\n4,3,R4C3,123,NSW,"comma, quote "" and\nnewline"\n',
    );
  });

  it("omits generated source fields in clean mode", () => {
    const traced: TidyOutputRow[] = [
      {
        count: 1,
        year: "2024",
        year_source: "R1C1",
        _source: { sheet: "S", address: "R2C1", row: 2, col: 1 },
      },
    ];
    expect(rowsToTableData(traced, { includeSourceColumns: false })).toEqual({
      headers: ["count", "year"],
      rows: [[1, "2024"]],
    });
  });

  it("guards formula-like strings only when requested", () => {
    expect(rowsToCsv([{ value: "=HYPERLINK(1)", count: -5 }])).toBe(
      "value,count\n=HYPERLINK(1),-5\n",
    );
    expect(
      rowsToCsv([{ value: "=HYPERLINK(1)", count: -5 }], {
        guardFormulas: true,
      }),
    ).toBe("value,count\n'=HYPERLINK(1),-5\n");
  });
});
