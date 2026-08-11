import { mkdir, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { parseRecipe, recipeV01Schema } from "../../../src/lib/recipe/schema";
import { findRecipeSheet } from "../../../src/lib/workbook/findRecipeSheet";
import { parseWorkbook } from "../../../src/lib/workbook/parseWorkbook";
import { parseCsv } from "../../benchmark/csv";
import { loadManifest, validateManifest } from "../../benchmark/manifest";
import { buildTableGraph } from "../../benchmark/metrics/graphSimilarity";
import type { BenchmarkAsset } from "../../benchmark/types";
import { resolveContainedPath } from "../../harvest/path-safety";
import {
  assertNoIncompleteArtifacts,
  digestCanonicalJson,
  readContainedArtifact,
  sha256Bytes,
} from "./artifact-io";
import {
  evidenceManifestSchema,
  implementationProvenanceSchema,
} from "./evidence";
import {
  validateEvidencePayload,
  writeImmutableEvidenceFile,
} from "./evidence-io";
import {
  captureImplementationProvenance,
  implementationProvenanceDigest,
  verifyImplementationProvenance,
} from "./provenance";
import { CELL_ROLE_COMPILER_VERSION } from "./compiler-v02";
import {
  buildComparisonReport,
  buildCorrectedComparisonReport,
  renderComparisonReport,
} from "./report";
import {
  assertPromptContractNoLeakage,
  buildCompactContextSnapshot,
  collectRecipeTargetNames,
  COMPACT_CONTEXT_SCHEMA_VERSION,
  estimateStaticTokens,
  parseCompactContext,
} from "./compact-context";
import {
  BASELINE_PROMPT_VERSION,
  buildCompactBaselinePrompt,
  buildSemanticsPrompt,
  buildTranslationPromptPreamble,
  SEMANTICS_PROMPT_VERSION,
  TRANSLATION_PROMPT_VERSION,
} from "./prompts";
import type { ArmOrder, PairedAssetResult } from "./types";

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

const configSchema = z
  .object({
    runId: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/),
    manifest: z
      .string()
      .min(1)
      .default("json-examples/benchmark-manifest.json"),
    assets: z.array(z.string().min(1)).min(1),
    outputRoot: z.string().min(1).default("research-runs/cell-role-pipeline"),
    providerAdapter: z
      .enum(["UNCONFIGURED", "pi-json-v1"])
      .default("UNCONFIGURED"),
    generationSettings: generationSettingsSchema,
    armOrdering: z.literal("counterbalanced"),
    researchArms: z
      .array(z.literal("llm-translation-research"))
      .max(1)
      .default([]),
  })
  .strict()
  .superRefine((value, ctx) => {
    const seen = new Set<string>();
    for (const asset of value.assets) {
      if (seen.has(asset)) {
        ctx.addIssue({
          code: "custom",
          path: ["assets"],
          message: `Duplicate configured asset: ${asset}.`,
        });
      }
      seen.add(asset);
    }
  });

const fileSnapshotSchema = z
  .object({ path: z.string().min(1), digest: z.string().length(64) })
  .strict();
const benchmarkAssetSchema = z
  .object({
    name: z.string().min(1),
    xlsx: z.string().min(1),
    recipe: z.string().min(1),
    expected_csv: z.string().min(1).optional(),
    expected_csvs: z.record(z.string(), z.string().min(1)).optional(),
    metadata: z.string().min(1).optional(),
    expected_overlay: z.string().min(1).optional(),
    enabled: z.boolean(),
    ci_smoke: z.boolean().optional(),
    disabled_reason: z.string().optional(),
    difficulty: z.string().optional(),
    features: z.array(z.string()).optional(),
    repeat_of: z.string().optional(),
    repeat_index: z.number().int().optional(),
  })
  .strict();
const inputSnapshotsSchema = z
  .object({
    xlsx: fileSnapshotSchema,
    approvedRecipe: fileSnapshotSchema,
    expectedCsv: fileSnapshotSchema.optional(),
    expectedCsvs: z.record(z.string(), fileSnapshotSchema).optional(),
    expectedOverlay: fileSnapshotSchema.optional(),
    metadata: fileSnapshotSchema.optional(),
  })
  .strict();
const summarySnapshotSchema = z
  .object({
    sheet: z.string().min(1),
    checked: z.boolean(),
    usedRange: z.string().nullable(),
    rowCount: z.number().int().nonnegative(),
    columnCount: z.number().int().nonnegative(),
    nonEmptyCellCount: z.number().int().nonnegative(),
    cells: z.array(z.unknown()),
    dataTypes: z.record(z.string(), z.number()),
    merges: z.array(z.unknown()),
    styleFingerprints: z.record(z.string(), z.unknown()),
    blankRows: z.array(z.unknown()),
    blankColumns: z.array(z.unknown()),
    candidateRegions: z.array(z.unknown()),
    candidateBlocks: z.array(z.unknown()).readonly().optional(),
    candidateBlockEvidence: z.unknown().optional(),
    dataRangeHintRegions: z.array(z.unknown()).optional(),
    contextCells: z.array(z.unknown()),
    header_list: z.array(z.unknown()),
    table_context_format: z.enum(["markdown_compact", "html_expanded"]),
    table_markdown: z.string(),
    table_markdown_truncated: z.boolean(),
    html_table: z.string(),
    html_table_truncated: z.boolean(),
    intent: z.string().optional(),
    truncated: z.boolean(),
    sizeChars: z.number().int().nonnegative(),
  })
  .strict();
const armOrderSchema = z.union([
  z.tuple([z.literal("baseline"), z.literal("staged")]),
  z.tuple([z.literal("staged"), z.literal("baseline")]),
]);
const planUnitSchema = z
  .object({
    asset: z.string().min(1),
    assetSnapshot: benchmarkAssetSchema,
    inputs: inputSnapshotsSchema,
    sheet: z.string().min(1),
    summary: summarySnapshotSchema,
    summaryDigest: z.string().length(64),
    baselinePrompt: z.string().min(1),
    baselinePromptMessages: z.array(z.string()),
    semanticsPrompt: z.string().min(1),
    translationPromptPreamble: z.string().min(1),
    settings: generationSettingsSchema,
    armOrder: armOrderSchema,
  })
  .strict();
export const unsignedLegacyPlanSchema = z
  .object({
    schemaVersion: z.literal("cell-role-experiment-plan-v1"),
    runId: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/),
    manifest: z.string().min(1),
    manifestDigest: z.string().length(64),
    outputRoot: z.string().min(1),
    providerAdapter: z.enum(["UNCONFIGURED", "pi-json-v1"]),
    generationSettings: generationSettingsSchema,
    armOrdering: z.literal("counterbalanced"),
    promptVersions: z
      .object({
        semantics: z.string(),
        translation: z.string(),
        baseline: z.literal("existing-recipe-v01-v1"),
      })
      .strict(),
    units: z.array(planUnitSchema),
  })
  .strict();
export const legacyPlanSchema = unsignedLegacyPlanSchema.extend({
  digest: z.string().length(64),
});
const unsignedProvenancePlanSchema = unsignedLegacyPlanSchema.extend({
  schemaVersion: z.literal("cell-role-experiment-plan-v2"),
  implementationProvenance: implementationProvenanceSchema,
  implementationProvenanceDigest: z.string().regex(/^[a-f0-9]{64}$/),
});
export const provenancePlanSchema = unsignedProvenancePlanSchema.extend({
  digest: z.string().length(64),
});

const providerCallBudgetSchema = z
  .object({
    perUnit: z
      .object({
        baseline: z.number().int().nonnegative(),
        staged: z.number().int().nonnegative(),
        llmTranslationResearch: z.number().int().nonnegative(),
        total: z.number().int().nonnegative(),
      })
      .strict(),
    maximumTotal: z.number().int().nonnegative(),
  })
  .strict();
const deterministicResearchUnitSchema = z
  .object({
    arm: z.literal("llm-translation-research"),
    translationPromptPreamble: z.string().min(1),
  })
  .strict();
const deterministicPlanUnitSchema = planUnitSchema
  .omit({ translationPromptPreamble: true })
  .extend({ research: deterministicResearchUnitSchema.optional() })
  .strict();
const compactContextSnapshotSchema = z
  .object({
    schemaVersion: z.literal(COMPACT_CONTEXT_SCHEMA_VERSION),
    digest: z.string().regex(/^[a-f0-9]{64}$/),
    bytes: z.number().int().positive(),
    characters: z.number().int().positive(),
    estimatedTokens: z.number().int().positive(),
    addressValueEntries: z.number().int().nonnegative(),
    duplicateAddressValueRepresentations: z.literal(0),
    serialized: z.string().min(1),
  })
  .strict();
const compactPlanUnitSchema = planUnitSchema
  .omit({
    summary: true,
    summaryDigest: true,
    baselinePromptMessages: true,
    translationPromptPreamble: true,
  })
  .extend({
    context: compactContextSnapshotSchema,
    contextAttestations: z
      .object({
        baseline: z.string().regex(/^[a-f0-9]{64}$/),
        semantics: z.string().regex(/^[a-f0-9]{64}$/),
      })
      .strict(),
    worksheetBounds: z
      .object({
        rowCount: z.number().int().nonnegative(),
        columnCount: z.number().int().nonnegative(),
      })
      .strict(),
    baselinePromptDigest: z.string().regex(/^[a-f0-9]{64}$/),
    semanticsPromptDigest: z.string().regex(/^[a-f0-9]{64}$/),
    research: deterministicResearchUnitSchema.optional(),
  })
  .strict();
const unsignedDeterministicPlanSchema = z
  .object({
    schemaVersion: z.literal("cell-role-experiment-plan-v3"),
    runId: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/),
    manifest: z.string().min(1),
    manifestDigest: z.string().length(64),
    outputRoot: z.string().min(1),
    providerAdapter: z.enum(["UNCONFIGURED", "pi-json-v1"]),
    generationSettings: generationSettingsSchema,
    armOrdering: z.literal("counterbalanced"),
    pipelineMode: z.literal("deterministic-compiler-v1"),
    researchArms: z.array(z.literal("llm-translation-research")).max(1),
    providerCallBudget: providerCallBudgetSchema,
    promptVersions: z
      .object({
        semantics: z.string(),
        baseline: z.literal("existing-recipe-v01-v1"),
        translationResearch: z.string().optional(),
      })
      .strict(),
    implementationProvenance: implementationProvenanceSchema,
    implementationProvenanceDigest: z.string().regex(/^[a-f0-9]{64}$/),
    units: z.array(deterministicPlanUnitSchema),
  })
  .strict();
export const deterministicPlanSchema = unsignedDeterministicPlanSchema.extend({
  digest: z.string().length(64),
});
const unsignedCompactPlanSchema = unsignedDeterministicPlanSchema
  .omit({ schemaVersion: true, promptVersions: true, units: true })
  .extend({
    schemaVersion: z.literal("cell-role-experiment-plan-v4"),
    promptVersions: z
      .object({
        context: z.literal(COMPACT_CONTEXT_SCHEMA_VERSION),
        semantics: z.literal(SEMANTICS_PROMPT_VERSION),
        baseline: z.literal(BASELINE_PROMPT_VERSION),
        translationResearch: z.string().optional(),
      })
      .strict(),
    units: z.array(compactPlanUnitSchema),
  })
  .strict();
export const compactPlanSchema = unsignedCompactPlanSchema.extend({
  digest: z.string().length(64),
});
export const experimentPlanSchema = z.union([
  legacyPlanSchema,
  provenancePlanSchema,
  deterministicPlanSchema,
  compactPlanSchema,
]);

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
const benchmarkSummarySchema = z
  .object({
    asset: z.string().min(1),
    sheet: z.string().min(1),
    deterministic_pass: z.boolean(),
    exact_csv_match: z.boolean(),
    cell_exact_match_rate: z.number(),
    address_conditioned_cell_match_rate: z.number(),
    value_address_f1: z.number(),
    full_row_header_match_rate: z.number(),
    full_row_with_value_match_rate: z.number(),
    warnings: z.array(
      z.object({ code: z.string(), message: z.string() }).strict(),
    ),
    metrics: z
      .object({ geometry: z.unknown(), graph: z.unknown() })
      .passthrough(),
  })
  .passthrough();
const metricsSchema = z
  .object({
    finalJsonParseValid: z.boolean(),
    schemaValid: z.boolean(),
    semanticXmlValid: z.boolean(),
    executable: z.boolean(),
    nonempty: z.boolean(),
    warningCount: z.number().int().nonnegative(),
    benchmark: benchmarkSummarySchema.nullable(),
  })
  .strict();
const armResultSchema = z
  .object({
    arm: z.enum(["baseline", "staged"]),
    recipe: recipeV01Schema.nullable(),
    metrics: metricsSchema,
    providerAttempts: z.number().int().nonnegative(),
    providerResponses: z.number().int().nonnegative(),
    providerFailures: z.number().int().nonnegative(),
    callsWithUsage: z.number().int().nonnegative(),
    usage: usageSchema,
    durationMs: z.number().nonnegative(),
    failures: z.array(z.string()),
    raw: z
      .object({
        semantics: z.string().optional(),
        translation: z.string().optional(),
        baseline: z.string().optional(),
      })
      .strict()
      .optional(),
  })
  .strict();
export const legacyPairedResultSchema = z
  .object({
    schemaVersion: z.literal("cell-role-paired-result-v1"),
    planDigest: z.string().length(64),
    unitDigest: z.string().length(64),
    asset: z.string().min(1),
    baseline: armResultSchema.extend({ arm: z.literal("baseline") }),
    staged: armResultSchema.extend({ arm: z.literal("staged") }),
  })
  .strict();
export const provenancePairedResultSchema = legacyPairedResultSchema.extend({
  schemaVersion: z.literal("cell-role-paired-result-v2"),
  provenanceDigest: z.string().regex(/^[a-f0-9]{64}$/),
});
export const deterministicPairedResultSchema = z
  .object({
    schemaVersion: z.literal("cell-role-paired-result-v3"),
    planDigest: z.string().length(64),
    provenanceDigest: z
      .string()
      .regex(/^[a-f0-9]{64}$/)
      .optional(),
    unitDigest: z.string().length(64),
    asset: z.string().min(1),
    baseline: armResultSchema.extend({ arm: z.literal("baseline") }),
    staged: armResultSchema.extend({ arm: z.literal("staged") }),
    providerCallBudget: providerCallBudgetSchema,
    llmTranslationResearch: armResultSchema
      .extend({ arm: z.literal("llm-translation-research") })
      .optional(),
  })
  .strict()
  .superRefine((value, ctx) => {
    const researchPlanned =
      value.providerCallBudget.perUnit.llmTranslationResearch > 0;
    if (Boolean(value.llmTranslationResearch) !== researchPlanned) {
      ctx.addIssue({
        code: "custom",
        message: "Result research arm does not match its call budget.",
      });
    }
    const actual = {
      baseline: value.baseline.providerAttempts,
      staged: value.staged.providerAttempts,
      research: value.llmTranslationResearch?.providerAttempts ?? 0,
    };
    if (
      actual.baseline > value.providerCallBudget.perUnit.baseline ||
      actual.staged > value.providerCallBudget.perUnit.staged ||
      actual.research >
        value.providerCallBudget.perUnit.llmTranslationResearch ||
      actual.baseline + actual.staged + actual.research >
        value.providerCallBudget.perUnit.total
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Result provider calls exceed the declared budget.",
      });
    }
  });
const liveExecutionEvidenceSchema = z
  .object({
    authorizationDigest: z.string().regex(/^[a-f0-9]{64}$/),
    implementationProvenanceDigest: z.string().regex(/^[a-f0-9]{64}$/),
    executableDigest: z.string().regex(/^[a-f0-9]{64}$/),
    oauthReadinessDigest: z.string().regex(/^[a-f0-9]{64}$/),
    validationDigest: z.string().regex(/^[a-f0-9]{64}$/),
    promptDigests: z
      .object({
        baseline: z.string().regex(/^[a-f0-9]{64}$/),
        semantics: z.string().regex(/^[a-f0-9]{64}$/),
        translationResearch: z
          .string()
          .regex(/^[a-f0-9]{64}$/)
          .optional(),
      })
      .strict(),
    settingsDigest: z.string().regex(/^[a-f0-9]{64}$/),
    responseDigests: z.array(z.string().regex(/^[a-f0-9]{64}$/)).min(1),
    orderedPredecessorEvidenceDigests: z
      .array(z.string().regex(/^[a-f0-9]{64}$/))
      .min(2),
  })
  .strict();
export const livePairedResultSchema = z
  .object({
    schemaVersion: z.literal("cell-role-paired-result-v4"),
    planDigest: z.string().length(64),
    provenanceDigest: z.string().regex(/^[a-f0-9]{64}$/),
    unitDigest: z.string().length(64),
    asset: z.string().min(1),
    baseline: armResultSchema.extend({ arm: z.literal("baseline") }),
    staged: armResultSchema.extend({ arm: z.literal("staged") }),
    providerCallBudget: providerCallBudgetSchema,
    llmTranslationResearch: armResultSchema
      .extend({ arm: z.literal("llm-translation-research") })
      .optional(),
    liveExecution: liveExecutionEvidenceSchema,
  })
  .strict()
  .superRefine((value, ctx) => {
    const researchPlanned =
      value.providerCallBudget.perUnit.llmTranslationResearch > 0;
    if (Boolean(value.llmTranslationResearch) !== researchPlanned) {
      ctx.addIssue({
        code: "custom",
        message: "Result research arm does not match its call budget.",
      });
    }
    const attempts =
      value.baseline.providerAttempts +
      value.staged.providerAttempts +
      (value.llmTranslationResearch?.providerAttempts ?? 0);
    if (
      attempts > value.providerCallBudget.perUnit.total ||
      value.liveExecution.responseDigests.length !== attempts
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Live result provider evidence does not match attempts.",
      });
    }
  });
export const pairedResultSchema = z.union([
  legacyPairedResultSchema,
  provenancePairedResultSchema,
  deterministicPairedResultSchema,
  livePairedResultSchema,
]);

export type ExperimentUnit =
  | z.infer<typeof planUnitSchema>
  | z.infer<typeof deterministicPlanUnitSchema>
  | z.infer<typeof compactPlanUnitSchema>;
export type ExperimentPlan = z.infer<typeof experimentPlanSchema>;

export async function createExperimentPlan(
  configPath: string,
  outputPath: string,
  repoRoot = process.cwd(),
): Promise<ExperimentPlan> {
  const safeConfig = await contained(
    repoRoot,
    configPath,
    true,
    "CONFIG_PATH_ESCAPE",
  );
  const config = configSchema.parse(
    JSON.parse(await readFile(safeConfig, "utf8")),
  );
  const implementationProvenance = implementationProvenanceSchema.parse(
    await captureImplementationProvenance(repoRoot),
  );
  const provenanceDigest = implementationProvenanceDigest(
    implementationProvenance,
  );
  const safeManifest = await contained(
    repoRoot,
    config.manifest,
    true,
    "MANIFEST_PATH_ESCAPE",
  );
  await contained(repoRoot, config.outputRoot, false, "RESULT_PATH_ESCAPE");
  const safeOutput = await contained(
    repoRoot,
    outputPath,
    false,
    "PLAN_PATH_ESCAPE",
  );
  const manifest = await loadManifest(
    path.relative(repoRoot, safeManifest),
    repoRoot,
  );

  for (const asset of manifest.assets)
    await assertAssetPathsContained(asset, repoRoot);
  const manifestErrors = validateManifest(manifest, repoRoot);
  if (manifestErrors.length) throw new Error(manifestErrors.join("\n"));

  const byName = new Map(manifest.assets.map((asset) => [asset.name, asset]));
  const units: Array<z.infer<typeof compactPlanUnitSchema>> = [];
  for (const [index, name] of config.assets.entries()) {
    const asset = byName.get(name);
    if (!asset || !asset.enabled)
      throw new Error(`Enabled manifest asset not found: ${name}.`);
    const inputs = await snapshotAssetInputs(asset, repoRoot);
    const workbookBytes = await readFile(
      await contained(repoRoot, asset.xlsx, true, "WORKBOOK_PATH_ESCAPE"),
    );
    const workbook = await parseWorkbook(workbookBytes);
    if (!workbook.ok) throw new Error(`Unable to parse ${asset.xlsx}.`);
    const recipe = parseRecipe(
      JSON.parse(
        await readFile(
          await contained(repoRoot, asset.recipe, true, "RECIPE_PATH_ESCAPE"),
          "utf8",
        ),
      ),
    );
    const sheet = findRecipeSheet(workbook.workbook, recipe.sheet);
    if (!sheet) throw new Error(`Sheet ${recipe.sheet} not found for ${name}.`);
    const context = buildCompactContextSnapshot(sheet);
    const baselinePrompt = buildCompactBaselinePrompt(context);
    const semanticsPrompt = buildSemanticsPrompt(context);
    assertPromptContractNoLeakage({
      context: context.serialized,
      baselinePrompt,
      semanticsPrompt,
      forbiddenPaths: [
        asset.recipe,
        asset.expected_csv ?? "",
        ...Object.values(asset.expected_csvs ?? {}),
        asset.expected_overlay ?? "",
        asset.metadata ?? "",
      ],
      targetNames: collectRecipeTargetNames(recipe),
      expectedCsvContents: await readExpectedCsvContents(asset, repoRoot),
    });
    units.push({
      asset: name,
      assetSnapshot: snapshotBenchmarkAsset(asset),
      inputs,
      sheet: sheet.name,
      context,
      contextAttestations: {
        baseline: context.digest,
        semantics: context.digest,
      },
      worksheetBounds: {
        rowCount: sheet.rowCount,
        columnCount: sheet.columnCount,
      },
      baselinePrompt,
      baselinePromptDigest: sha256Bytes(Buffer.from(baselinePrompt, "utf8")),
      semanticsPrompt,
      semanticsPromptDigest: sha256Bytes(Buffer.from(semanticsPrompt, "utf8")),
      ...(config.researchArms.length
        ? {
            research: {
              arm: "llm-translation-research" as const,
              translationPromptPreamble: buildTranslationPromptPreamble(),
            },
          }
        : {}),
      settings: config.generationSettings,
      armOrder:
        index % 2 === 0
          ? (["baseline", "staged"] as ArmOrder)
          : (["staged", "baseline"] as ArmOrder),
    });
  }
  const manifestBytes = await readFile(safeManifest);
  const perUnitCalls = 2 + (config.researchArms.length ? 1 : 0);
  const unsigned = unsignedCompactPlanSchema.parse({
    schemaVersion: "cell-role-experiment-plan-v4",
    runId: config.runId,
    manifest: config.manifest,
    manifestDigest: sha256(manifestBytes),
    outputRoot: config.outputRoot,
    providerAdapter: config.providerAdapter,
    generationSettings: config.generationSettings,
    armOrdering: config.armOrdering,
    pipelineMode: "deterministic-compiler-v1",
    researchArms: config.researchArms,
    providerCallBudget: {
      perUnit: {
        baseline: 1,
        staged: 1,
        llmTranslationResearch: config.researchArms.length ? 1 : 0,
        total: perUnitCalls,
      },
      maximumTotal: units.length * perUnitCalls,
    },
    promptVersions: {
      context: COMPACT_CONTEXT_SCHEMA_VERSION,
      semantics: SEMANTICS_PROMPT_VERSION,
      baseline: BASELINE_PROMPT_VERSION,
      ...(config.researchArms.length
        ? { translationResearch: TRANSLATION_PROMPT_VERSION }
        : {}),
    },
    implementationProvenance,
    implementationProvenanceDigest: provenanceDigest,
    units,
  });
  const plan = compactPlanSchema.parse({
    ...unsigned,
    digest: digestJson(unsigned),
  });
  assertPlanInternalDigests(plan);
  await mkdir(path.dirname(safeOutput), { recursive: true });
  await writeImmutableEvidenceFile({
    repoRoot,
    target: safeOutput,
    bytes: Buffer.from(`${JSON.stringify(plan, null, 2)}\n`),
    mediaType: "application/json",
    role: "plan",
    pathErrorCode: "PLAN_PATH_ESCAPE",
  });
  return plan;
}

export function parseExperimentPlan(value: unknown): ExperimentPlan {
  const plan = experimentPlanSchema.parse(value);
  const { digest, ...unsigned } = plan;
  const actual = digestJson(unsigned);
  if (actual !== digest) {
    throw new Error(
      `Plan digest mismatch: expected ${digest}, computed ${actual}.`,
    );
  }
  assertPlanInternalDigests(plan);
  return plan;
}

export async function readVerifiedPlan(
  planPath: string,
  repoRoot = process.cwd(),
): Promise<ExperimentPlan> {
  const safePlan = await contained(
    repoRoot,
    planPath,
    true,
    "PLAN_PATH_ESCAPE",
  );
  const plan = parseExperimentPlan(
    validateEvidencePayload({
      bytes: await readFile(safePlan),
      mediaType: "application/json",
      role: "plan",
    }),
  );
  await contained(repoRoot, plan.outputRoot, false, "RESULT_PATH_ESCAPE");
  if (plan.schemaVersion !== "cell-role-experiment-plan-v1") {
    if (
      implementationProvenanceDigest(plan.implementationProvenance) !==
      plan.implementationProvenanceDigest
    ) {
      throw new Error("Implementation provenance digest mismatch.");
    }
  }
  return plan;
}

function assertPlanInternalDigests(plan: ExperimentPlan): void {
  const planAssets = plan.units.map((unit) => unit.asset);
  if (new Set(planAssets).size !== planAssets.length) {
    throw new Error("DUPLICATE_PLAN_ASSET");
  }
  if (
    plan.schemaVersion !== "cell-role-experiment-plan-v1" &&
    implementationProvenanceDigest(plan.implementationProvenance) !==
      plan.implementationProvenanceDigest
  ) {
    throw new Error("Implementation provenance digest mismatch.");
  }
  if (
    plan.schemaVersion === "cell-role-experiment-plan-v2" &&
    plan.implementationProvenance.versions.plan !==
      "cell-role-experiment-plan-v2"
  ) {
    throw new Error("PLAN_IMPLEMENTATION_VERSION_MISMATCH");
  }
  if (
    plan.schemaVersion === "cell-role-experiment-plan-v3" ||
    plan.schemaVersion === "cell-role-experiment-plan-v4"
  ) {
    if (
      plan.implementationProvenance.versions.plan !== plan.schemaVersion ||
      plan.implementationProvenance.versions.compiler !==
        CELL_ROLE_COMPILER_VERSION
    ) {
      throw new Error("PLAN_IMPLEMENTATION_VERSION_MISMATCH");
    }
    const researchEnabled = plan.researchArms.includes(
      "llm-translation-research",
    );
    const expectedPerUnit = 2 + (researchEnabled ? 1 : 0);
    if (
      plan.providerCallBudget.perUnit.baseline !== 1 ||
      plan.providerCallBudget.perUnit.staged !== 1 ||
      plan.providerCallBudget.perUnit.llmTranslationResearch !==
        (researchEnabled ? 1 : 0) ||
      plan.providerCallBudget.perUnit.total !== expectedPerUnit ||
      plan.providerCallBudget.maximumTotal !==
        plan.units.length * expectedPerUnit
    ) {
      throw new Error("PLAN_PROVIDER_CALL_BUDGET_MISMATCH");
    }
    if (
      plan.units.some((unit) => Boolean(unit.research) !== researchEnabled) ||
      Boolean(plan.promptVersions.translationResearch) !== researchEnabled
    ) {
      throw new Error("PLAN_RESEARCH_ARM_BINDING_MISMATCH");
    }
  }
  for (const unit of plan.units) {
    if ("summary" in unit) {
      const actualSummaryDigest = digestJson(unit.summary);
      if (actualSummaryDigest !== unit.summaryDigest) {
        throw new Error(`Summary digest mismatch for ${unit.asset}.`);
      }
    } else {
      const parsedContext = parseCompactContext(unit.context.serialized);
      const actualContextDigest = sha256Bytes(
        Buffer.from(unit.context.serialized, "utf8"),
      );
      if (
        parsedContext.schemaVersion !== unit.context.schemaVersion ||
        actualContextDigest !== unit.context.digest ||
        unit.context.bytes !==
          Buffer.byteLength(unit.context.serialized, "utf8") ||
        unit.context.characters !== unit.context.serialized.length ||
        unit.context.estimatedTokens !==
          estimateStaticTokens(unit.context.characters) ||
        unit.context.addressValueEntries !==
          parsedContext.dimensions.rows * parsedContext.dimensions.columns ||
        unit.contextAttestations.baseline !== unit.context.digest ||
        unit.contextAttestations.semantics !== unit.context.digest
      ) {
        throw new Error(`Context binding mismatch for ${unit.asset}.`);
      }
      if (
        sha256Bytes(Buffer.from(unit.baselinePrompt, "utf8")) !==
          unit.baselinePromptDigest ||
        sha256Bytes(Buffer.from(unit.semanticsPrompt, "utf8")) !==
          unit.semanticsPromptDigest ||
        unit.baselinePrompt !== buildCompactBaselinePrompt(unit.context) ||
        unit.semanticsPrompt !== buildSemanticsPrompt(unit.context)
      ) {
        throw new Error(`Prompt snapshot digest mismatch for ${unit.asset}.`);
      }
    }
    if (digestJson(unit.settings) !== digestJson(plan.generationSettings)) {
      throw new Error(`Generation settings mismatch for ${unit.asset}.`);
    }
  }
}

/** Future live adapters must call this immediately before dispatch. */
export function assertApprovedPlanDigest(
  plan: ExperimentPlan,
  approvedPlanDigest: string | undefined,
): void {
  if (!approvedPlanDigest || approvedPlanDigest !== plan.digest) {
    throw new Error(
      `Live execution is unauthorized: --approved-plan-digest must exactly equal persisted plan digest ${plan.digest}.`,
    );
  }
}

export async function verifyPlanUnitInputs(
  plan: ExperimentPlan,
  unit: ExperimentUnit,
  repoRoot = process.cwd(),
): Promise<void> {
  if (
    !plan.units.some((candidate) => digestJson(candidate) === digestJson(unit))
  )
    throw new Error(`Unit ${unit.asset} is not bound to plan ${plan.digest}.`);
  const snapshots = [
    unit.inputs.xlsx,
    unit.inputs.approvedRecipe,
    unit.inputs.expectedCsv,
    unit.inputs.expectedOverlay,
    unit.inputs.metadata,
    ...Object.values(unit.inputs.expectedCsvs ?? {}),
  ].filter((entry): entry is { path: string; digest: string } =>
    Boolean(entry),
  );
  for (const snapshot of snapshots) {
    const safePath = await contained(
      repoRoot,
      snapshot.path,
      true,
      "INPUT_PATH_ESCAPE",
    );
    const actual = sha256(await readFile(safePath));
    if (actual !== snapshot.digest)
      throw new Error(`Input digest mismatch for ${snapshot.path}.`);
  }
}

export function digestLiveValidationResult(result: PairedAssetResult): string {
  const { liveExecution: ignored, ...payload } = result;
  void ignored;
  return digestCanonicalJson({
    ...payload,
    schemaVersion: "cell-role-paired-result-v3",
  });
}

export async function readPersistedResults(
  plan: ExperimentPlan,
  repoRoot = process.cwd(),
  options: { verifyLiveState?: boolean } = {},
): Promise<PairedAssetResult[]> {
  const unitRoot = await contained(
    repoRoot,
    path.join(plan.outputRoot, plan.runId, "units"),
    false,
    "RESULT_PATH_ESCAPE",
  );
  let names: string[];
  try {
    await assertNoIncompleteArtifacts(unitRoot);
    names = await readdir(unitRoot);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
  const units = new Map(plan.units.map((unit) => [unit.asset, unit]));
  const results: PairedAssetResult[] = [];
  const seen = new Set<string>();
  for (const name of names.filter((entry) => entry.endsWith(".json")).sort()) {
    const resultPath = await contained(
      unitRoot,
      name,
      true,
      "RESULT_FILE_PATH_ESCAPE",
    );
    const resultBytes = await readFile(resultPath);
    const parsed = pairedResultSchema.parse(
      validateEvidencePayload({
        bytes: resultBytes,
        mediaType: "application/json",
        role: "unit-result",
      }),
    ) as PairedAssetResult;
    const unit = units.get(parsed.asset);
    if (!unit)
      throw new Error(`Unexpected persisted result asset: ${parsed.asset}.`);
    if (seen.has(parsed.asset))
      throw new Error(`Duplicate persisted result asset: ${parsed.asset}.`);
    if (parsed.planDigest !== plan.digest)
      throw new Error(
        `Stale persisted result plan digest for ${parsed.asset}.`,
      );
    if (parsed.unitDigest !== digestJson(unit))
      throw new Error(
        `Stale persisted result unit digest for ${parsed.asset}.`,
      );
    if (
      plan.schemaVersion === "cell-role-experiment-plan-v3" ||
      plan.schemaVersion === "cell-role-experiment-plan-v4"
    ) {
      if (
        (parsed.schemaVersion !== "cell-role-paired-result-v3" &&
          parsed.schemaVersion !== "cell-role-paired-result-v4") ||
        parsed.provenanceDigest !== plan.implementationProvenanceDigest ||
        (parsed.schemaVersion === "cell-role-paired-result-v4" &&
          (parsed.liveExecution!.implementationProvenanceDigest !==
            plan.implementationProvenanceDigest ||
            parsed.liveExecution!.settingsDigest !==
              digestJson(plan.generationSettings)))
      ) {
        throw new Error(
          `Stale persisted deterministic result provenance for ${parsed.asset}.`,
        );
      }
      assertDeterministicResultAccounting(plan, parsed);
    } else if (plan.schemaVersion === "cell-role-experiment-plan-v2") {
      if (
        parsed.schemaVersion !== "cell-role-paired-result-v2" ||
        parsed.provenanceDigest !== plan.implementationProvenanceDigest
      ) {
        throw new Error(
          `Stale persisted result provenance for ${parsed.asset}.`,
        );
      }
    } else if (parsed.schemaVersion !== "cell-role-paired-result-v1") {
      throw new Error(
        `Unexpected provenance result for legacy plan ${parsed.asset}.`,
      );
    }
    seen.add(parsed.asset);
    results.push(parsed);
  }
  if (
    options.verifyLiveState !== false &&
    results.some(
      (result) => result.schemaVersion === "cell-role-paired-result-v4",
    )
  ) {
    const { verifyLiveRunState } = await import("./live-state");
    await verifyLiveRunState({
      plan,
      repoRoot,
      committedResults: results,
    });
  }
  return results;
}

function assertDeterministicResultAccounting(
  plan:
    | z.infer<typeof deterministicPlanSchema>
    | z.infer<typeof compactPlanSchema>,
  result: PairedAssetResult,
): void {
  if (
    !result.providerCallBudget ||
    digestJson(result.providerCallBudget) !==
      digestJson(plan.providerCallBudget)
  ) {
    throw new Error(`RESULT_PROVIDER_CALL_BUDGET_MISMATCH: ${result.asset}`);
  }
  const researchEnabled = plan.researchArms.includes(
    "llm-translation-research",
  );
  if (Boolean(result.llmTranslationResearch) !== researchEnabled) {
    throw new Error(`RESULT_RESEARCH_ARM_BINDING_MISMATCH: ${result.asset}`);
  }
  const actual = {
    baseline: result.baseline.providerAttempts,
    staged: result.staged.providerAttempts,
    llmTranslationResearch:
      result.llmTranslationResearch?.providerAttempts ?? 0,
  };
  const total = actual.baseline + actual.staged + actual.llmTranslationResearch;
  if (
    actual.baseline > plan.providerCallBudget.perUnit.baseline ||
    actual.staged > plan.providerCallBudget.perUnit.staged ||
    actual.llmTranslationResearch >
      plan.providerCallBudget.perUnit.llmTranslationResearch ||
    total > plan.providerCallBudget.perUnit.total
  ) {
    throw new Error(`RESULT_PROVIDER_CALL_BUDGET_EXCEEDED: ${result.asset}`);
  }
}

export type ReportEvidenceOptions = {
  evidenceManifestPath?: string;
};

export async function buildProvenanceVerifiedComparisonReport(
  plan: ExperimentPlan,
  results: PairedAssetResult[],
  repoRoot = process.cwd(),
  options: ReportEvidenceOptions = {},
) {
  if (plan.schemaVersion === "cell-role-experiment-plan-v1") {
    return buildComparisonReport(results);
  }
  await verifyImplementationProvenance(plan.implementationProvenance, repoRoot);
  if (!options.evidenceManifestPath) {
    throw new Error(
      "REPORT_EVIDENCE_MANIFEST_REQUIRED: --evidence-manifest must bind the plan and every persisted unit result.",
    );
  }
  const evidenceManifestDigest = await verifyReportEvidenceManifest(
    plan,
    results,
    options.evidenceManifestPath,
    repoRoot,
  );
  const graphReferenceAvailability =
    await resolvePlanGraphReferenceAvailability(plan, repoRoot);
  return buildCorrectedComparisonReport({
    runId: plan.runId,
    planDigest: plan.digest,
    implementationDigest: plan.implementationProvenanceDigest,
    experimentImplementationDigest: plan.implementationProvenanceDigest,
    evidenceManifestDigest,
    graphReferenceEvidenceManifestDigests: [evidenceManifestDigest],
    unitDigests: plan.units.map((unit) => ({
      asset: unit.asset,
      unitDigest: digestJson(unit),
    })),
    graphReferenceAvailability,
    results,
    ...(plan.schemaVersion === "cell-role-experiment-plan-v3" ||
    plan.schemaVersion === "cell-role-experiment-plan-v4"
      ? { providerCallBudget: plan.providerCallBudget }
      : {}),
  });
}

export async function finalizePersistedResults(
  plan: ExperimentPlan,
  repoRoot = process.cwd(),
  options: ReportEvidenceOptions = {},
) {
  const results = await readPersistedResults(plan, repoRoot);
  const expectedAssets = plan.units.map((unit) => unit.asset).sort();
  const actualAssets = results.map((result) => result.asset).sort();
  if (JSON.stringify(actualAssets) !== JSON.stringify(expectedAssets)) {
    const completed = new Set(actualAssets);
    const pending = expectedAssets.filter((asset) => !completed.has(asset));
    throw new Error(
      `Cannot finalize incomplete results. Pending: ${pending.join(", ") || "none"}. Unexpected: none.`,
    );
  }
  const report = await buildProvenanceVerifiedComparisonReport(
    plan,
    results,
    repoRoot,
    options,
  );
  const output = await contained(
    repoRoot,
    path.join(plan.outputRoot, plan.runId, "comparison.json"),
    false,
    "REPORT_PATH_ESCAPE",
  );
  await mkdir(path.dirname(output), { recursive: true });
  await writeImmutableEvidenceFile({
    repoRoot,
    target: output,
    bytes: renderComparisonReport(report),
    mediaType: "application/json",
    role: "comparison-report",
    pathErrorCode: "REPORT_PATH_ESCAPE",
  });
  return report;
}

async function verifyReportEvidenceManifest(
  plan: ExperimentPlan,
  results: PairedAssetResult[],
  manifestPath: string,
  repoRoot: string,
): Promise<string> {
  const safeManifest = await contained(
    repoRoot,
    manifestPath,
    true,
    "REPORT_EVIDENCE_MANIFEST_PATH_ESCAPE",
  );
  const manifestBytes = await readFile(safeManifest);
  const manifest = evidenceManifestSchema.parse(
    validateEvidencePayload({
      bytes: manifestBytes,
      mediaType: "application/json",
      role: "report-evidence-manifest",
    }),
  );
  if (manifest.runId !== plan.runId || manifest.planDigest !== plan.digest) {
    throw new Error("REPORT_EVIDENCE_MANIFEST_BINDING_MISMATCH");
  }
  const planEntries = manifest.entries.filter((entry) => entry.role === "plan");
  if (planEntries.length !== 1) {
    throw new Error("REPORT_EVIDENCE_PLAN_CARDINALITY_MISMATCH");
  }
  const unitEntries = manifest.entries.filter(
    (entry) => entry.role === "unit-result",
  );
  const expectedUnits = new Map(
    plan.units.map((unit) => [unit.asset, digestJson(unit)]),
  );
  if (
    expectedUnits.size !== plan.units.length ||
    new Set(expectedUnits.values()).size !== expectedUnits.size
  ) {
    throw new Error("REPORT_EVIDENCE_DUPLICATE_PLANNED_UNIT_IDENTITY");
  }
  const manifestUnits = new Map<string, string>();
  const manifestUnitDigests = new Set<string>();
  for (const entry of unitEntries) {
    if (
      !entry.asset ||
      !entry.unitDigest ||
      manifestUnits.has(entry.asset) ||
      manifestUnitDigests.has(entry.unitDigest)
    ) {
      throw new Error("REPORT_EVIDENCE_DUPLICATE_UNIT_IDENTITY");
    }
    manifestUnits.set(entry.asset, entry.unitDigest);
    manifestUnitDigests.add(entry.unitDigest);
  }
  if (unitMapFingerprint(manifestUnits) !== unitMapFingerprint(expectedUnits)) {
    throw new Error("REPORT_EVIDENCE_UNIT_SET_MISMATCH");
  }

  const reportedResults = new Map<string, PairedAssetResult>();
  const reportedUnitDigests = new Set<string>();
  for (const result of results) {
    if (
      reportedResults.has(result.asset) ||
      reportedUnitDigests.has(result.unitDigest)
    ) {
      throw new Error("REPORT_EVIDENCE_DUPLICATE_REPORTED_RESULT");
    }
    reportedResults.set(result.asset, result);
    reportedUnitDigests.add(result.unitDigest);
  }
  const reportedUnits = new Map(
    [...reportedResults].map(([asset, result]) => [asset, result.unitDigest]),
  );
  if (
    unitMapFingerprint(reportedUnits) !== unitMapFingerprint(expectedUnits) ||
    unitMapFingerprint(reportedUnits) !== unitMapFingerprint(manifestUnits)
  ) {
    throw new Error("REPORT_EVIDENCE_REPORTED_RESULT_SET_MISMATCH");
  }
  const manifestPayloadUnits = new Map<string, string>();
  const manifestPayloadUnitDigests = new Set<string>();
  const manifestDirectory = path.dirname(safeManifest);
  for (const entry of manifest.entries) {
    const bytes = await readContainedArtifact({
      repoRoot,
      target: path.join(manifestDirectory, entry.path),
      pathErrorCode: "REPORT_EVIDENCE_PAYLOAD_PATH_ESCAPE",
    });
    if (
      bytes.byteLength !== entry.bytes ||
      sha256Bytes(bytes) !== entry.sha256
    ) {
      throw new Error(`REPORT_EVIDENCE_PAYLOAD_DIGEST_MISMATCH: ${entry.path}`);
    }
    const parsed = validateEvidencePayload({
      bytes,
      mediaType: entry.mediaType,
      role: `report-evidence-${entry.role}`,
    });
    if (entry.role === "plan") {
      const manifestPlan = parseExperimentPlan(parsed);
      if (digestCanonicalJson(manifestPlan) !== digestCanonicalJson(plan)) {
        throw new Error("REPORT_EVIDENCE_PLAN_MISMATCH");
      }
    }
    if (entry.role === "unit-result") {
      const manifestResult = pairedResultSchema.parse(
        parsed,
      ) as PairedAssetResult;
      if (
        manifestPayloadUnits.has(manifestResult.asset) ||
        manifestPayloadUnitDigests.has(manifestResult.unitDigest)
      ) {
        throw new Error(
          `REPORT_EVIDENCE_DUPLICATE_UNIT_PAYLOAD_IDENTITY: ${entry.path}`,
        );
      }
      if (
        entry.schemaType !== manifestResult.schemaVersion ||
        entry.planDigest !== manifestResult.planDigest ||
        entry.asset !== manifestResult.asset ||
        entry.unitDigest !== manifestResult.unitDigest
      ) {
        throw new Error(
          `REPORT_EVIDENCE_UNIT_PAYLOAD_BINDING_MISMATCH: ${entry.path}`,
        );
      }
      manifestPayloadUnits.set(manifestResult.asset, manifestResult.unitDigest);
      manifestPayloadUnitDigests.add(manifestResult.unitDigest);
      const reported = reportedResults.get(manifestResult.asset);
      if (
        !reported ||
        digestCanonicalJson(manifestResult) !== digestCanonicalJson(reported)
      ) {
        throw new Error(
          `REPORT_EVIDENCE_RESULT_MISMATCH: ${manifestResult.asset}`,
        );
      }
    }
  }
  if (
    unitMapFingerprint(manifestPayloadUnits) !==
      unitMapFingerprint(expectedUnits) ||
    unitMapFingerprint(manifestPayloadUnits) !==
      unitMapFingerprint(manifestUnits) ||
    unitMapFingerprint(manifestPayloadUnits) !==
      unitMapFingerprint(reportedUnits)
  ) {
    throw new Error("REPORT_EVIDENCE_UNIT_PAYLOAD_SET_MISMATCH");
  }
  return sha256Bytes(manifestBytes);
}

function unitMapFingerprint(units: Map<string, string>): string {
  return JSON.stringify(
    [...units].sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0,
    ),
  );
}

async function resolvePlanGraphReferenceAvailability(
  plan: ExperimentPlan,
  repoRoot: string,
): Promise<Record<string, boolean>> {
  const entries = [] as Array<[string, boolean]>;
  for (const unit of plan.units) {
    await verifyPlanUnitInputs(plan, unit, repoRoot);
    const snapshots = unit.inputs.expectedCsvs
      ? Object.values(unit.inputs.expectedCsvs)
      : unit.inputs.expectedCsv
        ? [unit.inputs.expectedCsv]
        : [];
    const graphs = [];
    for (const snapshot of snapshots) {
      const bytes = await readFile(
        await contained(
          repoRoot,
          snapshot.path,
          true,
          "EXPECTED_INPUT_PATH_ESCAPE",
        ),
      );
      graphs.push(buildTableGraph(parseCsv(bytes.toString("utf8"))));
    }
    entries.push([
      unit.asset,
      graphs.some((graph) => graph.hasValueSources && graph.hasHeaderSources),
    ]);
  }
  return Object.fromEntries(
    entries.sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0,
    ),
  );
}

function snapshotBenchmarkAsset(asset: BenchmarkAsset): BenchmarkAsset {
  return {
    name: asset.name,
    xlsx: asset.xlsx,
    recipe: asset.recipe,
    expected_csv: asset.expected_csv,
    expected_csvs: asset.expected_csvs,
    metadata: asset.metadata,
    expected_overlay: asset.expected_overlay,
    enabled: asset.enabled,
    ci_smoke: asset.ci_smoke,
    disabled_reason: asset.disabled_reason,
    difficulty: asset.difficulty,
    features: asset.features,
    repeat_of: asset.repeat_of,
    repeat_index: asset.repeat_index,
  };
}

async function assertAssetPathsContained(
  asset: BenchmarkAsset,
  repoRoot: string,
) {
  const paths = [
    asset.xlsx,
    asset.recipe,
    asset.expected_csv,
    asset.expected_overlay,
    asset.metadata,
    ...Object.values(asset.expected_csvs ?? {}),
  ].filter((value): value is string => Boolean(value));
  for (const value of paths)
    await contained(repoRoot, value, true, "ASSET_PATH_ESCAPE");
}

async function readExpectedCsvContents(
  asset: BenchmarkAsset,
  repoRoot: string,
): Promise<string[]> {
  const paths = [
    asset.expected_csv,
    ...Object.values(asset.expected_csvs ?? {}),
  ].filter((value): value is string => Boolean(value));
  return Promise.all(
    paths.map(async (value) =>
      readFile(
        await contained(repoRoot, value, true, "EXPECTED_INPUT_PATH_ESCAPE"),
        "utf8",
      ),
    ),
  );
}

async function snapshotAssetInputs(asset: BenchmarkAsset, repoRoot: string) {
  const snapshot = async (value: string, code: string) => {
    const safePath = await contained(repoRoot, value, true, code);
    return { path: value, digest: sha256(await readFile(safePath)) };
  };
  const expectedCsvs = asset.expected_csvs
    ? Object.fromEntries(
        await Promise.all(
          Object.entries(asset.expected_csvs)
            .sort(([left], [right]) => left.localeCompare(right))
            .map(async ([name, value]) => [
              name,
              await snapshot(value, "EXPECTED_INPUT_PATH_ESCAPE"),
            ]),
        ),
      )
    : undefined;
  return {
    xlsx: await snapshot(asset.xlsx, "WORKBOOK_PATH_ESCAPE"),
    approvedRecipe: await snapshot(asset.recipe, "RECIPE_PATH_ESCAPE"),
    expectedCsv: asset.expected_csv
      ? await snapshot(asset.expected_csv, "EXPECTED_INPUT_PATH_ESCAPE")
      : undefined,
    expectedCsvs,
    expectedOverlay: asset.expected_overlay
      ? await snapshot(asset.expected_overlay, "EXPECTED_INPUT_PATH_ESCAPE")
      : undefined,
    metadata: asset.metadata
      ? await snapshot(asset.metadata, "EXPECTED_INPUT_PATH_ESCAPE")
      : undefined,
  };
}

async function contained(
  root: string,
  value: string,
  mustExist: boolean,
  code: string,
): Promise<string> {
  return resolveContainedPath({ root, value, mustExist, code });
}

export function digestJson(value: unknown): string {
  return digestCanonicalJson(value);
}

function sha256(value: Uint8Array): string {
  return sha256Bytes(value);
}
