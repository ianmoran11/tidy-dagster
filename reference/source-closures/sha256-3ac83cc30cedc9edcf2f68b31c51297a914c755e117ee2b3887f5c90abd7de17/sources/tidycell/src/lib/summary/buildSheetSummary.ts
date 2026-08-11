import { formatCell, parseRange } from "@/lib/address";
import {
  CANDIDATE_BLOCK_DETECTOR_VERSION,
  detectCandidateBlocks,
} from "@/lib/recipe/detectCandidateBlocks";
import { buildHeaderCandidates } from "@/lib/summary/buildHeaderCandidates";
import { buildHtmlTable } from "@/lib/summary/buildHtmlTable";
import { buildMarkdownTable } from "@/lib/summary/buildMarkdownTable";
import type {
  BlankBand,
  BuildSheetSummaryOptions,
  CandidateRegion,
  SheetSummary,
  SummaryCell,
} from "@/lib/summary/types";
import type { ParsedSheet, TidyCell } from "@/lib/workbook/types";

const DEFAULT_MAX_CELLS = 80;
const DEFAULT_MAX_CONTEXT_CELLS = 30;
const DEFAULT_MAX_CHARS = 12_000;
const DEFAULT_MAX_MARKDOWN_CHARS = 24_000;
const DEFAULT_MAX_HTML_CHARS = 40_000;

export function buildSheetSummary(
  sheet: ParsedSheet,
  options: BuildSheetSummaryOptions = {},
): SheetSummary {
  const candidateRegions = findCandidateRegions(sheet);
  const candidateBlocks = detectCandidateBlocks(sheet);
  const dataRangeHintRegions = options.includeNumericStringCandidateRegions
    ? findNumericStringCandidateRegions(sheet)
    : undefined;
  const styleFingerprints = buildStyleFingerprints(sheet);
  const tableContextMode = options.tableContextMode ?? "markdown_compact";
  const markdownTable = buildMarkdownTable(sheet);
  const htmlTable =
    tableContextMode === "html_expanded" ? buildHtmlTable(sheet) : "";
  const cappedMarkdown = capText(
    markdownTable,
    options.maxMarkdownChars ?? DEFAULT_MAX_MARKDOWN_CHARS,
    "\n<!-- Markdown table truncated -->",
  );
  const cappedHtml = capText(
    htmlTable,
    options.maxHtmlChars ?? DEFAULT_MAX_HTML_CHARS,
    "\n<!-- HTML table truncated -->",
  );
  const contextCells = findContextCells(sheet, candidateRegions).slice(
    0,
    options.maxContextCells ?? DEFAULT_MAX_CONTEXT_CELLS,
  );
  const summary: SheetSummary = {
    sheet: sheet.name,
    checked: options.checked ?? true,
    usedRange: sheet.usedRange,
    rowCount: sheet.rowCount,
    columnCount: sheet.columnCount,
    nonEmptyCellCount: sheet.nonEmptyCellCount,
    cells: prioritizeCells(sheet, candidateRegions).slice(
      0,
      options.maxCells ?? DEFAULT_MAX_CELLS,
    ),
    dataTypes: countDataTypes(sheet.cells),
    merges: sheet.merges,
    styleFingerprints,
    blankRows: findBlankBands(sheet, "row"),
    blankColumns: findBlankBands(sheet, "column"),
    candidateRegions,
    candidateBlocks,
    candidateBlockEvidence: {
      detector_version: CANDIDATE_BLOCK_DETECTOR_VERSION,
      total_count: candidateBlocks.length,
      included_count: candidateBlocks.length,
      omitted_count: 0,
      truncated: false,
      role_hypotheses_are_authoritative: false,
    },
    contextCells,
    header_list: buildHeaderCandidates(sheet),
    table_context_format: tableContextMode,
    table_markdown: cappedMarkdown.text,
    table_markdown_truncated: cappedMarkdown.truncated,
    html_table: cappedHtml.text,
    html_table_truncated: cappedHtml.truncated,
    intent: options.intent,
    truncated: false,
    sizeChars: 0,
  };

  const capped = capSummary(summary, options.maxChars ?? DEFAULT_MAX_CHARS);
  return dataRangeHintRegions ? { ...capped, dataRangeHintRegions } : capped;
}

function capText(
  text: string,
  maxChars: number,
  suffix: string,
): { text: string; truncated: boolean } {
  if (text.length <= maxChars) {
    return { text, truncated: false };
  }

  return {
    text: `${text.slice(0, Math.max(0, maxChars))}${suffix}`,
    truncated: true,
  };
}

export function buildWorkbookSummaries(
  sheets: ParsedSheet[],
  checkedSheetNames: string[],
  options: Omit<BuildSheetSummaryOptions, "checked"> = {},
): SheetSummary[] {
  const checked = new Set(checkedSheetNames);

  return sheets
    .filter((sheet) => checked.has(sheet.name))
    .map((sheet) => buildSheetSummary(sheet, { ...options, checked: true }));
}

function capSummary(summary: SheetSummary, maxChars: number): SheetSummary {
  let capped = { ...summary, sizeChars: JSON.stringify(summary).length };

  if (capped.sizeChars <= maxChars) {
    return capped;
  }

  capped = { ...capped, truncated: true };

  while (capped.sizeChars > maxChars && capped.cells.length > 6) {
    capped = {
      ...capped,
      cells: capped.cells.slice(
        0,
        Math.max(6, Math.floor(capped.cells.length * 0.75)),
      ),
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  while (capped.sizeChars > maxChars && capped.contextCells.length > 3) {
    capped = {
      ...capped,
      contextCells: capped.contextCells.slice(
        0,
        Math.max(3, Math.floor(capped.contextCells.length * 0.75)),
      ),
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  while (capped.sizeChars > maxChars && capped.candidateRegions.length > 1) {
    capped = {
      ...capped,
      candidateRegions: capped.candidateRegions.slice(
        0,
        capped.candidateRegions.length - 1,
      ),
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  if (capped.sizeChars > maxChars) {
    capped = {
      ...capped,
      styleFingerprints: {},
    };
  }

  capped.sizeChars = JSON.stringify(capped).length;

  if (capped.sizeChars > maxChars && capped.table_markdown.length > 1_000) {
    capped = {
      ...capped,
      table_markdown: `${capped.table_markdown.slice(
        0,
        Math.min(1_000, capped.table_markdown.length),
      )}\n<!-- Markdown table truncated -->`,
      table_markdown_truncated: true,
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  if (capped.sizeChars > maxChars && capped.table_markdown.length > 0) {
    capped = {
      ...capped,
      table_markdown: "<!-- Markdown table omitted after truncation -->",
      table_markdown_truncated: true,
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  if (capped.sizeChars > maxChars && capped.html_table.length > 1_000) {
    capped = {
      ...capped,
      html_table: `${capped.html_table.slice(
        0,
        Math.min(1_000, capped.html_table.length),
      )}\n<!-- HTML table truncated -->`,
      html_table_truncated: true,
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  if (capped.sizeChars > maxChars && capped.html_table.length > 0) {
    capped = {
      ...capped,
      html_table: "<!-- HTML table omitted after truncation -->",
      html_table_truncated: true,
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  while (capped.sizeChars > maxChars && capped.header_list.length > 3) {
    capped = {
      ...capped,
      header_list: capped.header_list.slice(
        0,
        Math.max(3, Math.floor(capped.header_list.length * 0.75)),
      ),
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  while (capped.sizeChars > maxChars && capped.header_list.length > 1) {
    capped = {
      ...capped,
      header_list: capped.header_list.slice(0, capped.header_list.length - 1),
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  while (capped.sizeChars > maxChars && capped.contextCells.length > 0) {
    capped = {
      ...capped,
      contextCells: capped.contextCells.slice(
        0,
        capped.contextCells.length - 1,
      ),
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  while (capped.sizeChars > maxChars && capped.cells.length > 1) {
    capped = {
      ...capped,
      cells: capped.cells.slice(0, capped.cells.length - 1),
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  while (
    capped.sizeChars > maxChars &&
    (capped.candidateBlocks?.length ?? 0) > 0
  ) {
    const candidateBlocks = capped.candidateBlocks!.slice(0, -1);
    const totalCount = capped.candidateBlockEvidence?.total_count ?? 0;
    capped = {
      ...capped,
      candidateBlocks,
      candidateBlockEvidence: {
        detector_version: CANDIDATE_BLOCK_DETECTOR_VERSION,
        total_count: totalCount,
        included_count: candidateBlocks.length,
        omitted_count: totalCount - candidateBlocks.length,
        truncated: true,
        role_hypotheses_are_authoritative: false,
      },
      truncated: true,
    };
    capped.sizeChars = JSON.stringify(capped).length;
  }

  capped.sizeChars = JSON.stringify(capped).length;
  return capped;
}

function prioritizeCells(
  sheet: ParsedSheet,
  candidateRegions: CandidateRegion[],
): SummaryCell[] {
  const candidateRanges = candidateRegions.map((region) =>
    parseRange(region.range),
  );

  return [...sheet.cells]
    .sort(
      (left, right) =>
        cellPriority(left, candidateRanges) -
        cellPriority(right, candidateRanges),
    )
    .map(toSummaryCell);
}

function cellPriority(
  cell: TidyCell,
  candidateRanges: ReturnType<typeof parseRange>[],
): number {
  if (isCellInRanges(cell, candidateRanges)) {
    return cell.row * 1000 + cell.col;
  }

  if (cell.data_type === "string") {
    return 1_000_000 + cell.row * 1000 + cell.col;
  }

  return 2_000_000 + cell.row * 1000 + cell.col;
}

function findCandidateRegions(sheet: ParsedSheet): CandidateRegion[] {
  const numericCells = sheet.cells.filter(
    (cell) => cell.data_type === "numeric",
  );

  return numericCells.length > 0 ? [boundingCandidateRegion(numericCells)] : [];
}

function findNumericStringCandidateRegions(
  sheet: ParsedSheet,
): CandidateRegion[] {
  const numericStringCells = sheet.cells.filter(
    (cell) =>
      cell.data_type === "string" &&
      isNumericLikeValue(String(cell.formatted ?? cell.value ?? "")),
  );
  const cellsByPosition = new Map(
    numericStringCells.map((cell) => [`${cell.row}:${cell.col}`, cell]),
  );
  const remaining = new Set(cellsByPosition.keys());
  const components: TidyCell[][] = [];

  while (remaining.size > 0) {
    const first = remaining.values().next().value as string;
    const queue = [first];
    const component: TidyCell[] = [];
    remaining.delete(first);

    while (queue.length > 0) {
      const key = queue.shift();
      if (!key) continue;
      const cell = cellsByPosition.get(key);
      if (!cell) continue;
      component.push(cell);

      for (const neighbor of [
        `${cell.row - 1}:${cell.col}`,
        `${cell.row + 1}:${cell.col}`,
        `${cell.row}:${cell.col - 1}`,
        `${cell.row}:${cell.col + 1}`,
      ]) {
        if (!remaining.delete(neighbor)) continue;
        queue.push(neighbor);
      }
    }

    components.push(component);
  }

  return components
    .filter((component) => {
      if (component.length < 2) return false;
      const rows = component.map((cell) => cell.row);
      return Math.max(...rows) > Math.min(...rows);
    })
    .sort((left, right) => right.length - left.length)
    .slice(0, 8)
    .map(boundingCandidateRegion);
}

function boundingCandidateRegion(cells: TidyCell[]): CandidateRegion {
  let minRow = cells[0].row;
  let maxRow = cells[0].row;
  let minCol = cells[0].col;
  let maxCol = cells[0].col;

  for (const cell of cells) {
    minRow = Math.min(minRow, cell.row);
    maxRow = Math.max(maxRow, cell.row);
    minCol = Math.min(minCol, cell.col);
    maxCol = Math.max(maxCol, cell.col);
  }

  return {
    range: `${formatCell({ row: minRow, col: minCol })}:${formatCell({
      row: maxRow,
      col: maxCol,
    })}`,
    rowCount: maxRow - minRow + 1,
    columnCount: maxCol - minCol + 1,
    numericCellCount: cells.length,
  };
}

function isNumericLikeValue(value: string): boolean {
  const normalized = value.replace(/\s+/g, "").trim();
  return /^\(?[-+]?(?:[$£€])?(?:\d{1,3}(?:,\d{3})+|\d+|\d*\.\d+)%?\)?$/.test(
    normalized,
  );
}

function findContextCells(
  sheet: ParsedSheet,
  candidateRegions: CandidateRegion[],
): SummaryCell[] {
  const candidateRanges = candidateRegions.map((region) =>
    parseRange(region.range),
  );

  return sheet.cells
    .filter((cell) => !isCellInRanges(cell, candidateRanges))
    .filter((cell) => cell.data_type === "string" || Boolean(cell.comment))
    .map(toSummaryCell);
}

function buildStyleFingerprints(sheet: ParsedSheet): Record<string, unknown> {
  const fingerprints: Record<string, unknown> = {};

  for (const cell of sheet.cells) {
    if (!cell.style) {
      continue;
    }

    const styleJson = stableJson(cell.style);
    const styleId = `s_${hashString(styleJson)}`;
    fingerprints[styleId] = cell.style;
  }

  return fingerprints;
}

function countDataTypes(sheetCells: TidyCell[]): SheetSummary["dataTypes"] {
  const counts: SheetSummary["dataTypes"] = {};

  for (const cell of sheetCells) {
    counts[cell.data_type] = (counts[cell.data_type] ?? 0) + 1;
  }

  return counts;
}

function findBlankBands(
  sheet: ParsedSheet,
  axis: "row" | "column",
): BlankBand[] {
  const occupied = new Set(
    sheet.cells
      .filter((cell) => cell.data_type !== "blank")
      .map((cell) => (axis === "row" ? cell.row : cell.col)),
  );
  const max = axis === "row" ? sheet.rowCount : sheet.columnCount;
  const bands: BlankBand[] = [];
  let start: number | undefined;

  for (let index = 1; index <= max; index += 1) {
    if (!occupied.has(index) && start === undefined) {
      start = index;
    }

    if ((occupied.has(index) || index === max) && start !== undefined) {
      const end = occupied.has(index) ? index - 1 : index;

      if (end >= start) {
        bands.push({ start, end });
      }

      start = undefined;
    }
  }

  return bands;
}

function toSummaryCell(cell: TidyCell): SummaryCell {
  return {
    address: cell.address,
    row: cell.row,
    col: cell.col,
    value: cell.value,
    data_type: cell.data_type,
    formatted: cell.formatted,
    style_id: cell.style
      ? `s_${hashString(stableJson(cell.style))}`
      : undefined,
    has_formula: Boolean(cell.formula),
    has_comment: Boolean(cell.comment),
  };
}

function isCellInRanges(
  cell: TidyCell,
  ranges: ReturnType<typeof parseRange>[],
): boolean {
  return ranges.some(
    (range) =>
      cell.row >= range.start.row &&
      cell.row <= range.end.row &&
      cell.col >= range.start.col &&
      cell.col <= range.end.col,
  );
}

export function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map(stableJson).join(",")}]`;
  }

  return `{${Object.entries(value)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, nested]) => `${JSON.stringify(key)}:${stableJson(nested)}`)
    .join(",")}}`;
}

export function hashString(input: string): string {
  let hash = 2166136261;

  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }

  return (hash >>> 0).toString(36);
}
