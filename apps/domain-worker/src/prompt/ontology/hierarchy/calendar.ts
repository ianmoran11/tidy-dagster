/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import type {
  HierarchyCanonicalValue,
  HierarchyValueSchemeReference,
  TypedHierarchy,
  TypedHierarchyEdge,
} from "./types.js";

function sameScheme(
  left: HierarchyValueSchemeReference,
  right: HierarchyValueSchemeReference,
): boolean {
  return (
    left.valueSchemeId === right.valueSchemeId &&
    left.valueSchemeVersion === right.valueSchemeVersion
  );
}

function edge(
  hierarchy: TypedHierarchy,
  sourceId: string,
  targetId: string,
  sourceLevelId: string,
  targetLevelId: string,
): TypedHierarchyEdge {
  return {
    hierarchyId: hierarchy.id,
    hierarchyVersion: hierarchy.version,
    sourceId,
    targetId,
    sourceLevelId,
    targetLevelId,
    relation: "rolls_up_to",
    aggregation: "unknown",
    evidence: ["known_calendar_period_scheme", "concrete_iso_period_codes"],
    confidence: 1,
    reviewStatus: "proposed",
  };
}

/**
 * Creates only concrete calendar roll-up candidates. Generic labels such as
 * January/Q1 and all fiscal schemes intentionally produce no membership edge.
 */
type CalendarCanonicalValue = HierarchyCanonicalValue & { code: string };

export function buildCalendarRollupCandidates(input: {
  hierarchy: TypedHierarchy;
  periodScheme: HierarchyValueSchemeReference;
  canonicalValues: CalendarCanonicalValue[];
}): TypedHierarchyEdge[] {
  const { hierarchy, periodScheme } = input;
  if (
    hierarchy.type !== "calendar" ||
    hierarchy.periodSchemeKind !== "calendar" ||
    !hierarchy.periodScheme ||
    !sameScheme(hierarchy.periodScheme, periodScheme)
  ) {
    return [];
  }
  const levels = new Set(hierarchy.levels.map((level) => level.id));
  if (!levels.has("year") || !levels.has("quarter") || !levels.has("month"))
    return [];
  const valueByCode = new Map(
    input.canonicalValues
      .filter((value) => sameScheme(value.valueScheme, periodScheme))
      .map((value) => [value.code, value]),
  );
  const candidates: TypedHierarchyEdge[] = [];
  const entries = [...valueByCode.entries()].sort(([left], [right]) =>
    left.localeCompare(right),
  );
  for (const [monthCode, month] of entries) {
    const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(monthCode);
    if (!match) continue;
    const quarter = `${match[1]}-Q${Math.ceil(Number(match[2]) / 3)}`;
    const quarterValue = valueByCode.get(quarter);
    if (quarterValue)
      candidates.push(
        edge(hierarchy, month.id, quarterValue.id, "month", "quarter"),
      );
  }
  for (const [quarterCode, quarter] of entries) {
    const match = /^(\d{4})-Q[1-4]$/.exec(quarterCode);
    if (!match) continue;
    const yearValue = valueByCode.get(match[1]);
    if (yearValue)
      candidates.push(
        edge(hierarchy, quarter.id, yearValue.id, "quarter", "year"),
      );
  }
  const seen = new Set<string>();
  return candidates
    .filter((candidate) => {
      const key = [candidate.sourceId, candidate.targetId].join("\u001f");
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((left, right) =>
      [left.sourceId, left.targetId]
        .join("\u001f")
        .localeCompare([right.sourceId, right.targetId].join("\u001f")),
    );
}
