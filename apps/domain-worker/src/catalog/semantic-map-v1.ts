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
  MAX_CELL_ROLE_SKETCH_V02_NODES,
  MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS,
  parseCellRoleSketchV02,
  type CellRoleSketchV02,
} from "./cell-role-sketch-v02.js";
import {
  validateCellRoleSketchGeometry,
  type CellRoleGeometryOptions,
  type CellRoleGeometryResult,
  type GeometryDiagnostic,
} from "./geometry-v02.js";
import type { RelationshipKind } from "./types.js";

export const SEMANTIC_TABLE_MAP_VERSION = "semantic-table-map-v1" as const;
export const DEFAULT_SEMANTIC_REGION_LIMIT = 400;

export const semanticDirectionSchema = z.enum(["N", "W", "NNW", "WNW"]);
export type SemanticDirection = z.infer<typeof semanticDirectionSchema>;

const regionIdList = z.array(z.string().min(1).max(80)).min(1).max(256);
const semanticDimensionSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    memberRegions: regionIdList,
    direction: semanticDirectionSchema,
    /** Reasoning-only references. They are never resolved or compiled. */
    captionHints: z.array(z.string().min(1).max(80)).max(32).optional(),
  })
  .strict();

export const semanticTableMapSchema = z
  .object({
    version: z.literal(SEMANTIC_TABLE_MAP_VERSION),
    table: z
      .object({
        name: z.string().trim().min(1).max(200),
        values: z
          .object({
            name: z.string().trim().min(1).max(200),
            regions: regionIdList,
          })
          .strict(),
        dimensions: z.array(semanticDimensionSchema).min(1).max(64),
      })
      .strict(),
  })
  .strict();

export type SemanticTableMapV1 = z.infer<typeof semanticTableMapSchema>;

export type SemanticRegionCandidate = {
  id: string;
  range: string;
  kinds: string[];
  nonblankCount: number;
  valueLikeCount: number;
  sample: string[];
};

export type SemanticRegionCatalog = {
  version: "semantic-region-catalog-v1";
  sheet: string;
  candidates: SemanticRegionCandidate[];
  omittedCandidateCount: number;
};

export type SemanticMapRoleNormalization = {
  regionIds: string[];
  selectedCellCount: number;
  representation: "range" | "addresses";
};

export type SemanticMapCompilationSuccess = {
  ok: true;
  map: SemanticTableMapV1;
  sketch: CellRoleSketchV02;
  canonicalXml: string;
  recipe: RecipeV01;
  canonicalRecipeJson: string;
  compilerVersion: string;
  normalizations: {
    values: SemanticMapRoleNormalization;
    dimensions: SemanticMapRoleNormalization[];
  };
  /** Retained only for experiment traces; absent from sketch and recipe. */
  captionHints: Array<{ dimension: string; hints: string[] }>;
  warnings: string[];
};

export type SemanticMapCompilationFailure = {
  ok: false;
  stage: "model-form" | "region-resolution" | "geometry" | "compiler";
  code: string;
  message: string;
  diagnostics: GeometryDiagnostic[];
};

export type SemanticMapCompilationResult =
  | SemanticMapCompilationSuccess
  | SemanticMapCompilationFailure;

type CandidateDraft = {
  range: string;
  kinds: Set<string>;
};

type RoleXml = {
  xml: string;
  normalization: SemanticMapRoleNormalization;
};

const DIRECTION_TO_RELATIONSHIP: Readonly<
  Record<SemanticDirection, RelationshipKind>
> = {
  N: "direct-column",
  W: "direct-row",
  NNW: "cascading-column",
  WNW: "cascading-row",
};

const CANDIDATE_KIND_PRIORITY: Readonly<Record<string, number>> = {
  "value-block": 100,
  "block-intersection": 95,
  "row-block": 90,
  "column-block": 85,
  section: 80,
  merge: 75,
  "value-row-run": 70,
  "value-column-run": 65,
  "row-run": 60,
  "column-run": 55,
  style: 45,
  "used-range": 10,
};

/**
 * Build a deliberately small, deterministic menu of structural regions. The
 * catalog describes geometry only; it does not decide which candidates are
 * values, dimensions, captions, or hierarchy levels.
 */
export function buildSemanticRegionCatalog(
  context: CompactSemanticContext,
  options: { maxCandidates?: number } = {},
): SemanticRegionCatalog {
  const maxCandidates = options.maxCandidates ?? DEFAULT_SEMANTIC_REGION_LIMIT;
  const drafts = new Map<string, CandidateDraft>();
  const rows = context.dimensions.rows;
  const columns = context.dimensions.columns;
  const values = context.grid.rows.map((row) => row.values);

  const add = (
    row1: number,
    col1: number,
    row2: number,
    col2: number,
    kind: string,
  ): void => {
    if (
      row1 < 1 ||
      col1 < 1 ||
      row2 < row1 ||
      col2 < col1 ||
      row2 > rows ||
      col2 > columns
    ) {
      return;
    }
    const range = formatRange({
      start: { row: row1, col: col1 },
      end: { row: row2, col: col2 },
    });
    const existing = drafts.get(range);
    if (existing) existing.kinds.add(kind);
    else drafts.set(range, { range, kinds: new Set([kind]) });
  };

  if (context.usedRange) {
    const used = parseRange(context.usedRange);
    add(
      used.start.row,
      used.start.col,
      used.end.row,
      used.end.col,
      "used-range",
    );
  }
  for (const merge of context.merges) {
    const range = parseRange(merge.range);
    add(
      range.start.row,
      range.start.col,
      range.end.row,
      range.end.col,
      "merge",
    );
  }
  for (const boundary of context.styleBoundaries) {
    add(
      boundary.row,
      boundary.startColumn,
      boundary.row,
      boundary.endColumn,
      "style",
    );
  }

  const rowRuns = values.map((row) => booleanRuns(row.map(isNonblank)));
  const valueRowRuns = values.map((row) =>
    booleanRuns(row.map(isObservationLike)),
  );
  rowRuns.forEach((runs, rowIndex) => {
    for (const [start, end] of runs)
      add(rowIndex + 1, start, rowIndex + 1, end, "row-run");
  });
  valueRowRuns.forEach((runs, rowIndex) => {
    for (const [start, end] of runs)
      add(rowIndex + 1, start, rowIndex + 1, end, "value-row-run");
  });
  addConsecutiveRunBlocks(rowRuns, "row-block", add);
  addConsecutiveRunBlocks(valueRowRuns, "value-block", add);
  addConsecutiveRunBlocksByRowSignature(
    valueRowRuns,
    rowRuns,
    "value-block",
    add,
  );

  const columnRuns: Array<Array<[number, number]>> = [];
  const valueColumnRuns: Array<Array<[number, number]>> = [];
  for (let col = 0; col < columns; col += 1) {
    columnRuns.push(booleanRuns(values.map((row) => isNonblank(row[col]))));
    valueColumnRuns.push(
      booleanRuns(values.map((row) => isObservationLike(row[col]))),
    );
  }
  columnRuns.forEach((runs, colIndex) => {
    for (const [start, end] of runs)
      add(start, colIndex + 1, end, colIndex + 1, "column-run");
  });
  valueColumnRuns.forEach((runs, colIndex) => {
    for (const [start, end] of runs)
      add(start, colIndex + 1, end, colIndex + 1, "value-column-run");
  });
  addConsecutiveColumnBlocks(columnRuns, "column-block", add);
  addConsecutiveColumnBlocks(valueColumnRuns, "value-block", add);

  for (const [startRow, endRow] of booleanRuns(
    values.map((row) => row.some(isNonblank)),
  )) {
    let minCol = columns;
    let maxCol = 1;
    let found = false;
    for (let row = startRow; row <= endRow; row += 1) {
      values[row - 1].forEach((value, colIndex) => {
        if (!isNonblank(value)) return;
        found = true;
        minCol = Math.min(minCol, colIndex + 1);
        maxCol = Math.max(maxCol, colIndex + 1);
      });
    }
    if (found) add(startRow, minCol, endRow, maxCol, "section");
  }

  addBlockIntersections(drafts, add);

  const all = [...drafts.values()].map((draft) =>
    describeCandidate(draft, values),
  );
  const ranked = all.sort(compareCandidatePriority);
  const retained = ranked.slice(0, maxCandidates);
  const candidates = retained.map((candidate, index) => ({
    id: `region-${String(index + 1).padStart(3, "0")}`,
    range: candidate.range,
    kinds: candidate.kinds,
    nonblankCount: candidate.nonblankCount,
    valueLikeCount: candidate.valueLikeCount,
    sample: candidate.sample,
  }));

  return {
    version: "semantic-region-catalog-v1",
    sheet: context.sheet,
    candidates,
    omittedCandidateCount: Math.max(0, all.length - retained.length),
  };
}

export function renderSemanticRegionCatalog(
  catalog: SemanticRegionCatalog,
): string {
  return catalog.candidates
    .map(
      (candidate) =>
        `${candidate.id} | ${candidate.range} | ${candidate.kinds.join(",")} | nonblank=${candidate.nonblankCount} valueLike=${candidate.valueLikeCount} | ${candidate.sample.join("; ")}`,
    )
    .join("\n");
}

export function parseSemanticTableMapJson(raw: string): SemanticTableMapV1 {
  const cleaned = raw
    .trim()
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/\s*```$/, "")
    .trim();
  return semanticTableMapSchema.parse(JSON.parse(cleaned));
}

export function compileSemanticTableMap({
  map: input,
  catalog,
  context,
}: {
  map: unknown;
  catalog: SemanticRegionCatalog;
  context: CompactSemanticContext;
}): SemanticMapCompilationResult {
  const parsedMap = semanticTableMapSchema.safeParse(input);
  if (!parsedMap.success) {
    return {
      ok: false,
      stage: "model-form",
      code: "SEMANTIC_MAP_SCHEMA_INVALID",
      message: parsedMap.error.issues
        .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
        .join("; "),
      diagnostics: [],
    };
  }
  const map = parsedMap.data;
  const byId = new Map(
    catalog.candidates.map((candidate) => [candidate.id, candidate]),
  );

  let values: RoleXml;
  const dimensions: RoleXml[] = [];
  try {
    values = buildRoleXml({
      regionIds: map.table.values.regions,
      byId,
      idPrefix: "value-cell",
    });
    for (const [index, dimension] of map.table.dimensions.entries()) {
      dimensions.push(
        buildRoleXml({
          regionIds: dimension.memberRegions,
          byId,
          idPrefix: `dimension-${index + 1}-cell`,
        }),
      );
    }
  } catch (error) {
    return {
      ok: false,
      stage: "region-resolution",
      code: errorCode(error, "SEMANTIC_REGION_RESOLUTION_FAILED"),
      message: errorMessage(error),
      diagnostics: [],
    };
  }

  const tableName = escapeXml(map.table.name);
  const valuesName = escapeXml(map.table.values.name);
  const dimensionXml = map.table.dimensions
    .map((dimension, index) => {
      const number = index + 1;
      const relationship = DIRECTION_TO_RELATIONSHIP[dimension.direction];
      return [
        `<Dimension id="dimension-${number}" name="${escapeXml(dimension.name)}" evidence="Selected semantic member regions.">${dimensions[index].xml}</Dimension>`,
        `<Relationship id="relationship-${number}" dimensionId="dimension-${number}" kind="${relationship}" evidence="Direction selected by the semantic model."/>`,
      ].join("");
    })
    .join("");
  const xml = [
    `<CellRoleSketch version="0.2" sheet="${escapeXml(context.sheet)}">`,
    `<Table id="table-1" name="${tableName}" evidence="Selected by semantic table map.">`,
    `<Values id="values-1" name="${valuesName}" evidence="Selected semantic observation regions.">${values.xml}</Values>`,
    dimensionXml,
    `</Table>`,
    `</CellRoleSketch>`,
  ].join("");

  const geometryOptions: CellRoleGeometryOptions = {
    sheet: { cells: contextCells(context) },
    collectAssociations: true,
  };
  const parsed = parseCellRoleSketchV02(
    xml,
    {
      rowCount: context.dimensions.rows,
      columnCount: context.dimensions.columns,
    },
    geometryOptions,
  );
  if (!parsed.ok) {
    return {
      ok: false,
      stage: "geometry",
      code: parsed.code,
      message: parsed.message,
      diagnostics: parsed.diagnostics ?? [],
    };
  }

  const compiled = compileCellRoleSketch(parsed.sketch, geometryOptions);
  if (!compiled.ok) {
    return compilerFailure(compiled.error);
  }

  const geometry = validateCellRoleSketchGeometry(
    parsed.sketch,
    geometryOptions,
  );
  const warnings = coverageWarnings(parsed.sketch, geometry);

  return {
    ok: true,
    map,
    sketch: parsed.sketch,
    canonicalXml: parsed.canonical,
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
    warnings,
  };
}

export function isCorrectionEligible(
  failure: SemanticMapCompilationFailure,
): boolean {
  return failure.stage === "region-resolution" || failure.stage === "geometry";
}

export function formatCorrectionDiagnostics(
  failure: SemanticMapCompilationFailure,
): string {
  const lines = [`${failure.code}: ${failure.message}`];
  for (const diagnostic of failure.diagnostics.slice(0, 20)) {
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
  return lines.join("\n");
}

export function contextCells(
  context: CompactSemanticContext,
): Array<{ address: string; data_type: string; value: unknown }> {
  return context.grid.rows.flatMap((row, rowIndex) =>
    row.values.map((value, columnIndex) => ({
      address: `R${rowIndex + 1}C${columnIndex + 1}`,
      data_type:
        value === null
          ? "blank"
          : typeof value === "number"
            ? "numeric"
            : typeof value === "boolean"
              ? "boolean"
              : "string",
      value,
    })),
  );
}

function buildRoleXml({
  regionIds,
  byId,
  idPrefix,
}: {
  regionIds: string[];
  byId: Map<string, SemanticRegionCandidate>;
  idPrefix: string;
}): RoleXml {
  const selectedRegions = [...new Set(regionIds)];
  const addresses = new Set<string>();
  for (const id of selectedRegions) {
    const candidate = byId.get(id);
    if (!candidate) {
      throw codedError(
        "UNKNOWN_SEMANTIC_REGION",
        `Unknown semantic region ${id}.`,
      );
    }
    for (const address of expandRange(candidate.range)) {
      addresses.add(address);
      if (addresses.size > MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS) {
        throw codedError(
          "SEMANTIC_REGION_EXPANSION_LIMIT",
          `Role expands beyond ${MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS} cells.`,
        );
      }
    }
  }
  const sorted = sortAddresses([...addresses]);
  const bounding = boundingRange(sorted);
  const rectangleSize = rectangleCellCount(bounding);
  if (rectangleSize === sorted.length) {
    return {
      xml: `<Cell id="${idPrefix}-1" range="${bounding}"/>`,
      normalization: {
        regionIds: selectedRegions,
        selectedCellCount: sorted.length,
        representation: "range",
      },
    };
  }
  if (sorted.length + 16 > MAX_CELL_ROLE_SKETCH_V02_NODES) {
    throw codedError(
      "SEMANTIC_REGION_NODE_LIMIT",
      `Disjoint role requires ${sorted.length} address nodes; maximum safe count is ${MAX_CELL_ROLE_SKETCH_V02_NODES - 16}.`,
    );
  }
  return {
    xml: sorted
      .map(
        (address, index) =>
          `<Cell id="${idPrefix}-${index + 1}" address="${address}"/>`,
      )
      .join(""),
    normalization: {
      regionIds: selectedRegions,
      selectedCellCount: sorted.length,
      representation: "addresses",
    },
  };
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

function addBlockIntersections(
  drafts: Map<string, CandidateDraft>,
  add: (
    row1: number,
    col1: number,
    row2: number,
    col2: number,
    kind: string,
  ) => void,
): void {
  const structuralKinds = new Set([
    "value-block",
    "row-block",
    "column-block",
    "section",
  ]);
  const structural = [...drafts.values()]
    .filter((draft) =>
      [...draft.kinds].some((kind) => structuralKinds.has(kind)),
    )
    .slice(0, 200);
  for (let leftIndex = 0; leftIndex < structural.length; leftIndex += 1) {
    const left = parseRange(structural[leftIndex].range);
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < structural.length;
      rightIndex += 1
    ) {
      const right = parseRange(structural[rightIndex].range);
      const row1 = Math.max(left.start.row, right.start.row);
      const col1 = Math.max(left.start.col, right.start.col);
      const row2 = Math.min(left.end.row, right.end.row);
      const col2 = Math.min(left.end.col, right.end.col);
      if (row1 > row2 || col1 > col2) continue;
      const intersection = formatRange({
        start: { row: row1, col: col1 },
        end: { row: row2, col: col2 },
      });
      if (
        intersection === structural[leftIndex].range ||
        intersection === structural[rightIndex].range
      ) {
        continue;
      }
      add(row1, col1, row2, col2, "block-intersection");
    }
  }
}

function addConsecutiveRunBlocks(
  runsByRow: Array<Array<[number, number]>>,
  kind: string,
  add: (
    row1: number,
    col1: number,
    row2: number,
    col2: number,
    kind: string,
  ) => void,
): void {
  const rowsBySpan = new Map<string, number[]>();
  runsByRow.forEach((runs, rowIndex) => {
    for (const [start, end] of runs) {
      const key = `${start}:${end}`;
      const rows = rowsBySpan.get(key) ?? [];
      rows.push(rowIndex + 1);
      rowsBySpan.set(key, rows);
    }
  });
  for (const [key, rows] of rowsBySpan) {
    const [startCol, endCol] = key.split(":").map(Number);
    for (const [startRow, endRow] of consecutiveNumberRuns(rows)) {
      if (endRow > startRow) add(startRow, startCol, endRow, endCol, kind);
    }
  }
}

function addConsecutiveRunBlocksByRowSignature(
  runsByRow: Array<Array<[number, number]>>,
  rowSignatures: Array<Array<[number, number]>>,
  kind: string,
  add: (
    row1: number,
    col1: number,
    row2: number,
    col2: number,
    kind: string,
  ) => void,
): void {
  const rowsBySpanAndSignature = new Map<string, number[]>();
  runsByRow.forEach((runs, rowIndex) => {
    const signature = rowSignatures[rowIndex]
      .map(([start, end]) => `${start}:${end}`)
      .join(",");
    for (const [start, end] of runs) {
      const key = `${start}:${end}|${signature}`;
      const rows = rowsBySpanAndSignature.get(key) ?? [];
      rows.push(rowIndex + 1);
      rowsBySpanAndSignature.set(key, rows);
    }
  });
  for (const [key, rows] of rowsBySpanAndSignature) {
    const [span] = key.split("|");
    const [startCol, endCol] = span.split(":").map(Number);
    for (const [startRow, endRow] of consecutiveNumberRuns(rows)) {
      if (endRow > startRow) add(startRow, startCol, endRow, endCol, kind);
    }
  }
}

function addConsecutiveColumnBlocks(
  runsByColumn: Array<Array<[number, number]>>,
  kind: string,
  add: (
    row1: number,
    col1: number,
    row2: number,
    col2: number,
    kind: string,
  ) => void,
): void {
  const columnsBySpan = new Map<string, number[]>();
  runsByColumn.forEach((runs, colIndex) => {
    for (const [start, end] of runs) {
      const key = `${start}:${end}`;
      const columns = columnsBySpan.get(key) ?? [];
      columns.push(colIndex + 1);
      columnsBySpan.set(key, columns);
    }
  });
  for (const [key, columns] of columnsBySpan) {
    const [startRow, endRow] = key.split(":").map(Number);
    for (const [startCol, endCol] of consecutiveNumberRuns(columns)) {
      if (endCol > startCol) add(startRow, startCol, endRow, endCol, kind);
    }
  }
}

function consecutiveNumberRuns(values: number[]): Array<[number, number]> {
  if (!values.length) return [];
  const sorted = [...new Set(values)].sort((a, b) => a - b);
  const runs: Array<[number, number]> = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (const value of sorted.slice(1)) {
    if (value === previous + 1) {
      previous = value;
      continue;
    }
    runs.push([start, previous]);
    start = previous = value;
  }
  runs.push([start, previous]);
  return runs;
}

function describeCandidate(
  draft: CandidateDraft,
  values: CompactSemanticContext["grid"]["rows"][number]["values"][],
): Omit<SemanticRegionCandidate, "id"> {
  let nonblankCount = 0;
  let valueLikeCount = 0;
  const sample: string[] = [];
  for (const address of expandRange(draft.range)) {
    const cell = parseCell(address);
    const value = values[cell.row - 1]?.[cell.col - 1];
    if (!isNonblank(value)) continue;
    nonblankCount += 1;
    if (isObservationLike(value)) valueLikeCount += 1;
    if (sample.length < 3) sample.push(`${address}=${JSON.stringify(value)}`);
  }
  return {
    range: draft.range,
    kinds: [...draft.kinds].sort(
      (left, right) => kindPriority(right) - kindPriority(left),
    ),
    nonblankCount,
    valueLikeCount,
    sample,
  };
}

function compareCandidatePriority(
  left: Omit<SemanticRegionCandidate, "id">,
  right: Omit<SemanticRegionCandidate, "id">,
): number {
  const leftPriority = Math.max(...left.kinds.map(kindPriority));
  const rightPriority = Math.max(...right.kinds.map(kindPriority));
  if (leftPriority !== rightPriority) return rightPriority - leftPriority;
  const leftRange = parseRange(left.range);
  const rightRange = parseRange(right.range);
  const leftArea = rectangleCellCount(left.range);
  const rightArea = rectangleCellCount(right.range);
  return (
    rightArea - leftArea ||
    leftRange.start.row - rightRange.start.row ||
    leftRange.start.col - rightRange.start.col ||
    leftRange.end.row - rightRange.end.row ||
    leftRange.end.col - rightRange.end.col
  );
}

function kindPriority(kind: string): number {
  return CANDIDATE_KIND_PRIORITY[kind] ?? 0;
}

function isNonblank(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "";
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

function sortAddresses(addresses: string[]): string[] {
  return addresses.sort((left, right) => {
    const a = parseCell(left);
    const b = parseCell(right);
    return a.row - b.row || a.col - b.col;
  });
}

function boundingRange(addresses: string[]): string {
  if (!addresses.length)
    throw codedError(
      "EMPTY_SEMANTIC_REGION",
      "Selected regions contain no cells.",
    );
  const cells = addresses.map(parseCell);
  return formatRange({
    start: {
      row: Math.min(...cells.map((cell) => cell.row)),
      col: Math.min(...cells.map((cell) => cell.col)),
    },
    end: {
      row: Math.max(...cells.map((cell) => cell.row)),
      col: Math.max(...cells.map((cell) => cell.col)),
    },
  });
}

function rectangleCellCount(range: string): number {
  const parsed = parseRange(range);
  return (
    (parsed.end.row - parsed.start.row + 1) *
    (parsed.end.col - parsed.start.col + 1)
  );
}

function coverageWarnings(
  sketch: CellRoleSketchV02,
  geometry: CellRoleGeometryResult,
): string[] {
  const table = sketch.tables[0];
  const activeValueCount = geometry.tables[0]?.activeValueCount ?? 0;
  if (!activeValueCount) return [];
  return table.dimensions.flatMap((dimension) => {
    const coveredValues = new Set(
      geometry.associations
        .filter((entry) => entry.dimensionId === dimension.id)
        .map((entry) => entry.valueAddress),
    ).size;
    return coveredValues < activeValueCount
      ? [
          `DIMENSION_PARTIAL_COVERAGE: ${dimension.name} attaches to ${coveredValues}/${activeValueCount} active observations.`,
        ]
      : [];
  });
}

function compilerFailure(
  error: CellRoleCompileError,
): SemanticMapCompilationFailure {
  return {
    ok: false,
    stage: "compiler",
    code: error.code,
    message: `${error.path}: ${error.message}`,
    diagnostics: [],
  };
}

function codedError(code: string, message: string): Error & { code: string } {
  return Object.assign(new Error(message), { code });
}

function errorCode(error: unknown, fallback: string): string {
  return (error as { code?: string })?.code ?? fallback;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
