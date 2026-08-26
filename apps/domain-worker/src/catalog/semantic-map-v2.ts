/* Atomic multi-panel semantic map. Compiles to the existing CellRoleSketch v0.2 / RecipeV01 runtime. */
import { createHash } from "node:crypto";
import { z } from "zod";
import {
  boundingRangeOf,
  expandRange,
  formatCell,
  formatRange,
  parseCell,
  parseRange,
} from "../address.js";
import type { CompactSemanticContext } from "../context/compactContext.js";
import { contextCells, semanticDirectionSchema } from "./semantic-map-v1.js";
import type { SemanticDirection } from "./semantic-map-v1.js";
import {
  CELL_ROLE_SKETCH_V02,
  MAX_CELL_ROLE_SKETCH_V02_BYTES,
  MAX_CELL_ROLE_SKETCH_V02_TABLES,
  MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS,
  parseCellRoleSketchV02,
  serializeCellRoleSketchV02,
  type CellRoleSketchV02,
  type SketchRoleSelectorV02,
  type SketchTableV02,
} from "./cell-role-sketch-v02.js";
import {
  CELL_ROLE_COMPILER_VERSION,
  compileCellRoleSketch,
} from "./compiler-v02.js";
import type { RelationshipKind } from "./types.js";
import {
  buildHeaderDirectionGroups,
  isBlankRelationshipValue,
  resolveRelationshipAttachmentAtAddress,
} from "../executor/relationshipResolution.js";
import { executeRecipe } from "../executor/executeRecipe.js";
import type {
  ExecutionResult,
  ExecutionTrace,
  TidyOutputRow,
  TidyTableResult,
} from "../executor/types.js";
import type { RecipeV01 } from "../recipe/types.js";
import type { ParsedSheet } from "../workbook/types.js";
import {
  geometricRoleHintSchema,
  ROLE_AWARE_REGION_CATALOG_VERSION,
} from "./role-aware-region-catalog-v5.js";

export const SEMANTIC_TABLE_MAP_V2 = "semantic-table-map-v2" as const;
export const ATOMIC_SEMANTIC_MAP_V2_COMPILER_VERSION =
  "atomic-semantic-table-map-v2-recipe-v01-compiler-v1" as const;
export const ATOMIC_SEMANTIC_MAP_V2_ENVELOPE =
  "atomic-semantic-table-map-compilation/v2" as const;
export const ATOMIC_LOGICAL_EXECUTION_V2 =
  "atomic-semantic-table-logical-execution/v2" as const;
export const MAX_ATOMIC_MAP_V2_DIMENSIONS = 64;
export const MAX_ATOMIC_MAP_V2_JSON_BYTES = 8 * 1024 * 1024;
export const MAX_ATOMIC_MAP_V2_JSON_NODES = 250_000;
export const MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE = 512;
export const MAX_ATOMIC_MAP_V2_TOTAL_SELECTORS = 10_000;
export const MAX_ATOMIC_MAP_V2_CATALOG_JSON_BYTES = 16 * 1024 * 1024;
export const MAX_ATOMIC_MAP_V2_CATALOG_JSON_NODES = 500_000;
export const MAX_ATOMIC_MAP_V2_CATALOG_CANDIDATES = 512;
export const MAX_ATOMIC_MAP_V2_CATALOG_SEGMENTS = 16_384;
export const MAX_ATOMIC_MAP_V2_CATALOG_EXPANDED_CELLS = 500_000;
export const MAX_ATOMIC_MAP_V2_ATTACHMENTS = 250_000;
export const MAX_ATOMIC_MAP_V2_STRICT_RESOLUTION_OPERATIONS = 2_000_000;
export const MAX_ATOMIC_MAP_V2_ENVELOPE_BYTES = 32 * 1024 * 1024;
export const MAX_ATOMIC_MAP_V2_ENVELOPE_NODES = 500_000;
export const ATOMIC_MAP_V2_SUPPORTED_CATALOG_VERSIONS = [
  "semantic-region-catalog-v1",
  ROLE_AWARE_REGION_CATALOG_VERSION,
] as const;

const stableId = z.string().regex(/^[a-z][a-z0-9-]{0,29}$/);
const UNSAFE_LOGICAL_OUTPUT_KEYS = new Set([
  "__proto__",
  "prototype",
  "constructor",
  "toString",
  "toLocaleString",
  "valueOf",
  "hasOwnProperty",
  "isPrototypeOf",
  "propertyIsEnumerable",
  "__defineGetter__",
  "__defineSetter__",
  "__lookupGetter__",
  "__lookupSetter__",
]);
export const logicalOutputNameV2Schema = z
  .string()
  .min(1)
  .max(200)
  .refine((value) => value === value.trim(), {
    message:
      "Logical output names must not have leading or trailing whitespace.",
  })
  .regex(
    /^[A-Za-z0-9][A-Za-z0-9 _-]{0,199}$/,
    "Logical output names may contain only ASCII letters, digits, spaces, underscores, and hyphens, and must start with a letter or digit.",
  )
  .refine((value) => !UNSAFE_LOGICAL_OUTPUT_KEYS.has(value), {
    message: "Logical output name is reserved or unsafe.",
  });
const digestSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/);
const canonicalAddressSchema = z
  .string()
  .min(4)
  .max(32)
  .refine((value) => {
    try {
      return formatCell(parseCell(value)) === value;
    } catch {
      return false;
    }
  }, "Expected a canonical uppercase R1C1 address.");
const canonicalRangeSchema = z
  .string()
  .min(9)
  .max(80)
  .refine((value) => {
    try {
      return formatRange(parseRange(value)) === value;
    } catch {
      return false;
    }
  }, "Expected a canonical uppercase R1C1 range.");
const selectorSchema = z.union([
  z.object({ address: canonicalAddressSchema }).strict(),
  z.object({ range: canonicalRangeSchema }).strict(),
]);
const ownedSubsetSchema = z
  .object({
    regionId: z.string().min(1).max(80),
    selectors: z
      .array(selectorSchema)
      .min(1)
      .max(MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE),
  })
  .strict();
const ownedSubsetList = z
  .array(ownedSubsetSchema)
  .min(1)
  .max(MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE);
const logicalDimensionSchema = z
  .object({ id: stableId, name: logicalOutputNameV2Schema })
  .strict();
const panelDimensionSchema = z
  .object({
    id: stableId,
    source: ownedSubsetList,
    direction: semanticDirectionSchema,
    allowSharedSource: z.boolean().optional(),
  })
  .strict();
const panelSchema = z
  .object({
    id: stableId,
    order: z.number().int().min(1).max(MAX_CELL_ROLE_SKETCH_V02_TABLES),
    tableName: z.string().trim().min(1).max(200),
    target: ownedSubsetList,
    dimensions: z
      .array(panelDimensionSchema)
      .min(1)
      .max(MAX_ATOMIC_MAP_V2_DIMENSIONS),
  })
  .strict();

export const semanticTableMapV2Schema = z
  .object({
    version: z.literal(SEMANTIC_TABLE_MAP_V2),
    catalog: z
      .object({
        version: z.enum(ATOMIC_MAP_V2_SUPPORTED_CATALOG_VERSIONS),
        digest: digestSchema,
      })
      .strict(),
    logicalTable: z
      .object({
        id: stableId,
        name: z.string().trim().min(1).max(200),
        values: z
          .object({
            id: stableId,
            name: logicalOutputNameV2Schema,
            target: ownedSubsetList,
          })
          .strict(),
        dimensions: z
          .array(logicalDimensionSchema)
          .min(1)
          .max(MAX_ATOMIC_MAP_V2_DIMENSIONS),
      })
      .strict(),
    panels: z.array(panelSchema).min(1).max(MAX_CELL_ROLE_SKETCH_V02_TABLES),
  })
  .strict();

export type SemanticTableMapV2 = z.infer<typeof semanticTableMapV2Schema>;

const catalogStringList = z.array(z.string().max(4096)).max(512);
const v1CatalogCandidateSchema = z
  .object({
    id: z.string().min(1).max(80),
    range: canonicalRangeSchema,
    kinds: catalogStringList,
    nonblankCount: z.number().int().nonnegative(),
    valueLikeCount: z.number().int().nonnegative(),
    sample: catalogStringList,
  })
  .strict();
const v5CatalogCandidateSchema = z
  .object({
    id: z.string().min(1).max(80),
    segments: z.array(canonicalRangeSchema).min(1).max(512),
    kinds: catalogStringList,
    roleHints: z.array(geometricRoleHintSchema).max(16),
    formatSignatures: catalogStringList,
    formatting: catalogStringList,
    selectedCellCount: z.number().int().nonnegative(),
    nonblankCount: z.number().int().nonnegative(),
    valueLikeCount: z.number().int().nonnegative(),
    sample: catalogStringList,
  })
  .strict();
const v1AtomicRegionCatalogSchema = z
  .object({
    version: z.literal("semantic-region-catalog-v1"),
    sheet: z.string().min(1).max(200),
    candidates: z
      .array(v1CatalogCandidateSchema)
      .max(MAX_ATOMIC_MAP_V2_CATALOG_CANDIDATES),
    omittedCandidateCount: z.number().int().nonnegative(),
  })
  .strict();
const v5AtomicRegionCatalogSchema = z
  .object({
    version: z.literal(ROLE_AWARE_REGION_CATALOG_VERSION),
    sheet: z.string().min(1).max(200),
    candidates: z
      .array(v5CatalogCandidateSchema)
      .max(MAX_ATOMIC_MAP_V2_CATALOG_CANDIDATES),
    omittedCandidateCount: z.number().int().nonnegative(),
    observationPanelCount: z.number().int().nonnegative(),
    formatFactCount: z.number().int().nonnegative(),
    cellDataFactCount: z.number().int().nonnegative(),
  })
  .strict();
export const atomicRegionCatalogSchema = z.discriminatedUnion("version", [
  v1AtomicRegionCatalogSchema,
  v5AtomicRegionCatalogSchema,
]);
export type AtomicRegionCatalog = z.infer<typeof atomicRegionCatalogSchema>;

export type AtomicAttachmentV2 = {
  targetAddress: string;
  panelId: string;
  tableName: string;
  dimensions: Array<{
    id: string;
    name: string;
    sourceAddress: string;
    direction: SemanticDirection;
  }>;
};

export type AtomicCompilationEnvelopeV2 = {
  version: typeof ATOMIC_SEMANTIC_MAP_V2_ENVELOPE;
  compilerVersion: typeof ATOMIC_SEMANTIC_MAP_V2_COMPILER_VERSION;
  cellRoleCompilerVersion: typeof CELL_ROLE_COMPILER_VERSION;
  map: SemanticTableMapV2;
  mapDigest: string;
  catalog: { version: string; digest: string; sheet: string };
  sheetContentProof: {
    sheet: string;
    usedRange: string | null;
    rowCount: number;
    columnCount: number;
    nonEmptyCellCount: number;
    cellCount: number;
    mergeCount: number;
    digest: string;
  };
  physicalExecutionProof: {
    digest: string;
    tableCount: number;
    nonTableCellCount: number;
  };
  sketch: CellRoleSketchV02;
  canonicalSketchXml: string;
  sketchDigest: string;
  recipe: RecipeV01;
  canonicalRecipeJson: string;
  recipeDigest: string;
  logicalTargetDigest: string;
  panelProofs: Array<{
    panelId: string;
    order: number;
    tableName: string;
    selectedTargets: string[];
    activeTargets: string[];
    targetDigest: string;
    dimensions: Array<{
      id: string;
      sourceAddresses: string[];
      sourceDigest: string;
      direction: SemanticDirection;
    }>;
  }>;
  attachmentProof: {
    count: number;
    digest: string;
    attachments: AtomicAttachmentV2[];
  };
  reconstitutionManifest: {
    logicalTableId: string;
    logicalTableName: string;
    valuesName: string;
    dimensionOrder: Array<{ id: string; name: string }>;
    expectedActiveTargets: string[];
    expectedActiveTargetDigest: string;
    panelTableNames: Array<{ panelId: string; tableName: string }>;
    digest: string;
  };
  envelopeDigest: string;
};

export type AtomicSemanticMapV2CompilationResult =
  | { ok: true; envelope: AtomicCompilationEnvelopeV2 }
  | {
      ok: false;
      stage: "schema" | "catalog" | "ownership" | "geometry" | "compiler";
      code: string;
      message: string;
    };

export type AtomicLogicalExecutionV2 = {
  version: typeof ATOMIC_LOGICAL_EXECUTION_V2;
  providerCalls: 0;
  compilationEnvelopeDigest: string;
  physicalExecution: ExecutionResult;
  logicalTable: TidyTableResult;
};

class AtomicMapError extends Error {
  constructor(
    readonly stage:
      | "schema"
      | "catalog"
      | "ownership"
      | "geometry"
      | "compiler",
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

const DIRECTION_TO_RELATIONSHIP: Readonly<
  Record<SemanticDirection, RelationshipKind>
> = {
  N: "direct-column",
  W: "direct-row",
  NNW: "cascading-column",
  WNW: "cascading-row",
};

export function digestAtomicCompilationEnvelopeV2(
  envelope: AtomicCompilationEnvelopeV2,
): string {
  const { envelopeDigest: _ignored, ...withoutDigest } = envelope;
  return digestCanonical(withoutDigest);
}

export function digestAtomicRegionCatalog(
  catalog: AtomicRegionCatalog,
): string {
  assertBoundedJsonValue(
    catalog,
    MAX_ATOMIC_MAP_V2_CATALOG_JSON_NODES,
    MAX_ATOMIC_MAP_V2_CATALOG_JSON_BYTES,
    "CATALOG_RESOURCE_LIMIT",
  );
  return digestCanonical(parseAtomicRegionCatalog(catalog));
}

export function parseSemanticTableMapV2Json(raw: string): SemanticTableMapV2 {
  if (Buffer.byteLength(raw, "utf8") > MAX_ATOMIC_MAP_V2_JSON_BYTES) {
    throw new Error("SEMANTIC_MAP_V2_JSON_BYTE_LIMIT");
  }
  const cleaned = raw
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/, "")
    .trim();
  const value: unknown = JSON.parse(cleaned);
  assertBoundedJsonValue(
    value,
    MAX_ATOMIC_MAP_V2_JSON_NODES,
    MAX_ATOMIC_MAP_V2_JSON_BYTES,
    "SEMANTIC_MAP_V2_JSON_RESOURCE_LIMIT",
  );
  return normalizeSemanticMap(semanticTableMapV2Schema.parse(value));
}

export function compileAtomicSemanticTableMapV2(input: {
  map: unknown;
  catalog: AtomicRegionCatalog;
  context: CompactSemanticContext;
  sheet: ParsedSheet;
}): AtomicSemanticMapV2CompilationResult {
  try {
    assertBoundedJsonValue(
      input.map,
      MAX_ATOMIC_MAP_V2_JSON_NODES,
      MAX_ATOMIC_MAP_V2_JSON_BYTES,
      "SEMANTIC_MAP_V2_RESOURCE_LIMIT",
      "schema",
    );
    assertBoundedJsonValue(
      input.catalog,
      MAX_ATOMIC_MAP_V2_CATALOG_JSON_NODES,
      MAX_ATOMIC_MAP_V2_CATALOG_JSON_BYTES,
      "CATALOG_RESOURCE_LIMIT",
      "catalog",
    );
    const parsed = semanticTableMapV2Schema.safeParse(input.map);
    if (!parsed.success) {
      throw new AtomicMapError(
        "schema",
        "SEMANTIC_MAP_V2_SCHEMA_INVALID",
        parsed.error.issues
          .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
          .join("; "),
      );
    }
    const parsedCatalog = atomicRegionCatalogSchema.safeParse(input.catalog);
    if (!parsedCatalog.success) {
      throw new AtomicMapError(
        "catalog",
        "CATALOG_SCHEMA_INVALID",
        parsedCatalog.error.issues
          .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
          .join("; "),
      );
    }
    const map = normalizeSemanticMap(parsed.data);
    const catalog = parsedCatalog.data;
    validateIdentity(map, catalog, input.context);
    validateMapStructure(map);
    const catalogRegions = buildCatalogRegions(catalog, input.context);
    const orderedPanels = [...map.panels].sort(
      (left, right) => left.order - right.order,
    );
    const logicalTargets = resolveRole(
      map.logicalTable.values.target,
      catalogRegions,
      "logicalTable.values.target",
    );

    const panelResolved = orderedPanels.map((panel) => ({
      panel,
      targets: resolveRole(
        panel.target,
        catalogRegions,
        `panels.${panel.id}.target`,
      ),
      dimensions: panel.dimensions.map((dimension) => ({
        dimension,
        addresses: resolveRole(
          dimension.source,
          catalogRegions,
          `panels.${panel.id}.dimensions.${dimension.id}.source`,
        ),
      })),
    }));
    proveTargetPartition(logicalTargets.addresses, panelResolved);
    proveSharedSourceDeclarations(panelResolved);
    validateAuthoritativeSheetContext(input.context, input.sheet);

    const sheetCells = contextCells(input.context);
    const cellByAddress = new Map(
      sheetCells.map((cell) => [cell.address, cell]),
    );
    const sketch: CellRoleSketchV02 = {
      version: CELL_ROLE_SKETCH_V02,
      sheet: input.context.sheet,
      tables: panelResolved.map(({ panel, targets, dimensions }) =>
        buildSketchTable(map, panel, targets, dimensions),
      ),
      uncertainties: [],
    };
    const bounds = {
      rowCount: input.context.dimensions.rows,
      columnCount: input.context.dimensions.columns,
    };
    let canonicalSketchXml: string;
    try {
      canonicalSketchXml = serializeCellRoleSketchV02(sketch, bounds);
    } catch (error) {
      const code = (error as { code?: string }).code ?? "INVALID_SKETCH";
      const message = error instanceof Error ? error.message : String(error);
      throw new AtomicMapError(
        "geometry",
        code === "BYTE_LIMIT" ||
        message.includes("BYTE_LIMIT") ||
        message.includes(`exceeds ${MAX_CELL_ROLE_SKETCH_V02_BYTES} bytes`)
          ? "SKETCH_BYTE_RESOURCE_LIMIT"
          : code === "NODE_LIMIT" || message.includes("NODE_LIMIT")
            ? "SKETCH_NODE_RESOURCE_LIMIT"
            : "SKETCH_RESOURCE_LIMIT",
        message,
      );
    }
    // Run the target-scoped audit before legacy geometry so equal-valued
    // competing sources fail with the v2-specific ambiguity code rather than
    // being masked by a later unused-header diagnostic.
    const attachments = auditAttachments(map, panelResolved, cellByAddress);
    const requiredDimensions = new Map(
      sketch.tables.flatMap((table) =>
        table.dimensions.map((dimension) => [
          dimension.id,
          `semantic-table-map-v2:${table.id}`,
        ]),
      ),
    );
    const parsedSketch = parseCellRoleSketchV02(canonicalSketchXml, bounds, {
      sheet: { cells: sheetCells },
      requiredDimensions,
      collectAssociations: true,
    });
    if (!parsedSketch.ok) {
      throw new AtomicMapError(
        "geometry",
        parsedSketch.code,
        parsedSketch.message,
      );
    }
    const compiled = compileCellRoleSketch(parsedSketch.sketch, {
      sheet: { cells: sheetCells },
      requiredDimensions,
      collectAssociations: true,
    });
    if (!compiled.ok) {
      throw new AtomicMapError(
        "compiler",
        compiled.error.code,
        compiled.error.message,
      );
    }

    const panelProofs = panelResolved.map(({ panel, targets, dimensions }) => {
      const selectedTargets = targets.addresses;
      const activeTargets = selectedTargets.filter(
        (address) =>
          !isBlankRelationshipValue(cellByAddress.get(address) ?? {}),
      );
      return {
        panelId: panel.id,
        order: panel.order,
        tableName: panel.tableName,
        selectedTargets,
        activeTargets,
        targetDigest: digestCanonical(selectedTargets),
        dimensions: dimensions.map(({ dimension, addresses }) => ({
          id: dimension.id,
          sourceAddresses: addresses.addresses,
          sourceDigest: digestCanonical(addresses.addresses),
          direction: dimension.direction,
        })),
      };
    });
    const expectedActiveTargets = sortAddresses(
      panelProofs.flatMap((panel) => panel.activeTargets),
    );
    const manifestWithoutDigest = {
      logicalTableId: map.logicalTable.id,
      logicalTableName: map.logicalTable.name,
      valuesName: map.logicalTable.values.name,
      dimensionOrder: map.logicalTable.dimensions,
      expectedActiveTargets,
      expectedActiveTargetDigest: digestCanonical(expectedActiveTargets),
      panelTableNames: orderedPanels.map((panel) => ({
        panelId: panel.id,
        tableName: panel.tableName,
      })),
    };
    const reconstitutionManifest = {
      ...manifestWithoutDigest,
      digest: digestCanonical(manifestWithoutDigest),
    };
    const attachmentProof = {
      count: attachments.reduce(
        (total, attachment) => total + attachment.dimensions.length,
        0,
      ),
      digest: digestCanonical(attachments),
      attachments,
    };
    const envelopeWithoutDigest = {
      version: ATOMIC_SEMANTIC_MAP_V2_ENVELOPE,
      compilerVersion: ATOMIC_SEMANTIC_MAP_V2_COMPILER_VERSION,
      cellRoleCompilerVersion: compiled.compilerVersion,
      map,
      mapDigest: digestCanonical(map),
      catalog: {
        version: catalog.version,
        digest: map.catalog.digest,
        sheet: catalog.sheet,
      },
      sheetContentProof: buildAuthoritativeSheetContentProof(input.sheet),
      sketch: parsedSketch.sketch,
      canonicalSketchXml: parsedSketch.canonical,
      sketchDigest: digestBytes(parsedSketch.canonical),
      recipe: compiled.recipe,
      canonicalRecipeJson: compiled.canonicalJson,
      recipeDigest: digestBytes(compiled.canonicalJson),
      logicalTargetDigest: digestCanonical(logicalTargets.addresses),
      panelProofs,
      attachmentProof,
      reconstitutionManifest,
      physicalExecutionProof: buildPhysicalExecutionProof(
        executeRecipe(compiled.recipe, input.sheet),
        orderedPanels.map((panel) => panel.tableName),
      ),
    };
    const envelope: AtomicCompilationEnvelopeV2 = {
      ...envelopeWithoutDigest,
      envelopeDigest: digestCanonical(envelopeWithoutDigest),
    };
    assertBoundedJsonValue(
      envelope,
      MAX_ATOMIC_MAP_V2_ENVELOPE_NODES,
      MAX_ATOMIC_MAP_V2_ENVELOPE_BYTES,
      "ENVELOPE_RESOURCE_LIMIT",
      "compiler",
    );
    return { ok: true, envelope };
  } catch (error) {
    if (error instanceof AtomicMapError) {
      return {
        ok: false,
        stage: error.stage,
        code: error.code,
        message: error.message,
      };
    }
    return {
      ok: false,
      stage: "ownership",
      code: "SEMANTIC_MAP_V2_INTERNAL_VALIDATION_FAILED",
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

export function executeAtomicSemanticTableMapV2(
  envelope: AtomicCompilationEnvelopeV2,
  sheet: ParsedSheet,
  trustedEnvelopeDigest: string,
): AtomicLogicalExecutionV2 {
  validateEnvelope(envelope, trustedEnvelopeDigest);
  validateRuntimeSheet(envelope, sheet);
  const physicalExecution = executeRecipe(envelope.recipe, sheet);
  return reconstituteAtomicSemanticExecutionV2(
    envelope,
    physicalExecution,
    sheet,
    trustedEnvelopeDigest,
  );
}

export function reconstituteAtomicSemanticExecutionV2(
  envelope: AtomicCompilationEnvelopeV2,
  suppliedPhysicalExecution: ExecutionResult,
  sheet: ParsedSheet,
  trustedEnvelopeDigest: string,
): AtomicLogicalExecutionV2 {
  validateEnvelope(envelope, trustedEnvelopeDigest);
  const runtimeCells = validateRuntimeSheet(envelope, sheet);
  validateSuppliedExecutionShape(suppliedPhysicalExecution, envelope);
  if (
    suppliedPhysicalExecution.sheet !== envelope.catalog.sheet ||
    sheet.name !== envelope.catalog.sheet
  ) {
    throw executionFailure("EXECUTION_SHEET_MISMATCH");
  }
  if (suppliedPhysicalExecution.warnings.length) {
    throw executionFailure("EXECUTION_WARNINGS_PRESENT");
  }
  const expectedNames = new Set(
    envelope.reconstitutionManifest.panelTableNames.map(
      (entry) => entry.tableName,
    ),
  );
  const actualByName = new Map<string, TidyTableResult>();
  for (const table of suppliedPhysicalExecution.tables) {
    if (actualByName.has(table.table)) {
      throw executionFailure("DUPLICATE_EXECUTION_TABLE");
    }
    actualByName.set(table.table, table);
  }
  if (
    actualByName.size !== expectedNames.size ||
    [...actualByName.keys()].some((name) => !expectedNames.has(name)) ||
    [...expectedNames].some((name) => !actualByName.has(name))
  ) {
    throw executionFailure("EXECUTION_TABLE_SET_MISMATCH");
  }
  const attachmentByTarget = new Map(
    envelope.attachmentProof.attachments.map((entry) => [
      entry.targetAddress,
      entry,
    ]),
  );
  const expectedTargets = new Set(
    envelope.reconstitutionManifest.expectedActiveTargets,
  );
  const observed = new Map<
    string,
    { row: TidyOutputRow; trace: ExecutionTrace["value_cells"][number] }
  >();
  for (const panel of envelope.panelProofs) {
    const table = actualByName.get(panel.tableName)!;
    if (table.sheet !== envelope.catalog.sheet) {
      throw executionFailure("TABLE_SHEET_MISMATCH");
    }
    if (table.warnings.length) throw executionFailure("TABLE_WARNINGS_PRESENT");
    if (
      table.rows.length !== panel.activeTargets.length ||
      table.trace.value_cells.length !== panel.activeTargets.length
    ) {
      throw executionFailure("ROW_TRACE_CARDINALITY_MISMATCH");
    }
    const traceByTarget = new Map<
      string,
      ExecutionTrace["value_cells"][number]
    >();
    for (const trace of table.trace.value_cells) {
      const address = trace.source.address;
      if (traceByTarget.has(address)) {
        throw executionFailure("DUPLICATE_TARGET_TRACE");
      }
      if (!panel.activeTargets.includes(address)) {
        throw executionFailure("UNEXPECTED_TARGET_TRACE");
      }
      assertSourceIdentity(trace.source, envelope.catalog.sheet, address);
      traceByTarget.set(address, trace);
    }
    const panelTargets = new Set(panel.activeTargets);
    for (const row of table.rows) {
      const address = row._source?.address;
      if (
        !address ||
        !panelTargets.has(address) ||
        !expectedTargets.has(address)
      ) {
        throw executionFailure("UNEXPECTED_TARGET_ROW");
      }
      assertSourceIdentity(row._source!, envelope.catalog.sheet, address);
      if (observed.has(address)) throw executionFailure("DUPLICATE_TARGET_ROW");
      const trace = traceByTarget.get(address);
      if (!trace) throw executionFailure("MISSING_TARGET_TRACE");
      const expected = attachmentByTarget.get(address);
      if (!expected) throw executionFailure("MISSING_ATTACHMENT_PROOF");
      const targetCell = runtimeCells.get(address);
      if (
        !targetCell ||
        !sameScalar(trace.value, targetCell.value) ||
        !sameScalar(
          row[envelope.reconstitutionManifest.valuesName],
          trace.value,
        )
      ) {
        throw executionFailure("VALUE_TRACE_MISMATCH");
      }
      if (trace.headers.length !== expected.dimensions.length) {
        throw executionFailure("HEADER_TRACE_CARDINALITY_MISMATCH");
      }
      const headerByName = new Map(
        trace.headers.map((entry) => [entry.header, entry]),
      );
      if (headerByName.size !== trace.headers.length) {
        throw executionFailure("DUPLICATE_HEADER_TRACE");
      }
      if (
        trace.headers.some(
          (entry, index) => entry.header !== expected.dimensions[index]?.name,
        )
      ) {
        throw executionFailure("HEADER_TRACE_ORDER_MISMATCH");
      }
      for (const dimension of expected.dimensions) {
        const rowValue = row[dimension.name];
        if (!isValidDimensionScalar(rowValue)) {
          throw executionFailure("INVALID_REQUIRED_DIMENSION");
        }
        if (row[`${dimension.name}_source`] !== dimension.sourceAddress) {
          throw executionFailure("DIMENSION_SOURCE_MISMATCH");
        }
        const headerTrace = headerByName.get(dimension.name);
        const sourceCell = runtimeCells.get(dimension.sourceAddress);
        if (
          !headerTrace ||
          !sourceCell ||
          headerTrace.missing !== false ||
          headerTrace.ambiguous !== false ||
          headerTrace.selected !== dimension.sourceAddress ||
          headerTrace.direction !== dimension.direction ||
          headerTrace.candidates.length !== 1 ||
          headerTrace.candidates[0] !== dimension.sourceAddress ||
          !sameScalar(headerTrace.value, sourceCell.value) ||
          !sameScalar(rowValue, headerTrace.value)
        ) {
          throw executionFailure("ATTACHMENT_TRACE_MISMATCH");
        }
        headerByName.delete(dimension.name);
      }
      if (headerByName.size) {
        throw executionFailure("EXTRA_HEADER_TRACE");
      }
      observed.set(address, { row, trace });
    }
    if ([...panelTargets].some((address) => !traceByTarget.has(address))) {
      throw executionFailure("MISSING_TARGET_TRACE");
    }
  }
  if (
    observed.size !== expectedTargets.size ||
    [...expectedTargets].some((address) => !observed.has(address))
  ) {
    throw executionFailure("MISSING_TARGET_ROW");
  }

  const physicalExecution = validatePhysicalExecutionProof(
    envelope,
    suppliedPhysicalExecution,
    sheet,
  );

  const reproducedByAddress = collectTrustedReproducedRows(
    physicalExecution,
    envelope,
  );
  const rows: TidyOutputRow[] = [];
  const valueCells: ExecutionTrace["value_cells"] = [];
  for (const address of envelope.reconstitutionManifest.expectedActiveTargets) {
    const entry = reproducedByAddress.get(address);
    if (!entry) throw executionFailure("MISSING_REPRODUCED_TARGET");
    const output: TidyOutputRow = {};
    for (const dimension of envelope.reconstitutionManifest.dimensionOrder) {
      output[dimension.name] = entry.row[dimension.name];
    }
    output[envelope.reconstitutionManifest.valuesName] =
      entry.row[envelope.reconstitutionManifest.valuesName];
    output._source = copySource(entry.row._source!);
    for (const dimension of envelope.reconstitutionManifest.dimensionOrder) {
      output[`${dimension.name}_source`] =
        entry.row[`${dimension.name}_source`];
    }
    rows.push(output);
    valueCells.push(copyValueTrace(entry.trace));
  }
  return {
    version: ATOMIC_LOGICAL_EXECUTION_V2,
    providerCalls: 0,
    compilationEnvelopeDigest: envelope.envelopeDigest,
    physicalExecution,
    logicalTable: {
      table: envelope.reconstitutionManifest.logicalTableName,
      sheet: physicalExecution.sheet,
      rows,
      warnings: [],
      trace: { value_cells: valueCells },
    },
  };
}

function validateIdentity(
  map: SemanticTableMapV2,
  catalog: AtomicRegionCatalog,
  context: CompactSemanticContext,
): void {
  if (catalog.version !== map.catalog.version) {
    throw new AtomicMapError(
      "catalog",
      "CATALOG_VERSION_MISMATCH",
      "Catalog version does not match the map pin.",
    );
  }
  if (catalog.sheet !== context.sheet) {
    throw new AtomicMapError(
      "catalog",
      "CATALOG_SHEET_MISMATCH",
      "Catalog and context sheets differ.",
    );
  }
  if (digestAtomicRegionCatalog(catalog) !== map.catalog.digest) {
    throw new AtomicMapError(
      "catalog",
      "CATALOG_DIGEST_MISMATCH",
      "Catalog bytes do not match the map digest pin.",
    );
  }
}

function validateMapStructure(map: SemanticTableMapV2): void {
  const roles = [
    map.logicalTable.values.target,
    ...map.panels.flatMap((panel) => [
      panel.target,
      ...panel.dimensions.map((dimension) => dimension.source),
    ]),
  ];
  let totalSelectors = 0;
  for (const role of roles) {
    const count = role.reduce(
      (sum, declaration) => sum + declaration.selectors.length,
      0,
    );
    if (count > MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE) {
      throw new AtomicMapError(
        "schema",
        "ROLE_SELECTOR_RESOURCE_LIMIT",
        `A logical role exceeds ${MAX_ATOMIC_MAP_V2_SELECTORS_PER_ROLE} selectors.`,
      );
    }
    totalSelectors += count;
    if (totalSelectors > MAX_ATOMIC_MAP_V2_TOTAL_SELECTORS) {
      throw new AtomicMapError(
        "schema",
        "TOTAL_SELECTOR_RESOURCE_LIMIT",
        `The map exceeds ${MAX_ATOMIC_MAP_V2_TOTAL_SELECTORS} selectors.`,
      );
    }
  }
  assertUnique(
    map.logicalTable.dimensions.map((entry) => entry.id),
    "DUPLICATE_DIMENSION_ID",
  );
  const dimensionNames = map.logicalTable.dimensions.map((entry) => entry.name);
  assertUnique(dimensionNames, "DUPLICATE_DIMENSION_NAME");
  const logicalOutputKeys = [
    map.logicalTable.values.name,
    ...dimensionNames,
    ...dimensionNames.map((name) => `${name}_source`),
    "_source",
  ];
  if (
    logicalOutputKeys.some(
      (key) =>
        !logicalOutputNameV2Schema.safeParse(key).success && key !== "_source",
    ) ||
    !isUnique(logicalOutputKeys)
  ) {
    throw new AtomicMapError(
      "schema",
      "LOGICAL_OUTPUT_KEY_COLLISION",
      "Logical value, dimension, generated dimension-source, and reserved source keys must be safe and globally unique.",
    );
  }
  assertUnique(
    map.panels.map((entry) => entry.id),
    "DUPLICATE_PANEL_ID",
  );
  assertUnique(
    map.panels.map((entry) => entry.tableName),
    "DUPLICATE_PANEL_TABLE_NAME",
  );
  assertUnique(
    map.panels.map((entry) => String(entry.order)),
    "DUPLICATE_PANEL_ORDER",
  );
  assertUnique(
    [
      map.logicalTable.id,
      map.logicalTable.values.id,
      ...map.logicalTable.dimensions.map((entry) => entry.id),
      ...map.panels.map((entry) => entry.id),
    ],
    "DUPLICATE_MAP_ENTITY_ID",
  );
  const sortedOrders = map.panels
    .map((panel) => panel.order)
    .sort((left, right) => left - right);
  if (sortedOrders.some((order, index) => order !== index + 1)) {
    throw new AtomicMapError(
      "ownership",
      "NON_CONTIGUOUS_PANEL_ORDER",
      "Explicit panel order must be contiguous and start at one.",
    );
  }
  const expectedIds = map.logicalTable.dimensions.map((entry) => entry.id);
  map.panels.forEach((panel) => {
    const ids = panel.dimensions.map((entry) => entry.id);
    if (
      ids.length !== expectedIds.length ||
      ids.some((id, offset) => id !== expectedIds[offset])
    ) {
      throw new AtomicMapError(
        "ownership",
        "PANEL_DIMENSION_ORDER_MISMATCH",
        `Panel ${panel.id} must declare every logical dimension once and in logical order.`,
      );
    }
  });
}

function buildCatalogRegions(
  catalog: AtomicRegionCatalog,
  context: CompactSemanticContext,
): Map<string, Set<string>> {
  const result = new Map<string, Set<string>>();
  let totalSegments = 0;
  let totalExpandedCells = 0;
  for (const candidate of catalog.candidates) {
    if (result.has(candidate.id)) {
      throw new AtomicMapError(
        "catalog",
        "DUPLICATE_CATALOG_REGION",
        `Duplicate catalog region ${candidate.id}.`,
      );
    }
    const segments =
      "range" in candidate ? [candidate.range] : candidate.segments;
    totalSegments += segments.length;
    if (totalSegments > MAX_ATOMIC_MAP_V2_CATALOG_SEGMENTS) {
      throw new AtomicMapError(
        "catalog",
        "CATALOG_SEGMENT_RESOURCE_LIMIT",
        "Catalog segment count exceeds the global limit.",
      );
    }
    const addresses = new Set<string>();
    for (const segment of segments) {
      const cardinality = rangeCardinality(segment);
      if (cardinality > MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS) {
        throw new AtomicMapError(
          "catalog",
          "CATALOG_REGION_RESOURCE_LIMIT",
          `Catalog region ${candidate.id} exceeds the per-region expansion limit.`,
        );
      }
      if (
        totalExpandedCells + cardinality >
        MAX_ATOMIC_MAP_V2_CATALOG_EXPANDED_CELLS
      ) {
        throw new AtomicMapError(
          "catalog",
          "CATALOG_EXPANSION_RESOURCE_LIMIT",
          "Catalog expanded-cell count exceeds the global limit.",
        );
      }
      const expanded = expandRange(segment);
      totalExpandedCells += cardinality;
      if (totalExpandedCells > MAX_ATOMIC_MAP_V2_CATALOG_EXPANDED_CELLS) {
        throw new AtomicMapError(
          "catalog",
          "CATALOG_EXPANSION_RESOURCE_LIMIT",
          "Catalog expanded-cell count exceeds the global limit.",
        );
      }
      for (const address of expanded) {
        assertWithinBounds(address, context);
        addresses.add(address);
        if (addresses.size > MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS) {
          throw new AtomicMapError(
            "catalog",
            "CATALOG_REGION_RESOURCE_LIMIT",
            `Catalog region ${candidate.id} exceeds the per-region expansion limit.`,
          );
        }
      }
    }
    result.set(candidate.id, addresses);
  }
  return result;
}

function resolveRole(
  declarations: SemanticTableMapV2["logicalTable"]["values"]["target"],
  catalogRegions: Map<string, Set<string>>,
  path: string,
): {
  addresses: string[];
  selectors: Array<{ kind: "address" | "range"; value: string }>;
} {
  const addresses = new Set<string>();
  const selectors: Array<{ kind: "address" | "range"; value: string }> = [];
  for (const declaration of declarations) {
    const parent = catalogRegions.get(declaration.regionId);
    if (!parent)
      throw new AtomicMapError(
        "catalog",
        "UNKNOWN_CATALOG_REGION",
        `${path} references unknown region ${declaration.regionId}.`,
      );
    for (const selector of declaration.selectors) {
      const kind = "address" in selector ? "address" : "range";
      const value = "address" in selector ? selector.address : selector.range;
      const cardinality = kind === "address" ? 1 : rangeCardinality(value);
      if (
        addresses.size + cardinality >
        MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS
      ) {
        throw new AtomicMapError(
          "ownership",
          "ROLE_RESOURCE_LIMIT",
          `${path} exceeds the expansion limit.`,
        );
      }
      const expanded = kind === "address" ? [value] : expandRange(value);
      for (const address of expanded) {
        if (!parent.has(address)) {
          throw new AtomicMapError(
            "ownership",
            "SUBSET_OUTSIDE_PARENT_REGION",
            `${path} selects ${address} outside ${declaration.regionId}.`,
          );
        }
        if (addresses.has(address)) {
          throw new AtomicMapError(
            "ownership",
            "SUBSET_SELECTOR_OVERLAP",
            `${path} selects ${address} more than once.`,
          );
        }
        addresses.add(address);
        if (addresses.size > MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS) {
          throw new AtomicMapError(
            "ownership",
            "ROLE_RESOURCE_LIMIT",
            `${path} exceeds the expansion limit.`,
          );
        }
      }
      selectors.push({ kind, value });
    }
  }
  if (!addresses.size)
    throw new AtomicMapError(
      "ownership",
      "EMPTY_OWNED_ROLE",
      `${path} is empty.`,
    );
  return {
    addresses: sortAddresses([...addresses]),
    selectors: selectors.sort(compareSelector),
  };
}

function proveTargetPartition(
  logicalTargets: string[],
  panels: Array<{
    panel: SemanticTableMapV2["panels"][number];
    targets: { addresses: string[] };
  }>,
): void {
  const logical = new Set(logicalTargets);
  const owner = new Map<string, string>();
  for (const { panel, targets } of panels) {
    for (const address of targets.addresses) {
      if (!logical.has(address))
        throw new AtomicMapError(
          "ownership",
          "PANEL_TARGET_OUTSIDE_LOGICAL_TARGET",
          `${panel.id} owns unexpected target ${address}.`,
        );
      const previous = owner.get(address);
      if (previous)
        throw new AtomicMapError(
          "ownership",
          "OVERLAPPING_PANEL_TARGET",
          `${address} is owned by ${previous} and ${panel.id}.`,
        );
      owner.set(address, panel.id);
    }
  }
  const missing = logicalTargets.find((address) => !owner.has(address));
  if (missing)
    throw new AtomicMapError(
      "ownership",
      "PANEL_TARGET_GAP",
      `No panel owns ${missing}.`,
    );
}

function proveSharedSourceDeclarations(
  panels: Array<{
    panel: SemanticTableMapV2["panels"][number];
    dimensions: Array<{
      dimension: SemanticTableMapV2["panels"][number]["dimensions"][number];
      addresses: { addresses: string[] };
    }>;
  }>,
): void {
  const uses = new Map<
    string,
    Array<{ panel: string; dimension: string; allowed: boolean }>
  >();
  for (const { panel, dimensions } of panels) {
    for (const { dimension, addresses } of dimensions) {
      for (const address of addresses.addresses) {
        const entries = uses.get(address) ?? [];
        entries.push({
          panel: panel.id,
          dimension: dimension.id,
          allowed: dimension.allowSharedSource === true,
        });
        uses.set(address, entries);
      }
    }
  }
  for (const [address, entries] of uses) {
    const distinctPanels = new Set(entries.map((entry) => entry.panel));
    if (distinctPanels.size > 1 && entries.some((entry) => !entry.allowed)) {
      throw new AtomicMapError(
        "ownership",
        "UNDECLARED_SHARED_SOURCE",
        `${address} is reused across panels without allowSharedSource=true on every use.`,
      );
    }
  }
}

function buildSketchTable(
  map: SemanticTableMapV2,
  panel: SemanticTableMapV2["panels"][number],
  targets: {
    addresses: string[];
    selectors: Array<{ kind: "address" | "range"; value: string }>;
  },
  dimensions: Array<{
    dimension: SemanticTableMapV2["panels"][number]["dimensions"][number];
    addresses: {
      addresses: string[];
      selectors: Array<{ kind: "address" | "range"; value: string }>;
    };
  }>,
): SketchTableV02 {
  const values = roleSelector(`${panel.id}-value`, targets.addresses);
  const logicalDimensionNames = new Map(
    map.logicalTable.dimensions.map((dimension) => [
      dimension.id,
      dimension.name,
    ]),
  );
  const dimensionEntries = dimensions.map(({ dimension, addresses }) => {
    const selector = roleSelector(
      `${panel.id}-${dimension.id}`,
      addresses.addresses,
    );
    return {
      id: `${panel.id}-${dimension.id}`,
      name: logicalDimensionNames.get(dimension.id)!,
      evidence: `Explicit source ownership for panel ${panel.id}.`,
      sources: selector.sources,
      addresses: selector.addresses,
    };
  });
  const allAddresses = [
    ...targets.addresses,
    ...dimensions.flatMap((entry) => entry.addresses.addresses),
  ];
  return {
    id: panel.id,
    name: panel.tableName,
    evidence: "Explicit atomic panel selected by semantic-table-map-v2.",
    selectorBounds: formatRange(boundingRangeOf(allAddresses)),
    values: {
      id: `${panel.id}-values`,
      name: map.logicalTable.values.name,
      evidence: "Exact panel target ownership.",
      sources: values.sources,
      addresses: values.addresses,
    },
    dimensions: dimensionEntries,
    relationships: dimensions.map(({ dimension }) => ({
      id: `${panel.id}-${dimension.id}-relationship`,
      dimensionId: `${panel.id}-${dimension.id}`,
      kind: DIRECTION_TO_RELATIONSHIP[dimension.direction],
      evidence: "Explicit panel relationship direction.",
    })),
  };
}

function roleSelector(
  prefix: string,
  addresses: string[],
): SketchRoleSelectorV02 {
  const bounds = formatRange(boundingRangeOf(addresses));
  const boundsCellCount = rangeCardinality(bounds);
  const selectors =
    boundsCellCount === addresses.length
      ? [{ kind: "range" as const, value: bounds }]
      : addresses.map((address) => ({
          kind: "address" as const,
          value: address,
        }));
  return {
    sources: selectors.map((selector, index) => ({
      id: `${prefix}-${index + 1}`,
      selector,
    })),
    addresses,
  };
}

function auditAttachments(
  map: SemanticTableMapV2,
  panels: Array<{
    panel: SemanticTableMapV2["panels"][number];
    targets: { addresses: string[] };
    dimensions: Array<{
      dimension: SemanticTableMapV2["panels"][number]["dimensions"][number];
      addresses: { addresses: string[] };
    }>;
  }>,
  cellByAddress: Map<
    string,
    { address: string; data_type?: string; value?: unknown }
  >,
): AtomicAttachmentV2[] {
  const dimensionName = new Map(
    map.logicalTable.dimensions.map((entry) => [entry.id, entry.name]),
  );
  const result: AtomicAttachmentV2[] = [];
  let count = 0;
  let strictResolutionOperations = 0;
  for (const { panel, targets, dimensions } of panels) {
    const activeTargets = targets.addresses.filter(
      (address) => !isBlankRelationshipValue(cellByAddress.get(address) ?? {}),
    );
    const selectedByDimension = new Map<string, Map<string, string>>();
    for (const { dimension, addresses } of dimensions) {
      strictResolutionOperations +=
        addresses.addresses.length * activeTargets.length;
      if (
        strictResolutionOperations >
        MAX_ATOMIC_MAP_V2_STRICT_RESOLUTION_OPERATIONS
      ) {
        throw new AtomicMapError(
          "geometry",
          "STRICT_RESOLUTION_RESOURCE_LIMIT",
          "Strict physical-candidate proof exceeds the bounded operation limit.",
        );
      }
      const groups = buildHeaderDirectionGroups({
        headerAddresses: addresses.addresses,
        valueAddresses: activeTargets,
        direction: dimension.direction,
      });
      const selected = new Map<string, string>();
      const used = new Set<string>();
      for (const target of activeTargets) {
        // Use the exact executor resolver, not the optimized batch selector:
        // the latter intentionally retains only the nearest source and cannot
        // prove that an equal-valued physical competitor was absent.
        const attachment = resolveRelationshipAttachmentAtAddress(
          groups,
          target,
        );
        if (!attachment?.selectedAddress)
          throw new AtomicMapError(
            "geometry",
            "MISSING_REQUIRED_ATTACHMENT",
            `${panel.id}/${dimension.id} does not attach to ${target}.`,
          );
        if (attachment.candidates.length !== 1)
          throw new AtomicMapError(
            "geometry",
            "AMBIGUOUS_ATTACHMENT",
            `${panel.id}/${dimension.id} has ${attachment.candidates.length} physical candidates for ${target}.`,
          );
        if (!addresses.addresses.includes(attachment.selectedAddress))
          throw new AtomicMapError(
            "geometry",
            "ATTACHMENT_OUTSIDE_OWNERSHIP",
            `${attachment.selectedAddress} is outside declared source ownership.`,
          );
        const selectedCell = cellByAddress.get(attachment.selectedAddress);
        if (
          !selectedCell ||
          isBlankRelationshipValue(selectedCell) ||
          (typeof selectedCell.value === "string" &&
            selectedCell.value.trim().length === 0)
        ) {
          throw new AtomicMapError(
            "geometry",
            "BLANK_REQUIRED_SOURCE",
            `${attachment.selectedAddress} is a blank required dimension source.`,
          );
        }
        if (
          typeof selectedCell.value === "boolean" ||
          (typeof selectedCell.value === "number" &&
            !Number.isFinite(selectedCell.value))
        ) {
          throw new AtomicMapError(
            "geometry",
            "INVALID_REQUIRED_SOURCE_SCALAR",
            `${attachment.selectedAddress} is not an exact string/finite-number dimension label.`,
          );
        }
        selected.set(target, attachment.selectedAddress);
        used.add(attachment.selectedAddress);
        count += 1;
        if (count > MAX_ATOMIC_MAP_V2_ATTACHMENTS)
          throw new AtomicMapError(
            "geometry",
            "ATTACHMENT_RESOURCE_LIMIT",
            "Attachment proof exceeds the bounded limit.",
          );
      }
      const unused = addresses.addresses.find((address) => !used.has(address));
      if (unused)
        throw new AtomicMapError(
          "geometry",
          "UNUSED_DECLARED_SOURCE",
          `${panel.id}/${dimension.id} source ${unused} is unused.`,
        );
      selectedByDimension.set(dimension.id, selected);
    }
    for (const targetAddress of activeTargets) {
      result.push({
        targetAddress,
        panelId: panel.id,
        tableName: panel.tableName,
        dimensions: panel.dimensions.map((dimension) => ({
          id: dimension.id,
          name: dimensionName.get(dimension.id)!,
          sourceAddress: selectedByDimension
            .get(dimension.id)!
            .get(targetAddress)!,
          direction: dimension.direction,
        })),
      });
    }
  }
  return result.sort((left, right) =>
    compareAddress(left.targetAddress, right.targetAddress),
  );
}

function validateEnvelope(
  envelope: AtomicCompilationEnvelopeV2,
  trustedEnvelopeDigest: string,
): void {
  if (!digestSchema.safeParse(trustedEnvelopeDigest).success) {
    throw executionFailure("TRUSTED_ENVELOPE_DIGEST_INVALID");
  }
  if (envelope.envelopeDigest !== trustedEnvelopeDigest) {
    throw executionFailure("TRUSTED_ENVELOPE_DIGEST_MISMATCH");
  }
  assertBoundedJsonValue(
    envelope,
    MAX_ATOMIC_MAP_V2_ENVELOPE_NODES,
    MAX_ATOMIC_MAP_V2_ENVELOPE_BYTES,
    "ENVELOPE_RESOURCE_LIMIT",
  );
  if (
    envelope.version !== ATOMIC_SEMANTIC_MAP_V2_ENVELOPE ||
    envelope.compilerVersion !== ATOMIC_SEMANTIC_MAP_V2_COMPILER_VERSION ||
    envelope.cellRoleCompilerVersion !== CELL_ROLE_COMPILER_VERSION
  ) {
    throw executionFailure("COMPILER_IDENTITY_MISMATCH");
  }
  const { envelopeDigest, ...withoutDigest } = envelope;
  if (digestCanonical(withoutDigest) !== envelopeDigest) {
    throw executionFailure("ENVELOPE_DIGEST_MISMATCH");
  }

  const parsedMap = semanticTableMapV2Schema.safeParse(envelope.map);
  if (!parsedMap.success) throw executionFailure("MAP_SCHEMA_MISMATCH");
  const normalizedMap = normalizeSemanticMap(parsedMap.data);
  if (
    canonicalJson(normalizedMap) !== canonicalJson(envelope.map) ||
    digestCanonical(normalizedMap) !== envelope.mapDigest ||
    envelope.map.catalog.version !== envelope.catalog.version ||
    envelope.map.catalog.digest !== envelope.catalog.digest
  ) {
    throw executionFailure("MAP_PROOF_MISMATCH");
  }
  if (envelope.catalog.sheet !== envelope.sketch.sheet) {
    throw executionFailure("CATALOG_SKETCH_SHEET_MISMATCH");
  }
  const bounds = {
    rowCount: envelope.sheetContentProof.rowCount,
    columnCount: envelope.sheetContentProof.columnCount,
  };
  let serializedSketch: string;
  try {
    serializedSketch = serializeCellRoleSketchV02(envelope.sketch, bounds);
  } catch {
    throw executionFailure("SKETCH_PROOF_MISMATCH");
  }
  if (
    serializedSketch !== envelope.canonicalSketchXml ||
    digestBytes(serializedSketch) !== envelope.sketchDigest ||
    Buffer.byteLength(serializedSketch, "utf8") > MAX_CELL_ROLE_SKETCH_V02_BYTES
  ) {
    throw executionFailure("SKETCH_PROOF_MISMATCH");
  }
  const recompiledRecipe = compileCellRoleSketch(envelope.sketch);
  if (
    !recompiledRecipe.ok ||
    digestBytes(envelope.canonicalRecipeJson) !== envelope.recipeDigest ||
    `${JSON.stringify(envelope.recipe)}\n` !== envelope.canonicalRecipeJson ||
    recompiledRecipe.canonicalJson !== envelope.canonicalRecipeJson ||
    envelope.recipe.version !== "0.1" ||
    envelope.recipe.sheet !== envelope.catalog.sheet
  ) {
    throw executionFailure("RECIPE_DIGEST_MISMATCH");
  }

  const orderedPanels = [...normalizedMap.panels].sort(
    (left, right) => left.order - right.order,
  );
  if (
    envelope.panelProofs.length !== orderedPanels.length ||
    envelope.recipe.tables.length !== orderedPanels.length ||
    envelope.sketch.tables.length !== orderedPanels.length
  ) {
    throw executionFailure("PANEL_PROOF_CARDINALITY_MISMATCH");
  }
  const allSelected: string[] = [];
  const allActive: string[] = [];
  const panelById = new Map<
    string,
    AtomicCompilationEnvelopeV2["panelProofs"][number]
  >();
  for (let index = 0; index < orderedPanels.length; index += 1) {
    const declared = orderedPanels[index];
    const proof = envelope.panelProofs[index];
    if (
      proof.panelId !== declared.id ||
      proof.order !== declared.order ||
      proof.tableName !== declared.tableName ||
      envelope.recipe.tables[index].name !== declared.tableName ||
      envelope.sketch.tables[index].name !== declared.tableName ||
      canonicalJson(proof.selectedTargets) !==
        canonicalJson(expandOwnedSelectors(declared.target)) ||
      !isCanonicalUniqueAddressList(proof.selectedTargets) ||
      !isCanonicalUniqueAddressList(proof.activeTargets) ||
      proof.activeTargets.some(
        (address) => !proof.selectedTargets.includes(address),
      ) ||
      digestCanonical(proof.selectedTargets) !== proof.targetDigest ||
      proof.dimensions.length !== declared.dimensions.length
    ) {
      throw executionFailure("PANEL_PROOF_MISMATCH");
    }
    for (
      let dimensionIndex = 0;
      dimensionIndex < declared.dimensions.length;
      dimensionIndex += 1
    ) {
      const declaredDimension = declared.dimensions[dimensionIndex];
      const dimensionProof = proof.dimensions[dimensionIndex];
      if (
        dimensionProof.id !== declaredDimension.id ||
        dimensionProof.direction !== declaredDimension.direction ||
        canonicalJson(dimensionProof.sourceAddresses) !==
          canonicalJson(expandOwnedSelectors(declaredDimension.source)) ||
        !isCanonicalUniqueAddressList(dimensionProof.sourceAddresses) ||
        digestCanonical(dimensionProof.sourceAddresses) !==
          dimensionProof.sourceDigest
      ) {
        throw executionFailure("PANEL_SOURCE_PROOF_MISMATCH");
      }
    }
    allSelected.push(...proof.selectedTargets);
    allActive.push(...proof.activeTargets);
    panelById.set(proof.panelId, proof);
  }
  const sortedSelected = sortAddresses(allSelected);
  const sortedActive = sortAddresses(allActive);
  if (
    !isUnique(sortedSelected) ||
    !isUnique(sortedActive) ||
    canonicalJson(sortedSelected) !==
      canonicalJson(
        expandOwnedSelectors(normalizedMap.logicalTable.values.target),
      ) ||
    digestCanonical(sortedSelected) !== envelope.logicalTargetDigest
  ) {
    throw executionFailure("LOGICAL_TARGET_PROOF_MISMATCH");
  }

  const attachments = envelope.attachmentProof.attachments;
  if (
    envelope.attachmentProof.count !==
      attachments.reduce(
        (total, attachment) => total + attachment.dimensions.length,
        0,
      ) ||
    digestCanonical(attachments) !== envelope.attachmentProof.digest ||
    attachments.length !== sortedActive.length ||
    attachments.some(
      (entry, index) => entry.targetAddress !== sortedActive[index],
    )
  ) {
    throw executionFailure("ATTACHMENT_PROOF_DIGEST_MISMATCH");
  }
  for (const attachment of attachments) {
    const panel = panelById.get(attachment.panelId);
    const declared = orderedPanels.find(
      (entry) => entry.id === attachment.panelId,
    );
    if (
      !panel ||
      !declared ||
      attachment.tableName !== panel.tableName ||
      !panel.activeTargets.includes(attachment.targetAddress) ||
      attachment.dimensions.length !== declared.dimensions.length
    ) {
      throw executionFailure("ATTACHMENT_PANEL_MISMATCH");
    }
    for (let index = 0; index < attachment.dimensions.length; index += 1) {
      const dimension = attachment.dimensions[index];
      const declaredDimension = declared.dimensions[index];
      const dimensionProof = panel.dimensions[index];
      const logicalDimension = normalizedMap.logicalTable.dimensions[index];
      if (
        dimension.id !== declaredDimension.id ||
        dimension.name !== logicalDimension.name ||
        dimension.direction !== declaredDimension.direction ||
        !dimensionProof.sourceAddresses.includes(dimension.sourceAddress)
      ) {
        throw executionFailure("ATTACHMENT_DIMENSION_MISMATCH");
      }
    }
  }

  const { digest, ...manifest } = envelope.reconstitutionManifest;
  const expectedPanelNames = orderedPanels.map((panel) => ({
    panelId: panel.id,
    tableName: panel.tableName,
  }));
  if (
    digestCanonical(manifest) !== digest ||
    envelope.reconstitutionManifest.logicalTableId !==
      normalizedMap.logicalTable.id ||
    envelope.reconstitutionManifest.logicalTableName !==
      normalizedMap.logicalTable.name ||
    envelope.reconstitutionManifest.valuesName !==
      normalizedMap.logicalTable.values.name ||
    canonicalJson(envelope.reconstitutionManifest.dimensionOrder) !==
      canonicalJson(normalizedMap.logicalTable.dimensions) ||
    canonicalJson(envelope.reconstitutionManifest.panelTableNames) !==
      canonicalJson(expectedPanelNames) ||
    !isCanonicalUniqueAddressList(
      envelope.reconstitutionManifest.expectedActiveTargets,
    ) ||
    canonicalJson(envelope.reconstitutionManifest.expectedActiveTargets) !==
      canonicalJson(sortedActive) ||
    digestCanonical(envelope.reconstitutionManifest.expectedActiveTargets) !==
      envelope.reconstitutionManifest.expectedActiveTargetDigest
  ) {
    throw executionFailure("RECONSTITUTION_MANIFEST_DIGEST_MISMATCH");
  }
  if (
    envelope.sheetContentProof.sheet !== envelope.catalog.sheet ||
    envelope.sheetContentProof.rowCount < 1 ||
    envelope.sheetContentProof.columnCount < 1 ||
    envelope.sheetContentProof.cellCount < 0 ||
    envelope.sheetContentProof.nonEmptyCellCount < 0 ||
    envelope.sheetContentProof.mergeCount < 0 ||
    !digestSchema.safeParse(envelope.sheetContentProof.digest).success ||
    !digestSchema.safeParse(envelope.physicalExecutionProof.digest).success ||
    envelope.physicalExecutionProof.tableCount !== orderedPanels.length ||
    envelope.physicalExecutionProof.nonTableCellCount < 0
  ) {
    throw executionFailure("SHEET_CONTENT_PROOF_INVALID");
  }
}

function parseAtomicRegionCatalog(catalog: unknown): AtomicRegionCatalog {
  const parsed = atomicRegionCatalogSchema.safeParse(catalog);
  if (!parsed.success) {
    throw new Error(
      `CATALOG_SCHEMA_INVALID: ${parsed.error.issues
        .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
        .join("; ")}`,
    );
  }
  return parsed.data;
}

function normalizeSemanticMap(map: SemanticTableMapV2): SemanticTableMapV2 {
  const normalized = structuredClone(map);
  const normalizeOwned = (
    declarations: SemanticTableMapV2["logicalTable"]["values"]["target"],
  ) =>
    declarations
      .map((declaration) => ({
        ...declaration,
        selectors: [...declaration.selectors].sort((left, right) =>
          compareSelector(
            "address" in left
              ? { kind: "address", value: left.address }
              : { kind: "range", value: left.range },
            "address" in right
              ? { kind: "address", value: right.address }
              : { kind: "range", value: right.range },
          ),
        ),
      }))
      .sort(
        (left, right) =>
          left.regionId.localeCompare(right.regionId) ||
          canonicalJson(left).localeCompare(canonicalJson(right)),
      );
  normalized.logicalTable.values.target = normalizeOwned(
    normalized.logicalTable.values.target,
  );
  normalized.panels = [...normalized.panels]
    .sort((left, right) => left.order - right.order)
    .map((panel) => ({
      ...panel,
      target: normalizeOwned(panel.target),
      dimensions: panel.dimensions.map((dimension) => ({
        ...dimension,
        source: normalizeOwned(dimension.source),
      })),
    }));
  return normalized;
}

function assertBoundedJsonValue(
  value: unknown,
  maxNodes: number,
  maxBytes: number,
  code: string,
  stage?: "schema" | "catalog" | "ownership" | "geometry" | "compiler",
): void {
  const stack: unknown[] = [value];
  let nodes = 0;
  let estimatedBytes = 0;
  while (stack.length) {
    const entry = stack.pop();
    nodes += 1;
    if (nodes > maxNodes) {
      if (stage)
        throw new AtomicMapError(stage, code, `${code}: node limit exceeded.`);
      throw executionFailure(code);
    }
    if (typeof entry === "string") {
      estimatedBytes += Buffer.byteLength(entry, "utf8") + 2;
    } else if (entry && typeof entry === "object") {
      if (Array.isArray(entry)) {
        if (nodes + stack.length + entry.length > maxNodes) {
          if (stage)
            throw new AtomicMapError(
              stage,
              code,
              `${code}: node limit exceeded.`,
            );
          throw executionFailure(code);
        }
        for (const child of entry) stack.push(child);
        estimatedBytes += entry.length + 2;
      } else {
        for (const [key, child] of Object.entries(entry)) {
          estimatedBytes += Buffer.byteLength(key, "utf8") + 3;
          stack.push(child);
        }
      }
    } else {
      estimatedBytes += 16;
    }
    if (estimatedBytes > maxBytes) {
      if (stage)
        throw new AtomicMapError(stage, code, `${code}: byte limit exceeded.`);
      throw executionFailure(code);
    }
  }
  let exactBytes: number;
  try {
    exactBytes = Buffer.byteLength(JSON.stringify(value), "utf8");
  } catch {
    if (stage)
      throw new AtomicMapError(stage, code, `${code}: non-JSON input.`);
    throw executionFailure(code);
  }
  if (exactBytes > maxBytes) {
    if (stage)
      throw new AtomicMapError(stage, code, `${code}: byte limit exceeded.`);
    throw executionFailure(code);
  }
}

type ExecutionVisibleCell = {
  address: string;
  row: number;
  col: number;
  value: string | number | boolean | null;
  data_type: string;
  formula: string | null;
  formatted: string | null;
  comment: string | null;
  hyperlink: string | null;
  style: unknown;
  merge: unknown;
};

function projectSheetCell(
  cell: ParsedSheet["cells"][number],
): ExecutionVisibleCell {
  return {
    address: cell.address,
    row: cell.row,
    col: cell.col,
    value: cell.value,
    data_type: cell.data_type,
    formula: cell.formula ?? null,
    formatted: cell.formatted ?? null,
    comment: cell.comment ?? null,
    hyperlink: cell.hyperlink ?? null,
    style: cell.style ?? null,
    merge: cell.merge ?? null,
  };
}

function canonicalSheetContent(sheet: ParsedSheet) {
  const cells = [...sheet.cells]
    .map(projectSheetCell)
    .sort((left, right) => compareAddress(left.address, right.address));
  const merges = [...sheet.merges].sort(
    (left, right) =>
      compareAddress(left.parent, right.parent) ||
      left.range.localeCompare(right.range),
  );
  return {
    sheet: sheet.name,
    usedRange: sheet.usedRange,
    rowCount: sheet.rowCount,
    columnCount: sheet.columnCount,
    nonEmptyCellCount: sheet.nonEmptyCellCount,
    cells,
    merges,
  };
}

function validateSheetCellIdentities(
  sheet: ParsedSheet,
  runtime: boolean,
): void {
  const supplied = new Set<string>();
  for (const cell of sheet.cells) {
    if (
      cell.sheet !== sheet.name ||
      formatCell({ row: cell.row, col: cell.col }) !== cell.address ||
      cell.row < 1 ||
      cell.col < 1 ||
      cell.row > sheet.rowCount ||
      cell.col > sheet.columnCount ||
      supplied.has(cell.address)
    ) {
      if (runtime) throw executionFailure("SHEET_CELL_IDENTITY_MISMATCH");
      throw new AtomicMapError(
        "geometry",
        "SHEET_CELL_IDENTITY_MISMATCH",
        "Authoritative sheet cells must have unique canonical identities within bounds.",
      );
    }
    supplied.add(cell.address);
  }
}

function validateAuthoritativeSheetContext(
  context: CompactSemanticContext,
  sheet: ParsedSheet,
): void {
  validateSheetCellIdentities(sheet, false);
  if (
    sheet.name !== context.sheet ||
    sheet.usedRange !== context.usedRange ||
    sheet.rowCount !== context.dimensions.rows ||
    sheet.columnCount !== context.dimensions.columns ||
    canonicalJson(
      [...sheet.merges].sort((a, b) => compareAddress(a.parent, b.parent)),
    ) !==
      canonicalJson(
        [...context.merges].sort((a, b) => compareAddress(a.parent, b.parent)),
      )
  ) {
    throw new AtomicMapError(
      "geometry",
      "AUTHORITATIVE_SHEET_CONTEXT_MISMATCH",
      "Compact context identity or geometry differs from the authoritative parsed sheet.",
    );
  }
  const byAddress = new Map(sheet.cells.map((cell) => [cell.address, cell]));
  for (let row = 1; row <= context.dimensions.rows; row += 1) {
    const values = context.grid.rows[row - 1]?.values;
    if (!values || values.length !== context.dimensions.columns) {
      throw new AtomicMapError(
        "geometry",
        "AUTHORITATIVE_SHEET_CONTEXT_MISMATCH",
        "Compact context grid shape differs from the authoritative parsed sheet.",
      );
    }
    for (let col = 1; col <= context.dimensions.columns; col += 1) {
      const address = formatCell({ row, col });
      if (!sameScalar(values[col - 1], byAddress.get(address)?.value ?? null)) {
        throw new AtomicMapError(
          "geometry",
          "AUTHORITATIVE_SHEET_CONTEXT_MISMATCH",
          `${address} differs between compact context and authoritative parsed sheet.`,
        );
      }
    }
  }
}

function buildAuthoritativeSheetContentProof(
  sheet: ParsedSheet,
): AtomicCompilationEnvelopeV2["sheetContentProof"] {
  const content = canonicalSheetContent(sheet);
  return {
    sheet: content.sheet,
    usedRange: content.usedRange,
    rowCount: content.rowCount,
    columnCount: content.columnCount,
    nonEmptyCellCount: content.nonEmptyCellCount,
    cellCount: content.cells.length,
    mergeCount: content.merges.length,
    digest: digestCanonical(content),
  };
}

function validateRuntimeSheet(
  envelope: AtomicCompilationEnvelopeV2,
  sheet: ParsedSheet,
): Map<string, ExecutionVisibleCell> {
  if (sheet.name !== envelope.sheetContentProof.sheet) {
    throw executionFailure("SHEET_CONTENT_IDENTITY_MISMATCH");
  }
  validateSheetCellIdentities(sheet, true);
  const content = canonicalSheetContent(sheet);
  if (
    sheet.usedRange !== envelope.sheetContentProof.usedRange ||
    sheet.rowCount !== envelope.sheetContentProof.rowCount ||
    sheet.columnCount !== envelope.sheetContentProof.columnCount ||
    sheet.nonEmptyCellCount !== envelope.sheetContentProof.nonEmptyCellCount ||
    content.cells.length !== envelope.sheetContentProof.cellCount ||
    content.merges.length !== envelope.sheetContentProof.mergeCount ||
    digestCanonical(content) !== envelope.sheetContentProof.digest
  ) {
    throw executionFailure("SHEET_CONTENT_DIGEST_MISMATCH");
  }
  const cells = new Map(content.cells.map((cell) => [cell.address, cell]));
  for (let row = 1; row <= sheet.rowCount; row += 1) {
    for (let col = 1; col <= sheet.columnCount; col += 1) {
      const address = formatCell({ row, col });
      if (!cells.has(address)) {
        cells.set(address, {
          address,
          row,
          col,
          value: null,
          data_type: "blank",
          formula: null,
          formatted: null,
          comment: null,
          hyperlink: null,
          style: null,
          merge: null,
        });
      }
    }
  }
  return cells;
}

function validateSuppliedExecutionShape(
  execution: unknown,
  envelope: AtomicCompilationEnvelopeV2,
): asserts execution is ExecutionResult {
  const root = strictRecord(
    execution,
    ["sheet", "tables", "non_table_cells", "warnings"],
    ["sheet", "tables", "non_table_cells", "warnings"],
  );
  requireString(root.sheet);
  const warnings = requireArray(root.warnings);
  warnings.forEach(validateExecutionWarningShape);
  const tables = requireArray(root.tables);
  const dimensionNames = envelope.reconstitutionManifest.dimensionOrder.map(
    (dimension) => dimension.name,
  );
  const rowKeys = [
    envelope.reconstitutionManifest.valuesName,
    "_source",
    ...dimensionNames.flatMap((name) => [name, `${name}_source`]),
  ];
  for (const tableValue of tables) {
    const table = strictRecord(
      tableValue,
      ["table", "sheet", "rows", "warnings", "trace"],
      ["table", "sheet", "rows", "warnings", "trace"],
    );
    requireString(table.table);
    requireString(table.sheet);
    requireArray(table.warnings).forEach(validateExecutionWarningShape);
    for (const rowValue of requireArray(table.rows)) {
      const row = strictRecord(rowValue, rowKeys, rowKeys);
      validateOutputScalar(row[envelope.reconstitutionManifest.valuesName]);
      validateSourceShape(row._source);
      for (const name of dimensionNames) {
        validateOutputScalar(row[name]);
        requireString(row[`${name}_source`]);
      }
    }
    const trace = strictRecord(table.trace, ["value_cells"], ["value_cells"]);
    for (const valueTraceValue of requireArray(trace.value_cells)) {
      const valueTrace = strictRecord(
        valueTraceValue,
        ["source", "value", "headers"],
        ["source", "value", "headers"],
      );
      validateSourceShape(valueTrace.source);
      validateOutputScalar(valueTrace.value);
      for (const headerValue of requireArray(valueTrace.headers)) {
        const header = strictRecord(
          headerValue,
          [
            "header",
            "direction",
            "candidates",
            "selected",
            "value",
            "missing",
            "ambiguous",
          ],
          [
            "header",
            "direction",
            "candidates",
            "selected",
            "value",
            "missing",
            "ambiguous",
          ],
        );
        requireString(header.header);
        requireString(header.direction);
        requireArray(header.candidates).forEach(requireString);
        requireString(header.selected);
        validateOutputScalar(header.value);
        if (typeof header.missing !== "boolean") executionShapeFailure();
        if (typeof header.ambiguous !== "boolean") executionShapeFailure();
      }
    }
  }
  for (const nonTableValue of requireArray(root.non_table_cells)) {
    const nonTable = strictRecord(
      nonTableValue,
      [
        "sheet",
        "address",
        "row",
        "col",
        "value",
        "data_type",
        "formatted",
        "formula",
        "comment",
        "style_id",
        "reason",
      ],
      ["sheet", "address", "row", "col", "value", "data_type", "reason"],
    );
    requireString(nonTable.sheet);
    requireString(nonTable.address);
    requirePositiveInteger(nonTable.row);
    requirePositiveInteger(nonTable.col);
    validateOutputScalar(nonTable.value);
    if (
      !["blank", "string", "numeric", "boolean", "date", "error"].includes(
        requireString(nonTable.data_type),
      ) ||
      nonTable.reason !== "not_referenced_by_recipe"
    ) {
      executionShapeFailure();
    }
    for (const key of ["formatted", "formula", "comment"] as const) {
      if (
        Object.hasOwn(nonTable, key) &&
        nonTable[key] !== null &&
        typeof nonTable[key] !== "string"
      ) {
        executionShapeFailure();
      }
    }
    if (
      Object.hasOwn(nonTable, "style_id") &&
      nonTable.style_id !== null &&
      typeof nonTable.style_id !== "string"
    ) {
      executionShapeFailure();
    }
  }
}

function strictRecord(
  value: unknown,
  allowedKeys: string[],
  requiredKeys: string[],
): Record<string, unknown> {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    (Object.getPrototypeOf(value) !== Object.prototype &&
      Object.getPrototypeOf(value) !== null)
  ) {
    executionShapeFailure();
  }
  const record = value as Record<string, unknown>;
  const allowed = new Set(allowedKeys);
  const ownKeys = Reflect.ownKeys(record);
  if (
    ownKeys.some((key) => typeof key !== "string" || !allowed.has(key)) ||
    requiredKeys.some((key) => !Object.hasOwn(record, key))
  ) {
    executionShapeFailure();
  }
  return record;
}

function requireArray(value: unknown): unknown[] {
  if (!Array.isArray(value)) executionShapeFailure();
  return value;
}

function requireString(value: unknown): string {
  if (typeof value !== "string") executionShapeFailure();
  return value;
}

function requirePositiveInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    executionShapeFailure();
  }
  return value;
}

function validateOutputScalar(value: unknown): void {
  if (
    value !== null &&
    typeof value !== "string" &&
    typeof value !== "boolean" &&
    (typeof value !== "number" || !Number.isFinite(value))
  ) {
    executionShapeFailure();
  }
}

function validateSourceShape(value: unknown): void {
  const source = strictRecord(
    value,
    ["sheet", "address", "row", "col"],
    ["sheet", "address", "row", "col"],
  );
  requireString(source.sheet);
  requireString(source.address);
  requirePositiveInteger(source.row);
  requirePositiveInteger(source.col);
}

function validateExecutionWarningShape(value: unknown): void {
  const warning = strictRecord(
    value,
    ["code", "message", "table", "header", "address"],
    ["code", "message"],
  );
  if (
    ![
      "EMPTY_VALUE_SELECTION",
      "EMPTY_HEADER_SELECTION",
      "UNUSED_HEADER",
      "MISSING_REQUIRED_HEADER",
      "AMBIGUOUS_HEADER",
      "OVERLAPPING_VALUE_CELL",
      "SELECTOR_WARNING",
    ].includes(requireString(warning.code))
  ) {
    executionShapeFailure();
  }
  requireString(warning.message);
  for (const key of ["table", "header", "address"] as const) {
    if (Object.hasOwn(warning, key)) requireString(warning[key]);
  }
}

function executionShapeFailure(): never {
  throw executionFailure("PHYSICAL_EXECUTION_SCHEMA_MISMATCH");
}

function collectTrustedReproducedRows(
  execution: ExecutionResult,
  envelope: AtomicCompilationEnvelopeV2,
): Map<
  string,
  { row: TidyOutputRow; trace: ExecutionTrace["value_cells"][number] }
> {
  const byAddress = new Map<
    string,
    { row: TidyOutputRow; trace: ExecutionTrace["value_cells"][number] }
  >();
  const tableByName = new Map(
    execution.tables.map((table) => [table.table, table]),
  );
  for (const panel of envelope.panelProofs) {
    const table = tableByName.get(panel.tableName);
    if (!table) throw executionFailure("MISSING_REPRODUCED_TABLE");
    const traceByAddress = new Map(
      table.trace.value_cells.map((trace) => [trace.source.address, trace]),
    );
    for (const row of table.rows) {
      const address = row._source?.address;
      const trace = address ? traceByAddress.get(address) : undefined;
      if (!address || !trace || byAddress.has(address)) {
        throw executionFailure("INVALID_REPRODUCED_EXECUTION");
      }
      byAddress.set(address, { row, trace });
    }
  }
  return byAddress;
}

function copySource(source: {
  sheet: string;
  address: string;
  row: number;
  col: number;
}): { sheet: string; address: string; row: number; col: number } {
  return {
    sheet: source.sheet,
    address: source.address,
    row: source.row,
    col: source.col,
  };
}

function copyValueTrace(
  trace: ExecutionTrace["value_cells"][number],
): ExecutionTrace["value_cells"][number] {
  return {
    source: copySource(trace.source),
    value: trace.value,
    headers: trace.headers.map((header) => ({
      header: header.header,
      direction: header.direction,
      candidates: [...header.candidates],
      ...(header.selected === undefined ? {} : { selected: header.selected }),
      value: header.value,
      missing: header.missing,
      ambiguous: header.ambiguous,
    })),
  };
}

function normalizePhysicalExecution(
  execution: ExecutionResult,
  tableOrder: string[],
): ExecutionResult {
  if (!Array.isArray(execution.tables) || !Array.isArray(execution.warnings)) {
    throw executionFailure("PHYSICAL_EXECUTION_SCHEMA_MISMATCH");
  }
  const byName = new Map<string, TidyTableResult>();
  for (const table of execution.tables) {
    if (byName.has(table.table))
      throw executionFailure("DUPLICATE_EXECUTION_TABLE");
    byName.set(table.table, table);
  }
  if (
    byName.size !== tableOrder.length ||
    tableOrder.some((name) => !byName.has(name))
  ) {
    throw executionFailure("EXECUTION_TABLE_SET_MISMATCH");
  }
  if (!Array.isArray(execution.non_table_cells)) {
    throw executionFailure("NON_TABLE_PROVENANCE_MISSING");
  }
  const nonTableCells = [...execution.non_table_cells].sort((left, right) =>
    compareAddress(left.address, right.address),
  );
  return {
    sheet: execution.sheet,
    tables: tableOrder.map((name) => byName.get(name)!),
    non_table_cells: nonTableCells,
    warnings: execution.warnings,
  };
}

function buildPhysicalExecutionProof(
  execution: ExecutionResult,
  tableOrder: string[],
): AtomicCompilationEnvelopeV2["physicalExecutionProof"] {
  if (
    execution.warnings.length ||
    execution.tables.some((table) => table.warnings.length)
  ) {
    throw new AtomicMapError(
      "compiler",
      "PHYSICAL_EXECUTION_WARNINGS_PRESENT",
      "Compiled RecipeV01 produced warnings against the authoritative sheet.",
    );
  }
  const normalized = normalizePhysicalExecution(execution, tableOrder);
  return {
    digest: digestCanonical(normalized),
    tableCount: normalized.tables.length,
    nonTableCellCount: normalized.non_table_cells?.length ?? 0,
  };
}

function validatePhysicalExecutionProof(
  envelope: AtomicCompilationEnvelopeV2,
  supplied: ExecutionResult,
  sheet: ParsedSheet,
): ExecutionResult {
  const tableOrder = envelope.reconstitutionManifest.panelTableNames.map(
    (entry) => entry.tableName,
  );
  const expected = normalizePhysicalExecution(
    executeRecipe(envelope.recipe, sheet),
    tableOrder,
  );
  const observed = normalizePhysicalExecution(supplied, tableOrder);
  if (
    expected.tables.some((table) => table.warnings.length) ||
    expected.warnings.length ||
    expected.tables.length !== envelope.physicalExecutionProof.tableCount ||
    (expected.non_table_cells?.length ?? 0) !==
      envelope.physicalExecutionProof.nonTableCellCount ||
    digestCanonical(expected) !== envelope.physicalExecutionProof.digest ||
    digestCanonical(observed) !== envelope.physicalExecutionProof.digest
  ) {
    throw executionFailure("PHYSICAL_EXECUTION_PROOF_MISMATCH");
  }
  return expected;
}

function assertSourceIdentity(
  source: { sheet: string; address: string; row: number; col: number },
  sheet: string,
  address: string,
): void {
  const parsed = parseCell(address);
  if (
    source.sheet !== sheet ||
    source.address !== address ||
    source.row !== parsed.row ||
    source.col !== parsed.col
  ) {
    throw executionFailure("SOURCE_COORDINATE_MISMATCH");
  }
}

function isValidDimensionScalar(value: unknown): value is string | number {
  return (
    (typeof value === "string" && value.trim().length > 0) ||
    (typeof value === "number" && Number.isFinite(value))
  );
}

function sameScalar(left: unknown, right: unknown): boolean {
  return Object.is(left, right);
}

function expandOwnedSelectors(
  declarations: SemanticTableMapV2["logicalTable"]["values"]["target"],
): string[] {
  const addresses: string[] = [];
  for (const declaration of declarations) {
    for (const selector of declaration.selectors) {
      const cardinality =
        "address" in selector ? 1 : rangeCardinality(selector.range);
      if (
        addresses.length + cardinality >
        MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS
      ) {
        throw executionFailure("ROLE_RESOURCE_LIMIT");
      }
      addresses.push(
        ...("address" in selector
          ? [selector.address]
          : expandRange(selector.range)),
      );
      if (addresses.length > MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS) {
        throw executionFailure("ROLE_RESOURCE_LIMIT");
      }
    }
  }
  return sortAddresses(addresses);
}

function isCanonicalUniqueAddressList(addresses: string[]): boolean {
  return (
    isUnique(addresses) &&
    addresses.every((address) => {
      try {
        return formatCell(parseCell(address)) === address;
      } catch {
        return false;
      }
    }) &&
    canonicalJson(addresses) === canonicalJson(sortAddresses(addresses))
  );
}

function isUnique(values: readonly string[]): boolean {
  return new Set(values).size === values.length;
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

function assertUnique(values: string[], code: string): void {
  if (new Set(values).size !== values.length)
    throw new AtomicMapError(
      "ownership",
      code,
      `${code}: values must be unique.`,
    );
}

function assertWithinBounds(
  address: string,
  context: CompactSemanticContext,
): void {
  const cell = parseCell(address);
  if (
    cell.row > context.dimensions.rows ||
    cell.col > context.dimensions.columns
  )
    throw new AtomicMapError(
      "catalog",
      "CATALOG_ADDRESS_OUT_OF_BOUNDS",
      `${address} is outside the context bounds.`,
    );
}

function rangeCardinality(range: string): number {
  const parsed = parseRange(range);
  const rows = parsed.end.row - parsed.start.row + 1;
  const columns = parsed.end.col - parsed.start.col + 1;
  const cardinality = rows * columns;
  if (!Number.isSafeInteger(cardinality) || cardinality < 1) {
    throw new Error("INVALID_RANGE_CARDINALITY");
  }
  return cardinality;
}

function sortAddresses(addresses: string[]): string[] {
  return [...addresses].sort(compareAddress);
}

function compareAddress(left: string, right: string): number {
  const a = parseCell(left);
  const b = parseCell(right);
  return a.row - b.row || a.col - b.col;
}

function compareSelector(
  left: { kind: "address" | "range"; value: string },
  right: { kind: "address" | "range"; value: string },
): number {
  const leftStart =
    left.kind === "address" ? left.value : left.value.split(":")[0];
  const rightStart =
    right.kind === "address" ? right.value : right.value.split(":")[0];
  return (
    compareAddress(leftStart, rightStart) ||
    left.kind.localeCompare(right.kind) ||
    left.value.localeCompare(right.value)
  );
}

function canonicalize(value: unknown): unknown {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("NON_FINITE_CANONICAL_NUMBER");
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

function digestCanonical(value: unknown): string {
  return digestBytes(JSON.stringify(canonicalize(value)));
}

function digestBytes(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function executionFailure(code: string): Error {
  return new Error(`ATOMIC_SEMANTIC_MAP_V2_${code}`);
}
