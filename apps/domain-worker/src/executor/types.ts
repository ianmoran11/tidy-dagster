/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import type { TidyCell } from "../workbook/types.js";

export type ExecutionWarningCode =
  | "EMPTY_VALUE_SELECTION"
  | "EMPTY_HEADER_SELECTION"
  | "UNUSED_HEADER"
  | "MISSING_REQUIRED_HEADER"
  | "AMBIGUOUS_HEADER"
  | "OVERLAPPING_VALUE_CELL"
  | "SELECTOR_WARNING";

export type ExecutionWarning = {
  code: ExecutionWarningCode;
  message: string;
  table?: string;
  header?: string;
  address?: string;
};

export type OutputScalar = string | number | boolean | null;

export type TidyOutputRow = {
  [key: string]:
    | OutputScalar
    | {
        sheet: string;
        address: string;
        row: number;
        col: number;
      }
    | undefined;
  _source?: {
    sheet: string;
    address: string;
    row: number;
    col: number;
  };
};

export type HeaderAttachmentTrace = {
  header: string;
  direction: string;
  candidates: string[];
  selected?: string;
  value: OutputScalar;
  missing: boolean;
  ambiguous: boolean;
};

export type ValueCellTrace = {
  source: {
    sheet: string;
    address: string;
    row: number;
    col: number;
  };
  value: OutputScalar;
  headers: HeaderAttachmentTrace[];
};

export type ExecutionTrace = {
  value_cells: ValueCellTrace[];
};

export type TidyTableResult = {
  table: string;
  sheet: string;
  rows: TidyOutputRow[];
  warnings: ExecutionWarning[];
  trace: ExecutionTrace;
};

export type NonTableCell = Pick<
  TidyCell,
  | "sheet"
  | "address"
  | "row"
  | "col"
  | "value"
  | "data_type"
  | "formatted"
  | "formula"
  | "comment"
> & {
  style_id?: string | null;
  reason: "not_referenced_by_recipe";
};

export type ExecutionResult = {
  sheet: string;
  tables: TidyTableResult[];
  non_table_cells?: NonTableCell[];
  warnings: ExecutionWarning[];
};
