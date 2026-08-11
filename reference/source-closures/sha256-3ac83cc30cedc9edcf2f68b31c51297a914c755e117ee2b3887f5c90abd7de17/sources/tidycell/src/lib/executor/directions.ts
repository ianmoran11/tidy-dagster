import { parseCell } from "@/lib/address";
import type { HeaderDirection } from "@/lib/recipe/types";

export type HeaderCandidate = {
  address: string;
  row: number;
  col: number;
  spanEndRow: number;
  spanEndCol: number;
};

export type ValuePosition = {
  row: number;
  col: number;
};

export function findHeaderCandidates(
  direction: HeaderDirection,
  headers: HeaderCandidate[],
  value: ValuePosition,
): HeaderCandidate[] {
  const candidates = headers.filter((header) => {
    switch (direction) {
      case "N":
        return header.col === value.col && header.row < value.row;
      case "W":
        return header.row === value.row && header.col < value.col;
      case "NNW":
        return (
          header.row < value.row &&
          header.col <= value.col &&
          header.spanEndCol >= value.col
        );
      case "WNW":
        return (
          header.col < value.col &&
          header.row <= value.row &&
          header.spanEndRow >= value.row
        );
    }
  });

  return candidates.sort((left, right) =>
    compareCandidates(direction, left, right),
  );
}

export function buildHeaderCandidates(
  addresses: string[],
  fill: "right" | "down" | undefined,
  valueAddresses: string[],
  direction?: HeaderDirection,
): HeaderCandidate[] {
  const parsedHeaders = addresses.map((address) => ({
    address,
    ...parseCell(address),
  }));
  let maxValueCol = 0;
  let maxValueRow = 0;

  for (const address of valueAddresses) {
    const cell = parseCell(address);
    maxValueCol = Math.max(maxValueCol, cell.col);
    maxValueRow = Math.max(maxValueRow, cell.row);
  }

  const effectiveFill = fill ?? getImplicitFill(direction);
  const rightFillEnds =
    effectiveFill === "right"
      ? buildFillEnds(parsedHeaders, "row", "col", maxValueCol)
      : undefined;
  const downFillEnds =
    effectiveFill === "down"
      ? buildFillEnds(parsedHeaders, "col", "row", maxValueRow)
      : undefined;

  return parsedHeaders.map((header) => ({
    ...header,
    spanEndCol:
      rightFillEnds?.get(positionKey(header.row, header.col)) ?? header.col,
    spanEndRow:
      downFillEnds?.get(positionKey(header.col, header.row)) ?? header.row,
  }));
}

function getImplicitFill(
  direction: HeaderDirection | undefined,
): "right" | "down" | undefined {
  if (direction === "NNW") {
    return "right";
  }

  if (direction === "WNW") {
    return "down";
  }

  return undefined;
}

function buildFillEnds(
  headers: Array<{ row: number; col: number }>,
  bandAxis: "row" | "col",
  fillAxis: "row" | "col",
  maximum: number,
): Map<string, number> {
  const bands = new Map<number, number[]>();
  for (const header of headers) {
    const positions = bands.get(header[bandAxis]) ?? [];
    positions.push(header[fillAxis]);
    bands.set(header[bandAxis], positions);
  }
  const ends = new Map<string, number>();
  for (const [band, positions] of bands) {
    positions.sort((left, right) => left - right);
    positions.forEach((position, index) => {
      ends.set(
        positionKey(band, position),
        index + 1 < positions.length ? positions[index + 1] - 1 : maximum,
      );
    });
  }
  return ends;
}

function positionKey(first: number, second: number): string {
  return `${first}:${second}`;
}

function compareCandidates(
  direction: HeaderDirection,
  left: HeaderCandidate,
  right: HeaderCandidate,
): number {
  switch (direction) {
    case "N":
      return right.row - left.row;
    case "W":
      return right.col - left.col;
    case "NNW":
      return right.row - left.row || right.col - left.col;
    case "WNW":
      return right.col - left.col || right.row - left.row;
  }
}
