/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
// @vitest-environment node

import { describe, expect, it } from "vitest";
import type { ParsedSheet } from "../src/workbook/types.js";
import {
  buildCompactContextSnapshot,
  parseCompactContext,
  type CompactSemanticContext,
} from "../src/context/compactContext.js";
import { buildSemanticCellFormattingFacts } from "../src/catalog/format-aware-region-catalog-v2.js";
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
} from "../src/catalog/role-aware-region-catalog-v5.js";
import type { SemanticTableMapV1 } from "../src/catalog/semantic-map-v1.js";

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

function terminalMarkerSheet({
  includeCorroboratingMarkers = true,
  includeTerminalMarkers = true,
  detachedCorroboratingMarkers = false,
  markerValue = "np",
  terminalStyleMismatch = false,
  terminalLabel = "string",
  mergeTerminalMarker = false,
}: {
  includeCorroboratingMarkers?: boolean;
  includeTerminalMarkers?: boolean;
  detachedCorroboratingMarkers?: boolean;
  markerValue?: ".." | "na" | "np";
  terminalStyleMismatch?: boolean;
  terminalLabel?: "string" | "blank" | "numeric" | "marker";
  mergeTerminalMarker?: boolean;
} = {}): ParsedSheet {
  const cells: ParsedSheet["cells"] = [];
  const markerStyle = { horizontalAlign: "right", fillColor: "FFF2CC" };
  const mismatchedMarkerStyle = {
    horizontalAlign: "right",
    fillColor: "DDEBF7",
  };
  const add = (
    row: number,
    col: number,
    value: string | number,
    style?: ParsedSheet["cells"][number]["style"],
  ) =>
    cells.push({
      sheet: "Sheet 1",
      address: `R${row}C${col}`,
      row,
      col,
      value,
      data_type: typeof value === "number" ? "numeric" : "string",
      ...(style ? { style } : {}),
    });
  const addNumericPanel = (row1: number, row2: number) => {
    for (let row = row1; row <= row2; row += 1) {
      add(row, 1, `Outcome ${row}`);
      for (let col = 2; col <= 7; col += 1) add(row, col, row * 10 + col);
    }
  };
  const addMarkerRow = (
    row: number,
    style = markerStyle,
    label: string | number = `Published marker outcome ${row}`,
  ) => {
    add(row, 1, label);
    for (let col = 2; col <= 7; col += 1) {
      add(row, col, markerValue, style);
    }
  };

  addNumericPanel(19, 26);
  if (includeCorroboratingMarkers) {
    addMarkerRow(27);
    addMarkerRow(28);
  }
  if (detachedCorroboratingMarkers) {
    addMarkerRow(35);
    addMarkerRow(36);
  }
  addNumericPanel(42, 49);
  // Keep valid row labels in the baseline context so appending values cannot
  // change established format/header candidates.
  for (const row of [50, 51]) {
    if (terminalLabel === "string") {
      add(row, 1, `Published marker outcome ${row}`);
    } else if (terminalLabel === "numeric") {
      add(row, 1, row);
    } else if (terminalLabel === "marker") {
      add(row, 1, markerValue);
    }
  }
  if (includeTerminalMarkers) {
    const terminalStyle = terminalStyleMismatch
      ? mismatchedMarkerStyle
      : markerStyle;
    for (let col = 2; col <= 7; col += 1) {
      add(50, col, markerValue, terminalStyle);
      add(51, col, markerValue, terminalStyle);
    }
  }
  add(52, 1, "Footnote np is descriptive text");
  add(52, 2, markerValue, markerStyle);
  add(53, 1, markerValue, markerStyle);

  return {
    name: "Sheet 1",
    usedRange: "R1C1:R53C7",
    rowCount: 53,
    columnCount: 7,
    nonEmptyCellCount: cells.length,
    cells,
    merges: mergeTerminalMarker
      ? [{ parent: "R50C2", range: "R50C2:R50C3" }]
      : [],
  };
}

function multipleTerminalMarkerSheet(
  includeTerminalMarkers = true,
): ParsedSheet {
  const cells: ParsedSheet["cells"] = [];
  const markerStyle = { horizontalAlign: "right", fillColor: "FFF2CC" };
  const add = (row: number, col: number, value: string | number) =>
    cells.push({
      sheet: "Sheet 1",
      address: `R${row}C${col}`,
      row,
      col,
      value,
      data_type: typeof value === "number" ? "numeric" : "string",
      ...(typeof value === "string" && ["..", "na", "np"].includes(value)
        ? { style: markerStyle }
        : {}),
    });
  const addPanelRow = (row: number) => {
    add(row, 1, `Left outcome ${row}`);
    add(row, 2, row * 10 + 2);
    add(row, 3, row * 10 + 3);
    add(row, 4, `Right outcome ${row}`);
    add(row, 5, row * 10 + 5);
    add(row, 6, row * 10 + 6);
  };
  const addMarkerRow = (row: number) => {
    add(row, 1, `Left marker ${row}`);
    add(row, 2, "np");
    add(row, 3, "np");
    add(row, 4, `Right marker ${row}`);
    add(row, 5, "np");
    add(row, 6, "np");
  };
  for (let row = 10; row <= 12; row += 1) addPanelRow(row);
  addMarkerRow(13);
  addMarkerRow(14);
  for (let row = 20; row <= 22; row += 1) addPanelRow(row);
  add(23, 1, "Left marker 23");
  add(23, 4, "Right marker 23");
  add(24, 1, "Left marker 24");
  add(24, 4, "Right marker 24");
  if (includeTerminalMarkers) {
    for (const row of [23, 24]) {
      for (const col of [2, 3, 5, 6]) add(row, col, "np");
    }
  }
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R24C6",
    rowCount: 24,
    columnCount: 6,
    nonEmptyCellCount: cells.length,
    cells,
    merges: [],
  };
}

function catalogFor(
  sheet: ParsedSheet,
  maxCandidates?: number,
): RoleAwareSemanticRegionCatalog {
  const snapshot = buildCompactContextSnapshot(sheet);
  const context = parseCompactContext(snapshot.serialized);
  return buildRoleAwareSemanticRegionCatalog(context, {
    formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
    cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
    ...(maxCandidates === undefined ? {} : { maxCandidates }),
  });
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

  it.each(["np", "..", "na"] as const)(
    "appends an exact terminal %s run without renumbering established regions",
    (markerValue) => {
      const baseline = catalogFor(
        terminalMarkerSheet({
          includeTerminalMarkers: false,
          markerValue,
        }),
      );
      const catalog = catalogFor(terminalMarkerSheet({ markerValue }));
      const marker = candidate(catalog, "terminal-repeated-marker-run");

      expect(marker).toMatchObject({
        id: `region-${String(baseline.candidates.length + 1).padStart(3, "0")}`,
        segments: ["R50C2:R51C7"],
        roleHints: ["observations"],
        selectedCellCount: 12,
        nonblankCount: 12,
        valueLikeCount: 12,
      });
      expect(marker.sample[0]).toBe(`R50C2=${JSON.stringify(markerValue)}`);
      expect(catalog.candidates.slice(0, baseline.candidates.length)).toEqual(
        baseline.candidates,
      );
      expect(marker.segments).not.toContain("R52C2:R52C2");
      expect(marker.segments).not.toContain("R53C1:R53C1");
    },
  );

  it("does not use a detached marker run to corroborate terminal markers", () => {
    const catalog = catalogFor(
      terminalMarkerSheet({
        includeCorroboratingMarkers: false,
        detachedCorroboratingMarkers: true,
      }),
    );

    expect(
      catalog.candidates.some((entry) =>
        entry.kinds.includes("terminal-repeated-marker-run"),
      ),
    ).toBe(false);
  });

  it("rejects a terminal marker run whose per-column style vector differs", () => {
    const catalog = catalogFor(
      terminalMarkerSheet({ terminalStyleMismatch: true }),
    );

    expect(
      catalog.candidates.some((entry) =>
        entry.kinds.includes("terminal-repeated-marker-run"),
      ),
    ).toBe(false);
  });

  it.each(["blank", "numeric", "marker"] as const)(
    "rejects a terminal marker run with a %s row label",
    (terminalLabel) => {
      const catalog = catalogFor(terminalMarkerSheet({ terminalLabel }));

      expect(
        catalog.candidates.some((entry) =>
          entry.kinds.includes("terminal-repeated-marker-run"),
        ),
      ).toBe(false);
    },
  );

  it("rejects a terminal run containing a merged marker cell", () => {
    const catalog = catalogFor(
      terminalMarkerSheet({ mergeTerminalMarker: true }),
    );

    expect(
      catalog.candidates.some((entry) =>
        entry.kinds.includes("terminal-repeated-marker-run"),
      ),
    ).toBe(false);
  });

  it("appends multiple terminal candidates deterministically and truncates only appended candidates", () => {
    const baseline = catalogFor(multipleTerminalMarkerSheet(false));
    const catalog = catalogFor(multipleTerminalMarkerSheet());
    const markers = catalog.candidates.filter((entry) =>
      entry.kinds.includes("terminal-repeated-marker-run"),
    );

    expect(markers.map((entry) => entry.segments)).toEqual([
      ["R23C2:R24C3"],
      ["R23C5:R24C6"],
    ]);
    expect(markers.map((entry) => entry.id)).toEqual([
      `region-${String(baseline.candidates.length + 1).padStart(3, "0")}`,
      `region-${String(baseline.candidates.length + 2).padStart(3, "0")}`,
    ]);
    expect(catalog.candidates.slice(0, baseline.candidates.length)).toEqual(
      baseline.candidates,
    );

    const limited = catalogFor(
      multipleTerminalMarkerSheet(),
      baseline.candidates.length + 1,
    );
    const limitedMarkers = limited.candidates.filter((entry) =>
      entry.kinds.includes("terminal-repeated-marker-run"),
    );
    expect(limitedMarkers).toEqual([markers[0]]);
    expect(limited.omittedCandidateCount).toBeGreaterThanOrEqual(1);
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
