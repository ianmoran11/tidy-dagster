/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import type { HeaderDirection } from "../../recipe/types.js";
import type { CellDataType, ParsedSheet } from "../../workbook/types.js";

export type CellRoleLabel =
  | "blank"
  | "value"
  | "header"
  | "unused"
  | "context"
  | "note";

export type MergeRoleFeature = "none" | "parent" | "child";

export type CellFeatureVector = {
  sheet: string;
  address: string;
  row: number;
  col: number;
  rowRatio: number;
  colRatio: number;
  dataType: CellDataType;
  isBlank: boolean;
  hasFormula: boolean;
  hasComment: boolean;
  hasFormattedValue: boolean;
  textLength: number;
  tokenCount: number;
  digitRatio: number;
  uppercaseRatio: number;
  punctuationRatio: number;
  /** Fixed, non-reversible hashed character n-grams for classical grouping ML. */
  textFingerprint?: number[];
  isNumericLikeText: boolean;
  isDateLikeText: boolean;
  rowNonEmptyCount: number;
  columnNonEmptyCount: number;
  rowDensity: number;
  columnDensity: number;
  nonEmptyAbove: number;
  nonEmptyBelow: number;
  nonEmptyLeft: number;
  nonEmptyRight: number;
  nearestBlankRowAbove: number | null;
  nearestBlankRowBelow: number | null;
  nearestBlankColumnLeft: number | null;
  nearestBlankColumnRight: number | null;
  isTopEdge: boolean;
  isLeftEdge: boolean;
  isBottomEdge: boolean;
  isRightEdge: boolean;
  isBold: boolean;
  isItalic: boolean;
  isUnderlined: boolean;
  fontSize: number | null;
  hasFillColor: boolean;
  hasFontColor: boolean;
  fontIndent: number;
  horizontalAlign: string | null;
  verticalAlign: string | null;
  hasBorderTop: boolean;
  hasBorderRight: boolean;
  hasBorderBottom: boolean;
  hasBorderLeft: boolean;
  hasAnyBorder: boolean;
  mergeRole: MergeRoleFeature;
  mergeRowSpan: number;
  mergeColumnSpan: number;
};

export type LabelledCellExample = CellFeatureVector & {
  role: CellRoleLabel;
  table?: string;
  header?: string;
  direction?: HeaderDirection;
  labelSource: "recipe" | "heuristic";
};

export type HeaderGroupCandidate = {
  table: string;
  header: string;
  direction: HeaderDirection;
  directionOverrides?: Record<string, HeaderDirection>;
  addresses: string[];
  range: string | null;
  confidence?: number;
  modelVersion?: string;
};

export type CellRoleProbabilities = Partial<Record<CellRoleLabel, number>>;

export type CellPrepassPrediction = CellFeatureVector & {
  predictedRole: CellRoleLabel;
  roleProbabilities: CellRoleProbabilities;
  predictedTable?: string;
  predictedHeader?: string;
  predictedDirection?: HeaderDirection;
  confidence?: number;
  /**
   * Optional numeric cell value (deterministic, not model-derived). Populated by
   * adapters that have the ParsedSheet; lets the compiler recognize numeric band
   * rows (e.g. year headers "2016".."2025") that role models systematically read
   * as values. Never fed to any ML model.
   */
  numericValue?: number;
  /**
   * Optional trimmed string cell value (deterministic, not model-derived). Lets the
   * compiler recognize constant/unit-label text bands ("$m", "%") that role models
   * systematically read as values. Never fed to any ML model.
   */
  textValue?: string;
  /**
   * Full direction-model distribution when available. The compiler uses it for
   * band-completion: cells the role model hesitates on (header prob just under the
   * bar) can still join a diagonal band when the direction model is confident.
   */
  directionProbabilities?: Partial<Record<HeaderDirection, number>>;
};

export type TableRegionCandidate = {
  table: string;
  range: string;
  valueAddresses: string[];
  confidence: number;
};

export type MlPrepassConfidenceSummary = {
  overall: number;
  valueRole: number | null;
  headerRole: number | null;
  lowConfidenceCellCount: number;
};

export type MlPrepassResult = {
  sheet: string;
  modelFamily:
    | "heuristic"
    | "xgboost"
    | "neural-net"
    | "transformer"
    | "ensemble";
  modelVersion: string;
  predictions: CellPrepassPrediction[];
  headerGroups: HeaderGroupCandidate[];
  tableRegions: TableRegionCandidate[];
  confidence: MlPrepassConfidenceSummary;
  promptHints: string[];
  lowConfidenceAddresses: string[];
};

export type NeuralRecipePrepass = {
  predict(sheet: ParsedSheet): Promise<MlPrepassResult>;
};
