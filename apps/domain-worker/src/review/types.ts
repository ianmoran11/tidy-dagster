/* Ported type subset from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
export type ProducedCsvColumnSummary = Array<{
  table: string;
  row_count: number;
  unique_row_key_count: number;
  duplicate_header_key_count: number;
  duplicate_header_row_count: number;
  duplicate_header_key_share: number;
  columns: Array<{
    name: string;
    unique_count: number;
    empty_count: number;
    missing_share: number;
    high_missing_share: boolean;
    numeric_parse_share: number;
    values: string[];
    truncated: boolean;
  }>;
  column_pair_overlap: Array<{
    columns: [string, string];
    both_present_share: number;
    left_only_share: number;
    right_only_share: number;
    neither_present_share: number;
    complementary_missing_share: number;
  }>;
}>;

export type ProducedCsvSuspiciousRows = {
  duplicate_header_keys: Array<{
    table: string;
    key_columns: string[];
    key_values: Record<string, string>;
    row_count: number;
    rows: Array<Record<string, string>>;
  }>;
  low_numeric_value_rows: Array<{
    table: string;
    column: string;
    numeric_parse_share: number;
    rows: Array<Record<string, string>>;
  }>;
  high_missing_column_rows: Array<{
    table: string;
    column: string;
    missing_share: number;
    rows: Array<Record<string, string>>;
  }>;
  sparse_column_pair_rows: Array<{
    table: string;
    columns: [string, string];
    complementary_missing_share: number;
    rows: Array<Record<string, string>>;
  }>;
};
