import type {
  NonTableCell,
  TidyOutputRow,
  TidyTableResult,
} from "@/lib/executor/types";
import type { RecipeV01 } from "@/lib/recipe/types";
import {
  enrichedRowsForExport,
  type EnrichedOutputTable,
  type OntologyEnrichmentMetadata,
  type OntologyExportMode,
  type ExportFlatRow,
} from "./enrichment";

export type CsvExportOptions = {
  valueColumn?: string;
  includeSourceColumns?: boolean;
  // Prefix string values that Excel would interpret as formulas (=, +, -, @,
  // tab, CR) with a single quote. Off by default because it alters values and
  // would break byte-exact benchmark comparisons; enable for user downloads.
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
  const lines = [table.headers.map(escape).join(",")];

  for (const row of table.rows) {
    lines.push(row.map(escape).join(","));
  }

  return `${lines.join("\n")}\n`;
}

/**
 * Formats an explicit sidecar-enrichment export. Raw mode (and every soft
 * failure with null metadata) delegates to the legacy formatter byte-for-byte.
 */
export function enrichedTableToCsv({
  table,
  mode,
  metadata,
  options = {},
}: {
  table: EnrichedOutputTable;
  mode: OntologyExportMode;
  metadata: OntologyEnrichmentMetadata | null;
  options?: CsvExportOptions;
}): string {
  if (mode === "raw" || !metadata) {
    return rowsToCsv(table.rows.map((row) => row.raw), options);
  }
  return flatRowsToCsv(enrichedRowsForExport(table, mode, metadata), options);
}

/** JSON sidecar metadata exposes bindings without relying on CSV column shape. */
export function enrichedTableToJson({
  table,
  mode,
  metadata,
}: {
  table: EnrichedOutputTable;
  mode: OntologyExportMode;
  metadata: OntologyEnrichmentMetadata | null;
}): string {
  if (mode === "raw" || !metadata) return tableToJson(table.table, table.rows.map((row) => row.raw));
  return `${JSON.stringify({
    table: table.table,
    ontology: { ...metadata, mode },
    rows: enrichedRowsForExport(table, mode, metadata),
  }, null, 2)}\n`;
}

/** CSVY carries the pin and generated collision-safe column map beside CSV rows. */
export function enrichedRowsToCsvy({
  table,
  nonTableCells = [],
  mode,
  metadata,
  guardFormulas,
}: {
  table: EnrichedOutputTable;
  nonTableCells?: NonTableCell[];
  mode: OntologyExportMode;
  metadata: OntologyEnrichmentMetadata | null;
  guardFormulas?: boolean;
}): string {
  if (mode === "raw" || !metadata) {
    return rowsToCsvy({
      rows: table.rows.map((row) => row.raw),
      nonTableCells,
      sheet: table.sheet,
      table: table.table,
      guardFormulas,
    });
  }
  const metadataJson = JSON.stringify({
    mode,
    profile: metadata.profile,
    ...(metadata.automaticMappingPolicyVersion ? { automaticMappingPolicyVersion: metadata.automaticMappingPolicyVersion } : {}),
    ...(metadata.automaticMappingPromotion ? { automaticMappingPromotion: metadata.automaticMappingPromotion } : {}),
    canonicalColumns: metadata.canonicalColumns,
  });
  const frontmatter = [
    "---",
    "tidycell:",
    '  version: "0.1"',
    `  sheet: ${yamlString(table.sheet)}`,
    `  table: ${yamlString(table.table)}`,
    `  ontology: ${yamlString(metadataJson)}`,
    "  non_table_cells:",
    ...nonTableCells.map(
      (cell) =>
        `    - address: ${yamlString(cell.address)}\n      value: ${yamlScalar(cell.value)}\n      data_type: ${yamlString(cell.data_type)}`,
    ),
    "---",
  ].join("\n");
  return `${frontmatter}\n${flatRowsToCsv(enrichedRowsForExport(table, mode, metadata), { guardFormulas })}`;
}

export function tableToJson(table: string, rows: TidyOutputRow[]): string {
  return `${JSON.stringify({ table, rows }, null, 2)}\n`;
}

export function tablesToJson({
  sheet,
  tables,
}: {
  sheet: string;
  tables: Pick<TidyTableResult, "table" | "rows">[];
}): string {
  return `${JSON.stringify(
    {
      sheet,
      tables: tables.map((table) => ({
        table: table.table,
        rows: table.rows,
      })),
    },
    null,
    2,
  )}\n`;
}

export function nonTableCellsToJson(cells: NonTableCell[] = []): string {
  return `${JSON.stringify(cells, null, 2)}\n`;
}

export function recipeToJson(recipe: RecipeV01): string {
  return `${JSON.stringify(recipe, null, 2)}\n`;
}

export function rowsToCsvy({
  rows,
  nonTableCells = [],
  sheet,
  table,
  valueColumn,
  guardFormulas,
}: {
  rows: TidyOutputRow[];
  nonTableCells?: NonTableCell[];
  sheet: string;
  table: string;
  valueColumn?: string;
  guardFormulas?: boolean;
}): string {
  const metadata = [
    "---",
    "tidycell:",
    '  version: "0.1"',
    `  sheet: ${yamlString(sheet)}`,
    `  table: ${yamlString(table)}`,
    "  non_table_cells:",
    ...nonTableCells.map(
      (cell) =>
        `    - address: ${yamlString(cell.address)}\n      value: ${yamlScalar(cell.value)}\n      data_type: ${yamlString(cell.data_type)}`,
    ),
    "---",
  ].join("\n");

  return `${metadata}\n${rowsToCsv(rows, { valueColumn, guardFormulas })}`;
}

export function makeExportFilename({
  extension,
  sheet,
  table,
  timestamp = new Date(),
}: {
  extension: string;
  sheet: string;
  table?: string;
  timestamp?: Date;
}): string {
  const stamp = timestamp.toISOString().replace(/[:.]/g, "-");
  // slug() can return "" for names without latin characters; drop those parts
  // rather than emitting filenames with dangling underscores.
  return (
    [sheet, table, stamp]
      .filter((part): part is string => Boolean(part))
      .map(slug)
      .filter((part) => part.length > 0)
      .join("_") + `.${extension}`
  );
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
    for (const sourceHeader of sourceHeaders) {
      headers.add(sourceHeader);
    }

    if (options.valueColumn) {
      headers.add(".value");
    }

    for (const key of Object.keys(row)) {
      if (
        key !== "_source" &&
        key !== options.valueColumn &&
        (includeSourceColumns || !isSourceColumn(row, key))
      ) {
        headers.add(key);
      }
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
  if (key === "_source" || key.startsWith("_source.")) {
    return true;
  }

  if (!key.endsWith("_source")) {
    return false;
  }

  const valueKey = key.slice(0, -"_source".length);
  return Object.prototype.hasOwnProperty.call(row, valueKey);
}

function getRowValue(
  row: TidyOutputRow,
  header: string,
  options: CsvExportOptions,
): string | number | boolean | null {
  if (options.valueColumn) {
    if (header === "row") {
      return row._source?.row ?? null;
    }

    if (header === "col") {
      return row._source?.col ?? null;
    }

    if (header === "address") {
      return row._source?.address ?? null;
    }

    if (header === ".value") {
      return scalarValue(row[options.valueColumn]);
    }
  }

  if (header.startsWith("_source.")) {
    const key = header.replace("_source.", "") as keyof NonNullable<
      TidyOutputRow["_source"]
    >;
    return row._source?.[key] ?? null;
  }

  const value = row[header];

  return scalarValue(value);
}

function scalarValue(
  value: TidyOutputRow[string],
): string | number | boolean | null {
  if (value === undefined || value === null || typeof value === "object") {
    return null;
  }

  return value;
}

function flatRowsToCsv(rows: ExportFlatRow[], options: CsvExportOptions): string {
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))].filter((header) =>
    options.includeSourceColumns ?? true ? true : !isFlatSourceColumn(header),
  );
  const escape = (value: string | number | boolean | null) => csvEscape(value, options.guardFormulas ?? false);
  return `${[
    headers.map(escape).join(","),
    ...rows.map((row) => headers.map((header) => escape(row[header] ?? null)).join(",")),
  ].join("\n")}\n`;
}

function isFlatSourceColumn(key: string): boolean {
  return key.startsWith("_source.") || key.endsWith("_source");
}

function csvEscape(
  value: string | number | boolean | null,
  guardFormulas = false,
): string {
  if (value === null) {
    return "";
  }

  let text = String(value);

  if (guardFormulas && typeof value === "string" && /^[=+\-@\t\r]/.test(text)) {
    text = `'${text}`;
  }

  if (/[",\n\r]/.test(text)) {
    return `"${text.replaceAll('"', '""')}"`;
  }

  return text;
}

function yamlString(value: string): string {
  return JSON.stringify(value);
}

function yamlScalar(value: string | number | boolean | null): string {
  return typeof value === "string" ? yamlString(value) : String(value);
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
