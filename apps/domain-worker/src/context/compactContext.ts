/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import { z } from "zod";
import { formatCell, formatRange, parseCell, parseRange } from "../address.js";
import type { RecipeV01 } from "../recipe/types.js";
import type {
  CellStyleSummary,
  ParsedSheet,
  TidyCell,
} from "../workbook/types.js";

export const COMPACT_CONTEXT_SCHEMA_VERSION =
  "cell-role-compact-context-v1" as const;
export const COMPACT_CONTEXT_ENCODING = "row-major-r1c1-json-v1" as const;
export const MAX_COMPACT_CONTEXT_ROWS = 5_000;
export const MAX_COMPACT_CONTEXT_COLUMNS = 512;
export const MAX_COMPACT_CONTEXT_CELLS = 500_000;
export const MAX_COMPACT_CONTEXT_INPUT_CELLS = 500_000;
export const MAX_COMPACT_CONTEXT_CHARACTERS = 1_000_000;

const GENERIC_PROMPT_TARGET_NAMES = new Set([
  "table",
  "value",
  "values",
  "state",
  "unit",
  "statistic",
  "variables",
]);
const MAX_EXPECTED_CSV_LEAK_SIGNATURES = 1_024;
const MIN_EXPECTED_CSV_ROW_SIGNATURE_LENGTH = 6;
const BENCHMARK_SCORE_PATTERN = new RegExp(
  String.raw`(?:\bbenchmark[\s_-]+(?:score|metric|result)|\bgraph[\s_-]+(?:score|similarity)|\bexact[\s_-]+csv[\s_-]+match(?:[\s_-]+rate)?|\bcell[\s_-]+exact[\s_-]+match(?:[\s_-]+rate)?|\bheader[\s_-]+(?:assignment[\s_-]+)?accuracy|\bassociation[\s_-]+(?:jaccard|similarity)|\b(?:f1|accuracy|precision|recall|similarity|score|match[\s_-]+rate|metric)\b)[^\d\n]{0,48}\d+(?:\.\d+)?%?`,
  "i",
);

const cellValueSchema = z.union([
  z.string(),
  z.number().finite(),
  z.boolean(),
  z.null(),
]);
const bandSchema = z.tuple([
  z.number().int().positive(),
  z.number().int().positive(),
]);
const styleBoundarySchema = z
  .object({
    row: z.number().int().positive(),
    startColumn: z.number().int().positive(),
    endColumn: z.number().int().positive(),
    style: z.string().min(1),
  })
  .strict();
const gridRowSchema = z
  .object({
    range: z.string().regex(/^R[1-9]\d*C[1-9]\d*:R[1-9]\d*C[1-9]\d*$/),
    values: z.array(cellValueSchema),
  })
  .strict();
export const compactContextSchema = z
  .object({
    schemaVersion: z.literal(COMPACT_CONTEXT_SCHEMA_VERSION),
    sheet: z.string().min(1),
    dimensions: z
      .object({
        rows: z.number().int().nonnegative(),
        columns: z.number().int().nonnegative(),
      })
      .strict(),
    usedRange: z.string().nullable(),
    merges: z.array(
      z
        .object({ parent: z.string().min(1), range: z.string().min(1) })
        .strict(),
    ),
    blankBands: z
      .object({ rows: z.array(bandSchema), columns: z.array(bandSchema) })
      .strict(),
    styleBoundaries: z.array(styleBoundarySchema),
    grid: z
      .object({
        encoding: z.literal(COMPACT_CONTEXT_ENCODING),
        rows: z.array(gridRowSchema),
      })
      .strict(),
  })
  .strict();

export type CompactSemanticContext = z.infer<typeof compactContextSchema>;

export type CompactContextSnapshot = {
  schemaVersion: typeof COMPACT_CONTEXT_SCHEMA_VERSION;
  digest: string;
  bytes: number;
  characters: number;
  estimatedTokens: number;
  addressValueEntries: number;
  duplicateAddressValueRepresentations: 0;
  serialized: string;
};

export type PromptLeakageInputs = {
  context: string;
  baselinePrompt: string;
  semanticsPrompt: string;
  forbiddenPaths: string[];
  targetNames: string[];
  expectedCsvContents: string[];
};

export function buildCompactContextSnapshot(
  sheet: ParsedSheet,
): CompactContextSnapshot {
  const context = buildCompactSemanticContext(sheet);
  const serialized = JSON.stringify(context);
  if (serialized.length > MAX_COMPACT_CONTEXT_CHARACTERS) {
    throw new Error(
      `COMPACT_CONTEXT_TOO_LARGE: serialized context has ${serialized.length} characters; maximum is ${MAX_COMPACT_CONTEXT_CHARACTERS}.`,
    );
  }
  assertCompactContextComplete(context);
  const bytes = Buffer.byteLength(serialized, "utf8");
  return {
    schemaVersion: COMPACT_CONTEXT_SCHEMA_VERSION,
    digest: sha256Bytes(Buffer.from(serialized, "utf8")),
    bytes,
    characters: serialized.length,
    estimatedTokens: estimateStaticTokens(serialized.length),
    addressValueEntries: sheet.rowCount * sheet.columnCount,
    duplicateAddressValueRepresentations: 0,
    serialized,
  };
}

export function buildCompactSemanticContext(
  sheet: ParsedSheet,
): CompactSemanticContext {
  assertInputBounds(sheet);
  const cellsByAddress = new Map<string, TidyCell>();
  for (const cell of sheet.cells) {
    const canonical = formatCell({ row: cell.row, col: cell.col });
    if (canonical !== cell.address) {
      throw new Error(
        `COMPACT_CONTEXT_NONCANONICAL_ADDRESS: ${JSON.stringify(cell.address)} must be ${canonical}.`,
      );
    }
    if (
      cell.row > sheet.rowCount ||
      cell.col > sheet.columnCount ||
      cell.row < 1 ||
      cell.col < 1
    ) {
      throw new Error(
        `COMPACT_CONTEXT_CELL_OUT_OF_BOUNDS: ${cell.address} is outside ${sheet.rowCount}x${sheet.columnCount}.`,
      );
    }
    if (cellsByAddress.has(cell.address)) {
      throw new Error(`COMPACT_CONTEXT_DUPLICATE_CELL: ${cell.address}.`);
    }
    cellsByAddress.set(cell.address, cell);
  }

  const gridRows: CompactSemanticContext["grid"]["rows"] = [];
  const blankRows: boolean[] = [];
  const columnHasValue = Array.from({ length: sheet.columnCount }, () => false);
  for (let row = 1; row <= sheet.rowCount; row += 1) {
    const values: Array<string | number | boolean | null> = [];
    let rowHasValue = false;
    for (let col = 1; col <= sheet.columnCount; col += 1) {
      const value = cellsByAddress.get(formatCell({ row, col }))?.value ?? null;
      values.push(value);
      if (value !== null) {
        rowHasValue = true;
        columnHasValue[col - 1] = true;
      }
    }
    blankRows.push(!rowHasValue);
    gridRows.push({
      range:
        sheet.columnCount === 0
          ? `${formatCell({ row, col: 1 })}:${formatCell({ row, col: 1 })}`
          : formatRange({
              start: { row, col: 1 },
              end: { row, col: sheet.columnCount },
            }),
      values,
    });
  }

  const context = compactContextSchema.parse({
    schemaVersion: COMPACT_CONTEXT_SCHEMA_VERSION,
    sheet: sheet.name,
    dimensions: { rows: sheet.rowCount, columns: sheet.columnCount },
    usedRange: sheet.usedRange,
    merges: [...sheet.merges].sort(compareMergeRanges),
    blankBands: {
      rows: toBands(blankRows),
      columns: toBands(columnHasValue.map((hasValue) => !hasValue)),
    },
    styleBoundaries: buildStyleBoundaries(sheet, cellsByAddress),
    grid: { encoding: COMPACT_CONTEXT_ENCODING, rows: gridRows },
  });
  return context;
}

export function parseCompactContext(
  serialized: string,
): CompactSemanticContext {
  if (serialized.length > MAX_COMPACT_CONTEXT_CHARACTERS) {
    throw new Error("COMPACT_CONTEXT_TOO_LARGE");
  }
  let value: unknown;
  try {
    value = JSON.parse(serialized);
  } catch {
    throw new Error("COMPACT_CONTEXT_INVALID_JSON");
  }
  const context = compactContextSchema.parse(value);
  assertCompactContextComplete(context);
  if (JSON.stringify(context) !== serialized) {
    throw new Error("COMPACT_CONTEXT_NONCANONICAL_SERIALIZATION");
  }
  return context;
}

export function assertCompactContextComplete(
  context: CompactSemanticContext,
): void {
  const { rows, columns } = context.dimensions;
  if (rows > MAX_COMPACT_CONTEXT_ROWS) {
    throw new Error("COMPACT_CONTEXT_ROW_LIMIT_EXCEEDED");
  }
  if (columns > MAX_COMPACT_CONTEXT_COLUMNS) {
    throw new Error("COMPACT_CONTEXT_COLUMN_LIMIT_EXCEEDED");
  }
  if (context.grid.rows.length !== rows) {
    throw new Error(
      `COMPACT_CONTEXT_INCOMPLETE_ROWS: expected ${rows}, received ${context.grid.rows.length}.`,
    );
  }
  for (let index = 0; index < context.grid.rows.length; index += 1) {
    const row = context.grid.rows[index];
    const rowNumber = index + 1;
    const expectedRange = formatRange({
      start: { row: rowNumber, col: 1 },
      end: { row: rowNumber, col: Math.max(columns, 1) },
    });
    if (row.range !== expectedRange || row.values.length !== columns) {
      throw new Error(
        `COMPACT_CONTEXT_INCOMPLETE_ROW: row ${rowNumber} must contain ${columns} values and range ${expectedRange}.`,
      );
    }
  }
  if (rows * columns > MAX_COMPACT_CONTEXT_CELLS) {
    throw new Error("COMPACT_CONTEXT_CELL_LIMIT_EXCEEDED");
  }
  if (context.usedRange) {
    const used = parseRange(context.usedRange);
    if (used.end.row > rows || used.end.col > columns) {
      throw new Error("COMPACT_CONTEXT_USED_RANGE_OUT_OF_BOUNDS");
    }
  }
}

export function assertPromptContractNoLeakage(
  input: PromptLeakageInputs,
): void {
  const allText = [input.context, input.baselinePrompt, input.semanticsPrompt];
  for (const forbiddenPath of input.forbiddenPaths.filter(Boolean)) {
    if (allText.some((text) => text.includes(forbiddenPath))) {
      throw new Error(
        `PROMPT_CONTEXT_LEAKAGE_PATH: ${JSON.stringify(forbiddenPath)}.`,
      );
    }
  }

  const allJoined = allText.join("\n");
  if (
    /(?:semantic-gold|gold\/|gold\\|accepted-recipe|expected[_-]?overlay)/i.test(
      allJoined,
    )
  ) {
    throw new Error("PROMPT_CONTEXT_LEAKAGE_FORBIDDEN_EVIDENCE");
  }

  const instructions = [
    extractInstructionEnvelope(input.baselinePrompt, input.context),
    extractInstructionEnvelope(input.semanticsPrompt, input.context),
  ];
  const normalizedInstructions = normalizeLeakText(instructions.join("\n"));

  for (const targetName of input.targetNames) {
    const normalizedTarget = normalizeLeakText(targetName);
    if (normalizedTarget.length < 3) continue;
    const variants = new Set([
      normalizedTarget,
      normalizeLeakText(targetName.replace(/[_-]+/g, " ")),
    ]);
    const generic = GENERIC_PROMPT_TARGET_NAMES.has(normalizedTarget);
    for (const variant of variants) {
      const targetPattern = targetNamePattern(variant, generic);
      if (targetPattern.test(normalizedInstructions)) {
        throw new Error(
          `PROMPT_CONTEXT_LEAKAGE_TARGET_NAME: ${JSON.stringify(targetName.trim())}.`,
        );
      }
    }
  }

  for (const expectedCsv of input.expectedCsvContents) {
    for (const signature of expectedCsvLeakSignatures(expectedCsv)) {
      if (normalizedInstructions.includes(signature)) {
        throw new Error("PROMPT_CONTEXT_LEAKAGE_EXPECTED_CSV");
      }
    }
  }

  if (BENCHMARK_SCORE_PATTERN.test(normalizedInstructions)) {
    throw new Error("PROMPT_CONTEXT_LEAKAGE_FORBIDDEN_EVIDENCE");
  }
}

export function collectRecipeTargetNames(recipe: RecipeV01): string[] {
  return recipe.tables.flatMap((table) => [
    table.name,
    table.values.name,
    ...table.headers.map((header) => header.name),
  ]);
}

export function estimateStaticTokens(characters: number): number {
  return Math.ceil(characters / 4);
}

export function countDuplicateCanonicalAddresses(text: string): {
  addressOccurrences: number;
  uniqueAddresses: number;
  duplicatedAddressOccurrences: number;
} {
  const matches = text.match(/R[1-9]\d*C[1-9]\d*/g) ?? [];
  const unique = new Set(matches);
  return {
    addressOccurrences: matches.length,
    uniqueAddresses: unique.size,
    duplicatedAddressOccurrences: matches.length - unique.size,
  };
}

function assertInputBounds(sheet: ParsedSheet): void {
  if (sheet.rowCount > MAX_COMPACT_CONTEXT_ROWS) {
    throw new Error(
      `COMPACT_CONTEXT_ROW_LIMIT_EXCEEDED: ${sheet.rowCount} > ${MAX_COMPACT_CONTEXT_ROWS}.`,
    );
  }
  if (sheet.columnCount > MAX_COMPACT_CONTEXT_COLUMNS) {
    throw new Error(
      `COMPACT_CONTEXT_COLUMN_LIMIT_EXCEEDED: ${sheet.columnCount} > ${MAX_COMPACT_CONTEXT_COLUMNS}.`,
    );
  }
  if (sheet.cells.length > MAX_COMPACT_CONTEXT_INPUT_CELLS) {
    throw new Error(
      `COMPACT_CONTEXT_INPUT_CELL_LIMIT_EXCEEDED: ${sheet.cells.length} > ${MAX_COMPACT_CONTEXT_INPUT_CELLS}.`,
    );
  }
  const gridCells = sheet.rowCount * sheet.columnCount;
  if (
    !Number.isSafeInteger(gridCells) ||
    gridCells > MAX_COMPACT_CONTEXT_CELLS
  ) {
    throw new Error(
      `COMPACT_CONTEXT_CELL_LIMIT_EXCEEDED: ${gridCells} > ${MAX_COMPACT_CONTEXT_CELLS}.`,
    );
  }
  if ((sheet.rowCount === 0) !== (sheet.columnCount === 0)) {
    throw new Error("COMPACT_CONTEXT_INVALID_DIMENSIONS");
  }
}

function buildStyleBoundaries(
  sheet: ParsedSheet,
  cellsByAddress: ReadonlyMap<string, TidyCell>,
): CompactSemanticContext["styleBoundaries"] {
  const result: CompactSemanticContext["styleBoundaries"] = [];
  for (let row = 1; row <= sheet.rowCount; row += 1) {
    let startColumn = 0;
    let activeStyle = "";
    const flush = (endColumn: number) => {
      if (!activeStyle) return;
      result.push({ row, startColumn, endColumn, style: activeStyle });
    };
    for (let col = 1; col <= sheet.columnCount + 1; col += 1) {
      const style =
        col <= sheet.columnCount
          ? minimalStyleSignature(
              cellsByAddress.get(formatCell({ row, col }))?.style,
            )
          : "";
      if (style === activeStyle) continue;
      flush(col - 1);
      activeStyle = style;
      startColumn = col;
    }
  }
  return result;
}

function minimalStyleSignature(style: CellStyleSummary | undefined): string {
  if (!style) return "";
  const tokens = [
    style.bold ? "b" : "",
    style.italic ? "i" : "",
    style.fontSize ? `s${style.fontSize}` : "",
    style.fontColor ? `fc${style.fontColor}` : "",
    style.fillColor ? `bg${style.fillColor}` : "",
    style.horizontalAlign ? `h${style.horizontalAlign}` : "",
    style.border?.top ? "bt" : "",
    style.border?.right ? "br" : "",
    style.border?.bottom ? "bb" : "",
    style.border?.left ? "bl" : "",
  ].filter(Boolean);
  return tokens.join("|");
}

function toBands(flags: boolean[]): Array<[number, number]> {
  const bands: Array<[number, number]> = [];
  let start = -1;
  for (let index = 0; index <= flags.length; index += 1) {
    if (flags[index] && start === -1) start = index + 1;
    if ((!flags[index] || index === flags.length) && start !== -1) {
      bands.push([start, index]);
      start = -1;
    }
  }
  return bands;
}

function compareMergeRanges(
  left: { parent: string; range: string },
  right: { parent: string; range: string },
): number {
  const a = parseCell(left.parent);
  const b = parseCell(right.parent);
  return (
    a.row - b.row || a.col - b.col || left.range.localeCompare(right.range)
  );
}

function normalizeLeakText(value: string): string {
  return value
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function targetNamePattern(targetName: string, generic: boolean): RegExp {
  const escaped = escapeRegExp(targetName);
  const boundedTarget = `(?:^|[^\\p{L}\\p{N}_])${escaped}(?=$|[^\\p{L}\\p{N}_])`;
  if (!generic) return new RegExp(boundedTarget, "iu");
  return new RegExp(
    `(?:accepted|expected|gold|recipe|target|output(?: name| label)?|label|named|use)(?:.{0,64})${boundedTarget}`,
    "iu",
  );
}

function expectedCsvLeakSignatures(expectedCsv: string): string[] {
  const rawLines = expectedCsv
    .normalize("NFKC")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .filter((line) => line.trim().length > 0);
  const lines = rawLines.map((line) => normalizeLeakText(line));
  const signatures = new Set<string>();
  const complete = normalizeLeakText(expectedCsv);
  if (complete.length >= 16) signatures.add(complete);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (
      line.length >= MIN_EXPECTED_CSV_ROW_SIGNATURE_LENGTH &&
      /[,;\t|]/.test(rawLines[index])
    ) {
      signatures.add(line);
    }
    if (index + 1 < lines.length) {
      const window = `${line} ${lines[index + 1]}`;
      if (window.length >= 16) signatures.add(window);
    }
    if (signatures.size >= MAX_EXPECTED_CSV_LEAK_SIGNATURES) break;
  }
  return [...signatures];
}

function extractInstructionEnvelope(prompt: string, context: string): string {
  if (!context) throw new Error("PROMPT_CONTEXT_BINDING_MISMATCH");
  const first = prompt.indexOf(context);
  if (first < 0 || prompt.indexOf(context, first + context.length) >= 0) {
    throw new Error("PROMPT_CONTEXT_BINDING_MISMATCH");
  }
  return `${prompt.slice(0, first)}${prompt.slice(first + context.length)}`;
}

function sha256Bytes(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
