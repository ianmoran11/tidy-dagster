import { z } from "zod";
import { DEFAULT_CANDIDATE_RANGE_HINT_MAX_CHARACTERS } from "@/lib/llm/candidateRangeHints";
import type { PromptExample } from "@/lib/llm/types";

const tableCompressionSchema = z
  .object({
    collapseBlankRows: z.boolean().optional(),
    collapseBlankColumns: z.boolean().optional(),
    collapseRepeatedRows: z.boolean().optional(),
    cellCharCap: z.number().int().min(1).max(1000).optional(),
    rowSampling: z
      .union([
        z.boolean(),
        z
          .object({
            firstRows: z.number().int().min(0).max(200).optional(),
            lastRows: z.number().int().min(0).max(200).optional(),
            boundaryPadding: z.number().int().min(0).max(50).optional(),
          })
          .strict(),
      ])
      .optional(),
    noHtml: z.boolean().optional(),
  })
  .strict();

export const promptVariantSchema = z
  .object({
    name: z.string().min(1).optional(),
    exampleCount: z.number().int().min(0).max(4).optional(),
    exampleFormat: z.enum(["pretty", "minified"]).optional(),
    includeExampleFilenames: z.boolean().optional(),
    exampleSource: z.enum(["real", "schema_skeleton"]).optional(),
    ruleTier: z.enum(["full", "core", "minimal"]).optional(),
    conditionalSections: z.boolean().optional(),
    tableContextMode: z.enum(["markdown_compact", "html_expanded"]).optional(),
    summaryFields: z.enum(["full", "compact"]).optional(),
    repairScope: z.enum(["full", "focused"]).optional(),
    rangeGuidance: z.boolean().optional(),
    candidateRangeHints: z.enum(["off", "tidybank-v1"]).optional(),
    candidateRangeHintMaxCharacters: z
      .number()
      .int()
      .min(500)
      .max(5_000)
      .optional(),
    tableCompression: tableCompressionSchema.optional(),
  })
  .strict();

export type PromptVariant = z.infer<typeof promptVariantSchema>;

export type ResolvedPromptVariant = Required<
  Pick<
    PromptVariant,
    | "exampleCount"
    | "exampleFormat"
    | "includeExampleFilenames"
    | "exampleSource"
    | "ruleTier"
    | "conditionalSections"
    | "summaryFields"
    | "repairScope"
    | "rangeGuidance"
    | "candidateRangeHints"
    | "candidateRangeHintMaxCharacters"
  >
> &
  Pick<PromptVariant, "name" | "tableContextMode" | "tableCompression">;

export const BASELINE_PROMPT_VARIANT: ResolvedPromptVariant = {
  name: "baseline",
  exampleCount: 4,
  exampleFormat: "pretty",
  includeExampleFilenames: true,
  exampleSource: "real",
  ruleTier: "full",
  conditionalSections: false,
  summaryFields: "full",
  repairScope: "full",
  rangeGuidance: false,
  candidateRangeHints: "off",
  candidateRangeHintMaxCharacters: DEFAULT_CANDIDATE_RANGE_HINT_MAX_CHARACTERS,
};

export function resolvePromptVariant(
  variant?: PromptVariant,
): ResolvedPromptVariant {
  const resolved = {
    ...BASELINE_PROMPT_VARIANT,
    ...(variant ?? {}),
  };

  return resolved;
}

export function examplesForPromptVariant(
  examples: PromptExample[],
  variant?: PromptVariant,
): PromptExample[] {
  const resolved = resolvePromptVariant(variant);

  return resolved.exampleSource === "schema_skeleton"
    ? []
    : examples.slice(0, resolved.exampleCount);
}

export function formatPromptExample(
  example: PromptExample,
  variant?: PromptVariant,
): string {
  const resolved = resolvePromptVariant(variant);
  const recipeJson = formatRecipeJson(
    resolved.rangeGuidance
      ? convertContiguousCellListsToRanges(example.recipe)
      : example.recipe,
    resolved.exampleFormat,
  );

  return resolved.includeExampleFilenames
    ? [`Example filename: ${example.filename}`, recipeJson].join("\n")
    : recipeJson;
}

export function schemaSkeletonExample(variant?: PromptVariant): string {
  const resolved = resolvePromptVariant(variant);
  return formatRecipeJson(SCHEMA_SKELETON_RECIPE, resolved.exampleFormat);
}

function formatRecipeJson(
  recipe: unknown,
  format: "pretty" | "minified",
): string {
  return format === "minified"
    ? JSON.stringify(recipe)
    : JSON.stringify(recipe, null, 2);
}

function convertContiguousCellListsToRanges(recipe: unknown): unknown {
  if (!recipe || typeof recipe !== "object") return recipe;

  return {
    ...(recipe as Record<string, unknown>),
    tables: Array.isArray((recipe as { tables?: unknown[] }).tables)
      ? (recipe as { tables: unknown[] }).tables.map((table) =>
          convertTableCellLists(table),
        )
      : (recipe as { tables?: unknown }).tables,
  };
}

function convertTableCellLists(table: unknown): unknown {
  if (!table || typeof table !== "object") return table;
  const typed = table as {
    values?: Record<string, unknown>;
    headers?: Array<Record<string, unknown>>;
  };

  return {
    ...typed,
    values: typed.values
      ? { ...typed.values, cells: contiguousRangeSelector(typed.values.cells) }
      : typed.values,
    headers: Array.isArray(typed.headers)
      ? typed.headers.map((header) => ({
          ...header,
          cells: contiguousRangeSelector(header.cells),
        }))
      : typed.headers,
  };
}

function contiguousRangeSelector(cells: unknown): unknown {
  if (
    !Array.isArray(cells) ||
    cells.length < 2 ||
    !cells.every((cell) => typeof cell === "string")
  ) {
    return cells;
  }

  const parsed = cells.map((cell) => {
    const match = /^R(\d+)C(\d+)$/.exec(cell);
    return match
      ? { address: cell, row: Number(match[1]), col: Number(match[2]) }
      : null;
  });
  if (parsed.some((cell) => cell === null)) return cells;

  const addresses = parsed as Array<{
    address: string;
    row: number;
    col: number;
  }>;
  const sameRow = addresses.every((cell) => cell.row === addresses[0].row);
  const sameColumn = addresses.every((cell) => cell.col === addresses[0].col);
  if (!sameRow && !sameColumn) return cells;

  const ordered = [...addresses].sort((left, right) =>
    sameRow ? left.col - right.col : left.row - right.row,
  );
  const contiguous = ordered.every(
    (cell, index) =>
      index === 0 ||
      (sameRow
        ? cell.col === ordered[index - 1].col + 1
        : cell.row === ordered[index - 1].row + 1),
  );

  return contiguous
    ? { range: `${ordered[0].address}:${ordered[ordered.length - 1].address}` }
    : cells;
}

const SCHEMA_SKELETON_RECIPE = {
  version: "0.1",
  sheet: "Example sheet",
  tables: [
    {
      name: "observations",
      values: {
        name: "value",
        cells: { range: "R5C3:R10C6", where: { non_blank: true } },
      },
      headers: [
        {
          name: "row_label",
          direction: "W",
          cells: { range: "R5C1:R10C1" },
        },
        {
          name: "column_label",
          direction: "N",
          fill: "right",
          cells: { range: "R3C3:R3C6" },
        },
        {
          name: "section",
          direction: "WNW",
          cells: { range: "R4C1:R10C1" },
        },
      ],
    },
  ],
};
