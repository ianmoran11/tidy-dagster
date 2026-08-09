/* Raw export subset reimplemented from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import type { TidyOutputRow } from "../executor/types.js";

export type CsvExportOptions = {
  valueColumn?: string;
  includeSourceColumns?: boolean;
  guardFormulas?: boolean;
};

export type CsvTableData = {
  headers: string[];
  rows: Array<Array<string | number | boolean | null>>;
};

export function rowsToTableData(
  rows: TidyOutputRow[],
  options: CsvExportOptions = {},
): CsvTableData {
  const headers = collectHeaders(rows, options);
  return {
    headers,
    rows: rows.map((row) =>
      headers.map((header) => getRowValue(row, header, options)),
    ),
  };
}

export function rowsToCsv(
  rows: TidyOutputRow[],
  options: CsvExportOptions = {},
): string {
  const table = rowsToTableData(rows, options);
  const escape = (value: string | number | boolean | null) =>
    csvEscape(value, options.guardFormulas ?? false);
  return `${[table.headers.map(escape).join(","), ...table.rows.map((row) => row.map(escape).join(","))].join("\n")}\n`;
}

function collectHeaders(
  rows: TidyOutputRow[],
  options: CsvExportOptions,
): string[] {
  const headers = new Set<string>();
  const includeSourceColumns = options.includeSourceColumns ?? true;
  const sourceHeaders =
    options.valueColumn && includeSourceColumns
      ? ["row", "col", "address"]
      : [];
  for (const row of rows) {
    sourceHeaders.forEach((header) => headers.add(header));
    if (options.valueColumn) headers.add(".value");
    for (const key of Object.keys(row)) {
      if (
        key !== "_source" &&
        key !== options.valueColumn &&
        (includeSourceColumns || !isSourceColumn(row, key))
      )
        headers.add(key);
    }
    if (row._source && !options.valueColumn && includeSourceColumns) {
      headers.add("_source.sheet");
      headers.add("_source.address");
      headers.add("_source.row");
      headers.add("_source.col");
    }
  }
  return [...headers];
}

function isSourceColumn(row: TidyOutputRow, key: string): boolean {
  if (key === "_source" || key.startsWith("_source.")) return true;
  if (!key.endsWith("_source")) return false;
  return Object.prototype.hasOwnProperty.call(
    row,
    key.slice(0, -"_source".length),
  );
}

function getRowValue(
  row: TidyOutputRow,
  header: string,
  options: CsvExportOptions,
): string | number | boolean | null {
  if (options.valueColumn) {
    if (header === "row") return row._source?.row ?? null;
    if (header === "col") return row._source?.col ?? null;
    if (header === "address") return row._source?.address ?? null;
    if (header === ".value") return scalarValue(row[options.valueColumn]);
  }
  if (header.startsWith("_source.")) {
    const key = header.replace("_source.", "") as keyof NonNullable<
      TidyOutputRow["_source"]
    >;
    return row._source?.[key] ?? null;
  }
  return scalarValue(row[header]);
}

function scalarValue(
  value: TidyOutputRow[string],
): string | number | boolean | null {
  return value === undefined || value === null || typeof value === "object"
    ? null
    : value;
}

function csvEscape(
  value: string | number | boolean | null,
  guardFormulas = false,
): string {
  if (value === null) return "";
  let text = String(value);
  if (guardFormulas && typeof value === "string" && /^[=+\-@\t\r]/.test(text))
    text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
