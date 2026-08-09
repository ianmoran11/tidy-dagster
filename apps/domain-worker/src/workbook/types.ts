/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
export type CellDataType =
  | "blank"
  | "string"
  | "numeric"
  | "boolean"
  | "date"
  | "error";

export type CellStyleSummary = {
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  fontSize?: number;
  fontColor?: string;
  fillColor?: string;
  fontIndent?: number;
  horizontalAlign?: string;
  verticalAlign?: string;
  border?: {
    top?: boolean;
    right?: boolean;
    bottom?: boolean;
    left?: boolean;
  };
};

export type CellMergeSummary = {
  parent: string;
  range: string;
  role: "parent" | "child";
};

export type TidyCell = {
  sheet: string;
  address: string;
  row: number;
  col: number;
  value: string | number | boolean | null;
  data_type: CellDataType;
  formula?: string | null;
  formatted?: string | null;
  comment?: string | null;
  hyperlink?: string | null;
  style?: CellStyleSummary;
  merge?: CellMergeSummary | null;
};

export type ParsedMergeRange = {
  parent: string;
  range: string;
};

export type ParsedSheet = {
  name: string;
  usedRange: string | null;
  rowCount: number;
  columnCount: number;
  nonEmptyCellCount: number;
  cells: TidyCell[];
  merges: ParsedMergeRange[];
};

export type ParsedWorkbook = {
  sheets: ParsedSheet[];
};

export type WorkbookParseError = {
  code: "INVALID_WORKBOOK" | "UNSUPPORTED_WORKBOOK";
  message: string;
};

export type WorkbookParseResult =
  | {
      ok: true;
      workbook: ParsedWorkbook;
      errors?: never;
    }
  | {
      ok: false;
      workbook?: never;
      errors: WorkbookParseError[];
    };
