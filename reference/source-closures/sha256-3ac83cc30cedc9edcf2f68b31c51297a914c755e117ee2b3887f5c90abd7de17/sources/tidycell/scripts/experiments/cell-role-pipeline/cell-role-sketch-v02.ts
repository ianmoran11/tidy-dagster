import {
  expandRange,
  formatRange,
  parseCell,
  parseRange,
} from "../../../src/lib/address";
import {
  validateCellRoleSketchGeometry,
  type CellRoleGeometryOptions,
  type GeometryDiagnostic,
} from "./geometry-v02";
import { RELATIONSHIP_KINDS, type RelationshipKind } from "./types";

export const CELL_ROLE_SKETCH_V02 = "0.2" as const;
export const MAX_CELL_ROLE_SKETCH_V02_BYTES = 128 * 1024;
export const MAX_CELL_ROLE_SKETCH_V02_NODES = 4096;
export const MAX_CELL_ROLE_SKETCH_V02_DEPTH = 32;
export const MAX_CELL_ROLE_SKETCH_V02_FIELD_LENGTH = 4096;
export const MAX_CELL_ROLE_SKETCH_V02_TABLES = 64;
export const MAX_CELL_ROLE_SKETCH_V02_DIMENSIONS = 512;
export const MAX_CELL_ROLE_SKETCH_V02_DIMENSIONS_PER_TABLE = 128;
export const MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS = 100_000;

export const UNCERTAINTY_FIELDS = [
  "selector",
  "dimension",
  "table",
  "relationship",
  "evidence",
] as const;
export type SketchUncertaintyFieldV02 = (typeof UNCERTAINTY_FIELDS)[number];

export type SketchSourceSelectorV02 =
  | { kind: "address"; value: string }
  | { kind: "range"; value: string };

export type SketchCellSourceV02 = {
  id: string;
  selector: SketchSourceSelectorV02;
  evidence?: string;
};

export type SketchRoleSelectorV02 = {
  sources: SketchCellSourceV02[];
  addresses: string[];
};

export type SketchValuesV02 = SketchRoleSelectorV02 & {
  id: string;
  name: string;
  evidence?: string;
};

export type SketchDimensionV02 = SketchRoleSelectorV02 & {
  id: string;
  name: string;
  evidence: string;
};

export type SketchRelationshipV02 = {
  id: string;
  dimensionId: string;
  kind: RelationshipKind;
  evidence: string;
};

export type SketchTableV02 = {
  id: string;
  name: string;
  evidence: string;
  selectorBounds: string;
  physicalExtent?: string;
  values: SketchValuesV02;
  dimensions: SketchDimensionV02[];
  relationships: SketchRelationshipV02[];
};

export type SketchUncertaintyV02 = {
  id: string;
  target: string;
  field: SketchUncertaintyFieldV02;
  alternatives: string[];
  evidence: string;
  blocking: boolean;
};

export type CellRoleSketchV02 = {
  version: typeof CELL_ROLE_SKETCH_V02;
  sheet: string;
  tables: SketchTableV02[];
  uncertainties: SketchUncertaintyV02[];
};

export type CellRoleSketchV02ParseResult =
  | {
      ok: true;
      sketch: CellRoleSketchV02;
      canonical: string;
      warnings: string[];
    }
  | {
      ok: false;
      code: string;
      message: string;
      warnings: string[];
      diagnostics?: GeometryDiagnostic[];
    };

export type CellRoleSketchV02CompilationResult =
  | { ok: true }
  | { ok: false; code: "BLOCKING_UNCERTAINTY"; message: string };

export type CellRoleSketchSheetBounds = {
  rowCount: number;
  columnCount: number;
};
type SheetBounds = CellRoleSketchSheetBounds;
type XmlNode = {
  name: string;
  attrs: Record<string, string>;
  children: XmlNode[];
};

const STABLE_ID = /^[a-z][a-z0-9-]{0,79}$/;
const CANONICAL_CELL = /^R[1-9]\d*C[1-9]\d*$/;
const CANONICAL_RANGE = /^R[1-9]\d*C[1-9]\d*:R[1-9]\d*C[1-9]\d*$/;
const STRUCTURAL_UNCERTAINTY_FIELDS = new Set<SketchUncertaintyFieldV02>([
  "selector",
  "dimension",
  "table",
  "relationship",
]);
const ELEMENTS = new Set([
  "CellRoleSketch",
  "Table",
  "Values",
  "Dimension",
  "Cell",
  "Relationship",
  "Uncertainty",
]);
const ATTRIBUTES: Record<string, ReadonlySet<string>> = {
  CellRoleSketch: new Set(["version", "sheet"]),
  Table: new Set(["id", "name", "evidence", "physicalExtent"]),
  Values: new Set(["id", "name", "evidence"]),
  Dimension: new Set(["id", "name", "evidence"]),
  Cell: new Set(["id", "address", "range", "evidence"]),
  Relationship: new Set(["id", "dimensionId", "kind", "evidence"]),
  Uncertainty: new Set([
    "id",
    "target",
    "field",
    "alternatives",
    "evidence",
    "blocking",
  ]),
};

/** The historical v0.1 parser remains in xml.ts and is intentionally unchanged. */
export { parseCellRoleSketch as parseCellRoleSketchV01 } from "./xml";

export function parseCellRoleSketchV02(
  raw: string,
  bounds?: SheetBounds,
  geometryOptions?: CellRoleGeometryOptions,
): CellRoleSketchV02ParseResult {
  const warnings: string[] = [];
  try {
    if (Buffer.byteLength(raw, "utf8") > MAX_CELL_ROLE_SKETCH_V02_BYTES) {
      throw failure(
        "INPUT_TOO_LARGE",
        `XML exceeds ${MAX_CELL_ROLE_SKETCH_V02_BYTES} bytes.`,
      );
    }
    assertBounds(bounds);
    const root = scanXml(raw);
    assertExpansionBudget(root);
    const sketch = buildSketch(root, bounds);
    const canonical = serializeValidatedSketch(sketch);
    if (geometryOptions) {
      const geometry = validateCellRoleSketchGeometry(sketch, geometryOptions);
      warnings.push(
        ...geometry.diagnostics
          .filter((diagnostic) => diagnostic.severity === "warning")
          .map((diagnostic) => `${diagnostic.code}: ${diagnostic.message}`),
      );
      if (!geometry.valid) {
        const first = geometry.diagnostics.find(
          (diagnostic) => diagnostic.severity === "error",
        )!;
        throw geometryFailure(first.code, first.message, geometry.diagnostics);
      }
    }
    return {
      ok: true,
      sketch,
      canonical,
      warnings,
    };
  } catch (error) {
    const parsed = error as Error & {
      code?: string;
      diagnostics?: GeometryDiagnostic[];
    };
    return {
      ok: false,
      code: parsed.code ?? "MALFORMED_XML",
      message: parsed.message,
      warnings,
      ...(parsed.diagnostics ? { diagnostics: parsed.diagnostics } : {}),
    };
  }
}

export function serializeCellRoleSketchV02(
  sketch: CellRoleSketchV02,
  bounds: SheetBounds,
): string {
  const canonical = serializeValidatedSketch(sketch);
  const reparsed = parseCellRoleSketchV02(canonical, bounds);
  if (!reparsed.ok) {
    throw failure(
      "INVALID_SKETCH_OBJECT",
      `Sketch object does not satisfy v0.2: ${reparsed.code}: ${reparsed.message}`,
    );
  }
  if (JSON.stringify(reparsed.sketch) !== JSON.stringify(sketch)) {
    throw failure(
      "INVALID_SKETCH_OBJECT",
      "Sketch object contains noncanonical or inconsistent derived content.",
    );
  }
  return canonical;
}

export function validateCellRoleSketchV02ForCompilation(
  sketch: CellRoleSketchV02,
): CellRoleSketchV02CompilationResult {
  const blocking = sketch.uncertainties.filter(
    (entry) => entry.blocking && STRUCTURAL_UNCERTAINTY_FIELDS.has(entry.field),
  );
  if (!blocking.length) return { ok: true };
  return {
    ok: false,
    code: "BLOCKING_UNCERTAINTY",
    message: `Blocking structural uncertainty remains: ${blocking
      .map((entry) => `${entry.id}:${entry.target}.${entry.field}`)
      .join(", ")}.`,
  };
}

function scanXml(raw: string): XmlNode {
  const stack: XmlNode[] = [];
  let root: XmlNode | undefined;
  let completedRoot = false;
  let cursor = 0;
  let nodeCount = 0;

  while (cursor < raw.length) {
    const next = raw.indexOf("<", cursor);
    if (next < 0) {
      assertText(raw.slice(cursor), stack.length > 0);
      break;
    }
    assertText(raw.slice(cursor, next), stack.length > 0);
    cursor = next;

    if (raw.startsWith("<!--", cursor)) {
      const end = raw.indexOf("-->", cursor + 4);
      if (end < 0) throw failure("MALFORMED_XML", "Unclosed XML comment.");
      cursor = end + 3;
      continue;
    }
    if (raw.startsWith("<?", cursor)) {
      throw failure("UNSAFE_XML", "Processing instructions are forbidden.");
    }
    if (raw.startsWith("<!", cursor)) {
      throw failure(
        "UNSAFE_XML",
        "DTD, entity declarations, CDATA, and declarations are forbidden.",
      );
    }

    const { token, end } = readTag(raw, cursor);
    cursor = end;
    if (token.startsWith("</")) {
      const close = /^<\/([A-Za-z_][\w.-]*)\s*>$/.exec(token);
      if (!close) throw failure("MALFORMED_XML", "Malformed closing tag.");
      const current = stack.pop();
      if (!current || current.name !== close[1]) {
        throw failure("MALFORMED_XML", `Mismatched closing tag ${close[1]}.`);
      }
      if (!stack.length) completedRoot = true;
      continue;
    }

    const selfClosing = /\/\s*>$/.test(token);
    const body = token
      .slice(1, selfClosing ? token.lastIndexOf("/") : -1)
      .trim();
    const nameMatch = /^([A-Za-z_][\w.-]*)/.exec(body);
    if (!nameMatch) throw failure("MALFORMED_XML", "Invalid element name.");
    const name = nameMatch[1];
    if (!ELEMENTS.has(name)) {
      throw failure("UNKNOWN_ELEMENT", `Unknown sketch element ${name}.`);
    }
    if (!stack.length && (root || completedRoot) && name === "CellRoleSketch") {
      throw failure("AMBIGUOUS_ROOT", "Multiple sketch roots are forbidden.");
    }
    if (!stack.length && name !== "CellRoleSketch") {
      throw failure(
        "INVALID_STRUCTURE",
        "Only CellRoleSketch may be a document root.",
      );
    }

    const attrs = parseAttributes(body.slice(nameMatch[0].length));
    assertAllowedAttributes(name, attrs);
    const node: XmlNode = { name, attrs, children: [] };
    nodeCount += 1;
    if (nodeCount > MAX_CELL_ROLE_SKETCH_V02_NODES) {
      throw failure("NODE_LIMIT", "Sketch has too many nodes.");
    }
    if (stack.length >= MAX_CELL_ROLE_SKETCH_V02_DEPTH) {
      throw failure("DEPTH_LIMIT", "Sketch is nested too deeply.");
    }
    if (stack.length) stack.at(-1)!.children.push(node);
    else root = node;
    if (!selfClosing) stack.push(node);
    else if (!stack.length) completedRoot = true;
  }

  if (stack.length || !root || root.name !== "CellRoleSketch") {
    throw failure(
      "MALFORMED_XML",
      "Sketch XML is incomplete or has an invalid root.",
    );
  }
  return root;
}

function readTag(raw: string, start: number): { token: string; end: number } {
  let quote: '"' | "'" | null = null;
  for (let index = start + 1; index < raw.length; index += 1) {
    const char = raw[index];
    if (quote) {
      if (char === "<") {
        throw failure(
          "MALFORMED_XML",
          "Raw '<' is forbidden inside an XML attribute; use &lt;.",
        );
      }
      if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }
    if (char === "<") {
      throw failure("MALFORMED_XML", "Unexpected '<' inside an XML tag.");
    }
    if (char === ">") {
      return { token: raw.slice(start, index + 1), end: index + 1 };
    }
  }
  throw failure(
    "MALFORMED_XML",
    quote ? "Unclosed quoted XML attribute." : "Unclosed XML tag.",
  );
}

function parseAttributes(source: string): Record<string, string> {
  const attrs = Object.create(null) as Record<string, string>;
  const pattern = /\s+([A-Za-z_][\w.-]*)\s*=\s*("[^"]*"|'[^']*')/gy;
  let cursor = 0;
  while (cursor < source.length) {
    pattern.lastIndex = cursor;
    const match = pattern.exec(source);
    if (!match) {
      if (!source.slice(cursor).trim()) break;
      throw failure("MALFORMED_XML", "Malformed or unquoted XML attribute.");
    }
    const name = match[1];
    if (Object.hasOwn(attrs, name)) {
      throw failure("DUPLICATE_FIELD", `Duplicate attribute ${name}.`);
    }
    const value = decodeXml(match[2].slice(1, -1));
    if (value.length > MAX_CELL_ROLE_SKETCH_V02_FIELD_LENGTH) {
      throw failure("FIELD_LIMIT", `${name} is too long.`);
    }
    attrs[name] = value;
    cursor = pattern.lastIndex;
  }
  return attrs;
}

function assertAllowedAttributes(
  element: string,
  attrs: Record<string, string>,
): void {
  const allowed = ATTRIBUTES[element];
  for (const name of Object.keys(attrs)) {
    if (!allowed.has(name)) {
      throw failure(
        "UNKNOWN_ATTRIBUTE",
        `${element}.${name} is not part of CellRoleSketch v0.2.`,
      );
    }
  }
}

function decodeXml(value: string): string {
  let decoded = "";
  let cursor = 0;
  const entities = /&(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);/g;
  for (const match of value.matchAll(entities)) {
    const index = match.index ?? 0;
    const literal = value.slice(cursor, index);
    if (literal.includes("&")) {
      throw failure("UNSAFE_XML", "Unknown or unterminated entity reference.");
    }
    decoded += literal;
    const entity = match[0];
    const named: Record<string, string> = {
      "&amp;": "&",
      "&lt;": "<",
      "&gt;": ">",
      "&quot;": '"',
      "&apos;": "'",
    };
    if (named[entity]) decoded += named[entity];
    else {
      const hexadecimal = entity.startsWith("&#x");
      const codePoint = Number.parseInt(
        entity.slice(hexadecimal ? 3 : 2, -1),
        hexadecimal ? 16 : 10,
      );
      if (
        !Number.isSafeInteger(codePoint) ||
        codePoint <= 0 ||
        codePoint > 0x10ffff ||
        (codePoint >= 0xd800 && codePoint <= 0xdfff)
      ) {
        throw failure("UNSAFE_XML", "Invalid numeric character reference.");
      }
      decoded += String.fromCodePoint(codePoint);
    }
    cursor = index + entity.length;
  }
  const remainder = value.slice(cursor);
  if (remainder.includes("&")) {
    throw failure("UNSAFE_XML", "Unknown or unterminated entity reference.");
  }
  return decoded + remainder;
}

function buildSketch(root: XmlNode, bounds?: SheetBounds): CellRoleSketchV02 {
  assertChildren(root, ["Table", "Uncertainty"]);
  const version = required(root, "version");
  if (version !== CELL_ROLE_SKETCH_V02) {
    throw failure("INVALID_VERSION", "Sketch version must be 0.2.");
  }
  const sheet = required(root, "sheet");
  const tableNodes = root.children.filter((child) => child.name === "Table");
  if (!tableNodes.length) {
    throw failure("BLANK_REQUIRED_FIELD", "At least one table is required.");
  }
  if (tableNodes.length > MAX_CELL_ROLE_SKETCH_V02_TABLES) {
    throw failure(
      "TABLE_LIMIT",
      `Sketch exceeds ${MAX_CELL_ROLE_SKETCH_V02_TABLES} tables.`,
    );
  }
  const totalDimensions = tableNodes.reduce(
    (total, table) =>
      total +
      table.children.filter((child) => child.name === "Dimension").length,
    0,
  );
  if (totalDimensions > MAX_CELL_ROLE_SKETCH_V02_DIMENSIONS) {
    throw failure(
      "DIMENSION_LIMIT",
      `Sketch exceeds ${MAX_CELL_ROLE_SKETCH_V02_DIMENSIONS} dimensions.`,
    );
  }
  const tables = tableNodes.map((node) => buildTable(node, bounds));
  const uncertainties = root.children
    .filter((child) => child.name === "Uncertainty")
    .map(buildUncertainty);
  assertUniqueIds(tables, uncertainties);
  assertUncertaintyTargets(tables, uncertainties);
  assertOutputNames(tables);
  assertRoleConsistency(tables);
  return { version: CELL_ROLE_SKETCH_V02, sheet, tables, uncertainties };
}

function buildTable(node: XmlNode, bounds?: SheetBounds): SketchTableV02 {
  assertChildren(node, ["Values", "Dimension", "Relationship"]);
  const valuesNodes = node.children.filter((child) => child.name === "Values");
  if (valuesNodes.length !== 1) {
    throw failure(
      "INVALID_STRUCTURE",
      "Each table needs exactly one Values element.",
    );
  }
  const dimensionNodes = node.children.filter(
    (child) => child.name === "Dimension",
  );
  if (!dimensionNodes.length) {
    throw failure(
      "BLANK_REQUIRED_FIELD",
      "A table needs at least one dimension.",
    );
  }
  if (dimensionNodes.length > MAX_CELL_ROLE_SKETCH_V02_DIMENSIONS_PER_TABLE) {
    throw failure(
      "DIMENSION_LIMIT",
      `Table exceeds ${MAX_CELL_ROLE_SKETCH_V02_DIMENSIONS_PER_TABLE} dimensions.`,
    );
  }
  const values = buildValues(valuesNodes[0], bounds);
  const dimensions = dimensionNodes.map((child) =>
    buildDimension(child, bounds),
  );
  const relationships = node.children
    .filter((child) => child.name === "Relationship")
    .map(buildRelationship);
  const dimensionIds = new Set(dimensions.map((dimension) => dimension.id));
  if (
    relationships.length !== dimensions.length ||
    relationships.some(
      (relationship) => !dimensionIds.has(relationship.dimensionId),
    ) ||
    new Set(relationships.map((relationship) => relationship.dimensionId))
      .size !== dimensions.length
  ) {
    throw failure(
      "INVALID_RELATIONSHIP",
      "Each dimension must have exactly one relationship.",
    );
  }

  const selectorBounds = boundingRange([
    ...values.addresses,
    ...dimensions.flatMap((dimension) => dimension.addresses),
  ]);
  const physicalInput = optional(node, "physicalExtent");
  let physicalExtent: string | undefined;
  if (physicalInput) {
    physicalExtent = canonicalRange(physicalInput, bounds);
    if (!rangeContains(physicalExtent, selectorBounds)) {
      throw failure(
        "PHYSICAL_EXTENT_EXCLUDES_ROLES",
        `Physical extent ${physicalExtent} does not contain selector bounds ${selectorBounds}.`,
      );
    }
  }
  return {
    id: stableId(node, "id"),
    name: required(node, "name"),
    evidence: required(node, "evidence"),
    selectorBounds,
    ...(physicalExtent ? { physicalExtent } : {}),
    values,
    dimensions,
    relationships,
  };
}

function buildValues(node: XmlNode, bounds?: SheetBounds): SketchValuesV02 {
  assertChildren(node, ["Cell"]);
  const selector = buildSelector(node, bounds);
  return {
    id: stableId(node, "id"),
    name: required(node, "name"),
    ...(optional(node, "evidence")
      ? { evidence: optional(node, "evidence") }
      : {}),
    ...selector,
  };
}

function buildDimension(
  node: XmlNode,
  bounds?: SheetBounds,
): SketchDimensionV02 {
  assertChildren(node, ["Cell"]);
  return {
    id: stableId(node, "id"),
    name: required(node, "name"),
    evidence: required(node, "evidence"),
    ...buildSelector(node, bounds),
  };
}

function buildRelationship(node: XmlNode): SketchRelationshipV02 {
  assertLeaf(node);
  const kind = required(node, "kind");
  if (!RELATIONSHIP_KINDS.includes(kind as RelationshipKind)) {
    throw failure("INVALID_RELATIONSHIP", `Invalid relationship kind ${kind}.`);
  }
  return {
    id: stableId(node, "id"),
    dimensionId: stableAttribute(node, "dimensionId"),
    kind: kind as RelationshipKind,
    evidence: required(node, "evidence"),
  };
}

function buildUncertainty(node: XmlNode): SketchUncertaintyV02 {
  assertLeaf(node);
  const field = required(node, "field");
  if (!UNCERTAINTY_FIELDS.includes(field as SketchUncertaintyFieldV02)) {
    throw failure("INVALID_UNCERTAINTY", `Unknown uncertainty field ${field}.`);
  }
  const blockingInput = required(node, "blocking");
  if (blockingInput !== "true" && blockingInput !== "false") {
    throw failure(
      "INVALID_UNCERTAINTY",
      "Uncertainty.blocking must be true or false.",
    );
  }
  const alternatives = required(node, "alternatives")
    .split("|")
    .map((entry) => entry.trim());
  if (
    alternatives.length < 2 ||
    alternatives.some((entry) => !entry) ||
    new Set(alternatives).size !== alternatives.length
  ) {
    throw failure(
      "INVALID_UNCERTAINTY",
      "Uncertainty alternatives need at least two distinct nonblank choices separated by '|'.",
    );
  }
  return {
    id: stableId(node, "id"),
    target: stableAttribute(node, "target"),
    field: field as SketchUncertaintyFieldV02,
    alternatives,
    evidence: required(node, "evidence"),
    blocking: blockingInput === "true",
  };
}

function buildSelector(
  node: XmlNode,
  bounds?: SheetBounds,
): SketchRoleSelectorV02 {
  const cellNodes = node.children;
  if (!cellNodes.length) {
    throw failure("BLANK_REQUIRED_FIELD", `${node.name} must contain cells.`);
  }
  if (
    cellNodes.some(
      (cell) =>
        Object.hasOwn(cell.attrs, "address") ===
        Object.hasOwn(cell.attrs, "range"),
    )
  ) {
    throw failure(
      "INVALID_SELECTOR",
      "Each Cell must contain exactly one address or range attribute.",
    );
  }
  const rangeCount = cellNodes.filter((cell) =>
    Object.hasOwn(cell.attrs, "range"),
  ).length;
  const addressCount = cellNodes.filter((cell) =>
    Object.hasOwn(cell.attrs, "address"),
  ).length;
  if (rangeCount && (rangeCount !== 1 || addressCount)) {
    throw failure(
      "UNREPRESENTABLE_SELECTOR",
      "Values and dimensions must use exactly one range Cell or only individual address Cells.",
    );
  }
  if (!rangeCount && addressCount !== cellNodes.length) {
    throw failure(
      "INVALID_SELECTOR",
      "Each Cell must contain exactly one address or range attribute.",
    );
  }
  const sources = cellNodes.map((cell): SketchCellSourceV02 => {
    assertLeaf(cell);
    const id = stableId(cell, "id");
    const hasAddress = Object.hasOwn(cell.attrs, "address");
    const hasRange = Object.hasOwn(cell.attrs, "range");
    if (hasAddress === hasRange) {
      throw failure(
        "INVALID_SELECTOR",
        "Each Cell must contain exactly one address or range attribute.",
      );
    }
    const address = hasAddress ? required(cell, "address") : undefined;
    const range = hasRange ? required(cell, "range") : undefined;
    if (Boolean(address) === Boolean(range)) {
      throw failure(
        "INVALID_SELECTOR",
        "Each Cell must contain exactly one address or range attribute.",
      );
    }
    const selector: SketchSourceSelectorV02 = address
      ? { kind: "address", value: canonicalCell(address, bounds) }
      : { kind: "range", value: canonicalRange(range!, bounds) };
    const evidence = optional(cell, "evidence");
    return { id, selector, ...(evidence ? { evidence } : {}) };
  });
  const addresses = sources.flatMap((source) =>
    source.selector.kind === "range"
      ? expandRange(source.selector.value)
      : [source.selector.value],
  );
  if (new Set(addresses).size !== addresses.length) {
    throw failure("DUPLICATE_CELL", "Role selectors contain duplicate cells.");
  }
  return { sources, addresses };
}

function assertExpansionBudget(root: XmlNode): void {
  let expanded = 0;
  const visit = (node: XmlNode): void => {
    if (node.name === "Cell") {
      const hasAddress = Object.hasOwn(node.attrs, "address");
      const hasRange = Object.hasOwn(node.attrs, "range");
      if (hasAddress !== hasRange) {
        if (hasAddress) expanded += 1;
        else {
          const parsed = parseCanonicalRange(required(node, "range"));
          expanded +=
            (parsed.end.row - parsed.start.row + 1) *
            (parsed.end.col - parsed.start.col + 1);
        }
        if (expanded > MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS) {
          throw failure(
            "EXPANSION_LIMIT",
            `Sketch expands to more than ${MAX_EXPANDED_CELL_ROLE_SKETCH_V02_CELLS} cells.`,
          );
        }
      }
    }
    node.children.forEach(visit);
  };
  visit(root);
}

function assertUniqueIds(
  tables: SketchTableV02[],
  uncertainties: SketchUncertaintyV02[],
): void {
  const ids = [
    ...tables.flatMap((table) => [
      table.id,
      table.values.id,
      ...table.values.sources.map((source) => source.id),
      ...table.dimensions.flatMap((dimension) => [
        dimension.id,
        ...dimension.sources.map((source) => source.id),
      ]),
      ...table.relationships.map((relationship) => relationship.id),
    ]),
    ...uncertainties.map((entry) => entry.id),
  ];
  if (new Set(ids).size !== ids.length) {
    throw failure(
      "DUPLICATE_ID",
      "All source IDs, including compact range source IDs, must be globally unique.",
    );
  }
}

function assertUncertaintyTargets(
  tables: SketchTableV02[],
  uncertainties: SketchUncertaintyV02[],
): void {
  const targets = new Set(
    tables.flatMap((table) => [
      table.id,
      table.values.id,
      ...table.values.sources.map((source) => source.id),
      ...table.dimensions.flatMap((dimension) => [
        dimension.id,
        ...dimension.sources.map((source) => source.id),
      ]),
      ...table.relationships.map((relationship) => relationship.id),
    ]),
  );
  for (const uncertainty of uncertainties) {
    if (!targets.has(uncertainty.target)) {
      throw failure(
        "INVALID_UNCERTAINTY_TARGET",
        `Uncertainty ${uncertainty.id} targets unknown source ${uncertainty.target}.`,
      );
    }
  }
}

function assertOutputNames(tables: SketchTableV02[]): void {
  const tableNames = new Set<string>();
  for (const table of tables) {
    const tableName = outputKey(table.name);
    if (tableNames.has(tableName)) {
      throw failure(
        "OUTPUT_NAME_COLLISION",
        `Duplicate RecipeV01 table output name ${table.name}.`,
      );
    }
    tableNames.add(tableName);
    const names = [
      table.values.name,
      ...table.dimensions.map((entry) => entry.name),
    ];
    const keys = names.map(outputKey);
    if (new Set(keys).size !== keys.length) {
      throw failure(
        "OUTPUT_NAME_COLLISION",
        `Table ${table.id} contains duplicate values/header output names.`,
      );
    }
  }
}

function assertRoleConsistency(tables: SketchTableV02[]): void {
  const valueOwners = new Map<string, string>();
  for (const table of tables) {
    const dimensions = table.dimensions.flatMap((entry) => entry.addresses);
    const dimensionSet = new Set(dimensions);
    if (dimensionSet.size !== dimensions.length) {
      throw failure(
        "ROLE_CELL_OVERLAP",
        `Table ${table.id} assigns a cell to more than one dimension.`,
      );
    }
    if (table.values.addresses.some((address) => dimensionSet.has(address))) {
      throw failure(
        "ROLE_CELL_OVERLAP",
        `Table ${table.id} assigns a cell as both a value and dimension.`,
      );
    }
    for (const address of table.values.addresses) {
      const owner = valueOwners.get(address);
      if (owner) {
        throw failure(
          "TABLE_VALUE_OVERLAP",
          `Value cell ${address} is assigned to both ${owner} and ${table.id}.`,
        );
      }
      valueOwners.set(address, table.id);
    }
  }
}

function serializeValidatedSketch(sketch: CellRoleSketchV02): string {
  const lines = [
    `<CellRoleSketch version="0.2" sheet="${escapeXml(sketch.sheet)}">`,
  ];
  for (const table of sketch.tables) {
    lines.push(
      `  <Table id="${escapeXml(table.id)}" name="${escapeXml(table.name)}" evidence="${escapeXml(table.evidence)}"${table.physicalExtent ? ` physicalExtent="${table.physicalExtent}"` : ""}>`,
    );
    lines.push(
      `    <Values id="${escapeXml(table.values.id)}" name="${escapeXml(table.values.name)}"${table.values.evidence ? ` evidence="${escapeXml(table.values.evidence)}"` : ""}>`,
    );
    serializeCells(lines, table.values.sources, 6);
    lines.push("    </Values>");
    for (const dimension of table.dimensions) {
      lines.push(
        `    <Dimension id="${escapeXml(dimension.id)}" name="${escapeXml(dimension.name)}" evidence="${escapeXml(dimension.evidence)}">`,
      );
      serializeCells(lines, dimension.sources, 6);
      lines.push("    </Dimension>");
    }
    for (const relationship of table.relationships) {
      lines.push(
        `    <Relationship id="${escapeXml(relationship.id)}" dimensionId="${escapeXml(relationship.dimensionId)}" kind="${relationship.kind}" evidence="${escapeXml(relationship.evidence)}"/>`,
      );
    }
    lines.push("  </Table>");
  }
  for (const uncertainty of sketch.uncertainties) {
    lines.push(
      `  <Uncertainty id="${escapeXml(uncertainty.id)}" target="${escapeXml(uncertainty.target)}" field="${uncertainty.field}" alternatives="${escapeXml(uncertainty.alternatives.join(" | "))}" evidence="${escapeXml(uncertainty.evidence)}" blocking="${uncertainty.blocking ? "true" : "false"}"/>`,
    );
  }
  lines.push("</CellRoleSketch>");
  const canonical = `${lines.join("\n")}\n`;
  const canonicalBytes = Buffer.byteLength(canonical, "utf8");
  if (canonicalBytes > MAX_CELL_ROLE_SKETCH_V02_BYTES) {
    throw failure(
      "CANONICAL_OUTPUT_TOO_LARGE",
      `Canonical XML is ${canonicalBytes} bytes and exceeds ${MAX_CELL_ROLE_SKETCH_V02_BYTES} bytes.`,
    );
  }
  return canonical;
}

function serializeCells(
  lines: string[],
  sources: SketchCellSourceV02[],
  spaces: number,
): void {
  const indent = " ".repeat(spaces);
  for (const source of sources) {
    const selector =
      source.selector.kind === "range"
        ? `range="${source.selector.value}"`
        : `address="${source.selector.value}"`;
    lines.push(
      `${indent}<Cell id="${escapeXml(source.id)}" ${selector}${source.evidence ? ` evidence="${escapeXml(source.evidence)}"` : ""}/>`,
    );
  }
}

function assertChildren(node: XmlNode, allowed: string[]): void {
  const allow = new Set(allowed);
  const invalid = node.children.find((child) => !allow.has(child.name));
  if (invalid) {
    throw failure(
      "INVALID_STRUCTURE",
      `${invalid.name} is not allowed inside ${node.name}.`,
    );
  }
}

function assertLeaf(node: XmlNode): void {
  if (node.children.length) {
    throw failure(
      "INVALID_STRUCTURE",
      `${node.name} must not contain child elements.`,
    );
  }
}

function required(node: XmlNode, name: string): string {
  const value = node.attrs[name]?.trim();
  if (!value) {
    throw failure("BLANK_REQUIRED_FIELD", `${node.name}.${name} is required.`);
  }
  return value;
}

function optional(node: XmlNode, name: string): string | undefined {
  const value = node.attrs[name]?.trim();
  return value || undefined;
}

function stableId(node: XmlNode, name: string): string {
  return stableAttribute(node, name);
}

function stableAttribute(node: XmlNode, name: string): string {
  const value = required(node, name);
  if (!STABLE_ID.test(value)) {
    throw failure(
      "INVALID_ID",
      `${node.name}.${name} must be a stable lowercase identifier.`,
    );
  }
  return value;
}

function canonicalCell(input: string, bounds?: SheetBounds): string {
  if (!CANONICAL_CELL.test(input)) {
    throw failure(
      "INVALID_SELECTOR",
      `${input} is not a canonical R1C1 address.`,
    );
  }
  const cell = parseCell(input);
  if (bounds && (cell.row > bounds.rowCount || cell.col > bounds.columnCount)) {
    throw failure(
      "ADDRESS_OUT_OF_BOUNDS",
      `${input} is outside the summarized sheet.`,
    );
  }
  return input;
}

function canonicalRange(input: string, bounds?: SheetBounds): string {
  const parsed = parseCanonicalRange(input);
  if (
    bounds &&
    (parsed.end.row > bounds.rowCount || parsed.end.col > bounds.columnCount)
  ) {
    throw failure(
      "ADDRESS_OUT_OF_BOUNDS",
      `${input} is outside the summarized sheet.`,
    );
  }
  return input;
}

function parseCanonicalRange(input: string): ReturnType<typeof parseRange> {
  if (!CANONICAL_RANGE.test(input)) {
    throw failure(
      "INVALID_SELECTOR",
      `${input} is not a canonical R1C1 range.`,
    );
  }
  let parsed: ReturnType<typeof parseRange>;
  try {
    parsed = parseRange(input);
  } catch {
    throw failure("INVALID_SELECTOR", `${input} is not a valid R1C1 range.`);
  }
  if (formatRange(parsed) !== input) {
    throw failure(
      "INVALID_SELECTOR",
      `${input} is not a canonical forward R1C1 range.`,
    );
  }
  return parsed;
}

function boundingRange(addresses: string[]): string {
  const extent = addresses.reduce(
    (current, address) => {
      const cell = parseCell(address);
      return {
        minRow: Math.min(current.minRow, cell.row),
        minCol: Math.min(current.minCol, cell.col),
        maxRow: Math.max(current.maxRow, cell.row),
        maxCol: Math.max(current.maxCol, cell.col),
      };
    },
    {
      minRow: Number.POSITIVE_INFINITY,
      minCol: Number.POSITIVE_INFINITY,
      maxRow: 0,
      maxCol: 0,
    },
  );
  return formatRange({
    start: { row: extent.minRow, col: extent.minCol },
    end: { row: extent.maxRow, col: extent.maxCol },
  });
}

function rangeContains(outer: string, inner: string): boolean {
  const outerRange = parseRange(outer);
  const innerRange = parseRange(inner);
  return (
    outerRange.start.row <= innerRange.start.row &&
    outerRange.start.col <= innerRange.start.col &&
    outerRange.end.row >= innerRange.end.row &&
    outerRange.end.col >= innerRange.end.col
  );
}

function outputKey(value: string): string {
  return value.trim().toLocaleLowerCase("en-US");
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;");
}

function assertText(text: string, insideRoot: boolean): void {
  if (insideRoot && text.trim()) {
    throw failure(
      "MALFORMED_XML",
      "Text content is not allowed; use attributes.",
    );
  }
}

function assertBounds(bounds: SheetBounds | undefined): void {
  if (
    bounds &&
    (!Number.isInteger(bounds.rowCount) ||
      bounds.rowCount <= 0 ||
      !Number.isInteger(bounds.columnCount) ||
      bounds.columnCount <= 0)
  ) {
    throw failure("INVALID_BOUNDS", "Sheet bounds must be positive integers.");
  }
}

function failure(code: string, message: string): Error & { code: string } {
  return Object.assign(new Error(message), { code });
}

function geometryFailure(
  code: string,
  message: string,
  diagnostics: GeometryDiagnostic[],
): Error & { code: string; diagnostics: GeometryDiagnostic[] } {
  return Object.assign(new Error(message), { code, diagnostics });
}
