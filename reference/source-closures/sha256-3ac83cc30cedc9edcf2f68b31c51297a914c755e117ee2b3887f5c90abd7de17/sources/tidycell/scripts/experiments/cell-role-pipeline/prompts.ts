import type { CompactContextSnapshot } from "./compact-context";

export const SEMANTICS_PROMPT_VERSION = "cell-role-semantics-v4";
export const BASELINE_PROMPT_VERSION = "cell-role-baseline-compact-v1";
export const TRANSLATION_PROMPT_VERSION = "cell-role-translation-v3";
export const SHARED_CONTEXT_BEGIN = "BEGIN_SHARED_WORKBOOK_CONTEXT";
export const SHARED_CONTEXT_END = "END_SHARED_WORKBOOK_CONTEXT";

export function buildSemanticsPrompt(context: CompactContextSnapshot): string {
  return [
    "You are analyzing spreadsheet meaning, not writing an extraction program.",
    "Identify observation/value cells, semantic tables, dimensions, hierarchy levels, header cells, and how each dimension relates to values.",
    "Relationship vocabulary:",
    "- direct-column: a header directly above values and mapped by column.",
    "- direct-row: a header directly left of values and mapped by row.",
    "- cascading-column: a distinct higher hierarchy level whose closest preceding header cascades across columns within scope.",
    "- cascading-row: a distinct higher hierarchy level whose closest preceding header cascades across rows within scope.",
    "Keep hierarchy levels separate: a direct label and a cascading group label are different Dimensions even when they share an axis. Each Dimension represents one concept at one hierarchy level and has exactly one Relationship kind.",
    "Use the complete compact workbook context below. Null grid entries are actual blank cells, not omitted evidence. Inspect all rows and columns, including late groups, sparse anchors, blank bands, notes, and footers.",
    "Return XML with exactly one CellRoleSketch root using version 0.2. Include one Table per semantic table; one Values selector; one Dimension per hierarchy level; and one Relationship per Dimension using direct-column, direct-row, cascading-column, or cascading-row.",
    'Required compact shape: <CellRoleSketch version="0.2" sheet="..."><Table id="..." name="..." evidence="..."><Values id="..." name="..."><Cell id="..." address="R1C1"/></Values><Dimension id="..." name="..." evidence="..."><Cell id="..." range="R1C1:R2C2"/></Dimension><Relationship id="..." dimensionId="..." kind="direct-column" evidence="..."/></Table><Uncertainty id="..." target="..." field="relationship" alternatives="choice A | choice B" evidence="..." blocking="true"/></CellRoleSketch>. Repeat elements as needed and omit Uncertainty when none remains.',
    "Selectors use canonical R1C1 address or range attributes on Cell elements. Use a compact range for a contiguous rectangle and individual addresses for a sparse set. The parser derives boundaries; do not author physical extents or selector boundaries.",
    "State concise observable evidence exactly once for each Table, Dimension, and Relationship. Do not repeat the workbook grid as prose.",
    "Represent unresolved interpretations with typed Uncertainty elements. Uncertainty.field is selector, dimension, table, relationship, or evidence; alternatives contains at least two distinct choices separated by '|'; blocking is true only when alternatives change selectors, dimensions, tables, or relationships.",
    "Use globally unique lowercase IDs. Do not add unknown attributes, mixed text, DTDs, declarations, entities beyond normal XML escaping, processing instructions, or CDATA.",
    "Do not discuss RecipeV01, direction codes, output JSON, transformations, benchmark targets, or implementation details.",
    `Prompt contract: ${SEMANTICS_PROMPT_VERSION}; context schema: ${context.schemaVersion}; context digest: ${context.digest}.`,
    buildSharedContextSection(context),
  ].join("\n");
}

export function buildCompactBaselinePrompt(
  context: CompactContextSnapshot,
): string {
  return [
    "Generate one RecipeV01 extraction recipe from the complete workbook evidence below.",
    "Return strict JSON only with version 0.1, the worksheet name, and semantic tables containing values and headers.",
    'Each selector is either {"range":"R1C1:R2C2"} for one contiguous rectangle or {"cells":["R1C1","R3C1"]} for sparse cells.',
    'Header directions are "N" for direct column headers, "W" for direct row headers, "NNW" for cascading column headers, and "WNW" for cascading row headers.',
    "Do not include filters, fills, options, direction overrides, inferred cells, commentary, Markdown, or any evidence not present in the shared context.",
    "Null grid entries are actual blank cells, not omitted evidence. Inspect every row and column, including late groups, sparse anchors, blank bands, notes, and footers.",
    `Prompt contract: ${BASELINE_PROMPT_VERSION}; context schema: ${context.schemaVersion}; context digest: ${context.digest}.`,
    buildSharedContextSection(context),
  ].join("\n");
}

export function buildSharedContextSection(
  context: CompactContextSnapshot,
): string {
  return [
    `${SHARED_CONTEXT_BEGIN} schema=${context.schemaVersion} digest=${context.digest} bytes=${context.bytes}`,
    context.serialized,
    SHARED_CONTEXT_END,
  ].join("\n");
}

export function buildTranslationPromptPreamble(): string {
  return [
    "Translate the canonical validated CellRoleSketch v0.2 below into RecipeV01 syntax. Do not reinterpret spreadsheet semantics.",
    "Return strict JSON only: no prose, Markdown, comments, or alternate envelope.",
    'The root must be {"version":"0.1","sheet":string,"tables":array}. Each table is {"name":string,"values":{"name":string,"cells":selector},"headers":array}. Each header is {"name":string,"direction":"N"|"W"|"NNW"|"WNW","cells":selector}. A selector is exactly {"range":"R1C1:R2C2"} for one contiguous region or {"cells":["R1C1","R3C1"]} for sparse cells.',
    "Translate relationships mechanically: direct-column=N, direct-row=W, cascading-column=NNW, cascading-row=WNW.",
    "Use one recipe table for each sketch Table, its Values for values, and one header for each Dimension. Preserve encounter order. Each sketch Values/Dimension is already validated as either one range or only individual addresses; map that representation directly to the matching selector form.",
    "Do not add, change, or drop any cell address, table, dimension, or relationship. Ignore analysis-only evidence, uncertainty notes, derived selector bounds, and physicalExtent; none is RecipeV01 syntax. Preserve compact ranges as range selectors and sparse anchors as cells selectors. Do not add filters, inferred cells, direction overrides, fill, or options.",
    "The sketch has already passed the blocking-uncertainty and mechanical-collision gates. Never consume provider prose or content outside this canonical root.",
    `Canonical CellRoleSketch (${TRANSLATION_PROMPT_VERSION}):`,
  ].join("\n");
}

export function buildTranslationPrompt(canonicalSketch: string): string {
  return `${buildTranslationPromptPreamble()}\n${canonicalSketch}`;
}
