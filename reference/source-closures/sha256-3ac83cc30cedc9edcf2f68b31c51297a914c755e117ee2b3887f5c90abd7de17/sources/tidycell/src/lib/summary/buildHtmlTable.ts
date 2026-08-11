import { formatCell, parseRange } from "@/lib/address";
import type { ParsedSheet, TidyCell } from "@/lib/workbook/types";

const MAX_TABLE_CONTEXT_ROWS = 80;
const MAX_TABLE_CONTEXT_COLUMNS = 40;

export function buildHtmlTable(sheet: ParsedSheet): string {
  if (!sheet.usedRange) {
    return `<table data-sheet="${escapeAttribute(sheet.name)}"></table>`;
  }

  const originalRange = parseRange(sheet.usedRange);
  const { range, truncated } = boundTableRange(originalRange);
  const cellsByAddress = new Map(
    sheet.cells.map((cell) => [cell.address, cell] as const),
  );
  const rows: string[] = [];

  for (let row = range.start.row; row <= range.end.row; row += 1) {
    const tds: string[] = [];

    for (let col = range.start.col; col <= range.end.col; col += 1) {
      const address = formatCell({ row, col });
      tds.push(buildTableCell(address, cellsByAddress.get(address)));
    }

    rows.push(`  <tr>\n    ${tds.join("\n    ")}\n  </tr>`);
  }

  const truncationMarker = truncated
    ? "  <!-- Table context truncated to a safe preview window -->\n"
    : "";

  return `<table data-sheet="${escapeAttribute(sheet.name)}">\n${truncationMarker}${rows.join("\n")}\n</table>`;
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

function buildTableCell(address: string, cell: TidyCell | undefined): string {
  const attributes = [
    styleAttribute(cell),
    `data-r1c1="${escapeAttribute(address)}"`,
    `title="${escapeAttribute(address)}"`,
    mergeAttributes(cell),
  ]
    .filter(Boolean)
    .join(" ");

  return `<td ${attributes}>${escapeHtml(displayValue(cell))}</td>`;
}

function styleAttribute(cell: TidyCell | undefined): string | undefined {
  const style = cell?.style;

  if (!style) {
    return undefined;
  }

  const declarations: string[] = [];

  if (style.horizontalAlign && style.horizontalAlign !== "general") {
    declarations.push(`text-align: ${style.horizontalAlign};`);
  }

  if (typeof style.fontIndent === "number" && style.fontIndent > 0) {
    declarations.push(`padding-left: ${style.fontIndent * 15}px;`);
  }

  if (style.bold) {
    declarations.push("font-weight: bold;");
  }

  if (style.italic) {
    declarations.push("font-style: italic;");
  }

  if (typeof style.fontSize === "number") {
    declarations.push(`font-size: ${style.fontSize}pt;`);
  }

  const fontColor = parseColor(style.fontColor);
  if (fontColor) {
    declarations.push(`color: ${fontColor};`);
  }

  const fillColor = parseColor(style.fillColor);
  if (fillColor) {
    declarations.push(`background-color: ${fillColor};`);
  }

  if (style.border?.top) {
    declarations.push("border-top: 1px solid currentColor;");
  }

  if (style.border?.right) {
    declarations.push("border-right: 1px solid currentColor;");
  }

  if (style.border?.bottom) {
    declarations.push("border-bottom: 1px solid currentColor;");
  }

  if (style.border?.left) {
    declarations.push("border-left: 1px solid currentColor;");
  }

  if (declarations.length === 0) {
    return undefined;
  }

  return `style="${escapeAttribute(declarations.join(" "))}"`;
}

function mergeAttributes(cell: TidyCell | undefined): string | undefined {
  if (!cell?.merge) {
    return undefined;
  }

  return [
    `data-merge-parent="${escapeAttribute(cell.merge.parent)}"`,
    `data-merge-range="${escapeAttribute(cell.merge.range)}"`,
    `data-merge-role="${escapeAttribute(cell.merge.role)}"`,
  ].join(" ");
}

function parseColor(value: string | undefined): string | undefined {
  if (!value) {
    return undefined;
  }

  const normalized = value.trim().replace(/^#/, "");

  if (/^[0-9a-f]{8}$/i.test(normalized)) {
    return `#${normalized.slice(2)}`;
  }

  if (/^[0-9a-f]{6}$/i.test(normalized)) {
    return `#${normalized}`;
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

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeAttribute(value: string): string {
  return escapeHtml(value).replaceAll('"', "&quot;");
}
