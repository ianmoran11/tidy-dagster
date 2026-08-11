/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
/**
 * Provenance: adapted from Tidybank's
 * `src/lib/recipe/detectCandidateBlocks.ts` at commit
 * `6eed7df0c54a53d4680a5a0551655bf6346d4c7d` (SHA-256
 * `b7b3d3a0c399ed30a895ec1707112ebe7e0a5fa21a632d198bf120780a4adc3d`).
 *
 * Compatibility adaptations are limited to using TidyCell's structurally
 * compatible canonical workbook/address modules and a local copy of the pure
 * selector-decomposition helper. Detection and ordering semantics are
 * intentionally unchanged; parity is locked by the shared fixture corpus.
 */
import { formatCell, formatRange, parseCell, parseRange } from "../address.js";
import { decomposeSelectorAddresses } from "./decomposeSelector.js";
import {
  SOURCE_GRID_MAX_COLUMNS,
  SOURCE_GRID_MAX_ROWS,
} from "../workbook/gridLimits.js";
import type { CellDataType, ParsedSheet, TidyCell } from "../workbook/types.js";

export const CANDIDATE_BLOCK_DETECTOR_VERSION =
  "tidybank-candidate-blocks-v1" as const;
export const CANDIDATE_BLOCK_DETECTOR_PROVENANCE = {
  source_path: "src/lib/recipe/detectCandidateBlocks.ts",
  source_commit: "6eed7df0c54a53d4680a5a0551655bf6346d4c7d",
  source_sha256:
    "b7b3d3a0c399ed30a895ec1707112ebe7e0a5fa21a632d198bf120780a4adc3d",
  detector_version: CANDIDATE_BLOCK_DETECTOR_VERSION,
  compatibility_adaptations:
    "TidyCell canonical workbook/address imports and local pure selector decomposition; no semantic divergence.",
} as const;

/** Maximum suggestions transported with one parsed worksheet. */
export const MAX_CANDIDATE_BLOCKS = 16;
export const MAX_GROUPED_CANDIDATE_RANGES =
  SOURCE_GRID_MAX_ROWS * SOURCE_GRID_MAX_COLUMNS;
export const CANDIDATE_YEAR_MIN = 1850;
export const CANDIDATE_YEAR_MAX = 2100;
export const PLAUSIBLE_YEAR_STEPS = [1, 2, 5, 10] as const;
export const LONG_YEAR_RUN_LENGTH = 5;
const PLAUSIBLE_YEAR_STEP_SET: ReadonlySet<number> = new Set(
  PLAUSIBLE_YEAR_STEPS,
);

export type CandidateBlockDataType = Exclude<CellDataType, "blank">;
export type CandidateBlockClassification =
  | "year-run"
  | "repeated-label-run"
  | "merged-heading"
  | "count-percentage-pairs"
  | "format-partition";
export type CandidateBlockSuggestedRole = "header" | "value" | "unknown";
export type CandidateBlockConfidence = "high" | "medium" | "low";
export type CandidateBlockConfidenceFactor =
  | "annual-step"
  | "plausible-step"
  | "ascending-direction"
  | "descending-direction"
  | "long-run"
  | "adjacent-value-body"
  | "exact-repeat"
  | "repeated-values"
  | "shared-label-stem"
  | "merged-extent"
  | "percentage-format"
  | "percentage-heading"
  | "format-signature";

/**
 * Deliberately coarse, local-only signature used for candidate block detection.
 * Fill colour and other visual details are intentionally excluded: only data
 * type class, bold, integer indent step, and fill presence partition cells.
 */
export interface CandidateBlockSignature {
  dataType: CandidateBlockDataType;
  bold: boolean;
  indentStep: number;
  hasFill: boolean;
}

export interface CandidateBlock {
  range: string;
  ranges: readonly string[];
  signature: CandidateBlockSignature;
  signatureSummary: string;
  cellCount: number;
  label: string;
  classification: CandidateBlockClassification;
  suggestedRole: CandidateBlockSuggestedRole;
  confidence: CandidateBlockConfidence;
  confidenceFactors: readonly CandidateBlockConfidenceFactor[];
  evidence: string;
}

type CandidateCell = TidyCell & { data_type: CandidateBlockDataType };

type CandidateExtent = {
  startRow: number;
  endRow: number;
  startCol: number;
  endCol: number;
};

type CandidateDetectionContext = {
  sheet: ParsedSheet;
  extent: CandidateExtent;
  allCells: readonly TidyCell[];
  cells: readonly CandidateCell[];
  cellsByAddress: ReadonlyMap<string, TidyCell>;
};

type DetectedCandidate = {
  block: CandidateBlock;
  addresses: readonly string[];
};

type YearCell = {
  cell: CandidateCell;
  year: number;
  row: number;
  col: number;
};

type LineAxis = "row" | "column";

type ColumnKind = {
  kind: "count" | "percentage";
  percentageFromFormatted: boolean;
  percentageFromHeading: boolean;
};

interface SignaturePartition {
  signature: CandidateBlockSignature;
  suggestedRole: CandidateBlockSuggestedRole;
  addresses: string[];
}

const STRUCTURAL_USEFULNESS: Readonly<
  Record<CandidateBlockClassification, number>
> = {
  "year-run": 500,
  "merged-heading": 480,
  "count-percentage-pairs": 460,
  "repeated-label-run": 440,
  "format-partition": 100,
};

const CONFIDENCE_USEFULNESS: Readonly<
  Record<CandidateBlockConfidence, number>
> = {
  high: 3,
  medium: 2,
  low: 1,
};

const ROLE_USEFULNESS: Readonly<Record<CandidateBlockSuggestedRole, number>> = {
  header: 3,
  value: 2,
  unknown: 1,
};

/**
 * Detect bounded, deterministic rectangles within the same capped extent as
 * the Source grid. Structural classifiers claim their member cells before the
 * remaining cells are decomposed by the legacy formatting signature, so a
 * header run cannot be absorbed into a value rectangle.
 */
export function detectCandidateBlocks(
  sheet: ParsedSheet,
): readonly CandidateBlock[] {
  const context = candidateDetectionContext(sheet);
  if (context === null) return [];

  const yearRuns = detectYearRuns(context);
  const repeatedLabels = detectRepeatedLabels(context);
  const mergedHeadings = detectMergedHeadings(context);
  const confirmedHeaders = [...yearRuns, ...mergedHeadings, ...repeatedLabels];
  const excludedHeaderAddresses = detectedAddressSet(confirmedHeaders);
  const countPercentagePairs = detectCountPercentagePairs(
    context,
    excludedHeaderAddresses,
  );
  const structural = [
    ...yearRuns,
    ...mergedHeadings,
    ...countPercentagePairs,
    ...repeatedLabels,
  ];
  const claimedAddresses = detectedAddressSet(structural);
  const formatPartitions = detectFormatPartitions(context, claimedAddresses);

  return candidateBlocksFromDetected([
    ...structural,
    ...formatPartitions,
  ]).slice(0, MAX_CANDIDATE_BLOCKS);
}

/** Detect value- and adjacency-based year header runs only. */
export function detectYearRunBlocks(
  sheet: ParsedSheet,
): readonly CandidateBlock[] {
  const context = candidateDetectionContext(sheet);
  return context === null
    ? []
    : candidateBlocksFromDetected(detectYearRuns(context));
}

/** Detect repeated or common-stem string label runs only. */
export function detectRepeatedLabelBlocks(
  sheet: ParsedSheet,
): readonly CandidateBlock[] {
  const context = candidateDetectionContext(sheet);
  return context === null
    ? []
    : candidateBlocksFromDetected(detectRepeatedLabels(context));
}

/** Detect full-extent merged heading suggestions only. */
export function detectMergedHeadingBlocks(
  sheet: ParsedSheet,
): readonly CandidateBlock[] {
  const context = candidateDetectionContext(sheet);
  return context === null
    ? []
    : candidateBlocksFromDetected(detectMergedHeadings(context));
}

/** Detect alternating count/percentage value pairs only. */
export function detectCountPercentagePairBlocks(
  sheet: ParsedSheet,
): readonly CandidateBlock[] {
  const context = candidateDetectionContext(sheet);
  if (context === null) return [];
  const confirmedHeaders = [
    ...detectYearRuns(context),
    ...detectMergedHeadings(context),
    ...detectRepeatedLabels(context),
  ];
  return candidateBlocksFromDetected(
    detectCountPercentagePairs(context, detectedAddressSet(confirmedHeaders)),
  );
}

export function candidateBlockSignature(
  cell: TidyCell,
): CandidateBlockSignature {
  if (cell.data_type === "blank") {
    throw new Error("Blank cells are not candidate block members.");
  }
  const indent = cell.style?.fontIndent;
  const indentStep =
    typeof indent === "number" && Number.isFinite(indent)
      ? Math.max(0, Math.trunc(indent))
      : 0;
  return {
    dataType: cell.data_type,
    bold: Boolean(cell.style?.bold),
    indentStep,
    hasFill: Boolean(cell.style?.fillColor),
  };
}

export function summarizeCandidateBlockSignature(
  signature: CandidateBlockSignature,
): string {
  return `${signature.dataType}; ${signature.bold ? "bold" : "regular"}; indent ${signature.indentStep}; ${signature.hasFill ? "fill present" : "no fill"}`;
}

/** Structural usefulness precedes size; all remaining keys are deterministic. */
export function compareCandidateBlocks(
  left: CandidateBlock,
  right: CandidateBlock,
): number {
  const leftRange = parseRange(left.range);
  const rightRange = parseRange(right.range);
  return (
    STRUCTURAL_USEFULNESS[right.classification] -
      STRUCTURAL_USEFULNESS[left.classification] ||
    CONFIDENCE_USEFULNESS[right.confidence] -
      CONFIDENCE_USEFULNESS[left.confidence] ||
    ROLE_USEFULNESS[right.suggestedRole] -
      ROLE_USEFULNESS[left.suggestedRole] ||
    right.cellCount - left.cellCount ||
    leftRange.start.row - rightRange.start.row ||
    leftRange.start.col - rightRange.start.col ||
    leftRange.end.row - rightRange.end.row ||
    leftRange.end.col - rightRange.end.col ||
    compareText(left.classification, right.classification) ||
    compareText(left.suggestedRole, right.suggestedRole) ||
    compareText(signatureKey(left.signature), signatureKey(right.signature)) ||
    compareText(left.evidence, right.evidence) ||
    compareText(left.label, right.label)
  );
}

function detectYearRuns(
  context: CandidateDetectionContext,
): readonly DetectedCandidate[] {
  const yearCells = context.cells
    .map((cell): YearCell | null => {
      const year = resolvedYear(cell);
      return year === null
        ? null
        : { cell, year, row: cell.row, col: cell.col };
    })
    .filter((item): item is YearCell => item !== null);
  const candidates: DetectedCandidate[] = [];

  for (const axis of ["row", "column"] as const) {
    for (const group of contiguousLineGroups(yearCells, axis)) {
      for (const run of arithmeticYearRuns(group)) {
        const first = run[0]!;
        const last = run.at(-1)!;
        const range = formatRange({
          start: { row: first.cell.row, col: first.cell.col },
          end: { row: last.cell.row, col: last.cell.col },
        });
        const values = run.map(({ year }) => year);
        const step = values[1]! - values[0]!;
        const confidenceFactors = yearRunConfidenceFactors(
          context,
          run,
          axis,
          step,
        );
        candidates.push({
          block: createCandidateBlock({
            range,
            signature: candidateBlockSignature(first.cell),
            cellCount: run.length,
            label: `year values ${values[0]}–${values.at(-1)}`,
            classification: "year-run",
            suggestedRole: "header",
            confidence: yearRunConfidence(confidenceFactors),
            confidenceFactors,
            evidence: yearRunEvidence(values, axis, step),
          }),
          addresses: run.map(({ cell }) => cell.address),
        });
      }
    }
  }

  return candidates;
}

function detectRepeatedLabels(
  context: CandidateDetectionContext,
): readonly DetectedCandidate[] {
  const labels = context.cells.filter(
    (cell) =>
      cell.data_type === "string" &&
      typeof cell.value === "string" &&
      cell.value.trim() !== "" &&
      cell.merge?.role !== "child",
  );
  const candidates: DetectedCandidate[] = [];

  for (const axis of ["row", "column"] as const) {
    for (const group of contiguousLineGroups(labels, axis)) {
      const groupValues = group.map(stringCellValue);
      const groupRepeats =
        new Set(groupValues.map(normalizeLabel)).size < groupValues.length;
      const runs = groupRepeats ? [group] : compatibleLabelRuns(group);
      for (const run of runs) {
        const values = run.map(stringCellValue);
        const normalized = values.map(normalizeLabel);
        const distinctValueCount = new Set(normalized).size;
        const exactRepeat = distinctValueCount === 1;
        const repeatedValues = distinctValueCount < normalized.length;
        const stem = commonLabelStem(values);
        if (!repeatedValues && stem === null) continue;
        const first = run[0]!;
        const last = run.at(-1)!;
        const range = formatRange({
          start: { row: first.row, col: first.col },
          end: { row: last.row, col: last.col },
        });
        candidates.push({
          block: createCandidateBlock({
            range,
            signature: candidateBlockSignature(first),
            cellCount: run.length,
            label: repeatedLabelDescription(
              values,
              exactRepeat,
              repeatedValues,
              stem,
            ),
            classification: "repeated-label-run",
            suggestedRole: "header",
            confidence: exactRepeat ? "high" : "medium",
            confidenceFactors: [
              exactRepeat
                ? "exact-repeat"
                : repeatedValues
                  ? "repeated-values"
                  : "shared-label-stem",
            ],
            evidence: exactRepeat
              ? `Repeated nonblank label “${values[0]!.trim()}” forms a ${axis} header run.`
              : repeatedValues
                ? `Nonblank label values repeat along one ${axis} header run.`
                : `Nonblank labels share the common stem “${stem}” along one ${axis}.`,
          }),
          addresses: run.map((cell) => cell.address),
        });
      }
    }
  }

  return candidates;
}

function detectMergedHeadings(
  context: CandidateDetectionContext,
): readonly DetectedCandidate[] {
  const merges = new Map<string, { parent: string; range: string }>();
  const addMerge = (parent: string, range: string): void => {
    try {
      const parsed = parseRange(range);
      const canonicalRange = formatRange(parsed);
      const canonicalParent = formatCell(parseCell(parent));
      const current = merges.get(canonicalRange);
      if (current === undefined || canonicalParent < current.parent) {
        merges.set(canonicalRange, {
          parent: canonicalParent,
          range: canonicalRange,
        });
      }
    } catch {
      // Ignore malformed legacy merge metadata.
    }
  };

  for (const merge of context.sheet.merges) {
    addMerge(merge.parent, merge.range);
  }
  for (const cell of context.allCells) {
    if (cell.merge !== null && cell.merge !== undefined) {
      addMerge(cell.merge.parent, cell.merge.range);
    }
  }

  return [...merges.values()]
    .sort((left, right) => compareRanges(left.range, right.range))
    .flatMap((merge): readonly DetectedCandidate[] => {
      const parsed = parseRange(merge.range);
      if (!isRangeWithinExtent(parsed, context.extent)) return [];
      const addresses = addressesInRange(parsed);
      const representative =
        context.cellsByAddress.get(merge.parent) ??
        addresses
          .map((address) => context.cellsByAddress.get(address))
          .find((cell): cell is TidyCell =>
            Boolean(cell && isCandidateCell(cell)),
          );
      if (representative === undefined || !isCandidateCell(representative)) {
        return [];
      }
      const width = parsed.end.col - parsed.start.col + 1;
      const height = parsed.end.row - parsed.start.row + 1;
      return [
        {
          block: createCandidateBlock({
            range: merge.range,
            signature: candidateBlockSignature(representative),
            cellCount: width * height,
            label: `merged heading “${stringCellValue(representative)}”`,
            classification: "merged-heading",
            suggestedRole: "header",
            confidence: "high",
            confidenceFactors: ["merged-extent"],
            evidence: `A merged heading spans its full ${height} × ${width} extent.`,
          }),
          addresses,
        },
      ];
    });
}

function detectCountPercentagePairs(
  context: CandidateDetectionContext,
  excludedHeaderAddresses: ReadonlySet<string>,
): readonly DetectedCandidate[] {
  const cellsByColumn = new Map<number, CandidateCell[]>();
  for (const cell of context.cells) {
    const column = cellsByColumn.get(cell.col) ?? [];
    column.push(cell);
    cellsByColumn.set(cell.col, column);
  }
  const columnKinds = new Map<number, ColumnKind>();
  for (const [col, cells] of cellsByColumn) {
    const kind = countPercentageColumnKind(cells);
    if (kind !== null) columnKinds.set(col, kind);
  }

  const candidates: DetectedCandidate[] = [];
  let col = context.extent.startCol;
  while (col <= context.extent.endCol - 3) {
    if (
      columnKinds.get(col)?.kind !== "count" ||
      columnKinds.get(col + 1)?.kind !== "percentage"
    ) {
      col += 1;
      continue;
    }
    let endCol = col + 1;
    let pairCount = 1;
    while (
      columnKinds.get(endCol + 1)?.kind === "count" &&
      columnKinds.get(endCol + 2)?.kind === "percentage"
    ) {
      endCol += 2;
      pairCount += 1;
    }
    if (pairCount < 2) {
      col += 2;
      continue;
    }

    const valueCells = context.cells.filter(
      (cell) =>
        cell.col >= col &&
        cell.col <= endCol &&
        (cell.data_type === "numeric" || cell.data_type === "date") &&
        !excludedHeaderAddresses.has(cell.address),
    );
    const addresses = valueCells.map((cell) => cell.address);
    const percentageColumns = Array.from(
      { length: pairCount },
      (_, index) => col + index * 2 + 1,
    );
    const usedFormattedEvidence = percentageColumns.some(
      (column) => columnKinds.get(column)?.percentageFromFormatted,
    );
    const usedHeadingEvidence = percentageColumns.some(
      (column) => columnKinds.get(column)?.percentageFromHeading,
    );
    const evidenceSource = usedFormattedEvidence
      ? usedHeadingEvidence
        ? "percentage formatting and headings"
        : "percentage formatting"
      : "percentage-bearing headings";

    for (const part of decomposeSelectorAddresses(addresses).parts) {
      const range = formatRange({ start: part.start, end: part.end });
      const representative = context.cellsByAddress.get(formatCell(part.start));
      if (representative === undefined || !isCandidateCell(representative)) {
        continue;
      }
      candidates.push({
        block: createCandidateBlock({
          range,
          signature: candidateBlockSignature(representative),
          cellCount: part.cellCount,
          label: `${pairCount} count/percentage column pairs`,
          classification: "count-percentage-pairs",
          suggestedRole: "value",
          confidence: usedFormattedEvidence ? "high" : "medium",
          confidenceFactors: [
            ...(usedFormattedEvidence ? (["percentage-format"] as const) : []),
            ...(usedHeadingEvidence ? (["percentage-heading"] as const) : []),
          ],
          evidence: `${pairCount} alternating count/percentage column pairs are confirmed by ${evidenceSource}.`,
        }),
        addresses: addressesInRange({ start: part.start, end: part.end }),
      });
    }
    col = endCol + 1;
  }

  return candidates;
}

function detectFormatPartitions(
  context: CandidateDetectionContext,
  claimedAddresses: ReadonlySet<string>,
): readonly DetectedCandidate[] {
  const partitions = new Map<string, SignaturePartition>();
  for (const cell of context.cells) {
    if (claimedAddresses.has(cell.address)) continue;
    const signature = candidateBlockSignature(cell);
    const suggestedRole = genericRoleHint(cell);
    const key = `${suggestedRole}|${signatureKey(signature)}`;
    const partition = partitions.get(key) ?? {
      signature,
      suggestedRole,
      addresses: [],
    };
    partition.addresses.push(cell.address);
    partitions.set(key, partition);
  }

  return [...partitions.values()].flatMap(
    ({ signature, suggestedRole, addresses }) =>
      decomposeSelectorAddresses(addresses).parts.map((part) => {
        const range = formatRange({ start: part.start, end: part.end });
        return {
          block: createCandidateBlock({
            range,
            signature,
            cellCount: part.cellCount,
            label: candidateBlockLabel(
              signature,
              part.width,
              part.height,
              range,
            ),
            classification: "format-partition",
            suggestedRole,
            confidence: "low",
            confidenceFactors: ["format-signature"],
            evidence: `Cells share the ${summarizeCandidateBlockSignature(signature)} signature; no stronger structural pattern was confirmed.`,
          }),
          addresses: addressesInRange({ start: part.start, end: part.end }),
        } satisfies DetectedCandidate;
      }),
  );
}

function candidateBlocksFromDetected(
  candidates: readonly DetectedCandidate[],
): readonly CandidateBlock[] {
  return groupRepeatedStructures(candidates)
    .map(({ block }) => block)
    .sort(compareCandidateBlocks);
}

function groupRepeatedStructures(
  candidates: readonly DetectedCandidate[],
): readonly DetectedCandidate[] {
  const groups = new Map<string, DetectedCandidate[]>();
  for (const candidate of [...candidates].sort((left, right) =>
    compareCandidateBlocks(left.block, right.block),
  )) {
    const { block } = candidate;
    const key = JSON.stringify([
      block.classification,
      block.suggestedRole,
      block.classification === "format-partition"
        ? signatureKey(block.signature)
        : null,
      block.confidence,
      block.label,
      block.evidence,
      block.classification === "format-partition" ? block.range : null,
    ]);
    const group = groups.get(key) ?? [];
    group.push(candidate);
    groups.set(key, group);
  }
  return [...groups.values()].map((group) => {
    const first = group[0]!;
    if (group.length === 1) return first;
    const ranges = group
      .flatMap(({ block }) => block.ranges)
      .sort(compareRanges)
      .slice(0, MAX_GROUPED_CANDIDATE_RANGES);
    return {
      block: {
        ...first.block,
        range: ranges[0]!,
        ranges,
        cellCount: group.reduce(
          (total, { block }) => total + block.cellCount,
          0,
        ),
        confidenceFactors: first.block.confidenceFactors.filter((factor) =>
          group.every(({ block }) => block.confidenceFactors.includes(factor)),
        ),
        evidence: `${first.block.evidence} This structure repeats ${ranges.length} times.`,
      },
      addresses: group.flatMap(({ addresses }) => addresses),
    };
  });
}

function createCandidateBlock(
  input: Omit<CandidateBlock, "ranges" | "signatureSummary">,
): CandidateBlock {
  return {
    ...input,
    ranges: [input.range],
    signatureSummary: summarizeCandidateBlockSignature(input.signature),
  };
}

function candidateBlockLabel(
  signature: CandidateBlockSignature,
  width: number,
  height: number,
  range: string,
): string {
  const position = rangePosition(range);
  if (signature.dataType === "string") {
    const emphasis = signature.bold ? "bold " : "";
    if (width === 1 && height > 1) {
      return `${emphasis}row labels at ${position}`;
    }
    if (height === 1 && width > 1) {
      return `${emphasis}column labels at ${position}`;
    }
    return `${emphasis}text block at ${position}`;
  }
  return `${signature.dataType} block at ${position}`;
}

function rangePosition(range: string): string {
  const parsed = parseRange(range);
  const { start, end } = parsed;
  if (start.row === end.row && start.col === end.col) {
    return `row ${start.row}, column ${start.col}`;
  }
  if (start.row === end.row) {
    return `row ${start.row}, columns ${start.col}–${end.col}`;
  }
  if (start.col === end.col) {
    return `rows ${start.row}–${end.row}, column ${start.col}`;
  }
  return `rows ${start.row}–${end.row}, columns ${start.col}–${end.col}`;
}

function repeatedLabelDescription(
  values: readonly string[],
  exactRepeat: boolean,
  repeatedValues: boolean,
  stem: string | null,
): string {
  if (exactRepeat) return `repeated label “${values[0]!.trim()}”`;
  if (repeatedValues) {
    const examples = [...new Set(values.map((value) => value.trim()))].slice(
      0,
      2,
    );
    return `repeating labels ${examples.map((value) => `“${value}”`).join(" and ")}`;
  }
  return `labels sharing “${stem}”`;
}

function candidateDetectionContext(
  sheet: ParsedSheet,
): CandidateDetectionContext | null {
  const extent = candidatePreviewExtent(sheet);
  if (extent === null) return null;
  const allCells = sheet.cells
    .filter((cell) => isWithinExtent(cell, extent))
    .sort(compareCells);
  const cellsByAddress = new Map(
    allCells.map((cell) => [cell.address, cell] as const),
  );
  return {
    sheet,
    extent,
    allCells,
    cells: allCells.filter(isCandidateCell),
    cellsByAddress,
  };
}

function candidatePreviewExtent(sheet: ParsedSheet): CandidateExtent | null {
  if (sheet.usedRange === null || sheet.cells.length === 0) return null;
  let startRow = 1;
  let startCol = 1;
  try {
    const usedRange = parseRange(sheet.usedRange);
    startRow = usedRange.start.row;
    startCol = usedRange.start.col;
  } catch {
    // Keep the defensive grid-compatible R1C1 fallback for old fixtures.
  }
  return {
    startRow,
    endRow: startRow + SOURCE_GRID_MAX_ROWS - 1,
    startCol,
    endCol: startCol + SOURCE_GRID_MAX_COLUMNS - 1,
  };
}

function isCandidateCell(cell: TidyCell): cell is CandidateCell {
  return (
    cell.data_type !== "blank" &&
    cell.value !== null &&
    cell.value !== undefined
  );
}

function isWithinExtent(cell: TidyCell, extent: CandidateExtent): boolean {
  return (
    cell.row >= extent.startRow &&
    cell.row <= extent.endRow &&
    cell.col >= extent.startCol &&
    cell.col <= extent.endCol
  );
}

function isRangeWithinExtent(
  range: ReturnType<typeof parseRange>,
  extent: CandidateExtent,
): boolean {
  return (
    range.start.row >= extent.startRow &&
    range.end.row <= extent.endRow &&
    range.start.col >= extent.startCol &&
    range.end.col <= extent.endCol
  );
}

function resolvedYear(cell: CandidateCell): number | null {
  if (cell.data_type !== "numeric" && cell.data_type !== "date") return null;
  let candidate: number | null = null;
  if (typeof cell.value === "number") {
    candidate = cell.value;
  } else if (cell.data_type === "date" && typeof cell.value === "string") {
    const trimmed = cell.value.trim();
    if (/^\d{4}$/.test(trimmed)) {
      candidate = Number(trimmed);
    } else {
      const timestamp = Date.parse(trimmed);
      if (Number.isFinite(timestamp)) {
        candidate = new Date(timestamp).getUTCFullYear();
      }
    }
  }
  return candidate !== null &&
    Number.isInteger(candidate) &&
    candidate >= CANDIDATE_YEAR_MIN &&
    candidate <= CANDIDATE_YEAR_MAX
    ? candidate
    : null;
}

function yearRunConfidenceFactors(
  context: CandidateDetectionContext,
  run: readonly YearCell[],
  axis: LineAxis,
  step: number,
): CandidateBlockConfidenceFactor[] {
  const factors: CandidateBlockConfidenceFactor[] = [
    Math.abs(step) === 1 ? "annual-step" : "plausible-step",
    step > 0 ? "ascending-direction" : "descending-direction",
  ];
  if (run.length >= LONG_YEAR_RUN_LENGTH) factors.push("long-run");
  if (hasAdjacentValueBody(context, run, axis)) {
    factors.push("adjacent-value-body");
  }
  return factors;
}

function yearRunConfidence(
  factors: readonly CandidateBlockConfidenceFactor[],
): CandidateBlockConfidence {
  const score =
    Number(factors.includes("annual-step")) +
    Number(factors.includes("ascending-direction")) +
    Number(factors.includes("long-run")) +
    2 * Number(factors.includes("adjacent-value-body"));
  return score >= 5 ? "high" : score >= 3 ? "medium" : "low";
}

function hasAdjacentValueBody(
  context: CandidateDetectionContext,
  run: readonly YearCell[],
  axis: LineAxis,
): boolean {
  const offsets =
    axis === "row"
      ? ([
          [-1, 0],
          [1, 0],
        ] as const)
      : ([
          [0, -1],
          [0, 1],
        ] as const);
  return offsets.some(([rowOffset, colOffset]) =>
    run.every(({ row, col }) => {
      const neighborRow = row + rowOffset;
      const neighborCol = col + colOffset;
      if (neighborRow < 1 || neighborCol < 1) return false;
      const neighbor = context.cellsByAddress.get(
        formatCell({ row: neighborRow, col: neighborCol }),
      );
      return (
        neighbor !== undefined &&
        isCandidateCell(neighbor) &&
        (neighbor.data_type === "numeric" || neighbor.data_type === "date") &&
        resolvedYear(neighbor) === null
      );
    }),
  );
}

function yearRunEvidence(
  values: readonly number[],
  axis: LineAxis,
  step: number,
): string {
  const sequence =
    Math.abs(step) === 1 ? "contiguous" : `evenly stepped by ${Math.abs(step)}`;
  const article = /^[aeiou]/i.test(sequence) ? "an" : "a";
  return `Year values ${values[0]}–${values.at(-1)} form ${article} ${sequence} ${axis} run inside ${CANDIDATE_YEAR_MIN}–${CANDIDATE_YEAR_MAX}.`;
}

function arithmeticYearRuns(group: readonly YearCell[]): readonly YearCell[][] {
  if (group.length < 2) return [];
  if (group.length === 2) {
    return Math.abs(group[1]!.year - group[0]!.year) === 1 ? [[...group]] : [];
  }

  const runs: YearCell[][] = [];
  let differenceStart = 0;
  while (differenceStart < group.length - 1) {
    const step =
      group[differenceStart + 1]!.year - group[differenceStart]!.year;
    let differenceEnd = differenceStart;
    while (
      differenceEnd + 1 < group.length - 1 &&
      group[differenceEnd + 2]!.year - group[differenceEnd + 1]!.year === step
    ) {
      differenceEnd += 1;
    }
    if (
      PLAUSIBLE_YEAR_STEP_SET.has(Math.abs(step)) &&
      differenceEnd - differenceStart + 1 >= 2
    ) {
      runs.push(group.slice(differenceStart, differenceEnd + 2));
    }
    differenceStart = differenceEnd + 1;
  }
  return runs;
}

function compatibleLabelRuns(
  group: readonly CandidateCell[],
): readonly CandidateCell[][] {
  if (group.length < 2) return [];
  const runs: CandidateCell[][] = [];
  let start = 0;
  for (let index = 1; index <= group.length; index += 1) {
    const compatible =
      index < group.length &&
      commonLabelStem([
        String(group[index - 1]!.value),
        String(group[index]!.value),
      ]) !== null;
    if (compatible) continue;
    const run = group.slice(start, index);
    if (run.length >= 2 && commonLabelStem(run.map(stringCellValue)) !== null) {
      runs.push(run);
    }
    start = index;
  }
  return runs;
}

function commonLabelStem(values: readonly string[]): string | null {
  if (values.length < 2) return null;
  const normalized = values.map(normalizeLabel);
  if (normalized.some((value) => value === "")) return null;
  if (new Set(normalized).size === 1) return values[0]!.trim();

  const tokenLists = normalized.map(
    (value) => value.match(/[\p{L}\p{N}]+/gu) ?? [],
  );
  const prefix: string[] = [];
  const shortest = Math.min(...tokenLists.map((tokens) => tokens.length));
  for (let index = 0; index < shortest; index += 1) {
    const token = tokenLists[0]![index]!;
    if (
      /^\d+$/.test(token) ||
      !tokenLists.every((tokens) => tokens[index] === token)
    ) {
      break;
    }
    prefix.push(token);
  }
  if (prefix.length > 0) return prefix.join(" ");

  const stripped = tokenLists.map((tokens) =>
    tokens
      .filter(
        (token, index) =>
          index < tokens.length - 1 ||
          !/^\d+$|^(?:count|number|no|percent|percentage|pct|rate|share|proportion)$/u.test(
            token,
          ),
      )
      .join(" "),
  );
  return stripped[0] !== "" && stripped.every((stem) => stem === stripped[0])
    ? stripped[0]!
    : null;
}

function normalizeLabel(value: string): string {
  return value
    .normalize("NFKC")
    .trim()
    .toLocaleLowerCase("en-AU")
    .replace(/%/gu, " percentage ")
    .replace(/\s+/gu, " ");
}

function countPercentageColumnKind(
  cells: readonly CandidateCell[],
): ColumnKind | null {
  const headings = cells.filter(
    (cell) => cell.data_type === "string" && typeof cell.value === "string",
  );
  const values = cells.filter(
    (cell) => cell.data_type === "numeric" || cell.data_type === "date",
  );
  if (values.length === 0) return null;
  const percentageFromFormatted = values.some((cell) =>
    /%\s*$/u.test(cell.formatted?.trim() ?? ""),
  );
  const percentageFromHeading = headings.some((cell) =>
    /(?:%|\bpercent(?:age)?\b|\bpct\b|\brate\b|\bshare\b|\bproportion\b)/iu.test(
      String(cell.value),
    ),
  );
  if (percentageFromFormatted || percentageFromHeading) {
    return {
      kind: "percentage",
      percentageFromFormatted,
      percentageFromHeading,
    };
  }
  const countFromHeading = headings.some((cell) =>
    /\b(?:count|number|no\.?|frequency|total)\b/iu.test(String(cell.value)),
  );
  return countFromHeading || values.length > 0
    ? {
        kind: "count",
        percentageFromFormatted: false,
        percentageFromHeading: false,
      }
    : null;
}

function genericRoleHint(cell: CandidateCell): CandidateBlockSuggestedRole {
  switch (cell.data_type) {
    case "numeric":
    case "date":
    case "boolean":
      return "value";
    case "string":
    case "error":
      return "unknown";
  }
}

function contiguousLineGroups<T extends { row: number; col: number }>(
  cells: readonly T[],
  axis: LineAxis,
): readonly T[][] {
  const lines = new Map<number, T[]>();
  for (const cell of cells) {
    const key = axis === "row" ? cell.row : cell.col;
    const line = lines.get(key) ?? [];
    line.push(cell);
    lines.set(key, line);
  }
  const groups: T[][] = [];
  const position = (cell: T): number => (axis === "row" ? cell.col : cell.row);
  for (const key of [...lines.keys()].sort((left, right) => left - right)) {
    const line = lines
      .get(key)!
      .sort((left, right) => position(left) - position(right));
    let start = 0;
    for (let index = 1; index <= line.length; index += 1) {
      if (
        index < line.length &&
        position(line[index]!) === position(line[index - 1]!) + 1
      ) {
        continue;
      }
      const group = line.slice(start, index);
      if (group.length >= 2) groups.push(group);
      start = index;
    }
  }
  return groups;
}

function detectedAddressSet(
  candidates: readonly DetectedCandidate[],
): ReadonlySet<string> {
  return new Set(candidates.flatMap(({ addresses }) => addresses));
}

function addressesInRange(range: ReturnType<typeof parseRange>): string[] {
  const addresses: string[] = [];
  for (let row = range.start.row; row <= range.end.row; row += 1) {
    for (let col = range.start.col; col <= range.end.col; col += 1) {
      addresses.push(formatCell({ row, col }));
    }
  }
  return addresses;
}

function compareRanges(left: string, right: string): number {
  const leftRange = parseRange(left);
  const rightRange = parseRange(right);
  return (
    leftRange.start.row - rightRange.start.row ||
    leftRange.start.col - rightRange.start.col ||
    leftRange.end.row - rightRange.end.row ||
    leftRange.end.col - rightRange.end.col ||
    compareText(left, right)
  );
}

function compareCells(left: TidyCell, right: TidyCell): number {
  return (
    left.row - right.row ||
    left.col - right.col ||
    compareText(left.address, right.address)
  );
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function signatureKey(signature: CandidateBlockSignature): string {
  return [
    signature.dataType,
    signature.bold ? "1" : "0",
    signature.indentStep.toString().padStart(6, "0"),
    signature.hasFill ? "1" : "0",
  ].join("|");
}

function stringCellValue(cell: CandidateCell): string {
  return String(cell.value);
}
