// @vitest-environment node

import { describe, expect, it } from "vitest";
import type { ParsedSheet } from "../../../src/lib/workbook/types";
import {
  buildCompactContextSnapshot,
  parseCompactContext,
  type CompactSemanticContext,
} from "./compact-context";
import { buildSemanticCellFormattingFacts } from "./format-aware-region-catalog-v2";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
  buildYearLikeCellFacts,
  compileRoleAwareSemanticTableMap,
  correctionCandidateSubset,
  inspectSemanticMapCompleteness,
  isNumericYearLike,
  renderRoleAwareSemanticRegionCatalog,
  type RoleAwareSemanticRegionCandidate,
  type RoleAwareSemanticRegionCatalog,
} from "./role-aware-region-catalog-v5";
import type { SemanticTableMapV1 } from "./semantic-map-v1";

function repeatedPanelSheet(): ParsedSheet {
  const cells: ParsedSheet["cells"] = [];
  const add = (
    address: string,
    row: number,
    col: number,
    value: string | number,
    style?: ParsedSheet["cells"][number]["style"],
  ) =>
    cells.push({
      sheet: "Sheet 1",
      address,
      row,
      col,
      value,
      data_type: typeof value === "number" ? "numeric" : "string",
      ...(style ? { style } : {}),
    });
  add("R1C2", 1, 2, "Year 2024", { bold: true });
  add("R2C2", 2, 2, "January", { bold: true });
  add("R2C3", 2, 3, "February", { bold: true });
  add("R3C1", 3, 1, "Males", { bold: true });
  add("R4C1", 4, 1, "18–24", { italic: true, fontIndent: 1 });
  add("R4C2", 4, 2, 10);
  add("R4C3", 4, 3, 11);
  add("R5C1", 5, 1, "25–34", { italic: true, fontIndent: 1 });
  add("R5C2", 5, 2, 12);
  add("R5C3", 5, 3, 13);
  add("R7C1", 7, 1, "Females", { bold: true });
  add("R8C1", 8, 1, "18–24", { italic: true, fontIndent: 1 });
  add("R8C2", 8, 2, 14);
  add("R8C3", 8, 3, 15);
  add("R9C1", 9, 1, "25–34", { italic: true, fontIndent: 1 });
  add("R9C2", 9, 2, 16);
  add("R9C3", 9, 3, 17);
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R9C3",
    rowCount: 9,
    columnCount: 3,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [{ parent: "R1C2", range: "R1C2:R1C3" }],
  };
}

function numericHeaderSheet({
  bold = true,
}: { bold?: boolean } = {}): ParsedSheet {
  const cells: ParsedSheet["cells"] = [
    {
      sheet: "Sheet 1",
      address: "R1C2",
      row: 1,
      col: 2,
      value: 2023,
      data_type: "numeric",
      style: { ...(bold ? { bold: true } : {}), horizontalAlign: "right" },
    },
    {
      sheet: "Sheet 1",
      address: "R1C3",
      row: 1,
      col: 3,
      value: 2024,
      data_type: "numeric",
      style: { ...(bold ? { bold: true } : {}), horizontalAlign: "right" },
    },
    {
      sheet: "Sheet 1",
      address: "R2C1",
      row: 2,
      col: 1,
      value: "A",
      data_type: "string",
    },
    {
      sheet: "Sheet 1",
      address: "R2C2",
      row: 2,
      col: 2,
      value: 10,
      data_type: "numeric",
    },
    {
      sheet: "Sheet 1",
      address: "R2C3",
      row: 2,
      col: 3,
      value: 11,
      data_type: "numeric",
    },
    {
      sheet: "Sheet 1",
      address: "R3C1",
      row: 3,
      col: 1,
      value: "B",
      data_type: "string",
    },
    {
      sheet: "Sheet 1",
      address: "R3C2",
      row: 3,
      col: 2,
      value: 12,
      data_type: "numeric",
    },
    {
      sheet: "Sheet 1",
      address: "R3C3",
      row: 3,
      col: 3,
      value: 13,
      data_type: "numeric",
    },
  ];
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R3C3",
    rowCount: 3,
    columnCount: 3,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

function verticalYearSheet(): ParsedSheet {
  const years = [2021, 2022, 2023];
  const cells: ParsedSheet["cells"] = years.flatMap((year, index) => [
    {
      sheet: "Sheet 1",
      address: `R${index + 1}C1`,
      row: index + 1,
      col: 1,
      value: year,
      data_type: "numeric" as const,
    },
    {
      sheet: "Sheet 1",
      address: `R${index + 1}C2`,
      row: index + 1,
      col: 2,
      value: 10 + index,
      data_type: "numeric" as const,
    },
  ]);
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R3C2",
    rowCount: 3,
    columnCount: 2,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

function separatedYearRunsSheet(): ParsedSheet {
  const cells: ParsedSheet["cells"] = [];
  for (const [column, year] of [
    [1, 1999],
    [2, 2000],
    [4, 2001],
    [5, 2002],
  ] as const) {
    cells.push({
      sheet: "Sheet 1",
      address: `R1C${column}`,
      row: 1,
      col: column,
      value: year,
      data_type: "numeric",
    });
    cells.push({
      sheet: "Sheet 1",
      address: `R2C${column}`,
      row: 2,
      col: column,
      value: column * 10,
      data_type: "numeric",
    });
  }
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R2C5",
    rowCount: 2,
    columnCount: 5,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

function setup() {
  const sheet = repeatedPanelSheet();
  const snapshot = buildCompactContextSnapshot(sheet);
  const context = parseCompactContext(snapshot.serialized);
  const catalog = buildRoleAwareSemanticRegionCatalog(context, {
    formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
    cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
  });
  return { context, catalog };
}

function candidate(
  catalog: RoleAwareSemanticRegionCatalog,
  kind: string,
): RoleAwareSemanticRegionCandidate {
  const result = catalog.candidates.find((entry) => entry.kinds.includes(kind));
  if (!result) throw new Error(`Missing candidate kind ${kind}`);
  return result;
}

describe("role-aware semantic region catalog v5", () => {
  it("offers repeated values, formatted direct labels, and cascading anchors as compact groups", () => {
    const { catalog } = setup();
    const values = candidate(catalog, "all-observation-panels");
    const rowLabels = catalog.candidates.find(
      (entry) =>
        entry.kinds.includes("direct-row-projection-group") &&
        entry.formatSignatures.includes("i|in1"),
    );
    const groupLabels = candidate(catalog, "preceding-panel-anchor-group");

    expect(values.segments).toEqual(["R4C2:R5C3", "R8C2:R9C3"]);
    expect(rowLabels).toMatchObject({
      segments: ["R4C1:R5C1", "R8C1:R9C1"],
      formatting: ["italic,indent=1"],
      roleHints: ["direct-row-candidate"],
    });
    expect(groupLabels.segments).toEqual(["R3C1:R3C1", "R7C1:R7C1"]);
    expect(renderRoleAwareSemanticRegionCatalog(catalog)).toContain(
      "use=direct-row-candidate",
    );
  });

  it("offers a bold numeric leading row as a header and preserves both observation alternatives", () => {
    const sheet = numericHeaderSheet();
    const snapshot = buildCompactContextSnapshot(sheet);
    const context = parseCompactContext(snapshot.serialized);
    const catalog = buildRoleAwareSemanticRegionCatalog(context, {
      formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
      cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
    });
    const trimmed = candidate(
      catalog,
      "observation-panel-trimmed-leading-header",
    );
    const header = candidate(catalog, "leading-formatted-header-row");
    const original = candidate(catalog, "observation-panel");

    expect(trimmed.segments).toEqual(["R2C2:R3C3"]);
    expect(trimmed.roleHints).toContain("observations");
    expect(header).toMatchObject({
      segments: ["R1C2:R1C3"],
      roleHints: ["direct-column-candidate"],
      formatting: expect.arrayContaining([expect.stringContaining("bold")]),
    });
    expect(original.segments).toEqual(["R1C2:R3C3"]);
  });

  it("recognizes only integer numeric years in the configured 1900–2099 window", () => {
    expect(isNumericYearLike(1900, "numeric")).toBe(true);
    expect(isNumericYearLike(2099, "numeric")).toBe(true);
    expect(isNumericYearLike(1899, "numeric")).toBe(false);
    expect(isNumericYearLike(2100, "numeric")).toBe(false);
    expect(isNumericYearLike(2024.5, "numeric")).toBe(false);
    expect(isNumericYearLike("2024", "string")).toBe(false);
    expect(isNumericYearLike(2024, "string")).toBe(false);
  });

  it("uses horizontal year adjacency even without bold formatting", () => {
    const sheet = numericHeaderSheet({ bold: false });
    const snapshot = buildCompactContextSnapshot(sheet);
    const context = parseCompactContext(snapshot.serialized);
    const dataFacts = buildSemanticCellDataFacts(sheet.cells);
    const catalog = buildRoleAwareSemanticRegionCatalog(context, {
      formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
      cellDataFacts: dataFacts,
    });
    const trimmed = candidate(
      catalog,
      "observation-panel-trimmed-leading-year-row",
    );
    const years = candidate(catalog, "adjacent-year-like-horizontal-run");
    const facts = buildYearLikeCellFacts(context, dataFacts);

    expect(trimmed.segments).toEqual(["R2C2:R3C3"]);
    expect(years).toMatchObject({
      segments: ["R1C2:R1C3"],
      roleHints: ["direct-column-candidate"],
    });
    expect(facts.find((fact) => fact.address === "R1C2")).toMatchObject({
      value: 2023,
      horizontalYearLikeNeighbors: ["R1C3"],
      verticalYearLikeNeighbors: [],
    });
    expect(
      catalog.candidates.some((entry) =>
        entry.kinds.includes("leading-formatted-header-row"),
      ),
    ).toBe(false);
  });

  it("records but does not promote an isolated in-range number", () => {
    const sheet = numericHeaderSheet({ bold: false });
    const neighbor = sheet.cells.find((cell) => cell.address === "R1C3");
    expect(neighbor).toBeDefined();
    neighbor!.value = 24;
    const snapshot = buildCompactContextSnapshot(sheet);
    const context = parseCompactContext(snapshot.serialized);
    const dataFacts = buildSemanticCellDataFacts(sheet.cells);
    const catalog = buildRoleAwareSemanticRegionCatalog(context, {
      formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
      cellDataFacts: dataFacts,
    });
    const fact = buildYearLikeCellFacts(context, dataFacts).find(
      (entry) => entry.address === "R1C2",
    );

    expect(fact).toMatchObject({
      value: 2023,
      horizontalYearLikeNeighbors: [],
      verticalYearLikeNeighbors: [],
    });
    expect(
      catalog.candidates.some((entry) =>
        entry.kinds.some((kind) => kind.includes("year")),
      ),
    ).toBe(false);
  });

  it("uses vertical year adjacency as direct-row evidence", () => {
    const sheet = verticalYearSheet();
    const snapshot = buildCompactContextSnapshot(sheet);
    const context = parseCompactContext(snapshot.serialized);
    const dataFacts = buildSemanticCellDataFacts(sheet.cells);
    const catalog = buildRoleAwareSemanticRegionCatalog(context, {
      formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
      cellDataFacts: dataFacts,
    });
    const trimmed = candidate(
      catalog,
      "observation-panel-trimmed-leading-year-column",
    );
    const years = candidate(catalog, "adjacent-year-like-vertical-run");
    const facts = buildYearLikeCellFacts(context, dataFacts);

    expect(trimmed.segments).toEqual(["R1C2:R3C2"]);
    expect(years).toMatchObject({
      segments: ["R1C1:R3C1"],
      roleHints: expect.arrayContaining(["direct-row-candidate"]),
    });
    expect(facts.find((fact) => fact.address === "R2C1")).toMatchObject({
      value: 2022,
      horizontalYearLikeNeighbors: [],
      verticalYearLikeNeighbors: ["R1C1", "R3C1"],
    });
  });

  it("keeps separated adjacent year runs local instead of combining them globally", () => {
    const sheet = separatedYearRunsSheet();
    const snapshot = buildCompactContextSnapshot(sheet);
    const context = parseCompactContext(snapshot.serialized);
    const catalog = buildRoleAwareSemanticRegionCatalog(context, {
      formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
      cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
    });
    const runs = catalog.candidates
      .filter((entry) =>
        entry.kinds.includes("adjacent-year-like-horizontal-run"),
      )
      .map((entry) => entry.segments);

    expect(runs).toEqual(
      expect.arrayContaining([["R1C1:R1C2"], ["R1C4:R1C5"]]),
    );
    expect(runs).toHaveLength(2);
  });

  it("represents a merged heading by its semantic anchor rather than blank span cells", () => {
    const { catalog } = setup();
    const merged = candidate(catalog, "merged-header-anchor");

    expect(merged.segments).toEqual(["R1C2:R1C2"]);
    expect(merged.selectedCellCount).toBe(1);
    expect(merged.sample).toEqual(['R1C2="Year 2024"']);
  });

  it("compiles repeated groups through the existing in-memory sketch and compiler", () => {
    const { context, catalog } = setup();
    const values = candidate(catalog, "all-observation-panels");
    const rowLabels = candidate(catalog, "direct-row-projection-group");
    const months = catalog.candidates.find(
      (entry) =>
        entry.roleHints.includes("direct-column-candidate") &&
        entry.sample.some((sample) => sample.includes("January")),
    );
    expect(months).toBeDefined();
    const map: SemanticTableMapV1 = {
      version: "semantic-table-map-v1",
      table: {
        name: "Counts",
        values: { name: "Count", regions: [values.id] },
        dimensions: [
          {
            name: "Age",
            memberRegions: [rowLabels.id],
            direction: "W",
          },
          {
            name: "Month",
            memberRegions: [months!.id],
            direction: "N",
          },
        ],
      },
    };

    const result = compileRoleAwareSemanticTableMap({ map, catalog, context });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.recipe.tables).toHaveLength(1);
    expect(result.recipe.tables[0].headers).toHaveLength(2);
    expect(result.canonicalSketchJson).toContain('"version": "0.2"');
  });

  it("reports structurally adjacent direct groups omitted by a valid-looking map", () => {
    const { catalog } = setup();
    const values = candidate(catalog, "all-observation-panels");
    const rowLabels = candidate(catalog, "direct-row-projection-group");
    const map: SemanticTableMapV1 = {
      version: "semantic-table-map-v1",
      table: {
        name: "Counts",
        values: { name: "Count", regions: [values.id] },
        dimensions: [
          {
            name: "Age",
            memberRegions: [rowLabels.id],
            direction: "W",
          },
        ],
      },
    };

    const diagnostics = inspectSemanticMapCompleteness({ map, catalog });
    expect(diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: "UNASSIGNED_DIRECT_HEADER_GROUP",
          roleHint: "direct-column-candidate",
        }),
      ]),
    );
    const subset = correctionCandidateSubset({
      catalog,
      map,
      completenessDiagnostics: diagnostics,
      maxCandidates: 12,
    });
    expect(subset.candidates.length).toBeLessThanOrEqual(12);
    expect(
      diagnostics.every((diagnostic) =>
        subset.candidates.some((entry) => entry.id === diagnostic.candidateId),
      ),
    ).toBe(true);
  });

  it("reports an omitted cascading group without assigning its semantics", () => {
    const { catalog } = setup();
    const values = candidate(catalog, "all-observation-panels");
    const rowLabels = candidate(catalog, "direct-row-projection-group");
    const months = catalog.candidates.find(
      (entry) =>
        entry.roleHints.includes("direct-column-candidate") &&
        entry.sample.some((sample) => sample.includes("January")),
    );
    const groupLabels = candidate(catalog, "preceding-panel-anchor-group");
    expect(months).toBeDefined();
    const map: SemanticTableMapV1 = {
      version: "semantic-table-map-v1",
      table: {
        name: "Counts",
        values: { name: "Count", regions: [values.id] },
        dimensions: [
          {
            name: "Age",
            memberRegions: [rowLabels.id],
            direction: "W",
          },
          {
            name: "Month",
            memberRegions: [months!.id],
            direction: "N",
          },
        ],
      },
    };

    const diagnostics = inspectSemanticMapCompleteness({ map, catalog });
    expect(diagnostics).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: "UNASSIGNED_CASCADING_HEADER_GROUP",
          candidateId: groupLabels.id,
          roleHint: "cascading-row-candidate",
        }),
      ]),
    );
  });

  it("does not treat a repeated uniform separator as a cascading coordinate", () => {
    const { catalog } = setup();
    const values = candidate(catalog, "all-observation-panels");
    const rowLabels = candidate(catalog, "direct-row-projection-group");
    const groupLabels = candidate(catalog, "preceding-panel-anchor-group");
    const uniformCatalog: RoleAwareSemanticRegionCatalog = {
      ...catalog,
      candidates: catalog.candidates.map((entry) =>
        entry.id === groupLabels.id
          ? {
              ...entry,
              sample: ['R3C1="Total"', 'R7C1="Total"'],
            }
          : entry,
      ),
    };
    const map: SemanticTableMapV1 = {
      version: "semantic-table-map-v1",
      table: {
        name: "Counts",
        values: { name: "Count", regions: [values.id] },
        dimensions: [
          {
            name: "Age",
            memberRegions: [rowLabels.id],
            direction: "W",
          },
        ],
      },
    };

    const diagnostics = inspectSemanticMapCompleteness({
      map,
      catalog: uniformCatalog,
    });
    expect(
      diagnostics.some(
        (diagnostic) => diagnostic.candidateId === groupLabels.id,
      ),
    ).toBe(false);
  });

  it("treats a reasoning-only caption hint as an accounted-for structural group", () => {
    const { catalog } = setup();
    const values = candidate(catalog, "all-observation-panels");
    const rowLabels = candidate(catalog, "direct-row-projection-group");
    const columnCaption = catalog.candidates.find((entry) =>
      entry.roleHints.includes("direct-column-candidate"),
    );
    const cascadingCaption = candidate(catalog, "preceding-panel-anchor-group");
    expect(columnCaption).toBeDefined();
    const map: SemanticTableMapV1 = {
      version: "semantic-table-map-v1",
      table: {
        name: "Counts",
        values: { name: "Count", regions: [values.id] },
        dimensions: [
          {
            name: "Age",
            memberRegions: [rowLabels.id],
            direction: "W",
            captionHints: [columnCaption!.id, cascadingCaption.id],
          },
        ],
      },
    };

    const diagnostics = inspectSemanticMapCompleteness({ map, catalog });
    expect(
      diagnostics.some((diagnostic) =>
        [columnCaption!.id, cascadingCaption.id].includes(
          diagnostic.candidateId,
        ),
      ),
    ).toBe(false);
  });

  it("bypasses the XML node limit for a large deterministic disjoint union", () => {
    const rows = 26;
    const columns = 400;
    const grid = Array.from({ length: rows }, (_, rowIndex) => ({
      range: `R${rowIndex + 1}C1:R${rowIndex + 1}C${columns}`,
      values: Array.from({ length: columns }, (_, columnIndex) => {
        if (rowIndex === 0) return `Header ${columnIndex + 1}`;
        return columnIndex % 2 === 0 ? rowIndex * columns + columnIndex : null;
      }),
    }));
    const context: CompactSemanticContext = {
      schemaVersion: "cell-role-compact-context-v1",
      sheet: "Sheet 1",
      dimensions: { rows, columns },
      usedRange: `R1C1:R${rows}C${columns}`,
      merges: [],
      blankBands: { rows: [], columns: [] },
      styleBoundaries: [],
      grid: { encoding: "row-major-r1c1-json-v1", rows: grid },
    };
    const valueSegments: string[] = [];
    for (let row = 2; row <= rows; row += 1) {
      for (let column = 1; column <= columns; column += 2) {
        valueSegments.push(`R${row}C${column}:R${row}C${column}`);
      }
    }
    expect(valueSegments).toHaveLength(5_000);
    const catalog: RoleAwareSemanticRegionCatalog = {
      version: "semantic-region-catalog-v5-adjacent-year-aware",
      sheet: "Sheet 1",
      omittedCandidateCount: 0,
      observationPanelCount: valueSegments.length,
      formatFactCount: 0,
      cellDataFactCount: 0,
      candidates: [
        manualCandidate("region-001", valueSegments, "observations"),
        manualCandidate(
          "region-002",
          Array.from({ length: columns / 2 }, (_, index) => {
            const column = index * 2 + 1;
            return `R1C${column}:R1C${column}`;
          }),
          "direct-column-candidate",
        ),
      ],
    };
    const map: SemanticTableMapV1 = {
      version: "semantic-table-map-v1",
      table: {
        name: "Large",
        values: { name: "Value", regions: ["region-001"] },
        dimensions: [
          {
            name: "Column",
            memberRegions: ["region-002"],
            direction: "N",
          },
        ],
      },
    };

    const result = compileRoleAwareSemanticTableMap({ map, catalog, context });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.normalizations.values).toMatchObject({
      selectedCellCount: 5_000,
      representation: "addresses",
    });
    expect(result.recipe.tables[0].values.cells).toMatchObject({
      cells: expect.any(Array),
    });
  });
});

function manualCandidate(
  id: string,
  segments: string[],
  roleHint: RoleAwareSemanticRegionCandidate["roleHints"][number],
): RoleAwareSemanticRegionCandidate {
  const selectedCellCount = segments.reduce((sum, segment) => {
    const match = /^R(\d+)C(\d+):R(\d+)C(\d+)$/.exec(segment)!;
    return (
      sum +
      (Number(match[3]) - Number(match[1]) + 1) *
        (Number(match[4]) - Number(match[2]) + 1)
    );
  }, 0);
  return {
    id,
    segments,
    kinds: ["manual-test"],
    roleHints: [roleHint],
    formatSignatures: [],
    formatting: [],
    selectedCellCount,
    nonblankCount: selectedCellCount,
    valueLikeCount: roleHint === "observations" ? selectedCellCount : 0,
    sample: [],
  };
}
