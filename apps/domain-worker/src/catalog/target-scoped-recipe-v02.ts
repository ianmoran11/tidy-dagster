/* Isolated target-scoped semantic map / RecipeV02 runtime. No RecipeV01 fallback. */
import { createHash } from "node:crypto";
import { types as utilTypes } from "node:util";
import { z } from "zod";
import {
  expandRange,
  formatCell,
  formatRange,
  parseCell,
  parseRange,
} from "../address.js";
import {
  buildHeaderDirectionGroups,
  resolveRelationshipAttachmentAtAddress,
} from "../executor/relationshipResolution.js";
import type { OutputScalar } from "../executor/types.js";
import type { ParsedSheet, TidyCell } from "../workbook/types.js";
import {
  atomicRegionCatalogSchema,
  digestAtomicRegionCatalog,
  logicalOutputNameV2Schema,
  type AtomicRegionCatalog,
} from "./semantic-map-v2.js";
import { semanticDirectionSchema } from "./semantic-map-v1.js";
import type { SemanticDirection } from "./semantic-map-v1.js";

export const TARGET_SCOPED_SEMANTIC_MAP_V1 =
  "target-scoped-semantic-map-v1" as const;
export const TARGET_SCOPED_RECIPE_V02 = "TargetScopedRecipeV02" as const;
export const TARGET_SCOPED_COMPILER_V02 =
  "target-scoped-recipe-v02-compiler-v1" as const;
export const TARGET_SCOPED_ENVELOPE_V02 =
  "target-scoped-compilation-envelope/v02" as const;
export const TARGET_SCOPED_EXECUTION_V02 =
  "target-scoped-logical-execution/v02" as const;
export const TARGET_SCOPED_SOURCE_CONTEXT_V1 =
  "target-scoped-source-context/v1" as const;

export const MAX_TARGET_SCOPED_JSON_BYTES = 8 * 1024 * 1024;
export const MAX_TARGET_SCOPED_JSON_NODES = 250_000;
export const MAX_TARGET_SCOPED_CATALOG_BYTES = 16 * 1024 * 1024;
export const MAX_TARGET_SCOPED_CATALOG_NODES = 500_000;
export const MAX_TARGET_SCOPED_CATALOG_CANDIDATES = 512;
export const MAX_TARGET_SCOPED_CATALOG_SEGMENTS = 16_384;
export const MAX_TARGET_SCOPED_CATALOG_CELLS = 500_000;
export const MAX_TARGET_SCOPED_ENVELOPE_BYTES = 32 * 1024 * 1024;
export const MAX_TARGET_SCOPED_ENVELOPE_NODES = 500_000;
export const MAX_TARGET_SCOPED_EXECUTION_BYTES = 128 * 1024 * 1024;
export const MAX_TARGET_SCOPED_EXECUTION_NODES = 2_000_000;
export const MAX_TARGET_SCOPED_TARGETS = 8_192;
export const MAX_TARGET_SCOPED_DIMENSIONS = 64;
export const MAX_TARGET_SCOPED_BINDINGS = 250_000;
export const MAX_TARGET_SCOPED_TOTAL_SELECTORS = 10_000;
export const MAX_TARGET_SCOPED_SELECTORS_PER_ROLE = 512;
export const MAX_TARGET_SCOPED_EXPANDED_SELECTED_CELLS = 100_000;
export const MAX_TARGET_SCOPED_SHEET_CELLS = 500_000;
export const MAX_TARGET_SCOPED_RESOLUTION_OPERATIONS = 2_000_000;
export const TARGET_SCOPED_LIMITS = Object.freeze({
  mapRecipeBytes: MAX_TARGET_SCOPED_JSON_BYTES,
  mapRecipeNodes: MAX_TARGET_SCOPED_JSON_NODES,
  envelopeBytes: MAX_TARGET_SCOPED_ENVELOPE_BYTES,
  envelopeNodes: MAX_TARGET_SCOPED_ENVELOPE_NODES,
  executionBytes: MAX_TARGET_SCOPED_EXECUTION_BYTES,
  executionNodes: MAX_TARGET_SCOPED_EXECUTION_NODES,
  catalogBytes: MAX_TARGET_SCOPED_CATALOG_BYTES,
  catalogNodes: MAX_TARGET_SCOPED_CATALOG_NODES,
  catalogCandidates: MAX_TARGET_SCOPED_CATALOG_CANDIDATES,
  catalogSegments: MAX_TARGET_SCOPED_CATALOG_SEGMENTS,
  catalogCells: MAX_TARGET_SCOPED_CATALOG_CELLS,
  bindings: MAX_TARGET_SCOPED_BINDINGS,
  selectors: MAX_TARGET_SCOPED_TOTAL_SELECTORS,
  selectorsPerRole: MAX_TARGET_SCOPED_SELECTORS_PER_ROLE,
  selectedCells: MAX_TARGET_SCOPED_EXPANDED_SELECTED_CELLS,
  sheetCells: MAX_TARGET_SCOPED_SHEET_CELLS,
  targets: MAX_TARGET_SCOPED_TARGETS,
  dimensions: MAX_TARGET_SCOPED_DIMENSIONS,
  operations: MAX_TARGET_SCOPED_RESOLUTION_OPERATIONS,
});
export function assertTargetScopedCountLimit(
  kind: keyof typeof TARGET_SCOPED_LIMITS,
  value: number,
): void {
  if (
    !Number.isSafeInteger(value) ||
    value < 0 ||
    value > TARGET_SCOPED_LIMITS[kind]
  )
    throw new Error(`TARGET_SCOPED_${kind.toUpperCase()}_LIMIT`);
}

const digestSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/);
const idSchema = z.string().regex(/^[a-z][a-z0-9-]{0,79}$/);
const addressSchema = z.string().refine((value) => {
  try {
    return formatCell(parseCell(value)) === value;
  } catch {
    return false;
  }
}, "Expected canonical R1C1 address");
const rangeSchema = z.string().refine((value) => {
  try {
    return formatRange(parseRange(value)) === value;
  } catch {
    return false;
  }
}, "Expected canonical R1C1 range");
const selectorSchema = z.union([
  z.object({ address: addressSchema }).strict(),
  z.object({ range: rangeSchema }).strict(),
]);
const subsetSchema = z
  .object({
    id: idSchema,
    regionId: z.string().min(1).max(80),
    selectors: z.array(selectorSchema).min(1),
  })
  .strict();
const sourceContextSchema = z
  .object({
    version: z.literal(TARGET_SCOPED_SOURCE_CONTEXT_V1),
    workbookDigest: digestSchema,
    physicalSheet: z.string().min(1).max(200),
  })
  .strict();
export type TargetScopedSourceContext = z.infer<typeof sourceContextSchema>;

const dimensionSchema = z
  .object({ id: idSchema, name: logicalOutputNameV2Schema })
  .strict();
const attachmentSchema = z
  .object({
    id: idSchema,
    dimensionId: idSchema,
    direction: semanticDirectionSchema,
    selectedAddress: addressSchema,
    universeId: idSchema,
  })
  .strict();
const vectorSchema = z
  .object({
    id: idSchema,
    attachmentIds: z.array(idSchema).min(1),
  })
  .strict();
const targetSchema = z
  .object({
    address: addressSchema,
    targetSetId: idSchema,
    vectorId: idSchema,
  })
  .strict();

export const targetScopedSemanticMapV1Schema = z
  .object({
    version: z.literal(TARGET_SCOPED_SEMANTIC_MAP_V1),
    catalog: z
      .object({
        version: z.enum([
          "semantic-region-catalog-v1",
          "semantic-region-catalog-v5-adjacent-year-aware",
        ]),
        bytesDigest: digestSchema,
        contentDigest: digestSchema,
      })
      .strict(),
    source: sourceContextSchema,
    logicalTable: z
      .object({
        id: idSchema,
        name: z.string().trim().min(1).max(200),
        valuesName: logicalOutputNameV2Schema,
        dimensions: z.array(dimensionSchema).min(1),
      })
      .strict(),
    targetSets: z.array(subsetSchema).min(1),
    sourceUniverses: z.array(subsetSchema).min(1),
    attachments: z.array(attachmentSchema).min(1),
    vectors: z.array(vectorSchema).min(1),
    targets: z.array(targetSchema).min(1),
  })
  .strict();
export type TargetScopedSemanticMapV1 = z.infer<
  typeof targetScopedSemanticMapV1Schema
>;

export type TargetScopedRecipeV02 = {
  version: typeof TARGET_SCOPED_RECIPE_V02;
  sheet: string;
  table: { id: string; name: string; valuesName: string };
  dimensions: Array<{ id: string; name: string }>;
  sourceUniverses: Array<{ id: string; addresses: string[] }>;
  attachments: Array<{
    id: string;
    dimensionId: string;
    direction: SemanticDirection;
    selectedAddress: string;
    universeId: string;
  }>;
  vectors: Array<{ id: string; attachmentIds: string[] }>;
  targets: Array<{ address: string; vectorId: string }>;
};

export const targetScopedRecipeV02Schema: z.ZodType<TargetScopedRecipeV02> = z
  .object({
    version: z.literal(TARGET_SCOPED_RECIPE_V02),
    sheet: z.string().min(1).max(200),
    table: z
      .object({
        id: idSchema,
        name: z.string().min(1).max(200),
        valuesName: logicalOutputNameV2Schema,
      })
      .strict(),
    dimensions: z.array(dimensionSchema).min(1),
    sourceUniverses: z
      .array(
        z
          .object({
            id: idSchema,
            addresses: z.array(addressSchema).min(1),
          })
          .strict(),
      )
      .min(1),
    attachments: z.array(attachmentSchema).min(1),
    vectors: z.array(vectorSchema).min(1),
    targets: z
      .array(z.object({ address: addressSchema, vectorId: idSchema }).strict())
      .min(1),
  })
  .strict();

export function parseTargetScopedRecipeV02(raw: string): TargetScopedRecipeV02 {
  assertTargetScopedCountLimit("mapRecipeBytes", Buffer.byteLength(raw));
  assertRawJsonBudget(
    raw,
    MAX_TARGET_SCOPED_JSON_NODES,
    "RECIPE_RESOURCE_LIMIT",
  );
  const value: unknown = JSON.parse(raw);
  assertStrictInertJson(
    value,
    MAX_TARGET_SCOPED_JSON_NODES,
    MAX_TARGET_SCOPED_JSON_BYTES,
    "RECIPE_RESOURCE_LIMIT",
  );
  const recipe = targetScopedRecipeV02Schema.parse(value);
  validateStandaloneRecipe(recipe);
  return recipe;
}

export type TargetScopedAttachmentTraceV02 = {
  dimensionId: string;
  dimensionName: string;
  direction: SemanticDirection;
  universeId: string;
  candidates: string[];
  selected: string;
  source: {
    sheet: string;
    address: string;
    row: number;
    col: number;
    data_type: TidyCell["data_type"];
  };
  value: string | number;
  missing: false;
  ambiguous: false;
};
export type TargetScopedExecutionV02 = {
  version: typeof TARGET_SCOPED_EXECUTION_V02;
  recipeVersion: typeof TARGET_SCOPED_RECIPE_V02;
  source: TargetScopedSourceContext;
  table: {
    id: string;
    name: string;
    sheet: string;
    rows: Array<Record<string, unknown>>;
    trace: Array<{
      target: {
        sheet: string;
        address: string;
        row: number;
        col: number;
        data_type: TidyCell["data_type"];
      };
      value: OutputScalar;
      attachments: TargetScopedAttachmentTraceV02[];
    }>;
  };
  warnings: [];
  providerCalls: 0;
  acceptanceAuthority: false;
  trainingEligibility: false;
};

export type TargetScopedAttachmentProof = {
  targetAddress: string;
  vectorId: string;
  dimensions: Array<{
    dimensionId: string;
    direction: SemanticDirection;
    universeId: string;
    candidates: string[];
    selectedAddress: string;
    rawValue: string | number;
  }>;
};

export type TargetScopedCompilationEnvelopeV02 = {
  version: typeof TARGET_SCOPED_ENVELOPE_V02;
  compilerVersion: typeof TARGET_SCOPED_COMPILER_V02;
  source: TargetScopedSourceContext;
  map: {
    version: typeof TARGET_SCOPED_SEMANTIC_MAP_V1;
    bytesDigest: string;
    digest: string;
  };
  catalog: {
    version: AtomicRegionCatalog["version"];
    bytesDigest: string;
    contentDigest: string;
    sheet: string;
  };
  sheetProof: {
    sheet: string;
    usedRange: string | null;
    rows: number;
    columns: number;
    cells: number;
    merges: number;
    digest: string;
  };
  recipe: TargetScopedRecipeV02;
  recipeDigest: string;
  targetManifest: { count: number; digest: string };
  attachmentManifest: { count: number; operations: number; digest: string };
  logicalExecutionProof: { rows: number; digest: string };
  envelopeDigest: string;
};

export const targetScopedCompilationEnvelopeV02Schema: z.ZodType<TargetScopedCompilationEnvelopeV02> =
  z
    .object({
      version: z.literal(TARGET_SCOPED_ENVELOPE_V02),
      compilerVersion: z.literal(TARGET_SCOPED_COMPILER_V02),
      source: sourceContextSchema,
      map: z
        .object({
          version: z.literal(TARGET_SCOPED_SEMANTIC_MAP_V1),
          bytesDigest: digestSchema,
          digest: digestSchema,
        })
        .strict(),
      catalog: z
        .object({
          version: z.enum([
            "semantic-region-catalog-v1",
            "semantic-region-catalog-v5-adjacent-year-aware",
          ]),
          bytesDigest: digestSchema,
          contentDigest: digestSchema,
          sheet: z.string().min(1).max(200),
        })
        .strict(),
      sheetProof: z
        .object({
          sheet: z.string().min(1).max(200),
          usedRange: z.string().nullable(),
          rows: z.number().int().nonnegative(),
          columns: z.number().int().nonnegative(),
          cells: z.number().int().nonnegative(),
          merges: z.number().int().nonnegative(),
          digest: digestSchema,
        })
        .strict(),
      recipe: targetScopedRecipeV02Schema,
      recipeDigest: digestSchema,
      targetManifest: z
        .object({
          count: z.number().int().positive(),
          digest: digestSchema,
        })
        .strict(),
      attachmentManifest: z
        .object({
          count: z.number().int().positive(),
          operations: z.number().int().nonnegative(),
          digest: digestSchema,
        })
        .strict(),
      logicalExecutionProof: z
        .object({
          rows: z.number().int().positive(),
          digest: digestSchema,
        })
        .strict(),
      envelopeDigest: digestSchema,
    })
    .strict();

export function parseTargetScopedCompilationEnvelopeV02(
  value: unknown,
): TargetScopedCompilationEnvelopeV02 {
  assertStrictInertJson(
    value,
    MAX_TARGET_SCOPED_ENVELOPE_NODES,
    MAX_TARGET_SCOPED_ENVELOPE_BYTES,
    "ENVELOPE_RESOURCE_LIMIT",
    "runtime",
  );
  const envelope = targetScopedCompilationEnvelopeV02Schema.parse(value);
  enforceCountLimit(
    "targets",
    envelope.targetManifest.count,
    "runtime",
    "ENVELOPE_TARGET_LIMIT",
  );
  enforceCountLimit(
    "bindings",
    envelope.attachmentManifest.count,
    "runtime",
    "ENVELOPE_BINDING_LIMIT",
  );
  enforceCountLimit(
    "operations",
    envelope.attachmentManifest.operations,
    "runtime",
    "ENVELOPE_OPERATION_LIMIT",
  );
  validateStandaloneRecipe(envelope.recipe);
  return envelope;
}

export type TargetScopedCompilationResult =
  | { ok: true; envelope: TargetScopedCompilationEnvelopeV02 }
  | { ok: false; stage: string; code: string; message: string };

class TargetScopedError extends Error {
  constructor(
    readonly stage: string,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export function digestTargetScopedBytes(value: string | Buffer): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}
export function digestTargetScopedCanonical(value: unknown): string {
  return digestTargetScopedBytes(canonicalJson(value));
}
export function digestTargetScopedEnvelopeV02(
  envelope: TargetScopedCompilationEnvelopeV02,
): string {
  if (utilTypes.isProxy(envelope)) throw new Error("PROXY_ENVELOPE_REJECTED");
  const { envelopeDigest: _ignored, ...rest } = envelope;
  return digestTargetScopedCanonical(rest);
}

export function parseTargetScopedSemanticMapV1(
  raw: string,
): TargetScopedSemanticMapV1 {
  assertTargetScopedCountLimit("mapRecipeBytes", Buffer.byteLength(raw));
  assertRawJsonBudget(
    raw,
    MAX_TARGET_SCOPED_JSON_NODES,
    "TARGET_SCOPED_MAP_RESOURCE_LIMIT",
  );
  const value: unknown = JSON.parse(raw);
  assertStrictInertJson(
    value,
    MAX_TARGET_SCOPED_JSON_NODES,
    MAX_TARGET_SCOPED_JSON_BYTES,
    "TARGET_SCOPED_MAP_RESOURCE_LIMIT",
  );
  const map = normalizeMap(targetScopedSemanticMapV1Schema.parse(value));
  validateMapResourceCounts(map);
  return map;
}

export function compileTargetScopedRecipeV02(input: {
  mapRaw: string;
  expectedMapBytesDigest: string;
  catalogRaw: string;
  expectedCatalogBytesDigest: string;
  sheet: ParsedSheet;
  source: TargetScopedSourceContext;
}): TargetScopedCompilationResult {
  try {
    const envelope = compileOrThrow(input);
    return { ok: true, envelope };
  } catch (error) {
    if (error instanceof TargetScopedError)
      return {
        ok: false,
        stage: error.stage,
        code: error.code,
        message: error.message,
      };
    return {
      ok: false,
      stage: "internal",
      code: "TARGET_SCOPED_INTERNAL_ERROR",
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

function compileOrThrow(input: {
  mapRaw: string;
  expectedMapBytesDigest: string;
  catalogRaw: string;
  expectedCatalogBytesDigest: string;
  sheet: ParsedSheet;
  source: TargetScopedSourceContext;
}): TargetScopedCompilationEnvelopeV02 {
  if (utilTypes.isProxy(input.sheet)) fail("sheet", "SHEET_PROXY_REJECTED");
  if (digestTargetScopedBytes(input.mapRaw) !== input.expectedMapBytesDigest)
    fail("trust", "MAP_EXTERNAL_PIN_MISMATCH");
  if (
    digestTargetScopedBytes(input.catalogRaw) !==
    input.expectedCatalogBytesDigest
  )
    fail("trust", "CATALOG_EXTERNAL_PIN_MISMATCH");
  enforceCountLimit(
    "catalogBytes",
    Buffer.byteLength(input.catalogRaw),
    "catalog",
    "CATALOG_BYTE_LIMIT",
  );
  let map: TargetScopedSemanticMapV1;
  let catalog: AtomicRegionCatalog;
  try {
    map = parseTargetScopedSemanticMapV1(input.mapRaw);
  } catch (error) {
    fail("schema", "TARGET_SCOPED_MAP_INVALID", error);
  }
  let catalogValue: unknown;
  try {
    assertRawJsonBudget(
      input.catalogRaw,
      MAX_TARGET_SCOPED_CATALOG_NODES,
      "CATALOG_RESOURCE_LIMIT",
      "catalog",
    );
    catalogValue = JSON.parse(input.catalogRaw);
  } catch (error) {
    fail("catalog", "CATALOG_JSON_INVALID", error);
  }
  assertStrictInertJson(
    catalogValue,
    MAX_TARGET_SCOPED_CATALOG_NODES,
    MAX_TARGET_SCOPED_CATALOG_BYTES,
    "CATALOG_RESOURCE_LIMIT",
    "catalog",
  );
  const parsedCatalog = atomicRegionCatalogSchema.safeParse(catalogValue);
  if (!parsedCatalog.success)
    fail("catalog", "CATALOG_SCHEMA_INVALID", parsedCatalog.error);
  catalog = parsedCatalog.data;
  const source = sourceContextSchema.parse(input.source);
  if (canonicalJson(source) !== canonicalJson(map.source))
    fail("trust", "SOURCE_CONTEXT_MISMATCH");
  if (
    source.physicalSheet !== input.sheet.name ||
    catalog.sheet !== input.sheet.name
  )
    fail("trust", "PHYSICAL_SHEET_MISMATCH");
  if (
    map.catalog.version !== catalog.version ||
    map.catalog.bytesDigest !== input.expectedCatalogBytesDigest ||
    map.catalog.contentDigest !== digestAtomicRegionCatalog(catalog)
  )
    fail("trust", "CATALOG_IDENTITY_MISMATCH");
  validateSheet(input.sheet);
  validateOutputKeys(map);
  validateUniqueMapIds(map);
  const catalogRegions = expandCatalog(catalog, input.sheet);
  const selectionBudget = { cells: 0 };
  const targetSets = expandSubsets(
    map.targetSets,
    catalogRegions,
    input.sheet,
    "target",
    selectionBudget,
  );
  const targetOwners = new Map<string, string>();
  for (const [setId, addresses] of targetSets) {
    for (const address of addresses) {
      if (targetOwners.has(address))
        fail("ownership", "DUPLICATE_TARGET_OWNER");
      targetOwners.set(address, setId);
    }
  }
  const universes = expandSubsets(
    map.sourceUniverses,
    catalogRegions,
    input.sheet,
    "source",
    selectionBudget,
  );
  const allSourceAddresses = new Set([...universes.values()].flat());
  if (
    [...targetOwners.keys()].some((address) => allSourceAddresses.has(address))
  )
    fail("ownership", "TARGET_SOURCE_ROLE_OVERLAP");

  const targetSetById = new Map(
    map.targetSets.map((entry) => [entry.id, entry]),
  );
  const universeById = new Map(
    map.sourceUniverses.map((entry) => [entry.id, entry]),
  );
  const dimensions = new Map(
    map.logicalTable.dimensions.map((entry) => [entry.id, entry]),
  );
  const attachments = new Map(
    map.attachments.map((entry) => [entry.id, entry]),
  );
  const vectors = new Map(map.vectors.map((entry) => [entry.id, entry]));
  let bindingCount = 0;
  for (const vector of map.vectors) {
    bindingCount += vector.attachmentIds.length;
    enforceCountLimit("bindings", bindingCount, "ownership", "BINDING_LIMIT");
    const seen = new Set<string>();
    const ordered = vector.attachmentIds.map((id) => attachments.get(id)!);
    for (const [index, attachment] of ordered.entries()) {
      const expected = map.logicalTable.dimensions[index]?.id;
      if (
        !attachment ||
        attachment.dimensionId !== expected ||
        seen.has(attachment.dimensionId)
      )
        fail("ownership", "VECTOR_DIMENSION_ORDER_MISMATCH");
      seen.add(attachment.dimensionId);
    }
    if (seen.size !== dimensions.size)
      fail("ownership", "VECTOR_DIMENSION_MISSING");
  }
  let preflightOperations = 0;
  let targetBindingCount = 0;
  for (const target of map.targets) {
    const vector = vectors.get(target.vectorId);
    if (!vector) fail("ownership", "MISSING_VECTOR");
    targetBindingCount += vector.attachmentIds.length;
    enforceCountLimit(
      "bindings",
      targetBindingCount,
      "ownership",
      "BINDING_LIMIT",
    );
    for (const attachmentId of vector.attachmentIds) {
      const attachment = attachments.get(attachmentId);
      const universe = attachment && universes.get(attachment.universeId);
      if (!attachment || !universe)
        fail("ownership", "MISSING_ATTACHMENT_UNIVERSE");
      preflightOperations += universe.length + 1;
      enforceCountLimit(
        "operations",
        preflightOperations,
        "ownership",
        "RESOLUTION_OPERATION_LIMIT",
      );
    }
  }

  const usedTargets = new Set<string>();
  const usedTargetSets = new Set<string>();
  const usedVectors = new Set<string>();
  const usedAttachments = new Set<string>();
  const usedUniverseAddresses = new Map<string, Set<string>>();
  const cellByAddress = new Map(
    input.sheet.cells.map((cell) => [cell.address, cell]),
  );
  const proof: TargetScopedAttachmentProof[] = [];
  const operations = preflightOperations;
  for (const target of map.targets) {
    if (usedTargets.has(target.address)) fail("ownership", "DUPLICATE_TARGET");
    usedTargets.add(target.address);
    const targetSet = targetSets.get(target.targetSetId);
    if (
      !targetSetById.has(target.targetSetId) ||
      !targetSet?.includes(target.address)
    )
      fail("ownership", "TARGET_OUTSIDE_PARENT");
    usedTargetSets.add(target.targetSetId);
    const vector = vectors.get(target.vectorId);
    if (!vector) fail("ownership", "MISSING_VECTOR");
    usedVectors.add(target.vectorId);
    const targetCell = cellByAddress.get(target.address);
    if (!isValueScalar(targetCell?.value))
      fail("ownership", "INVALID_TARGET_VALUE");
    const dimensionProof: TargetScopedAttachmentProof["dimensions"] = [];
    for (const attachmentId of vector.attachmentIds) {
      const attachment = attachments.get(attachmentId)!;
      usedAttachments.add(attachmentId);
      const universe = universes.get(attachment.universeId);
      if (
        !universeById.has(attachment.universeId) ||
        !universe?.includes(attachment.selectedAddress)
      )
        fail("ownership", "SOURCE_OUTSIDE_PARENT");
      const groups = buildHeaderDirectionGroups({
        headerAddresses: universe,
        valueAddresses: [target.address],
        direction: attachment.direction,
      });
      const resolved = resolveRelationshipAttachmentAtAddress(
        groups,
        target.address,
      );
      if (
        resolved.candidates.length !== 1 ||
        resolved.selectedAddress !== attachment.selectedAddress
      )
        fail("ownership", "TARGET_SCOPED_AMBIGUOUS_SOURCE");
      const sourceCell = cellByAddress.get(attachment.selectedAddress);
      if (!isDimensionScalar(sourceCell?.value))
        fail("ownership", "INVALID_DIMENSION_SOURCE");
      const used =
        usedUniverseAddresses.get(attachment.universeId) ?? new Set<string>();
      used.add(attachment.selectedAddress);
      usedUniverseAddresses.set(attachment.universeId, used);
      dimensionProof.push({
        dimensionId: attachment.dimensionId,
        direction: attachment.direction,
        universeId: attachment.universeId,
        candidates: [...resolved.candidates],
        selectedAddress: attachment.selectedAddress,
        rawValue: sourceCell.value,
      });
    }
    proof.push({
      targetAddress: target.address,
      vectorId: target.vectorId,
      dimensions: dimensionProof,
    });
  }
  const declaredTargets = new Set([...targetSets.values()].flat());
  if (
    declaredTargets.size !== usedTargets.size ||
    [...declaredTargets].some((address) => !usedTargets.has(address))
  )
    fail("ownership", "TARGET_COVERAGE_MISMATCH");
  if (usedTargetSets.size !== targetSets.size)
    fail("ownership", "UNUSED_TARGET_SET");
  if (usedVectors.size !== vectors.size) fail("ownership", "UNUSED_VECTOR");
  if (usedAttachments.size !== attachments.size)
    fail("ownership", "UNUSED_ATTACHMENT");
  for (const [id, addresses] of universes) {
    const used = usedUniverseAddresses.get(id) ?? new Set<string>();
    if (addresses.some((address) => !used.has(address)))
      fail("ownership", "UNUSED_SOURCE_DECLARATION");
  }

  const recipe: TargetScopedRecipeV02 = {
    version: TARGET_SCOPED_RECIPE_V02,
    sheet: input.sheet.name,
    table: {
      id: map.logicalTable.id,
      name: map.logicalTable.name,
      valuesName: map.logicalTable.valuesName,
    },
    dimensions: map.logicalTable.dimensions.map((entry) => ({ ...entry })),
    sourceUniverses: map.sourceUniverses.map((entry) => ({
      id: entry.id,
      addresses: [...universes.get(entry.id)!],
    })),
    attachments: map.attachments.map((entry) => ({ ...entry })),
    vectors: map.vectors.map((entry) => ({
      id: entry.id,
      attachmentIds: [...entry.attachmentIds],
    })),
    targets: map.targets.map((entry) => ({
      address: entry.address,
      vectorId: entry.vectorId,
    })),
  };
  assertStrictInertJson(
    recipe,
    MAX_TARGET_SCOPED_JSON_NODES,
    MAX_TARGET_SCOPED_JSON_BYTES,
    "RECIPE_RESOURCE_LIMIT",
    "compiler",
  );
  validateStandaloneRecipe(recipe);
  const execution = executeRecipeV02(recipe, input.sheet, source);
  const addresses = recipe.targets.map((entry) => entry.address);
  const sheetProof = buildSheetProof(input.sheet);
  const attachmentCount = proof.reduce(
    (sum, entry) => sum + entry.dimensions.length,
    0,
  );
  const withoutDigest = {
    version: TARGET_SCOPED_ENVELOPE_V02,
    compilerVersion: TARGET_SCOPED_COMPILER_V02,
    source,
    map: {
      version: TARGET_SCOPED_SEMANTIC_MAP_V1,
      bytesDigest: input.expectedMapBytesDigest,
      digest: digestTargetScopedCanonical(map),
    },
    catalog: {
      version: catalog.version,
      bytesDigest: input.expectedCatalogBytesDigest,
      contentDigest: digestAtomicRegionCatalog(catalog),
      sheet: catalog.sheet,
    },
    sheetProof,
    recipe,
    recipeDigest: digestTargetScopedCanonical(recipe),
    targetManifest: {
      count: addresses.length,
      digest: digestTargetScopedCanonical(addresses),
    },
    attachmentManifest: {
      count: attachmentCount,
      operations,
      digest: digestTargetScopedCanonical(proof),
    },
    logicalExecutionProof: {
      rows: execution.table.rows.length,
      digest: digestTargetScopedCanonical(execution),
    },
  } satisfies Omit<TargetScopedCompilationEnvelopeV02, "envelopeDigest">;
  const envelope: TargetScopedCompilationEnvelopeV02 = {
    ...withoutDigest,
    envelopeDigest: digestTargetScopedCanonical(withoutDigest),
  };
  assertStrictInertJson(
    envelope,
    MAX_TARGET_SCOPED_ENVELOPE_NODES,
    MAX_TARGET_SCOPED_ENVELOPE_BYTES,
    "ENVELOPE_RESOURCE_LIMIT",
    "compiler",
  );
  targetScopedCompilationEnvelopeV02Schema.parse(envelope);
  return envelope;
}

export function executeTargetScopedRecipeV02(
  envelope: TargetScopedCompilationEnvelopeV02,
  input: {
    mapRaw: string;
    catalogRaw: string;
    sheet: ParsedSheet;
    source: TargetScopedSourceContext;
    trustedEnvelopeDigest: string;
    suppliedExecution?: unknown;
  },
): TargetScopedExecutionV02 {
  const trusted = parseTargetScopedCompilationEnvelopeV02(envelope);
  if (
    input.trustedEnvelopeDigest !== trusted.envelopeDigest ||
    digestTargetScopedEnvelopeV02(trusted) !== input.trustedEnvelopeDigest
  )
    fail("runtime", "TRUSTED_ENVELOPE_DIGEST_MISMATCH");
  const recompiled = compileOrThrow({
    mapRaw: input.mapRaw,
    expectedMapBytesDigest: trusted.map.bytesDigest,
    catalogRaw: input.catalogRaw,
    expectedCatalogBytesDigest: trusted.catalog.bytesDigest,
    sheet: input.sheet,
    source: input.source,
  });
  if (canonicalJson(recompiled) !== canonicalJson(trusted))
    fail("runtime", "ENVELOPE_RECOMPILE_MISMATCH");
  const expected = executeRecipeV02(trusted.recipe, input.sheet, input.source);
  if (
    digestTargetScopedCanonical(expected) !==
    trusted.logicalExecutionProof.digest
  )
    fail("runtime", "LOGICAL_EXECUTION_PROOF_MISMATCH");
  if (input.suppliedExecution !== undefined) {
    parseTargetScopedExecutionV02(input.suppliedExecution, trusted.recipe);
    if (canonicalJson(input.suppliedExecution) !== canonicalJson(expected))
      fail("runtime", "SUPPLIED_EXECUTION_MISMATCH");
  }
  return structuredClone(expected);
}

function executeRecipeV02(
  recipe: TargetScopedRecipeV02,
  sheet: ParsedSheet,
  source: TargetScopedSourceContext,
): TargetScopedExecutionV02 {
  const cells = new Map(sheet.cells.map((cell) => [cell.address, cell]));
  const universeById = new Map(
    recipe.sourceUniverses.map((entry) => [entry.id, entry.addresses]),
  );
  const attachmentById = new Map(
    recipe.attachments.map((entry) => [entry.id, entry]),
  );
  const vectorById = new Map(recipe.vectors.map((entry) => [entry.id, entry]));
  const dimensionById = new Map(
    recipe.dimensions.map((entry) => [entry.id, entry]),
  );
  const rows: Array<Record<string, unknown>> = [];
  const trace: TargetScopedExecutionV02["table"]["trace"] = [];
  for (const target of recipe.targets) {
    const targetCell = cells.get(target.address)!;
    const position = parseCell(target.address);
    const row: Record<string, unknown> = {
      [recipe.table.valuesName]: targetCell.value,
      _source: {
        sheet: sheet.name,
        address: target.address,
        row: position.row,
        col: position.col,
        data_type: targetCell.data_type,
      },
    };
    const attachments: TargetScopedAttachmentTraceV02[] = [];
    const vector = vectorById.get(target.vectorId)!;
    for (const id of vector.attachmentIds) {
      const binding = attachmentById.get(id)!;
      const dimension = dimensionById.get(binding.dimensionId)!;
      const sourceCell = cells.get(binding.selectedAddress)!;
      const sourcePosition = parseCell(binding.selectedAddress);
      const universe = universeById.get(binding.universeId)!;
      const resolved = resolveRelationshipAttachmentAtAddress(
        buildHeaderDirectionGroups({
          headerAddresses: universe,
          valueAddresses: [target.address],
          direction: binding.direction,
        }),
        target.address,
      );
      row[dimension.name] = sourceCell.value;
      row[`${dimension.name}_source`] = binding.selectedAddress;
      attachments.push({
        dimensionId: dimension.id,
        dimensionName: dimension.name,
        direction: binding.direction,
        universeId: binding.universeId,
        candidates: [...resolved.candidates],
        selected: binding.selectedAddress,
        source: {
          sheet: sheet.name,
          address: binding.selectedAddress,
          row: sourcePosition.row,
          col: sourcePosition.col,
          data_type: sourceCell.data_type,
        },
        value: sourceCell.value as string | number,
        missing: false,
        ambiguous: false,
      });
    }
    rows.push(row);
    trace.push({
      target: {
        sheet: sheet.name,
        address: target.address,
        row: position.row,
        col: position.col,
        data_type: targetCell.data_type,
      },
      value: targetCell.value,
      attachments,
    });
  }
  return {
    version: TARGET_SCOPED_EXECUTION_V02,
    recipeVersion: TARGET_SCOPED_RECIPE_V02,
    source: { ...source },
    table: {
      id: recipe.table.id,
      name: recipe.table.name,
      sheet: sheet.name,
      rows,
      trace,
    },
    warnings: [],
    providerCalls: 0,
    acceptanceAuthority: false,
    trainingEligibility: false,
  };
}

function validateStandaloneRecipe(recipe: TargetScopedRecipeV02): void {
  enforceCountLimit("targets", recipe.targets.length, "schema", "TARGET_LIMIT");
  enforceCountLimit(
    "targets",
    recipe.sourceUniverses.length,
    "schema",
    "UNIVERSE_LIMIT",
  );
  enforceCountLimit(
    "bindings",
    recipe.attachments.length,
    "schema",
    "BINDING_LIMIT",
  );
  enforceCountLimit("targets", recipe.vectors.length, "schema", "VECTOR_LIMIT");
  enforceCountLimit(
    "dimensions",
    recipe.dimensions.length,
    "schema",
    "DIMENSION_LIMIT",
  );
  unique(
    recipe.dimensions.map((x) => x.id),
    "DUPLICATE_DIMENSION_ID",
  );
  unique(
    recipe.dimensions.map((x) => x.name),
    "DUPLICATE_DIMENSION_NAME",
  );
  unique(
    recipe.sourceUniverses.map((x) => x.id),
    "DUPLICATE_UNIVERSE_ID",
  );
  unique(
    recipe.attachments.map((x) => x.id),
    "DUPLICATE_ATTACHMENT_ID",
  );
  unique(
    recipe.vectors.map((x) => x.id),
    "DUPLICATE_VECTOR_ID",
  );
  unique(
    recipe.targets.map((x) => x.address),
    "DUPLICATE_TARGET",
  );
  const universes = new Map(recipe.sourceUniverses.map((x) => [x.id, x]));
  const dimensions = new Map(recipe.dimensions.map((x) => [x.id, x]));
  const attachments = new Map(recipe.attachments.map((x) => [x.id, x]));
  const vectors = new Map(recipe.vectors.map((x) => [x.id, x]));
  let addresses = 0;
  for (const universe of recipe.sourceUniverses) {
    unique(universe.addresses, "DUPLICATE_UNIVERSE_ADDRESS");
    addresses += universe.addresses.length;
    enforceCountLimit(
      "selectedCells",
      addresses,
      "schema",
      "SOURCE_ADDRESS_LIMIT",
    );
  }
  let declaredBindings = 0;
  for (const vector of recipe.vectors) {
    declaredBindings += vector.attachmentIds.length;
    enforceCountLimit("bindings", declaredBindings, "schema", "BINDING_LIMIT");
    const seen = new Set<string>();
    for (const [index, id] of vector.attachmentIds.entries()) {
      const attachment = attachments.get(id);
      if (
        !attachment ||
        !universes.has(attachment.universeId) ||
        !dimensions.has(attachment.dimensionId) ||
        attachment.dimensionId !== recipe.dimensions[index]?.id ||
        seen.has(attachment.dimensionId)
      )
        fail("schema", "VECTOR_DIMENSION_ORDER_MISMATCH");
      seen.add(attachment.dimensionId);
    }
    if (seen.size !== dimensions.size)
      fail("schema", "VECTOR_DIMENSION_MISSING");
  }
  const usedVectors = new Set<string>(),
    usedAttachments = new Set<string>(),
    usedUniverses = new Set<string>();
  let operations = 0,
    bindings = 0;
  for (const target of recipe.targets) {
    const vector = vectors.get(target.vectorId);
    if (!vector) fail("schema", "MISSING_VECTOR");
    usedVectors.add(vector.id);
    bindings += vector.attachmentIds.length;
    enforceCountLimit("bindings", bindings, "schema", "BINDING_LIMIT");
    for (const id of vector.attachmentIds) {
      const attachment = attachments.get(id)!;
      usedAttachments.add(id);
      usedUniverses.add(attachment.universeId);
      const universe = universes.get(attachment.universeId)!;
      if (!universe.addresses.includes(attachment.selectedAddress))
        fail("schema", "SOURCE_OUTSIDE_PARENT");
      operations += universe.addresses.length + 1;
      enforceCountLimit(
        "operations",
        operations,
        "schema",
        "RESOLUTION_OPERATION_LIMIT",
      );
    }
  }
  if (
    usedVectors.size !== vectors.size ||
    usedAttachments.size !== attachments.size ||
    usedUniverses.size !== universes.size
  )
    fail("schema", "UNUSED_RECIPE_DECLARATION");
}

function normalizeMap(
  map: TargetScopedSemanticMapV1,
): TargetScopedSemanticMapV1 {
  const result = structuredClone(map);
  const normalizeSubset = (entry: z.infer<typeof subsetSchema>) => ({
    ...entry,
    selectors: [...entry.selectors].sort((a, b) =>
      compareCodeUnits(canonicalJson(a), canonicalJson(b)),
    ),
  });
  result.targetSets = result.targetSets
    .map(normalizeSubset)
    .sort((a, b) => compareCodeUnits(a.id, b.id));
  result.sourceUniverses = result.sourceUniverses
    .map(normalizeSubset)
    .sort((a, b) => compareCodeUnits(a.id, b.id));
  result.attachments = [...result.attachments].sort((a, b) =>
    compareCodeUnits(a.id, b.id),
  );
  result.vectors = [...result.vectors]
    .map((entry) => ({ ...entry, attachmentIds: [...entry.attachmentIds] }))
    .sort((a, b) => compareCodeUnits(a.id, b.id));
  result.targets = [...result.targets].sort((a, b) =>
    compareAddress(a.address, b.address),
  );
  return result;
}

function validateMapResourceCounts(map: TargetScopedSemanticMapV1): void {
  enforceCountLimit("targets", map.targets.length, "schema", "TARGET_LIMIT");
  enforceCountLimit(
    "targets",
    map.targetSets.length,
    "schema",
    "TARGET_SET_LIMIT",
  );
  enforceCountLimit(
    "targets",
    map.sourceUniverses.length,
    "schema",
    "UNIVERSE_LIMIT",
  );
  enforceCountLimit(
    "bindings",
    map.attachments.length,
    "schema",
    "BINDING_LIMIT",
  );
  enforceCountLimit("targets", map.vectors.length, "schema", "VECTOR_LIMIT");
  enforceCountLimit(
    "dimensions",
    map.logicalTable.dimensions.length,
    "schema",
    "DIMENSION_LIMIT",
  );
  let selectors = 0;
  for (const entry of [...map.targetSets, ...map.sourceUniverses]) {
    enforceCountLimit(
      "selectorsPerRole",
      entry.selectors.length,
      "schema",
      "SELECTOR_PER_ROLE_LIMIT",
    );
    selectors += entry.selectors.length;
    enforceCountLimit("selectors", selectors, "schema", "SELECTOR_LIMIT");
  }
}

function validateUniqueMapIds(map: TargetScopedSemanticMapV1): void {
  unique(
    map.logicalTable.dimensions.map((entry) => entry.id),
    "DUPLICATE_DIMENSION_ID",
  );
  unique(
    map.logicalTable.dimensions.map((entry) => entry.name),
    "DUPLICATE_DIMENSION_NAME",
  );
  unique(
    map.targetSets.map((entry) => entry.id),
    "DUPLICATE_TARGET_SET_ID",
  );
  unique(
    map.sourceUniverses.map((entry) => entry.id),
    "DUPLICATE_UNIVERSE_ID",
  );
  unique(
    map.attachments.map((entry) => entry.id),
    "DUPLICATE_ATTACHMENT_ID",
  );
  unique(
    map.vectors.map((entry) => entry.id),
    "DUPLICATE_VECTOR_ID",
  );
}

function validateOutputKeys(map: TargetScopedSemanticMapV1): void {
  const keys = [
    map.logicalTable.valuesName,
    "_source",
    ...map.logicalTable.dimensions.flatMap((entry) => [
      entry.name,
      `${entry.name}_source`,
    ]),
  ];
  if (new Set(keys).size !== keys.length)
    fail("schema", "LOGICAL_OUTPUT_KEY_COLLISION");
}

function expandCatalog(
  catalog: AtomicRegionCatalog,
  sheet: ParsedSheet,
): Map<string, string[]> {
  enforceCountLimit(
    "catalogCandidates",
    catalog.candidates.length,
    "catalog",
    "CATALOG_CANDIDATE_LIMIT",
  );
  unique(
    catalog.candidates.map((candidate) => candidate.id),
    "DUPLICATE_CATALOG_REGION_ID",
  );
  const result = new Map<string, string[]>();
  let segments = 0;
  let cells = 0;
  for (const candidate of catalog.candidates) {
    const ranges =
      "segments" in candidate ? candidate.segments : [candidate.range];
    segments += ranges.length;
    enforceCountLimit(
      "catalogSegments",
      segments,
      "catalog",
      "CATALOG_SEGMENT_LIMIT",
    );
    const addresses: string[] = [];
    for (const range of ranges) {
      const count = rangeCardinality(range);
      enforceCountLimit(
        "catalogCells",
        cells + count,
        "catalog",
        "CATALOG_CELL_LIMIT",
      );
      const expanded = expandRange(range);
      cells += expanded.length;
      for (const address of expanded) assertInBounds(address, sheet);
      addresses.push(...expanded);
    }
    unique(addresses, "CATALOG_REGION_OVERLAP");
    result.set(candidate.id, sortAddresses(addresses));
  }
  return result;
}

function expandSubsets(
  subsets: Array<z.infer<typeof subsetSchema>>,
  catalog: Map<string, string[]>,
  sheet: ParsedSheet,
  role: string,
  budget: { cells: number },
): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const subset of subsets) {
    const parent = new Set(catalog.get(subset.regionId));
    if (!catalog.has(subset.regionId))
      fail("ownership", "UNKNOWN_PARENT_REGION");
    const addresses: string[] = [];
    for (const selector of subset.selectors) {
      const count =
        "address" in selector ? 1 : rangeCardinality(selector.range);
      enforceCountLimit(
        "selectedCells",
        addresses.length + count,
        "ownership",
        `${role.toUpperCase()}_CELL_LIMIT`,
      );
      enforceCountLimit(
        "selectedCells",
        budget.cells + count,
        "ownership",
        `${role.toUpperCase()}_CELL_LIMIT`,
      );
      budget.cells += count;
      const expanded =
        "address" in selector
          ? [selector.address]
          : expandRange(selector.range);
      for (const address of expanded) {
        assertInBounds(address, sheet);
        if (!parent.has(address)) fail("ownership", "SUBSET_OUTSIDE_PARENT");
      }
      addresses.push(...expanded);
    }
    unique(addresses, "DUPLICATE_SUBSET_ADDRESS");
    result.set(subset.id, sortAddresses(addresses));
  }
  return result;
}

function canonicalSheet(sheet: ParsedSheet): unknown {
  const optional = [
    "formula",
    "formatted",
    "comment",
    "hyperlink",
    "style",
    "merge",
  ] as const;
  return {
    name: sheet.name,
    usedRange: sheet.usedRange,
    rowCount: sheet.rowCount,
    columnCount: sheet.columnCount,
    nonEmptyCellCount: sheet.nonEmptyCellCount,
    cells: [...sheet.cells]
      .map((cell) => ({
        sheet: cell.sheet,
        address: cell.address,
        row: cell.row,
        col: cell.col,
        value: cell.value,
        data_type: cell.data_type,
        optional: Object.fromEntries(
          optional.map((key) => [key, optionalPresence(cell, key)]),
        ),
      }))
      .sort((a, b) => compareAddress(a.address, b.address)),
    merges: [...sheet.merges]
      .map((merge) => ({ ...merge }))
      .sort((a, b) => compareAddress(a.parent, b.parent)),
  };
}
function optionalPresence(value: object, key: string): unknown {
  if (!Object.hasOwn(value, key)) return { presence: "absent" };
  const child = (value as Record<string, unknown>)[key];
  if (child === undefined) return { presence: "undefined" };
  return { presence: "value", value: child };
}
function buildSheetProof(
  sheet: ParsedSheet,
): TargetScopedCompilationEnvelopeV02["sheetProof"] {
  const canonical = canonicalSheet(sheet) as any;
  return {
    sheet: sheet.name,
    usedRange: sheet.usedRange,
    rows: sheet.rowCount,
    columns: sheet.columnCount,
    cells: sheet.cells.length,
    merges: sheet.merges.length,
    digest: digestTargetScopedCanonical(canonical),
  };
}

function validateSheet(sheet: ParsedSheet): void {
  exactKeys(
    sheet,
    [
      "name",
      "usedRange",
      "rowCount",
      "columnCount",
      "nonEmptyCellCount",
      "cells",
      "merges",
    ],
    "SHEET_SCHEMA_INVALID",
  );
  if (
    typeof sheet.name !== "string" ||
    sheet.name.length < 1 ||
    sheet.name.length > 200 ||
    !Number.isInteger(sheet.rowCount) ||
    sheet.rowCount < 0 ||
    !Number.isInteger(sheet.columnCount) ||
    sheet.columnCount < 0 ||
    !Number.isInteger(sheet.nonEmptyCellCount) ||
    sheet.nonEmptyCellCount < 0
  )
    fail("sheet", "SHEET_SCHEMA_INVALID");
  if (
    sheet.usedRange !== null &&
    (typeof sheet.usedRange !== "string" ||
      formatRange(parseRange(sheet.usedRange)) !== sheet.usedRange)
  )
    fail("sheet", "SHEET_SCHEMA_INVALID");
  assertDomainArray(
    sheet.cells,
    MAX_TARGET_SCOPED_SHEET_CELLS,
    "SHEET_CELL_LIMIT",
  );
  assertDomainArray(
    sheet.merges,
    MAX_TARGET_SCOPED_SHEET_CELLS,
    "SHEET_MERGE_SCHEMA_INVALID",
  );
  enforceCountLimit(
    "sheetCells",
    sheet.cells.length,
    "sheet",
    "SHEET_CELL_LIMIT",
  );
  const seen = new Set<string>();
  const required = ["sheet", "address", "row", "col", "value", "data_type"];
  const optional = [
    "formula",
    "formatted",
    "comment",
    "hyperlink",
    "style",
    "merge",
  ];
  for (const cell of sheet.cells) {
    allowedKeys(cell, required, optional, "SHEET_CELL_SCHEMA_INVALID");
    if (
      cell.sheet !== sheet.name ||
      !Number.isInteger(cell.row) ||
      !Number.isInteger(cell.col) ||
      cell.address !== formatCell({ row: cell.row, col: cell.col }) ||
      seen.has(cell.address) ||
      !CELL_DATA_TYPES.has(cell.data_type)
    )
      fail("sheet", "SHEET_CELL_IDENTITY_MISMATCH");
    const typeOk =
      cell.data_type === "blank"
        ? cell.value === null
        : cell.data_type === "numeric"
          ? typeof cell.value === "number" && Number.isFinite(cell.value)
          : cell.data_type === "boolean"
            ? typeof cell.value === "boolean"
            : typeof cell.value === "string";
    if (!typeOk) fail("sheet", "SHEET_CELL_TYPE_MISMATCH");
    for (const key of ["formula", "formatted", "comment", "hyperlink"] as const)
      if (
        Object.hasOwn(cell, key) &&
        cell[key] !== undefined &&
        cell[key] !== null &&
        typeof cell[key] !== "string"
      )
        fail("sheet", "SHEET_CELL_SCHEMA_INVALID");
    if (cell.style !== undefined) validateStyle(cell.style);
    if (cell.merge !== undefined && cell.merge !== null) {
      exactKeys(
        cell.merge,
        ["parent", "range", "role"],
        "SHEET_MERGE_SCHEMA_INVALID",
      );
      if (
        !addressSchema.safeParse(cell.merge.parent).success ||
        !rangeSchema.safeParse(cell.merge.range).success ||
        !["parent", "child"].includes(cell.merge.role)
      )
        fail("sheet", "SHEET_MERGE_SCHEMA_INVALID");
    }
    assertInBounds(cell.address, sheet);
    seen.add(cell.address);
  }
  for (const merge of sheet.merges) {
    exactKeys(merge, ["parent", "range"], "SHEET_MERGE_SCHEMA_INVALID");
    if (
      !addressSchema.safeParse(merge.parent).success ||
      !rangeSchema.safeParse(merge.range).success
    )
      fail("sheet", "SHEET_MERGE_SCHEMA_INVALID");
  }
  if (
    sheet.cells.filter((cell) => cell.value !== null).length !==
    sheet.nonEmptyCellCount
  )
    fail("sheet", "SHEET_COUNT_MISMATCH");
  assertStrictInertJson(
    canonicalSheet(sheet),
    MAX_TARGET_SCOPED_CATALOG_NODES,
    MAX_TARGET_SCOPED_ENVELOPE_BYTES,
    "SHEET_RESOURCE_LIMIT",
    "sheet",
  );
}
function validateStyle(style: object): void {
  allowedKeys(
    style,
    [],
    [
      "bold",
      "italic",
      "underline",
      "fontSize",
      "fontColor",
      "fillColor",
      "fontIndent",
      "horizontalAlign",
      "verticalAlign",
      "border",
    ],
    "SHEET_STYLE_SCHEMA_INVALID",
  );
  const record = style as Record<string, unknown>;
  for (const key of ["bold", "italic", "underline"])
    if (
      Object.hasOwn(record, key) &&
      record[key] !== undefined &&
      typeof record[key] !== "boolean"
    )
      fail("sheet", "SHEET_STYLE_SCHEMA_INVALID");
  for (const key of ["fontSize", "fontIndent"])
    if (
      Object.hasOwn(record, key) &&
      record[key] !== undefined &&
      !(typeof record[key] === "number" && Number.isFinite(record[key]))
    )
      fail("sheet", "SHEET_STYLE_SCHEMA_INVALID");
  for (const key of [
    "fontColor",
    "fillColor",
    "horizontalAlign",
    "verticalAlign",
  ])
    if (
      Object.hasOwn(record, key) &&
      record[key] !== undefined &&
      typeof record[key] !== "string"
    )
      fail("sheet", "SHEET_STYLE_SCHEMA_INVALID");
  if (Object.hasOwn(record, "border") && record.border !== undefined) {
    const border = record.border;
    allowedKeys(
      border,
      [],
      ["top", "right", "bottom", "left"],
      "SHEET_STYLE_SCHEMA_INVALID",
    );
    for (const value of Object.values(border as object))
      if (typeof value !== "boolean")
        fail("sheet", "SHEET_STYLE_SCHEMA_INVALID");
  }
}
function exactKeys(value: object, keys: string[], code: string): void {
  validateDomainObject(value, keys, keys, code);
}
function allowedKeys(
  value: unknown,
  required: string[],
  optional: string[],
  code: string,
): void {
  validateDomainObject(value, [...required, ...optional], required, code);
}
function validateDomainObject(
  value: unknown,
  allowed: string[],
  required: string[],
  code: string,
): void {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    utilTypes.isProxy(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  )
    fail("sheet", code);
  const own = Reflect.ownKeys(value);
  if (
    own.some((key) => typeof key !== "string" || !allowed.includes(key)) ||
    required.some((key) => !Object.hasOwn(value, key))
  )
    fail("sheet", code);
  for (const key of own) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)!;
    if (
      !("value" in descriptor) ||
      !descriptor.enumerable ||
      !descriptor.configurable ||
      !descriptor.writable
    )
      fail("sheet", code);
    if (descriptor.value === undefined && !allowed.includes(key as string))
      fail("sheet", code);
  }
}
function assertDomainArray(
  value: unknown[],
  maxLength: number,
  code: string,
): void {
  if (utilTypes.isProxy(value) || value.length > maxLength) fail("sheet", code);
  try {
    assertInertArray(value, code, maxLength);
  } catch {
    fail("sheet", code);
  }
}

export function parseTargetScopedExecutionV02(
  value: unknown,
  recipe: TargetScopedRecipeV02,
): TargetScopedExecutionV02 {
  validateStandaloneRecipe(recipe);
  assertStrictInertJson(
    value,
    MAX_TARGET_SCOPED_EXECUTION_NODES,
    MAX_TARGET_SCOPED_EXECUTION_BYTES,
    "SUPPLIED_EXECUTION_RESOURCE_LIMIT",
    "runtime",
  );
  validateExecutionShape(value, recipe);
  return structuredClone(value as TargetScopedExecutionV02);
}

const CELL_DATA_TYPES = new Set([
  "blank",
  "string",
  "numeric",
  "boolean",
  "date",
  "error",
]);
function validateExecutionShape(
  value: unknown,
  recipe: TargetScopedRecipeV02,
): void {
  const root = strictObject(value, [
    "version",
    "recipeVersion",
    "source",
    "table",
    "warnings",
    "providerCalls",
    "acceptanceAuthority",
    "trainingEligibility",
  ]);
  if (
    root.version !== TARGET_SCOPED_EXECUTION_V02 ||
    root.recipeVersion !== TARGET_SCOPED_RECIPE_V02 ||
    root.providerCalls !== 0 ||
    root.acceptanceAuthority !== false ||
    root.trainingEligibility !== false
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  const source = strictObject(root.source, [
    "version",
    "workbookDigest",
    "physicalSheet",
  ]);
  if (
    source.version !== TARGET_SCOPED_SOURCE_CONTEXT_V1 ||
    typeof source.workbookDigest !== "string" ||
    !/^sha256:[a-f0-9]{64}$/.test(source.workbookDigest) ||
    source.physicalSheet !== recipe.sheet
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  strictArray(root.warnings, 0);
  const table = strictObject(root.table, [
    "id",
    "name",
    "sheet",
    "rows",
    "trace",
  ]);
  if (
    table.id !== recipe.table.id ||
    table.name !== recipe.table.name ||
    table.sheet !== recipe.sheet
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  const rows = strictArray(table.rows, recipe.targets.length);
  const traces = strictArray(table.trace, recipe.targets.length);
  const universeById = new Map(recipe.sourceUniverses.map((x) => [x.id, x]));
  const attachmentById = new Map(recipe.attachments.map((x) => [x.id, x]));
  const vectorById = new Map(recipe.vectors.map((x) => [x.id, x]));
  const rowKeys = [
    recipe.table.valuesName,
    "_source",
    ...recipe.dimensions.flatMap((x) => [x.name, `${x.name}_source`]),
  ];
  for (let index = 0; index < recipe.targets.length; index++) {
    const target = recipe.targets[index];
    const targetPosition = parseCell(target.address);
    const row = strictObject(rows[index], rowKeys);
    assertExecutionScalar(row[recipe.table.valuesName]);
    const targetDataType = strictPosition(
      row._source,
      recipe.sheet,
      target.address,
      targetPosition.row,
      targetPosition.col,
    );
    assertScalarDataType(row[recipe.table.valuesName], targetDataType);
    const trace = strictObject(traces[index], [
      "target",
      "value",
      "attachments",
    ]);
    const traceTargetDataType = strictPosition(
      trace.target,
      recipe.sheet,
      target.address,
      targetPosition.row,
      targetPosition.col,
    );
    if (traceTargetDataType !== targetDataType)
      fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
    assertExecutionScalar(trace.value);
    if (!Object.is(trace.value, row[recipe.table.valuesName]))
      fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
    const vector = vectorById.get(target.vectorId)!;
    const traceAttachments = strictArray(
      trace.attachments,
      recipe.dimensions.length,
    );
    for (
      let dimensionIndex = 0;
      dimensionIndex < recipe.dimensions.length;
      dimensionIndex++
    ) {
      const dimension = recipe.dimensions[dimensionIndex];
      const binding = attachmentById.get(vector.attachmentIds[dimensionIndex])!;
      assertExecutionScalar(row[dimension.name]);
      if (row[`${dimension.name}_source`] !== binding.selectedAddress)
        fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
      const attachment = strictObject(traceAttachments[dimensionIndex], [
        "dimensionId",
        "dimensionName",
        "direction",
        "universeId",
        "candidates",
        "selected",
        "source",
        "value",
        "missing",
        "ambiguous",
      ]);
      if (
        attachment.dimensionId !== dimension.id ||
        attachment.dimensionName !== dimension.name ||
        attachment.direction !== binding.direction ||
        attachment.universeId !== binding.universeId ||
        attachment.selected !== binding.selectedAddress ||
        attachment.missing !== false ||
        attachment.ambiguous !== false
      )
        fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
      assertExecutionScalar(attachment.value);
      if (!Object.is(attachment.value, row[dimension.name]))
        fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
      const candidates = strictArray(attachment.candidates, 1);
      if (
        candidates[0] !== binding.selectedAddress ||
        !universeById
          .get(binding.universeId)!
          .addresses.includes(candidates[0] as string)
      )
        fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
      const sourcePosition = parseCell(binding.selectedAddress);
      const sourceDataType = strictPosition(
        attachment.source,
        recipe.sheet,
        binding.selectedAddress,
        sourcePosition.row,
        sourcePosition.col,
      );
      assertScalarDataType(attachment.value, sourceDataType);
    }
  }
}
function strictPosition(
  value: unknown,
  sheet: string,
  address: string,
  row: number,
  col: number,
): TidyCell["data_type"] {
  const source = strictObject(value, [
    "sheet",
    "address",
    "row",
    "col",
    "data_type",
  ]);
  if (
    source.sheet !== sheet ||
    source.address !== address ||
    source.row !== row ||
    source.col !== col ||
    !CELL_DATA_TYPES.has(source.data_type as string)
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  return source.data_type as TidyCell["data_type"];
}
function assertScalarDataType(
  value: unknown,
  dataType: TidyCell["data_type"],
): void {
  const valid =
    typeof value === "number"
      ? dataType === "numeric"
      : typeof value === "string" &&
        ["string", "date", "error"].includes(dataType);
  if (!valid) fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
}
function assertExecutionScalar(
  value: unknown,
): asserts value is string | number {
  if (
    typeof value !== "string" &&
    !(typeof value === "number" && Number.isFinite(value))
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
}
function strictArray(
  value: unknown,
  expectedLength?: number,
  maxLength = expectedLength ?? MAX_TARGET_SCOPED_EXECUTION_NODES,
): unknown[] {
  if (!Array.isArray(value) || utilTypes.isProxy(value))
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  if (
    value.length > maxLength ||
    (expectedLength !== undefined && value.length !== expectedLength)
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  assertInertArray(value, "SUPPLIED_EXECUTION_SCHEMA_MISMATCH", maxLength);
  return value;
}
function strictObject(value: unknown, keys: string[]): Record<string, unknown> {
  if (
    !value ||
    typeof value !== "object" ||
    utilTypes.isProxy(value) ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  const own = Reflect.ownKeys(value);
  if (
    own.length !== keys.length ||
    own.some((key) => typeof key !== "string" || !keys.includes(key)) ||
    keys.some((key) => !Object.hasOwn(value, key))
  )
    fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  for (const key of own) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)!;
    if (
      !("value" in descriptor) ||
      !descriptor.enumerable ||
      !descriptor.configurable ||
      !descriptor.writable
    )
      fail("runtime", "SUPPLIED_EXECUTION_SCHEMA_MISMATCH");
  }
  return value as Record<string, unknown>;
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalEncode(value, new Set<object>()));
}
function canonicalEncode(value: unknown, ancestors: Set<object>): unknown {
  if (value === null) return ["null"];
  if (typeof value === "string") return ["string", value];
  if (typeof value === "boolean") return ["boolean", value];
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("NONFINITE_CANONICAL_NUMBER");
    return ["number", Object.is(value, -0) ? "-0" : String(value)];
  }
  if (!value || typeof value !== "object")
    throw new Error("NON_JSON_CANONICAL_VALUE");
  if (utilTypes.isProxy(value)) throw new Error("PROXY_CANONICAL_VALUE");
  if (ancestors.has(value)) throw new Error("CYCLIC_CANONICAL_VALUE");
  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      assertInertArray(
        value,
        "NON_INERT_CANONICAL_ARRAY",
        MAX_TARGET_SCOPED_EXECUTION_NODES,
      );
      return ["array", value.map((child) => canonicalEncode(child, ancestors))];
    }
    assertInertObject(value, "NON_INERT_CANONICAL_OBJECT");
    return [
      "object",
      Object.keys(value)
        .sort(compareCodeUnits)
        .map((key) => [
          key,
          canonicalEncode((value as Record<string, unknown>)[key], ancestors),
        ]),
    ];
  } finally {
    ancestors.delete(value);
  }
}
function compareCodeUnits(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

export function assertTargetScopedRawJsonBudget(
  raw: string,
  maxNodes: number,
  code = "RAW_JSON_RESOURCE_LIMIT",
): void {
  assertRawJsonBudget(raw, maxNodes, code);
}
function assertRawJsonBudget(
  raw: string,
  maxNodes: number,
  code: string,
  stage = "schema",
): void {
  let nodes = 0,
    inString = false,
    escaped = false,
    token = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') {
        inString = false;
        nodes++;
      }
    } else if (ch === '"') {
      inString = true;
      token = false;
    } else if (ch === "{" || ch === "[") {
      nodes++;
      token = false;
    } else if (/[-0-9tfn]/.test(ch) && !token) {
      nodes++;
      token = true;
    } else if (/[,\]}:\s]/.test(ch)) token = false;
    if (nodes > maxNodes) fail(stage, code);
  }
}
export function assertTargetScopedValueBudget(
  value: unknown,
  maxNodes: number,
  maxBytes: number,
  code = "VALUE_RESOURCE_LIMIT",
): void {
  assertStrictInertJson(value, maxNodes, maxBytes, code);
}
export function measureTargetScopedValue(
  value: unknown,
  maxNodes: number,
  maxBytes: number,
): { nodes: number; bytes: number } {
  return inspectStrictInertJson(
    value,
    maxNodes,
    maxBytes,
    "VALUE_RESOURCE_LIMIT",
  );
}
function assertStrictInertJson(
  value: unknown,
  maxNodes: number,
  maxBytes: number,
  code: string,
  stage = "schema",
): void {
  try {
    inspectStrictInertJson(value, maxNodes, maxBytes, code);
  } catch {
    fail(stage, code);
  }
}
function inspectStrictInertJson(
  value: unknown,
  maxNodes: number,
  maxBytes: number,
  code: string,
): { nodes: number; bytes: number } {
  const stack: unknown[] = [value];
  let nodes = 0,
    bytes = 0;
  const seen = new Set<object>();
  const addBytes = (count: number) => {
    bytes += count;
    if (bytes > maxBytes) throw new Error(code);
  };
  while (stack.length) {
    const current = stack.pop();
    nodes++;
    if (nodes > maxNodes) throw new Error(code);
    if (current === null) addBytes(4);
    else if (typeof current === "boolean") addBytes(current ? 4 : 5);
    else if (typeof current === "number") {
      if (!Number.isFinite(current)) throw new Error(code);
      addBytes(
        Buffer.byteLength(Object.is(current, -0) ? "0" : String(current)),
      );
    } else if (typeof current === "string")
      addBytes(jsonStringByteLength(current));
    else if (current && typeof current === "object") {
      if (utilTypes.isProxy(current) || seen.has(current))
        throw new Error(code);
      seen.add(current);
      if (Array.isArray(current)) {
        const remaining = maxNodes - nodes - stack.length;
        if (current.length > remaining) throw new Error(code);
        assertInertArray(current, code, remaining);
        addBytes(2 + Math.max(0, current.length - 1));
        for (let index = current.length - 1; index >= 0; index--)
          stack.push(
            Object.getOwnPropertyDescriptor(current, String(index))!.value,
          );
      } else {
        assertInertObject(current, code);
        const keys = Reflect.ownKeys(current) as string[];
        if (keys.length > maxNodes - nodes - stack.length)
          throw new Error(code);
        addBytes(2 + Math.max(0, keys.length - 1));
        for (const key of keys) {
          addBytes(jsonStringByteLength(key) + 1);
          stack.push(Object.getOwnPropertyDescriptor(current, key)!.value);
        }
      }
    } else throw new Error(code);
  }
  return { nodes, bytes };
}
function jsonStringByteLength(value: string): number {
  let bytes = 2;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (
      code === 0x22 ||
      code === 0x5c ||
      code === 0x08 ||
      code === 0x09 ||
      code === 0x0a ||
      code === 0x0c ||
      code === 0x0d
    )
      bytes += 2;
    else if (code < 0x20) bytes += 6;
    else if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        bytes += 4;
        index++;
      } else bytes += 6;
    } else if (code >= 0xdc00 && code <= 0xdfff) bytes += 6;
    else if (code < 0x80) bytes += 1;
    else if (code < 0x800) bytes += 2;
    else bytes += 3;
  }
  return bytes;
}
function assertInertArray(
  value: unknown[],
  code: string,
  maxLength: number,
): void {
  if (
    utilTypes.isProxy(value) ||
    Object.getPrototypeOf(value) !== Array.prototype ||
    value.length > maxLength
  )
    throw new Error(code);
  const keys = Reflect.ownKeys(value);
  if (keys.length !== value.length + 1) throw new Error(code);
  let indexed = 0;
  for (const key of keys) {
    if (typeof key !== "string") throw new Error(code);
    const descriptor = Object.getOwnPropertyDescriptor(value, key)!;
    if (!("value" in descriptor)) throw new Error(code);
    if (key === "length") {
      if (
        descriptor.enumerable ||
        descriptor.configurable ||
        !descriptor.writable
      )
        throw new Error(code);
      continue;
    }
    if (!/^(0|[1-9][0-9]*)$/.test(key)) throw new Error(code);
    const index = Number(key);
    if (
      !Number.isSafeInteger(index) ||
      index >= value.length ||
      String(index) !== key ||
      !descriptor.enumerable ||
      !descriptor.configurable ||
      !descriptor.writable
    )
      throw new Error(code);
    indexed++;
  }
  if (indexed !== value.length) throw new Error(code);
  for (let index = 0; index < value.length; index++)
    if (!Object.hasOwn(value, index)) throw new Error(code);
}
function assertInertObject(value: object, code: string): void {
  if (
    utilTypes.isProxy(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  )
    throw new Error(code);
  for (const key of Reflect.ownKeys(value)) {
    if (typeof key !== "string") throw new Error(code);
    const d = Object.getOwnPropertyDescriptor(value, key)!;
    if (
      !("value" in d) ||
      d.value === undefined ||
      !d.enumerable ||
      !d.configurable ||
      !d.writable
    )
      throw new Error(code);
  }
}

function rangeCardinality(value: string): number {
  const range = parseRange(value);
  const count =
    (range.end.row - range.start.row + 1) *
    (range.end.col - range.start.col + 1);
  if (!Number.isSafeInteger(count) || count < 1)
    throw new Error("INVALID_RANGE");
  return count;
}
function compareAddress(left: string, right: string): number {
  const a = parseCell(left),
    b = parseCell(right);
  return a.row - b.row || a.col - b.col;
}
function sortAddresses(values: string[]): string[] {
  return [...values].sort(compareAddress);
}
function unique(values: string[], code: string): void {
  if (new Set(values).size !== values.length) fail("schema", code);
}
function assertInBounds(address: string, sheet: ParsedSheet): void {
  const cell = parseCell(address);
  if (cell.row > sheet.rowCount || cell.col > sheet.columnCount)
    fail("ownership", "ADDRESS_OUT_OF_BOUNDS");
}
function isDimensionScalar(value: unknown): value is string | number {
  return (
    (typeof value === "string" && value.trim().length > 0) ||
    (typeof value === "number" && Number.isFinite(value))
  );
}
function isValueScalar(value: unknown): value is string | number {
  return (
    typeof value === "string" ||
    (typeof value === "number" && Number.isFinite(value))
  );
}
function enforceCountLimit(
  kind: keyof typeof TARGET_SCOPED_LIMITS,
  value: number,
  stage: string,
  code: string,
): void {
  try {
    assertTargetScopedCountLimit(kind, value);
  } catch {
    fail(stage, code);
  }
}
function fail(stage: string, code: string, cause?: unknown): never {
  throw new TargetScopedError(
    stage,
    code,
    cause instanceof Error ? `${code}: ${cause.message}` : code,
  );
}
