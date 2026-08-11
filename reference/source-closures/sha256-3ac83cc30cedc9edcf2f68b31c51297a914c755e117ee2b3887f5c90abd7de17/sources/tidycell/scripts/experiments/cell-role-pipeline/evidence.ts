import path from "node:path";
import { z } from "zod";

export const SHA256_PATTERN = /^[a-f0-9]{64}$/;
export const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const sha256Schema = z.string().regex(SHA256_PATTERN);
const relativeEvidencePathSchema = z
  .string()
  .min(1)
  .superRefine((value, ctx) => {
    if (
      path.posix.isAbsolute(value) ||
      value.includes("\\") ||
      value.split("/").some((part) => !part || part === "." || part === "..") ||
      path.posix.normalize(value) !== value
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Evidence path must be a normalized contained POSIX path.",
      });
    }
  });

export const implementationSourceSchema = z
  .object({
    role: z.enum(["prompt", "parser", "compiler", "scorer", "report"]),
    path: relativeEvidencePathSchema,
    sha256: sha256Schema,
    bytes: z.number().int().nonnegative(),
  })
  .strict();

export const implementationProvenanceSchema = z
  .object({
    schemaVersion: z.literal("cell-role-implementation-provenance-v1"),
    gitCommit: z.string().regex(/^[a-f0-9]{40,64}$/),
    gitTree: z.string().regex(/^[a-f0-9]{40,64}$/),
    clean: z.literal(true),
    versions: z
      .object({
        plan: z.enum([
          "cell-role-experiment-plan-v2",
          "cell-role-experiment-plan-v3",
          "cell-role-experiment-plan-v4",
        ]),
        promptSemantics: z.string().min(1),
        promptTranslation: z.string().min(1),
        promptBaseline: z.string().min(1),
        parser: z.string().min(1),
        compiler: z.string().min(1),
        scorer: z.string().min(1),
        report: z.string().min(1),
      })
      .strict(),
    sources: z.array(implementationSourceSchema).min(5),
  })
  .strict()
  .superRefine((value, ctx) => {
    const paths = value.sources.map((source) => source.path);
    if (new Set(paths).size !== paths.length) {
      ctx.addIssue({
        code: "custom",
        message: "Duplicate implementation source path.",
      });
    }
  });
export type ImplementationProvenance = z.infer<
  typeof implementationProvenanceSchema
>;

const generationSettingsSchema = z
  .object({
    provider: z.enum(["openrouter", "pi", "claude"]),
    model: z.string().min(1),
    temperature: z.number().finite().min(0).max(2),
    reasoning: z.enum(["low", "medium", "high"]),
    timeoutMs: z.number().int().positive(),
    maxAttempts: z.literal(1),
  })
  .strict();
const usageSchema = z
  .object({
    promptTokens: z.number().optional(),
    completionTokens: z.number().optional(),
    totalTokens: z.number().optional(),
    cachedTokens: z.number().optional(),
    cacheCreationInputTokens: z.number().optional(),
    cacheReadInputTokens: z.number().optional(),
    cacheWriteInputTokens: z.number().optional(),
    reasoningTokens: z.number().optional(),
    catalogPricedUsd: z.number().optional(),
    apiEquivalentUsd: z.number().optional(),
    usageSource: z
      .enum(["provider_observed", "char_estimate", "mixed", "unknown"])
      .optional(),
  })
  .strict();

export const callEvidenceSchema = z
  .object({
    schemaVersion: z.literal("cell-role-call-v1"),
    attemptId: z
      .string()
      .regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/)
      .optional(),
    planDigest: sha256Schema,
    provenanceDigest: sha256Schema.optional(),
    unitDigest: sha256Schema,
    arm: z.enum(["baseline", "staged", "llm-translation-research"]),
    stage: z.enum(["baseline", "semantics", "translation"]),
    settings: generationSettingsSchema,
    promptDigest: sha256Schema,
    startedAt: z.string().datetime(),
    completedAt: z.string().datetime(),
    durationMs: z.number().nonnegative(),
    response: z
      .union([
        z
          .object({
            ok: z.literal(true),
            content: z.string(),
            usage: usageSchema.optional(),
          })
          .strict(),
        z
          .object({
            ok: z.literal(false),
            code: z.string().min(1),
            status: z.number().int().optional(),
            message: z.string(),
          })
          .strict(),
      ])
      .optional(),
    thrownError: z.string().optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (value.stage === "baseline" && value.arm !== "baseline") {
      ctx.addIssue({
        code: "custom",
        message: "Baseline stage must use baseline arm.",
      });
    }
    if (value.stage === "semantics" && value.arm !== "staged") {
      ctx.addIssue({
        code: "custom",
        message: "Semantic stage must use staged arm.",
      });
    }
    if (
      value.stage === "translation" &&
      value.arm !== "staged" &&
      value.arm !== "llm-translation-research"
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "Translation stage must use staged or llm-translation-research arm.",
      });
    }
    if (Boolean(value.response) === Boolean(value.thrownError)) {
      ctx.addIssue({
        code: "custom",
        message: "Attempt requires exactly one response or thrownError.",
      });
    }
  });

const operationUsageSchema = z
  .object({
    prompt_tokens: z.number(),
    completion_tokens: z.number(),
    reasoning_tokens: z.number(),
    total_tokens: z.number(),
    api_equivalent_usd: z.number(),
  })
  .strict();
const operationArmSchema = z
  .object({
    successes: z.number().int().nonnegative(),
    failures: z.number().int().nonnegative(),
    success_rate: z.number(),
    final_json_parse_valid: z.number().int().nonnegative(),
    schema_valid: z.number().int().nonnegative(),
    semantic_xml_valid: z.number().int().nonnegative().optional(),
    executable: z.number().int().nonnegative(),
    nonempty: z.number().int().nonnegative(),
    warnings: z.number().int().nonnegative(),
    usage: operationUsageSchema,
    duration_ms_sum: z.number().nonnegative(),
    failures_by_code: z.record(z.string(), z.number().int().nonnegative()),
  })
  .strict();
export const historicalOperationSummarySchema = z
  .object({
    schema_version: z.literal("1.0.0"),
    run_id: z.string().regex(RUN_ID_PATTERN),
    status: z.literal("complete"),
    plan: relativeEvidencePathSchema,
    plan_digest: sha256Schema,
    implementation_commit: z.string().regex(/^[a-f0-9]{7,64}$/),
    provider: z.string().min(1),
    provider_authentication: z.string().min(1),
    model: z.string().min(1),
    reasoning: z.string().min(1),
    temperature: z.number(),
    retries: z.number().int().nonnegative(),
    started_at: z.string().datetime(),
    completed_at: z.string().datetime(),
    wall_seconds: z.number().nonnegative(),
    assets: z.number().int().positive(),
    provider_calls: z
      .object({
        attempted: z.number().int().nonnegative(),
        responses: z.number().int().nonnegative(),
        failures: z.number().int().nonnegative(),
        baseline: z.number().int().nonnegative(),
        semantic_xml: z.number().int().nonnegative(),
        syntax_translation: z.number().int().nonnegative(),
        maximum_authorized: z.number().int().nonnegative(),
      })
      .strict(),
    denominators: z
      .object({
        intention_to_treat_pairs: z.number().int().nonnegative(),
        successful_pairs: z.number().int().nonnegative(),
      })
      .strict(),
    baseline: operationArmSchema,
    staged: operationArmSchema,
    complete_case_quality: z
      .object({
        denominator: z.number().int().nonnegative(),
        asset: z.string().min(1),
        cell_exact_match_rate_delta: z.number(),
        address_conditioned_cell_match_rate_delta: z.number(),
        value_address_f1_delta: z.number(),
        full_row_header_match_rate_delta: z.number(),
        full_row_with_value_match_rate_delta: z.number(),
      })
      .strict(),
    evidence: z
      .object({
        comparison_report: z.string().min(1),
        comparison_report_sha256: sha256Schema,
        comparison_report_bytes: z.number().int().positive(),
        unit_result_count: z.number().int().positive(),
        attempt_evidence_count: z.number().int().positive(),
        attempt_evidence_bytes: z.number().int().positive(),
      })
      .strict(),
    conclusion: z.string().min(1),
  })
  .strict();

const reportGeometrySchema = z
  .object({
    expected_overlay_available: z.boolean(),
    data_cell_precision: z.number().nullable(),
    data_cell_recall: z.number().nullable(),
    data_cell_f1: z.number().nullable(),
    header_cell_precision: z.number().nullable(),
    header_cell_recall: z.number().nullable(),
    header_cell_f1: z.number().nullable(),
    direction_accuracy: z.number().nullable(),
    table_boundary_iou: z.number().nullable(),
    multi_table_count_accuracy: z.number().nullable(),
    header_fill_accuracy: z.number().nullable(),
    missing_data_cells: z.array(z.string()),
    extra_data_cells: z.array(z.string()),
    missing_header_cells: z.array(z.string()),
    extra_header_cells: z.array(z.string()),
    direction_errors: z.array(
      z
        .object({
          table: z.string(),
          header: z.string(),
          expected: z.string(),
          actual: z.string().nullable(),
        })
        .strict(),
    ),
  })
  .strict();
const reportGraphSchema = z
  .object({
    reference_available: z.boolean(),
    expected_value_sources_available: z.boolean(),
    expected_header_sources_available: z.boolean(),
    graph_similarity: z.number().nullable(),
    column_axis_jaccard: z.number().nullable(),
    association_jaccard: z.number().nullable(),
    matched_column_pairs: z.array(
      z
        .object({
          expected_cells: z.array(z.string()),
          actual_cells: z.array(z.string()),
          shared_cell_count: z.number().int().nonnegative(),
        })
        .strict(),
    ),
    unmatched_expected_column_count: z.number().int().nonnegative(),
    unmatched_actual_column_count: z.number().int().nonnegative(),
    expected_edge_count: z.number().int().nonnegative(),
    actual_edge_count: z.number().int().nonnegative(),
    shared_edge_count: z.number().int().nonnegative(),
  })
  .strict();
const reportBenchmarkSchema = z
  .object({
    deterministicPass: z.boolean(),
    exactCsvMatch: z.boolean(),
    cellExactMatchRate: z.number(),
    addressConditionedCellMatchRate: z.number(),
    valueAddressF1: z.number(),
    fullRowHeaderMatchRate: z.number(),
    fullRowWithValueMatchRate: z.number(),
    geometry: reportGeometrySchema,
    graph: reportGraphSchema,
  })
  .strict();
const reportArmSummarySchema = z
  .object({
    finalJsonParseValid: z.boolean(),
    schemaValid: z.boolean(),
    semanticXmlValid: z.boolean(),
    executable: z.boolean(),
    nonempty: z.boolean(),
    warningCount: z.number().int().nonnegative(),
    providerAttempts: z.number().int().nonnegative(),
    providerResponses: z.number().int().nonnegative(),
    providerFailures: z.number().int().nonnegative(),
    callsWithUsage: z.number().int().nonnegative(),
    usage: usageSchema,
    durationMs: z.number().nonnegative(),
    failures: z.array(z.string()),
    benchmark: reportBenchmarkSchema.nullable(),
  })
  .strict();
const aggregateArmSchema = z
  .object({
    denominator: z.number().int().nonnegative(),
    intentionToTreat: z
      .object({
        successes: z.number().int().nonnegative(),
        failures: z.number().int().nonnegative(),
        successRate: z.number().nullable(),
        failureRate: z.number().nullable(),
      })
      .strict(),
    finalJsonParseValid: z.number().int().nonnegative(),
    schemaValid: z.number().int().nonnegative(),
    semanticXmlValid: z.number().int().nonnegative(),
    executable: z.number().int().nonnegative(),
    nonempty: z.number().int().nonnegative(),
    warnings: z.number().int().nonnegative(),
    providerAttempts: z.number().int().nonnegative(),
    providerResponses: z.number().int().nonnegative(),
    providerFailures: z.number().int().nonnegative(),
    usageCoverage: z
      .object({
        callsWithUsage: z.number().int().nonnegative(),
        attemptedCalls: z.number().int().nonnegative(),
        rate: z.number().nullable(),
      })
      .strict(),
    usage: usageSchema,
    durationMs: z.number().nonnegative(),
    failures: z.array(z.string()),
  })
  .strict();
const pairedQualitySchema = z
  .object({
    denominator: z.number().int().nonnegative(),
    meanDelta: z.number().nullable(),
    wins: z.number().int().nonnegative(),
    ties: z.number().int().nonnegative(),
    losses: z.number().int().nonnegative(),
    pairs: z.array(
      z
        .object({
          asset: z.string().min(1),
          baseline: z.number(),
          staged: z.number(),
          delta: z.number(),
        })
        .strict(),
    ),
  })
  .strict();
const comparisonBodySchema = z
  .object({
    liveExecutionEvidence: z
      .array(
        z
          .object({
            asset: z.string().min(1),
            authorizationDigest: sha256Schema,
            executableDigest: sha256Schema,
            oauthReadinessDigest: sha256Schema,
            evidenceDigest: sha256Schema,
          })
          .strict(),
      )
      .optional(),
    denominators: z
      .object({
        intentionToTreatPairs: z.number().int().nonnegative(),
        successfulPairs: z.number().int().nonnegative(),
      })
      .strict(),
    arms: z
      .object({ baseline: aggregateArmSchema, staged: aggregateArmSchema })
      .strict(),
    completeCasePairedQualityMetrics: z
      .object({
        cell_exact_match_rate: pairedQualitySchema,
        address_conditioned_cell_match_rate: pairedQualitySchema,
        value_address_f1: pairedQualitySchema,
        full_row_header_match_rate: pairedQualitySchema,
        full_row_with_value_match_rate: pairedQualitySchema,
      })
      .strict(),
    assets: z.array(
      z
        .object({
          asset: z.string().min(1),
          baseline: reportArmSummarySchema,
          staged: reportArmSummarySchema,
          successfulPair: z.boolean(),
        })
        .strict(),
    ),
  })
  .strict();
export const legacyComparisonReportSchema = z.discriminatedUnion(
  "schemaVersion",
  [
    comparisonBodySchema.extend({
      schemaVersion: z.literal("cell-role-comparison-v1"),
    }),
    comparisonBodySchema.extend({
      schemaVersion: z.literal("cell-role-comparison-v2"),
      provenanceDigest: sha256Schema,
    }),
  ],
);

const correctedEndpointSchema = z
  .object({
    numerator: z.number().int().nonnegative(),
    denominator: z.number().int().nonnegative(),
    rate: z.number().nullable(),
  })
  .strict();
const correctedSemanticEndpointSchema = correctedEndpointSchema
  .extend({ applicable: z.boolean() })
  .strict();
const estimateSchema = z
  .object({
    denominator: z.number().int().nonnegative(),
    sum: z.number(),
    mean: z.number().nullable(),
  })
  .strict();
const latencyResourceSchema = z
  .object({
    observedAssetCount: z.number().int().nonnegative(),
    total: z.number().nonnegative(),
    realizedPerPlannedAsset: z
      .object({
        denominator: z.number().int().nonnegative(),
        mean: z.number().nullable(),
      })
      .strict(),
    conditionalPerBenchmarkCompleted: z
      .object({
        denominator: z.number().int().nonnegative(),
        total: z.number().nonnegative(),
        mean: z.number().nullable(),
      })
      .strict(),
  })
  .strict();
const costResourceSchema = z
  .object({
    knownValueCount: z.number().int().nonnegative(),
    expectedValueCount: z.number().int().nonnegative(),
    total: z.number().nullable(),
    realizedPerPlannedAsset: z
      .object({
        denominator: z.number().int().nonnegative(),
        mean: z.number().nullable(),
      })
      .strict(),
    conditionalPerBenchmarkCompleted: z
      .object({
        denominator: z.number().int().nonnegative(),
        knownValueCount: z.number().int().nonnegative(),
        total: z.number().nullable(),
        mean: z.number().nullable(),
      })
      .strict(),
  })
  .strict();
const correctedGraphRollupSchema = z
  .object({
    counts: z
      .object({
        planned: z.number().int().nonnegative(),
        referenceAvailable: z.number().int().nonnegative(),
        pipelineReachedScoring: z.number().int().nonnegative(),
        scored: z.number().int().nonnegative(),
        unscoredReferenceUnavailable: z.number().int().nonnegative(),
        unscoredArmFailed: z.number().int().nonnegative(),
      })
      .strict(),
    deployable: z
      .object({
        denominator: z.number().int().nonnegative(),
        failedBeforeScoringAssignedZero: z.number().int().nonnegative(),
        graphSimilarity: estimateSchema,
        columnAxisJaccard: estimateSchema,
        associationJaccard: estimateSchema,
      })
      .strict(),
    observedScoreOnly: z
      .object({
        graphSimilarity: estimateSchema,
        columnAxisJaccard: estimateSchema,
        associationJaccard: estimateSchema,
      })
      .strict(),
  })
  .strict();
const correctedAggregateArmSchema = z
  .object({
    plannedDenominator: z.number().int().nonnegative(),
    operationalEndpoints: z
      .object({
        providerAttempted: correctedEndpointSchema,
        providerResponded: correctedEndpointSchema,
        providerFailed: correctedEndpointSchema,
        semanticParseValid: correctedSemanticEndpointSchema,
        finalJsonParseValid: correctedEndpointSchema,
        schemaValid: correctedEndpointSchema,
        benchmarkCompleted: correctedEndpointSchema,
        executable: correctedEndpointSchema,
        nonempty: correctedEndpointSchema,
        deterministicPass: correctedEndpointSchema,
        graphReferenceAvailable: correctedEndpointSchema,
        graphScored: correctedEndpointSchema,
      })
      .strict(),
    graph: correctedGraphRollupSchema,
    resourceUse: z
      .object({
        latencyMs: latencyResourceSchema,
        catalogPricedUsd: costResourceSchema,
        apiEquivalentUsd: costResourceSchema,
      })
      .strict(),
    warningCount: z.number().int().nonnegative(),
    providerCallTotals: z
      .object({
        attempted: z.number().int().nonnegative(),
        responded: z.number().int().nonnegative(),
        failed: z.number().int().nonnegative(),
        withUsage: z.number().int().nonnegative(),
      })
      .strict(),
    usage: usageSchema,
    failureCodes: z.array(z.string()),
  })
  .strict();
const providerCallAccountingArmSchema = z
  .object({
    maximumAuthorized: z.number().int().nonnegative(),
    realized: z.number().int().nonnegative(),
  })
  .strict();
const providerCallAccountingSchema = z
  .object({
    maximumAuthorized: z.number().int().nonnegative(),
    realized: z.number().int().nonnegative(),
    perArm: z
      .object({
        baseline: providerCallAccountingArmSchema,
        staged: providerCallAccountingArmSchema,
        llmTranslationResearch: providerCallAccountingArmSchema,
      })
      .strict(),
  })
  .strict();
const correctedCompleteCaseMetricSchema = pairedQualitySchema
  .extend({ assets: z.array(z.string().min(1)) })
  .strict();
const correctedAssetArmSchema = z
  .object({
    providerAttempted: z.boolean(),
    providerResponded: z.boolean(),
    providerFailed: z.boolean(),
    providerAttempts: z.number().int().nonnegative(),
    providerResponses: z.number().int().nonnegative(),
    providerFailures: z.number().int().nonnegative(),
    callsWithUsage: z.number().int().nonnegative(),
    warningCount: z.number().int().nonnegative(),
    semanticParseValid: z.boolean().nullable(),
    finalJsonParseValid: z.boolean(),
    schemaValid: z.boolean(),
    benchmarkCompleted: z.boolean(),
    executable: z.boolean(),
    nonempty: z.boolean(),
    deterministicPass: z.boolean(),
    deterministicStatus: z.enum(["pass", "fail", "not_reached"]),
    durationMs: z.number().nullable(),
    usage: usageSchema.nullable(),
    failures: z.array(z.string()),
    graph: z
      .object({
        referenceAvailable: z.boolean(),
        status: z.enum([
          "scored",
          "unscored_reference_unavailable",
          "unscored_arm_failed",
        ]),
        graphSimilarity: z.number().min(0).max(1).nullable(),
        columnAxisJaccard: z.number().min(0).max(1).nullable(),
        associationJaccard: z.number().min(0).max(1).nullable(),
      })
      .strict(),
  })
  .strict();
export const correctedComparisonReportSchema = z
  .object({
    schemaVersion: z.literal("cell-role-comparison-v3"),
    reportGenerationVersion: z.literal("cell-role-report-v3"),
    provenance: z
      .object({
        runId: z.string().regex(RUN_ID_PATTERN),
        planDigest: sha256Schema,
        implementationDigest: sha256Schema,
        experimentImplementationDigest: sha256Schema.nullable(),
        evidenceManifestDigest: sha256Schema,
        graphReferenceEvidenceManifestDigests: z.array(sha256Schema).min(1),
        unitDigests: z.array(
          z
            .object({
              asset: z.string().min(1),
              unitDigest: sha256Schema,
            })
            .strict(),
        ),
        liveExecutionEvidence: z
          .array(
            z
              .object({
                asset: z.string().min(1),
                authorizationDigest: sha256Schema,
                executableDigest: sha256Schema,
                oauthReadinessDigest: sha256Schema,
                evidenceDigest: sha256Schema,
              })
              .strict(),
          )
          .optional(),
      })
      .strict(),
    denominators: z
      .object({
        plannedPairs: z.number().int().nonnegative(),
        plannedAssetsPerArm: z.number().int().nonnegative(),
        benchmarkCompletedPairs: z.number().int().nonnegative(),
        completeCaseQualityPairs: z.number().int().nonnegative(),
        completeCaseQualityAssets: z.array(z.string().min(1)),
      })
      .strict(),
    primaryEndpoint: z.literal("deterministic_pass_over_planned_assets"),
    arms: z
      .object({
        baseline: correctedAggregateArmSchema,
        staged: correctedAggregateArmSchema,
      })
      .strict(),
    providerCallAccounting: providerCallAccountingSchema.optional(),
    researchArms: z
      .object({
        llmTranslationResearch: correctedAggregateArmSchema,
      })
      .strict()
      .optional(),
    pairedIntentionToTreatDeterministic: z
      .object({
        denominator: z.number().int().nonnegative(),
        wins: z.number().int().nonnegative(),
        ties: z.number().int().nonnegative(),
        losses: z.number().int().nonnegative(),
        pairs: z.array(
          z
            .object({
              asset: z.string().min(1),
              baselinePass: z.boolean(),
              stagedPass: z.boolean(),
              outcome: z.enum(["win", "tie", "loss"]),
            })
            .strict(),
        ),
      })
      .strict(),
    completeCasePairedQualityMetrics: z
      .object({
        cell_exact_match_rate: correctedCompleteCaseMetricSchema,
        address_conditioned_cell_match_rate: correctedCompleteCaseMetricSchema,
        value_address_f1: correctedCompleteCaseMetricSchema,
        full_row_header_match_rate: correctedCompleteCaseMetricSchema,
        full_row_with_value_match_rate: correctedCompleteCaseMetricSchema,
      })
      .strict(),
    assets: z.array(
      z
        .object({
          asset: z.string().min(1),
          unitDigest: sha256Schema,
          benchmarkCompletedPair: z.boolean(),
          baseline: correctedAssetArmSchema,
          staged: correctedAssetArmSchema,
          llmTranslationResearch: correctedAssetArmSchema.optional(),
        })
        .strict(),
    ),
  })
  .strict()
  .superRefine((value, ctx) => {
    const issue = (message: string, path: Array<string | number> = []) =>
      ctx.addIssue({ code: "custom", message, path });
    const planned = value.denominators.plannedPairs;
    if (
      value.denominators.plannedAssetsPerArm !== planned ||
      value.assets.length !== planned ||
      value.provenance.unitDigests.length !== planned
    ) {
      issue("Corrected report planned denominators do not reconcile.");
    }
    const expectedUnitBindings = value.assets.map((asset) => ({
      asset: asset.asset,
      unitDigest: asset.unitDigest,
    }));
    if (
      JSON.stringify(expectedUnitBindings) !==
      JSON.stringify(value.provenance.unitDigests)
    ) {
      issue("Corrected report asset/unit bindings do not reconcile.");
    }
    const completeCaseAssets = value.assets
      .filter((asset) => asset.benchmarkCompletedPair)
      .map((asset) => asset.asset);
    if (
      value.denominators.completeCaseQualityPairs !==
        value.denominators.completeCaseQualityAssets.length ||
      value.denominators.benchmarkCompletedPairs !==
        value.denominators.completeCaseQualityPairs ||
      JSON.stringify(value.denominators.completeCaseQualityAssets) !==
        JSON.stringify(completeCaseAssets)
    ) {
      issue("Corrected report complete-case denominators do not reconcile.");
    }
    const paired = value.pairedIntentionToTreatDeterministic;
    if (
      paired.denominator !== planned ||
      paired.pairs.length !== planned ||
      paired.wins + paired.ties + paired.losses !== paired.denominator
    ) {
      issue("Paired deterministic outcomes do not reconcile.");
    }
    for (const [index, pair] of paired.pairs.entries()) {
      const asset = value.assets[index];
      const expectedOutcome =
        pair.stagedPass === pair.baselinePass
          ? "tie"
          : pair.stagedPass
            ? "win"
            : "loss";
      if (
        !asset ||
        pair.asset !== asset.asset ||
        pair.baselinePass !== asset.baseline.deterministicPass ||
        pair.stagedPass !== asset.staged.deterministicPass ||
        pair.outcome !== expectedOutcome
      ) {
        issue(`Paired deterministic row ${index} does not reconcile.`);
      }
    }
    if (
      paired.wins !==
        paired.pairs.filter((pair) => pair.outcome === "win").length ||
      paired.ties !==
        paired.pairs.filter((pair) => pair.outcome === "tie").length ||
      paired.losses !==
        paired.pairs.filter((pair) => pair.outcome === "loss").length
    ) {
      issue("Paired deterministic aggregate counts do not reconcile.");
    }
    const researchAssetsPresent = value.assets.some(
      (asset) => asset.llmTranslationResearch !== undefined,
    );
    const researchAssetsComplete = value.assets.every(
      (asset) => asset.llmTranslationResearch !== undefined,
    );
    if (
      Boolean(value.researchArms) !== researchAssetsPresent ||
      (researchAssetsPresent && !researchAssetsComplete)
    ) {
      issue("Research arm aggregate/assets do not reconcile.");
    }
    const reportArms = {
      ...value.arms,
      ...(value.researchArms && researchAssetsComplete
        ? {
            llmTranslationResearch: value.researchArms.llmTranslationResearch,
          }
        : {}),
    };
    if (value.providerCallAccounting) {
      const accounting = value.providerCallAccounting;
      const realized = {
        baseline: value.assets.reduce(
          (sum, asset) => sum + asset.baseline.providerAttempts,
          0,
        ),
        staged: value.assets.reduce(
          (sum, asset) => sum + asset.staged.providerAttempts,
          0,
        ),
        llmTranslationResearch: value.assets.reduce(
          (sum, asset) =>
            sum + (asset.llmTranslationResearch?.providerAttempts ?? 0),
          0,
        ),
      };
      const realizedTotal =
        realized.baseline + realized.staged + realized.llmTranslationResearch;
      if (
        accounting.realized !== realizedTotal ||
        accounting.maximumAuthorized !==
          Object.values(accounting.perArm).reduce(
            (sum, arm) => sum + arm.maximumAuthorized,
            0,
          ) ||
        accounting.realized !==
          Object.values(accounting.perArm).reduce(
            (sum, arm) => sum + arm.realized,
            0,
          ) ||
        accounting.perArm.baseline.realized !== realized.baseline ||
        accounting.perArm.staged.realized !== realized.staged ||
        accounting.perArm.llmTranslationResearch.realized !==
          realized.llmTranslationResearch ||
        Object.values(accounting.perArm).some(
          (arm) => arm.realized > arm.maximumAuthorized,
        )
      ) {
        issue("Provider call accounting does not reconcile.");
      }
    }
    for (const [armName, arm] of Object.entries(reportArms)) {
      if (arm.plannedDenominator !== planned) {
        issue(`Arm ${armName} planned denominator mismatch.`);
      }
      const assetArms = value.assets.map((asset) =>
        armName === "baseline"
          ? asset.baseline
          : armName === "staged"
            ? asset.staged
            : asset.llmTranslationResearch!,
      );
      for (const [name, endpoint] of Object.entries(arm.operationalEndpoints)) {
        if (endpoint.numerator > endpoint.denominator) {
          issue(`Endpoint ${armName}.${name} numerator exceeds denominator.`);
        }
        const expectedRate = endpoint.denominator
          ? endpoint.numerator / endpoint.denominator
          : null;
        if (
          name === "semanticParseValid" &&
          "applicable" in endpoint &&
          !endpoint.applicable
        ) {
          if (
            endpoint.numerator !== 0 ||
            endpoint.denominator !== 0 ||
            endpoint.rate !== null
          ) {
            issue(`Non-applicable semantic endpoint ${armName} is nonempty.`);
          }
        } else if (endpoint.rate !== expectedRate) {
          issue(`Endpoint ${armName}.${name} rate mismatch.`);
        }
      }
      const expectedEndpointCounts: Record<string, number> = {
        providerAttempted: assetArms.filter((entry) => entry.providerAttempted)
          .length,
        providerResponded: assetArms.filter((entry) => entry.providerResponded)
          .length,
        providerFailed: assetArms.filter((entry) => entry.providerFailed)
          .length,
        semanticParseValid: assetArms.filter(
          (entry) => entry.semanticParseValid === true,
        ).length,
        finalJsonParseValid: assetArms.filter(
          (entry) => entry.finalJsonParseValid,
        ).length,
        schemaValid: assetArms.filter((entry) => entry.schemaValid).length,
        benchmarkCompleted: assetArms.filter(
          (entry) => entry.benchmarkCompleted,
        ).length,
        executable: assetArms.filter((entry) => entry.executable).length,
        nonempty: assetArms.filter((entry) => entry.nonempty).length,
        deterministicPass: assetArms.filter((entry) => entry.deterministicPass)
          .length,
        graphReferenceAvailable: assetArms.filter(
          (entry) => entry.graph.referenceAvailable,
        ).length,
        graphScored: assetArms.filter(
          (entry) => entry.graph.status === "scored",
        ).length,
      };
      for (const [name, expected] of Object.entries(expectedEndpointCounts)) {
        const endpoint =
          arm.operationalEndpoints[
            name as keyof typeof arm.operationalEndpoints
          ];
        if (endpoint.numerator !== expected) {
          issue(`Endpoint ${armName}.${name} asset count mismatch.`);
        }
        if (
          !(name === "semanticParseValid" && armName === "baseline") &&
          endpoint.denominator !== planned
        ) {
          issue(`Endpoint ${armName}.${name} planned denominator mismatch.`);
        }
      }
      const expectedCallTotals = {
        attempted: assetArms.reduce(
          (sum, entry) => sum + entry.providerAttempts,
          0,
        ),
        responded: assetArms.reduce(
          (sum, entry) => sum + entry.providerResponses,
          0,
        ),
        failed: assetArms.reduce(
          (sum, entry) => sum + entry.providerFailures,
          0,
        ),
        withUsage: assetArms.reduce(
          (sum, entry) => sum + entry.callsWithUsage,
          0,
        ),
      };
      if (
        JSON.stringify(arm.providerCallTotals) !==
        JSON.stringify(expectedCallTotals)
      ) {
        issue(`Provider call totals for ${armName} do not reconcile.`);
      }
      if (
        arm.warningCount !==
        assetArms.reduce((sum, entry) => sum + entry.warningCount, 0)
      ) {
        issue(`Warning count for ${armName} does not reconcile.`);
      }
      const expectedFailures = assetArms
        .flatMap((entry) => entry.failures)
        .sort();
      if (
        JSON.stringify(arm.failureCodes) !== JSON.stringify(expectedFailures)
      ) {
        issue(`Failure codes for ${armName} do not reconcile.`);
      }
      for (const usageKey of [
        "promptTokens",
        "completionTokens",
        "reasoningTokens",
        "totalTokens",
        "cachedTokens",
        "cacheCreationInputTokens",
        "cacheReadInputTokens",
        "cacheWriteInputTokens",
        "catalogPricedUsd",
        "apiEquivalentUsd",
      ] as const) {
        const values = assetArms
          .map((entry) => entry.usage?.[usageKey])
          .filter((entry): entry is number => typeof entry === "number");
        const expected = values.length
          ? values.reduce((sum, entry) => sum + entry, 0)
          : undefined;
        if (arm.usage[usageKey] !== expected) {
          issue(`Usage ${armName}.${usageKey} does not reconcile.`);
        }
      }
      if (arm.usage.usageSource !== undefined) {
        issue(`Aggregate usage source for ${armName} must be omitted.`);
      }
      const counts = arm.graph.counts;
      if (
        counts.planned !== planned ||
        counts.referenceAvailable + counts.unscoredReferenceUnavailable !==
          counts.planned ||
        counts.scored + counts.unscoredArmFailed !==
          counts.referenceAvailable ||
        arm.graph.deployable.denominator !== counts.referenceAvailable ||
        arm.graph.deployable.graphSimilarity.denominator !==
          counts.referenceAvailable ||
        arm.graph.deployable.columnAxisJaccard.denominator !==
          counts.referenceAvailable ||
        arm.graph.deployable.associationJaccard.denominator !==
          counts.referenceAvailable ||
        arm.graph.deployable.failedBeforeScoringAssignedZero !==
          counts.unscoredArmFailed
      ) {
        issue(`Graph denominators for ${armName} do not reconcile.`);
      }
      for (const population of [
        arm.graph.deployable,
        arm.graph.observedScoreOnly,
      ]) {
        for (const metric of [
          population.graphSimilarity,
          population.columnAxisJaccard,
          population.associationJaccard,
        ]) {
          if (
            metric.mean !==
            (metric.denominator ? metric.sum / metric.denominator : null)
          ) {
            issue(`Graph estimate for ${armName} does not reconcile.`);
          }
          if (metric.mean !== null && (metric.mean < 0 || metric.mean > 1)) {
            issue(`Graph estimate for ${armName} is outside [0,1].`);
          }
        }
      }
      const expectedGraphCounts = {
        pipelineReachedScoring: assetArms.filter(
          (entry) => entry.benchmarkCompleted,
        ).length,
        scored: assetArms.filter((entry) => entry.graph.status === "scored")
          .length,
        unscoredReferenceUnavailable: assetArms.filter(
          (entry) => entry.graph.status === "unscored_reference_unavailable",
        ).length,
        unscoredArmFailed: assetArms.filter(
          (entry) => entry.graph.status === "unscored_arm_failed",
        ).length,
      };
      if (
        counts.pipelineReachedScoring !==
          expectedGraphCounts.pipelineReachedScoring ||
        counts.scored !== expectedGraphCounts.scored ||
        counts.unscoredReferenceUnavailable !==
          expectedGraphCounts.unscoredReferenceUnavailable ||
        counts.unscoredArmFailed !== expectedGraphCounts.unscoredArmFailed
      ) {
        issue(`Graph asset counts for ${armName} do not reconcile.`);
      }
      for (const [assetKey, reportKey] of [
        ["graphSimilarity", "graphSimilarity"],
        ["columnAxisJaccard", "columnAxisJaccard"],
        ["associationJaccard", "associationJaccard"],
      ] as const) {
        const observedValues = assetArms
          .filter((entry) => entry.graph.status === "scored")
          .map((entry) => entry.graph[assetKey] as number);
        const observedSum = observedValues.reduce(
          (sum, entry) => sum + entry,
          0,
        );
        if (
          arm.graph.observedScoreOnly[reportKey].sum !== observedSum ||
          arm.graph.deployable[reportKey].sum !== observedSum
        ) {
          issue(`Graph ${armName}.${reportKey} asset sum mismatch.`);
        }
      }
      if (
        arm.graph.observedScoreOnly.graphSimilarity.denominator !==
          counts.scored ||
        arm.graph.observedScoreOnly.columnAxisJaccard.denominator !==
          counts.scored ||
        arm.graph.observedScoreOnly.associationJaccard.denominator !==
          counts.scored
      ) {
        issue(`Observed graph denominators for ${armName} do not reconcile.`);
      }
      const durations = assetArms
        .map((entry) => entry.durationMs)
        .filter((entry): entry is number => entry !== null);
      const completedAssets = assetArms.filter(
        (entry) => entry.benchmarkCompleted,
      );
      const completedDurations = completedAssets
        .map((entry) => entry.durationMs)
        .filter((entry): entry is number => entry !== null);
      const latency = arm.resourceUse.latencyMs;
      const durationTotal = durations.reduce((sum, entry) => sum + entry, 0);
      const completedDurationTotal = completedDurations.reduce(
        (sum, entry) => sum + entry,
        0,
      );
      if (
        latency.observedAssetCount !== durations.length ||
        latency.total !== durationTotal ||
        latency.realizedPerPlannedAsset.denominator !== planned ||
        latency.realizedPerPlannedAsset.mean !==
          (durations.length === planned && planned
            ? durationTotal / planned
            : null) ||
        completedDurations.length !== completedAssets.length ||
        latency.conditionalPerBenchmarkCompleted.denominator !==
          completedAssets.length ||
        latency.conditionalPerBenchmarkCompleted.total !==
          completedDurationTotal ||
        latency.conditionalPerBenchmarkCompleted.mean !==
          (completedDurations.length
            ? completedDurationTotal / completedDurations.length
            : null)
      ) {
        issue(`Latency resources for ${armName} do not reconcile.`);
      }
      for (const key of ["catalogPricedUsd", "apiEquivalentUsd"] as const) {
        const resource = arm.resourceUse[key];
        const values = assetArms
          .map((entry) => entry.usage?.[key])
          .filter((entry): entry is number => typeof entry === "number");
        const completedValues = assetArms
          .filter((entry) => entry.benchmarkCompleted)
          .map((entry) => entry.usage?.[key])
          .filter((entry): entry is number => typeof entry === "number");
        const expectedTotal =
          values.length === planned
            ? values.reduce((sum, entry) => sum + entry, 0)
            : null;
        const completedDenominator = assetArms.filter(
          (entry) => entry.benchmarkCompleted,
        ).length;
        const expectedCompletedTotal =
          completedValues.length === completedDenominator
            ? completedValues.reduce((sum, entry) => sum + entry, 0)
            : null;
        if (
          resource.knownValueCount !== values.length ||
          resource.expectedValueCount !== planned ||
          resource.total !== expectedTotal ||
          resource.realizedPerPlannedAsset.denominator !== planned ||
          resource.realizedPerPlannedAsset.mean !==
            (expectedTotal !== null && planned
              ? expectedTotal / planned
              : null) ||
          resource.conditionalPerBenchmarkCompleted.denominator !==
            completedDenominator ||
          resource.conditionalPerBenchmarkCompleted.knownValueCount !==
            completedValues.length ||
          resource.conditionalPerBenchmarkCompleted.total !==
            expectedCompletedTotal ||
          resource.conditionalPerBenchmarkCompleted.mean !==
            (expectedCompletedTotal !== null && completedDenominator
              ? expectedCompletedTotal / completedDenominator
              : null)
        ) {
          issue(`Cost resources ${armName}.${key} do not reconcile.`);
        }
      }
    }
    for (const asset of value.assets) {
      if (
        asset.benchmarkCompletedPair !==
        (asset.baseline.benchmarkCompleted && asset.staged.benchmarkCompleted)
      ) {
        issue(`Benchmark-completed pair mismatch for ${asset.asset}.`);
      }
      const assetArms: Array<
        [
          "baseline" | "staged" | "llm-translation-research",
          typeof asset.baseline,
        ]
      > = [
        ["baseline", asset.baseline],
        ["staged", asset.staged],
      ];
      if (asset.llmTranslationResearch) {
        assetArms.push([
          "llm-translation-research",
          asset.llmTranslationResearch,
        ]);
      }
      for (const [armName, arm] of assetArms) {
        const values = [
          arm.graph.graphSimilarity,
          arm.graph.columnAxisJaccard,
          arm.graph.associationJaccard,
        ];
        if (
          (arm.graph.status === "scored" &&
            values.some((entry) => entry === null)) ||
          (arm.graph.status !== "scored" &&
            values.some((entry) => entry !== null)) ||
          (arm.graph.status === "unscored_reference_unavailable" &&
            arm.graph.referenceAvailable) ||
          (arm.graph.status === "unscored_arm_failed" &&
            !arm.graph.referenceAvailable)
        ) {
          issue(`Asset graph status mismatch for ${asset.asset}:${armName}.`);
        }
        if (
          arm.providerAttempted !== arm.providerAttempts > 0 ||
          arm.providerResponded !== arm.providerResponses > 0 ||
          arm.providerFailed !== arm.providerFailures > 0 ||
          arm.providerResponses > arm.providerAttempts ||
          arm.providerFailures > arm.providerAttempts ||
          arm.callsWithUsage > arm.providerResponses
        ) {
          issue(
            `Asset provider accounting mismatch for ${asset.asset}:${armName}.`,
          );
        }
        if (
          arm.deterministicPass !== (arm.deterministicStatus === "pass") ||
          (arm.finalJsonParseValid && !arm.providerResponded) ||
          (arm.schemaValid && !arm.finalJsonParseValid) ||
          (arm.nonempty && !arm.executable) ||
          ((arm.executable || arm.nonempty || arm.deterministicPass) &&
            !arm.benchmarkCompleted) ||
          (armName !== "baseline" &&
            arm.benchmarkCompleted &&
            arm.semanticParseValid !== true) ||
          (armName !== "baseline" &&
            arm.semanticParseValid === true &&
            !arm.providerResponded) ||
          (arm.benchmarkCompleted &&
            (!arm.finalJsonParseValid ||
              !arm.schemaValid ||
              !arm.executable ||
              arm.durationMs === null)) ||
          (arm.deterministicStatus === "not_reached") !==
            !arm.benchmarkCompleted ||
          (arm.graph.status === "scored" && !arm.benchmarkCompleted) ||
          (arm.graph.status === "unscored_arm_failed" && arm.benchmarkCompleted)
        ) {
          issue(`Asset stage status mismatch for ${asset.asset}:${armName}.`);
        }
      }
    }
    for (const [name, metric] of Object.entries(
      value.completeCasePairedQualityMetrics,
    )) {
      const deltas = metric.pairs.map((pair) => pair.delta);
      if (
        metric.denominator !== completeCaseAssets.length ||
        JSON.stringify(metric.assets) !== JSON.stringify(completeCaseAssets) ||
        JSON.stringify(metric.pairs.map((pair) => pair.asset)) !==
          JSON.stringify(completeCaseAssets) ||
        metric.pairs.some(
          (pair) =>
            pair.baseline < 0 ||
            pair.baseline > 1 ||
            pair.staged < 0 ||
            pair.staged > 1 ||
            pair.delta !== pair.staged - pair.baseline,
        ) ||
        metric.wins !== deltas.filter((delta) => delta > 0).length ||
        metric.ties !== deltas.filter((delta) => delta === 0).length ||
        metric.losses !== deltas.filter((delta) => delta < 0).length ||
        metric.meanDelta !==
          (deltas.length
            ? deltas.reduce((sum, delta) => sum + delta, 0) / deltas.length
            : null)
      ) {
        issue(`Complete-case quality metric ${name} does not reconcile.`);
      }
    }
  });

export const comparisonReportSchema = z.union([
  legacyComparisonReportSchema,
  correctedComparisonReportSchema,
]);

export const historicalReportingManifestSchema = z
  .object({
    schemaVersion: z.literal("cell-role-historical-reporting-manifest-v1"),
    reportingLayoutVersion: z.literal("reporting-v2"),
    historicalLabel: z.enum(["v1", "v2"]),
    runId: z.string().regex(RUN_ID_PATTERN),
    sourceEvidence: z
      .object({
        rootPath: relativeEvidencePathSchema,
        rootSha256: sha256Schema,
        manifestPath: relativeEvidencePathSchema,
        manifestSha256: sha256Schema,
        graphReferenceManifestSha256s: z.array(sha256Schema).min(1),
      })
      .strict(),
    reportGenerationVersion: z.literal("cell-role-report-v3"),
    implementationDigest: sha256Schema,
    artifacts: z
      .array(
        z
          .object({
            path: z.enum(["comparison.json", "summary.md"]),
            sha256: sha256Schema,
            bytes: z.number().int().positive(),
            mediaType: z.enum(["application/json", "text/markdown"]),
            schemaType: z.enum([
              "cell-role-comparison-v3",
              "cell-role-comparison-summary-v1",
            ]),
          })
          .strict(),
      )
      .length(2),
  })
  .strict();

export const historicalReportingIndexSchema = z
  .object({
    schemaVersion: z.literal("cell-role-historical-reporting-index-v1"),
    reportingLayoutVersion: z.literal("reporting-v2"),
    reports: z
      .array(
        z
          .object({
            historicalLabel: z.enum(["v1", "v2"]),
            runId: z.string().regex(RUN_ID_PATTERN),
            manifestPath: relativeEvidencePathSchema,
            manifestSha256: sha256Schema,
            manifestBytes: z.number().int().positive(),
          })
          .strict(),
      )
      .length(2),
  })
  .strict();

export const authorizationRecordSchema = z
  .object({
    schemaVersion: z.literal("cell-role-authorization-v1"),
    authorizationId: z.string().min(1),
    planDigest: sha256Schema,
    provenanceDigest: sha256Schema,
    authorizedAt: z.string().datetime(),
    expiresAt: z.string().datetime(),
    providerAdapter: z.literal("pi-json-v1"),
    maximumCalls: z.number().int().positive(),
    stages: z.array(z.enum(["baseline", "semantics", "translation"])).min(1),
    approvedBy: z.string().min(1),
  })
  .strict();

export const evidenceRoles = [
  "plan",
  "authorization",
  "attempt",
  "unit-result",
  "comparison-report",
  "benchmark-summary",
  "benchmark-diff",
  "candidate-recipe",
  "operation-summary",
  "sanitized-derivative",
] as const;
export type EvidenceRole = (typeof evidenceRoles)[number];

export const evidenceManifestEntrySchema = z
  .object({
    path: relativeEvidencePathSchema,
    sha256: sha256Schema,
    bytes: z.number().int().nonnegative(),
    mediaType: z.enum(["application/json", "text/csv", "text/plain"]),
    schemaType: z.string().min(1),
    role: z.enum(evidenceRoles),
    planDigest: sha256Schema,
    unitDigest: sha256Schema.optional(),
    asset: z.string().min(1).optional(),
    attemptId: z.string().min(1).optional(),
    arm: z.enum(["baseline", "staged", "llm-translation-research"]).optional(),
    stage: z.enum(["baseline", "semantics", "translation"]).optional(),
    sourceSha256: sha256Schema.optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (
      [
        "attempt",
        "unit-result",
        "benchmark-summary",
        "benchmark-diff",
        "candidate-recipe",
      ].includes(value.role)
    ) {
      if (!value.unitDigest || !value.asset)
        ctx.addIssue({
          code: "custom",
          message: `${value.role} requires unitDigest and asset.`,
        });
    }
    if (
      value.role === "attempt" &&
      (!value.attemptId || !value.arm || !value.stage)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Attempt requires attemptId, arm, and stage.",
      });
    }
    if (
      ["benchmark-summary", "benchmark-diff", "candidate-recipe"].includes(
        value.role,
      ) &&
      !value.arm
    ) {
      ctx.addIssue({ code: "custom", message: `${value.role} requires arm.` });
    }
    if (value.role === "sanitized-derivative" && !value.sourceSha256) {
      ctx.addIssue({
        code: "custom",
        message: "Sanitized derivative requires sourceSha256.",
      });
    }
  });
export type EvidenceManifestEntry = z.infer<typeof evidenceManifestEntrySchema>;

function evidenceManifestLogicalIdentity(entry: EvidenceManifestEntry): string {
  if (entry.role === "unit-result") {
    return `${entry.role}:${entry.planDigest}:${entry.asset}`;
  }
  if (entry.role === "attempt") {
    return `${entry.role}:${entry.planDigest}:${entry.unitDigest}:${entry.arm}:${entry.stage}:${entry.attemptId}`;
  }
  if (
    ["benchmark-summary", "benchmark-diff", "candidate-recipe"].includes(
      entry.role,
    )
  ) {
    return `${entry.role}:${entry.planDigest}:${entry.unitDigest}:${entry.arm}`;
  }
  return `${entry.role}:${entry.path}`;
}

export const evidenceManifestSchema = z
  .object({
    schemaVersion: z.literal("cell-role-evidence-manifest-v1"),
    runId: z.string().regex(RUN_ID_PATTERN),
    planDigest: sha256Schema,
    historical: z.boolean(),
    legacyProvenanceLimitations: z.array(z.string()),
    entries: z.array(evidenceManifestEntrySchema).min(1),
  })
  .strict()
  .superRefine((value, ctx) => {
    const paths = value.entries.map((entry) => entry.path);
    if (new Set(paths).size !== paths.length)
      ctx.addIssue({ code: "custom", message: "Duplicate manifest path." });
    const identities = value.entries.map(evidenceManifestLogicalIdentity);
    if (new Set(identities).size !== identities.length)
      ctx.addIssue({ code: "custom", message: "Duplicate manifest identity." });
    if (value.entries.some((entry) => entry.planDigest !== value.planDigest)) {
      ctx.addIssue({
        code: "custom",
        message: "Manifest entry plan digest mismatch.",
      });
    }
    const sorted = [...paths].sort((a, b) => a.localeCompare(b));
    if (paths.some((value, index) => value !== sorted[index])) {
      ctx.addIssue({
        code: "custom",
        message: "Manifest entries must be path-sorted.",
      });
    }
  });
export type EvidenceManifest = z.infer<typeof evidenceManifestSchema>;

export const evidenceRootSchema = z
  .object({
    schemaVersion: z.literal("cell-role-evidence-root-v1"),
    runId: z.string().regex(RUN_ID_PATTERN),
    planDigest: sha256Schema,
    manifestPath: z.literal("manifest.json"),
    manifestSha256: sha256Schema,
    manifestBytes: z.number().int().positive(),
    payloadEntryCount: z.number().int().positive(),
  })
  .strict();

export const evidenceIndexSchema = z
  .object({
    schemaVersion: z.literal("cell-role-evidence-index-v1"),
    runs: z
      .array(
        z
          .object({
            runId: z.string().regex(RUN_ID_PATTERN),
            rootPath: relativeEvidencePathSchema,
            rootSha256: sha256Schema,
            rootBytes: z.number().int().positive(),
            rootDigestPath: relativeEvidencePathSchema,
            rootDigestSha256: sha256Schema,
            rootDigestBytes: z.number().int().positive(),
            manifestSha256: sha256Schema,
          })
          .strict(),
      )
      .min(1),
  })
  .strict();

const SENSITIVE_ASSIGNMENT_KEY =
  "(?:api[_-]?key|authorization|password|secret|device[_-]?code|auth[_-]?cache|bearer|token|[A-Za-z][A-Za-z0-9_-]*token)";
const SENSITIVE_TEXT = [
  /\bBearer\s+[^\s,;]+/i,
  /\bBasic\s+[A-Za-z0-9+/=]{8,}/i,
  /\b(?:sk|key)-[A-Za-z0-9_-]{8,}\b/i,
  new RegExp(`["']${SENSITIVE_ASSIGNMENT_KEY}["']\\s*:\\s*["'][^"']+["']`, "i"),
  new RegExp(`\\b${SENSITIVE_ASSIGNMENT_KEY}\\s*[:=]\\s*[^\\s,;]+`, "i"),
  /(?:^|[^A-Za-z0-9])(?:\/Users\/[^/\s<]+|\/home\/[^/\s<]+|[A-Za-z]:\\Users\\[^\\\s<]+)/,
];

export function isSensitiveEvidenceKey(key: string): boolean {
  const normalized = key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
  return (
    /^(?:api[_-]?key|authorization|password|secret|device[_-]?code|auth[_-]?cache|bearer|token)$/.test(
      normalized,
    ) ||
    normalized.endsWith("_token") ||
    normalized.endsWith("-token") ||
    normalized.endsWith("token")
  );
}

export function redactSensitiveEvidenceText(value: string): string {
  return value
    .replace(/Bearer\s+[^\s,;]+/gi, "Bearer [REDACTED]")
    .replace(/Basic\s+[^\s,;]+/gi, "Basic [REDACTED]")
    .replace(/\b(?:sk|key)-[A-Za-z0-9_-]{4,}\b/gi, "[REDACTED]")
    .replace(
      new RegExp(
        `(["']?)(${SENSITIVE_ASSIGNMENT_KEY})\\1(\\s*[:=]\\s*)(["']?)[^\\s,;"']+\\4`,
        "gi",
      ),
      "$1$2$1$3$4[REDACTED]$4",
    );
}

export function assertSafeEvidence(value: unknown, location = "$"): void {
  if (typeof value === "string") {
    if (SENSITIVE_TEXT.some((pattern) => pattern.test(value)))
      throw new Error(`UNSAFE_EVIDENCE: sensitive value at ${location}.`);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((entry, index) =>
      assertSafeEvidence(entry, `${location}[${index}]`),
    );
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, entry] of Object.entries(
      value as Record<string, unknown>,
    )) {
      if (isSensitiveEvidenceKey(key))
        throw new Error(
          `UNSAFE_EVIDENCE: sensitive key at ${location}.${key}.`,
        );
      assertSafeEvidence(entry, `${location}.${key}`);
    }
  }
}
