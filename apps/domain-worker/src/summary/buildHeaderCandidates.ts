/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import type { HeaderCandidate } from "./types.js";
import type { ParsedSheet, TidyCell } from "../workbook/types.js";

type HeaderGroup = {
  value: string;
  addresses: string[];
  minRow: number;
};

export function buildHeaderCandidates(sheet: ParsedSheet): HeaderCandidate[] {
  const groups = new Map<string, HeaderGroup>();

  for (const cell of sheet.cells) {
    const value = displayValue(cell).trim();

    if (value.length === 0 || isNumericLike(cell, value)) {
      continue;
    }

    const existing = groups.get(value);

    if (existing) {
      existing.addresses.push(cell.address);
      existing.minRow = Math.min(existing.minRow, cell.row);
      continue;
    }

    groups.set(value, {
      value,
      addresses: [cell.address],
      minRow: cell.row,
    });
  }

  return [...groups.values()]
    .sort(
      (left, right) =>
        left.minRow - right.minRow || left.value.localeCompare(right.value),
    )
    .map((group) => ({
      value: group.value,
      addresses:
        group.addresses.length === 1 ? group.addresses[0] : group.addresses,
    }));
}

function isNumericLike(cell: TidyCell, value: string): boolean {
  if (cell.data_type === "numeric") {
    return true;
  }

  const normalized = value.trim();

  if (normalized.length === 0) {
    return false;
  }

  return Number.isFinite(Number(normalized));
}

function displayValue(cell: TidyCell): string {
  if (cell.formatted !== null && cell.formatted !== undefined) {
    return cell.formatted;
  }

  if (cell.value === null) {
    return "";
  }

  return String(cell.value);
}
