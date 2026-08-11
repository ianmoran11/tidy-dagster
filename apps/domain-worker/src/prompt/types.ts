/* Ported type subset from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import type {
  ProducedCsvColumnSummary,
  ProducedCsvSuspiciousRows,
} from "../review/types.js";
import type {
  HeaderCandidate,
  SheetSummary,
  TableContextFormat,
} from "../summary/types.js";
import type { ParsedSheet } from "../workbook/types.js";
import type {
  CandidateRangeHintProvenance,
  ProjectedCandidateRangeHint,
} from "./candidateRangeHints.js";
import type { MlPrepassResult } from "./ml/types.js";
import type {
  OntologyPromptInput,
  OntologyPromptProvenance,
  PublicationOntologyPromptFeature,
} from "./ontology/promptHints.js";
import type { PromptVariant } from "./promptVariants.js";

export type PromptExample = { filename: string; recipe: unknown };
export type RecipeGenerationProvider = "openrouter" | "pi" | "claude";
export type RecipeGenerationPipelineMode = "legacy" | "cell_role_v5_canary";
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
  validationErrors?: unknown[];
  autoFixRecords?: unknown[];
  summaries: SheetSummary[];
  pipelineMode?: RecipeGenerationPipelineMode;
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
  neuralPolicyOptions?: {
    highConfidenceThreshold?: number;
    mediumConfidenceThreshold?: number;
    maxLowConfidenceCellsForDraft?: number;
    allowDirectDraft?: boolean;
  };
};
export type GenerationSpeed = "standard" | "fast";
export type PromptCachingMode = "off" | "provider";
export type NeuralPromptMode = "hints" | "compact";
export type NeuralGenerationPolicy = "off" | "auto" | "draft_only";
export type TableStructureMode = "auto" | "single_table";
