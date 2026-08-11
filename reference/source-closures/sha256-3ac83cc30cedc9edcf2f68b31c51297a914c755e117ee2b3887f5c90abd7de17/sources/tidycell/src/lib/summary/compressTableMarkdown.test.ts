import { describe, expect, it } from "vitest";
import { compressTableMarkdown } from "./compressTableMarkdown";

describe("compressTableMarkdown", () => {
  it("collapses blank row runs only at the three-row threshold and preserves row indices", () => {
    const markdown = [
      "| [R1C1] name | [R1C2] value |",
      "|---|---|",
      "| [R2C1] a | [R2C2] 1 |",
      "| [R3C1] | [R3C2] |",
      "| [R4C1] | [R4C2] |",
      "| [R5C1] b | [R5C2] 2 |",
      "| [R6C1] | [R6C2] |",
      "| [R7C1] | [R7C2] |",
      "| [R8C1] | [R8C2] |",
    ].join("\n");

    const compressed = compressTableMarkdown(markdown, { collapseBlankRows: true });

    expect(compressed).toContain("[R3C1]");
    expect(compressed).toContain("[R4C1]");
    expect(compressed).toContain("rows 6–8 blank");
    expect(compressed).not.toContain("[R7C1]");
  });

  it("collapses repeated row runs only at the three-row threshold with row numbers", () => {
    const markdown = [
      "| [R1C1] label | [R1C2] value |",
      "| [R2C1] same | [R2C2] 10 |",
      "| [R3C1] same | [R3C2] 10 |",
      "| [R4C1] other | [R4C2] 20 |",
      "| [R5C1] same | [R5C2] 10 |",
      "| [R6C1] same | [R6C2] 10 |",
      "| [R7C1] same | [R7C2] 10 |",
    ].join("\n");

    const compressed = compressTableMarkdown(markdown, { collapseRepeatedRows: true });

    expect(compressed).toContain("[R2C1] same");
    expect(compressed).toContain("[R3C1] same");
    expect(compressed).toContain("rows 5–7 repeat previous row 2 more times");
    expect(compressed).not.toContain("[R6C1]");
  });

  it("caps cell text with an ellipsis marker", () => {
    const compressed = compressTableMarkdown("| [R1C1] abcdefghij |", { cellCharCap: 12 });
    expect(compressed).toContain("[R1C1] abcd…");
  });

  it("collapses blank columns at the three-column threshold and preserves C indices", () => {
    const markdown = [
      "| [R1C1] a | [R1C2] | [R1C3] | [R1C4] | [R1C5] z |",
      "| [R2C1] b | [R2C2] | [R2C3] | [R2C4] | [R2C5] y |",
    ].join("\n");

    const compressed = compressTableMarkdown(markdown, { collapseBlankColumns: true });

    expect(compressed).toContain("columns C2–C4 blank");
    expect(compressed).toContain("[R1C5] z");
  });

  it("samples tall rows with R1C1 row annotations and candidate-boundary padding", () => {
    const rows = Array.from({ length: 30 }, (_, index) => {
      const row = index + 1;
      return `| [R${row}C1] label ${row} | [R${row}C2] ${row} |`;
    }).join("\n");

    const compressed = compressTableMarkdown(rows, {
      rowSampling: { firstRows: 3, lastRows: 2, boundaryPadding: 1 },
      candidateRegions: [{ range: "R20C1:R25C2", rowCount: 6, columnCount: 2, numericCellCount: 6 }],
    });

    expect(compressed).toContain("[R1C1]");
    expect(compressed).toContain("[R19C1]");
    expect(compressed).toContain("[R20C1]");
    expect(compressed).toContain("[R26C1]");
    expect(compressed).toContain("[R30C1]");
    expect(compressed).toMatch(/rows \d+–\d+ elided by sampling/);
  });
});
