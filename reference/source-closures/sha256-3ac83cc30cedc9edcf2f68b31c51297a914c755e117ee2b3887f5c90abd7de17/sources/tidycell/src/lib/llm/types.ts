import type { RecipeValidationIssue } from "@/lib/recipe/schema";
import type { AutoFixChange } from "@/lib/recipe/autoFix";
import type { RecipeV01 } from "@/lib/recipe/types";
import type {
  CandidateRangeHintProvenance,
  ProjectedCandidateRangeHint,
} from "@/lib/llm/candidateRangeHints";
import type { PromptVariant } from "@/lib/llm/promptVariants";
import type { MlPrepassResult } from "@/lib/ml-prepass/types";
import type {
  OntologyPromptInput,
  OntologyPromptProvenance,
  PublicationOntologyPromptFeature,
} from "@/lib/ontology/promptHints";
import type {
  HeaderCandidate,
  SheetSummary,
  TableContextFormat,
} from "@/lib/summary/types";
import type { ParsedSheet } from "@/lib/workbook/types";

export type PromptExample = {
  filename: string;
  recipe: RecipeV01;
};

export type RecipeGenerationProvider = "openrouter" | "pi" | "claude";

export type RecipeGenerationPipelineMode = "legacy" | "cell_role_v5_canary";

export type CellRoleV5CanaryAttemptReport = {
  providerOk: boolean;
  mapValid: boolean;
  geometryValid: boolean;
  completenessDiagnosticCount: number;
  latencyMs?: number;
  failure?: string;
};

export type CellRoleV5CanarySheetReport = {
  sheet: string;
  contextDigest?: string;
  estimatedTokens?: number;
  catalogCandidates?: number;
  catalogOmitted?: number;
  yearLikeCells?: number;
  horizontallyAdjacentYearLikeCells?: number;
  verticallyAdjacentYearLikeCells?: number;
  yearEvidenceCandidates?: number;
  selectedYearEvidenceCandidates?: number;
  firstPass?: CellRoleV5CanaryAttemptReport;
  correction?: CellRoleV5CanaryAttemptReport & {
    attempted: boolean;
    trigger?: "geometry" | "completeness";
  };
  finalSource?: "first-pass" | "correction";
  recipeValid: boolean;
  finalCompletenessDiagnosticCount?: number;
  warningCount?: number;
  executionRowCount?: number;
  executionWarningCount?: number;
  failure?: string;
};

export type CellRoleV5CanaryReport = {
  version: "cell-role-semantic-map-v5-canary-v1";
  promptVersion: "cell-role-semantic-map-v13-adjacent-year-aware";
  requested: true;
  enabled: boolean;
  attempted: boolean;
  succeeded: boolean;
  fallback: boolean;
  fallbackReason?: string;
  model: string;
  providerCallCount: number;
  latencyMs: number;
  sheets: CellRoleV5CanarySheetReport[];
  usage?: LlmUsage;
};

export type PromptTextBlock = {
  type: "text";
  text: string;
  cache_control?: { type: "ephemeral" };
};

export type PromptMessage = {
  role: "user";
  content: string | PromptTextBlock[];
};

export type PromptSectionPlacement = "static" | "dynamic";

export type PromptSectionSize = {
  id: string;
  placement: PromptSectionPlacement;
  chars: number;
};

export type PromptBundle = {
  provider: RecipeGenerationProvider;
  model: string;
  messages: PromptMessage[];
  examples: Array<{ filename: string; included: boolean; reason?: string }>;
  summaries: SheetSummary[];
  header_lists: Record<string, HeaderCandidate[]>;
  table_context_format: TableContextFormat;
  table_structure_mode: TableStructureMode;
  table_contexts: Record<
    string,
    {
      sheet: string;
      format: TableContextFormat;
      content: string;
      expanded_available: boolean;
      truncated: boolean;
      estimated_chars: number;
    }
  >;
  table_markdown: Record<string, string>;
  table_html_expanded?: Record<string, string>;
  neural_prepass?: unknown[];
  ontology_hints?: unknown[];
  publication_ontology_hints?: unknown[];
  candidate_range_hints?: ProjectedCandidateRangeHint[];
  candidate_range_hint_provenance: CandidateRangeHintProvenance;
  ontology_prompt_provenance: OntologyPromptProvenance;
  estimated_chars: number;
  section_sizes: PromptSectionSize[];
  warnings: string[];
};

export type GenerateRecipeRequest = {
  provider?: RecipeGenerationProvider;
  mode?: "generate" | "repair" | "review";
  previousRecipe?: unknown;
  validationErrors?: RecipeValidationIssue[];
  autoFixRecords?: AutoFixChange[];
  summaries: SheetSummary[];
  pipelineMode?: RecipeGenerationPipelineMode;
  /** Full selected-sheet evidence, sent only for the guarded V5 canary. */
  semanticMapSheets?: ParsedSheet[];
  intent?: string;
  model?: string;
  inspectOnly?: boolean;
  openRouterApiKey?: string;
  piProvider?: string;
  tableContextMode?: TableContextFormat;
  tableStructureMode?: TableStructureMode;
  promptVariant?: PromptVariant;
  examples?: PromptExample[];
  customPrompt?: string;
  promptAppend?: string;
  generationSpeed?: GenerationSpeed;
  promptCaching?: PromptCachingMode;
  reasoningEffort?: "low" | "medium" | "high";
  producedCsvSample?: string;
  producedCsvColumnSummary?: ProducedCsvColumnSummary;
  producedCsvSuspiciousRows?: ProducedCsvSuspiciousRows;
  producedCsvDuplicates?: string;
  userGuidance?: string;
  neuralPrepass?: MlPrepassResult | MlPrepassResult[];
  ontologyHints?: OntologyPromptInput | OntologyPromptInput[];
  publicationOntologyPrompt?: PublicationOntologyPromptFeature;
  neuralPromptMode?: NeuralPromptMode;
  neuralPolicy?: NeuralGenerationPolicy;
  /** Experiment-only override; production defaults remain in generationPolicy.ts. */
  neuralPolicyOptions?: {
    highConfidenceThreshold?: number;
    mediumConfidenceThreshold?: number;
    maxLowConfidenceCellsForDraft?: number;
    allowDirectDraft?: boolean;
  };
};

export type ProducedCsvColumnSummary = Array<{
  table: string;
  row_count: number;
  unique_row_key_count: number;
  duplicate_header_key_count: number;
  duplicate_header_row_count: number;
  duplicate_header_key_share: number;
  columns: Array<{
    name: string;
    unique_count: number;
    empty_count: number;
    missing_share: number;
    high_missing_share: boolean;
    numeric_parse_share: number;
    values: string[];
    truncated: boolean;
  }>;
  column_pair_overlap: Array<{
    columns: [string, string];
    both_present_share: number;
    left_only_share: number;
    right_only_share: number;
    neither_present_share: number;
    complementary_missing_share: number;
  }>;
}>;

export type ProducedCsvSuspiciousRows = {
  duplicate_header_keys: Array<{
    table: string;
    key_columns: string[];
    key_values: Record<string, string>;
    row_count: number;
    rows: Array<Record<string, string>>;
  }>;
  low_numeric_value_rows: Array<{
    table: string;
    column: string;
    numeric_parse_share: number;
    rows: Array<Record<string, string>>;
  }>;
  high_missing_column_rows: Array<{
    table: string;
    column: string;
    missing_share: number;
    rows: Array<Record<string, string>>;
  }>;
  sparse_column_pair_rows: Array<{
    table: string;
    columns: [string, string];
    complementary_missing_share: number;
    rows: Array<Record<string, string>>;
  }>;
};

export type GenerationSpeed = "standard" | "fast";
export type PromptCachingMode = "off" | "provider";
export type NeuralPromptMode = "hints" | "compact";
export type NeuralGenerationPolicy = "off" | "auto" | "draft_only";
export type TableStructureMode = "auto" | "single_table";

export type GenerateRecipeSuccess = {
  ok: true;
  model: string;
  provider?: RecipeGenerationProvider;
  recipes: RecipeV01[];
  promptBundle?: PromptBundle;
  generationSource?:
    | "llm"
    | "pi"
    | "claude"
    | "neural_draft"
    | "cell_role_v5_canary";
  generationMs?: number;
  usage?: LlmUsage;
  cellRoleV5Canary?: CellRoleV5CanaryReport;
};

export type LlmUsage = {
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  cachedTokens?: number;
  cacheCreationInputTokens?: number;
  cacheReadInputTokens?: number;
  /** Provider-reported cache writes, retained separately from cache reads. */
  cacheWriteInputTokens?: number;
  /** Reasoning is a subset of completion tokens when the provider exposes it. */
  reasoningTokens?: number;
  /** Observed/catalog-priced API spend; omitted for subscription-backed calls. */
  catalogPricedUsd?: number;
  /** Catalog/API-equivalent price, never the actual charge for subscription-backed calls. */
  apiEquivalentUsd?: number;
  usageSource?: "provider_observed" | "char_estimate" | "mixed" | "unknown";
};

export type GenerateRecipeFailure = {
  ok: false;
  cellRoleV5Canary?: CellRoleV5CanaryReport;
  errors: Array<{
    code: string;
    message: string;
    path?: string;
    validationErrors?: RecipeValidationIssue[];
  }>;
};

export type GenerateRecipeResponse =
  | GenerateRecipeSuccess
  | GenerateRecipeFailure;
