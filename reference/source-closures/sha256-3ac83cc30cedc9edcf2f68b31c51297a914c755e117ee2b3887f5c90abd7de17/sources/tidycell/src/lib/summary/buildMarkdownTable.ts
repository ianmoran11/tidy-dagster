import { formatCell, parseRange } from "@/lib/address";
import type { ParsedSheet, TidyCell } from "@/lib/workbook/types";

const MAX_TABLE_CONTEXT_ROWS = 80;
const MAX_TABLE_CONTEXT_COLUMNS = 40;

export function buildMarkdownTable(sheet: ParsedSheet): string {
  if (!sheet.usedRange) {
    return "";
  }

  const originalRange = parseRange(sheet.usedRange);
  const { range, truncated } = boundTableRange(originalRange);
  const cellsByAddress = new Map(
    sheet.cells.map((cell) => [cell.address, cell] as const),
  );
  const rows: string[] = [];

  for (let row = range.start.row; row <= range.end.row; row += 1) {
    const cells: string[] = [];

    for (let col = range.start.col; col <= range.end.col; col += 1) {
      const address = formatCell({ row, col });
      cells.push(buildMarkdownCell(address, cellsByAddress.get(address)));
    }

    rows.push(`| ${cells.join(" | ")} |`);
  }

  if (rows.length === 0) {
    return "";
  }

  const columnCount = range.end.col - range.start.col + 1;
  const separator = `|${Array.from({ length: columnCount }, () => "---|").join("")}`;
  const truncationMarker =
    "<!-- Table context truncated to a safe preview window -->";

  return [
    ...(truncated ? [truncationMarker] : []),
    rows[0],
    separator,
    ...rows.slice(1),
  ].join("\n");
}

function boundTableRange(range: ReturnType<typeof parseRange>): {
  range: ReturnType<typeof parseRange>;
  truncated: boolean;
} {
  const bounded = {
    start: range.start,
    end: {
      row: Math.min(
        range.end.row,
        range.start.row + MAX_TABLE_CONTEXT_ROWS - 1,
      ),
      col: Math.min(
        range.end.col,
        range.start.col + MAX_TABLE_CONTEXT_COLUMNS - 1,
      ),
    },
  };

  return {
    range: bounded,
    truncated:
      bounded.end.row !== range.end.row || bounded.end.col !== range.end.col,
  };
}

function buildMarkdownCell(
  address: string,
  cell: TidyCell | undefined,
): string {
  const meta = buildMetadata(address, cell);
  const value = applyMarkdownFormatting(compactValue(displayValue(cell)), cell);

  return [meta, value].filter(Boolean).join(" ");
}

function buildMetadata(address: string, cell: TidyCell | undefined): string {
  const attributes = compactAttributes(cell);

  if (attributes.length === 0) {
    return `[${address}]`;
  }

  return `[${address}|${attributes.join(",")}]`;
}

function compactAttributes(cell: TidyCell | undefined): string[] {
  const style = cell?.style;

  if (!style) {
    return [];
  }

  const attributes: string[] = [];

  if (typeof style.fontSize === "number" && style.fontSize !== 11) {
    attributes.push(`s:${style.fontSize}`);
  }

  if (style.horizontalAlign && style.horizontalAlign !== "general") {
    attributes.push(`a:${style.horizontalAlign.slice(0, 1)}`);
  }

  if (typeof style.fontIndent === "number" && style.fontIndent > 0) {
    attributes.push(`i:${style.fontIndent}`);
  }

  const fontColor = parseColor(style.fontColor);
  if (fontColor && fontColor.toUpperCase() !== "#000000") {
    attributes.push(`c:${fontColor}`);
  }

  return attributes;
}

function applyMarkdownFormatting(value: string, cell: TidyCell | undefined) {
  if (!value) {
    return value;
  }

  if (cell?.style?.bold && cell.style.italic) {
    return `***${value}***`;
  }

  if (cell?.style?.bold) {
    return `**${value}**`;
  }

  if (cell?.style?.italic) {
    return `*${value}*`;
  }

  return value;
}

function parseColor(value: string | undefined): string | undefined {
  if (!value) {
    return undefined;
  }

  const normalized = value.trim().replace(/^#/, "");

  if (/^[0-9a-f]{8}$/i.test(normalized)) {
    return `#${normalized.slice(2).toUpperCase()}`;
  }

  if (/^[0-9a-f]{6}$/i.test(normalized)) {
    return `#${normalized.toUpperCase()}`;
  }

  return undefined;
}

function displayValue(cell: TidyCell | undefined): string {
  if (!cell) {
    return "";
  }

  if (cell.formatted !== null && cell.formatted !== undefined) {
    return cell.formatted;
  }

  if (cell.value === null) {
    return "";
  }

  return String(cell.value);
}

function compactValue(value: string): string {
  return value
    .replaceAll("|", "\\|")
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
