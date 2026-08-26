// @vitest-environment node
import { execFile } from "node:child_process";
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
import { PassThrough } from "node:stream";
import { promisify } from "node:util";
import ExcelJS from "exceljs";
import JSZip from "jszip";
import yauzl, { type Entry, type ZipFile } from "yauzl";
import { afterEach, describe, expect, it } from "vitest";
import { parseA1Cell, parseA1Range } from "../src/address.js";
import {
  digestFederalDefendantsCanonical,
  encodeFederalPanelKeySourceValue,
  FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1,
  FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1,
  FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1,
  type FederalDefendantsGroupedSemanticMapV1,
  type FederalTargetProvenance,
} from "../src/catalog/federal-defendants-grouped-recipe-v1.js";
import type { PrototypeWorkerRequest } from "../src/protocol/prototype.js";
import { runPrototypeAwareWorker } from "../src/protocol/prototypeSchema.js";
import {
  preflightXlsxZip,
  preflightXlsxZipArchive,
  type WorkerLimits,
} from "../src/protocol/resourceLimits.js";
import {
  FEDERAL_DEFENDANTS_BOUNDED_EXCLUSION_LEDGER_AUTHORITY_DIGEST,
  FEDERAL_DEFENDANTS_BOUNDED_EXCLUSION_LEDGER_BYTES_DIGEST,
  FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
  FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
  FederalDefendantsBoundedWorkbookError,
  parseBoundedRawXlsxSheetForParity,
  parseFederalDefendantsBoundedRawWorkbook,
  preflightFederalDefendantsWorkbookRoute,
} from "../src/workbook/parseFederalDefendantsBoundedWorkbook.js";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";
import type { ParsedSheet } from "../src/workbook/types.js";

const rawWorkbookPath = path.resolve(
  "fixtures/product-prototype/workbooks/federal-defendants-australia-2023-24-national-source.xlsx",
);
const ordinaryWorkbookPath = path.resolve(
  "fixtures/product-prototype/workbooks/federal-defendants-australia-2024-25-federal-offence-group-source.xlsx",
);
const exclusionLedgerPath = path.resolve(
  "fixtures/product-prototype/federal-defendants-bounded-range-exclusions-v1.json",
);
const execFileAsync = promisify(execFile);
const roots: string[] = [];
afterEach(async () => {
  await Promise.all(
    roots.splice(0).map((root) => rm(root, { recursive: true, force: true })),
  );
});

const limits: WorkerLimits = {
  timeoutMs: 300_000,
  maxInputBytes: 50_000_000,
  maxOutputBytes: 50_000_000,
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
};

const cases = [
  {
    sheet: "Table 1",
    range: "R1C1:R69C15",
    a1Range: "A1:O69",
    target: "R7C2",
    label: "R7C1",
    labelValue: "Females",
    value: 2805,
    cells: 1030,
    nonEmpty: 707,
    numeric: 630,
    rawNumericCells: 646,
    strings: 77,
    merges: 10,
    zeros: 25,
    proofDigest:
      "sha256:ca43a96d9281bf0719b0a7d5162848f4be0e0497da2ad49597083e896c1e58bd",
    styleProofDigest:
      "sha256:76f19057e74ba483a08acace754af27b6df39e3b67a91f51f7a5787b5fcf3472",
    footer: "R69C1",
    footerMerge: "R69C1:R1048576C15",
    excluded: 21,
  },
  {
    sheet: "Table 2",
    range: "R1C1:R64C15",
    a1Range: "A1:O64",
    target: "R7C2",
    label: "R7C1",
    labelValue: "Females",
    value: 2229,
    cells: 949,
    nonEmpty: 661,
    numeric: 588,
    rawNumericCells: 605,
    strings: 73,
    merges: 11,
    zeros: 40,
    proofDigest:
      "sha256:d330ee77ffad2ad0d31320266cb581b091269b7d308867a10c8cdbfc8df1be4f",
    styleProofDigest:
      "sha256:467fd4c21096a7e2b77a6290138297a3b1cb5c0e2cbc60eff851611d1b8c136b",
    footer: "R64C1",
    footerMerge: "R64C1:R64C15",
    excluded: 0,
  },
  {
    sheet: "Table 3",
    range: "R1C1:R86C10",
    a1Range: "A1:J86",
    target: "R7C2",
    label: "R7C1",
    labelValue: "Females",
    value: 613,
    cells: 827,
    nonEmpty: 574,
    numeric: 486,
    rawNumericCells: 507,
    strings: 88,
    merges: 17,
    zeros: 82,
    proofDigest:
      "sha256:01934ab46de0757cb508f38ef9b89fb99cf4addabe03a37225b8826ca7a92645",
    styleProofDigest:
      "sha256:f6e0f9312334217ae1a7c92445d3dd1f2191a11ae718ae3426f08a63651ae9e1",
    footer: "R86C1",
    footerMerge: "R86C1:R86C10",
    excluded: 1_020,
  },
  {
    sheet: "Table 4",
    range: "R1C1:R74C10",
    a1Range: "A1:J74",
    target: "R7C2",
    label: "R7C1",
    labelValue: "032 Non-assaultive sexual offences",
    value: 266,
    cells: 730,
    nonEmpty: 595,
    numeric: 513,
    rawNumericCells: 530,
    strings: 82,
    merges: 15,
    zeros: 48,
    proofDigest:
      "sha256:aadbd084dd38bf1c2c7beb7febad7649620e9e079a21e0d42e1bef7763f20c77",
    styleProofDigest:
      "sha256:e145e6b776aec07fba2a2c2d5343357e8a0c0f251fa6a1fbe2de71e5468a011b",
    footer: "R74C1",
    footerMerge: "R74C1:R74C10",
    excluded: 0,
  },
  {
    sheet: "Table 5",
    range: "R1C1:R56C15",
    a1Range: "A1:O56",
    target: "R7C2",
    label: "R7C1",
    labelValue: "Females",
    value: 297,
    cells: 833,
    nonEmpty: 469,
    numeric: 406,
    rawNumericCells: 430,
    strings: 63,
    merges: 13,
    zeros: 0,
    proofDigest:
      "sha256:95c71177baf8607c995da2b6a6daad25516ff25b93c9867f4c5ed849585e1177",
    styleProofDigest:
      "sha256:863917a96b9bfc047af270ae01f25a7ce1e3e0d2c1074f2ca7d7bcf18b14ebfa",
    footer: "R56C1",
    footerMerge: "R56C1:R56C15",
    excluded: 0,
  },
] as const;

function source(sheet: string, authoritativeRange: string) {
  return {
    version: FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1,
    sourceWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
    executionWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
    physicalSheet: sheet,
    authoritativeRange,
  };
}

function boundedProofDigest(sheet: ParsedSheet): string {
  return digestFederalDefendantsCanonical(
    sheet.cells.map((cell) => ({
      address: cell.address,
      value: cell.value,
      data_type: cell.data_type,
      formula: cell.formula ?? null,
      formatted: cell.formatted ?? null,
      comment: cell.comment ?? null,
      hyperlink: cell.hyperlink ?? null,
    })),
  );
}

function sha256(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

async function rawZipEntries(
  bytes: Buffer,
  wanted: Set<string>,
): Promise<Map<string, Buffer>> {
  const zip = await new Promise<ZipFile>((resolve, reject) => {
    yauzl.fromBuffer(
      bytes,
      { autoClose: false, lazyEntries: true },
      (error, value) =>
        error || !value
          ? reject(error ?? new Error("ZIP open failed"))
          : resolve(value),
    );
  });
  const found = new Map<string, Buffer>();
  try {
    await new Promise<void>((resolve, reject) => {
      zip.once("error", reject);
      zip.once("end", resolve);
      zip.on("entry", (entry: Entry) => {
        if (!wanted.has(entry.fileName)) {
          zip.readEntry();
          return;
        }
        zip.openReadStream(entry, (error, stream) => {
          if (error || !stream) {
            reject(error ?? new Error("ZIP entry read failed"));
            return;
          }
          const chunks: Buffer[] = [];
          stream.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
          stream.once("error", reject);
          stream.once("end", () => {
            found.set(entry.fileName, Buffer.concat(chunks));
            zip.readEntry();
          });
        });
      });
      zip.readEntry();
    });
  } finally {
    zip.close();
  }
  return found;
}

async function mutateXlsxEntry(
  bytes: Buffer,
  entry: string,
  mutate: (value: string) => string,
): Promise<Buffer> {
  const zip = await JSZip.loadAsync(bytes);
  const file = zip.file(entry);
  if (!file) throw new Error(`Missing test entry ${entry}`);
  zip.file(entry, mutate(await file.async("string")));
  return await zip.generateAsync({
    type: "nodebuffer",
    compression: "DEFLATE",
  });
}

function decodeXmlAttribute(value: string): string {
  return value
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

function xmlAttributes(tag: string): Map<string, string> {
  return new Map(
    [...tag.matchAll(/\b([A-Za-z_:][A-Za-z0-9_.:-]*)="([^"]*)"/g)].map(
      (match) => [match[1], decodeXmlAttribute(match[2])],
    ),
  );
}

const builtInDateNumberFormats = new Set([
  14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
  45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58,
]);

function isIndependentDateFormat(
  id: number,
  customFormats: Map<number, string>,
): boolean {
  if (builtInDateNumberFormats.has(id)) return true;
  const custom = customFormats.get(id);
  if (!custom) return false;
  const semantic = custom
    .replace(/"[^"]*"/g, "")
    .replace(/\\./g, "")
    .replace(/\[[^\]]*\]/g, "")
    .replace(/[_*]./g, "")
    .toLowerCase();
  return /[ymdhis]/.test(semantic);
}

function independentNumericDateStyleCensus(
  stylesXml: string,
  worksheetXml: string,
  authorityRange: string,
): {
  numericAddresses: string[];
  dateFormattedNumericAddresses: string[];
  usedStyleIds: number[];
} {
  const customFormats = new Map<number, string>();
  for (const match of stylesXml.matchAll(/<numFmt\b[^>]*\/?\s*>/g)) {
    const attributes = xmlAttributes(match[0]);
    const id = Number(attributes.get("numFmtId"));
    const code = attributes.get("formatCode");
    if (Number.isSafeInteger(id) && code !== undefined)
      customFormats.set(id, code);
  }
  const cellXfs = stylesXml.match(/<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/)?.[1];
  if (!cellXfs) throw new Error("Missing independent cellXfs census source");
  const styleNumberFormats = [...cellXfs.matchAll(/<xf\b[^>]*>/g)].map(
    (match) => Number(xmlAttributes(match[0]).get("numFmtId") ?? "0"),
  );
  const authority = parseA1Range(authorityRange);
  const numericAddresses: string[] = [];
  const dateFormattedNumericAddresses: string[] = [];
  const usedStyleIds = new Set<number>();
  for (const match of worksheetXml.matchAll(
    /<c\b([^>]*)(?:\/>|>([\s\S]*?)<\/c>)/g,
  )) {
    const attributes = xmlAttributes(match[1]);
    const sourceAddress = attributes.get("r");
    if (!sourceAddress) continue;
    const address = parseA1Cell(sourceAddress);
    if (
      address.row > authority.end.row ||
      address.col > authority.end.col ||
      address.row < authority.start.row ||
      address.col < authority.start.col
    )
      continue;
    const type = attributes.get("t");
    if (
      (type !== undefined && type !== "n") ||
      !/<v(?:\s[^>]*)?>/.test(match[2] ?? "")
    )
      continue;
    const styleId = Number(attributes.get("s") ?? "0");
    if (
      !Number.isSafeInteger(styleId) ||
      styleId < 0 ||
      styleNumberFormats[styleId] === undefined
    )
      throw new Error(`Invalid independent style ID at ${sourceAddress}`);
    numericAddresses.push(sourceAddress);
    usedStyleIds.add(styleId);
    if (isIndependentDateFormat(styleNumberFormats[styleId], customFormats))
      dateFormattedNumericAddresses.push(sourceAddress);
  }
  return {
    numericAddresses,
    dateFormattedNumericAddresses,
    usedStyleIds: [...usedStyleIds].sort((left, right) => left - right),
  };
}

function styleProofDigest(sheet: ParsedSheet): string {
  return digestFederalDefendantsCanonical(
    sheet.cells.map((cell) => ({
      address: cell.address,
      style: cell.style ?? null,
      formatted: cell.formatted ?? null,
      comment: cell.comment ?? null,
      hyperlink: cell.hyperlink ?? null,
      merge: cell.merge ?? null,
    })),
  );
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

const profile: FederalTargetProvenance = {
  populationBasis: "finalised-defendants",
  transferPolicy: "as-published",
  entityType: "persons-and-organisations",
  denominator: "published-finalised-defendants",
  rowClassification: "summary-characteristic",
  principalOffenceClassification: "anzsoc-2023",
  classificationTreatment: "native",
  principalSelectionVersion: "published-method",
  sentenceClassificationTreatment: "not-applicable",
  revisionTreatment: "as-published",
  measure: "defendant-count",
  statistic: "count",
  unit: "defendants",
  hierarchy: "leaf",
  totalStatus: "not-total",
  footnoteRefs: [],
  perturbation: true,
};

function workerCanaryMap(testCase: (typeof cases)[number]) {
  const mapSource = source(testCase.sheet, testCase.range);
  const authority = {
    version: FEDERAL_DEFENDANTS_GEOMETRY_AUTHORITY_V1,
    source: mapSource,
    panels: [
      { panelId: "panel", targetSelectors: [{ address: testCase.target }] },
    ],
    bands: [
      {
        id: "row-band",
        panelId: "panel",
        dimensionId: "row-label",
        direction: "W" as const,
        range: `${testCase.label}:${testCase.label}`,
      },
    ],
  };
  const map: FederalDefendantsGroupedSemanticMapV1 = {
    version: FEDERAL_DEFENDANTS_GROUPED_SEMANTIC_MAP_V1,
    source: mapSource,
    geometryAuthority: authority,
    geometryAuthorityDigest: digestFederalDefendantsCanonical(authority),
    logicalTable: {
      id: "bounded-canary",
      name: "bounded canary",
      valuesName: "published value",
      dimensions: [
        { id: "row-label", name: "row label", source: { kind: "cell" } },
        ...provenanceDimensions.map(([id, name, field]) => ({
          id,
          name,
          source: { kind: "provenance" as const, field },
        })),
      ],
    },
    panels: [
      {
        id: "panel",
        order: 1,
        key: `row-label:${encodeFederalPanelKeySourceValue(testCase.labelValue)}`,
        keySource: {
          dimensionId: "row-label",
          selectedAddress: testCase.label,
        },
        name: testCase.labelValue,
        selectors: [{ address: testCase.target }],
      },
    ],
    sourceUniverses: [
      {
        id: "row-universe",
        panelId: "panel",
        dimensionId: "row-label",
        direction: "W",
        authorityBandId: "row-band",
        selectors: [{ address: testCase.label }],
      },
    ],
    bindings: [
      {
        id: "row-binding",
        dimensionId: "row-label",
        direction: "W",
        selectedAddress: testCase.label,
        universeId: "row-universe",
      },
    ],
    vectors: [{ id: "vector", bindingIds: ["row-binding"] }],
    provenanceProfiles: [{ id: "profile", values: profile }],
    targets: [
      {
        address: testCase.target,
        panelId: "panel",
        vectorId: "vector",
        provenanceProfileId: "profile",
      },
    ],
  };
  return map;
}

async function workerRoots() {
  const root = await mkdtemp(path.join(tmpdir(), "federal-bounded-worker-"));
  roots.push(root);
  const input = path.join(root, "input");
  const output = path.join(root, "output");
  await mkdir(input);
  await mkdir(output);
  return { input, output };
}

function descriptor(name: string, relativePath: string, bytes: Buffer) {
  return {
    name,
    relativePath,
    contentDigest: sha256(bytes),
    byteLength: bytes.byteLength,
  };
}

async function runWorkerCanary(testCase: (typeof cases)[number]) {
  const bytes = await readFile(rawWorkbookPath);
  const mapBytes = Buffer.from(
    `${JSON.stringify(workerCanaryMap(testCase))}\n`,
  );
  const root = await workerRoots();
  await writeFile(path.join(root.input, "workbook.xlsx"), bytes);
  await writeFile(path.join(root.input, "semantic-map.json"), mapBytes);
  const request: PrototypeWorkerRequest = {
    protocolVersion: "tidy.worker/v1",
    requestId: `bounded-${testCase.sheet.replace(" ", "-")}`,
    operation: "interpret-semantic-map-v13",
    inputs: [
      descriptor("workbook", "workbook.xlsx", bytes),
      descriptor("semantic-map", "semantic-map.json", mapBytes),
    ],
    parameters: { sheet: testCase.sheet },
    limits: { ...limits, maxOutputFiles: 10, maxWarnings: 10 },
  };
  const result = await runPrototypeAwareWorker(
    request,
    root.input,
    root.output,
  );
  return { result, output: root.output };
}

describe("Federal Defendants bounded raw XLSX parser", () => {
  it("parses all five immutable pathological-workbook sheets directly and deterministically", async () => {
    const bytes = await readFile(rawWorkbookPath);
    const before = sha256(bytes);
    expect(bytes.byteLength).toBe(
      FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
    );
    expect(before).toBe(FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST);
    await expect(
      preflightXlsxZipArchive(bytes, limits),
    ).resolves.toBeUndefined();
    await expect(preflightXlsxZip(bytes, limits)).rejects.toMatchObject({
      code: "MERGE_EXPANSION_LIMIT_EXCEEDED",
    });
    const sheetEntries = new Set([
      "xl/styles.xml",
      ...[2, 3, 4, 5, 6].flatMap((number) => [
        `xl/worksheets/sheet${number}.xml`,
        `xl/worksheets/_rels/sheet${number}.xml.rels`,
      ]),
    ]);
    const rawParts = await rawZipEntries(bytes, sheetEntries);
    expect(rawParts.size).toBe(11);
    const stylesXml = rawParts.get("xl/styles.xml")!.toString("utf8");
    for (const number of [2, 3, 4, 5, 6]) {
      const testCase = cases[number - 2];
      const xml = rawParts
        .get(`xl/worksheets/sheet${number}.xml`)!
        .toString("utf8");
      const rels = rawParts
        .get(`xl/worksheets/_rels/sheet${number}.xml.rels`)!
        .toString("utf8");
      expect(xml.match(/<f(?:\s|>)/g) ?? []).toEqual([]);
      expect(xml.match(/\bt="d"/g) ?? []).toEqual([]);
      const hyperlinkRefs = [
        ...xml.matchAll(/<hyperlink\b[^>]*\bref="([^"]+)"/g),
      ].map((match) => match[1]);
      expect(hyperlinkRefs).toHaveLength(1);
      expect(hyperlinkRefs.every((reference) => !reference.includes(":"))).toBe(
        true,
      );
      expect(rels).not.toContain("/comments");
      const census = independentNumericDateStyleCensus(
        stylesXml,
        xml,
        testCase.a1Range,
      );
      expect(census.numericAddresses).toHaveLength(testCase.rawNumericCells);
      expect(census.usedStyleIds.length).toBeGreaterThan(0);
      expect(census.dateFormattedNumericAddresses).toEqual([]);
    }

    for (const testCase of cases) {
      const args = {
        bytes,
        source: source(testCase.sheet, testCase.range),
        requestedSheet: testCase.sheet,
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        limits,
      };
      const first = await parseFederalDefendantsBoundedRawWorkbook(args);
      const second = await parseFederalDefendantsBoundedRawWorkbook(args);
      expect(second).toEqual(first);
      expect(first.ok).toBe(true);
      if (!first.ok) continue;
      const sheet = first.workbook.sheets[0];
      expect(first.workbook.sheets).toHaveLength(1);
      expect(sheet).toMatchObject({
        name: testCase.sheet,
        usedRange: testCase.range,
        rowCount: parseA1Range(testCase.a1Range).end.row,
        columnCount: parseA1Range(testCase.a1Range).end.col,
        nonEmptyCellCount: testCase.nonEmpty,
      });
      expect(sheet.cells).toHaveLength(testCase.cells);
      expect(sheet.merges).toHaveLength(testCase.merges);
      expect(
        sheet.cells.filter((cell) => cell.data_type === "numeric"),
      ).toHaveLength(testCase.numeric);
      expect(
        sheet.cells.filter((cell) => cell.data_type === "string"),
      ).toHaveLength(testCase.strings);
      expect(
        sheet.cells.filter((cell) => cell.data_type === "date"),
      ).toHaveLength(0);
      expect(sheet.cells.filter((cell) => cell.value === 0)).toHaveLength(
        testCase.zeros,
      );
      expect(sheet.cells.filter((cell) => cell.value === "np")).toHaveLength(0);
      expect(sheet.cells.filter((cell) => cell.formula)).toHaveLength(0);
      expect(sheet.cells.filter((cell) => cell.style)).toHaveLength(
        testCase.cells,
      );
      expect(sheet.cells.filter((cell) => cell.formatted)).toHaveLength(1);
      expect(sheet.cells.filter((cell) => cell.comment)).toHaveLength(0);
      expect(sheet.cells.filter((cell) => cell.hyperlink)).toHaveLength(1);
      expect(boundedProofDigest(sheet)).toBe(testCase.proofDigest);
      expect(styleProofDigest(sheet)).toBe(testCase.styleProofDigest);
      expect(
        sheet.cells.find((cell) => cell.address === testCase.target),
      ).toMatchObject({
        value: testCase.value,
        data_type: "numeric",
      });
      expect(
        sheet.cells.find((cell) => cell.address === testCase.label),
      ).toMatchObject({
        value: testCase.labelValue,
        data_type: "string",
      });
      expect(
        sheet.cells.find((cell) => cell.address === testCase.footer),
      ).toMatchObject({
        value: "© Commonwealth of Australia",
        formatted: "© Commonwealth of Australia",
        hyperlink:
          "https://www.abs.gov.au/website-privacy-copyright-and-disclaimer",
        merge: {
          parent: testCase.footer,
          range: testCase.footerMerge,
          role: "parent",
        },
      });
      expect(
        sheet.cells.every(
          (cell) => cell.row <= sheet.rowCount && cell.col <= sheet.columnCount,
        ),
      ).toBe(true);
      expect(
        sheet.merges.every((merge) => {
          const parsed = /^R(\d+)C(\d+):R(\d+)C(\d+)$/.exec(merge.range)!;
          return (
            Number(parsed[3]) <= sheet.rowCount &&
            Number(parsed[4]) <= sheet.columnCount
          );
        }),
      ).toBe(true);
    }
    expect(sha256(bytes)).toBe(before);
  });

  it("matches historical dates, formulas, shared formulas, comments, inline strings, hyperlinks, and cross-boundary merges", async () => {
    const workbook = new ExcelJS.Workbook();
    workbook.properties.date1904 = true;
    const worksheet = workbook.addWorksheet("Data");
    worksheet.getCell("A1").value = "inline source";
    worksheet.getCell("B1").value = new Date("2020-01-02T00:00:00.000Z");
    worksheet.getCell("C1").value = {
      formula: "DATE(2020,1,3)",
      result: new Date("2020-01-03T00:00:00.000Z"),
    };
    worksheet.getCell("A2").value = 1;
    worksheet.getCell("B2").value = {
      formula: "A2+1",
      result: 2,
      shareType: "shared",
      ref: "B2:B3",
    } as ExcelJS.CellFormulaValue;
    worksheet.getCell("B3").value = {
      sharedFormula: "B2",
      result: 3,
    };
    worksheet.getCell("C2").value = {
      formula: '"2020-01-03"',
      result: "2020-01-03",
    };
    worksheet.getCell("D2").value = {
      formula: "1-1",
      result: 0,
    };
    worksheet.getCell("E2").value = {
      formula: "1=0",
      result: false,
    };
    worksheet.getCell("D1").value = true;
    worksheet.getCell("E1").value = { error: "#N/A" };
    worksheet.getCell("A1").note = {
      texts: [
        { text: "rich ", font: { bold: true } },
        { text: "comment", font: { italic: true } },
      ],
    };
    worksheet.getCell("G1").value = {
      text: "example",
      hyperlink: "https://example.test/path",
    };
    worksheet.getCell("G2").value = {
      text: "internal",
      hyperlink: "#Data!A1",
    };
    worksheet.getCell("F3").value = "cross merge 1";
    worksheet.getCell("F4").value = "cross merge 2";
    worksheet.getCell("F5").value = "cross merge 3";
    worksheet.mergeCells("F3:H3");
    worksheet.mergeCells("F4:H4");
    worksheet.mergeCells("F5:H5");
    const bytes = Buffer.from(
      await workbook.xlsx.writeBuffer({ useSharedStrings: false }),
    );
    const direct = await parseBoundedRawXlsxSheetForParity({
      bytes,
      physicalSheet: "Data",
      authoritativeRange: "R1C1:R5C7",
      limits,
    });
    const full = await parseWorkbook(bytes);
    expect(full.ok).toBe(true);
    if (!full.ok) return;
    const historical = full.workbook.sheets.find(
      (sheet) => sheet.name === "Data",
    )!;
    expect(
      direct.cells
        .filter((cell) => cell.address !== "R2C4" && cell.address !== "R2C5")
        .map((cell) => ({ ...cell, comment: null })),
    ).toEqual(
      historical.cells.filter((cell) => cell.row <= 5 && cell.col <= 7),
    );
    // parseWorkbook currently drops XLSX comments and falsy-result formula
    // cells from its worksheet model. The bounded parser intentionally retains
    // those exact source facts while matching historical formatted=null.
    expect(
      historical.cells.some(
        (cell) => cell.address === "R2C4" || cell.address === "R2C5",
      ),
    ).toBe(false);
    // parseWorkbook currently drops XLSX comments from its worksheet model;
    // the bounded parser intentionally preserves the source comment instead.
    expect(direct.cells.find((cell) => cell.address === "R1C1")?.comment).toBe(
      "rich comment",
    );
    expect(direct.merges).toEqual([]);
    expect(direct.cells.find((cell) => cell.address === "R1C2")).toMatchObject({
      value: "2020-01-02T00:00:00.000Z",
      data_type: "date",
    });
    expect(direct.cells.find((cell) => cell.address === "R3C2")).toMatchObject({
      formula: "B2",
    });
    expect(direct.cells.find((cell) => cell.address === "R2C3")).toMatchObject({
      value: "2020-01-03",
      data_type: "string",
      formula: '"2020-01-03"',
      formatted: "2020-01-03",
    });
    expect(direct.cells.find((cell) => cell.address === "R2C4")).toMatchObject({
      value: 0,
      data_type: "numeric",
      formula: "1-1",
      formatted: null,
    });
    expect(direct.cells.find((cell) => cell.address === "R2C5")).toMatchObject({
      value: false,
      data_type: "boolean",
      formula: "1=0",
      formatted: null,
    });
    expect(direct.cells.find((cell) => cell.address === "R3C6")?.merge).toEqual(
      {
        parent: "R3C6",
        range: "R3C6:R3C8",
        role: "parent",
      },
    );
    expect(direct.cells.find((cell) => cell.address === "R3C7")?.merge).toEqual(
      {
        parent: "R3C6",
        range: "R3C6:R3C8",
        role: "child",
      },
    );
    await expect(
      parseBoundedRawXlsxSheetForParity({
        bytes,
        physicalSheet: "Data",
        authoritativeRange: "R1C1:R5C7",
        limits: { ...limits, maxCells: 34 },
      }),
    ).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_TEST_AUTHORITY_LIMIT_EXCEEDED",
      stage: "limit",
    });
    await expect(
      parseBoundedRawXlsxSheetForParity({
        bytes,
        physicalSheet: "Data",
        authoritativeRange: "R1C1:R5C7",
        limits: { ...limits, maxMergeExpansionCells: 5 },
      }),
    ).rejects.toMatchObject({
      code: "MERGE_EXPANSION_LIMIT_EXCEEDED",
      stage: "limit",
    });
  });

  it("accepts a valid inline-only package with no sharedStrings part", async () => {
    const stream = new PassThrough();
    const chunks: Buffer[] = [];
    stream.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
    const workbook = new ExcelJS.stream.xlsx.WorkbookWriter({
      stream,
      useSharedStrings: false,
    });
    const worksheet = workbook.addWorksheet("Inline");
    worksheet.addRow(["inline only", 7]).commit();
    await workbook.commit();
    const bytes = Buffer.concat(chunks);
    expect(
      await rawZipEntries(bytes, new Set(["xl/sharedStrings.xml"])),
    ).toEqual(new Map());
    const direct = await parseBoundedRawXlsxSheetForParity({
      bytes,
      physicalSheet: "Inline",
      authoritativeRange: "R1C1:R1C2",
      limits,
    });
    const full = await parseWorkbook(bytes);
    expect(full.ok).toBe(true);
    if (!full.ok) return;
    expect(direct.cells).toEqual(full.workbook.sheets[0].cells);
    expect(direct.cells.map((cell) => cell.value)).toEqual(["inline only", 7]);
  });

  it("preserves an accepted exact multi-cell hyperlink range under deterministic bounds", async () => {
    const workbook = new ExcelJS.Workbook();
    const worksheet = workbook.addWorksheet("Data");
    worksheet.getCell("A1").value = {
      text: "range source",
      hyperlink: "https://example.test/range",
    };
    worksheet.getCell("B2").value = 7;
    const original = Buffer.from(await workbook.xlsx.writeBuffer());
    const ranged = await mutateXlsxEntry(
      original,
      "xl/worksheets/sheet1.xml",
      (xml) => xml.replace('ref="A1"', 'ref="A1:B2"'),
    );
    const raw = await rawZipEntries(
      ranged,
      new Set(["xl/worksheets/sheet1.xml"]),
    );
    const worksheetXml = raw.get("xl/worksheets/sheet1.xml")!.toString("utf8");
    expect(
      [...worksheetXml.matchAll(/<hyperlink\b[^>]*\bref="([^"]+)"/g)].map(
        (match) => match[1],
      ),
    ).toEqual(["A1:B2"]);

    const parse = (maxCells: number) =>
      parseBoundedRawXlsxSheetForParity({
        bytes: ranged,
        physicalSheet: "Data",
        authoritativeRange: "R1C1:R2C2",
        limits: { ...limits, maxCells },
      });
    const first = await parse(4);
    const second = await parse(4);
    expect(second).toEqual(first);
    expect(
      first.cells.map((cell) => ({
        address: cell.address,
        value: cell.value,
        data_type: cell.data_type,
        formatted: cell.formatted,
        hyperlink: cell.hyperlink,
      })),
    ).toEqual([
      {
        address: "R1C1",
        value: "range source",
        data_type: "string",
        formatted: "range source",
        hyperlink: "https://example.test/range",
      },
      {
        address: "R1C2",
        value: null,
        data_type: "blank",
        formatted: null,
        hyperlink: "https://example.test/range",
      },
      {
        address: "R2C1",
        value: null,
        data_type: "blank",
        formatted: null,
        hyperlink: "https://example.test/range",
      },
      {
        address: "R2C2",
        value: 7,
        data_type: "numeric",
        formatted: null,
        hyperlink: "https://example.test/range",
      },
    ]);
    await expect(parse(3)).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_TEST_AUTHORITY_LIMIT_EXCEEDED",
      stage: "limit",
    });

    // Intentional source-preserving divergence: historical ExcelJS indexes the
    // literal A1:B2 ref and fails to attach it to any individual cell.
    const historical = await parseWorkbook(ranged);
    expect(historical.ok).toBe(true);
    if (historical.ok)
      expect(
        historical.workbook.sheets[0].cells.filter((cell) => cell.hyperlink),
      ).toEqual([]);
  });

  it("rejects hostile OOXML content types, declarations, relationships, cells, and hyperlink expansion", async () => {
    const workbook = new ExcelJS.Workbook();
    const worksheet = workbook.addWorksheet("Data");
    worksheet.getCell("A1").value = {
      text: "link",
      hyperlink: "https://example.test",
    };
    worksheet.getCell("B1").value = 1;
    const original = Buffer.from(await workbook.xlsx.writeBuffer());
    const parse = (bytes: Buffer, overrides: Partial<WorkerLimits> = {}) =>
      parseBoundedRawXlsxSheetForParity({
        bytes,
        physicalSheet: "Data",
        authoritativeRange: "R1C1:R10C10",
        limits: { ...limits, ...overrides },
      });

    const badContentType = await mutateXlsxEntry(
      original,
      "[Content_Types].xml",
      (xml) =>
        xml.replace(
          "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
          "application/octet-stream",
        ),
    );
    await expect(parse(badContentType)).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_CONTENT_TYPE_INVALID",
    });

    const traversal = await mutateXlsxEntry(
      original,
      "xl/_rels/workbook.xml.rels",
      (xml) =>
        xml.replace(
          "worksheets/sheet1.xml",
          "worksheets/../worksheets/sheet1.xml",
        ),
    );
    await expect(parse(traversal)).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_RELATIONSHIP_PATH_UNSAFE",
    });

    const doctype = await mutateXlsxEntry(original, "xl/workbook.xml", (xml) =>
      xml.replace("?>", "?><!DOCTYPE workbook [<!ENTITY x 'x'>]>"),
    );
    await expect(parse(doctype)).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_XML_DECLARATION_INVALID",
    });

    const stylesDoctype = await mutateXlsxEntry(
      original,
      "xl/styles.xml",
      (xml) =>
        xml.replace(
          "?>",
          "?><!DOCTYPE styleSheet [<!ENTITY styleEntity 'forbidden'>]>",
        ),
    );
    await expect(parse(stylesDoctype)).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_XML_DECLARATION_INVALID",
    });

    const duplicateCell = await mutateXlsxEntry(
      original,
      "xl/worksheets/sheet1.xml",
      (xml) => xml.replace("</row>", '<c r="A1"><v>9</v></c></row>'),
    );
    await expect(parse(duplicateCell)).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_DUPLICATE_CELL",
    });

    const hyperlinkExpansion = await mutateXlsxEntry(
      original,
      "xl/worksheets/sheet1.xml",
      (xml) => {
        const tag = xml.match(/<hyperlink\s[^>]+\/>/)?.[0];
        if (!tag) throw new Error("Missing hyperlink fixture");
        return xml.replace(
          tag,
          `${tag.replace('ref="A1"', 'ref="A1:J6"')}${tag.replace('ref="A1"', 'ref="A5:J10"')}`,
        );
      },
    );
    await expect(
      parse(hyperlinkExpansion, { maxCells: 100 }),
    ).rejects.toMatchObject({
      code: "CELL_LIMIT_EXCEEDED",
      stage: "limit",
    });

    const invalidTargetMode = await mutateXlsxEntry(
      original,
      "xl/worksheets/_rels/sheet1.xml.rels",
      (xml) => xml.replace('TargetMode="External"', 'TargetMode="Internal"'),
    );
    await expect(parse(invalidTargetMode)).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_HYPERLINK_INVALID",
    });
  });

  it("matches the historical full parser byte-for-byte on an ordinary bounded sheet", async () => {
    const bytes = await readFile(ordinaryWorkbookPath);
    const direct = await parseBoundedRawXlsxSheetForParity({
      bytes,
      physicalSheet: "Table 7",
      authoritativeRange: "R1C1:R70C10",
      limits,
    });
    const full = await parseWorkbook(bytes);
    expect(full.ok).toBe(true);
    if (!full.ok) return;
    const historical = full.workbook.sheets.find(
      (sheet) => sheet.name === "Table 7",
    )!;
    expect(direct.cells).toEqual(
      historical.cells.filter((cell) => cell.row <= 70 && cell.col <= 10),
    );
    expect(direct.merges).toEqual(
      historical.merges.filter((merge) => {
        const parsed = /^R(\d+)C(\d+):R(\d+)C(\d+)$/.exec(merge.range)!;
        return Number(parsed[3]) <= 70 && Number(parsed[4]) <= 10;
      }),
    );
    expect(direct.nonEmptyCellCount).toBe(566);
  });

  it("fails closed on every source-context and custody mismatch before bounded parsing", async () => {
    for (const testCase of cases) {
      expect(
        preflightFederalDefendantsWorkbookRoute({
          source: source(testCase.sheet, testCase.range),
          requestedSheet: testCase.sheet,
          declaredWorkbookDigest:
            FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
          declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        }),
      ).toMatchObject({ ok: true, bounded: true });
    }
    const exact = source("Table 1", "R1C1:R69C15");
    const failures = [
      {
        source: { ...exact, physicalSheet: "Table 2" },
        code: "FEDERAL_BOUNDED_WORKBOOK_ROUTE_MISMATCH",
      },
      {
        source: { ...exact, authoritativeRange: "R1C1:R70C15" },
        code: "FEDERAL_BOUNDED_WORKBOOK_ROUTE_MISMATCH",
      },
      {
        source: { ...exact, authoritativeRange: "R1C1:R68C15" },
        code: "FEDERAL_BOUNDED_WORKBOOK_ROUTE_MISMATCH",
      },
      {
        source: { ...exact, authoritativeRange: "R1C1:R69C16" },
        code: "FEDERAL_BOUNDED_WORKBOOK_ROUTE_MISMATCH",
      },
    ];
    for (const failure of failures)
      expect(
        preflightFederalDefendantsWorkbookRoute({
          source: failure.source,
          requestedSheet: failure.source.physicalSheet,
          declaredWorkbookDigest:
            FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
          declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        }),
      ).toMatchObject({ ok: false, code: failure.code });
    expect(
      preflightFederalDefendantsWorkbookRoute({
        source: exact,
        requestedSheet: "Table 3",
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
      }),
    ).toMatchObject({ ok: false, code: "FEDERAL_SOURCE_CONTEXT_MISMATCH" });
    expect(
      preflightFederalDefendantsWorkbookRoute({
        source: exact,
        requestedSheet: "Table 1",
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes:
          FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES + 1,
      }),
    ).toMatchObject({
      ok: false,
      code: "FEDERAL_BOUNDED_WORKBOOK_LENGTH_MISMATCH",
    });
    expect(
      preflightFederalDefendantsWorkbookRoute({
        source: {
          ...exact,
          executionWorkbookDigest: `sha256:${"0".repeat(64)}`,
        },
        requestedSheet: "Table 1",
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
      }),
    ).toMatchObject({ ok: false, code: "FEDERAL_SOURCE_CONTEXT_MISMATCH" });
    expect(
      preflightFederalDefendantsWorkbookRoute({
        source: exact,
        requestedSheet: "Table 1",
        declaredWorkbookDigest: `sha256:${"0".repeat(64)}`,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
      }),
    ).toMatchObject({ ok: false, code: "FEDERAL_SOURCE_CONTEXT_MISMATCH" });
  });

  it("leaves non-pathological Federal sources on the historical full-parser route", async () => {
    const bytes = await readFile(ordinaryWorkbookPath);
    const digest = sha256(bytes);
    expect(
      preflightFederalDefendantsWorkbookRoute({
        source: {
          version: FEDERAL_DEFENDANTS_SOURCE_CONTEXT_V1,
          sourceWorkbookDigest: digest,
          executionWorkbookDigest: digest,
          physicalSheet: "Table 7",
          authoritativeRange: "R1C1:R70C10",
        },
        requestedSheet: "Table 7",
        declaredWorkbookDigest: digest,
        declaredWorkbookBytes: bytes.byteLength,
      }),
    ).toEqual({ ok: true, bounded: false });
  });

  it("rejects an invalid bounded route before attempting to read workbook bytes", async () => {
    const map = workerCanaryMap(cases[0]);
    const invalidSource = {
      ...map.source,
      authoritativeRange: "R1C1:R70C15",
    };
    map.source = invalidSource;
    map.geometryAuthority = {
      ...map.geometryAuthority,
      source: invalidSource,
    };
    map.geometryAuthorityDigest = digestFederalDefendantsCanonical(
      map.geometryAuthority,
    );
    const mapBytes = Buffer.from(`${JSON.stringify(map)}\n`);
    const root = await workerRoots();
    await writeFile(path.join(root.input, "semantic-map.json"), mapBytes);
    const request: PrototypeWorkerRequest = {
      protocolVersion: "tidy.worker/v1",
      requestId: "bounded-pre-read-rejection",
      operation: "interpret-semantic-map-v13",
      inputs: [
        {
          name: "workbook",
          relativePath: "deliberately-missing.xlsx",
          contentDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
          byteLength: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        },
        descriptor("semantic-map", "semantic-map.json", mapBytes),
      ],
      parameters: { sheet: "Table 1" },
      limits: { ...limits, maxOutputFiles: 10, maxWarnings: 10 },
    };
    const result = await runPrototypeAwareWorker(
      request,
      root.input,
      root.output,
    );
    expect(result).toMatchObject({
      ok: false,
      error: {
        code: "FEDERAL_BOUNDED_WORKBOOK_ROUTE_MISMATCH",
        stage: "semantic-map",
      },
    });
    expect(await readdir(root.output)).toEqual([]);
  });

  it("rejects mutated/malformed bytes and bounded resource under-runs atomically", async () => {
    const bytes = await readFile(rawWorkbookPath);
    const exactSource = source("Table 1", "R1C1:R69C15");
    const mutated = Buffer.from(bytes);
    mutated[mutated.length - 8] ^= 1;
    await expect(
      parseFederalDefendantsBoundedRawWorkbook({
        bytes: mutated,
        source: exactSource,
        requestedSheet: "Table 1",
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        limits,
      }),
    ).rejects.toMatchObject({
      code: "FEDERAL_BOUNDED_WORKBOOK_DIGEST_MISMATCH",
      stage: "source",
    });
    await expect(
      parseFederalDefendantsBoundedRawWorkbook({
        bytes,
        source: exactSource,
        requestedSheet: "Table 1",
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        limits: { ...limits, maxCells: 1029 },
      }),
    ).rejects.toMatchObject({ code: "CELL_LIMIT_EXCEEDED", stage: "limit" });
    await expect(
      parseFederalDefendantsBoundedRawWorkbook({
        bytes,
        source: exactSource,
        requestedSheet: "Table 1",
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        limits: { ...limits, maxMerges: 9 },
      }),
    ).rejects.toMatchObject({ code: "MERGE_LIMIT_EXCEEDED", stage: "limit" });
    await expect(
      parseFederalDefendantsBoundedRawWorkbook({
        bytes,
        source: exactSource,
        requestedSheet: "Table 1",
        declaredWorkbookDigest: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
        declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        limits: { ...limits, maxMergeExpansionCells: 149 },
      }),
    ).rejects.toMatchObject({
      code: "MERGE_EXPANSION_LIMIT_EXCEEDED",
      stage: "limit",
    });
    await expect(
      parseBoundedRawXlsxSheetForParity({
        bytes: Buffer.from("not a zip"),
        physicalSheet: "Data",
        authoritativeRange: "R1C1:R1C1",
        limits,
      }),
    ).rejects.toThrow();
  });

  it("uses the bounded parser in the real provider-free worker for all five sheets", async () => {
    for (const testCase of cases) {
      const { result, output } = await runWorkerCanary(testCase);
      expect(result).toMatchObject({ ok: true, warnings: [] });
      if (!result.ok) continue;
      expect(result.outputs).toHaveLength(6);
      expect(await readdir(output)).toEqual([
        "execution.json",
        "geometry.json",
        "normalized-recipe.json",
        "selectors.json",
        "semantic-map.json",
        "tables",
      ]);
      expect(await readdir(path.join(output, "tables"))).toEqual([
        "bounded%20canary.csv",
      ]);
      const recipe = JSON.parse(
        await readFile(path.join(output, "normalized-recipe.json"), "utf8"),
      );
      const execution = JSON.parse(
        await readFile(path.join(output, "execution.json"), "utf8"),
      );
      const geometry = JSON.parse(
        await readFile(path.join(output, "geometry.json"), "utf8"),
      );
      expect(geometry.boundedSheetProof).toMatchObject({
        sheet: testCase.sheet,
        authoritativeRange: testCase.range,
        cellCount: testCase.cells,
        nonEmptyCellCount: testCase.nonEmpty,
        digest: testCase.proofDigest,
      });
      expect(geometry.formulaProof).toMatchObject({ count: 0, addresses: [] });
      expect(geometry.targetManifest).toMatchObject({
        count: 1,
        markerCount: 0,
        zeroCount: 0,
      });
      expect(recipe.source).toEqual(source(testCase.sheet, testCase.range));
      expect(execution.source).toEqual(source(testCase.sheet, testCase.range));
      expect(execution).toMatchObject({
        providerCalls: 0,
        acceptanceAuthority: false,
        trainingEligibility: false,
        warnings: [],
      });
      expect(execution.tables[0].rows).toHaveLength(1);
      expect(execution.tables[0].rows[0]).toMatchObject({
        "row label": testCase.labelValue,
        "published value": testCase.value,
        "published value numeric": testCase.value,
        "published value status": "observed",
      });
    }
  });

  it("parses all five exact raw routes under a constrained 192 MiB heap", async () => {
    const script = `
      import { readFile } from "node:fs/promises";
      import {
        FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES as byteLength,
        FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST as digest,
        parseFederalDefendantsBoundedRawWorkbook,
      } from "./apps/domain-worker/src/workbook/parseFederalDefendantsBoundedWorkbook.ts";
      const bytes = await readFile(${JSON.stringify(rawWorkbookPath)});
      const limits = ${JSON.stringify(limits)};
      const results = [];
      for (const [physicalSheet, authoritativeRange] of [
        ["Table 1", "R1C1:R69C15"],
        ["Table 2", "R1C1:R64C15"],
        ["Table 3", "R1C1:R86C10"],
        ["Table 4", "R1C1:R74C10"],
        ["Table 5", "R1C1:R56C15"],
      ]) {
        const parsed = await parseFederalDefendantsBoundedRawWorkbook({
          bytes,
          source: {
            version: "federal-defendants-source-context/v1",
            sourceWorkbookDigest: digest,
            executionWorkbookDigest: digest,
            physicalSheet,
            authoritativeRange,
          },
          requestedSheet: physicalSheet,
          declaredWorkbookDigest: digest,
          declaredWorkbookBytes: byteLength,
          limits,
        });
        if (!parsed.ok) throw new Error("bounded parse failed");
        results.push({
          sheet: parsed.workbook.sheets[0].name,
          cells: parsed.workbook.sheets[0].cells.length,
        });
      }
      console.log(JSON.stringify(results));
    `;
    const { stdout, stderr } = await execFileAsync(
      process.execPath,
      [
        "--max-old-space-size=192",
        "--import",
        "tsx",
        "--input-type=module",
        "--eval",
        script,
      ],
      {
        cwd: path.resolve("."),
        env: { ...process.env, NODE_OPTIONS: "" },
        timeout: 120_000,
        maxBuffer: 1_000_000,
      },
    );
    expect(stderr).toBe("");
    expect(JSON.parse(stdout)).toEqual([
      { sheet: "Table 1", cells: 1030 },
      { sheet: "Table 2", cells: 949 },
      { sheet: "Table 3", cells: 827 },
      { sheet: "Table 4", cells: 730 },
      { sheet: "Table 5", cells: 833 },
    ]);
  });

  it("independently aligns immutable parser routes with the 21/1020 exclusion ledger", async () => {
    const ledgerBytes = await readFile(exclusionLedgerPath);
    expect(sha256(ledgerBytes)).toBe(
      FEDERAL_DEFENDANTS_BOUNDED_EXCLUSION_LEDGER_BYTES_DIGEST,
    );
    const ledger = JSON.parse(ledgerBytes.toString("utf8")) as {
      boundedSheetCount: number;
      excludedNonblankCellCount: number;
      ledgerDigest: string;
      sheets: Array<{
        sourceDigest: string;
        physicalSheetName: string;
        authoritativeRange: string;
        boundedSemanticCellCount: number;
        excludedNonblankCellCount: number;
        excludedNonblankCells: Array<{ address: string }>;
      }>;
    };
    expect(ledger).toMatchObject({
      boundedSheetCount: 2,
      excludedNonblankCellCount: 1041,
    });
    expect(ledger.ledgerDigest).toBe(
      FEDERAL_DEFENDANTS_BOUNDED_EXCLUSION_LEDGER_AUTHORITY_DIGEST,
    );
    expect(
      ledger.sheets.map((entry) => ({
        sheet: entry.physicalSheetName,
        range: entry.authoritativeRange,
        bounded: entry.boundedSemanticCellCount,
        excluded: entry.excludedNonblankCellCount,
      })),
    ).toEqual([
      { sheet: "Table 1", range: "A1:O69", bounded: 707, excluded: 21 },
      { sheet: "Table 3", range: "A1:J86", bounded: 574, excluded: 1020 },
    ]);
    for (const entry of ledger.sheets) {
      expect(entry.sourceDigest).toBe(
        FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
      );
      const authority = parseA1Range(entry.authoritativeRange);
      expect(entry.excludedNonblankCells).toHaveLength(
        entry.excludedNonblankCellCount,
      );
      expect(
        entry.excludedNonblankCells.every(({ address }) => {
          const cell = parseA1Cell(address);
          return cell.row > authority.end.row || cell.col > authority.end.col;
        }),
      ).toBe(true);
      const testCase = cases.find(
        (candidate) => candidate.sheet === entry.physicalSheetName,
      )!;
      expect(entry.physicalSheetName).toBe(testCase.sheet);
      expect(entry.authoritativeRange).toBe(testCase.a1Range);
      expect(entry.boundedSemanticCellCount).toBe(testCase.nonEmpty);
      expect(entry.excludedNonblankCellCount).toBe(testCase.excluded);
      expect(
        preflightFederalDefendantsWorkbookRoute({
          source: source(testCase.sheet, testCase.range),
          requestedSheet: testCase.sheet,
          declaredWorkbookDigest:
            FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST,
          declaredWorkbookBytes: FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES,
        }),
      ).toMatchObject({
        ok: true,
        bounded: true,
        route: { excludedNonblankCellCount: testCase.excluded },
      });
    }
  });
});
