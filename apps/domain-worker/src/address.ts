/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
export type CellAddress = {
  row: number;
  col: number;
};

export type CellRange = {
  start: CellAddress;
  end: CellAddress;
};

export type AddressErrorCode =
  | "EMPTY_ADDRESS"
  | "INVALID_CELL"
  | "INVALID_RANGE"
  | "OUT_OF_BOUNDS";

const R1C1_CELL_PATTERN = /^R([1-9]\d*)C([1-9]\d*)$/;
const A1_CELL_PATTERN = /^([A-Z]+)([1-9]\d*)$/i;
// Excel worksheet limits. Addresses beyond these cannot exist in a workbook,
// and rejecting them keeps range expansion bounded.
export const MAX_ROW = 1_048_576;
export const MAX_COL = 16_384;
// Upper bound on cells a single range may expand to. Guards against
// LLM-generated or hand-written recipes that select absurd ranges and would
// otherwise exhaust memory when the range is materialized.
export const MAX_EXPANDED_RANGE_CELLS = 2_000_000;

export class AddressValidationError extends Error {
  readonly code: AddressErrorCode;
  readonly input: string;

  constructor(code: AddressErrorCode, input: string, message: string) {
    super(message);
    this.name = "AddressValidationError";
    this.code = code;
    this.input = input;
  }
}

export function isAddressValidationError(
  error: unknown,
): error is AddressValidationError {
  return error instanceof AddressValidationError;
}

export function parseCell(input: string): CellAddress {
  const address = normalizeInput(input);
  const match = R1C1_CELL_PATTERN.exec(address);

  if (!match) {
    throw new AddressValidationError(
      "INVALID_CELL",
      input,
      `Expected an R1C1 address like R3C4, received ${JSON.stringify(input)}.`,
    );
  }

  return {
    row: parseRowOrCol(match[1], "row", input),
    col: parseRowOrCol(match[2], "col", input),
  };
}

export function formatCell(address: CellAddress): string {
  assertRowOrCol(address.row, "row", "row");
  assertRowOrCol(address.col, "col", "col");

  return `R${address.row}C${address.col}`;
}

export function parseRange(input: string): CellRange {
  const range = normalizeInput(input);
  const parts = range.split(":");

  if (parts.length !== 2 || parts.some((part) => part.length === 0)) {
    throw new AddressValidationError(
      "INVALID_RANGE",
      input,
      `Expected an R1C1 range like R3C4:R4C5, received ${JSON.stringify(input)}.`,
    );
  }

  const start = parseCell(parts[0]);
  const end = parseCell(parts[1]);

  if (start.row > end.row || start.col > end.col) {
    throw new AddressValidationError(
      "INVALID_RANGE",
      input,
      `Range start must be above and to the left of range end: ${input}.`,
    );
  }

  return { start, end };
}

export function formatRange(range: CellRange): string {
  if (range.start.row > range.end.row || range.start.col > range.end.col) {
    throw new AddressValidationError(
      "INVALID_RANGE",
      `${formatCell(range.start)}:${formatCell(range.end)}`,
      "Range start must be above and to the left of range end.",
    );
  }

  return `${formatCell(range.start)}:${formatCell(range.end)}`;
}

export function expandRange(input: string | CellRange): string[] {
  const range = typeof input === "string" ? parseRange(input) : input;
  const cellCount =
    (range.end.row - range.start.row + 1) *
    (range.end.col - range.start.col + 1);

  if (cellCount > MAX_EXPANDED_RANGE_CELLS) {
    throw new AddressValidationError(
      "OUT_OF_BOUNDS",
      typeof input === "string" ? input : formatRange(input),
      `Range expands to ${cellCount} cells, which exceeds the supported maximum of ${MAX_EXPANDED_RANGE_CELLS}.`,
    );
  }

  const addresses: string[] = [];

  for (let row = range.start.row; row <= range.end.row; row += 1) {
    for (let col = range.start.col; col <= range.end.col; col += 1) {
      addresses.push(formatCell({ row, col }));
    }
  }

  return addresses;
}

// Loop-based bounding box. Spreading large address arrays into Math.min/max
// overflows the call stack, so this must stay iterative.
export function boundingRangeOf(addresses: string[]): CellRange {
  if (addresses.length === 0) {
    throw new AddressValidationError(
      "EMPTY_ADDRESS",
      "",
      "Cannot compute the bounding range of an empty address list.",
    );
  }

  const first = parseCell(addresses[0]);
  let minRow = first.row;
  let maxRow = first.row;
  let minCol = first.col;
  let maxCol = first.col;

  for (let index = 1; index < addresses.length; index += 1) {
    const cell = parseCell(addresses[index]);
    minRow = Math.min(minRow, cell.row);
    maxRow = Math.max(maxRow, cell.row);
    minCol = Math.min(minCol, cell.col);
    maxCol = Math.max(maxCol, cell.col);
  }

  return {
    start: { row: minRow, col: minCol },
    end: { row: maxRow, col: maxCol },
  };
}

export function parseA1Cell(input: string): CellAddress {
  const address = normalizeInput(input);
  const match = A1_CELL_PATTERN.exec(address);

  if (!match) {
    throw new AddressValidationError(
      "INVALID_CELL",
      input,
      `Expected an A1 address like D3, received ${JSON.stringify(input)}.`,
    );
  }

  return {
    row: parseRowOrCol(match[2], "row", input),
    col: lettersToColumn(match[1]),
  };
}

export function parseA1Range(input: string): CellRange {
  const range = normalizeInput(input);
  const parts = range.split(":");

  if (parts.length !== 2 || parts.some((part) => part.length === 0)) {
    throw new AddressValidationError(
      "INVALID_RANGE",
      input,
      `Expected an A1 range like D3:G8, received ${JSON.stringify(input)}.`,
    );
  }

  const start = parseA1Cell(parts[0]);
  const end = parseA1Cell(parts[1]);

  if (start.row > end.row || start.col > end.col) {
    throw new AddressValidationError(
      "INVALID_RANGE",
      input,
      `Range start must be above and to the left of range end: ${input}.`,
    );
  }

  return { start, end };
}

export function a1ToR1C1(input: string): string {
  return formatCell(parseA1Cell(input));
}

export function a1RangeToR1C1(input: string): string {
  return formatRange(parseA1Range(input));
}

function normalizeInput(input: string): string {
  if (typeof input !== "string" || input.trim().length === 0) {
    throw new AddressValidationError(
      "EMPTY_ADDRESS",
      String(input),
      "Address input must be a non-empty string.",
    );
  }

  return input.trim().toUpperCase();
}

function parseRowOrCol(
  value: string,
  kind: "row" | "col",
  input: string,
): number {
  const parsed = Number(value);
  assertRowOrCol(parsed, kind, input);
  return parsed;
}

function assertRowOrCol(
  value: number,
  kind: "row" | "col",
  input: string,
): void {
  const max = kind === "row" ? MAX_ROW : MAX_COL;

  if (!Number.isSafeInteger(value) || value < 1 || value > max) {
    throw new AddressValidationError(
      "OUT_OF_BOUNDS",
      input,
      `${kind === "row" ? "Rows" : "Columns"} must be integers between 1 and ${max}, received ${value}.`,
    );
  }
}

function lettersToColumn(letters: string): number {
  let col = 0;

  for (const letter of letters.toUpperCase()) {
    col = col * 26 + letter.charCodeAt(0) - 64;

    if (col > MAX_COL) {
      throw new AddressValidationError(
        "OUT_OF_BOUNDS",
        letters,
        `Column letters exceed the supported range: ${letters}.`,
      );
    }
  }

  return col;
}
