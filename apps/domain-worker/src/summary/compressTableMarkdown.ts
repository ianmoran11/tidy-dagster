/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import type { CandidateRegion } from "./types.js";

export type TableMarkdownCompressionOptions = {
  collapseBlankRows?: boolean;
  collapseBlankColumns?: boolean;
  collapseRepeatedRows?: boolean;
  cellCharCap?: number;
  rowSampling?:
    | boolean
    | {
        firstRows?: number;
        lastRows?: number;
        boundaryPadding?: number;
      };
  candidateRegions?: CandidateRegion[];
};

type MarkdownRow = {
  line: string;
  cells: string[];
  rowIndex: number | null;
  isSeparator: boolean;
};

const DEFAULT_CELL_CHAR_CAP = 80;
const ELLIPSIS = "…";

export function compressTableMarkdown(
  markdown: string,
  options: TableMarkdownCompressionOptions = {},
): string {
  if (!markdown || Object.keys(options).length === 0) return markdown;

  let rows = parseMarkdownRows(markdown);

  if (options.cellCharCap !== undefined) {
    rows = rows
      .map((row) => ({
        ...row,
        cells: row.cells.map((cell) =>
          capCellText(cell, options.cellCharCap ?? DEFAULT_CELL_CHAR_CAP),
        ),
      }))
      .map(materializeRow);
  }

  if (options.collapseBlankColumns) {
    rows = collapseBlankColumns(rows);
  }

  if (options.collapseBlankRows) {
    rows = collapseBlankRows(rows);
  }

  if (options.collapseRepeatedRows) {
    rows = collapseRepeatedRows(rows);
  }

  if (options.rowSampling) {
    rows = sampleRows(rows, options);
  }

  return rows.map((row) => row.line).join("\n");
}

export function parseMarkdownRows(markdown: string): MarkdownRow[] {
  return markdown.split(/\r?\n/).map((line, index) => {
    const cells = splitMarkdownCells(line);
    return {
      line,
      cells,
      rowIndex: extractRowIndex(line) ?? index + 1,
      isSeparator: isSeparatorLine(line),
    };
  });
}

function splitMarkdownCells(line: string): string[] {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) return [line];
  return trimmed
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
}

function materializeRow(row: MarkdownRow): MarkdownRow {
  if (row.cells.length <= 1 && !row.line.trim().startsWith("|")) {
    return { ...row, line: row.cells[0] ?? row.line };
  }
  return { ...row, line: `| ${row.cells.join(" | ")} |` };
}

function extractRowIndex(line: string): number | null {
  const rows = [...line.matchAll(/R(\d+)C\d+/gi)].map((match) =>
    Number(match[1]),
  );
  const finite = rows.filter(Number.isFinite);
  return finite.length > 0 ? Math.min(...finite) : null;
}

function isSeparatorLine(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function cellSemanticText(cell: string): string {
  return cell
    .replace(/\[?R\d+C\d+\]?/gi, "")
    .replace(/[|\-:]/g, "")
    .trim();
}

function isBlankDataRow(row: MarkdownRow): boolean {
  return (
    !row.isSeparator &&
    row.cells.length > 1 &&
    row.cells.every((cell) => cellSemanticText(cell) === "")
  );
}

function collapseBlankRows(rows: MarkdownRow[]): MarkdownRow[] {
  const result: MarkdownRow[] = [];
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    if (!row || !isBlankDataRow(row)) {
      if (row) result.push(row);
      continue;
    }

    let end = index;
    while (end + 1 < rows.length && isBlankDataRow(rows[end + 1]!)) end += 1;
    const count = end - index + 1;
    if (count >= 3) {
      result.push(
        annotationRow(
          `… rows ${rows[index]?.rowIndex ?? index + 1}–${rows[end]?.rowIndex ?? end + 1} blank …`,
        ),
      );
    } else {
      result.push(...rows.slice(index, end + 1));
    }
    index = end;
  }
  return result;
}

function normalizedRow(row: MarkdownRow): string {
  return row.cells
    .map((cell) => cellSemanticText(cell).toLowerCase())
    .join("|");
}

function collapseRepeatedRows(rows: MarkdownRow[]): MarkdownRow[] {
  const result: MarkdownRow[] = [];
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    if (!row || row.isSeparator || row.cells.length <= 1) {
      if (row) result.push(row);
      continue;
    }

    const normalized = normalizedRow(row);
    let end = index;
    while (
      end + 1 < rows.length &&
      !rows[end + 1]!.isSeparator &&
      normalizedRow(rows[end + 1]!) === normalized
    ) {
      end += 1;
    }

    const count = end - index + 1;
    if (count >= 3) {
      result.push(row);
      result.push(
        annotationRow(
          `… rows ${rows[index]?.rowIndex ?? index + 1}–${rows[end]?.rowIndex ?? end + 1} repeat previous row ${count - 1} more times …`,
        ),
      );
    } else {
      result.push(...rows.slice(index, end + 1));
    }
    index = end;
  }
  return result;
}

function collapseBlankColumns(rows: MarkdownRow[]): MarkdownRow[] {
  const tableRows = rows.filter(
    (row) => row.cells.length > 1 && !row.isSeparator,
  );
  const maxColumns = Math.max(0, ...tableRows.map((row) => row.cells.length));
  const blankColumns: boolean[] = [];

  for (let col = 0; col < maxColumns; col += 1) {
    blankColumns[col] =
      tableRows.length > 0 &&
      tableRows.every((row) => cellSemanticText(row.cells[col] ?? "") === "");
  }

  const runs: Array<{ start: number; end: number }> = [];
  for (let col = 0; col < blankColumns.length; col += 1) {
    if (!blankColumns[col]) continue;
    let end = col;
    while (blankColumns[end + 1]) end += 1;
    if (end - col + 1 >= 3) runs.push({ start: col, end });
    col = end;
  }

  if (runs.length === 0) return rows;

  return rows.map((row) => {
    if (row.cells.length <= 1) return row;
    const cells: string[] = [];
    for (let col = 0; col < row.cells.length; col += 1) {
      const run = runs.find((candidate) => candidate.start === col);
      if (run) {
        cells.push(`… columns C${run.start + 1}–C${run.end + 1} blank …`);
        col = run.end;
      } else if (
        !runs.some((candidate) => col > candidate.start && col <= candidate.end)
      ) {
        cells.push(row.cells[col] ?? "");
      }
    }
    return materializeRow({ ...row, cells });
  });
}

function capCellText(cell: string, maxChars: number): string {
  if (!Number.isFinite(maxChars) || maxChars <= 0 || cell.length <= maxChars)
    return cell;
  return `${cell.slice(0, Math.max(0, maxChars - ELLIPSIS.length))}${ELLIPSIS}`;
}

function sampleRows(
  rows: MarkdownRow[],
  options: TableMarkdownCompressionOptions,
): MarkdownRow[] {
  const sampling =
    typeof options.rowSampling === "object" ? options.rowSampling : {};
  const firstRows = sampling.firstRows ?? 12;
  const lastRows = sampling.lastRows ?? 8;
  const boundaryPadding = sampling.boundaryPadding ?? 2;
  const dataRows = rows.filter(
    (row) => !row.isSeparator && row.cells.length > 1,
  );
  if (dataRows.length <= firstRows + lastRows + 6) return rows;

  const keep = new Set<MarkdownRow>();
  rows.forEach((row) => {
    if (row.isSeparator || row.cells.length <= 1) keep.add(row);
  });
  dataRows.slice(0, firstRows).forEach((row) => keep.add(row));
  dataRows.slice(-lastRows).forEach((row) => keep.add(row));

  const boundaries = (options.candidateRegions ?? []).flatMap((region) =>
    rangeRows(region.range),
  );
  for (const row of dataRows) {
    const rowIndex = row.rowIndex ?? 0;
    if (
      boundaries.some(
        (boundary) => Math.abs(rowIndex - boundary) <= boundaryPadding,
      )
    ) {
      keep.add(row);
    }
  }

  const result: MarkdownRow[] = [];
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index]!;
    if (keep.has(row)) {
      result.push(row);
      continue;
    }

    let end = index;
    while (end + 1 < rows.length && !keep.has(rows[end + 1]!)) end += 1;
    result.push(
      annotationRow(
        `… rows ${rows[index]?.rowIndex ?? index + 1}–${rows[end]?.rowIndex ?? end + 1} elided by sampling …`,
      ),
    );
    index = end;
  }
  return result;
}

function rangeRows(range: string): number[] {
  const match = /^R(\d+)C\d+(?::R(\d+)C\d+)?$/i.exec(range.trim());
  if (!match) return [];
  return [Number(match[1]), Number(match[2] ?? match[1])].filter(
    Number.isFinite,
  );
}

function annotationRow(text: string): MarkdownRow {
  return {
    line: `| ${text} |`,
    cells: [text],
    rowIndex: null,
    isSeparator: false,
  };
}
