import { isValidIsoDate } from "./dates";
import {
  HIERARCHY_EDGE_RELATIONS,
  type HierarchyCanonicalValue,
  type HierarchyCoverageStatus,
  type HierarchyPeriodSchemeMetadata,
  type HierarchyValidationIssue,
  type HierarchyValidationResult,
  type TypedHierarchy,
  type TypedHierarchyEdge,
} from "./types";

function sameScheme(
  left: { valueSchemeId: string; valueSchemeVersion: string },
  right: { valueSchemeId: string; valueSchemeVersion: string },
): boolean {
  return left.valueSchemeId === right.valueSchemeId
    && left.valueSchemeVersion === right.valueSchemeVersion;
}

function isIntervalValid(from?: string, to?: string): boolean {
  return (!from || isValidIsoDate(from))
    && (!to || isValidIsoDate(to))
    && (!from || !to || from <= to);
}

function isWithinHierarchyInterval(
  edge: TypedHierarchyEdge,
  hierarchy: TypedHierarchy,
): boolean {
  return (!hierarchy.validFrom || !edge.validFrom || hierarchy.validFrom <= edge.validFrom)
    && (!hierarchy.validTo || !edge.validTo || edge.validTo <= hierarchy.validTo)
    && (!hierarchy.validFrom || !edge.validTo || hierarchy.validFrom <= edge.validTo)
    && (!hierarchy.validTo || !edge.validFrom || edge.validFrom <= hierarchy.validTo);
}

/** Rejected/abstained records remain auditable but do not assert graph semantics. */
export function isActiveHierarchyEdge(edge: TypedHierarchyEdge): boolean {
  return edge.reviewStatus === "automatic"
    || edge.reviewStatus === "proposed"
    || edge.reviewStatus === "approved";
}

function hasDirectedCycle(edges: TypedHierarchyEdge[]): boolean {
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) {
    adjacency.set(edge.sourceId, [...(adjacency.get(edge.sourceId) ?? []), edge.targetId]);
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (id: string): boolean => {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    visiting.add(id);
    for (const next of adjacency.get(id) ?? []) {
      if (visit(next)) return true;
    }
    visiting.delete(id);
    visited.add(id);
    return false;
  };
  return [...adjacency.keys()].sort().some(visit);
}

function coverageStatus(
  hierarchy: TypedHierarchy,
  activeRollups: TypedHierarchyEdge[],
): HierarchyCoverageStatus {
  if (!hierarchy.coverage) return { status: "unassessed", missingMemberIds: [] };
  const parents = new Set(activeRollups.map((edge) => edge.sourceId));
  const missingMemberIds = [...new Set(hierarchy.coverage.requiredMemberIds)]
    .filter((id) => !parents.has(id))
    .sort();
  if (missingMemberIds.length === 0) return { status: "complete", missingMemberIds };
  return {
    status: hierarchy.coverage.status === "partial" ? "partial" : "orphaned",
    missingMemberIds,
  };
}

/**
 * Validates one hierarchy snapshot. All active typed edges participate in
 * acyclicity validation, while only active `rolls_up_to` edges participate in
 * level membership, parent cardinality, coverage, and aggregation semantics.
 * Rejected and abstained edges remain audit records and affect neither.
 */
export function validateTypedHierarchy(input: {
  hierarchy: TypedHierarchy;
  canonicalValues: HierarchyCanonicalValue[];
  periodSchemeMetadata?: HierarchyPeriodSchemeMetadata[];
}): HierarchyValidationResult {
  const { hierarchy } = input;
  const issues: HierarchyValidationIssue[] = [];
  const add = (issue: HierarchyValidationIssue) => issues.push(issue);
  const levels = new Map(hierarchy.levels.map((level) => [level.id, level]));
  const canonicalValues = new Map(input.canonicalValues.map((value) => [value.id, value]));
  const levelIds = new Set<string>();
  const levelOrders = new Set<number>();

  for (const level of hierarchy.levels) {
    if (levelIds.has(level.id) || levelOrders.has(level.order)) {
      add({ code: "unknown_level", message: "Hierarchy level IDs and orders must be unique." });
    }
    levelIds.add(level.id);
    levelOrders.add(level.order);
  }

  const activeEdges = hierarchy.edges.filter(isActiveHierarchyEdge);
  const activeRollups = activeEdges.filter((edge) => edge.relation === "rolls_up_to");
  if ((hierarchy.type === "calendar" || hierarchy.type === "fiscal")
    && activeRollups.length > 0
    && !hierarchy.periodScheme) {
    add({
      code: "missing_period_scheme",
      message: "Active calendar and fiscal roll-ups require an explicit period scheme ID and version.",
    });
  }
  if ((hierarchy.type === "calendar" || hierarchy.type === "fiscal")
    && hierarchy.periodScheme
    && hierarchy.periodSchemeKind !== hierarchy.type) {
    add({
      code: "period_scheme_kind",
      message: "A calendar/fiscal hierarchy period scheme kind must match the hierarchy type.",
    });
  }
  const periodScheme = hierarchy.periodScheme;
  if (periodScheme) {
    const metadata = input.periodSchemeMetadata?.find(
      (candidate) => sameScheme(candidate.valueScheme, periodScheme),
    );
    if (metadata && metadata.periodSchemeKind !== hierarchy.periodSchemeKind) {
      add({
        code: "period_scheme_kind",
        message: "Hierarchy period scheme kind must match registered value-scheme metadata.",
      });
    }
  }
  if (!isIntervalValid(hierarchy.validFrom, hierarchy.validTo)) {
    add({ code: "invalid_interval", message: "Hierarchy validity interval must contain real dates and must not end before it starts." });
  }

  for (const requiredMemberId of hierarchy.coverage?.requiredMemberIds ?? []) {
    const member = canonicalValues.get(requiredMemberId);
    if (!member) {
      add({ code: "unknown_value", message: `Hierarchy coverage references an unknown canonical member: ${requiredMemberId}.` });
      continue;
    }
    const levelSchemes = hierarchy.levels.flatMap((level) => level.valueScheme ? [level.valueScheme] : []);
    const inScope = periodScheme
      ? sameScheme(member.valueScheme, periodScheme)
      : levelSchemes.some((scheme) => sameScheme(member.valueScheme, scheme));
    if (!inScope) {
      add({ code: "scheme_mismatch", message: `Hierarchy coverage member is outside the declared level schemes: ${requiredMemberId}.` });
    }
  }

  const edgeKeys = new Set<string>();
  const parentKeys = new Set<string>();
  const assignedLevelByValue = new Map<string, string>();
  const assignLevel = (valueId: string, levelId: string, edgeIndex: number) => {
    const existing = assignedLevelByValue.get(valueId);
    if (existing && existing !== levelId) {
      add({
        code: "inconsistent_level_membership",
        edgeIndex,
        message: `Canonical value ${valueId} is assigned to both ${existing} and ${levelId} in one hierarchy version.`,
      });
    } else {
      assignedLevelByValue.set(valueId, levelId);
    }
  };

  hierarchy.edges.forEach((edge, edgeIndex) => {
    if (!HIERARCHY_EDGE_RELATIONS.includes(edge.relation as (typeof HIERARCHY_EDGE_RELATIONS)[number])) {
      add({ code: "invalid_relation", edgeIndex, message: "Hierarchy edge has an unsupported relation." });
      return;
    }
    if (edge.hierarchyId !== hierarchy.id || edge.hierarchyVersion !== hierarchy.version) {
      add({ code: "hierarchy_identity", edgeIndex, message: "Edge hierarchy ID and version must match the containing hierarchy." });
    }
    const edgeKey = [edge.relation, edge.sourceId, edge.targetId].join("\u001f");
    if (edgeKeys.has(edgeKey)) {
      add({ code: "duplicate_edge", edgeIndex, message: "Duplicate typed hierarchy edge." });
    }
    edgeKeys.add(edgeKey);
    if (!isIntervalValid(edge.validFrom, edge.validTo) || !isWithinHierarchyInterval(edge, hierarchy)) {
      add({ code: "invalid_interval", edgeIndex, message: "Edge validity interval contains an impossible date, is reversed, or falls outside its hierarchy interval." });
    }
    if (edge.relation !== "rolls_up_to") {
      if (edge.sourceLevelId || edge.targetLevelId || edge.aggregation || edge.aggregationContext) {
        add({
          code: "invalid_relation_metadata",
          edgeIndex,
          message: "Only statistical roll-up edges may carry level or aggregation metadata.",
        });
      }
      return;
    }

    const source = canonicalValues.get(edge.sourceId);
    const target = canonicalValues.get(edge.targetId);
    if (!source || !target) {
      add({ code: "unknown_value", edgeIndex, message: "Roll-up edges must connect declared canonical values." });
    }
    const sourceLevel = edge.sourceLevelId ? levels.get(edge.sourceLevelId) : undefined;
    const targetLevel = edge.targetLevelId ? levels.get(edge.targetLevelId) : undefined;
    if (!sourceLevel || !targetLevel) {
      add({ code: "unknown_level", edgeIndex, message: "Roll-up edges must name declared source and target levels." });
    }

    // Rejected and abstained records retain valid references but assert no graph semantics.
    if (!isActiveHierarchyEdge(edge)) return;

    const isAdditive = edge.aggregation === "sum" || edge.aggregation === "weighted_mean";
    if (source?.valueRole === "total" || target?.valueRole === "total" || edge.aggregationContext || isAdditive) {
      const aggregation = edge.aggregationContext;
      if (!aggregation
        || !sameScheme(aggregation.sourceValueScheme, aggregation.targetValueScheme)
        || !sameScheme(aggregation.sourceValueScheme, source?.valueScheme ?? aggregation.sourceValueScheme)
        || !sameScheme(aggregation.targetValueScheme, target?.valueScheme ?? aggregation.targetValueScheme)
        || aggregation.sourceUniverse !== aggregation.targetUniverse
        || aggregation.sourceAggregationRule !== aggregation.targetAggregationRule
        || !["sum", "weighted_mean"].includes(aggregation.sourceAggregationRule)
        || edge.aggregation !== aggregation.sourceAggregationRule) {
        add({ code: "incompatible_aggregation", edgeIndex, message: "Additive and totals/member roll-ups require compatible universe, scheme version, and matching additive aggregation rules." });
      }
    }

    if (sourceLevel && targetLevel) {
      assignLevel(edge.sourceId, sourceLevel.id, edgeIndex);
      assignLevel(edge.targetId, targetLevel.id, edgeIndex);
      if (sourceLevel.order !== targetLevel.order + 1) {
        add({ code: "invalid_level_transition", edgeIndex, message: "Roll-up levels must be adjacent child-to-parent levels." });
      }
      if (source && sourceLevel.valueScheme && !sameScheme(source.valueScheme, sourceLevel.valueScheme)) {
        add({ code: "scheme_mismatch", edgeIndex, message: "Roll-up source does not match its level value-scheme version." });
      }
      if (target && targetLevel.valueScheme && !sameScheme(target.valueScheme, targetLevel.valueScheme)) {
        add({ code: "scheme_mismatch", edgeIndex, message: "Roll-up target does not match its level value-scheme version." });
      }
      const temporalUniqueParent = hierarchy.type === "calendar" || hierarchy.type === "fiscal";
      if (sourceLevel.requiresUniqueParent || temporalUniqueParent) {
        const parentKey = [sourceLevel.id, edge.sourceId].join("\u001f");
        if (parentKeys.has(parentKey)) {
          add({ code: "duplicate_parent", edgeIndex, message: "This hierarchy level requires one roll-up parent per member." });
        }
        parentKeys.add(parentKey);
      }
    }
    if (periodScheme) {
      if (source && !sameScheme(source.valueScheme, periodScheme)) {
        add({ code: "scheme_mismatch", edgeIndex, message: "Temporal roll-up source must use the hierarchy period scheme version." });
      }
      if (target && !sameScheme(target.valueScheme, periodScheme)) {
        add({ code: "scheme_mismatch", edgeIndex, message: "Temporal roll-up target must use the hierarchy period scheme version." });
      }
    }

  });

  if (hasDirectedCycle(activeEdges)) {
    add({ code: "cycle", message: "Active typed hierarchy edges must be acyclic." });
  }
  const coverage = coverageStatus(hierarchy, activeRollups);
  if (coverage.status === "orphaned") {
    add({ code: "orphaned_member", message: `Required hierarchy members lack active parents: ${coverage.missingMemberIds.join(", ")}.` });
  }
  issues.sort((left, right) => `${left.code}\u001f${left.edgeIndex ?? -1}\u001f${left.message}`.localeCompare(`${right.code}\u001f${right.edgeIndex ?? -1}\u001f${right.message}`));
  return { issues, coverage, valid: issues.length === 0 };
}
