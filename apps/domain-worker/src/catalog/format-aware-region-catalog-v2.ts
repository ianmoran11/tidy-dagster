/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import { expandRange, formatRange, parseCell, parseRange } from "../address.js";
import type { CellStyleSummary } from "../workbook/types.js";
import type { CompactSemanticContext } from "../context/compactContext.js";
import {
  buildSemanticRegionCatalog,
  compileSemanticTableMap,
  type SemanticMapCompilationResult,
  type SemanticRegionCandidate,
  type SemanticRegionCatalog,
} from "./semantic-map-v1.js";

export const FORMAT_AWARE_REGION_CATALOG_VERSION =
  "semantic-region-catalog-v2-format-aware" as const;
export const DEFAULT_FORMAT_AWARE_REGION_LIMIT = 400;

export type FormatAwareSemanticRegionCandidate = SemanticRegionCandidate & {
  /** Exact compact-context formatting signatures found on nonblank cells. */
  formatSignatures: string[];
  /** Human-readable rendering of formatSignatures for the model prompt. */
  formatting: string[];
};

export type FormatAwareSemanticRegionCatalog = {
  version: typeof FORMAT_AWARE_REGION_CATALOG_VERSION;
  sheet: string;
  candidates: FormatAwareSemanticRegionCandidate[];
  omittedCandidateCount: number;
  baseCandidateCount: number;
  formatDerivedCandidateCount: number;
};

export type SemanticCellFormattingFact = {
  address: string;
  signature: string;
};

type CandidateDraft = {
  range: string;
  kinds: Set<string>;
};

type FormatRun = {
  row: number;
  startColumn: number;
  endColumn: number;
  signature: string;
};

const KIND_PRIORITY: Readonly<Record<string, number>> = {
  "value-block": 100,
  "format-block": 97,
  "block-intersection": 95,
  "format-row": 93,
  "format-column": 93,
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
 * Add formatting as structural evidence without assigning spreadsheet meaning.
 *
 * Formatting-derived candidates contain only nonblank cells with exactly the
 * same compact formatting signature. They are kept local to one contiguous row,
 * column, or rectangular band so unrelated bold/italic cells are not grouped
 * merely because they happen to share presentation.
 */
export function buildFormatAwareSemanticRegionCatalog(
  context: CompactSemanticContext,
  options: {
    maxCandidates?: number;
    baseCandidateLimit?: number;
    /** Rich formatting read directly from workbook cells for this V2 protocol. */
    formattingFacts?: readonly SemanticCellFormattingFact[];
  } = {},
): FormatAwareSemanticRegionCatalog {
  const maxCandidates =
    options.maxCandidates ?? DEFAULT_FORMAT_AWARE_REGION_LIMIT;
  const base = buildSemanticRegionCatalog(context, {
    maxCandidates: options.baseCandidateLimit ?? maxCandidates,
  });
  const drafts = new Map<string, CandidateDraft>();

  const add = (range: string, ...kinds: string[]): void => {
    const existing = drafts.get(range);
    if (existing) {
      for (const kind of kinds) existing.kinds.add(kind);
      return;
    }
    drafts.set(range, { range, kinds: new Set(kinds) });
  };

  for (const candidate of base.candidates) {
    add(candidate.range, ...candidate.kinds);
  }

  const styleByAddress = buildStyleByAddress(
    context,
    options.formattingFacts ?? [],
  );
  const runs = buildFormatRuns(context, styleByAddress);
  for (const run of runs) {
    add(
      range(run.row, run.startColumn, run.row, run.endColumn),
      "format-row",
      "style",
    );
  }
  addFormatColumns(context, styleByAddress, add);
  addFormatBlocks(runs, add);

  const values = context.grid.rows.map((row) => row.values);
  const described = [...drafts.values()].map((draft) =>
    describeCandidate(draft, values, styleByAddress),
  );
  described.sort(compareCandidatePriority);
  const retained = described.slice(0, maxCandidates);
  const formatDerivedCandidateCount = described.filter((candidate) =>
    candidate.kinds.some((kind) => kind.startsWith("format-")),
  ).length;

  return {
    version: FORMAT_AWARE_REGION_CATALOG_VERSION,
    sheet: context.sheet,
    candidates: retained.map((candidate, index) => ({
      id: `region-${String(index + 1).padStart(3, "0")}`,
      ...candidate,
    })),
    omittedCandidateCount:
      base.omittedCandidateCount +
      Math.max(0, described.length - retained.length),
    baseCandidateCount: base.candidates.length,
    formatDerivedCandidateCount,
  };
}

export function renderFormatAwareSemanticRegionCatalog(
  catalog: FormatAwareSemanticRegionCatalog,
): string {
  return catalog.candidates
    .map((candidate) => {
      const formatting = candidate.formatting.length
        ? candidate.formatting.join(" + ")
        : "none-recorded";
      return `${candidate.id} | ${candidate.range} | ${candidate.kinds.join(",")} | formatting=${formatting} | nonblank=${candidate.nonblankCount} valueLike=${candidate.valueLikeCount} | ${candidate.sample.join("; ")}`;
    })
    .join("\n");
}

/** Use the existing semantic-map schema and compiler without changing V1. */
export function compileFormatAwareSemanticTableMap({
  map,
  catalog,
  context,
}: {
  map: unknown;
  catalog: FormatAwareSemanticRegionCatalog;
  context: CompactSemanticContext;
}): SemanticMapCompilationResult {
  return compileSemanticTableMap({
    map,
    catalog: toV1Catalog(catalog),
    context,
  });
}

export function toV1Catalog(
  catalog: FormatAwareSemanticRegionCatalog,
): SemanticRegionCatalog {
  return {
    version: "semantic-region-catalog-v1",
    sheet: catalog.sheet,
    candidates: catalog.candidates.map((candidate) => ({
      id: candidate.id,
      range: candidate.range,
      kinds: candidate.kinds,
      nonblankCount: candidate.nonblankCount,
      valueLikeCount: candidate.valueLikeCount,
      sample: candidate.sample,
    })),
    omittedCandidateCount: catalog.omittedCandidateCount,
  };
}

export function formatSignatureForPrompt(signature: string): string {
  const descriptions = signature
    .split("|")
    .filter(Boolean)
    .map((token) => {
      if (token === "b") return "bold";
      if (token === "i") return "italic";
      if (token === "u") return "underline";
      if (token === "bt") return "border-top";
      if (token === "br") return "border-right";
      if (token === "bb") return "border-bottom";
      if (token === "bl") return "border-left";
      if (token.startsWith("fc")) return `font-color=${token.slice(2)}`;
      if (token.startsWith("bg")) return `fill-color=${token.slice(2)}`;
      if (token.startsWith("in")) return `indent=${token.slice(2)}`;
      if (token.startsWith("s")) return `font-size=${token.slice(1)}`;
      if (token.startsWith("h")) return `horizontal=${token.slice(1)}`;
      if (token.startsWith("v")) return `vertical=${token.slice(1)}`;
      return token;
    });
  return descriptions.join(",");
}

export function buildSemanticCellFormattingFacts(
  cells: ReadonlyArray<{ address: string; style?: CellStyleSummary }>,
): SemanticCellFormattingFact[] {
  return cells
    .map((cell) => ({
      address: cell.address,
      signature: compactFormattingSignature(cell.style),
    }))
    .filter((fact) => fact.signature)
    .sort((left, right) => compareAddresses(left.address, right.address));
}

function buildStyleByAddress(
  context: CompactSemanticContext,
  formattingFacts: readonly SemanticCellFormattingFact[],
): ReadonlyMap<string, string> {
  const result = new Map<string, string>();
  for (const boundary of context.styleBoundaries) {
    for (
      let column = boundary.startColumn;
      column <= boundary.endColumn;
      column += 1
    ) {
      result.set(`R${boundary.row}C${column}`, boundary.style);
    }
  }
  for (const fact of formattingFacts) result.set(fact.address, fact.signature);
  return result;
}

function compactFormattingSignature(
  style: CellStyleSummary | undefined,
): string {
  if (!style) return "";
  return [
    style.bold ? "b" : "",
    style.italic ? "i" : "",
    style.underline ? "u" : "",
    style.fontSize ? `s${style.fontSize}` : "",
    style.fontColor ? `fc${style.fontColor}` : "",
    style.fillColor ? `bg${style.fillColor}` : "",
    style.fontIndent !== undefined ? `in${style.fontIndent}` : "",
    style.horizontalAlign ? `h${style.horizontalAlign}` : "",
    style.verticalAlign ? `v${style.verticalAlign}` : "",
    style.border?.top ? "bt" : "",
    style.border?.right ? "br" : "",
    style.border?.bottom ? "bb" : "",
    style.border?.left ? "bl" : "",
  ]
    .filter(Boolean)
    .join("|");
}

function compareAddresses(left: string, right: string): number {
  const a = parseCell(left);
  const b = parseCell(right);
  return a.row - b.row || a.col - b.col;
}

function buildFormatRuns(
  context: CompactSemanticContext,
  styleByAddress: ReadonlyMap<string, string>,
): FormatRun[] {
  const runs: FormatRun[] = [];
  for (let row = 1; row <= context.dimensions.rows; row += 1) {
    let startColumn: number | null = null;
    let activeSignature = "";
    const flush = (endColumn: number): void => {
      if (startColumn === null || !activeSignature) return;
      runs.push({ row, startColumn, endColumn, signature: activeSignature });
    };
    for (
      let column = 1;
      column <= context.dimensions.columns + 1;
      column += 1
    ) {
      const address = `R${row}C${column}`;
      const value =
        column <= context.dimensions.columns
          ? context.grid.rows[row - 1]?.values[column - 1]
          : null;
      const signature = isNonblank(value)
        ? (styleByAddress.get(address) ?? "")
        : "";
      if (signature === activeSignature) continue;
      flush(column - 1);
      activeSignature = signature;
      startColumn = signature ? column : null;
    }
  }
  return runs;
}

function addFormatColumns(
  context: CompactSemanticContext,
  styleByAddress: ReadonlyMap<string, string>,
  add: (range: string, ...kinds: string[]) => void,
): void {
  for (let column = 1; column <= context.dimensions.columns; column += 1) {
    let startRow: number | null = null;
    let activeSignature = "";
    const flush = (endRow: number): void => {
      if (startRow === null || !activeSignature) return;
      add(range(startRow, column, endRow, column), "format-column", "style");
    };
    for (let row = 1; row <= context.dimensions.rows + 1; row += 1) {
      const address = `R${row}C${column}`;
      const value =
        row <= context.dimensions.rows
          ? context.grid.rows[row - 1]?.values[column - 1]
          : null;
      const signature = isNonblank(value)
        ? (styleByAddress.get(address) ?? "")
        : "";
      if (signature === activeSignature) continue;
      flush(row - 1);
      activeSignature = signature;
      startRow = signature ? row : null;
    }
  }
}

function addFormatBlocks(
  runs: FormatRun[],
  add: (range: string, ...kinds: string[]) => void,
): void {
  const grouped = new Map<string, number[]>();
  for (const run of runs) {
    const key = `${run.signature}\u0000${run.startColumn}\u0000${run.endColumn}`;
    const rows = grouped.get(key) ?? [];
    rows.push(run.row);
    grouped.set(key, rows);
  }
  for (const [key, rows] of grouped) {
    const [, startColumnText, endColumnText] = key.split("\u0000");
    const startColumn = Number(startColumnText);
    const endColumn = Number(endColumnText);
    let startRow = rows[0];
    let previousRow = rows[0];
    const flush = (): void => {
      if (startRow === undefined || previousRow === undefined) return;
      add(
        range(startRow, startColumn, previousRow, endColumn),
        "format-block",
        "style",
      );
    };
    for (const row of rows.slice(1)) {
      if (row === previousRow + 1) {
        previousRow = row;
        continue;
      }
      flush();
      startRow = row;
      previousRow = row;
    }
    flush();
  }
}

function describeCandidate(
  draft: CandidateDraft,
  values: CompactSemanticContext["grid"]["rows"][number]["values"][],
  styleByAddress: ReadonlyMap<string, string>,
): Omit<FormatAwareSemanticRegionCandidate, "id"> {
  let nonblankCount = 0;
  let valueLikeCount = 0;
  const sample: string[] = [];
  const signatures = new Set<string>();
  for (const address of expandRange(draft.range)) {
    const cell = parseCell(address);
    const value = values[cell.row - 1]?.[cell.col - 1];
    if (!isNonblank(value)) continue;
    nonblankCount += 1;
    if (isObservationLike(value)) valueLikeCount += 1;
    const signature = styleByAddress.get(address);
    if (signature) signatures.add(signature);
    if (sample.length < 3) sample.push(`${address}=${JSON.stringify(value)}`);
  }
  const formatSignatures = [...signatures].sort();
  return {
    range: draft.range,
    kinds: [...draft.kinds].sort(
      (left, right) => kindPriority(right) - kindPriority(left),
    ),
    nonblankCount,
    valueLikeCount,
    sample,
    formatSignatures,
    formatting: formatSignatures.map(formatSignatureForPrompt),
  };
}

function compareCandidatePriority(
  left: Omit<FormatAwareSemanticRegionCandidate, "id">,
  right: Omit<FormatAwareSemanticRegionCandidate, "id">,
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
  return KIND_PRIORITY[kind] ?? 0;
}

function range(row1: number, col1: number, row2: number, col2: number): string {
  return formatRange({
    start: { row: row1, col: col1 },
    end: { row: row2, col: col2 },
  });
}

function rectangleCellCount(input: string): number {
  const parsed = parseRange(input);
  return (
    (parsed.end.row - parsed.start.row + 1) *
    (parsed.end.col - parsed.start.col + 1)
  );
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
