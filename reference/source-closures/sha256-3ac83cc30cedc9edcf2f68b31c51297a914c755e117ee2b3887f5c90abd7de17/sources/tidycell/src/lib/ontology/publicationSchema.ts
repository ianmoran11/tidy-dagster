import { z } from "zod";
import {
  isPublicationEntityId,
  type PublicationEntityId,
  type PublicationIdPrefix,
} from "./publicationIds";
import { createOccurrenceStructuralSignature } from "./occurrences";
import {
  isActiveHierarchyEdge,
  isValidIsoDate,
  validateTypedHierarchy,
} from "./hierarchy";

export const PUBLICATION_ONTOLOGY_ARTIFACT_VERSION = "0.2" as const;

export const PUBLICATION_ONTOLOGY_VERSIONING_RULES = [
  "The artifact version selects this strict JSON schema; a newer artifact version requires a new validator.",
  "Each artifact is one validated snapshot; stable entity IDs persist across snapshots while mutable semantic definitions carry explicit versions.",
  "Embedded mappings, edges, decisions, and supersession records inherit the containing artifact or entity version and retain their own method, review, and provenance metadata.",
  "Unknown data is allowed only in the explicit extensions object so current-version validation remains strict.",
  "A later artifact version may add a new extension namespace or a new schema version, but may not silently reinterpret current fields.",
] as const;

const SEMVER_PATTERN = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?Z$/;
const GENERIC_ID_PATTERN = /^[a-z][a-z0-9_]*_[a-z0-9]{8,32}$/;
const CONCEPT_SCHEME_ID_PATTERN = /^concept_scheme_[a-z0-9]{8,32}$/;

const extensionsSchema = z.record(z.string().min(1), z.unknown());
const semanticVersionSchema = z.string().regex(SEMVER_PATTERN, "Expected semantic version.");
const isoDateSchema = z.string()
  .regex(ISO_DATE_PATTERN, "Expected ISO date (YYYY-MM-DD).")
  .refine(isValidIsoDate, "Expected a real ISO calendar date.");
const isoDateTimeSchema = z
  .string()
  .regex(ISO_DATETIME_PATTERN, "Expected UTC ISO datetime.");
const genericIdSchema = z.string().regex(GENERIC_ID_PATTERN, "Expected stable typed ID.");
export const ExternalConceptSchemeIdSchema = z
  .string()
  .regex(CONCEPT_SCHEME_ID_PATTERN, "Expected stable external concept-scheme ID.");

function entityIdSchema(prefix: PublicationIdPrefix) {
  return z
    .string()
    .refine((value) => isPublicationEntityId(value, prefix), `Expected stable ${prefix} ID.`);
}

const ontologyOwnerIdSchema = z.union([
  ExternalConceptSchemeIdSchema,
  entityIdSchema("publisher"),
  entityIdSchema("publication"),
]);

const entityStatusSchema = z.enum(["draft", "reviewed", "published", "deprecated"]);
const reviewStatusSchema = z.enum(["automatic", "proposed", "approved", "rejected", "abstained"]);

/** Canonical orthogonal axes used by represented variables and PRD 005 classification. */
export const COMPONENT_ROLES = ["dimension", "measure", "attribute", "identifier"] as const;
export const SEMANTIC_DOMAINS = [
  "temporal",
  "geographic",
  "demographic",
  "classification",
  "administrative",
  "economic",
  "other",
] as const;
export const REPRESENTATIONS = [
  "string",
  "integer",
  "decimal",
  "boolean",
  "date",
  "datetime",
  "interval",
  "code",
] as const;
export const VALUE_BEHAVIOURS = [
  "nominal",
  "ordinal",
  "hierarchical",
  "temporal",
  "geographic",
  "continuous",
  "discrete",
] as const;
export const MEASURE_TYPES = [
  "count",
  "amount_currency",
  "percent",
  "rate",
  "ratio",
  "index",
  "mean",
  "median",
  "stock",
  "flow",
  "not_applicable",
] as const;
export const AGGREGATION_RULES = ["sum", "weighted_mean", "non_additive", "last_value", "unknown"] as const;
export const OBSERVATION_STATUS_ROLES = ["none", "attribute", "flag", "suppression", "quality"] as const;

export type ComponentRole = (typeof COMPONENT_ROLES)[number];
export type SemanticDomain = (typeof SEMANTIC_DOMAINS)[number];
export type Representation = (typeof REPRESENTATIONS)[number];
export type ValueBehaviour = (typeof VALUE_BEHAVIOURS)[number];
export type MeasureType = (typeof MEASURE_TYPES)[number];
export type AggregationRule = (typeof AGGREGATION_RULES)[number];
export type ObservationStatusRole = (typeof OBSERVATION_STATUS_ROLES)[number];
const mappingRelationSchema = z.enum([
  "exact",
  "alias",
  "close",
  "broader",
  "narrower",
  "unmapped",
]);
const crosswalkRelationSchema = z.enum(["exact", "close", "broader", "narrower"]);

export const LocalizedLabelSchema = z.strictObject({
  language: z.string().regex(/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/, "Expected BCP-47 language tag."),
  value: z.string().trim().min(1),
});

export const ProvenanceRecordSchema = z.strictObject({
  sourceType: z.enum(["publisher", "external_standard", "import", "rule", "user", "migration"]),
  sourceId: z.string().trim().min(1),
  sourceUrl: z.string().url().optional(),
  recordedAt: isoDateTimeSchema,
  evidence: z.array(z.string().trim().min(1)).min(1),
  artifactHash: z.string().trim().min(1).optional(),
  extensions: extensionsSchema.optional(),
});

const entityLifecycleSchema = {
  version: semanticVersionSchema,
  status: entityStatusSchema,
  validFrom: isoDateSchema.optional(),
  validTo: isoDateSchema.optional(),
  extensions: extensionsSchema.optional(),
};

export const ExternalConceptSchemeSchema = z.strictObject({
  id: ExternalConceptSchemeIdSchema,
  externalId: z.string().trim().min(1),
  version: semanticVersionSchema,
  status: entityStatusSchema,
  validFrom: isoDateSchema.optional(),
  validTo: isoDateSchema.optional(),
  preferredLabels: z.array(LocalizedLabelSchema).min(1),
  sourceUrl: z.string().url().optional(),
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

export const PublisherSchemeSchema = z.strictObject({
  id: entityIdSchema("publisher"),
  authority: z.string().trim().min(1),
  registryId: z.string().trim().min(1),
  version: semanticVersionSchema,
  status: entityStatusSchema,
  validFrom: isoDateSchema.optional(),
  validTo: isoDateSchema.optional(),
  preferredLabels: z.array(LocalizedLabelSchema).min(1),
  conceptSchemes: z.array(ExternalConceptSchemeSchema),
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

export const PublicationProfileSchema = z.strictObject({
  id: entityIdSchema("publication"),
  publisherId: entityIdSchema("publisher"),
  ontologyVersion: semanticVersionSchema,
  status: entityStatusSchema,
  durableIdentifiers: z.array(
    z.strictObject({
      type: z.enum(["catalogue_number", "dataflow", "doi", "registry", "publisher_native"]),
      value: z.string().trim().min(1),
    }),
  ).min(1),
  displayAliases: z.array(z.string().trim().min(1)),
  pathAliases: z.array(z.string().trim().min(1)),
  publisherSchemeIds: z.array(entityIdSchema("publisher")).min(1),
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

export const OntologyConceptSchema = z.strictObject({
  id: entityIdSchema("concept"),
  ownerSchemeId: ontologyOwnerIdSchema,
  preferredLabels: z.array(LocalizedLabelSchema).min(1),
  alternativeLabels: z.array(LocalizedLabelSchema).default([]),
  hiddenLabels: z.array(LocalizedLabelSchema).default([]),
  definition: z.string().trim().min(1).optional(),
  externalMappings: z.array(
    z.strictObject({
      schemeId: genericIdSchema,
      targetId: z.string().trim().min(1),
      relation: crosswalkRelationSchema,
    }),
  ).default([]),
  provenance: ProvenanceRecordSchema,
  ...entityLifecycleSchema,
});

export const ConceptualVariableSchema = z.strictObject({
  id: entityIdSchema("variable"),
  conceptId: entityIdSchema("concept"),
  preferredLabels: z.array(LocalizedLabelSchema).min(1),
  definition: z.string().trim().min(1).optional(),
  universe: z.string().trim().min(1).optional(),
  provenance: ProvenanceRecordSchema,
  ...entityLifecycleSchema,
});

export const ValueSchemeReferenceSchema = z.strictObject({
  valueSchemeId: entityIdSchema("value_scheme"),
  valueSchemeVersion: semanticVersionSchema,
});

export const RepresentedVariableSchema = z.strictObject({
  id: entityIdSchema("variable"),
  conceptualVariableId: entityIdSchema("variable"),
  preferredLabels: z.array(LocalizedLabelSchema).min(1),
  componentRole: z.enum(COMPONENT_ROLES),
  semanticDomain: z.enum(SEMANTIC_DOMAINS),
  representation: z.enum(REPRESENTATIONS),
  valueBehaviour: z.enum(VALUE_BEHAVIOURS),
  measureType: z.enum(MEASURE_TYPES),
  unitScale: z.string().trim().min(1).optional(),
  universe: z.string().trim().min(1).optional(),
  aggregationRule: z.enum(AGGREGATION_RULES),
  observationStatusRole: z.enum(OBSERVATION_STATUS_ROLES).default("none"),
  valueScheme: ValueSchemeReferenceSchema.optional(),
  provenance: ProvenanceRecordSchema,
  ...entityLifecycleSchema,
});

export const ValueSchemeSchema = z.strictObject({
  id: entityIdSchema("value_scheme"),
  ownerId: ontologyOwnerIdSchema,
  version: semanticVersionSchema,
  status: entityStatusSchema,
  preferredLabels: z.array(LocalizedLabelSchema).min(1),
  representation: z.enum(["code", "string", "integer", "decimal", "date", "interval"]),
  valueBehaviour: z.enum(VALUE_BEHAVIOURS),
  /** Registered calendar/fiscal semantics are authoritative for temporal roll-ups. */
  periodSchemeKind: z.enum(["calendar", "fiscal"]).optional(),
  provenance: ProvenanceRecordSchema,
  validFrom: isoDateSchema.optional(),
  validTo: isoDateSchema.optional(),
  extensions: extensionsSchema.optional(),
});

export const CanonicalValueSchema = z
  .strictObject({
    id: entityIdSchema("value"),
    version: semanticVersionSchema,
    valueScheme: ValueSchemeReferenceSchema,
    code: z.string().trim().min(1),
    preferredLabels: z.array(LocalizedLabelSchema).min(1),
    alternativeLabels: z.array(LocalizedLabelSchema).default([]),
    hiddenLabels: z.array(LocalizedLabelSchema).default([]),
    /** Explicitly distinguishes aggregate totals from ordinary scheme members. */
    valueRole: z.enum(["member", "total"]).optional(),
    /** Supports conservative demographic hard-negative checks across locales. */
    demographicRole: z.enum(["male", "female", "other"]).optional(),
    description: z.string().trim().min(1).optional(),
    validFrom: isoDateSchema.optional(),
    validTo: isoDateSchema.optional(),
    status: z.enum(["active", "deprecated"]),
    provenance: ProvenanceRecordSchema,
    extensions: extensionsSchema.optional(),
  })
  .superRefine((value, context) => {
    const labels = [
      ...value.preferredLabels.map((label) => ({ ...label, kind: "preferred" })),
      ...value.alternativeLabels.map((label) => ({ ...label, kind: "alternative" })),
      ...value.hiddenLabels.map((label) => ({ ...label, kind: "hidden" })),
    ];
    const duplicates = new Set<string>();
    for (const label of labels) {
      const key = `${label.language.toLowerCase()}\u001f${label.value.normalize("NFKC").trim().toLowerCase()}`;
      if (duplicates.has(key)) {
        context.addIssue({
          code: "custom",
          message: "Labels must not be duplicated across preferred, alternative, or hidden labels.",
        });
        return;
      }
      duplicates.add(key);
    }
  });

export const RawValueMappingSchema = z.strictObject({
  id: genericIdSchema,
  publicationId: entityIdSchema("publication"),
  representedVariableId: entityIdSchema("variable"),
  valueScheme: ValueSchemeReferenceSchema,
  // Blank and punctuation-only source cells are retained as abstentions rather
  // than silently discarded; their raw and normalized forms remain reversible.
  rawValue: z.string(),
  publisherCode: z.string().refine(
    (value) => value.normalize("NFKC").trim().length > 0,
    "Publisher code cannot be blank.",
  ).optional(),
  rawLanguage: z.string().regex(/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/).optional(),
  normalizedValue: z.string(),
  effectiveAt: isoDateSchema.optional(),
  normalizationMethod: z.enum(["publisher_code", "approved_dictionary", "rule", "fuzzy", "embedding", "llm", "user"]),
  normalizationMethodVersion: z.string().trim().min(1),
  canonicalValueId: entityIdSchema("value").optional(),
  relation: mappingRelationSchema,
  confidence: z.number().min(0).max(1),
  evidence: z.array(z.string().trim().min(1)).min(1),
  reviewStatus: reviewStatusSchema,
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

export const ValueSchemeCrosswalkEntrySchema = z.strictObject({
  id: genericIdSchema,
  sourceCanonicalValueId: entityIdSchema("value"),
  targetCanonicalValueId: entityIdSchema("value"),
  relation: crosswalkRelationSchema,
  method: z.enum(["publisher_code", "approved_dictionary", "rule", "user", "import"]),
  methodVersion: z.string().trim().min(1),
  confidence: z.number().min(0).max(1),
  evidence: z.array(z.string().trim().min(1)).min(1),
  reviewStatus: reviewStatusSchema,
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

export const ValueSchemeCrosswalkSchema = z.strictObject({
  id: genericIdSchema,
  version: semanticVersionSchema,
  sourceScheme: ValueSchemeReferenceSchema,
  targetScheme: ValueSchemeReferenceSchema,
  entries: z.array(ValueSchemeCrosswalkEntrySchema).min(1),
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

export const HierarchyEdgeSchema = z
  .strictObject({
    hierarchyId: entityIdSchema("hierarchy"),
    hierarchyVersion: semanticVersionSchema,
    sourceId: z.string().trim().min(1),
    targetId: z.string().trim().min(1),
    sourceLevelId: z.string().trim().min(1).optional(),
    targetLevelId: z.string().trim().min(1).optional(),
    relation: z.enum(["rolls_up_to", "broader_concept", "contains"]),
    aggregation: z.enum(["sum", "weighted_mean", "non_additive", "unknown"]).optional(),
    aggregationContext: z.strictObject({
      sourceValueScheme: ValueSchemeReferenceSchema,
      targetValueScheme: ValueSchemeReferenceSchema,
      sourceUniverse: z.string().trim().min(1),
      targetUniverse: z.string().trim().min(1),
      sourceAggregationRule: z.enum(["sum", "weighted_mean", "non_additive", "last_value", "unknown"]),
      targetAggregationRule: z.enum(["sum", "weighted_mean", "non_additive", "last_value", "unknown"]),
    }).optional(),
    validFrom: isoDateSchema.optional(),
    validTo: isoDateSchema.optional(),
    /** New hierarchy evidence remains explicit while old v0.2 artifacts parse safely. */
    evidence: z.array(z.string().trim().min(1)).default([]),
    confidence: z.number().min(0).max(1).default(0),
    // Legacy edges without an explicit decision remain inactive audit records.
    reviewStatus: reviewStatusSchema.default("abstained"),
    provenance: ProvenanceRecordSchema,
    extensions: extensionsSchema.optional(),
  })
  .superRefine((edge, context) => {
    if (edge.relation === "rolls_up_to") {
      if (!edge.sourceLevelId) {
        addIssue(context, ["sourceLevelId"], "Roll-up edges require a source level ID.");
      }
      if (!edge.targetLevelId) {
        addIssue(context, ["targetLevelId"], "Roll-up edges require a target level ID.");
      }
    } else if (edge.sourceLevelId || edge.targetLevelId || edge.aggregation || edge.aggregationContext) {
      addIssue(
        context,
        [],
        "Only statistical roll-up edges may name levels or aggregation semantics.",
      );
    }
    if (edge.validFrom && edge.validTo && edge.validFrom > edge.validTo) {
      addIssue(context, [], "Hierarchy edge validity interval must not end before it starts.");
    }
  });

export const HierarchySchema = z.strictObject({
  id: entityIdSchema("hierarchy"),
  version: semanticVersionSchema,
  status: entityStatusSchema,
  type: z.enum(["calendar", "fiscal", "geographic", "classification", "publication_custom"]),
  levels: z.array(
    z.strictObject({
      id: z.string().trim().min(1),
      preferredLabels: z.array(LocalizedLabelSchema).min(1),
      valueScheme: ValueSchemeReferenceSchema.optional(),
      order: z.number().int().nonnegative(),
      requiresUniqueParent: z.boolean().default(false),
    }),
  ).min(1),
  edges: z.array(HierarchyEdgeSchema),
  /** Exact calendar/fiscal scheme context prevents bare-month membership assumptions. */
  periodScheme: ValueSchemeReferenceSchema.optional(),
  periodSchemeKind: z.enum(["calendar", "fiscal"]).optional(),
  coverage: z.strictObject({
    status: z.enum(["complete", "partial"]),
    requiredMemberIds: z.array(entityIdSchema("value")).default([]),
  }).optional(),
  provenance: ProvenanceRecordSchema,
  validFrom: isoDateSchema.optional(),
  validTo: isoDateSchema.optional(),
  extensions: extensionsSchema.optional(),
});

const occurrenceSourceLocationSchema = z.strictObject({
  assetId: z.string().trim().min(1),
  sheetName: z.string().trim().min(1),
  range: z.string().trim().min(1),
  addresses: z.array(z.string().trim().min(1)).min(1),
});

const occurrenceStructuralEvidenceSchema = z.strictObject({
  tableContext: z.strictObject({
    id: z.string().trim().min(1),
    kind: z.string().trim().min(1),
    neighbouringHeaders: z.array(z.string().trim().min(1)),
  }),
  orientation: z.enum(["row", "column", "block"]),
  valueDomainFingerprint: z.string().trim().min(1),
  unitScale: z.string().trim().min(1).optional(),
  universe: z.string().trim().min(1).optional(),
  classification: ValueSchemeReferenceSchema.optional(),
  priorRepresentedVariableId: entityIdSchema("variable").optional(),
});

/** Existing PRD 001 occurrence mapping retained for v0.2 artifact compatibility. */
export const LegacyOccurrenceMappingSchema = z.strictObject({
  occurrenceId: entityIdSchema("occurrence"),
  publicationId: entityIdSchema("publication"),
  workbookEditionId: z.string().trim().min(1),
  structuralSignature: z.string().trim().min(1),
  representedVariableId: entityIdSchema("variable"),
  sourceLocation: occurrenceSourceLocationSchema,
  reviewStatus: reviewStatusSchema,
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

/** Durable, edition-scoped occurrence record used by reconciliation. */
export const DurableOccurrenceMappingSchema = z
  .strictObject({
    occurrenceId: entityIdSchema("occurrence"),
    publicationId: entityIdSchema("publication"),
    workbookEditionId: z.string().trim().min(1),
    sourceLocation: occurrenceSourceLocationSchema,
    rawDetectionIds: z.array(z.string().trim().min(1)).min(1),
    representedVariableId: entityIdSchema("variable").optional(),
    structuralSignature: z.string().regex(/^occurrence_signature_v\d+_[a-z0-9]{8,32}$/),
    structuralSignatureVersion: semanticVersionSchema,
    structuralEvidence: occurrenceStructuralEvidenceSchema,
    reviewStatus: reviewStatusSchema,
    supersedes: z.array(entityIdSchema("occurrence")).default([]),
    supersededBy: z.array(entityIdSchema("occurrence")).default([]),
    provenance: ProvenanceRecordSchema,
    extensions: extensionsSchema.optional(),
  })
  .superRefine((occurrence, context) => {
    if (new Set(occurrence.rawDetectionIds).size !== occurrence.rawDetectionIds.length) {
      addIssue(context, ["rawDetectionIds"], "Raw detection IDs must be unique within an occurrence.");
    }
    if (
      occurrence.rawDetectionIds.includes(occurrence.occurrenceId) ||
      occurrence.rawDetectionIds.some((id) => isPublicationEntityId(id, "occurrence"))
    ) {
      addIssue(
        context,
        ["rawDetectionIds"],
        "Raw detection IDs cannot use the durable occurrence ID namespace.",
      );
    }
    if (new Set(occurrence.supersedes).size !== occurrence.supersedes.length) {
      addIssue(context, ["supersedes"], "Superseded occurrence IDs must be unique.");
    }
    if (new Set(occurrence.supersededBy).size !== occurrence.supersededBy.length) {
      addIssue(context, ["supersededBy"], "Superseding occurrence IDs must be unique.");
    }
    if (occurrence.supersedes.includes(occurrence.occurrenceId)) {
      addIssue(context, ["supersedes"], "An occurrence cannot supersede itself.");
    }
    if (occurrence.supersededBy.includes(occurrence.occurrenceId)) {
      addIssue(context, ["supersededBy"], "An occurrence cannot be superseded by itself.");
    }
    if (occurrence.reviewStatus === "approved" && !occurrence.representedVariableId) {
      addIssue(context, ["representedVariableId"], "Approved occurrences require a represented-variable binding.");
    }
    if (occurrence.reviewStatus !== "approved" && occurrence.representedVariableId) {
      addIssue(context, ["representedVariableId"], "Only approved occurrences may carry a represented-variable binding.");
    }
  });

export const OccurrenceMappingSchema = z.union([
  DurableOccurrenceMappingSchema,
  LegacyOccurrenceMappingSchema,
]);

/**
 * Auditable classification/binding decision for one occurrence. This is kept
 * separate from the occurrence record so deterministic proposals never mutate
 * raw detections or confer an approval by themselves.
 */
export const OccurrenceVariableBindingSchema = z
  .strictObject({
    id: genericIdSchema,
    occurrenceId: entityIdSchema("occurrence"),
    representedVariableId: entityIdSchema("variable").optional(),
    representedVariableVersion: semanticVersionSchema.optional(),
    conceptualVariableId: entityIdSchema("variable").optional(),
    conceptId: entityIdSchema("concept").optional(),
    valueScheme: ValueSchemeReferenceSchema.optional(),
    method: z.enum([
      "deterministic_rules",
      "publication_override",
      "existing_approved_occurrence",
    ]),
    methodVersion: semanticVersionSchema,
    confidence: z.number().min(0).max(1),
    evidence: z.array(z.string().trim().min(1)).min(1),
    reviewStatus: z.enum(["proposed", "approved", "rejected", "abstained"]),
    extensions: extensionsSchema.optional(),
  })
  .superRefine((binding, context) => {
    const hasTarget = Boolean(binding.representedVariableId);
    const targetReferenceCount = [
      binding.representedVariableId,
      binding.representedVariableVersion,
      binding.conceptualVariableId,
      binding.conceptId,
    ].filter(Boolean).length;
    if ((hasTarget && targetReferenceCount !== 4) || (!hasTarget && targetReferenceCount !== 0)) {
      addIssue(
        context,
        ["representedVariableId"],
        "Bound occurrence decisions require represented-variable, conceptual-variable, concept, and version references.",
      );
    }
    if (binding.reviewStatus === "abstained" && hasTarget) {
      addIssue(context, ["representedVariableId"], "Abstained occurrence decisions cannot bind a represented variable.");
    }
    if (binding.reviewStatus !== "abstained" && !hasTarget) {
      addIssue(context, ["representedVariableId"], "Non-abstained occurrence decisions require a represented-variable binding.");
    }
    if (
      binding.reviewStatus === "approved" &&
      !["publication_override", "existing_approved_occurrence"].includes(binding.method)
    ) {
      addIssue(context, ["method"], "Only a publication override or existing approved occurrence may approve a binding.");
    }
  });

export const ReviewDecisionSchema = z.strictObject({
  id: genericIdSchema,
  entityId: z.string().trim().min(1),
  reviewStatus: z.enum(["approved", "rejected", "abstained"]),
  reviewerId: z.string().trim().min(1),
  decidedAt: isoDateTimeSchema,
  evidence: z.array(z.string().trim().min(1)).min(1),
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

export const SupersessionRecordSchema = z.strictObject({
  supersededOccurrenceId: entityIdSchema("occurrence"),
  supersedingOccurrenceId: entityIdSchema("occurrence"),
  reason: z.enum(["edition_reconciliation", "split", "merge", "retired"]),
  recordedAt: isoDateTimeSchema,
  provenance: ProvenanceRecordSchema,
  extensions: extensionsSchema.optional(),
});

const publicationOntologyBaseSchema = z.strictObject({
  version: z.literal(PUBLICATION_ONTOLOGY_ARTIFACT_VERSION),
  artifactVersion: z.literal(PUBLICATION_ONTOLOGY_ARTIFACT_VERSION),
  profile: PublicationProfileSchema,
  publisherSchemes: z.array(PublisherSchemeSchema).min(1),
  concepts: z.array(OntologyConceptSchema),
  conceptualVariables: z.array(ConceptualVariableSchema),
  representedVariables: z.array(RepresentedVariableSchema),
  valueSchemes: z.array(ValueSchemeSchema),
  canonicalValues: z.array(CanonicalValueSchema),
  rawValueMappings: z.array(RawValueMappingSchema),
  valueSchemeCrosswalks: z.array(ValueSchemeCrosswalkSchema),
  hierarchies: z.array(HierarchySchema),
  occurrenceMappings: z.array(OccurrenceMappingSchema),
  occurrenceVariableBindings: z.array(OccurrenceVariableBindingSchema).default([]),
  reviewDecisions: z.array(ReviewDecisionSchema),
  supersessionHistory: z.array(SupersessionRecordSchema),
  provenance: z.array(ProvenanceRecordSchema).min(1),
  extensions: extensionsSchema.optional(),
});

export const PublicationOntologySchema = publicationOntologyBaseSchema.superRefine(
  (artifact, context) => validatePublicationOntologyReferences(artifact, context),
);

export type PublicationOntology = z.infer<typeof PublicationOntologySchema>;
export type ValueSchemeCrosswalk = z.infer<typeof ValueSchemeCrosswalkSchema>;
export type ValueSchemeCrosswalkEntry = z.infer<typeof ValueSchemeCrosswalkEntrySchema>;
export type OccurrenceVariableBinding = z.infer<typeof OccurrenceVariableBindingSchema>;

export function parsePublicationOntology(input: unknown): PublicationOntology {
  return PublicationOntologySchema.parse(input);
}

export function safeParsePublicationOntology(input: unknown) {
  return PublicationOntologySchema.safeParse(input);
}

export function isApprovedCrosswalkEntry(entry: ValueSchemeCrosswalkEntry): boolean {
  return entry.reviewStatus === "approved";
}

/** Throws unless an approved, explicit entry establishes the requested scheme compatibility. */
export function assertApprovedValueSchemeCompatibility(
  artifact: PublicationOntology,
  sourceScheme: z.infer<typeof ValueSchemeReferenceSchema>,
  targetScheme: z.infer<typeof ValueSchemeReferenceSchema>,
  sourceCanonicalValueId: string,
  targetCanonicalValueId: string,
): ValueSchemeCrosswalkEntry {
  const matchingEntry = artifact.valueSchemeCrosswalks
    .filter(
      (crosswalk) =>
        sameScheme(crosswalk.sourceScheme, sourceScheme) &&
        sameScheme(crosswalk.targetScheme, targetScheme),
    )
    .flatMap((crosswalk) => crosswalk.entries)
    .find(
      (entry) =>
        entry.sourceCanonicalValueId === sourceCanonicalValueId &&
        entry.targetCanonicalValueId === targetCanonicalValueId &&
        isApprovedCrosswalkEntry(entry),
    );

  if (!matchingEntry) {
    throw new Error(
      "Different value schemes are compatible only through an approved, explicit value-to-value crosswalk entry.",
    );
  }

  return matchingEntry;
}

function validatePublicationOntologyReferences(
  artifact: z.infer<typeof publicationOntologyBaseSchema>,
  context: z.RefinementCtx,
): void {
  const publisherIds = new Set<string>(artifact.publisherSchemes.map((scheme) => scheme.id));
  const externalConceptSchemeIds = new Set<string>(
    artifact.publisherSchemes.flatMap((scheme) =>
      scheme.conceptSchemes.map((conceptScheme) => conceptScheme.id),
    ),
  );
  const allowedOwnerIds = new Set<string>([
    artifact.profile.id,
    ...publisherIds,
    ...externalConceptSchemeIds,
  ]);
  if (!publisherIds.has(artifact.profile.publisherId)) {
    addIssue(context, ["profile", "publisherId"], "Publication profile must reference a publisher scheme.");
  }
  for (const publisherSchemeId of artifact.profile.publisherSchemeIds) {
    if (!publisherIds.has(publisherSchemeId)) {
      addIssue(context, ["profile", "publisherSchemeIds"], "Unknown publisher scheme ID.");
    }
  }

  assertUniqueIds(context, [
    artifact.profile.id,
    ...artifact.publisherSchemes.flatMap((entity) => [
      entity.id,
      ...entity.conceptSchemes.map((conceptScheme) => conceptScheme.id),
    ]),
    ...artifact.concepts.map((entity) => entity.id),
    ...artifact.conceptualVariables.map((entity) => entity.id),
    ...artifact.representedVariables.map((entity) => entity.id),
    ...artifact.valueSchemes.map((entity) => entity.id),
    ...artifact.canonicalValues.map((entity) => entity.id),
    ...artifact.rawValueMappings.map((entity) => entity.id),
    ...artifact.valueSchemeCrosswalks.flatMap((crosswalk) => [
      crosswalk.id,
      ...crosswalk.entries.map((entry) => entry.id),
    ]),
    ...artifact.hierarchies.map((entity) => entity.id),
    ...artifact.occurrenceMappings.map((entity) => entity.occurrenceId),
    ...artifact.occurrenceVariableBindings.map((entity) => entity.id),
    ...artifact.reviewDecisions.map((entity) => entity.id),
  ]);

  const conceptIds = new Set<string>(artifact.concepts.map((concept) => concept.id));
  const conceptualVariableIds = new Set<string>(artifact.conceptualVariables.map((variable) => variable.id));
  const representedVariableIds = new Set<string>(artifact.representedVariables.map((variable) => variable.id));
  const occurrenceIds = new Set<string>(
    artifact.occurrenceMappings.map((occurrence) => occurrence.occurrenceId),
  );
  const schemeByKey = new Map(
    artifact.valueSchemes.map((scheme) => [schemeKey(scheme.id, scheme.version), scheme]),
  );
  const canonicalValueById = new Map<string, (typeof artifact.canonicalValues)[number]>(
    artifact.canonicalValues.map((value) => [value.id, value]),
  );
  const knownEntityIds = new Set<string>([
    artifact.profile.id,
    ...publisherIds,
    ...externalConceptSchemeIds,
    ...conceptIds,
    ...conceptualVariableIds,
    ...representedVariableIds,
    ...artifact.valueSchemes.map((scheme) => scheme.id),
    ...canonicalValueById.keys(),
    ...artifact.hierarchies.map((hierarchy) => hierarchy.id),
    ...occurrenceIds,
  ]);

  for (const concept of artifact.concepts) {
    if (!allowedOwnerIds.has(concept.ownerSchemeId)) {
      addIssue(context, ["concepts"], "Concept references an unknown ontology owner.");
    }
  }

  for (const valueScheme of artifact.valueSchemes) {
    if (!allowedOwnerIds.has(valueScheme.ownerId)) {
      addIssue(context, ["valueSchemes"], "Value scheme references an unknown ontology owner.");
    }
  }

  for (const conceptualVariable of artifact.conceptualVariables) {
    if (!conceptIds.has(conceptualVariable.conceptId)) {
      addIssue(context, ["conceptualVariables"], "Conceptual variable references an unknown concept.");
    }
  }

  for (const variable of artifact.representedVariables) {
    if (!conceptualVariableIds.has(variable.conceptualVariableId)) {
      addIssue(context, ["representedVariables"], "Represented variable references an unknown conceptual variable.");
    }
    if (variable.valueScheme && !schemeByKey.has(schemeKeyOf(variable.valueScheme))) {
      addIssue(context, ["representedVariables"], "Represented variable references an unknown value-scheme version.");
    }
  }

  const canonicalCodes = new Set<string>();
  const canonicalLabels = new Map<string, string>();
  for (const value of artifact.canonicalValues) {
    if (!schemeByKey.has(schemeKeyOf(value.valueScheme))) {
      addIssue(context, ["canonicalValues"], "Canonical value references an unknown value-scheme version.");
    }
    const key = `${schemeKeyOf(value.valueScheme)}\u001f${value.code.normalize("NFKC").trim().toLowerCase()}`;
    if (canonicalCodes.has(key)) {
      addIssue(context, ["canonicalValues"], "Canonical value codes must be unique within a scheme version.");
    }
    canonicalCodes.add(key);

    for (const label of [
      ...value.preferredLabels,
      ...value.alternativeLabels,
      ...value.hiddenLabels,
    ]) {
      const labelKey = `${schemeKeyOf(value.valueScheme)}\u001f${localizedLabelKey(label)}`;
      const existingValueId = canonicalLabels.get(labelKey);
      if (existingValueId && existingValueId !== value.id) {
        addIssue(
          context,
          ["canonicalValues"],
          "Canonical labels must not ambiguously identify multiple values in the same scheme version.",
        );
      } else {
        canonicalLabels.set(labelKey, value.id);
      }
    }
  }

  const mappingKeys = new Set<string>();
  for (const mapping of artifact.rawValueMappings) {
    if (mapping.publicationId !== artifact.profile.id) {
      addIssue(context, ["rawValueMappings"], "Raw-value mapping must belong to the publication profile.");
    }
    const representedVariable = artifact.representedVariables.find(
      (variable) => variable.id === mapping.representedVariableId,
    );
    if (!representedVariable) {
      addIssue(context, ["rawValueMappings"], "Raw-value mapping references an unknown represented variable.");
    } else if (
      !representedVariable.valueScheme ||
      !sameScheme(representedVariable.valueScheme, mapping.valueScheme)
    ) {
      addIssue(context, ["rawValueMappings"], "Raw-value mapping value scheme must match the represented-variable definition.");
    }
    if (!schemeByKey.has(schemeKeyOf(mapping.valueScheme))) {
      addIssue(context, ["rawValueMappings"], "Raw-value mapping references an unknown value-scheme version.");
    }
    const mappingKey = [
      mapping.representedVariableId,
      schemeKeyOf(mapping.valueScheme),
      mapping.rawLanguage ?? "",
      mapping.effectiveAt ?? "",
      mapping.publisherCode?.normalize("NFKC").trim() ?? "",
      mapping.rawValue.normalize("NFKC").trim().toLowerCase(),
    ].join("\u001f");
    if (mappingKeys.has(mappingKey)) {
      addIssue(context, ["rawValueMappings"], "Duplicate or conflicting raw-value mapping for the same variable and scheme version.");
    }
    mappingKeys.add(mappingKey);

    if (mapping.relation === "unmapped" && mapping.canonicalValueId) {
      addIssue(context, ["rawValueMappings"], "Unmapped raw values cannot reference a canonical value.");
    }
    if (mapping.relation !== "unmapped" && !mapping.canonicalValueId) {
      addIssue(context, ["rawValueMappings"], "Mapped raw values require a canonical value ID.");
    }
    if (mapping.canonicalValueId) {
      const canonicalValue = canonicalValueById.get(mapping.canonicalValueId);
      if (!canonicalValue) {
        addIssue(context, ["rawValueMappings"], "Raw-value mapping references an unknown canonical value.");
      } else if (!sameScheme(canonicalValue.valueScheme, mapping.valueScheme)) {
        addIssue(context, ["rawValueMappings"], "Canonical value must use the mapping's scheme ID and version.");
      }
    }
  }

  const crosswalkMappingKeys = new Set<string>();
  for (const crosswalk of artifact.valueSchemeCrosswalks) {
    if (!schemeByKey.has(schemeKeyOf(crosswalk.sourceScheme)) || !schemeByKey.has(schemeKeyOf(crosswalk.targetScheme))) {
      addIssue(context, ["valueSchemeCrosswalks"], "Crosswalk references an unknown source or target scheme version.");
    }
    for (const entry of crosswalk.entries) {
      const mappingKey = [
        schemeKeyOf(crosswalk.sourceScheme),
        schemeKeyOf(crosswalk.targetScheme),
        entry.sourceCanonicalValueId,
        entry.targetCanonicalValueId,
      ].join("\u001f");
      if (crosswalkMappingKeys.has(mappingKey)) {
        addIssue(
          context,
          ["valueSchemeCrosswalks"],
          "Duplicate or conflicting crosswalk mapping for the same directed value pair.",
        );
      }
      crosswalkMappingKeys.add(mappingKey);

      const source = canonicalValueById.get(entry.sourceCanonicalValueId);
      const target = canonicalValueById.get(entry.targetCanonicalValueId);
      if (!source || !target) {
        addIssue(context, ["valueSchemeCrosswalks"], "Crosswalk entry references an unknown canonical value.");
      } else if (!sameScheme(source.valueScheme, crosswalk.sourceScheme) || !sameScheme(target.valueScheme, crosswalk.targetScheme)) {
        addIssue(context, ["valueSchemeCrosswalks"], "Crosswalk entry canonical values must match source and target scheme versions.");
      }
    }
  }

  for (const hierarchy of artifact.hierarchies) {
    const periodScheme = hierarchy.periodScheme
      ? schemeByKey.get(schemeKeyOf(hierarchy.periodScheme))
      : undefined;
    if (hierarchy.periodScheme && !periodScheme) {
      addIssue(context, ["hierarchies"], "Hierarchy period scheme references an unknown value-scheme version.");
    }
    if (
      periodScheme
      && (hierarchy.type === "calendar" || hierarchy.type === "fiscal")
      && periodScheme.periodSchemeKind !== hierarchy.type
    ) {
      addIssue(context, ["hierarchies"], "Hierarchy type must match its registered calendar/fiscal period scheme kind.");
    }
    for (const requiredMemberId of hierarchy.coverage?.requiredMemberIds ?? []) {
      if (!canonicalValueById.has(requiredMemberId)) {
        addIssue(context, ["hierarchies"], "Hierarchy coverage references an unknown canonical member.");
      }
    }
    const levelIds = new Set<string>();
    const levelOrders = new Set<number>();
    const levelById = new Map(hierarchy.levels.map((level) => [level.id, level]));
    for (const level of hierarchy.levels) {
      if (levelIds.has(level.id)) {
        addIssue(context, ["hierarchies"], "Hierarchy level ID must be unique.");
      }
      levelIds.add(level.id);
      if (levelOrders.has(level.order)) {
        addIssue(context, ["hierarchies"], "Hierarchy level order must be unique.");
      }
      levelOrders.add(level.order);
      if (level.valueScheme && !schemeByKey.has(schemeKeyOf(level.valueScheme))) {
        addIssue(context, ["hierarchies"], "Hierarchy level references an unknown value-scheme version.");
      }
    }

    const edgeKeys = new Set<string>();
    for (const edge of hierarchy.edges) {
      if (edge.hierarchyId !== hierarchy.id || edge.hierarchyVersion !== hierarchy.version) {
        addIssue(context, ["hierarchies"], "Every hierarchy edge must name its containing hierarchy ID and version.");
      }
      if (!knownEntityIds.has(edge.sourceId) || !knownEntityIds.has(edge.targetId)) {
        addIssue(context, ["hierarchies"], "Hierarchy edge references an unknown entity.");
      }
      if (edge.sourceId === edge.targetId) {
        addIssue(context, ["hierarchies"], "Hierarchy edges cannot be self-referential.");
      }

      const edgeKey = [edge.relation, edge.sourceId, edge.targetId].join("\u001f");
      if (edgeKeys.has(edgeKey)) {
        addIssue(context, ["hierarchies"], "Duplicate hierarchy edges are not allowed.");
      }
      edgeKeys.add(edgeKey);

      if (edge.relation === "rolls_up_to" && isActiveHierarchyEdge(edge)) {
        const sourceValue = canonicalValueById.get(edge.sourceId);
        const targetValue = canonicalValueById.get(edge.targetId);
        if (!sourceValue || !targetValue) {
          addIssue(context, ["hierarchies"], "Statistical roll-up edges must connect canonical values.");
        }

        const sourceLevel = edge.sourceLevelId
          ? levelById.get(edge.sourceLevelId)
          : undefined;
        const targetLevel = edge.targetLevelId
          ? levelById.get(edge.targetLevelId)
          : undefined;
        if (!sourceLevel || !targetLevel) {
          addIssue(context, ["hierarchies"], "Roll-up edges must reference known hierarchy levels.");
        } else if (sourceLevel.order !== targetLevel.order + 1) {
          addIssue(
            context,
            ["hierarchies"],
            "Roll-up edges must connect adjacent child-to-parent hierarchy levels.",
          );
        }
        if (
          sourceValue &&
          sourceLevel?.valueScheme &&
          !sameScheme(sourceValue.valueScheme, sourceLevel.valueScheme)
        ) {
          addIssue(context, ["hierarchies"], "Roll-up source value must match its level's value scheme version.");
        }
        if (
          targetValue &&
          targetLevel?.valueScheme &&
          !sameScheme(targetValue.valueScheme, targetLevel.valueScheme)
        ) {
          addIssue(context, ["hierarchies"], "Roll-up target value must match its level's value scheme version.");
        }
      }

      if (edge.relation === "broader_concept" && (!conceptIds.has(edge.sourceId) || !conceptIds.has(edge.targetId))) {
        addIssue(context, ["hierarchies"], "Conceptual broader edges must connect concepts.");
      }

      if (
        edge.relation === "contains" &&
        (edge.sourceId !== artifact.profile.id || !occurrenceIds.has(edge.targetId))
      ) {
        addIssue(
          context,
          ["hierarchies"],
          "Artifact version 0.2 containment edges must connect the publication profile to an occurrence.",
        );
      }
    }

    if (hasDirectedCycle(hierarchy.edges.filter(isActiveHierarchyEdge))) {
      addIssue(context, ["hierarchies"], "Active hierarchy edges must form an acyclic directed graph.");
    }

    const typedResult = validateTypedHierarchy({
      hierarchy,
      canonicalValues: artifact.canonicalValues.map((value) => ({
        id: value.id,
        valueScheme: value.valueScheme,
        valueRole: value.valueRole,
      })),
      periodSchemeMetadata: artifact.valueSchemes.map((scheme) => ({
        valueScheme: { valueSchemeId: scheme.id, valueSchemeVersion: scheme.version },
        periodSchemeKind: scheme.periodSchemeKind,
      })),
    });
    for (const issue of typedResult.issues) {
      addIssue(context, ["hierarchies"], issue.message);
    }
  }

  const occurrenceById = new Map(
    artifact.occurrenceMappings.map((occurrence) => [occurrence.occurrenceId, occurrence]),
  );
  const isDurableOccurrence = (
    occurrence: (typeof artifact.occurrenceMappings)[number],
  ): occurrence is z.infer<typeof DurableOccurrenceMappingSchema> =>
    "rawDetectionIds" in occurrence;
  for (const occurrence of artifact.occurrenceMappings) {
    if (occurrence.publicationId !== artifact.profile.id) {
      addIssue(context, ["occurrenceMappings"], "Occurrence mapping must reference this publication.");
    }
    if (occurrence.representedVariableId && !representedVariableIds.has(occurrence.representedVariableId)) {
      addIssue(context, ["occurrenceMappings"], "Occurrence mapping references an unknown represented variable.");
    }
    if (!isDurableOccurrence(occurrence)) continue;

    const expectedSignature = createOccurrenceStructuralSignature(
      occurrence.structuralEvidence,
    );
    if (
      occurrence.structuralSignature !== expectedSignature.signature ||
      occurrence.structuralSignatureVersion !== expectedSignature.signatureVersion
    ) {
      addIssue(
        context,
        ["occurrenceMappings"],
        "Occurrence structural signature must match its versioned structural evidence.",
      );
    }
    if (
      occurrence.structuralEvidence.classification &&
      !schemeByKey.has(schemeKeyOf(occurrence.structuralEvidence.classification))
    ) {
      addIssue(
        context,
        ["occurrenceMappings"],
        "Occurrence classification references an unknown value-scheme version.",
      );
    }
    if (
      occurrence.structuralEvidence.priorRepresentedVariableId &&
      !representedVariableIds.has(occurrence.structuralEvidence.priorRepresentedVariableId)
    ) {
      addIssue(
        context,
        ["occurrenceMappings"],
        "Occurrence structural evidence references an unknown represented variable.",
      );
    }
    for (const supersededOccurrenceId of occurrence.supersedes) {
      const superseded = occurrenceById.get(supersededOccurrenceId);
      if (!superseded) {
        addIssue(context, ["occurrenceMappings"], "Occurrence supersession references an unknown occurrence.");
      } else if (!isDurableOccurrence(superseded) || !superseded.supersededBy.includes(occurrence.occurrenceId)) {
        addIssue(context, ["occurrenceMappings"], "Occurrence supersession history must be bidirectional.");
      }
    }
    for (const supersedingOccurrenceId of occurrence.supersededBy) {
      const superseding = occurrenceById.get(supersedingOccurrenceId);
      if (!superseding) {
        addIssue(context, ["occurrenceMappings"], "Occurrence supersession references an unknown occurrence.");
      } else if (!isDurableOccurrence(superseding) || !superseding.supersedes.includes(occurrence.occurrenceId)) {
        addIssue(context, ["occurrenceMappings"], "Occurrence supersession history must be bidirectional.");
      }
    }
  }

  const bindingOccurrenceIds = new Set<string>();
  for (const binding of artifact.occurrenceVariableBindings) {
    if (bindingOccurrenceIds.has(binding.occurrenceId)) {
      addIssue(context, ["occurrenceVariableBindings"], "An occurrence may have only one current binding decision.");
    }
    bindingOccurrenceIds.add(binding.occurrenceId);

    const occurrence = occurrenceById.get(binding.occurrenceId);
    if (!occurrence) {
      addIssue(context, ["occurrenceVariableBindings"], "Occurrence binding references an unknown occurrence.");
    }
    if (!binding.representedVariableId) continue;

    const representedVariable = artifact.representedVariables.find(
      (variable) => variable.id === binding.representedVariableId,
    );
    if (!representedVariable) {
      addIssue(context, ["occurrenceVariableBindings"], "Occurrence binding references an unknown represented variable.");
      continue;
    }
    const conceptualVariable = artifact.conceptualVariables.find(
      (variable) => variable.id === representedVariable.conceptualVariableId,
    );
    if (
      binding.representedVariableVersion !== representedVariable.version ||
      binding.conceptualVariableId !== representedVariable.conceptualVariableId ||
      binding.conceptId !== conceptualVariable?.conceptId
    ) {
      addIssue(context, ["occurrenceVariableBindings"], "Occurrence binding references must match the represented-variable definition.");
    }
    if (
      (representedVariable.valueScheme &&
        (!binding.valueScheme || !sameScheme(representedVariable.valueScheme, binding.valueScheme))) ||
      (!representedVariable.valueScheme && binding.valueScheme)
    ) {
      addIssue(context, ["occurrenceVariableBindings"], "Occurrence binding value-scheme reference must match the represented-variable definition.");
    }
    if (
      binding.method === "existing_approved_occurrence" &&
      (!occurrence ||
        occurrence.reviewStatus !== "approved" ||
        occurrence.representedVariableId !== binding.representedVariableId)
    ) {
      addIssue(context, ["occurrenceVariableBindings"], "Existing approved occurrence bindings must match the approved occurrence record.");
    }
    if (
      occurrence?.reviewStatus === "approved" &&
      occurrence.representedVariableId &&
      occurrence.representedVariableId !== binding.representedVariableId
    ) {
      addIssue(context, ["occurrenceVariableBindings"], "Occurrence binding cannot replace an explicit approved occurrence binding.");
    }
  }

  const reviewableEntityIds = new Set([
    ...knownEntityIds,
    ...artifact.occurrenceVariableBindings.map((binding) => binding.id),
    ...artifact.rawValueMappings.map((mapping) => mapping.id),
    ...artifact.valueSchemeCrosswalks.flatMap((crosswalk) => [
      crosswalk.id,
      ...crosswalk.entries.map((entry) => entry.id),
    ]),
  ]);
  for (const decision of artifact.reviewDecisions) {
    if (!reviewableEntityIds.has(decision.entityId)) {
      addIssue(context, ["reviewDecisions"], "Review decision references an unknown ontology entity.");
    }
  }

  const supersessionPairs = new Set<string>();
  for (const record of artifact.supersessionHistory) {
    const pair = `${record.supersededOccurrenceId}\u001f${record.supersedingOccurrenceId}`;
    const superseded = occurrenceById.get(record.supersededOccurrenceId);
    const superseding = occurrenceById.get(record.supersedingOccurrenceId);
    if (!superseded || !superseding) {
      addIssue(context, ["supersessionHistory"], "Supersession history must reference known occurrences.");
    }
    if (record.supersededOccurrenceId === record.supersedingOccurrenceId) {
      addIssue(context, ["supersessionHistory"], "Supersession history cannot be self-referential.");
    }
    if (supersessionPairs.has(pair)) {
      addIssue(context, ["supersessionHistory"], "Supersession history cannot duplicate an occurrence pair.");
    }
    supersessionPairs.add(pair);
    if (
      superseded &&
      superseding &&
      superseded.workbookEditionId === superseding.workbookEditionId
    ) {
      addIssue(context, ["supersessionHistory"], "Occurrence supersession must cross workbook editions.");
    }
    if (
      superseded &&
      superseding &&
      (isDurableOccurrence(superseded) || isDurableOccurrence(superseding)) &&
      (!isDurableOccurrence(superseded) ||
        !isDurableOccurrence(superseding) ||
        !superseding.supersedes.includes(superseded.occurrenceId) ||
        !superseded.supersededBy.includes(superseding.occurrenceId))
    ) {
      addIssue(
        context,
        ["supersessionHistory"],
        "Supersession records for durable occurrences must match bidirectional occurrence history.",
      );
    }
  }
  if (
    hasDirectedCycle(
      artifact.supersessionHistory.map((record) => ({
        sourceId: record.supersededOccurrenceId,
        targetId: record.supersedingOccurrenceId,
      })),
    )
  ) {
    addIssue(context, ["supersessionHistory"], "Occurrence supersession history must be acyclic.");
  }
  for (const occurrence of artifact.occurrenceMappings.filter(isDurableOccurrence)) {
    for (const supersededOccurrenceId of occurrence.supersedes) {
      const pair = `${supersededOccurrenceId}\u001f${occurrence.occurrenceId}`;
      if (!supersessionPairs.has(pair)) {
        addIssue(context, ["supersessionHistory"], "Durable occurrence supersession requires a history record.");
      }
    }
  }
}

function hasDirectedCycle(
  edges: readonly { sourceId: string; targetId: string }[],
): boolean {
  const adjacency = new Map<string, Set<string>>();
  const indegree = new Map<string, number>();

  for (const edge of edges) {
    if (!adjacency.has(edge.sourceId)) adjacency.set(edge.sourceId, new Set());
    if (!adjacency.has(edge.targetId)) adjacency.set(edge.targetId, new Set());
    if (!indegree.has(edge.sourceId)) indegree.set(edge.sourceId, 0);
    if (!indegree.has(edge.targetId)) indegree.set(edge.targetId, 0);

    const targets = adjacency.get(edge.sourceId);
    if (targets && !targets.has(edge.targetId)) {
      targets.add(edge.targetId);
      indegree.set(edge.targetId, (indegree.get(edge.targetId) ?? 0) + 1);
    }
  }

  const queue = [...indegree.entries()]
    .filter(([, degree]) => degree === 0)
    .map(([id]) => id);
  let visited = 0;

  for (let index = 0; index < queue.length; index += 1) {
    const sourceId = queue[index];
    visited += 1;
    for (const targetId of adjacency.get(sourceId) ?? []) {
      const nextDegree = (indegree.get(targetId) ?? 0) - 1;
      indegree.set(targetId, nextDegree);
      if (nextDegree === 0) queue.push(targetId);
    }
  }

  return visited !== indegree.size;
}

function assertUniqueIds(context: z.RefinementCtx, ids: string[]): void {
  const uniqueIds = new Set<string>();
  for (const id of ids) {
    if (uniqueIds.has(id)) {
      addIssue(context, [], "Publication ontology entity IDs must be globally unique.");
      return;
    }
    uniqueIds.add(id);
  }
}

function localizedLabelKey(label: z.infer<typeof LocalizedLabelSchema>): string {
  return `${label.language.toLowerCase()}\u001f${label.value
    .normalize("NFKC")
    .trim()
    .toLowerCase()}`;
}

function schemeKey(id: string, version: string): string {
  return `${id}\u001f${version}`;
}

function schemeKeyOf(reference: z.infer<typeof ValueSchemeReferenceSchema>): string {
  return schemeKey(reference.valueSchemeId, reference.valueSchemeVersion);
}

function sameScheme(
  left: z.infer<typeof ValueSchemeReferenceSchema>,
  right: z.infer<typeof ValueSchemeReferenceSchema>,
): boolean {
  return schemeKeyOf(left) === schemeKeyOf(right);
}

function addIssue(context: z.RefinementCtx, path: (string | number)[], message: string): void {
  context.addIssue({ code: "custom", path, message });
}

export type PublicationOntologyId = PublicationEntityId;
