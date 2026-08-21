/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import { z } from "zod";
import { expandRange, formatRange, parseCell, parseRange } from "../address.js";
import type { RecipeV01 } from "../recipe/types.js";
import {
  compileCellRoleSketch,
  type CellRoleCompileError,
} from "./compiler-v02.js";
import type { CompactSemanticContext } from "../context/compactContext.js";
import {
  buildFormatAwareSemanticRegionCatalog,
  formatSignatureForPrompt,
  type SemanticCellFormattingFact,
} from "./format-aware-region-catalog-v2.js";
import {
  semanticTableMapSchema,
  type SemanticMapRoleNormalization,
  type SemanticTableMapV1,
} from "./semantic-map-v1.js";
import type {
  CellRoleSketchV02,
  SketchRoleSelectorV02,
} from "./cell-role-sketch-v02.js";
import {
  validateCellRoleSketchGeometry,
  type CellRoleGeometryOptions,
  type GeometryDiagnostic,
} from "./geometry-v02.js";
import type { RelationshipKind } from "./types.js";

export const ROLE_AWARE_REGION_CATALOG_VERSION =
  "semantic-region-catalog-v5-adjacent-year-aware" as const;
export const DEFAULT_ROLE_AWARE_REGION_LIMIT = 160;
export const MAX_ROLE_AWARE_SELECTED_CELLS = 100_000;
export const MIN_NUMERIC_YEAR_LIKE_VALUE = 1900;
export const MAX_NUMERIC_YEAR_LIKE_VALUE = 2099;

export const geometricRoleHintSchema = z.enum([
  "observations",
  "direct-row-candidate",
  "direct-column-candidate",
  "cascading-row-candidate",
  "cascading-column-candidate",
  "header-format-candidate",
]);
export type GeometricRoleHint = z.infer<typeof geometricRoleHintSchema>;

export type RoleAwareSemanticRegionCandidate = {
  id: string;
  /** One or more exact rectangles; disjoint repeated panels remain compact. */
  segments: string[];
  kinds: string[];
  roleHints: GeometricRoleHint[];
  formatSignatures: string[];
  formatting: string[];
  selectedCellCount: number;
  nonblankCount: number;
  valueLikeCount: number;
  sample: string[];
};

export type RoleAwareSemanticRegionCatalog = {
  version: typeof ROLE_AWARE_REGION_CATALOG_VERSION;
  sheet: string;
  candidates: RoleAwareSemanticRegionCandidate[];
  omittedCandidateCount: number;
  observationPanelCount: number;
  formatFactCount: number;
  cellDataFactCount: number;
};

export type SemanticCellDataFact = {
  address: string;
  dataType: string;
};

export type YearLikeCellFact = {
  address: string;
  value: number;
  horizontalYearLikeNeighbors: string[];
  verticalYearLikeNeighbors: string[];
};

export type SemanticCompletenessDiagnostic = {
  code: "UNASSIGNED_DIRECT_HEADER_GROUP" | "UNASSIGNED_CASCADING_HEADER_GROUP";
  candidateId: string;
  roleHint:
    | "direct-row-candidate"
    | "direct-column-candidate"
    | "cascading-row-candidate"
    | "cascading-column-candidate";
  selectedCellCount: number;
  missingCellCount: number;
  sample: string[];
  message: string;
};

export type RoleAwareCompilationFailure = {
  ok: false;
  stage: "model-form" | "region-resolution" | "geometry" | "compiler";
  code: string;
  message: string;
  diagnostics: GeometryDiagnostic[];
};

export type RoleAwareCompilationSuccess = {
  ok: true;
  map: SemanticTableMapV1;
  sketch: CellRoleSketchV02;
  canonicalSketchJson: string;
  recipe: RecipeV01;
  canonicalRecipeJson: string;
  compilerVersion: string;
  normalizations: {
    values: SemanticMapRoleNormalization;
    dimensions: SemanticMapRoleNormalization[];
  };
  captionHints: Array<{ dimension: string; hints: string[] }>;
  warnings: string[];
};

export type RoleAwareCompilationResult =
  | RoleAwareCompilationFailure
  | RoleAwareCompilationSuccess;

type Panel = {
  row1: number;
  col1: number;
  row2: number;
  col2: number;
};

type CandidateDraft = {
  segments: Set<string>;
  kinds: Set<string>;
  roleHints: Set<GeometricRoleHint>;
  formatSignatures: Set<string>;
};

type Anchor = {
  address: string;
  row: number;
  col: number;
  signature: string;
};

const DIRECTION_TO_RELATIONSHIP: Readonly<
  Record<"N" | "W" | "NNW" | "WNW", RelationshipKind>
> = {
  N: "direct-column",
  W: "direct-row",
  NNW: "cascading-column",
  WNW: "cascading-row",
};

const KIND_PRIORITY: Readonly<Record<string, number>> = {
  "observation-panel-trimmed-leading-year-row": 134,
  "repeated-observation-panels-trimmed-leading-year-row": 133,
  "observation-panel-trimmed-leading-year-column": 132,
  "repeated-observation-panels-trimmed-leading-year-column": 131,
  "observation-panel-trimmed-leading-header": 130,
  "repeated-observation-panels-trimmed-leading-header": 129,
  "adjacent-year-like-horizontal-run": 109,
  "adjacent-year-like-vertical-run": 109,
  "leading-formatted-header-row": 108,
  "all-observation-panels-trimmed-leading-label": 125,
  "all-observation-panels": 120,
  "repeated-observation-panels-trimmed-leading-label": 119,
  "observation-panel-trimmed-leading-label": 118,
  "repeated-observation-panels": 115,
  "observation-panel": 110,
  "direct-row-projection-group": 105,
  "top-header-level-group": 105,
  "preceding-panel-anchor-group": 100,
  "merged-header-anchor": 95,
  "format-header-group": 80,
};

/**
 * Build a small menu around observation panels instead of offering arbitrary
 * sheet rectangles. Geometry proposes plausible uses; the model still chooses
 * semantic names, membership, hierarchy, and N/W/NNW/WNW direction.
 */
export function buildRoleAwareSemanticRegionCatalog(
  context: CompactSemanticContext,
  options: {
    maxCandidates?: number;
    formattingFacts?: readonly SemanticCellFormattingFact[];
    cellDataFacts?: readonly SemanticCellDataFact[];
    maxTopHeaderLevels?: number;
  } = {},
): RoleAwareSemanticRegionCatalog {
  const maxCandidates =
    options.maxCandidates ?? DEFAULT_ROLE_AWARE_REGION_LIMIT;
  const valueByAddress = contextValueMap(context);
  const styleByAddress = new Map(
    (options.formattingFacts ?? []).map((fact) => [
      fact.address,
      fact.signature,
    ]),
  );
  const dataTypeByAddress = new Map(
    (options.cellDataFacts ?? []).map((fact) => [fact.address, fact.dataType]),
  );
  const mergeParentByAddress = buildMergeParentByAddress(context);
  const drafts = new Map<string, CandidateDraft>();
  const panels = deriveObservationPanels(context, dataTypeByAddress);
  const projectionPanels = panels.map(trimLeadingLabelColumn);
  const observationAddresses = new Set(
    panels.flatMap((panel) => expandRange(panelRange(panel))),
  );

  const add = ({
    segments,
    kind,
    roleHint,
    signatures = [],
  }: {
    segments: string[];
    kind: string;
    roleHint: GeometricRoleHint;
    signatures?: string[];
  }): void => {
    const normalized = normalizeSegments(segments);
    if (!normalized.length) return;
    const key = normalized.join("|");
    const existing = drafts.get(key);
    if (existing) {
      existing.kinds.add(kind);
      existing.roleHints.add(roleHint);
      for (const signature of signatures)
        if (signature) existing.formatSignatures.add(signature);
      return;
    }
    drafts.set(key, {
      segments: new Set(normalized),
      kinds: new Set([kind]),
      roleHints: new Set([roleHint]),
      formatSignatures: new Set(signatures.filter(Boolean)),
    });
  };

  for (const panel of panels) {
    add({
      segments: [panelRange(panel)],
      kind: "observation-panel",
      roleHint: "observations",
    });
  }
  if (panels.length > 1) {
    add({
      segments: panels.map(panelRange),
      kind: "all-observation-panels",
      roleHint: "observations",
    });
  }
  addRepeatedPanelGroups(panels, add);

  // Numeric-looking coordinates such as years can be absorbed into a numeric
  // observation panel. Preserve every original panel while offering narrowly
  // supported alternatives from either formatting or an adjacent year-like
  // sequence. Meaning remains model-owned.
  const formattedHeaderTrimmedPanels = panels.map((panel) =>
    trimLeadingFormattedHeaderRow(panel, styleByAddress),
  );
  const yearRowTrimmedPanels = panels.map((panel) =>
    trimLeadingAdjacentYearRow(panel, valueByAddress, dataTypeByAddress),
  );
  const headerTrimmedPanels = panels.map((panel, index) =>
    formattedHeaderTrimmedPanels[index].row1 !== panel.row1 ||
    yearRowTrimmedPanels[index].row1 !== panel.row1
      ? { ...panel, row1: panel.row1 + 1 }
      : panel,
  );
  const changedHeaderTrimmedPanels = headerTrimmedPanels.filter(
    (panel, index) => panel.row1 !== panels[index].row1,
  );
  for (const panel of changedHeaderTrimmedPanels) {
    const originalIndex = headerTrimmedPanels.indexOf(panel);
    const formatted =
      formattedHeaderTrimmedPanels[originalIndex].row1 !==
      panels[originalIndex].row1;
    const adjacentYears =
      yearRowTrimmedPanels[originalIndex].row1 !== panels[originalIndex].row1;
    if (formatted) {
      add({
        segments: [panelRange(panel)],
        kind: "observation-panel-trimmed-leading-header",
        roleHint: "observations",
      });
    }
    if (adjacentYears) {
      add({
        segments: [panelRange(panel)],
        kind: "observation-panel-trimmed-leading-year-row",
        roleHint: "observations",
      });
    }
  }
  if (changedHeaderTrimmedPanels.length) {
    const repeatedHeaderTrimmedPanels = repeatedPanelsRelatedToChanges(
      panels,
      headerTrimmedPanels,
    );
    if (
      formattedHeaderTrimmedPanels.some(
        (panel, index) => panel.row1 !== panels[index].row1,
      )
    ) {
      addRepeatedPanelGroups(
        repeatedHeaderTrimmedPanels,
        add,
        "repeated-observation-panels-trimmed-leading-header",
      );
    }
    if (
      yearRowTrimmedPanels.some(
        (panel, index) => panel.row1 !== panels[index].row1,
      )
    ) {
      addRepeatedPanelGroups(
        repeatedHeaderTrimmedPanels,
        add,
        "repeated-observation-panels-trimmed-leading-year-row",
      );
    }
    panels.forEach((panel, index) => {
      const formatted = formattedHeaderTrimmedPanels[index].row1 !== panel.row1;
      const adjacentYears = yearRowTrimmedPanels[index].row1 !== panel.row1;
      if (!formatted && !adjacentYears) return;
      const signatures = formattingSignaturesForRange(
        panel.row1,
        panel.col1,
        panel.row1,
        panel.col2,
        styleByAddress,
      );
      if (formatted) {
        add({
          segments: [range(panel.row1, panel.col1, panel.row1, panel.col2)],
          kind: "leading-formatted-header-row",
          roleHint: "direct-column-candidate",
          signatures,
        });
      }
      if (adjacentYears) {
        add({
          segments: [range(panel.row1, panel.col1, panel.row1, panel.col2)],
          kind: "adjacent-year-like-horizontal-run",
          roleHint: "direct-column-candidate",
          signatures,
        });
      }
    });
  }

  const trimmedPanels = projectionPanels.filter(
    (panel, index) => panel.col1 !== panels[index].col1,
  );
  for (const panel of trimmedPanels) {
    add({
      segments: [panelRange(panel)],
      kind: "observation-panel-trimmed-leading-label",
      roleHint: "observations",
    });
  }
  if (trimmedPanels.length) {
    add({
      segments: projectionPanels.map(panelRange),
      kind: "all-observation-panels-trimmed-leading-label",
      roleHint: "observations",
    });
    addRepeatedPanelGroups(
      projectionPanels,
      add,
      "repeated-observation-panels-trimmed-leading-label",
    );
  }

  const yearColumnTrimmedPanels = panels.map((panel) =>
    trimLeadingAdjacentYearColumn(panel, valueByAddress, dataTypeByAddress),
  );
  const changedYearColumnPanels = yearColumnTrimmedPanels.filter(
    (panel, index) => panel.col1 !== panels[index].col1,
  );
  for (const panel of changedYearColumnPanels) {
    add({
      segments: [panelRange(panel)],
      kind: "observation-panel-trimmed-leading-year-column",
      roleHint: "observations",
    });
  }
  if (changedYearColumnPanels.length) {
    addRepeatedPanelGroups(
      repeatedPanelsRelatedToChanges(panels, yearColumnTrimmedPanels),
      add,
      "repeated-observation-panels-trimmed-leading-year-column",
    );
    panels.forEach((panel, index) => {
      if (yearColumnTrimmedPanels[index].col1 === panel.col1) return;
      add({
        segments: [range(panel.row1, panel.col1, panel.row2, panel.col1)],
        kind: "adjacent-year-like-vertical-run",
        roleHint: "direct-row-candidate",
        signatures: formattingSignaturesForRange(
          panel.row1,
          panel.col1,
          panel.row2,
          panel.col1,
          styleByAddress,
        ),
      });
    });
  }

  const rowProjectionGroups = new Map<string, Set<string>>();
  const topProjectionGroups = new Map<string, Set<string>>();
  const precedingAnchorGroups = new Map<string, Set<string>>();
  const maxTopHeaderLevels = options.maxTopHeaderLevels ?? 16;

  for (const panel of projectionPanels) {
    for (let row = panel.row1; row <= panel.row2; row += 1) {
      const anchor = findNearestRowAnchor({
        row,
        beforeColumn: panel.col1,
        context,
        valueByAddress,
        styleByAddress,
        mergeParentByAddress,
      });
      if (!anchor) continue;
      addGroupedAnchor(
        rowProjectionGroups,
        `${anchor.col}\u0000${anchor.signature}`,
        anchor.address,
      );
    }

    for (let column = panel.col1; column <= panel.col2; column += 1) {
      const levels = findTopAnchors({
        column,
        beforeRow: panel.row1,
        maxLevels: maxTopHeaderLevels,
        context,
        valueByAddress,
        styleByAddress,
        mergeParentByAddress,
        excludedAddresses: observationAddresses,
      });
      levels.forEach((anchor, levelIndex) => {
        addGroupedAnchor(
          topProjectionGroups,
          `${levelIndex + 1}\u0000${anchor.signature}`,
          anchor.address,
        );
      });
    }

    const preceding = findPrecedingPanelAnchor({
      panel,
      context,
      valueByAddress,
      styleByAddress,
      mergeParentByAddress,
    });
    if (preceding) {
      addGroupedAnchor(
        precedingAnchorGroups,
        `${preceding.col}\u0000${preceding.signature}`,
        preceding.address,
      );
    }
  }

  for (const [key, addresses] of rowProjectionGroups) {
    const [, signature = ""] = key.split("\u0000");
    add({
      segments: compressAddresses([...addresses]),
      kind: "direct-row-projection-group",
      roleHint: "direct-row-candidate",
      signatures: [signature],
    });
  }
  for (const [key, addresses] of topProjectionGroups) {
    const [levelText, signature = ""] = key.split("\u0000");
    const level = Number(levelText);
    add({
      segments: compressAddresses([...addresses]),
      kind: "top-header-level-group",
      roleHint:
        level === 1 ? "direct-column-candidate" : "cascading-column-candidate",
      signatures: [signature],
    });
  }
  for (const [key, addresses] of precedingAnchorGroups) {
    const [, signature = ""] = key.split("\u0000");
    add({
      segments: compressAddresses([...addresses]),
      kind: "preceding-panel-anchor-group",
      roleHint: "cascading-row-candidate",
      signatures: [signature],
    });
  }

  for (const merge of context.merges) {
    const value = valueByAddress.get(merge.parent);
    if (!isNonblank(value)) continue;
    add({
      segments: [cellRange(merge.parent)],
      kind: "merged-header-anchor",
      roleHint: "header-format-candidate",
      signatures: [styleByAddress.get(merge.parent) ?? ""],
    });
  }

  // Retain a bounded number of pure-format header groups as fallbacks for
  // structures that are not adjacent to an inferred observation panel.
  const formatCatalog = buildFormatAwareSemanticRegionCatalog(context, {
    maxCandidates: 400,
    formattingFacts: options.formattingFacts,
  });
  for (const candidate of formatCatalog.candidates) {
    if (candidate.valueLikeCount > 0 || candidate.nonblankCount === 0) continue;
    if (!candidate.kinds.some((kind) => kind.startsWith("format-"))) continue;
    add({
      segments: [candidate.range],
      kind: "format-header-group",
      roleHint: "header-format-candidate",
      signatures: candidate.formatSignatures,
    });
  }

  const described = [...drafts.values()]
    .map((draft) => describeCandidate(draft, valueByAddress))
    .sort(compareCandidates);
  const retained = described.slice(0, maxCandidates);

  // Marker-only rows can legitimately terminate a repeated observation panel.
  // They cannot participate in numeric panel inference, and unlike marker rows
  // before a later numeric panel they cannot be discovered as top anchors.
  // Append narrowly corroborated terminal marker runs after the established
  // sorted menu so every existing candidate ID remains stable.
  const existingKeys = new Set(drafts.keys());
  const terminalMarkerCandidates = deriveTerminalRepeatedMarkerDrafts({
    context,
    panels,
    valueByAddress,
    styleByAddress,
    dataTypeByAddress,
    mergeParentByAddress,
  })
    .filter(
      (draft) =>
        !existingKeys.has([...draft.segments].sort(compareRanges).join("|")),
    )
    .map((draft) => describeCandidate(draft, valueByAddress))
    .sort((left, right) => compareRanges(left.segments[0], right.segments[0]));
  const availableMarkerSlots = Math.max(0, maxCandidates - retained.length);
  const retainedWithTerminalMarkers = [
    ...retained,
    ...terminalMarkerCandidates.slice(0, availableMarkerSlots),
  ];

  return {
    version: ROLE_AWARE_REGION_CATALOG_VERSION,
    sheet: context.sheet,
    candidates: retainedWithTerminalMarkers.map((candidate, index) => ({
      id: `region-${String(index + 1).padStart(3, "0")}`,
      ...candidate,
    })),
    omittedCandidateCount: Math.max(
      0,
      described.length +
        terminalMarkerCandidates.length -
        retainedWithTerminalMarkers.length,
    ),
    observationPanelCount: panels.length,
    formatFactCount: options.formattingFacts?.length ?? 0,
    cellDataFactCount: options.cellDataFacts?.length ?? 0,
  };
}

export function buildSemanticCellDataFacts(
  cells: ReadonlyArray<{ address: string; data_type: string }>,
): SemanticCellDataFact[] {
  return cells
    .map((cell) => ({ address: cell.address, dataType: cell.data_type }))
    .sort((left, right) => {
      const a = parseCell(left.address);
      const b = parseCell(right.address);
      return a.row - b.row || a.col - b.col;
    });
}

export function isNumericYearLike(
  value: unknown,
  dataType?: string,
): value is number {
  if (dataType && dataType !== "numeric") return false;
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= MIN_NUMERIC_YEAR_LIKE_VALUE &&
    value <= MAX_NUMERIC_YEAR_LIKE_VALUE
  );
}

export function buildYearLikeCellFacts(
  context: CompactSemanticContext,
  cellDataFacts: readonly SemanticCellDataFact[] = [],
): YearLikeCellFact[] {
  const values = contextValueMap(context);
  const dataTypes = new Map(
    cellDataFacts.map((fact) => [fact.address, fact.dataType]),
  );
  const years = new Map<string, number>();
  for (const [address, value] of values) {
    if (isNumericYearLike(value, dataTypes.get(address))) {
      years.set(address, value);
    }
  }
  return sortAddresses([...years.keys()]).map((address) => {
    const cell = parseCell(address);
    const horizontal = [
      `R${cell.row}C${cell.col - 1}`,
      `R${cell.row}C${cell.col + 1}`,
    ].filter((neighbor) => years.has(neighbor));
    const vertical = [
      `R${cell.row - 1}C${cell.col}`,
      `R${cell.row + 1}C${cell.col}`,
    ].filter((neighbor) => years.has(neighbor));
    return {
      address,
      value: years.get(address)!,
      horizontalYearLikeNeighbors: horizontal,
      verticalYearLikeNeighbors: vertical,
    };
  });
}

export function renderRoleAwareSemanticRegionCatalog(
  catalog: RoleAwareSemanticRegionCatalog,
): string {
  return catalog.candidates
    .map((candidate) => {
      const segments =
        candidate.segments.length <= 6
          ? candidate.segments.join(",")
          : `${candidate.segments.slice(0, 6).join(",")},…(+${candidate.segments.length - 6})`;
      return [
        candidate.id,
        `use=${candidate.roleHints.join(",")}`,
        `shape=${candidate.kinds.join(",")}`,
        `segments=${segments}`,
        `cells=${candidate.selectedCellCount}`,
        `format=${candidate.formatting.join(" + ") || "none-recorded"}`,
        `sample=${candidate.sample.join("; ")}`,
      ].join(" | ");
    })
    .join("\n");
}

/**
 * Compile directly into the existing in-memory CellRoleSketch v0.2 type. This
 * preserves the schema and compiler while avoiding a huge intermediate XML
 * document and its 4,096-node parser limit.
 */
export function compileRoleAwareSemanticTableMap({
  map: input,
  catalog,
  context,
}: {
  map: unknown;
  catalog: RoleAwareSemanticRegionCatalog;
  context: CompactSemanticContext;
}): RoleAwareCompilationResult {
  const parsed = semanticTableMapSchema.safeParse(input);
  if (!parsed.success) {
    return failure(
      "model-form",
      "SEMANTIC_MAP_SCHEMA_INVALID",
      parsed.error.issues
        .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
        .join("; "),
    );
  }
  const map = parsed.data;
  const byId = new Map(
    catalog.candidates.map((candidate) => [candidate.id, candidate]),
  );

  let values: BuiltRole;
  const dimensions: BuiltRole[] = [];
  try {
    values = buildRole(map.table.values.regions, byId, "value-cell");
    for (const [index, dimension] of map.table.dimensions.entries()) {
      dimensions.push(
        buildRole(dimension.memberRegions, byId, `dimension-${index + 1}-cell`),
      );
    }
  } catch (error) {
    return failure(
      "region-resolution",
      errorCode(error, "SEMANTIC_REGION_RESOLUTION_FAILED"),
      errorMessage(error),
    );
  }

  const allAddresses = new Set(values.selector.addresses);
  for (const dimension of dimensions) {
    for (const address of dimension.selector.addresses)
      allAddresses.add(address);
  }
  const sketch: CellRoleSketchV02 = {
    version: "0.2",
    sheet: context.sheet,
    uncertainties: [],
    tables: [
      {
        id: "table-1",
        name: map.table.name,
        evidence: "Selected by semantic table map.",
        selectorBounds: boundingRange([...allAddresses]),
        values: {
          id: "values-1",
          name: map.table.values.name,
          evidence: "Selected semantic observation regions.",
          ...values.selector,
        },
        dimensions: map.table.dimensions.map((dimension, index) => ({
          id: `dimension-${index + 1}`,
          name: dimension.name,
          evidence: "Selected semantic member regions.",
          ...dimensions[index].selector,
        })),
        relationships: map.table.dimensions.map((dimension, index) => ({
          id: `relationship-${index + 1}`,
          dimensionId: `dimension-${index + 1}`,
          kind: DIRECTION_TO_RELATIONSHIP[dimension.direction],
          evidence: "Direction selected by the semantic model.",
        })),
      },
    ],
  };

  const geometryOptions: CellRoleGeometryOptions = {
    sheet: { cells: contextCells(context) },
    collectAssociations: true,
  };
  const geometry = validateCellRoleSketchGeometry(sketch, geometryOptions);
  const errors = geometry.diagnostics.filter(
    (entry) => entry.severity === "error",
  );
  if (errors.length) {
    return {
      ok: false,
      stage: "geometry",
      code: geometryFailureCode(errors[0]),
      message: errors[0].message,
      diagnostics: geometry.diagnostics,
    };
  }

  const compiled = compileCellRoleSketch(sketch, geometryOptions);
  if (!compiled.ok) return compilerFailure(compiled.error);

  return {
    ok: true,
    map,
    sketch,
    canonicalSketchJson: `${JSON.stringify(sketch, null, 2)}\n`,
    recipe: compiled.recipe,
    canonicalRecipeJson: compiled.canonicalJson,
    compilerVersion: compiled.compilerVersion,
    normalizations: {
      values: values.normalization,
      dimensions: dimensions.map((entry) => entry.normalization),
    },
    captionHints: map.table.dimensions
      .filter((dimension) => dimension.captionHints?.length)
      .map((dimension) => ({
        dimension: dimension.name,
        hints: dimension.captionHints ?? [],
      })),
    warnings: geometry.diagnostics
      .filter((entry) => entry.severity === "warning")
      .map((entry) => `${entry.code}: ${entry.message}`),
  };
}

export function inspectSemanticMapCompleteness({
  map,
  catalog,
}: {
  map: SemanticTableMapV1;
  catalog: RoleAwareSemanticRegionCatalog;
}): SemanticCompletenessDiagnostic[] {
  const byId = new Map(
    catalog.candidates.map((candidate) => [candidate.id, candidate]),
  );
  const selectedAddresses = new Set<string>();
  const accountedCandidateIds = new Set<string>();
  for (const dimension of map.table.dimensions) {
    for (const id of [
      ...dimension.memberRegions,
      ...(dimension.captionHints ?? []),
    ]) {
      accountedCandidateIds.add(id);
      const candidate = byId.get(id);
      if (!candidate) continue;
      for (const address of candidateAddresses(candidate))
        selectedAddresses.add(address);
    }
  }

  const diagnostics: SemanticCompletenessDiagnostic[] = [];
  for (const candidate of catalog.candidates) {
    if (accountedCandidateIds.has(candidate.id)) continue;
    const roleHint = candidate.roleHints.find(
      (
        hint,
      ): hint is
        | "direct-row-candidate"
        | "direct-column-candidate"
        | "cascading-row-candidate"
        | "cascading-column-candidate" =>
        hint === "direct-row-candidate" ||
        hint === "direct-column-candidate" ||
        hint === "cascading-row-candidate" ||
        hint === "cascading-column-candidate",
    );
    if (!roleHint) continue;
    const cascading =
      roleHint === "cascading-row-candidate" ||
      roleHint === "cascading-column-candidate";
    if (cascading) {
      const distinctSampleValues = new Set(
        candidate.sample.map((sample) => sample.slice(sample.indexOf("=") + 1)),
      ).size;
      const repeatedCategoryBand =
        roleHint === "cascading-row-candidate" &&
        candidate.kinds.includes("preceding-panel-anchor-group") &&
        candidate.selectedCellCount >= 2 &&
        distinctSampleValues >= 2;
      if (!repeatedCategoryBand) continue;
    }
    const addresses = candidateAddresses(candidate);
    const missing = addresses.filter(
      (address) => !selectedAddresses.has(address),
    );
    if (!missing.length) continue;
    const code = cascading
      ? "UNASSIGNED_CASCADING_HEADER_GROUP"
      : "UNASSIGNED_DIRECT_HEADER_GROUP";
    diagnostics.push({
      code,
      candidateId: candidate.id,
      roleHint,
      selectedCellCount: addresses.length,
      missingCellCount: missing.length,
      sample: candidate.sample,
      message: `${candidate.id} is a ${roleHint} structural group adjacent to selected observation panels; ${missing.length} of ${addresses.length} cells are not assigned to any dimension or caption hint. This is a completeness fact, not an instruction to choose a semantic meaning.`,
    });
  }
  return diagnostics.slice(0, 32);
}

export function correctionCandidateSubset({
  catalog,
  map,
  geometryDiagnostics = [],
  completenessDiagnostics = [],
  maxCandidates = 80,
}: {
  catalog: RoleAwareSemanticRegionCatalog;
  map: SemanticTableMapV1;
  geometryDiagnostics?: GeometryDiagnostic[];
  completenessDiagnostics?: SemanticCompletenessDiagnostic[];
  maxCandidates?: number;
}): RoleAwareSemanticRegionCatalog {
  const requested = new Set<string>([
    ...map.table.values.regions,
    ...map.table.dimensions.flatMap((dimension) => [
      ...dimension.memberRegions,
      ...(dimension.captionHints ?? []),
    ]),
    ...completenessDiagnostics.map((diagnostic) => diagnostic.candidateId),
  ]);
  const diagnosticAddresses = new Set(
    geometryDiagnostics.flatMap((diagnostic) =>
      [
        diagnostic.address,
        diagnostic.headerAddress,
        diagnostic.valueAddress,
      ].filter((value): value is string => Boolean(value)),
    ),
  );
  for (const candidate of catalog.candidates) {
    if (
      candidateAddresses(candidate).some((address) =>
        diagnosticAddresses.has(address),
      )
    ) {
      requested.add(candidate.id);
    }
  }

  const selected = catalog.candidates.filter((candidate) =>
    requested.has(candidate.id),
  );
  for (const candidate of catalog.candidates) {
    if (selected.length >= maxCandidates) break;
    if (selected.some((entry) => entry.id === candidate.id)) continue;
    if (
      candidate.roleHints.some((hint) => hint !== "header-format-candidate")
    ) {
      selected.push(candidate);
    }
  }
  return {
    ...catalog,
    candidates: selected.slice(0, maxCandidates),
    omittedCandidateCount:
      catalog.omittedCandidateCount +
      Math.max(
        0,
        catalog.candidates.length - selected.slice(0, maxCandidates).length,
      ),
  };
}

export function formatRoleAwareCorrectionDiagnostics({
  failure: compilationFailure,
  completenessDiagnostics,
}: {
  failure?: RoleAwareCompilationFailure;
  completenessDiagnostics?: SemanticCompletenessDiagnostic[];
}): string {
  const lines: string[] = [];
  if (compilationFailure) {
    lines.push(`${compilationFailure.code}: ${compilationFailure.message}`);
    for (const diagnostic of compilationFailure.diagnostics.slice(0, 20)) {
      lines.push(
        [
          diagnostic.code,
          diagnostic.message,
          diagnostic.address ? `address=${diagnostic.address}` : "",
          diagnostic.relationshipKind
            ? `chosenRelationship=${diagnostic.relationshipKind}`
            : "",
        ]
          .filter(Boolean)
          .join(" | "),
      );
    }
  }
  for (const diagnostic of completenessDiagnostics ?? []) {
    lines.push(`${diagnostic.code}: ${diagnostic.message}`);
  }
  return lines.join("\n");
}

type BuiltRole = {
  selector: SketchRoleSelectorV02;
  normalization: SemanticMapRoleNormalization;
};

function buildRole(
  regionIds: string[],
  byId: Map<string, RoleAwareSemanticRegionCandidate>,
  idPrefix: string,
): BuiltRole {
  const selectedIds = [...new Set(regionIds)];
  const addresses = new Set<string>();
  for (const id of selectedIds) {
    const candidate = byId.get(id);
    if (!candidate)
      throw codedError(
        "UNKNOWN_SEMANTIC_REGION",
        `Unknown semantic region ${id}.`,
      );
    for (const address of candidateAddresses(candidate)) {
      addresses.add(address);
      if (addresses.size > MAX_ROLE_AWARE_SELECTED_CELLS) {
        throw codedError(
          "SEMANTIC_REGION_EXPANSION_LIMIT",
          `Role expands beyond ${MAX_ROLE_AWARE_SELECTED_CELLS} cells.`,
        );
      }
    }
  }
  const sorted = sortAddresses([...addresses]);
  if (!sorted.length)
    throw codedError("EMPTY_SEMANTIC_REGION", "Role selects no cells.");
  const bounding = boundingRange(sorted);
  const rectangular = rectangleCellCount(bounding) === sorted.length;
  const sources = rectangular
    ? [
        {
          id: `${idPrefix}-1`,
          selector: { kind: "range" as const, value: bounding },
          evidence: "Deterministically grouped semantic region.",
        },
      ]
    : sorted.map((address, index) => ({
        id: `${idPrefix}-${index + 1}`,
        selector: { kind: "address" as const, value: address },
        evidence: "Deterministically expanded semantic region.",
      }));
  return {
    selector: { sources, addresses: sorted },
    normalization: {
      regionIds: selectedIds,
      selectedCellCount: sorted.length,
      representation: rectangular ? "range" : "addresses",
    },
  };
}

function deriveObservationPanels(
  context: CompactSemanticContext,
  dataTypeByAddress: ReadonlyMap<string, string>,
): Panel[] {
  const runsByRow = context.grid.rows.map((row, rowIndex) => {
    const primary = row.values.map((value, columnIndex) =>
      isObservedDataCell(
        value,
        dataTypeByAddress.get(`R${rowIndex + 1}C${columnIndex + 1}`),
      ),
    );
    const rowHasPrimary = primary.some(Boolean);
    return booleanRuns(
      row.values.map(
        (value, columnIndex) =>
          primary[columnIndex] ||
          (rowHasPrimary && isReportedMissingValueMarker(value)),
      ),
    );
  });
  const panels: Panel[] = [];
  const open = new Map<string, Panel>();
  for (let row = 1; row <= runsByRow.length + 1; row += 1) {
    const runs = row <= runsByRow.length ? runsByRow[row - 1] : [];
    const keys = new Set(runs.map(([col1, col2]) => `${col1}:${col2}`));
    for (const [key, panel] of [...open]) {
      if (keys.has(key)) continue;
      panels.push(panel);
      open.delete(key);
    }
    for (const [col1, col2] of runs) {
      const key = `${col1}:${col2}`;
      const existing = open.get(key);
      if (existing) existing.row2 = row;
      else open.set(key, { row1: row, col1, row2: row, col2 });
    }
  }
  return panels
    .filter((panel) => rectangleCellCount(panelRange(panel)) > 0)
    .sort(comparePanels);
}

function deriveTerminalRepeatedMarkerDrafts({
  context,
  panels,
  valueByAddress,
  styleByAddress,
  dataTypeByAddress,
  mergeParentByAddress,
}: {
  context: CompactSemanticContext;
  panels: readonly Panel[];
  valueByAddress: ReadonlyMap<string, unknown>;
  styleByAddress: ReadonlyMap<string, string>;
  dataTypeByAddress: ReadonlyMap<string, string>;
  mergeParentByAddress: ReadonlyMap<string, string>;
}): CandidateDraft[] {
  const drafts: CandidateDraft[] = [];
  const byColumnSpan = groupBy(
    [...panels],
    (panel) => `${panel.col1}:${panel.col2}`,
  );
  for (const sameSpan of byColumnSpan.values()) {
    if (sameSpan.length < 2) continue;
    const ordered = [...sameSpan].sort(comparePanels);
    const terminalPanel = ordered.reduce((latest, panel) =>
      panel.row2 > latest.row2 ? panel : latest,
    );
    const startRow = terminalPanel.row2 + 1;
    if (startRow > context.dimensions.rows) continue;

    const isEligibleMarkerRow = (row: number): boolean => {
      const label = valueByAddress.get(`R${row}C${terminalPanel.col1 - 1}`);
      if (
        terminalPanel.col1 <= 1 ||
        typeof label !== "string" ||
        !label.trim() ||
        isExactRetainedMarker(label) ||
        isObservationLike(label)
      ) {
        return false;
      }
      for (let col = terminalPanel.col1; col <= terminalPanel.col2; col += 1) {
        const address = `R${row}C${col}`;
        const dataType = dataTypeByAddress.get(address);
        if (
          !isExactRetainedMarker(valueByAddress.get(address)) ||
          (dataType !== undefined && dataType !== "string") ||
          mergeParentByAddress.has(address) ||
          !styleByAddress.get(address)
        ) {
          return false;
        }
      }
      return true;
    };

    const markerRunAfterPanel = (panel: Panel): number[] => {
      const rows: number[] = [];
      for (
        let row = panel.row2 + 1;
        row <= context.dimensions.rows && isEligibleMarkerRow(row);
        row += 1
      ) {
        rows.push(row);
      }
      return rows;
    };
    const terminalRows = markerRunAfterPanel(terminalPanel);
    if (!terminalRows.length) continue;

    const styleVector = (row: number): string =>
      Array.from(
        { length: terminalPanel.col2 - terminalPanel.col1 + 1 },
        (_, offset) =>
          styleByAddress.get(`R${row}C${terminalPanel.col1 + offset}`) ?? "",
      ).join("\u0000");
    const isCorroborated = ordered.some((panel) => {
      if (panel === terminalPanel) return false;
      const earlierRows = markerRunAfterPanel(panel);
      return (
        earlierRows.length === terminalRows.length &&
        earlierRows.every(
          (row, index) => styleVector(row) === styleVector(terminalRows[index]),
        )
      );
    });
    if (!isCorroborated) continue;

    const signatures = new Set<string>();
    for (const row of terminalRows) {
      for (let col = terminalPanel.col1; col <= terminalPanel.col2; col += 1) {
        const signature = styleByAddress.get(`R${row}C${col}`);
        if (signature) signatures.add(signature);
      }
    }
    drafts.push({
      segments: new Set([
        range(
          terminalRows[0],
          terminalPanel.col1,
          terminalRows[terminalRows.length - 1],
          terminalPanel.col2,
        ),
      ]),
      kinds: new Set(["terminal-repeated-marker-run"]),
      roleHints: new Set(["observations"]),
      formatSignatures: signatures,
    });
  }
  return drafts;
}

function addRepeatedPanelGroups(
  panels: Panel[],
  add: (input: {
    segments: string[];
    kind: string;
    roleHint: GeometricRoleHint;
    signatures?: string[];
  }) => void,
  kind = "repeated-observation-panels",
): void {
  const vertical = groupBy(panels, (panel) => `${panel.col1}:${panel.col2}`);
  const horizontal = groupBy(panels, (panel) => `${panel.row1}:${panel.row2}`);
  for (const group of [...vertical.values(), ...horizontal.values()]) {
    if (group.length < 2) continue;
    add({
      segments: group.map(panelRange),
      kind,
      roleHint: "observations",
    });
  }
}

function repeatedPanelsRelatedToChanges(
  original: Panel[],
  transformed: Panel[],
): Panel[] {
  const changedColumnSpans = new Set<string>();
  const changedRowSpans = new Set<string>();
  transformed.forEach((panel, index) => {
    const before = original[index];
    if (
      panel.row1 === before.row1 &&
      panel.col1 === before.col1 &&
      panel.row2 === before.row2 &&
      panel.col2 === before.col2
    ) {
      return;
    }
    changedColumnSpans.add(`${panel.col1}:${panel.col2}`);
    changedRowSpans.add(`${panel.row1}:${panel.row2}`);
  });
  return transformed.filter(
    (panel) =>
      changedColumnSpans.has(`${panel.col1}:${panel.col2}`) ||
      changedRowSpans.has(`${panel.row1}:${panel.row2}`),
  );
}

function findNearestRowAnchor({
  row,
  beforeColumn,
  context,
  valueByAddress,
  styleByAddress,
  mergeParentByAddress,
}: {
  row: number;
  beforeColumn: number;
  context: CompactSemanticContext;
  valueByAddress: ReadonlyMap<string, unknown>;
  styleByAddress: ReadonlyMap<string, string>;
  mergeParentByAddress: ReadonlyMap<string, string>;
}): Anchor | null {
  for (let col = beforeColumn - 1; col >= 1; col -= 1) {
    const anchor = anchorAt({
      row,
      col,
      context,
      valueByAddress,
      styleByAddress,
      mergeParentByAddress,
    });
    if (anchor) return anchor;
  }
  return null;
}

function findTopAnchors({
  column,
  beforeRow,
  maxLevels,
  context,
  valueByAddress,
  styleByAddress,
  mergeParentByAddress,
  excludedAddresses,
}: {
  column: number;
  beforeRow: number;
  maxLevels: number;
  context: CompactSemanticContext;
  valueByAddress: ReadonlyMap<string, unknown>;
  styleByAddress: ReadonlyMap<string, string>;
  mergeParentByAddress: ReadonlyMap<string, string>;
  excludedAddresses: ReadonlySet<string>;
}): Anchor[] {
  const anchors: Anchor[] = [];
  const seen = new Set<string>();
  let blankRowsAfterFinding = 0;
  for (
    let row = beforeRow - 1;
    row >= 1 && anchors.length < maxLevels;
    row -= 1
  ) {
    const anchor = anchorAt({
      row,
      col: column,
      context,
      valueByAddress,
      styleByAddress,
      mergeParentByAddress,
      excludedAddresses,
    });
    if (!anchor) {
      if (anchors.length) blankRowsAfterFinding += 1;
      if (blankRowsAfterFinding >= 2) break;
      continue;
    }
    blankRowsAfterFinding = 0;
    if (seen.has(anchor.address)) continue;
    seen.add(anchor.address);
    anchors.push(anchor);
  }
  return anchors;
}

function findPrecedingPanelAnchor({
  panel,
  context,
  valueByAddress,
  styleByAddress,
  mergeParentByAddress,
}: {
  panel: Panel;
  context: CompactSemanticContext;
  valueByAddress: ReadonlyMap<string, unknown>;
  styleByAddress: ReadonlyMap<string, string>;
  mergeParentByAddress: ReadonlyMap<string, string>;
}): Anchor | null {
  for (let row = panel.row1 - 1; row >= Math.max(1, panel.row1 - 3); row -= 1) {
    for (let col = Math.max(1, panel.col1 - 1); col >= 1; col -= 1) {
      const anchor = anchorAt({
        row,
        col,
        context,
        valueByAddress,
        styleByAddress,
        mergeParentByAddress,
      });
      if (anchor) return anchor;
    }
  }
  return null;
}

function anchorAt({
  row,
  col,
  context,
  valueByAddress,
  styleByAddress,
  mergeParentByAddress,
  excludedAddresses,
}: {
  row: number;
  col: number;
  context: CompactSemanticContext;
  valueByAddress: ReadonlyMap<string, unknown>;
  styleByAddress: ReadonlyMap<string, string>;
  mergeParentByAddress: ReadonlyMap<string, string>;
  excludedAddresses?: ReadonlySet<string>;
}): Anchor | null {
  if (
    row < 1 ||
    col < 1 ||
    row > context.dimensions.rows ||
    col > context.dimensions.columns
  ) {
    return null;
  }
  const raw = `R${row}C${col}`;
  const address = mergeParentByAddress.get(raw) ?? raw;
  if (excludedAddresses?.has(raw) || excludedAddresses?.has(address))
    return null;
  const value = valueByAddress.get(address);
  if (!isNonblank(value)) return null;
  const parsed = parseCell(address);
  return {
    address,
    row: parsed.row,
    col: parsed.col,
    signature: styleByAddress.get(address) ?? "",
  };
}

function buildMergeParentByAddress(
  context: CompactSemanticContext,
): ReadonlyMap<string, string> {
  const result = new Map<string, string>();
  for (const merge of context.merges) {
    for (const address of expandRange(merge.range))
      result.set(address, merge.parent);
  }
  return result;
}

function describeCandidate(
  draft: CandidateDraft,
  valueByAddress: ReadonlyMap<string, unknown>,
): Omit<RoleAwareSemanticRegionCandidate, "id"> {
  const segments = [...draft.segments].sort(compareRanges);
  const addresses = uniqueAddresses(segments);
  let nonblankCount = 0;
  let valueLikeCount = 0;
  const sample: string[] = [];
  for (const address of addresses) {
    const value = valueByAddress.get(address);
    if (!isNonblank(value)) continue;
    nonblankCount += 1;
    if (isObservationLike(value)) valueLikeCount += 1;
    if (sample.length < 5) sample.push(`${address}=${JSON.stringify(value)}`);
  }
  const formatSignatures = [...draft.formatSignatures].filter(Boolean).sort();
  return {
    segments,
    kinds: [...draft.kinds].sort((a, b) => kindPriority(b) - kindPriority(a)),
    roleHints: [...draft.roleHints].sort(),
    formatSignatures,
    formatting: formatSignatures.map(formatSignatureForPrompt),
    selectedCellCount: addresses.length,
    nonblankCount,
    valueLikeCount,
    sample,
  };
}

function compareCandidates(
  left: Omit<RoleAwareSemanticRegionCandidate, "id">,
  right: Omit<RoleAwareSemanticRegionCandidate, "id">,
): number {
  const leftPriority = Math.max(...left.kinds.map(kindPriority));
  const rightPriority = Math.max(...right.kinds.map(kindPriority));
  return (
    rightPriority - leftPriority ||
    right.selectedCellCount - left.selectedCellCount ||
    compareRanges(left.segments[0], right.segments[0])
  );
}

function candidateAddresses(
  candidate: RoleAwareSemanticRegionCandidate,
): string[] {
  return uniqueAddresses(candidate.segments);
}

function normalizeSegments(segments: string[]): string[] {
  return [
    ...new Set(segments.map((segment) => formatParsedRange(segment))),
  ].sort(compareRanges);
}

function compressAddresses(addresses: string[]): string[] {
  const sorted = sortAddresses([...new Set(addresses)]);
  const rowRuns: Array<{
    row1: number;
    row2: number;
    col1: number;
    col2: number;
  }> = [];
  const byRow = groupBy(sorted.map(parseCell), (cell) => String(cell.row));
  for (const [rowText, cells] of byRow) {
    const row = Number(rowText);
    const columns = cells.map((cell) => cell.col).sort((a, b) => a - b);
    let start = columns[0];
    let previous = columns[0];
    for (const column of columns.slice(1)) {
      if (column === previous + 1) {
        previous = column;
        continue;
      }
      rowRuns.push({ row1: row, row2: row, col1: start, col2: previous });
      start = column;
      previous = column;
    }
    rowRuns.push({ row1: row, row2: row, col1: start, col2: previous });
  }
  const vertical: typeof rowRuns = [];
  for (const run of rowRuns.sort(
    (a, b) => a.col1 - b.col1 || a.col2 - b.col2 || a.row1 - b.row1,
  )) {
    const previous = vertical.at(-1);
    if (
      previous &&
      previous.col1 === run.col1 &&
      previous.col2 === run.col2 &&
      previous.row2 + 1 === run.row1
    ) {
      previous.row2 = run.row2;
    } else vertical.push({ ...run });
  }
  return vertical.map((entry) =>
    range(entry.row1, entry.col1, entry.row2, entry.col2),
  );
}

function uniqueAddresses(segments: string[]): string[] {
  const addresses = new Set<string>();
  for (const segment of segments)
    for (const address of expandRange(segment)) addresses.add(address);
  return sortAddresses([...addresses]);
}

function contextValueMap(
  context: CompactSemanticContext,
): ReadonlyMap<string, unknown> {
  const result = new Map<string, unknown>();
  context.grid.rows.forEach((row, rowIndex) =>
    row.values.forEach((value, columnIndex) =>
      result.set(`R${rowIndex + 1}C${columnIndex + 1}`, value),
    ),
  );
  return result;
}

function contextCells(
  context: CompactSemanticContext,
): Array<{ address: string; data_type: string; value: unknown }> {
  return context.grid.rows.flatMap((row, rowIndex) =>
    row.values.map((value, columnIndex) => ({
      address: `R${rowIndex + 1}C${columnIndex + 1}`,
      data_type: dataType(value),
      value,
    })),
  );
}

function dataType(value: unknown): string {
  if (value === null || value === undefined || value === "") return "blank";
  if (typeof value === "number") return "numeric";
  if (typeof value === "boolean") return "boolean";
  return "string";
}

function addGroupedAnchor(
  groups: Map<string, Set<string>>,
  key: string,
  address: string,
): void {
  const entries = groups.get(key) ?? new Set<string>();
  entries.add(address);
  groups.set(key, entries);
}

function booleanRuns(values: boolean[]): Array<[number, number]> {
  const runs: Array<[number, number]> = [];
  let start: number | null = null;
  for (let index = 0; index <= values.length; index += 1) {
    if (values[index] && start === null) start = index + 1;
    if ((!values[index] || index === values.length) && start !== null) {
      runs.push([start, index]);
      start = null;
    }
  }
  return runs;
}

function trimLeadingLabelColumn(panel: Panel): Panel {
  return panel.col1 === 1 && panel.col2 > 1
    ? { ...panel, col1: panel.col1 + 1 }
    : panel;
}

function trimLeadingAdjacentYearRow(
  panel: Panel,
  valueByAddress: ReadonlyMap<string, unknown>,
  dataTypeByAddress: ReadonlyMap<string, string>,
): Panel {
  if (panel.row1 >= panel.row2 || panel.col2 - panel.col1 + 1 < 2) return panel;
  const leading = Array.from(
    { length: panel.col2 - panel.col1 + 1 },
    (_, offset) => {
      const address = `R${panel.row1}C${panel.col1 + offset}`;
      const value = valueByAddress.get(address);
      return isNumericYearLike(value, dataTypeByAddress.get(address))
        ? value
        : null;
    },
  );
  if (leading.some((value) => value === null) || new Set(leading).size < 2) {
    return panel;
  }
  const nextRowAllYearLike = Array.from(
    { length: panel.col2 - panel.col1 + 1 },
    (_, offset) => {
      const address = `R${panel.row1 + 1}C${panel.col1 + offset}`;
      return isNumericYearLike(
        valueByAddress.get(address),
        dataTypeByAddress.get(address),
      );
    },
  ).every(Boolean);
  return nextRowAllYearLike ? panel : { ...panel, row1: panel.row1 + 1 };
}

function trimLeadingAdjacentYearColumn(
  panel: Panel,
  valueByAddress: ReadonlyMap<string, unknown>,
  dataTypeByAddress: ReadonlyMap<string, string>,
): Panel {
  if (panel.col1 >= panel.col2 || panel.row2 - panel.row1 + 1 < 2) return panel;
  const leading = Array.from(
    { length: panel.row2 - panel.row1 + 1 },
    (_, offset) => {
      const address = `R${panel.row1 + offset}C${panel.col1}`;
      const value = valueByAddress.get(address);
      return isNumericYearLike(value, dataTypeByAddress.get(address))
        ? value
        : null;
    },
  );
  if (leading.some((value) => value === null) || new Set(leading).size < 2) {
    return panel;
  }
  const nextColumnAllYearLike = Array.from(
    { length: panel.row2 - panel.row1 + 1 },
    (_, offset) => {
      const address = `R${panel.row1 + offset}C${panel.col1 + 1}`;
      return isNumericYearLike(
        valueByAddress.get(address),
        dataTypeByAddress.get(address),
      );
    },
  ).every(Boolean);
  return nextColumnAllYearLike ? panel : { ...panel, col1: panel.col1 + 1 };
}

function trimLeadingFormattedHeaderRow(
  panel: Panel,
  styleByAddress: ReadonlyMap<string, string>,
): Panel {
  if (panel.row1 >= panel.row2) return panel;
  const leadingSignatures = Array.from(
    { length: panel.col2 - panel.col1 + 1 },
    (_, offset) =>
      styleByAddress.get(`R${panel.row1}C${panel.col1 + offset}`) ?? "",
  );
  const nextSignatures = Array.from(
    { length: panel.col2 - panel.col1 + 1 },
    (_, offset) =>
      styleByAddress.get(`R${panel.row1 + 1}C${panel.col1 + offset}`) ?? "",
  );
  const allLeadingBold = leadingSignatures.every(hasBoldFormatting);
  const noNextBold = nextSignatures.every(
    (signature) => !hasBoldFormatting(signature),
  );
  return allLeadingBold && noNextBold
    ? { ...panel, row1: panel.row1 + 1 }
    : panel;
}

function hasBoldFormatting(signature: string): boolean {
  return signature.split("|").includes("b");
}

function formattingSignaturesForRange(
  row1: number,
  col1: number,
  row2: number,
  col2: number,
  styleByAddress: ReadonlyMap<string, string>,
): string[] {
  const signatures = new Set<string>();
  for (let row = row1; row <= row2; row += 1) {
    for (let col = col1; col <= col2; col += 1) {
      const signature = styleByAddress.get(`R${row}C${col}`);
      if (signature) signatures.add(signature);
    }
  }
  return [...signatures];
}

function panelRange(panel: Panel): string {
  return range(panel.row1, panel.col1, panel.row2, panel.col2);
}

function cellRange(address: string): string {
  const cell = parseCell(address);
  return range(cell.row, cell.col, cell.row, cell.col);
}

function range(row1: number, col1: number, row2: number, col2: number): string {
  return formatRange({
    start: { row: row1, col: col1 },
    end: { row: row2, col: col2 },
  });
}

function formatParsedRange(input: string): string {
  const parsed = parseRange(input);
  return formatRange(parsed);
}

function compareRanges(left: string, right: string): number {
  const a = parseRange(left);
  const b = parseRange(right);
  return (
    a.start.row - b.start.row ||
    a.start.col - b.start.col ||
    a.end.row - b.end.row ||
    a.end.col - b.end.col
  );
}

function comparePanels(left: Panel, right: Panel): number {
  return (
    left.row1 - right.row1 ||
    left.col1 - right.col1 ||
    left.row2 - right.row2 ||
    left.col2 - right.col2
  );
}

function sortAddresses(addresses: string[]): string[] {
  return addresses.sort((left, right) => {
    const a = parseCell(left);
    const b = parseCell(right);
    return a.row - b.row || a.col - b.col;
  });
}

function boundingRange(addresses: string[]): string {
  if (!addresses.length)
    throw codedError("EMPTY_SEMANTIC_REGION", "No selected cells.");
  const cells = addresses.map(parseCell);
  return range(
    Math.min(...cells.map((cell) => cell.row)),
    Math.min(...cells.map((cell) => cell.col)),
    Math.max(...cells.map((cell) => cell.row)),
    Math.max(...cells.map((cell) => cell.col)),
  );
}

function rectangleCellCount(input: string): number {
  const parsed = parseRange(input);
  return (
    (parsed.end.row - parsed.start.row + 1) *
    (parsed.end.col - parsed.start.col + 1)
  );
}

function kindPriority(kind: string): number {
  return KIND_PRIORITY[kind] ?? 0;
}

function groupBy<T>(items: T[], key: (item: T) => string): Map<string, T[]> {
  const result = new Map<string, T[]>();
  for (const item of items) {
    const value = key(item);
    const entries = result.get(value) ?? [];
    entries.push(item);
    result.set(value, entries);
  }
  return result;
}

function isNonblank(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "";
}

function isObservedDataCell(
  value: unknown,
  dataType: string | undefined,
): boolean {
  if (dataType === "numeric" || dataType === "boolean") return true;
  return typeof value === "number" || typeof value === "boolean";
}

function isExactRetainedMarker(value: unknown): boolean {
  return typeof value === "string" && /^(?:\.\.|na|np)$/i.test(value.trim());
}

function isReportedMissingValueMarker(value: unknown): boolean {
  if (typeof value !== "string") return false;
  return /^(?:[-–—.]+|n\.?p\.?|n\.?a\.?|\.\.)$/i.test(value.trim());
}

function isObservationLike(value: unknown): boolean {
  if (typeof value === "number" || typeof value === "boolean") return true;
  if (typeof value !== "string") return false;
  const text = value.trim();
  if (!text) return false;
  return /^(?:[-–—.]+|n\.?p\.?|n\.?a\.?|\.\.|[($+−-]?\d[\d,]*(?:\.\d+)?(?:%|\))?(?:[a-z*#]+)?)$/i.test(
    text,
  );
}

function geometryFailureCode(diagnostic: GeometryDiagnostic): string {
  if (diagnostic.code === "ROLE_OVERLAP") return "ROLE_CELL_OVERLAP";
  return diagnostic.code;
}

function compilerFailure(
  error: CellRoleCompileError,
): RoleAwareCompilationFailure {
  return {
    ok: false,
    stage: "compiler",
    code: error.code,
    message: `${error.path}: ${error.message}`,
    diagnostics: [],
  };
}

function failure(
  stage: RoleAwareCompilationFailure["stage"],
  code: string,
  message: string,
): RoleAwareCompilationFailure {
  return { ok: false, stage, code, message, diagnostics: [] };
}

function codedError(code: string, message: string): Error & { code: string } {
  return Object.assign(new Error(message), { code });
}

function errorCode(error: unknown, fallback: string): string {
  if (
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string"
  ) {
    return error.code;
  }
  return fallback;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
