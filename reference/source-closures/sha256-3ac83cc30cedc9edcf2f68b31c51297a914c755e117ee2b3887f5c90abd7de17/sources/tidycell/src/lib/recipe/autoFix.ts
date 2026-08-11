import { formatCell, formatRange, parseCell, parseRange } from "@/lib/address";
import { validateRecipe, type RecipeValidationIssue } from "@/lib/recipe/schema";
import type { CellSelector, HeaderSpec, RecipeV01, TableSpec } from "@/lib/recipe/types";

export type AutoFixFlags = {
  headerSpanExtension?: boolean;
  selectorNormalization?: boolean;
  dataTypeRelaxation?: boolean;
};

export const DEFAULT_AUTO_FIX_FLAGS: Required<AutoFixFlags> = {
  headerSpanExtension: false,
  selectorNormalization: false,
  dataTypeRelaxation: false,
};

export type AutoFixChange = {
  fix: "header_span_extension" | "selector_normalization" | "data_type_relaxation";
  table?: string;
  header?: string;
  path: string;
  before: unknown;
  after: unknown;
  reason: string;
};

export type AutoFixInput = {
  recipe: unknown;
  flags?: AutoFixFlags;
  execution?: {
    rowCount?: number;
    zeroRows?: boolean;
  };
};

export type AutoFixResult = {
  recipe: unknown;
  changes: AutoFixChange[];
  validation: ReturnType<typeof validateRecipe>;
};

export type AutoFixExecutionRetryResult<TExecution> = AutoFixResult & {
  beforeExecution: TExecution;
  afterExecution?: TExecution;
};

export function applyAutoFixes({
  recipe,
  flags,
  execution,
}: AutoFixInput): AutoFixResult {
  const resolvedFlags = { ...DEFAULT_AUTO_FIX_FLAGS, ...(flags ?? {}) };
  const working = deepClone(recipe);
  const changes: AutoFixChange[] = [];

  if (isRecipeLike(working)) {
    if (resolvedFlags.selectorNormalization) {
      applySelectorNormalizations(working, changes);
    }
    if (resolvedFlags.headerSpanExtension) {
      applyHeaderSpanExtensions(working, changes);
    }
    if (resolvedFlags.dataTypeRelaxation && isZeroRowExecution(execution)) {
      applyDataTypeRelaxations(working, changes);
    }
  }

  return {
    recipe: working,
    changes,
    validation: validateRecipe(working),
  };
}

export async function applyAutoFixesWithExecutionRetry<TExecution>({
  recipe,
  flags,
  execute,
  rowCount,
}: {
  recipe: unknown;
  flags?: AutoFixFlags;
  execute: (recipe: unknown) => TExecution | Promise<TExecution>;
  rowCount: (execution: TExecution) => number;
}): Promise<AutoFixExecutionRetryResult<TExecution>> {
  const beforeExecution = await execute(recipe);
  const fixed = applyAutoFixes({
    recipe,
    flags,
    execution: { rowCount: rowCount(beforeExecution) },
  });
  const shouldRetry =
    rowCount(beforeExecution) === 0 &&
    fixed.changes.some((change) => change.fix === "data_type_relaxation") &&
    fixed.validation.success;
  const afterExecution = shouldRetry ? await execute(fixed.recipe) : undefined;
  return { ...fixed, beforeExecution, afterExecution };
}

export function autoFixRecordsToValidationIssues(
  changes: AutoFixChange[],
): RecipeValidationIssue[] {
  return changes.map((change) => ({
    path: change.path,
    code: `auto_fix.${change.fix}`,
    message: `${change.reason}: ${JSON.stringify(change.before)} -> ${JSON.stringify(change.after)}`,
  }));
}

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function isRecipeLike(value: unknown): value is RecipeV01 {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { tables?: unknown }).tables)
  );
}

function isZeroRowExecution(execution: AutoFixInput["execution"]): boolean {
  return Boolean(execution?.zeroRows) || execution?.rowCount === 0;
}

function applySelectorNormalizations(
  recipe: RecipeV01,
  changes: AutoFixChange[],
): void {
  recipe.tables.forEach((table, tableIndex) => {
    normalizeSelectorAt(
      table.values,
      "cells",
      `tables.${tableIndex}.values.cells`,
      changes,
      table.name,
    );
    table.headers.forEach((header, headerIndex) => {
      normalizeSelectorAt(
        header,
        "cells",
        `tables.${tableIndex}.headers.${headerIndex}.cells`,
        changes,
        table.name,
        header.name,
      );
    });
  });
}

function normalizeSelectorAt(
  owner: { cells: CellSelector },
  key: "cells",
  path: string,
  changes: AutoFixChange[],
  table: string,
  header?: string,
): void {
  const before = owner[key];
  const after = normalizeSelector(before);
  if (after.changed) {
    owner[key] = after.selector;
    changes.push({
      fix: "selector_normalization",
      table,
      header,
      path,
      before,
      after: after.selector,
      reason: after.reason,
    });
  }
}

function normalizeSelector(
  selector: CellSelector,
): { changed: true; selector: CellSelector; reason: string } | { changed: false } {
  if (typeof selector === "string") {
    const single = singleCellRange(selector);
    if (single) {
      return {
        changed: true,
        selector: [single],
        reason: "Converted single-cell range string to an address list.",
      };
    }
    return { changed: false };
  }

  if (Array.isArray(selector)) {
    return { changed: false };
  }

  if (selector.range) {
    const single = singleCellRange(selector.range);
    if (single) {
      const rest = { ...selector };
      delete rest.range;
      return {
        changed: true,
        selector: { ...rest, cells: [single] },
        reason: "Converted single-cell selector range to cells[].",
      };
    }
  }

  return { changed: false };
}

function singleCellRange(value: string): string | null {
  if (!value.includes(":")) return null;
  try {
    const range = parseRange(value);
    if (
      range.start.row === range.end.row &&
      range.start.col === range.end.col
    ) {
      return formatCell(range.start);
    }
  } catch {
    return null;
  }
  return null;
}

function applyHeaderSpanExtensions(
  recipe: RecipeV01,
  changes: AutoFixChange[],
): void {
  recipe.tables.forEach((table, tableIndex) => {
    const valueRange = selectorRange(table.values.cells);
    if (!valueRange) return;

    table.headers.forEach((header, headerIndex) => {
      const headerRange = selectorRange(header.cells);
      if (!headerRange) return;
      const extended = extendedHeaderRange(table, header, valueRange, headerRange);
      if (!extended) return;

      const path = `tables.${tableIndex}.headers.${headerIndex}.cells`;
      const before = header.cells;
      header.cells = replaceSelectorRange(header.cells, extended);
      changes.push({
        fix: "header_span_extension",
        table: table.name,
        header: header.name,
        path,
        before,
        after: header.cells,
        reason: `Extended ${header.direction} header span to match the value span on its attachment axis.`,
      });
    });
  });
}

function selectorRange(selector: CellSelector) {
  try {
    if (typeof selector === "string") {
      return selector.includes(":")
        ? parseRange(selector)
        : { start: parseCell(selector), end: parseCell(selector) };
    }
    if (Array.isArray(selector)) {
      if (selector.length !== 1) return null;
      const cell = parseCell(selector[0]);
      return { start: cell, end: cell };
    }
    if (selector.range) return parseRange(selector.range);
    if (selector.cells?.length === 1) {
      const cell = parseCell(selector.cells[0]);
      return { start: cell, end: cell };
    }
  } catch {
    return null;
  }
  return null;
}

type ParsedRange = NonNullable<ReturnType<typeof selectorRange>>;

function extendedHeaderRange(
  table: TableSpec,
  header: HeaderSpec,
  values: ParsedRange,
  headerRange: ParsedRange,
): ParsedRange | null {
  const valueRows = span(values.start.row, values.end.row);
  const valueCols = span(values.start.col, values.end.col);
  const headerRows = span(headerRange.start.row, headerRange.end.row);
  const headerCols = span(headerRange.start.col, headerRange.end.col);

  if (header.direction === "N") {
    if (!isStrictSubset(headerCols, valueCols)) return null;
    if (headerRows.length > valueRows.length || spansOverlap(headerRows, valueRows)) {
      return null;
    }
    return {
      start: { row: headerRange.start.row, col: values.start.col },
      end: { row: headerRange.end.row, col: values.end.col },
    };
  }

  if (header.direction === "W") {
    if (!isStrictSubset(headerRows, valueRows)) return null;
    if (headerCols.length > valueCols.length || spansOverlap(headerCols, valueCols)) {
      return null;
    }
    return {
      start: { row: values.start.row, col: headerRange.start.col },
      end: { row: values.end.row, col: headerRange.end.col },
    };
  }

  void table;
  return null;
}

function replaceSelectorRange(selector: CellSelector, range: ParsedRange): CellSelector {
  const rangeText = formatRange(range);
  if (typeof selector === "string") return rangeText;
  if (Array.isArray(selector)) return { range: rangeText };
  const rest = { ...selector };
  delete rest.cells;
  return { ...rest, range: rangeText };
}

function span(start: number, end: number): number[] {
  const result: number[] = [];
  for (let value = start; value <= end; value += 1) result.push(value);
  return result;
}

function isStrictSubset(candidate: number[], container: number[]): boolean {
  if (candidate.length >= container.length) return false;
  const set = new Set(container);
  return candidate.every((value) => set.has(value));
}

function spansOverlap(left: number[], right: number[]): boolean {
  const set = new Set(right);
  return left.some((value) => set.has(value));
}

function applyDataTypeRelaxations(
  recipe: RecipeV01,
  changes: AutoFixChange[],
): void {
  recipe.tables.forEach((table, tableIndex) => {
    const selector = table.values.cells;
    if (typeof selector !== "object" || Array.isArray(selector)) return;
    const dataType = selector.where?.data_type;
    if (!dataType || dataType.length === 0) return;

    const before = deepClone(selector);
    const nextWhere = { ...(selector.where ?? {}) };
    delete nextWhere.data_type;
    nextWhere.non_blank = true;
    selector.where = nextWhere;
    changes.push({
      fix: "data_type_relaxation",
      table: table.name,
      path: `tables.${tableIndex}.values.cells.where`,
      before,
      after: selector,
      reason: "Relaxed values data_type filter to non_blank after a zero-row execution.",
    });
  });
}
