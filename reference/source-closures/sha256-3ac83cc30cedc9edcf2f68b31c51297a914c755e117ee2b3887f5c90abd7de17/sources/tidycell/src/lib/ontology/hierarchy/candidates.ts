import type { TypedHierarchyEdge } from "./types";

export const HIERARCHY_EVIDENCE_SIGNALS = [
  "nested_headers",
  "merged_cells",
  "indentation",
  "repeated_parent_blocks",
  "known_scheme",
  "approved_mapping",
] as const;
export type HierarchyEvidenceSignal = (typeof HIERARCHY_EVIDENCE_SIGNALS)[number];

export type HierarchyStructuralEvidence = {
  nestedHeaders?: string[];
  mergedCells?: string[];
  indentation?: boolean;
  repeatedParentBlocks?: string[];
  knownScheme?: boolean;
  approvedMappings?: string[];
};

export type HierarchyCandidateInput = {
  hierarchyId: string;
  hierarchyVersion: string;
  sourceId: string;
  targetId: string;
  sourceLevelId: string;
  targetLevelId: string;
  /** Direct evidence codes are useful when imported from a reviewed artifact. */
  evidence?: HierarchyEvidenceSignal[];
  /** Sheet/table facts are converted deterministically to the same evidence codes. */
  structuralEvidence?: HierarchyStructuralEvidence;
};

export function hierarchyEvidenceFromStructuralContext(
  context: HierarchyStructuralEvidence,
): HierarchyEvidenceSignal[] {
  return [
    ...(context.nestedHeaders?.length ? ["nested_headers" as const] : []),
    ...(context.mergedCells?.length ? ["merged_cells" as const] : []),
    ...(context.indentation ? ["indentation" as const] : []),
    ...(context.repeatedParentBlocks?.length ? ["repeated_parent_blocks" as const] : []),
    ...(context.knownScheme ? ["known_scheme" as const] : []),
    ...(context.approvedMappings?.length ? ["approved_mapping" as const] : []),
  ];
}

/**
 * Structural evidence is reviewable evidence, not authority to create an
 * approved relation. All candidates are deliberately proposed.
 */
export function proposeHierarchyCandidates(
  inputs: HierarchyCandidateInput[],
): TypedHierarchyEdge[] {
  return inputs
    .map((input) => {
      const evidence = [...new Set([
        ...(input.evidence ?? []),
        ...hierarchyEvidenceFromStructuralContext(input.structuralEvidence ?? {}),
      ])].sort();
      return {
        hierarchyId: input.hierarchyId,
        hierarchyVersion: input.hierarchyVersion,
        sourceId: input.sourceId,
        targetId: input.targetId,
        sourceLevelId: input.sourceLevelId,
        targetLevelId: input.targetLevelId,
        relation: "rolls_up_to" as const,
        evidence,
        confidence: Number((evidence.length / HIERARCHY_EVIDENCE_SIGNALS.length).toFixed(6)),
        reviewStatus: "proposed" as const,
      };
    })
    .sort((left, right) => [left.hierarchyId, left.hierarchyVersion, left.sourceId, left.targetId].join("\u001f").localeCompare([right.hierarchyId, right.hierarchyVersion, right.sourceId, right.targetId].join("\u001f")));
}
