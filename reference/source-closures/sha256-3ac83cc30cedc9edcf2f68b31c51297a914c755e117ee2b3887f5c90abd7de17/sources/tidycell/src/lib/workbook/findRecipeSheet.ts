import type { ParsedSheet, ParsedWorkbook } from "./types";

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
