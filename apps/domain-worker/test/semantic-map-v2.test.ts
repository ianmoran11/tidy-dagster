// @vitest-environment node
import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import * as addressModule from "../src/address.js";

vi.mock("../src/address.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/address.js")>();
  return { ...actual, expandRange: vi.fn(actual.expandRange) };
});
import type { CompactSemanticContext } from "../src/context/compactContext.js";
import type { ParsedSheet, TidyCell } from "../src/workbook/types.js";
import { executeRecipe } from "../src/executor/executeRecipe.js";
import {
  compileSemanticTableMap,
  type SemanticRegionCatalog,
  type SemanticTableMapV1,
} from "../src/catalog/semantic-map-v1.js";
import {
  compileAtomicSemanticTableMapV2,
  digestAtomicCompilationEnvelopeV2,
  digestAtomicRegionCatalog,
  MAX_ATOMIC_MAP_V2_CATALOG_JSON_BYTES,
  MAX_ATOMIC_MAP_V2_CATALOG_JSON_NODES,
  MAX_ATOMIC_MAP_V2_JSON_BYTES,
  MAX_ATOMIC_MAP_V2_JSON_NODES,
  MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE,
  MAX_ATOMIC_MAP_V2_TOTAL_SELECTORS,
  executeAtomicSemanticTableMapV2,
  logicalOutputNameV2Schema,
  parseSemanticTableMapV2Json,
  reconstituteAtomicSemanticExecutionV2,
  type AtomicCompilationEnvelopeV2,
  type AtomicRegionCatalog,
  type SemanticTableMapV2,
} from "../src/catalog/semantic-map-v2.js";

function compactContext(
  rows: Array<Array<string | number | boolean | null>>,
): CompactSemanticContext {
  const columns = Math.max(...rows.map((row) => row.length));
  const padded = rows.map((row) => [
    ...row,
    ...Array.from({ length: columns - row.length }, () => null),
  ]);
  return {
    schemaVersion: "cell-role-compact-context-v1",
    sheet: "Sheet 1",
    dimensions: { rows: padded.length, columns },
    usedRange: `R1C1:R${padded.length}C${columns}`,
    merges: [],
    blankBands: { rows: [], columns: [] },
    styleBoundaries: [],
    grid: {
      encoding: "row-major-r1c1-json-v1",
      rows: padded.map((values, index) => ({
        range: `R${index + 1}C1:R${index + 1}C${columns}`,
        values,
      })),
    },
  };
}

const sheetContext = compactContext([
  [null, "2023", "2024"],
  ["A", 1, 2],
  ["B", 3, 4],
  [null, null, null],
  [null, "2023", "2024"],
  ["C", 5, 6],
  ["D", 7, 8],
]);

function parsedSheet(context = sheetContext): ParsedSheet {
  const cells: TidyCell[] = context.grid.rows.flatMap((row, rowIndex) =>
    row.values.map((value, columnIndex) => ({
      sheet: context.sheet,
      address: `R${rowIndex + 1}C${columnIndex + 1}`,
      row: rowIndex + 1,
      col: columnIndex + 1,
      value,
      data_type:
        value === null
          ? "blank"
          : typeof value === "number"
            ? "numeric"
            : typeof value === "boolean"
              ? "boolean"
              : "string",
    })),
  );
  return {
    name: context.sheet,
    usedRange: context.usedRange,
    rowCount: context.dimensions.rows,
    columnCount: context.dimensions.columns,
    nonEmptyCellCount: cells.filter((cell) => cell.value !== null).length,
    cells,
    merges: [],
  };
}

function atomicCatalog(): AtomicRegionCatalog {
  const candidate = (id: string, segments: string[], kinds: string[]) => ({
    id,
    segments,
    kinds,
    roleHints: [],
    formatSignatures: [],
    formatting: [],
    selectedCellCount: segments.length,
    nonblankCount: segments.length,
    valueLikeCount: kinds.includes("observations") ? segments.length : 0,
    sample: [],
  });
  return {
    version: "semantic-region-catalog-v5-adjacent-year-aware",
    sheet: "Sheet 1",
    candidates: [
      candidate("all-values", ["R2C2:R3C3", "R6C2:R7C3"], ["observations"]),
      candidate("year-headers", ["R1C2:R1C3", "R5C2:R5C3"], ["headers"]),
      candidate("category-headers", ["R2C1:R3C1", "R6C1:R7C1"], ["headers"]),
    ],
    omittedCandidateCount: 0,
    observationPanelCount: 2,
    formatFactCount: 0,
    cellDataFactCount: 0,
  };
}

function subset(regionId: string, range: string) {
  return [{ regionId, selectors: [{ range }] }];
}

function atomicMap(catalog = atomicCatalog()): SemanticTableMapV2 {
  return {
    version: "semantic-table-map-v2",
    catalog: {
      version: catalog.version,
      digest: digestAtomicRegionCatalog(catalog),
    },
    logicalTable: {
      id: "observations",
      name: "Observations",
      values: {
        id: "published-value",
        name: "published value",
        target: [
          {
            regionId: "all-values",
            selectors: [{ range: "R2C2:R3C3" }, { range: "R6C2:R7C3" }],
          },
        ],
      },
      dimensions: [
        { id: "year", name: "year" },
        { id: "category", name: "category" },
      ],
    },
    panels: [
      {
        id: "panel-one",
        order: 1,
        tableName: "Observations panel one",
        target: subset("all-values", "R2C2:R3C3"),
        dimensions: [
          {
            id: "year",
            source: subset("year-headers", "R1C2:R1C3"),
            direction: "N",
          },
          {
            id: "category",
            source: subset("category-headers", "R2C1:R3C1"),
            direction: "W",
          },
        ],
      },
      {
        id: "panel-two",
        order: 2,
        tableName: "Observations panel two",
        target: subset("all-values", "R6C2:R7C3"),
        dimensions: [
          {
            id: "year",
            source: subset("year-headers", "R5C2:R5C3"),
            direction: "N",
          },
          {
            id: "category",
            source: subset("category-headers", "R6C1:R7C1"),
            direction: "W",
          },
        ],
      },
    ],
  };
}

function compileOk(
  map = atomicMap(),
  catalog = atomicCatalog(),
): AtomicCompilationEnvelopeV2 {
  const result = compileAtomicSemanticTableMapV2({
    map,
    catalog,
    context: sheetContext,
    sheet: parsedSheet(),
  });
  if (!result.ok) throw new Error(`${result.code}: ${result.message}`);
  return result.envelope;
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function canonicalize(value: unknown): unknown {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("non-finite test digest");
    return {
      $atomicScalar: "number",
      value: Object.is(value, -0) ? "-0" : String(value),
    };
  }
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, entry]) => entry !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, entry]) => [key, canonicalize(entry)]),
    );
  }
  return value;
}

function canonicalDigest(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalize(value)))
    .digest("hex")}`;
}

function failureCode(map: unknown, catalog = atomicCatalog()): string {
  const result = compileAtomicSemanticTableMapV2({
    map,
    catalog,
    context: sheetContext,
    sheet: parsedSheet(),
  });
  expect(result.ok).toBe(false);
  return result.ok ? "unexpected-success" : result.code;
}

describe("semantic table map v2 atomic multi-panel compilation", () => {
  it("compiles explicit panels through unchanged RecipeV01 multi-table support", () => {
    const envelope = compileOk();
    expect(envelope.recipe.version).toBe("0.1");
    expect(envelope.recipe.tables.map((table) => table.name)).toEqual([
      "Observations panel one",
      "Observations panel two",
    ]);
    expect(
      envelope.recipe.tables[0].headers.map((header) => header.direction),
    ).toEqual(["N", "W"]);
    expect(
      envelope.panelProofs.map((panel) => panel.activeTargets.length),
    ).toEqual([4, 4]);
    expect(envelope.attachmentProof.count).toBe(16);
    expect(envelope.reconstitutionManifest.expectedActiveTargets).toEqual([
      "R2C2",
      "R2C3",
      "R3C2",
      "R3C3",
      "R6C2",
      "R6C3",
      "R7C2",
      "R7C3",
    ]);
  });

  it("is deterministic in canonical sketch, recipe, manifests, and envelope digest", () => {
    const first = compileOk();
    const second = compileOk();
    expect(second.canonicalSketchXml).toBe(first.canonicalSketchXml);
    expect(second.canonicalRecipeJson).toBe(first.canonicalRecipeJson);
    expect(second.attachmentProof.digest).toBe(first.attachmentProof.digest);
    expect(second.reconstitutionManifest.digest).toBe(
      first.reconstitutionManifest.digest,
    );
    expect(second.envelopeDigest).toBe(first.envelopeDigest);

    const declarationArrayReversed = atomicMap();
    declarationArrayReversed.panels.reverse();
    declarationArrayReversed.logicalTable.values.target[0].selectors.reverse();
    declarationArrayReversed.panels[0].dimensions[0].source[0].selectors.reverse();
    const reordered = compileOk(declarationArrayReversed);
    expect(reordered.canonicalRecipeJson).toBe(first.canonicalRecipeJson);
    expect(reordered.mapDigest).toBe(first.mapDigest);
    expect(reordered.envelopeDigest).toBe(first.envelopeDigest);
    expect(reordered.panelProofs.map((panel) => panel.order)).toEqual([1, 2]);
  });

  it("rejects stale catalog identity and any unknown version/field", () => {
    const stale = atomicMap();
    stale.catalog.digest = `sha256:${"0".repeat(64)}`;
    expect(failureCode(stale)).toBe("CATALOG_DIGEST_MISMATCH");

    const future = { ...atomicMap(), version: "semantic-table-map-v3" };
    expect(failureCode(future)).toBe("SEMANTIC_MAP_V2_SCHEMA_INVALID");

    const unknown = { ...atomicMap(), inferredPanels: true };
    expect(failureCode(unknown)).toBe("SEMANTIC_MAP_V2_SCHEMA_INVALID");
    expect(() =>
      parseSemanticTableMapV2Json(JSON.stringify(unknown)),
    ).toThrow();

    const unknownCatalogVersion = clone(atomicMap()) as unknown as {
      catalog: { version: string };
    };
    unknownCatalogVersion.catalog.version = "semantic-region-catalog-v99";
    expect(failureCode(unknownCatalogVersion)).toBe(
      "SEMANTIC_MAP_V2_SCHEMA_INVALID",
    );
  });

  it("rejects unsafe logical output names before envelope issuance", () => {
    const reservedNames = [
      "__proto__",
      "prototype",
      "constructor",
      "toString",
      "hasOwnProperty",
      "valueOf",
    ];
    for (const name of reservedNames) {
      const valueMap = atomicMap();
      valueMap.logicalTable.values.name = name;
      expect(failureCode(valueMap), `value name ${name}`).toBe(
        "SEMANTIC_MAP_V2_SCHEMA_INVALID",
      );

      const dimensionMap = atomicMap();
      dimensionMap.logicalTable.dimensions[0].name = name;
      expect(failureCode(dimensionMap), `dimension name ${name}`).toBe(
        "SEMANTIC_MAP_V2_SCHEMA_INVALID",
      );
    }

    for (const name of [
      " leading",
      "trailing ",
      "line\nbreak",
      "tab\tname",
      "punctuation/name",
      "dot.name",
      "_source",
    ]) {
      const map = atomicMap();
      map.logicalTable.values.name = name;
      expect(failureCode(map), `unsafe grammar ${JSON.stringify(name)}`).toBe(
        "SEMANTIC_MAP_V2_SCHEMA_INVALID",
      );
    }
  });

  it("rejects direct and generated logical output-key collisions", () => {
    const cases: Array<[string, (map: SemanticTableMapV2) => void]> = [
      ["value/dimension", (map) => (map.logicalTable.values.name = "year")],
      [
        "value/generated source",
        (map) => (map.logicalTable.values.name = "year_source"),
      ],
      [
        "dimension/value",
        (map) => (map.logicalTable.dimensions[0].name = "published value"),
      ],
      [
        "dimension/generated source",
        (map) => (map.logicalTable.dimensions[1].name = "year_source"),
      ],
    ];
    for (const [label, mutate] of cases) {
      const map = atomicMap();
      mutate(map);
      expect(failureCode(map), label).toBe("LOGICAL_OUTPUT_KEY_COLLISION");
    }
  });

  it("supports every logical output name recovered from the 170 Offenders members", () => {
    const recoveredDimensionNames = [
      "age group",
      "characteristic category",
      "characteristic group",
      "classification context",
      "indigenous status",
      "jurisdiction",
      "method of proceeding",
      "observation period",
      "principal offence",
      "rate basis",
      "sex",
      "statistic basis",
      "times proceeded",
    ];
    const recoveredValueNames = ["published value"];
    for (const name of [...recoveredDimensionNames, ...recoveredValueNames]) {
      expect(logicalOutputNameV2Schema.safeParse(name).success, name).toBe(
        true,
      );
    }
    for (const name of recoveredDimensionNames) {
      const map = atomicMap();
      map.logicalTable.dimensions[0].name = name;
      expect(
        compileAtomicSemanticTableMapV2({
          map,
          catalog: atomicCatalog(),
          context: sheetContext,
          sheet: parsedSheet(),
        }).ok,
        name,
      ).toBe(true);
    }
    expect(compileOk().reconstitutionManifest.valuesName).toBe(
      recoveredValueNames[0],
    );
  });

  it("strictly validates version-specific catalog shapes and canonical selectors", () => {
    const unknownRoot = { ...atomicCatalog(), futureField: true };
    expect(failureCode(atomicMap(), unknownRoot as AtomicRegionCatalog)).toBe(
      "CATALOG_SCHEMA_INVALID",
    );

    const v1WithSegments = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "bad",
          segments: ["R1C1:R1C1"],
          kinds: [],
          nonblankCount: 1,
          valueLikeCount: 0,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
    };
    expect(
      failureCode(
        atomicMap(),
        v1WithSegments as unknown as AtomicRegionCatalog,
      ),
    ).toBe("CATALOG_SCHEMA_INVALID");

    const v5WithRange = clone(atomicCatalog()) as unknown as {
      candidates: Array<Record<string, unknown>>;
    };
    v5WithRange.candidates[0].range = "R1C1:R1C1";
    expect(
      failureCode(atomicMap(), v5WithRange as unknown as AtomicRegionCatalog),
    ).toBe("CATALOG_SCHEMA_INVALID");

    const noncanonicalMap = clone(atomicMap()) as unknown as {
      panels: Array<{ target: Array<{ selectors: Array<{ range: string }> }> }>;
    };
    noncanonicalMap.panels[0].target[0].selectors[0].range = " r2c2:r3c3 ";
    expect(failureCode(noncanonicalMap)).toBe("SEMANTIC_MAP_V2_SCHEMA_INVALID");

    const noncanonicalCatalog = clone(atomicCatalog()) as unknown as {
      candidates: Array<{ segments: string[] }>;
    };
    noncanonicalCatalog.candidates[0].segments[0] = "r2c2:r3c3";
    expect(
      failureCode(
        atomicMap(),
        noncanonicalCatalog as unknown as AtomicRegionCatalog,
      ),
    ).toBe("CATALOG_SCHEMA_INVALID");
  });

  it("rejects duplicate IDs/order and missing or reordered dimensions", () => {
    const duplicateId = atomicMap();
    duplicateId.panels[1].id = duplicateId.panels[0].id;
    expect(failureCode(duplicateId)).toBe("DUPLICATE_PANEL_ID");

    const duplicateOrder = atomicMap();
    duplicateOrder.panels[1].order = 1;
    expect(failureCode(duplicateOrder)).toBe("DUPLICATE_PANEL_ORDER");

    const missingDimension = atomicMap();
    missingDimension.panels[1].dimensions.pop();
    expect(failureCode(missingDimension)).toBe(
      "PANEL_DIMENSION_ORDER_MISMATCH",
    );

    const reordered = atomicMap();
    reordered.panels[1].dimensions.reverse();
    expect(failureCode(reordered)).toBe("PANEL_DIMENSION_ORDER_MISMATCH");
  });

  it("rejects target overlap, target gaps, targets outside logical ownership, and subset escape", () => {
    const overlap = atomicMap();
    overlap.panels[1].target[0].selectors.push({ address: "R2C2" });
    expect(failureCode(overlap)).toBe("OVERLAPPING_PANEL_TARGET");

    const gap = atomicMap();
    gap.panels[1].target = [
      {
        regionId: "all-values",
        selectors: [{ range: "R6C2:R7C2" }, { address: "R6C3" }],
      },
    ];
    expect(failureCode(gap)).toBe("PANEL_TARGET_GAP");

    const outsideLogical = atomicMap();
    outsideLogical.logicalTable.values.target[0].selectors = [
      { range: "R2C2:R3C3" },
      { range: "R6C2:R7C2" },
    ];
    expect(failureCode(outsideLogical)).toBe(
      "PANEL_TARGET_OUTSIDE_LOGICAL_TARGET",
    );

    const outsideParent = atomicMap();
    outsideParent.panels[0].dimensions[0].source = subset(
      "year-headers",
      "R2C2:R2C3",
    );
    expect(failureCode(outsideParent)).toBe("SUBSET_OUTSIDE_PARENT_REGION");
  });

  it("permits shared physical sources only with explicit opt-in on every use", () => {
    const map = atomicMap();
    map.panels[1].dimensions[0].source = subset("year-headers", "R1C2:R1C3");
    expect(failureCode(map)).toBe("UNDECLARED_SHARED_SOURCE");
    map.panels[0].dimensions[0].allowSharedSource = true;
    map.panels[1].dimensions[0].allowSharedSource = true;
    const result = compileAtomicSemanticTableMapV2({
      map,
      catalog: atomicCatalog(),
      context: sheetContext,
      sheet: parsedSheet(),
    });
    expect(result.ok).toBe(true);
  });

  it("fails closed on missing, equal-valued competing, and unused attachments", () => {
    const missing = atomicMap();
    missing.panels[0].dimensions[1].source = subset(
      "category-headers",
      "R2C1:R2C1",
    );
    expect(failureCode(missing)).toBe("MISSING_REQUIRED_ATTACHMENT");

    const ambiguous = atomicMap();
    ambiguous.panels[1].dimensions[0].source = [
      {
        regionId: "year-headers",
        selectors: [{ range: "R1C2:R1C3" }, { range: "R5C2:R5C3" }],
      },
    ];
    ambiguous.panels[1].dimensions[0].direction = "NNW";
    ambiguous.panels[0].dimensions[0].allowSharedSource = true;
    ambiguous.panels[1].dimensions[0].allowSharedSource = true;
    expect(failureCode(ambiguous)).toBe("AMBIGUOUS_ATTACHMENT");

    const unused = atomicMap();
    unused.panels[0].dimensions[1].source[0].selectors.push({
      address: "R6C1",
    });
    unused.panels[1].dimensions[1].allowSharedSource = true;
    unused.panels[0].dimensions[1].allowSharedSource = true;
    expect(failureCode(unused)).toBe("UNUSED_DECLARED_SOURCE");
  });

  it("rejects blank and boolean required dimension sources during compilation", () => {
    for (const [value, code] of [
      [null, "BLANK_REQUIRED_SOURCE"],
      [true, "INVALID_REQUIRED_SOURCE_SCALAR"],
    ] as const) {
      const context = clone(sheetContext);
      context.grid.rows[0].values[1] = value;
      const result = compileAtomicSemanticTableMapV2({
        map: atomicMap(),
        catalog: atomicCatalog(),
        context,
        sheet: parsedSheet(context),
      });
      expect(result).toMatchObject({ ok: false, code });
    }
  });

  it("enforces map JSON, aggregate role, and total selector limits", () => {
    expect(() =>
      parseSemanticTableMapV2Json(" ".repeat(MAX_ATOMIC_MAP_V2_JSON_BYTES + 1)),
    ).toThrow("SEMANTIC_MAP_V2_JSON_BYTE_LIMIT");
    const overNodes = {
      ...atomicMap(),
      padding: Array.from({ length: MAX_ATOMIC_MAP_V2_JSON_NODES }, () => null),
    };
    expect(failureCode(overNodes)).toBe("SEMANTIC_MAP_V2_RESOURCE_LIMIT");

    const overRole = atomicMap();
    overRole.panels[0].target = [
      {
        regionId: "all-values",
        selectors: Array.from(
          { length: MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE },
          () => ({ address: "R2C2" }),
        ),
      },
      { regionId: "all-values", selectors: [{ address: "R2C3" }] },
    ];
    expect(failureCode(overRole)).toBe("ROLE_SELECTOR_RESOURCE_LIMIT");

    const overTotal = atomicMap();
    const selectorList = Array.from(
      { length: MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE },
      () => ({ address: "R1C2" as const }),
    );
    const dimensionCount =
      Math.floor(MAX_ATOMIC_MAP_V2_TOTAL_SELECTORS / selectorList.length) + 1;
    overTotal.logicalTable.dimensions = Array.from(
      { length: dimensionCount },
      (_, index) => ({ id: `dimension-${index}`, name: `Dimension ${index}` }),
    );
    overTotal.panels.forEach((panel) => {
      panel.dimensions = overTotal.logicalTable.dimensions.map((dimension) => ({
        id: dimension.id,
        source: [{ regionId: "year-headers", selectors: selectorList }],
        direction: "N" as const,
      }));
    });
    expect(failureCode(overTotal)).toBe("TOTAL_SELECTOR_RESOURCE_LIMIT");
  });

  it("enforces strict catalog candidate, segment, expansion, and byte limits", () => {
    const overCandidates = clone(atomicCatalog()) as unknown as {
      candidates: Array<Record<string, unknown>>;
    };
    overCandidates.candidates = Array.from({ length: 513 }, (_, index) => ({
      ...clone(atomicCatalog().candidates[0]),
      id: `region-${index}`,
    }));
    expect(
      failureCode(
        atomicMap(),
        overCandidates as unknown as AtomicRegionCatalog,
      ),
    ).toBe("CATALOG_SCHEMA_INVALID");

    const overSegments = clone(atomicCatalog()) as unknown as {
      candidates: Array<Record<string, unknown> & { segments: string[] }>;
    };
    overSegments.candidates = Array.from({ length: 33 }, (_, index) => ({
      ...clone(atomicCatalog().candidates[0]),
      id: `region-${index}`,
      segments: Array.from({ length: 512 }, () => "R1C1:R1C1"),
    }));
    const segmentMap = atomicMap(
      overSegments as unknown as AtomicRegionCatalog,
    );
    expect(
      failureCode(segmentMap, overSegments as unknown as AtomicRegionCatalog),
    ).toBe("CATALOG_SEGMENT_RESOURCE_LIMIT");

    const perRegionCatalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "too-large",
          range: "R1C1:R100001C1",
          kinds: [],
          nonblankCount: 100001,
          valueLikeCount: 100001,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
    };
    const perRegionContext = clone(sheetContext);
    perRegionContext.dimensions = { rows: 100_001, columns: 1 };
    perRegionContext.usedRange = "R1C1:R100001C1";
    expect(
      compileAtomicSemanticTableMapV2({
        map: atomicMap(perRegionCatalog),
        catalog: perRegionCatalog,
        context: perRegionContext,
        sheet: parsedSheet(perRegionContext),
      }),
    ).toMatchObject({ ok: false, code: "CATALOG_REGION_RESOURCE_LIMIT" });

    const expansionCatalog = clone(atomicCatalog()) as unknown as {
      candidates: Array<Record<string, unknown> & { segments: string[] }>;
    };
    expansionCatalog.candidates = Array.from({ length: 6 }, (_, index) => ({
      ...clone(atomicCatalog().candidates[0]),
      id: `region-${index}`,
      segments: ["R1C1:R100000C1"],
    }));
    const expansionContext = clone(sheetContext);
    expansionContext.dimensions = { rows: 100_000, columns: 1 };
    expansionContext.usedRange = "R1C1:R100000C1";
    const expansionResult = compileAtomicSemanticTableMapV2({
      map: atomicMap(expansionCatalog as unknown as AtomicRegionCatalog),
      catalog: expansionCatalog as unknown as AtomicRegionCatalog,
      context: expansionContext,
      sheet: parsedSheet(expansionContext),
    });
    expect(expansionResult).toMatchObject({
      ok: false,
      code: "CATALOG_EXPANSION_RESOURCE_LIMIT",
    });

    const byteCatalog = {
      ...atomicCatalog(),
      padding: "x".repeat(MAX_ATOMIC_MAP_V2_CATALOG_JSON_BYTES),
    };
    expect(
      failureCode(atomicMap(), byteCatalog as unknown as AtomicRegionCatalog),
    ).toBe("CATALOG_RESOURCE_LIMIT");
    const nodeCatalog = {
      ...atomicCatalog(),
      padding: Array.from(
        { length: MAX_ATOMIC_MAP_V2_CATALOG_JSON_NODES },
        () => null,
      ),
    };
    expect(
      failureCode(atomicMap(), nodeCatalog as unknown as AtomicRegionCatalog),
    ).toBe("CATALOG_RESOURCE_LIMIT");
  });

  it("enforces bounded panel and strict-resolution resources", () => {
    const tooMany = atomicMap() as unknown as Record<string, unknown>;
    tooMany.panels = Array.from({ length: 65 }, (_, index) => ({
      ...(atomicMap().panels[0] as object),
      id: `panel-${index + 1}`,
      order: index + 1,
      tableName: `Panel ${index + 1}`,
    }));
    expect(failureCode(tooMany)).toBe("SEMANTIC_MAP_V2_SCHEMA_INVALID");

    const tooManyDimensions = atomicMap() as unknown as {
      logicalTable: { dimensions: Array<{ id: string; name: string }> };
      panels: Array<{ dimensions: unknown[] }>;
    };
    tooManyDimensions.logicalTable.dimensions = Array.from(
      { length: 65 },
      (_, index) => ({ id: `dimension-${index}`, name: `Dimension ${index}` }),
    );
    tooManyDimensions.panels.forEach((panel) => {
      panel.dimensions = tooManyDimensions.logicalTable.dimensions.map(
        (dimension) => ({
          id: dimension.id,
          source: subset("year-headers", "R1C2:R1C2"),
          direction: "N",
        }),
      );
    });
    expect(failureCode(tooManyDimensions)).toBe(
      "SEMANTIC_MAP_V2_SCHEMA_INVALID",
    );

    const largeContext = compactContext(
      Array.from({ length: 3_000 }, (_, index) => [
        index < 1_500 ? `Header ${index}` : index,
      ]),
    );
    const largeCatalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "headers",
          range: "R1C1:R1500C1",
          kinds: [],
          nonblankCount: 1500,
          valueLikeCount: 0,
          sample: [],
        },
        {
          id: "values",
          range: "R1501C1:R3000C1",
          kinds: [],
          nonblankCount: 1500,
          valueLikeCount: 1500,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
    };
    const largeMap = {
      version: "semantic-table-map-v2",
      catalog: {
        version: largeCatalog.version,
        digest: digestAtomicRegionCatalog(largeCatalog),
      },
      logicalTable: {
        id: "observations",
        name: "Observations",
        values: {
          id: "value",
          name: "value",
          target: subset("values", "R1501C1:R3000C1"),
        },
        dimensions: [{ id: "label", name: "label" }],
      },
      panels: [
        {
          id: "panel-one",
          order: 1,
          tableName: "Panel one",
          target: subset("values", "R1501C1:R3000C1"),
          dimensions: [
            {
              id: "label",
              source: subset("headers", "R1C1:R1500C1"),
              direction: "N",
            },
          ],
        },
      ],
    };
    const result = compileAtomicSemanticTableMapV2({
      map: largeMap,
      catalog: largeCatalog,
      context: largeContext,
      sheet: parsedSheet(largeContext),
    });
    expect(result).toMatchObject({
      ok: false,
      code: "STRICT_RESOLUTION_RESOURCE_LIMIT",
    });
  });

  it("enforces owned-role expansion and canonical sketch byte ceilings", () => {
    const expansionCatalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "values-one",
          range: "R1C1:R60000C1",
          kinds: [],
          nonblankCount: 60000,
          valueLikeCount: 60000,
          sample: [],
        },
        {
          id: "values-two",
          range: "R60001C1:R120000C1",
          kinds: [],
          nonblankCount: 60000,
          valueLikeCount: 60000,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
    };
    const expansionContext = clone(sheetContext);
    expansionContext.dimensions = { rows: 120_000, columns: 1 };
    expansionContext.usedRange = "R1C1:R120000C1";
    const expansionTarget = [
      ...subset("values-one", "R1C1:R60000C1"),
      ...subset("values-two", "R60001C1:R120000C1"),
    ];
    const expansionMap: SemanticTableMapV2 = {
      version: "semantic-table-map-v2",
      catalog: {
        version: expansionCatalog.version,
        digest: digestAtomicRegionCatalog(expansionCatalog),
      },
      logicalTable: {
        id: "observations",
        name: "Observations",
        values: {
          id: "value",
          name: "value",
          target: expansionTarget,
        },
        dimensions: [{ id: "label", name: "label" }],
      },
      panels: [
        {
          id: "panel-one",
          order: 1,
          tableName: "Panel one",
          target: expansionTarget,
          dimensions: [
            {
              id: "label",
              source: subset("values-one", "R1C1:R1C1"),
              direction: "N",
            },
          ],
        },
      ],
    };
    expect(
      compileAtomicSemanticTableMapV2({
        map: expansionMap,
        catalog: expansionCatalog,
        context: expansionContext,
        sheet: parsedSheet(expansionContext),
      }),
    ).toMatchObject({ ok: false, code: "ROLE_RESOURCE_LIMIT" });

    const sketchContext = compactContext([
      Array.from({ length: 1025 }, (_, index) =>
        index % 2 === 0 ? `H${index}` : null,
      ),
      Array.from({ length: 1025 }, (_, index) => (index === 1024 ? 1 : null)),
    ]);
    const sketchCatalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "headers",
          range: "R1C1:R1C1024",
          kinds: [],
          nonblankCount: 512,
          valueLikeCount: 0,
          sample: [],
        },
        {
          id: "values",
          range: "R2C1025:R2C1025",
          kinds: [],
          nonblankCount: 1,
          valueLikeCount: 1,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
    };
    const sourceSelectors = Array.from({ length: 512 }, (_, index) => ({
      address: `R1C${index * 2 + 1}`,
    }));
    const dimensions = Array.from({ length: 6 }, (_, index) => ({
      id: `dimension-${index}`,
      name: `Dimension ${index}`,
    }));
    const sketchMap: SemanticTableMapV2 = {
      version: "semantic-table-map-v2",
      catalog: {
        version: sketchCatalog.version,
        digest: digestAtomicRegionCatalog(sketchCatalog),
      },
      logicalTable: {
        id: "observations",
        name: "Observations",
        values: {
          id: "value",
          name: "value",
          target: subset("values", "R2C1025:R2C1025"),
        },
        dimensions,
      },
      panels: [
        {
          id: "panel-one",
          order: 1,
          tableName: "Panel one",
          target: subset("values", "R2C1025:R2C1025"),
          dimensions: dimensions.map((dimension) => ({
            id: dimension.id,
            source: [{ regionId: "headers", selectors: sourceSelectors }],
            direction: "N" as const,
          })),
        },
      ],
    };
    const sketchResult = compileAtomicSemanticTableMapV2({
      map: sketchMap,
      catalog: sketchCatalog,
      context: sketchContext,
      sheet: parsedSheet(sketchContext),
    });
    expect(sketchResult).toMatchObject({
      ok: false,
      code: "SKETCH_BYTE_RESOURCE_LIMIT",
    });
  });

  it("counts a sparse wide role bounding rectangle without materializing it", () => {
    const rows = Array.from({ length: 100 }, () =>
      Array.from({ length: 100 }, () => null as string | number | null),
    );
    rows[0][1] = "2023";
    rows[0][99] = "2024";
    rows[1][0] = "A";
    rows[99][0] = "B";
    rows[1][1] = 1;
    rows[99][99] = 2;
    const context = compactContext(rows);
    const candidate = (id: string, segments: string[], kinds: string[]) => ({
      id,
      segments,
      kinds,
      roleHints: [],
      formatSignatures: [],
      formatting: [],
      selectedCellCount: segments.length,
      nonblankCount: segments.length,
      valueLikeCount: kinds.includes("observations") ? segments.length : 0,
      sample: [],
    });
    const catalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v5-adjacent-year-aware",
      sheet: "Sheet 1",
      candidates: [
        candidate(
          "values",
          ["R2C2:R2C2", "R100C100:R100C100"],
          ["observations"],
        ),
        candidate("years", ["R1C2:R1C2", "R1C100:R1C100"], ["headers"]),
        candidate("categories", ["R2C1:R2C1", "R100C1:R100C1"], ["headers"]),
      ],
      omittedCandidateCount: 0,
      observationPanelCount: 1,
      formatFactCount: 0,
      cellDataFactCount: 0,
    };
    const owned = (regionId: string, addresses: string[]) => [
      {
        regionId,
        selectors: addresses.map((address) => ({ address })),
      },
    ];
    const map: SemanticTableMapV2 = {
      version: "semantic-table-map-v2",
      catalog: {
        version: catalog.version,
        digest: digestAtomicRegionCatalog(catalog),
      },
      logicalTable: {
        id: "observations",
        name: "Observations",
        values: {
          id: "value",
          name: "published value",
          target: owned("values", ["R2C2", "R100C100"]),
        },
        dimensions: [
          { id: "year", name: "year" },
          { id: "category", name: "category" },
        ],
      },
      panels: [
        {
          id: "panel-one",
          order: 1,
          tableName: "Panel one",
          target: owned("values", ["R2C2", "R100C100"]),
          dimensions: [
            {
              id: "year",
              source: owned("years", ["R1C2", "R1C100"]),
              direction: "N",
            },
            {
              id: "category",
              source: owned("categories", ["R2C1", "R100C1"]),
              direction: "W",
            },
          ],
        },
      ],
    };
    const expand = vi.mocked(addressModule.expandRange);
    const delegate = expand.getMockImplementation();
    expect(delegate).toBeDefined();
    expand.mockImplementation((range) => {
      const formatted = typeof range === "string" ? range : "";
      if (formatted === "R2C2:R100C100") {
        throw new Error("sparse role bounding rectangle was materialized");
      }
      return delegate!(range);
    });
    try {
      const result = compileAtomicSemanticTableMapV2({
        map,
        catalog,
        context,
        sheet: parsedSheet(context),
      });
      expect(result.ok).toBe(true);
      if (result.ok) {
        expect(result.envelope.recipe.tables[0].values.cells).toEqual({
          cells: ["R2C2", "R100C100"],
        });
      }
    } finally {
      expand.mockImplementation(delegate!);
    }
  });

  it("enforces the total attachment ceiling before issuing an envelope", () => {
    const context = compactContext([
      ...Array.from({ length: 6 }, (_, index) => [`Header ${index}`]),
      ...Array.from({ length: 50_000 }, (_, index) => [index]),
    ]);
    const catalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "headers",
          range: "R1C1:R6C1",
          kinds: [],
          nonblankCount: 6,
          valueLikeCount: 0,
          sample: [],
        },
        {
          id: "values",
          range: "R7C1:R50006C1",
          kinds: [],
          nonblankCount: 50_000,
          valueLikeCount: 50_000,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
    };
    const dimensions = Array.from({ length: 6 }, (_, index) => ({
      id: `dimension-${index}`,
      name: `Dimension ${index}`,
    }));
    const map: SemanticTableMapV2 = {
      version: "semantic-table-map-v2",
      catalog: {
        version: catalog.version,
        digest: digestAtomicRegionCatalog(catalog),
      },
      logicalTable: {
        id: "observations",
        name: "Observations",
        values: {
          id: "value",
          name: "value",
          target: subset("values", "R7C1:R50006C1"),
        },
        dimensions,
      },
      panels: [
        {
          id: "panel-one",
          order: 1,
          tableName: "Panel one",
          target: subset("values", "R7C1:R50006C1"),
          dimensions: dimensions.map((dimension, index) => ({
            id: dimension.id,
            source: subset("headers", `R${index + 1}C1:R${index + 1}C1`),
            direction: "NNW" as const,
          })),
        },
      ],
    };
    expect(
      compileAtomicSemanticTableMapV2({
        map,
        catalog,
        context,
        sheet: parsedSheet(context),
      }),
    ).toMatchObject({ ok: false, code: "ATTACHMENT_RESOURCE_LIMIT" });
  });

  it("never issues a compile-success envelope above its own execution limit", () => {
    const dimensionCount = 1;
    const targetCount = 70_000;
    const context = compactContext([
      ["Header"],
      ...Array.from({ length: targetCount }, (_, index) => [index + 1]),
    ]);
    const catalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "header",
          range: "R1C1:R1C1",
          kinds: [],
          nonblankCount: 1,
          valueLikeCount: 0,
          sample: [],
        },
        {
          id: "values",
          range: `R2C1:R${targetCount + 1}C1`,
          kinds: [],
          nonblankCount: targetCount,
          valueLikeCount: targetCount,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
    };
    const dimensions = Array.from({ length: dimensionCount }, (_, index) => ({
      id: `dimension-${index}`,
      name: `Dimension ${index}`,
    }));
    const map: SemanticTableMapV2 = {
      version: "semantic-table-map-v2",
      catalog: {
        version: catalog.version,
        digest: digestAtomicRegionCatalog(catalog),
      },
      logicalTable: {
        id: "observations",
        name: "Observations",
        values: {
          id: "value",
          name: "value",
          target: subset("values", `R2C1:R${targetCount + 1}C1`),
        },
        dimensions,
      },
      panels: [
        {
          id: "panel-one",
          order: 1,
          tableName: "Panel one",
          target: subset("values", `R2C1:R${targetCount + 1}C1`),
          dimensions: dimensions.map((dimension) => ({
            id: dimension.id,
            source: subset("header", "R1C1:R1C1"),
            direction: "N" as const,
          })),
        },
      ],
    };
    const result = compileAtomicSemanticTableMapV2({
      map,
      catalog,
      context,
      sheet: parsedSheet(context),
    });
    expect(result).toMatchObject({
      ok: false,
      code: "ENVELOPE_RESOURCE_LIMIT",
    });
    if (!result.ok) expect(result.code).not.toBe("ATTACHMENT_RESOURCE_LIMIT");
  });
});

describe("semantic table map v2 execution and exact-address reconstitution", () => {
  it("executes provider-free and emits one canonical logical table with exact source evidence", () => {
    const envelope = compileOk();
    const result = executeAtomicSemanticTableMapV2(
      envelope,
      parsedSheet(),
      envelope.envelopeDigest,
    );
    expect(result.providerCalls).toBe(0);
    expect(result.logicalTable.rows).toHaveLength(8);
    expect(result.logicalTable.rows[0]).toEqual({
      year: "2023",
      category: "A",
      "published value": 1,
      _source: { sheet: "Sheet 1", address: "R2C2", row: 2, col: 2 },
      year_source: "R1C2",
      category_source: "R2C1",
    });
    expect(Object.keys(result.logicalTable.rows[0])).toEqual([
      "year",
      "category",
      "published value",
      "_source",
      "year_source",
      "category_source",
    ]);
    expect(result.logicalTable.rows.at(-1)?._source?.address).toBe("R7C3");
  });

  it("does not depend on physical panel execution array order", () => {
    const envelope = compileOk();
    const physical = executeRecipe(envelope.recipe, parsedSheet());
    const first = reconstituteAtomicSemanticExecutionV2(
      envelope,
      physical,
      parsedSheet(),
      envelope.envelopeDigest,
    );
    const reversed = clone(physical);
    reversed.tables.reverse();
    const second = reconstituteAtomicSemanticExecutionV2(
      envelope,
      reversed,
      parsedSheet(),
      envelope.envelopeDigest,
    );
    expect(second.logicalTable).toEqual(first.logicalTable);
  });

  it.each([
    [
      "global warning",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.warnings.push({ code: "AMBIGUOUS_HEADER", message: "x" });
      },
      "EXECUTION_WARNINGS_PRESENT",
    ],
    [
      "null dimension",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows[0].year = null;
      },
      "INVALID_REQUIRED_DIMENSION",
    ],
    [
      "wrong source",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows[0].year_source = "R5C2";
      },
      "DIMENSION_SOURCE_MISMATCH",
    ],
    [
      "missing target",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows.pop();
      },
      "ROW_TRACE_CARDINALITY_MISMATCH",
    ],
    [
      "duplicate target",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows.push(clone(execution.tables[0].rows[0]));
      },
      "ROW_TRACE_CARDINALITY_MISMATCH",
    ],
    [
      "extra target",
      (execution: ReturnType<typeof executeRecipe>) => {
        const row = clone(execution.tables[0].rows[0]);
        row._source = { sheet: "Sheet 1", address: "R4C2", row: 4, col: 2 };
        execution.tables[0].rows.push(row);
      },
      "ROW_TRACE_CARDINALITY_MISMATCH",
    ],
    [
      "missing table",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables.pop();
      },
      "EXECUTION_TABLE_SET_MISMATCH",
    ],
  ])("rejects %s", (_name, mutate, code) => {
    const envelope = compileOk();
    const physical = executeRecipe(envelope.recipe, parsedSheet());
    mutate(physical);
    expect(() =>
      reconstituteAtomicSemanticExecutionV2(
        envelope,
        physical,
        parsedSheet(),
        envelope.envelopeDigest,
      ),
    ).toThrow(`ATOMIC_SEMANTIC_MAP_V2_${code}`);
  });

  it("requires an externally trusted digest and rejects coordinated proof mutation", () => {
    const envelope = compileOk();
    expect(() =>
      executeAtomicSemanticTableMapV2(
        envelope,
        parsedSheet(),
        `sha256:${"0".repeat(64)}`,
      ),
    ).toThrow("ATOMIC_SEMANTIC_MAP_V2_TRUSTED_ENVELOPE_DIGEST_MISMATCH");

    const coordinated = clone(envelope);
    coordinated.reconstitutionManifest.logicalTableName = "Changed";
    const { digest: _oldManifestDigest, ...manifest } =
      coordinated.reconstitutionManifest;
    coordinated.reconstitutionManifest.digest = canonicalDigest(manifest);
    coordinated.envelopeDigest = digestAtomicCompilationEnvelopeV2(coordinated);
    expect(() =>
      executeAtomicSemanticTableMapV2(
        coordinated,
        parsedSheet(),
        envelope.envelopeDigest,
      ),
    ).toThrow("ATOMIC_SEMANTIC_MAP_V2_TRUSTED_ENVELOPE_DIGEST_MISMATCH");

    const inconsistent = clone(envelope);
    inconsistent.panelProofs[0].targetDigest = `sha256:${"1".repeat(64)}`;
    inconsistent.envelopeDigest =
      digestAtomicCompilationEnvelopeV2(inconsistent);
    expect(() =>
      executeAtomicSemanticTableMapV2(
        inconsistent,
        parsedSheet(),
        inconsistent.envelopeDigest,
      ),
    ).toThrow("ATOMIC_SEMANTIC_MAP_V2_PANEL_PROOF_MISMATCH");
  });

  it.each([
    [
      "map digest",
      (envelope: AtomicCompilationEnvelopeV2) => {
        envelope.mapDigest = `sha256:${"1".repeat(64)}`;
      },
      "MAP_PROOF_MISMATCH",
    ],
    [
      "sketch digest",
      (envelope: AtomicCompilationEnvelopeV2) => {
        envelope.sketchDigest = `sha256:${"1".repeat(64)}`;
      },
      "SKETCH_PROOF_MISMATCH",
    ],
    [
      "recipe digest",
      (envelope: AtomicCompilationEnvelopeV2) => {
        envelope.recipeDigest = `sha256:${"1".repeat(64)}`;
      },
      "RECIPE_DIGEST_MISMATCH",
    ],
    [
      "logical target digest",
      (envelope: AtomicCompilationEnvelopeV2) => {
        envelope.logicalTargetDigest = `sha256:${"1".repeat(64)}`;
      },
      "LOGICAL_TARGET_PROOF_MISMATCH",
    ],
    [
      "panel source digest",
      (envelope: AtomicCompilationEnvelopeV2) => {
        envelope.panelProofs[0].dimensions[0].sourceDigest = `sha256:${"1".repeat(64)}`;
      },
      "PANEL_SOURCE_PROOF_MISMATCH",
    ],
    [
      "attachment count",
      (envelope: AtomicCompilationEnvelopeV2) => {
        envelope.attachmentProof.count += 1;
      },
      "ATTACHMENT_PROOF_DIGEST_MISMATCH",
    ],
    [
      "active target digest",
      (envelope: AtomicCompilationEnvelopeV2) => {
        envelope.reconstitutionManifest.expectedActiveTargetDigest = `sha256:${"1".repeat(64)}`;
        const { digest: _old, ...manifest } = envelope.reconstitutionManifest;
        envelope.reconstitutionManifest.digest = canonicalDigest(manifest);
      },
      "RECONSTITUTION_MANIFEST_DIGEST_MISMATCH",
    ],
    [
      "compiler identity",
      (envelope: AtomicCompilationEnvelopeV2) => {
        (envelope as unknown as { compilerVersion: string }).compilerVersion =
          "future-compiler";
      },
      "COMPILER_IDENTITY_MISMATCH",
    ],
  ])(
    "rejects regenerated envelopes with inconsistent %s",
    (_name, mutate, code) => {
      const envelope = compileOk();
      mutate(envelope);
      envelope.envelopeDigest = digestAtomicCompilationEnvelopeV2(envelope);
      expect(() =>
        executeAtomicSemanticTableMapV2(
          envelope,
          parsedSheet(),
          envelope.envelopeDigest,
        ),
      ).toThrow(`ATOMIC_SEMANTIC_MAP_V2_${code}`);
    },
  );

  it("rejects same-name target or header sheet-content drift", () => {
    const envelope = compileOk();
    for (const address of ["R2C2", "R1C2"]) {
      const drifted = parsedSheet();
      const cell = drifted.cells.find((entry) => entry.address === address)!;
      cell.value = typeof cell.value === "number" ? 999 : "changed";
      expect(() =>
        executeAtomicSemanticTableMapV2(
          envelope,
          drifted,
          envelope.envelopeDigest,
        ),
      ).toThrow("ATOMIC_SEMANTIC_MAP_V2_SHEET_CONTENT_DIGEST_MISMATCH");
    }
  });

  it("round-trips authoritative parsed date and error cells", () => {
    const context = clone(sheetContext);
    context.grid.rows[3].values[0] = "2026-01-01T00:00:00.000Z";
    context.grid.rows[3].values[1] = "#N/A";
    const sheet = parsedSheet(context);
    sheet.cells.find((cell) => cell.address === "R4C1")!.data_type = "date";
    sheet.cells.find((cell) => cell.address === "R4C2")!.data_type = "error";
    const compiled = compileAtomicSemanticTableMapV2({
      map: atomicMap(),
      catalog: atomicCatalog(),
      context,
      sheet,
    });
    expect(compiled.ok).toBe(true);
    if (!compiled.ok) return;
    expect(() =>
      executeAtomicSemanticTableMapV2(
        compiled.envelope,
        sheet,
        compiled.envelope.envelopeDigest,
      ),
    ).not.toThrow();
  });

  it("round-trips execution-bound date and error typed cells", () => {
    const context = clone(sheetContext);
    context.grid.rows[0].values[1] = "#N/A";
    context.grid.rows[1].values[1] = "2026-01-01T00:00:00.000Z";
    const sheet = parsedSheet(context);
    sheet.cells.find((cell) => cell.address === "R1C2")!.data_type = "error";
    sheet.cells.find((cell) => cell.address === "R2C2")!.data_type = "date";
    const compiled = compileAtomicSemanticTableMapV2({
      map: atomicMap(),
      catalog: atomicCatalog(),
      context,
      sheet,
    });
    expect(compiled.ok).toBe(true);
    if (!compiled.ok) return;
    const result = executeAtomicSemanticTableMapV2(
      compiled.envelope,
      sheet,
      compiled.envelope.envelopeDigest,
    );
    expect(result.logicalTable.rows[0]["published value"]).toBe(
      "2026-01-01T00:00:00.000Z",
    );
    expect(result.logicalTable.rows[0].year).toBe("#N/A");
  });

  it.each(["formula", "formatted", "comment", "data_type"] as const)(
    "rejects authoritative sheet %s-only drift",
    (field) => {
      const context = clone(sheetContext);
      context.grid.rows[3].values[0] = "metadata";
      const sheet = parsedSheet(context);
      const metadata = sheet.cells.find((cell) => cell.address === "R4C1")!;
      metadata.formula = '="metadata"';
      metadata.formatted = "Metadata";
      metadata.comment = "ABS note";
      const compiled = compileAtomicSemanticTableMapV2({
        map: atomicMap(),
        catalog: atomicCatalog(),
        context,
        sheet,
      });
      expect(compiled.ok).toBe(true);
      if (!compiled.ok) return;
      const drifted = clone(sheet);
      const cell = drifted.cells.find((entry) => entry.address === "R4C1")!;
      if (field === "formula") cell.formula = '="changed"';
      else if (field === "formatted") cell.formatted = "Changed";
      else if (field === "comment") cell.comment = "Changed";
      else cell.data_type = "error";
      expect(() =>
        executeAtomicSemanticTableMapV2(
          compiled.envelope,
          drifted,
          compiled.envelope.envelopeDigest,
        ),
      ).toThrow("ATOMIC_SEMANTIC_MAP_V2_SHEET_CONTENT_DIGEST_MISMATCH");
    },
  );

  it.each(["hyperlink", "style", "merge"] as const)(
    "rejects authoritative sheet %s-only drift",
    (field) => {
      const sheet = parsedSheet();
      const cell = sheet.cells.find((entry) => entry.address === "R4C1")!;
      cell.hyperlink = "https://example.invalid/source";
      cell.style = { bold: true, border: { bottom: true } };
      const compiled = compileAtomicSemanticTableMapV2({
        map: atomicMap(),
        catalog: atomicCatalog(),
        context: sheetContext,
        sheet,
      });
      expect(compiled.ok).toBe(true);
      if (!compiled.ok) return;
      const drifted = clone(sheet);
      const driftedCell = drifted.cells.find(
        (entry) => entry.address === "R4C1",
      )!;
      if (field === "hyperlink") {
        driftedCell.hyperlink = "https://example.invalid/changed";
      } else if (field === "style") {
        driftedCell.style = { bold: false, border: { bottom: true } };
      } else {
        drifted.merges.push({ parent: "R4C1", range: "R4C1:R4C2" });
      }
      expect(() =>
        executeAtomicSemanticTableMapV2(
          compiled.envelope,
          drifted,
          compiled.envelope.envelopeDigest,
        ),
      ).toThrow("ATOMIC_SEMANTIC_MAP_V2_SHEET_CONTENT_DIGEST_MISMATCH");
    },
  );

  it.each(["remove", "duplicate", "forge"] as const)(
    "rejects %s non-table physical provenance",
    (mode) => {
      const context = clone(sheetContext);
      context.grid.rows[3].values[0] = "metadata";
      const sheet = parsedSheet(context);
      const compiled = compileAtomicSemanticTableMapV2({
        map: atomicMap(),
        catalog: atomicCatalog(),
        context,
        sheet,
      });
      expect(compiled.ok).toBe(true);
      if (!compiled.ok) return;
      const physical = executeRecipe(compiled.envelope.recipe, sheet);
      expect(physical.non_table_cells?.length).toBeGreaterThan(0);
      if (mode === "remove") physical.non_table_cells!.pop();
      else if (mode === "duplicate")
        physical.non_table_cells!.push(clone(physical.non_table_cells![0]));
      else physical.non_table_cells![0].comment = "forged";
      expect(() =>
        reconstituteAtomicSemanticExecutionV2(
          compiled.envelope,
          physical,
          sheet,
          compiled.envelope.envelopeDigest,
        ),
      ).toThrow("ATOMIC_SEMANTIC_MAP_V2_PHYSICAL_EXECUTION_PROOF_MISMATCH");
    },
  );

  const unknownExecutionFieldCases: Array<
    [
      string,
      (execution: ReturnType<typeof executeRecipe>, value: unknown) => void,
    ]
  > = [
    [
      "top-level execution",
      (execution, value) => {
        (execution as unknown as Record<string, unknown>).forged = value;
      },
    ],
    [
      "table",
      (execution, value) => {
        (execution.tables[0] as unknown as Record<string, unknown>).forged =
          value;
      },
    ],
    [
      "row",
      (execution, value) => {
        execution.tables[0].rows[0].forged = value as never;
      },
    ],
    [
      "row source",
      (execution, value) => {
        (
          execution.tables[0].rows[0]._source as unknown as Record<
            string,
            unknown
          >
        ).forged = value;
      },
    ],
    [
      "trace container",
      (execution, value) => {
        (
          execution.tables[0].trace as unknown as Record<string, unknown>
        ).forged = value;
      },
    ],
    [
      "value trace",
      (execution, value) => {
        (
          execution.tables[0].trace.value_cells[0] as unknown as Record<
            string,
            unknown
          >
        ).forged = value;
      },
    ],
    [
      "header trace",
      (execution, value) => {
        (
          execution.tables[0].trace.value_cells[0]
            .headers[0] as unknown as Record<string, unknown>
        ).forged = value;
      },
    ],
    [
      "global warning",
      (execution, value) => {
        execution.warnings.push({
          code: "SELECTOR_WARNING",
          message: "malformed warning",
        });
        (execution.warnings[0] as unknown as Record<string, unknown>).forged =
          value;
      },
    ],
    [
      "table warning",
      (execution, value) => {
        execution.tables[0].warnings.push({
          code: "SELECTOR_WARNING",
          message: "malformed warning",
        });
        (
          execution.tables[0].warnings[0] as unknown as Record<string, unknown>
        ).forged = value;
      },
    ],
    [
      "non-table record",
      (execution, value) => {
        (
          execution.non_table_cells![0] as unknown as Record<string, unknown>
        ).forged = value;
      },
    ],
  ];

  it.each(unknownExecutionFieldCases)(
    "strictly rejects unknown properties on %s",
    (_name, mutate) => {
      for (const value of [undefined, "defined-forgery"]) {
        const context = clone(sheetContext);
        context.grid.rows[3].values[0] = "metadata";
        const sheet = parsedSheet(context);
        const compiled = compileAtomicSemanticTableMapV2({
          map: atomicMap(),
          catalog: atomicCatalog(),
          context,
          sheet,
        });
        expect(compiled.ok).toBe(true);
        if (!compiled.ok) return;
        const physical = executeRecipe(compiled.envelope.recipe, sheet);
        expect(physical.non_table_cells?.length).toBeGreaterThan(0);
        mutate(physical, value);
        expect(() =>
          reconstituteAtomicSemanticExecutionV2(
            compiled.envelope,
            physical,
            sheet,
            compiled.envelope.envelopeDigest,
          ),
        ).toThrow("ATOMIC_SEMANTIC_MAP_V2_PHYSICAL_EXECUTION_SCHEMA_MISMATCH");
      }
    },
  );

  it("returns only independently reproduced execution objects", () => {
    const envelope = compileOk();
    const supplied = executeRecipe(envelope.recipe, parsedSheet());
    const originalValue = supplied.tables[0].rows[0]["published value"];
    const result = reconstituteAtomicSemanticExecutionV2(
      envelope,
      supplied,
      parsedSheet(),
      envelope.envelopeDigest,
    );
    expect(result.physicalExecution).not.toBe(supplied);
    expect(result.physicalExecution.tables[0]).not.toBe(supplied.tables[0]);
    expect(result.logicalTable.rows[0]._source).not.toBe(
      supplied.tables[0].rows[0]._source,
    );
    expect(result.logicalTable.trace.value_cells[0]).not.toBe(
      supplied.tables[0].trace.value_cells[0],
    );
    supplied.tables[0].rows[0]["published value"] = 999;
    supplied.tables[0].trace.value_cells[0].value = 999;
    expect(result.physicalExecution.tables[0].rows[0]["published value"]).toBe(
      originalValue,
    );
    expect(result.logicalTable.rows[0]["published value"]).toBe(originalValue);
    expect(result.logicalTable.trace.value_cells[0].value).toBe(originalValue);
  });

  it.each([undefined, null, 0, ""])(
    "rejects malformed falsy trace flag %s",
    (flag) => {
      const envelope = compileOk();
      const physical = executeRecipe(envelope.recipe, parsedSheet());
      const header = physical.tables[0].trace.value_cells[0]
        .headers[0] as unknown as Record<string, unknown>;
      header.missing = flag;
      expect(() =>
        reconstituteAtomicSemanticExecutionV2(
          envelope,
          physical,
          parsedSheet(),
          envelope.envelopeDigest,
        ),
      ).toThrow("ATOMIC_SEMANTIC_MAP_V2_PHYSICAL_EXECUTION_SCHEMA_MISMATCH");
      const second = executeRecipe(envelope.recipe, parsedSheet());
      const secondHeader = second.tables[0].trace.value_cells[0]
        .headers[0] as unknown as Record<string, unknown>;
      secondHeader.ambiguous = flag;
      expect(() =>
        reconstituteAtomicSemanticExecutionV2(
          envelope,
          second,
          parsedSheet(),
          envelope.envelopeDigest,
        ),
      ).toThrow("ATOMIC_SEMANTIC_MAP_V2_PHYSICAL_EXECUTION_SCHEMA_MISMATCH");
    },
  );

  it("rejects reordered header traces", () => {
    const envelope = compileOk();
    const physical = executeRecipe(envelope.recipe, parsedSheet());
    physical.tables[0].trace.value_cells[0].headers.reverse();
    expect(() =>
      reconstituteAtomicSemanticExecutionV2(
        envelope,
        physical,
        parsedSheet(),
        envelope.envelopeDigest,
      ),
    ).toThrow("ATOMIC_SEMANTIC_MAP_V2_HEADER_TRACE_ORDER_MISMATCH");
  });

  it.each([
    ["target", "R2C2"],
    ["dimension", "R1C2"],
  ] as const)("distinguishes -0 from 0 %s drift", (_kind, address) => {
    const context = clone(sheetContext);
    const parsed = /^R(\d+)C(\d+)$/.exec(address)!;
    context.grid.rows[Number(parsed[1]) - 1].values[Number(parsed[2]) - 1] = -0;
    const sheet = parsedSheet(context);
    const compiled = compileAtomicSemanticTableMapV2({
      map: atomicMap(),
      catalog: atomicCatalog(),
      context,
      sheet,
    });
    expect(compiled.ok).toBe(true);
    if (!compiled.ok) return;
    const drifted = clone(sheet);
    drifted.cells.find((cell) => cell.address === address)!.value = 0;
    expect(() =>
      executeAtomicSemanticTableMapV2(
        compiled.envelope,
        drifted,
        compiled.envelope.envelopeDigest,
      ),
    ).toThrow("ATOMIC_SEMANTIC_MAP_V2_SHEET_CONTENT_DIGEST_MISMATCH");
  });

  it("rejects a coordinated physical-execution proof mutation", () => {
    const envelope = compileOk();
    envelope.physicalExecutionProof.digest = `sha256:${"9".repeat(64)}`;
    envelope.envelopeDigest = digestAtomicCompilationEnvelopeV2(envelope);
    expect(() =>
      executeAtomicSemanticTableMapV2(
        envelope,
        parsedSheet(),
        envelope.envelopeDigest,
      ),
    ).toThrow("ATOMIC_SEMANTIC_MAP_V2_PHYSICAL_EXECUTION_PROOF_MISMATCH");
  });

  it.each([
    [
      "table sheet",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].sheet = "Other";
      },
      "TABLE_SHEET_MISMATCH",
    ],
    [
      "source coordinate",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows[0]._source!.row = 99;
      },
      "SOURCE_COORDINATE_MISMATCH",
    ],
    [
      "published value",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows[0]["published value"] = 999;
      },
      "VALUE_TRACE_MISMATCH",
    ],
    [
      "non-null dimension value",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows[0].year = "changed";
      },
      "ATTACHMENT_TRACE_MISMATCH",
    ],
    [
      "boolean dimension value",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].rows[0].year = true;
      },
      "INVALID_REQUIRED_DIMENSION",
    ],
    [
      "trace value",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].trace.value_cells[0].value = 999;
      },
      "VALUE_TRACE_MISMATCH",
    ],
    [
      "trace direction",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].trace.value_cells[0].headers[0].direction = "W";
      },
      "ATTACHMENT_TRACE_MISMATCH",
    ],
    [
      "trace candidate identity",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].trace.value_cells[0].headers[0].candidates = [
          "R5C2",
        ];
      },
      "ATTACHMENT_TRACE_MISMATCH",
    ],
    [
      "trace header value",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].trace.value_cells[0].headers[0].value = "changed";
      },
      "ATTACHMENT_TRACE_MISMATCH",
    ],
    [
      "duplicate target trace",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].trace.value_cells[1] = clone(
          execution.tables[0].trace.value_cells[0],
        );
      },
      "DUPLICATE_TARGET_TRACE",
    ],
    [
      "extra header trace",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].trace.value_cells[0].headers.push(
          clone(execution.tables[0].trace.value_cells[0].headers[0]),
        );
      },
      "HEADER_TRACE_CARDINALITY_MISMATCH",
    ],
    [
      "duplicate header trace",
      (execution: ReturnType<typeof executeRecipe>) => {
        execution.tables[0].trace.value_cells[0].headers[1] = clone(
          execution.tables[0].trace.value_cells[0].headers[0],
        );
      },
      "DUPLICATE_HEADER_TRACE",
    ],
    [
      "missing published value",
      (execution: ReturnType<typeof executeRecipe>) => {
        delete execution.tables[0].rows[0]["published value"];
      },
      "PHYSICAL_EXECUTION_SCHEMA_MISMATCH",
    ],
  ])("rejects altered %s evidence", (_name, mutate, code) => {
    const envelope = compileOk();
    const physical = executeRecipe(envelope.recipe, parsedSheet());
    mutate(physical);
    expect(() =>
      reconstituteAtomicSemanticExecutionV2(
        envelope,
        physical,
        parsedSheet(),
        envelope.envelopeDigest,
      ),
    ).toThrow(`ATOMIC_SEMANTIC_MAP_V2_${code}`);
  });
});

describe("semantic map v1 compatibility", () => {
  it("retains exact v1 RecipeV01 and execution bytes", () => {
    const context = compactContext([
      [null, "2023", "2024"],
      ["A", 1, 2],
      ["B", 3, 4],
    ]);
    const catalog: SemanticRegionCatalog = {
      version: "semantic-region-catalog-v1",
      sheet: "Sheet 1",
      omittedCandidateCount: 0,
      candidates: [
        ["values", "R2C2:R3C3"],
        ["years", "R1C2:R1C3"],
        ["categories", "R2C1:R3C1"],
      ].map(([id, range]) => ({
        id,
        range,
        kinds: ["test"],
        nonblankCount: 1,
        valueLikeCount: 1,
        sample: [],
      })),
    };
    const map: SemanticTableMapV1 = {
      version: "semantic-table-map-v1",
      table: {
        name: "observations",
        values: { name: "value", regions: ["values"] },
        dimensions: [
          { name: "year", memberRegions: ["years"], direction: "N" },
          {
            name: "category",
            memberRegions: ["categories"],
            direction: "W",
          },
        ],
      },
    };
    const compiled = compileSemanticTableMap({ map, catalog, context });
    expect(compiled.ok).toBe(true);
    if (!compiled.ok) return;
    expect(compiled.canonicalRecipeJson).toBe(
      '{"version":"0.1","sheet":"Sheet 1","tables":[{"name":"observations","values":{"name":"value","cells":{"range":"R2C2:R3C3"}},"headers":[{"name":"year","direction":"N","cells":{"range":"R1C2:R1C3"}},{"name":"category","direction":"W","cells":{"range":"R2C1:R3C1"}}]}]}\n',
    );
    expect(
      JSON.stringify(executeRecipe(compiled.recipe, parsedSheet(context))),
    ).toBe(
      '{"sheet":"Sheet 1","tables":[{"table":"observations","sheet":"Sheet 1","rows":[{"value":1,"_source":{"sheet":"Sheet 1","address":"R2C2","row":2,"col":2},"year":"2023","year_source":"R1C2","category":"A","category_source":"R2C1"},{"value":2,"_source":{"sheet":"Sheet 1","address":"R2C3","row":2,"col":3},"year":"2024","year_source":"R1C3","category":"A","category_source":"R2C1"},{"value":3,"_source":{"sheet":"Sheet 1","address":"R3C2","row":3,"col":2},"year":"2023","year_source":"R1C2","category":"B","category_source":"R3C1"},{"value":4,"_source":{"sheet":"Sheet 1","address":"R3C3","row":3,"col":3},"year":"2024","year_source":"R1C3","category":"B","category_source":"R3C1"}],"warnings":[],"trace":{"value_cells":[{"source":{"sheet":"Sheet 1","address":"R2C2","row":2,"col":2},"value":1,"headers":[{"header":"year","direction":"N","candidates":["R1C2"],"selected":"R1C2","value":"2023","missing":false,"ambiguous":false},{"header":"category","direction":"W","candidates":["R2C1"],"selected":"R2C1","value":"A","missing":false,"ambiguous":false}]},{"source":{"sheet":"Sheet 1","address":"R2C3","row":2,"col":3},"value":2,"headers":[{"header":"year","direction":"N","candidates":["R1C3"],"selected":"R1C3","value":"2024","missing":false,"ambiguous":false},{"header":"category","direction":"W","candidates":["R2C1"],"selected":"R2C1","value":"A","missing":false,"ambiguous":false}]},{"source":{"sheet":"Sheet 1","address":"R3C2","row":3,"col":2},"value":3,"headers":[{"header":"year","direction":"N","candidates":["R1C2"],"selected":"R1C2","value":"2023","missing":false,"ambiguous":false},{"header":"category","direction":"W","candidates":["R3C1"],"selected":"R3C1","value":"B","missing":false,"ambiguous":false}]},{"source":{"sheet":"Sheet 1","address":"R3C3","row":3,"col":3},"value":4,"headers":[{"header":"year","direction":"N","candidates":["R1C3"],"selected":"R1C3","value":"2024","missing":false,"ambiguous":false},{"header":"category","direction":"W","candidates":["R3C1"],"selected":"R3C1","value":"B","missing":false,"ambiguous":false}]}]}}],"non_table_cells":[],"warnings":[]}',
    );
  });
});
