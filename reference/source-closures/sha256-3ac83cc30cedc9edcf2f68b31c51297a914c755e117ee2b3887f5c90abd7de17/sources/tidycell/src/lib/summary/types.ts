import type { CandidateBlock } from "@/lib/recipe/detectCandidateBlocks";
import type { CellDataType } from "@/lib/workbook/types";

export type SummaryCell = {
  address: string;
  row: number;
  col: number;
  value: string | number | boolean | null;
  data_type: CellDataType;
  formatted?: string | null;
  style_id?: string;
  has_formula: boolean;
  has_comment: boolean;
};

export type BlankBand = {
  start: number;
  end: number;
};

export type CandidateRegion = {
  range: string;
  rowCount: number;
  columnCount: number;
  numericCellCount: number;
};

export type HeaderCandidate = {
  value: string;
  addresses: string | string[];
};

export type TableContextFormat = "markdown_compact" | "html_expanded";

export type SheetSummary = {
  sheet: string;
  checked: boolean;
  usedRange: string | null;
  rowCount: number;
  columnCount: number;
  nonEmptyCellCount: number;
  cells: SummaryCell[];
  dataTypes: Partial<Record<CellDataType, number>>;
  merges: Array<{ parent: string; range: string }>;
  styleFingerprints: Record<string, unknown>;
  blankRows: BlankBand[];
  blankColumns: BlankBand[];
  candidateRegions: CandidateRegion[];
  candidateBlocks?: readonly CandidateBlock[];
  candidateBlockEvidence?: {
    detector_version: "tidybank-candidate-blocks-v1";
    total_count: number;
    included_count: number;
    omitted_count: number;
    truncated: boolean;
    role_hypotheses_are_authoritative: false;
  };
  dataRangeHintRegions?: CandidateRegion[];
  contextCells: SummaryCell[];
  header_list: HeaderCandidate[];
  table_context_format: TableContextFormat;
  table_markdown: string;
  table_markdown_truncated: boolean;
  html_table: string;
  html_table_truncated: boolean;
  intent?: string;
  truncated: boolean;
  sizeChars: number;
};

export type BuildSheetSummaryOptions = {
  checked?: boolean;
  intent?: string;
  maxChars?: number;
  maxCells?: number;
  maxContextCells?: number;
  maxMarkdownChars?: number;
  maxHtmlChars?: number;
  tableContextMode?: TableContextFormat;
  includeNumericStringCandidateRegions?: boolean;
};
