// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { ParsedSheet, TidyCell } from "../src/workbook/types.js";
import {
  assertTargetScopedCountLimit,
  assertTargetScopedRawJsonBudget,
  assertTargetScopedValueBudget,
  compileTargetScopedRecipeV02,
  digestTargetScopedBytes,
  digestTargetScopedCanonical,
  digestTargetScopedEnvelopeV02,
  executeTargetScopedRecipeV02,
  MAX_TARGET_SCOPED_EXECUTION_BYTES,
  MAX_TARGET_SCOPED_EXECUTION_NODES,
  MAX_TARGET_SCOPED_JSON_BYTES,
  MAX_TARGET_SCOPED_RESOLUTION_OPERATIONS,
  MAX_TARGET_SCOPED_TARGETS,
  measureTargetScopedValue,
  parseTargetScopedCompilationEnvelopeV02,
  parseTargetScopedExecutionV02,
  parseTargetScopedRecipeV02,
  parseTargetScopedSemanticMapV1,
  TARGET_SCOPED_EXECUTION_V02,
  TARGET_SCOPED_LIMITS,
  TARGET_SCOPED_RECIPE_V02,
  type TargetScopedSemanticMapV1,
  type TargetScopedSourceContext,
} from "../src/catalog/target-scoped-recipe-v02.js";
import {
  digestAtomicRegionCatalog,
  parseSemanticTableMapV2Json,
  type AtomicRegionCatalog,
} from "../src/catalog/semantic-map-v2.js";
import { parseRecipe } from "../src/recipe/schema.js";
import { parseSemanticTableMapJson } from "../src/catalog/semantic-map-v1.js";

const source: TargetScopedSourceContext = {
  version: "target-scoped-source-context/v1",
  workbookDigest: `sha256:${"1".repeat(64)}`,
  physicalSheet: "Sheet 1",
};

function cell(
  address: string,
  value: TidyCell["value"],
  extra: Partial<TidyCell> = {},
): TidyCell {
  const match = /^R(\d+)C(\d+)$/.exec(address)!;
  return {
    sheet: "Sheet 1",
    address,
    row: Number(match[1]),
    col: Number(match[2]),
    value,
    data_type:
      value === null
        ? "blank"
        : typeof value === "number"
          ? "numeric"
          : typeof value === "boolean"
            ? "boolean"
            : "string",
    ...extra,
  };
}

function sheet(): ParsedSheet {
  const cells = [
    cell("R1C1", null),
    cell("R1C2", "2023", { formula: '="2023"', formatted: "2023" }),
    cell("R1C3", "2024"),
    cell("R2C1", "A", { comment: "shared category/group" }),
    cell("R2C2", 1),
    cell("R2C3", 2),
    cell("R3C1", null),
    cell("R3C2", null),
    cell("R3C3", null),
  ];
  return {
    name: "Sheet 1",
    usedRange: "R1C1:R3C3",
    rowCount: 3,
    columnCount: 3,
    nonEmptyCellCount: cells.filter((entry) => entry.value !== null).length,
    cells,
    merges: [],
  };
}

function catalog(): AtomicRegionCatalog {
  const candidate = (id: string, segments: string[]) => ({
    id,
    segments,
    kinds: [],
    roleHints: [],
    formatSignatures: [],
    formatting: [],
    selectedCellCount: segments.length,
    nonblankCount: segments.length,
    valueLikeCount: 0,
    sample: [],
  });
  return {
    version: "semantic-region-catalog-v5-adjacent-year-aware",
    sheet: "Sheet 1",
    candidates: [
      candidate("values", ["R2C2:R2C3"]),
      candidate("category", ["R2C1:R2C1"]),
      candidate("years", ["R1C2:R1C3"]),
    ],
    omittedCandidateCount: 0,
    observationPanelCount: 1,
    formatFactCount: 0,
    cellDataFactCount: 0,
  };
}

function mapFor(catalogValue = catalog()): TargetScopedSemanticMapV1 {
  return {
    version: "target-scoped-semantic-map-v1",
    catalog: {
      version: catalogValue.version,
      bytesDigest: "",
      contentDigest: digestAtomicRegionCatalog(catalogValue),
    },
    source,
    logicalTable: {
      id: "observations",
      name: "Observations",
      valuesName: "published value",
      dimensions: [
        { id: "category", name: "category" },
        { id: "group", name: "group" },
        { id: "year", name: "year" },
      ],
    },
    targetSets: [
      {
        id: "targets",
        regionId: "values",
        selectors: [{ range: "R2C2:R2C3" }],
      },
    ],
    sourceUniverses: [
      {
        id: "category-source",
        regionId: "category",
        selectors: [{ address: "R2C1" }],
      },
      {
        id: "year-2023-source",
        regionId: "years",
        selectors: [{ address: "R1C2" }],
      },
      {
        id: "year-2024-source",
        regionId: "years",
        selectors: [{ address: "R1C3" }],
      },
    ],
    attachments: [
      {
        id: "category-binding",
        dimensionId: "category",
        direction: "W",
        selectedAddress: "R2C1",
        universeId: "category-source",
      },
      {
        id: "group-binding",
        dimensionId: "group",
        direction: "W",
        selectedAddress: "R2C1",
        universeId: "category-source",
      },
      {
        id: "year-2023-binding",
        dimensionId: "year",
        direction: "N",
        selectedAddress: "R1C2",
        universeId: "year-2023-source",
      },
      {
        id: "year-2024-binding",
        dimensionId: "year",
        direction: "N",
        selectedAddress: "R1C3",
        universeId: "year-2024-source",
      },
    ],
    vectors: [
      {
        id: "vector-2023",
        attachmentIds: [
          "category-binding",
          "group-binding",
          "year-2023-binding",
        ],
      },
      {
        id: "vector-2024",
        attachmentIds: [
          "category-binding",
          "group-binding",
          "year-2024-binding",
        ],
      },
    ],
    targets: [
      { address: "R2C2", targetSetId: "targets", vectorId: "vector-2023" },
      { address: "R2C3", targetSetId: "targets", vectorId: "vector-2024" },
    ],
  };
}

function fixture(
  map = mapFor(),
  catalogValue = catalog(),
  sheetValue = sheet(),
) {
  const catalogRaw = JSON.stringify(catalogValue);
  map.catalog.bytesDigest = digestTargetScopedBytes(catalogRaw);
  map.catalog.contentDigest = digestAtomicRegionCatalog(catalogValue);
  const mapRaw = JSON.stringify(map);
  const result = compileTargetScopedRecipeV02({
    mapRaw,
    expectedMapBytesDigest: digestTargetScopedBytes(mapRaw),
    catalogRaw,
    expectedCatalogBytesDigest: digestTargetScopedBytes(catalogRaw),
    sheet: sheetValue,
    source,
  });
  return { result, mapRaw, catalogRaw, map, catalogValue, sheetValue };
}

function jsonNodeCount(value: unknown): number {
  const stack: unknown[] = [value];
  let count = 0;
  while (stack.length) {
    const current = stack.pop();
    count++;
    if (Array.isArray(current)) {
      for (const child of current) stack.push(child);
    } else if (current && typeof current === "object") {
      for (const child of Object.values(current)) stack.push(child);
    }
  }
  return count;
}

function expectFailure(
  mutate: (
    map: TargetScopedSemanticMapV1,
    catalog: AtomicRegionCatalog,
    sheet: ParsedSheet,
  ) => void,
  code: string,
) {
  const map = structuredClone(mapFor());
  const catalogValue = structuredClone(catalog());
  const sheetValue = structuredClone(sheet());
  mutate(map, catalogValue, sheetValue);
  const { result } = fixture(map, catalogValue, sheetValue);
  expect(result.ok).toBe(false);
  if (!result.ok) expect(result.code).toBe(code);
}

describe("target-scoped RecipeV02", () => {
  it("compiles and executes one logical table provider-free", () => {
    const { result, mapRaw, catalogRaw, sheetValue } = fixture();
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.envelope.recipe.version).toBe(TARGET_SCOPED_RECIPE_V02);
    expect(result.envelope.attachmentManifest.count).toBe(6);
    const execution = executeTargetScopedRecipeV02(result.envelope, {
      mapRaw,
      catalogRaw,
      sheet: sheetValue,
      source,
      trustedEnvelopeDigest: result.envelope.envelopeDigest,
    });
    expect(execution.version).toBe(TARGET_SCOPED_EXECUTION_V02);
    expect(execution.providerCalls).toBe(0);
    expect(execution.table.rows).toEqual([
      expect.objectContaining({
        "published value": 1,
        category: "A",
        group: "A",
        year: "2023",
      }),
      expect.objectContaining({
        "published value": 2,
        category: "A",
        group: "A",
        year: "2024",
      }),
    ]);
  });

  it("namespaces one physical source used by two dimensions", () => {
    const { result, mapRaw, catalogRaw, sheetValue } = fixture();
    if (!result.ok) throw new Error(result.message);
    const execution = executeTargetScopedRecipeV02(result.envelope, {
      mapRaw,
      catalogRaw,
      sheet: sheetValue,
      source,
      trustedEnvelopeDigest: result.envelope.envelopeDigest,
    });
    const [category, group] = execution.table.trace[0].attachments;
    expect(category.source.address).toBe("R2C1");
    expect(group.source.address).toBe("R2C1");
    expect(category.dimensionId).toBe("category");
    expect(group.dimensionId).toBe("group");
  });

  it("is deterministic under non-semantic declaration order", () => {
    const first = fixture();
    const reordered = structuredClone(mapFor());
    reordered.targetSets.reverse();
    reordered.sourceUniverses.reverse();
    reordered.attachments.reverse();
    reordered.vectors.reverse();
    reordered.targets.reverse();
    const second = fixture(reordered);
    if (!first.result.ok || !second.result.ok)
      throw new Error("compile failed");
    // Raw map bytes remain externally pinned and therefore change the outer
    // envelope; normalized semantic and RecipeV02 proofs remain identical.
    expect(second.result.envelope.map.digest).toBe(
      first.result.envelope.map.digest,
    );
    expect(second.result.envelope.recipeDigest).toBe(
      first.result.envelope.recipeDigest,
    );
    expect(second.result.envelope.logicalExecutionProof).toEqual(
      first.result.envelope.logicalExecutionProof,
    );
  });

  it("rejects equal/cascading competitors", () => {
    expectFailure((map, catalogValue, sheetValue) => {
      const category = catalogValue.candidates.find(
        (entry) => entry.id === "category",
      )!;
      if ("segments" in category)
        category.segments = ["R1C2:R1C2", "R2C1:R2C1"];
      const competitor = sheetValue.cells.find(
        (entry) => entry.address === "R1C2",
      )!;
      competitor.value = "A";
      competitor.formula = '= "A"';
      competitor.formatted = "A";
      const universe = map.sourceUniverses.find(
        (entry) => entry.id === "category-source",
      )!;
      universe.selectors = [{ address: "R1C2" }, { address: "R2C1" }];
      for (const binding of map.attachments.filter(
        (entry) => entry.dimensionId !== "year",
      ))
        binding.direction = "WNW";
    }, "TARGET_SCOPED_AMBIGUOUS_SOURCE");
  });

  it("rejects a nearer direct competitor rather than silently selecting it", () => {
    expectFailure((map, catalogValue, sheetValue) => {
      const values = catalogValue.candidates.find(
        (entry) => entry.id === "values",
      )!;
      const category = catalogValue.candidates.find(
        (entry) => entry.id === "category",
      )!;
      const years = catalogValue.candidates.find(
        (entry) => entry.id === "years",
      )!;
      if ("segments" in values) values.segments = ["R3C2:R3C3"];
      if ("segments" in category) category.segments = ["R3C1:R3C1"];
      if ("segments" in years) years.segments = ["R1C2:R2C3"];
      const r3c1 = sheetValue.cells.find((entry) => entry.address === "R3C1")!;
      const r3c2 = sheetValue.cells.find((entry) => entry.address === "R3C2")!;
      const r3c3 = sheetValue.cells.find((entry) => entry.address === "R3C3")!;
      r3c1.value = "A";
      r3c1.data_type = "string";
      r3c2.value = 3;
      r3c2.data_type = "numeric";
      r3c3.value = 4;
      r3c3.data_type = "numeric";
      sheetValue.nonEmptyCellCount += 3;
      map.targetSets[0].selectors = [{ range: "R3C2:R3C3" }];
      map.targets[0].address = "R3C2";
      map.targets[1].address = "R3C3";
      const categorySource = map.sourceUniverses.find(
        (entry) => entry.id === "category-source",
      )!;
      categorySource.selectors = [{ address: "R3C1" }];
      for (const binding of map.attachments.filter(
        (entry) => entry.dimensionId !== "year",
      ))
        binding.selectedAddress = "R3C1";
      const year2023 = map.sourceUniverses.find(
        (entry) => entry.id === "year-2023-source",
      )!;
      year2023.selectors = [{ address: "R1C2" }, { address: "R2C2" }];
    }, "TARGET_SCOPED_AMBIGUOUS_SOURCE");
  });

  it("rejects wrong direction", () => {
    expectFailure((map) => {
      map.attachments[0].direction = "N";
    }, "TARGET_SCOPED_AMBIGUOUS_SOURCE");
  });

  it.each([
    [null, "INVALID_DIMENSION_SOURCE"],
    [true, "INVALID_DIMENSION_SOURCE"],
    ["", "INVALID_DIMENSION_SOURCE"],
  ] as const)("rejects invalid source %p", (value, code) => {
    expectFailure((_map, _catalog, sheetValue) => {
      sheetValue.cells.find((entry) => entry.address === "R2C1")!.value = value;
      sheetValue.cells.find((entry) => entry.address === "R2C1")!.data_type =
        value === null
          ? "blank"
          : typeof value === "boolean"
            ? "boolean"
            : "string";
      sheetValue.nonEmptyCellCount = sheetValue.cells.filter(
        (entry) => entry.value !== null,
      ).length;
    }, code);
  });

  it("rejects source, target, and duplicate target ownership outside their exact parents", () => {
    expectFailure((map) => {
      map.attachments[0].selectedAddress = "R1C1";
    }, "SOURCE_OUTSIDE_PARENT");
    expectFailure((map) => {
      map.targets[0].address = "R3C3";
    }, "TARGET_OUTSIDE_PARENT");
    expectFailure((map) => {
      map.targetSets.push({
        id: "overlapping-targets",
        regionId: "values",
        selectors: [{ address: "R2C3" }],
      });
      map.targets[1].targetSetId = "overlapping-targets";
    }, "DUPLICATE_TARGET_OWNER");
  });

  it("rejects duplicate, missing and extra target ownership", () => {
    expectFailure((map) => {
      map.targets[1].address = map.targets[0].address;
    }, "DUPLICATE_TARGET");
    expectFailure((map) => {
      map.targets.pop();
    }, "TARGET_COVERAGE_MISMATCH");
    expectFailure((map, catalogValue, sheetValue) => {
      map.targetSets[0].selectors.push({ address: "R3C3" });
      const values = catalogValue.candidates.find(
        (entry) => entry.id === "values",
      )!;
      if ("segments" in values) values.segments.push("R3C3:R3C3");
      sheetValue.cells.find((entry) => entry.address === "R3C3")!.value = 3;
      sheetValue.cells.find((entry) => entry.address === "R3C3")!.data_type =
        "numeric";
      sheetValue.nonEmptyCellCount++;
    }, "TARGET_COVERAGE_MISMATCH");
  });

  it("rejects missing, duplicate, reordered and unused declarations", () => {
    expectFailure((map) => {
      map.vectors[0].attachmentIds.pop();
    }, "VECTOR_DIMENSION_MISSING");
    expectFailure((map) => {
      map.vectors[0].attachmentIds[1] = map.vectors[0].attachmentIds[0];
    }, "VECTOR_DIMENSION_ORDER_MISMATCH");
    expectFailure((map) => {
      map.vectors[0].attachmentIds.reverse();
    }, "VECTOR_DIMENSION_ORDER_MISMATCH");
    expectFailure((map) => {
      map.sourceUniverses.push({
        id: "unused-source",
        regionId: "years",
        selectors: [{ address: "R1C2" }],
      });
    }, "UNUSED_SOURCE_DECLARATION");
  });

  it("rejects external pin, catalog and source-context drift", () => {
    const base = fixture();
    expect(base.result.ok).toBe(true);
    const result = compileTargetScopedRecipeV02({
      mapRaw: base.mapRaw,
      expectedMapBytesDigest: `sha256:${"0".repeat(64)}`,
      catalogRaw: base.catalogRaw,
      expectedCatalogBytesDigest: digestTargetScopedBytes(base.catalogRaw),
      sheet: base.sheetValue,
      source,
    });
    expect(result).toMatchObject({
      ok: false,
      code: "MAP_EXTERNAL_PIN_MISMATCH",
    });
    expectFailure((map) => {
      map.source.workbookDigest = `sha256:${"2".repeat(64)}`;
    }, "SOURCE_CONTEXT_MISMATCH");
  });

  it("rejects trusted-envelope and coherent proof tamper", () => {
    const base = fixture();
    if (!base.result.ok) throw new Error(base.result.message);
    const envelope = base.result.envelope;
    expect(() =>
      executeTargetScopedRecipeV02(envelope, {
        mapRaw: base.mapRaw,
        catalogRaw: base.catalogRaw,
        sheet: base.sheetValue,
        source,
        trustedEnvelopeDigest: `sha256:${"0".repeat(64)}`,
      }),
    ).toThrow("TRUSTED_ENVELOPE_DIGEST_MISMATCH");
    const tampered = structuredClone(envelope);
    tampered.logicalExecutionProof.digest = `sha256:${"3".repeat(64)}`;
    expect(() =>
      executeTargetScopedRecipeV02(tampered, {
        mapRaw: base.mapRaw,
        catalogRaw: base.catalogRaw,
        sheet: base.sheetValue,
        source,
        trustedEnvelopeDigest: envelope.envelopeDigest,
      }),
    ).toThrow("TRUSTED_ENVELOPE_DIGEST_MISMATCH");

    const coherentlyRehashed = structuredClone(envelope);
    coherentlyRehashed.attachmentManifest.digest = `sha256:${"2".repeat(64)}`;
    coherentlyRehashed.envelopeDigest =
      digestTargetScopedEnvelopeV02(coherentlyRehashed);
    expect(() =>
      executeTargetScopedRecipeV02(coherentlyRehashed, {
        mapRaw: base.mapRaw,
        catalogRaw: base.catalogRaw,
        sheet: base.sheetValue,
        source,
        trustedEnvelopeDigest: coherentlyRehashed.envelopeDigest,
      }),
    ).toThrow("ENVELOPE_RECOMPILE_MISMATCH");
  });

  it("binds complete typed sheet provenance and negative zero", () => {
    const base = fixture();
    if (!base.result.ok) throw new Error(base.result.message);
    const envelope = base.result.envelope;
    const mutations: Array<(changed: ParsedSheet) => void> = [
      (changed) => {
        changed.cells.find((entry) => entry.address === "R1C2")!.formula =
          '="changed"';
      },
      (changed) => {
        changed.cells.find((entry) => entry.address === "R1C2")!.formatted =
          "changed";
      },
      (changed) => {
        changed.cells.find((entry) => entry.address === "R2C1")!.comment =
          "changed";
      },
      (changed) => {
        changed.cells.find((entry) => entry.address === "R2C1")!.hyperlink =
          "https://example.invalid";
      },
      (changed) => {
        changed.cells.find((entry) => entry.address === "R2C1")!.style = {
          bold: true,
        };
      },
      (changed) => {
        changed.merges = [{ parent: "R1C2", range: "R1C2:R1C3" }];
      },
      (changed) => {
        changed.cells.find((entry) => entry.address === "R1C2")!.data_type =
          "error";
      },
    ];
    for (const mutate of mutations) {
      const changed = structuredClone(base.sheetValue);
      mutate(changed);
      expect(() =>
        executeTargetScopedRecipeV02(envelope, {
          mapRaw: base.mapRaw,
          catalogRaw: base.catalogRaw,
          sheet: changed,
          source,
          trustedEnvelopeDigest: envelope.envelopeDigest,
        }),
      ).toThrow("ENVELOPE_RECOMPILE_MISMATCH");
    }

    const negativeMap = mapFor();
    const negativeSheet = sheet();
    negativeSheet.cells.find((entry) => entry.address === "R2C2")!.value = -0;
    const negative = fixture(negativeMap, catalog(), negativeSheet);
    if (!negative.result.ok) throw new Error(negative.result.message);
    const negativeEnvelope = negative.result.envelope;
    const zeroSheet = structuredClone(negativeSheet);
    zeroSheet.cells.find((entry) => entry.address === "R2C2")!.value = 0;
    expect(() =>
      executeTargetScopedRecipeV02(negativeEnvelope, {
        mapRaw: negative.mapRaw,
        catalogRaw: negative.catalogRaw,
        sheet: zeroSheet,
        source,
        trustedEnvelopeDigest: negativeEnvelope.envelopeDigest,
      }),
    ).toThrow("ENVELOPE_RECOMPILE_MISMATCH");
  });

  it("round-trips execution-bound date and error typed strings", () => {
    const typedSheet = sheet();
    typedSheet.cells.find((entry) => entry.address === "R2C2")!.data_type =
      "date";
    typedSheet.cells.find((entry) => entry.address === "R2C2")!.value =
      "2023-06-30";
    typedSheet.cells.find((entry) => entry.address === "R2C1")!.data_type =
      "error";
    typedSheet.cells.find((entry) => entry.address === "R2C1")!.value = "#N/A";
    const typed = fixture(mapFor(), catalog(), typedSheet);
    if (!typed.result.ok) throw new Error(typed.result.message);
    const execution = executeTargetScopedRecipeV02(typed.result.envelope, {
      mapRaw: typed.mapRaw,
      catalogRaw: typed.catalogRaw,
      sheet: typedSheet,
      source,
      trustedEnvelopeDigest: typed.result.envelope.envelopeDigest,
    });
    expect(execution.table.rows[0]).toEqual(
      expect.objectContaining({
        "published value": "2023-06-30",
        category: "#N/A",
      }),
    );
    expect(execution.table.trace[0].target.data_type).toBe("date");
    expect(execution.table.trace[0].attachments[0].source.data_type).toBe(
      "error",
    );
  });

  it("rejects unsafe logical output names", () => {
    expectFailure((map) => {
      map.logicalTable.valuesName = "__proto__";
    }, "TARGET_SCOPED_MAP_INVALID");
  });

  it("strictly validates supplied execution and returns no aliases", () => {
    const base = fixture();
    if (!base.result.ok) throw new Error(base.result.message);
    const envelope = base.result.envelope;
    const execution = executeTargetScopedRecipeV02(envelope, {
      mapRaw: base.mapRaw,
      catalogRaw: base.catalogRaw,
      sheet: base.sheetValue,
      source,
      trustedEnvelopeDigest: envelope.envelopeDigest,
    });
    const supplied = structuredClone(execution) as any;
    supplied.table.trace[0].forged = undefined;
    expect(() =>
      executeTargetScopedRecipeV02(envelope, {
        mapRaw: base.mapRaw,
        catalogRaw: base.catalogRaw,
        sheet: base.sheetValue,
        source,
        trustedEnvelopeDigest: envelope.envelopeDigest,
        suppliedExecution: supplied,
      }),
    ).toThrow("SUPPLIED_EXECUTION_RESOURCE_LIMIT");
    const clean = structuredClone(execution);
    const returned = executeTargetScopedRecipeV02(envelope, {
      mapRaw: base.mapRaw,
      catalogRaw: base.catalogRaw,
      sheet: base.sheetValue,
      source,
      trustedEnvelopeDigest: envelope.envelopeDigest,
      suppliedExecution: clean,
    });
    expect(returned).not.toBe(clean);
    expect(returned.table.rows[0]).not.toBe(clean.table.rows[0]);
  });

  it("strictly parses literal RecipeV02, envelope, and execution formats", () => {
    const compiled = fixture();
    if (!compiled.result.ok) throw new Error(compiled.result.message);
    const envelope = compiled.result.envelope;
    expect(
      parseTargetScopedRecipeV02(JSON.stringify(envelope.recipe)).version,
    ).toBe(TARGET_SCOPED_RECIPE_V02);
    expect(parseTargetScopedCompilationEnvelopeV02(envelope)).toEqual(envelope);
    const envelopeMeasurement = measureTargetScopedValue(
      envelope,
      500_000,
      32 * 1024 * 1024,
    );
    expect(envelopeMeasurement.bytes).toBe(
      Buffer.byteLength(JSON.stringify(envelope)),
    );
    expect(() =>
      assertTargetScopedValueBudget(
        envelope,
        envelopeMeasurement.nodes,
        envelopeMeasurement.bytes,
      ),
    ).not.toThrow();
    expect(() =>
      assertTargetScopedValueBudget(
        envelope,
        envelopeMeasurement.nodes - 1,
        envelopeMeasurement.bytes,
      ),
    ).toThrow();
    expect(() =>
      assertTargetScopedValueBudget(
        envelope,
        envelopeMeasurement.nodes,
        envelopeMeasurement.bytes - 1,
      ),
    ).toThrow();
    const execution = executeTargetScopedRecipeV02(envelope, {
      mapRaw: compiled.mapRaw,
      catalogRaw: compiled.catalogRaw,
      sheet: compiled.sheetValue,
      source,
      trustedEnvelopeDigest: envelope.envelopeDigest,
    });
    expect(parseTargetScopedExecutionV02(execution, envelope.recipe)).toEqual(
      execution,
    );
    expect(() =>
      parseTargetScopedRecipeV02(
        JSON.stringify({ ...envelope.recipe, unknown: true }),
      ),
    ).toThrow();
    expect(() =>
      parseTargetScopedCompilationEnvelopeV02({ ...envelope, unknown: true }),
    ).toThrow();
    const duplicateRecipe = structuredClone(envelope.recipe);
    duplicateRecipe.sourceUniverses[0].id =
      duplicateRecipe.sourceUniverses[1].id;
    expect(() =>
      parseTargetScopedRecipeV02(JSON.stringify(duplicateRecipe)),
    ).toThrow();
  });

  it("mutually rejects V01/B1 and target-scoped formats", () => {
    const targetRaw = fixture().mapRaw;
    expect(() => parseSemanticTableMapV2Json(targetRaw)).toThrow();
    expect(() =>
      parseTargetScopedSemanticMapV1(
        JSON.stringify({ version: "semantic-table-map-v2" }),
      ),
    ).toThrow();
    const validV01 = {
      version: "0.1",
      sheet: "Sheet 1",
      tables: [
        {
          name: "Observations",
          values: { name: "published value", cells: "R2C2" },
          headers: [{ name: "category", direction: "W", cells: "R2C1" }],
        },
      ],
    };
    expect(() => parseRecipe(validV01)).not.toThrow();
    expect(() =>
      parseTargetScopedRecipeV02(JSON.stringify(validV01)),
    ).toThrow();
    const compiled = fixture();
    if (!compiled.result.ok) throw new Error(compiled.result.message);
    const compiledEnvelope = compiled.result.envelope;
    expect(() => parseRecipe(compiledEnvelope.recipe)).toThrow();

    const validV1Map = {
      version: "semantic-table-map-v1",
      table: {
        name: "Observations",
        values: { name: "published value", regions: ["values"] },
        dimensions: [
          { name: "category", memberRegions: ["category"], direction: "W" },
        ],
      },
    };
    expect(() =>
      parseSemanticTableMapJson(JSON.stringify(validV1Map)),
    ).not.toThrow();
    expect(() =>
      parseTargetScopedSemanticMapV1(JSON.stringify(validV1Map)),
    ).toThrow();

    const validV2Map = {
      version: "semantic-table-map-v2",
      catalog: {
        version: "semantic-region-catalog-v5-adjacent-year-aware",
        digest: `sha256:${"1".repeat(64)}`,
      },
      logicalTable: {
        id: "observations",
        name: "Observations",
        values: {
          id: "published-value",
          name: "published value",
          target: [{ regionId: "values", selectors: [{ range: "R2C2:R2C2" }] }],
        },
        dimensions: [{ id: "category", name: "category" }],
      },
      panels: [
        {
          id: "panel-one",
          order: 1,
          tableName: "Observations panel one",
          target: [{ regionId: "values", selectors: [{ range: "R2C2:R2C2" }] }],
          dimensions: [
            {
              id: "category",
              source: [
                { regionId: "category", selectors: [{ range: "R2C1:R2C1" }] },
              ],
              direction: "W",
            },
          ],
        },
      ],
    };
    expect(() =>
      parseSemanticTableMapV2Json(JSON.stringify(validV2Map)),
    ).not.toThrow();
    expect(() =>
      parseTargetScopedSemanticMapV1(JSON.stringify(validV2Map)),
    ).toThrow();
    expect(() => parseSemanticTableMapJson(targetRaw)).toThrow();
    expect(() => parseSemanticTableMapV2Json(targetRaw)).toThrow();
  });

  it("rejects every target/source role intersection but permits non-target cross-dimension reuse", () => {
    expectFailure((map, catalogValue) => {
      const category = catalogValue.candidates.find(
        (entry) => entry.id === "category",
      )!;
      if ("segments" in category) category.segments.push("R2C2:R2C2");
      map.sourceUniverses[0].selectors.push({ address: "R2C2" });
    }, "TARGET_SOURCE_ROLE_OVERLAP");
  });

  it("strictly rejects execution scalar, array, metadata, candidate, field and type spoofs", () => {
    const base = fixture();
    if (!base.result.ok) throw new Error(base.result.message);
    const envelope = base.result.envelope;
    const execution = executeTargetScopedRecipeV02(envelope, {
      mapRaw: base.mapRaw,
      catalogRaw: base.catalogRaw,
      sheet: base.sheetValue,
      source,
      trustedEnvelopeDigest: envelope.envelopeDigest,
    });
    const mutations: Array<(value: any) => void> = [
      (value) => {
        value.table.rows[0]["published value"] = { $number: "1" };
      },
      (value) => {
        value.table.id = "forged";
      },
      (value) => {
        value.table.trace[0].attachments[0].direction = "N";
      },
      (value) => {
        value.table.trace[0].attachments[0].candidates[0] = "R1C1";
      },
      (value) => {
        value.table.trace[0].attachments[0].source.data_type = "forged";
      },
      (value) => {
        value.table.trace[0].attachments[0].extra = true;
      },
      (value) => {
        value.source.workbookDigest = "forged";
      },
      (value) => {
        Object.defineProperty(value.table.rows, "forged", {
          value: true,
          enumerable: true,
        });
      },
      (value) => {
        Object.defineProperty(value.table.trace, Symbol("forged"), {
          value: true,
        });
      },
      (value) => {
        Object.setPrototypeOf(
          value.table.trace[0].attachments,
          Object.create(Array.prototype),
        );
      },
    ];
    for (const mutate of mutations) {
      const forged: any = structuredClone(execution);
      mutate(forged);
      expect(() =>
        parseTargetScopedExecutionV02(forged, envelope.recipe),
      ).toThrow();
    }
  });

  it("uses injective canonical types and rejects forged style provenance", () => {
    expect(digestTargetScopedCanonical({ value: 1 })).not.toBe(
      digestTargetScopedCanonical({ value: { $number: "1" } }),
    );
    const base = fixture();
    if (!base.result.ok) throw new Error(base.result.message);
    const forged = structuredClone(base.sheetValue);
    (forged.cells[0] as any).style = { fontSize: { $number: "12" } };
    const result = compileTargetScopedRecipeV02({
      mapRaw: base.mapRaw,
      expectedMapBytesDigest: digestTargetScopedBytes(base.mapRaw),
      catalogRaw: base.catalogRaw,
      expectedCatalogBytesDigest: digestTargetScopedBytes(base.catalogRaw),
      sheet: forged,
      source,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("SHEET_STYLE_SCHEMA_INVALID");
  });

  it("parses/clones the trusted envelope without caller aliases", () => {
    const base = fixture();
    if (!base.result.ok) throw new Error(base.result.message);
    const parsed = parseTargetScopedCompilationEnvelopeV02(
      base.result.envelope,
    );
    parsed.recipe.targets[0].vectorId = "vector-2024";
    expect(base.result.envelope.recipe.targets[0].vectorId).toBe("vector-2023");
    base.result.envelope.recipe.targets[1].vectorId = "vector-2023";
    expect(parsed.recipe.targets[1].vectorId).toBe("vector-2024");
  });

  it("checks practical exact/one-over resource budgets without oversized allocation", () => {
    for (const [kind, limit] of Object.entries(TARGET_SCOPED_LIMITS)) {
      expect(() =>
        assertTargetScopedCountLimit(
          kind as keyof typeof TARGET_SCOPED_LIMITS,
          limit,
        ),
      ).not.toThrow();
      expect(() =>
        assertTargetScopedCountLimit(
          kind as keyof typeof TARGET_SCOPED_LIMITS,
          limit + 1,
        ),
      ).toThrow();
    }
    expect(() => assertTargetScopedRawJsonBudget("[null]", 2)).not.toThrow();
    expect(() => assertTargetScopedRawJsonBudget("[null]", 1)).toThrow();
    expect(() => assertTargetScopedValueBudget([null], 2, 6)).not.toThrow();
    expect(() => assertTargetScopedValueBudget([null], 2, 5)).toThrow();
    expect(() => assertTargetScopedValueBudget([null], 1, 6)).toThrow();
    const escaped = { 'a"': "line\n\ud800" };
    const measurement = measureTargetScopedValue(escaped, 10, 100);
    expect(measurement.bytes).toBe(Buffer.byteLength(JSON.stringify(escaped)));
    expect(() =>
      assertTargetScopedValueBudget(
        escaped,
        measurement.nodes,
        measurement.bytes,
      ),
    ).not.toThrow();
    expect(() =>
      assertTargetScopedValueBudget(
        escaped,
        measurement.nodes,
        measurement.bytes - 1,
      ),
    ).toThrow();
  });

  it("rejects huge sparse arrays and proxies before trappable or proportional traversal", () => {
    const sparse: unknown[] = [];
    sparse.length = 100_000_000;
    expect(() =>
      assertTargetScopedValueBudget(
        sparse,
        MAX_TARGET_SCOPED_EXECUTION_NODES,
        MAX_TARGET_SCOPED_EXECUTION_BYTES,
      ),
    ).toThrow();

    const trap = () => {
      throw new Error("PROXY_TRAP_WAS_REACHED");
    };
    const base = fixture();
    if (!base.result.ok) throw new Error(base.result.message);
    const envelope = base.result.envelope;
    const proxiedEnvelope = new Proxy(envelope, {
      getPrototypeOf: trap,
      ownKeys: trap,
    });
    expect(() =>
      parseTargetScopedCompilationEnvelopeV02(proxiedEnvelope),
    ).toThrow("ENVELOPE_RESOURCE_LIMIT");
    expect(() => digestTargetScopedEnvelopeV02(proxiedEnvelope)).toThrow(
      "PROXY_ENVELOPE_REJECTED",
    );
    const proxiedCanonical = new Proxy(
      { value: 1 },
      {
        getPrototypeOf: trap,
        ownKeys: trap,
      },
    );
    expect(() => digestTargetScopedCanonical(proxiedCanonical)).toThrow(
      "PROXY_CANONICAL_VALUE",
    );
    const execution = executeTargetScopedRecipeV02(envelope, {
      mapRaw: base.mapRaw,
      catalogRaw: base.catalogRaw,
      sheet: base.sheetValue,
      source,
      trustedEnvelopeDigest: envelope.envelopeDigest,
    });
    expect(() =>
      parseTargetScopedExecutionV02(
        new Proxy(execution, { getPrototypeOf: trap, ownKeys: trap }),
        envelope.recipe,
      ),
    ).toThrow("SUPPLIED_EXECUTION_RESOURCE_LIMIT");
    const styleSheet = structuredClone(base.sheetValue);
    styleSheet.cells[0].style = new Proxy(
      {},
      { getPrototypeOf: trap, ownKeys: trap },
    );
    const styleResult = compileTargetScopedRecipeV02({
      mapRaw: base.mapRaw,
      expectedMapBytesDigest: digestTargetScopedBytes(base.mapRaw),
      catalogRaw: base.catalogRaw,
      expectedCatalogBytesDigest: digestTargetScopedBytes(base.catalogRaw),
      sheet: styleSheet,
      source,
    });
    expect(styleResult.ok).toBe(false);
    if (!styleResult.ok)
      expect(styleResult.code).toBe("SHEET_STYLE_SCHEMA_INVALID");
    const proxiedSheet = new Proxy(base.sheetValue, {
      get: trap,
      getPrototypeOf: trap,
      ownKeys: trap,
    });
    const result = compileTargetScopedRecipeV02({
      mapRaw: base.mapRaw,
      expectedMapBytesDigest: digestTargetScopedBytes(base.mapRaw),
      catalogRaw: base.catalogRaw,
      expectedCatalogBytesDigest: digestTargetScopedBytes(base.catalogRaw),
      sheet: proxiedSheet,
      source,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.code).toBe("SHEET_PROXY_REJECTED");
  });

  it("accepts faithful parseWorkbook optional undefined fields and rejects unknown undefined", () => {
    const faithful = sheet();
    for (const entry of faithful.cells) {
      entry.formula ??= null;
      entry.formatted ??= null;
      entry.comment ??= null;
      entry.hyperlink ??= null;
      if (!Object.hasOwn(entry, "style")) entry.style = undefined;
      if (!Object.hasOwn(entry, "merge")) entry.merge = undefined;
    }
    const accepted = fixture(mapFor(), catalog(), faithful).result;
    expect(accepted.ok).toBe(true);
    const forged = structuredClone(faithful) as any;
    forged.cells[0].unknown = undefined;
    const rejected = fixture(mapFor(), catalog(), forged).result;
    expect(rejected.ok).toBe(false);
    if (!rejected.ok) expect(rejected.code).toBe("SHEET_CELL_SCHEMA_INVALID");
  });

  it("uses the compiler operation preflight at the exact and one-over boundary", () => {
    const targetCount = 8_000;
    const sourceCount = 250;
    const targetStart = sourceCount + 1;
    const cells = [
      ...Array.from({ length: sourceCount }, (_, index) =>
        cell(`R${index + 1}C1`, `source ${index + 1}`),
      ),
      ...Array.from({ length: targetCount }, (_, index) =>
        cell(`R${targetStart + index}C1`, index + 1),
      ),
    ];
    const operationSheet: ParsedSheet = {
      name: "Sheet 1",
      usedRange: `R1C1:R${sourceCount + targetCount}C1`,
      rowCount: sourceCount + targetCount,
      columnCount: 1,
      nonEmptyCellCount: cells.length,
      cells,
      merges: [],
    };
    const operationCatalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v5-adjacent-year-aware",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "values",
          segments: [`R${targetStart}C1:R${sourceCount + targetCount}C1`],
          kinds: [],
          roleHints: [],
          formatSignatures: [],
          formatting: [],
          selectedCellCount: targetCount,
          nonblankCount: targetCount,
          valueLikeCount: targetCount,
          sample: [],
        },
        {
          id: "headers",
          segments: [`R1C1:R${sourceCount}C1`],
          kinds: [],
          roleHints: [],
          formatSignatures: [],
          formatting: [],
          selectedCellCount: sourceCount,
          nonblankCount: sourceCount,
          valueLikeCount: 0,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
      observationPanelCount: 1,
      formatFactCount: 0,
      cellDataFactCount: 0,
    };
    const exactMap: TargetScopedSemanticMapV1 = {
      version: "target-scoped-semantic-map-v1",
      catalog: {
        version: operationCatalog.version,
        bytesDigest: "",
        contentDigest: digestAtomicRegionCatalog(operationCatalog),
      },
      source,
      logicalTable: {
        id: "observations",
        name: "Observations",
        valuesName: "published value",
        dimensions: [{ id: "dimension", name: "dimension" }],
      },
      targetSets: [
        {
          id: "targets",
          regionId: "values",
          selectors: [
            { range: `R${targetStart}C1:R${sourceCount + targetCount}C1` },
          ],
        },
      ],
      sourceUniverses: [
        {
          id: "u249",
          regionId: "headers",
          selectors: [{ range: "R1C1:R249C1" }],
        },
      ],
      attachments: [
        {
          id: "a249",
          dimensionId: "dimension",
          direction: "N",
          selectedAddress: "R1C1",
          universeId: "u249",
        },
      ],
      vectors: [{ id: "v249", attachmentIds: ["a249"] }],
      targets: Array.from({ length: targetCount }, (_, index) => ({
        address: `R${targetStart + index}C1`,
        targetSetId: "targets",
        vectorId: "v249",
      })),
    };
    expect(targetCount * 250).toBe(MAX_TARGET_SCOPED_RESOLUTION_OPERATIONS);
    const exact = fixture(exactMap, operationCatalog, operationSheet).result;
    expect(exact.ok).toBe(false);
    if (!exact.ok) expect(exact.code).toBe("TARGET_SCOPED_AMBIGUOUS_SOURCE");

    const overMap = structuredClone(exactMap);
    overMap.sourceUniverses.push({
      id: "u250",
      regionId: "headers",
      selectors: [{ range: "R1C1:R250C1" }],
    });
    overMap.attachments.push({
      id: "a250",
      dimensionId: "dimension",
      direction: "N",
      selectedAddress: "R1C1",
      universeId: "u250",
    });
    overMap.vectors.push({ id: "v250", attachmentIds: ["a250"] });
    overMap.targets[0].vectorId = "v250";
    const over = fixture(overMap, operationCatalog, operationSheet).result;
    expect(over.ok).toBe(false);
    if (!over.ok) expect(over.code).toBe("RESOLUTION_OPERATION_LIMIT");
  }, 30_000);

  it("fits the 8,192-target boundary, including the measured 7,200 maximum", () => {
    const started = performance.now();
    const rssBefore = process.memoryUsage().rss;
    const count = MAX_TARGET_SCOPED_TARGETS;
    const cells = [cell("R1C1", "All")];
    const targets = [];
    for (let row = 2; row <= count + 1; row++) {
      cells.push(cell(`R${row}C1`, row - 1));
      targets.push({
        address: `R${row}C1`,
        targetSetId: "targets",
        vectorId: "all-vector",
      });
    }
    const largeSheet: ParsedSheet = {
      name: "Sheet 1",
      usedRange: `R1C1:R${count + 1}C1`,
      rowCount: count + 1,
      columnCount: 1,
      nonEmptyCellCount: cells.length,
      cells,
      merges: [],
    };
    const largeCatalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v5-adjacent-year-aware",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "values",
          segments: [`R2C1:R${count + 1}C1`],
          kinds: [],
          roleHints: [],
          formatSignatures: [],
          formatting: [],
          selectedCellCount: count,
          nonblankCount: count,
          valueLikeCount: count,
          sample: [],
        },
        {
          id: "header",
          segments: ["R1C1:R1C1"],
          kinds: [],
          roleHints: [],
          formatSignatures: [],
          formatting: [],
          selectedCellCount: 1,
          nonblankCount: 1,
          valueLikeCount: 0,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
      observationPanelCount: 1,
      formatFactCount: 0,
      cellDataFactCount: 0,
    };
    const largeMap: TargetScopedSemanticMapV1 = {
      version: "target-scoped-semantic-map-v1",
      catalog: {
        version: largeCatalog.version,
        bytesDigest: "",
        contentDigest: digestAtomicRegionCatalog(largeCatalog),
      },
      source,
      logicalTable: {
        id: "observations",
        name: "Observations",
        valuesName: "published value",
        dimensions: [{ id: "category", name: "category" }],
      },
      targetSets: [
        {
          id: "targets",
          regionId: "values",
          selectors: [{ range: `R2C1:R${count + 1}C1` }],
        },
      ],
      sourceUniverses: [
        {
          id: "header-source",
          regionId: "header",
          selectors: [{ address: "R1C1" }],
        },
      ],
      attachments: [
        {
          id: "all-binding",
          dimensionId: "category",
          direction: "N",
          selectedAddress: "R1C1",
          universeId: "header-source",
        },
      ],
      vectors: [{ id: "all-vector", attachmentIds: ["all-binding"] }],
      targets,
    };
    const large = fixture(largeMap, largeCatalog, largeSheet);
    expect(large.result.ok).toBe(true);
    if (!large.result.ok) return;
    const recipeBytes = Buffer.byteLength(
      JSON.stringify(large.result.envelope.recipe),
    );
    const envelopeBytes = Buffer.byteLength(
      JSON.stringify(large.result.envelope),
    );
    expect(recipeBytes).toBeLessThan(MAX_TARGET_SCOPED_JSON_BYTES);
    expect(large.result.envelope.targetManifest.count).toBe(count);
    if (process.env.TARGET_SCOPED_MEASURE === "1") {
      console.info(
        JSON.stringify({
          targets: count,
          bindings: large.result.envelope.attachmentManifest.count,
          operations: large.result.envelope.attachmentManifest.operations,
          recipeBytes,
          recipeNodes: jsonNodeCount(large.result.envelope.recipe),
          envelopeBytes,
          envelopeNodes: jsonNodeCount(large.result.envelope),
          elapsedMs: Math.round(performance.now() - started),
          rssDeltaBytes: process.memoryUsage().rss - rssBefore,
        }),
      );
    }
  }, 30_000);

  it("fits the measured 7,200-target, five-dimension unique-vector shape", () => {
    const started = performance.now();
    const rssBefore = process.memoryUsage().rss;
    const count = 7_200;
    const dimensionCount = 5;
    // The custody oracle's measured 7,200-target member has 297 distinct
    // dimension/source choices across five dimensions.
    const choicesByDimension = [200, 36, 20, 20, 21];
    const sourceCount = choicesByDimension.reduce(
      (sum, value) => sum + value,
      0,
    );
    const targetStartRow = sourceCount + 1;
    const cells = Array.from({ length: sourceCount }, (_, index) =>
      cell(`R${index + 1}C1`, `source ${index + 1}`),
    );
    const targets: TargetScopedSemanticMapV1["targets"] = [];
    const vectors: TargetScopedSemanticMapV1["vectors"] = [];
    for (let index = 0; index < count; index++) {
      const row = index + targetStartRow;
      cells.push(cell(`R${row}C1`, index + 1));
      const attachmentIds = Array.from(
        { length: dimensionCount },
        (_, dimension) => {
          const choice =
            dimension === 0
              ? index % choicesByDimension[dimension]
              : dimension === 1
                ? Math.floor(index / choicesByDimension[0]) %
                  choicesByDimension[dimension]
                : index % choicesByDimension[dimension];
          return `d${dimension + 1}-a${choice}`;
        },
      );
      const vectorId = `vector-${index + 1}`;
      vectors.push({ id: vectorId, attachmentIds });
      targets.push({
        address: `R${row}C1`,
        targetSetId: "targets",
        vectorId,
      });
    }
    const largeSheet: ParsedSheet = {
      name: "Sheet 1",
      usedRange: `R1C1:R${count + sourceCount}C1`,
      rowCount: count + sourceCount,
      columnCount: 1,
      nonEmptyCellCount: cells.length,
      cells,
      merges: [],
    };
    const largeCatalog: AtomicRegionCatalog = {
      version: "semantic-region-catalog-v5-adjacent-year-aware",
      sheet: "Sheet 1",
      candidates: [
        {
          id: "values",
          segments: [`R${targetStartRow}C1:R${count + sourceCount}C1`],
          kinds: [],
          roleHints: [],
          formatSignatures: [],
          formatting: [],
          selectedCellCount: count,
          nonblankCount: count,
          valueLikeCount: count,
          sample: [],
        },
        {
          id: "header",
          segments: [`R1C1:R${sourceCount}C1`],
          kinds: [],
          roleHints: [],
          formatSignatures: [],
          formatting: [],
          selectedCellCount: sourceCount,
          nonblankCount: sourceCount,
          valueLikeCount: 0,
          sample: [],
        },
      ],
      omittedCandidateCount: 0,
      observationPanelCount: 1,
      formatFactCount: 0,
      cellDataFactCount: 0,
    };
    const dimensions = Array.from({ length: dimensionCount }, (_, index) => ({
      id: `d${index + 1}`,
      name: `dimension ${index + 1}`,
    }));
    const sourceUniverses: TargetScopedSemanticMapV1["sourceUniverses"] = [];
    const attachments: TargetScopedSemanticMapV1["attachments"] = [];
    let sourceOffset = 0;
    for (let dimension = 0; dimension < dimensionCount; dimension++) {
      for (let choice = 0; choice < choicesByDimension[dimension]; choice++) {
        const id = `d${dimension + 1}-a${choice}`;
        const universeId = `d${dimension + 1}-u${choice}`;
        const selectedAddress = `R${sourceOffset + choice + 1}C1`;
        sourceUniverses.push({
          id: universeId,
          regionId: "header",
          selectors: [{ address: selectedAddress }],
        });
        attachments.push({
          id,
          dimensionId: `d${dimension + 1}`,
          direction: "N",
          selectedAddress,
          universeId,
        });
      }
      sourceOffset += choicesByDimension[dimension];
    }
    const largeMap: TargetScopedSemanticMapV1 = {
      version: "target-scoped-semantic-map-v1",
      catalog: {
        version: largeCatalog.version,
        bytesDigest: "",
        contentDigest: digestAtomicRegionCatalog(largeCatalog),
      },
      source,
      logicalTable: {
        id: "observations",
        name: "Observations",
        valuesName: "published value",
        dimensions,
      },
      targetSets: [
        {
          id: "targets",
          regionId: "values",
          selectors: [
            { range: `R${targetStartRow}C1:R${count + sourceCount}C1` },
          ],
        },
      ],
      sourceUniverses,
      attachments,
      vectors,
      targets,
    };
    const large = fixture(largeMap, largeCatalog, largeSheet);
    const result = large.result;
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.envelope.targetManifest.count).toBe(count);
    expect(result.envelope.attachmentManifest.count).toBe(
      count * dimensionCount,
    );
    const recipeBytes = Buffer.byteLength(
      JSON.stringify(result.envelope.recipe),
    );
    expect(recipeBytes).toBeLessThan(MAX_TARGET_SCOPED_JSON_BYTES);
    const envelopeNodes = jsonNodeCount(result.envelope);
    expect(envelopeNodes).toBeLessThanOrEqual(Math.floor(500_000 * 0.8));
    const execution = executeTargetScopedRecipeV02(result.envelope, {
      mapRaw: large.mapRaw,
      catalogRaw: large.catalogRaw,
      sheet: largeSheet,
      source,
      trustedEnvelopeDigest: result.envelope.envelopeDigest,
    });
    const executionMeasurement = measureTargetScopedValue(
      execution,
      MAX_TARGET_SCOPED_EXECUTION_NODES,
      MAX_TARGET_SCOPED_EXECUTION_BYTES,
    );
    expect(executionMeasurement.nodes).toBeLessThanOrEqual(
      Math.floor(MAX_TARGET_SCOPED_EXECUTION_NODES * 0.8),
    );
    expect(executionMeasurement.bytes).toBeLessThanOrEqual(
      Math.floor(MAX_TARGET_SCOPED_EXECUTION_BYTES * 0.8),
    );
    expect(executionMeasurement.bytes).toBe(
      Buffer.byteLength(JSON.stringify(execution)),
    );
    expect(() =>
      parseTargetScopedExecutionV02(execution, result.envelope.recipe),
    ).not.toThrow();
    expect(() =>
      assertTargetScopedValueBudget(
        execution,
        executionMeasurement.nodes,
        executionMeasurement.bytes,
      ),
    ).not.toThrow();
    expect(() =>
      assertTargetScopedValueBudget(
        execution,
        executionMeasurement.nodes - 1,
        executionMeasurement.bytes,
      ),
    ).toThrow();
    expect(() =>
      assertTargetScopedValueBudget(
        execution,
        executionMeasurement.nodes,
        executionMeasurement.bytes - 1,
      ),
    ).toThrow();
    if (process.env.TARGET_SCOPED_MEASURE === "1") {
      console.info(
        JSON.stringify({
          shape: "measured-7200x5",
          targets: count,
          vectors: vectors.length,
          attachmentChoices: attachments.length,
          bindings: result.envelope.attachmentManifest.count,
          operations: result.envelope.attachmentManifest.operations,
          recipeBytes,
          recipeNodes: jsonNodeCount(result.envelope.recipe),
          envelopeBytes: Buffer.byteLength(JSON.stringify(result.envelope)),
          envelopeNodes,
          executionBytes: executionMeasurement.bytes,
          executionNodes: executionMeasurement.nodes,
          elapsedMs: Math.round(performance.now() - started),
          rssDeltaBytes: process.memoryUsage().rss - rssBefore,
        }),
      );
    }
  }, 30_000);

  it("rejects 8,193 targets at the fixed boundary", () => {
    const map = mapFor() as any;
    map.targets = Array.from(
      { length: MAX_TARGET_SCOPED_TARGETS + 1 },
      (_, index) => ({
        address: `R${index + 1}C1`,
        targetSetId: "targets",
        vectorId: "vector-2023",
      }),
    );
    expect(() => parseTargetScopedSemanticMapV1(JSON.stringify(map))).toThrow();
  });
});
