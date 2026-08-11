/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import { formatCell, parseRange } from "../address.js";
import type {
  GenerateRecipeRequest,
  PromptBundle,
  PromptExample,
  PromptMessage,
  PromptSectionPlacement,
  PromptSectionSize,
  PromptTextBlock,
  RecipeGenerationProvider,
  TableStructureMode,
} from "./types.js";
import { projectCandidateRangeHints } from "./candidateRangeHints.js";
import {
  examplesForPromptVariant,
  formatPromptExample,
  resolvePromptVariant,
  schemaSkeletonExample,
} from "./promptVariants.js";
import { buildDslRules } from "./ruleTiers.js";
import { buildCompactPrepassPromptSection } from "./ml/promptHints.js";
import {
  buildOntologyPromptPayload,
  PUBLICATION_ONTOLOGY_PROMPT_GUIDANCE,
} from "./ontology/promptHints.js";
import { compressTableMarkdown } from "../summary/compressTableMarkdown.js";
import type { SheetSummary } from "../summary/types.js";

export function buildPromptBundle(
  request: GenerateRecipeRequest,
  examples: PromptExample[] = request.examples ?? [],
): PromptBundle {
  const provider = request.provider ?? "openrouter";
  const model = request.model ?? "deepseek/deepseek-v4-pro";
  const promptVariant = resolvePromptVariant(request.promptVariant);
  const candidateRangeHints = projectCandidateRangeHints(
    request.summaries,
    promptVariant.candidateRangeHints,
    promptVariant.candidateRangeHintMaxCharacters,
  );
  const variantExamples = examplesForPromptVariant(examples, promptVariant);
  const promptSections = buildRecipePromptSections(request, variantExamples);
  const messages = buildPromptMessages({
    provider,
    promptCaching: request.promptCaching,
    sections: promptSections,
  });
  const neuralPrepass = buildCompactPrepassPromptSection(request.neuralPrepass);
  const ontologyPrompt = buildOntologyPromptPayload(
    request.ontologyHints,
    request.publicationOntologyPrompt,
  );
  const ontologyHints = ontologyPrompt.legacySections;
  const publicationOntologyHints = ontologyPrompt.publicationSections;
  const headerLists = Object.fromEntries(
    request.summaries.map((summary) => [
      summary.sheet,
      summary.header_list ?? [],
    ]),
  );
  const tableContextFormat = request.tableContextMode ?? "markdown_compact";
  const tableStructureMode = request.tableStructureMode ?? "auto";
  const promptSummaryContexts = preparePromptSummariesForRequest(request);
  const tableMarkdown = Object.fromEntries(
    promptSummaryContexts.map((summary) => [
      summary.sheet ?? "",
      summary.table_markdown ?? "",
    ]),
  );
  const tableHtmlExpanded = Object.fromEntries(
    promptSummaryContexts
      .filter((summary) => summary.table_html_expanded)
      .map((summary) => [
        summary.sheet ?? "",
        summary.table_html_expanded ?? "",
      ]),
  );
  const tableContexts = Object.fromEntries(
    promptSummaryContexts.map((summary) => {
      const format = summary.table_context_format ?? tableContextFormat;
      const html = summary.table_html_expanded ?? "";
      const markdown = summary.table_markdown ?? "";
      const content = format === "html_expanded" ? html : markdown;

      return [
        summary.sheet ?? "",
        {
          sheet: summary.sheet ?? "",
          format,
          content,
          expanded_available: Boolean(html),
          truncated:
            format === "html_expanded"
              ? Boolean(summary.html_table_truncated)
              : Boolean(summary.table_markdown_truncated),
          estimated_chars: content.length,
        },
      ];
    }),
  );
  const warnings = request.summaries.flatMap((summary) =>
    summary.truncated ||
    summary.table_markdown_truncated ||
    summary.html_table_truncated
      ? [`Prompt context for ${summary.sheet} was truncated.`]
      : [],
  );

  if (request.neuralPromptMode === "compact" && neuralPrepass.length > 0) {
    warnings.push(
      "Neural compact prompt mode omitted full table markdown/HTML from the LLM prompt.",
    );
  }

  return {
    provider,
    model,
    messages,
    examples: variantExamples.map((example) => ({
      filename: example.filename,
      included: true,
    })),
    summaries: request.summaries,
    header_lists: headerLists,
    table_context_format: tableContextFormat,
    table_structure_mode: tableStructureMode,
    table_contexts: tableContexts,
    table_markdown: tableMarkdown,
    table_html_expanded:
      Object.keys(tableHtmlExpanded).length > 0 ? tableHtmlExpanded : undefined,
    neural_prepass: neuralPrepass.length > 0 ? neuralPrepass : undefined,
    ontology_hints: ontologyHints.length > 0 ? ontologyHints : undefined,
    publication_ontology_hints:
      publicationOntologyHints.length > 0
        ? publicationOntologyHints
        : undefined,
    candidate_range_hints:
      candidateRangeHints.hints.length > 0
        ? candidateRangeHints.hints
        : undefined,
    candidate_range_hint_provenance: candidateRangeHints.provenance,
    ontology_prompt_provenance: ontologyPrompt.provenance,
    estimated_chars: promptMessagesEstimatedChars(messages),
    section_sizes: promptSectionSizes(promptSections.sections),
    warnings,
  };
}

export function buildRecipePrompt(
  request: GenerateRecipeRequest,
  examples: PromptExample[] = request.examples ?? [],
): string {
  return joinPromptSections(buildRecipePromptSections(request, examples));
}

export type RecipePromptSection = {
  id: string;
  text: string;
  placement: PromptSectionPlacement;
};

export type RecipePromptSections = {
  staticPrefix: string;
  dynamicSuffix: string;
  sections: RecipePromptSection[];
};

export function buildPromptMessages({
  provider,
  promptCaching,
  sections,
}: {
  provider: RecipeGenerationProvider;
  promptCaching: GenerateRecipeRequest["promptCaching"];
  sections: RecipePromptSections;
}): PromptMessage[] {
  if (provider === "openrouter" && promptCaching === "provider") {
    const content: PromptTextBlock[] = [];

    if (sections.staticPrefix.trim()) {
      content.push({
        type: "text",
        text: sections.staticPrefix,
        cache_control: { type: "ephemeral" },
      });
    }

    if (sections.dynamicSuffix.trim()) {
      content.push({
        type: "text",
        text: sections.dynamicSuffix,
      });
    }

    return [{ role: "user", content }];
  }

  return [{ role: "user", content: joinPromptSections(sections) }];
}

export function promptMessagesEstimatedChars(
  messages: PromptMessage[],
): number {
  return messages.reduce(
    (total, message) =>
      total + promptMessageContentToText(message.content).length,
    0,
  );
}

export function promptMessageContentToText(
  content: PromptMessage["content"],
): string {
  return typeof content === "string"
    ? content
    : content.map((part) => part.text).join("\n\n");
}

export function joinPromptSections(sections: RecipePromptSections): string {
  return [sections.staticPrefix, sections.dynamicSuffix]
    .filter((part) => part.trim())
    .join("\n");
}

export function promptSectionSizes(
  sections: RecipePromptSection[],
): PromptSectionSize[] {
  return sections.map((section) => ({
    id: section.id,
    placement: section.placement,
    chars: section.text.length,
  }));
}

export function assemblePromptSections(
  sections: RecipePromptSection[],
): RecipePromptSections {
  return {
    staticPrefix: sections
      .filter((section) => section.placement === "static")
      .map((section) => section.text)
      .join("\n"),
    dynamicSuffix: sections
      .filter((section) => section.placement === "dynamic")
      .map((section) => section.text)
      .join("\n"),
    sections,
  };
}

function promptSection(
  id: string,
  placement: PromptSectionPlacement,
  text: string | false | undefined,
): RecipePromptSection[] {
  return text === undefined || text === false || text === ""
    ? []
    : [{ id, placement, text }];
}

export function buildRecipePromptSections(
  request: GenerateRecipeRequest,
  examples: PromptExample[] = request.examples ?? [],
): RecipePromptSections {
  const isRepair = request.mode === "repair";
  const isReview = request.mode === "review";
  const promptVariant = resolvePromptVariant(request.promptVariant);
  const isFocusedRepair = isRepair && promptVariant.repairScope === "focused";
  const variantExamples = examplesForPromptVariant(examples, promptVariant);
  const tableStructureMode = request.tableStructureMode ?? "auto";
  const neuralPrepass = buildCompactPrepassPromptSection(request.neuralPrepass);
  const ontologyPrompt = buildOntologyPromptPayload(
    request.ontologyHints,
    request.publicationOntologyPrompt,
  );
  const ontologyHints = ontologyPrompt.legacySections;
  const exampleSection =
    promptVariant.exampleSource === "schema_skeleton"
      ? [
          "Valid example recipes from json-examples/:",
          "Schema skeleton example:",
          schemaSkeletonExample(promptVariant),
        ].join("\n\n")
      : variantExamples.length > 0
        ? [
            "Valid example recipes from json-examples/:",
            ...variantExamples.map((example) =>
              formatPromptExample(example, promptVariant),
            ),
          ].join("\n\n")
        : "Valid example recipes from json-examples/: none available.";
  const promptSummaries = isFocusedRepair
    ? prepareFocusedRepairSummaries(request)
    : preparePromptSummariesForRequest(request);
  const candidateRangeHints = projectCandidateRangeHints(
    request.summaries,
    promptVariant.candidateRangeHints,
    promptVariant.candidateRangeHintMaxCharacters,
  );

  const roleIntro = [
    isRepair
      ? "You are TidyCell's spreadsheet recipe repair planner."
      : isReview
        ? "You are TidyCell's spreadsheet recipe revision planner."
        : "You are TidyCell's spreadsheet structure planner.",
    "Return only strict JSON. Do not output prose, Markdown, comments, or code fences.",
    isRepair
      ? isFocusedRepair
        ? "Your task is to return a corrected full RecipeV01 JSON using only the previous recipe, failure-specific validation errors, deterministic auto-fix records, and the bounded sheet excerpt below."
        : "Your task is to return a corrected full RecipeV01 JSON using the previous recipe, validation errors, user guidance, and checked sheet summaries."
      : isReview
        ? "Your task is to return a corrected full RecipeV01 JSON using the previous recipe, produced CSV output, user guidance, and checked sheet summaries. If the recipe is already correct and the guidance does not require a change, output the previous recipe identically."
        : "Your task is to produce declarative RecipeV01 JSON for each checked sheet summary.",
    "The LLM must identify cell roles only. It must not reshape data directly and must not produce procedural code.",
  ].join("\n");

  const dslRules = buildDslRules({
    tier: promptVariant.ruleTier,
    summaries: request.summaries,
    tableStructureMode,
    conditionalSections: promptVariant.conditionalSections,
  });

  const staticSections: RecipePromptSection[] = [
    ...promptSection("role_intro", "static", roleIntro),
    ...promptSection("dsl_rules", "static", dslRules),
    ...promptSection(
      "neural_hints",
      "static",
      neuralPrepass.length > 0
        ? "- Use neural_prepass hints as high-signal spreadsheet structure predictions. Respect high-confidence value/header ranges unless the sheet context contradicts them, and inspect low-confidence cells carefully."
        : "",
    ),
    ...promptSection(
      "ontology_hints",
      "static",
      ontologyHints.length > 0
        ? [
            "- Use ontology_hints as deterministic JS-derived evidence about reusable dimensions and measures.",
            "- Prefer specific confirmed or edited ontology dimensions (for example year and quarter) over broad overlapping aliases (for example period).",
            "- Keep ontology-indicated mutually-exclusive dimensions separate.",
            "- Avoid assigning the same header cells to both a broad alias and a specific ontology dimension.",
            "- Preserve joinKey ontology dimensions as output header variables when they describe observation values, because they are important for future cross-spreadsheet joins.",
            "- Treat rejected ontology detections as exclusions, not active guidance.",
          ].join("\n")
        : "",
    ),
    ...promptSection(
      "publication_ontology_rules",
      "static",
      ontologyPrompt.publicationActive
        ? PUBLICATION_ONTOLOGY_PROMPT_GUIDANCE.map((line) => `- ${line}`).join(
            "\n",
          )
        : "",
    ),
    ...promptSection(
      "output_schema_rules",
      "static",
      [
        "- Do not copy helper fields that are not part of the RecipeV01 schema.",
        ...(promptVariant.rangeGuidance
          ? [
              '- Use each sheet summary\'s data_range_corners as concise bounding evidence. Prefer one {"range":"start:end"} selector for each contiguous value or header span instead of enumerating every cell address.',
            ]
          : []),
        "- Mental Check: Imagine removing the values column from your extracted tidy table. If there would be any duplicate rows (i.e., identical combinations of all header variables), it means you are missing a dimension (like Year or Category) and need to define an additional header.",
      ].join("\n"),
    ),
    ...promptSection(
      "examples",
      "static",
      isFocusedRepair ? "" : exampleSection,
    ),
    ...promptSection(
      "user_guidance",
      "static",
      request.promptAppend
        ? `Additional user-provided guidance (apply on top of the rules above; use this to head off known issues):\n${request.promptAppend}`
        : "",
    ),
    ...promptSection(
      "output_shape",
      "static",
      [
        "Output shape:",
        request.summaries.length === 1
          ? "Return one RecipeV01 object."
          : 'Return an object with a "recipes" array containing one RecipeV01 per checked sheet.',
      ].join("\n"),
    ),
    ...promptSection(
      "intent",
      "static",
      request.intent
        ? `User intent: ${request.intent}`
        : "User intent: not provided.",
    ),
  ];

  const dynamicSections: RecipePromptSection[] = [
    ...promptSection(
      "previous_recipe",
      "dynamic",
      isRepair || isReview
        ? `Previous recipe:\n${JSON.stringify(request.previousRecipe)}`
        : "",
    ),
    ...promptSection(
      "validation_errors",
      "dynamic",
      isRepair || (isReview && request.validationErrors?.length)
        ? `Validation errors:\n${JSON.stringify(request.validationErrors ?? [])}`
        : "",
    ),
    ...promptSection(
      "auto_fix_records",
      "dynamic",
      isRepair && request.autoFixRecords?.length
        ? `Deterministic auto-fix records already attempted:\n${JSON.stringify(request.autoFixRecords)}`
        : "",
    ),
    ...promptSection(
      "produced_csv_sample",
      "dynamic",
      isReview && request.producedCsvSample
        ? `Produced CSV output from previous recipe:\n${request.producedCsvSample}\n\nReview this CSV output by comparing it against the original spreadsheet representation in the checked sheet prompt context. If the structure or extracted values are incorrect, adjust the previous recipe and output a corrected RecipeV01.`
        : "",
    ),
    ...promptSection(
      "produced_csv_diagnostics",
      "dynamic",
      isReview && request.producedCsvColumnSummary?.length
        ? `Produced CSV column diagnostics:\n${JSON.stringify(request.producedCsvColumnSummary)}\n\nUse these diagnostics to detect whether unrelated header dimensions have been collapsed into one output column, or whether values that belong together have been split across columns. Pay special attention to duplicate_header_key_share, unique_row_key_count versus row_count, low numeric_parse_share on .value, high_missing_share columns, and column_pair_overlap entries.`
        : "",
    ),
    ...promptSection(
      "produced_csv_suspicious_rows",
      "dynamic",
      isReview && request.producedCsvSuspiciousRows
        ? `Suspicious produced CSV rows:\n${JSON.stringify(request.producedCsvSuspiciousRows)}\n\nUse these rows as targeted evidence for the diagnostics above. They are excerpts only; do not assume omitted rows are error-free.`
        : "",
    ),
    ...promptSection(
      "produced_csv_duplicates",
      "dynamic",
      isReview && request.producedCsvDuplicates
        ? `Duplicate extracted rows warning:\n${request.producedCsvDuplicates}`
        : "",
    ),
    ...promptSection(
      "user_guidance",
      "dynamic",
      request.userGuidance
        ? `User guidance for this revision:\n${request.userGuidance}`
        : "",
    ),
    ...promptSection(
      "neural_hints",
      "dynamic",
      neuralPrepass.length > 0
        ? `Neural prepass hints:\n${JSON.stringify(neuralPrepass)}`
        : "",
    ),
    ...promptSection(
      "ontology_hints",
      "dynamic",
      ontologyHints.length > 0
        ? `Ontology hints (deterministic JS prepass):\n${JSON.stringify(ontologyHints)}`
        : "",
    ),
    ...promptSection(
      "publication_ontology_hints",
      "dynamic",
      ontologyPrompt.publicationActive
        ? `Approved publication ontology hints (reviewed, pinned, structural evidence only):\n${JSON.stringify(ontologyPrompt.publicationSections)}`
        : "",
    ),
    ...promptSection(
      "candidate_range_hints",
      "dynamic",
      candidateRangeHints.section,
    ),
    ...promptSection(
      "sheet_context",
      "dynamic",
      `Checked sheet prompt context:\n${JSON.stringify(promptSummaries)}`,
    ),
  ];

  return assemblePromptSections([...staticSections, ...dynamicSections]);
}

export function buildTableStructurePromptSection(
  tableStructureMode: TableStructureMode,
): string[] {
  if (tableStructureMode === "single_table") {
    return [
      "Table structure mode: SINGLE TABLE PER SHEET.",
      "- For each returned RecipeV01, tables[] must contain exactly one table object.",
      "- The single table must capture all tabular data observations in that sheet. Do not split a sheet into separate tables because of spacing, repeated headers, stacked blocks, merged labels, category bands, or section labels.",
      '- Encode apparent sections as header variables using "N", "W", "NNW", or "WNW" directions, so output rows remain uniquely identified without creating extra tables.',
      "- If the sheet appears to contain multiple regions, reconcile all regions that belong to the sheet data into the one table. Leave only titles, notes, footers, source citations, and truly explanatory cells as non-table cells.",
      "- Name the single table after the sheet or primary dataset, and add every required dimension as a header rather than starting a second table.",
    ];
  }

  return [
    "- Use one tables[] declaration per unrelated table on the same sheet.",
    '- If a sheet contains multiple sections with identical column structures (e.g., stacked data blocks for males, females, persons), unify them into a SINGLE table. Do NOT create separate tables. Use a "WNW" or "NNW" header to extract the block labels (e.g., the gender) and apply it to all rows in the respective blocks.',
  ];
}

export const COMPACT_SUMMARY_DROPPED_FIELDS = [
  "sizeChars",
  "styleFingerprints",
  "table_markdown_truncated when false",
  "html_table_truncated when false",
  "truncated when false",
] as const;

export function preparePromptSummariesForRequest(
  request: GenerateRecipeRequest,
): Array<
  Partial<SheetSummary> & {
    neural_context_note?: string;
    table_html_expanded?: string;
    compact_summary_note?: string;
    data_range_corners?: DataRangeCornerHint[];
    contextCells_omitted_count?: number;
    header_list_omitted_count?: number;
  }
> {
  return promptSummariesForRequest(request).map((summary) =>
    preparePromptSummary(summary, request),
  );
}

export function prepareFocusedRepairSummaries(
  request: GenerateRecipeRequest,
): Array<
  Partial<SheetSummary> & {
    focused_repair_note: string;
    contextCells_omitted_count?: number;
    header_list_omitted_count?: number;
  }
> {
  const previous = request.previousRecipe as
    | { sheet?: string; tables?: unknown[] }
    | undefined;
  const failingSheet =
    typeof previous?.sheet === "string" ? previous.sheet : undefined;
  const summaries = failingSheet
    ? request.summaries.filter((summary) => summary.sheet === failingSheet)
    : request.summaries.slice(0, 1);
  const selected =
    summaries.length > 0 ? summaries : request.summaries.slice(0, 1);

  return selected.map((summary) => {
    const contextCells = Array.isArray(summary.contextCells)
      ? summary.contextCells.slice(0, 24)
      : [];
    const headerList = Array.isArray(summary.header_list)
      ? summary.header_list.slice(0, 24)
      : [];
    const markdownLines = (summary.table_markdown ?? "").split("\n");
    const excerpt = markdownLines.slice(0, 18).join("\n");
    return {
      sheet: summary.sheet,
      checked: summary.checked,
      usedRange: summary.usedRange,
      rowCount: summary.rowCount,
      columnCount: summary.columnCount,
      nonEmptyCellCount: summary.nonEmptyCellCount,
      dataTypes: summary.dataTypes,
      merges: summary.merges,
      candidateRegions: summary.candidateRegions?.slice(0, 8) ?? [],
      contextCells,
      header_list: headerList,
      table_context_format: summary.table_context_format,
      table_markdown: excerpt,
      table_markdown_truncated: markdownLines.length > 18,
      html_table: "",
      html_table_truncated: false,
      truncated: true,
      sizeChars: excerpt.length,
      focused_repair_note:
        "Focused repair scope: full static examples and full sheet context are intentionally omitted; use only this bounded excerpt plus previous_recipe, validation_errors, and auto_fix_records.",
      contextCells_omitted_count: Math.max(
        0,
        (summary.contextCells?.length ?? 0) - contextCells.length,
      ),
      header_list_omitted_count: Math.max(
        0,
        (summary.header_list?.length ?? 0) - headerList.length,
      ),
    };
  });
}

function promptSummariesForRequest(
  request: GenerateRecipeRequest,
): Array<Partial<SheetSummary> & { neural_context_note?: string }> {
  const neuralPrepass = buildCompactPrepassPromptSection(request.neuralPrepass);

  if (request.neuralPromptMode !== "compact" || neuralPrepass.length === 0) {
    return request.summaries;
  }

  return request.summaries.map((summary) => ({
    sheet: summary.sheet,
    checked: summary.checked,
    usedRange: summary.usedRange,
    rowCount: summary.rowCount,
    columnCount: summary.columnCount,
    nonEmptyCellCount: summary.nonEmptyCellCount,
    dataTypes: summary.dataTypes,
    merges: summary.merges,
    blankRows: summary.blankRows,
    blankColumns: summary.blankColumns,
    candidateRegions: summary.candidateRegions,
    contextCells: summary.contextCells.slice(0, 8),
    header_list: summary.header_list.slice(0, 40),
    table_context_format: summary.table_context_format,
    table_markdown: "<!-- omitted in neural compact prompt mode -->",
    table_markdown_truncated: true,
    html_table: "",
    html_table_truncated: false,
    intent: summary.intent,
    truncated: true,
    sizeChars: 0,
    neural_context_note:
      "Full table markdown/HTML omitted because neural prepass hints were supplied in compact mode.",
  }));
}

function preparePromptSummary(
  summary: Partial<SheetSummary> & { neural_context_note?: string },
  request: GenerateRecipeRequest,
): Partial<SheetSummary> & {
  neural_context_note?: string;
  table_html_expanded?: string;
  compact_summary_note?: string;
  data_range_corners?: DataRangeCornerHint[];
  contextCells_omitted_count?: number;
  header_list_omitted_count?: number;
} {
  const variant = resolvePromptVariant(request.promptVariant);
  const compression = variant.tableCompression;
  const noHtml = compression?.noHtml === true;
  const compact = variant.summaryFields === "compact";
  const tableMarkdown = compression
    ? compressTableMarkdown(summary.table_markdown ?? "", {
        collapseBlankRows: compression.collapseBlankRows,
        collapseBlankColumns: compression.collapseBlankColumns,
        collapseRepeatedRows: compression.collapseRepeatedRows,
        cellCharCap: compression.cellCharCap,
        rowSampling: compression.rowSampling,
        candidateRegions: summary.candidateRegions,
      })
    : (summary.table_markdown ?? "");

  const { html_table, dataRangeHintRegions, ...rest } = summary;
  const prepared: Record<string, unknown> = {
    ...rest,
    table_markdown: tableMarkdown,
  };
  delete prepared.candidateBlocks;
  delete prepared.candidateBlockEvidence;

  if (variant.rangeGuidance) {
    prepared.data_range_corners = buildDataRangeCornerHints({
      ...summary,
      dataRangeHintRegions,
    });
  }

  if (compact) {
    prepared.compact_summary_note = `Compact summary omitted: ${COMPACT_SUMMARY_DROPPED_FIELDS.join(", ")}; contextCells/header_list may be capped with omitted counts.`;
    delete prepared.sizeChars;
    delete prepared.styleFingerprints;
    if (prepared.table_markdown_truncated === false)
      delete prepared.table_markdown_truncated;
    if (prepared.html_table_truncated === false)
      delete prepared.html_table_truncated;
    if (prepared.truncated === false) delete prepared.truncated;

    const contextCells = Array.isArray(summary.contextCells)
      ? summary.contextCells
      : [];
    if (contextCells.length > 12) {
      prepared.contextCells = contextCells.slice(0, 12);
      prepared.contextCells_omitted_count = contextCells.length - 12;
    }

    const headerList = Array.isArray(summary.header_list)
      ? summary.header_list
      : [];
    if (headerList.length > 40) {
      prepared.header_list = headerList.slice(0, 40);
      prepared.header_list_omitted_count = headerList.length - 40;
    }
  }

  if (!noHtml && html_table) {
    prepared.table_html_expanded = html_table;
  }

  if (noHtml) {
    delete prepared.html_table_truncated;
  }

  delete prepared.html_table;
  return prepared;
}

type DataRangeCornerHint = {
  range: string;
  top_left: string;
  top_right: string;
  bottom_left: string;
  bottom_right: string;
};

function buildDataRangeCornerHints(
  summary: Partial<SheetSummary>,
): DataRangeCornerHint[] {
  const candidateRanges = (summary.candidateRegions ?? []).map(
    (region) => region.range,
  );
  const hintRanges = (summary.dataRangeHintRegions ?? []).map(
    (region) => region.range,
  );
  const explicitRanges = [...new Set([...candidateRanges, ...hintRanges])];
  const ranges =
    explicitRanges.length > 0
      ? explicitRanges
      : numericDataRangesFromMarkdown(summary.table_markdown ?? "");

  return ranges.flatMap((range) => {
    try {
      const { start, end } = parseRange(range);
      return [
        {
          range,
          top_left: formatCell(start),
          top_right: formatCell({ row: start.row, col: end.col }),
          bottom_left: formatCell({ row: end.row, col: start.col }),
          bottom_right: formatCell(end),
        },
      ];
    } catch {
      return [];
    }
  });
}

function numericDataRangesFromMarkdown(markdown: string): string[] {
  const numericCells = new Map<string, { row: number; col: number }>();

  for (const line of markdown.split("\n")) {
    const cells = line.matchAll(
      /\[R(\d+)C(\d+)(?:\|[^\]]+)?\]\s*(.*?)(?=\s+\|\s*(?:\[R|$))/g,
    );
    for (const match of cells) {
      if (!isNumericLikeMarkdownValue(match[3])) continue;
      const cell = { row: Number(match[1]), col: Number(match[2]) };
      numericCells.set(`${cell.row}:${cell.col}`, cell);
    }
  }

  const remaining = new Set(numericCells.keys());
  const components: Array<Array<{ row: number; col: number }>> = [];

  while (remaining.size > 0) {
    const first = remaining.values().next().value as string;
    const queue = [first];
    const component: Array<{ row: number; col: number }> = [];
    remaining.delete(first);

    while (queue.length > 0) {
      const key = queue.shift();
      if (!key) continue;
      const cell = numericCells.get(key);
      if (!cell) continue;
      component.push(cell);

      for (const neighbor of [
        `${cell.row - 1}:${cell.col}`,
        `${cell.row + 1}:${cell.col}`,
        `${cell.row}:${cell.col - 1}`,
        `${cell.row}:${cell.col + 1}`,
      ]) {
        if (!remaining.delete(neighbor)) continue;
        queue.push(neighbor);
      }
    }

    components.push(component);
  }

  return components
    .map((component) => {
      const rows = component.map((cell) => cell.row);
      const cols = component.map((cell) => cell.col);
      return {
        component,
        start: { row: Math.min(...rows), col: Math.min(...cols) },
        end: { row: Math.max(...rows), col: Math.max(...cols) },
      };
    })
    .filter(
      ({ component, start, end }) =>
        component.length >= 2 && end.row > start.row,
    )
    .sort((left, right) => right.component.length - left.component.length)
    .slice(0, 8)
    .map(({ start, end }) => `${formatCell(start)}:${formatCell(end)}`);
}

function isNumericLikeMarkdownValue(value: string): boolean {
  const normalized = value
    .replace(/^\*\*|\*\*$/g, "")
    .replace(/\s+/g, "")
    .trim();

  return /^\(?[-+]?(?:[$£€])?(?:\d{1,3}(?:,\d{3})+|\d+|\d*\.\d+)%?\)?$/.test(
    normalized,
  );
}
