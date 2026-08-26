// @vitest-environment node
import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  compileFederalDefendantsGroupedRecipeV1,
  digestFederalDefendantsBytes,
  digestFederalDefendantsCanonical,
  executeFederalDefendantsGroupedRecipeV1,
  FEDERAL_DEFENDANTS_GROUPED_EXECUTION_V1,
  FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1,
  FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1,
  FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1,
  FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1,
  MAX_FEDERAL_GROUPED_JSON_BYTES,
  MAX_FEDERAL_GROUPED_JSON_DEPTH,
  MAX_FEDERAL_GROUPED_JSON_NODES,
  assertFederalGroupedJsonBudget,
  decodeFederalPanelKeySourceValue,
  encodeFederalPanelKeySourceValue,
  parseFederalDefendantsGroupedSemanticMapV1,
  type FederalDefendantsGeometryAuthorityV1,
  type FederalDefendantsGroupedSemanticMapV1,
  type FederalTargetProvenance,
} from "../src/catalog/federal-defendants-grouped-recipe-v1.js";
import { parseSemanticTableMapJson } from "../src/catalog/semantic-map-v1.js";
import { parseSemanticTableMapV2Json } from "../src/catalog/semantic-map-v2.js";
import { parseTargetScopedSemanticMapV1 } from "../src/catalog/target-scoped-recipe-v02.js";
import { rowsToCsv } from "../src/export/formatters.js";
import type { PrototypeWorkerRequest } from "../src/protocol/prototype.js";
import { runPrototypeAwareWorker } from "../src/protocol/prototypeSchema.js";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";
import type { ParsedSheet, TidyCell } from "../src/workbook/types.js";

const roots: string[] = [];
afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) => rm(root, { recursive: true, force: true })),
  );
});

const fakeDigest = (digit: string) => `sha256:${digit.repeat(64)}`;

function cell(
  address: string,
  value: TidyCell["value"],
  extra: Partial<TidyCell> = {},
): TidyCell {
  const match = /^R(\d+)C(\d+)$/.exec(address)!;
  return {
    sheet: "Table 7",
    address,
    row: Number(match[1]),
    col: Number(match[2]),
    value,
    data_type:
      value === null
        ? "blank"
        : typeof value === "number"
          ? "numeric"
          : typeof value === "boolean"
            ? "boolean"
            : "string",
    ...extra,
  };
}

function syntheticSheet(): ParsedSheet {
  const cells = [
    cell("R1C1", null),
    cell("R1C2", "Males"),
    cell("R1C3", null),
    cell("R1C4", "Total"),
    cell("R2C1", null),
    cell("R2C2", "No. of defendants"),
    cell("R2C3", "Mean age (years)"),
    cell("R2C4", "Median age (years)"),
    cell("R3C1", null),
    cell("R3C2", "2024-25", { formula: '="2024-25"', formatted: "2024-25" }),
    cell("R3C3", null),
    cell("R3C4", null),
    cell("R4C1", "Aviation"),
    cell("R4C2", 0),
    cell("R4C3", 39.3),
    cell("R4C4", "np"),
    cell("R5C1", null),
    cell("R5C2", null),
    cell("R5C3", null),
    cell("R5C4", null),
    cell("R6C1", null),
    cell("R6C2", "2023-24"),
    cell("R6C3", null),
    cell("R6C4", null),
    cell("R7C1", "Aviation"),
    cell("R7C2", 1),
    cell("R7C3", null),
    cell("R7C4", 38),
    cell("R99C99", "out-of-range stale accessibility text"),
  ];
  return {
    name: "Table 7",
    usedRange: "R1C1:R99C99",
    rowCount: 99,
    columnCount: 99,
    nonEmptyCellCount: cells.filter((entry) => entry.value !== null).length,
    cells,
    merges: [],
  };
}

const provenanceDimensions = [
  ["population-basis", "population basis", "populationBasis"],
  ["transfer-policy", "transfer policy", "transferPolicy"],
  ["entity-type", "entity type", "entityType"],
  ["denominator", "denominator", "denominator"],
  ["row-classification", "row classification", "rowClassification"],
  [
    "principal-classification",
    "principal offence classification",
    "principalOffenceClassification",
  ],
  [
    "classification-treatment",
    "classification treatment",
    "classificationTreatment",
  ],
  [
    "principal-selection",
    "principal selection version",
    "principalSelectionVersion",
  ],
  [
    "sentence-treatment",
    "sentence classification treatment",
    "sentenceClassificationTreatment",
  ],
  ["revision-treatment", "revision treatment", "revisionTreatment"],
  ["measure-id", "measure id", "measure"],
  ["statistic-code", "statistic code", "statistic"],
  ["unit-id", "unit id", "unit"],
  ["hierarchy", "hierarchy", "hierarchy"],
  ["total-status", "total status", "totalStatus"],
  ["footnote-references", "footnote references", "footnoteReferences"],
  ["perturbation", "perturbation", "perturbation"],
] as const;

function profile(
  measure: string,
  statistic: string,
  unit: string,
  entityType = "persons-only",
  footnoteRefs: string[] = [],
  hierarchy = "leaf",
  totalStatus = "not-total",
): FederalTargetProvenance {
  return {
    populationBasis: "finalised-excluding-transfers",
    transferPolicy: "transfers-excluded",
    entityType,
    denominator: "published-finalised-defendants",
    rowClassification: "abs-federal-offence-group",
    principalOffenceClassification: "anzsoc-2023",
    classificationTreatment: "native-federal-offence-group",
    principalSelectionVersion:
      "2018-19-plus-method-finalisation-sentence-then-noi",
    sentenceClassificationTreatment: "not-applicable-no-sentence-dimension",
    revisionTreatment: "as-published-no-member-specific-revision-rule",
    measure,
    statistic,
    unit,
    hierarchy,
    totalStatus,
    footnoteRefs,
    perturbation: true,
  };
}

type Builder = {
  geometryBands: FederalDefendantsGeometryAuthorityV1["bands"];
  sourceUniverses: FederalDefendantsGroupedSemanticMapV1["sourceUniverses"];
  bindings: FederalDefendantsGroupedSemanticMapV1["bindings"];
  vectors: FederalDefendantsGroupedSemanticMapV1["vectors"];
  targets: FederalDefendantsGroupedSemanticMapV1["targets"];
};

function rc(address: string): { row: number; col: number } {
  const match = /^R(\d+)C(\d+)$/.exec(address)!;
  return { row: Number(match[1]), col: Number(match[2]) };
}

function extendBand(
  existing: string | undefined,
  direction: "N" | "NNW" | "W" | "WNW",
  sourceAddress: string,
  targetAddress: string,
): string {
  const source = rc(sourceAddress);
  const target = rc(targetAddress);
  const endpoints = existing
    ? /^R(\d+)C(\d+):R(\d+)C(\d+)$/.exec(existing)!.slice(1).map(Number)
    : [source.row, source.col, source.row, source.col];
  let [startRow, startCol, endRow, endCol] = endpoints;
  if (direction === "N" || direction === "NNW") {
    startRow = Math.min(startRow, source.row);
    endRow = Math.max(endRow, source.row);
    startCol = Math.min(startCol, target.col);
    endCol = Math.max(endCol, target.col);
  } else {
    startRow = Math.min(startRow, target.row);
    endRow = Math.max(endRow, target.row);
    startCol = Math.min(startCol, source.col);
    endCol = Math.max(endCol, source.col);
  }
  return `R${startRow}C${startCol}:R${endRow}C${endCol}`;
}

function addTarget(
  builder: Builder,
  input: {
    address: string;
    panelId: string;
    profileId: string;
    row: string;
    sex: string;
    statistic: string;
    period: string;
  },
): void {
  const suffix = input.address.toLowerCase();
  const sources = [
    ["offence-group", input.row, "W"],
    ["sex", input.sex, "NNW"],
    ["statistic", input.statistic, "N"],
    ["observation-period", input.period, "NNW"],
  ] as const;
  const bindingIds: string[] = [];
  for (const [dimensionId, sourceAddress, direction] of sources) {
    const short = dimensionId
      .replace("observation-period", "period")
      .replace("offence-group", "offence");
    const universeId = `u-${input.panelId}-${short}`;
    const bindingId = `b-${short}-${suffix}`;
    const authorityBandId = `a-${input.panelId}-${short}`;
    const existingUniverse = builder.sourceUniverses.find(
      (entry) => entry.id === universeId,
    );
    const existingBand = builder.geometryBands.find(
      (entry) => entry.id === authorityBandId,
    );
    if (existingUniverse && existingBand) {
      if (
        !existingUniverse.selectors.some(
          (selector) =>
            "address" in selector && selector.address === sourceAddress,
        )
      )
        existingUniverse.selectors.push({ address: sourceAddress });
      existingBand.range = extendBand(
        existingBand.range,
        direction,
        sourceAddress,
        input.address,
      );
    } else {
      builder.geometryBands.push({
        id: authorityBandId,
        panelId: input.panelId,
        dimensionId,
        direction,
        range: extendBand(undefined, direction, sourceAddress, input.address),
      });
      builder.sourceUniverses.push({
        id: universeId,
        panelId: input.panelId,
        dimensionId,
        direction,
        authorityBandId,
        selectors: [{ address: sourceAddress }],
      });
    }
    builder.bindings.push({
      id: bindingId,
      dimensionId,
      direction,
      selectedAddress: sourceAddress,
      universeId,
    });
    bindingIds.push(bindingId);
  }
  const vectorId = `v-${suffix}`;
  builder.vectors.push({ id: vectorId, bindingIds });
  builder.targets.push({
    address: input.address,
    panelId: input.panelId,
    vectorId,
    provenanceProfileId: input.profileId,
  });
}

function finalizeMap(
  map: Omit<
    FederalDefendantsGroupedSemanticMapV1,
    "geometryAuthority" | "geometryAuthorityDigest"
  >,
  bands: FederalDefendantsGeometryAuthorityV1["bands"],
): FederalDefendantsGroupedSemanticMapV1 {
  const geometryAuthority: FederalDefendantsGeometryAuthorityV1 = {
    version: FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1,
    source: structuredClone(map.source),
    panels: map.panels
      .map((panel) => ({
        panelId: panel.id,
        targetSelectors: structuredClone(panel.selectors),
      }))
      .sort((left, right) => left.panelId.localeCompare(right.panelId)),
    bands: structuredClone(bands).sort((left, right) =>
      left.id.localeCompare(right.id),
    ),
  };
  return {
    ...map,
    geometryAuthority,
    geometryAuthorityDigest:
      digestFederalDefendantsCanonical(geometryAuthority),
  };
}

function repinGeometryAuthority(
  map: FederalDefendantsGroupedSemanticMapV1,
): void {
  map.geometryAuthorityDigest = digestFederalDefendantsCanonical(
    map.geometryAuthority,
  );
}

function baseMap(
  sourceWorkbookDigest = fakeDigest("1"),
  executionWorkbookDigest = sourceWorkbookDigest,
): FederalDefendantsGroupedSemanticMapV1 {
  const builder: Builder = {
    geometryBands: [],
    sourceUniverses: [],
    bindings: [],
    vectors: [],
    targets: [],
  };
  const targetInputs = [
    ["R4C2", "current", "count", "R4C1", "R1C2", "R2C2", "R3C2"],
    ["R4C3", "current", "mean", "R4C1", "R1C2", "R2C3", "R3C2"],
    ["R4C4", "current", "median", "R4C1", "R1C4", "R2C4", "R3C2"],
    ["R7C2", "previous", "count", "R7C1", "R1C2", "R2C2", "R6C2"],
    ["R7C4", "previous", "median", "R7C1", "R1C4", "R2C4", "R6C2"],
  ] as const;
  for (const [
    address,
    panelId,
    profileId,
    row,
    sex,
    statistic,
    period,
  ] of targetInputs)
    addTarget(builder, {
      address,
      panelId,
      profileId,
      row,
      sex,
      statistic,
      period,
    });
  const previousStatisticUniverse = builder.sourceUniverses.find(
    (entry) => entry.id === "u-previous-statistic",
  )!;
  previousStatisticUniverse.selectors.push({ address: "R2C3" });
  return finalizeMap(
    {
      version: FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1,
      source: {
        version: FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1,
        sourceWorkbookDigest,
        executionWorkbookDigest,
        physicalSheet: "Table 7",
        authoritativeRange: "R1C1:R7C4",
      },
      logicalTable: {
        id: "federal-defendants",
        name: "Federal defendants",
        valuesName: "published value",
        dimensions: [
          {
            id: "offence-group",
            name: "principal federal offence group raw",
            source: { kind: "cell" },
          },
          { id: "sex", name: "sex raw", source: { kind: "cell" } },
          { id: "statistic", name: "statistic raw", source: { kind: "cell" } },
          {
            id: "observation-period",
            name: "observation period raw",
            source: { kind: "cell" },
          },
          ...provenanceDimensions.map(([id, name, field]) => ({
            id,
            name,
            source: { kind: "provenance" as const, field },
          })),
        ],
      },
      panels: [
        {
          id: "current",
          order: 1,
          key: "observation-period:2024-25",
          keySource: {
            dimensionId: "observation-period",
            selectedAddress: "R3C2",
          },
          name: "2024-25",
          selectors: [{ range: "R4C2:R4C4" }],
        },
        {
          id: "previous",
          order: 2,
          key: "observation-period:2023-24",
          keySource: {
            dimensionId: "observation-period",
            selectedAddress: "R6C2",
          },
          name: "2023-24",
          selectors: [{ range: "R7C2:R7C4" }],
        },
      ],
      sourceUniverses: builder.sourceUniverses,
      bindings: builder.bindings,
      vectors: builder.vectors,
      provenanceProfiles: [
        {
          id: "count",
          values: profile("defendant-count", "count", "defendants"),
        },
        { id: "mean", values: profile("mean-age", "mean", "years") },
        { id: "median", values: profile("median-age", "median", "years") },
      ],
      targets: builder.targets,
    },
    builder.geometryBands,
  );
}

function multiRowWestFixture(direction: "W" | "WNW") {
  const map = baseMap();
  const sheet = syntheticSheet();
  const rowHeader = sheet.cells.find((entry) => entry.address === "R5C1")!;
  rowHeader.value = "Customs";
  rowHeader.data_type = "string";
  const target = sheet.cells.find((entry) => entry.address === "R5C2")!;
  target.value = 2;
  target.data_type = "numeric";
  map.panels.find((entry) => entry.id === "current")!.selectors = [
    { range: "R4C2:R5C4" },
  ];
  map.geometryAuthority.panels.find(
    (entry) => entry.panelId === "current",
  )!.targetSelectors = [{ range: "R4C2:R5C4" }];
  addTarget(
    {
      geometryBands: map.geometryAuthority.bands,
      sourceUniverses: map.sourceUniverses,
      bindings: map.bindings,
      vectors: map.vectors,
      targets: map.targets,
    },
    {
      address: "R5C2",
      panelId: "current",
      profileId: "count",
      row: "R5C1",
      sex: "R1C2",
      statistic: "R2C2",
      period: "R3C2",
    },
  );
  const universe = map.sourceUniverses.find(
    (entry) => entry.id === "u-current-offence",
  )!;
  const band = map.geometryAuthority.bands.find(
    (entry) => entry.id === universe.authorityBandId,
  )!;
  universe.direction = direction;
  band.direction = direction;
  for (const target of map.targets.filter(
    (entry) => entry.panelId === "current",
  )) {
    const vector = map.vectors.find((entry) => entry.id === target.vectorId)!;
    const binding = map.bindings.find(
      (entry) =>
        vector.bindingIds.includes(entry.id) &&
        entry.dimensionId === "offence-group",
    )!;
    binding.direction = direction;
  }
  repinGeometryAuthority(map);
  return { map, sheet };
}

function coordinatedWestShrink(
  map: FederalDefendantsGroupedSemanticMapV1,
): void {
  const removedTarget = map.targets.find(
    (entry) => entry.address === "R5C2" && entry.panelId === "current",
  )!;
  const removedVector = map.vectors.find(
    (entry) => entry.id === removedTarget.vectorId,
  )!;
  const removedBindingIds = new Set(removedVector.bindingIds);
  map.targets = map.targets.filter((entry) => entry !== removedTarget);
  map.vectors = map.vectors.filter((entry) => entry !== removedVector);
  map.bindings = map.bindings.filter(
    (entry) => !removedBindingIds.has(entry.id),
  );
  map.panels.find((entry) => entry.id === "current")!.selectors = [
    { range: "R4C2:R4C4" },
  ];
  map.geometryAuthority.panels.find(
    (entry) => entry.panelId === "current",
  )!.targetSelectors = [{ range: "R4C2:R4C4" }];
  const universe = map.sourceUniverses.find(
    (entry) => entry.id === "u-current-offence",
  )!;
  universe.selectors = universe.selectors.filter(
    (selector) => !("address" in selector && selector.address === "R5C1"),
  );
  map.geometryAuthority.bands.find(
    (entry) => entry.id === universe.authorityBandId,
  )!.range = "R4C1:R4C1";
  repinGeometryAuthority(map);
}

function operationHeavyMap(): FederalDefendantsGroupedSemanticMapV1 {
  const map = baseMap();
  map.source.authoritativeRange = "R1C1:R7C16384";
  map.geometryAuthority.source = structuredClone(map.source);
  const currentPanel = map.panels.find((panel) => panel.id === "current")!;
  currentPanel.selectors = [{ range: "R4C2:R4C16384" }];
  map.geometryAuthority.panels.find(
    (panel) => panel.panelId === "current",
  )!.targetSelectors = structuredClone(currentPanel.selectors);
  const currentTarget = map.targets.find(
    (target) => target.address === "R4C4",
  )!;
  map.targets.push(
    ...Array.from({ length: 200 }, () => structuredClone(currentTarget)),
    { ...structuredClone(currentTarget), address: "R4C16384" },
  );
  for (const sourceUniverse of map.sourceUniverses.filter(
    (entry) =>
      entry.panelId === "current" &&
      (entry.direction === "N" || entry.direction === "NNW"),
  )) {
    const band = map.geometryAuthority.bands.find(
      (entry) => entry.id === sourceUniverse.authorityBandId,
    )!;
    const parsed = /^R(\d+)C\d+:R(\d+)C\d+$/.exec(band.range)!;
    band.range = `R${parsed[1]}C2:R${parsed[2]}C16384`;
  }
  repinGeometryAuthority(map);
  return map;
}

function compile(
  map: FederalDefendantsGroupedSemanticMapV1,
  sheet = syntheticSheet(),
) {
  const raw = `${JSON.stringify(map)}\n`;
  return {
    raw,
    result: compileFederalDefendantsGroupedRecipeV1({
      mapRaw: raw,
      expectedMapBytesDigest: digestFederalDefendantsBytes(raw),
      sheet,
      expectedExecutionWorkbookDigest: map.source.executionWorkbookDigest,
      expectedSourceWorkbookDigest: map.source.sourceWorkbookDigest,
    }),
  };
}

function expectFailure(
  mutation: (map: FederalDefendantsGroupedSemanticMapV1) => void,
  code: string,
): void {
  const map = structuredClone(baseMap());
  mutation(map);
  expect(compile(map).result).toMatchObject({ ok: false, code });
}

function realCanaryMap(digest: string): FederalDefendantsGroupedSemanticMapV1 {
  const builder: Builder = {
    geometryBands: [],
    sourceUniverses: [],
    bindings: [],
    vectors: [],
    targets: [],
  };
  const profiles = new Map<string, FederalTargetProvenance>();
  const panelSpecs: Array<[string, number, number, string]> = [
    ["current", 8, 34, "R7C2"],
    ["previous", 36, 62, "R35C2"],
  ];
  for (const [panelId, startRow, endRow, period] of panelSpecs) {
    for (let row = startRow; row <= endRow; row += 1) {
      for (let col = 2; col <= 10; col += 1) {
        const statisticKind = [2, 5, 8].includes(col)
          ? "count"
          : [3, 6, 9].includes(col)
            ? "mean"
            : "median";
        const sexTotalColumn = col >= 8;
        const includesOrganisations = col === 8;
        const grandTotal = row === endRow;
        const entityType = includesOrganisations
          ? "persons-and-organisations"
          : "persons-only";
        const hierarchy = grandTotal
          ? sexTotalColumn
            ? "grand-total-and-sex-total"
            : "grand-total"
          : sexTotalColumn
            ? "sex-total"
            : "leaf";
        const totalStatus = grandTotal
          ? "published-grand-total"
          : sexTotalColumn
            ? "published-sex-total"
            : "not-total";
        const profileId = [
          statisticKind,
          entityType,
          hierarchy,
          totalStatus,
        ].join("-");
        if (!profiles.has(profileId)) {
          const values = profile(
            statisticKind === "count"
              ? "defendant-count"
              : `${statisticKind}-age`,
            statisticKind,
            statisticKind === "count" ? "defendants" : "years",
            entityType,
            [
              ...(sexTotalColumn ? ["a"] : []),
              ...(includesOrganisations ? ["b"] : []),
              ...(grandTotal ? ["c"] : []),
            ],
            hierarchy,
            totalStatus,
          );
          values.denominator =
            statisticKind === "count"
              ? "published-finalised-defendants"
              : "published-age-eligible-person-defendants";
          profiles.set(profileId, values);
        }
        addTarget(builder, {
          address: `R${row}C${col}`,
          panelId,
          profileId,
          row: `R${row}C1`,
          sex: col <= 4 ? "R5C2" : col <= 7 ? "R5C5" : "R5C8",
          statistic: `R6C${col}`,
          period,
        });
      }
    }
  }
  return finalizeMap(
    {
      version: FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1,
      source: {
        version: FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1,
        sourceWorkbookDigest: digest,
        executionWorkbookDigest: digest,
        physicalSheet: "Table 7",
        authoritativeRange: "R1C1:R70C10",
      },
      logicalTable: {
        id: "federal-defendants",
        name: "Federal defendants by age and sex",
        valuesName: "published value",
        dimensions: [
          {
            id: "offence-group",
            name: "principal federal offence group raw",
            source: { kind: "cell" },
          },
          { id: "sex", name: "sex raw", source: { kind: "cell" } },
          {
            id: "statistic",
            name: "statistic raw",
            source: { kind: "cell" },
          },
          {
            id: "observation-period",
            name: "observation period raw",
            source: { kind: "cell" },
          },
          ...provenanceDimensions.map(([id, name, field]) => ({
            id,
            name,
            source: { kind: "provenance" as const, field },
          })),
        ],
      },
      panels: [
        {
          id: "current",
          order: 1,
          key: "observation-period:2024%E2%80%9325",
          keySource: {
            dimensionId: "observation-period",
            selectedAddress: "R7C2",
          },
          name: "2024-25",
          selectors: [{ range: "R8C2:R34C10" }],
        },
        {
          id: "previous",
          order: 2,
          key: "observation-period:2023%E2%80%9324",
          keySource: {
            dimensionId: "observation-period",
            selectedAddress: "R35C2",
          },
          name: "2023-24",
          selectors: [{ range: "R36C2:R62C10" }],
        },
      ],
      sourceUniverses: builder.sourceUniverses,
      bindings: builder.bindings,
      vectors: builder.vectors,
      provenanceProfiles: [...profiles].map(([id, values]) => ({ id, values })),
      targets: builder.targets,
    },
    builder.geometryBands,
  );
}

const realWorkbookPath = path.resolve(
  "fixtures/product-prototype/workbooks/federal-defendants-australia-2024-25-federal-offence-group-source.xlsx",
);
const realInventoryPath = path.resolve(
  "fixtures/product-prototype/federal-defendants-release-source-inventory-v1.json",
);
const REAL_WORKBOOK_BYTES = 70_342;
const REAL_WORKBOOK_DIGEST =
  "sha256:e813cd80e101c4ade831dc5dbbf501beebbe05e3286b521a7c13ec99c5a4043d";
const REAL_TABLE7_SEMANTIC_DIGEST =
  "sha256:60ca87fa038b905aa49b4e48452916beda58de25e2dcb180710c64dccc97b3cc";
const REAL_TABLE7_STRUCTURE_DIGEST =
  "sha256:e25482880beebb62a0c959dec4d0e363b6946d900f50c4ad14ad50f22222db4b";

async function realFixture() {
  const bytes = await readFile(realWorkbookPath);
  const digest = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
  expect(bytes.byteLength).toBe(REAL_WORKBOOK_BYTES);
  expect(digest).toBe(REAL_WORKBOOK_DIGEST);
  const inventory = JSON.parse(await readFile(realInventoryPath, "utf8")) as {
    downloads: Array<{
      releaseId: string;
      downloadOrdinal: number;
      contentDigest: string;
      byteLength: number;
      sheets: Array<{
        name: string;
        semanticCellDigest?: string;
        worksheetStructureDigest?: string;
      }>;
    }>;
  };
  const download = inventory.downloads.find(
    (entry) => entry.releaseId === "2024-25" && entry.downloadOrdinal === 2,
  );
  const inventorySheet = download?.sheets.find(
    (entry) => entry.name === "Table 7",
  );
  expect(download).toMatchObject({
    contentDigest: REAL_WORKBOOK_DIGEST,
    byteLength: REAL_WORKBOOK_BYTES,
  });
  expect(inventorySheet).toMatchObject({
    semanticCellDigest: REAL_TABLE7_SEMANTIC_DIGEST,
    worksheetStructureDigest: REAL_TABLE7_STRUCTURE_DIGEST,
  });
  const parsed = await parseWorkbook(bytes);
  if (!parsed.ok) throw new Error(parsed.errors[0].message);
  const sheet = parsed.workbook.sheets.find(
    (entry) => entry.name === "Table 7",
  )!;
  const map = realCanaryMap(digest);
  const raw = `${JSON.stringify(map)}\n`;
  return { bytes, digest, sheet, map, raw };
}

describe("Federal Defendants grouped RecipeV1", () => {
  it("percent-encodes exact raw UTF-8 panel keys reversibly without normalization", () => {
    const examples = [
      [
        "Latest 5 years (2017–18 to 2021–22)",
        "Latest%205%20years%20%282017%E2%80%9318%20to%202021%E2%80%9322%29",
      ],
      [
        "Previous 5 years ( 2012–13...)",
        "Previous%205%20years%20%28%202012%E2%80%9313...%29",
      ],
      ["Vic.(a)", "Vic.%28a%29"],
      ["2010–11(a)", "2010%E2%80%9311%28a%29"],
      [
        "Total finalised (excluding transfer to other court levels)",
        "Total%20finalised%20%28excluding%20transfer%20to%20other%20court%20levels%29",
      ],
      ["A/B?C#D% E", "A%2FB%3FC%23D%25%20E"],
      [
        "é|e\u0301|Ａ|A|–|-",
        "%C3%A9%7Ce%CC%81%7C%EF%BC%A1%7CA%7C%E2%80%93%7C-",
      ],
      ["AZaz09-._~", "AZaz09-._~"],
    ] as const;
    const encodedExamples = examples.map(([raw, encoded]) => {
      expect(encodeFederalPanelKeySourceValue(raw), raw).toBe(encoded);
      expect(decodeFederalPanelKeySourceValue(encoded), encoded).toBe(raw);
      return encoded;
    });
    expect(new Set(encodedExamples).size).toBe(examples.length);

    expect(encodeFederalPanelKeySourceValue("A")).not.toBe(
      encodeFederalPanelKeySourceValue("a"),
    );
    expect(encodeFederalPanelKeySourceValue("é")).not.toBe(
      encodeFederalPanelKeySourceValue("e\u0301"),
    );
    expect(encodeFederalPanelKeySourceValue("–")).not.toBe(
      encodeFederalPanelKeySourceValue("-"),
    );
    expect(encodeFederalPanelKeySourceValue(" leading")).toBe("%20leading");
    for (const invalid of ["", 1, true, null, "\ud800", "\udc00"])
      expect(() => encodeFederalPanelKeySourceValue(invalid)).toThrow(
        "FEDERAL_PANEL_KEY_SOURCE_INVALID",
      );
    for (const invalid of ["%41", "%c3%A9", "%FF", "A/B", "%", "%0"])
      expect(() => decodeFederalPanelKeySourceValue(invalid)).toThrow(
        "FEDERAL_PANEL_KEY_SOURCE_INVALID",
      );

    for (const invalid of ["", 1, "\ud800"] as const) {
      const sheet = syntheticSheet();
      const keyCell = sheet.cells.find((entry) => entry.address === "R3C2")!;
      keyCell.value = invalid;
      keyCell.data_type = typeof invalid === "number" ? "numeric" : "string";
      expect(compile(baseMap(), sheet).result).toMatchObject({
        ok: false,
        code: "FEDERAL_PANEL_KEY_SOURCE_INVALID",
      });
    }
  });

  it("binds official punctuated panel keys to exact raw source evidence", () => {
    const examples = [
      "Latest 5 years (2017–18 to 2021–22)",
      "Previous 5 years ( 2012–13...)",
      "Vic.(a)",
      "2010–11(a)",
      "Total finalised (excluding transfer to other court levels)",
    ];
    for (const rawValue of examples) {
      const sheet = syntheticSheet();
      const keyCell = sheet.cells.find((entry) => entry.address === "R3C2")!;
      keyCell.value = rawValue;
      keyCell.formula = `=${JSON.stringify(rawValue)}`;
      keyCell.formatted = rawValue;
      const map = baseMap();
      const encodedValue = encodeFederalPanelKeySourceValue(rawValue);
      map.panels[0].key = `observation-period:${encodedValue}`;
      const compiled = compile(map, sheet);
      expect(compiled.result.ok, rawValue).toBe(true);
      if (!compiled.result.ok) continue;
      const panel = compiled.result.envelope.recipe.panels[0];
      expect(panel.key).toBe(`observation-period:${encodedValue}`);
      expect(panel.keySource).toMatchObject({
        dimensionId: "observation-period",
        selectedAddress: "R3C2",
        rawValue,
        encodedValue,
        source: {
          sheet: "Table 7",
          address: "R3C2",
          row: 3,
          col: 2,
          data_type: "string",
          formula: `=${JSON.stringify(rawValue)}`,
          formatted: rawValue,
        },
      });
      const firstProof =
        compiled.result.envelope.attachmentManifest.attachments[0]
          .panelKeyAttachment;
      expect(firstProof).toEqual({
        dimensionId: "observation-period",
        key: `observation-period:${encodedValue}`,
        selectedAddress: "R3C2",
        rawValue,
        encodedValue,
        source: panel.keySource.source,
      });
      const execution = executeFederalDefendantsGroupedRecipeV1(
        compiled.result.envelope,
        {
          mapRaw: compiled.raw,
          sheet,
          expectedExecutionWorkbookDigest: map.source.executionWorkbookDigest,
          expectedSourceWorkbookDigest: map.source.sourceWorkbookDigest,
          trustedEnvelopeDigest: compiled.result.envelope.envelopeDigest,
        },
      );
      expect(
        execution.tables[0].trace.value_cells[0].panelKeyAttachment,
      ).toEqual(firstProof);
      expect(execution.tables[0].rows[0]._panel_key).toBe(
        `observation-period:${encodedValue}`,
      );
    }
  });

  it("compiles repeated panels, grouped headers, sparse cells, formulas, markers and zeros", () => {
    const map = baseMap();
    const { raw, result } = compile(map);
    expect(result.ok, JSON.stringify(result)).toBe(true);
    if (!result.ok) return;
    expect(result.envelope.recipe.version).toBe(
      FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1,
    );
    expect(result.envelope.targetManifest).toMatchObject({
      count: 5,
      markerCount: 1,
      zeroCount: 1,
    });
    expect(result.envelope.formulaProof).toMatchObject({
      count: 1,
      addresses: ["R3C2"],
    });
    const execution = executeFederalDefendantsGroupedRecipeV1(result.envelope, {
      mapRaw: raw,
      sheet: syntheticSheet(),
      expectedExecutionWorkbookDigest: map.source.executionWorkbookDigest,
      expectedSourceWorkbookDigest: map.source.sourceWorkbookDigest,
      trustedEnvelopeDigest: result.envelope.envelopeDigest,
    });
    expect(execution.version).toBe(FEDERAL_DEFENDANTS_GROUPED_EXECUTION_V1);
    expect(execution.providerCalls).toBe(0);
    expect(execution.acceptanceAuthority).toBe(false);
    expect(execution.trainingEligibility).toBe(false);
    expect(execution.tables[0].rows).toHaveLength(5);
    expect(execution.tables[0].rows[0]).toMatchObject({
      "published value": 0,
      "published value numeric": 0,
      "published value status": "observed",
      "sex raw": "Males",
      "statistic raw": "No. of defendants",
      "observation period raw": "2024-25",
      "measure id": "defendant-count",
      _panel_id: "current",
      _panel_key: "observation-period:2024-25",
      _panel_name: "2024-25",
      _panel_order: 1,
      perturbation: true,
    });
    expect(execution.tables[0].rows[2]).toMatchObject({
      "published value": "np",
      "published value numeric": null,
      "published value status": "not-published",
    });
    expect(JSON.stringify(execution)).not.toContain(
      "out-of-range stale accessibility text",
    );
  });

  it("is deterministic and rejects envelope, source and semantic drift", () => {
    const first = compile(baseMap());
    const second = compile(baseMap());
    const firstResult = first.result;
    const secondResult = second.result;
    if (!firstResult.ok || !secondResult.ok) throw new Error("compile failed");
    expect(secondResult.envelope).toEqual(firstResult.envelope);
    expect(() =>
      executeFederalDefendantsGroupedRecipeV1(firstResult.envelope, {
        mapRaw: first.raw,
        sheet: syntheticSheet(),
        expectedExecutionWorkbookDigest: fakeDigest("1"),
        expectedSourceWorkbookDigest: fakeDigest("1"),
        trustedEnvelopeDigest: fakeDigest("0"),
      }),
    ).toThrow("FEDERAL_TRUSTED_ENVELOPE_DIGEST_MISMATCH");
    expectFailure((map) => {
      map.bindings[0].direction = "N";
    }, "FEDERAL_BINDING_UNIVERSE_SCOPE_MISMATCH");
    expectFailure((map) => {
      map.targets.splice(
        map.targets.findIndex((target) => target.address === "R4C3"),
        1,
      );
    }, "FEDERAL_TARGET_COVERAGE_MISMATCH");
    expectFailure((map) => {
      map.panels[1].key = map.panels[0].key;
    }, "FEDERAL_DUPLICATE_PANEL");
    expectFailure((map) => {
      map.panels[0].key = "observation-period:1999-00";
    }, "FEDERAL_PANEL_KEY_SOURCE_MISMATCH");
    expectFailure((map) => {
      const universe = map.sourceUniverses.find(
        (entry) => entry.id === "u-current-sex",
      )!;
      universe.selectors = universe.selectors.filter(
        (selector) => !("address" in selector && selector.address === "R1C4"),
      );
    }, "FEDERAL_INCOMPLETE_SOURCE_UNIVERSE");
    expectFailure((map) => {
      const target = map.targets.find((entry) => entry.address === "R4C4")!;
      const vector = map.vectors.find((entry) => entry.id === target.vectorId)!;
      const binding = map.bindings.find(
        (entry) =>
          vector.bindingIds.includes(entry.id) && entry.dimensionId === "sex",
      )!;
      binding.selectedAddress = "R1C2";
    }, "FEDERAL_AMBIGUOUS_DIMENSION_SOURCE");
    expectFailure((map) => {
      map.logicalTable.dimensions[0].name = "published value numeric";
    }, "FEDERAL_DUPLICATE_OR_RESERVED_OUTPUT_NAME");
    expectFailure((map) => {
      map.source.authoritativeRange = "R1C1:R3C3";
      map.geometryAuthority.source = structuredClone(map.source);
      repinGeometryAuthority(map);
    }, "FEDERAL_SELECTOR_OUTSIDE_AUTHORITY");
    const wrongPin = compileFederalDefendantsGroupedRecipeV1({
      mapRaw: first.raw,
      expectedMapBytesDigest: fakeDigest("0"),
      sheet: syntheticSheet(),
      expectedExecutionWorkbookDigest: fakeDigest("1"),
    });
    expect(wrongPin).toMatchObject({
      ok: false,
      code: "FEDERAL_MAP_EXTERNAL_PIN_MISMATCH",
    });
    const sourceMismatchMap = baseMap(fakeDigest("2"), fakeDigest("1"));
    const sourceMismatchRaw = JSON.stringify(sourceMismatchMap);
    expect(
      compileFederalDefendantsGroupedRecipeV1({
        mapRaw: sourceMismatchRaw,
        expectedMapBytesDigest: digestFederalDefendantsBytes(sourceMismatchRaw),
        sheet: syntheticSheet(),
        expectedExecutionWorkbookDigest: fakeDigest("1"),
        expectedSourceWorkbookDigest: fakeDigest("1"),
      }),
    ).toMatchObject({ ok: false, code: "FEDERAL_SOURCE_CONTEXT_MISMATCH" });

    const reorderedMap = baseMap();
    reorderedMap.panels[0].order = 2;
    reorderedMap.panels[1].order = 1;
    const reordered = compile(reorderedMap);
    if (!reordered.result.ok) throw new Error("reordered compile failed");
    const reorderedExecution = executeFederalDefendantsGroupedRecipeV1(
      reordered.result.envelope,
      {
        mapRaw: reordered.raw,
        sheet: syntheticSheet(),
        expectedExecutionWorkbookDigest: fakeDigest("1"),
        expectedSourceWorkbookDigest: fakeDigest("1"),
        trustedEnvelopeDigest: reordered.result.envelope.envelopeDigest,
      },
    );
    expect(reorderedExecution.tables[0].rows[0]).toMatchObject({
      _panel_id: "previous",
      _panel_order: 1,
    });

    const tampered = structuredClone(firstResult.envelope);
    tampered.recipe.panels[0].name = "tampered";
    expect(() =>
      executeFederalDefendantsGroupedRecipeV1(tampered, {
        mapRaw: first.raw,
        sheet: syntheticSheet(),
        expectedExecutionWorkbookDigest: fakeDigest("1"),
        expectedSourceWorkbookDigest: fakeDigest("1"),
        trustedEnvelopeDigest: firstResult.envelope.envelopeDigest,
      }),
    ).toThrow("FEDERAL_ENVELOPE_DIGEST_MISMATCH");
  });

  it("requires complete target-level provenance and mutually rejects existing formats", () => {
    const value = structuredClone(baseMap()) as unknown as Record<
      string,
      unknown
    >;
    const profiles = value.provenanceProfiles as Array<{
      values: Record<string, unknown>;
    }>;
    delete profiles[0].values.perturbation;
    expect(() =>
      parseFederalDefendantsGroupedSemanticMapV1(JSON.stringify(value)),
    ).toThrow();
    const raw = JSON.stringify(baseMap());
    expect(() => parseSemanticTableMapJson(raw)).toThrow();
    expect(() => parseSemanticTableMapV2Json(raw)).toThrow();
    expect(() => parseTargetScopedSemanticMapV1(raw)).toThrow();
    expect(() =>
      parseFederalDefendantsGroupedSemanticMapV1(
        JSON.stringify({ version: "semantic-table-map-v1" }),
      ),
    ).toThrow();
  });

  it("enforces the Federal JSON byte budget at its exact boundary", () => {
    const prefix = `{"version":"${FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1}","pad":"`;
    const suffix = `"}`;
    const exact = `${prefix}${"x".repeat(
      MAX_FEDERAL_GROUPED_JSON_BYTES - Buffer.byteLength(prefix + suffix),
    )}${suffix}`;
    let exactError = "";
    try {
      parseFederalDefendantsGroupedSemanticMapV1(exact);
    } catch (error) {
      exactError = error instanceof Error ? error.message : String(error);
    }
    expect(exactError).not.toContain("FEDERAL_GROUPED_JSON_BYTE_LIMIT");
    expect(() =>
      parseFederalDefendantsGroupedSemanticMapV1(`${exact} `),
    ).toThrow("FEDERAL_GROUPED_JSON_BYTE_LIMIT");
  });

  it("enforces exact JSON node/depth structure before JSON.parse", () => {
    const exactNodes = `[${Array.from(
      { length: MAX_FEDERAL_GROUPED_JSON_NODES - 1 },
      () => "0",
    ).join(",")}]`;
    expect(() => assertFederalGroupedJsonBudget(exactNodes)).not.toThrow();
    const overNodes = `${exactNodes.slice(0, -1)},0]`;
    expect(() => assertFederalGroupedJsonBudget(overNodes)).toThrow(
      "FEDERAL_GROUPED_JSON_NODE_LIMIT",
    );
    const exactDepth = `${"[".repeat(MAX_FEDERAL_GROUPED_JSON_DEPTH)}0${"]".repeat(MAX_FEDERAL_GROUPED_JSON_DEPTH)}`;
    expect(() => assertFederalGroupedJsonBudget(exactDepth)).not.toThrow();
    const overDepth = `[${exactDepth}]`;
    expect(() => assertFederalGroupedJsonBudget(overDepth)).toThrow(
      "FEDERAL_GROUPED_JSON_DEPTH_LIMIT",
    );
    for (const malformed of [
      String.raw`["\x"]`,
      "[}",
      '["unterminated]',
      '{"a":0,}',
      "[0,]",
      '{"a":[0,] }',
      '{,"a":0}',
      "[,0]",
      '{"a":0,,"b":1}',
    ])
      expect(() => assertFederalGroupedJsonBudget(malformed)).toThrow(
        "FEDERAL_GROUPED_JSON_STRUCTURE_INVALID",
      );
  });

  it("compiles a valid coordinated west-axis shrink only after repinning geometry authority", () => {
    const baselineDigests = {
      W: "sha256:e6b205f6a31d517d526782d1884933b7b866ec11463372a6e934f351208b1c0d",
      WNW: "sha256:e0d3e02f2060efa457a65c0309f7ddfa8397f5db11245e723da425c12ee46314",
    } as const;
    const expectedDigests = {
      W: "sha256:808048d3541a36a41351d03695f88e59de56b2e0c4d4fe0ef061147c2b10beaf",
      WNW: "sha256:b6442bf5723805b4ee118d4a85c8e388499b23bd3fda08bd65cb13691c5e24c2",
    } as const;
    for (const direction of ["W", "WNW"] as const) {
      const { map, sheet } = multiRowWestFixture(direction);
      const baseline = compile(map, sheet);
      expect(baseline.result, JSON.stringify(baseline.result)).toMatchObject({
        ok: true,
      });
      const originalDigest = map.geometryAuthorityDigest;
      expect(originalDigest).toBe(baselineDigests[direction]);
      coordinatedWestShrink(map);
      expect(map.geometryAuthorityDigest).not.toBe(originalDigest);
      expect(compile(map, sheet).result).toMatchObject({ ok: true });
      expect(map.geometryAuthorityDigest).toBe(expectedDigests[direction]);
    }
  });

  it("preserves every exact marker spelling and rejects case or whitespace drift", () => {
    const cases = new Map<string, string>([
      ["np", "not-published"],
      ["n.p.", "not-published"],
      ["na", "not-available"],
      ["n.a.", "not-available"],
      ["..", "not-applicable"],
      ["-", "nil-or-rounded-to-zero"],
      ["–", "nil-or-rounded-to-zero"],
    ]);
    for (const [marker, status] of cases) {
      const sheet = syntheticSheet();
      sheet.cells.find((entry) => entry.address === "R4C4")!.value = marker;
      const compiled = compile(baseMap(), sheet);
      expect(compiled.result.ok, marker).toBe(true);
      if (!compiled.result.ok) continue;
      const execution = executeFederalDefendantsGroupedRecipeV1(
        compiled.result.envelope,
        {
          mapRaw: compiled.raw,
          sheet,
          expectedExecutionWorkbookDigest: fakeDigest("1"),
          expectedSourceWorkbookDigest: fakeDigest("1"),
          trustedEnvelopeDigest: compiled.result.envelope.envelopeDigest,
        },
      );
      expect(execution.tables[0].rows[2]).toMatchObject({
        "published value": marker,
        "published value status": status,
      });
    }
    for (const invalid of ["NP", " np"]) {
      const sheet = syntheticSheet();
      sheet.cells.find((entry) => entry.address === "R4C4")!.value = invalid;
      expect(compile(baseMap(), sheet).result).toMatchObject({
        ok: false,
        code: "FEDERAL_INVALID_TARGET_MARKER",
      });
    }
  });

  it("rejects meaningful whole-band omissions for N, NNW, W and WNW", () => {
    for (const [id, omitted] of [
      ["u-current-statistic", "R2C3"],
      ["u-current-sex", "R1C4"],
    ] as const) {
      const map = baseMap();
      const universe = map.sourceUniverses.find((entry) => entry.id === id)!;
      universe.selectors = universe.selectors.filter(
        (selector) => !("address" in selector && selector.address === omitted),
      );
      expect(compile(map).result).toMatchObject({
        ok: false,
        code: "FEDERAL_INCOMPLETE_SOURCE_UNIVERSE",
      });
    }
    for (const direction of ["W", "WNW"] as const) {
      const { map, sheet } = multiRowWestFixture(direction);
      const universe = map.sourceUniverses.find(
        (entry) => entry.id === "u-current-offence",
      )!;
      expect(universe.selectors).toEqual(
        expect.arrayContaining([{ address: "R4C1" }, { address: "R5C1" }]),
      );
      universe.selectors = universe.selectors.filter(
        (selector) => !("address" in selector && selector.address === "R5C1"),
      );
      expect(compile(map, sheet).result).toMatchObject({
        ok: false,
        code: "FEDERAL_INCOMPLETE_SOURCE_UNIVERSE",
      });
    }
  });

  it("enforces complete WNW universes and pre-allocation caller limits", () => {
    const wnw = baseMap();
    const universe = wnw.sourceUniverses.find(
      (entry) => entry.id === "u-current-offence",
    )!;
    universe.direction = "WNW";
    wnw.geometryAuthority.bands.find(
      (entry) => entry.id === universe.authorityBandId,
    )!.direction = "WNW";
    repinGeometryAuthority(wnw);
    for (const target of wnw.targets.filter(
      (entry) => entry.panelId === "current",
    )) {
      const vector = wnw.vectors.find((entry) => entry.id === target.vectorId)!;
      const binding = wnw.bindings.find(
        (entry) =>
          vector.bindingIds.includes(entry.id) &&
          entry.dimensionId === "offence-group",
      )!;
      binding.direction = "WNW";
    }
    expect(compile(wnw).result).toMatchObject({ ok: true });

    const base = baseMap();
    const raw = `${JSON.stringify(base)}\n`;
    const baseline = compile(base);
    expect(baseline.result.ok).toBe(true);
    if (!baseline.result.ok) return;
    const exactOperations =
      baseline.result.envelope.attachmentManifest.operations;
    const limited = (limits: {
      maxSelectorCells: number;
      maxOutputRows: number;
      maxOperations?: number;
    }) =>
      compileFederalDefendantsGroupedRecipeV1({
        mapRaw: raw,
        expectedMapBytesDigest: digestFederalDefendantsBytes(raw),
        sheet: syntheticSheet(),
        expectedExecutionWorkbookDigest: fakeDigest("1"),
        expectedSourceWorkbookDigest: fakeDigest("1"),
        limits,
      });
    expect(limited({ maxSelectorCells: 40, maxOutputRows: 100 })).toMatchObject(
      {
        ok: true,
      },
    );
    expect(limited({ maxSelectorCells: 39, maxOutputRows: 100 })).toMatchObject(
      {
        ok: false,
        code: "FEDERAL_SELECTED_CELL_LIMIT",
      },
    );
    expect(limited({ maxSelectorCells: 1, maxOutputRows: 100 })).toMatchObject({
      ok: false,
      code: "FEDERAL_SELECTED_CELL_LIMIT",
    });
    expect(limited({ maxSelectorCells: 100, maxOutputRows: 4 })).toMatchObject({
      ok: false,
      code: "FEDERAL_OUTPUT_ROW_LIMIT",
    });
    expect(
      limited({
        maxSelectorCells: 100,
        maxOutputRows: 100,
        maxOperations: exactOperations,
      }),
    ).toMatchObject({ ok: true });
    expect(
      limited({
        maxSelectorCells: 100,
        maxOutputRows: 100,
        maxOperations: exactOperations - 1,
      }),
    ).toMatchObject({ ok: false, code: "FEDERAL_OPERATION_LIMIT" });

    const oversized = baseMap();
    oversized.source.authoritativeRange = "R1C1:R100001C4";
    oversized.geometryAuthority.source = structuredClone(oversized.source);
    oversized.panels[0].selectors = [{ range: "R1C1:R100001C1" }];
    oversized.geometryAuthority.panels.find(
      (entry) => entry.panelId === oversized.panels[0].id,
    )!.targetSelectors = structuredClone(oversized.panels[0].selectors);
    repinGeometryAuthority(oversized);
    const oversizedRaw = JSON.stringify(oversized);
    expect(
      compileFederalDefendantsGroupedRecipeV1({
        mapRaw: oversizedRaw,
        expectedMapBytesDigest: digestFederalDefendantsBytes(oversizedRaw),
        sheet: syntheticSheet(),
        expectedExecutionWorkbookDigest: fakeDigest("1"),
        expectedSourceWorkbookDigest: fakeDigest("1"),
      }),
    ).toMatchObject({ ok: false, code: "FEDERAL_SELECTED_CELL_LIMIT" });

    expect(compile(operationHeavyMap()).result).toMatchObject({
      ok: false,
      code: "FEDERAL_OPERATION_LIMIT",
    });
  });

  it("executes a real bounded 2024-25 Table 7 grouped-header canary", async () => {
    const { digest, sheet, map, raw } = await realFixture();
    const first = compileFederalDefendantsGroupedRecipeV1({
      mapRaw: raw,
      expectedMapBytesDigest: digestFederalDefendantsBytes(raw),
      sheet,
      expectedExecutionWorkbookDigest: digest,
      expectedSourceWorkbookDigest: digest,
    });
    const second = compileFederalDefendantsGroupedRecipeV1({
      mapRaw: raw,
      expectedMapBytesDigest: digestFederalDefendantsBytes(raw),
      sheet,
      expectedExecutionWorkbookDigest: digest,
      expectedSourceWorkbookDigest: digest,
    });
    expect(first.ok, JSON.stringify(first)).toBe(true);
    expect(second).toEqual(first);
    if (!first.ok) return;
    const execution = executeFederalDefendantsGroupedRecipeV1(first.envelope, {
      mapRaw: raw,
      sheet,
      expectedExecutionWorkbookDigest: digest,
      expectedSourceWorkbookDigest: digest,
      trustedEnvelopeDigest: first.envelope.envelopeDigest,
    });
    expect(first.envelope.geometryAuthorityProof.digest).toBe(
      map.geometryAuthorityDigest,
    );
    expect(first.envelope.recipe.geometryAuthorityDigest).toBe(
      map.geometryAuthorityDigest,
    );
    expect(execution.geometryAuthorityDigest).toBe(map.geometryAuthorityDigest);
    expect(execution.tables[0].rows).toHaveLength(486);
    expect(execution.tables[0].rows[0]).toMatchObject({
      "principal federal offence group raw": "Aviation",
      "sex raw": "Males",
      "statistic raw": "No. of defendants",
      "observation period raw": "2024–25",
      "published value": 97,
      "population basis": "finalised-excluding-transfers",
      "transfer policy": "transfers-excluded",
      "entity type": "persons-only",
      denominator: "published-finalised-defendants",
      "row classification": "abs-federal-offence-group",
      "principal offence classification": "anzsoc-2023",
      "classification treatment": "native-federal-offence-group",
      "principal selection version":
        "2018-19-plus-method-finalisation-sentence-then-noi",
      "sentence classification treatment":
        "not-applicable-no-sentence-dimension",
      "revision treatment": "as-published-no-member-specific-revision-rule",
      "measure id": "defendant-count",
      "statistic code": "count",
      "unit id": "defendants",
      hierarchy: "leaf",
      "total status": "not-total",
      "footnote references": "",
      perturbation: true,
    });
    const suppressed = execution.tables[0].rows.find(
      (row) => (row._source as { address: string }).address === "R13C6",
    );
    expect(suppressed).toMatchObject({
      "sex raw": "Females",
      "statistic raw": "Mean age (years)",
      "published value": "np",
      "published value numeric": null,
      "published value status": "not-published",
      "entity type": "persons-only",
      denominator: "published-age-eligible-person-defendants",
      "measure id": "mean-age",
      "statistic code": "mean",
      "unit id": "years",
    });
    const totalCount = execution.tables[0].rows.find(
      (row) => (row._source as { address: string }).address === "R34C8",
    );
    expect(totalCount).toMatchObject({
      "sex raw": "Total(a)",
      "entity type": "persons-and-organisations",
      hierarchy: "grand-total-and-sex-total",
      "total status": "published-grand-total",
      "footnote references": "a|b|c",
    });
    const totalMean = execution.tables[0].rows.find(
      (row) => (row._source as { address: string }).address === "R34C9",
    );
    expect(totalMean).toMatchObject({
      "entity type": "persons-only",
      denominator: "published-age-eligible-person-defendants",
      "footnote references": "a|c",
    });
    expect(first.envelope.targetManifest).toMatchObject({
      count: 486,
      markerCount: 36,
      zeroCount: 52,
    });
    expect(first.envelope.formulaProof.count).toBe(0);
    expect(map.source.authoritativeRange).toBe("R1C1:R70C10");
  });

  it("rejects malformed and node-oversized Federal maps before workbook parsing", async () => {
    const root = await mkdtemp(
      path.join(tmpdir(), "federal-grouped-preflight-"),
    );
    roots.push(root);
    const input = path.join(root, "input");
    await mkdir(input);
    const workbook = Buffer.from("not-an-xlsx", "utf8");
    const descriptor = (name: string, relativePath: string, data: Buffer) => ({
      name,
      relativePath,
      contentDigest: `sha256:${createHash("sha256").update(data).digest("hex")}`,
      byteLength: data.byteLength,
    });
    await writeFile(path.join(input, "workbook.xlsx"), workbook);
    const maps = [
      Buffer.from(
        `{"version":"${FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1}","logicalTable":`,
        "utf8",
      ),
      Buffer.from(
        JSON.stringify({
          version: FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1,
          nodes: Array.from({ length: 500_002 }, () => null),
        }),
        "utf8",
      ),
    ];
    for (const [index, map] of maps.entries()) {
      await writeFile(path.join(input, `map-${index}.json`), map);
      const output = path.join(root, `output-${index}`);
      await mkdir(output);
      const result = await runPrototypeAwareWorker(
        {
          protocolVersion: "tidy.worker/v1",
          requestId: `federal-preflight-${index}`,
          operation: "interpret-semantic-map-v13",
          inputs: [
            descriptor("workbook", "workbook.xlsx", workbook),
            descriptor("semantic-map", `map-${index}.json`, map),
          ],
          parameters: { sheet: "Table 7" },
          limits: {
            timeoutMs: 300_000,
            maxInputBytes: 50_000_000,
            maxOutputBytes: 50_000_000,
            maxOutputFiles: 100,
            maxWarnings: 100,
            maxWorkbookCompressedBytes: 25_000_000,
            maxZipEntries: 10_000,
            maxZipEntryUncompressedBytes: 50_000_000,
            maxZipTotalUncompressedBytes: 200_000_000,
            maxSheets: 256,
            maxCells: 1_000_000,
            maxMerges: 100_000,
            maxMergeExpansionCells: 1_000_000,
            maxSelectorCells: 1_000_000,
            maxOutputRows: 1_000_000,
          },
        },
        input,
        output,
      );
      expect(result).toMatchObject({
        ok: false,
        error: { code: "FEDERAL_GROUPED_SCHEMA_INVALID" },
      });
      expect(JSON.stringify(result)).not.toContain("INVALID_WORKBOOK");
    }

    const validMap = Buffer.from(JSON.stringify(baseMap()), "utf8");
    await writeFile(path.join(input, "valid-map.json"), validMap);
    const output = path.join(root, "output-budget-before-workbook");
    await mkdir(output);
    const preflightRequest: PrototypeWorkerRequest = {
      protocolVersion: "tidy.worker/v1",
      requestId: "federal-budget-before-workbook",
      operation: "interpret-semantic-map-v13",
      inputs: [
        descriptor("workbook", "workbook.xlsx", workbook),
        descriptor("semantic-map", "valid-map.json", validMap),
      ],
      parameters: { sheet: "Table 7" },
      limits: {
        timeoutMs: 300_000,
        maxInputBytes: 50_000_000,
        maxOutputBytes: 512,
        maxOutputFiles: 100,
        maxWarnings: 100,
        maxWorkbookCompressedBytes: 25_000_000,
        maxZipEntries: 10_000,
        maxZipEntryUncompressedBytes: 50_000_000,
        maxZipTotalUncompressedBytes: 200_000_000,
        maxSheets: 256,
        maxCells: 1_000_000,
        maxMerges: 100_000,
        maxMergeExpansionCells: 1_000_000,
        maxSelectorCells: 1_000_000,
        maxOutputRows: 1_000_000,
      },
    };
    await expect(
      runPrototypeAwareWorker(preflightRequest, input, output),
    ).rejects.toMatchObject({ code: "OUTPUT_LIMIT_EXCEEDED" });

    const selectorOutput = path.join(root, "selector-before-workbook");
    await mkdir(selectorOutput);
    const selectorResult = await runPrototypeAwareWorker(
      {
        ...preflightRequest,
        requestId: "federal-selector-before-workbook",
        limits: {
          ...preflightRequest.limits,
          maxOutputBytes: 50_000_000,
          maxSelectorCells: 1,
        },
      },
      input,
      selectorOutput,
    );
    expect(selectorResult).toMatchObject({
      ok: false,
      error: { code: "FEDERAL_SELECTED_CELL_LIMIT" },
    });
    expect(JSON.stringify(selectorResult)).not.toContain("INVALID_WORKBOOK");

    const operationMap = Buffer.from(
      JSON.stringify(operationHeavyMap()),
      "utf8",
    );
    await writeFile(path.join(input, "operation-map.json"), operationMap);
    const operationOutput = path.join(root, "operation-before-workbook");
    await mkdir(operationOutput);
    const operationResult = await runPrototypeAwareWorker(
      {
        ...preflightRequest,
        requestId: "federal-operation-before-workbook",
        inputs: [
          descriptor("workbook", "workbook.xlsx", workbook),
          descriptor("semantic-map", "operation-map.json", operationMap),
        ],
        limits: {
          ...preflightRequest.limits,
          maxOutputBytes: 50_000_000,
        },
      },
      input,
      operationOutput,
    );
    expect(operationResult).toMatchObject({
      ok: false,
      error: { code: "FEDERAL_OPERATION_LIMIT" },
    });
    expect(JSON.stringify(operationResult)).not.toContain("INVALID_WORKBOOK");
  });

  it("runs through the provider-free worker dispatch with pinned inputs", async () => {
    const { bytes, raw } = await realFixture();
    const root = await mkdtemp(path.join(tmpdir(), "federal-grouped-worker-"));
    roots.push(root);
    const input = path.join(root, "input");
    const output = path.join(root, "output");
    await mkdir(input);
    await mkdir(output);
    await writeFile(path.join(input, "workbook.xlsx"), bytes);
    await writeFile(path.join(input, "semantic-map.json"), raw);
    const descriptor = (
      name: string,
      relativePath: string,
      data: Uint8Array | string,
    ) => ({
      name,
      relativePath,
      contentDigest: `sha256:${createHash("sha256").update(data).digest("hex")}`,
      byteLength: Buffer.byteLength(data),
    });
    const request: PrototypeWorkerRequest = {
      protocolVersion: "tidy.worker/v1",
      requestId: "federal-grouped-canary",
      operation: "interpret-semantic-map-v13",
      inputs: [
        descriptor("workbook", "workbook.xlsx", bytes),
        descriptor("semantic-map", "semantic-map.json", raw),
      ],
      parameters: { sheet: "Table 7" },
      limits: {
        timeoutMs: 300_000,
        maxInputBytes: 50_000_000,
        maxOutputBytes: 50_000_000,
        maxOutputFiles: 100,
        maxWarnings: 100,
        maxWorkbookCompressedBytes: 25_000_000,
        maxZipEntries: 10_000,
        maxZipEntryUncompressedBytes: 50_000_000,
        maxZipTotalUncompressedBytes: 200_000_000,
        maxSheets: 256,
        maxCells: 1_000_000,
        maxMerges: 100_000,
        maxMergeExpansionCells: 1_000_000,
        maxSelectorCells: 1_000_000,
        maxOutputRows: 1_000_000,
      },
    };
    const result = await runPrototypeAwareWorker(request, input, output);
    expect(result.ok, JSON.stringify(result)).toBe(true);
    if (!result.ok) return;
    expect(result.warnings).toEqual([]);
    const execution = JSON.parse(
      await readFile(path.join(output, "execution.json"), "utf8"),
    );
    const recipe = JSON.parse(
      await readFile(path.join(output, "normalized-recipe.json"), "utf8"),
    );
    expect(recipe.version).toBe(FEDERAL_DEFENDANTS_GROUPED_RECIPE_V1);
    expect(execution).toMatchObject({
      providerCalls: 0,
      acceptanceAuthority: false,
      trainingEligibility: false,
    });
    expect(execution.tables[0].rows).toHaveLength(486);
    const csvOutput = result.outputs.find((entry) =>
      entry.relativePath.endsWith(".csv"),
    )!;
    expect(
      await readFile(path.join(output, csvOutput.relativePath), "utf8"),
    ).toBe(
      rowsToCsv(execution.tables[0].rows, {
        valueColumn: recipe.table.valuesName,
      }),
    );

    const rowLimitedOutput = path.join(root, "row-limited-output");
    await mkdir(rowLimitedOutput);
    const rowLimited = await runPrototypeAwareWorker(
      {
        ...request,
        requestId: "federal-grouped-row-limit",
        limits: { ...request.limits, maxOutputRows: 1 },
      },
      input,
      rowLimitedOutput,
    );
    expect(rowLimited).toMatchObject({
      ok: false,
      error: { code: "FEDERAL_OUTPUT_ROW_LIMIT" },
    });

    const selectorLimitedOutput = path.join(root, "selector-limited-output");
    await mkdir(selectorLimitedOutput);
    const selectorLimited = await runPrototypeAwareWorker(
      {
        ...request,
        requestId: "federal-grouped-selector-limit",
        limits: { ...request.limits, maxSelectorCells: 1 },
      },
      input,
      selectorLimitedOutput,
    );
    expect(selectorLimited).toMatchObject({
      ok: false,
      error: { code: "FEDERAL_SELECTED_CELL_LIMIT" },
    });

    const declaredInputBytes = request.inputs.reduce(
      (sum, entry) => sum + entry.byteLength,
      0,
    );
    for (const [suffix, maxInputBytes, expectedOk] of [
      ["exact", declaredInputBytes, true],
      ["one-under", declaredInputBytes - 1, false],
    ] as const) {
      const destination = path.join(root, `input-limit-${suffix}`);
      await mkdir(destination);
      const invoke = () =>
        runPrototypeAwareWorker(
          {
            ...request,
            requestId: `federal-grouped-input-${suffix}`,
            limits: { ...request.limits, maxInputBytes },
          },
          input,
          destination,
        );
      if (expectedOk) expect((await invoke()).ok).toBe(true);
      else
        await expect(invoke()).rejects.toMatchObject({
          code: "INPUT_LIMIT_EXCEEDED",
        });
    }

    for (const [suffix, limits, code] of [
      ["files", { maxOutputFiles: 5 }, "OUTPUT_DESCRIPTOR_LIMIT_EXCEEDED"],
      ["bytes", { maxOutputBytes: 512 }, "OUTPUT_LIMIT_EXCEEDED"],
    ] as const) {
      const destination = path.join(root, `output-preflight-${suffix}`);
      await mkdir(destination);
      await expect(
        runPrototypeAwareWorker(
          {
            ...request,
            requestId: `federal-grouped-output-${suffix}`,
            limits: { ...request.limits, ...limits },
          },
          input,
          destination,
        ),
      ).rejects.toMatchObject({ code });
    }

    const outputBytes = result.outputs.reduce(
      (sum, entry) => sum + entry.byteLength,
      0,
    );
    for (const [suffix, maxOutputBytes, expectedOk] of [
      ["exact", outputBytes, true],
      ["one-under", outputBytes - 1, false],
    ] as const) {
      const destination = path.join(root, `output-limit-${suffix}`);
      await mkdir(destination);
      const invoke = () =>
        runPrototypeAwareWorker(
          {
            ...request,
            requestId: `federal-grouped-output-${suffix}`,
            limits: { ...request.limits, maxOutputBytes },
          },
          input,
          destination,
        );
      if (expectedOk) expect((await invoke()).ok).toBe(true);
      else {
        await expect(invoke()).rejects.toMatchObject({
          code: "OUTPUT_LIMIT_EXCEEDED",
        });
        expect(await readdir(destination)).toEqual([]);
      }
    }
  });
});
