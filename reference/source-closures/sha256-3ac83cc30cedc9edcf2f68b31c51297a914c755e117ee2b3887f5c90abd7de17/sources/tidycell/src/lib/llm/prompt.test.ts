import { describe, expect, it } from "vitest";
import {
  buildPromptBundle,
  buildRecipePrompt,
  buildRecipePromptSections,
  joinPromptSections,
} from "./prompt";
import { loadPromptExamples } from "@/lib/llm/examples";
import { schemaSkeletonExample } from "@/lib/llm/promptVariants";
import { resolveSheetOntology } from "@/lib/ontology/overrides";
import type { OntologyDetection, SheetOntology } from "@/lib/ontology/types";
import { validateRecipe } from "@/lib/recipe/schema";
import type { GenerateRecipeRequest } from "./types";
import type { SheetSummary } from "@/lib/summary/types";

const yearDetection: OntologyDetection = {
  id: "det_year",
  name: "year",
  kind: "time.year",
  sheet: "Sheet1",
  range: "R1C2:R1C5",
  addresses: ["R1C2", "R1C3", "R1C4", "R1C5"],
  orientation: "row",
  confidence: 0.97,
  evidence: "matched year header values",
  joinKey: true,
  sampleValues: ["2020", "2021"],
  source: "deterministic",
};

const quarterDetection: OntologyDetection = {
  id: "det_quarter",
  name: "quarter",
  kind: "time.quarter",
  sheet: "Sheet1",
  range: "R2C2:R2C5",
  addresses: ["R2C2", "R2C3", "R2C4", "R2C5"],
  orientation: "row",
  confidence: 0.93,
  evidence: "matched quarter header values",
  joinKey: true,
  sampleValues: ["Q1", "Q2"],
  source: "deterministic",
};

describe("ontology prompt construction", () => {
  it("serializes resolved edited ontology and broad-alias guidance", () => {
    const ontology = ontologyFixture();
    const resolved = resolveSheetOntology(ontology, {
      detections: [{ detectionId: "det_year", canonicalName: "fiscal_year" }],
    });

    const bundle = buildPromptBundle({
      ...requestFixture(),
      ontologyHints: [resolved],
    });
    const hint = bundle.ontology_hints?.[0] as {
      deterministicRawDetections: Array<{ name: string; source: string }>;
      activeDetections: Array<{
        name: string;
        source: string;
        confirmed: boolean;
        joinKey: boolean;
      }>;
      avoidBroadAliases: Array<{ broadName: string; prefer: string[] }>;
      joinCandidates: Array<{ name: string }>;
    };

    expect(hint.deterministicRawDetections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ name: "year", source: "detected" }),
      ]),
    );
    expect(hint.activeDetections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: "fiscal_year",
          source: "user_override",
          confirmed: true,
          joinKey: true,
        }),
        expect.objectContaining({ name: "quarter", source: "detected" }),
      ]),
    );
    expect(hint.avoidBroadAliases).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          broadName: "period",
          prefer: expect.arrayContaining(["fiscal_year", "quarter"]),
        }),
      ]),
    );
    expect(hint.joinCandidates).toEqual(
      expect.arrayContaining([expect.objectContaining({ name: "fiscal_year" })]),
    );

    const prompt = buildRecipePrompt({
      ...requestFixture(),
      ontologyHints: [resolved],
    });
    expect(prompt).toContain("Ontology hints (deterministic JS prepass)");
    expect(prompt).toContain("Prefer specific confirmed or edited ontology dimensions");
    expect(prompt).toContain("Avoid assigning the same header cells");
    expect(prompt).toContain("period");
    expect(prompt).toContain("fiscal_year");

    const previewText = bundle.messages[0]?.content;
    expect(typeof previewText === "string" ? previewText : "").toContain(
      "fiscal_year",
    );
    expect(typeof previewText === "string" ? previewText : "").toContain(
      "period",
    );
  });

  it("lists rejected detections as exclusions instead of active guidance", () => {
    const resolved = resolveSheetOntology(ontologyFixture(), {
      detections: [{ detectionId: "det_quarter", rejected: true }],
    });

    const bundle = buildPromptBundle({
      ...requestFixture(),
      ontologyHints: [resolved],
    });
    const hint = bundle.ontology_hints?.[0] as {
      activeDetections: Array<{ id: string; name: string }>;
      rejectedDetections: Array<{ id: string; name: string; status: string }>;
    };

    expect(hint.activeDetections).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ id: "det_quarter" })]),
    );
    expect(hint.rejectedDetections).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "det_quarter",
          name: "quarter",
          status: "rejected_excluded",
        }),
      ]),
    );
  });

  it("leaves prompt behavior unchanged when ontology is absent", () => {
    const bundle = buildPromptBundle(requestFixture());
    const prompt = buildRecipePrompt(requestFixture());

    expect(bundle.ontology_hints).toBeUndefined();
    expect(prompt).not.toContain("Ontology hints (deterministic JS prepass)");
    expect(prompt).not.toContain("Use ontology_hints as deterministic JS-derived evidence");
  });
});

describe("prompt variants", () => {
  const exampleRecipe = {
    version: "0.1" as const,
    sheet: "Sheet1",
    tables: [
      {
        name: "observations",
        values: { name: "value", selector: { range: "R3C2:R4C5" } },
        headers: [],
      },
    ],
  };
  const examples = [
    { filename: "a.json", recipe: exampleRecipe },
    { filename: "b.json", recipe: exampleRecipe },
    { filename: "c.json", recipe: exampleRecipe },
  ];

  it("keeps an explicit baseline variant byte-identical to the default", () => {
    const request = { ...requestFixture(), examples };

    expect(
      joinPromptSections(buildRecipePromptSections(request, examples)),
    ).toBe(
      joinPromptSections(
        buildRecipePromptSections(
          { ...request, promptVariant: { name: "baseline" } },
          examples,
        ),
      ),
    );
  });

  it("applies example knobs only to the examples section", () => {
    const baseline = buildRecipePromptSections(
      { ...requestFixture(), examples },
      examples,
    );
    const minified = buildRecipePromptSections(
      { ...requestFixture(), promptVariant: { exampleFormat: "minified" } },
      examples,
    );
    const twoExamples = buildRecipePromptSections(
      { ...requestFixture(), promptVariant: { exampleCount: 2 } },
      examples,
    );
    const noExamples = buildRecipePromptSections(
      { ...requestFixture(), promptVariant: { exampleCount: 0 } },
      examples,
    );

    const withoutExamples = (sections: ReturnType<typeof buildRecipePromptSections>) =>
      sections.sections.filter((section) => section.id !== "examples");

    expect(withoutExamples(minified)).toEqual(withoutExamples(baseline));
    expect(withoutExamples(twoExamples)).toEqual(withoutExamples(baseline));
    expect(withoutExamples(noExamples)).toEqual(withoutExamples(baseline));
    expect(sectionText(minified, "examples")).not.toContain("\n  ");
    expect(sectionText(twoExamples, "examples")).toContain("a.json");
    expect(sectionText(twoExamples, "examples")).toContain("b.json");
    expect(sectionText(twoExamples, "examples")).not.toContain("c.json");
    expect(sectionText(noExamples, "examples")).toBe(
      "Valid example recipes from json-examples/: none available.",
    );
  });

  it("adds four-corner range hints and range-form examples only when enabled", () => {
    const rangeExample = {
      filename: "sales.json",
      recipe: {
        version: "0.1" as const,
        sheet: "Sheet1",
        tables: [
          {
            name: "product_sales",
            values: {
              name: "sales",
              cells: { range: "R11C3:R12C4" },
            },
            headers: [
              {
                name: "month",
                direction: "N" as const,
                cells: ["R10C3", "R10C4"],
              },
              {
                name: "sparse_period",
                direction: "NNW" as const,
                cells: ["R9C3", "R9C5"],
              },
            ],
          },
        ],
      },
    };
    const summary = {
      ...summaryFixture(),
      candidateRegions: [
        {
          range: "R11C3:R12C4",
          rowCount: 2,
          columnCount: 2,
          numericCellCount: 4,
        },
      ],
    };
    const baseline = buildRecipePromptSections(
      { ...requestFixture(), summaries: [summary], examples: [rangeExample] },
      [rangeExample],
    );
    const treatment = buildRecipePromptSections(
      {
        ...requestFixture(),
        summaries: [summary],
        examples: [rangeExample],
        promptVariant: { rangeGuidance: true },
      },
      [rangeExample],
    );

    expect(sectionText(baseline, "output_schema_rules")).not.toContain(
      "data_range_corners",
    );
    expect(sectionText(baseline, "sheet_context")).not.toContain(
      "data_range_corners",
    );
    expect(sectionText(treatment, "output_schema_rules")).toContain(
      "instead of enumerating every cell address",
    );
    expect(sectionText(treatment, "sheet_context")).toContain(
      '"top_left":"R11C3"',
    );
    expect(sectionText(treatment, "sheet_context")).toContain(
      '"top_right":"R11C4"',
    );
    expect(sectionText(treatment, "sheet_context")).toContain(
      '"bottom_left":"R12C3"',
    );
    expect(sectionText(treatment, "sheet_context")).toContain(
      '"bottom_right":"R12C4"',
    );
    expect(sectionText(treatment, "examples")).toContain(
      '"range": "R10C3:R10C4"',
    );
    expect(sectionText(treatment, "examples")).toContain(
      '"cells": [\n            "R9C3",\n            "R9C5"',
    );

    const hiddenHintSummary = {
      ...summaryFixture(),
      candidateRegions: [
        {
          range: "R3C5:R3C5",
          rowCount: 1,
          columnCount: 1,
          numericCellCount: 1,
        },
      ],
      dataRangeHintRegions: [
        {
          range: "R8C2:R9C3",
          rowCount: 2,
          columnCount: 2,
          numericCellCount: 4,
        },
      ],
    };
    const hiddenHintBaseline = buildRecipePromptSections({
      ...requestFixture(),
      summaries: [hiddenHintSummary],
    });
    const hiddenHintTreatment = buildRecipePromptSections({
      ...requestFixture(),
      summaries: [hiddenHintSummary],
      promptVariant: { rangeGuidance: true },
    });
    const baselineSummaryContext = JSON.parse(
      sectionText(hiddenHintBaseline, "sheet_context").split("\n")[1],
    );
    const treatmentSummaryContext = JSON.parse(
      sectionText(hiddenHintTreatment, "sheet_context").split("\n")[1],
    );
    const corners = treatmentSummaryContext[0].data_range_corners;
    delete treatmentSummaryContext[0].data_range_corners;

    expect(corners).toEqual([
      {
        range: "R3C5:R3C5",
        top_left: "R3C5",
        top_right: "R3C5",
        bottom_left: "R3C5",
        bottom_right: "R3C5",
      },
      {
        range: "R8C2:R9C3",
        top_left: "R8C2",
        top_right: "R8C3",
        bottom_left: "R9C2",
        bottom_right: "R9C3",
      },
    ]);
    expect(treatmentSummaryContext).toEqual(baselineSummaryContext);
    expect(sectionText(hiddenHintTreatment, "sheet_context")).not.toContain(
      "dataRangeHintRegions",
    );

    const markdownFallback = buildRecipePromptSections({
      ...requestFixture(),
      summaries: [
        {
          ...summaryFixture(),
          candidateRegions: [],
          table_markdown: [
            "| [R1C1|s:title] Dataset | [R1C2] 2 | [R1C3] 3 |",
            "|---|---|---|",
            "| [R7C1] category | [R7C2] Value A | [R7C3] Value B |",
            "| [R8C1] Alpha | [R8C2|s:number] 10 | [R8C3] 20 |",
            "| [R9C1] Beta | [R9C2] 30 | [R9C3] 40 |",
          ].join("\n"),
        },
      ],
      promptVariant: { rangeGuidance: true },
    });
    const fallbackContext = sectionText(markdownFallback, "sheet_context");

    expect(fallbackContext).toContain('"range":"R8C2:R9C3"');
    expect(fallbackContext).toContain('"top_left":"R8C2"');
    expect(fallbackContext).not.toContain('"range":"R1C2:R1C3"');
  });

  it("keeps output shape specific to single vs multi sheet requests", () => {
    const single = buildRecipePromptSections({
      ...requestFixture(),
      promptVariant: { ruleTier: "core", conditionalSections: true },
    });
    const multi = buildRecipePromptSections({
      ...requestFixture(),
      summaries: [summaryFixture(), { ...summaryFixture(), sheet: "Sheet2" }],
      promptVariant: { ruleTier: "core", conditionalSections: true },
    });

    expect(sectionText(single, "output_shape")).toContain("Return one RecipeV01 object.");
    expect(sectionText(single, "output_shape")).not.toContain('"recipes" array');
    expect(sectionText(multi, "output_shape")).toContain('"recipes" array');
  });

  it("applies rule tiers and schema skeleton examples behind variant knobs", () => {
    const core = buildRecipePromptSections({
      ...requestFixture(),
      promptVariant: { ruleTier: "core" },
    });
    const minimal = buildRecipePromptSections({
      ...requestFixture(),
      promptVariant: { ruleTier: "minimal" },
    });
    const skeleton = buildRecipePromptSections({
      ...requestFixture(),
      promptVariant: { ruleTier: "core", exampleSource: "schema_skeleton" },
    });

    expect(sectionText(core, "dsl_rules").length).toBeLessThanOrEqual(3200);
    expect(sectionText(minimal, "dsl_rules").length).toBeLessThanOrEqual(1800);
    expect(sectionText(skeleton, "examples")).toContain("Schema skeleton example");
    expect(sectionText(skeleton, "examples")).toContain('"direction": "WNW"');
  });

  it("applies table context compression and compact summaries only behind variant knobs", () => {
    const summary = {
      ...summaryFixture(),
      sizeChars: 1234,
      styleFingerprints: { bold: { count: 3 } },
      contextCells: Array.from({ length: 14 }, (_, index) => ({
        address: `R${index + 1}C1`,
        row: index + 1,
        col: 1,
        value: `context ${index}`,
        data_type: "string" as const,
        has_formula: false,
        has_comment: false,
      })),
      header_list: Array.from({ length: 42 }, (_, index) => ({
        value: `header ${index}`,
        addresses: `R${index + 1}C1`,
      })),
      table_markdown: [
        "| [R1C1] label | [R1C2] value |",
        "| [R2C1] | [R2C2] |",
        "| [R3C1] | [R3C2] |",
        "| [R4C1] | [R4C2] |",
        "| [R5C1] done | [R5C2] 1 |",
      ].join("\n"),
      html_table: "<table><tr><td>expanded</td></tr></table>",
    };
    const baseline = buildRecipePromptSections({
      ...requestFixture(),
      summaries: [summary],
    });
    const compressed = buildRecipePromptSections({
      ...requestFixture(),
      summaries: [summary],
      promptVariant: {
        summaryFields: "compact",
        tableCompression: { collapseBlankRows: true, noHtml: true },
      },
    });

    expect(sectionText(baseline, "sheet_context")).toContain("sizeChars");
    expect(sectionText(baseline, "sheet_context")).toContain("table_html_expanded");
    expect(sectionText(compressed, "sheet_context")).toContain("rows 2–4 blank");
    expect(sectionText(compressed, "sheet_context")).toContain("compact_summary_note");
    expect(sectionText(compressed, "sheet_context")).toContain("contextCells_omitted_count");
    expect(sectionText(compressed, "sheet_context")).toContain("header_list_omitted_count");
    expect(sectionText(compressed, "sheet_context")).not.toContain('"sizeChars"');
    expect(sectionText(compressed, "sheet_context")).not.toContain("table_html_expanded");
  });

  it("keeps the schema skeleton example valid RecipeV01 JSON", () => {
    const parsed = JSON.parse(
      schemaSkeletonExample({
        exampleSource: "schema_skeleton",
        exampleFormat: "minified",
      }),
    );

    expect(validateRecipe(parsed).success).toBe(true);
  });
});

function sectionText(
  sections: ReturnType<typeof buildRecipePromptSections>,
  id: string,
): string {
  return sections.sections.find((section) => section.id === id)?.text ?? "";
}

const DEFAULT_STATIC_PREFIX_CHAR_BUDGET = 10158;
const EXPECTED_DEFAULT_PROMPT_SECTION_IDS = [
  "role_intro",
  "dsl_rules",
  "output_schema_rules",
  "examples",
  "output_shape",
  "intent",
  "sheet_context",
];

function assertPromptBudgetGuard(
  bundle: ReturnType<typeof buildPromptBundle>,
  budget: number = DEFAULT_STATIC_PREFIX_CHAR_BUDGET,
): void {
  const staticChars = bundle.section_sizes
    .filter((section) => section.placement === "static")
    .reduce((total, section) => total + section.chars, 0);

  expect(bundle.section_sizes.map((section) => section.id)).toEqual(
    EXPECTED_DEFAULT_PROMPT_SECTION_IDS,
  );
  expect(staticChars).toBeLessThanOrEqual(budget);
}

describe("prompt section instrumentation", () => {
  it("locks representative joined prompt text snapshots", () => {
    const previousRecipe = {
      version: "0.1",
      sheet: "Sheet1",
      tables: [
        {
          name: "observations",
          values: { name: "value", selector: { range: "R3C2:R4C5" } },
          headers: [],
        },
      ],
    };

    expect(
      joinPromptSections(
        buildRecipePromptSections(
          {
            ...requestFixture(),
            examples: [
              {
                filename: "example.json",
                recipe: previousRecipe,
              },
            ],
          },
          [{ filename: "example.json", recipe: previousRecipe }],
        ),
      ),
    ).toMatchSnapshot("generate mode with examples");

    expect(
      joinPromptSections(
        buildRecipePromptSections({
          ...requestFixture(),
          mode: "review",
          previousRecipe,
          producedCsvSample: "year,quarter,value\n2020,Q1,10\n",
          producedCsvColumnSummary: [
            {
              table: "observations",
              row_count: 1,
              unique_row_key_count: 1,
              duplicate_header_key_count: 0,
              duplicate_header_row_count: 0,
              duplicate_header_key_share: 0,
              columns: [],
              column_pair_overlap: [],
            },
          ],
        }),
      ),
    ).toMatchSnapshot("review mode with produced CSV payloads");

    expect(
      joinPromptSections(
        buildRecipePromptSections({
          ...requestFixture(),
          mode: "repair",
          previousRecipe,
          validationErrors: [
            {
              path: "tables.0.values.selector",
              code: "invalid_range",
              message: "Invalid range",
            },
          ],
        }),
      ),
    ).toMatchSnapshot("repair mode with validation errors");
  });

  it("guards the default static prefix budget and section ids", () => {
    const examples = loadPromptExamples();
    const bundle = buildPromptBundle({
      provider: "openrouter",
      model: "test-model",
      summaries: [summaryFixture()],
      examples,
    });
    const staticChars = bundle.section_sizes
      .filter((section) => section.placement === "static")
      .reduce((total, section) => total + section.chars, 0);

    assertPromptBudgetGuard(bundle);
    expect(staticChars).toBe(9234);
    expect(DEFAULT_STATIC_PREFIX_CHAR_BUDGET).toBe(Math.ceil(staticChars * 1.1));
  });

  it("demonstrates the prompt budget guard fails when the prefix is inflated", () => {
    const bundle = buildPromptBundle(requestFixture());
    const staticChars = bundle.section_sizes
      .filter((section) => section.placement === "static")
      .reduce((total, section) => total + section.chars, 0);

    expect(() => assertPromptBudgetGuard(bundle, staticChars - 1)).toThrow();
  });

  it("reports section ids and accounts for cached prompt separators", () => {
    const bundle = buildPromptBundle({
      ...requestFixture(),
      provider: "openrouter",
      promptCaching: "provider",
    });
    const staticSections = bundle.section_sizes.filter(
      (section) => section.placement === "static",
    );
    const dynamicSections = bundle.section_sizes.filter(
      (section) => section.placement === "dynamic",
    );
    const sectionChars = bundle.section_sizes.reduce(
      (total, section) => total + section.chars,
      0,
    );
    const staticJoinChars = Math.max(0, staticSections.length - 1);
    const dynamicJoinChars = Math.max(0, dynamicSections.length - 1);
    const cachedBlockJoinChars = staticSections.length > 0 && dynamicSections.length > 0 ? 2 : 0;

    expect(bundle.section_sizes.map((section) => section.id)).toEqual(
      EXPECTED_DEFAULT_PROMPT_SECTION_IDS,
    );
    expect(
      sectionChars + staticJoinChars + dynamicJoinChars + cachedBlockJoinChars,
    ).toBe(bundle.estimated_chars);
  });
});

function ontologyFixture(): SheetOntology {
  return {
    version: "0.1",
    sheet: "Sheet1",
    detections: [yearDetection, quarterDetection],
    avoidBroadAliases: [
      {
        broadName: "period",
        prefer: ["quarter", "year"],
        ranges: ["R1C2:R1C5", "R2C2:R2C5"],
        reason:
          "Deterministic ontology prepass found separate specific temporal dimensions; avoid assigning these cells to an overlapping broad period header.",
      },
    ],
    joinCandidates: [
      {
        kind: "time.year",
        name: "year",
        sheet: "Sheet1",
        range: "R1C2:R1C5",
        confidence: 0.97,
      },
    ],
    promptHints: [
      "Prefer year + quarter over broad 'period'; keep these header variables mutually exclusive.",
    ],
  };
}

function requestFixture(): GenerateRecipeRequest {
  return {
    provider: "openrouter",
    model: "test-model",
    summaries: [summaryFixture()],
    intent: "Extract the table.",
  };
}

function summaryFixture(): SheetSummary {
  return {
    sheet: "Sheet1",
    checked: true,
    usedRange: "R1C1:R4C5",
    rowCount: 4,
    columnCount: 5,
    nonEmptyCellCount: 12,
    cells: [],
    dataTypes: {},
    merges: [],
    styleFingerprints: {},
    blankRows: [],
    blankColumns: [],
    candidateRegions: [],
    contextCells: [],
    header_list: [
      { value: "year", addresses: "R1C2:R1C5" },
      { value: "quarter", addresses: "R2C2:R2C5" },
    ],
    table_context_format: "markdown_compact",
    table_markdown: "| year | 2020 | 2021 |\n| quarter | Q1 | Q2 |",
    table_markdown_truncated: false,
    html_table: "",
    html_table_truncated: false,
    truncated: false,
    sizeChars: 42,
  };
}
