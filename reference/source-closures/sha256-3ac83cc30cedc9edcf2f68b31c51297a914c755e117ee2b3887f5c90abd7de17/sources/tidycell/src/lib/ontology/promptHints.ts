import { compatibilityWarningsForOccurrence } from "./publicationCompatibility";
import {
  safeParsePublicationOntology,
  type PublicationOntology,
} from "./publicationSchema";
import type { OntologyDetection, SheetOntology } from "./types";
import type { OntologyOverrides, ResolvedSheetOntology } from "./overrides";

export type OntologyPromptInput = SheetOntology | ResolvedSheetOntology;

export const PUBLICATION_ONTOLOGY_PROMPT_CHAR_BUDGET = 8_000;
export const PUBLICATION_ONTOLOGY_TOKEN_ESTIMATOR = "utf16_chars_div_4_ceil_v1" as const;
export const PUBLICATION_ONTOLOGY_PROMPT_GUIDANCE = [
  "Preserve every raw source label and raw source value exactly; ontology hints are structural evidence only and must never canonicalise source cells.",
  "Keep year, quarter, and month as separate header dimensions whenever they are represented separately.",
  "Prefer specific represented variables over broad aliases that overlap them.",
  "Canonical labels and ontology IDs are metadata, not source values, and must not be emitted as if they occurred in the workbook.",
  "Respect every rejected or non-equivalent binding in hardExclusions; never merge those concepts.",
  "Preserve approved join-key dimensions as output headers when they describe observation values.",
  "Recipe output cannot publish, approve, or modify publication ontology state.",
] as const;

export type PublicationOntologyPromptPin = {
  publicationId: string;
  publisherId: string;
  artifactVersion: "0.2";
  ontologyVersion: string;
};

export type PublicationOntologyPromptFeature =
  | { enabled: false }
  | {
      enabled: true;
      artifact?: unknown;
      assetId?: string;
      workbookEditionId?: string;
      sheetNames?: string[];
      expectedPin?: PublicationOntologyPromptPin;
      unavailableReason?: string;
    };

export type OntologyPromptOmissionReason =
  | "feature_flag_off"
  | "artifact_missing"
  | "artifact_invalid"
  | "scope_missing"
  | "pin_conflict"
  | "profile_not_approved"
  | "out_of_scope"
  | "not_approved"
  | "ambiguous"
  | "stale"
  | "version_conflict"
  | "compatibility_conflict"
  | "budget";

export type OntologyPromptProvenance = {
  feature: {
    name: "approved_publication_ontology_prompts";
    enabled: boolean;
    source: "default_off" | "explicit_off" | "explicit_on";
  };
  artifact: {
    supplied: boolean;
    validated: boolean;
    eligible: boolean;
    reason?: string;
    expectedPin?: PublicationOntologyPromptPin;
    actualPin?: PublicationOntologyPromptPin;
  };
  included: Record<string, number>;
  omitted: Partial<Record<OntologyPromptOmissionReason, number>>;
  budget: {
    scope: "serialized_ontology_guidance_utf16";
    maxCharacters: number;
    maxEstimatedTokens: number;
    usedCharacters: number;
    estimatedTokens: number;
    estimator: typeof PUBLICATION_ONTOLOGY_TOKEN_ESTIMATOR;
    truncated: boolean;
  };
  legacyFallback: "used" | "unavailable" | "not_needed";
};

export type OntologyPromptPayload = {
  legacySections: unknown[];
  publicationSections: unknown[];
  publicationActive: boolean;
  provenance: OntologyPromptProvenance;
};

type PromptDetectionSource = "detected" | "user_override" | "user_defined";

type PromptDetection = {
  id: string;
  name: string;
  kind: string;
  range: string;
  orientation: string;
  confidence: number;
  evidence: string;
  joinKey: boolean;
  sampleValues: string[];
  source: PromptDetectionSource;
  confirmed: boolean;
};

type ApprovedBinding = {
  occurrenceId: string;
  sheet: string;
  source: {
    range: string;
    rawDetectionIds: string[];
  };
  concept: { id: string; label: string };
  representedVariable: {
    id: string;
    label: string;
    version: string;
    componentRole: string;
    semanticDomain: string;
    measureType: string;
    unitScale: string | null;
  };
  valueScheme: { id: string; version: string } | null;
  joinKey: boolean;
  bindingMethod: string;
  temporal: boolean;
};

type HardExclusion = {
  kind: "rejected_occurrence_binding" | "rejected_hierarchy_relation";
  occurrenceId?: string;
  representedVariableId?: string;
  representedVariableLabel?: string;
  source?: {
    sheet: string;
    range: string;
    rawDetectionIds: string[];
  };
  hierarchyId?: string;
  hierarchyVersion?: string;
  sourceLevelId?: string;
  targetLevelId?: string;
  relation?: string;
  reason: "explicit_rejection_non_equivalence";
};

type HierarchyHint = {
  id: string;
  version: string;
  type: string;
  periodScheme: { id: string; version: string; kind: string | null } | null;
  levels: Array<{
    id: string;
    label: string;
    order: number;
    valueScheme: { id: string; version: string } | null;
  }>;
  approvedRelations: Array<{
    sourceLevelId: string;
    targetLevelId: string;
    relation: string;
    aggregation: string | null;
  }>;
};

/** Existing sheet-ontology serializer. Its one-argument output is intentionally unchanged. */
export function buildOntologyPromptSection(
  ontologies: OntologyPromptInput | OntologyPromptInput[] | undefined,
): unknown[] {
  if (!ontologies) {
    return [];
  }

  return (Array.isArray(ontologies) ? ontologies : [ontologies])
    .map((ontology) => serializeOntology(ontology))
    .filter((section) => section !== null);
}

export function buildOntologyPromptPayload(
  ontologies: OntologyPromptInput | OntologyPromptInput[] | undefined,
  publicationFeature?: PublicationOntologyPromptFeature,
): OntologyPromptPayload {
  const originalLegacy = buildOntologyPromptSection(ontologies);
  const flagEnabled = publicationFeature?.enabled === true;
  const provenance = baseProvenance(publicationFeature, originalLegacy.length);

  if (!flagEnabled) {
    provenance.omitted.feature_flag_off = 1;
    return {
      legacySections: originalLegacy,
      publicationSections: [],
      publicationActive: false,
      provenance,
    };
  }

  const feature = publicationFeature;
  if (feature.artifact === undefined) {
    provenance.artifact.reason = feature.unavailableReason ?? "Publication artifact was not supplied.";
    provenance.omitted.artifact_missing = 1;
    return fallbackPayload(originalLegacy, provenance);
  }

  const parsed = safeParsePublicationOntology(feature.artifact);
  if (!parsed.success) {
    provenance.artifact.reason = "Publication artifact failed strict validation.";
    provenance.omitted.artifact_invalid = 1;
    return fallbackPayload(originalLegacy, provenance);
  }
  provenance.artifact.validated = true;
  const artifact = parsed.data;
  provenance.artifact.actualPin = actualPin(artifact);

  if (
    !feature.expectedPin ||
    !feature.assetId ||
    !feature.workbookEditionId ||
    !feature.sheetNames?.length
  ) {
    provenance.artifact.reason = "Publication prompt scope or independent pin is incomplete.";
    provenance.omitted.scope_missing = 1;
    return fallbackPayload(originalLegacy, provenance);
  }

  if (!samePin(feature.expectedPin, actualPin(artifact))) {
    provenance.artifact.reason = "Publication artifact does not match the independent expected pin.";
    provenance.omitted.pin_conflict = 1;
    return fallbackPayload(originalLegacy, provenance);
  }

  if (!isReviewed(artifact.profile.status)) {
    provenance.artifact.reason = "Publication profile is not reviewed or published.";
    provenance.omitted.profile_not_approved = 1;
    return fallbackPayload(originalLegacy, provenance);
  }

  provenance.artifact.eligible = true;
  const omissionCounts: Partial<Record<OntologyPromptOmissionReason, number>> = {};
  const legacyOntologies = Array.isArray(ontologies)
    ? ontologies
    : ontologies
      ? [ontologies]
      : [];
  const approvedBindings = approvedPromptBindings({
    artifact,
    feature,
    legacyOntologies,
    omissions: omissionCounts,
  });
  const hierarchyHints = promptHierarchyHints(artifact, approvedBindings, omissionCounts);
  const hardExclusions = promptHardExclusions({
    artifact,
    feature,
    approvedBindings,
    omissions: omissionCounts,
  });

  const profile = {
    publicationId: artifact.profile.id,
    publisherId: artifact.profile.publisherId,
    artifactVersion: artifact.artifactVersion,
    ontologyVersion: artifact.profile.ontologyVersion,
  };
  const publicationSection = {
    source: "approved_publication_ontology",
    profile,
    hardExclusions: [] as HardExclusion[],
    approvedBindings: [] as ApprovedBinding[],
    approvedHierarchies: [] as HierarchyHint[],
  };
  const publicationSections: unknown[] = [publicationSection];
  let used = PUBLICATION_ONTOLOGY_PROMPT_GUIDANCE.join("\n").length + serializedChars(publicationSections);
  let truncated = false;
  const included: Record<string, number> = {};

  const admit = <T>(section: keyof Pick<typeof publicationSection, "hardExclusions" | "approvedBindings" | "approvedHierarchies">, item: T) => {
    const values = publicationSection[section] as unknown[];
    values.push(item);
    const next = PUBLICATION_ONTOLOGY_PROMPT_GUIDANCE.join("\n").length + serializedChars(publicationSections);
    if (next > PUBLICATION_ONTOLOGY_PROMPT_CHAR_BUDGET) {
      values.pop();
      truncated = true;
      increment(omissionCounts, "budget");
      return;
    }
    used = next;
    included[section] = (included[section] ?? 0) + 1;
  };

  hardExclusions.sort(stableEntityCompare).forEach((item) => admit("hardExclusions", item));
  approvedBindings
    .sort(bindingPriorityCompare)
    .forEach((item) => admit("approvedBindings", item));
  hierarchyHints.sort(stableEntityCompare).forEach((item) => admit("approvedHierarchies", item));

  // Publication safety and reviewed records always win. Legacy sections are admitted
  // afterward as whole, deterministically sorted records; low-confidence sections are
  // therefore the first material omitted under pressure.
  const budgetedLegacy: unknown[] = [];
  for (const legacy of sortLegacySectionsForBudget(originalLegacy)) {
    const next = PUBLICATION_ONTOLOGY_PROMPT_GUIDANCE.join("\n").length
      + serializedChars(publicationSections)
      + serializedChars([...budgetedLegacy, legacy]);
    if (next > PUBLICATION_ONTOLOGY_PROMPT_CHAR_BUDGET) {
      truncated = true;
      increment(omissionCounts, "budget");
      continue;
    }
    budgetedLegacy.push(legacy);
    used = next;
    included.legacySheetOntology = (included.legacySheetOntology ?? 0) + 1;
  }

  provenance.included = included;
  provenance.omitted = omissionCounts;
  provenance.budget.usedCharacters = used;
  provenance.budget.estimatedTokens = estimatedTokens(used);
  provenance.budget.truncated = truncated;
  provenance.legacyFallback = budgetedLegacy.length > 0 ? "used" : "unavailable";

  const hasPublicationContent =
    publicationSection.hardExclusions.length > 0 ||
    publicationSection.approvedBindings.length > 0 ||
    publicationSection.approvedHierarchies.length > 0;
  if (!hasPublicationContent) {
    provenance.artifact.reason = "No current approved publication guidance matched the requested scope.";
    return fallbackPayload(originalLegacy, provenance);
  }

  return {
    legacySections: budgetedLegacy,
    publicationSections,
    publicationActive: true,
    provenance,
  };
}

function approvedPromptBindings({
  artifact,
  feature,
  legacyOntologies,
  omissions,
}: {
  artifact: PublicationOntology;
  feature: Extract<PublicationOntologyPromptFeature, { enabled: true }>;
  legacyOntologies: OntologyPromptInput[];
  omissions: Partial<Record<OntologyPromptOmissionReason, number>>;
}): ApprovedBinding[] {
  const sheets = new Set(feature.sheetNames);
  const results: ApprovedBinding[] = [];

  for (const occurrence of [...artifact.occurrenceMappings].sort((a, b) => a.occurrenceId.localeCompare(b.occurrenceId))) {
    if (!("rawDetectionIds" in occurrence) || !("structuralEvidence" in occurrence)) continue;
    if (
      occurrence.sourceLocation.assetId !== feature.assetId ||
      occurrence.workbookEditionId !== feature.workbookEditionId ||
      !sheets.has(occurrence.sourceLocation.sheetName)
    ) {
      increment(omissions, "out_of_scope");
      continue;
    }
    if (occurrence.reviewStatus !== "approved" || !occurrence.representedVariableId) {
      increment(omissions, "not_approved");
      continue;
    }
    if (occurrence.supersededBy.length > 0) {
      increment(omissions, "stale");
      continue;
    }

    const decisions = artifact.occurrenceVariableBindings.filter((binding) => binding.occurrenceId === occurrence.occurrenceId);
    const approvedDecisions = decisions.filter((binding) =>
      binding.reviewStatus === "approved" &&
      binding.representedVariableId === occurrence.representedVariableId,
    );
    if (decisions.length > 0 && approvedDecisions.length !== 1) {
      increment(omissions, approvedDecisions.length > 1 ? "ambiguous" : "not_approved");
      continue;
    }
    const explicit = approvedDecisions[0];
    const represented = artifact.representedVariables.find((item) => item.id === occurrence.representedVariableId);
    if (!represented || !isReviewed(represented.status)) {
      increment(omissions, "stale");
      continue;
    }
    const conceptual = artifact.conceptualVariables.find((item) => item.id === represented.conceptualVariableId);
    const concept = conceptual
      ? artifact.concepts.find((item) => item.id === conceptual.conceptId)
      : undefined;
    if (!conceptual || !concept || !isReviewed(conceptual.status) || !isReviewed(concept.status)) {
      increment(omissions, "stale");
      continue;
    }
    if (
      explicit &&
      (explicit.representedVariableVersion !== represented.version ||
        explicit.conceptualVariableId !== conceptual.id ||
        explicit.conceptId !== concept.id)
    ) {
      increment(omissions, "version_conflict");
      continue;
    }
    const scheme = represented.valueScheme
      ? artifact.valueSchemes.find((item) =>
          item.id === represented.valueScheme?.valueSchemeId &&
          item.version === represented.valueScheme?.valueSchemeVersion,
        )
      : undefined;
    if (represented.valueScheme && (!scheme || !isReviewed(scheme.status))) {
      increment(omissions, "version_conflict");
      continue;
    }
    if (
      explicit?.valueScheme &&
      (!represented.valueScheme ||
        explicit.valueScheme.valueSchemeId !== represented.valueScheme.valueSchemeId ||
        explicit.valueScheme.valueSchemeVersion !== represented.valueScheme.valueSchemeVersion)
    ) {
      increment(omissions, "version_conflict");
      continue;
    }
    if (compatibilityWarningsForOccurrence(artifact, occurrence).length > 0) {
      increment(omissions, "compatibility_conflict");
      continue;
    }

    const joinKey = occurrence.rawDetectionIds.some((rawId) =>
      legacyOntologies.some((ontology) =>
        ontology.sheet === occurrence.sourceLocation.sheetName &&
        ontology.detections.some((detection) =>
          detection.id === rawId &&
          detection.sheet === occurrence.sourceLocation.sheetName &&
          detection.range === occurrence.sourceLocation.range &&
          sameStrings(detection.addresses, occurrence.sourceLocation.addresses) &&
          detection.joinKey,
        ),
      ),
    );
    results.push({
      occurrenceId: occurrence.occurrenceId,
      sheet: occurrence.sourceLocation.sheetName,
      source: {
        range: occurrence.sourceLocation.range,
        rawDetectionIds: [...occurrence.rawDetectionIds].sort(),
      },
      concept: { id: concept.id, label: preferredLabel(concept.preferredLabels) },
      representedVariable: {
        id: represented.id,
        label: preferredLabel(represented.preferredLabels),
        version: represented.version,
        componentRole: represented.componentRole,
        semanticDomain: represented.semanticDomain,
        measureType: represented.measureType,
        unitScale: represented.unitScale ?? null,
      },
      valueScheme: represented.valueScheme
        ? { id: represented.valueScheme.valueSchemeId, version: represented.valueScheme.valueSchemeVersion }
        : null,
      joinKey,
      bindingMethod: explicit?.method ?? "approved_occurrence",
      temporal: represented.semanticDomain === "temporal",
    });
  }

  return results;
}

function promptHardExclusions({
  artifact,
  feature,
  approvedBindings,
  omissions,
}: {
  artifact: PublicationOntology;
  feature: Extract<PublicationOntologyPromptFeature, { enabled: true }>;
  approvedBindings: ApprovedBinding[];
  omissions: Partial<Record<OntologyPromptOmissionReason, number>>;
}): HardExclusion[] {
  const exclusions: HardExclusion[] = [];
  for (const binding of artifact.occurrenceVariableBindings) {
    if (binding.reviewStatus !== "rejected" || !binding.representedVariableId) continue;
    const occurrence = artifact.occurrenceMappings.find((item) => item.occurrenceId === binding.occurrenceId);
    if (
      !occurrence ||
      !("rawDetectionIds" in occurrence) ||
      occurrence.sourceLocation.assetId !== feature.assetId ||
      occurrence.workbookEditionId !== feature.workbookEditionId ||
      !feature.sheetNames?.includes(occurrence.sourceLocation.sheetName)
    ) continue;
    if (occurrence.supersededBy.length > 0) {
      increment(omissions, "stale");
      continue;
    }
    const represented = artifact.representedVariables.find((item) => item.id === binding.representedVariableId);
    const conceptual = represented
      ? artifact.conceptualVariables.find((item) => item.id === represented.conceptualVariableId)
      : undefined;
    const concept = conceptual
      ? artifact.concepts.find((item) => item.id === conceptual.conceptId)
      : undefined;
    if (
      !represented ||
      !conceptual ||
      !concept ||
      !isReviewed(represented.status) ||
      !isReviewed(conceptual.status) ||
      !isReviewed(concept.status)
    ) {
      increment(omissions, "stale");
      continue;
    }
    if (
      binding.representedVariableVersion !== represented.version ||
      binding.conceptualVariableId !== conceptual.id ||
      binding.conceptId !== concept.id
    ) {
      increment(omissions, "version_conflict");
      continue;
    }
    const scheme = represented.valueScheme
      ? artifact.valueSchemes.find((item) =>
          item.id === represented.valueScheme?.valueSchemeId &&
          item.version === represented.valueScheme?.valueSchemeVersion,
        )
      : undefined;
    if (
      (represented.valueScheme && (!scheme || !isReviewed(scheme.status))) ||
      (binding.valueScheme &&
        (!represented.valueScheme ||
          binding.valueScheme.valueSchemeId !== represented.valueScheme.valueSchemeId ||
          binding.valueScheme.valueSchemeVersion !== represented.valueScheme.valueSchemeVersion))
    ) {
      increment(omissions, "version_conflict");
      continue;
    }
    exclusions.push({
      kind: "rejected_occurrence_binding",
      occurrenceId: occurrence.occurrenceId,
      representedVariableId: represented.id,
      representedVariableLabel: preferredLabel(represented.preferredLabels),
      source: {
        sheet: occurrence.sourceLocation.sheetName,
        range: occurrence.sourceLocation.range,
        rawDetectionIds: [...occurrence.rawDetectionIds].sort(),
      },
      reason: "explicit_rejection_non_equivalence",
    });
  }

  const relevantSchemeVersions = new Set(
    approvedBindings.flatMap((item) => item.valueScheme ? [`${item.valueScheme.id}@${item.valueScheme.version}`] : []),
  );
  for (const hierarchy of artifact.hierarchies) {
    if (!isReviewed(hierarchy.status)) continue;
    const periodScheme = hierarchy.periodScheme
      ? artifact.valueSchemes.find((item) =>
          item.id === hierarchy.periodScheme?.valueSchemeId &&
          item.version === hierarchy.periodScheme?.valueSchemeVersion &&
          isReviewed(item.status),
        )
      : undefined;
    if (hierarchy.periodScheme && !periodScheme) continue;
    const currentLevels = hierarchy.levels.filter((level) => {
      if (!level.valueScheme) return false;
      const key = `${level.valueScheme.valueSchemeId}@${level.valueScheme.valueSchemeVersion}`;
      if (!relevantSchemeVersions.has(key)) return false;
      return artifact.valueSchemes.some((item) =>
        item.id === level.valueScheme?.valueSchemeId &&
        item.version === level.valueScheme?.valueSchemeVersion &&
        isReviewed(item.status),
      );
    });
    const levelIds = new Set(currentLevels.map((level) => level.id));
    if (levelIds.size === 0) continue;
    for (const edge of hierarchy.edges) {
      if (edge.reviewStatus !== "rejected" || !edge.sourceLevelId || !edge.targetLevelId) continue;
      if (edge.hierarchyId !== hierarchy.id || edge.hierarchyVersion !== hierarchy.version) {
        increment(omissions, "version_conflict");
        continue;
      }
      if (!levelIds.has(edge.sourceLevelId) || !levelIds.has(edge.targetLevelId)) continue;
      exclusions.push({
        kind: "rejected_hierarchy_relation",
        hierarchyId: hierarchy.id,
        hierarchyVersion: hierarchy.version,
        sourceLevelId: edge.sourceLevelId,
        targetLevelId: edge.targetLevelId,
        relation: edge.relation,
        reason: "explicit_rejection_non_equivalence",
      });
    }
  }
  return dedupeByJson(exclusions);
}

function promptHierarchyHints(
  artifact: PublicationOntology,
  bindings: ApprovedBinding[],
  omissions: Partial<Record<OntologyPromptOmissionReason, number>>,
): HierarchyHint[] {
  const relevantSchemeIds = new Set(bindings.flatMap((item) => item.valueScheme ? [item.valueScheme.id] : []));
  const relevantSchemeVersions = new Set(bindings.flatMap((item) => item.valueScheme ? [`${item.valueScheme.id}@${item.valueScheme.version}`] : []));
  return artifact.hierarchies.flatMap((hierarchy) => {
    const candidateLevels = hierarchy.levels.filter((level) =>
      level.valueScheme && relevantSchemeIds.has(level.valueScheme.valueSchemeId),
    );
    if (candidateLevels.length === 0) return [];
    if (!isReviewed(hierarchy.status)) {
      increment(omissions, "not_approved");
      return [];
    }
    const hasVersionConflict = candidateLevels.some((level) => {
      if (!level.valueScheme) return false;
      const key = `${level.valueScheme.valueSchemeId}@${level.valueScheme.valueSchemeVersion}`;
      const scheme = artifact.valueSchemes.find((item) =>
        item.id === level.valueScheme?.valueSchemeId &&
        item.version === level.valueScheme?.valueSchemeVersion,
      );
      return !relevantSchemeVersions.has(key) || !scheme || !isReviewed(scheme.status);
    });
    const periodScheme = hierarchy.periodScheme
      ? artifact.valueSchemes.find((item) =>
          item.id === hierarchy.periodScheme?.valueSchemeId &&
          item.version === hierarchy.periodScheme?.valueSchemeVersion,
        )
      : undefined;
    if (hasVersionConflict || (hierarchy.periodScheme && (!periodScheme || !isReviewed(periodScheme.status)))) {
      increment(omissions, "version_conflict");
      return [];
    }
    const levels = candidateLevels
      .map((level) => ({
        id: level.id,
        label: preferredLabel(level.preferredLabels),
        order: level.order,
        valueScheme: level.valueScheme
          ? { id: level.valueScheme.valueSchemeId, version: level.valueScheme.valueSchemeVersion }
          : null,
      }))
      .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
    const levelIds = new Set(levels.map((level) => level.id));
    const approvedRelations = hierarchy.edges
      .filter((edge) => {
        if (edge.reviewStatus !== "approved") return false;
        if (edge.hierarchyId !== hierarchy.id || edge.hierarchyVersion !== hierarchy.version) {
          increment(omissions, "version_conflict");
          return false;
        }
        return Boolean(edge.sourceLevelId && levelIds.has(edge.sourceLevelId)) &&
          Boolean(edge.targetLevelId && levelIds.has(edge.targetLevelId));
      })
      .map((edge) => ({
        sourceLevelId: edge.sourceLevelId!,
        targetLevelId: edge.targetLevelId!,
        relation: edge.relation,
        aggregation: edge.aggregation ?? null,
      }))
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    if (approvedRelations.length === 0) {
      increment(omissions, "not_approved");
      return [];
    }
    return [{
      id: hierarchy.id,
      version: hierarchy.version,
      type: hierarchy.type,
      periodScheme: hierarchy.periodScheme
        ? {
            id: hierarchy.periodScheme.valueSchemeId,
            version: hierarchy.periodScheme.valueSchemeVersion,
            kind: hierarchy.periodSchemeKind ?? null,
          }
        : null,
      levels,
      approvedRelations,
    }];
  });
}

function baseProvenance(
  feature: PublicationOntologyPromptFeature | undefined,
  legacyCount: number,
): OntologyPromptProvenance {
  const enabled = feature?.enabled === true;
  const source = feature === undefined
    ? "default_off"
    : enabled
      ? "explicit_on"
      : "explicit_off";
  return {
    feature: { name: "approved_publication_ontology_prompts", enabled, source },
    artifact: {
      supplied: enabled && feature.artifact !== undefined,
      validated: false,
      eligible: false,
      expectedPin: enabled ? feature.expectedPin : undefined,
    },
    included: legacyCount > 0 ? { legacySheetOntology: legacyCount } : {},
    omitted: {},
    budget: {
      scope: "serialized_ontology_guidance_utf16",
      maxCharacters: PUBLICATION_ONTOLOGY_PROMPT_CHAR_BUDGET,
      maxEstimatedTokens: estimatedTokens(PUBLICATION_ONTOLOGY_PROMPT_CHAR_BUDGET),
      usedCharacters: 0,
      estimatedTokens: 0,
      estimator: PUBLICATION_ONTOLOGY_TOKEN_ESTIMATOR,
      truncated: false,
    },
    legacyFallback: legacyCount > 0 ? "used" : "unavailable",
  };
}

function fallbackPayload(legacy: unknown[], provenance: OntologyPromptProvenance): OntologyPromptPayload {
  provenance.included = legacy.length > 0 ? { legacySheetOntology: legacy.length } : {};
  provenance.budget.usedCharacters = 0;
  provenance.budget.estimatedTokens = 0;
  provenance.budget.truncated = false;
  provenance.legacyFallback = legacy.length > 0 ? "used" : "unavailable";
  return { legacySections: legacy, publicationSections: [], publicationActive: false, provenance };
}

function actualPin(artifact: PublicationOntology): PublicationOntologyPromptPin {
  return {
    publicationId: artifact.profile.id,
    publisherId: artifact.profile.publisherId,
    artifactVersion: artifact.artifactVersion,
    ontologyVersion: artifact.profile.ontologyVersion,
  };
}

function samePin(left: PublicationOntologyPromptPin, right: PublicationOntologyPromptPin): boolean {
  return left.publicationId === right.publicationId &&
    left.publisherId === right.publisherId &&
    left.artifactVersion === right.artifactVersion &&
    left.ontologyVersion === right.ontologyVersion;
}

function serializeOntology(ontology: OntologyPromptInput) {
  const deterministicDetections =
    "deterministicDetections" in ontology
      ? ontology.deterministicDetections
      : ontology.detections.filter((detection) => detection.source !== "user");
  const rejectedDetections =
    "rejectedDetections" in ontology ? ontology.rejectedDetections : [];
  const overrides = "overrides" in ontology ? ontology.overrides : undefined;
  const activeDetections = ontology.detections;

  if (
    activeDetections.length === 0 &&
    deterministicDetections.length === 0 &&
    rejectedDetections.length === 0 &&
    ontology.avoidBroadAliases.length === 0 &&
    ontology.joinCandidates.length === 0 &&
    ontology.promptHints.length === 0
  ) {
    return null;
  }

  return {
    sheet: ontology.sheet,
    deterministicRawDetections: deterministicDetections.map((detection) =>
      compactDetection(detection, "detected", false),
    ),
    activeDetections: activeDetections.map((detection) =>
      compactDetection(detection, promptSourceForDetection(detection, overrides),
        promptSourceForDetection(detection, overrides) !== "detected"),
    ),
    rejectedDetections: rejectedDetections.map((detection) => ({
      ...compactDetection(detection, "detected", false),
      status: "rejected_excluded",
    })),
    avoidBroadAliases: ontology.avoidBroadAliases.map((alias) => ({
      broadName: alias.broadName,
      prefer: alias.prefer,
      ranges: alias.ranges,
      reason: alias.reason,
    })),
    joinCandidates: ontology.joinCandidates.map((candidate) => ({
      kind: candidate.kind,
      name: candidate.name,
      sheet: candidate.sheet,
      range: candidate.range,
      confidence: candidate.confidence,
    })),
    guidance: [
      "Prefer activeDetections marked user_override or user_defined over deterministic raw names.",
      "Prefer specific ontology dimensions over broad aliases such as period.",
      "Keep mutually-exclusive ontology dimensions separate; do not assign the same header cells to both a broad alias and a specific ontology dimension.",
      "Preserve joinKey dimensions as output header variables when they describe observation values.",
      "Treat rejectedDetections as exclusions, not active guidance.",
    ],
    hints: ontology.promptHints,
  };
}

function compactDetection(
  detection: OntologyDetection,
  source: PromptDetectionSource,
  confirmed: boolean,
): PromptDetection {
  return {
    id: detection.id,
    name: detection.name,
    kind: detection.kind,
    range: detection.range,
    orientation: detection.orientation,
    confidence: detection.confidence,
    evidence: detection.evidence,
    joinKey: detection.joinKey,
    sampleValues: detection.sampleValues.slice(0, 8),
    source,
    confirmed,
  };
}

function promptSourceForDetection(
  detection: OntologyDetection,
  overrides?: OntologyOverrides,
): PromptDetectionSource {
  if (detection.source === "user") {
    return "user_defined";
  }

  const override = (overrides?.detections ?? []).find(
    (candidate) => candidate.detectionId === detection.id,
  );

  if (
    override &&
    !override.rejected &&
    (override.canonicalName !== undefined ||
      override.kind !== undefined ||
      override.joinKey !== undefined)
  ) {
    return "user_override";
  }

  return "detected";
}

function preferredLabel(labels: Array<{ language: string; value: string }>): string {
  return labels.find((label) => label.language.toLowerCase().startsWith("en"))?.value ?? labels[0]?.value ?? "";
}

function isReviewed(status: string): boolean {
  return status === "reviewed" || status === "published";
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return [...left].sort().join("\u0000") === [...right].sort().join("\u0000");
}

function increment(
  counts: Partial<Record<OntologyPromptOmissionReason, number>>,
  reason: OntologyPromptOmissionReason,
): void {
  counts[reason] = (counts[reason] ?? 0) + 1;
}

function serializedChars(value: unknown): number {
  return JSON.stringify(value).length;
}

function estimatedTokens(chars: number): number {
  return Math.ceil(chars / 4);
}

function stableEntityCompare(left: unknown, right: unknown): number {
  return JSON.stringify(left).localeCompare(JSON.stringify(right));
}

function bindingPriorityCompare(left: ApprovedBinding, right: ApprovedBinding): number {
  const priority = (item: ApprovedBinding) =>
    item.bindingMethod === "publication_override" ? 0 : item.joinKey || item.temporal ? 1 : 2;
  return priority(left) - priority(right) || left.occurrenceId.localeCompare(right.occurrenceId);
}

function sortLegacySectionsForBudget(sections: unknown[]): unknown[] {
  return sections.map((section) => {
    if (!section || typeof section !== "object") return section;
    const copy = structuredClone(section) as Record<string, unknown>;
    for (const key of ["rejectedDetections", "avoidBroadAliases", "activeDetections", "joinCandidates", "deterministicRawDetections"]) {
      const values = copy[key];
      if (Array.isArray(values)) values.sort(stableEntityCompare);
    }
    return copy;
  }).sort(stableEntityCompare);
}

function dedupeByJson<T>(values: T[]): T[] {
  return [...new Map(values.map((value) => [JSON.stringify(value), value])).values()];
}
