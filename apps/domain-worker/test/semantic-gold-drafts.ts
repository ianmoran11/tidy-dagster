/* Ported test helper from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import {
  boundingRangeOf,
  formatCell,
  formatRange,
  parseCell,
} from "../src/address.js";
import type {
  LegacyMapping,
  RelationshipKind,
  SemanticGoldDraft,
  SemanticHierarchyLevel,
} from "../src/catalog/semantic-gold-schema.js";

export const SEMANTIC_GOLD_ASSET_IDS = [
  "ABS_PRISONERS_2022_00_02_04",
  "ABS_PRISONERS_2021_00_02_17",
  "ABS_FRAUD_2020-21_00_01_16",
  "ABS_LEGALASSISTANCE_2023-24_00_02_04",
  "AIHW_DRUGTREAT_492",
  "ABS_CORRECTIONS_2021_03_01_01",
  "ABS_CORRECTIONS_2024_09_01_01",
  "ABS_DEFENDANTS_2022-23_00_01_05",
] as const;

export type SemanticGoldAssetId = (typeof SEMANTIC_GOLD_ASSET_IDS)[number];

type RowGroup = { headerRow: number; valueRows: number[] };
type LevelSpec = {
  id: string;
  displayLabel: string;
  coverage?: "required" | "partial";
  kind: RelationshipKind;
  headerColumn?: number;
  headerRow?: number;
  groups?: RowGroup[];
  evidence: string[];
};

type DimensionSpec = {
  id: string;
  displayLabel: string;
  levels: LevelSpec[];
};

type MappingSpec = Omit<
  LegacyMapping,
  | "schemaVersion"
  | "goldSetId"
  | "goldSetVersion"
  | "assetId"
  | "draftSha256"
  | "acceptedRecipe"
  | "independenceNotice"
>;

export type SemanticGoldAssetSpec = {
  assetId: SemanticGoldAssetId;
  workbookPath: string;
  recipePath: string;
  worksheet: string;
  tableLabel: string;
  physicalExtent: string;
  valueRows: number[];
  valueColumns: number[];
  dimensions: DimensionSpec[];
  evidence: string[];
  alternatives: Array<{
    id: string;
    targetIds: string[];
    description: string;
    evidence: string[];
  }>;
  mapping: MappingSpec;
};

const rows = (...values: number[]) => values;
const columns = (start: number, end: number) =>
  Array.from({ length: end - start + 1 }, (_, index) => start + index);

const correctionsRows = rows(
  8,
  9,
  10,
  12,
  13,
  14,
  16,
  17,
  18,
  20,
  21,
  22,
  25,
  26,
  27,
  29,
  30,
  31,
  33,
  34,
  35,
  37,
  38,
  39,
  41,
  42,
  43,
  45,
  46,
  47,
  49,
  50,
  51,
);

const correctionsPopulationGroups: RowGroup[] = [
  { headerRow: 7, valueRows: rows(8, 9, 10) },
  { headerRow: 11, valueRows: rows(12, 13, 14) },
  { headerRow: 15, valueRows: rows(16, 17, 18) },
  { headerRow: 19, valueRows: rows(20, 21, 22) },
  { headerRow: 24, valueRows: rows(25, 26, 27) },
  { headerRow: 28, valueRows: rows(29, 30, 31) },
  { headerRow: 32, valueRows: rows(33, 34, 35) },
  { headerRow: 36, valueRows: rows(37, 38, 39) },
  { headerRow: 40, valueRows: rows(41, 42, 43) },
  { headerRow: 44, valueRows: rows(45, 46, 47) },
  { headerRow: 48, valueRows: rows(49, 50, 51) },
];

const correctionsDimensions: DimensionSpec[] = [
  {
    id: "dimension-jurisdiction",
    displayLabel: "Jurisdiction",
    levels: [
      {
        id: "level-jurisdiction",
        displayLabel: "Jurisdiction",
        kind: "direct-column",
        headerRow: 5,
        evidence: ["Workbook row 5 labels columns B:J by jurisdiction."],
      },
    ],
  },
  {
    id: "dimension-observation-period",
    displayLabel: "Observation period",
    levels: [
      {
        id: "level-measure-basis",
        displayLabel: "Measure basis",
        kind: "cascading-row",
        headerColumn: 1,
        groups: [
          {
            headerRow: 6,
            valueRows: correctionsRows.filter((row) => row <= 22),
          },
          {
            headerRow: 23,
            valueRows: correctionsRows.filter((row) => row >= 25),
          },
        ],
        evidence: [
          "Workbook column A separates average-daily-population and first-day-of-quarter sections.",
        ],
      },
      {
        id: "level-population-category",
        displayLabel: "Population category",
        kind: "cascading-row",
        headerColumn: 1,
        groups: correctionsPopulationGroups,
        evidence: [
          "Workbook column A has population-category anchors followed by three quarter rows.",
        ],
      },
      {
        id: "level-quarter",
        displayLabel: "Quarter",
        kind: "direct-row",
        headerColumn: 1,
        evidence: [
          "Each selected value row has its quarter label in column A.",
        ],
      },
    ],
  },
];

export const SEMANTIC_GOLD_ASSET_SPECS: SemanticGoldAssetSpec[] = [
  {
    assetId: "ABS_PRISONERS_2022_00_02_04",
    workbookPath: "json-examples/ABS_PRISONERS_2022_00_02_04.xlsx",
    recipePath: "json-examples/ABS_PRISONERS_2022_00_02_04.json",
    worksheet: "Sheet 1",
    tableLabel: "Imprisonment rates by jurisdiction",
    physicalExtent: "R4C1:R44C10",
    valueRows: rows(
      8,
      9,
      10,
      13,
      14,
      15,
      18,
      19,
      20,
      23,
      24,
      27,
      28,
      31,
      32,
      35,
      36,
      39,
      40,
      43,
      44,
    ),
    valueColumns: columns(2, 10),
    dimensions: [
      {
        id: "dimension-jurisdiction",
        displayLabel: "Jurisdiction",
        levels: [
          {
            id: "level-jurisdiction",
            displayLabel: "Jurisdiction",
            kind: "direct-column",
            headerRow: 5,
            evidence: ["Workbook row 5 labels columns B:J by jurisdiction."],
          },
        ],
      },
      {
        id: "dimension-rate-characteristic",
        displayLabel: "Rate characteristic",
        levels: [
          {
            id: "level-rate-family",
            displayLabel: "Rate family",
            kind: "cascading-row",
            headerColumn: 1,
            groups: [
              {
                headerRow: 6,
                valueRows: rows(8, 9, 10, 13, 14, 15, 18, 19, 20),
              },
              { headerRow: 21, valueRows: rows(23, 24, 27, 28, 31, 32) },
              { headerRow: 33, valueRows: rows(35, 36, 39, 40, 43, 44) },
            ],
            evidence: [
              "Column A contains three observable rate-family section labels.",
            ],
          },
          {
            id: "level-sex",
            displayLabel: "Sex",
            kind: "cascading-row",
            headerColumn: 1,
            groups: [
              { headerRow: 7, valueRows: rows(8, 9, 10) },
              { headerRow: 12, valueRows: rows(13, 14, 15) },
              { headerRow: 17, valueRows: rows(18, 19, 20) },
              { headerRow: 22, valueRows: rows(23, 24) },
              { headerRow: 26, valueRows: rows(27, 28) },
              { headerRow: 30, valueRows: rows(31, 32) },
              { headerRow: 34, valueRows: rows(35, 36) },
              { headerRow: 38, valueRows: rows(39, 40) },
              { headerRow: 42, valueRows: rows(43, 44) },
            ],
            evidence: ["Sex labels begin each repeated row block in column A."],
          },
          {
            id: "level-characteristic",
            displayLabel: "Indigenous status or ratio basis",
            kind: "direct-row",
            headerColumn: 1,
            evidence: [
              "Each selected value row has its leaf characteristic in column A.",
            ],
          },
        ],
      },
    ],
    evidence: [
      "Workbook cells show three rate families, repeated sex blocks, and exact sparse data rows.",
    ],
    alternatives: [
      {
        id: "alternative-split-ratio-basis",
        targetIds: ["level-characteristic"],
        description:
          "Split Indigenous-status leaves from crude/age-standardised ratio-basis leaves.",
        evidence: [
          "Ratio rows use a different leaf vocabulary from rate rows.",
        ],
      },
    ],
    mapping: {
      coalescedDimensions: [
        {
          recipeTargetName: "indigenous_status",
          semanticTargetIds: ["level-characteristic", "level-rate-family"],
          loss: "The accepted column combines Indigenous status with ratio-basis labels.",
        },
      ],
      renamedConcepts: [
        {
          recipeTargetName: "state",
          semanticTargetId: "level-jurisdiction",
          semanticDisplayLabel: "Jurisdiction",
          note: "The workbook includes states, territories, and Australia.",
        },
      ],
      omittedConcepts: [],
      orderingDifferences: [],
      intentionalBroadSelectors: [
        {
          recipeSelector: "R8C2:R44C10",
          note: "The accepted rectangle spans section and separator rows omitted from the exact value set.",
        },
      ],
    },
  },
  {
    assetId: "ABS_PRISONERS_2021_00_02_17",
    workbookPath: "json-examples/ABS_PRISONERS_2021_00_02_17.xlsx",
    recipePath: "json-examples/ABS_PRISONERS_2021_00_02_17.json",
    worksheet: "Sheet 1",
    tableLabel: "Prisoner counts by jurisdiction",
    physicalExtent: "R4C1:R44C10",
    valueRows: rows(
      8,
      9,
      10,
      12,
      13,
      14,
      16,
      17,
      18,
      21,
      22,
      23,
      25,
      26,
      27,
      29,
      30,
      31,
      34,
      35,
      36,
      38,
      39,
      40,
      42,
      43,
      44,
    ),
    valueColumns: columns(2, 10),
    dimensions: [
      {
        id: "dimension-jurisdiction",
        displayLabel: "Jurisdiction",
        levels: [
          {
            id: "level-jurisdiction",
            displayLabel: "Jurisdiction",
            kind: "direct-column",
            headerRow: 5,
            evidence: ["Workbook row 5 labels columns B:J by jurisdiction."],
          },
        ],
      },
      {
        id: "dimension-prisoner-characteristic",
        displayLabel: "Prisoner characteristic",
        levels: [
          {
            id: "level-indigenous-status",
            displayLabel: "Indigenous status",
            kind: "cascading-row",
            headerColumn: 1,
            groups: [
              {
                headerRow: 6,
                valueRows: rows(8, 9, 10, 12, 13, 14, 16, 17, 18),
              },
              {
                headerRow: 19,
                valueRows: rows(21, 22, 23, 25, 26, 27, 29, 30, 31),
              },
              {
                headerRow: 32,
                valueRows: rows(34, 35, 36, 38, 39, 40, 42, 43, 44),
              },
            ],
            evidence: ["Column A has three Indigenous-status section anchors."],
          },
          {
            id: "level-sex",
            displayLabel: "Sex",
            kind: "cascading-row",
            headerColumn: 1,
            groups: [7, 11, 15, 20, 24, 28, 33, 37, 41].map((headerRow) => ({
              headerRow,
              valueRows: rows(headerRow + 1, headerRow + 2, headerRow + 3),
            })),
            evidence: [
              "Sex labels begin repeated three-row legal-status blocks.",
            ],
          },
          {
            id: "level-legal-status",
            displayLabel: "Legal status",
            kind: "direct-row",
            headerColumn: 1,
            evidence: [
              "Each selected value row is labelled Sentenced, Unsentenced, or Total.",
            ],
          },
        ],
      },
    ],
    evidence: [
      "Workbook cells expose a three-level row hierarchy and sparse value rows.",
    ],
    alternatives: [
      {
        id: "alternative-total-as-aggregate",
        targetIds: ["level-legal-status"],
        description:
          "Represent Total as an aggregate annotation rather than an ordinary member.",
        evidence: ["Each legal-status block ends with a Total row."],
      },
    ],
    mapping: {
      coalescedDimensions: [],
      renamedConcepts: [
        {
          recipeTargetName: "state",
          semanticTargetId: "level-jurisdiction",
          semanticDisplayLabel: "Jurisdiction",
          note: "Jurisdiction is the workbook concept.",
        },
      ],
      omittedConcepts: [
        {
          semanticTargetId: "table-main",
          note: "The accepted summary_label promotes a constant stub caption; the draft keeps it as table evidence.",
        },
      ],
      orderingDifferences: [],
      intentionalBroadSelectors: [
        {
          recipeSelector: "R8C2:R44C10",
          note: "The accepted rectangle includes headers and blank separators.",
        },
      ],
    },
  },
  {
    assetId: "ABS_FRAUD_2020-21_00_01_16",
    workbookPath: "json-examples/ABS_FRAUD_2020-21_00_01_16.xlsx",
    recipePath: "json-examples/ABS_FRAUD_2020-21_00_01_16.json",
    worksheet: "Sheet 1",
    tableLabel: "Relative standard errors for identity-theft characteristics",
    physicalExtent: "R4C1:R21C3",
    valueRows: rows(8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21),
    valueColumns: columns(2, 3),
    dimensions: [
      {
        id: "dimension-measure",
        displayLabel: "Measure",
        levels: [
          {
            id: "level-statistic",
            displayLabel: "Statistic",
            kind: "direct-column",
            headerRow: 5,
            evidence: ["Workbook row 5 names Persons and Proportion columns."],
          },
          {
            id: "level-unit",
            displayLabel: "Unit",
            kind: "direct-column",
            headerRow: 6,
            evidence: [
              "Workbook row 6 supplies the percent unit for both columns.",
            ],
          },
        ],
      },
      {
        id: "dimension-characteristic",
        displayLabel: "Identity-theft characteristic",
        levels: [
          {
            id: "level-characteristic-family",
            displayLabel: "Characteristic family",
            kind: "cascading-row",
            headerColumn: 1,
            groups: [
              { headerRow: 7, valueRows: rows(8, 9, 10, 11, 12) },
              {
                headerRow: 13,
                valueRows: rows(14, 15, 16, 17, 18, 19, 20, 21),
              },
            ],
            evidence: [
              "Column A has distinct information-use and reporting sections.",
            ],
          },
          {
            id: "level-characteristic",
            displayLabel: "Characteristic",
            kind: "direct-row",
            headerColumn: 1,
            evidence: [
              "Each selected row has an observable characteristic label in column A.",
            ],
          },
        ],
      },
    ],
    evidence: [
      "Workbook rows 7 and 13 visibly separate two characteristic domains.",
    ],
    alternatives: [
      {
        id: "alternative-two-subtables",
        targetIds: ["level-characteristic-family"],
        description:
          "Represent the two characteristic families as separate semantic tables.",
        evidence: ["The two blocks use different leaf vocabularies."],
      },
    ],
    mapping: {
      coalescedDimensions: [
        {
          recipeTargetName: "fraud_method",
          semanticTargetIds: [
            "level-characteristic-family",
            "level-characteristic",
          ],
          loss: "Reporting outcomes and authorities are not fraud methods.",
        },
      ],
      renamedConcepts: [
        {
          recipeTargetName: "variables",
          semanticTargetId: "level-characteristic-family",
          semanticDisplayLabel: "Characteristic family",
          note: "The accepted name is generic relative to the workbook sections.",
        },
      ],
      omittedConcepts: [],
      orderingDifferences: [],
      intentionalBroadSelectors: [
        {
          recipeSelector: "R8C2:R21C3",
          note: "The accepted rectangle crosses the row-13 section header.",
        },
      ],
    },
  },
  {
    assetId: "ABS_LEGALASSISTANCE_2023-24_00_02_04",
    workbookPath: "json-examples/ABS_LEGALASSISTANCE_2023-24_00_02_04.xlsx",
    recipePath: "json-examples/ABS_LEGALASSISTANCE_2023-24_00_02_04.json",
    worksheet: "Sheet 1",
    tableLabel:
      "Legal-assistance clients and services by selected characteristics",
    physicalExtent: "R3C1:R44C3",
    valueRows: rows(
      7,
      8,
      9,
      12,
      13,
      16,
      17,
      18,
      19,
      20,
      21,
      22,
      23,
      24,
      27,
      28,
      29,
      30,
      31,
      32,
      34,
      35,
      36,
      37,
      38,
      39,
      40,
      41,
      42,
      43,
      44,
    ),
    valueColumns: columns(2, 3),
    dimensions: [
      {
        id: "dimension-statistic",
        displayLabel: "Statistic",
        levels: [
          {
            id: "level-statistic",
            displayLabel: "Statistic",
            kind: "direct-column",
            headerRow: 5,
            evidence: ["Workbook row 5 names the two statistic columns."],
          },
        ],
      },
      {
        id: "dimension-characteristic",
        displayLabel: "Selected characteristic",
        levels: [
          {
            id: "level-characteristic-domain",
            displayLabel: "Characteristic domain",
            kind: "cascading-row",
            headerColumn: 1,
            groups: [
              { headerRow: 6, valueRows: rows(7, 8, 9) },
              { headerRow: 11, valueRows: rows(12, 13) },
              {
                headerRow: 15,
                valueRows: rows(16, 17, 18, 19, 20, 21, 22, 23, 24),
              },
              { headerRow: 26, valueRows: rows(27, 28, 29, 30, 31, 32) },
              {
                headerRow: 33,
                valueRows: rows(34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44),
              },
            ],
            evidence: [
              "Workbook column A has five section headers: Indigenous status, gender, age, service count, and problem type.",
            ],
          },
          {
            id: "level-characteristic",
            displayLabel: "Characteristic member",
            kind: "direct-row",
            headerColumn: 1,
            evidence: [
              "Every selected row has its own characteristic label in column A.",
            ],
          },
        ],
      },
    ],
    evidence: [
      "Workbook evidence visibly contains five heterogeneous characteristic sections and changes grain from clients to services.",
    ],
    alternatives: [
      {
        id: "alternative-five-subtables",
        targetIds: ["level-characteristic-domain", "level-characteristic"],
        description:
          "Represent the five domains as separate logical subtables sharing statistic columns.",
        evidence: [
          "Section vocabularies and the problem-type observation grain differ.",
        ],
      },
    ],
    mapping: {
      coalescedDimensions: [
        {
          recipeTargetName: "indigenous_status",
          semanticTargetIds: [
            "level-characteristic-domain",
            "level-characteristic",
          ],
          loss: "Gender, age, service-count, problem-type, and Indigenous-status labels are coalesced into one accepted column.",
        },
      ],
      renamedConcepts: [
        {
          recipeTargetName: "variables",
          semanticTargetId: "level-characteristic-domain",
          semanticDisplayLabel: "Characteristic domain",
          note: "The draft identifies the observable domain role explicitly.",
        },
      ],
      omittedConcepts: [
        {
          semanticTargetId: "table-main",
          note: "The accepted shape does not preserve the client-versus-service grain change as a semantic concept.",
        },
      ],
      orderingDifferences: [],
      intentionalBroadSelectors: [
        {
          recipeSelector: "R7C2:R44C3",
          note: "The accepted rectangle crosses blank and section-header rows.",
        },
      ],
    },
  },
  {
    assetId: "AIHW_DRUGTREAT_492",
    workbookPath: "json-examples/AIHW_DRUGTREAT_492.xlsx",
    recipePath: "json-examples/AIHW_DRUGTREAT_492.json",
    worksheet: "Sheet 1",
    tableLabel: "Closed treatment episodes",
    physicalExtent: "R1C1:R30C14",
    valueRows: columns(4, 30),
    valueColumns: columns(5, 14),
    dimensions: [
      {
        id: "dimension-time",
        displayLabel: "Financial year",
        levels: [
          {
            id: "level-financial-year",
            displayLabel: "Financial year",
            kind: "direct-column",
            headerRow: 3,
            evidence: ["Workbook row 3 labels columns E:N by financial year."],
          },
        ],
      },
      {
        id: "dimension-treatment",
        displayLabel: "Treatment episode characteristic",
        levels: [
          {
            id: "level-client-context",
            displayLabel: "Client type / drug-use context",
            kind: "cascading-row",
            headerColumn: 3,
            groups: [
              { headerRow: 4, valueRows: columns(4, 12) },
              { headerRow: 13, valueRows: columns(13, 21) },
              { headerRow: 22, valueRows: columns(22, 30) },
            ],
            evidence: [
              "Workbook column C anchors three repeated treatment blocks.",
            ],
          },
          {
            id: "level-treatment-type",
            displayLabel: "Main treatment type",
            kind: "direct-row",
            headerColumn: 4,
            evidence: [
              "Each selected row has a main-treatment-type label in column D.",
            ],
          },
        ],
      },
    ],
    evidence: [
      "Workbook contains three repeated nine-row blocks over ten financial-year columns.",
    ],
    alternatives: [
      {
        id: "alternative-three-subtables",
        targetIds: ["level-client-context"],
        description:
          "Represent each client-context block as a separate repeated subtable.",
        evidence: ["Rows 4, 13, and 22 start structurally repeated blocks."],
      },
    ],
    mapping: {
      coalescedDimensions: [],
      renamedConcepts: [
        {
          recipeTargetName: "drug_use_context",
          semanticTargetId: "level-client-context",
          semanticDisplayLabel: "Client type / drug-use context",
          note: "The workbook title uses client type while row anchors describe drug-use context.",
        },
      ],
      omittedConcepts: [],
      orderingDifferences: [],
      intentionalBroadSelectors: [],
    },
  },
  {
    assetId: "ABS_CORRECTIONS_2021_03_01_01",
    workbookPath: "json-examples/ABS_CORRECTIONS_2021_03_01_01.xlsx",
    recipePath: "json-examples/ABS_CORRECTIONS_2021_03_01_01.json",
    worksheet: "Sheet 1",
    tableLabel: "Corrective-services summary",
    physicalExtent: "R4C1:R51C10",
    valueRows: correctionsRows,
    valueColumns: columns(2, 10),
    dimensions: correctionsDimensions,
    evidence: [
      "Workbook cells contain two measure-basis sections and repeated three-quarter blocks.",
    ],
    alternatives: [
      {
        id: "alternative-decompose-population",
        targetIds: ["level-population-category"],
        description:
          "Decompose composite population labels into setting, sex, legal status, and Indigenous status where supported.",
        evidence: [
          "Population labels combine several concepts and only selected cross-products occur.",
        ],
      },
    ],
    mapping: {
      coalescedDimensions: [
        {
          recipeTargetName: "corrections_population",
          semanticTargetIds: [
            "level-population-category",
            "level-measure-basis",
          ],
          loss: "Composite labels preserve text but do not expose their component concepts.",
        },
      ],
      renamedConcepts: [
        {
          recipeTargetName: "state",
          semanticTargetId: "level-jurisdiction",
          semanticDisplayLabel: "Jurisdiction",
          note: "Jurisdiction includes territories and Australia.",
        },
      ],
      omittedConcepts: [],
      orderingDifferences: [],
      intentionalBroadSelectors: [
        {
          recipeSelector: "R7C2:R51C10",
          note: "The accepted rectangle includes population anchors and section rows.",
        },
      ],
    },
  },
  {
    assetId: "ABS_CORRECTIONS_2024_09_01_01",
    workbookPath: "json-examples/ABS_CORRECTIONS_2024_09_01_01.xlsx",
    recipePath: "json-examples/ABS_CORRECTIONS_2024_09_01_01.json",
    worksheet: "Sheet 1",
    tableLabel: "Corrective-services summary",
    physicalExtent: "R3C1:R51C10",
    valueRows: correctionsRows,
    valueColumns: columns(2, 10),
    dimensions: correctionsDimensions,
    evidence: [
      "Workbook cells repeat the two-section, three-quarter block structure.",
    ],
    alternatives: [
      {
        id: "alternative-decompose-population",
        targetIds: ["level-population-category"],
        description:
          "Decompose composite population labels into setting, sex, legal status, and Indigenous status where supported.",
        evidence: [
          "Population labels combine several concepts and only selected cross-products occur.",
        ],
      },
    ],
    mapping: {
      coalescedDimensions: [
        {
          recipeTargetName: "corrections_population",
          semanticTargetIds: [
            "level-population-category",
            "level-measure-basis",
          ],
          loss: "Composite labels preserve text but do not expose their component concepts.",
        },
      ],
      renamedConcepts: [
        {
          recipeTargetName: "state",
          semanticTargetId: "level-jurisdiction",
          semanticDisplayLabel: "Jurisdiction",
          note: "Jurisdiction includes territories and Australia.",
        },
      ],
      omittedConcepts: [],
      orderingDifferences: [
        "Accepted recipe header order differs from structural hierarchy order.",
      ],
      intentionalBroadSelectors: [
        {
          recipeSelector: "R7C2:R51C10",
          note: "The accepted rectangle includes population anchors and section rows.",
        },
      ],
    },
  },
  {
    assetId: "ABS_DEFENDANTS_2022-23_00_01_05",
    workbookPath: "json-examples/ABS_DEFENDANTS_2022-23_00_01_05.xlsx",
    recipePath: "json-examples/ABS_DEFENDANTS_2022-23_00_01_05.json",
    worksheet: "Sheet 1",
    tableLabel: "Federal defendants summary characteristics over time",
    physicalExtent: "R4C1:R46C14",
    valueRows: rows(
      7,
      8,
      11,
      12,
      14,
      17,
      18,
      19,
      22,
      23,
      24,
      25,
      26,
      27,
      28,
      29,
      32,
      33,
      34,
      37,
      38,
      39,
      40,
      41,
      42,
      43,
      44,
      45,
      46,
    ),
    valueColumns: columns(2, 14),
    dimensions: [
      {
        id: "dimension-time",
        displayLabel: "Financial year",
        levels: [
          {
            id: "level-financial-year",
            displayLabel: "Financial year",
            kind: "direct-column",
            headerRow: 5,
            evidence: ["Workbook row 5 labels columns B:N by financial year."],
          },
        ],
      },
      {
        id: "dimension-characteristic",
        displayLabel: "Defendant characteristic",
        levels: [
          {
            id: "level-characteristic-domain",
            displayLabel: "Characteristic domain",
            coverage: "partial",
            kind: "cascading-row",
            headerColumn: 1,
            groups: [
              { headerRow: 6, valueRows: rows(7, 8) },
              { headerRow: 10, valueRows: rows(11, 12) },
              { headerRow: 16, valueRows: rows(17, 18, 19) },
              {
                headerRow: 21,
                valueRows: rows(22, 23, 24, 25, 26, 27, 28, 29),
              },
              { headerRow: 31, valueRows: rows(32, 33, 34) },
              {
                headerRow: 36,
                valueRows: rows(37, 38, 39, 40, 41, 42, 43, 44, 45, 46),
              },
            ],
            evidence: [
              "Column A contains six heterogeneous section labels; standalone total row 14 has no section anchor.",
            ],
          },
          {
            id: "level-characteristic",
            displayLabel: "Characteristic member or statistic",
            kind: "direct-row",
            headerColumn: 1,
            evidence: [
              "Every selected value row has its member/statistic label in column A.",
            ],
          },
        ],
      },
    ],
    evidence: [
      "Workbook sections mix sex, age statistics, court level, finalisation, duration, sentence categories, and measurement units.",
    ],
    alternatives: [
      {
        id: "alternative-six-subtables",
        targetIds: ["level-characteristic-domain", "level-characteristic"],
        description:
          "Represent six domains plus the standalone total as separate logical tables.",
        evidence: [
          "Domains have heterogeneous concepts and count/years/weeks units.",
        ],
      },
      {
        id: "alternative-finalisation-hierarchy",
        targetIds: ["level-characteristic"],
        description:
          "Represent finalisation and sentence subtotal labels as reviewed parent-child hierarchies.",
        evidence: [
          "Workbook adjacency suggests subtotal structure but does not uniquely prove parentage.",
        ],
      },
    ],
    mapping: {
      coalescedDimensions: [
        {
          recipeTargetName: "sentence_type",
          semanticTargetIds: [
            "level-characteristic-domain",
            "level-characteristic",
          ],
          loss: "Sex, age statistics, total, court level, finalisation, duration, and sentence categories are coalesced into one accepted column.",
        },
      ],
      renamedConcepts: [
        {
          recipeTargetName: "defendant_dimensions",
          semanticTargetId: "level-characteristic-domain",
          semanticDisplayLabel: "Characteristic domain",
          note: "The draft records the structural role rather than an output-specific name.",
        },
      ],
      omittedConcepts: [
        {
          semanticTargetId: "table-main",
          note: "Accepted output does not explicitly preserve count/years/weeks measure-unit differences.",
        },
      ],
      orderingDifferences: [
        "Accepted output order is compatibility metadata, not semantic identity.",
      ],
      intentionalBroadSelectors: [
        {
          recipeSelector: "R7C2:R46C14",
          note: "The accepted rectangle includes section and separator rows.",
        },
      ],
    },
  },
];

function addressSort(left: string, right: string): number {
  const a = parseCell(left);
  const b = parseCell(right);
  return a.row - b.row || a.col - b.col;
}

export function buildValueAddresses(spec: SemanticGoldAssetSpec): string[] {
  return spec.valueRows
    .flatMap((row) => spec.valueColumns.map((col) => formatCell({ row, col })))
    .sort(addressSort);
}

function buildLevel(
  spec: LevelSpec,
  valueAddresses: string[],
): SemanticHierarchyLevel {
  const values = valueAddresses.map((address) => ({
    address,
    ...parseCell(address),
  }));
  let headerSourceAddresses: string[];
  let associations: Array<{ valueAddress: string; headerAddress: string }>;

  if (spec.kind === "direct-column") {
    if (!spec.headerRow) throw new Error(`MISSING_HEADER_ROW: ${spec.id}`);
    headerSourceAddresses = [
      ...new Set(
        values.map(({ col }) => formatCell({ row: spec.headerRow!, col })),
      ),
    ].sort(addressSort);
    associations = values.map(({ address, col }) => ({
      valueAddress: address,
      headerAddress: formatCell({ row: spec.headerRow!, col }),
    }));
  } else if (spec.kind === "direct-row") {
    if (!spec.headerColumn)
      throw new Error(`MISSING_HEADER_COLUMN: ${spec.id}`);
    headerSourceAddresses = [
      ...new Set(
        values.map(({ row }) => formatCell({ row, col: spec.headerColumn! })),
      ),
    ].sort(addressSort);
    associations = values.map(({ address, row }) => ({
      valueAddress: address,
      headerAddress: formatCell({ row, col: spec.headerColumn! }),
    }));
  } else if (spec.kind === "cascading-row") {
    if (!spec.headerColumn || !spec.groups) {
      throw new Error(`MISSING_CASCADING_ROW_GROUPS: ${spec.id}`);
    }
    headerSourceAddresses = spec.groups
      .map(({ headerRow }) =>
        formatCell({ row: headerRow, col: spec.headerColumn! }),
      )
      .sort(addressSort);
    const rowToHeader = new Map(
      spec.groups.flatMap(({ headerRow, valueRows }) =>
        valueRows.map(
          (row) =>
            [
              row,
              formatCell({ row: headerRow, col: spec.headerColumn! }),
            ] as const,
        ),
      ),
    );
    associations = values
      .filter(({ row }) => rowToHeader.has(row))
      .map(({ address, row }) => ({
        valueAddress: address,
        headerAddress: rowToHeader.get(row)!,
      }));
  } else {
    throw new Error(`UNSUPPORTED_DRAFT_RELATIONSHIP_KIND: ${spec.kind}`);
  }

  return {
    id: spec.id,
    displayLabel: spec.displayLabel,
    coverage: spec.coverage ?? "required",
    headerSourceAddresses,
    relationshipKind: spec.kind,
    associations: associations.sort(
      (left, right) =>
        addressSort(left.valueAddress, right.valueAddress) ||
        addressSort(left.headerAddress, right.headerAddress),
    ),
    evidence: spec.evidence,
  };
}

export function buildSemanticGoldDraft(options: {
  spec: SemanticGoldAssetSpec;
  workbookSha256: string;
  workbookBytes: number;
  worksheetOrdinal: number;
  rowCount: number;
  columnCount: number;
}): SemanticGoldDraft {
  const valueAddresses = buildValueAddresses(options.spec);
  return {
    schemaVersion: "cell-role-semantic-gold-asset-v1",
    goldSetId: "cell-role-smoke-semantic-gold",
    goldSetVersion: "v1",
    assetId: options.spec.assetId,
    workbook: {
      path: options.spec.workbookPath,
      sha256: options.workbookSha256,
      bytes: options.workbookBytes,
    },
    worksheet: {
      name: options.spec.worksheet,
      ordinal: options.worksheetOrdinal,
      rowCount: options.rowCount,
      columnCount: options.columnCount,
    },
    reviewStatus: "pending_human_review",
    reviewerProvenance: [],
    adjudicationProvenance: null,
    preparationProvenance: {
      method: "agent_assisted_workbook_evidence_draft",
      semanticSources: ["workbook_cells"],
      excludedSemanticSources: [
        "generated_v1_output",
        "generated_v2_output",
        "accepted_recipe",
        "historical_expected_csv",
      ],
    },
    tables: [
      {
        id: "table-main",
        displayLabel: options.spec.tableLabel,
        valueAddresses,
        selectorDerivedBounds: formatRange(boundingRangeOf(valueAddresses)),
        physicalExtent: options.spec.physicalExtent,
        dimensions: options.spec.dimensions.map((dimension) => ({
          id: dimension.id,
          displayLabel: dimension.displayLabel,
          levels: dimension.levels.map((level) =>
            buildLevel(level, valueAddresses),
          ),
        })),
        evidence: options.spec.evidence,
      },
    ],
    ambiguities: options.spec.alternatives.map((alternative) => ({
      id: `ambiguity-${alternative.id.replace(/^alternative-/, "")}`,
      targetIds: alternative.targetIds,
      evidence: alternative.evidence,
      candidateAlternativeIds: [alternative.id],
    })),
    alternatives: options.spec.alternatives.map((alternative) => ({
      ...alternative,
      status: "candidate_pending_human_review" as const,
    })),
  };
}

export function buildLegacyMapping(options: {
  spec: SemanticGoldAssetSpec;
  draftSha256: string;
  recipeSha256: string;
  recipeBytes: number;
}): LegacyMapping {
  return {
    schemaVersion: "cell-role-semantic-legacy-map-v1",
    goldSetId: "cell-role-smoke-semantic-gold",
    goldSetVersion: "v1",
    assetId: options.spec.assetId,
    draftSha256: options.draftSha256,
    acceptedRecipe: {
      path: options.spec.recipePath,
      sha256: options.recipeSha256,
      bytes: options.recipeBytes,
    },
    independenceNotice:
      "Compatibility mapping only; excluded from semantic draft and graph identity.",
    ...options.spec.mapping,
  };
}
