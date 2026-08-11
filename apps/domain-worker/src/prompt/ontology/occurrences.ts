/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import { occurrenceIdFor, type PublicationEntityId } from "./publicationIds.js";
import type { OntologyArtifact } from "./overrides.js";
import type { OntologyDetection } from "./types.js";

/** Structural-signature format implemented by this provider-free reconciler. */
export const OCCURRENCE_SIGNATURE_VERSION = "1.0.0" as const;
export const DEFAULT_RECONCILIATION_MINIMUM_SCORE = 0.85;
export const DEFAULT_RECONCILIATION_MINIMUM_MARGIN = 0.1;

export type OccurrenceReviewStatus =
  | "automatic"
  | "proposed"
  | "approved"
  | "rejected"
  | "abstained";

export type OccurrenceProvenance = {
  sourceType:
    | "publisher"
    | "external_standard"
    | "import"
    | "rule"
    | "user"
    | "migration";
  sourceId: string;
  recordedAt: string;
  evidence: string[];
};

/** A stable table context, deliberately distinct from a mutable sheet display name. */
export type OccurrenceTableContext = {
  id: string;
  kind: string;
  neighbouringHeaders: string[];
};

export type OccurrenceClassificationReference = {
  valueSchemeId: string;
  valueSchemeVersion: string;
};

export type OccurrenceStructuralEvidence = {
  tableContext: OccurrenceTableContext;
  orientation: "row" | "column" | "block";
  valueDomainFingerprint: string;
  unitScale?: string;
  universe?: string;
  classification?: OccurrenceClassificationReference;
  priorRepresentedVariableId?: string;
};

export type OccurrenceStructuralSignature = {
  signature: string;
  signatureVersion: typeof OCCURRENCE_SIGNATURE_VERSION;
  evidence: OccurrenceStructuralEvidence;
};

export type OccurrenceSourceLocation = {
  assetId: string;
  sheetName: string;
  range: string;
  addresses: string[];
};

export type OccurrenceSourceIdentity = {
  publicationId: string;
  workbookEditionId: string;
  sourceLocation: OccurrenceSourceLocation;
  rawDetectionIds: readonly string[];
};

/**
 * Exact current-edition source matching shared by the editor and persistence
 * boundary. Source fields validate context only; they never derive durable IDs.
 */
export function occurrenceMatchesDetectionSource(
  occurrence: OccurrenceSourceIdentity,
  detection: Pick<OntologyDetection, "id" | "sheet" | "range" | "addresses">,
  context: {
    publicationId: string;
    workbookEditionId: string;
    assetId: string;
    sheetName: string;
  },
): boolean {
  return (
    occurrence.publicationId === context.publicationId &&
    occurrence.workbookEditionId === context.workbookEditionId &&
    occurrence.sourceLocation.assetId === context.assetId &&
    occurrence.sourceLocation.sheetName === context.sheetName &&
    detection.sheet === context.sheetName &&
    occurrence.sourceLocation.range === detection.range &&
    sameExactValues(occurrence.sourceLocation.addresses, detection.addresses) &&
    occurrence.rawDetectionIds.includes(detection.id)
  );
}

/**
 * A per-edition occurrence record. Detection IDs are audit links only: they
 * remain the range/name-derived raw identity and are never reused as this ID.
 */
export type DurableVariableOccurrence = {
  occurrenceId: PublicationEntityId;
  publicationId: PublicationEntityId;
  workbookEditionId: string;
  sourceLocation: OccurrenceSourceLocation;
  rawDetectionIds: string[];
  representedVariableId?: PublicationEntityId;
  structuralSignature: string;
  structuralSignatureVersion: string;
  structuralEvidence: OccurrenceStructuralEvidence;
  reviewStatus: OccurrenceReviewStatus;
  provenance: OccurrenceProvenance;
  supersedes: PublicationEntityId[];
  supersededBy: PublicationEntityId[];
};

export type CreateOccurrenceInput = Omit<
  DurableVariableOccurrence,
  | "occurrenceId"
  | "structuralSignature"
  | "structuralSignatureVersion"
  | "structuralEvidence"
  | "supersedes"
  | "supersededBy"
> & {
  /** A caller-owned, edition-local discriminator; never a range, label, or detection ID. */
  durableOccurrenceKey: string;
  structuralEvidence: OccurrenceStructuralEvidence;
  occurrenceId?: PublicationEntityId;
  supersedes?: PublicationEntityId[];
  supersededBy?: PublicationEntityId[];
};

export type ReconciliationScoreComponent = {
  name:
    | "table_context"
    | "neighbouring_headers"
    | "orientation"
    | "value_domain"
    | "unit_scale"
    | "universe"
    | "classification"
    | "prior_binding";
  weight: number;
  similarity: number;
  contribution: number;
};

export type ReconciliationCandidate = {
  occurrenceId: PublicationEntityId;
  score: number;
  components: ReconciliationScoreComponent[];
  blockingReasons: ReconciliationReviewReason[];
};

export type ReconciliationReviewReason =
  | "different_publication"
  | "incompatible_table_context"
  | "incompatible_value_domain"
  | "changed_unit_scale"
  | "changed_universe"
  | "conflicting_classification_version"
  | "tied_candidates"
  | "low_margin"
  | "low_score"
  | "prior_binding_not_approved"
  | "conflicting_current_binding";

export type OccurrenceReconciliationEntry = {
  occurrenceId: PublicationEntityId;
  status: "retained" | "moved" | "new" | "ambiguous";
  matchedOccurrenceId: PublicationEntityId | null;
  transferredApprovedBinding: boolean;
  reviewRequired: boolean;
  reviewReasons: ReconciliationReviewReason[];
  candidates: ReconciliationCandidate[];
};

export type OccurrenceSupersession = {
  supersededOccurrenceId: PublicationEntityId;
  supersedingOccurrenceId: PublicationEntityId;
  reason: "edition_reconciliation";
  recordedAt: string;
  provenance: OccurrenceProvenance;
};

export type OccurrenceReconciliationReport = {
  version: "1.0";
  retained: OccurrenceReconciliationEntry[];
  moved: OccurrenceReconciliationEntry[];
  new: OccurrenceReconciliationEntry[];
  ambiguous: OccurrenceReconciliationEntry[];
  retired: PublicationEntityId[];
  supersessions: OccurrenceSupersession[];
};

export type OccurrenceReconciliationResult = {
  occurrences: DurableVariableOccurrence[];
  priorOccurrences: DurableVariableOccurrence[];
  report: OccurrenceReconciliationReport;
};

/**
 * Creates a canonical signature from structural evidence. Ranges, addresses,
 * sheet display names, raw detection IDs, and labels are intentionally absent.
 */
export function createOccurrenceStructuralSignature(
  input: OccurrenceStructuralEvidence,
): OccurrenceStructuralSignature {
  const evidence: OccurrenceStructuralEvidence = {
    tableContext: {
      id: normalizeRequired(input.tableContext.id, "table context ID"),
      kind: normalizeRequired(input.tableContext.kind, "table context kind"),
      neighbouringHeaders: normalizeTokens(
        input.tableContext.neighbouringHeaders,
      ),
    },
    orientation: input.orientation,
    valueDomainFingerprint: normalizeRequired(
      input.valueDomainFingerprint,
      "value-domain fingerprint",
    ),
    ...(input.unitScale
      ? { unitScale: normalizeOptional(input.unitScale) }
      : {}),
    ...(input.universe ? { universe: normalizeOptional(input.universe) } : {}),
    ...(input.classification
      ? {
          classification: {
            valueSchemeId: normalizeRequired(
              input.classification.valueSchemeId,
              "classification value-scheme ID",
            ),
            valueSchemeVersion: normalizeRequired(
              input.classification.valueSchemeVersion,
              "classification value-scheme version",
            ),
          },
        }
      : {}),
    ...(input.priorRepresentedVariableId
      ? {
          priorRepresentedVariableId: normalizeOptional(
            input.priorRepresentedVariableId,
          ),
        }
      : {}),
  };
  const serialized = JSON.stringify(evidence);
  return {
    signature: `occurrence_signature_v1_${fnv1a32(serialized)}`,
    signatureVersion: OCCURRENCE_SIGNATURE_VERSION,
    evidence,
  };
}

/** Builds a durable occurrence without changing the linked raw detection IDs. */
export function createDurableOccurrence(
  input: CreateOccurrenceInput,
): DurableVariableOccurrence {
  const structuralSignature = createOccurrenceStructuralSignature(
    input.structuralEvidence,
  );
  const rawDetectionIds = sortedUniqueExact(
    input.rawDetectionIds,
    "raw detection IDs",
  );
  const durableOccurrenceKey = normalizeRequired(
    input.durableOccurrenceKey,
    "durable occurrence key",
  );
  if (
    /^(det|usr)_/.test(durableOccurrenceKey) ||
    rawDetectionIds.some(
      (detectionId) => normalizeOptional(detectionId) === durableOccurrenceKey,
    )
  ) {
    throw new Error(
      "Raw detection IDs cannot be repurposed as durable occurrence keys.",
    );
  }
  const occurrenceId =
    input.occurrenceId ??
    occurrenceIdFor(
      input.publicationId,
      input.workbookEditionId,
      durableOccurrenceKey,
    );
  if (input.reviewStatus === "approved" && !input.representedVariableId) {
    throw new Error(
      "Approved occurrences require a represented-variable binding.",
    );
  }
  if (input.reviewStatus !== "approved" && input.representedVariableId) {
    throw new Error(
      "Only approved occurrences may carry a represented-variable binding.",
    );
  }
  if (rawDetectionIds.some((id) => id === occurrenceId)) {
    throw new Error(
      "Raw detection IDs cannot be used as durable occurrence IDs.",
    );
  }

  return {
    occurrenceId,
    publicationId: input.publicationId,
    workbookEditionId: normalizeRequired(
      input.workbookEditionId,
      "workbook edition ID",
    ),
    sourceLocation: normalizeSourceLocation(input.sourceLocation),
    rawDetectionIds,
    ...(input.representedVariableId
      ? { representedVariableId: input.representedVariableId }
      : {}),
    structuralSignature: structuralSignature.signature,
    structuralSignatureVersion: structuralSignature.signatureVersion,
    structuralEvidence: structuralSignature.evidence,
    reviewStatus: input.reviewStatus,
    provenance: cloneProvenance(input.provenance),
    supersedes: sortedUniqueEntityIds(input.supersedes ?? [], "supersedes"),
    supersededBy: sortedUniqueEntityIds(
      input.supersededBy ?? [],
      "supersededBy",
    ),
  };
}

/**
 * Reconciles one later edition against prior occurrence records. Matches are
 * publication- and table-context-blocked, explicitly scored, and accepted only
 * when unique, high-margin, structurally compatible candidates are available.
 */
export function reconcileOccurrences({
  priorOccurrences,
  incomingOccurrences,
  recordedAt = "1970-01-01T00:00:00Z",
  provenance,
  minimumScore = DEFAULT_RECONCILIATION_MINIMUM_SCORE,
  minimumMargin = DEFAULT_RECONCILIATION_MINIMUM_MARGIN,
}: {
  priorOccurrences: readonly DurableVariableOccurrence[];
  incomingOccurrences: readonly DurableVariableOccurrence[];
  recordedAt?: string;
  provenance: OccurrenceProvenance;
  minimumScore?: number;
  minimumMargin?: number;
}): OccurrenceReconciliationResult {
  assertUniqueOccurrenceIds(priorOccurrences, "prior");
  assertUniqueOccurrenceIds(incomingOccurrences, "incoming");
  if (
    minimumScore < 0 ||
    minimumScore > 1 ||
    minimumMargin < 0 ||
    minimumMargin > 1
  ) {
    throw new Error(
      "Reconciliation score and margin thresholds must be between zero and one.",
    );
  }

  const previous = new Map(
    [...priorOccurrences]
      .sort(compareOccurrence)
      .map((occurrence) => [
        occurrence.occurrenceId,
        cloneOccurrence(occurrence),
      ]),
  );
  const output = new Map(
    [...incomingOccurrences]
      .sort(compareOccurrence)
      .map((occurrence) => [
        occurrence.occurrenceId,
        cloneOccurrence(occurrence),
      ]),
  );
  const usedPriorIds = new Set<PublicationEntityId>();
  const consideredPriorIds = new Set<PublicationEntityId>();
  const entries: OccurrenceReconciliationEntry[] = [];
  const supersessions: OccurrenceSupersession[] = [];

  for (const incoming of [...output.values()].sort(compareOccurrence)) {
    const candidates = [...previous.values()]
      .filter((prior) => prior.workbookEditionId !== incoming.workbookEditionId)
      .map((prior) => scoreOccurrenceCandidate(incoming, prior))
      .sort(compareCandidate);
    for (const candidate of candidates) {
      if (
        !candidate.blockingReasons.includes("different_publication") &&
        !candidate.blockingReasons.includes("incompatible_table_context") &&
        !candidate.blockingReasons.includes("incompatible_value_domain")
      ) {
        consideredPriorIds.add(candidate.occurrenceId);
      }
    }

    const eligible = candidates.filter(
      (candidate) => candidate.blockingReasons.length === 0,
    );
    const best = eligible[0];
    const runnerUp = eligible[1];
    const reviewReasons: ReconciliationReviewReason[] = [];

    if (best) {
      if (runnerUp && almostEqual(best.score, runnerUp.score))
        reviewReasons.push("tied_candidates");
      else if (runnerUp && best.score - runnerUp.score < minimumMargin)
        reviewReasons.push("low_margin");
      if (best.score < minimumScore) reviewReasons.push("low_score");
    }

    const incompatibleReasons = sortedUnique(
      candidates.flatMap((candidate) => candidate.blockingReasons),
      "candidate reasons",
    ) as ReconciliationReviewReason[];
    const candidateReviewReasons = incompatibleReasons.filter(
      (reason) =>
        !["different_publication", "incompatible_table_context"].includes(
          reason,
        ),
    );

    if (!best) {
      const isAmbiguous = candidateReviewReasons.length > 0;
      const entry: OccurrenceReconciliationEntry = {
        occurrenceId: incoming.occurrenceId,
        status: isAmbiguous ? "ambiguous" : "new",
        matchedOccurrenceId: null,
        transferredApprovedBinding: false,
        reviewRequired: isAmbiguous,
        reviewReasons: candidateReviewReasons,
        candidates,
      };
      if (isAmbiguous) {
        output.set(
          incoming.occurrenceId,
          abstainedUnlessAlreadyApproved(incoming),
        );
      }
      entries.push(entry);
      continue;
    }

    const chosenPrior = previous.get(best.occurrenceId);
    if (!chosenPrior)
      throw new Error("Reconciliation candidate disappeared during matching.");
    const hasConflictingApprovedCurrentBinding = Boolean(
      incoming.reviewStatus === "approved" &&
        incoming.representedVariableId &&
        chosenPrior.reviewStatus === "approved" &&
        chosenPrior.representedVariableId &&
        incoming.representedVariableId !== chosenPrior.representedVariableId,
    );
    if (hasConflictingApprovedCurrentBinding)
      reviewReasons.push("conflicting_current_binding");
    const safeMatch =
      reviewReasons.length === 0 && !usedPriorIds.has(chosenPrior.occurrenceId);
    if (!safeMatch) {
      const reasons = sortedUnique(
        [
          ...reviewReasons,
          ...(usedPriorIds.has(chosenPrior.occurrenceId)
            ? ["tied_candidates"]
            : []),
        ],
        "review reasons",
      ) as ReconciliationReviewReason[];
      output.set(
        incoming.occurrenceId,
        abstainedUnlessAlreadyApproved(incoming),
      );
      entries.push({
        occurrenceId: incoming.occurrenceId,
        status: "ambiguous",
        matchedOccurrenceId: chosenPrior.occurrenceId,
        transferredApprovedBinding: false,
        reviewRequired: true,
        reviewReasons: reasons,
        candidates,
      });
      continue;
    }

    usedPriorIds.add(chosenPrior.occurrenceId);
    const preserveCurrentApprovedBinding = Boolean(
      incoming.reviewStatus === "approved" && incoming.representedVariableId,
    );
    const transferredApprovedBinding = Boolean(
      !preserveCurrentApprovedBinding &&
        chosenPrior.reviewStatus === "approved" &&
        chosenPrior.representedVariableId,
    );
    const updatedIncoming: DurableVariableOccurrence = {
      ...incoming,
      reviewStatus: transferredApprovedBinding
        ? "approved"
        : incoming.reviewStatus,
      ...(transferredApprovedBinding
        ? { representedVariableId: chosenPrior.representedVariableId }
        : {}),
      supersedes: sortedUniqueEntityIds(
        [...incoming.supersedes, chosenPrior.occurrenceId],
        "supersedes",
      ),
    };
    const updatedPrior: DurableVariableOccurrence = {
      ...chosenPrior,
      supersededBy: sortedUniqueEntityIds(
        [...chosenPrior.supersededBy, incoming.occurrenceId],
        "supersededBy",
      ),
    };
    output.set(incoming.occurrenceId, updatedIncoming);
    previous.set(chosenPrior.occurrenceId, updatedPrior);
    const locationUnchanged = sameLocation(
      incoming.sourceLocation,
      chosenPrior.sourceLocation,
    );
    const entry: OccurrenceReconciliationEntry = {
      occurrenceId: incoming.occurrenceId,
      status: locationUnchanged ? "retained" : "moved",
      matchedOccurrenceId: chosenPrior.occurrenceId,
      transferredApprovedBinding,
      reviewRequired:
        !transferredApprovedBinding && !preserveCurrentApprovedBinding,
      reviewReasons:
        transferredApprovedBinding || preserveCurrentApprovedBinding
          ? []
          : ["prior_binding_not_approved"],
      candidates,
    };
    entries.push(entry);
    supersessions.push({
      supersededOccurrenceId: chosenPrior.occurrenceId,
      supersedingOccurrenceId: incoming.occurrenceId,
      reason: "edition_reconciliation",
      recordedAt,
      provenance: cloneProvenance(provenance),
    });
  }

  const retired = [...previous.values()]
    .filter(
      (occurrence) =>
        !usedPriorIds.has(occurrence.occurrenceId) &&
        !consideredPriorIds.has(occurrence.occurrenceId),
    )
    .map((occurrence) => occurrence.occurrenceId)
    .sort();
  const report = buildReport(entries, retired, supersessions);
  return {
    occurrences: [...output.values()].sort(compareOccurrence),
    priorOccurrences: [...previous.values()].sort(compareOccurrence),
    report,
  };
}

/** Computes explicit, explainable candidate components without mutating either occurrence. */
export function scoreOccurrenceCandidate(
  incoming: DurableVariableOccurrence,
  prior: DurableVariableOccurrence,
): ReconciliationCandidate {
  const blockingReasons: ReconciliationReviewReason[] = [];
  if (incoming.publicationId !== prior.publicationId)
    blockingReasons.push("different_publication");
  if (
    !sameTableContext(incoming.structuralEvidence, prior.structuralEvidence)
  ) {
    blockingReasons.push("incompatible_table_context");
  }
  const domainSimilarity = equalNormalized(
    incoming.structuralEvidence.valueDomainFingerprint,
    prior.structuralEvidence.valueDomainFingerprint,
  )
    ? 1
    : 0;
  if (domainSimilarity === 0) blockingReasons.push("incompatible_value_domain");
  const unitSimilarity = optionalSimilarity(
    incoming.structuralEvidence.unitScale,
    prior.structuralEvidence.unitScale,
  );
  if (unitSimilarity === 0) blockingReasons.push("changed_unit_scale");
  const universeSimilarity = optionalSimilarity(
    incoming.structuralEvidence.universe,
    prior.structuralEvidence.universe,
  );
  if (universeSimilarity === 0) blockingReasons.push("changed_universe");
  const classificationSimilarity = classificationSimilarityFor(
    incoming.structuralEvidence.classification,
    prior.structuralEvidence.classification,
  );
  if (classificationSimilarity === 0)
    blockingReasons.push("conflicting_classification_version");

  const components: ReconciliationScoreComponent[] = [
    component(
      "table_context",
      0.2,
      sameTableContext(incoming.structuralEvidence, prior.structuralEvidence)
        ? 1
        : 0,
    ),
    component(
      "neighbouring_headers",
      0.15,
      jaccardSimilarity(
        incoming.structuralEvidence.tableContext.neighbouringHeaders,
        prior.structuralEvidence.tableContext.neighbouringHeaders,
      ),
    ),
    component(
      "orientation",
      0.1,
      incoming.structuralEvidence.orientation ===
        prior.structuralEvidence.orientation
        ? 1
        : 0,
    ),
    component("value_domain", 0.2, domainSimilarity),
    component("unit_scale", 0.1, unitSimilarity),
    component("universe", 0.1, universeSimilarity),
    component("classification", 0.1, classificationSimilarity),
    component(
      "prior_binding",
      0.05,
      incoming.structuralEvidence.priorRepresentedVariableId &&
        prior.representedVariableId &&
        incoming.structuralEvidence.priorRepresentedVariableId ===
          prior.representedVariableId
        ? 1
        : incoming.structuralEvidence.priorRepresentedVariableId ||
            prior.representedVariableId
          ? 0.5
          : 1,
    ),
  ];
  return {
    occurrenceId: prior.occurrenceId,
    score: round(
      components.reduce((sum, entry) => sum + entry.contribution, 0),
    ),
    components,
    blockingReasons: sortedUnique(
      blockingReasons,
      "blocking reasons",
    ) as ReconciliationReviewReason[],
  };
}

/** Converts a validated v0.1 sheet artifact into raw occurrence candidates only. */
export function occurrenceCandidatesFromSheetArtifact({
  artifact,
  publicationId,
  workbookEditionId,
  tableContext,
  unitScale,
  universe,
  classification,
  provenance,
  neighbouringHeadersByDetectionId = {},
  durableOccurrenceKeyByDetectionId = {},
}: {
  artifact: OntologyArtifact;
  publicationId: PublicationEntityId;
  workbookEditionId: string;
  tableContext: Pick<OccurrenceTableContext, "id" | "kind">;
  unitScale?: string;
  universe?: string;
  classification?: OccurrenceClassificationReference;
  provenance: OccurrenceProvenance;
  neighbouringHeadersByDetectionId?: Record<string, string[]>;
  durableOccurrenceKeyByDetectionId?: Record<string, string>;
}): DurableVariableOccurrence[] {
  const prepared = artifact.resolvedDetections.map((detection) => {
    const structuralEvidence: OccurrenceStructuralEvidence = {
      tableContext: {
        id: tableContext.id,
        kind: tableContext.kind,
        neighbouringHeaders:
          neighbouringHeadersByDetectionId[detection.id] ?? [],
      },
      orientation: detection.orientation,
      valueDomainFingerprint: valueDomainFingerprint(detection),
      ...(unitScale ? { unitScale } : {}),
      ...(universe ? { universe } : {}),
      ...(classification ? { classification } : {}),
    };
    return {
      detection,
      structuralEvidence,
      structuralSignature:
        createOccurrenceStructuralSignature(structuralEvidence),
    };
  });
  const signatureCounts = new Map<string, number>();
  for (const candidate of prepared) {
    signatureCounts.set(
      candidate.structuralSignature.signature,
      (signatureCounts.get(candidate.structuralSignature.signature) ?? 0) + 1,
    );
  }

  return prepared
    .sort(
      (left, right) =>
        left.structuralSignature.signature.localeCompare(
          right.structuralSignature.signature,
        ) || left.detection.id.localeCompare(right.detection.id),
    )
    .map(({ detection, structuralEvidence, structuralSignature }) => {
      const suppliedKey = durableOccurrenceKeyByDetectionId[detection.id];
      if (
        !suppliedKey &&
        (signatureCounts.get(structuralSignature.signature) ?? 0) > 1
      ) {
        throw new Error(
          "Structurally identical detections require caller-supplied durable occurrence keys.",
        );
      }
      return createDurableOccurrence({
        publicationId,
        workbookEditionId,
        // A signature excludes the mutable v0.1 sheet/range/name hash.
        durableOccurrenceKey: suppliedKey ?? structuralSignature.signature,
        sourceLocation: {
          assetId: artifact.assetId,
          sheetName: detection.sheet,
          range: detection.range,
          addresses: detection.addresses,
        },
        rawDetectionIds: [detection.id],
        structuralEvidence,
        reviewStatus: "proposed",
        provenance,
      });
    });
}

function abstainedUnlessAlreadyApproved(
  occurrence: DurableVariableOccurrence,
): DurableVariableOccurrence {
  if (
    occurrence.reviewStatus === "approved" &&
    occurrence.representedVariableId
  ) {
    return occurrence;
  }
  return {
    ...occurrence,
    reviewStatus: "abstained",
    representedVariableId: undefined,
  };
}

function buildReport(
  entries: OccurrenceReconciliationEntry[],
  retired: PublicationEntityId[],
  supersessions: OccurrenceSupersession[],
): OccurrenceReconciliationReport {
  const sortEntries = (status: OccurrenceReconciliationEntry["status"]) =>
    entries
      .filter((entry) => entry.status === status)
      .sort((left, right) =>
        left.occurrenceId.localeCompare(right.occurrenceId),
      );
  return {
    version: "1.0",
    retained: sortEntries("retained"),
    moved: sortEntries("moved"),
    new: sortEntries("new"),
    ambiguous: sortEntries("ambiguous"),
    retired: [...retired].sort(),
    supersessions: [...supersessions].sort((left, right) =>
      `${left.supersededOccurrenceId}\u001f${left.supersedingOccurrenceId}`.localeCompare(
        `${right.supersededOccurrenceId}\u001f${right.supersedingOccurrenceId}`,
      ),
    ),
  };
}

function component(
  name: ReconciliationScoreComponent["name"],
  weight: number,
  similarity: number,
): ReconciliationScoreComponent {
  return {
    name,
    weight,
    similarity: round(similarity),
    contribution: round(weight * similarity),
  };
}

function compareCandidate(
  left: ReconciliationCandidate,
  right: ReconciliationCandidate,
): number {
  return (
    right.score - left.score ||
    left.occurrenceId.localeCompare(right.occurrenceId)
  );
}

function compareOccurrence(
  left: DurableVariableOccurrence,
  right: DurableVariableOccurrence,
): number {
  return left.occurrenceId.localeCompare(right.occurrenceId);
}

function sameTableContext(
  left: OccurrenceStructuralEvidence,
  right: OccurrenceStructuralEvidence,
): boolean {
  return (
    normalizeOptional(left.tableContext.id) ===
      normalizeOptional(right.tableContext.id) &&
    normalizeOptional(left.tableContext.kind) ===
      normalizeOptional(right.tableContext.kind)
  );
}

function classificationSimilarityFor(
  left?: OccurrenceClassificationReference,
  right?: OccurrenceClassificationReference,
): number {
  if (!left && !right) return 1;
  if (!left || !right) return 0.5;
  return left.valueSchemeId === right.valueSchemeId &&
    left.valueSchemeVersion === right.valueSchemeVersion
    ? 1
    : 0;
}

function optionalSimilarity(left?: string, right?: string): number {
  if (!left && !right) return 1;
  if (!left || !right) return 0;
  return equalNormalized(left, right) ? 1 : 0;
}

function jaccardSimilarity(
  left: readonly string[],
  right: readonly string[],
): number {
  const leftSet = new Set(normalizeTokens(left));
  const rightSet = new Set(normalizeTokens(right));
  if (leftSet.size === 0 && rightSet.size === 0) return 1;
  const intersection = [...leftSet].filter((value) =>
    rightSet.has(value),
  ).length;
  return intersection / new Set([...leftSet, ...rightSet]).size;
}

function valueDomainFingerprint(detection: OntologyDetection): string {
  return [detection.kind, ...normalizeTokens(detection.sampleValues)].join("|");
}

function sameLocation(
  left: OccurrenceSourceLocation,
  right: OccurrenceSourceLocation,
): boolean {
  return (
    left.sheetName === right.sheetName &&
    left.range === right.range &&
    JSON.stringify([...left.addresses].sort()) ===
      JSON.stringify([...right.addresses].sort())
  );
}

function cloneOccurrence(
  occurrence: DurableVariableOccurrence,
): DurableVariableOccurrence {
  return {
    ...occurrence,
    sourceLocation: normalizeSourceLocation(occurrence.sourceLocation),
    rawDetectionIds: [...occurrence.rawDetectionIds],
    structuralEvidence: createOccurrenceStructuralSignature(
      occurrence.structuralEvidence,
    ).evidence,
    provenance: cloneProvenance(occurrence.provenance),
    supersedes: [...occurrence.supersedes],
    supersededBy: [...occurrence.supersededBy],
  };
}

function cloneProvenance(
  provenance: OccurrenceProvenance,
): OccurrenceProvenance {
  return { ...provenance, evidence: [...provenance.evidence] };
}

function normalizeSourceLocation(
  sourceLocation: OccurrenceSourceLocation,
): OccurrenceSourceLocation {
  return {
    assetId: trimRequired(sourceLocation.assetId, "asset ID"),
    sheetName: trimRequired(sourceLocation.sheetName, "sheet name"),
    range: trimRequired(sourceLocation.range, "source range"),
    addresses: sortedUniqueExact(sourceLocation.addresses, "source addresses"),
  };
}

function assertUniqueOccurrenceIds(
  occurrences: readonly DurableVariableOccurrence[],
  description: string,
): void {
  const ids = occurrences.map((occurrence) => occurrence.occurrenceId);
  if (new Set(ids).size !== ids.length) {
    throw new Error(
      `Duplicate ${description} occurrence IDs are not reconcilable.`,
    );
  }
}

function sortedUnique(
  values: readonly string[],
  description: string,
): string[] {
  const normalized = values.map((value) =>
    normalizeRequired(value, description),
  );
  const unique = [...new Set(normalized)].sort();
  if (unique.length !== normalized.length) {
    throw new Error(`${description} must be unique.`);
  }
  return unique;
}

function sameExactValues(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return (
    left.length === right.length &&
    [...left].sort().every((value, index) => value === [...right].sort()[index])
  );
}

function sortedUniqueExact(
  values: readonly string[],
  description: string,
): string[] {
  const normalized = values.map((value) => value.trim());
  if (normalized.some((value) => !value)) {
    throw new Error(`${description} must be non-empty.`);
  }
  const unique = [...new Set(normalized)].sort();
  if (unique.length !== normalized.length) {
    throw new Error(`${description} must be unique.`);
  }
  return unique;
}

function sortedUniqueEntityIds(
  values: readonly PublicationEntityId[],
  description: string,
): PublicationEntityId[] {
  const unique = sortedUnique(values, description);
  return unique as PublicationEntityId[];
}

function normalizeTokens(values: readonly string[]): string[] {
  return [
    ...new Set(values.map((value) => normalizeOptional(value)).filter(Boolean)),
  ].sort();
}

function normalizeRequired(value: string, description: string): string {
  const normalized = normalizeOptional(value);
  if (!normalized) throw new Error(`${description} must be non-empty.`);
  return normalized;
}

function trimRequired(value: string, description: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error(`${description} must be non-empty.`);
  return trimmed;
}

function normalizeOptional(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase();
}

function equalNormalized(left: string, right: string): boolean {
  return normalizeOptional(left) === normalizeOptional(right);
}

function almostEqual(left: number, right: number): boolean {
  return Math.abs(left - right) < 0.000001;
}

function round(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

function fnv1a32(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return (hash >>> 0).toString(36).padStart(8, "0");
}
