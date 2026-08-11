import { boundingRangeOf, formatRange, parseCell } from "@/lib/address";
import type { LabelledCellExample, MlPrepassResult } from "./types";

export function buildPromptHintsFromLabels(
  sheet: string,
  labels: LabelledCellExample[],
): MlPrepassResult {
  const valueAddresses = labels
    .filter((label) => label.role === "value")
    .map((label) => label.address);
  const headerAddresses = labels
    .filter((label) => label.role === "header")
    .map((label) => label.address);
  const ignoredAddresses = labels
    .filter((label) => label.role === "blank" || label.role === "unused")
    .map((label) => label.address);
  const tableRegions = [...groupAddressesByTable(labels, "value").entries()]
    .filter(([, addresses]) => addresses.length > 0)
    .map(([table, addresses]) => ({
      table,
      range: addressesToBoundingRange(addresses),
      valueAddresses: addresses,
      confidence: 1,
    }));

  return {
    sheet,
    modelFamily: "heuristic",
    modelVersion: "recipe-label-oracle-v0",
    predictions: labels.map((label) => ({
      ...label,
      predictedRole: label.role,
      roleProbabilities: { [label.role]: 1 },
      predictedTable: label.table,
      predictedHeader: label.header,
      predictedDirection: label.direction,
      confidence: 1,
    })),
    headerGroups: [],
    tableRegions,
    confidence: {
      overall: 1,
      valueRole: valueAddresses.length > 0 ? 1 : null,
      headerRole: headerAddresses.length > 0 ? 1 : null,
      lowConfidenceCellCount: 0,
    },
    promptHints: [
      `Likely value cells: ${summarizeAddressesAsRanges(valueAddresses)}`,
      `Likely header cells: ${summarizeAddressesAsRanges(headerAddresses)}`,
      `Likely ignorable cells: ${summarizeAddressesAsRanges(ignoredAddresses)}`,
    ],
    lowConfidenceAddresses: [],
  };
}

export function buildCompactPrepassPromptSection(
  prepasses: MlPrepassResult | MlPrepassResult[] | undefined,
): unknown[] {
  if (!prepasses) {
    return [];
  }

  return (Array.isArray(prepasses) ? prepasses : [prepasses]).map((prepass) => {
    const predictions = prepass.predictions ?? [];
    const headerGroups = prepass.headerGroups ?? [];
    const tableRegions = prepass.tableRegions ?? [];
    const lowConfidenceAddresses = prepass.lowConfidenceAddresses ?? [];
    const valueAddresses = predictions
      .filter((prediction) => prediction.predictedRole === "value")
      .map((prediction) => prediction.address);
    const headerAddresses = predictions
      .filter((prediction) => prediction.predictedRole === "header")
      .map((prediction) => prediction.address);

    return {
      sheet: prepass.sheet,
      modelFamily: prepass.modelFamily,
      modelVersion: prepass.modelVersion,
      confidence: prepass.confidence ?? null,
      tableRegions: tableRegions.map((region) => ({
        table: region.table,
        range: region.range,
        confidence: region.confidence,
      })),
      valueRanges: compactAddressRanges(valueAddresses),
      headerRanges: compactAddressRanges(headerAddresses),
      headerGroups: headerGroups.map((group) => ({
        table: group.table,
        header: group.header,
        direction: group.direction,
        range: group.range,
        addressCount: group.addresses.length,
        confidence: group.confidence ?? null,
        modelVersion: group.modelVersion ?? null,
      })),
      lowConfidenceAddresses: summarizeAddresses(lowConfidenceAddresses),
      hints: prepass.promptHints ?? [],
    };
  });
}

export function summarizeAddresses(addresses: string[]): string {
  if (addresses.length === 0) {
    return "none";
  }

  if (addresses.length <= 20) {
    return addresses.join(", ");
  }

  return `${addresses.slice(0, 20).join(", ")} (+${addresses.length - 20} more)`;
}

export function summarizeAddressesAsRanges(addresses: string[]): string {
  const ranges = compactAddressRanges(addresses);

  if (ranges.length === 0) {
    return "none";
  }

  if (ranges.length <= 12) {
    return ranges.join(", ");
  }

  return `${ranges.slice(0, 12).join(", ")} (+${ranges.length - 12} more ranges)`;
}

export function compactAddressRanges(addresses: string[]): string[] {
  if (addresses.length === 0) {
    return [];
  }

  const byRow = new Map<number, number[]>();

  for (const address of addresses) {
    const parsed = parseCell(address);
    const cols = byRow.get(parsed.row) ?? [];
    cols.push(parsed.col);
    byRow.set(parsed.row, cols);
  }

  const rowSegments = [...byRow.entries()]
    .map(([row, cols]) => ({
      row,
      segments: contiguousSegments([...new Set(cols)].sort((a, b) => a - b)),
    }))
    .sort((a, b) => a.row - b.row);
  const ranges: string[] = [];
  let active: {
    startRow: number;
    endRow: number;
    startCol: number;
    endCol: number;
  } | null = null;

  for (const rowSegment of rowSegments) {
    for (const segment of rowSegment.segments) {
      if (
        active &&
        rowSegment.row === active.endRow + 1 &&
        segment.start === active.startCol &&
        segment.end === active.endCol
      ) {
        active.endRow = rowSegment.row;
        continue;
      }

      if (active) {
        ranges.push(formatCompactRange(active));
      }

      active = {
        startRow: rowSegment.row,
        endRow: rowSegment.row,
        startCol: segment.start,
        endCol: segment.end,
      };
    }
  }

  if (active) {
    ranges.push(formatCompactRange(active));
  }

  return ranges;
}

export function addressesToBoundingRange(addresses: string[]): string {
  return formatRange(boundingRangeOf(addresses));
}

function groupAddressesByTable(
  labels: LabelledCellExample[],
  role: "value" | "header",
): Map<string, string[]> {
  const groups = new Map<string, string[]>();

  for (const label of labels) {
    if (label.role !== role || !label.table) {
      continue;
    }

    const addresses = groups.get(label.table) ?? [];
    addresses.push(label.address);
    groups.set(label.table, addresses);
  }

  return groups;
}

function contiguousSegments(
  values: number[],
): Array<{ start: number; end: number }> {
  if (values.length === 0) {
    return [];
  }

  const segments: Array<{ start: number; end: number }> = [];
  let start = values[0];
  let previous = values[0];

  for (const value of values.slice(1)) {
    if (value === previous + 1) {
      previous = value;
      continue;
    }

    segments.push({ start, end: previous });
    start = value;
    previous = value;
  }

  segments.push({ start, end: previous });
  return segments;
}

function formatCompactRange(range: {
  startRow: number;
  endRow: number;
  startCol: number;
  endCol: number;
}): string {
  const start = { row: range.startRow, col: range.startCol };
  const end = { row: range.endRow, col: range.endCol };

  if (start.row === end.row && start.col === end.col) {
    return `R${start.row}C${start.col}`;
  }

  return formatRange({ start, end });
}
