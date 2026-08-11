import { z } from "zod";

export const SEMANTIC_GOLD_SCHEMA_VERSION =
  "cell-role-semantic-gold-asset-v1" as const;
export const SEMANTIC_GOLD_MANIFEST_VERSION =
  "cell-role-semantic-gold-manifest-v1" as const;
export const SEMANTIC_GOLD_GRAPH_VERSION =
  "cell-role-semantic-graph-v1" as const;
export const SEMANTIC_GOLD_REVIEW_VERSION =
  "cell-role-semantic-review-v1" as const;
export const SEMANTIC_GOLD_ADJUDICATION_VERSION =
  "cell-role-semantic-adjudication-v1" as const;
export const SEMANTIC_GOLD_AUTHORIZATION_VERSION =
  "cell-role-semantic-gold-authorization-v1" as const;

export const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
export const canonicalCellSchema = z.string().regex(/^R[1-9]\d*C[1-9]\d*$/);
export const canonicalRangeSchema = z
  .string()
  .regex(/^R[1-9]\d*C[1-9]\d*:R[1-9]\d*C[1-9]\d*$/);
export const stableIdSchema = z.string().regex(/^[a-z][a-z0-9-]{1,79}$/);
export const containedArtifactPathSchema = z
  .string()
  .min(1)
  .refine(
    (value) =>
      !value.startsWith("/") &&
      !value.includes("\\") &&
      !value
        .split("/")
        .some((part) => part === "" || part === "." || part === ".."),
    "Artifact path must be a normalized repository-relative POSIX path.",
  );

export const relationshipKindSchema = z.enum([
  "direct-column",
  "direct-row",
  "cascading-column",
  "cascading-row",
]);

export const semanticAssociationSchema = z
  .object({
    valueAddress: canonicalCellSchema,
    headerAddress: canonicalCellSchema,
  })
  .strict();

export const semanticHierarchyLevelSchema = z
  .object({
    id: stableIdSchema,
    displayLabel: z.string().min(1),
    coverage: z.enum(["required", "partial"]),
    headerSourceAddresses: z.array(canonicalCellSchema).min(1),
    relationshipKind: relationshipKindSchema,
    associations: z.array(semanticAssociationSchema).min(1),
    evidence: z.array(z.string().min(1)).min(1),
  })
  .strict();

export const semanticDimensionSchema = z
  .object({
    id: stableIdSchema,
    displayLabel: z.string().min(1),
    levels: z.array(semanticHierarchyLevelSchema).min(1),
  })
  .strict();

export const semanticTableSchema = z
  .object({
    id: stableIdSchema,
    displayLabel: z.string().min(1),
    valueAddresses: z.array(canonicalCellSchema).min(1),
    selectorDerivedBounds: canonicalRangeSchema,
    physicalExtent: canonicalRangeSchema.optional(),
    dimensions: z.array(semanticDimensionSchema).min(1),
    evidence: z.array(z.string().min(1)).min(1),
  })
  .strict();

export const semanticAmbiguitySchema = z
  .object({
    id: stableIdSchema,
    targetIds: z.array(stableIdSchema).min(1),
    evidence: z.array(z.string().min(1)).min(1),
    candidateAlternativeIds: z.array(stableIdSchema).min(1),
  })
  .strict();

export const semanticAlternativeSchema = z
  .object({
    id: stableIdSchema,
    status: z.literal("candidate_pending_human_review"),
    targetIds: z.array(stableIdSchema).min(1),
    description: z.string().min(1),
    evidence: z.array(z.string().min(1)).min(1),
  })
  .strict();

export const semanticGoldDraftSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_SCHEMA_VERSION),
    goldSetId: z.literal("cell-role-smoke-semantic-gold"),
    goldSetVersion: z.literal("v1"),
    assetId: z.string().min(1),
    workbook: z
      .object({
        path: containedArtifactPathSchema,
        sha256: sha256Schema,
        bytes: z.number().int().positive(),
      })
      .strict(),
    worksheet: z
      .object({
        name: z.string().min(1),
        ordinal: z.number().int().positive(),
        rowCount: z.number().int().positive(),
        columnCount: z.number().int().positive(),
      })
      .strict(),
    reviewStatus: z.literal("pending_human_review"),
    reviewerProvenance: z.array(z.never()).length(0),
    adjudicationProvenance: z.null(),
    preparationProvenance: z
      .object({
        method: z.literal("agent_assisted_workbook_evidence_draft"),
        semanticSources: z.tuple([z.literal("workbook_cells")]),
        excludedSemanticSources: z.tuple([
          z.literal("generated_v1_output"),
          z.literal("generated_v2_output"),
          z.literal("accepted_recipe"),
          z.literal("historical_expected_csv"),
        ]),
      })
      .strict(),
    tables: z.array(semanticTableSchema).min(1),
    ambiguities: z.array(semanticAmbiguitySchema),
    alternatives: z.array(semanticAlternativeSchema).min(1),
  })
  .strict();

export type SemanticGoldDraft = z.infer<typeof semanticGoldDraftSchema>;
export type SemanticTable = z.infer<typeof semanticTableSchema>;
export type SemanticHierarchyLevel = z.infer<
  typeof semanticHierarchyLevelSchema
>;
export type RelationshipKind = z.infer<typeof relationshipKindSchema>;

export const legacyMappingSchema = z
  .object({
    schemaVersion: z.literal("cell-role-semantic-legacy-map-v1"),
    goldSetId: z.literal("cell-role-smoke-semantic-gold"),
    goldSetVersion: z.literal("v1"),
    assetId: z.string().min(1),
    draftSha256: sha256Schema,
    acceptedRecipe: z
      .object({
        path: containedArtifactPathSchema,
        sha256: sha256Schema,
        bytes: z.number().int().positive(),
      })
      .strict(),
    independenceNotice: z.literal(
      "Compatibility mapping only; excluded from semantic draft and graph identity.",
    ),
    coalescedDimensions: z.array(
      z
        .object({
          recipeTargetName: z.string().min(1),
          semanticTargetIds: z.array(stableIdSchema).min(2),
          loss: z.string().min(1),
        })
        .strict(),
    ),
    renamedConcepts: z.array(
      z
        .object({
          recipeTargetName: z.string().min(1),
          semanticTargetId: stableIdSchema,
          semanticDisplayLabel: z.string().min(1),
          note: z.string().min(1),
        })
        .strict(),
    ),
    omittedConcepts: z.array(
      z
        .object({ semanticTargetId: stableIdSchema, note: z.string().min(1) })
        .strict(),
    ),
    orderingDifferences: z.array(z.string().min(1)),
    intentionalBroadSelectors: z.array(
      z
        .object({ recipeSelector: z.string().min(1), note: z.string().min(1) })
        .strict(),
    ),
  })
  .strict();

export type LegacyMapping = z.infer<typeof legacyMappingSchema>;

export const semanticGoldGraphSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_GRAPH_VERSION),
    assetId: z.string().min(1),
    draftSha256: sha256Schema,
    identityPolicy: z.literal(
      "source-address topology; display labels, declaration order, physical extent, and legacy names excluded",
    ),
    nodes: z.array(z.string().min(1)),
    edges: z.array(z.string().min(1)),
    graphDigest: sha256Schema,
    reviewStatus: z.literal("pending_human_review"),
  })
  .strict();

export type SemanticGoldGraph = z.infer<typeof semanticGoldGraphSchema>;

export const overlaySchema = z
  .object({
    schemaVersion: z.literal("cell-role-semantic-overlay-v1"),
    assetId: z.string().min(1),
    worksheet: z.string().min(1),
    graphDigest: sha256Schema,
    reviewStatus: z.literal("pending_human_review"),
    legend: z.record(z.string(), z.string()),
    cells: z.array(
      z
        .object({
          address: canonicalCellSchema,
          roles: z.array(z.string().min(1)).min(1),
          workbookDisplay: z.string(),
        })
        .strict(),
    ),
  })
  .strict();

const pendingReviewTemplateSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_REVIEW_VERSION),
    goldSetId: z.literal("cell-role-smoke-semantic-gold"),
    goldSetVersion: z.literal("v1"),
    assetId: z.string().min(1),
    reviewSlot: z.enum(["review-1", "review-2"]),
    status: z.literal("pending_human_review"),
    candidateManifestSha256: z.null(),
    reviewer: z.null(),
    reviewedAt: z.null(),
    decision: z.null(),
    independenceAttestation: z.null(),
    findings: z.array(z.never()).length(0),
  })
  .strict();

const reviewerProvenanceSchema = z
  .object({
    authorityId: z.string().min(1),
    displayName: z.string().min(1),
    organization: z.string().min(1),
    attestation: z.string().min(1),
  })
  .strict();

const submittedReviewSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_REVIEW_VERSION),
    goldSetId: z.string().min(1),
    goldSetVersion: z.string().min(1),
    assetIds: z.array(z.string().min(1)).min(1),
    reviewSlot: z.enum(["review-1", "review-2"]),
    status: z.literal("submitted"),
    candidateManifestSha256: sha256Schema,
    reviewer: reviewerProvenanceSchema,
    reviewedAt: z.string().datetime({ offset: true }),
    decision: z.enum(["approve", "changes_required", "abstain"]),
    independenceAttestation: z.string().min(1),
    findings: z.array(
      z
        .object({
          id: stableIdSchema,
          target: z.string().min(1),
          disposition: z.string().min(1),
        })
        .strict(),
    ),
  })
  .strict();

export const semanticReviewRecordSchema = z.union([
  pendingReviewTemplateSchema,
  submittedReviewSchema,
]);
export const submittedSemanticReviewSchema = submittedReviewSchema;

const pendingAdjudicationSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_ADJUDICATION_VERSION),
    goldSetId: z.literal("cell-role-smoke-semantic-gold"),
    goldSetVersion: z.literal("v1"),
    assetId: z.string().min(1),
    status: z.literal("pending_human_review"),
    candidateManifestSha256: z.null(),
    reviewOneSha256: z.null(),
    reviewTwoSha256: z.null(),
    finalManifestSha256: z.null(),
    adjudicator: z.null(),
    adjudicatedAt: z.null(),
    dispositions: z.array(z.never()).length(0),
  })
  .strict();

const resolvedAdjudicationSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_ADJUDICATION_VERSION),
    goldSetId: z.string().min(1),
    goldSetVersion: z.string().min(1),
    status: z.literal("resolved"),
    candidateManifestSha256: sha256Schema,
    reviewOneSha256: sha256Schema,
    reviewTwoSha256: sha256Schema,
    finalManifestSha256: sha256Schema,
    adjudicator: reviewerProvenanceSchema,
    adjudicatedAt: z.string().datetime({ offset: true }),
    dispositions: z.array(
      z
        .object({ findingId: stableIdSchema, resolution: z.string().min(1) })
        .strict(),
    ),
  })
  .strict();

export const semanticAdjudicationRecordSchema = z.union([
  pendingAdjudicationSchema,
  resolvedAdjudicationSchema,
]);
export const resolvedSemanticAdjudicationSchema = resolvedAdjudicationSchema;

export const semanticGoldAuthorizationSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_AUTHORIZATION_VERSION),
    goldSetId: z.string().min(1),
    goldSetVersion: z.string().min(1),
    finalManifest: z
      .object({
        schemaVersion: z.literal(SEMANTIC_GOLD_MANIFEST_VERSION),
        sha256: sha256Schema,
      })
      .strict(),
    reviews: z
      .object({ reviewOneSha256: sha256Schema, reviewTwoSha256: sha256Schema })
      .strict(),
    adjudication: z
      .object({ status: z.literal("resolved"), sha256: sha256Schema })
      .strict(),
    authorizedGraphDigests: z.array(sha256Schema).min(1),
    approver: reviewerProvenanceSchema,
    approvedAt: z.string().datetime({ offset: true }),
    authorizationPolicyVersion: z.literal("two-independent-reviews-v1"),
    fixtureOnly: z.boolean(),
  })
  .strict();

export type SemanticGoldAuthorization = z.infer<
  typeof semanticGoldAuthorizationSchema
>;

export const goldEvidenceRoleSchema = z.enum([
  "schema",
  "draft",
  "legacy-map",
  "graph",
  "overlay",
  "review-packet",
  "review-template",
  "adjudication-template",
  "inspection-record",
]);

export const goldEvidenceEntrySchema = z
  .object({
    path: containedArtifactPathSchema,
    sha256: sha256Schema,
    bytes: z.number().int().nonnegative(),
    mediaType: z.enum(["application/json", "text/markdown"]),
    schemaType: z.string().min(1),
    role: goldEvidenceRoleSchema,
    assetId: z.string().min(1).optional(),
  })
  .strict();

export const semanticGoldManifestSchema = z
  .object({
    schemaVersion: z.literal(SEMANTIC_GOLD_MANIFEST_VERSION),
    goldSetId: z.literal("cell-role-smoke-semantic-gold"),
    goldSetVersion: z.literal("v1"),
    state: z.literal("draft"),
    reviewStatus: z.literal("pending_human_review"),
    authorizationRequired: z.literal(true),
    authorizationRecord: z.null(),
    assets: z.array(
      z
        .object({
          assetId: z.string().min(1),
          workbookSha256: sha256Schema,
          draftPath: containedArtifactPathSchema,
          graphPath: containedArtifactPathSchema,
          graphDigest: sha256Schema,
          reviewedAlternativeGraphDigests: z.array(sha256Schema),
          reviewStatus: z.literal("pending_human_review"),
        })
        .strict(),
    ),
    entries: z.array(goldEvidenceEntrySchema).min(1),
  })
  .strict();

export type SemanticGoldManifest = z.infer<typeof semanticGoldManifestSchema>;

export const semanticGoldRootSchema = z
  .object({
    schemaVersion: z.literal("cell-role-semantic-gold-root-v1"),
    goldSetId: z.literal("cell-role-smoke-semantic-gold"),
    goldSetVersion: z.literal("v1"),
    state: z.literal("draft"),
    reviewStatus: z.literal("pending_human_review"),
    manifest: z
      .object({
        path: z.literal("manifest.json"),
        sha256: sha256Schema,
        bytes: z.number().int().positive(),
        schemaType: z.literal(SEMANTIC_GOLD_MANIFEST_VERSION),
      })
      .strict(),
    authorizationRecord: z.null(),
  })
  .strict();
