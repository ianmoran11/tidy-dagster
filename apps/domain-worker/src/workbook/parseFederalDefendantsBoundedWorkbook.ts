import { createHash } from "node:crypto";
import path from "node:path";
import { Readable } from "node:stream";
import { TextDecoder } from "node:util";
import { SaxesParser, type SaxesTagPlain } from "saxes";
import StylesXform from "exceljs/lib/xlsx/xform/style/styles-xform.js";
import excelUtils from "exceljs/lib/utils/utils.js";
import yauzl, { type Entry, type ZipFile } from "yauzl";
import {
  formatCell,
  formatRange,
  parseA1Cell,
  parseA1Range,
  parseCell,
  parseRange,
  type CellAddress,
  type CellRange,
} from "../address.js";
import type { FederalDefendantsSourceContext } from "../catalog/federal-defendants-grouped-recipe-v1.js";
import {
  LimitViolation,
  preflightXlsxZipArchive,
  type WorkerLimits,
} from "../protocol/resourceLimits.js";
import type {
  CellMergeSummary,
  CellStyleSummary,
  ParsedMergeRange,
  ParsedSheet,
  TidyCell,
  WorkbookParseResult,
} from "./types.js";

export const FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST =
  "sha256:75ea565770a4234b1e67a187e2d277708038bcc8a04263a19ab646e339d196f0" as const;
export const FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES = 212_799;
export const FEDERAL_DEFENDANTS_BOUNDED_EXCLUSION_LEDGER_BYTES_DIGEST =
  "sha256:d6e839b6866874df6e134b82420b5a68ce6e6622be7daee6f4402025c372dede" as const;
export const FEDERAL_DEFENDANTS_BOUNDED_EXCLUSION_LEDGER_AUTHORITY_DIGEST =
  "sha256:10fd3b283781d963724ad80f61ab39aafb41d0191ac9d0f99f0d58c95c6e243e" as const;

const CONTENT_TYPES_XML = "[Content_Types].xml";
const WORKBOOK_XML = "xl/workbook.xml";
const WORKBOOK_RELS_XML = "xl/_rels/workbook.xml.rels";
const STYLES_XML = "xl/styles.xml";
const SHARED_STRINGS_XML = "xl/sharedStrings.xml";
const TRANSITIONAL_RELATIONSHIP_BASE =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships/";
const STRICT_RELATIONSHIP_BASE =
  "http://purl.oclc.org/ooxml/officeDocument/relationships/";
const WORKSHEET_RELATIONSHIP_TYPES = new Set([
  `${TRANSITIONAL_RELATIONSHIP_BASE}worksheet`,
  `${STRICT_RELATIONSHIP_BASE}worksheet`,
]);
const HYPERLINK_RELATIONSHIP_TYPES = new Set([
  `${TRANSITIONAL_RELATIONSHIP_BASE}hyperlink`,
  `${STRICT_RELATIONSHIP_BASE}hyperlink`,
]);
const COMMENTS_RELATIONSHIP_TYPES = new Set([
  `${TRANSITIONAL_RELATIONSHIP_BASE}comments`,
  `${STRICT_RELATIONSHIP_BASE}comments`,
]);
const WORKSHEET_CONTENT_TYPES = new Set([
  "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
]);
const WORKBOOK_CONTENT_TYPES = new Set([
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
  "application/vnd.ms-excel.sheet.main+xml",
]);
const STYLES_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml";
const SHARED_STRINGS_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml";
const COMMENTS_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml";
const MAX_BOUNDED_XML_CELLS = 100_000;
const MAX_BOUNDED_XML_MERGES = 10_000;
const MAX_TEST_AUTHORITY_CELLS = 10_000;

const routes = [
  {
    physicalSheet: "Table 1",
    authoritativeRange: "R1C1:R69C15",
    a1Range: "A1:O69",
    expectedWorksheetEntry: "xl/worksheets/sheet2.xml",
    excludedNonblankCellCount: 21,
  },
  {
    physicalSheet: "Table 2",
    authoritativeRange: "R1C1:R64C15",
    a1Range: "A1:O64",
    expectedWorksheetEntry: "xl/worksheets/sheet3.xml",
    excludedNonblankCellCount: 0,
  },
  {
    physicalSheet: "Table 3",
    authoritativeRange: "R1C1:R86C10",
    a1Range: "A1:J86",
    expectedWorksheetEntry: "xl/worksheets/sheet4.xml",
    excludedNonblankCellCount: 1_020,
  },
  {
    physicalSheet: "Table 4",
    authoritativeRange: "R1C1:R74C10",
    a1Range: "A1:J74",
    expectedWorksheetEntry: "xl/worksheets/sheet5.xml",
    excludedNonblankCellCount: 0,
  },
  {
    physicalSheet: "Table 5",
    authoritativeRange: "R1C1:R56C15",
    a1Range: "A1:O56",
    expectedWorksheetEntry: "xl/worksheets/sheet6.xml",
    excludedNonblankCellCount: 0,
  },
] as const;

export type FederalDefendantsBoundedRoute = (typeof routes)[number];

export type FederalDefendantsWorkbookRouteResult =
  | { ok: true; bounded: false }
  | { ok: true; bounded: true; route: FederalDefendantsBoundedRoute }
  | { ok: false; code: string; stage: "source"; message: string };

export class FederalDefendantsBoundedWorkbookError extends Error {
  constructor(
    readonly code: string,
    readonly stage: "source" | "parse" | "limit",
    message = code,
  ) {
    super(message);
    this.name = "FederalDefendantsBoundedWorkbookError";
  }
}

/**
 * Preflight a Federal workbook manifest before reading or parsing workbook
 * bytes. A source-context mismatch for any Federal grouped map is fatal. The
 * bounded route is available only to the one immutable pathological workbook
 * and its five committed sheet/range authorities.
 */
export function preflightFederalDefendantsWorkbookRoute(input: {
  source: FederalDefendantsSourceContext;
  requestedSheet: string;
  declaredWorkbookDigest: string;
  declaredWorkbookBytes: number;
}): FederalDefendantsWorkbookRouteResult {
  const { source } = input;
  if (
    source.physicalSheet !== input.requestedSheet ||
    source.sourceWorkbookDigest !== input.declaredWorkbookDigest ||
    source.executionWorkbookDigest !== input.declaredWorkbookDigest ||
    source.sourceWorkbookDigest !== source.executionWorkbookDigest
  )
    return {
      ok: false,
      code: "FEDERAL_SOURCE_CONTEXT_MISMATCH",
      stage: "source",
      message:
        "Federal source and execution context must match the exact declared raw workbook and requested sheet.",
    };

  if (
    source.sourceWorkbookDigest !==
    FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST
  )
    return { ok: true, bounded: false };

  if (
    input.declaredWorkbookBytes !==
    FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_BYTES
  )
    return {
      ok: false,
      code: "FEDERAL_BOUNDED_WORKBOOK_LENGTH_MISMATCH",
      stage: "source",
      message: "The bounded Federal workbook byte length is not custodied.",
    };

  const route = routes.find(
    (candidate) =>
      candidate.physicalSheet === source.physicalSheet &&
      candidate.authoritativeRange === source.authoritativeRange,
  );
  if (!route)
    return {
      ok: false,
      code: "FEDERAL_BOUNDED_WORKBOOK_ROUTE_MISMATCH",
      stage: "source",
      message:
        "The pathological Federal workbook is accepted only for its exact custodied sheet/range pairs.",
    };
  return { ok: true, bounded: true, route };
}

/**
 * Parse the exact custodied pathological Federal workbook directly from raw
 * OOXML into one bounded ParsedSheet. This never writes an execution workbook
 * or worksheet derivative and never instantiates ExcelJS worksheet geometry.
 */
export async function parseFederalDefendantsBoundedRawWorkbook(input: {
  bytes: Uint8Array;
  source: FederalDefendantsSourceContext;
  requestedSheet: string;
  declaredWorkbookDigest: string;
  declaredWorkbookBytes: number;
  limits: WorkerLimits;
}): Promise<WorkbookParseResult> {
  const preflight = preflightFederalDefendantsWorkbookRoute(input);
  if (!preflight.ok)
    throw new FederalDefendantsBoundedWorkbookError(
      preflight.code,
      preflight.stage,
      preflight.message,
    );
  if (!preflight.bounded)
    throw new FederalDefendantsBoundedWorkbookError(
      "FEDERAL_BOUNDED_WORKBOOK_ROUTE_MISMATCH",
      "source",
      "The requested source is not an approved bounded Federal workbook.",
    );
  if (input.bytes.byteLength !== input.declaredWorkbookBytes)
    throw new FederalDefendantsBoundedWorkbookError(
      "FEDERAL_BOUNDED_WORKBOOK_LENGTH_MISMATCH",
      "source",
      "The bounded Federal workbook bytes do not match the declared length.",
    );
  const actualDigest = digestBytes(input.bytes);
  if (
    actualDigest !== input.declaredWorkbookDigest ||
    actualDigest !== FEDERAL_DEFENDANTS_PATHOLOGICAL_WORKBOOK_DIGEST
  )
    throw new FederalDefendantsBoundedWorkbookError(
      "FEDERAL_BOUNDED_WORKBOOK_DIGEST_MISMATCH",
      "source",
      "The bounded parser received bytes outside immutable Federal custody.",
    );

  try {
    await preflightXlsxZipArchive(input.bytes, input.limits);
    const sheet = await parseBoundedRawXlsxSheet(
      input.bytes,
      preflight.route,
      input.limits,
    );
    return { ok: true, workbook: { sheets: [sheet] } };
  } catch (error) {
    if (
      error instanceof FederalDefendantsBoundedWorkbookError ||
      error instanceof LimitViolation
    )
      throw error;
    return {
      ok: false,
      errors: [
        {
          code: "INVALID_WORKBOOK",
          message:
            error instanceof Error
              ? error.message
              : "The bounded Federal workbook could not be parsed.",
        },
      ],
    };
  }
}

/**
 * Direct OOXML core exported for deterministic parser/full-parser parity
 * tests. It is not a custody gate and must not be used by a runtime without
 * the immutable preflight above.
 */
export async function parseBoundedRawXlsxSheetForParity(input: {
  bytes: Uint8Array;
  physicalSheet: string;
  authoritativeRange: string;
  limits: WorkerLimits;
}): Promise<ParsedSheet> {
  const authority = parseRange(input.authoritativeRange);
  const cardinality = rangeArea(authority);
  if (
    authority.start.row !== 1 ||
    authority.start.col !== 1 ||
    cardinality > Math.min(input.limits.maxCells, MAX_TEST_AUTHORITY_CELLS)
  )
    throw limitError(
      "FEDERAL_BOUNDED_TEST_AUTHORITY_LIMIT_EXCEEDED",
      "The parity helper accepts only a small R1C1-anchored test authority.",
    );
  await preflightXlsxZipArchive(input.bytes, input.limits);
  return await parseBoundedRawXlsxSheet(
    input.bytes,
    {
      physicalSheet: input.physicalSheet,
      authoritativeRange: input.authoritativeRange,
      a1Range: formatA1Range(parseRange(input.authoritativeRange)),
      expectedWorksheetEntry: "",
    },
    input.limits,
    false,
  );
}

type RuntimeRoute = {
  physicalSheet: string;
  authoritativeRange: string;
  a1Range: string;
  expectedWorksheetEntry: string;
  excludedNonblankCellCount?: number;
};

type Relationship = {
  id: string;
  type: string;
  target: string;
  targetMode?: string;
};

type SheetDeclaration = { name: string; relationshipId: string };

type RawCell = {
  a1Address: string;
  type?: string;
  styleId: number | null;
  formula: string | null;
  formulaType?: string;
  formulaSharedIndex?: number;
  formulaReference?: string;
  valueText: string | null;
  inlineText: string;
};

type WorkbookMetadata = {
  sheets: SheetDeclaration[];
  date1904: boolean;
};

type WorksheetMetadata = {
  cells: RawCell[];
  merges: CellRange[];
  hyperlinks: Array<{
    range: CellRange;
    relationshipId?: string;
    location?: string;
  }>;
};

type StyleManager = {
  parseStream(stream: AsyncIterable<Uint8Array>): Promise<void>;
  getStyleModel(index: number): Record<string, unknown> | undefined;
};

type ContentTypes = {
  defaults: Map<string, string>;
  overrides: Map<string, string>;
};

async function parseBoundedRawXlsxSheet(
  bytes: Uint8Array,
  route: RuntimeRoute,
  limits: WorkerLimits,
  enforcePinnedWorksheetEntry = true,
): Promise<ParsedSheet> {
  const commonEntries = await extractZipEntries(
    bytes,
    new Set([
      CONTENT_TYPES_XML,
      WORKBOOK_XML,
      WORKBOOK_RELS_XML,
      STYLES_XML,
      SHARED_STRINGS_XML,
    ]),
    new Set([CONTENT_TYPES_XML, WORKBOOK_XML, WORKBOOK_RELS_XML, STYLES_XML]),
  );
  const contentTypes = parseContentTypes(
    required(commonEntries, CONTENT_TYPES_XML),
  );
  assertPartContentType(contentTypes, WORKBOOK_XML, WORKBOOK_CONTENT_TYPES);
  assertPartContentType(
    contentTypes,
    STYLES_XML,
    new Set([STYLES_CONTENT_TYPE]),
  );
  if (commonEntries.has(SHARED_STRINGS_XML))
    assertPartContentType(
      contentTypes,
      SHARED_STRINGS_XML,
      new Set([SHARED_STRINGS_CONTENT_TYPE]),
    );
  const workbookMetadata = parseWorkbookMetadata(
    required(commonEntries, WORKBOOK_XML),
  );
  const declarations = workbookMetadata.sheets;
  const workbookRelationships = parseRelationships(
    required(commonEntries, WORKBOOK_RELS_XML),
  );
  const declaration = declarations.find(
    (candidate) => candidate.name === route.physicalSheet,
  );
  if (!declaration)
    throw parseError(
      "FEDERAL_BOUNDED_SHEET_NOT_FOUND",
      `Workbook does not declare ${JSON.stringify(route.physicalSheet)}.`,
    );
  if (
    declarations.filter((candidate) => candidate.name === route.physicalSheet)
      .length !== 1
  )
    throw parseError(
      "FEDERAL_BOUNDED_DUPLICATE_SHEET",
      "Workbook contains a duplicate bounded sheet declaration.",
    );
  const matchingRelationships = workbookRelationships.filter(
    (candidate) => candidate.id === declaration.relationshipId,
  );
  const relationship = matchingRelationships[0];
  if (
    matchingRelationships.length !== 1 ||
    !relationship ||
    !WORKSHEET_RELATIONSHIP_TYPES.has(relationship.type) ||
    relationship.targetMode !== undefined
  )
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_INVALID",
      "Bounded sheet relationship is absent or not an internal worksheet.",
    );
  const worksheetEntry = resolveWorkbookTarget(relationship.target);
  if (
    enforcePinnedWorksheetEntry &&
    worksheetEntry !== route.expectedWorksheetEntry
  )
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_INVALID",
      "Bounded sheet relationship target differs from immutable custody.",
    );
  assertPartContentType(contentTypes, worksheetEntry, WORKSHEET_CONTENT_TYPES);
  const worksheetRelsEntry = `${path.posix.dirname(worksheetEntry)}/_rels/${path.posix.basename(worksheetEntry)}.rels`;
  const initialTargetEntries = await extractZipEntries(
    bytes,
    new Set([worksheetEntry, worksheetRelsEntry]),
    new Set([worksheetEntry]),
  );
  const worksheetXml = required(initialTargetEntries, worksheetEntry);
  const worksheetRelationships = initialTargetEntries.has(worksheetRelsEntry)
    ? parseRelationships(required(initialTargetEntries, worksheetRelsEntry))
    : [];
  const commentRelationship = uniqueRelationshipOfType(
    worksheetRelationships,
    COMMENTS_RELATIONSHIP_TYPES,
    "comments",
  );
  const commentEntry = commentRelationship
    ? resolveWorksheetTarget(worksheetEntry, commentRelationship)
    : undefined;
  const commentEntries = commentEntry
    ? await extractZipEntries(bytes, new Set([commentEntry]))
    : new Map<string, Buffer>();
  if (commentEntry)
    assertPartContentType(
      contentTypes,
      commentEntry,
      new Set([COMMENTS_CONTENT_TYPE]),
    );
  const comments = commentEntry
    ? parseComments(required(commentEntries, commentEntry), limits)
    : new Map<string, string>();
  const authority = parseRange(route.authoritativeRange);
  if (
    authority.start.row !== 1 ||
    authority.start.col !== 1 ||
    formatA1Range(authority) !== route.a1Range
  )
    throw parseError(
      "FEDERAL_BOUNDED_AUTHORITY_INVALID",
      "Bounded authority must be the exact canonical A1/R1C1 rectangle.",
    );
  const authorityArea = rangeArea(authority);
  if (authorityArea > limits.maxCells)
    throw limitError(
      "CELL_LIMIT_EXCEEDED",
      `Authority requires ${authorityArea} cells; limit is ${limits.maxCells}.`,
    );
  const metadata = parseWorksheetXml(worksheetXml, authority, limits);
  const sharedStrings = commonEntries.has(SHARED_STRINGS_XML)
    ? parseSharedStrings(required(commonEntries, SHARED_STRINGS_XML), limits)
    : [];
  const styleManager = await parseStyles(required(commonEntries, STYLES_XML));
  const hyperlinkTargets = hyperlinkRelationshipTargets(
    worksheetRelationships,
    worksheetEntry,
  );
  const hyperlinks = expandHyperlinks(
    metadata.hyperlinks,
    hyperlinkTargets,
    authority,
    limits,
  );
  const mergeIndex = buildBoundedMergeIndex(metadata.merges, authority, limits);
  const sharedFormulaMasters = buildSharedFormulaMasters(metadata.cells);
  const cells = new Map<string, TidyCell>();
  for (const raw of metadata.cells) {
    const parsed = parseA1Cell(raw.a1Address);
    const address = formatCell(parsed);
    const merge = mergeIndex.byAddress.get(address) ?? null;
    const styleModel =
      raw.styleId === null
        ? undefined
        : styleManager.getStyleModel(raw.styleId);
    if (raw.styleId !== null && styleModel === undefined)
      throw parseError(
        "FEDERAL_BOUNDED_STYLE_INVALID",
        `Style ID ${raw.styleId} at ${raw.a1Address} is out of bounds.`,
      );
    const content = parseRawCell(
      raw,
      sharedStrings,
      styleModel,
      workbookMetadata.date1904,
      sharedFormulaMasters,
    );
    const style =
      raw.styleId === null || raw.styleId === 0
        ? undefined
        : summarizeBoundedStyle(styleModel);
    const hyperlink = hyperlinks.get(address) ?? null;
    const cell: TidyCell = {
      sheet: route.physicalSheet,
      address,
      row: parsed.row,
      col: parsed.col,
      value: merge?.role === "child" ? null : content.value,
      data_type: merge?.role === "child" ? "blank" : content.dataType,
      formula: merge?.role === "child" ? null : content.formula,
      formatted:
        raw.formula !== null
          ? formulaFormattedText(content.value, content.dataType)
          : hyperlink && typeof content.value === "string"
            ? content.value
            : null,
      comment: comments.get(address) ?? null,
      hyperlink,
      style,
      merge,
    };
    if (isMeaningful(cell)) cells.set(address, cell);
  }
  for (const [address, comment] of comments) {
    const parsed = parseCell(address);
    if (!within(parsed, authority)) continue;
    const existing = cells.get(address);
    if (existing) existing.comment = comment;
    else
      cells.set(address, {
        sheet: route.physicalSheet,
        address,
        row: parsed.row,
        col: parsed.col,
        value: null,
        data_type: "blank",
        formula: null,
        formatted: null,
        comment,
        hyperlink: hyperlinks.get(address) ?? null,
        merge: mergeIndex.byAddress.get(address) ?? null,
      });
  }
  for (const [address, hyperlink] of hyperlinks) {
    const existing = cells.get(address);
    if (existing) existing.hyperlink = hyperlink;
    else {
      const parsed = parseCell(address);
      cells.set(address, {
        sheet: route.physicalSheet,
        address,
        row: parsed.row,
        col: parsed.col,
        value: null,
        data_type: "blank",
        formula: null,
        formatted: null,
        comment: comments.get(address) ?? null,
        hyperlink,
        merge: mergeIndex.byAddress.get(address) ?? null,
      });
    }
  }
  applyMergeCells(cells, mergeIndex, route.physicalSheet, authority, limits);
  const ordered = [...cells.values()].sort(compareCells);
  if (ordered.length > limits.maxCells)
    throw limitError(
      "CELL_LIMIT_EXCEEDED",
      `Bounded sheet has ${ordered.length} cells; limit is ${limits.maxCells}.`,
    );
  for (const cell of ordered)
    if (
      cell.row < authority.start.row ||
      cell.row > authority.end.row ||
      cell.col < authority.start.col ||
      cell.col > authority.end.col
    )
      throw parseError(
        "FEDERAL_BOUNDED_CELL_OUTSIDE_AUTHORITY",
        `Bounded parser emitted ${cell.address} outside authority.`,
      );
  for (const merge of mergeIndex.merges) {
    const parsed = parseRange(merge.range);
    if (!fullyContained(parsed, authority))
      throw parseError(
        "FEDERAL_BOUNDED_MERGE_OUTSIDE_AUTHORITY",
        `Bounded parser emitted merge ${merge.range} outside authority.`,
      );
  }
  return {
    name: route.physicalSheet,
    usedRange: route.authoritativeRange,
    rowCount: authority.end.row,
    columnCount: authority.end.col,
    nonEmptyCellCount: ordered.filter((cell) => cell.data_type !== "blank")
      .length,
    cells: ordered,
    merges: mergeIndex.merges,
  };
}

function parseRawCell(
  raw: RawCell,
  sharedStrings: string[],
  styleModel: Record<string, unknown> | undefined,
  date1904: boolean,
  sharedFormulaMasters: Map<number, string>,
): {
  value: TidyCell["value"];
  dataType: TidyCell["data_type"];
  formula: string | null;
} {
  let value: TidyCell["value"] = null;
  let dataType: TidyCell["data_type"] = "blank";
  const text = raw.valueText;
  switch (raw.type) {
    case "s": {
      if (text === null || !/^\d+$/.test(text))
        throw parseError(
          "FEDERAL_BOUNDED_SHARED_STRING_INVALID",
          `Invalid shared-string index at ${raw.a1Address}.`,
        );
      const index = Number(text);
      if (!Number.isSafeInteger(index) || sharedStrings[index] === undefined)
        throw parseError(
          "FEDERAL_BOUNDED_SHARED_STRING_INVALID",
          `Missing shared-string index at ${raw.a1Address}.`,
        );
      value = sharedStrings[index];
      dataType = "string";
      break;
    }
    case "inlineStr":
      value = raw.inlineText;
      dataType = "string";
      break;
    case "str":
      value = text ?? "";
      dataType = "string";
      break;
    case "b":
      if (text !== "0" && text !== "1")
        throw parseError(
          "FEDERAL_BOUNDED_BOOLEAN_INVALID",
          `Invalid boolean at ${raw.a1Address}.`,
        );
      value = text === "1";
      dataType = "boolean";
      break;
    case "e":
      value = text ?? "#VALUE!";
      dataType = "error";
      break;
    default:
      if (raw.type !== undefined && raw.type !== "n" && raw.type !== "d")
        throw parseError(
          "FEDERAL_BOUNDED_CELL_TYPE_INVALID",
          `Unsupported cell type ${raw.type} at ${raw.a1Address}.`,
        );
      if (raw.type === "d") {
        if (text === null || Number.isNaN(Date.parse(text)))
          throw parseError(
            "FEDERAL_BOUNDED_DATE_INVALID",
            `Invalid ISO date at ${raw.a1Address}.`,
          );
        value = new Date(text).toISOString();
        dataType = "date";
      } else if (text !== null) {
        const numeric = Number(text);
        if (!Number.isFinite(numeric))
          throw parseError(
            "FEDERAL_BOUNDED_NUMERIC_INVALID",
            `Invalid numeric value at ${raw.a1Address}.`,
          );
        const numFmt =
          typeof styleModel?.numFmt === "string"
            ? styleModel.numFmt
            : undefined;
        if (excelUtils.isDateFmt(numFmt)) {
          value = excelUtils.excelToDate(numeric, date1904).toISOString();
          dataType = "date";
        } else {
          value = numeric;
          dataType = "numeric";
        }
      }
      break;
  }
  let formula = raw.formula;
  if (raw.formulaType === "shared" && raw.formula === "") {
    const index = raw.formulaSharedIndex;
    const master =
      index === undefined ? undefined : sharedFormulaMasters.get(index);
    if (!master)
      throw parseError(
        "FEDERAL_BOUNDED_SHARED_FORMULA_INVALID",
        `Shared formula at ${raw.a1Address} has no in-authority master.`,
      );
    formula = master;
  }
  return { value, dataType, formula };
}

function buildSharedFormulaMasters(cells: RawCell[]): Map<number, string> {
  const masters = new Map<number, string>();
  for (const cell of cells) {
    if (cell.formulaType !== "shared" || !cell.formula) continue;
    const index = cell.formulaSharedIndex;
    if (index === undefined || masters.has(index))
      throw parseError(
        "FEDERAL_BOUNDED_SHARED_FORMULA_INVALID",
        "Shared-formula master index is absent or duplicated.",
      );
    masters.set(index, cell.a1Address);
  }
  return masters;
}

function formulaFormattedText(
  value: TidyCell["value"],
  dataType: TidyCell["data_type"],
): string | null {
  // ExcelJS FormulaValue.toString() returns an empty string for every falsy
  // cached result. parseWorkbook then normalizes that empty cell.text to null.
  if (!value) return null;
  // A true Excel date result reaches parseRawCell as an ISO string; only that
  // typed case receives Date.toString(). A cached string that merely resembles
  // an ISO date must remain the exact source string.
  if (dataType === "date" && typeof value === "string")
    return new Date(value).toString();
  return String(value);
}

function summarizeBoundedStyle(style: unknown): CellStyleSummary | undefined {
  const summary: CellStyleSummary = {};
  const styleRecord = asRecord(style);
  const font = asRecord(styleRecord?.font);
  const fill = asRecord(styleRecord?.fill);
  const alignment = asRecord(styleRecord?.alignment);
  const border = asRecord(styleRecord?.border);
  if (font?.bold === true) summary.bold = true;
  if (font?.italic === true) summary.italic = true;
  if (font?.underline === true || typeof font?.underline === "string")
    summary.underline = true;
  if (typeof font?.size === "number") summary.fontSize = font.size;
  const fontColor = colorToString(font?.color);
  if (fontColor) summary.fontColor = fontColor;
  const fillColor = colorToString(fill?.fgColor);
  if (fillColor) summary.fillColor = fillColor;
  if (typeof alignment?.horizontal === "string")
    summary.horizontalAlign = alignment.horizontal;
  if (typeof alignment?.indent === "number" && alignment.indent > 0)
    summary.fontIndent = alignment.indent;
  if (typeof alignment?.vertical === "string")
    summary.verticalAlign = alignment.vertical;
  const borderSummary = {
    top: hasBorder(border?.top),
    right: hasBorder(border?.right),
    bottom: hasBorder(border?.bottom),
    left: hasBorder(border?.left),
  };
  if (Object.values(borderSummary).some(Boolean))
    summary.border = borderSummary;
  return Object.keys(summary).length > 0 ? summary : undefined;
}

function colorToString(value: unknown): string | undefined {
  const color = asRecord(value);
  if (!color) return undefined;
  if (typeof color.argb === "string") return color.argb;
  if (typeof color.rgb === "string") return color.rgb;
  if (typeof color.theme === "number") return `theme:${color.theme}`;
  if (typeof color.indexed === "number") return `indexed:${color.indexed}`;
  return undefined;
}

function hasBorder(value: unknown): boolean {
  const border = asRecord(value);
  return typeof border?.style === "string" && border.style.length > 0;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

function isMeaningful(cell: TidyCell): boolean {
  return (
    cell.data_type !== "blank" ||
    Boolean(cell.formatted) ||
    Boolean(cell.comment) ||
    Boolean(cell.hyperlink) ||
    Boolean(cell.style) ||
    Boolean(cell.merge)
  );
}

function applyMergeCells(
  cells: Map<string, TidyCell>,
  index: MergeIndex,
  sheet: string,
  authority: CellRange,
  limits: WorkerLimits,
): void {
  for (const item of index.expansions) {
    const { original, intersection, expandChildren } = item;
    const parentAddress = formatCell(original.start);
    const parentInAuthority = within(original.start, authority);
    const parent = parentInAuthority
      ? (cells.get(parentAddress) ?? {
          sheet,
          address: parentAddress,
          row: original.start.row,
          col: original.start.col,
          value: null,
          data_type: "blank" as const,
          formula: null,
          formatted: null,
          comment: null,
          hyperlink: null,
        })
      : undefined;
    if (parent) {
      parent.merge = index.byAddress.get(parentAddress) ?? null;
      cells.set(parentAddress, parent);
    }
    if (!expandChildren) continue;
    for (
      let row = intersection.start.row;
      row <= intersection.end.row;
      row += 1
    )
      for (
        let col = intersection.start.col;
        col <= intersection.end.col;
        col += 1
      ) {
        const address = formatCell({ row, col });
        if (address === parentAddress) continue;
        const existing = cells.get(address);
        cells.set(address, {
          sheet,
          address,
          row,
          col,
          value: null,
          data_type: "blank",
          formula: null,
          formatted: null,
          comment: existing?.comment ?? null,
          hyperlink: existing?.hyperlink ?? null,
          style: existing?.style ?? parent?.style,
          merge: index.byAddress.get(address) ?? null,
        });
        if (cells.size > limits.maxCells)
          throw limitError(
            "CELL_LIMIT_EXCEEDED",
            "Bounded merge expansion exceeds the cell limit.",
          );
      }
  }
}

type MergeIndex = {
  merges: ParsedMergeRange[];
  byAddress: Map<string, CellMergeSummary>;
  expansions: Array<{
    original: CellRange;
    intersection: CellRange;
    expandChildren: boolean;
  }>;
};

function buildBoundedMergeIndex(
  ranges: CellRange[],
  authority: CellRange,
  limits: WorkerLimits,
): MergeIndex {
  const merges: ParsedMergeRange[] = [];
  const byAddress = new Map<string, CellMergeSummary>();
  const expansions: MergeIndex["expansions"] = [];
  let expansion = 0;
  let mergeCount = 0;
  const seen = new Set<string>();
  for (const parsed of ranges) {
    const range = formatRange(parsed);
    if (seen.has(range))
      throw parseError(
        "FEDERAL_BOUNDED_DUPLICATE_MERGE",
        `Duplicate bounded merge ${range}.`,
      );
    seen.add(range);
    const parent = formatCell(parsed.start);
    const area =
      (parsed.end.row - parsed.start.row + 1) *
      (parsed.end.col - parsed.start.col + 1);
    const contained = fullyContained(parsed, authority);
    mergeCount += 1;
    if (mergeCount > Math.min(limits.maxMerges, MAX_BOUNDED_XML_MERGES))
      throw limitError(
        "MERGE_LIMIT_EXCEEDED",
        "Bounded sheet exceeds the merge limit.",
      );
    if (contained) merges.push({ parent, range });

    const intersection: CellRange = {
      start: {
        row: Math.max(parsed.start.row, authority.start.row),
        col: Math.max(parsed.start.col, authority.start.col),
      },
      end: {
        row: Math.min(parsed.end.row, authority.end.row),
        col: Math.min(parsed.end.col, authority.end.col),
      },
    };
    const expandChildren = contained || area <= 10_000;
    const boundedExpansion = expandChildren
      ? rangeArea(intersection)
      : within(parsed.start, authority)
        ? 1
        : 0;
    expansion = safeAdd(
      expansion,
      boundedExpansion,
      "MERGE_EXPANSION_LIMIT_EXCEEDED",
    );
    if (expansion > limits.maxMergeExpansionCells)
      throw limitError(
        "MERGE_EXPANSION_LIMIT_EXCEEDED",
        "Bounded merges exceed the cumulative merge-expansion limit.",
      );
    expansions.push({ original: parsed, intersection, expandChildren });
    if (!expandChildren) {
      if (within(parsed.start, authority))
        setMergeProof(byAddress, parent, { parent, range, role: "parent" });
      continue;
    }
    for (
      let row = intersection.start.row;
      row <= intersection.end.row;
      row += 1
    )
      for (
        let col = intersection.start.col;
        col <= intersection.end.col;
        col += 1
      ) {
        const address = formatCell({ row, col });
        setMergeProof(byAddress, address, {
          parent,
          range,
          role: address === parent ? "parent" : "child",
        });
      }
  }
  return { merges, byAddress, expansions };
}

function setMergeProof(
  byAddress: Map<string, CellMergeSummary>,
  address: string,
  proof: CellMergeSummary,
): void {
  if (byAddress.has(address))
    throw parseError(
      "FEDERAL_BOUNDED_OVERLAPPING_MERGE",
      `Bounded merge overlaps at ${address}.`,
    );
  byAddress.set(address, proof);
}

function parseWorksheetXml(
  bytes: Buffer,
  authority: CellRange,
  limits: WorkerLimits,
): WorksheetMetadata {
  const cells: RawCell[] = [];
  const merges: CellRange[] = [];
  const hyperlinks: WorksheetMetadata["hyperlinks"] = [];
  const seenCells = new Set<string>();
  const seenHyperlinks = new Set<string>();
  let current: RawCell | undefined;
  let capture: "v" | "f" | "t" | undefined;
  let captured = "";
  let totalCells = 0;
  let totalMerges = 0;
  const parser = xmlParser();
  parser.on("opentag", (node) => {
    const name = localName(node.name);
    if (name === "c") {
      totalCells += 1;
      if (totalCells > Math.min(MAX_BOUNDED_XML_CELLS, limits.maxCells))
        throw limitError(
          "CELL_LIMIT_EXCEEDED",
          "Worksheet XML exceeds the bounded explicit-cell scan limit.",
        );
      const address = xmlAttribute(node, "r");
      if (!address)
        throw parseError(
          "FEDERAL_BOUNDED_CELL_ADDRESS_INVALID",
          "Worksheet cell has no address.",
        );
      const parsed = parseA1Cell(address);
      current = within(parsed, authority)
        ? {
            a1Address: canonicalA1(parsed),
            type: xmlAttribute(node, "t"),
            styleId: parseStyleId(xmlAttribute(node, "s"), address),
            formula: null,
            formulaType: undefined,
            formulaSharedIndex: undefined,
            formulaReference: undefined,
            valueText: null,
            inlineText: "",
          }
        : undefined;
      return;
    }
    if (current && (name === "v" || name === "f" || name === "t")) {
      capture = name;
      captured = "";
      if (name === "f") {
        current.formula = "";
        current.formulaType = xmlAttribute(node, "t");
        current.formulaReference = xmlAttribute(node, "ref");
        const sharedIndex = xmlAttribute(node, "si");
        if (sharedIndex !== undefined) {
          if (
            !/^\d+$/.test(sharedIndex) ||
            !Number.isSafeInteger(Number(sharedIndex))
          )
            throw parseError(
              "FEDERAL_BOUNDED_SHARED_FORMULA_INVALID",
              `Invalid shared formula index at ${current.a1Address}.`,
            );
          current.formulaSharedIndex = Number(sharedIndex);
        }
        if (
          current.formulaType !== undefined &&
          current.formulaType !== "shared" &&
          current.formulaType !== "array"
        )
          throw parseError(
            "FEDERAL_BOUNDED_FORMULA_INVALID",
            `Unsupported formula type at ${current.a1Address}.`,
          );
        if (
          current.formulaType === "shared" &&
          current.formulaSharedIndex === undefined
        )
          throw parseError(
            "FEDERAL_BOUNDED_SHARED_FORMULA_INVALID",
            `Shared formula index is absent at ${current.a1Address}.`,
          );
      }
      return;
    }
    if (name === "mergeCell") {
      totalMerges += 1;
      if (totalMerges > MAX_BOUNDED_XML_MERGES)
        throw limitError(
          "MERGE_LIMIT_EXCEEDED",
          "Worksheet XML exceeds the bounded merge scan limit.",
        );
      const ref = xmlAttribute(node, "ref");
      if (!ref)
        throw parseError(
          "FEDERAL_BOUNDED_MERGE_INVALID",
          "Worksheet merge has no ref.",
        );
      const parsed = parseA1Range(ref);
      if (
        parsed.end.row >= authority.start.row &&
        parsed.end.col >= authority.start.col &&
        parsed.start.row <= authority.end.row &&
        parsed.start.col <= authority.end.col
      )
        merges.push(parsed);
      return;
    }
    if (name === "hyperlink") {
      const ref = xmlAttribute(node, "ref");
      if (!ref)
        throw parseError(
          "FEDERAL_BOUNDED_HYPERLINK_INVALID",
          "Worksheet hyperlink has no ref.",
        );
      const parsed = ref.includes(":")
        ? parseA1Range(ref)
        : { start: parseA1Cell(ref), end: parseA1Cell(ref) };
      const relationshipId = xmlAttribute(node, "r:id");
      const location = xmlAttribute(node, "location");
      if (!relationshipId && !location)
        throw parseError(
          "FEDERAL_BOUNDED_HYPERLINK_INVALID",
          "Worksheet hyperlink has no external or internal target.",
        );
      const hyperlinkKey = `${formatRange(parsed)}|${relationshipId ?? ""}|${location ?? ""}`;
      if (seenHyperlinks.has(hyperlinkKey))
        throw parseError(
          "FEDERAL_BOUNDED_DUPLICATE_HYPERLINK",
          "Worksheet contains a duplicate hyperlink declaration.",
        );
      seenHyperlinks.add(hyperlinkKey);
      if (hyperlinks.length + 1 > limits.maxCells)
        throw limitError(
          "CELL_LIMIT_EXCEEDED",
          "Worksheet hyperlink declarations exceed the cell limit.",
        );
      hyperlinks.push({ range: parsed, relationshipId, location });
    }
  });
  parser.on("text", (text) => {
    if (capture) captured += text;
  });
  parser.on("cdata", (text) => {
    if (capture) captured += text;
  });
  parser.on("closetag", (node) => {
    const name = localName(
      typeof node === "string" ? node : (node as { name: string }).name,
    );
    if (current && capture && name === capture) {
      if (capture === "v") current.valueText = captured;
      else if (capture === "f") current.formula = captured;
      else current.inlineText += captured;
      capture = undefined;
      captured = "";
    }
    if (name === "c") {
      if (current) {
        if (seenCells.has(current.a1Address))
          throw parseError(
            "FEDERAL_BOUNDED_DUPLICATE_CELL",
            `Duplicate bounded cell ${current.a1Address}.`,
          );
        seenCells.add(current.a1Address);
        cells.push(current);
      }
      current = undefined;
      capture = undefined;
      captured = "";
    }
  });
  parseXml(parser, bytes);
  return { cells, merges, hyperlinks };
}

function parseContentTypes(bytes: Buffer): ContentTypes {
  const defaults = new Map<string, string>();
  const overrides = new Map<string, string>();
  const parser = xmlParser();
  parser.on("opentag", (node) => {
    const name = localName(node.name);
    if (name === "Default") {
      const extension = xmlAttribute(node, "Extension")?.toLowerCase();
      const type = xmlAttribute(node, "ContentType");
      if (!extension || !type || defaults.has(extension))
        throw parseError(
          "FEDERAL_BOUNDED_CONTENT_TYPES_INVALID",
          "Content-type default is incomplete or duplicated.",
        );
      defaults.set(extension, type);
    } else if (name === "Override") {
      const rawPart = xmlAttribute(node, "PartName");
      const type = xmlAttribute(node, "ContentType");
      if (!rawPart || !type || !rawPart.startsWith("/"))
        throw parseError(
          "FEDERAL_BOUNDED_CONTENT_TYPES_INVALID",
          "Content-type override is incomplete.",
        );
      const part = rawPart.slice(1);
      assertSafeZipName(part);
      if (overrides.has(part))
        throw parseError(
          "FEDERAL_BOUNDED_CONTENT_TYPES_INVALID",
          "Content-type override is duplicated.",
        );
      overrides.set(part, type);
    }
  });
  parseXml(parser, bytes);
  return { defaults, overrides };
}

function assertPartContentType(
  contentTypes: ContentTypes,
  part: string,
  accepted: Set<string>,
): void {
  const extension = path.posix.extname(part).slice(1).toLowerCase();
  const actual =
    contentTypes.overrides.get(part) ?? contentTypes.defaults.get(extension);
  if (!actual || !accepted.has(actual))
    throw parseError(
      "FEDERAL_BOUNDED_CONTENT_TYPE_INVALID",
      `OOXML part ${part} has an invalid content type.`,
    );
}

function parseSharedStrings(bytes: Buffer, limits: WorkerLimits): string[] {
  const strings: string[] = [];
  let inItem = false;
  let inText = false;
  let value = "";
  const parser = xmlParser();
  parser.on("opentag", (node) => {
    const name = localName(node.name);
    if (name === "si") {
      if (inItem)
        throw parseError(
          "FEDERAL_BOUNDED_SHARED_STRING_INVALID",
          "Nested shared-string item.",
        );
      inItem = true;
      value = "";
    } else if (name === "t" && inItem) inText = true;
  });
  parser.on("text", (text) => {
    if (inText) value += text;
  });
  parser.on("cdata", (text) => {
    if (inText) value += text;
  });
  parser.on("closetag", (node) => {
    const name = localName(
      typeof node === "string" ? node : (node as { name: string }).name,
    );
    if (name === "t") inText = false;
    if (name === "si") {
      if (strings.length + 1 > limits.maxCells)
        throw limitError(
          "CELL_LIMIT_EXCEEDED",
          "Shared-string count exceeds the bounded cell limit.",
        );
      strings.push(value);
      inItem = false;
      inText = false;
    }
  });
  parseXml(parser, bytes);
  return strings;
}

function parseComments(
  bytes: Buffer,
  limits: WorkerLimits,
): Map<string, string> {
  const comments = new Map<string, string>();
  let authorCount = 0;
  let inAuthors = false;
  let inComment = false;
  let inText = false;
  let ref = "";
  let authorId = -1;
  let text = "";
  const parser = xmlParser();
  parser.on("opentag", (node) => {
    const name = localName(node.name);
    if (name === "authors") inAuthors = true;
    else if (name === "author" && inAuthors) authorCount += 1;
    else if (name === "comment") {
      if (inComment)
        throw parseError(
          "FEDERAL_BOUNDED_COMMENT_INVALID",
          "Nested comments are invalid.",
        );
      ref = xmlAttribute(node, "ref") ?? "";
      const rawAuthor = xmlAttribute(node, "authorId");
      if (!ref || rawAuthor === undefined || !/^\d+$/.test(rawAuthor))
        throw parseError(
          "FEDERAL_BOUNDED_COMMENT_INVALID",
          "Comment reference or author is invalid.",
        );
      parseA1Cell(ref);
      authorId = Number(rawAuthor);
      inComment = true;
      text = "";
    } else if (name === "t" && inComment) inText = true;
  });
  parser.on("text", (value) => {
    if (inText) text += value;
  });
  parser.on("cdata", (value) => {
    if (inText) text += value;
  });
  parser.on("closetag", (node) => {
    const name = localName(
      typeof node === "string" ? node : (node as { name: string }).name,
    );
    if (name === "t") inText = false;
    else if (name === "authors") inAuthors = false;
    else if (name === "comment") {
      const address = formatCell(parseA1Cell(ref));
      if (
        !Number.isSafeInteger(authorId) ||
        authorId < 0 ||
        authorId >= authorCount ||
        comments.has(address) ||
        comments.size + 1 > limits.maxCells
      )
        throw parseError(
          "FEDERAL_BOUNDED_COMMENT_INVALID",
          "Comment author, reference, or count is invalid.",
        );
      comments.set(address, text);
      inComment = false;
      inText = false;
    }
  });
  parseXml(parser, bytes);
  return comments;
}

async function parseStyles(bytes: Buffer): Promise<StyleManager> {
  // StylesXform parses its own stream rather than using parseXml below, so run
  // the identical fatal UTF-8 and forbidden declaration gate first.
  assertXmlTextSafe(bytes);
  const manager = new StylesXform();
  await manager.parseStream(Readable.from([bytes]));
  return manager;
}

function parseWorkbookMetadata(bytes: Buffer): WorkbookMetadata {
  const sheets: SheetDeclaration[] = [];
  const names = new Set<string>();
  const ids = new Set<string>();
  let date1904 = false;
  let workbookPropertiesSeen = false;
  const parser = xmlParser();
  parser.on("opentag", (node) => {
    const name = localName(node.name);
    if (name === "workbookPr") {
      if (workbookPropertiesSeen)
        throw parseError(
          "FEDERAL_BOUNDED_WORKBOOK_PROPERTIES_INVALID",
          "Workbook properties are duplicated.",
        );
      workbookPropertiesSeen = true;
      const value = xmlAttribute(node, "date1904");
      if (
        value !== undefined &&
        value !== "0" &&
        value !== "1" &&
        value !== "false" &&
        value !== "true"
      )
        throw parseError(
          "FEDERAL_BOUNDED_WORKBOOK_PROPERTIES_INVALID",
          "Workbook date1904 is invalid.",
        );
      date1904 = value === "1" || value === "true";
      return;
    }
    if (name !== "sheet") return;
    const sheetName = xmlAttribute(node, "name");
    const relationshipId = xmlAttribute(node, "r:id");
    if (!sheetName || !relationshipId)
      throw parseError(
        "FEDERAL_BOUNDED_SHEET_DECLARATION_INVALID",
        "Workbook sheet declaration is incomplete.",
      );
    if (names.has(sheetName) || ids.has(relationshipId))
      throw parseError(
        "FEDERAL_BOUNDED_DUPLICATE_SHEET",
        "Workbook contains duplicate sheet names or relationship IDs.",
      );
    names.add(sheetName);
    ids.add(relationshipId);
    sheets.push({ name: sheetName, relationshipId });
  });
  parseXml(parser, bytes);
  return { sheets, date1904 };
}

function parseRelationships(bytes: Buffer): Relationship[] {
  const relationships: Relationship[] = [];
  const ids = new Set<string>();
  const parser = xmlParser();
  parser.on("opentag", (node) => {
    if (localName(node.name) !== "Relationship") return;
    const id = xmlAttribute(node, "Id");
    const type = xmlAttribute(node, "Type");
    const target = xmlAttribute(node, "Target");
    if (!id || !type || !target)
      throw parseError(
        "FEDERAL_BOUNDED_RELATIONSHIP_INVALID",
        "OOXML relationship is incomplete.",
      );
    if (ids.has(id))
      throw parseError(
        "FEDERAL_BOUNDED_DUPLICATE_RELATIONSHIP",
        `Duplicate relationship ${id}.`,
      );
    ids.add(id);
    relationships.push({
      id,
      type,
      target,
      targetMode: xmlAttribute(node, "TargetMode"),
    });
  });
  parseXml(parser, bytes);
  return relationships;
}

function uniqueRelationshipOfType(
  relationships: Relationship[],
  accepted: Set<string>,
  label: string,
): Relationship | undefined {
  const matching = relationships.filter((entry) => accepted.has(entry.type));
  if (matching.length > 1)
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_INVALID",
      `Worksheet has duplicate ${label} relationships.`,
    );
  const relationship = matching[0];
  if (relationship?.targetMode !== undefined)
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_INVALID",
      `${label} relationship must be internal.`,
    );
  return relationship;
}

function hyperlinkRelationshipTargets(
  relationships: Relationship[],
  worksheetEntry: string,
): Map<string, string> {
  const result = new Map<string, string>();
  for (const entry of relationships) {
    if (!HYPERLINK_RELATIONSHIP_TYPES.has(entry.type)) continue;
    if (entry.targetMode !== "External")
      throw parseError(
        "FEDERAL_BOUNDED_HYPERLINK_INVALID",
        "Hyperlink relationship must use TargetMode=External.",
      );
    if (result.has(entry.id))
      throw parseError(
        "FEDERAL_BOUNDED_DUPLICATE_RELATIONSHIP",
        "Hyperlink relationship is duplicated.",
      );
    // Parse the worksheet path here so this helper cannot accidentally be
    // reused with a non-worksheet relationship base.
    if (!worksheetEntry.startsWith("xl/worksheets/"))
      throw parseError(
        "FEDERAL_BOUNDED_RELATIONSHIP_PATH_UNSAFE",
        "Hyperlink relationship base is invalid.",
      );
    result.set(entry.id, entry.target);
  }
  return result;
}

function expandHyperlinks(
  entries: WorksheetMetadata["hyperlinks"],
  relationshipTargets: Map<string, string>,
  authority: CellRange,
  limits: WorkerLimits,
): Map<string, string> {
  // Deliberate source-preservation rule: OOXML permits a hyperlink ref to be a
  // multi-cell range. Historical ExcelJS indexes the literal range string and
  // consequently drops it when reconciling individual cells. This bounded
  // parser instead retains the exact parsed raw range until here, then attaches
  // its target to every in-authority cell. Cumulative cardinality is checked
  // before allocation. The five immutable production routes currently contain
  // only single-cell refs; range behavior is explicitly regression-tested.
  const result = new Map<string, string>();
  let expansion = 0;
  for (const entry of entries) {
    const target = entry.relationshipId
      ? relationshipTargets.get(entry.relationshipId)
      : entry.location;
    if (!target)
      throw parseError(
        "FEDERAL_BOUNDED_HYPERLINK_INVALID",
        "Worksheet hyperlink relationship is unresolved.",
      );
    const startRow = Math.max(entry.range.start.row, authority.start.row);
    const endRow = Math.min(entry.range.end.row, authority.end.row);
    const startCol = Math.max(entry.range.start.col, authority.start.col);
    const endCol = Math.min(entry.range.end.col, authority.end.col);
    if (startRow > endRow || startCol > endCol) continue;
    const cardinality = (endRow - startRow + 1) * (endCol - startCol + 1);
    expansion = safeAdd(expansion, cardinality, "CELL_LIMIT_EXCEEDED");
    if (expansion > limits.maxCells)
      throw limitError(
        "CELL_LIMIT_EXCEEDED",
        "Hyperlink expansion exceeds the bounded cell limit.",
      );
    for (let row = startRow; row <= endRow; row += 1)
      for (let col = startCol; col <= endCol; col += 1) {
        const address = formatCell({ row, col });
        if (result.has(address))
          throw parseError(
            "FEDERAL_BOUNDED_DUPLICATE_HYPERLINK",
            `Duplicate hyperlink at ${address}.`,
          );
        result.set(address, target);
      }
  }
  return result;
}

async function extractZipEntries(
  bytes: Uint8Array,
  wanted: Set<string>,
  requiredNames = wanted,
): Promise<Map<string, Buffer>> {
  const zip = await openZip(bytes);
  const found = new Map<string, Buffer>();
  const names = new Set<string>();
  try {
    await new Promise<void>((resolve, reject) => {
      let settled = false;
      const fail = (error: unknown) => {
        if (settled) return;
        settled = true;
        reject(error);
      };
      zip.once("error", fail);
      zip.once("end", () => {
        if (settled) return;
        settled = true;
        resolve();
      });
      zip.on("entry", (entry: Entry) => {
        void (async () => {
          assertSafeZipName(entry.fileName);
          if (names.has(entry.fileName))
            throw parseError(
              "FEDERAL_BOUNDED_DUPLICATE_ZIP_ENTRY",
              `Duplicate ZIP entry ${entry.fileName}.`,
            );
          names.add(entry.fileName);
          if (wanted.has(entry.fileName))
            found.set(entry.fileName, await readZipEntry(zip, entry));
          zip.readEntry();
        })().catch(fail);
      });
      zip.readEntry();
    });
  } finally {
    zip.close();
  }
  for (const name of requiredNames)
    if (!found.has(name))
      throw parseError(
        "FEDERAL_BOUNDED_ZIP_ENTRY_MISSING",
        `Required OOXML entry ${name} is missing.`,
      );
  return found;
}

async function openZip(bytes: Uint8Array): Promise<ZipFile> {
  const buffer = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return await new Promise((resolve, reject) => {
    yauzl.fromBuffer(
      buffer,
      { autoClose: false, lazyEntries: true, validateEntrySizes: true },
      (error, zip) => {
        if (error || !zip) reject(error ?? new Error("ZIP did not open."));
        else resolve(zip);
      },
    );
  });
}

async function readZipEntry(zip: ZipFile, entry: Entry): Promise<Buffer> {
  const stream = await new Promise<NodeJS.ReadableStream>((resolve, reject) => {
    zip.openReadStream(entry, (error, value) => {
      if (error || !value)
        reject(error ?? new Error(`Could not read ${entry.fileName}.`));
      else resolve(value);
    });
  });
  const chunks: Buffer[] = [];
  let length = 0;
  for await (const raw of stream) {
    const chunk = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
    length += chunk.byteLength;
    if (length > entry.uncompressedSize)
      throw parseError(
        "FEDERAL_BOUNDED_ZIP_SIZE_MISMATCH",
        `ZIP entry ${entry.fileName} exceeds its declared size.`,
      );
    chunks.push(chunk);
  }
  if (length !== entry.uncompressedSize)
    throw parseError(
      "FEDERAL_BOUNDED_ZIP_SIZE_MISMATCH",
      `ZIP entry ${entry.fileName} differs from its declared size.`,
    );
  return Buffer.concat(chunks, length);
}

function resolveWorkbookTarget(target: string): string {
  const withoutLeading = target.startsWith("/") ? target.slice(1) : target;
  const lexicalParts = withoutLeading.split("/");
  if (
    target.includes("\\") ||
    target.includes("\0") ||
    target.includes("?") ||
    target.includes("#") ||
    lexicalParts.some((part) => part === "" || part === "." || part === "..")
  )
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_PATH_UNSAFE",
      "Workbook relationship target is unsafe.",
    );
  const resolved = target.startsWith("/")
    ? withoutLeading
    : path.posix.join("xl", withoutLeading);
  if (!resolved.startsWith("xl/worksheets/"))
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_PATH_UNSAFE",
      "Workbook relationship target escapes xl/worksheets.",
    );
  return resolved;
}

function resolveWorksheetTarget(
  worksheetEntry: string,
  relationship: Relationship,
): string {
  const target = relationship.target;
  if (
    target.startsWith("/") ||
    target.includes("\\") ||
    target.includes("\0") ||
    target.includes("?") ||
    target.includes("#")
  )
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_PATH_UNSAFE",
      "Worksheet relationship target is unsafe.",
    );
  const parts = target.split("/");
  // Standard comments are ../commentsN.xml. Permit exactly one leading
  // parent step from xl/worksheets, never an escape-and-return path.
  if (
    parts.some(
      (part, index) =>
        part === "" || part === "." || (part === ".." && index !== 0),
    ) ||
    parts.filter((part) => part === "..").length > 1
  )
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_PATH_UNSAFE",
      "Worksheet relationship target traverses unexpectedly.",
    );
  const resolved = path.posix.normalize(
    path.posix.join(path.posix.dirname(worksheetEntry), target),
  );
  if (!resolved.startsWith("xl/") || resolved.includes("/../"))
    throw parseError(
      "FEDERAL_BOUNDED_RELATIONSHIP_PATH_UNSAFE",
      "Worksheet relationship target escapes xl.",
    );
  return resolved;
}

function required(entries: Map<string, Buffer>, name: string): Buffer {
  const value = entries.get(name);
  if (!value)
    throw parseError(
      "FEDERAL_BOUNDED_ZIP_ENTRY_MISSING",
      `Required OOXML entry ${name} is missing.`,
    );
  return value;
}

function assertSafeZipName(name: string): void {
  const lexical = name.endsWith("/") ? name.slice(0, -1) : name;
  if (
    !lexical ||
    name.includes("\\") ||
    name.includes("\0") ||
    name.startsWith("/") ||
    lexical
      .split("/")
      .some((part) => part === ".." || part === "." || part === "")
  )
    throw parseError(
      "FEDERAL_BOUNDED_ZIP_PATH_UNSAFE",
      "Workbook ZIP contains an unsafe entry path.",
    );
}

function parseStyleId(raw: string | undefined, address: string): number | null {
  if (raw === undefined) return null;
  if (!/^\d+$/.test(raw))
    throw parseError(
      "FEDERAL_BOUNDED_STYLE_INVALID",
      `Invalid style ID at ${address}.`,
    );
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 0)
    throw parseError(
      "FEDERAL_BOUNDED_STYLE_INVALID",
      `Invalid style ID at ${address}.`,
    );
  return value;
}

function xmlParser(): SaxesParser<{}> {
  return new SaxesParser({ xmlns: false });
}

function assertXmlTextSafe(bytes: Buffer): string {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  if (/<!DOCTYPE\b|<!ENTITY\b/i.test(text))
    throw parseError(
      "FEDERAL_BOUNDED_XML_DECLARATION_INVALID",
      "DOCTYPE and entity declarations are forbidden.",
    );
  return text;
}

function parseXml(parser: SaxesParser<{}>, bytes: Buffer): void {
  parser.write(assertXmlTextSafe(bytes));
  parser.close();
}

function xmlAttribute(node: SaxesTagPlain, name: string): string | undefined {
  const value = node.attributes[name];
  return typeof value === "string" ? value : undefined;
}

function localName(name: string): string {
  const separator = name.lastIndexOf(":");
  return separator < 0 ? name : name.slice(separator + 1);
}

function within(cell: CellAddress, range: CellRange): boolean {
  return (
    cell.row >= range.start.row &&
    cell.row <= range.end.row &&
    cell.col >= range.start.col &&
    cell.col <= range.end.col
  );
}

function rangeArea(range: CellRange): number {
  const rows = range.end.row - range.start.row + 1;
  const columns = range.end.col - range.start.col + 1;
  const area = rows * columns;
  if (!Number.isSafeInteger(area) || area < 1)
    throw limitError(
      "FEDERAL_BOUNDED_CARDINALITY_INVALID",
      "Bounded range cardinality is invalid.",
    );
  return area;
}

function safeAdd(left: number, right: number, code: string): number {
  const result = left + right;
  if (!Number.isSafeInteger(result) || result < 0)
    throw limitError(code, "Bounded resource arithmetic overflowed.");
  return result;
}

function fullyContained(candidate: CellRange, authority: CellRange): boolean {
  return (
    candidate.start.row >= authority.start.row &&
    candidate.start.col >= authority.start.col &&
    candidate.end.row <= authority.end.row &&
    candidate.end.col <= authority.end.col
  );
}

function compareCells(left: TidyCell, right: TidyCell): number {
  return left.row - right.row || left.col - right.col;
}

function canonicalA1(cell: CellAddress): string {
  return `${columnLetters(cell.col)}${cell.row}`;
}

function formatA1Range(range: CellRange): string {
  return `${canonicalA1(range.start)}:${canonicalA1(range.end)}`;
}

function columnLetters(column: number): string {
  let value = column;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function digestBytes(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function parseError(
  code: string,
  message: string,
): FederalDefendantsBoundedWorkbookError {
  return new FederalDefendantsBoundedWorkbookError(code, "parse", message);
}

function limitError(
  code: string,
  message: string,
): FederalDefendantsBoundedWorkbookError {
  return new FederalDefendantsBoundedWorkbookError(code, "limit", message);
}
