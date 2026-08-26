/* Federal Defendants-only grouped-panel semantic map and replay runtime. */
import { createHash } from "node:crypto";
import { TextDecoder, TextEncoder, types as utilTypes } from "node:util";
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
import type { HeaderDirection } from "../recipe/types.js";
import type { ParsedSheet, TidyCell } from "../workbook/types.js";

export const FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1 =
  "federal-defendants-grouped-semantic-map-v1" as const;
export const FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1 =
  "FederalDefendantsGroupedRecipeV1" as const;
export const FEDERAL_DEFENDANTS_GROUPED_COMPILER_V1 =
  "federal-defendants-grouped-recipe-v1-compiler-v1" as const;
export const FEDERAL_DEFENDANTS_GROUPED_ENVELOPE_V1 =
  "federal-defendants-grouped-compilation-envelope/v1" as const;
export const FEDERAL_DEFENDANTS_GROUPED_EXECUTION_V1 =
  "federal-defendants-grouped-logical-execution/v1" as const;
export const FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1 =
  "federal-defendants-source-context/v1" as const;
export const FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1 =
  "federal-defendants-geometry-authority/v1" as const;
export const FEDERAL_DEFENDANTS_REPLAY_MODEL_V1 =
  "provider-free/federal-defendants/grouped-recipe-v1" as const;
export const FEDERAL_DEFENDANTS_BOUNDED_NORMALIZATION_V1 =
  "digest-pinned-bounded-federal-defendants-v1" as const;

export const MAX_FEDERAL_GROUPED_JSON_BYTES = 16 * 1024 * 1024;
export const MAX_FEDERAL_GROUPED_JSON_NODES = 500_000;
export const MAX_FEDERAL_GROUPED_JSON_DEPTH = 128;
export const MAX_FEDERAL_GROUPED_TARGETS = 25_000;
export const MAX_FEDERAL_GROUPED_DIMENSIONS = 64;
export const MAX_FEDERAL_GROUPED_SELECTORS = 20_000;
export const MAX_FEDERAL_GROUPED_SELECTED_CELLS = 100_000;
export const MAX_FEDERAL_GROUPED_BINDINGS = 500_000;
export const MAX_FEDERAL_GROUPED_OPERATIONS = 2_000_000;

const digestSchema = z.string().regex(/^sha256:[a-f0-9]{64}$/);
const idSchema = z.string().regex(/^[a-z][a-z0-9-]{0,79}$/);
const outputNameSchema = z
  .string()
  .min(1)
  .max(120)
  .refine((value) => value === value.trim(), "Output names must be trimmed")
  .regex(/^[A-Za-z0-9][A-Za-z0-9 _-]{0,119}$/);
const semanticValueSchema = z
  .string()
  .min(1)
  .max(240)
  .regex(/^[a-z0-9][a-z0-9._:|+-]{0,239}$/);
const MAX_FEDERAL_PANEL_KEY_SOURCE_BYTES = 1_024;
const MAX_FEDERAL_PANEL_KEY_ENCODED_LENGTH =
  MAX_FEDERAL_PANEL_KEY_SOURCE_BYTES * 3;
const panelKeyEncodedValueSchema = z
  .string()
  .min(1)
  .max(MAX_FEDERAL_PANEL_KEY_ENCODED_LENGTH)
  .regex(/^(?:[A-Za-z0-9._~-]|%[0-9A-F]{2})+$/);
const panelKeySchema = z
  .string()
  .min(3)
  .max(80 + 1 + MAX_FEDERAL_PANEL_KEY_ENCODED_LENGTH)
  .refine((value) => {
    const separator = value.indexOf(":");
    if (separator <= 0) return false;
    return (
      idSchema.safeParse(value.slice(0, separator)).success &&
      panelKeyEncodedValueSchema.safeParse(value.slice(separator + 1)).success
    );
  }, "Expected a dimension ID and canonical percent-encoded source value");
const addressSchema = z.string().refine((value) => {
  try {
    return formatCell(parseCell(value)) === value;
  } catch {
    return false;
  }
}, "Expected a canonical R1C1 address");
const rangeSchema = z.string().refine((value) => {
  try {
    return formatRange(parseRange(value)) === value;
  } catch {
    return false;
  }
}, "Expected a canonical R1C1 range");
const selectorSchema = z.union([
  z.object({ address: addressSchema }).strict(),
  z.object({ range: rangeSchema }).strict(),
]);
const directionSchema = z.enum(["N", "W", "NNW", "WNW"]);

export const FEDERAL_PROVENANCE_FIELDS = [
  "populationBasis",
  "transferPolicy",
  "entityType",
  "denominator",
  "rowClassification",
  "principalOffenceClassification",
  "classificationTreatment",
  "principalSelectionVersion",
  "sentenceClassificationTreatment",
  "revisionTreatment",
  "measure",
  "statistic",
  "unit",
  "hierarchy",
  "totalStatus",
  "footnoteReferences",
  "perturbation",
] as const;
export type FederalProvenanceField = (typeof FEDERAL_PROVENANCE_FIELDS)[number];

const provenanceSchema = z
  .object({
    populationBasis: semanticValueSchema,
    transferPolicy: semanticValueSchema,
    entityType: semanticValueSchema,
    denominator: semanticValueSchema,
    rowClassification: semanticValueSchema,
    principalOffenceClassification: semanticValueSchema,
    classificationTreatment: semanticValueSchema,
    principalSelectionVersion: semanticValueSchema,
    sentenceClassificationTreatment: semanticValueSchema,
    revisionTreatment: semanticValueSchema,
    measure: semanticValueSchema,
    statistic: semanticValueSchema,
    unit: semanticValueSchema,
    hierarchy: semanticValueSchema,
    totalStatus: semanticValueSchema,
    footnoteRefs: z
      .array(
        z
          .string()
          .trim()
          .min(1)
          .max(40)
          .regex(
            /^[^|]+$/,
            "Footnote references cannot contain the | delimiter",
          ),
      )
      .max(32),
    perturbation: z.literal(true),
  })
  .strict();
export type FederalTargetProvenance = z.infer<typeof provenanceSchema>;

const sourceContextSchema = z
  .object({
    version: z.literal(FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1),
    sourceWorkbookDigest: digestSchema,
    executionWorkbookDigest: digestSchema,
    physicalSheet: z.string().min(1).max(200),
    authoritativeRange: rangeSchema,
  })
  .strict();
export type FederalDefendantsSourceContext = z.infer<
  typeof sourceContextSchema
>;

const cellDimensionSchema = z
  .object({
    id: idSchema,
    name: outputNameSchema,
    source: z.object({ kind: z.literal("cell") }).strict(),
  })
  .strict();
const provenanceDimensionSchema = z
  .object({
    id: idSchema,
    name: outputNameSchema,
    source: z
      .object({
        kind: z.literal("provenance"),
        field: z.enum(FEDERAL_PROVENANCE_FIELDS),
      })
      .strict(),
  })
  .strict();
const logicalDimensionSchema = z.union([
  cellDimensionSchema,
  provenanceDimensionSchema,
]);

const geometryAuthoritySchema = z
  .object({
    version: z.literal(FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1),
    source: sourceContextSchema,
    panels: z
      .array(
        z
          .object({
            panelId: idSchema,
            targetSelectors: z
              .array(selectorSchema)
              .min(1)
              .max(MAX_FEDERAL_GROUPED_SELECTORS),
          })
          .strict(),
      )
      .min(1)
      .max(1_000),
    bands: z
      .array(
        z
          .object({
            id: idSchema,
            panelId: idSchema,
            dimensionId: idSchema,
            direction: directionSchema,
            range: rangeSchema,
          })
          .strict(),
      )
      .min(1)
      .max(20_000),
  })
  .strict();
export type FederalDefendantsGeometryAuthorityV1 = z.infer<
  typeof geometryAuthoritySchema
>;

const subsetSchema = z
  .object({
    id: idSchema,
    panelId: idSchema,
    dimensionId: idSchema,
    direction: directionSchema,
    authorityBandId: idSchema,
    selectors: z
      .array(selectorSchema)
      .min(1)
      .max(MAX_FEDERAL_GROUPED_SELECTORS),
  })
  .strict();
const panelSchema = z
  .object({
    id: idSchema,
    order: z.number().int().min(1).max(1_000),
    key: panelKeySchema,
    keySource: z
      .object({
        dimensionId: idSchema,
        selectedAddress: addressSchema,
      })
      .strict(),
    name: z.string().trim().min(1).max(200),
    selectors: z
      .array(selectorSchema)
      .min(1)
      .max(MAX_FEDERAL_GROUPED_SELECTORS),
  })
  .strict();
const bindingSchema = z
  .object({
    id: idSchema,
    dimensionId: idSchema,
    direction: directionSchema,
    selectedAddress: addressSchema,
    universeId: idSchema,
  })
  .strict();
const vectorSchema = z
  .object({ id: idSchema, bindingIds: z.array(idSchema).min(1).max(64) })
  .strict();
const targetValueStatusAuthoritySchema = z
  .object({
    kind: z.literal("exact-comment"),
    rawComment: z.literal("not published\n"),
    status: z.literal("not-published"),
  })
  .strict();
const targetSchema = z
  .object({
    address: addressSchema,
    panelId: idSchema,
    vectorId: idSchema,
    provenanceProfileId: idSchema,
    valueStatusAuthority: targetValueStatusAuthoritySchema.optional(),
  })
  .strict();

export const federalDefendantsGroupedSemanticMapV1Schema = z
  .object({
    version: z.literal(FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1),
    source: sourceContextSchema,
    geometryAuthority: geometryAuthoritySchema,
    geometryAuthorityDigest: digestSchema,
    logicalTable: z
      .object({
        id: idSchema,
        name: z.string().trim().min(1).max(200),
        valuesName: outputNameSchema,
        dimensions: z
          .array(logicalDimensionSchema)
          .min(1)
          .max(MAX_FEDERAL_GROUPED_DIMENSIONS),
      })
      .strict(),
    panels: z.array(panelSchema).min(1).max(1_000),
    sourceUniverses: z.array(subsetSchema).min(1).max(20_000),
    bindings: z.array(bindingSchema).min(1).max(MAX_FEDERAL_GROUPED_BINDINGS),
    vectors: z.array(vectorSchema).min(1).max(20_000),
    provenanceProfiles: z
      .array(z.object({ id: idSchema, values: provenanceSchema }).strict())
      .min(1)
      .max(20_000),
    targets: z.array(targetSchema).min(1).max(MAX_FEDERAL_GROUPED_TARGETS),
  })
  .strict();
export type FederalDefendantsGroupedSemanticMapV1 = z.infer<
  typeof federalDefendantsGroupedSemanticMapV1Schema
>;

export type FederalDefendantsGroupedRecipeV1 = {
  version: typeof FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1;
  source: FederalDefendantsSourceContext;
  geometryAuthorityDigest: string;
  table: { id: string; name: string; valuesName: string };
  dimensions: FederalDefendantsGroupedSemanticMapV1["logicalTable"]["dimensions"];
  panels: Array<{
    id: string;
    order: number;
    key: string;
    keySource: {
      dimensionId: string;
      selectedAddress: string;
      rawValue: string;
      encodedValue: string;
      source: CellProof;
    };
    name: string;
    targetAddresses: string[];
  }>;
  sourceUniverses: Array<{
    id: string;
    panelId: string;
    dimensionId: string;
    direction: HeaderDirection;
    authorityBandId: string;
    bandRange: string;
    addresses: string[];
  }>;
  bindings: FederalDefendantsGroupedSemanticMapV1["bindings"];
  vectors: FederalDefendantsGroupedSemanticMapV1["vectors"];
  provenanceProfiles: FederalDefendantsGroupedSemanticMapV1["provenanceProfiles"];
  targets: FederalDefendantsGroupedSemanticMapV1["targets"];
};

const recipeSchema: z.ZodType<FederalDefendantsGroupedRecipeV1> = z
  .object({
    version: z.literal(FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1),
    source: sourceContextSchema,
    geometryAuthorityDigest: digestSchema,
    table: z
      .object({
        id: idSchema,
        name: z.string().min(1).max(200),
        valuesName: outputNameSchema,
      })
      .strict(),
    dimensions: z
      .array(logicalDimensionSchema)
      .min(1)
      .max(MAX_FEDERAL_GROUPED_DIMENSIONS),
    panels: z
      .array(
        z
          .object({
            id: idSchema,
            order: z.number().int().positive(),
            key: panelKeySchema,
            keySource: z
              .object({
                dimensionId: idSchema,
                selectedAddress: addressSchema,
                rawValue: z.string().min(1),
                encodedValue: panelKeyEncodedValueSchema,
                source: z
                  .object({
                    sheet: z.string().min(1),
                    address: addressSchema,
                    row: z.number().int().positive(),
                    col: z.number().int().positive(),
                    data_type: z.enum([
                      "blank",
                      "string",
                      "numeric",
                      "boolean",
                      "date",
                      "error",
                    ]),
                    formula: z.string().nullable(),
                    formatted: z.string().nullable(),
                    comment: z.string().nullable(),
                  })
                  .strict(),
              })
              .strict(),
            name: z.string().min(1).max(200),
            targetAddresses: z
              .array(addressSchema)
              .min(1)
              .max(MAX_FEDERAL_GROUPED_TARGETS),
          })
          .strict(),
      )
      .min(1),
    sourceUniverses: z
      .array(
        z
          .object({
            id: idSchema,
            panelId: idSchema,
            dimensionId: idSchema,
            direction: directionSchema,
            authorityBandId: idSchema,
            bandRange: rangeSchema,
            addresses: z.array(addressSchema).min(1),
          })
          .strict(),
      )
      .min(1),
    bindings: z.array(bindingSchema).min(1),
    vectors: z.array(vectorSchema).min(1),
    provenanceProfiles: z
      .array(z.object({ id: idSchema, values: provenanceSchema }).strict())
      .min(1),
    targets: z.array(targetSchema).min(1),
  })
  .strict();

export type FederalPanelKeyAttachmentProof = {
  dimensionId: string;
  key: string;
  selectedAddress: string;
  rawValue: string;
  encodedValue: string;
  source: CellProof;
};

export type FederalDefendantsGroupedAttachmentProof = {
  targetAddress: string;
  vectorId: string;
  panelKeyAttachment: FederalPanelKeyAttachmentProof;
  dimensions: Array<{
    dimensionId: string;
    direction: HeaderDirection;
    universeId: string;
    candidates: string[];
    selectedAddress: string;
    rawValue: string | number;
    formula: string | null;
  }>;
};

export type FederalGroupedCompileLimits = {
  maxSelectorCells: number;
  maxOutputRows: number;
  maxOperations: number;
};

export type FederalDefendantsGroupedEnvelopeV1 = {
  version: typeof FEDERAL_DEFENDANTS_GROUPED_ENVELOPE_V1;
  compilerVersion: typeof FEDERAL_DEFENDANTS_GROUPED_COMPILER_V1;
  source: FederalDefendantsSourceContext;
  geometryAuthorityProof: {
    version: typeof FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1;
    digest: string;
    panelCount: number;
    bandCount: number;
  };
  limits: FederalGroupedCompileLimits;
  map: {
    version: typeof FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1;
    bytesDigest: string;
    contentDigest: string;
  };
  boundedSheetProof: {
    sheet: string;
    authoritativeRange: string;
    cellCount: number;
    nonEmptyCellCount: number;
    digest: string;
  };
  formulaProof: { count: number; addresses: string[]; digest: string };
  recipe: FederalDefendantsGroupedRecipeV1;
  recipeDigest: string;
  targetManifest: {
    count: number;
    markerCount: number;
    notPublishedCount: number;
    zeroCount: number;
    digest: string;
  };
  attachmentManifest: {
    count: number;
    operations: number;
    digest: string;
    attachments: FederalDefendantsGroupedAttachmentProof[];
  };
  envelopeDigest: string;
};

export type FederalDefendantsGroupedCompilationResult =
  | { ok: true; envelope: FederalDefendantsGroupedEnvelopeV1 }
  | { ok: false; stage: string; code: string; message: string };
export type FederalDefendantsGroupedPreflightResult =
  | { ok: true }
  | { ok: false; stage: string; code: string; message: string };

export type FederalDefendantsGroupedExecutionV1 = {
  version: typeof FEDERAL_DEFENDANTS_GROUPED_EXECUTION_V1;
  recipeProtocol: typeof FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1;
  source: FederalDefendantsSourceContext;
  geometryAuthorityDigest: string;
  sheet: string;
  tables: Array<{
    table: string;
    sheet: string;
    rows: Array<Record<string, unknown>>;
    warnings: [];
    trace: {
      value_cells: Array<{
        panelId: string;
        target: CellProof;
        rawValue: string | number | null;
        valueStatus: FederalValueStatus;
        markerSource: FederalMarkerSource;
        sourceComment: string | null;
        valueStatusAuthority: z.infer<
          typeof targetValueStatusAuthoritySchema
        > | null;
        provenanceProfileId: string;
        panelKeyAttachment: FederalPanelKeyAttachmentProof;
        attachments: Array<{
          dimensionId: string;
          dimensionName: string;
          direction: HeaderDirection;
          universeId: string;
          candidates: string[];
          selected: string;
          source: CellProof;
          value: string | number;
        }>;
      }>;
    };
  }>;
  warnings: [];
  providerCalls: 0;
  acceptanceAuthority: false;
  trainingEligibility: false;
};

type CellProof = {
  sheet: string;
  address: string;
  row: number;
  col: number;
  data_type: TidyCell["data_type"];
  formula: string | null;
  formatted: string | null;
  comment: string | null;
};
export type FederalMarkerSource = "cell-value" | "cell-comment" | null;
export type FederalValueStatus =
  | "observed"
  | "not-published"
  | "not-available"
  | "not-applicable"
  | "nil-or-rounded-to-zero";

class FederalGroupedError extends Error {
  constructor(
    readonly stage: string,
    readonly code: string,
    message = code,
  ) {
    super(message);
  }
}

export function digestFederalDefendantsBytes(
  value: string | Uint8Array,
): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}
export function digestFederalDefendantsCanonical(value: unknown): string {
  return digestFederalDefendantsBytes(canonicalJson(value));
}
export function digestFederalDefendantsEnvelopeV1(
  envelope: FederalDefendantsGroupedEnvelopeV1,
): string {
  const { envelopeDigest: _ignored, ...rest } = envelope;
  return digestFederalDefendantsCanonical(rest);
}

export function isFederalDefendantsGroupedMapRaw(raw: string): boolean {
  const prefix = raw.slice(0, 65_536);
  return /"version"\s*:\s*"federal-defendants-grouped-semantic-map-v1"/.test(
    prefix,
  );
}

export function parseFederalDefendantsGroupedSemanticMapV1(
  raw: string,
): FederalDefendantsGroupedSemanticMapV1 {
  assertJsonBudget(raw);
  const value: unknown = JSON.parse(raw);
  if (utilTypes.isProxy(value)) throw new Error("PROXY_MAP_REJECTED");
  const parsed = federalDefendantsGroupedSemanticMapV1Schema.parse(value);
  return normalizeMap(parsed);
}

export function estimateFederalGroupedOutputPreflightBytes(
  _raw: string,
  map: FederalDefendantsGroupedSemanticMapV1,
  _declaredWorkbookBytes: number,
): number {
  // semantic-map.json is published verbatim as this deterministic pretty JSON.
  // The other five required artifacts are non-empty, so this is an exact,
  // source-independent lower bound that rejects impossible budgets before any
  // workbook read while preserving final exact cumulative-byte enforcement.
  return safeAdd(
    Buffer.byteLength(`${JSON.stringify(map, null, 2)}\n`),
    5,
    "OUTPUT_LIMIT_EXCEEDED",
  );
}

export function parseFederalDefendantsGroupedRecipeV1(
  raw: string,
): FederalDefendantsGroupedRecipeV1 {
  assertJsonBudget(raw);
  const value: unknown = JSON.parse(raw);
  const recipe = recipeSchema.parse(value);
  validateRecipe(recipe);
  return recipe;
}

export function preflightFederalDefendantsGroupedMapV1(
  map: FederalDefendantsGroupedSemanticMapV1,
  requestedLimits?: Partial<FederalGroupedCompileLimits>,
): FederalDefendantsGroupedPreflightResult {
  try {
    prepareFederalGeometry(map, requestedLimits);
    return { ok: true };
  } catch (error) {
    if (error instanceof FederalGroupedError)
      return {
        ok: false,
        stage: error.stage,
        code: error.code,
        message: error.message,
      };
    return {
      ok: false,
      stage: "schema",
      code: "FEDERAL_GROUPED_SCHEMA_INVALID",
      message:
        error instanceof Error ? error.message : "Invalid Federal grouped map",
    };
  }
}

export function compileFederalDefendantsGroupedRecipeV1(input: {
  mapRaw: string;
  expectedMapBytesDigest: string;
  sheet: ParsedSheet;
  expectedExecutionWorkbookDigest: string;
  expectedSourceWorkbookDigest?: string;
  limits?: Partial<FederalGroupedCompileLimits>;
}): FederalDefendantsGroupedCompilationResult {
  try {
    return { ok: true, envelope: compileOrThrow(input) };
  } catch (error) {
    if (error instanceof FederalGroupedError)
      return {
        ok: false,
        stage: error.stage,
        code: error.code,
        message: error.message,
      };
    return {
      ok: false,
      stage: "schema",
      code: "FEDERAL_GROUPED_SCHEMA_INVALID",
      message:
        error instanceof Error ? error.message : "Invalid Federal grouped map",
    };
  }
}

function compileOrThrow(input: {
  mapRaw: string;
  expectedMapBytesDigest: string;
  sheet: ParsedSheet;
  expectedExecutionWorkbookDigest: string;
  expectedSourceWorkbookDigest?: string;
  limits?: Partial<FederalGroupedCompileLimits>;
}): FederalDefendantsGroupedEnvelopeV1 {
  if (
    digestFederalDefendantsBytes(input.mapRaw) !== input.expectedMapBytesDigest
  )
    fail("schema", "FEDERAL_MAP_EXTERNAL_PIN_MISMATCH");
  const map = parseFederalDefendantsGroupedSemanticMapV1(input.mapRaw);
  if (
    map.source.physicalSheet !== input.sheet.name ||
    map.source.executionWorkbookDigest !==
      input.expectedExecutionWorkbookDigest ||
    (input.expectedSourceWorkbookDigest !== undefined &&
      map.source.sourceWorkbookDigest !== input.expectedSourceWorkbookDigest)
  )
    fail("source", "FEDERAL_SOURCE_CONTEXT_MISMATCH");

  const { limits, geometry, preflight } = prepareFederalGeometry(
    map,
    input.limits,
  );
  const bounded = boundedSheet(input.sheet, map.source.authoritativeRange);
  const cellDimensions = map.logicalTable.dimensions.filter(
    (dimension): dimension is z.infer<typeof cellDimensionSchema> =>
      dimension.source.kind === "cell",
  );
  const cellDimensionIds = new Set(cellDimensions.map((entry) => entry.id));
  const declaredTargets = new Map(
    map.targets.map((target) => [target.address, target]),
  );
  if (declaredTargets.size !== map.targets.length)
    fail("ownership", "FEDERAL_DUPLICATE_TARGET");
  const targetAddresses = new Set<string>();
  const panelAddresses = new Map<string, string[]>();
  const panelAddressSets = new Map<string, Set<string>>();
  const panelIds = new Set<string>();
  const panelKeys = new Set<string>();
  const panelOrders = new Set<number>();
  let activeTargetCount = 0;
  for (const panel of map.panels) {
    if (
      panelIds.has(panel.id) ||
      panelKeys.has(panel.key) ||
      panelOrders.has(panel.order)
    )
      fail("ownership", "FEDERAL_DUPLICATE_PANEL");
    panelIds.add(panel.id);
    panelKeys.add(panel.key);
    panelOrders.add(panel.order);
    const expanded = expandSelectors(
      panel.selectors,
      map.source.authoritativeRange,
    );
    const active: string[] = [];
    for (const address of expanded) {
      if (targetAddresses.has(address))
        fail("ownership", "FEDERAL_DUPLICATE_TARGET_OWNER");
      targetAddresses.add(address);
      const cell = bounded.byAddress.get(address);
      const declaredTarget = declaredTargets.get(address);
      if (isActiveTarget(cell, declaredTarget)) active.push(address);
    }
    if (!active.length) fail("ownership", "FEDERAL_EMPTY_PANEL");
    activeTargetCount += active.length;
    enforceLimit(
      activeTargetCount,
      limits.maxOutputRows,
      "FEDERAL_OUTPUT_ROW_LIMIT",
    );
    const sortedActive = sortAddresses(active);
    panelAddresses.set(panel.id, sortedActive);
    panelAddressSets.set(panel.id, new Set(sortedActive));
  }

  const activeTargets = new Set([...panelAddresses.values()].flat());
  if (
    activeTargets.size !== declaredTargets.size ||
    [...activeTargets].some((address) => !declaredTargets.has(address))
  )
    fail("ownership", "FEDERAL_TARGET_COVERAGE_MISMATCH");

  // Panel identity must be derivable from an exact non-empty Unicode string.
  // Validate it before generic universe validation so invalid panel-key cells
  // cannot be reported as ordinary dimension-source failures.
  for (const panel of map.panels)
    encodeFederalPanelKeySourceValue(
      bounded.byAddress.get(panel.keySource.selectedAddress)?.value,
    );

  const universes = uniqueById(
    map.sourceUniverses,
    "FEDERAL_DUPLICATE_SOURCE_UNIVERSE",
  );
  const universeAddresses = new Map<string, string[]>();
  const universeAddressSets = new Map<string, Set<string>>();
  const universeGroups = new Map<
    string,
    ReturnType<typeof buildHeaderDirectionGroups>
  >();
  const universeByPanelDimension = new Map<
    string,
    FederalDefendantsGroupedSemanticMapV1["sourceUniverses"][number]
  >();
  for (const universe of universes.values()) {
    if (
      !panelIds.has(universe.panelId) ||
      !cellDimensionIds.has(universe.dimensionId)
    )
      fail("ownership", "FEDERAL_SOURCE_UNIVERSE_SCOPE_INVALID");
    const scopeKey = `${universe.panelId}:${universe.dimensionId}`;
    if (universeByPanelDimension.has(scopeKey))
      fail("ownership", "FEDERAL_DUPLICATE_PANEL_DIMENSION_UNIVERSE");
    universeByPanelDimension.set(scopeKey, universe);
    const authorityBand = geometry.bands.get(universe.authorityBandId);
    if (
      !authorityBand ||
      authorityBand.panelId !== universe.panelId ||
      authorityBand.dimensionId !== universe.dimensionId ||
      authorityBand.direction !== universe.direction
    )
      fail("ownership", "FEDERAL_SOURCE_UNIVERSE_AUTHORITY_MISMATCH");
    const addresses = expandSelectors(
      universe.selectors,
      map.source.authoritativeRange,
    );
    if (!addresses.length) fail("ownership", "FEDERAL_EMPTY_SOURCE_UNIVERSE");
    for (const address of addresses) {
      const cell = bounded.byAddress.get(address);
      if (!isDimensionValue(cell))
        fail("ownership", "FEDERAL_INVALID_DIMENSION_SOURCE");
    }
    const normalized = sortAddresses([...new Set(addresses)]);
    universeAddresses.set(universe.id, normalized);
    universeAddressSets.set(universe.id, new Set(normalized));
    universeGroups.set(
      universe.id,
      buildHeaderDirectionGroups({
        headerAddresses: normalized,
        valueAddresses: panelAddresses.get(universe.panelId)!,
        direction: universe.direction,
      }),
    );
    validateCompleteUniverse({
      universe,
      authorityBand,
      addresses: normalized,
      panelTargets: panelAddresses.get(universe.panelId)!,
      authorityRange: map.source.authoritativeRange,
      byAddress: bounded.byAddress,
    });
  }
  if (universeByPanelDimension.size !== panelIds.size * cellDimensions.length)
    fail("ownership", "FEDERAL_PANEL_DIMENSION_UNIVERSE_COVERAGE_MISMATCH");

  const panelKeyProofs = new Map<string, FederalPanelKeyAttachmentProof>();
  const derivedPanelKeys = new Set<string>();
  for (const panel of map.panels) {
    const keyUniverse = universeByPanelDimension.get(
      `${panel.id}:${panel.keySource.dimensionId}`,
    );
    const keyAddresses = keyUniverse
      ? universeAddressSets.get(keyUniverse.id)
      : undefined;
    const keyCell = bounded.byAddress.get(panel.keySource.selectedAddress);
    if (
      !keyUniverse ||
      !keyAddresses?.has(panel.keySource.selectedAddress) ||
      keyCell === undefined
    )
      fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_MISMATCH");
    const encodedValue = encodeFederalPanelKeySourceValue(keyCell.value);
    const derivedKey = `${panel.keySource.dimensionId}:${encodedValue}`;
    if (panel.key !== derivedKey)
      fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_MISMATCH");
    if (derivedPanelKeys.has(derivedKey))
      fail("ownership", "FEDERAL_DUPLICATE_PANEL");
    derivedPanelKeys.add(derivedKey);
    panelKeyProofs.set(panel.id, {
      dimensionId: panel.keySource.dimensionId,
      key: derivedKey,
      selectedAddress: panel.keySource.selectedAddress,
      rawValue: keyCell.value as string,
      encodedValue,
      source: cellProof(keyCell),
    });
  }
  const panelDefinitions = new Map(
    map.panels.map((panel) => [panel.id, panel]),
  );
  const bindings = uniqueById(map.bindings, "FEDERAL_DUPLICATE_BINDING");
  const vectors = uniqueById(map.vectors, "FEDERAL_DUPLICATE_VECTOR");
  const profiles = uniqueById(
    map.provenanceProfiles,
    "FEDERAL_DUPLICATE_PROVENANCE_PROFILE",
  );
  validateVectors(vectors, bindings, cellDimensions);

  const usedPanels = new Set<string>();
  const usedVectors = new Set<string>();
  const usedBindings = new Set<string>();
  const usedProfiles = new Set<string>();
  const usedUniverseAddresses = new Map<string, Set<string>>();
  const attachmentProof: FederalDefendantsGroupedAttachmentProof[] = [];
  let markerCount = 0;
  let notPublishedCount = 0;
  let zeroCount = 0;
  for (const target of map.targets) {
    const panelTargets = panelAddressSets.get(target.panelId);
    if (!panelTargets?.has(target.address))
      fail("ownership", "FEDERAL_TARGET_OUTSIDE_PANEL");
    usedPanels.add(target.panelId);
    const vector = vectors.get(target.vectorId);
    const profile = profiles.get(target.provenanceProfileId);
    if (!vector) fail("ownership", "FEDERAL_MISSING_VECTOR");
    if (!profile) fail("ownership", "FEDERAL_MISSING_PROVENANCE_PROFILE");
    usedVectors.add(target.vectorId);
    usedProfiles.add(target.provenanceProfileId);
    const targetCell = bounded.byAddress.get(target.address);
    const observation = classifyTargetObservation(targetCell, target);
    if (observation.valueStatus !== "observed") markerCount += 1;
    if (observation.valueStatus === "not-published") notPublishedCount += 1;
    if (targetCell?.value === 0) zeroCount += 1;
    const dimensions: FederalDefendantsGroupedAttachmentProof["dimensions"] =
      [];
    const selectedByDimension = new Map<string, string>();
    for (const bindingId of vector.bindingIds) {
      const binding = bindings.get(bindingId);
      if (!binding) fail("ownership", "FEDERAL_MISSING_BINDING");
      const universeDefinition = universes.get(binding.universeId);
      const universe = universeAddresses.get(binding.universeId);
      const universeSet = universeAddressSets.get(binding.universeId);
      if (
        !universeDefinition ||
        !universe ||
        universeDefinition.panelId !== target.panelId ||
        universeDefinition.dimensionId !== binding.dimensionId ||
        universeDefinition.direction !== binding.direction
      )
        fail("ownership", "FEDERAL_BINDING_UNIVERSE_SCOPE_MISMATCH");
      if (!universeSet?.has(binding.selectedAddress))
        fail("ownership", "FEDERAL_SOURCE_OUTSIDE_UNIVERSE");
      const groups = universeGroups.get(binding.universeId);
      if (!groups) fail("ownership", "FEDERAL_SOURCE_UNIVERSE_GROUP_MISSING");
      const resolved = resolveRelationshipAttachmentAtAddress(
        groups,
        target.address,
      );
      if (
        resolved.candidates.length !== 1 ||
        resolved.selectedAddress !== binding.selectedAddress
      )
        fail("ownership", "FEDERAL_AMBIGUOUS_DIMENSION_SOURCE");
      const sourceCell = bounded.byAddress.get(binding.selectedAddress);
      if (!isDimensionValue(sourceCell))
        fail("ownership", "FEDERAL_INVALID_DIMENSION_SOURCE");
      usedBindings.add(binding.id);
      const used =
        usedUniverseAddresses.get(binding.universeId) ?? new Set<string>();
      used.add(binding.selectedAddress);
      usedUniverseAddresses.set(binding.universeId, used);
      selectedByDimension.set(binding.dimensionId, binding.selectedAddress);
      dimensions.push({
        dimensionId: binding.dimensionId,
        direction: binding.direction,
        universeId: binding.universeId,
        candidates: [...resolved.candidates],
        selectedAddress: binding.selectedAddress,
        rawValue: sourceCell.value,
        formula: sourceCell.formula ?? null,
      });
    }
    const panel = panelDefinitions.get(target.panelId)!;
    if (
      selectedByDimension.get(panel.keySource.dimensionId) !==
      panel.keySource.selectedAddress
    )
      fail("ownership", "FEDERAL_PANEL_KEY_BINDING_MISMATCH");
    attachmentProof.push({
      targetAddress: target.address,
      vectorId: target.vectorId,
      panelKeyAttachment: structuredClone(panelKeyProofs.get(panel.id)!),
      dimensions,
    });
  }
  if (usedPanels.size !== panelIds.size)
    fail("ownership", "FEDERAL_UNUSED_PANEL");
  if (usedVectors.size !== vectors.size)
    fail("ownership", "FEDERAL_UNUSED_VECTOR");
  if (usedBindings.size !== bindings.size)
    fail("ownership", "FEDERAL_UNUSED_BINDING");
  if (usedProfiles.size !== profiles.size)
    fail("ownership", "FEDERAL_UNUSED_PROVENANCE_PROFILE");
  for (const id of universeAddresses.keys())
    if (!usedUniverseAddresses.has(id))
      fail("ownership", "FEDERAL_UNUSED_SOURCE_UNIVERSE");

  const recipe: FederalDefendantsGroupedRecipeV1 = {
    version: FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1,
    source: { ...map.source },
    geometryAuthorityDigest: map.geometryAuthorityDigest,
    table: {
      id: map.logicalTable.id,
      name: map.logicalTable.name,
      valuesName: map.logicalTable.valuesName,
    },
    dimensions: map.logicalTable.dimensions.map((entry) =>
      structuredClone(entry),
    ),
    panels: map.panels.map((panel) => ({
      id: panel.id,
      order: panel.order,
      key: panel.key,
      keySource: {
        dimensionId: panel.keySource.dimensionId,
        selectedAddress: panel.keySource.selectedAddress,
        rawValue: panelKeyProofs.get(panel.id)!.rawValue,
        encodedValue: panelKeyProofs.get(panel.id)!.encodedValue,
        source: structuredClone(panelKeyProofs.get(panel.id)!.source),
      },
      name: panel.name,
      targetAddresses: [...panelAddresses.get(panel.id)!],
    })),
    sourceUniverses: map.sourceUniverses.map((entry) => ({
      id: entry.id,
      panelId: entry.panelId,
      dimensionId: entry.dimensionId,
      direction: entry.direction,
      authorityBandId: entry.authorityBandId,
      bandRange: geometry.bands.get(entry.authorityBandId)!.range,
      addresses: [...universeAddresses.get(entry.id)!],
    })),
    bindings: map.bindings.map((entry) => ({ ...entry })),
    vectors: map.vectors.map((entry) => ({
      id: entry.id,
      bindingIds: [...entry.bindingIds],
    })),
    provenanceProfiles: map.provenanceProfiles.map((entry) =>
      structuredClone(entry),
    ),
    targets: map.targets.map((entry) => ({ ...entry })),
  };
  validateRecipe(recipe);
  const execution = executeRecipe(recipe, bounded.sheet);
  const formulas = bounded.sheet.cells
    .filter(
      (cell) => typeof cell.formula === "string" && cell.formula.length > 0,
    )
    .map((cell) => ({ address: cell.address, formula: cell.formula }))
    .sort((left, right) => compareAddresses(left.address, right.address));
  const mapContentDigest = digestFederalDefendantsCanonical(map);
  const withoutDigest: Omit<
    FederalDefendantsGroupedEnvelopeV1,
    "envelopeDigest"
  > = {
    version: FEDERAL_DEFENDANTS_GROUPED_ENVELOPE_V1,
    compilerVersion: FEDERAL_DEFENDANTS_GROUPED_COMPILER_V1,
    source: { ...map.source },
    geometryAuthorityProof: {
      version: FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1,
      digest: geometry.digest,
      panelCount: geometry.panels.size,
      bandCount: geometry.bands.size,
    },
    limits,
    map: {
      version: FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1,
      bytesDigest: input.expectedMapBytesDigest,
      contentDigest: mapContentDigest,
    },
    boundedSheetProof: bounded.proof,
    formulaProof: {
      count: formulas.length,
      addresses: formulas.map((entry) => entry.address),
      digest: digestFederalDefendantsCanonical(formulas),
    },
    recipe,
    recipeDigest: digestFederalDefendantsCanonical(recipe),
    targetManifest: {
      count: map.targets.length,
      markerCount,
      notPublishedCount,
      zeroCount,
      digest: digestFederalDefendantsCanonical(
        execution.tables[0].trace.value_cells.map((entry) => ({
          address: entry.target.address,
          rawValue: entry.rawValue,
          valueStatus: entry.valueStatus,
          markerSource: entry.markerSource,
          sourceComment: entry.sourceComment,
          valueStatusAuthority: entry.valueStatusAuthority,
          targetProof: entry.target,
          provenanceProfileId: entry.provenanceProfileId,
        })),
      ),
    },
    attachmentManifest: {
      count: attachmentProof.reduce(
        (sum, entry) => sum + entry.dimensions.length,
        0,
      ),
      operations: preflight.operations,
      digest: digestFederalDefendantsCanonical(attachmentProof),
      attachments: attachmentProof,
    },
  };
  const envelope: FederalDefendantsGroupedEnvelopeV1 = {
    ...withoutDigest,
    envelopeDigest: digestFederalDefendantsCanonical(withoutDigest),
  };
  return envelope;
}

export function executeFederalDefendantsGroupedRecipeV1(
  envelope: FederalDefendantsGroupedEnvelopeV1,
  input: {
    mapRaw: string;
    sheet: ParsedSheet;
    expectedExecutionWorkbookDigest: string;
    expectedSourceWorkbookDigest?: string;
    trustedEnvelopeDigest: string;
  },
): FederalDefendantsGroupedExecutionV1 {
  if (input.trustedEnvelopeDigest !== envelope.envelopeDigest)
    throw new Error("FEDERAL_TRUSTED_ENVELOPE_DIGEST_MISMATCH");
  if (digestFederalDefendantsEnvelopeV1(envelope) !== envelope.envelopeDigest)
    throw new Error("FEDERAL_ENVELOPE_DIGEST_MISMATCH");
  const recompiled = compileFederalDefendantsGroupedRecipeV1({
    mapRaw: input.mapRaw,
    expectedMapBytesDigest: envelope.map.bytesDigest,
    sheet: input.sheet,
    expectedExecutionWorkbookDigest: input.expectedExecutionWorkbookDigest,
    expectedSourceWorkbookDigest: input.expectedSourceWorkbookDigest,
    limits: envelope.limits,
  });
  if (!recompiled.ok)
    throw new Error(`${recompiled.code}: ${recompiled.message}`);
  if (recompiled.envelope.envelopeDigest !== envelope.envelopeDigest)
    throw new Error("FEDERAL_ENVELOPE_REPRODUCTION_MISMATCH");
  return executeRecipe(
    envelope.recipe,
    boundedSheet(input.sheet, envelope.source.authoritativeRange).sheet,
  );
}

function executeRecipe(
  recipe: FederalDefendantsGroupedRecipeV1,
  sheet: ParsedSheet,
): FederalDefendantsGroupedExecutionV1 {
  validateRecipe(recipe);
  if (recipe.source.physicalSheet !== sheet.name)
    throw new Error("FEDERAL_RECIPE_SHEET_MISMATCH");
  const cells = new Map(sheet.cells.map((cell) => [cell.address, cell]));
  const universes = new Map(
    recipe.sourceUniverses.map((entry) => [entry.id, entry.addresses]),
  );
  const bindings = new Map(recipe.bindings.map((entry) => [entry.id, entry]));
  const vectors = new Map(recipe.vectors.map((entry) => [entry.id, entry]));
  const profiles = new Map(
    recipe.provenanceProfiles.map((entry) => [entry.id, entry.values]),
  );
  const panels = new Map(recipe.panels.map((entry) => [entry.id, entry]));
  const panelKeyAttachments = new Map<string, FederalPanelKeyAttachmentProof>();
  for (const panel of recipe.panels) {
    const sourceCell = cells.get(panel.keySource.selectedAddress);
    if (sourceCell === undefined)
      throw new Error("FEDERAL_RECIPE_PANEL_KEY_SOURCE_MISSING");
    const encodedValue = encodeFederalPanelKeySourceValue(sourceCell.value);
    const sourceProof = cellProof(sourceCell);
    if (
      panel.key !== `${panel.keySource.dimensionId}:${encodedValue}` ||
      panel.keySource.rawValue !== sourceCell.value ||
      panel.keySource.encodedValue !== encodedValue ||
      digestFederalDefendantsCanonical(panel.keySource.source) !==
        digestFederalDefendantsCanonical(sourceProof)
    )
      throw new Error("FEDERAL_RECIPE_PANEL_KEY_SOURCE_DRIFT");
    panelKeyAttachments.set(panel.id, {
      dimensionId: panel.keySource.dimensionId,
      key: panel.key,
      selectedAddress: panel.keySource.selectedAddress,
      rawValue: sourceCell.value as string,
      encodedValue,
      source: sourceProof,
    });
  }
  const universeGroups = new Map(
    recipe.sourceUniverses.map((entry) => {
      const panel = panels.get(entry.panelId);
      if (!panel) throw new Error("FEDERAL_RECIPE_UNIVERSE_PANEL_MISSING");
      return [
        entry.id,
        buildHeaderDirectionGroups({
          headerAddresses: entry.addresses,
          valueAddresses: panel.targetAddresses,
          direction: entry.direction,
        }),
      ] as const;
    }),
  );
  const cellDimensions = recipe.dimensions.filter(
    (dimension): dimension is z.infer<typeof cellDimensionSchema> =>
      dimension.source.kind === "cell",
  );
  const targets = [...recipe.targets].sort((left, right) => {
    const leftOrder = panels.get(left.panelId)?.order;
    const rightOrder = panels.get(right.panelId)?.order;
    if (leftOrder === undefined || rightOrder === undefined)
      throw new Error("FEDERAL_RECIPE_PANEL_MISSING");
    return (
      leftOrder - rightOrder || compareAddresses(left.address, right.address)
    );
  });
  const rows: Array<Record<string, unknown>> = [];
  const trace: FederalDefendantsGroupedExecutionV1["tables"][0]["trace"]["value_cells"] =
    [];
  for (const target of targets) {
    const targetCell = cells.get(target.address);
    if (!targetCell) throw new Error("FEDERAL_RECIPE_TARGET_MISSING");
    const observation = classifyTargetObservation(targetCell, target);
    const vector = vectors.get(target.vectorId);
    const profile = profiles.get(target.provenanceProfileId);
    const panel = panels.get(target.panelId);
    if (!vector || !profile || !panel)
      throw new Error("FEDERAL_RECIPE_REFERENCE_MISSING");
    const bindingByDimension = new Map(
      vector.bindingIds.map((id) => {
        const binding = bindings.get(id);
        if (!binding) throw new Error("FEDERAL_RECIPE_BINDING_MISSING");
        return [binding.dimensionId, binding] as const;
      }),
    );
    const row: Record<string, unknown> = {
      [recipe.table.valuesName]: observation.rawValue,
      [`${recipe.table.valuesName} numeric`]:
        typeof observation.rawValue === "number" ? observation.rawValue : null,
      [`${recipe.table.valuesName} status`]: observation.valueStatus,
      [`${recipe.table.valuesName} marker source`]: observation.markerSource,
      [`${recipe.table.valuesName} source comment`]: observation.sourceComment,
      _panel_id: panel.id,
      _panel_key: panel.key,
      _panel_name: panel.name,
      _panel_order: panel.order,
      _source: sourceCoordinates(targetCell),
    };
    const attachmentTrace: (typeof trace)[number]["attachments"] = [];
    for (const dimension of recipe.dimensions) {
      if (dimension.source.kind === "provenance") {
        row[dimension.name] = provenanceOutput(profile, dimension.source.field);
        continue;
      }
      const binding = bindingByDimension.get(dimension.id);
      if (!binding) throw new Error("FEDERAL_RECIPE_DIMENSION_BINDING_MISSING");
      const universe = universes.get(binding.universeId);
      const sourceCell = cells.get(binding.selectedAddress);
      const groups = universeGroups.get(binding.universeId);
      if (!universe || !groups || !sourceCell || !isDimensionValue(sourceCell))
        throw new Error("FEDERAL_RECIPE_DIMENSION_SOURCE_INVALID");
      const resolved = resolveRelationshipAttachmentAtAddress(
        groups,
        target.address,
      );
      if (
        resolved.candidates.length !== 1 ||
        resolved.selectedAddress !== binding.selectedAddress
      )
        throw new Error("FEDERAL_RECIPE_DIMENSION_RESOLUTION_DRIFT");
      row[dimension.name] = sourceCell.value;
      attachmentTrace.push({
        dimensionId: dimension.id,
        dimensionName: dimension.name,
        direction: binding.direction,
        universeId: binding.universeId,
        candidates: [...resolved.candidates],
        selected: binding.selectedAddress,
        source: cellProof(sourceCell),
        value: sourceCell.value,
      });
    }
    // Every cell-bound dimension must be represented exactly once.
    if (attachmentTrace.length !== cellDimensions.length)
      throw new Error("FEDERAL_RECIPE_DIMENSION_CARDINALITY_DRIFT");
    rows.push(row);
    trace.push({
      panelId: panel.id,
      target: cellProof(targetCell),
      rawValue: observation.rawValue,
      valueStatus: observation.valueStatus,
      markerSource: observation.markerSource,
      sourceComment: observation.sourceComment,
      valueStatusAuthority: target.valueStatusAuthority
        ? structuredClone(target.valueStatusAuthority)
        : null,
      provenanceProfileId: target.provenanceProfileId,
      panelKeyAttachment: structuredClone(panelKeyAttachments.get(panel.id)!),
      attachments: attachmentTrace,
    });
  }
  return {
    version: FEDERAL_DEFENDANTS_GROUPED_EXECUTION_V1,
    recipeProtocol: FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1,
    source: { ...recipe.source },
    geometryAuthorityDigest: recipe.geometryAuthorityDigest,
    sheet: sheet.name,
    tables: [
      {
        table: recipe.table.name,
        sheet: sheet.name,
        rows,
        warnings: [],
        trace: { value_cells: trace },
      },
    ],
    warnings: [],
    providerCalls: 0,
    acceptanceAuthority: false,
    trainingEligibility: false,
  };
}

function normalizeMap(
  value: FederalDefendantsGroupedSemanticMapV1,
): FederalDefendantsGroupedSemanticMapV1 {
  const panelOrder = new Map(
    value.panels.map((panel) => [panel.id, panel.order]),
  );
  return {
    ...structuredClone(value),
    panels: [...value.panels].sort(
      (left, right) =>
        left.order - right.order || left.id.localeCompare(right.id),
    ),
    geometryAuthority: {
      ...structuredClone(value.geometryAuthority),
      panels: [...value.geometryAuthority.panels].sort((left, right) =>
        left.panelId.localeCompare(right.panelId),
      ),
      bands: [...value.geometryAuthority.bands].sort((left, right) =>
        left.id.localeCompare(right.id),
      ),
    },
    sourceUniverses: [...value.sourceUniverses].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    bindings: [...value.bindings].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    vectors: [...value.vectors]
      .map((entry) => ({ ...entry, bindingIds: [...entry.bindingIds] }))
      .sort((left, right) => left.id.localeCompare(right.id)),
    provenanceProfiles: [...value.provenanceProfiles].sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
    targets: [...value.targets].sort(
      (left, right) =>
        (panelOrder.get(left.panelId) ?? Number.MAX_SAFE_INTEGER) -
          (panelOrder.get(right.panelId) ?? Number.MAX_SAFE_INTEGER) ||
        compareAddresses(left.address, right.address),
    ),
  };
}

function validateDimensions(
  dimensions: FederalDefendantsGroupedSemanticMapV1["logicalTable"]["dimensions"],
  valuesName: string,
): void {
  const ids = new Set<string>();
  const names = new Set<string>();
  const reservedNames = new Set([
    valuesName,
    `${valuesName} numeric`,
    `${valuesName} status`,
    `${valuesName} marker source`,
    `${valuesName} source comment`,
    "_panel_id",
    "_panel_key",
    "_panel_name",
    "_panel_order",
    "_source",
  ]);
  const provenanceFields = new Set<FederalProvenanceField>();
  let cellCount = 0;
  for (const dimension of dimensions) {
    if (ids.has(dimension.id)) fail("schema", "FEDERAL_DUPLICATE_DIMENSION_ID");
    if (names.has(dimension.name) || reservedNames.has(dimension.name))
      fail("schema", "FEDERAL_DUPLICATE_OR_RESERVED_OUTPUT_NAME");
    ids.add(dimension.id);
    names.add(dimension.name);
    if (dimension.source.kind === "cell") cellCount += 1;
    else {
      if (provenanceFields.has(dimension.source.field))
        fail("schema", "FEDERAL_DUPLICATE_PROVENANCE_DIMENSION");
      provenanceFields.add(dimension.source.field);
    }
  }
  if (!cellCount) fail("schema", "FEDERAL_CELL_DIMENSION_REQUIRED");
  if (
    provenanceFields.size !== FEDERAL_PROVENANCE_FIELDS.length ||
    FEDERAL_PROVENANCE_FIELDS.some((field) => !provenanceFields.has(field))
  )
    fail("schema", "FEDERAL_PROVENANCE_DIMENSIONS_INCOMPLETE");
}

function validateVectors(
  vectors: Map<
    string,
    FederalDefendantsGroupedSemanticMapV1["vectors"][number]
  >,
  bindings: Map<
    string,
    FederalDefendantsGroupedSemanticMapV1["bindings"][number]
  >,
  cellDimensions: Array<z.infer<typeof cellDimensionSchema>>,
): void {
  let count = 0;
  for (const vector of vectors.values()) {
    count += vector.bindingIds.length;
    enforceLimit(count, MAX_FEDERAL_GROUPED_BINDINGS, "FEDERAL_BINDING_LIMIT");
    if (vector.bindingIds.length !== cellDimensions.length)
      fail("ownership", "FEDERAL_VECTOR_DIMENSION_MISSING");
    const seen = new Set<string>();
    vector.bindingIds.forEach((id, index) => {
      const binding = bindings.get(id);
      if (
        !binding ||
        binding.dimensionId !== cellDimensions[index].id ||
        seen.has(binding.dimensionId)
      )
        fail("ownership", "FEDERAL_VECTOR_DIMENSION_ORDER_MISMATCH");
      seen.add(binding.dimensionId);
    });
  }
}

function validateRecipe(recipe: FederalDefendantsGroupedRecipeV1): void {
  recipeSchema.parse(recipe);
  validateDimensions(recipe.dimensions, recipe.table.valuesName);
  if (recipe.targets.length > MAX_FEDERAL_GROUPED_TARGETS)
    throw new Error("FEDERAL_TARGET_LIMIT");
}

function boundedSheet(
  sheet: ParsedSheet,
  authority: string,
): {
  sheet: ParsedSheet;
  byAddress: Map<string, TidyCell>;
  proof: FederalDefendantsGroupedEnvelopeV1["boundedSheetProof"];
} {
  const range = parseRange(authority);
  if (range.start.row !== 1 || range.start.col !== 1)
    fail("source", "FEDERAL_AUTHORITY_RANGE_MUST_START_R1C1");
  const cells = sheet.cells
    .filter((cell) => withinRange(cell.address, range))
    .sort((left, right) => compareAddresses(left.address, right.address));
  const merges = sheet.merges.filter((merge) => {
    const candidate = parseRange(merge.range);
    return (
      candidate.start.row >= range.start.row &&
      candidate.start.col >= range.start.col &&
      candidate.end.row <= range.end.row &&
      candidate.end.col <= range.end.col
    );
  });
  const bounded: ParsedSheet = {
    name: sheet.name,
    usedRange: authority,
    rowCount: range.end.row,
    columnCount: range.end.col,
    nonEmptyCellCount: cells.filter((cell) => !isBlank(cell)).length,
    cells,
    merges,
  };
  const proofPayload = cells.map((cell) => ({
    address: cell.address,
    value: cell.value,
    data_type: cell.data_type,
    formula: cell.formula ?? null,
    formatted: cell.formatted ?? null,
    comment: cell.comment ?? null,
    hyperlink: cell.hyperlink ?? null,
  }));
  return {
    sheet: bounded,
    byAddress: new Map(cells.map((cell) => [cell.address, cell])),
    proof: {
      sheet: sheet.name,
      authoritativeRange: authority,
      cellCount: cells.length,
      nonEmptyCellCount: bounded.nonEmptyCellCount,
      digest: digestFederalDefendantsCanonical(proofPayload),
    },
  };
}

function normalizeCompileLimits(
  requested: Partial<FederalGroupedCompileLimits> | undefined,
): FederalGroupedCompileLimits {
  const selector =
    requested?.maxSelectorCells ?? MAX_FEDERAL_GROUPED_SELECTED_CELLS;
  const rows = requested?.maxOutputRows ?? MAX_FEDERAL_GROUPED_TARGETS;
  const operations = requested?.maxOperations ?? MAX_FEDERAL_GROUPED_OPERATIONS;
  if (
    !Number.isSafeInteger(selector) ||
    selector < 1 ||
    !Number.isSafeInteger(rows) ||
    rows < 1 ||
    !Number.isSafeInteger(operations) ||
    operations < 1
  )
    fail("limit", "FEDERAL_CALLER_LIMIT_INVALID");
  return {
    maxSelectorCells: Math.min(selector, MAX_FEDERAL_GROUPED_SELECTED_CELLS),
    maxOutputRows: Math.min(rows, MAX_FEDERAL_GROUPED_TARGETS),
    maxOperations: Math.min(operations, MAX_FEDERAL_GROUPED_OPERATIONS),
  };
}

type GeometryAuthorityIndex = {
  digest: string;
  panels: Map<string, FederalDefendantsGeometryAuthorityV1["panels"][number]>;
  bands: Map<string, FederalDefendantsGeometryAuthorityV1["bands"][number]>;
};
type PanelGeometry = {
  cardinality: number;
  minimumRow: number;
  maximumRow: number;
  minimumCol: number;
  maximumCol: number;
};
type FederalGeometryPreflight = { selectedCells: number; operations: number };

function validateGeometryAuthority(
  map: FederalDefendantsGroupedSemanticMapV1,
): GeometryAuthorityIndex {
  const authority = map.geometryAuthority;
  const digest = digestFederalDefendantsCanonical(authority);
  if (
    digest !== map.geometryAuthorityDigest ||
    canonicalJson(authority.source) !== canonicalJson(map.source)
  )
    fail("authority", "FEDERAL_GEOMETRY_AUTHORITY_DIGEST_MISMATCH");
  const panels = new Map<
    string,
    FederalDefendantsGeometryAuthorityV1["panels"][number]
  >();
  for (const panel of authority.panels) {
    if (panels.has(panel.panelId))
      fail("authority", "FEDERAL_DUPLICATE_GEOMETRY_PANEL");
    panels.set(panel.panelId, panel);
  }
  if (
    panels.size !== map.panels.length ||
    map.panels.some((panel) => {
      const pinned = panels.get(panel.id);
      return (
        !pinned ||
        canonicalJson(pinned.targetSelectors) !== canonicalJson(panel.selectors)
      );
    })
  )
    fail("authority", "FEDERAL_GEOMETRY_PANEL_COVERAGE_MISMATCH");
  const bands = new Map<
    string,
    FederalDefendantsGeometryAuthorityV1["bands"][number]
  >();
  const scopes = new Set<string>();
  for (const band of authority.bands) {
    const scope = `${band.panelId}:${band.dimensionId}`;
    if (bands.has(band.id) || scopes.has(scope) || !panels.has(band.panelId))
      fail("authority", "FEDERAL_DUPLICATE_GEOMETRY_BAND");
    bands.set(band.id, band);
    scopes.add(scope);
  }
  const cellDimensionIds = map.logicalTable.dimensions
    .filter((dimension) => dimension.source.kind === "cell")
    .map((dimension) => dimension.id);
  const expectedScopes = new Set(
    map.panels.flatMap((panel) =>
      cellDimensionIds.map((dimensionId) => `${panel.id}:${dimensionId}`),
    ),
  );
  if (
    scopes.size !== expectedScopes.size ||
    [...expectedScopes].some((scope) => !scopes.has(scope))
  )
    fail("authority", "FEDERAL_GEOMETRY_BAND_COVERAGE_MISMATCH");
  return { digest, panels, bands };
}

function prepareFederalGeometry(
  map: FederalDefendantsGroupedSemanticMapV1,
  requestedLimits?: Partial<FederalGroupedCompileLimits>,
): {
  limits: FederalGroupedCompileLimits;
  geometry: GeometryAuthorityIndex;
  preflight: FederalGeometryPreflight;
} {
  const limits = normalizeCompileLimits(requestedLimits);
  enforceLimit(
    map.targets.length,
    limits.maxOutputRows,
    "FEDERAL_OUTPUT_ROW_LIMIT",
  );
  validateDimensions(map.logicalTable.dimensions, map.logicalTable.valuesName);
  const geometry = validateGeometryAuthority(map);
  return {
    limits,
    geometry,
    preflight: preflightFederalGeometry(map, limits, geometry),
  };
}

function preflightFederalGeometry(
  map: FederalDefendantsGroupedSemanticMapV1,
  limits: FederalGroupedCompileLimits,
  geometry: GeometryAuthorityIndex,
): FederalGeometryPreflight {
  const panelIds = new Set(map.panels.map((panel) => panel.id));
  if (panelIds.size !== map.panels.length)
    fail("ownership", "FEDERAL_DUPLICATE_PANEL");
  const panelGeometry = new Map<string, PanelGeometry>();
  let selectedCells = 0;
  let operations = 0;
  const addSelected = (value: number): void => {
    selectedCells = safeAdd(
      selectedCells,
      value,
      "FEDERAL_SELECTED_CELL_LIMIT",
    );
    enforceLimit(
      selectedCells,
      limits.maxSelectorCells,
      "FEDERAL_SELECTED_CELL_LIMIT",
    );
  };
  const addOperations = (value: number): void => {
    operations = safeAdd(operations, value, "FEDERAL_OPERATION_LIMIT");
    enforceLimit(operations, limits.maxOperations, "FEDERAL_OPERATION_LIMIT");
  };
  for (const panel of map.panels) {
    const targetGeometry = selectorGeometry(
      panel.selectors,
      map.source.authoritativeRange,
    );
    if (targetGeometry.cardinality < 1)
      fail("ownership", "FEDERAL_EMPTY_PANEL");
    panelGeometry.set(panel.id, targetGeometry);
    addSelected(targetGeometry.cardinality);
    // Exact target ownership and the two compilation/reproduction passes.
    addOperations(
      safeMultiply(targetGeometry.cardinality, 3, "FEDERAL_OPERATION_LIMIT"),
    );
  }
  const universeScopes = new Set<string>();
  for (const universe of map.sourceUniverses) {
    const targets = panelGeometry.get(universe.panelId);
    const authorityBand = geometry.bands.get(universe.authorityBandId);
    const scope = `${universe.panelId}:${universe.dimensionId}`;
    if (
      !targets ||
      universeScopes.has(scope) ||
      !authorityBand ||
      authorityBand.panelId !== universe.panelId ||
      authorityBand.dimensionId !== universe.dimensionId ||
      authorityBand.direction !== universe.direction
    )
      fail("ownership", "FEDERAL_SOURCE_UNIVERSE_SCOPE_INVALID");
    universeScopes.add(scope);
    const selectorCells = selectorCardinality(
      universe.selectors,
      map.source.authoritativeRange,
    );
    addSelected(selectorCells);
    const bandCells = validateBandGeometry(
      authorityBand.range,
      universe.direction,
      targets,
      map.source.authoritativeRange,
    );
    addSelected(bandCells);
    // Seven relationship passes cover: completeness, proof, compile execution,
    // trusted reproduction completeness/proof/execution, and final execution.
    const relationshipWork = safeMultiply(
      safeMultiply(
        targets.cardinality,
        safeAdd(bandCells, 1, "FEDERAL_OPERATION_LIMIT"),
        "FEDERAL_OPERATION_LIMIT",
      ),
      7,
      "FEDERAL_OPERATION_LIMIT",
    );
    addOperations(
      safeAdd(bandCells, relationshipWork, "FEDERAL_OPERATION_LIMIT"),
    );
  }
  addOperations(map.bindings.length);
  addOperations(
    map.vectors.reduce(
      (sum, vector) =>
        safeAdd(sum, vector.bindingIds.length, "FEDERAL_OPERATION_LIMIT"),
      0,
    ),
  );
  return { selectedCells, operations };
}

function selectorGeometry(
  selectors: Array<z.infer<typeof selectorSchema>>,
  authority: string,
): PanelGeometry {
  const allowed = parseRange(authority);
  let cardinality = 0;
  let minimumRow = Number.MAX_SAFE_INTEGER;
  let maximumRow = 0;
  let minimumCol = Number.MAX_SAFE_INTEGER;
  let maximumCol = 0;
  for (const selector of selectors) {
    const selected =
      "address" in selector
        ? {
            start: parseCell(selector.address),
            end: parseCell(selector.address),
          }
        : parseRange(selector.range);
    if (
      selected.start.row < allowed.start.row ||
      selected.start.col < allowed.start.col ||
      selected.end.row > allowed.end.row ||
      selected.end.col > allowed.end.col
    )
      fail("ownership", "FEDERAL_SELECTOR_OUTSIDE_AUTHORITY");
    cardinality = safeAdd(
      cardinality,
      rangeCardinality(selected, "FEDERAL_SELECTOR_CARDINALITY_INVALID"),
      "FEDERAL_SELECTED_CELL_LIMIT",
    );
    minimumRow = Math.min(minimumRow, selected.start.row);
    maximumRow = Math.max(maximumRow, selected.end.row);
    minimumCol = Math.min(minimumCol, selected.start.col);
    maximumCol = Math.max(maximumCol, selected.end.col);
  }
  return { cardinality, minimumRow, maximumRow, minimumCol, maximumCol };
}

function addressGeometry(addresses: string[]): PanelGeometry {
  const cells = addresses.map(parseCell);
  return {
    cardinality: cells.length,
    minimumRow: Math.min(...cells.map((entry) => entry.row)),
    maximumRow: Math.max(...cells.map((entry) => entry.row)),
    minimumCol: Math.min(...cells.map((entry) => entry.col)),
    maximumCol: Math.max(...cells.map((entry) => entry.col)),
  };
}

function validateBandGeometry(
  bandRange: string,
  direction: HeaderDirection,
  targets: PanelGeometry,
  authority: string,
): number {
  const band = parseRange(bandRange);
  const allowed = parseRange(authority);
  if (
    band.start.row < allowed.start.row ||
    band.start.col < allowed.start.col ||
    band.end.row > allowed.end.row ||
    band.end.col > allowed.end.col
  )
    fail("ownership", "FEDERAL_SOURCE_UNIVERSE_BAND_INVALID");
  if (direction === "N" || direction === "NNW") {
    if (
      band.start.col !== targets.minimumCol ||
      band.end.col !== targets.maximumCol ||
      band.end.row >= targets.minimumRow
    )
      fail("ownership", "FEDERAL_SOURCE_UNIVERSE_BAND_INVALID");
  } else if (
    band.start.row !== targets.minimumRow ||
    band.end.row !== targets.maximumRow ||
    band.end.col >= targets.minimumCol
  )
    fail("ownership", "FEDERAL_SOURCE_UNIVERSE_BAND_INVALID");
  return rangeCardinality(band, "FEDERAL_SOURCE_UNIVERSE_BAND_INVALID");
}

function selectorCardinality(
  selectors: Array<z.infer<typeof selectorSchema>>,
  authority: string,
): number {
  const allowed = parseRange(authority);
  let count = 0;
  for (const selector of selectors) {
    const selected =
      "address" in selector
        ? {
            start: parseCell(selector.address),
            end: parseCell(selector.address),
          }
        : parseRange(selector.range);
    if (
      selected.start.row < allowed.start.row ||
      selected.start.col < allowed.start.col ||
      selected.end.row > allowed.end.row ||
      selected.end.col > allowed.end.col
    )
      fail("ownership", "FEDERAL_SELECTOR_OUTSIDE_AUTHORITY");
    const cells = rangeCardinality(
      selected,
      "FEDERAL_SELECTOR_CARDINALITY_INVALID",
    );
    count += cells;
    enforceLimit(
      count,
      MAX_FEDERAL_GROUPED_SELECTED_CELLS,
      "FEDERAL_SELECTED_CELL_LIMIT",
    );
  }
  return count;
}

function expandSelectors(
  selectors: Array<z.infer<typeof selectorSchema>>,
  authority: string,
): string[] {
  // Cardinality and containment are proven before expandRange allocates.
  selectorCardinality(selectors, authority);
  const addresses: string[] = [];
  for (const selector of selectors) {
    const expanded =
      "address" in selector ? [selector.address] : expandRange(selector.range);
    addresses.push(...expanded);
  }
  if (new Set(addresses).size !== addresses.length)
    fail("ownership", "FEDERAL_DUPLICATE_SELECTOR_CELL");
  return sortAddresses(addresses);
}

function validateCompleteUniverse(input: {
  universe: FederalDefendantsGroupedSemanticMapV1["sourceUniverses"][number];
  authorityBand: FederalDefendantsGeometryAuthorityV1["bands"][number];
  addresses: string[];
  panelTargets: string[];
  authorityRange: string;
  byAddress: Map<string, TidyCell>;
}): void {
  validateBandGeometry(
    input.authorityBand.range,
    input.universe.direction,
    addressGeometry(input.panelTargets),
    input.authorityRange,
  );
  const declared = new Set(input.addresses);
  const expectedBand = new Set(
    expandRange(input.authorityBand.range).filter((address) =>
      isDimensionValue(input.byAddress.get(address)),
    ),
  );
  if (
    expectedBand.size !== declared.size ||
    [...expectedBand].some((address) => !declared.has(address))
  )
    fail(
      "ownership",
      "FEDERAL_INCOMPLETE_SOURCE_UNIVERSE",
      `FEDERAL_INCOMPLETE_SOURCE_UNIVERSE:${input.universe.id}`,
    );

  const groups = buildHeaderDirectionGroups({
    headerAddresses: input.addresses,
    valueAddresses: input.panelTargets,
    direction: input.universe.direction,
  });
  for (const target of input.panelTargets) {
    const resolved = resolveRelationshipAttachmentAtAddress(groups, target);
    if (resolved.candidates.length !== 1 || !resolved.selectedAddress)
      fail(
        "ownership",
        "FEDERAL_INCOMPLETE_SOURCE_UNIVERSE",
        `FEDERAL_INCOMPLETE_SOURCE_UNIVERSE:${input.universe.id}`,
      );
  }
  // A complete header band can legitimately contain a candidate whose sparse
  // value position is blank; completeness, not forced use, is authoritative.
}

function hasOnlyUnicodeScalarValues(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}

function isRfc3986UnreservedByte(byte: number): boolean {
  return (
    (byte >= 0x41 && byte <= 0x5a) ||
    (byte >= 0x61 && byte <= 0x7a) ||
    (byte >= 0x30 && byte <= 0x39) ||
    byte === 0x2d ||
    byte === 0x2e ||
    byte === 0x5f ||
    byte === 0x7e
  );
}

export function encodeFederalPanelKeySourceValue(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    !hasOnlyUnicodeScalarValues(value)
  )
    fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_INVALID");
  const bytes = new TextEncoder().encode(value);
  if (bytes.length === 0 || bytes.length > MAX_FEDERAL_PANEL_KEY_SOURCE_BYTES)
    fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_INVALID");
  let encoded = "";
  for (const byte of bytes)
    encoded += isRfc3986UnreservedByte(byte)
      ? String.fromCharCode(byte)
      : `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
  if (!panelKeyEncodedValueSchema.safeParse(encoded).success)
    fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_INVALID");
  return encoded;
}

export function decodeFederalPanelKeySourceValue(encoded: unknown): string {
  if (
    typeof encoded !== "string" ||
    !panelKeyEncodedValueSchema.safeParse(encoded).success
  )
    fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_INVALID");
  const bytes: number[] = [];
  for (let index = 0; index < encoded.length; ) {
    const code = encoded.charCodeAt(index);
    if (code <= 0x7f && isRfc3986UnreservedByte(code)) {
      bytes.push(code);
      index += 1;
      continue;
    }
    if (
      encoded[index] !== "%" ||
      !/^[0-9A-F]{2}$/.test(encoded.slice(index + 1, index + 3))
    )
      fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_INVALID");
    bytes.push(Number.parseInt(encoded.slice(index + 1, index + 3), 16));
    index += 3;
  }
  let decoded: string;
  try {
    decoded = new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(bytes),
    );
  } catch {
    fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_INVALID");
  }
  if (
    decoded.length === 0 ||
    !hasOnlyUnicodeScalarValues(decoded) ||
    encodeFederalPanelKeySourceValue(decoded) !== encoded
  )
    fail("ownership", "FEDERAL_PANEL_KEY_SOURCE_INVALID");
  return decoded;
}

type FederalTargetObservation = {
  rawValue: string | number | null;
  valueStatus: FederalValueStatus;
  markerSource: FederalMarkerSource;
  sourceComment: string | null;
};

function isActiveTarget(
  cell: TidyCell | undefined,
  target: FederalDefendantsGroupedSemanticMapV1["targets"][number] | undefined,
): boolean {
  if (!isBlank(cell)) {
    if (target?.valueStatusAuthority)
      fail("ownership", "FEDERAL_COMMENT_STATUS_VALUE_CONFLICT");
    if (target) classifyTargetObservation(cell, target);
    else classifyTargetValue(cell);
    return true;
  }
  if (!target?.valueStatusAuthority) return false;
  classifyTargetObservation(cell, target);
  return true;
}

function classifyTargetObservation(
  cell: TidyCell | undefined,
  target: FederalDefendantsGroupedSemanticMapV1["targets"][number],
): FederalTargetObservation {
  const authority = target.valueStatusAuthority;
  if (authority) {
    if (!isBlank(cell))
      fail("ownership", "FEDERAL_COMMENT_STATUS_VALUE_CONFLICT");
    if (
      cell === undefined ||
      cell.data_type !== "blank" ||
      cell.value !== null ||
      cell.comment !== authority.rawComment
    )
      fail("ownership", "FEDERAL_COMMENT_STATUS_AUTHORITY_MISMATCH");
    return {
      rawValue: null,
      valueStatus: authority.status,
      markerSource: "cell-comment",
      sourceComment: cell.comment,
    };
  }
  const valueStatus = classifyTargetValue(cell);
  return {
    rawValue: cell!.value as string | number,
    valueStatus,
    markerSource: valueStatus === "observed" ? null : "cell-value",
    sourceComment: cell?.comment ?? null,
  };
}

function classifyTargetValue(cell: TidyCell | undefined): FederalValueStatus {
  const value = cell?.value;
  if (typeof value === "number" && Number.isFinite(value)) return "observed";
  if (typeof value !== "string")
    fail("ownership", "FEDERAL_INVALID_TARGET_VALUE");
  switch (value) {
    case "np":
    case "n.p.":
      return "not-published";
    case "na":
    case "n.a.":
      return "not-available";
    case "..":
      return "not-applicable";
    case "-":
    case "–":
      return "nil-or-rounded-to-zero";
    default:
      fail("ownership", "FEDERAL_INVALID_TARGET_MARKER");
  }
}

function provenanceOutput(
  profile: FederalTargetProvenance,
  field: FederalProvenanceField,
): string | boolean {
  if (field === "footnoteReferences") return profile.footnoteRefs.join("|");
  if (field === "perturbation") return profile.perturbation;
  return profile[field];
}

function isDimensionValue(
  cell: TidyCell | undefined,
): cell is TidyCell & { value: string | number } {
  return (
    cell !== undefined &&
    ((typeof cell.value === "string" && cell.value.length > 0) ||
      (typeof cell.value === "number" && Number.isFinite(cell.value)))
  );
}
function isBlank(cell: TidyCell | undefined): boolean {
  return (
    cell === undefined || cell.data_type === "blank" || cell.value === null
  );
}
function cellProof(cell: TidyCell): CellProof {
  return {
    sheet: cell.sheet,
    address: cell.address,
    row: cell.row,
    col: cell.col,
    data_type: cell.data_type,
    formula: cell.formula ?? null,
    formatted: cell.formatted ?? null,
    comment: cell.comment ?? null,
  };
}
function sourceCoordinates(cell: TidyCell): {
  sheet: string;
  address: string;
  row: number;
  col: number;
} {
  return {
    sheet: cell.sheet,
    address: cell.address,
    row: cell.row,
    col: cell.col,
  };
}
function withinRange(
  address: string,
  range: ReturnType<typeof parseRange>,
): boolean {
  const cell = parseCell(address);
  return (
    cell.row >= range.start.row &&
    cell.row <= range.end.row &&
    cell.col >= range.start.col &&
    cell.col <= range.end.col
  );
}
function sortAddresses(addresses: string[]): string[] {
  return [...addresses].sort(compareAddresses);
}
function compareAddresses(left: string, right: string): number {
  const a = parseCell(left);
  const b = parseCell(right);
  return a.row - b.row || a.col - b.col;
}
function uniqueById<T extends { id: string }>(
  entries: T[],
  code: string,
): Map<string, T> {
  const result = new Map<string, T>();
  for (const entry of entries) {
    if (result.has(entry.id)) fail("schema", code);
    result.set(entry.id, entry);
  }
  return result;
}
function rangeCardinality(
  range: ReturnType<typeof parseRange>,
  code: string,
): number {
  const rows = range.end.row - range.start.row + 1;
  const columns = range.end.col - range.start.col + 1;
  return safeMultiply(rows, columns, code);
}
function safeAdd(left: number, right: number, code: string): number {
  const result = left + right;
  if (!Number.isSafeInteger(result) || result < 0) fail("limit", code);
  return result;
}
function safeMultiply(left: number, right: number, code: string): number {
  const result = left * right;
  if (!Number.isSafeInteger(result) || result < 1) fail("limit", code);
  return result;
}
function enforceLimit(value: number, maximum: number, code: string): void {
  if (!Number.isSafeInteger(value) || value < 0 || value > maximum)
    fail("limit", code);
}
export function assertFederalGroupedJsonBudget(raw: string): void {
  if (Buffer.byteLength(raw) > MAX_FEDERAL_GROUPED_JSON_BYTES)
    throw new Error("FEDERAL_GROUPED_JSON_BYTE_LIMIT");
  type Context =
    | {
        kind: "object";
        state: "key-or-end" | "key" | "colon" | "value" | "comma-or-end";
      }
    | { kind: "array"; state: "value-or-end" | "value" | "comma-or-end" };
  const stack: Context[] = [];
  let rootState: "value" | "done" = "value";
  let nodes = 0;
  let index = 0;
  const failJson = (): never => {
    throw new Error("FEDERAL_GROUPED_JSON_STRUCTURE_INVALID");
  };
  const skipWhitespace = (): void => {
    while (index < raw.length && /\s/.test(raw[index]!)) index += 1;
  };
  const countNode = (): void => {
    nodes += 1;
    if (nodes > MAX_FEDERAL_GROUPED_JSON_NODES)
      throw new Error("FEDERAL_GROUPED_JSON_NODE_LIMIT");
  };
  const scanString = (): void => {
    if (raw[index] !== '"') failJson();
    index += 1;
    while (index < raw.length) {
      const char = raw[index++]!;
      if (char === '"') return;
      if (char.charCodeAt(0) < 0x20) failJson();
      if (char !== "\\") continue;
      if (index >= raw.length) failJson();
      const escaped = raw[index++]!;
      if ('"\\/bfnrt'.includes(escaped)) continue;
      if (
        escaped !== "u" ||
        !/^[0-9a-fA-F]{4}$/.test(raw.slice(index, index + 4))
      )
        failJson();
      index += 4;
    }
    failJson();
  };
  const markValueConsumed = (): void => {
    const parent = stack.at(-1);
    if (!parent) rootState = "done";
    else if (parent.kind === "object") parent.state = "comma-or-end";
    else parent.state = "comma-or-end";
  };
  const consumeValue = (): void => {
    skipWhitespace();
    const char = raw[index];
    if (char === undefined) failJson();
    countNode();
    markValueConsumed();
    if (char === '"') {
      scanString();
      return;
    }
    if (char === "{") {
      index += 1;
      stack.push({ kind: "object", state: "key-or-end" });
    } else if (char === "[") {
      index += 1;
      stack.push({ kind: "array", state: "value-or-end" });
    } else {
      const remainder = raw.slice(index);
      const token =
        /^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(
          remainder,
        );
      if (!token) throw new Error("FEDERAL_GROUPED_JSON_STRUCTURE_INVALID");
      index += token[0].length;
    }
    if (stack.length > MAX_FEDERAL_GROUPED_JSON_DEPTH)
      throw new Error("FEDERAL_GROUPED_JSON_DEPTH_LIMIT");
  };

  while (true) {
    skipWhitespace();
    const context = stack.at(-1);
    if (!context) {
      if (rootState === "value") consumeValue();
      else {
        skipWhitespace();
        if (index !== raw.length) failJson();
        return;
      }
      continue;
    }
    const char = raw[index];
    if (context.kind === "object") {
      if (context.state === "key-or-end") {
        if (char === "}") {
          index += 1;
          stack.pop();
        } else {
          scanString();
          context.state = "colon";
        }
      } else if (context.state === "key") {
        scanString();
        context.state = "colon";
      } else if (context.state === "colon") {
        if (char !== ":") failJson();
        index += 1;
        context.state = "value";
      } else if (context.state === "value") consumeValue();
      else if (char === ",") {
        index += 1;
        context.state = "key";
      } else if (char === "}") {
        index += 1;
        stack.pop();
      } else failJson();
    } else if (context.state === "value-or-end") {
      if (char === "]") {
        index += 1;
        stack.pop();
      } else consumeValue();
    } else if (context.state === "value") consumeValue();
    else if (char === ",") {
      index += 1;
      context.state = "value";
    } else if (char === "]") {
      index += 1;
      stack.pop();
    } else failJson();
  }
}

function assertJsonBudget(raw: string): void {
  assertFederalGroupedJsonBudget(raw);
}
function canonicalJson(value: unknown): string {
  return JSON.stringify(stable(value));
}
function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (isRecord(value))
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, stable(value[key])]),
    );
  return value;
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function fail(stage: string, code: string, message = code): never {
  throw new FederalGroupedError(stage, code, message);
}
