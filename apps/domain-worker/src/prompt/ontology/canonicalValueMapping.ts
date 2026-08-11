/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import {
  CANONICAL_VALUE_NORMALIZATION_VERSION,
  exactCanonicalValueText,
  normalizeCanonicalValue,
} from "./valueNormalization.js";

export const CANONICAL_VALUE_MAPPER_ID =
  "deterministic_canonical_value_mapper" as const;
export const CANONICAL_VALUE_MAPPER_VERSION = "1.0.0" as const;

export type ValueSchemeReference = {
  valueSchemeId: string;
  valueSchemeVersion: string;
};

export type MappingCanonicalValue = {
  id: string;
  version: string;
  valueScheme: ValueSchemeReference;
  code: string;
  preferredLabels: Array<{ language: string; value: string }>;
  alternativeLabels?: Array<{ language: string; value: string }>;
  hiddenLabels?: Array<{ language: string; value: string }>;
  /** Explicit category semantics used by total/member hard-negative checks. */
  valueRole?: "member" | "total";
  /** Explicit demographic semantics; protected labels require this metadata. */
  demographicRole?: "male" | "female" | "other";
  validFrom?: string;
  validTo?: string;
  status: "active" | "deprecated";
};

export type MappingRepresentedVariable = {
  id: string;
  valueScheme?: ValueSchemeReference;
};

export type ApprovedValueDictionary = {
  id: string;
  version: string;
  publicationId: string;
  representedVariableId: string;
  valueScheme: ValueSchemeReference;
  language: string;
  validFrom?: string;
  validTo?: string;
  reviewStatus: "approved";
  source: string;
  entries: Array<{
    canonicalValueId: string;
    publisherCodes?: string[];
    aliases?: string[];
    validFrom?: string;
    validTo?: string;
  }>;
};

export type CanonicalValueMappingContext = {
  profileId: string;
  representedVariables: MappingRepresentedVariable[];
  canonicalValues: MappingCanonicalValue[];
  approvedDictionaries: ApprovedValueDictionary[];
};

export type CanonicalValueMappingRequest = {
  publicationId: string;
  representedVariableId: string;
  valueScheme: ValueSchemeReference;
  rawValue: string;
  rawLanguage?: string;
  /** An explicitly supplied publisher code; rawValue is also tested as a code. */
  publisherCode?: string;
  /** Historical effective date in ISO YYYY-MM-DD form. */
  validAt?: string;
  provenance: {
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
    sourceUrl?: string;
  };
};

export type RawValueMapping = {
  id: string;
  publicationId: string;
  representedVariableId: string;
  valueScheme: ValueSchemeReference;
  rawValue: string;
  /** Original explicit publisher code, retained separately from the display value. */
  publisherCode?: string;
  rawLanguage?: string;
  normalizedValue: string;
  effectiveAt?: string;
  normalizationMethod: "publisher_code" | "approved_dictionary" | "rule";
  normalizationMethodVersion: string;
  canonicalValueId?: string;
  relation: "exact" | "alias" | "unmapped";
  confidence: number;
  evidence: string[];
  reviewStatus: "automatic" | "abstained";
  provenance: CanonicalValueMappingRequest["provenance"];
};

export type CanonicalValueMappingOutcome = {
  mapping: RawValueMapping;
  candidates: string[];
  collision: boolean;
};

type Candidate = {
  value: MappingCanonicalValue;
  relation: "exact" | "alias";
  method: RawValueMapping["normalizationMethod"];
  evidence: string;
};

export function mapCanonicalValue(
  context: CanonicalValueMappingContext,
  request: CanonicalValueMappingRequest,
): CanonicalValueMappingOutcome {
  const normalized = normalizeCanonicalValue(request.rawValue);
  const baseEvidence = [
    `${CANONICAL_VALUE_MAPPER_ID}@${CANONICAL_VALUE_MAPPER_VERSION}`,
    `normalization.${CANONICAL_VALUE_NORMALIZATION_VERSION}`,
    `value_scheme.${request.valueScheme.valueSchemeId}@${request.valueScheme.valueSchemeVersion}`,
  ];
  const rejected = (reason: string): CanonicalValueMappingOutcome => ({
    mapping: abstainedMapping(request, normalized.value, [
      ...baseEvidence,
      reason,
    ]),
    candidates: [],
    collision: false,
  });

  if (!request.rawValue.normalize("NFKC").trim())
    return rejected("mapping.empty_raw_value");
  if (request.rawLanguage && !isLanguageTag(request.rawLanguage))
    return rejected("mapping.invalid_raw_language");
  if (request.validAt && !isIsoDate(request.validAt))
    return rejected("mapping.invalid_effective_date");
  if (request.publicationId !== context.profileId)
    return rejected("mapping.profile_mismatch");
  const variable = context.representedVariables.find(
    (candidate) => candidate.id === request.representedVariableId,
  );
  if (!variable) return rejected("mapping.unknown_represented_variable");
  if (
    !variable.valueScheme ||
    !sameScheme(variable.valueScheme, request.valueScheme)
  ) {
    return rejected("mapping.represented_variable_scheme_mismatch");
  }
  const language = request.rawLanguage;
  const values = context.canonicalValues.filter(
    (value) =>
      sameScheme(value.valueScheme, request.valueScheme) &&
      isValidFor(value, request.validAt),
  );
  if (!values.length)
    return rejected("mapping.no_valid_canonical_values_for_scheme_version");

  const dictionaries = language
    ? context.approvedDictionaries.filter(
        (dictionary) =>
          dictionary.reviewStatus === "approved" &&
          dictionary.publicationId === request.publicationId &&
          dictionary.representedVariableId === request.representedVariableId &&
          sameScheme(dictionary.valueScheme, request.valueScheme) &&
          sameLanguage(dictionary.language, language) &&
          isValidityWindowApplicable(dictionary, request.validAt),
      )
    : [];
  const rawExact = exactCanonicalValueText(request.rawValue);
  const explicitPublisherCode = publisherCodeKey(request.publisherCode);
  const publisherCodes = [explicitPublisherCode, rawExact].filter(
    (value): value is string => Boolean(value),
  );

  const publisherMatches = uniqueCandidates(
    dictionaries.flatMap((dictionary) =>
      applicableDictionaryEntries(dictionary, request.validAt).flatMap(
        (entry) =>
          (entry.publisherCodes ?? [])
            .filter((code) =>
              publisherCodes.includes(exactCanonicalValueText(code)),
            )
            .flatMap(() =>
              candidateFor(
                values,
                entry.canonicalValueId,
                "exact",
                "publisher_code",
                `publisher_code.${dictionary.id}@${dictionary.version}`,
              ),
            ),
      ),
    ),
  );
  const publisherOutcome = resolvedOutcome(
    request,
    normalized.value,
    publisherMatches,
    baseEvidence,
  );
  if (publisherOutcome) return publisherOutcome;

  const canonicalIdentifierMatches = uniqueCandidates([
    ...values.flatMap((value) =>
      rawExact === value.id
        ? [
            candidate(
              value,
              "exact",
              "approved_dictionary",
              "canonical_id.exact",
            ),
          ]
        : [],
    ),
    ...values.flatMap((value) =>
      rawExact === exactCanonicalValueText(value.code)
        ? [
            candidate(
              value,
              "exact",
              "approved_dictionary",
              "canonical_code.exact",
            ),
          ]
        : [],
    ),
  ]);
  const canonicalIdentifierOutcome = resolvedOutcome(
    request,
    normalized.value,
    canonicalIdentifierMatches,
    baseEvidence,
  );
  if (canonicalIdentifierOutcome) return canonicalIdentifierOutcome;

  const directLabels = uniqueCandidates([
    ...values.flatMap((value) =>
      labelsFor(value, language).flatMap((label) =>
        rawExact === exactCanonicalValueText(label.value)
          ? [
              candidate(
                value,
                label.kind === "preferred" ? "exact" : "alias",
                "approved_dictionary",
                `canonical_label.${label.kind}`,
              ),
            ]
          : [],
      ),
    ),
    ...dictionaries.flatMap((dictionary) =>
      applicableDictionaryEntries(dictionary, request.validAt).flatMap(
        (entry) =>
          (entry.aliases ?? []).flatMap((alias) =>
            rawExact === exactCanonicalValueText(alias)
              ? candidateFor(
                  values,
                  entry.canonicalValueId,
                  "alias",
                  "approved_dictionary",
                  `dictionary.${dictionary.id}@${dictionary.version}`,
                )
              : [],
          ),
      ),
    ),
  ]);
  const directLabelOutcome = resolvedOutcome(
    request,
    normalized.value,
    directLabels,
    baseEvidence,
  );
  if (directLabelOutcome) return directLabelOutcome;

  const normalizedMatches = uniqueCandidates([
    ...values.flatMap((value) =>
      labelsFor(value, language).flatMap((label) =>
        normalizeCanonicalValue(label.value).value === normalized.value
          ? [
              candidate(
                value,
                "alias",
                "rule",
                `normalized_canonical_label.${label.kind}`,
              ),
            ]
          : [],
      ),
    ),
    ...dictionaries.flatMap((dictionary) =>
      applicableDictionaryEntries(dictionary, request.validAt).flatMap(
        (entry) =>
          (entry.aliases ?? []).flatMap((alias) =>
            normalizeCanonicalValue(alias).value === normalized.value
              ? candidateFor(
                  values,
                  entry.canonicalValueId,
                  "alias",
                  "rule",
                  `normalized_dictionary.${dictionary.id}@${dictionary.version}`,
                )
              : [],
          ),
      ),
    ),
  ]);
  const normalizedOutcome = resolvedOutcome(
    request,
    normalized.value,
    normalizedMatches,
    baseEvidence,
  );
  if (normalizedOutcome) return normalizedOutcome;

  return rejected("mapping.no_collision_free_deterministic_match");
}

function resolvedOutcome(
  request: CanonicalValueMappingRequest,
  normalizedValue: string,
  candidates: Candidate[],
  baseEvidence: string[],
): CanonicalValueMappingOutcome | undefined {
  if (!candidates.length) return undefined;
  const ids = [
    ...new Set(candidates.map((candidate) => candidate.value.id)),
  ].sort();
  const protectedSourceValues = [
    normalizedValue,
    ...(request.publisherCode
      ? [normalizeCanonicalValue(request.publisherCode).value]
      : []),
  ];
  const unsafeCandidates = candidates
    .map((candidate) => ({
      candidate,
      reason: protectedHardNegativeReason(
        protectedSourceValues,
        candidate.value,
      ),
    }))
    .filter((entry): entry is { candidate: Candidate; reason: string } =>
      Boolean(entry.reason),
    );
  if (unsafeCandidates.length) {
    return {
      mapping: abstainedMapping(request, normalizedValue, [
        ...baseEvidence,
        "mapping.protected_hard_negative",
        ...unsafeCandidates
          .map(({ candidate, reason }) => `${reason}.${candidate.value.id}`)
          .sort(),
        ...(ids.length > 1 ? ["mapping.safe_unsafe_candidate_collision"] : []),
      ]),
      candidates: ids,
      collision: ids.length > 1,
    };
  }
  if (ids.length !== 1) {
    return {
      mapping: abstainedMapping(request, normalizedValue, [
        ...baseEvidence,
        "mapping.normalization_collision",
        ...ids.map((id) => `candidate.${id}`),
      ]),
      candidates: ids,
      collision: true,
    };
  }
  const selected = candidates.sort(compareCandidates)[0];
  return {
    mapping: {
      id: mappingIdFor(request),
      publicationId: request.publicationId,
      representedVariableId: request.representedVariableId,
      valueScheme: request.valueScheme,
      rawValue: request.rawValue,
      ...(request.publisherCode && publisherCodeKey(request.publisherCode)
        ? { publisherCode: request.publisherCode }
        : {}),
      ...(request.rawLanguage && isLanguageTag(request.rawLanguage)
        ? { rawLanguage: request.rawLanguage }
        : {}),
      normalizedValue,
      ...(request.validAt && isIsoDate(request.validAt)
        ? { effectiveAt: request.validAt }
        : {}),
      normalizationMethod: selected.method,
      normalizationMethodVersion:
        selected.method === "rule"
          ? CANONICAL_VALUE_NORMALIZATION_VERSION
          : CANONICAL_VALUE_MAPPER_VERSION,
      canonicalValueId: selected.value.id,
      relation: selected.relation,
      confidence:
        selected.method === "publisher_code"
          ? 1
          : selected.method === "approved_dictionary"
            ? 0.999
            : 0.998,
      evidence: [...baseEvidence, selected.evidence],
      reviewStatus: "automatic",
      provenance: request.provenance,
    },
    candidates: ids,
    collision: false,
  };
}

function abstainedMapping(
  request: CanonicalValueMappingRequest,
  normalizedValue: string,
  evidence: string[],
): RawValueMapping {
  return {
    id: mappingIdFor(request),
    publicationId: request.publicationId,
    representedVariableId: request.representedVariableId,
    valueScheme: request.valueScheme,
    rawValue: request.rawValue,
    ...(request.publisherCode && publisherCodeKey(request.publisherCode)
      ? { publisherCode: request.publisherCode }
      : {}),
    ...(request.rawLanguage && isLanguageTag(request.rawLanguage)
      ? { rawLanguage: request.rawLanguage }
      : {}),
    normalizedValue,
    ...(request.validAt && isIsoDate(request.validAt)
      ? { effectiveAt: request.validAt }
      : {}),
    normalizationMethod: "rule",
    normalizationMethodVersion: CANONICAL_VALUE_NORMALIZATION_VERSION,
    relation: "unmapped",
    confidence: 0,
    evidence,
    reviewStatus: "abstained",
    provenance: request.provenance,
  };
}

function labelsFor(
  value: MappingCanonicalValue,
  language: string | undefined,
): Array<{ kind: "preferred" | "alternative" | "hidden"; value: string }> {
  if (!language) return [];
  return [
    ...value.preferredLabels.map((label) => ({
      ...label,
      kind: "preferred" as const,
    })),
    ...(value.alternativeLabels ?? []).map((label) => ({
      ...label,
      kind: "alternative" as const,
    })),
    ...(value.hiddenLabels ?? []).map((label) => ({
      ...label,
      kind: "hidden" as const,
    })),
  ].filter((label) => sameLanguage(label.language, language));
}

function candidate(
  value: MappingCanonicalValue,
  relation: Candidate["relation"],
  method: Candidate["method"],
  evidence: string,
): Candidate {
  return { value, relation, method, evidence };
}
function candidateFor(
  values: MappingCanonicalValue[],
  id: string,
  relation: Candidate["relation"],
  method: Candidate["method"],
  evidence: string,
): Candidate[] {
  return values
    .filter((value) => value.id === id)
    .map((value) => candidate(value, relation, method, evidence));
}
function uniqueCandidates(candidates: Candidate[]): Candidate[] {
  const byKey = new Map<string, Candidate>();
  for (const entry of candidates) {
    const key = `${entry.value.id}\u001f${entry.relation}\u001f${entry.method}\u001f${entry.evidence}`;
    if (!byKey.has(key)) byKey.set(key, entry);
  }
  return [...byKey.values()].sort(compareCandidates);
}
function compareCandidates(left: Candidate, right: Candidate): number {
  const relationRank = (relation: Candidate["relation"]) =>
    relation === "exact" ? 0 : 1;
  const methodRank = (method: Candidate["method"]) =>
    method === "publisher_code" ? 0 : method === "approved_dictionary" ? 1 : 2;
  return (
    [
      left.value.id.localeCompare(right.value.id),
      relationRank(left.relation) - relationRank(right.relation),
      methodRank(left.method) - methodRank(right.method),
      left.evidence.localeCompare(right.evidence),
    ].find((comparison) => comparison !== 0) ?? 0
  );
}
function sameScheme(
  left: ValueSchemeReference,
  right: ValueSchemeReference,
): boolean {
  return (
    left.valueSchemeId === right.valueSchemeId &&
    left.valueSchemeVersion === right.valueSchemeVersion
  );
}
function sameLanguage(left: string, right: string): boolean {
  return left.toLowerCase() === right.toLowerCase();
}
function isLanguageTag(value: string): boolean {
  return /^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(value);
}
function isIsoDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}
function isValidFor(
  value: MappingCanonicalValue,
  validAt: string | undefined,
): boolean {
  const bounded = Boolean(value.validFrom || value.validTo);
  if (value.status === "deprecated") {
    // Undated deprecated definitions cannot be placed safely in history.
    if (!validAt || !bounded) return false;
    return isValidityWindowApplicable(value, validAt);
  }
  if (bounded)
    return Boolean(validAt) && isValidityWindowApplicable(value, validAt);
  return true;
}

function isValidityWindowApplicable(
  value: { validFrom?: string; validTo?: string },
  validAt: string | undefined,
): boolean {
  if (!value.validFrom && !value.validTo) return true;
  if (!validAt) return false;
  return (
    (!value.validFrom || value.validFrom <= validAt) &&
    (!value.validTo || value.validTo >= validAt)
  );
}

function applicableDictionaryEntries(
  dictionary: ApprovedValueDictionary,
  validAt: string | undefined,
): ApprovedValueDictionary["entries"] {
  return dictionary.entries.filter((entry) =>
    isValidityWindowApplicable(entry, validAt),
  );
}

function protectedHardNegativeReason(
  normalizedSourceValues: string[],
  target: MappingCanonicalValue,
): string | undefined {
  if (
    normalizedSourceValues.some((value) =>
      new Set(["men", "boys", "persons"]).has(value),
    ) &&
    target.demographicRole !== "other"
  ) {
    return "mapping.people_label_requires_explicit_non_male_target";
  }
  if (
    normalizedSourceValues.some((value) =>
      new Set(["total", "totals"]).has(value),
    ) &&
    target.valueRole !== "total"
  ) {
    return "mapping.total_cannot_alias_member_or_unknown_role";
  }
  return undefined;
}
function publisherCodeKey(value: string | undefined): string {
  return value ? exactCanonicalValueText(value) : "";
}

function mappingIdFor(request: CanonicalValueMappingRequest): string {
  const text = [
    request.publicationId,
    request.representedVariableId,
    request.valueScheme.valueSchemeId,
    request.valueScheme.valueSchemeVersion,
    request.rawLanguage ?? "",
    request.validAt ?? "",
    publisherCodeKey(request.publisherCode),
    request.rawValue,
  ].join("\u001f");
  let hash = 2166136261;
  for (const char of text) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  return `raw_mapping_${(hash >>> 0).toString(36).padStart(8, "0")}`;
}

export type CanonicalValueMappingEvaluationCase = {
  id: string;
  publicationId?: string;
  editionId?: string;
  split: "tuning" | "publication_holdout" | "temporal_holdout";
  request: CanonicalValueMappingRequest;
  context?: CanonicalValueMappingContext;
  expectedCanonicalValueId?: string;
  expectedRelation: RawValueMapping["relation"];
  expectedGoldRelation?:
    | "exact"
    | "alias"
    | "close"
    | "broader"
    | "narrower"
    | "unmapped";
};
export type CanonicalValueMappingEvidence = {
  source: string;
  autoEligibleMappingDecisionCount: number;
  hardNegativeCount: number;
  sufficient: boolean;
  missing: string[];
};
export type CanonicalValueMappingReport = {
  reportVersion: "1.0";
  mapper: {
    id: typeof CANONICAL_VALUE_MAPPER_ID;
    version: typeof CANONICAL_VALUE_MAPPER_VERSION;
  };
  counts: { automatic: number; abstained: number; collisions: number };
  evidence: CanonicalValueMappingEvidence;
  heldOutAutomaticMergePrecision: {
    correct: number;
    total: number;
    value: number | null;
  };
  promotion: {
    status: "eligible_for_promotion" | "review_only" | "insufficient_evidence";
    threshold: 0.995;
    oneSided95LowerBound: number | null;
    reasons: string[];
  };
  mappings: Array<{
    id: string;
    publicationId?: string;
    editionId?: string;
    split: CanonicalValueMappingEvaluationCase["split"];
    publisherCode?: string;
    canonicalValueId?: string;
    relation: RawValueMapping["relation"];
    expectedRelation: RawValueMapping["relation"];
    expectedGoldRelation:
      | "exact"
      | "alias"
      | "close"
      | "broader"
      | "narrower"
      | "unmapped";
    expectedCanonicalValueId?: string;
    reviewStatus: RawValueMapping["reviewStatus"];
    confidence: number;
    correct: boolean;
    recoveredGoldMapping: boolean;
    collision: boolean;
  }>;
};

/**
 * Deterministic mapping report. Evidence is explicit because PRD 002 remains
 * the authority for publication/edition-held-out promotion eligibility.
 */
export function reportCanonicalValueMappings(
  context: CanonicalValueMappingContext,
  cases: CanonicalValueMappingEvaluationCase[],
  evidence: CanonicalValueMappingEvidence = {
    source: "local mapping cases",
    autoEligibleMappingDecisionCount: cases.length,
    hardNegativeCount: cases.filter(
      (entry) => entry.expectedRelation === "unmapped",
    ).length,
    sufficient: false,
    missing: [
      "PRD 002 publication/edition-held-out evidence floor was not supplied",
    ],
  },
): CanonicalValueMappingReport {
  const results = cases.map((entry) => ({
    entry,
    outcome: mapCanonicalValue(entry.context ?? context, entry.request),
  }));
  const heldOut = results.filter(
    ({ entry, outcome }) =>
      entry.split !== "tuning" && outcome.mapping.reviewStatus === "automatic",
  );
  const correct = heldOut.filter(
    ({ entry, outcome }) =>
      outcome.mapping.canonicalValueId === entry.expectedCanonicalValueId &&
      evaluationRelationsCompatible(
        entry.expectedGoldRelation ?? entry.expectedRelation,
        outcome.mapping.relation,
      ),
  ).length;
  const precision = heldOut.length ? correct / heldOut.length : null;
  const lower = heldOut.length
    ? oneSidedExactBinomialLowerBound(correct, heldOut.length)
    : null;
  const reasons = evidence.sufficient
    ? [
        ...(precision === null
          ? ["No automatic held-out mappings were evaluated."]
          : []),
        ...(precision !== null && precision < 0.995
          ? ["Observed automatic-merge precision is below 99.5%."]
          : []),
        ...(lower !== null && lower < 0.995
          ? ["One-sided 95% exact-binomial lower bound is below 99.5%."]
          : []),
      ]
    : [...evidence.missing].sort();
  const status = !evidence.sufficient
    ? "insufficient_evidence"
    : reasons.length
      ? "review_only"
      : "eligible_for_promotion";
  return {
    reportVersion: "1.0",
    mapper: {
      id: CANONICAL_VALUE_MAPPER_ID,
      version: CANONICAL_VALUE_MAPPER_VERSION,
    },
    counts: {
      automatic: results.filter(
        ({ outcome }) => outcome.mapping.reviewStatus === "automatic",
      ).length,
      abstained: results.filter(
        ({ outcome }) => outcome.mapping.reviewStatus === "abstained",
      ).length,
      collisions: results.filter(({ outcome }) => outcome.collision).length,
    },
    evidence: { ...evidence, missing: [...evidence.missing].sort() },
    heldOutAutomaticMergePrecision: {
      correct,
      total: heldOut.length,
      value: precision,
    },
    promotion: {
      status,
      threshold: 0.995,
      oneSided95LowerBound: lower,
      reasons: reasons.length ? reasons : ["PRD 002 promotion criteria met."],
    },
    mappings: results
      .map(({ entry, outcome }) => ({
        id: entry.id,
        publicationId: entry.publicationId,
        editionId: entry.editionId,
        split: entry.split,
        publisherCode: outcome.mapping.publisherCode,
        canonicalValueId: outcome.mapping.canonicalValueId,
        relation: outcome.mapping.relation,
        expectedRelation: entry.expectedRelation,
        expectedGoldRelation:
          entry.expectedGoldRelation ?? entry.expectedRelation,
        expectedCanonicalValueId: entry.expectedCanonicalValueId,
        reviewStatus: outcome.mapping.reviewStatus,
        confidence: outcome.mapping.confidence,
        correct:
          entry.expectedRelation === "unmapped"
            ? outcome.mapping.reviewStatus === "abstained" &&
              outcome.mapping.relation === "unmapped"
            : outcome.mapping.canonicalValueId ===
                entry.expectedCanonicalValueId &&
              evaluationRelationsCompatible(
                entry.expectedGoldRelation ?? entry.expectedRelation,
                outcome.mapping.relation,
              ),
        recoveredGoldMapping:
          outcome.mapping.reviewStatus === "automatic" &&
          outcome.mapping.canonicalValueId === entry.expectedCanonicalValueId &&
          evaluationRelationsCompatible(
            entry.expectedGoldRelation ?? entry.expectedRelation,
            outcome.mapping.relation,
          ),
        collision: outcome.collision,
      }))
      .sort((left, right) => left.id.localeCompare(right.id)),
  };
}

function evaluationRelationsCompatible(
  expected: CanonicalValueMappingEvaluationCase["expectedGoldRelation"],
  observed: RawValueMapping["relation"],
): boolean {
  return (
    (expected === "exact" || expected === "alias") &&
    (observed === "exact" || observed === "alias")
  );
}

export function stableCanonicalValueMappingJson(
  report: CanonicalValueMappingReport,
): string {
  return `${JSON.stringify(sortObjectKeys(report), null, 2)}\n`;
}

export function canonicalValueMappingMarkdown(
  report: CanonicalValueMappingReport,
): string {
  const precision = report.heldOutAutomaticMergePrecision.value;
  return [
    "# Deterministic Canonical-Value Mapping Baseline",
    "",
    `Mapper: ${report.mapper.id} ${report.mapper.version}`,
    `- Automatic mappings: ${report.counts.automatic}`,
    `- Abstained mappings: ${report.counts.abstained}`,
    `- Normalization collisions: ${report.counts.collisions}`,
    `- PRD 002 evidence source: ${report.evidence.source}`,
    `- Evidence: ${report.evidence.autoEligibleMappingDecisionCount} auto-eligible decisions; ${report.evidence.hardNegativeCount} hard negatives; ${report.evidence.sufficient ? "sufficient" : "insufficient_evidence"}.`,
    `- Held-out automatic-merge precision: ${report.heldOutAutomaticMergePrecision.correct}/${report.heldOutAutomaticMergePrecision.total} (${precision === null ? "n/a" : `${(precision * 100).toFixed(3)}%`})`,
    `- One-sided 95% exact-binomial lower bound: ${report.promotion.oneSided95LowerBound === null ? "n/a" : `${(report.promotion.oneSided95LowerBound * 100).toFixed(3)}%`}`,
    "- Required promotion threshold: 99.500% observed precision and lower bound.",
    `- Promotion status: **${report.promotion.status}** (${report.promotion.reasons.join("; ")}).`,
    "",
  ].join("\n");
}

export function oneSidedExactBinomialLowerBound(
  successes: number,
  trials: number,
  alpha = 0.05,
): number {
  if (
    !Number.isInteger(successes) ||
    !Number.isInteger(trials) ||
    successes < 0 ||
    trials < successes ||
    !(alpha > 0 && alpha < 1)
  ) {
    throw new Error("Invalid binomial confidence interval arguments.");
  }
  if (successes === 0) return 0;
  if (successes === trials) return Math.pow(alpha, 1 / trials);
  let lower = 0;
  let upper = 1;
  for (let iteration = 0; iteration < 100; iteration += 1) {
    const midpoint = (lower + upper) / 2;
    if (regularizedBeta(midpoint, successes, trials - successes + 1) > alpha)
      upper = midpoint;
    else lower = midpoint;
  }
  return (lower + upper) / 2;
}

function regularizedBeta(x: number, a: number, b: number): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const front = Math.exp(a * Math.log(x) + b * Math.log1p(-x) - logBeta(a, b));
  return x < (a + 1) / (a + b + 2)
    ? (front * betaFraction(x, a, b)) / a
    : 1 - (front * betaFraction(1 - x, b, a)) / b;
}
function logBeta(a: number, b: number): number {
  return logGamma(a) + logGamma(b) - logGamma(a + b);
}
function logGamma(value: number): number {
  const coefficients = [
    Number("76.18009172947146"),
    Number("-86.50532032941677"),
    24.01409824083091,
    -1.231739572450155,
    0.001208650973866179,
    -0.000005395239384953,
  ];
  let x = value - 1;
  const tmp = x + 5.5 - (x + 0.5) * Math.log(x + 5.5);
  let series = Number("1.000000000190015");
  for (const coefficient of coefficients) {
    x += 1;
    series += coefficient / x;
  }
  return -tmp + Math.log(Number("2.5066282746310005") * series);
}
function betaFraction(x: number, a: number, b: number): number {
  const epsilon = 3e-14;
  const minimum = 1e-300;
  let c = 1;
  let d = 1 - ((a + b) * x) / (a + 1);
  d = Math.abs(d) < minimum ? minimum : d;
  d = 1 / d;
  let h = d;
  for (let m = 1; m <= 200; m += 1) {
    const m2 = 2 * m;
    let aa = (m * (b - m) * x) / ((a + m2 - 1) * (a + m2));
    d = 1 + aa * d;
    d = Math.abs(d) < minimum ? minimum : d;
    c = 1 + aa / c;
    c = Math.abs(c) < minimum ? minimum : c;
    d = 1 / d;
    h *= d * c;
    aa = (-(a + m) * (a + b + m) * x) / ((a + m2) * (a + m2 + 1));
    d = 1 + aa * d;
    d = Math.abs(d) < minimum ? minimum : d;
    c = 1 + aa / c;
    c = Math.abs(c) < minimum ? minimum : c;
    d = 1 / d;
    const delta = d * c;
    h *= delta;
    if (Math.abs(delta - 1) < epsilon) break;
  }
  return h;
}

function sortObjectKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortObjectKeys);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, child]) => [key, sortObjectKeys(child)]),
    );
  return value;
}
