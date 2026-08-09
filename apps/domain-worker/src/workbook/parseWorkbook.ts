/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import ExcelJS from "exceljs";
import { formatCell, parseA1Cell, parseA1Range } from "../address.js";
import type {
  CellDataType,
  CellMergeSummary,
  CellStyleSummary,
  ParsedMergeRange,
  ParsedSheet,
  TidyCell,
  WorkbookParseResult,
} from "./types.js";

type CellContent = {
  value: string | number | boolean | null;
  dataType: CellDataType;
  formula?: string | null;
  hyperlink?: string | null;
};

type MergeIndex = {
  merges: ParsedMergeRange[];
  byAddress: Map<string, CellMergeSummary>;
};

type XlsxLoadInput = Parameters<ExcelJS.Workbook["xlsx"]["load"]>[0];

const MAX_EXPANDED_MERGE_CELLS = 10_000;

export async function parseWorkbook(
  input: ArrayBuffer | Uint8Array,
): Promise<WorkbookParseResult> {
  try {
    const workbook = new ExcelJS.Workbook();
    await workbook.xlsx.load(toUint8Array(input) as unknown as XlsxLoadInput);

    const sheetNames = workbook.worksheets.map((s) => s.name);
    const sheets: ParsedSheet[] = [];

    for (const name of sheetNames) {
      const worksheet = workbook.getWorksheet(name);
      if (worksheet) {
        sheets.push(parseExcelJsWorksheet(worksheet));
      }
      collectGarbage();
    }

    return {
      ok: true,
      workbook: {
        sheets,
      },
    };
  } catch (error) {
    return {
      ok: false,
      errors: [
        {
          code: "INVALID_WORKBOOK",
          message:
            error instanceof Error
              ? error.message
              : "The uploaded workbook could not be parsed.",
        },
      ],
    };
  }
}

function collectGarbage(): void {
  const globalWithGc = globalThis as typeof globalThis & { gc?: () => void };
  if (typeof globalWithGc.gc === "function") {
    globalWithGc.gc();
  }
}

export function parseExcelJsWorksheet(
  worksheet: ExcelJS.Worksheet,
): ParsedSheet {
  const mergeIndex = buildMergeIndex(worksheet);
  const cells: TidyCell[] = [];

  const modelRows = (worksheet as { model?: WorksheetModel }).model?.rows ?? [];

  for (const modelRow of modelRows) {
    const rowNumber = modelRow.number;

    if (typeof rowNumber !== "number" || rowNumber < 1) {
      continue;
    }

    for (const cell of modelRow.cells ?? []) {
      if (!cell) {
        continue;
      }

      const address = typeof cell.address === "string" ? cell.address : "";

      if (!address) {
        continue;
      }

      try {
        const parsed = parseA1Cell(address);
        const r1c1 = formatCell(parsed);
        const merge = mergeIndex.byAddress.get(r1c1) ?? null;

        // Model cells strip formula results and comments. When the value is
        // null or undefined, resolve the full cell via worksheet.getCell() so
        // that formulas, styled blanks, and comments are not lost.
        const resolved =
          cell.value === null || cell.value === undefined
            ? worksheet.getCell(parsed.row, parsed.col)
            : cell;

        const content =
          merge?.role === "child"
            ? { value: null, dataType: "blank" as const }
            : parseCellContent(resolved.value);
        // ExcelJS aliases getCell() reads (row/col text included) to the merge
        // master for every cell in a merged range, so a child cell's `resolved`
        // would otherwise report the master's displayed text.
        const formatted =
          merge?.role === "child" ? null : safeCellText(resolved);
        const comment = extractComment(resolved.note);
        const style = summarizeStyle(resolved.style);
        const hyperlink = content.hyperlink ?? extractHyperlink(resolved);

        if (
          !isMeaningfulCell(
            content,
            formatted,
            comment,
            hyperlink,
            style,
            merge,
          )
        ) {
          continue;
        }

        cells.push({
          sheet: worksheet.name,
          address: r1c1,
          row: parsed.row,
          col: parsed.col,
          value: content.value,
          data_type: content.dataType,
          formula: content.formula ?? null,
          formatted,
          comment,
          hyperlink,
          style,
          merge,
        });
      } catch {
        // Ignore cells whose address cannot be parsed.
      }
    }
  }

  const { rowCount, columnCount } = getWorksheetBounds(
    cells,
    mergeIndex.merges,
  );

  return {
    name: worksheet.name,
    usedRange: getUsedRange(cells),
    rowCount,
    columnCount,
    nonEmptyCellCount: cells.filter((cell) => cell.data_type !== "blank")
      .length,
    cells,
    merges: mergeIndex.merges,
  };
}

function parseCellContent(rawValue: unknown): CellContent {
  if (isFormulaValue(rawValue)) {
    const result = parseCellContent(rawValue.result ?? null);

    return {
      ...result,
      formula: rawValue.formula ?? rawValue.sharedFormula ?? null,
    };
  }

  if (isHyperlinkValue(rawValue)) {
    return {
      dataType: "string",
      hyperlink: rawValue.hyperlink,
      value: rawValue.text,
    };
  }

  if (isRichTextValue(rawValue)) {
    return {
      dataType: "string",
      value: rawValue.richText.map((part) => part.text).join(""),
    };
  }

  if (isErrorValue(rawValue)) {
    return {
      dataType: "error",
      value: rawValue.error,
    };
  }

  if (rawValue instanceof Date) {
    return {
      dataType: "date",
      value: rawValue.toISOString(),
    };
  }

  switch (typeof rawValue) {
    case "string":
      return { dataType: "string", value: rawValue };
    case "number":
      return { dataType: "numeric", value: rawValue };
    case "boolean":
      return { dataType: "boolean", value: rawValue };
    default:
      return { dataType: "blank", value: null };
  }
}

function buildMergeIndex(worksheet: ExcelJS.Worksheet): MergeIndex {
  const merges = extractMergeRanges(worksheet);
  const byAddress = new Map<string, CellMergeSummary>();
  const parsedMerges = merges.map((range) => {
    const parsed = parseA1Range(range);
    return {
      parent: formatCell(parsed.start),
      range: `${formatCell(parsed.start)}:${formatCell(parsed.end)}`,
      parsed,
    };
  });

  for (const merge of parsedMerges) {
    const area =
      (merge.parsed.end.row - merge.parsed.start.row + 1) *
      (merge.parsed.end.col - merge.parsed.start.col + 1);

    if (area > MAX_EXPANDED_MERGE_CELLS) {
      byAddress.set(merge.parent, {
        parent: merge.parent,
        range: merge.range,
        role: "parent",
      });
      continue;
    }

    for (
      let row = merge.parsed.start.row;
      row <= merge.parsed.end.row;
      row += 1
    ) {
      for (
        let col = merge.parsed.start.col;
        col <= merge.parsed.end.col;
        col += 1
      ) {
        const address = formatCell({ row, col });
        byAddress.set(address, {
          parent: merge.parent,
          range: merge.range,
          role: address === merge.parent ? "parent" : "child",
        });
      }
    }
  }

  return {
    byAddress,
    merges: parsedMerges.map((merge) => ({
      parent: merge.parent,
      range: merge.range,
    })),
  };
}

function extractMergeRanges(worksheet: ExcelJS.Worksheet): string[] {
  const model = worksheet.model as { merges?: string[] };
  return model.merges ?? [];
}

type WorksheetModel = {
  rows?: WorksheetModelRow[];
};

type WorksheetModelRow = {
  number?: number;
  cells?: Array<ExcelJS.Cell | undefined>;
};

function getWorksheetBounds(
  cells: TidyCell[],
  merges: ParsedMergeRange[],
): { rowCount: number; columnCount: number } {
  let rowCount = 0;
  let columnCount = 0;

  for (const cell of cells) {
    rowCount = Math.max(rowCount, cell.row);
    columnCount = Math.max(columnCount, cell.col);
  }

  for (const merge of merges) {
    const range = merge.range.split(":");
    const end = range[1];

    if (!end) {
      continue;
    }

    const endMatch = /^R(\d+)C(\d+)$/.exec(end);

    if (!endMatch) {
      continue;
    }

    rowCount = Math.max(rowCount, Number(endMatch[1]));
    columnCount = Math.max(columnCount, Number(endMatch[2]));
  }

  return { rowCount, columnCount };
}

function getUsedRange(cells: TidyCell[]): string | null {
  if (cells.length === 0) {
    return null;
  }

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

  return `${formatCell({ row: minRow, col: minCol })}:${formatCell({ row: maxRow, col: maxCol })}`;
}

function summarizeStyle(
  style: Partial<ExcelJS.Style>,
): CellStyleSummary | undefined {
  const summary: CellStyleSummary = {};
  const styleRecord = asRecord(style);
  const font = asRecord(styleRecord?.font);
  const fill = asRecord(styleRecord?.fill);
  const alignment = asRecord(styleRecord?.alignment);
  const border = asRecord(styleRecord?.border);

  if (font?.bold === true) {
    summary.bold = true;
  }

  if (font?.italic === true) {
    summary.italic = true;
  }

  if (font?.underline === true || typeof font?.underline === "string") {
    summary.underline = true;
  }

  if (typeof font?.size === "number") {
    summary.fontSize = font.size;
  }

  const fontColor = colorToString(font?.color);
  if (fontColor) {
    summary.fontColor = fontColor;
  }

  const fillColor = colorToString(fill?.fgColor);
  if (fillColor) {
    summary.fillColor = fillColor;
  }

  if (typeof alignment?.horizontal === "string") {
    summary.horizontalAlign = alignment.horizontal;
  }

  if (typeof alignment?.indent === "number" && alignment.indent > 0) {
    summary.fontIndent = alignment.indent;
  }

  if (typeof alignment?.vertical === "string") {
    summary.verticalAlign = alignment.vertical;
  }

  const borderSummary = {
    top: hasBorder(border?.top),
    right: hasBorder(border?.right),
    bottom: hasBorder(border?.bottom),
    left: hasBorder(border?.left),
  };

  if (Object.values(borderSummary).some(Boolean)) {
    summary.border = borderSummary;
  }

  return Object.keys(summary).length > 0 ? summary : undefined;
}

function isMeaningfulCell(
  content: CellContent,
  formatted: string | null,
  comment: string | null,
  hyperlink: string | null,
  style: CellStyleSummary | undefined,
  merge: CellMergeSummary | null,
): boolean {
  return (
    content.dataType !== "blank" ||
    Boolean(formatted) ||
    Boolean(comment) ||
    Boolean(hyperlink) ||
    Boolean(style) ||
    Boolean(merge)
  );
}

function extractComment(note: unknown): string | null {
  if (typeof note === "string") {
    return note;
  }

  const noteRecord = asRecord(note);

  if (!noteRecord) {
    return null;
  }

  if (typeof noteRecord.text === "string") {
    return noteRecord.text;
  }

  const texts = noteRecord.texts;

  if (Array.isArray(texts)) {
    const text = texts
      .map((part) => asRecord(part)?.text)
      .filter((part): part is string => typeof part === "string")
      .join("");

    return text.length > 0 ? text : null;
  }

  return null;
}

function extractHyperlink(cell: ExcelJS.Cell): string | null {
  const cellRecord = cell as unknown as Record<string, unknown>;
  const hyperlink = cellRecord.hyperlink;

  return typeof hyperlink === "string" ? hyperlink : null;
}

function normalizeOptionalString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function safeCellText(cell: ExcelJS.Cell): string | null {
  try {
    return normalizeOptionalString(cell.text);
  } catch {
    return null;
  }
}

function colorToString(value: unknown): string | undefined {
  const color = asRecord(value);

  if (!color) {
    return undefined;
  }

  if (typeof color.argb === "string") {
    return color.argb;
  }

  if (typeof color.rgb === "string") {
    return color.rgb;
  }

  if (typeof color.theme === "number") {
    return `theme:${color.theme}`;
  }

  if (typeof color.indexed === "number") {
    return `indexed:${color.indexed}`;
  }

  return undefined;
}

function hasBorder(value: unknown): boolean {
  const border = asRecord(value);
  return typeof border?.style === "string" && border.style.length > 0;
}

function isFormulaValue(value: unknown): value is {
  formula?: string;
  sharedFormula?: string;
  result?: unknown;
} {
  const record = asRecord(value);
  return Boolean(
    record &&
      (typeof record.formula === "string" ||
        typeof record.sharedFormula === "string"),
  );
}

function isHyperlinkValue(value: unknown): value is {
  text: string;
  hyperlink: string;
} {
  const record = asRecord(value);
  return (
    typeof record?.text === "string" && typeof record.hyperlink === "string"
  );
}

function isRichTextValue(value: unknown): value is {
  richText: Array<{ text: string }>;
} {
  const record = asRecord(value);

  if (!Array.isArray(record?.richText)) {
    return false;
  }

  return record.richText.every(
    (part) => typeof asRecord(part)?.text === "string",
  );
}

function isErrorValue(value: unknown): value is { error: string } {
  const record = asRecord(value);
  return typeof record?.error === "string";
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

function toUint8Array(input: ArrayBuffer | Uint8Array): Uint8Array {
  return input instanceof Uint8Array ? input : new Uint8Array(input);
}
