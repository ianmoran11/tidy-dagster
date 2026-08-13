import {
  formatRoleAwareCorrectionDiagnostics,
  renderRoleAwareSemanticRegionCatalog,
  type RoleAwareCompilationFailure,
  type RoleAwareSemanticRegionCatalog,
} from "../catalog/role-aware-region-catalog-v5.js";
import type { SemanticTableMapV1 } from "../catalog/semantic-map-v1.js";

export const SEMANTIC_MAP_V13_PROMPT_VERSION =
  "cell-role-semantic-map-v13-adjacent-year-aware" as const;
export const SEMANTIC_MAP_V13_CORRECTION_PROMPT_VERSION =
  "cell-role-semantic-map-v13-compact-correction-1" as const;

const RULES = [
  "The catalog's use= labels are geometric suggestions, not semantic decisions. You must decide the semantic name, membership, hierarchy, and direction.",
  "Formatting is structural evidence, not semantic truth. Matching indentation, bold, italic, underline, font, fill, alignment, or borders may indicate one header level when nearby geometry agrees. Differently indented or formatted cells may indicate separate levels.",
  "Numeric-looking coordinates can resemble observations. When the catalog offers a trimmed-leading-header observation alternative and a matching leading formatted header row, decide their roles semantically and do not select the same cells as both values and members.",
  "Integer numeric cells from 1900 through 2099 are marked as year-like evidence only when they form a local adjacent horizontal or vertical run. Adjacency and orientation strengthen a possible year-coordinate interpretation but do not prove it; inspect surrounding labels and formatting, and do not infer a year from an isolated in-range number alone.",
  "For every dimension choose N (directly above/by column), W (directly left/by row), NNW (higher group cascading across columns), or WNW (higher group cascading across rows).",
  "Apply the tidy-row coordinate test: coordinates that apply simultaneously to one observation are separate dimensions; mutually exclusive sections at the same structural level should share a generic dimension.",
  "Account for every plausible direct-row and direct-column group adjacent to selected observations. If one is only a caption rather than members, do not place it in memberRegions; captionHints may reference it for trace-only reasoning.",
  "Account for plausible cascading-row and cascading-column groups that label repeated sections or higher header levels. Decide whether each is a separate simultaneously applicable dimension, a mutually exclusive member group, or only a caption; captionHints may record the caption case.",
  "Represent every observation panel belonging to this one table. Prefer compact repeated-panel groups when they exactly cover the intended role.",
] as const;

export function buildSemanticMapV13Prompt(
  context: { schemaVersion: string; digest: string; serialized: string },
  catalog: RoleAwareSemanticRegionCatalog,
): string {
  return [
    "Describe the meaning and shape of exactly one spreadsheet table. You perform semantic decisions only; deterministic code handles addresses, merges, IDs, CellRoleSketch, RecipeV01, selector expansion, validation, and compilation.",
    ...RULES,
    "Return JSON only in exactly this shape:",
    semanticMapExample(),
    "Do not return addresses, ranges, XML, recipe JSON, evidence prose, alternatives, uncertainty, Markdown, or commentary.",
    `Prompt contract: ${SEMANTIC_MAP_V13_PROMPT_VERSION}; context schema: ${context.schemaVersion}; context digest: ${context.digest}; catalog schema: ${catalog.version}; candidates: ${catalog.candidates.length}; observation panels: ${catalog.observationPanelCount}; omitted candidates: ${catalog.omittedCandidateCount}.`,
    "BEGIN_ROLE_FORMAT_AWARE_REGION_CATALOG",
    renderRoleAwareSemanticRegionCatalog(catalog),
    "END_ROLE_FORMAT_AWARE_REGION_CATALOG",
    "BEGIN_COMPACT_CONTEXT",
    context.serialized,
    "END_COMPACT_CONTEXT",
  ].join("\n");
}

export function buildSemanticMapV13CorrectionPrompt({
  context,
  previousMap,
  diagnostics,
  correctionCatalog,
}: {
  context: { schemaVersion: string; digest: string };
  previousMap: SemanticTableMapV1;
  diagnostics: string;
  correctionCatalog: RoleAwareSemanticRegionCatalog;
}): string {
  return [
    "Revise one semantic table map after deterministic factual diagnostics. You have exactly one correction opportunity; this is not a provider retry.",
    ...RULES,
    "Return one complete revised JSON object in exactly this shape and nothing else:",
    semanticMapExample(),
    `Correction contract: ${SEMANTIC_MAP_V13_CORRECTION_PROMPT_VERSION}; context schema: ${context.schemaVersion}; context digest: ${context.digest}.`,
    "BEGIN_PREVIOUS_SEMANTIC_MAP",
    JSON.stringify(previousMap),
    "END_PREVIOUS_SEMANTIC_MAP",
    "BEGIN_FACTUAL_DIAGNOSTICS",
    diagnostics,
    "END_FACTUAL_DIAGNOSTICS",
    "BEGIN_RELEVANT_CANDIDATES",
    renderRoleAwareSemanticRegionCatalog(correctionCatalog),
    "END_RELEVANT_CANDIDATES",
  ].join("\n");
}

export function formatSemanticMapCorrectionDiagnostics({
  failure,
  completenessDiagnostics,
}: {
  failure: RoleAwareCompilationFailure;
  completenessDiagnostics: Parameters<
    typeof formatRoleAwareCorrectionDiagnostics
  >[0]["completenessDiagnostics"];
}): string {
  return formatRoleAwareCorrectionDiagnostics({
    failure,
    completenessDiagnostics,
  });
}

function semanticMapExample(): string {
  return JSON.stringify(
    {
      version: "semantic-table-map-v1",
      table: {
        name: "descriptive table name",
        values: { name: "observation value name", regions: ["region-001"] },
        dimensions: [
          {
            name: "dimension name",
            memberRegions: ["region-002"],
            direction: "N",
            captionHints: ["region-003"],
          },
        ],
      },
    },
    null,
    2,
  );
}
