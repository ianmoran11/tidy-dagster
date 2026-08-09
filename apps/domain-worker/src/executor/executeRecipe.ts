/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import { parseCell } from "../address.js";
import {
  buildHeaderDirectionGroups,
  isBlankRelationshipValue,
  resolveRelationshipAttachment,
  type HeaderDirectionGroup,
} from "./relationshipResolution.js";
import type {
  ExecutionResult,
  ExecutionTrace,
  ExecutionWarning,
  NonTableCell,
  OutputScalar,
  TidyOutputRow,
} from "./types.js";
import { resolveRecipeSelectors } from "../recipe/resolveSelectors.js";
import type {
  HeaderDirection,
  RecipeOptions,
  RecipeV01,
  TableSpec,
} from "../recipe/types.js";
import type { ParsedSheet, TidyCell } from "../workbook/types.js";

const DEFAULT_OPTIONS: Required<RecipeOptions> = {
  include_blank_values: false,
  preserve_source_address: true,
  preserve_header_source_address: true,
  preserve_formatted_value: false,
  preserve_non_table_cells: true,
  include_blank_non_table_cells: false,
};

export function executeRecipe(
  recipe: RecipeV01,
  sheet: ParsedSheet,
): ExecutionResult {
  const cellMap = new Map(sheet.cells.map((cell) => [cell.address, cell]));
  const resolved = resolveRecipeSelectors(recipe, sheet, cellMap);
  const warnings: ExecutionWarning[] = resolved.warnings.map((warning) => ({
    code: "SELECTOR_WARNING",
    message: warning.message,
    table: warning.table,
    address: warning.address,
  }));
  const referencedCells = new Set<string>();
  const valueOwners = new Map<string, string>();

  const tables = recipe.tables.map((table) => {
    const tableResolved = resolved.tables.find(
      (candidate) => candidate.table === table.name,
    );

    if (!tableResolved) {
      throw new Error(`Resolved selectors missing for table ${table.name}.`);
    }

    const tableOptions = {
      ...DEFAULT_OPTIONS,
      ...recipe.options,
      ...table.options,
    };
    const tableWarnings: ExecutionWarning[] = [];
    const rows: TidyOutputRow[] = [];
    const trace: ExecutionTrace = { value_cells: [] };
    const valueAddresses = tableResolved.values.addresses;

    if (valueAddresses.length === 0) {
      tableWarnings.push({
        code: "EMPTY_VALUE_SELECTION",
        message: `Table ${table.name} has no value cells.`,
        table: table.name,
      });
    }

    for (const address of valueAddresses) {
      const existingOwner = valueOwners.get(address);

      if (existingOwner && existingOwner !== table.name) {
        const warning = {
          code: "OVERLAPPING_VALUE_CELL" as const,
          message: `Value cell ${address} appears in both ${existingOwner} and ${table.name}.`,
          table: table.name,
          address,
        };
        tableWarnings.push(warning);
        warnings.push(warning);
      }

      valueOwners.set(address, table.name);
      referencedCells.add(address);
    }

    for (const header of tableResolved.headers) {
      if (header.result.addresses.length === 0) {
        tableWarnings.push({
          code: "EMPTY_HEADER_SELECTION",
          message: `Header ${header.name} in table ${table.name} has no cells.`,
          table: table.name,
          header: header.name,
        });
      }

      header.result.addresses.forEach((address) =>
        referencedCells.add(address),
      );
    }

    const headerUsage = new Map<string, number>();
    const headerLookup = buildHeaderLookup(table, tableResolved);

    for (const address of valueAddresses) {
      const sourceCell = getCellOrBlank(sheet, cellMap, address);

      if (!tableOptions.include_blank_values && isBlankCell(sourceCell)) {
        continue;
      }

      const outputRow: TidyOutputRow = {
        [table.values.name]: getOutputValue(sourceCell, tableOptions),
      };
      const source = {
        sheet: sheet.name,
        address,
        row: sourceCell.row,
        col: sourceCell.col,
      };
      const traceRow = {
        source,
        value: getOutputValue(sourceCell, tableOptions),
        headers: [] as ExecutionTrace["value_cells"][number]["headers"],
      };

      if (tableOptions.preserve_source_address) {
        outputRow._source = source;
      }

      for (const header of table.headers) {
        const attachment = attachHeader(
          headerLookup.get(header.name),
          sourceCell,
          cellMap,
        );
        const selected = attachment.selectedAddress
          ? getCellOrBlank(sheet, cellMap, attachment.selectedAddress)
          : undefined;

        outputRow[header.name] = selected
          ? getOutputValue(selected, tableOptions)
          : null;

        if (tableOptions.preserve_header_source_address) {
          outputRow[`${header.name}_source`] =
            attachment.selectedAddress ?? null;
        }

        if (attachment.selectedAddress) {
          headerUsage.set(
            attachment.selectedAddress,
            (headerUsage.get(attachment.selectedAddress) ?? 0) + 1,
          );
        }

        if (header.required && !attachment.selectedAddress) {
          tableWarnings.push({
            code: "MISSING_REQUIRED_HEADER",
            message: `Value cell ${address} is missing required header ${header.name}.`,
            table: table.name,
            header: header.name,
            address,
          });
        }

        if (attachment.ambiguous) {
          tableWarnings.push({
            code: "AMBIGUOUS_HEADER",
            message: `Multiple ${header.name} headers could attach to value cell ${address}.`,
            table: table.name,
            header: header.name,
            address,
          });
        }

        traceRow.headers.push({
          header: header.name,
          direction: attachment.direction ?? header.direction,
          candidates: attachment.candidates,
          selected: attachment.selectedAddress,
          value: selected ? getOutputValue(selected, tableOptions) : null,
          missing: !attachment.selectedAddress,
          ambiguous: attachment.ambiguous,
        });
      }

      rows.push(outputRow);
      trace.value_cells.push(traceRow);
    }

    for (const header of tableResolved.headers) {
      for (const address of header.result.addresses) {
        if (!headerUsage.has(address)) {
          tableWarnings.push({
            code: "UNUSED_HEADER",
            message: `Header cell ${address} was not attached to any value cell.`,
            table: table.name,
            header: header.name,
            address,
          });
        }
      }
    }

    warnings.push(...tableWarnings);

    return {
      table: table.name,
      sheet: sheet.name,
      rows,
      warnings: tableWarnings,
      trace,
    };
  });

  const preserveNonTable = { ...DEFAULT_OPTIONS, ...recipe.options }
    .preserve_non_table_cells;

  return {
    sheet: sheet.name,
    tables,
    non_table_cells: preserveNonTable
      ? getNonTableCells(sheet, referencedCells, recipe.options)
      : undefined,
    warnings,
  };
}

function attachHeader(
  resolvedHeader: HeaderLookupEntry | undefined,
  valueCell: TidyCell,
  cellMap: Map<string, TidyCell>,
): {
  candidates: string[];
  selectedAddress?: string;
  direction?: HeaderDirection;
  ambiguous: boolean;
} {
  if (!resolvedHeader || resolvedHeader.groups.length === 0) {
    return { candidates: [], ambiguous: false };
  }

  const resolved = resolveRelationshipAttachment(
    resolvedHeader.groups,
    valueCell,
  );
  if (!resolved.selectedAddress) {
    return { candidates: resolved.candidates, ambiguous: false };
  }

  const selectedAddress = resolved.selectedAddress;
  const selectedValue = cellMap.get(selectedAddress)?.value;
  const ambiguous = resolved.candidates
    .slice(1)
    .some((address) => cellMap.get(address)?.value !== selectedValue);

  return { ...resolved, selectedAddress, ambiguous };
}

type HeaderLookupEntry = {
  groups: HeaderDirectionGroup[];
};

function buildHeaderLookup(
  table: TableSpec,
  tableResolved: ReturnType<typeof resolveRecipeSelectors>["tables"][number],
): Map<string, HeaderLookupEntry> {
  const lookup = new Map<string, HeaderLookupEntry>();

  for (const header of table.headers) {
    const resolvedHeader = tableResolved.headers.find(
      (candidate) => candidate.name === header.name,
    );
    lookup.set(header.name, {
      groups: buildHeaderDirectionGroups({
        headerAddresses: resolvedHeader?.result.addresses ?? [],
        valueAddresses: tableResolved.values.addresses,
        direction: header.direction,
        fill: header.fill,
        directionOverrides: header.direction_overrides,
      }),
    });
  }

  return lookup;
}

function getNonTableCells(
  sheet: ParsedSheet,
  referencedCells: Set<string>,
  options: RecipeOptions | undefined,
): NonTableCell[] {
  const mergedOptions = { ...DEFAULT_OPTIONS, ...options };

  return sheet.cells
    .filter((cell) => !referencedCells.has(cell.address))
    .filter(
      (cell) =>
        mergedOptions.include_blank_non_table_cells || !isBlankCell(cell),
    )
    .map((cell) => {
      const nonTableCell: NonTableCell = {
        sheet: cell.sheet,
        address: cell.address,
        row: cell.row,
        col: cell.col,
        value: cell.value,
        data_type: cell.data_type,
        reason: "not_referenced_by_recipe",
      };

      if (cell.formatted && cell.formatted !== String(cell.value)) {
        nonTableCell.formatted = cell.formatted;
      }

      if (cell.formula) {
        nonTableCell.formula = cell.formula;
      }

      if (cell.comment) {
        nonTableCell.comment = cell.comment;
      }

      return nonTableCell;
    });
}

function getCellOrBlank(
  sheet: ParsedSheet,
  cellMap: Map<string, TidyCell>,
  address: string,
): TidyCell {
  const parsed = parseCell(address);

  return (
    cellMap.get(address) ?? {
      sheet: sheet.name,
      address,
      row: parsed.row,
      col: parsed.col,
      value: null,
      data_type: "blank",
    }
  );
}

function getOutputValue(
  cell: TidyCell,
  options: Required<RecipeOptions>,
): OutputScalar {
  if (options.preserve_formatted_value && cell.formatted) {
    return cell.formatted;
  }

  return cell.value;
}

function isBlankCell(cell: TidyCell): boolean {
  return isBlankRelationshipValue(cell);
}
