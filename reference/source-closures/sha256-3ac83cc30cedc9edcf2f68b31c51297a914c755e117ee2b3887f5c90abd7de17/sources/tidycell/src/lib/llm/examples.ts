import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import type { PromptExample } from "@/lib/llm/types";
import { validateRecipe } from "@/lib/recipe/schema";

const DEFAULT_EXAMPLE_LIMIT = 4;

export function loadPromptExamples(
  examplesDir = path.join(process.cwd(), "fixtures", "recipes"),
  limit = DEFAULT_EXAMPLE_LIMIT,
): PromptExample[] {
  let filenames: string[];

  try {
    filenames = readdirSync(examplesDir)
      .filter((filename) => filename.endsWith(".json"))
      .sort();
  } catch {
    return [];
  }

  const examples: PromptExample[] = [];

  for (const filename of filenames) {
    if (examples.length >= limit) {
      break;
    }

    const example = readPromptExample(path.join(examplesDir, filename));

    if (example) {
      examples.push({ filename, recipe: example });
    }
  }

  return examples;
}

function readPromptExample(filePath: string): PromptExample["recipe"] | null {
  try {
    const parsed = JSON.parse(readFileSync(filePath, "utf8"));
    const cleaned = normalizeExampleRecipe(stripDiagnosticFields(parsed));
    const result = validateRecipe(cleaned);

    return result.success ? result.data : null;
  } catch {
    return null;
  }
}

function stripDiagnosticFields(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stripDiagnosticFields);
  }

  if (!value || typeof value !== "object") {
    return value;
  }

  const output: Record<string, unknown> = {};

  for (const [key, entry] of Object.entries(value)) {
    if (key.startsWith(".")) {
      continue;
    }

    output[key] = stripDiagnosticFields(entry);
  }

  return output;
}

function normalizeExampleRecipe(value: unknown): unknown {
  if (!value || typeof value !== "object") {
    return value;
  }

  const recipe = value as {
    tables?: Array<{
      values?: { cells?: unknown };
      headers?: Array<{ cells?: unknown }>;
    }>;
  };

  if (!Array.isArray(recipe.tables)) {
    return value;
  }

  return {
    ...(value as Record<string, unknown>),
    tables: recipe.tables.map((table) => ({
      ...table,
      values: table.values
        ? { ...table.values, cells: normalizeCells(table.values.cells) }
        : table.values,
      headers: Array.isArray(table.headers)
        ? table.headers.map((header) => ({
            ...header,
            cells: normalizeCells(header.cells),
          }))
        : table.headers,
    })),
  };
}

function normalizeCells(cells: unknown): unknown {
  if (typeof cells !== "string") {
    return cells;
  }

  return cells.includes(":") ? { range: cells } : [cells];
}
