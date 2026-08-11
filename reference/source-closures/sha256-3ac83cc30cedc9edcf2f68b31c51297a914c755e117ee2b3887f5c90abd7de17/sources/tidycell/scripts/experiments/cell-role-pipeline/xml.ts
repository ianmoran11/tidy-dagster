import {
  expandRange,
  formatRange,
  parseCell,
  parseRange,
} from "../../../src/lib/address";
import type {
  CellRoleSketch,
  RelationshipKind,
  SketchCell,
  SketchDimension,
  SketchRelationship,
  SketchTable,
} from "./types";
import { RELATIONSHIP_KINDS } from "./types";

const MAX_XML_BYTES = 128 * 1024;
const MAX_NODES = 4096;
const MAX_DEPTH = 32;
const MAX_FIELD_LENGTH = 4096;
export const MAX_EXPANDED_SKETCH_CELLS = 100_000;
const KNOWN_TAGS = new Set([
  "cellrolesketch",
  "table",
  "values",
  "dimension",
  "cell",
  "relationship",
  "uncertainty",
]);

type XmlNode = {
  name: string;
  attrs: Record<string, string>;
  children: XmlNode[];
};

export type SketchParseResult =
  | { ok: true; sketch: CellRoleSketch; warnings: string[] }
  | { ok: false; code: string; message: string; warnings: string[] };

export function parseCellRoleSketch(
  raw: string,
  bounds?: { rowCount: number; columnCount: number },
): SketchParseResult {
  const warnings: string[] = [];
  try {
    if (Buffer.byteLength(raw, "utf8") > MAX_XML_BYTES) {
      throw failure("INPUT_TOO_LARGE", `XML exceeds ${MAX_XML_BYTES} bytes.`);
    }
    if (/<!\s*(?:DOCTYPE|ENTITY)\b/i.test(raw)) {
      throw failure(
        "UNSAFE_XML",
        "DOCTYPE and entity declarations are forbidden.",
      );
    }

    const starts = [
      ...raw.matchAll(/<\s*(?:[A-Za-z_][\w.-]*:)?CellRoleSketch\b/gi),
    ];
    const closes = [
      ...raw.matchAll(/<\/\s*(?:[A-Za-z_][\w.-]*:)?CellRoleSketch\s*>/gi),
    ];
    if (starts.length !== 1 || closes.length !== 1) {
      throw failure(
        "AMBIGUOUS_ROOT",
        "Exactly one CellRoleSketch root is required.",
      );
    }
    const start = starts[0].index ?? -1;
    const closeStart = closes[0].index ?? -1;
    if (start < 0 || closeStart < start) {
      throw failure(
        "MALFORMED_XML",
        "CellRoleSketch closing tag is missing or misplaced.",
      );
    }
    const xml = raw.slice(start, closeStart + closes[0][0].length);
    const root = scanXml(xml);
    assertExpansionBudget(root);
    const sketch = buildSketch(root, bounds, warnings);
    return { ok: true, sketch, warnings };
  } catch (error) {
    const parsed = error as Error & { code?: string };
    return {
      ok: false,
      code: parsed.code ?? "MALFORMED_XML",
      message: parsed.message,
      warnings,
    };
  }
}

function scanXml(xml: string): XmlNode {
  const tokenPattern =
    /<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|<\/[\s\S]*?>|<[^>]*>|[^<]+/g;
  const stack: XmlNode[] = [];
  let root: XmlNode | undefined;
  let cursor = 0;
  let nodeCount = 0;

  for (const match of xml.matchAll(tokenPattern)) {
    if ((match.index ?? -1) !== cursor) {
      throw failure("MALFORMED_XML", "Unrecognized XML syntax.");
    }
    cursor += match[0].length;
    const token = match[0];
    if (token.startsWith("<!--")) continue;
    if (token.startsWith("<?")) {
      throw failure(
        "UNSAFE_XML",
        "Processing instructions are forbidden inside the sketch.",
      );
    }
    if (token.startsWith("<![CDATA[")) {
      if (token.slice(9, -3).trim()) {
        throw failure(
          "MALFORMED_XML",
          "Text content is not allowed in the narrow sketch grammar.",
        );
      }
      continue;
    }
    if (!token.startsWith("<")) {
      if (token.trim()) {
        throw failure(
          "MALFORMED_XML",
          "Text content is not allowed; use attributes.",
        );
      }
      continue;
    }
    if (token.startsWith("</")) {
      const name = normalizeName(token.slice(2, -1).trim());
      const current = stack.pop();
      if (!current || current.name !== name) {
        throw failure("MALFORMED_XML", `Mismatched closing tag ${name}.`);
      }
      continue;
    }

    const selfClosing = /\/\s*>$/.test(token);
    const body = token
      .slice(1, selfClosing ? token.lastIndexOf("/") : -1)
      .trim();
    const nameMatch = /^(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)/.exec(body);
    if (!nameMatch) throw failure("MALFORMED_XML", "Invalid element name.");
    const name = nameMatch[1].toLowerCase();
    if (!KNOWN_TAGS.has(name)) {
      throw failure(
        "UNKNOWN_ELEMENT",
        `Unknown sketch element ${nameMatch[1]}.`,
      );
    }
    const attrs = parseAttributes(body.slice(nameMatch[0].length));
    const node: XmlNode = { name, attrs, children: [] };
    nodeCount += 1;
    if (nodeCount > MAX_NODES)
      throw failure("NODE_LIMIT", "Sketch has too many nodes.");
    if (stack.length >= MAX_DEPTH)
      throw failure("DEPTH_LIMIT", "Sketch is nested too deeply.");
    if (stack.length) stack.at(-1)?.children.push(node);
    else if (root)
      throw failure("AMBIGUOUS_ROOT", "Multiple XML roots are forbidden.");
    else root = node;
    if (!selfClosing) stack.push(node);
  }

  if (
    cursor !== xml.length ||
    stack.length ||
    !root ||
    root.name !== "cellrolesketch"
  ) {
    throw failure(
      "MALFORMED_XML",
      "Sketch XML is incomplete or has an invalid root.",
    );
  }
  return root;
}

function parseAttributes(source: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  const pattern = /\s+([A-Za-z_][\w.:-]*)\s*=\s*("[^"]*"|'[^']*')/gy;
  let cursor = 0;
  while (cursor < source.length) {
    pattern.lastIndex = cursor;
    const match = pattern.exec(source);
    if (!match) {
      if (!source.slice(cursor).trim()) break;
      throw failure("MALFORMED_XML", "Malformed or unquoted XML attribute.");
    }
    const name = normalizeName(match[1]);
    if (name in attrs)
      throw failure("DUPLICATE_FIELD", `Duplicate attribute ${name}.`);
    const value = decodeXml(match[2].slice(1, -1));
    if (value.length > MAX_FIELD_LENGTH)
      throw failure("FIELD_LIMIT", `${name} is too long.`);
    attrs[name] = value;
    cursor = pattern.lastIndex;
  }
  return attrs;
}

function decodeXml(value: string): string {
  let decoded = "";
  let cursor = 0;
  const entities = /&(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-f]+);/gi;
  for (const match of value.matchAll(entities)) {
    const index = match.index ?? 0;
    const literal = value.slice(cursor, index);
    if (literal.includes("&")) {
      throw failure("UNSAFE_XML", "Unknown or unterminated entity reference.");
    }
    decoded += literal;
    const entity = match[0].toLowerCase();
    const named: Record<string, string> = {
      "&amp;": "&",
      "&lt;": "<",
      "&gt;": ">",
      "&quot;": '"',
      "&apos;": "'",
    };
    if (named[entity]) {
      decoded += named[entity];
    } else {
      const codePoint = entity.startsWith("&#x")
        ? Number.parseInt(entity.slice(3, -1), 16)
        : Number.parseInt(entity.slice(2, -1), 10);
      if (
        !Number.isSafeInteger(codePoint) ||
        codePoint < 0 ||
        codePoint > 0x10ffff
      ) {
        throw failure("UNSAFE_XML", "Invalid numeric character reference.");
      }
      decoded += String.fromCodePoint(codePoint);
    }
    cursor = index + match[0].length;
  }
  const remainder = value.slice(cursor);
  if (remainder.includes("&")) {
    throw failure("UNSAFE_XML", "Unknown or unterminated entity reference.");
  }
  return decoded + remainder;
}

function buildSketch(
  root: XmlNode,
  bounds: { rowCount: number; columnCount: number } | undefined,
  warnings: string[],
): CellRoleSketch {
  const version = required(root, "version");
  const sheet = required(root, "sheet");
  if (version !== "0.1")
    throw failure("INVALID_VERSION", "Sketch version must be 0.1.");
  const tables = root.children
    .filter((node) => node.name === "table")
    .map((node) => buildTable(node, bounds));
  const uncertaintyNodes = root.children.filter(
    (node) => node.name === "uncertainty",
  );
  if (
    root.children.some(
      (node) => node.name !== "table" && node.name !== "uncertainty",
    )
  ) {
    throw failure(
      "INVALID_STRUCTURE",
      "Only Table and Uncertainty may be root children.",
    );
  }
  if (!tables.length)
    throw failure("BLANK_REQUIRED_FIELD", "At least one table is required.");
  const uncertainties = uncertaintyNodes.map((node) => ({
    id: required(node, "id"),
    evidence: required(node, "evidence"),
  }));
  assertUniqueIds(tables, uncertainties);
  if (uncertainties.length) {
    throw failure(
      "UNRESOLVED_UNCERTAINTY",
      "Sketch contains unresolved uncertainties.",
    );
  }
  if (warnings.length) warnings.sort();
  return { version: "0.1", sheet, tables, uncertainties };
}

function buildTable(
  node: XmlNode,
  bounds?: { rowCount: number; columnCount: number },
): SketchTable {
  const valuesNodes = node.children.filter((child) => child.name === "values");
  if (valuesNodes.length !== 1)
    throw failure(
      "INVALID_STRUCTURE",
      "Each table needs exactly one Values element.",
    );
  const dimensionNodes = node.children.filter(
    (child) => child.name === "dimension",
  );
  const relationshipNodes = node.children.filter(
    (child) => child.name === "relationship",
  );
  if (
    node.children.some(
      (child) => !["values", "dimension", "relationship"].includes(child.name),
    )
  ) {
    throw failure("INVALID_STRUCTURE", "Invalid table child element.");
  }
  const values = buildCells(valuesNodes[0], bounds);
  if (!values.length)
    throw failure("BLANK_REQUIRED_FIELD", "Values must contain cells.");
  const dimensions = dimensionNodes.map((dimension) =>
    buildDimension(dimension, bounds),
  );
  if (!dimensions.length)
    throw failure(
      "BLANK_REQUIRED_FIELD",
      "A table needs at least one dimension.",
    );
  const relationships = relationshipNodes.map(buildRelationship);
  const dimensionIds = new Set(dimensions.map((dimension) => dimension.id));
  if (
    relationships.length !== dimensions.length ||
    relationships.some((relation) => !dimensionIds.has(relation.dimensionId))
  ) {
    throw failure(
      "INVALID_RELATIONSHIP",
      "Each dimension must have exactly one relationship.",
    );
  }
  if (
    new Set(relationships.map((relation) => relation.dimensionId)).size !==
    dimensions.length
  ) {
    throw failure(
      "INVALID_RELATIONSHIP",
      "Duplicate or missing dimension relationship.",
    );
  }
  const boundary = required(node, "boundary").toUpperCase();
  const parsedBoundary = parseRange(boundary);
  assertRangeBounds(parsedBoundary, bounds, boundary);
  const addresses = [
    ...values,
    ...dimensions.flatMap((dimension) => dimension.cells),
  ].map((cell) => cell.address);
  const boundaryExtents = addresses.reduce(
    (extent, address) => {
      const cell = parseCell(address);
      return {
        minRow: Math.min(extent.minRow, cell.row),
        minCol: Math.min(extent.minCol, cell.col),
        maxRow: Math.max(extent.maxRow, cell.row),
        maxCol: Math.max(extent.maxCol, cell.col),
      };
    },
    {
      minRow: Number.POSITIVE_INFINITY,
      minCol: Number.POSITIVE_INFINITY,
      maxRow: 0,
      maxCol: 0,
    },
  );
  const actualBoundary = formatRange({
    start: { row: boundaryExtents.minRow, col: boundaryExtents.minCol },
    end: { row: boundaryExtents.maxRow, col: boundaryExtents.maxCol },
  });
  if (actualBoundary !== boundary)
    throw failure(
      "INVALID_BOUNDARY",
      `Table boundary ${boundary} does not exactly match role cells ${actualBoundary}.`,
    );
  return {
    id: required(node, "id"),
    name: required(node, "name"),
    boundary,
    evidence: required(node, "evidence"),
    valueName: required(valuesNodes[0], "name"),
    values,
    dimensions,
    relationships,
  };
}

function buildDimension(
  node: XmlNode,
  bounds?: { rowCount: number; columnCount: number },
): SketchDimension {
  const cells = buildCells(node, bounds);
  if (!cells.length)
    throw failure("BLANK_REQUIRED_FIELD", "Dimension must contain cells.");
  return {
    id: required(node, "id"),
    name: required(node, "name"),
    evidence: required(node, "evidence"),
    cells,
  };
}

function buildRelationship(node: XmlNode): SketchRelationship {
  const kind = required(node, "kind");
  if (!RELATIONSHIP_KINDS.includes(kind as RelationshipKind)) {
    throw failure("INVALID_RELATIONSHIP", `Invalid relationship kind ${kind}.`);
  }
  return {
    id: required(node, "id"),
    dimensionId: required(node, "dimensionid"),
    kind: kind as RelationshipKind,
    evidence: required(node, "evidence"),
  };
}

function buildCells(
  parent: XmlNode,
  bounds?: { rowCount: number; columnCount: number },
): SketchCell[] {
  if (parent.children.some((child) => child.name !== "cell")) {
    throw failure("INVALID_STRUCTURE", "Only Cell elements are allowed here.");
  }
  const rangeCount = parent.children.filter((node) =>
    Boolean(node.attrs.range?.trim()),
  ).length;
  const addressCount = parent.children.filter((node) =>
    Boolean(node.attrs.address?.trim()),
  ).length;
  if (rangeCount > 0 && (rangeCount !== 1 || addressCount > 0)) {
    throw failure(
      "UNREPRESENTABLE_SELECTOR",
      "Values and dimensions must use exactly one range Cell or only individual address Cells.",
    );
  }
  const cells = parent.children.flatMap<SketchCell>((node) => {
    const id = required(node, "id");
    const evidence = required(node, "evidence");
    const addressInput = node.attrs.address?.trim();
    const rangeInput = node.attrs.range?.trim();
    if (Boolean(addressInput) === Boolean(rangeInput)) {
      throw failure(
        "INVALID_SELECTOR",
        "Each Cell must contain exactly one address or range attribute.",
      );
    }
    if (addressInput) {
      const address = addressInput.toUpperCase();
      const parsed = parseCell(address);
      assertCellBounds(parsed, bounds, address);
      return [
        {
          id,
          address,
          evidence,
          selector: { kind: "address", value: address },
        },
      ];
    }

    const range = rangeInput!.toUpperCase();
    const parsedRange = parseRange(range);
    assertRangeBounds(parsedRange, bounds, range);
    const canonicalRange = formatRange(parsedRange);
    if (canonicalRange !== range) {
      throw failure(
        "INVALID_SELECTOR",
        `Range ${range} is not canonical R1C1 (${canonicalRange}).`,
      );
    }
    return expandRange(range).map((address) => ({
      id: `${id}:${address}`,
      address,
      evidence,
      selector: { kind: "range", value: range },
    }));
  });
  if (new Set(cells.map((cell) => cell.address)).size !== cells.length) {
    throw failure("DUPLICATE_CELL", "Role selectors contain duplicate cells.");
  }
  return cells;
}

function assertExpansionBudget(root: XmlNode): void {
  let expandedCells = 0;
  const visit = (node: XmlNode): void => {
    if (node.name === "cell") {
      const address = node.attrs.address?.trim();
      const range = node.attrs.range?.trim();
      if (Boolean(address) !== Boolean(range)) {
        if (address) {
          expandedCells += 1;
        } else if (range) {
          const parsed = parseRange(range.toUpperCase());
          expandedCells +=
            (parsed.end.row - parsed.start.row + 1) *
            (parsed.end.col - parsed.start.col + 1);
        }
        if (expandedCells > MAX_EXPANDED_SKETCH_CELLS) {
          throw failure(
            "EXPANSION_LIMIT",
            `Sketch expands to more than ${MAX_EXPANDED_SKETCH_CELLS} cells.`,
          );
        }
      }
    }
    node.children.forEach(visit);
  };
  visit(root);
}

function assertCellBounds(
  cell: ReturnType<typeof parseCell>,
  bounds: { rowCount: number; columnCount: number } | undefined,
  input: string,
): void {
  if (bounds && (cell.row > bounds.rowCount || cell.col > bounds.columnCount)) {
    throw failure(
      "ADDRESS_OUT_OF_BOUNDS",
      `${input} is outside the summarized sheet.`,
    );
  }
}

function assertRangeBounds(
  range: ReturnType<typeof parseRange>,
  bounds: { rowCount: number; columnCount: number } | undefined,
  input: string,
): void {
  if (
    bounds &&
    (range.end.row > bounds.rowCount || range.end.col > bounds.columnCount)
  ) {
    throw failure(
      "ADDRESS_OUT_OF_BOUNDS",
      `${input} is outside the summarized sheet.`,
    );
  }
}

function assertUniqueIds(
  tables: SketchTable[],
  uncertainties: Array<{ id: string }>,
): void {
  const ids = [
    ...tables.flatMap((table) => [
      table.id,
      ...table.values.map((cell) => cell.id),
      ...table.dimensions.flatMap((dimension) => [
        dimension.id,
        ...dimension.cells.map((cell) => cell.id),
      ]),
      ...table.relationships.map((relationship) => relationship.id),
    ]),
    ...uncertainties.map((entry) => entry.id),
  ];
  if (new Set(ids).size !== ids.length)
    throw failure("DUPLICATE_ID", "All sketch IDs must be globally unique.");
}

function required(node: XmlNode, name: string): string {
  const value = node.attrs[name]?.trim();
  if (!value)
    throw failure("BLANK_REQUIRED_FIELD", `${node.name}.${name} is required.`);
  return value;
}

function normalizeName(name: string): string {
  return name.split(":").at(-1)?.toLowerCase() ?? name.toLowerCase();
}

function failure(code: string, message: string): Error & { code: string } {
  return Object.assign(new Error(message), { code });
}
