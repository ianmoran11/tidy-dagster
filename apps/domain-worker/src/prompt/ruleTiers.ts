/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import type { TableStructureMode } from "./types.js";
import type { SheetSummary } from "../summary/types.js";

export type PromptRuleTier = "full" | "core" | "minimal";
export type PromptRuleFeature =
  | "merged_cells"
  | "time_series"
  | "hierarchical_headers"
  | "metadata_sheet"
  | "multi_table";

export type PromptRule = {
  id: string;
  tiers: PromptRuleTier[];
  text: string | ((context: PromptRuleContext) => string | string[]);
  feature?: PromptRuleFeature;
};

export type PromptRuleContext = {
  summaries: SheetSummary[];
  tableStructureMode: TableStructureMode;
  conditionalSections: boolean;
};

export type PromptRuleFeatures = Record<PromptRuleFeature, boolean>;

export function detectPromptRuleFeatures(
  summaries: SheetSummary[],
  tableStructureMode: TableStructureMode,
): PromptRuleFeatures {
  return {
    merged_cells: hasMergedCells(summaries),
    time_series: hasTemporalFirstColumn(summaries),
    hierarchical_headers: hasHierarchicalHeaderSignals(summaries),
    metadata_sheet: hasMetadataSheetSignals(summaries),
    multi_table:
      tableStructureMode !== "single_table" &&
      (summaries.length > 1 ||
        summaries.some(
          (summary) => (summary.candidateRegions ?? []).length > 1,
        )),
  };
}

export function hasMergedCells(summaries: SheetSummary[]): boolean {
  return summaries.some((summary) => (summary.merges ?? []).length > 0);
}

export function hasTemporalFirstColumn(summaries: SheetSummary[]): boolean {
  return summaries.some((summary) => {
    const firstColumnValues = [
      ...(summary.cells ?? []),
      ...(summary.contextCells ?? []),
    ]
      .filter((cell) => cell.col === 1)
      .map((cell) =>
        String(cell.formatted ?? cell.value ?? "")
          .trim()
          .toLowerCase(),
      )
      .filter(Boolean);

    return firstColumnValues.some(isTemporalText);
  });
}

export function hasHierarchicalHeaderSignals(
  summaries: SheetSummary[],
): boolean {
  return summaries.some(
    (summary) =>
      (summary.merges ?? []).length > 0 ||
      (summary.blankRows ?? []).length > 0 ||
      (summary.blankColumns ?? []).length > 0 ||
      (summary.header_list ?? []).some((header) =>
        Array.isArray(header.addresses),
      ),
  );
}

export function hasMetadataSheetSignals(summaries: SheetSummary[]): boolean {
  return summaries.some((summary) => {
    const hasSmallRegion = (summary.candidateRegions ?? []).some(
      (region) => region.columnCount <= 2 && region.rowCount >= 2,
    );
    const dataTypes = summary.dataTypes as Partial<Record<string, number>>;
    const mostlyText = (dataTypes.string ?? 0) >= (dataTypes.number ?? 0);
    const sparse =
      summary.rowCount * summary.columnCount > 0 &&
      summary.nonEmptyCellCount / (summary.rowCount * summary.columnCount) <
        0.35;
    const metadataLabels = [
      ...(summary.cells ?? []),
      ...(summary.contextCells ?? []),
    ].some((cell) =>
      /^(series|source|unit|frequency|collection|table|contents|notes?)\b/i.test(
        String(cell.value ?? ""),
      ),
    );

    return metadataLabels || (hasSmallRegion && mostlyText && sparse);
  });
}

function isTemporalText(value: string): boolean {
  return (
    /\b(19|20)\d{2}\b/.test(value) ||
    /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b/.test(
      value,
    ) ||
    /\b(q[1-4]|quarter|month|date|year)\b/.test(value)
  );
}

export function buildDslRules({
  tier,
  summaries,
  tableStructureMode,
  conditionalSections,
}: PromptRuleContext & { tier: PromptRuleTier }): string {
  const context = { summaries, tableStructureMode, conditionalSections };
  const features = detectPromptRuleFeatures(summaries, tableStructureMode);
  const lines = ["DSL rules:"];

  for (const rule of PROMPT_RULES) {
    if (!rule.tiers.includes(tier)) continue;
    if (conditionalSections && rule.feature && !features[rule.feature])
      continue;

    const text =
      typeof rule.text === "function" ? rule.text(context) : rule.text;
    lines.push(...(Array.isArray(text) ? text : [text]));
  }

  return lines.join("\n");
}

function tableStructureRules(tableStructureMode: TableStructureMode): string[] {
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

export const PROMPT_RULES: PromptRule[] = [
  {
    id: "full-version",
    tiers: ["full"],
    text: '- version must be exactly "0.1".',
  },
  {
    id: "full-sheet-level",
    tiers: ["full"],
    text: "- Each recipe is sheet-level and has exactly one sheet name.",
  },
  {
    id: "full-tables",
    tiers: ["full"],
    text: "- Use canonical tables[]; never use a single-table shorthand.",
  },
  {
    id: "full-table-fields",
    tiers: ["full"],
    text: "- Each table must have a unique name, values, and headers.",
  },
  { id: "full-values", tiers: ["full"], text: "- Use values, not value." },
  {
    id: "full-values-name",
    tiers: ["full"],
    text: "- values.name is the output value column name.",
  },
  {
    id: "full-r1c1",
    tiers: ["full"],
    text: "- Cell addresses and ranges must be canonical R1C1, such as R3C4 and R3C4:R8C7.",
  },
  {
    id: "full-cells",
    tiers: ["full"],
    text: '- A cells array may contain only single addresses like "R3C4"; never put a range string inside a cells array.',
  },
  {
    id: "full-discrete",
    tiers: ["full"],
    text: '- NEVER use a discrete array of cell strings (e.g., ["R7C2", "R267C2"]) to represent a contiguous block. For contiguous cells spanning multiple rows or columns, ALWAYS use the object selector {"range": "R7C2:R267C2"}.',
  },
  {
    id: "full-range",
    tiers: ["full"],
    text: '- For contiguous ranges, use a clean object selector such as {"range":"R3C4:R8C7"} or {"range":"R3C4:R8C7","where":{"non_blank":true}}.',
  },
  {
    id: "full-single-cell-range",
    tiers: ["full"],
    text: '- In object selectors for ranges, if selecting a single cell, you MUST format it as a range, e.g. {"range": "R29C1:R29C1"}, never {"range": "R29C1"}.',
  },
  {
    id: "full-data-type",
    tiers: ["full"],
    text: '- Do NOT use strict "data_type": ["numeric"] filters unless you are absolutely certain that cells are exclusively stored as native Excel numbers. In many sheets, numbers are parsed as "string" types; using a numeric-only filter will exclude them and result in an empty (0-row) extraction failure. It is safer to omit data_type or use {"non_blank":true}.',
  },
  {
    id: "full-directions",
    tiers: ["full"],
    text: '- Supported directions are "N", "W", "NNW", and "WNW" only.',
  },
  {
    id: "full-bad-directions",
    tiers: ["full"],
    text: '- Never use "S", "E", "NE", "NW", "SE", "SW", "left", "right", "up", or "down" as header directions.',
  },
  {
    id: "full-above-left",
    tiers: ["full"],
    text: '- Headers located ABOVE the data must use "N", "NNW", or "WNW". "W" is strictly for headers located to the LEFT of the data.',
  },
  {
    id: "full-fill-values",
    tiers: ["full"],
    text: '- Supported fill values are "right" and "down" only.',
  },
  {
    id: "full-fill-merged",
    tiers: ["full"],
    feature: "merged_cells",
    text: '- ALWAYS use the "fill" property ("right" or "down") for header variables corresponding to merged header cells or empty cells that should inherit their value from a preceding label (e.g. for merged category spans).',
  },
  {
    id: "full-span",
    tiers: ["full"],
    text: '- Ensure that row/column header ranges cover the exact same span as the value cells they describe (e.g. if the value range is R12C8:R173C8 spanning rows 12 to 173, then the west header range must cover rows 12 to 173, such as {"range":"R12C5:R173C5"} instead of a truncated range). Header ranges MUST exactly cover the ENTIRE span of the data values they describe. For example, if data values span columns 2 to 130, a North header must span columns 2 to 130 (e.g., {"range": "R1C2:R1C130"}). Do not truncate header ranges.',
  },
  {
    id: "full-time",
    tiers: ["full"],
    feature: "time_series",
    text: '- Time-series sheets always require the primary temporal indexing dimension (typically dates or months in the first column, Column A/1) to be declared as a West ("W") header.',
  },
  {
    id: "full-hierarchy",
    tiers: ["full"],
    feature: "hierarchical_headers",
    text: '- For hierarchical temporal headers (e.g., Years above Quarters), ensure the parent header (e.g., Year) is explicitly extracted. Use "WNW" (West-North-West) or "NNW" (North-North-West) for hierarchical super-headers that span multiple sub-headers. WNW and NNW are geometric and cascade across their respective bounds automatically, so they do NOT require the "fill" property.',
  },
  {
    id: "full-header-map",
    tiers: ["full"],
    text: '- "N" and "W" map exactly the 1D span of their range directly to the values. If they span merged cells, they need "fill": "right" (for N) or "fill": "down" (for W). "NNW" and "WNW" are cumulative/cascading: they assign the closest preceding header value to all subsequent columns or rows, making them ideal for hierarchical super-headers (like Years above Quarters) without needing explicit fill properties.',
  },
  {
    id: "full-bound",
    tiers: ["full"],
    text: '- To prevent over-extraction of empty spacer rows, sub-headers, or totals embedded within data blocks, strictly bound the value range and use {"non_blank":true}.',
  },
  {
    id: "full-logical-hierarchies",
    tiers: ["full"],
    text: ({ tableStructureMode }) =>
      tableStructureMode === "single_table"
        ? "- When row headers contain logical hierarchies represented by indentation, or when a column mixes completely different semantic concepts (e.g. Sex vs Age vs Offence), define separate header variables rather than creating another table or collapsing them into a generic column."
        : "- When row headers contain logical hierarchies represented by indentation, or when a column mixes completely different semantic concepts (e.g. Sex vs Age vs Offence), define separate header variables or tables rather than collapsing them into a generic column.",
  },
  {
    id: "full-metadata",
    tiers: ["full"],
    feature: "metadata_sheet",
    text: '- For metadata, index, or contents sheets containing non-tabular key-value pairs, do NOT force them into a multi-dimensional table schema. Map them cleanly using West ("W") directions targeting exactly the cells containing the keys.',
  },
  {
    id: "full-table-structure",
    tiers: ["full"],
    feature: "multi_table",
    text: ({ tableStructureMode }) => tableStructureRules(tableStructureMode),
  },
  {
    id: "full-at-least-one",
    tiers: ["full"],
    text: "- A recipe must ALWAYS contain at least one table. If a sheet is explanatory, contains enquiries, or is a contents-only sheet, you MUST still declare at least one table to extract the text, metadata, or table of contents as string/value observations. NEVER return an empty tables[] array.",
  },
  {
    id: "full-exclude-metadata",
    tiers: ["full"],
    feature: "metadata_sheet",
    text: "- Strictly exclude metadata rows (e.g., Series Start, Series End, Collection Month) situated above data blocks from the `values` range. Only include actual data observations.",
  },
  {
    id: "full-notes",
    tiers: ["full"],
    text: "- Leave titles, notes, footers, source citations, and explanatory cells as non-table cells.",
  },
  {
    id: "full-optimize",
    tiers: ["full"],
    text: "- Optimize for benchmark-verifiable structure: exact value cells, correct source addresses, precise header assignments, and explicit exclusion of titles, notes, footers, and source citations from tables.",
  },
  {
    id: "full-final-check",
    tiers: ["full"],
    text: ({ tableStructureMode }) =>
      tableStructureMode === "single_table"
        ? "- Before finalizing the single table, check whether its value range captures all intended data observations while still excluding titles, notes, footers, source citations, and explanatory cells."
        : "- Before finalizing each table, check whether a smaller table region would preserve all intended values while improving value-address F1 and non-table-cell precision.",
  },
  {
    id: "full-header-list",
    tiers: ["full"],
    text: "- Use each sheet's header_list as candidate headers with exact R1C1 locations.",
  },
  {
    id: "full-markdown",
    tiers: ["full"],
    text: "- Use each sheet's table_markdown to reason about layout and formatting.",
  },
  {
    id: "full-html",
    tiers: ["full"],
    text: "- If table_html_expanded is present, use it only as additional formatting detail.",
  },

  {
    id: "core-schema",
    tiers: ["core", "minimal"],
    text: '- Return strict RecipeV01 JSON: version "0.1", one sheet name, canonical tables[] only, and at least one table with unique name, values, and headers. Use values.name for the output value column.',
  },
  {
    id: "core-selectors",
    tiers: ["core", "minimal"],
    text: '- Select cells with canonical R1C1 addresses/ranges. cells[] contains single addresses only. Contiguous data must use {"range":"RrCc:RrCc"}; add where:{"non_blank":true} when bounding sparse value ranges. Avoid numeric-only data_type filters unless the sheet proves numbers are native.',
  },
  {
    id: "core-directions",
    tiers: ["core", "minimal"],
    text: '- Header directions are only "N", "W", "NNW", and "WNW". Use N for headers above values and W for headers left of values; NNW/WNW are cascading super-header directions. Fill is only "right" or "down".',
  },
  {
    id: "core-spans",
    tiers: ["core"],
    text: "- Header ranges must cover exactly the same row/column span as the value cells they describe; do not truncate rows or columns. Bound value ranges tightly so spacer rows, sub-headers, totals, titles, notes, footers, and source citations stay out of tables.",
  },
  {
    id: "core-merged",
    tiers: ["core"],
    feature: "merged_cells",
    text: '- For merged header cells or blank cells inheriting a preceding label, add fill:"right" for N headers or fill:"down" for W headers.',
  },
  {
    id: "core-time",
    tiers: ["core"],
    feature: "time_series",
    text: "- If column 1 contains dates, months, quarters, or years, include it as the primary temporal W header.",
  },
  {
    id: "core-hierarchy",
    tiers: ["core"],
    feature: "hierarchical_headers",
    text: "- For hierarchical headers such as years above quarters or block labels above/left of rows, include the parent with NNW or WNW so duplicate child labels remain distinguishable.",
  },
  {
    id: "core-metadata",
    tiers: ["core"],
    feature: "metadata_sheet",
    text: "- Metadata/index/contents sheets may be key-value text observations. Do not force them into a fake numeric table; map keys with W headers and exclude metadata rows from ordinary data blocks.",
  },
  {
    id: "core-table-structure",
    tiers: ["core"],
    feature: "multi_table",
    text: ({ tableStructureMode }) =>
      tableStructureMode === "single_table"
        ? "- Single-table mode: return exactly one table per sheet and encode sections as header variables instead of separate tables."
        : "- Use separate tables only for unrelated regions. Merge stacked blocks with identical columns into one table using WNW/NNW block labels.",
  },
  {
    id: "core-mental-check",
    tiers: ["core"],
    text: "- Mental check: after removing the values column, header columns must uniquely identify each observation. Duplicate rows mean a missing dimension such as year, category, sex, age, or block label.",
  },
  {
    id: "core-evidence",
    tiers: ["core"],
    text: "- Use header_list R1C1 candidates and table_markdown layout evidence; table_html_expanded is formatting detail only.",
  },
];
