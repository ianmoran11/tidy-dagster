import type { LlmUsage } from "../../../src/lib/llm/types";
import { digestCanonicalJson } from "./artifact-io";
import type { ArmResult, PairedAssetResult, ProviderCallBudget } from "./types";

export const CORRECTED_REPORT_SCHEMA_VERSION =
  "cell-role-comparison-v3" as const;
export const REPORT_GENERATION_VERSION = "cell-role-report-v3" as const;

const QUALITY_METRIC_KEYS = [
  "cell_exact_match_rate",
  "address_conditioned_cell_match_rate",
  "value_address_f1",
  "full_row_header_match_rate",
  "full_row_with_value_match_rate",
] as const;
const GRAPH_METRIC_KEYS = [
  "graph_similarity",
  "column_axis_jaccard",
  "association_jaccard",
] as const;

type QualityMetricKey = (typeof QUALITY_METRIC_KEYS)[number];
type GraphMetricKey = (typeof GRAPH_METRIC_KEYS)[number];

type BinaryEndpoint = {
  numerator: number;
  denominator: number;
  rate: number | null;
};

type GraphReferenceAvailability = Record<string, boolean>;

export type CorrectedComparisonInput = {
  runId: string;
  planDigest: string;
  implementationDigest: string;
  experimentImplementationDigest: string | null;
  evidenceManifestDigest: string;
  graphReferenceEvidenceManifestDigests: string[];
  unitDigests: Array<{ asset: string; unitDigest: string }>;
  graphReferenceAvailability: GraphReferenceAvailability;
  results: PairedAssetResult[];
  providerCallBudget?: ProviderCallBudget;
};

export type CorrectedComparisonReport = ReturnType<
  typeof buildCorrectedComparisonReport
>;

/**
 * Immutable legacy builder used only to regenerate comparison-v1/v2 bytes.
 * Its historical field names and benchmark-completion interpretation cannot
 * be changed without invalidating the PRD 001 archive.
 */
export function buildComparisonReport(results: PairedAssetResult[]) {
  const pairs = [...results].sort(compareAssets);
  const benchmarkCompletedPairs = pairs.filter(
    (pair) => pair.baseline.metrics.benchmark && pair.staged.metrics.benchmark,
  );
  const provenanceDigests = new Set(
    pairs
      .map((pair) => pair.provenanceDigest)
      .filter((digest): digest is string => Boolean(digest)),
  );
  if (
    provenanceDigests.size > 1 ||
    (provenanceDigests.size === 1 &&
      pairs.some((pair) => !pair.provenanceDigest))
  ) {
    throw new Error("RESULT_PROVENANCE_MISMATCH");
  }
  const provenanceDigest = [...provenanceDigests][0];
  const liveExecutionEvidence = pairs
    .filter((pair) => Boolean(pair.liveExecution))
    .map((pair) => ({
      asset: pair.asset,
      authorizationDigest: pair.liveExecution!.authorizationDigest,
      executableDigest: pair.liveExecution!.executableDigest,
      oauthReadinessDigest: pair.liveExecution!.oauthReadinessDigest,
      evidenceDigest: digestCanonicalJson(pair.liveExecution),
    }));
  if (
    liveExecutionEvidence.length > 0 &&
    liveExecutionEvidence.length !== pairs.length
  ) {
    throw new Error("MIXED_LIVE_EXECUTION_EVIDENCE");
  }
  return {
    schemaVersion: provenanceDigest
      ? "cell-role-comparison-v2"
      : "cell-role-comparison-v1",
    ...(provenanceDigest ? { provenanceDigest } : {}),
    ...(liveExecutionEvidence.length ? { liveExecutionEvidence } : {}),
    denominators: {
      intentionToTreatPairs: pairs.length,
      successfulPairs: benchmarkCompletedPairs.length,
    },
    arms: {
      baseline: aggregateLegacyArm(
        pairs.map((pair) => pair.baseline),
        pairs.length,
      ),
      staged: aggregateLegacyArm(
        pairs.map((pair) => pair.staged),
        pairs.length,
      ),
    },
    completeCasePairedQualityMetrics: Object.fromEntries(
      QUALITY_METRIC_KEYS.map((key) => [
        key,
        legacyPairedMetric(benchmarkCompletedPairs, key),
      ]),
    ),
    assets: pairs.map((pair) => ({
      asset: pair.asset,
      baseline: summarizeLegacyArm(pair.baseline),
      staged: summarizeLegacyArm(pair.staged),
      successfulPair: Boolean(
        pair.baseline.metrics.benchmark && pair.staged.metrics.benchmark,
      ),
    })),
  };
}

export function buildCorrectedComparisonReport(
  input: CorrectedComparisonInput,
) {
  const plannedUnits = [...input.unitDigests].sort(compareAssets);
  assertUnique(
    plannedUnits.map((unit) => unit.asset),
    "PLANNED_ASSET",
  );
  assertUnique(
    plannedUnits.map((unit) => unit.unitDigest),
    "PLANNED_UNIT_DIGEST",
  );
  assertUnique(
    input.graphReferenceEvidenceManifestDigests,
    "GRAPH_REFERENCE_MANIFEST_DIGEST",
  );
  if (!input.graphReferenceEvidenceManifestDigests.length) {
    throw new Error("GRAPH_REFERENCE_EVIDENCE_REQUIRED");
  }

  const plannedByAsset = new Map(
    plannedUnits.map((unit) => [unit.asset, unit.unitDigest]),
  );
  const resultsByAsset = new Map<string, PairedAssetResult>();
  for (const result of input.results) {
    if (!plannedByAsset.has(result.asset)) {
      throw new Error(`UNEXPECTED_RESULT_ASSET: ${result.asset}`);
    }
    if (resultsByAsset.has(result.asset)) {
      throw new Error(`DUPLICATE_RESULT_ASSET: ${result.asset}`);
    }
    if (
      result.planDigest !== input.planDigest ||
      result.unitDigest !== plannedByAsset.get(result.asset)
    ) {
      throw new Error(`RESULT_BINDING_MISMATCH: ${result.asset}`);
    }
    if (
      input.experimentImplementationDigest !== null &&
      result.provenanceDigest !== input.experimentImplementationDigest
    ) {
      throw new Error(`RESULT_PROVENANCE_MISMATCH: ${result.asset}`);
    }
    resultsByAsset.set(result.asset, result);
  }

  const availabilityKeys = Object.keys(input.graphReferenceAvailability).sort(
    compareStrings,
  );
  const plannedAssets = plannedUnits.map((unit) => unit.asset);
  if (JSON.stringify(availabilityKeys) !== JSON.stringify(plannedAssets)) {
    throw new Error("GRAPH_REFERENCE_AVAILABILITY_SET_MISMATCH");
  }

  for (const unit of plannedUnits) {
    const result = resultsByAsset.get(unit.asset);
    if (!result) continue;
    const expected = input.graphReferenceAvailability[unit.asset];
    for (const arm of [
      result.baseline,
      result.staged,
      result.llmTranslationResearch,
    ].filter((entry): entry is ArmResult => Boolean(entry))) {
      validateGraphEvidence(unit.asset, arm, expected);
    }
  }

  const plannedRows = plannedUnits.map((unit) => ({
    asset: unit.asset,
    unitDigest: unit.unitDigest,
    result: resultsByAsset.get(unit.asset),
    graphReferenceAvailable: input.graphReferenceAvailability[unit.asset],
  }));
  const benchmarkCompletedPairs = plannedRows.filter(
    (row) =>
      row.result?.baseline.metrics.benchmark &&
      row.result.staged.metrics.benchmark,
  );
  const completeCaseAssets = benchmarkCompletedPairs.map((row) => row.asset);

  const liveExecutionEvidence = input.results
    .filter(
      (result) =>
        result.schemaVersion === "cell-role-paired-result-v4" &&
        Boolean(result.liveExecution),
    )
    .map((result) => ({
      asset: result.asset,
      authorizationDigest: result.liveExecution!.authorizationDigest,
      executableDigest: result.liveExecution!.executableDigest,
      oauthReadinessDigest: result.liveExecution!.oauthReadinessDigest,
      evidenceDigest: digestCanonicalJson(result.liveExecution),
    }))
    .sort(compareAssets);
  if (
    liveExecutionEvidence.length > 0 &&
    liveExecutionEvidence.length !== input.results.length
  ) {
    throw new Error("MIXED_LIVE_EXECUTION_EVIDENCE");
  }

  const deterministicPairs = plannedRows.map((row) => {
    const baselinePass = deterministicPass(row.result?.baseline);
    const stagedPass = deterministicPass(row.result?.staged);
    const outcome =
      stagedPass === baselinePass
        ? ("tie" as const)
        : stagedPass
          ? ("win" as const)
          : ("loss" as const);
    return {
      asset: row.asset,
      baselinePass,
      stagedPass,
      outcome,
    };
  });

  return {
    schemaVersion: CORRECTED_REPORT_SCHEMA_VERSION,
    reportGenerationVersion: REPORT_GENERATION_VERSION,
    provenance: {
      runId: input.runId,
      planDigest: input.planDigest,
      implementationDigest: input.implementationDigest,
      experimentImplementationDigest: input.experimentImplementationDigest,
      evidenceManifestDigest: input.evidenceManifestDigest,
      graphReferenceEvidenceManifestDigests: [
        ...input.graphReferenceEvidenceManifestDigests,
      ].sort(compareStrings),
      unitDigests: plannedUnits,
      ...(liveExecutionEvidence.length ? { liveExecutionEvidence } : {}),
    },
    denominators: {
      plannedPairs: plannedRows.length,
      plannedAssetsPerArm: plannedRows.length,
      benchmarkCompletedPairs: benchmarkCompletedPairs.length,
      completeCaseQualityPairs: benchmarkCompletedPairs.length,
      completeCaseQualityAssets: completeCaseAssets,
    },
    primaryEndpoint: "deterministic_pass_over_planned_assets" as const,
    arms: {
      baseline: aggregateCorrectedArm(plannedRows, "baseline"),
      staged: aggregateCorrectedArm(plannedRows, "staged"),
    },
    ...(input.providerCallBudget
      ? {
          providerCallAccounting: buildProviderCallAccounting(
            plannedRows,
            input.providerCallBudget,
          ),
          ...(input.providerCallBudget.perUnit.llmTranslationResearch > 0
            ? {
                researchArms: {
                  llmTranslationResearch: aggregateCorrectedArm(
                    plannedRows,
                    "llm-translation-research",
                  ),
                },
              }
            : {}),
        }
      : {}),
    pairedIntentionToTreatDeterministic: {
      denominator: plannedRows.length,
      wins: deterministicPairs.filter((pair) => pair.outcome === "win").length,
      ties: deterministicPairs.filter((pair) => pair.outcome === "tie").length,
      losses: deterministicPairs.filter((pair) => pair.outcome === "loss")
        .length,
      pairs: deterministicPairs,
    },
    completeCasePairedQualityMetrics: Object.fromEntries(
      QUALITY_METRIC_KEYS.map((key) => [
        key,
        correctedPairedMetric(benchmarkCompletedPairs, key),
      ]),
    ) as Record<QualityMetricKey, ReturnType<typeof correctedPairedMetric>>,
    assets: plannedRows.map((row) => ({
      asset: row.asset,
      unitDigest: row.unitDigest,
      benchmarkCompletedPair: Boolean(
        row.result?.baseline.metrics.benchmark &&
        row.result.staged.metrics.benchmark,
      ),
      baseline: summarizeCorrectedArm(
        row.result?.baseline,
        "baseline",
        row.graphReferenceAvailable,
      ),
      staged: summarizeCorrectedArm(
        row.result?.staged,
        "staged",
        row.graphReferenceAvailable,
      ),
      ...(input.providerCallBudget?.perUnit.llmTranslationResearch
        ? {
            llmTranslationResearch: summarizeCorrectedArm(
              row.result?.llmTranslationResearch,
              "llm-translation-research",
              row.graphReferenceAvailable,
            ),
          }
        : {}),
    })),
  };
}

export function renderComparisonReport(
  report: ReturnType<typeof buildComparisonReport> | CorrectedComparisonReport,
): Buffer {
  return Buffer.from(`${JSON.stringify(report, null, 2)}\n`);
}

export function renderCorrectedComparisonMarkdown(
  report: CorrectedComparisonReport,
): Buffer {
  const lines = [
    `# Corrected cell-role report — ${report.provenance.runId}`,
    "",
    `Schema: \`${report.schemaVersion}\` (${report.reportGenerationVersion})`,
    `Plan digest: \`${report.provenance.planDigest}\``,
    `Evidence manifest digest: \`${report.provenance.evidenceManifestDigest}\``,
    ...(report.providerCallAccounting
      ? [
          `Provider calls: ${report.providerCallAccounting.realized} realized of ${report.providerCallAccounting.maximumAuthorized} maximum authorized.`,
        ]
      : []),
    "",
    "Benchmark completion is an operational endpoint, not semantic success. The primary strict endpoint is deterministic pass over every planned asset; all pipeline failures count as not passing.",
    "",
    "## Intention-to-treat endpoints",
    "",
    "| Arm | Planned | Benchmark completed | Deterministic pass | Executable | Nonempty |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
    endpointRow("Baseline", report.arms.baseline),
    endpointRow("Staged", report.arms.staged),
    "",
    `Paired deterministic outcomes across ${report.pairedIntentionToTreatDeterministic.denominator} planned pairs: ${report.pairedIntentionToTreatDeterministic.wins} staged wins, ${report.pairedIntentionToTreatDeterministic.ties} ties, ${report.pairedIntentionToTreatDeterministic.losses} staged losses.`,
    "",
    "## Graph-aware endpoints",
    "",
    "Assets without graph references are **unscored** and excluded from the deployable denominator; they are never assigned zero. Reference-available assets whose arm failed before scoring receive zero only in the deployable estimand.",
    "",
    ...graphMarkdown("Baseline", report.arms.baseline),
    "",
    ...graphMarkdown("Staged", report.arms.staged),
    "",
    "## Complete-case quality sensitivity analysis",
    "",
    `Denominator: ${report.denominators.completeCaseQualityPairs}. Assets: ${report.denominators.completeCaseQualityAssets.length ? report.denominators.completeCaseQualityAssets.map((asset) => `\`${asset}\``).join(", ") : "none"}.`,
    "This secondary population contains only pairs where both arms completed benchmarking and must not be interpreted as the ITT population.",
    "",
    "## Resource use",
    "",
    "Realized latency/cost per planned asset includes failure paths. Conditional latency/cost includes only benchmark-completed outputs.",
    "",
    resourceMarkdown("Baseline", report.arms.baseline),
    resourceMarkdown("Staged", report.arms.staged),
    ...("researchArms" in report && report.researchArms
      ? [
          resourceMarkdown(
            "LLM translation research",
            report.researchArms.llmTranslationResearch,
          ),
        ]
      : []),
    "",
    "## Asset graph status",
    "",
    "| Asset | Baseline | Staged |",
    "| --- | --- | --- |",
    ...report.assets.map(
      (asset) =>
        `| ${asset.asset} | ${humanGraphStatus(asset.baseline.graph.status)} | ${humanGraphStatus(asset.staged.graph.status)} |`,
    ),
    "",
  ];
  return Buffer.from(`${lines.join("\n")}\n`);
}

function resultArm(
  result: PairedAssetResult | undefined,
  armName: "baseline" | "staged" | "llm-translation-research",
): ArmResult | undefined {
  if (!result) return undefined;
  return armName === "llm-translation-research"
    ? result.llmTranslationResearch
    : result[armName];
}

function buildProviderCallAccounting(
  rows: Array<{ result?: PairedAssetResult }>,
  budget: ProviderCallBudget,
) {
  const realized = {
    baseline: rows.reduce(
      (sum, row) => sum + (row.result?.baseline.providerAttempts ?? 0),
      0,
    ),
    staged: rows.reduce(
      (sum, row) => sum + (row.result?.staged.providerAttempts ?? 0),
      0,
    ),
    llmTranslationResearch: rows.reduce(
      (sum, row) =>
        sum + (row.result?.llmTranslationResearch?.providerAttempts ?? 0),
      0,
    ),
  };
  const total =
    realized.baseline + realized.staged + realized.llmTranslationResearch;
  if (
    realized.baseline > rows.length * budget.perUnit.baseline ||
    realized.staged > rows.length * budget.perUnit.staged ||
    realized.llmTranslationResearch >
      rows.length * budget.perUnit.llmTranslationResearch ||
    total > budget.maximumTotal
  ) {
    throw new Error("REPORT_PROVIDER_CALL_BUDGET_EXCEEDED");
  }
  return {
    maximumAuthorized: budget.maximumTotal,
    realized: total,
    perArm: {
      baseline: {
        maximumAuthorized: rows.length * budget.perUnit.baseline,
        realized: realized.baseline,
      },
      staged: {
        maximumAuthorized: rows.length * budget.perUnit.staged,
        realized: realized.staged,
      },
      llmTranslationResearch: {
        maximumAuthorized: rows.length * budget.perUnit.llmTranslationResearch,
        realized: realized.llmTranslationResearch,
      },
    },
  };
}

function aggregateCorrectedArm(
  rows: Array<{
    asset: string;
    result?: PairedAssetResult;
    graphReferenceAvailable: boolean;
  }>,
  armName: "baseline" | "staged" | "llm-translation-research",
) {
  const arms = rows.map((row) => resultArm(row.result, armName));
  const denominator = rows.length;
  const benchmarkCompleted = arms.filter(
    (arm) => arm?.metrics.benchmark,
  ).length;
  const graphRows = rows.map((row) => ({
    referenceAvailable: row.graphReferenceAvailable,
    arm: resultArm(row.result, armName),
  }));
  const scored = graphRows.filter(
    (row) => row.referenceAvailable && graphValues(row.arm) !== null,
  );
  const failedBeforeScoring = graphRows.filter(
    (row) => row.referenceAvailable && graphValues(row.arm) === null,
  );
  const deployableValues = (key: GraphMetricKey) => [
    ...scored.map((row) => graphValues(row.arm)![key]),
    ...failedBeforeScoring.map(() => 0),
  ];
  const observedValues = (key: GraphMetricKey) =>
    scored.map((row) => graphValues(row.arm)![key]);
  const endpoint = (predicate: (arm: ArmResult | undefined) => boolean) =>
    binaryEndpoint(arms.filter(predicate).length, denominator);

  return {
    plannedDenominator: denominator,
    operationalEndpoints: {
      providerAttempted: endpoint((arm) => (arm?.providerAttempts ?? 0) > 0),
      providerResponded: endpoint((arm) => (arm?.providerResponses ?? 0) > 0),
      providerFailed: endpoint((arm) => (arm?.providerFailures ?? 0) > 0),
      semanticParseValid:
        armName !== "baseline"
          ? {
              ...endpoint((arm) => Boolean(arm?.metrics.semanticXmlValid)),
              applicable: true,
            }
          : {
              numerator: 0,
              denominator: 0,
              rate: null,
              applicable: false,
            },
      finalJsonParseValid: endpoint((arm) =>
        Boolean(arm?.metrics.finalJsonParseValid),
      ),
      schemaValid: endpoint((arm) => Boolean(arm?.metrics.schemaValid)),
      benchmarkCompleted: binaryEndpoint(benchmarkCompleted, denominator),
      executable: endpoint((arm) => Boolean(arm?.metrics.executable)),
      nonempty: endpoint((arm) => Boolean(arm?.metrics.nonempty)),
      deterministicPass: endpoint((arm) => deterministicPass(arm)),
      graphReferenceAvailable: binaryEndpoint(
        graphRows.filter((row) => row.referenceAvailable).length,
        denominator,
      ),
      graphScored: binaryEndpoint(scored.length, denominator),
    },
    graph: {
      counts: {
        planned: denominator,
        referenceAvailable: graphRows.filter((row) => row.referenceAvailable)
          .length,
        pipelineReachedScoring: graphRows.filter(
          (row) => row.arm?.metrics.benchmark,
        ).length,
        scored: scored.length,
        unscoredReferenceUnavailable: graphRows.filter(
          (row) => !row.referenceAvailable,
        ).length,
        unscoredArmFailed: failedBeforeScoring.length,
      },
      deployable: {
        denominator: scored.length + failedBeforeScoring.length,
        failedBeforeScoringAssignedZero: failedBeforeScoring.length,
        graphSimilarity: estimate(deployableValues("graph_similarity")),
        columnAxisJaccard: estimate(deployableValues("column_axis_jaccard")),
        associationJaccard: estimate(deployableValues("association_jaccard")),
      },
      observedScoreOnly: {
        graphSimilarity: estimate(observedValues("graph_similarity")),
        columnAxisJaccard: estimate(observedValues("column_axis_jaccard")),
        associationJaccard: estimate(observedValues("association_jaccard")),
      },
    },
    resourceUse: {
      latencyMs: latencyResource(arms, denominator),
      catalogPricedUsd: costResource(arms, denominator, "catalogPricedUsd"),
      apiEquivalentUsd: costResource(arms, denominator, "apiEquivalentUsd"),
    },
    warningCount: arms.reduce(
      (sum, arm) => sum + (arm?.metrics.warningCount ?? 0),
      0,
    ),
    providerCallTotals: {
      attempted: arms.reduce(
        (sum, arm) => sum + (arm?.providerAttempts ?? 0),
        0,
      ),
      responded: arms.reduce(
        (sum, arm) => sum + (arm?.providerResponses ?? 0),
        0,
      ),
      failed: arms.reduce((sum, arm) => sum + (arm?.providerFailures ?? 0), 0),
      withUsage: arms.reduce((sum, arm) => sum + (arm?.callsWithUsage ?? 0), 0),
    },
    usage: sumUsage(arms.filter(Boolean).map((arm) => arm!.usage)),
    failureCodes: arms
      .flatMap((arm) => arm?.failures ?? [])
      .sort(compareStrings),
  };
}

function summarizeCorrectedArm(
  arm: ArmResult | undefined,
  armName: "baseline" | "staged" | "llm-translation-research",
  referenceAvailable: boolean,
) {
  const values = graphValues(arm);
  const status = !referenceAvailable
    ? ("unscored_reference_unavailable" as const)
    : values
      ? ("scored" as const)
      : ("unscored_arm_failed" as const);
  return {
    providerAttempted: (arm?.providerAttempts ?? 0) > 0,
    providerResponded: (arm?.providerResponses ?? 0) > 0,
    providerFailed: (arm?.providerFailures ?? 0) > 0,
    providerAttempts: arm?.providerAttempts ?? 0,
    providerResponses: arm?.providerResponses ?? 0,
    providerFailures: arm?.providerFailures ?? 0,
    callsWithUsage: arm?.callsWithUsage ?? 0,
    warningCount: arm?.metrics.warningCount ?? 0,
    semanticParseValid:
      armName === "baseline" ? null : Boolean(arm?.metrics.semanticXmlValid),
    finalJsonParseValid: Boolean(arm?.metrics.finalJsonParseValid),
    schemaValid: Boolean(arm?.metrics.schemaValid),
    benchmarkCompleted: Boolean(arm?.metrics.benchmark),
    executable: Boolean(arm?.metrics.executable),
    nonempty: Boolean(arm?.metrics.nonempty),
    deterministicPass: deterministicPass(arm),
    deterministicStatus: arm?.metrics.benchmark
      ? arm.metrics.benchmark.deterministic_pass
        ? ("pass" as const)
        : ("fail" as const)
      : ("not_reached" as const),
    durationMs: arm?.durationMs ?? null,
    usage: arm?.usage ?? null,
    failures: arm?.failures ?? [],
    graph: {
      referenceAvailable,
      status,
      graphSimilarity: values?.graph_similarity ?? null,
      columnAxisJaccard: values?.column_axis_jaccard ?? null,
      associationJaccard: values?.association_jaccard ?? null,
    },
  };
}

function validateGraphEvidence(
  asset: string,
  arm: ArmResult,
  expectedReferenceAvailable: boolean,
): void {
  const graph = arm.metrics.benchmark?.metrics.graph;
  if (!graph) return;
  if (graph.reference_available !== expectedReferenceAvailable) {
    throw new Error(`GRAPH_REFERENCE_DISAGREEMENT: ${asset}:${arm.arm}`);
  }
  const values = GRAPH_METRIC_KEYS.map((key) => graph[key]);
  if (expectedReferenceAvailable) {
    if (
      values.some(
        (value) =>
          typeof value !== "number" ||
          !Number.isFinite(value) ||
          value < 0 ||
          value > 1,
      )
    ) {
      throw new Error(`GRAPH_SCORE_MISSING_OR_INVALID: ${asset}:${arm.arm}`);
    }
  } else if (values.some((value) => value !== null)) {
    throw new Error(`GRAPH_UNAVAILABLE_SCORE_PRESENT: ${asset}:${arm.arm}`);
  }
}

function graphValues(
  arm: ArmResult | undefined,
): Record<GraphMetricKey, number> | null {
  const graph = arm?.metrics.benchmark?.metrics.graph;
  if (!graph?.reference_available) return null;
  if (
    graph.graph_similarity === null ||
    graph.column_axis_jaccard === null ||
    graph.association_jaccard === null
  ) {
    return null;
  }
  return {
    graph_similarity: graph.graph_similarity,
    column_axis_jaccard: graph.column_axis_jaccard,
    association_jaccard: graph.association_jaccard,
  };
}

function correctedPairedMetric(
  rows: Array<{ asset: string; result?: PairedAssetResult }>,
  key: QualityMetricKey,
) {
  const pairs = rows.map((row) => {
    const baseline = row.result?.baseline.metrics.benchmark?.[key];
    const staged = row.result?.staged.metrics.benchmark?.[key];
    if (baseline === undefined || staged === undefined) {
      throw new Error(`COMPLETE_CASE_METRIC_MISSING: ${row.asset}:${key}`);
    }
    return {
      asset: row.asset,
      baseline,
      staged,
      delta: staged - baseline,
    };
  });
  return {
    denominator: pairs.length,
    assets: pairs.map((pair) => pair.asset),
    meanDelta: mean(pairs.map((pair) => pair.delta)),
    wins: pairs.filter((pair) => pair.delta > 0).length,
    ties: pairs.filter((pair) => pair.delta === 0).length,
    losses: pairs.filter((pair) => pair.delta < 0).length,
    pairs,
  };
}

function latencyResource(
  arms: Array<ArmResult | undefined>,
  denominator: number,
) {
  const observed = arms.filter((arm): arm is ArmResult => Boolean(arm));
  const completed = observed.filter((arm) => arm.metrics.benchmark);
  const total = observed.reduce((sum, arm) => sum + arm.durationMs, 0);
  const completedTotal = completed.reduce(
    (sum, arm) => sum + arm.durationMs,
    0,
  );
  return {
    observedAssetCount: observed.length,
    total,
    realizedPerPlannedAsset: {
      denominator,
      mean:
        observed.length === denominator && denominator
          ? total / denominator
          : null,
    },
    conditionalPerBenchmarkCompleted: {
      denominator: completed.length,
      total: completedTotal,
      mean: completed.length ? completedTotal / completed.length : null,
    },
  };
}

function costResource(
  arms: Array<ArmResult | undefined>,
  denominator: number,
  key: "catalogPricedUsd" | "apiEquivalentUsd",
) {
  const observed = arms.filter((arm): arm is ArmResult => Boolean(arm));
  const completed = observed.filter((arm) => arm.metrics.benchmark);
  const values = observed
    .map((arm) => arm.usage[key])
    .filter((value): value is number => typeof value === "number");
  const completedValues = completed
    .map((arm) => arm.usage[key])
    .filter((value): value is number => typeof value === "number");
  const fullyObserved =
    observed.length === denominator && values.length === denominator;
  const completedFullyObserved = completedValues.length === completed.length;
  const total = fullyObserved ? sum(values) : null;
  const completedTotal = completedFullyObserved ? sum(completedValues) : null;
  return {
    knownValueCount: values.length,
    expectedValueCount: denominator,
    total,
    realizedPerPlannedAsset: {
      denominator,
      mean: total !== null && denominator ? total / denominator : null,
    },
    conditionalPerBenchmarkCompleted: {
      denominator: completed.length,
      knownValueCount: completedValues.length,
      total: completedTotal,
      mean:
        completedTotal !== null && completed.length
          ? completedTotal / completed.length
          : null,
    },
  };
}

function binaryEndpoint(
  numerator: number,
  denominator: number,
): BinaryEndpoint {
  return {
    numerator,
    denominator,
    rate: denominator ? numerator / denominator : null,
  };
}

function estimate(values: number[]) {
  return {
    denominator: values.length,
    sum: sum(values),
    mean: mean(values),
  };
}

function deterministicPass(arm: ArmResult | undefined): boolean {
  return arm?.metrics.benchmark?.deterministic_pass === true;
}

function endpointRow(
  label: string,
  arm: CorrectedComparisonReport["arms"]["baseline"],
): string {
  const endpoints = arm.operationalEndpoints;
  return `| ${label} | ${arm.plannedDenominator} | ${formatEndpoint(endpoints.benchmarkCompleted)} | ${formatEndpoint(endpoints.deterministicPass)} | ${formatEndpoint(endpoints.executable)} | ${formatEndpoint(endpoints.nonempty)} |`;
}

function graphMarkdown(
  label: string,
  arm: CorrectedComparisonReport["arms"]["baseline"],
): string[] {
  return [
    `### ${label}`,
    "",
    `Reference available: ${arm.graph.counts.referenceAvailable}/${arm.graph.counts.planned}; pipeline reached scoring: ${arm.graph.counts.pipelineReachedScoring}; scored: ${arm.graph.counts.scored}; unscored because reference unavailable: ${arm.graph.counts.unscoredReferenceUnavailable}; unscored because arm failed: ${arm.graph.counts.unscoredArmFailed}.`,
    `Deployable graph similarity: ${formatEstimate(arm.graph.deployable.graphSimilarity)}; observed-score-only: ${formatEstimate(arm.graph.observedScoreOnly.graphSimilarity)}.`,
    `Deployable column-axis Jaccard: ${formatEstimate(arm.graph.deployable.columnAxisJaccard)}; observed-score-only: ${formatEstimate(arm.graph.observedScoreOnly.columnAxisJaccard)}.`,
    `Deployable association Jaccard: ${formatEstimate(arm.graph.deployable.associationJaccard)}; observed-score-only: ${formatEstimate(arm.graph.observedScoreOnly.associationJaccard)}.`,
  ];
}

function resourceMarkdown(
  label: string,
  arm: CorrectedComparisonReport["arms"]["baseline"],
): string {
  const latency = arm.resourceUse.latencyMs;
  const cost = arm.resourceUse.apiEquivalentUsd;
  return `${label}: realized latency per planned asset ${formatNullable(latency.realizedPerPlannedAsset.mean)} ms (denominator ${latency.realizedPerPlannedAsset.denominator}); conditional latency per benchmark-completed output ${formatNullable(latency.conditionalPerBenchmarkCompleted.mean)} ms (denominator ${latency.conditionalPerBenchmarkCompleted.denominator}). Realized API-equivalent cost per planned asset ${formatNullable(cost.realizedPerPlannedAsset.mean)} USD; conditional cost per benchmark-completed output ${formatNullable(cost.conditionalPerBenchmarkCompleted.mean)} USD.`;
}

function humanGraphStatus(status: string): string {
  if (status === "scored") return "scored";
  if (status === "unscored_reference_unavailable") {
    return "unscored (reference unavailable)";
  }
  return "unscored (arm failed before scoring)";
}

function formatEndpoint(endpoint: BinaryEndpoint): string {
  return `${endpoint.numerator}/${endpoint.denominator}`;
}

function formatEstimate(value: {
  denominator: number;
  mean: number | null;
}): string {
  return `${formatNullable(value.mean)} (n=${value.denominator})`;
}

function formatNullable(value: number | null): string {
  return value === null ? "unavailable" : String(value);
}

function aggregateLegacyArm(arms: ArmResult[], denominator: number) {
  const benchmarkCompleted = arms.filter((arm) => arm.metrics.benchmark).length;
  const providerAttempts = arms.reduce(
    (sum, arm) => sum + arm.providerAttempts,
    0,
  );
  const callsWithUsage = arms.reduce((sum, arm) => sum + arm.callsWithUsage, 0);
  return {
    denominator,
    intentionToTreat: {
      successes: benchmarkCompleted,
      failures: denominator - benchmarkCompleted,
      successRate: denominator ? benchmarkCompleted / denominator : null,
      failureRate: denominator
        ? (denominator - benchmarkCompleted) / denominator
        : null,
    },
    finalJsonParseValid: arms.filter((arm) => arm.metrics.finalJsonParseValid)
      .length,
    schemaValid: arms.filter((arm) => arm.metrics.schemaValid).length,
    semanticXmlValid: arms.filter((arm) => arm.metrics.semanticXmlValid).length,
    executable: arms.filter((arm) => arm.metrics.executable).length,
    nonempty: arms.filter((arm) => arm.metrics.nonempty).length,
    warnings: arms.reduce((sum, arm) => sum + arm.metrics.warningCount, 0),
    providerAttempts,
    providerResponses: arms.reduce(
      (sum, arm) => sum + arm.providerResponses,
      0,
    ),
    providerFailures: arms.reduce((sum, arm) => sum + arm.providerFailures, 0),
    usageCoverage: {
      callsWithUsage,
      attemptedCalls: providerAttempts,
      rate: providerAttempts ? callsWithUsage / providerAttempts : null,
    },
    usage: sumUsage(arms.map((arm) => arm.usage)),
    durationMs: arms.reduce((sum, arm) => sum + arm.durationMs, 0),
    failures: arms.flatMap((arm) => arm.failures).sort(),
  };
}

function summarizeLegacyArm(arm: ArmResult) {
  const benchmark = arm.metrics.benchmark;
  return {
    finalJsonParseValid: arm.metrics.finalJsonParseValid,
    schemaValid: arm.metrics.schemaValid,
    semanticXmlValid: arm.metrics.semanticXmlValid,
    executable: arm.metrics.executable,
    nonempty: arm.metrics.nonempty,
    warningCount: arm.metrics.warningCount,
    providerAttempts: arm.providerAttempts,
    providerResponses: arm.providerResponses,
    providerFailures: arm.providerFailures,
    callsWithUsage: arm.callsWithUsage,
    usage: arm.usage,
    durationMs: arm.durationMs,
    failures: arm.failures,
    benchmark: benchmark
      ? {
          deterministicPass: benchmark.deterministic_pass,
          exactCsvMatch: benchmark.exact_csv_match,
          cellExactMatchRate: benchmark.cell_exact_match_rate,
          addressConditionedCellMatchRate:
            benchmark.address_conditioned_cell_match_rate,
          valueAddressF1: benchmark.value_address_f1,
          fullRowHeaderMatchRate: benchmark.full_row_header_match_rate,
          fullRowWithValueMatchRate: benchmark.full_row_with_value_match_rate,
          geometry: benchmark.metrics.geometry,
          graph: benchmark.metrics.graph,
        }
      : null,
  };
}

function legacyPairedMetric(pairs: PairedAssetResult[], key: QualityMetricKey) {
  const deltas = pairs.map((pair) => {
    const baseline = pair.baseline.metrics.benchmark?.[key] ?? 0;
    const staged = pair.staged.metrics.benchmark?.[key] ?? 0;
    return { asset: pair.asset, baseline, staged, delta: staged - baseline };
  });
  return {
    denominator: pairs.length,
    meanDelta: mean(deltas.map((entry) => entry.delta)),
    wins: deltas.filter((entry) => entry.delta > 0).length,
    ties: deltas.filter((entry) => entry.delta === 0).length,
    losses: deltas.filter((entry) => entry.delta < 0).length,
    pairs: deltas,
  };
}

function sumUsage(usages: LlmUsage[]): LlmUsage {
  const result: LlmUsage = {};
  const keys: Array<keyof LlmUsage> = [
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
  ];
  for (const key of keys) {
    const values = usages
      .map((usage) => usage[key])
      .filter((value): value is number => typeof value === "number");
    if (values.length) {
      (result as Record<string, unknown>)[key] = sum(values);
    }
  }
  return result;
}

function mean(values: number[]): number | null {
  return values.length ? sum(values) / values.length : null;
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

function assertUnique(values: string[], identity: string): void {
  if (new Set(values).size !== values.length) {
    throw new Error(`DUPLICATE_${identity}`);
  }
}

function compareAssets(
  left: { asset: string },
  right: { asset: string },
): number {
  return compareStrings(left.asset, right.asset);
}

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
