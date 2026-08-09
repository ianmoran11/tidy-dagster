/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import { expandRange, parseCell } from "../address.js";
import type { CellSelector, RecipeV01 } from "../recipe/types.js";
import { hashString, stableJson } from "./styleFingerprint.js";
import type { CellDataType, ParsedSheet, TidyCell } from "../workbook/types.js";

export type SelectorWarningCode =
  | "EMPTY_SELECTION"
  | "OUT_OF_USED_RANGE"
  | "PREDICATE_FILTERED_ALL";

export type SelectorWarning = {
  code: SelectorWarningCode;
  message: string;
  table?: string;
  selector: string;
  address?: string;
};

export type ResolvedSelector = {
  selector: string;
  addresses: string[];
  warnings: SelectorWarning[];
};

export type ResolvedTableSelectors = {
  table: string;
  values: ResolvedSelector;
  headers: Array<{
    name: string;
    result: ResolvedSelector;
  }>;
};

export type ResolvedRecipeSelectors = {
  sheet: string;
  tables: ResolvedTableSelectors[];
  warnings: SelectorWarning[];
};

export function resolveSelector(
  selector: CellSelector,
  sheet: ParsedSheet,
  selectorName = "selector",
  tableName?: string,
  sheetCellMap?: Map<string, TidyCell>,
): ResolvedSelector {
  const cellMap =
    sheetCellMap ?? new Map(sheet.cells.map((cell) => [cell.address, cell]));
  const warnings: SelectorWarning[] = [];
  const candidates = getCandidateAddresses(selector);
  const uniqueCandidates = sortAddresses([...new Set(candidates)]);

  for (const address of uniqueCandidates) {
    if (isOutsideUsedRange(address, sheet)) {
      warnings.push({
        code: "OUT_OF_USED_RANGE",
        message: `Selected cell ${address} is outside the used range for sheet ${sheet.name}.`,
        selector: selectorName,
        table: tableName,
        address,
      });
    }
  }

  const where =
    typeof selector === "string" || Array.isArray(selector)
      ? undefined
      : selector.where;
  const filtered = where
    ? uniqueCandidates.filter((address) =>
        cellMatchesPredicate(cellMap.get(address), where),
      )
    : uniqueCandidates;

  if (uniqueCandidates.length > 0 && filtered.length === 0 && where) {
    warnings.push({
      code: "PREDICATE_FILTERED_ALL",
      message: `Predicate filtered all selected cells for ${selectorName}.`,
      selector: selectorName,
      table: tableName,
    });
  }

  if (filtered.length === 0) {
    warnings.push({
      code: "EMPTY_SELECTION",
      message: `Selector ${selectorName} resolved to no cells.`,
      selector: selectorName,
      table: tableName,
    });
  }

  return {
    selector: selectorName,
    addresses: sortAddresses(filtered),
    warnings,
  };
}

export function resolveRecipeSelectors(
  recipe: RecipeV01,
  sheet: ParsedSheet,
  sheetCellMap?: Map<string, TidyCell>,
): ResolvedRecipeSelectors {
  const cellMap =
    sheetCellMap ?? new Map(sheet.cells.map((cell) => [cell.address, cell]));
  const tables = recipe.tables.map((table) => {
    const values = resolveSelector(
      table.values.cells,
      sheet,
      `${table.name}.values`,
      table.name,
      cellMap,
    );
    const headers = table.headers.map((header) => ({
      name: header.name,
      result: resolveSelector(
        header.cells,
        sheet,
        `${table.name}.headers.${header.name}`,
        table.name,
        cellMap,
      ),
    }));

    return {
      table: table.name,
      values,
      headers,
    };
  });

  return {
    sheet: sheet.name,
    tables,
    warnings: tables.flatMap((table) => [
      ...table.values.warnings,
      ...table.headers.flatMap((header) => header.result.warnings),
    ]),
  };
}

function getCandidateAddresses(selector: CellSelector): string[] {
  if (typeof selector === "string") {
    return selector.includes(":") ? expandRange(selector) : [selector];
  }
  if (Array.isArray(selector)) {
    return selector;
  }

  return [
    ...(selector.range ? expandRange(selector.range) : []),
    ...(selector.cells ?? []),
  ];
}

export function cellMatchesPredicate(
  cell: TidyCell | undefined,
  where: NonNullable<Exclude<CellSelector, string | string[]>["where"]>,
): boolean {
  const dataType = cell?.data_type ?? "blank";

  if (where.data_type && !where.data_type.includes(dataType)) {
    return false;
  }

  if (where.non_blank === true && isBlank(cell, dataType)) {
    return false;
  }

  if (where.non_blank === false && !isBlank(cell, dataType)) {
    return false;
  }

  if (
    where.has_formula !== undefined &&
    Boolean(cell?.formula) !== where.has_formula
  ) {
    return false;
  }

  if (
    where.has_comment !== undefined &&
    Boolean(cell?.comment) !== where.has_comment
  ) {
    return false;
  }

  if (where.style_id) {
    if (!cell?.style) {
      return false;
    }
    const cellStyleId = `s_${hashString(stableJson(cell.style))}`;
    if (!where.style_id.includes(cellStyleId)) {
      return false;
    }
  }

  return true;
}

function isBlank(cell: TidyCell | undefined, dataType: CellDataType): boolean {
  return (
    dataType === "blank" || cell?.value === null || cell?.value === undefined
  );
}

function isOutsideUsedRange(address: string, sheet: ParsedSheet): boolean {
  const parsed = parseCell(address);
  return parsed.row > sheet.rowCount || parsed.col > sheet.columnCount;
}

function sortAddresses(addresses: string[]): string[] {
  return [...addresses].sort((left, right) => {
    const a = parseCell(left);
    const b = parseCell(right);

    if (a.row !== b.row) {
      return a.row - b.row;
    }

    return a.col - b.col;
  });
}
