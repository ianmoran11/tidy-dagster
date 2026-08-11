/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
/** Pure, versioned contracts for hierarchy-scoped graphs. */
export const HIERARCHY_EDGE_RELATIONS = [
  "rolls_up_to",
  "broader_concept",
  "contains",
] as const;
export type HierarchyEdgeRelation = (typeof HIERARCHY_EDGE_RELATIONS)[number];

export const HIERARCHY_REVIEW_STATUSES = [
  "automatic",
  "proposed",
  "approved",
  "rejected",
  "abstained",
] as const;
export type HierarchyReviewStatus = (typeof HIERARCHY_REVIEW_STATUSES)[number];

export type HierarchyValueSchemeReference = {
  valueSchemeId: string;
  valueSchemeVersion: string;
};

export type TypedHierarchyLevel = {
  id: string;
  order: number;
  valueScheme?: HierarchyValueSchemeReference;
  /** A child at this level may have at most one roll-up parent in this hierarchy version. */
  requiresUniqueParent?: boolean;
};

export type HierarchyCoverage = {
  /** Complete means every required member has a declared parent; partial makes gaps explicit. */
  status: "complete" | "partial";
  requiredMemberIds: string[];
};

export type HierarchyAggregationContext = {
  sourceValueScheme: HierarchyValueSchemeReference;
  targetValueScheme: HierarchyValueSchemeReference;
  sourceUniverse: string;
  targetUniverse: string;
  sourceAggregationRule:
    | "sum"
    | "weighted_mean"
    | "non_additive"
    | "last_value"
    | "unknown";
  targetAggregationRule:
    | "sum"
    | "weighted_mean"
    | "non_additive"
    | "last_value"
    | "unknown";
};

export type TypedHierarchyEdge = {
  hierarchyId: string;
  hierarchyVersion: string;
  sourceId: string;
  targetId: string;
  sourceLevelId?: string;
  targetLevelId?: string;
  relation: HierarchyEdgeRelation | string;
  aggregation?: "sum" | "weighted_mean" | "non_additive" | "unknown";
  aggregationContext?: HierarchyAggregationContext;
  validFrom?: string;
  validTo?: string;
  evidence: string[];
  confidence?: number;
  reviewStatus: HierarchyReviewStatus;
};

export type TypedHierarchy = {
  id: string;
  version: string;
  type:
    | "calendar"
    | "fiscal"
    | "geographic"
    | "classification"
    | "publication_custom";
  /** Calendar/fiscal member roll-ups must declare the exact temporal scheme/version. */
  periodScheme?: HierarchyValueSchemeReference;
  /** Prevents a fiscal hierarchy from silently reusing calendar period semantics. */
  periodSchemeKind?: "calendar" | "fiscal";
  levels: TypedHierarchyLevel[];
  edges: TypedHierarchyEdge[];
  validFrom?: string;
  validTo?: string;
  coverage?: HierarchyCoverage;
};

export type HierarchyCanonicalValue = {
  id: string;
  valueScheme: HierarchyValueSchemeReference;
  valueRole?: "member" | "total";
};

/** Authoritative metadata from the registered value-scheme snapshot. */
export type HierarchyPeriodSchemeMetadata = {
  valueScheme: HierarchyValueSchemeReference;
  periodSchemeKind?: "calendar" | "fiscal";
};

export type HierarchyValidationIssue = {
  code:
    | "invalid_relation"
    | "invalid_relation_metadata"
    | "hierarchy_identity"
    | "unknown_value"
    | "unknown_level"
    | "invalid_level_transition"
    | "inconsistent_level_membership"
    | "scheme_mismatch"
    | "missing_period_scheme"
    | "period_scheme_kind"
    | "invalid_interval"
    | "duplicate_edge"
    | "duplicate_parent"
    | "cycle"
    | "orphaned_member"
    | "incompatible_aggregation";
  edgeIndex?: number;
  message: string;
};

export type HierarchyCoverageStatus = {
  status: "complete" | "partial" | "orphaned" | "unassessed";
  missingMemberIds: string[];
};

export type HierarchyValidationResult = {
  issues: HierarchyValidationIssue[];
  coverage: HierarchyCoverageStatus;
  valid: boolean;
};
