/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import type { ParsedSheet, ParsedWorkbook } from "./types.js";

export function findRecipeSheet(
  workbook: ParsedWorkbook,
  recipeSheetName: string,
): ParsedSheet | undefined {
  const exact = workbook.sheets.find((sheet) => sheet.name === recipeSheetName);

  if (exact) {
    return exact;
  }

  const normalizedRecipeName = normalizeSheetName(recipeSheetName);
  return workbook.sheets.find(
    (sheet) => normalizeSheetName(sheet.name) === normalizedRecipeName,
  );
}

function normalizeSheetName(value: string): string {
  return value.toLowerCase().replace(/\s+/g, "");
}
