/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import type { ExecutionResult } from "../executor/types.js";
import { rowsToCsv } from "../export/formatters.js";
import type { RecipeV01 } from "../recipe/types.js";
import type {
  ProducedCsvColumnSummary,
  ProducedCsvSuspiciousRows,
} from "./types.js";

const DEFAULT_MAX_VALUES_PER_COLUMN = 40;
const DEFAULT_MAX_VALUE_CHARS = 80;
const DEFAULT_HIGH_MISSING_SHARE_THRESHOLD = 0.5;
const DEFAULT_MAX_COLUMN_PAIR_OVERLAPS = 8;
const DEFAULT_COLUMN_PAIR_OVERLAP_THRESHOLD = 0.5;
const DEFAULT_FULL_CSV_CHAR_LIMIT = 12_000;
const DEFAULT_EXCERPT_HEAD_ROWS = 8;
const DEFAULT_EXCERPT_TAIL_ROWS = 8;
const DEFAULT_EXCERPT_STRATIFIED_ROWS = 8;
const DEFAULT_MAX_SUSPICIOUS_GROUPS = 6;
const DEFAULT_MAX_ROWS_PER_SUSPICIOUS_GROUP = 4;
const DEFAULT_LOW_NUMERIC_PARSE_THRESHOLD = 1;
const DEFAULT_MAX_RECORD_FIELDS = 18;

const SOURCE_COLUMNS = new Set(["row", "col", "address", ".value"]);

type CsvTable = {
  headers: string[];
  records: Array<Record<string, string>>;
};

type ParsedOutputTable = {
  table: string;
  csv: string;
  headers: string[];
  records: Array<Record<string, string>>;
};

export function buildProducedCsvReviewArtifacts(
  recipe: RecipeV01,
  execution: ExecutionResult,
  producedCsv: string,
  options: {
    fullCsvCharLimit?: number;
    excerptHeadRows?: number;
    excerptTailRows?: number;
    excerptStratifiedRows?: number;
    maxValuesPerColumn?: number;
    maxValueChars?: number;
    highMissingShareThreshold?: number;
    maxColumnPairOverlaps?: number;
    columnPairOverlapThreshold?: number;
    maxSuspiciousGroups?: number;
    maxRowsPerSuspiciousGroup?: number;
    lowNumericParseThreshold?: number;
    maxRecordFields?: number;
  } = {},
): {
  producedCsvSample: string;
  producedCsvColumnSummary: ProducedCsvColumnSummary;
  producedCsvSuspiciousRows: ProducedCsvSuspiciousRows;
} {
  const tables = parseOutputTables(recipe, execution);
  const producedCsvColumnSummary = buildProducedCsvColumnSummaryFromTables(
    tables,
    options,
  );

  return {
    producedCsvSample: buildProducedCsvPromptSample(producedCsv, tables, {
      fullCsvCharLimit: options.fullCsvCharLimit,
      excerptHeadRows: options.excerptHeadRows,
      excerptTailRows: options.excerptTailRows,
      excerptStratifiedRows: options.excerptStratifiedRows,
    }),
    producedCsvColumnSummary,
    producedCsvSuspiciousRows: buildProducedCsvSuspiciousRows(
      tables,
      producedCsvColumnSummary,
      options,
    ),
  };
}

export function buildProducedCsvColumnSummary(
  recipe: RecipeV01,
  execution: ExecutionResult,
  options: {
    maxValuesPerColumn?: number;
    maxValueChars?: number;
    highMissingShareThreshold?: number;
    maxColumnPairOverlaps?: number;
    columnPairOverlapThreshold?: number;
  } = {},
): ProducedCsvColumnSummary {
  return buildProducedCsvColumnSummaryFromTables(
    parseOutputTables(recipe, execution),
    options,
  );
}

function parseOutputTables(
  recipe: RecipeV01,
  execution: ExecutionResult,
): ParsedOutputTable[] {
  return execution.tables.map((table, tableIndex) => {
    const csv = rowsToCsv(table.rows, {
      valueColumn: recipe.tables[tableIndex]?.values.name,
    });
    const parsed = parseCsv(csv);

    return {
      table: table.table,
      csv,
      headers: parsed.headers,
      records: parsed.records,
    };
  });
}

function buildProducedCsvColumnSummaryFromTables(
  tables: ParsedOutputTable[],
  options: {
    maxValuesPerColumn?: number;
    maxValueChars?: number;
    highMissingShareThreshold?: number;
    maxColumnPairOverlaps?: number;
    columnPairOverlapThreshold?: number;
  } = {},
): ProducedCsvColumnSummary {
  const maxValuesPerColumn =
    options.maxValuesPerColumn ?? DEFAULT_MAX_VALUES_PER_COLUMN;
  const maxValueChars = options.maxValueChars ?? DEFAULT_MAX_VALUE_CHARS;
  const highMissingShareThreshold =
    options.highMissingShareThreshold ?? DEFAULT_HIGH_MISSING_SHARE_THRESHOLD;
  const maxColumnPairOverlaps =
    options.maxColumnPairOverlaps ?? DEFAULT_MAX_COLUMN_PAIR_OVERLAPS;
  const columnPairOverlapThreshold =
    options.columnPairOverlapThreshold ?? DEFAULT_COLUMN_PAIR_OVERLAP_THRESHOLD;

  return tables.map((table) => {
    if (table.records.length === 0) {
      return {
        table: table.table,
        row_count: 0,
        unique_row_key_count: 0,
        duplicate_header_key_count: 0,
        duplicate_header_row_count: 0,
        duplicate_header_key_share: 0,
        columns: [],
        column_pair_overlap: [],
      };
    }

    const diagnosticColumns = table.headers.filter(isDiagnosticColumn);
    const headerKeyDiagnostics = buildHeaderKeyDiagnostics(
      table.records,
      diagnosticColumns,
    );

    return {
      table: table.table,
      row_count: table.records.length,
      ...headerKeyDiagnostics,
      columns: table.headers.map((name) =>
        summarizeColumn({
          name,
          records: table.records,
          maxValuesPerColumn,
          maxValueChars,
          highMissingShareThreshold,
        }),
      ),
      column_pair_overlap: buildColumnPairOverlap({
        records: table.records,
        columns: diagnosticColumns,
        maxPairs: maxColumnPairOverlaps,
        threshold: columnPairOverlapThreshold,
      }),
    };
  });
}

function buildProducedCsvPromptSample(
  producedCsv: string,
  tables: ParsedOutputTable[],
  options: {
    fullCsvCharLimit?: number;
    excerptHeadRows?: number;
    excerptTailRows?: number;
    excerptStratifiedRows?: number;
  },
): string {
  const fullCsvCharLimit =
    options.fullCsvCharLimit ?? DEFAULT_FULL_CSV_CHAR_LIMIT;

  if (producedCsv.length <= fullCsvCharLimit) {
    return producedCsv;
  }

  const excerptHeadRows = options.excerptHeadRows ?? DEFAULT_EXCERPT_HEAD_ROWS;
  const excerptTailRows = options.excerptTailRows ?? DEFAULT_EXCERPT_TAIL_ROWS;
  const excerptStratifiedRows =
    options.excerptStratifiedRows ?? DEFAULT_EXCERPT_STRATIFIED_ROWS;
  const totalRows = tables.reduce(
    (total, table) => total + table.records.length,
    0,
  );
  const sections = [
    `# Produced CSV excerpt; full CSV omitted because it is ${producedCsv.length} chars across ${totalRows} rows.`,
  ];

  for (const table of tables) {
    if (tables.length > 1) {
      sections.push(`# Table: ${table.table} (${table.records.length} rows)`);
    } else {
      sections.push(`# Table rows: ${table.records.length}`);
    }

    sections.push(
      buildTableExcerpt({
        table,
        headRows: excerptHeadRows,
        tailRows: excerptTailRows,
        stratifiedRows: excerptStratifiedRows,
      }),
    );
  }

  return `${sections.filter(Boolean).join("\n")}\n`;
}

function buildTableExcerpt({
  table,
  headRows,
  tailRows,
  stratifiedRows,
}: {
  table: ParsedOutputTable;
  headRows: number;
  tailRows: number;
  stratifiedRows: number;
}): string {
  if (table.records.length === 0) {
    return table.headers.map(csvEscape).join(",");
  }

  const indices = selectedExcerptIndices(table.records.length, {
    headRows,
    tailRows,
    stratifiedRows,
  });
  const lines = [
    table.headers.map(csvEscape).join(","),
    ...indices.map((index) =>
      table.headers
        .map((header) => csvEscape(table.records[index][header] ?? ""))
        .join(","),
    ),
  ];

  return lines.join("\n");
}

function selectedExcerptIndices(
  rowCount: number,
  {
    headRows,
    tailRows,
    stratifiedRows,
  }: { headRows: number; tailRows: number; stratifiedRows: number },
): number[] {
  const indices = new Set<number>();

  for (let index = 0; index < Math.min(headRows, rowCount); index += 1) {
    indices.add(index);
  }

  for (
    let index = Math.max(0, rowCount - tailRows);
    index < rowCount;
    index += 1
  ) {
    indices.add(index);
  }

  if (stratifiedRows > 0 && rowCount > headRows + tailRows) {
    for (let sample = 1; sample <= stratifiedRows; sample += 1) {
      const index = Math.round(
        (sample * (rowCount - 1)) / (stratifiedRows + 1),
      );
      indices.add(index);
    }
  }

  return [...indices].sort((left, right) => left - right);
}

function buildProducedCsvSuspiciousRows(
  tables: ParsedOutputTable[],
  summaries: ProducedCsvColumnSummary,
  options: {
    maxSuspiciousGroups?: number;
    maxRowsPerSuspiciousGroup?: number;
    lowNumericParseThreshold?: number;
    maxRecordFields?: number;
  } = {},
): ProducedCsvSuspiciousRows {
  const maxGroups =
    options.maxSuspiciousGroups ?? DEFAULT_MAX_SUSPICIOUS_GROUPS;
  const maxRows =
    options.maxRowsPerSuspiciousGroup ?? DEFAULT_MAX_ROWS_PER_SUSPICIOUS_GROUP;
  const lowNumericParseThreshold =
    options.lowNumericParseThreshold ?? DEFAULT_LOW_NUMERIC_PARSE_THRESHOLD;
  const maxRecordFields = options.maxRecordFields ?? DEFAULT_MAX_RECORD_FIELDS;
  const result: ProducedCsvSuspiciousRows = {
    duplicate_header_keys: [],
    low_numeric_value_rows: [],
    high_missing_column_rows: [],
    sparse_column_pair_rows: [],
  };

  for (const [tableIndex, table] of tables.entries()) {
    const summary = summaries[tableIndex];

    if (!summary || table.records.length === 0) {
      continue;
    }

    result.duplicate_header_keys.push(
      ...duplicateHeaderKeyRows({
        table,
        maxGroups,
        maxRows,
        maxRecordFields,
      }),
    );
    result.low_numeric_value_rows.push(
      ...lowNumericValueRows({
        table,
        summary,
        threshold: lowNumericParseThreshold,
        maxGroups,
        maxRows,
        maxRecordFields,
      }),
    );
    result.high_missing_column_rows.push(
      ...highMissingColumnRows({
        table,
        summary,
        maxGroups,
        maxRows,
        maxRecordFields,
      }),
    );
    result.sparse_column_pair_rows.push(
      ...sparseColumnPairRows({
        table,
        summary,
        maxGroups,
        maxRows,
        maxRecordFields,
      }),
    );
  }

  return {
    duplicate_header_keys: result.duplicate_header_keys.slice(0, maxGroups),
    low_numeric_value_rows: result.low_numeric_value_rows.slice(0, maxGroups),
    high_missing_column_rows: result.high_missing_column_rows.slice(
      0,
      maxGroups,
    ),
    sparse_column_pair_rows: result.sparse_column_pair_rows.slice(0, maxGroups),
  };
}

function duplicateHeaderKeyRows({
  table,
  maxGroups,
  maxRows,
  maxRecordFields,
}: {
  table: ParsedOutputTable;
  maxGroups: number;
  maxRows: number;
  maxRecordFields: number;
}): ProducedCsvSuspiciousRows["duplicate_header_keys"] {
  const keyColumns = table.headers.filter(isDiagnosticColumn);
  const groups = new Map<
    string,
    { keyValues: Record<string, string>; rows: Array<Record<string, string>> }
  >();

  for (const record of table.records) {
    const keyValues = Object.fromEntries(
      keyColumns.map((column) => [column, record[column] ?? ""]),
    );
    const key = JSON.stringify(keyValues);
    const group = groups.get(key) ?? { keyValues, rows: [] };

    group.rows.push(record);
    groups.set(key, group);
  }

  return [...groups.values()]
    .filter(
      (group) =>
        group.rows.length > 1 &&
        new Set(group.rows.map((record) => (record[".value"] ?? "").trim()))
          .size > 1,
    )
    .sort((left, right) => right.rows.length - left.rows.length)
    .slice(0, maxGroups)
    .map((group) => ({
      table: table.table,
      key_columns: keyColumns,
      key_values: group.keyValues,
      row_count: group.rows.length,
      rows: group.rows
        .slice(0, maxRows)
        .map((record) =>
          compactRecord(record, table.headers, keyColumns, maxRecordFields),
        ),
    }));
}

function lowNumericValueRows({
  table,
  summary,
  threshold,
  maxGroups,
  maxRows,
  maxRecordFields,
}: {
  table: ParsedOutputTable;
  summary: ProducedCsvColumnSummary[number];
  threshold: number;
  maxGroups: number;
  maxRows: number;
  maxRecordFields: number;
}): ProducedCsvSuspiciousRows["low_numeric_value_rows"] {
  return summary.columns
    .filter(
      (column) =>
        column.name === ".value" &&
        column.unique_count > 0 &&
        column.numeric_parse_share < threshold,
    )
    .slice(0, maxGroups)
    .map((column) => ({
      table: table.table,
      column: column.name,
      numeric_parse_share: column.numeric_parse_share,
      rows: table.records
        .filter((record) => {
          const value = (record[column.name] ?? "").trim();
          return value && !isNumericLike(value);
        })
        .slice(0, maxRows)
        .map((record) =>
          compactRecord(record, table.headers, [column.name], maxRecordFields),
        ),
    }))
    .filter((group) => group.rows.length > 0);
}

function highMissingColumnRows({
  table,
  summary,
  maxGroups,
  maxRows,
  maxRecordFields,
}: {
  table: ParsedOutputTable;
  summary: ProducedCsvColumnSummary[number];
  maxGroups: number;
  maxRows: number;
  maxRecordFields: number;
}): ProducedCsvSuspiciousRows["high_missing_column_rows"] {
  return summary.columns
    .filter(
      (column) => column.high_missing_share && isDiagnosticColumn(column.name),
    )
    .sort((left, right) => right.missing_share - left.missing_share)
    .slice(0, maxGroups)
    .map((column) => ({
      table: table.table,
      column: column.name,
      missing_share: column.missing_share,
      rows: table.records
        .filter((record) => Boolean((record[column.name] ?? "").trim()))
        .slice(0, maxRows)
        .map((record) =>
          compactRecord(record, table.headers, [column.name], maxRecordFields),
        ),
    }))
    .filter((group) => group.rows.length > 0);
}

function sparseColumnPairRows({
  table,
  summary,
  maxGroups,
  maxRows,
  maxRecordFields,
}: {
  table: ParsedOutputTable;
  summary: ProducedCsvColumnSummary[number];
  maxGroups: number;
  maxRows: number;
  maxRecordFields: number;
}): ProducedCsvSuspiciousRows["sparse_column_pair_rows"] {
  return summary.column_pair_overlap.slice(0, maxGroups).map((pair) => ({
    table: table.table,
    columns: pair.columns,
    complementary_missing_share: pair.complementary_missing_share,
    rows: table.records
      .filter((record) => {
        const [left, right] = pair.columns;
        const hasLeft = Boolean((record[left] ?? "").trim());
        const hasRight = Boolean((record[right] ?? "").trim());
        return hasLeft !== hasRight;
      })
      .slice(0, maxRows)
      .map((record) =>
        compactRecord(record, table.headers, pair.columns, maxRecordFields),
      ),
  }));
}

function compactRecord(
  record: Record<string, string>,
  headers: string[],
  requiredColumns: string[],
  maxFields: number,
): Record<string, string> {
  const keep = new Set(["row", "col", "address", ".value", ...requiredColumns]);
  const compact: Record<string, string> = {};

  for (const header of headers) {
    const value = record[header] ?? "";

    if (!keep.has(header) && !value.trim()) {
      continue;
    }

    if (keep.has(header) || Object.keys(compact).length < maxFields) {
      compact[header] = truncateValue(value, DEFAULT_MAX_VALUE_CHARS);
    }
  }

  return compact;
}

function summarizeColumn({
  name,
  records,
  maxValuesPerColumn,
  maxValueChars,
  highMissingShareThreshold,
}: {
  name: string;
  records: Array<Record<string, string>>;
  maxValuesPerColumn: number;
  maxValueChars: number;
  highMissingShareThreshold: number;
}): ProducedCsvColumnSummary[number]["columns"][number] {
  const seen = new Set<string>();
  const values: string[] = [];
  let emptyCount = 0;
  let nonEmptyCount = 0;
  let numericCount = 0;
  let truncated = false;

  for (const record of records) {
    const value = (record[name] ?? "").trim();

    if (!value) {
      emptyCount += 1;
      continue;
    }

    nonEmptyCount += 1;

    if (isNumericLike(value)) {
      numericCount += 1;
    }

    if (seen.has(value)) {
      continue;
    }

    seen.add(value);

    if (values.length < maxValuesPerColumn) {
      values.push(truncateValue(value, maxValueChars));
    } else {
      truncated = true;
    }
  }

  const missingShare =
    records.length === 0 ? 0 : roundShare(emptyCount / records.length);
  const numericParseShare =
    nonEmptyCount === 0 ? 0 : roundShare(numericCount / nonEmptyCount);

  return {
    name,
    unique_count: seen.size,
    empty_count: emptyCount,
    missing_share: missingShare,
    high_missing_share: missingShare >= highMissingShareThreshold,
    numeric_parse_share: numericParseShare,
    values,
    truncated,
  };
}

function buildHeaderKeyDiagnostics(
  records: Array<Record<string, string>>,
  headerColumns: string[],
): Pick<
  ProducedCsvColumnSummary[number],
  | "unique_row_key_count"
  | "duplicate_header_key_count"
  | "duplicate_header_row_count"
  | "duplicate_header_key_share"
> {
  if (records.length === 0) {
    return {
      unique_row_key_count: 0,
      duplicate_header_key_count: 0,
      duplicate_header_row_count: 0,
      duplicate_header_key_share: 0,
    };
  }

  const groups = new Map<string, { rowCount: number; values: Set<string> }>();

  for (const record of records) {
    const key = JSON.stringify(headerColumns.map((column) => record[column]));
    const group = groups.get(key) ?? { rowCount: 0, values: new Set<string>() };

    group.rowCount += 1;
    group.values.add((record[".value"] ?? "").trim());
    groups.set(key, group);
  }

  const duplicateGroups = [...groups.values()].filter(
    (group) => group.rowCount > 1 && group.values.size > 1,
  );
  const duplicateRowCount = duplicateGroups.reduce(
    (total, group) => total + group.rowCount,
    0,
  );

  return {
    unique_row_key_count: groups.size,
    duplicate_header_key_count: duplicateGroups.length,
    duplicate_header_row_count: duplicateRowCount,
    duplicate_header_key_share: roundShare(duplicateRowCount / records.length),
  };
}

function buildColumnPairOverlap({
  records,
  columns,
  maxPairs,
  threshold,
}: {
  records: Array<Record<string, string>>;
  columns: string[];
  maxPairs: number;
  threshold: number;
}): ProducedCsvColumnSummary[number]["column_pair_overlap"] {
  if (records.length === 0 || columns.length < 2 || maxPairs <= 0) {
    return [];
  }

  const overlaps: ProducedCsvColumnSummary[number]["column_pair_overlap"] = [];

  for (let leftIndex = 0; leftIndex < columns.length - 1; leftIndex += 1) {
    for (
      let rightIndex = leftIndex + 1;
      rightIndex < columns.length;
      rightIndex += 1
    ) {
      const left = columns[leftIndex];
      const right = columns[rightIndex];
      let bothPresent = 0;
      let leftOnly = 0;
      let rightOnly = 0;
      let neitherPresent = 0;

      for (const record of records) {
        const hasLeft = Boolean((record[left] ?? "").trim());
        const hasRight = Boolean((record[right] ?? "").trim());

        if (hasLeft && hasRight) {
          bothPresent += 1;
        } else if (hasLeft) {
          leftOnly += 1;
        } else if (hasRight) {
          rightOnly += 1;
        } else {
          neitherPresent += 1;
        }
      }

      const complementaryMissingShare = roundShare(
        (leftOnly + rightOnly) / records.length,
      );

      if (
        complementaryMissingShare < threshold ||
        leftOnly === 0 ||
        rightOnly === 0
      ) {
        continue;
      }

      overlaps.push({
        columns: [left, right],
        both_present_share: roundShare(bothPresent / records.length),
        left_only_share: roundShare(leftOnly / records.length),
        right_only_share: roundShare(rightOnly / records.length),
        neither_present_share: roundShare(neitherPresent / records.length),
        complementary_missing_share: complementaryMissingShare,
      });
    }
  }

  return overlaps
    .sort(
      (left, right) =>
        right.complementary_missing_share - left.complementary_missing_share ||
        left.both_present_share - right.both_present_share ||
        left.columns.join("|").localeCompare(right.columns.join("|")),
    )
    .slice(0, maxPairs);
}

function isDiagnosticColumn(column: string): boolean {
  return !SOURCE_COLUMNS.has(column) && !column.startsWith("_source.");
}

function isNumericLike(value: string): boolean {
  const normalized = value.trim().replace(/,/g, "").replace(/%$/, "");

  if (!normalized) {
    return false;
  }

  if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(normalized)) {
    return false;
  }

  return Number.isFinite(Number(normalized));
}

function roundShare(value: number): number {
  return Number(value.toFixed(4));
}

function truncateValue(value: string, maxChars: number): string {
  if (value.length <= maxChars) {
    return value;
  }

  return `${value.slice(0, Math.max(0, maxChars - 3))}...`;
}

function csvEscape(value: string | number | boolean | null): string {
  if (value === null) {
    return "";
  }

  const text = String(value);

  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function parseCsv(csv: string): CsvTable {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < csv.length; index += 1) {
    const char = csv[index];

    if (inQuotes) {
      if (char === '"') {
        if (csv[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        cell += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char === "\r") {
      if (csv[index + 1] === "\n") {
        continue;
      }
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  if (cell.length > 0 || row.length > 0 || !csv.endsWith("\n")) {
    row.push(cell);
    rows.push(row);
  }

  const headers = rows[0] ?? [];
  const dataRows = rows
    .slice(1)
    .filter((dataRow) => dataRow.length > 1 || dataRow[0] !== "");
  const records = dataRows.map((dataRow) =>
    Object.fromEntries(
      headers.map((header, index) => [header, dataRow[index] ?? ""]),
    ),
  );

  return {
    headers,
    records,
  };
}
