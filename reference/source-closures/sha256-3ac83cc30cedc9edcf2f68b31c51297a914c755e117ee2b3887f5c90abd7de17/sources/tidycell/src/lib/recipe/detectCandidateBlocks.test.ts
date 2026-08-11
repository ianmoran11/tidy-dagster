import { describe, expect, it } from "vitest";

import { expandRange, parseRange } from "@/lib/address";
import type { CellDataType, ParsedSheet, TidyCell } from "@/lib/workbook/types";
import {
  candidateBlockSignature,
  detectCandidateBlocks,
  detectCountPercentagePairBlocks,
  detectMergedHeadingBlocks,
  detectRepeatedLabelBlocks,
  detectYearRunBlocks,
  MAX_CANDIDATE_BLOCKS,
} from "./detectCandidateBlocks";
import parity from "../../../tests/fixtures/workspace/candidate-block-parity-v1.json";
import {
  BLOCK_SUGGESTION_LABEL_RANGE,
  BLOCK_SUGGESTION_VALUE_RANGE,
  createBlockSuggestionSheet,
  createFactorVariantYearSuggestionSheet,
  createRecordedSuggestionSheet,
  createStructureAwareSuggestionSheet,
  FACTOR_VARIANT_YEAR_RANGES,
  RECORDED_SUGGESTION_FALSE_YEAR_RANGE,
  RECORDED_SUGGESTION_YEAR_RANGES,
  STRUCTURE_SUGGESTION_VALUE_RANGE,
  STRUCTURE_SUGGESTION_YEAR_RANGE,
} from "../../../tests/fixtures/workspace/blockSuggestions";

function createCell(
  sheet: string,
  row: number,
  col: number,
  value: TidyCell["value"],
  dataType: CellDataType,
  formatted: string | null = null,
): TidyCell {
  return {
    sheet,
    address: `R${row}C${col}`,
    row,
    col,
    value,
    data_type: dataType,
    formula: null,
    formatted,
    comment: null,
    hyperlink: null,
    merge: null,
  };
}

describe("detectCandidateBlocks", () => {
  it("is byte-identical to the pinned Tidybank detector on shared parity fixtures", () => {
    const fixtures = [
      createBlockSuggestionSheet(),
      createStructureAwareSuggestionSheet(),
      createRecordedSuggestionSheet(),
      createFactorVariantYearSuggestionSheet(),
    ];

    for (const sheet of fixtures) {
      expect(JSON.stringify(detectCandidateBlocks(sheet))).toBe(
        JSON.stringify(
          parity.fixtures[sheet.name as keyof typeof parity.fixtures],
        ),
      );
    }
  });

  it("grades a contiguous year row from named evidence factors", () => {
    const blocks = detectYearRunBlocks(createStructureAwareSuggestionSheet());

    expect(blocks).toContainEqual(
      expect.objectContaining({
        range: STRUCTURE_SUGGESTION_YEAR_RANGE,
        ranges: [STRUCTURE_SUGGESTION_YEAR_RANGE],
        classification: "year-run",
        suggestedRole: "header",
        confidence: "medium",
        confidenceFactors: [
          "annual-step",
          "ascending-direction",
          "adjacent-value-body",
        ],
        evidence:
          "Year values 2017–2019 form a contiguous row run inside 1850–2100.",
      }),
    );
  });

  it("accepts annual pairs and plausible stepped runs but rejects arbitrary and inconsistent steps", () => {
    const run = (name: string, years: number[]) =>
      fixtureSheet(
        name,
        `R1C1:R1C${years.length}`,
        years.map((year, index) =>
          createCell(name, 1, index + 1, year, "numeric"),
        ),
      );

    expect(detectYearRunBlocks(run("Annual pair", [2019, 2020]))).toHaveLength(
      1,
    );
    expect(
      detectYearRunBlocks(run("Stepped years", [2015, 2020, 2025])),
    ).toContainEqual(
      expect.objectContaining({
        range: "R1C1:R1C3",
        suggestedRole: "header",
        evidence:
          "Year values 2015–2025 form an evenly stepped by 5 row run inside 1850–2100.",
      }),
    );
    expect(detectYearRunBlocks(run("Recorded totals", [1970, 1888]))).toEqual(
      [],
    );
    expect(
      detectYearRunBlocks(run("Implausible step", [2010, 2013, 2016])),
    ).toEqual([]);
    expect(
      detectYearRunBlocks(run("Inconsistent", [2017, 2018, 2020])),
    ).toEqual([]);
    expect(
      detectYearRunBlocks(run("Direction reversal", [2017, 2018, 2017])),
    ).toEqual([]);
    expect(
      detectYearRunBlocks(run("Descending stepped", [2020, 2015, 2010])),
    ).toContainEqual(
      expect.objectContaining({
        confidenceFactors: ["plausible-step", "descending-direction"],
      }),
    );
  });

  it("varies confidence with annual, length, direction, and adjacent-body evidence", () => {
    const short = fixtureSheet("Short years", "R1C1:R1C2", [
      createCell("Short years", 1, 1, 2019, "numeric"),
      createCell("Short years", 1, 2, 2020, "numeric"),
    ]);
    const strongCells = [2016, 2017, 2018, 2019, 2020].flatMap(
      (year, index) => [
        createCell("Strong years", 1, index + 1, year, "numeric"),
        createCell("Strong years", 2, index + 1, 100 + index, "numeric"),
      ],
    );
    const strong = fixtureSheet("Strong years", "R1C1:R2C5", strongCells);

    expect(detectYearRunBlocks(short)[0]).toMatchObject({
      confidence: "low",
      confidenceFactors: ["annual-step", "ascending-direction"],
    });
    expect(
      detectYearRunBlocks(createStructureAwareSuggestionSheet())[0],
    ).toMatchObject({ confidence: "medium" });
    expect(detectYearRunBlocks(strong)[0]).toMatchObject({
      confidence: "high",
      confidenceFactors: [
        "annual-step",
        "ascending-direction",
        "long-run",
        "adjacent-value-body",
      ],
    });
  });

  it("detects a year column including parsed date values", () => {
    const sheet = fixtureSheet(
      "Year column",
      "R1C1:R3C1",
      [2017, 2018, 2019].map((year, index) =>
        createCell(
          "Year column",
          index + 1,
          1,
          `${year}-01-01T00:00:00.000Z`,
          "date",
        ),
      ),
    );

    expect(detectYearRunBlocks(sheet)).toContainEqual(
      expect.objectContaining({
        range: "R1C1:R3C1",
        suggestedRole: "header",
        evidence:
          "Year values 2017–2019 form a contiguous column run inside 1850–2100.",
      }),
    );
  });

  it("groups the recorded year blocks and excludes the 1970/1888 false positive", () => {
    const blocks = detectYearRunBlocks(createRecordedSuggestionSheet());

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({
      range: RECORDED_SUGGESTION_YEAR_RANGES[0],
      ranges: RECORDED_SUGGESTION_YEAR_RANGES,
      label: "year values 2010–2020",
      confidence: "high",
      signature: expect.objectContaining({ bold: false }),
      evidence: expect.stringContaining("This structure repeats 3 times."),
    });
    expect(blocks[0]?.ranges).not.toContain(
      RECORDED_SUGGESTION_FALSE_YEAR_RANGE,
    );
  });

  it("groups repeats with the same visible confidence despite different hidden factors", () => {
    const sheet = createFactorVariantYearSuggestionSheet();
    const blocks = detectYearRunBlocks(sheet);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({
      range: FACTOR_VARIANT_YEAR_RANGES[0],
      ranges: FACTOR_VARIANT_YEAR_RANGES,
      label: "year values 2020–2010",
      confidence: "low",
      confidenceFactors: ["plausible-step", "descending-direction"],
      evidence:
        "Year values 2020–2010 form an evenly stepped by 5 column run inside 1850–2100. This structure repeats 2 times.",
    });
    expect(blocks[0]?.cellCount).toBe(6);

    const reversed = { ...sheet, cells: [...sheet.cells].reverse() };
    expect(JSON.stringify(detectYearRunBlocks(reversed))).toBe(
      JSON.stringify(blocks),
    );
  });

  it("keeps otherwise identical repeats separate when visible confidence differs", () => {
    const cells = [
      ...[2016, 2017, 2018, 2019, 2020].flatMap((year, index) => [
        createCell("Confidence variants", index + 1, 1, year, "numeric"),
        createCell("Confidence variants", index + 1, 2, 100 + index, "numeric"),
      ]),
      ...[2016, 2017, 2018, 2019, 2020].map((year, index) =>
        createCell("Confidence variants", index + 7, 1, year, "numeric"),
      ),
    ];
    const blocks = detectYearRunBlocks(
      fixtureSheet("Confidence variants", "R1C1:R11C2", cells),
    );

    expect(blocks).toHaveLength(2);
    expect(blocks.map(({ label }) => label)).toEqual([
      "year values 2016–2020",
      "year values 2016–2020",
    ]);
    expect(blocks.map(({ confidence }) => confidence)).toEqual([
      "high",
      "medium",
    ]);
    expect(blocks.map(({ ranges }) => ranges)).toEqual([
      ["R1C1:R5C1"],
      ["R7C1:R11C1"],
    ]);
  });

  it("groups structural classifiers across cosmetic formatting without conflating format partitions", () => {
    const repeatedLabels = detectRepeatedLabelBlocks(
      fixtureSheet("Styled labels", "R1C1:R5C1", [
        createCell("Styled labels", 1, 1, "Total", "string"),
        createCell("Styled labels", 2, 1, "Total", "string"),
        styledCell(createCell("Styled labels", 4, 1, "Total", "string"), {
          bold: true,
        }),
        styledCell(createCell("Styled labels", 5, 1, "Total", "string"), {
          bold: true,
        }),
      ]),
    );
    expect(repeatedLabels).toHaveLength(1);
    expect(repeatedLabels[0]).toMatchObject({
      classification: "repeated-label-run",
      ranges: ["R1C1:R2C1", "R4C1:R5C1"],
      signature: expect.objectContaining({ bold: false }),
      evidence: expect.stringContaining("This structure repeats 2 times."),
    });

    const mergedHeadings = detectMergedHeadingBlocks(
      fixtureSheet(
        "Styled merges",
        "R1C1:R3C2",
        [
          createCell("Styled merges", 1, 1, "Total", "string"),
          styledCell(createCell("Styled merges", 3, 1, "Total", "string"), {
            bold: true,
          }),
        ],
        [
          { parent: "R1C1", range: "R1C1:R1C2" },
          { parent: "R3C1", range: "R3C1:R3C2" },
        ],
      ),
    );
    expect(mergedHeadings).toHaveLength(1);
    expect(mergedHeadings[0]).toMatchObject({
      classification: "merged-heading",
      ranges: ["R1C1:R1C2", "R3C1:R3C2"],
      signature: expect.objectContaining({ bold: false }),
      evidence: expect.stringContaining("This structure repeats 2 times."),
    });

    const pairCells = [
      createCell("Styled pairs", 1, 1, "Count", "string"),
      createCell("Styled pairs", 1, 2, "Percentage", "string"),
      createCell("Styled pairs", 1, 3, "Count", "string"),
      createCell("Styled pairs", 1, 4, "Percentage", "string"),
    ];
    for (const row of [2, 3, 5, 6]) {
      for (const col of [1, 2, 3, 4]) {
        const value = row * 10 + col;
        const cell = createCell(
          "Styled pairs",
          row,
          col,
          value,
          "numeric",
          col % 2 === 0 ? `${value}%` : `${value}`,
        );
        pairCells.push(row >= 5 ? styledCell(cell, { bold: true }) : cell);
      }
    }
    const countPercentagePairs = detectCountPercentagePairBlocks(
      fixtureSheet("Styled pairs", "R1C1:R6C4", pairCells),
    );
    expect(countPercentagePairs).toHaveLength(1);
    expect(countPercentagePairs[0]).toMatchObject({
      classification: "count-percentage-pairs",
      ranges: ["R2C1:R3C4", "R5C1:R6C4"],
      signature: expect.objectContaining({ bold: false }),
      evidence: expect.stringContaining("This structure repeats 2 times."),
    });

    const formatPartitions = detectCandidateBlocks(
      fixtureSheet("Styled partitions", "R1C1:R3C1", [
        createCell("Styled partitions", 1, 1, 10, "numeric"),
        styledCell(createCell("Styled partitions", 3, 1, 20, "numeric"), {
          bold: true,
        }),
      ]),
    ).filter(({ classification }) => classification === "format-partition");
    expect(formatPartitions).toHaveLength(2);
    expect(formatPartitions.map(({ ranges }) => ranges)).toEqual([
      ["R1C1:R1C1"],
      ["R3C1:R3C1"],
    ]);
  });

  it("leaves a lone plausible year inside numeric data as a value", () => {
    const sheet = fixtureSheet("Lone year", "R1C1:R2C2", [
      createCell("Lone year", 1, 1, 10, "numeric"),
      createCell("Lone year", 1, 2, 2017, "numeric"),
      createCell("Lone year", 2, 1, 20, "numeric"),
      createCell("Lone year", 2, 2, 30, "numeric"),
    ]);
    const blocks = detectCandidateBlocks(sheet);

    expect(blocks).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ classification: "year-run" }),
      ]),
    );
    expect(blocks).toContainEqual(
      expect.objectContaining({
        range: "R1C1:R2C2",
        suggestedRole: "value",
        classification: "format-partition",
      }),
    );
  });

  it("keeps the year band inclusive and rejects fractional values", () => {
    const boundarySheets = [
      fixtureSheet("Lower boundary", "R1C1:R1C2", [
        createCell("Lower boundary", 1, 1, 1850, "numeric"),
        createCell("Lower boundary", 1, 2, 1851, "numeric"),
      ]),
      fixtureSheet("Upper boundary", "R1C1:R1C2", [
        createCell("Upper boundary", 1, 1, 2099, "numeric"),
        createCell("Upper boundary", 1, 2, 2100, "numeric"),
      ]),
    ];
    const fractionalSheet = fixtureSheet(
      "Fractional years",
      "R1C1:R1C2",
      [2017.5, 2018.5].map((year, index) =>
        createCell("Fractional years", 1, index + 1, year, "numeric"),
      ),
    );

    expect(boundarySheets.map(detectYearRunBlocks)).toEqual([
      [expect.objectContaining({ range: "R1C1:R1C2" })],
      [expect.objectContaining({ range: "R1C1:R1C2" })],
    ]);
    expect(detectYearRunBlocks(fractionalSheet)).toEqual([]);
  });

  it("rejects year-like values outside the plausible band", () => {
    const sheet = fixtureSheet(
      "Outside band",
      "R1C1:R1C3",
      [1847, 1848, 1849].map((year, index) =>
        createCell("Outside band", 1, index + 1, year, "numeric"),
      ),
    );

    expect(detectYearRunBlocks(sheet)).toEqual([]);
    expect(detectCandidateBlocks(sheet)[0]).toMatchObject({
      range: "R1C1:R1C3",
      suggestedRole: "value",
    });
  });

  it("does not infer years from formatted text or string 2017 labels", () => {
    const sheet = fixtureSheet("Text years", "R1C1:R1C2", [
      createCell("Text years", 1, 1, "2017", "string", "2017"),
      createCell("Text years", 1, 2, "2018", "string", "2018"),
    ]);

    expect(detectYearRunBlocks(sheet)).toEqual([]);
    expect(detectCandidateBlocks(sheet)).toContainEqual(
      expect.objectContaining({
        range: "R1C1:R1C2",
        suggestedRole: "unknown",
      }),
    );
  });

  it("detects repeated nonblank labels and common stems as headers", () => {
    const sheet = fixtureSheet(
      "Repeated labels",
      "R1C1:R3C1",
      ["Offence 1", "Offence 2", "Offence 3"].map((label, index) =>
        createCell("Repeated labels", index + 1, 1, label, "string"),
      ),
    );

    expect(detectRepeatedLabelBlocks(sheet)).toContainEqual(
      expect.objectContaining({
        range: "R1C1:R3C1",
        classification: "repeated-label-run",
        suggestedRole: "header",
        confidence: "medium",
        label: "labels sharing “offence”",
        evidence:
          "Nonblank labels share the common stem “offence” along one column.",
      }),
    );

    const repeatedSequence = fixtureSheet(
      "Repeated sequence",
      "R1C1:R1C4",
      ["Count", "Percentage", "Count", "Percentage"].map((label, index) =>
        createCell("Repeated sequence", 1, index + 1, label, "string"),
      ),
    );
    expect(detectRepeatedLabelBlocks(repeatedSequence)).toContainEqual(
      expect.objectContaining({
        range: "R1C1:R1C4",
        suggestedRole: "header",
        label: "repeating labels “Count” and “Percentage”",
        evidence: "Nonblank label values repeat along one row header run.",
      }),
    );

    const exactRepeat = fixtureSheet("Exact repeat", "R1C1:R2C1", [
      createCell("Exact repeat", 1, 1, "Total", "string"),
      createCell("Exact repeat", 2, 1, "Total", "string"),
    ]);
    expect(detectRepeatedLabelBlocks(exactRepeat)).toContainEqual(
      expect.objectContaining({
        label: "repeated label “Total”",
        evidence: "Repeated nonblank label “Total” forms a column header run.",
      }),
    );
  });

  it("covers the full merge extent from ParsedSheet and TidyCell metadata", () => {
    const parent = styledCell(createCell("Merged", 1, 1, "Offence", "string"), {
      bold: true,
    });
    parent.merge = {
      parent: "R1C1",
      range: "R1C1:R1C4",
      role: "parent",
    };
    const children = [2, 3, 4].map((col) => {
      const child = createCell("Merged", 1, col, null, "blank");
      child.merge = {
        parent: "R1C1",
        range: "R1C1:R1C4",
        role: "child",
      };
      return child;
    });
    const sheet = fixtureSheet(
      "Merged",
      "R1C1:R1C4",
      [parent, ...children],
      [{ parent: "R1C1", range: "R1C1:R1C4" }],
    );

    expect(detectMergedHeadingBlocks(sheet)).toEqual([
      expect.objectContaining({
        range: "R1C1:R1C4",
        cellCount: 4,
        classification: "merged-heading",
        suggestedRole: "header",
        label: "merged heading “Offence”",
        evidence: "A merged heading spans its full 1 × 4 extent.",
      }),
    ]);

    const summaryOnly = fixtureSheet(
      "Summary merge",
      "R1C1:R1C4",
      [createCell("Summary merge", 1, 1, "Offence", "string")],
      [{ parent: "R1C1", range: "R1C1:R1C4" }],
    );
    expect(detectMergedHeadingBlocks(summaryOnly)).toContainEqual(
      expect.objectContaining({
        range: "R1C1:R1C4",
        classification: "merged-heading",
      }),
    );
  });

  it("detects alternating count and percentage column pairs as values", () => {
    const cells = [
      createCell("Pairs", 1, 1, "Assault count", "string"),
      createCell("Pairs", 1, 2, "Assault %", "string"),
      createCell("Pairs", 1, 3, "Theft count", "string"),
      createCell("Pairs", 1, 4, "Theft %", "string"),
      ...[2, 3].flatMap((row) => [
        createCell("Pairs", row, 1, row * 10, "numeric", `${row * 10}`),
        createCell("Pairs", row, 2, row / 10, "numeric", `${row * 10}%`),
        createCell("Pairs", row, 3, row * 20, "numeric", `${row * 20}`),
        createCell("Pairs", row, 4, row / 20, "numeric", `${row * 5}%`),
      ]),
    ];
    const sheet = fixtureSheet("Pairs", "R1C1:R3C4", cells);

    expect(detectCountPercentagePairBlocks(sheet)).toContainEqual(
      expect.objectContaining({
        range: "R2C1:R3C4",
        classification: "count-percentage-pairs",
        suggestedRole: "value",
        confidence: "high",
        confidenceFactors: ["percentage-format", "percentage-heading"],
        evidence:
          "2 alternating count/percentage column pairs are confirmed by percentage formatting and headings.",
      }),
    );
  });

  it.each([
    ["percentage formatting", "Value", true, ["percentage-format"]],
    [
      "percentage-bearing headings",
      "Percentage",
      false,
      ["percentage-heading"],
    ],
  ] as const)(
    "generates grammatical count/percentage evidence from %s",
    (source, percentageHeading, formattedPercentage, confidenceFactors) => {
      const cells = [
        createCell("Pair evidence", 1, 1, "Count", "string"),
        createCell("Pair evidence", 1, 2, percentageHeading, "string"),
        createCell("Pair evidence", 1, 3, "Count", "string"),
        createCell("Pair evidence", 1, 4, percentageHeading, "string"),
        ...[2, 3].flatMap((row) =>
          [1, 2, 3, 4].map((col) =>
            createCell(
              "Pair evidence",
              row,
              col,
              row * 10 + col,
              "numeric",
              formattedPercentage && col % 2 === 0
                ? `${row * 10 + col}%`
                : `${row * 10 + col}`,
            ),
          ),
        ),
      ];

      expect(
        detectCountPercentagePairBlocks(
          fixtureSheet("Pair evidence", "R1C1:R3C4", cells),
        ),
      ).toContainEqual(
        expect.objectContaining({
          confidenceFactors,
          evidence: `2 alternating count/percentage column pairs are confirmed by ${source}.`,
        }),
      );
    },
  );

  it.each([
    ["ParsedSheet.merges", "sheet"],
    ["TidyCell.merge", "cell"],
  ] as const)(
    "keeps %s header claims out of count/percentage value ranges",
    (_sourceName, source) => {
      const parent = createCell("Merged pairs", 1, 1, 42, "numeric", "42");
      if (source === "cell") {
        parent.merge = {
          parent: "R1C1",
          range: "R1C1:R1C4",
          role: "parent",
        };
      }
      const cells = [
        parent,
        ...[2, 3].flatMap((row) => [
          createCell("Merged pairs", row, 1, row * 10, "numeric"),
          createCell(
            "Merged pairs",
            row,
            2,
            row / 10,
            "numeric",
            `${row * 10}%`,
          ),
          createCell("Merged pairs", row, 3, row * 20, "numeric"),
          createCell(
            "Merged pairs",
            row,
            4,
            row / 20,
            "numeric",
            `${row * 5}%`,
          ),
        ]),
      ];
      const sheet = fixtureSheet(
        "Merged pairs",
        "R1C1:R3C4",
        cells,
        source === "sheet" ? [{ parent: "R1C1", range: "R1C1:R1C4" }] : [],
      );

      const blocks = detectCandidateBlocks(sheet);
      expect(blocks).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            range: "R1C1:R1C4",
            classification: "merged-heading",
            suggestedRole: "header",
          }),
          expect.objectContaining({
            range: "R2C1:R3C4",
            classification: "count-percentage-pairs",
            suggestedRole: "value",
          }),
        ]),
      );
      expect(detectCountPercentagePairBlocks(sheet)).toContainEqual(
        expect.objectContaining({
          range: "R2C1:R3C4",
          suggestedRole: "value",
        }),
      );
      expectNoIncompatibleRoleOverlaps(blocks);
    },
  );

  it("splits one numeric signature at incompatible header and value hints", () => {
    const blocks = detectCandidateBlocks(createStructureAwareSuggestionSheet());

    expect(blocks[0]).toMatchObject({
      range: STRUCTURE_SUGGESTION_YEAR_RANGE,
      classification: "year-run",
      suggestedRole: "header",
    });
    expect(blocks).toContainEqual(
      expect.objectContaining({
        range: STRUCTURE_SUGGESTION_VALUE_RANGE,
        classification: "format-partition",
        suggestedRole: "value",
      }),
    );
    expect(blocks).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ range: "R1C2:R4C4" })]),
    );
  });

  it("ranks a structural header above a larger undifferentiated value block", () => {
    const blocks = detectCandidateBlocks(createStructureAwareSuggestionSheet());

    expect(blocks[0]).toMatchObject({
      classification: "year-run",
      suggestedRole: "header",
      cellCount: 3,
    });
    expect(
      blocks.findIndex(
        ({ range }) => range === STRUCTURE_SUGGESTION_VALUE_RANGE,
      ),
    ).toBeGreaterThan(0);
  });

  it("keeps the striped value and label ranges with explicit roles", () => {
    const blocks = detectCandidateBlocks(createBlockSuggestionSheet());

    expect(blocks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          range: BLOCK_SUGGESTION_LABEL_RANGE,
          classification: "repeated-label-run",
          suggestedRole: "header",
        }),
        expect.objectContaining({
          range: BLOCK_SUGGESTION_VALUE_RANGE,
          classification: "format-partition",
          suggestedRole: "value",
          cellCount: 558,
        }),
      ]),
    );
  });

  it("keeps legacy formatting partitions internally signature-compatible", () => {
    const sheet = createBlockSuggestionSheet();
    const candidates = detectCandidateBlocks(sheet).filter(
      ({ classification }) => classification === "format-partition",
    );
    const cells = new Map(sheet.cells.map((cell) => [cell.address, cell]));

    for (const candidate of candidates) {
      const signatures = expandRange(candidate.range).map((address) =>
        candidateBlockSignature(cells.get(address) as TidyCell),
      );
      expect(
        signatures.every(
          (signature) =>
            JSON.stringify(signature) === JSON.stringify(candidate.signature),
        ),
      ).toBe(true);
    }
  });

  it("keeps labels range-free and siblings distinguishable by rendered prose", () => {
    const blocks = detectCandidateBlocks(createRecordedSuggestionSheet());
    for (const block of blocks) {
      expect(block.label).not.toContain(block.range);
      expect(block.evidence).toMatch(/[.!]$/);
    }
    for (let left = 0; left < blocks.length; left += 1) {
      for (let right = left + 1; right < blocks.length; right += 1) {
        const a = blocks[left]!;
        const b = blocks[right]!;
        if (
          a.classification === b.classification &&
          a.evidence === b.evidence
        ) {
          expect(a.label).not.toBe(b.label);
        }
      }
    }
  });

  it("is byte-deterministic for repeated and shuffled input", () => {
    for (const sheet of [
      createStructureAwareSuggestionSheet(),
      createRecordedSuggestionSheet(),
      createFactorVariantYearSuggestionSheet(),
    ]) {
      const reversed = {
        ...sheet,
        cells: [...sheet.cells].reverse(),
        merges: [...sheet.merges].reverse(),
      };
      const first = JSON.stringify(detectCandidateBlocks(sheet));

      expect(JSON.stringify(detectCandidateBlocks(sheet))).toBe(first);
      expect(JSON.stringify(detectCandidateBlocks(reversed))).toBe(first);
    }
  });

  it("uses total row-major tie-breaking and keeps the transported cap bounded", () => {
    const cells = Array.from({ length: 24 }, (_, index) =>
      createCell("Sparse", index * 2 + 1, 1, index, "numeric"),
    );
    const candidates = detectCandidateBlocks(
      fixtureSheet("Sparse", "R1C1:R47C1", cells),
    );

    expect(candidates).toHaveLength(MAX_CANDIDATE_BLOCKS);
    expect(candidates.map(({ cellCount }) => cellCount)).toEqual(
      Array(MAX_CANDIDATE_BLOCKS).fill(1),
    );
    expect(candidates.map(({ range }) => range)).toEqual(
      Array.from(
        { length: MAX_CANDIDATE_BLOCKS },
        (_, index) => `R${index * 2 + 1}C1:R${index * 2 + 1}C1`,
      ),
    );
  });

  it("bounds detection to the same capped preview extent as the Source grid", () => {
    const cells = Array.from({ length: 305 }, (_, index) =>
      createCell("Tall", index + 1, 1, 10_000 + index, "numeric"),
    );

    expect(
      detectCandidateBlocks(fixtureSheet("Tall", "R1C1:R305C1", cells))[0],
    ).toMatchObject({ range: "R1C1:R300C1", cellCount: 300 });
  });
});

function styledCell(
  cell: TidyCell,
  style: NonNullable<TidyCell["style"]>,
): TidyCell {
  return { ...cell, style };
}

function expectNoIncompatibleRoleOverlaps(
  blocks: ReturnType<typeof detectCandidateBlocks>,
): void {
  const rolesByAddress = new Map<string, Set<string>>();
  for (const block of blocks) {
    for (const range of block.ranges) {
      for (const address of expandRange(range)) {
        const roles = rolesByAddress.get(address) ?? new Set<string>();
        roles.add(block.suggestedRole);
        rolesByAddress.set(address, roles);
      }
    }
  }
  expect(
    [...rolesByAddress.entries()].filter(([, roles]) => roles.size > 1),
  ).toEqual([]);
}

function fixtureSheet(
  name: string,
  usedRange: string,
  cells: TidyCell[],
  merges: ParsedSheet["merges"] = [],
): ParsedSheet {
  const range = parseRange(usedRange);
  return {
    name,
    usedRange,
    rowCount: range.end.row,
    columnCount: range.end.col,
    nonEmptyCellCount: cells.filter((cell) => cell.data_type !== "blank")
      .length,
    cells,
    merges,
  };
}
