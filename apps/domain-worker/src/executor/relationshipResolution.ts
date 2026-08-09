/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import { parseCell } from "../address.js";
import {
  buildHeaderCandidates,
  findHeaderCandidates,
  type HeaderCandidate,
  type ValuePosition,
} from "./directions.js";
import type { HeaderDirection } from "../recipe/types.js";

export type HeaderDirectionGroup = {
  direction: HeaderDirection;
  candidates: HeaderCandidate[];
};

export type RelationshipAttachment = {
  candidates: string[];
  selectedAddress?: string;
  direction?: HeaderDirection;
};

/**
 * Builds the exact effective-direction groups used by RecipeV01 execution.
 * Cascading implicit fills and explicit-fill/default-direction behavior are
 * delegated to buildHeaderCandidates, the production geometry authority.
 */
export function buildHeaderDirectionGroups(input: {
  headerAddresses: readonly string[];
  valueAddresses: readonly string[];
  direction: HeaderDirection;
  fill?: "right" | "down";
  directionOverrides?: Readonly<Record<string, HeaderDirection>>;
}): HeaderDirectionGroup[] {
  const addressesByDirection = new Map<HeaderDirection, string[]>();

  for (const address of input.headerAddresses) {
    const direction = input.directionOverrides?.[address] ?? input.direction;
    const addresses = addressesByDirection.get(direction) ?? [];
    addresses.push(address);
    addressesByDirection.set(direction, addresses);
  }

  return [...addressesByDirection.entries()].map(([direction, addresses]) => ({
    direction,
    candidates: buildHeaderCandidates(
      addresses,
      direction === input.direction ? input.fill : undefined,
      [...input.valueAddresses],
      direction,
    ),
  }));
}

/**
 * Resolves one value position with the same candidate ordering and mixed
 * direction Manhattan-distance arbitration as the Recipe executor.
 */
export function resolveRelationshipAttachment(
  groups: readonly HeaderDirectionGroup[],
  value: ValuePosition,
): RelationshipAttachment {
  let rank = 0;
  const directionMatches = groups.flatMap((group) =>
    findHeaderCandidates(group.direction, group.candidates, value).map(
      (candidate) => ({
        candidate,
        direction: group.direction,
        rank: rank++,
      }),
    ),
  );
  const matching =
    groups.length > 1
      ? directionMatches.sort(
          (left, right) =>
            attachmentDistance(left.candidate, value) -
              attachmentDistance(right.candidate, value) ||
            left.rank - right.rank,
        )
      : directionMatches;
  const selected = matching[0];

  return {
    candidates: matching.map((match) => match.candidate.address),
    ...(selected
      ? {
          selectedAddress: selected.candidate.address,
          direction: selected.direction,
        }
      : {}),
  };
}

export function resolveRelationshipAttachmentAtAddress(
  groups: readonly HeaderDirectionGroup[],
  valueAddress: string,
): RelationshipAttachment {
  return resolveRelationshipAttachment(groups, parseCell(valueAddress));
}

/**
 * Batch selection used by geometry validation. Direct N/W relationships use
 * band indexes and binary search, avoiding a header×value Cartesian scan.
 * Cascading and mixed-direction groups retain the canonical resolver above.
 */
export function resolveRelationshipSelections(
  groups: readonly HeaderDirectionGroup[],
  valueAddresses: readonly string[],
): Map<string, RelationshipAttachment> {
  if (groups.length === 1) {
    if (groups[0].direction === "N" || groups[0].direction === "W") {
      return resolveDirectSelections(groups[0], valueAddresses);
    }
    return resolveCascadingSelections(groups[0], valueAddresses);
  }
  return new Map(
    valueAddresses.map((address) => [
      address,
      resolveRelationshipAttachmentAtAddress(groups, address),
    ]),
  );
}

export function estimateRelationshipResolutionOperations(
  direction: HeaderDirection,
  headerCount: number,
  valueAddresses: readonly string[],
): number {
  if (direction === "N" || direction === "W") {
    return headerCount + valueAddresses.length;
  }
  const bands = new Set(
    valueAddresses.map((address) => {
      const value = parseCell(address);
      return direction === "NNW" ? value.col : value.row;
    }),
  );
  return headerCount * bands.size + valueAddresses.length;
}

export function isBlankRelationshipValue(cell: {
  data_type?: string;
  value?: unknown;
}): boolean {
  return (
    cell.data_type === "blank" ||
    cell.value === null ||
    cell.value === undefined
  );
}

function resolveDirectSelections(
  group: HeaderDirectionGroup,
  valueAddresses: readonly string[],
): Map<string, RelationshipAttachment> {
  const byBand = new Map<number, HeaderCandidate[]>();
  for (const candidate of group.candidates) {
    const band = group.direction === "N" ? candidate.col : candidate.row;
    const entries = byBand.get(band) ?? [];
    entries.push(candidate);
    byBand.set(band, entries);
  }
  for (const entries of byBand.values()) {
    entries.sort((left, right) =>
      group.direction === "N" ? left.row - right.row : left.col - right.col,
    );
  }

  const resolved = new Map<string, RelationshipAttachment>();
  for (const address of valueAddresses) {
    const value = parseCell(address);
    const band = group.direction === "N" ? value.col : value.row;
    const coordinate = group.direction === "N" ? value.row : value.col;
    const candidates = byBand.get(band) ?? [];
    let low = 0;
    let high = candidates.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      const candidateCoordinate =
        group.direction === "N"
          ? candidates[middle].row
          : candidates[middle].col;
      if (candidateCoordinate < coordinate) low = middle + 1;
      else high = middle;
    }
    const selected = low > 0 ? candidates[low - 1] : undefined;
    resolved.set(address, {
      candidates: selected ? [selected.address] : [],
      ...(selected
        ? { selectedAddress: selected.address, direction: group.direction }
        : {}),
    });
  }
  return resolved;
}

function resolveCascadingSelections(
  group: HeaderDirectionGroup,
  valueAddresses: readonly string[],
): Map<string, RelationshipAttachment> {
  const byBand = new Map<number, HeaderCandidate[]>();
  const values = valueAddresses.map((address) => ({
    address,
    position: parseCell(address),
  }));
  const bands = new Set(
    values.map(({ position }) =>
      group.direction === "NNW" ? position.col : position.row,
    ),
  );
  for (const band of bands) {
    const candidates = group.candidates
      .filter((candidate) =>
        group.direction === "NNW"
          ? candidate.col <= band && candidate.spanEndCol >= band
          : candidate.row <= band && candidate.spanEndRow >= band,
      )
      .sort((left, right) =>
        group.direction === "NNW"
          ? left.row - right.row || left.col - right.col
          : left.col - right.col || left.row - right.row,
      );
    byBand.set(band, candidates);
  }

  const resolved = new Map<string, RelationshipAttachment>();
  for (const { address, position } of values) {
    const band = group.direction === "NNW" ? position.col : position.row;
    const coordinate = group.direction === "NNW" ? position.row : position.col;
    const candidates = byBand.get(band) ?? [];
    let low = 0;
    let high = candidates.length;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      const candidateCoordinate =
        group.direction === "NNW"
          ? candidates[middle].row
          : candidates[middle].col;
      if (candidateCoordinate < coordinate) low = middle + 1;
      else high = middle;
    }
    const selected = low > 0 ? candidates[low - 1] : undefined;
    resolved.set(address, {
      candidates: selected ? [selected.address] : [],
      ...(selected
        ? { selectedAddress: selected.address, direction: group.direction }
        : {}),
    });
  }
  return resolved;
}

function attachmentDistance(
  candidate: HeaderCandidate,
  value: ValuePosition,
): number {
  return (
    Math.abs(value.row - candidate.row) + Math.abs(value.col - candidate.col)
  );
}
