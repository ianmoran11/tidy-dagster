/* Exact feature port from TidyCell features.ts; MIT, Copyright (c) 2026 Ian Moran. */
import { parseRange } from "../../address.js";
import type { ParsedSheet, TidyCell } from "../../workbook/types.js";
import type { CellFeatureVector, MergeRoleFeature } from "./types.js";

export function extractCellFeatures(
  sheet: ParsedSheet,
  options: { addresses?: ReadonlySet<string> } = {},
): CellFeatureVector[] {
  const rowNonEmptyCounts = new Map<number, number>();
  const columnNonEmptyCounts = new Map<number, number>();
  const cellsByAddress = new Map(
    sheet.cells.map((cell) => [cell.address, cell]),
  );

  for (const cell of sheet.cells) {
    if (isNonEmpty(cell)) {
      rowNonEmptyCounts.set(
        cell.row,
        (rowNonEmptyCounts.get(cell.row) ?? 0) + 1,
      );
      columnNonEmptyCounts.set(
        cell.col,
        (columnNonEmptyCounts.get(cell.col) ?? 0) + 1,
      );
    }
  }

  const featureCells = options.addresses
    ? sheet.cells.filter((cell) => options.addresses?.has(cell.address))
    : sheet.cells;

  return featureCells.map((cell) => {
    const text = cellText(cell);
    const digitCount = countMatches(text, /\d/g);
    const letterCount = countMatches(text, /[a-z]/gi);
    const uppercaseCount = countMatches(text, /[A-Z]/g);
    const punctuationCount = countMatches(text, /[^\w\s]/g);
    const mergeShape = describeMergeShape(cell);
    const border = cell.style?.border;

    return {
      sheet: sheet.name,
      address: cell.address,
      row: cell.row,
      col: cell.col,
      rowRatio: ratio(cell.row, sheet.rowCount),
      colRatio: ratio(cell.col, sheet.columnCount),
      dataType: cell.data_type,
      isBlank: !isNonEmpty(cell),
      hasFormula: Boolean(cell.formula),
      hasComment: Boolean(cell.comment),
      hasFormattedValue:
        cell.formatted !== null && cell.formatted !== undefined,
      textLength: text.length,
      tokenCount: tokenCount(text),
      digitRatio: ratio(digitCount, text.length),
      uppercaseRatio: ratio(uppercaseCount, letterCount),
      punctuationRatio: ratio(punctuationCount, text.length),
      textFingerprint: hashedTextFingerprint(text),
      isNumericLikeText: isNumericLikeText(text),
      isDateLikeText: isDateLikeText(text),
      rowNonEmptyCount: rowNonEmptyCounts.get(cell.row) ?? 0,
      columnNonEmptyCount: columnNonEmptyCounts.get(cell.col) ?? 0,
      rowDensity: ratio(
        rowNonEmptyCounts.get(cell.row) ?? 0,
        sheet.columnCount,
      ),
      columnDensity: ratio(
        columnNonEmptyCounts.get(cell.col) ?? 0,
        sheet.rowCount,
      ),
      nonEmptyAbove: countDirectionalNonEmpty(cellsByAddress, cell, -1, 0),
      nonEmptyBelow: countDirectionalNonEmpty(cellsByAddress, cell, 1, 0),
      nonEmptyLeft: countDirectionalNonEmpty(cellsByAddress, cell, 0, -1),
      nonEmptyRight: countDirectionalNonEmpty(cellsByAddress, cell, 0, 1),
      nearestBlankRowAbove: nearestBlankDistance(
        cell.row,
        -1,
        1,
        rowNonEmptyCounts,
      ),
      nearestBlankRowBelow: nearestBlankDistance(
        cell.row,
        1,
        sheet.rowCount,
        rowNonEmptyCounts,
      ),
      nearestBlankColumnLeft: nearestBlankDistance(
        cell.col,
        -1,
        1,
        columnNonEmptyCounts,
      ),
      nearestBlankColumnRight: nearestBlankDistance(
        cell.col,
        1,
        sheet.columnCount,
        columnNonEmptyCounts,
      ),
      isTopEdge: cell.row === 1,
      isLeftEdge: cell.col === 1,
      isBottomEdge: cell.row === sheet.rowCount,
      isRightEdge: cell.col === sheet.columnCount,
      isBold: Boolean(cell.style?.bold),
      isItalic: Boolean(cell.style?.italic),
      isUnderlined: Boolean(cell.style?.underline),
      fontSize: cell.style?.fontSize ?? null,
      hasFillColor: Boolean(cell.style?.fillColor),
      hasFontColor: Boolean(cell.style?.fontColor),
      fontIndent: cell.style?.fontIndent ?? 0,
      horizontalAlign: cell.style?.horizontalAlign ?? null,
      verticalAlign: cell.style?.verticalAlign ?? null,
      hasBorderTop: Boolean(border?.top),
      hasBorderRight: Boolean(border?.right),
      hasBorderBottom: Boolean(border?.bottom),
      hasBorderLeft: Boolean(border?.left),
      hasAnyBorder: Boolean(
        border?.top || border?.right || border?.bottom || border?.left,
      ),
      mergeRole: mergeShape.role,
      mergeRowSpan: mergeShape.rowSpan,
      mergeColumnSpan: mergeShape.columnSpan,
    };
  });
}

function isNonEmpty(cell: TidyCell): boolean {
  return (
    cell.data_type !== "blank" &&
    cell.value !== null &&
    cell.value !== undefined
  );
}

function cellText(cell: TidyCell): string {
  if (cell.formatted !== null && cell.formatted !== undefined) {
    return String(cell.formatted);
  }

  if (cell.value === null || cell.value === undefined) {
    return "";
  }

  return String(cell.value);
}

function tokenCount(text: string): number {
  return text.trim().length === 0 ? 0 : text.trim().split(/\s+/).length;
}

function countMatches(text: string, pattern: RegExp): number {
  return text.match(pattern)?.length ?? 0;
}

const TEXT_FINGERPRINT_SIZE = 16;

function hashedTextFingerprint(text: string): number[] {
  const normalized = text
    .normalize("NFKC")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, " ");
  const values = Array.from({ length: TEXT_FINGERPRINT_SIZE }, () => 0);

  if (normalized.length === 0) return values;
  const padded = `^${normalized}$`;
  const grams =
    padded.length < 3
      ? [padded]
      : Array.from({ length: padded.length - 2 }, (_, index) =>
          padded.slice(index, index + 3),
        );
  for (const gram of grams) {
    values[fnv1a(gram) % TEXT_FINGERPRINT_SIZE] += 1;
  }
  const magnitude = Math.sqrt(
    values.reduce((sum, value) => sum + value * value, 0),
  );
  return magnitude > 0 ? values.map((value) => value / magnitude) : values;
}

function fnv1a(value: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash;
}

function ratio(numerator: number, denominator: number): number {
  return denominator <= 0 ? 0 : numerator / denominator;
}

function isNumericLikeText(text: string): boolean {
  const normalized = text.replace(/[$,%\s,]/g, "");
  return normalized.length > 0 && /^-?\d+(?:\.\d+)?$/.test(normalized);
}

function isDateLikeText(text: string): boolean {
  const normalized = text.trim();

  return (
    /^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$/.test(normalized) ||
    /^\d{4}[/-]\d{1,2}[/-]\d{1,2}$/.test(normalized) ||
    /^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{2,4}$/i.test(
      normalized,
    )
  );
}

function countDirectionalNonEmpty(
  cellsByAddress: Map<string, TidyCell>,
  cell: TidyCell,
  rowDelta: number,
  colDelta: number,
): number {
  let count = 0;

  for (let step = 1; step <= 3; step += 1) {
    const neighbor = cellsByAddress.get(
      `R${cell.row + rowDelta * step}C${cell.col + colDelta * step}`,
    );

    if (neighbor && isNonEmpty(neighbor)) {
      count += 1;
    }
  }

  return count;
}

function nearestBlankDistance(
  start: number,
  step: -1 | 1,
  limit: number,
  nonEmptyCounts: Map<number, number>,
): number | null {
  for (
    let position = start + step, distance = 1;
    step === -1 ? position >= limit : position <= limit;
    position += step, distance += 1
  ) {
    if ((nonEmptyCounts.get(position) ?? 0) === 0) {
      return distance;
    }
  }

  return null;
}

function describeMergeShape(cell: TidyCell): {
  role: MergeRoleFeature;
  rowSpan: number;
  columnSpan: number;
} {
  if (!cell.merge) {
    return { role: "none", rowSpan: 1, columnSpan: 1 };
  }

  const range = parseRange(cell.merge.range);

  return {
    role: cell.merge.role,
    rowSpan: range.end.row - range.start.row + 1,
    columnSpan: range.end.col - range.start.col + 1,
  };
}
