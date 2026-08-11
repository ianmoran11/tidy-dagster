import {
  formatCell,
  formatRange,
  MAX_EXPANDED_RANGE_CELLS,
  parseCell,
  type CellAddress,
} from "@/lib/address";
import type { CellSelector } from "@/lib/recipe/types";

export const MAX_RECTANGLE_DECOMPOSITION_CELLS = MAX_EXPANDED_RANGE_CELLS;

export type SelectorCoverPart = {
  selector: string;
  start: CellAddress;
  end: CellAddress;
  width: number;
  height: number;
  cellCount: number;
};

export type SelectorDecomposition = {
  parts: SelectorCoverPart[];
  entries: string[];
  cellCount: number;
};

type ColumnRun = {
  start: number;
  end: number;
};

/**
 * Greedily covers a canonical R1C1 address set with disjoint rectangles.
 *
 * The next rectangle is always anchored at the remaining top-left cell. For
 * that anchor, the candidate with the greatest area wins; equal-area
 * candidates prefer the greater width. This top-left-then-width tie-break is
 * deterministic, produces stable row-major output, and compacts common sheet
 * stripes without attempting the NP-hard optimal rectangle-cover problem.
 */
export function decomposeSelectorAddresses(
  addresses: readonly string[],
): SelectorDecomposition {
  if (addresses.length > MAX_RECTANGLE_DECOMPOSITION_CELLS) {
    throw new RangeError(
      `Selector decomposition received ${addresses.length} entries, which exceeds the supported maximum of ${MAX_RECTANGLE_DECOMPOSITION_CELLS}.`,
    );
  }

  const columnsByRow = new Map<number, Set<number>>();
  for (const input of addresses) {
    const parsed = parseCell(input);
    if (input !== formatCell(parsed)) {
      throw new Error(
        `Expected a canonical R1C1 address like R3C4, received ${JSON.stringify(input)}.`,
      );
    }
    const columns = columnsByRow.get(parsed.row) ?? new Set<number>();
    columns.add(parsed.col);
    columnsByRow.set(parsed.row, columns);
  }

  const sortedRows = [...columnsByRow.keys()].sort(
    (left, right) => left - right,
  );
  const runsByRow = new Map<number, ColumnRun[]>(
    sortedRows.map((row) => [row, columnRuns(columnsByRow.get(row)!)]),
  );
  const parts: SelectorCoverPart[] = [];
  let rowIndex = 0;

  while (rowIndex < sortedRows.length) {
    const anchorRow = sortedRows[rowIndex]!;
    const anchorRuns = runsByRow.get(anchorRow)!;
    if (anchorRuns.length === 0) {
      rowIndex += 1;
      continue;
    }

    const anchorCol = anchorRuns[0]!.start;
    let narrowestWidth = Number.POSITIVE_INFINITY;
    let bestWidth = 1;
    let bestHeight = 1;
    let bestArea = 1;

    for (let row = anchorRow; ; row += 1) {
      const run = findContainingRun(runsByRow.get(row), anchorCol);
      if (run === undefined) break;

      const height = row - anchorRow + 1;
      narrowestWidth = Math.min(narrowestWidth, run.end - anchorCol + 1);
      const area = narrowestWidth * height;
      if (
        area > bestArea ||
        (area === bestArea && narrowestWidth > bestWidth)
      ) {
        bestArea = area;
        bestWidth = narrowestWidth;
        bestHeight = height;
      }
    }

    const endRow = anchorRow + bestHeight - 1;
    const endCol = anchorCol + bestWidth - 1;
    for (let row = anchorRow; row <= endRow; row += 1) {
      removeRunSegment(runsByRow.get(row)!, anchorCol, endCol);
    }

    const start = { row: anchorRow, col: anchorCol };
    const end = { row: endRow, col: endCol };
    parts.push({
      selector:
        bestArea === 1 ? formatCell(start) : formatRange({ start, end }),
      start,
      end,
      width: bestWidth,
      height: bestHeight,
      cellCount: bestArea,
    });
  }

  return {
    parts,
    entries: parts.map(({ selector }) => selector),
    cellCount: [...columnsByRow.values()].reduce(
      (count, columns) => count + columns.size,
      0,
    ),
  };
}

/** Serialize an exact address set using the additive RecipeV01 range union. */
export function selectorFromAddresses(
  addresses: readonly string[],
): CellSelector {
  const decomposition = decomposeSelectorAddresses(addresses);
  if (decomposition.parts.length === 1) {
    const only = decomposition.parts[0]!;
    if (only.cellCount > 1) return { range: only.selector };
  }
  return decomposition.entries;
}

function columnRuns(columns: ReadonlySet<number>): ColumnRun[] {
  const sorted = [...columns].sort((left, right) => left - right);
  const runs: ColumnRun[] = [];
  for (const column of sorted) {
    const previous = runs[runs.length - 1];
    if (previous !== undefined && column === previous.end + 1) {
      previous.end = column;
    } else {
      runs.push({ start: column, end: column });
    }
  }
  return runs;
}

function findContainingRun(
  runs: readonly ColumnRun[] | undefined,
  column: number,
): ColumnRun | undefined {
  if (runs === undefined) return undefined;
  let low = 0;
  let high = runs.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    const run = runs[middle]!;
    if (column < run.start) high = middle - 1;
    else if (column > run.end) low = middle + 1;
    else return run;
  }
  return undefined;
}

function removeRunSegment(runs: ColumnRun[], start: number, end: number): void {
  const index = runs.findIndex((run) => run.start <= start && run.end >= end);
  if (index < 0) {
    throw new Error(`Rectangle cover lost the segment C${start}:C${end}.`);
  }

  const run = runs[index]!;
  const replacement: ColumnRun[] = [];
  if (run.start < start) replacement.push({ start: run.start, end: start - 1 });
  if (end < run.end) replacement.push({ start: end + 1, end: run.end });
  runs.splice(index, 1, ...replacement);
}
