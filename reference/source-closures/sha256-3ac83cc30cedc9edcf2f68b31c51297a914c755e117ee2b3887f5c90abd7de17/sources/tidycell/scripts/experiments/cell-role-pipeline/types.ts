import type { LlmUsage } from "../../../src/lib/llm/types";
import type { RecipeV01 } from "../../../src/lib/recipe/types";
import type { SheetSummary } from "../../../src/lib/summary/types";
import type { ParsedSheet } from "../../../src/lib/workbook/types";
import type {
  AssetBenchmarkSummary,
  BenchmarkAsset,
} from "../../benchmark/types";

export const RELATIONSHIP_KINDS = [
  "direct-column",
  "direct-row",
  "cascading-column",
  "cascading-row",
] as const;
export type RelationshipKind = (typeof RELATIONSHIP_KINDS)[number];

export type SketchSelector =
  | { kind: "address"; value: string }
  | { kind: "range"; value: string };

export type SketchCell = {
  id: string;
  address: string;
  evidence: string;
  selector: SketchSelector;
};

export type SketchDimension = {
  id: string;
  name: string;
  evidence: string;
  cells: SketchCell[];
};

export type SketchRelationship = {
  id: string;
  dimensionId: string;
  kind: RelationshipKind;
  evidence: string;
};

export type SketchTable = {
  id: string;
  name: string;
  boundary: string;
  evidence: string;
  valueName: string;
  values: SketchCell[];
  dimensions: SketchDimension[];
  relationships: SketchRelationship[];
};

export type CellRoleSketch = {
  version: "0.1";
  sheet: string;
  tables: SketchTable[];
  uncertainties: Array<{ id: string; evidence: string }>;
};

export type GenerationSettings = {
  provider: "openrouter" | "pi" | "claude";
  model: string;
  temperature: number;
  reasoning: "low" | "medium" | "high";
  timeoutMs: number;
  maxAttempts: 1;
};

export type ArmOrder = ["baseline", "staged"] | ["staged", "baseline"];
export type ResultArm = "baseline" | "staged" | "llm-translation-research";
export type PipelineMode =
  | "deterministic-compiler-v1"
  | "legacy-llm-translation-v1";

export type ProviderCallBudget = {
  perUnit: {
    baseline: number;
    staged: number;
    llmTranslationResearch: number;
    total: number;
  };
  maximumTotal: number;
};

export type ProviderRequest = {
  arm: ResultArm;
  stage: "baseline" | "semantics" | "translation";
  prompt: string;
  output: "xml" | "json";
  settings: GenerationSettings;
  armOrder: ArmOrder;
};

export type ProviderResult = {
  content: string;
  usage?: LlmUsage;
  durationMs: number;
};

export type ProviderFunction = (
  request: ProviderRequest,
) => Promise<ProviderResult>;

export type ArmMetrics = {
  finalJsonParseValid: boolean;
  schemaValid: boolean;
  semanticXmlValid: boolean;
  executable: boolean;
  nonempty: boolean;
  warningCount: number;
  benchmark: AssetBenchmarkSummary | null;
};

export type ArmResult = {
  arm: ResultArm;
  recipe: RecipeV01 | null;
  metrics: ArmMetrics;
  providerAttempts: number;
  providerResponses: number;
  providerFailures: number;
  callsWithUsage: number;
  usage: LlmUsage;
  durationMs: number;
  failures: string[];
  raw?: { semantics?: string; translation?: string; baseline?: string };
};

export type LiveExecutionEvidence = {
  authorizationDigest: string;
  implementationProvenanceDigest: string;
  executableDigest: string;
  oauthReadinessDigest: string;
  validationDigest: string;
  promptDigests: {
    baseline: string;
    semantics: string;
    translationResearch?: string;
  };
  settingsDigest: string;
  responseDigests: string[];
  orderedPredecessorEvidenceDigests: string[];
};

export type PairedAssetResult = {
  schemaVersion:
    | "cell-role-paired-result-v1"
    | "cell-role-paired-result-v2"
    | "cell-role-paired-result-v3"
    | "cell-role-paired-result-v4";
  planDigest: string;
  provenanceDigest?: string;
  unitDigest: string;
  asset: string;
  baseline: ArmResult;
  staged: ArmResult;
  providerCallBudget?: ProviderCallBudget;
  llmTranslationResearch?: ArmResult;
  liveExecution?: LiveExecutionEvidence;
};

export type PipelineInput = {
  asset: BenchmarkAsset;
  summary?: SheetSummary;
  worksheetBounds?: { rowCount: number; columnCount: number };
  relationshipSheet?: ParsedSheet;
  baselinePrompt: string;
  semanticsPrompt: string;
  translationPromptPreamble?: string;
  settings: GenerationSettings;
  pipelineMode?: PipelineMode;
  llmTranslationResearch?: {
    translationPromptPreamble: string;
  };
  providerCallBudget?: ProviderCallBudget;
  armOrder: ArmOrder;
  planDigest: string;
  provenanceDigest?: string;
  unitDigest: string;
};

export type BenchmarkScorer = (
  recipe: RecipeV01,
  arm: ResultArm,
) => Promise<{
  summary: AssetBenchmarkSummary;
  executable: boolean;
  nonempty: boolean;
  warningCount: number;
}>;
