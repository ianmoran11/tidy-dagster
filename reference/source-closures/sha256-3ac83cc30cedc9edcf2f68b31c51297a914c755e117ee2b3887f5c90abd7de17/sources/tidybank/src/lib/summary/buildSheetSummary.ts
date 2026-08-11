import type { CellDataType, ParsedSheet, TidyCell } from "@/lib/workbook/types";

export type SheetSummary = {
  name: string;
  usedRange: string | null;
  rowCount: number;
  columnCount: number;
  nonEmptyCellCount: number;
  dataTypeCounts: Record<CellDataType, number>;
  mergeCount: number;
  headerCandidateRows: number[];
};

type RowStats = {
  row: number;
  nonBlank: number;
  string: number;
  numeric: number;
};

/**
 * Builds the deliberately small v0 sheet summary. Header candidates are
 * examined from top to bottom: a row must have a strict majority of string
 * cells among its non-blank cells, while the next populated row below it has
 * a strict numeric majority. Blank-only rows are skipped, ties are not
 * majorities, and at most the first five matching rows are returned.
 */
export function buildSheetSummary(sheet: ParsedSheet): SheetSummary {
  return {
    name: sheet.name,
    usedRange: sheet.usedRange,
    rowCount: sheet.rowCount,
    columnCount: sheet.columnCount,
    nonEmptyCellCount: sheet.nonEmptyCellCount,
    dataTypeCounts:
      sheet.workspaceSummary?.dataTypeCounts ?? countDataTypes(sheet.cells),
    mergeCount: sheet.workspaceSummary?.mergeCount ?? sheet.merges.length,
    headerCandidateRows:
      sheet.workspaceSummary?.headerCandidateRows ??
      findHeaderCandidateRows(sheet.cells),
  };
}

function countDataTypes(cells: TidyCell[]): Record<CellDataType, number> {
  const counts: Record<CellDataType, number> = {
    blank: 0,
    string: 0,
    numeric: 0,
    boolean: 0,
    date: 0,
    error: 0,
  };

  for (const cell of cells) {
    counts[cell.data_type] += 1;
  }

  return counts;
}

function findHeaderCandidateRows(cells: TidyCell[]): number[] {
  const statsByRow = new Map<number, RowStats>();

  for (const cell of cells) {
    if (cell.data_type === "blank") {
      continue;
    }

    const stats = statsByRow.get(cell.row) ?? {
      row: cell.row,
      nonBlank: 0,
      string: 0,
      numeric: 0,
    };

    stats.nonBlank += 1;
    if (cell.data_type === "string") {
      stats.string += 1;
    } else if (cell.data_type === "numeric") {
      stats.numeric += 1;
    }
    statsByRow.set(cell.row, stats);
  }

  const rows = [...statsByRow.values()].sort(
    (left, right) => left.row - right.row,
  );
  const candidates: number[] = [];

  for (let index = 0; index < rows.length - 1; index += 1) {
    const row = rows[index];
    const nextRow = rows[index + 1];

    if (!row || !nextRow) {
      continue;
    }

    const isStringMajority = row.string * 2 > row.nonBlank;
    const nextRowIsNumericMajority = nextRow.numeric * 2 > nextRow.nonBlank;

    if (isStringMajority && nextRowIsNumericMajority) {
      candidates.push(row.row);
      if (candidates.length === 5) {
        break;
      }
    }
  }

  return candidates;
}
