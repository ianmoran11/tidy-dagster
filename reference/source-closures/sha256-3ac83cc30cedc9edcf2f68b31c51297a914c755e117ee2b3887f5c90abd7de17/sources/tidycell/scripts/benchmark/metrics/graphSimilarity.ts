import { parseCell } from "../../../src/lib/address";
import type { CsvTable, GraphSimilarityMetrics } from "../types";

export type { GraphSimilarityMetrics, MatchedColumnPair } from "../types";

/**
 * Jaccard graph similarity — core metric module.
 *
 * Builds an implied association graph from a source-addressed tidy table and
 * scores expected-vs-actual similarity with edge-set Jaccard. The graph has
 * address-keyed cell nodes, anonymous latent header-column nodes, type-1
 * `column → cell` membership edges, and type-2 `value cell → header cell`
 * association edges. Column *names* are never used for identity, matching,
 * edges, or labels. See `docs/performance-measures/graph-similarity.md`.
 *
 * This module is pure and framework-free: it has no imports from the
 * benchmark runner, suite, or renderers. Wiring lives in later PRDs.
 */

const SOURCE_COLUMNS = new Set([
  "row",
  "col",
  "address",
  "_source.sheet",
  "_source.address",
  "_source.row",
  "_source.col",
]);

/** Stable export convention identifying the value column. */
const VALUE_COLUMN = ".value";
/** Metadata column used to split multi-table exports; never a header axis. */
const TABLE_COLUMN = "table";

export type LatentColumn = {
  /** Local, anonymous identity. Stable within one graph only. */
  id: string;
  /** Distinct source addresses appearing in the column, sorted. */
  cells: string[];
};

export type Type1Edge = {
  columnId: string;
  address: string;
};

export type Type2Edge = {
  valueAddress: string;
  headerAddress: string;
};

export type TableGraph = {
  /** All cell addresses appearing in the graph, sorted. */
  cellNodes: string[];
  /** Anonymous latent header-column nodes (the value column is excluded). */
  columns: LatentColumn[];
  /** `column → cell` membership edges, sorted by (columnId, address). */
  type1Edges: Type1Edge[];
  /** `value cell → header cell` association edges, sorted by endpoints. */
  type2Edges: Type2Edge[];
  /** Non-blank value rows that fed the graph. */
  valueRowCount: number;
  /** Whether any row carried a value source address. */
  hasValueSources: boolean;
  /** Whether any header column carried a `<header>_source` address. */
  hasHeaderSources: boolean;
};

/**
 * Build the per-table graph from a source-addressed tidy table.
 *
 * Input is a `CsvTable` carrying value source (`address` or
 * `_source.address`) and per-header source (`<header>_source`) columns.
 * Columns matching the `SOURCE_COLUMNS` convention (plus the `table`
 * metadata column) are never treated as data columns. When a `table` column
 * is present the rows are split per table and one latent column set is built
 * per table, so same-named header columns from different tables never merge.
 * Blank-value rows are excluded, consistent with `filterNonBlankValueRows`
 * in `csvDiff`.
 */
export function buildTableGraph(table: CsvTable): TableGraph {
  const records = filterNonBlankValueRows(table);
  const valueColumn = table.headers.includes(VALUE_COLUMN)
    ? VALUE_COLUMN
    : null;
  const headerColumns = table.headers.filter(isHeaderColumn);
  const groups = groupRecordsByTable(table, records);

  const cellNodes = new Set<string>();
  const type2Keys = new Set<string>();
  const rawColumns: Array<{ cells: Set<string> }> = [];
  let hasValueSources = false;
  let hasHeaderSources = false;

  for (const groupRecords of groups.values()) {
    const columnCells = new Map<string, Set<string>>(
      headerColumns.map((header) => [header, new Set<string>()]),
    );

    for (const record of groupRecords) {
      const valueAddress = valueColumn ? getSourceAddress(record) : undefined;
      if (valueAddress) {
        hasValueSources = true;
        cellNodes.add(valueAddress);
      }

      for (const header of headerColumns) {
        const headerAddress = normalizeAddress(record[`${header}_source`]);
        if (!headerAddress) {
          continue;
        }
        hasHeaderSources = true;
        columnCells.get(header)?.add(headerAddress);
        cellNodes.add(headerAddress);
        if (valueAddress) {
          type2Keys.add(edgeKey(valueAddress, headerAddress));
        }
      }
    }

    for (const cells of columnCells.values()) {
      if (cells.size > 0) {
        rawColumns.push({ cells });
      }
    }
  }

  // Latent columns are anonymous: sort by canonical cell-set key and assign
  // local ids in that order so every output is deterministic.
  const columns: LatentColumn[] = rawColumns
    .map((column) => [...column.cells].sort(sortAddress))
    .sort(compareCellSets)
    .map((cells, index) => ({ id: `col-${index}`, cells }));

  const type1Edges: Type1Edge[] = columns.flatMap((column) =>
    column.cells.map((address) => ({ columnId: column.id, address })),
  );

  const type2Edges: Type2Edge[] = [...type2Keys]
    .map((key) => {
      const [valueAddress, headerAddress] = key.split(EDGE_SEPARATOR);
      return { valueAddress, headerAddress };
    })
    .sort(
      (left, right) =>
        sortAddress(left.valueAddress, right.valueAddress) ||
        sortAddress(left.headerAddress, right.headerAddress),
    );

  return {
    cellNodes: [...cellNodes].sort(sortAddress),
    columns,
    type1Edges,
    type2Edges,
    valueRowCount: records.length,
    hasValueSources,
    hasHeaderSources,
  };
}

/**
 * Compare two source-addressed tidy tables (or pre-built graphs) with
 * edge-set Jaccard.
 *
 * Latent header columns are aligned across the graphs by **greedy
 * maximum-weight bipartite matching** with weight `|S_exp ∩ S_act|` (raw
 * cell-set intersection, which is exactly the shared type-1 edge count).
 * Candidate pairs are processed in descending weight order with
 * deterministic tie-breaking on the canonical cell-set keys, and each column
 * matches at most once. Greedy is used instead of an exact Hungarian
 * assignment: it is deterministic, total, and simple, and the spec only
 * requires invariance of the *score* to the pairing — greedy maximises the
 * same per-pair quantity (shared type-1 edges) that the union formula
 * consumes. Only pairs with non-empty intersection may match; disjoint
 * columns are left unmatched rather than force-paired, and contribute their
 * cells to the union only.
 *
 * Availability gating mirrors the spec: type-2 (`association_jaccard`)
 * requires per-header source addresses on the expected side; type-1
 * (`column_axis_jaccard`) requires at least value or header source
 * addresses. Uncomputable sub-scores are `null` with the availability flags
 * indicating why. When type-2 is unavailable, the combined
 * `graph_similarity` is computed over the scored (type-1) edges only.
 */
export function compareTableGraphs(
  expected: CsvTable | TableGraph,
  actual: CsvTable | TableGraph,
): GraphSimilarityMetrics {
  const expectedGraph = toGraph(expected);
  const actualGraph = toGraph(actual);

  const referenceAvailable =
    expectedGraph.hasValueSources || expectedGraph.hasHeaderSources;
  if (!referenceAvailable) {
    return unscoredGraphSimilarity(actualGraph);
  }

  const type2Scoreable = expectedGraph.hasHeaderSources;

  const matching = matchColumns(expectedGraph.columns, actualGraph.columns);

  // Type-1: an edge is shared iff a matched pair both connect to the same
  // cell address — exactly the matching weight summed over pairs.
  const sharedType1 = matching.pairs.reduce(
    (sum, pair) => sum + pair.weight,
    0,
  );
  const expectedType1Count = expectedGraph.type1Edges.length;
  const actualType1Count = actualGraph.type1Edges.length;
  const columnAxisJaccard = jaccardScore(
    sharedType1,
    expectedType1Count,
    actualType1Count,
  );

  // Type-2: both endpoints are address-keyed, so edges compare directly.
  let associationJaccard: number | null = null;
  let sharedType2 = 0;
  let expectedType2Count = 0;
  let actualType2Count = 0;
  if (type2Scoreable) {
    const expectedType2 = new Set(
      expectedGraph.type2Edges.map(type2EdgeKeyOf),
    );
    const actualType2 = new Set(actualGraph.type2Edges.map(type2EdgeKeyOf));
    sharedType2 = [...expectedType2].filter((key) =>
      actualType2.has(key),
    ).length;
    expectedType2Count = expectedType2.size;
    actualType2Count = actualType2.size;
    associationJaccard = jaccardScore(
      sharedType2,
      expectedType2Count,
      actualType2Count,
    );
  }

  const expectedEdgeCount = expectedType1Count + expectedType2Count;
  const actualEdgeCount = actualType1Count + actualType2Count;
  const sharedEdgeCount = sharedType1 + sharedType2;

  return {
    reference_available: true,
    expected_value_sources_available: expectedGraph.hasValueSources,
    expected_header_sources_available: expectedGraph.hasHeaderSources,
    graph_similarity: jaccardScore(
      sharedEdgeCount,
      expectedEdgeCount,
      actualEdgeCount,
    ),
    column_axis_jaccard: columnAxisJaccard,
    association_jaccard: associationJaccard,
    matched_column_pairs: matching.pairs.map((pair) => ({
      expected_cells: pair.expected.cells,
      actual_cells: pair.actual.cells,
      shared_cell_count: pair.weight,
    })),
    unmatched_expected_column_count: matching.unmatchedExpectedCount,
    unmatched_actual_column_count: matching.unmatchedActualCount,
    expected_edge_count: expectedEdgeCount,
    actual_edge_count: actualEdgeCount,
    shared_edge_count: sharedEdgeCount,
  };
}

/**
 * Companion for when expected source data is unavailable: reports
 * `reference_available: false` with null scores, mirroring
 * `unscoredCsvDiff`. The actual graph (when provided) is still summarised in
 * the edge/column counts.
 */
export function unscoredGraphSimilarity(
  actual?: CsvTable | TableGraph,
): GraphSimilarityMetrics {
  const actualGraph = actual ? toGraph(actual) : null;

  return {
    reference_available: false,
    expected_value_sources_available: false,
    expected_header_sources_available: false,
    graph_similarity: null,
    column_axis_jaccard: null,
    association_jaccard: null,
    matched_column_pairs: [],
    unmatched_expected_column_count: 0,
    unmatched_actual_column_count: actualGraph?.columns.length ?? 0,
    expected_edge_count: 0,
    actual_edge_count: actualGraph
      ? actualGraph.type1Edges.length + actualGraph.type2Edges.length
      : 0,
    shared_edge_count: 0,
  };
}

const EDGE_SEPARATOR = "→";

function edgeKey(valueAddress: string, headerAddress: string): string {
  return `${valueAddress}${EDGE_SEPARATOR}${headerAddress}`;
}

function type2EdgeKeyOf(edge: Type2Edge): string {
  return edgeKey(edge.valueAddress, edge.headerAddress);
}

function toGraph(input: CsvTable | TableGraph): TableGraph {
  if (isTableGraph(input)) {
    return input;
  }
  return buildTableGraph(input);
}

function isTableGraph(input: CsvTable | TableGraph): input is TableGraph {
  return Array.isArray((input as TableGraph).type1Edges);
}

function isHeaderColumn(header: string): boolean {
  return (
    !SOURCE_COLUMNS.has(header) &&
    !header.endsWith("_source") &&
    header !== VALUE_COLUMN &&
    header !== TABLE_COLUMN
  );
}

function filterNonBlankValueRows(table: CsvTable): Record<string, string>[] {
  if (!table.headers.includes(VALUE_COLUMN)) {
    return table.records;
  }
  return table.records.filter(
    (record) => !isBlankValue(record[VALUE_COLUMN]),
  );
}

function isBlankValue(value: string | undefined): boolean {
  return value === undefined || value.trim() === "";
}

function getSourceAddress(record: Record<string, string>): string | undefined {
  return record.address || record["_source.address"] || undefined;
}

function normalizeAddress(value: string | undefined): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed === "" ? undefined : trimmed;
}

function groupRecordsByTable(
  table: CsvTable,
  records: Record<string, string>[],
): Map<string, Record<string, string>[]> {
  const groups = new Map<string, Record<string, string>[]>();
  if (!table.headers.includes(TABLE_COLUMN)) {
    groups.set("", records);
    return groups;
  }
  for (const record of records) {
    const key = record[TABLE_COLUMN] ?? "";
    const group = groups.get(key);
    if (group) {
      group.push(record);
    } else {
      groups.set(key, [record]);
    }
  }
  return groups;
}

type ColumnSet = {
  key: string;
  cells: string[];
  set: Set<string>;
};

type ColumnPair = {
  expected: ColumnSet;
  actual: ColumnSet;
  weight: number;
};

function matchColumns(
  expectedColumns: LatentColumn[],
  actualColumns: LatentColumn[],
): {
  pairs: ColumnPair[];
  unmatchedExpectedCount: number;
  unmatchedActualCount: number;
} {
  const expected = expectedColumns.map(toColumnSet);
  const actual = actualColumns.map(toColumnSet);

  const candidates: Array<{
    expectedIndex: number;
    actualIndex: number;
    weight: number;
  }> = [];
  for (let e = 0; e < expected.length; e += 1) {
    for (let a = 0; a < actual.length; a += 1) {
      const weight = intersectionSize(expected[e].set, actual[a].set);
      // Only non-empty intersections may match; disjoint columns are left
      // unmatched rather than force-paired.
      if (weight > 0) {
        candidates.push({ expectedIndex: e, actualIndex: a, weight });
      }
    }
  }

  // Greedy maximum-weight matching: descending weight, with deterministic
  // tie-breaking on the canonical cell-set keys of both endpoints.
  candidates.sort(
    (left, right) =>
      right.weight - left.weight ||
      compareKeys(
        expected[left.expectedIndex].key,
        expected[right.expectedIndex].key,
      ) ||
      compareKeys(
        actual[left.actualIndex].key,
        actual[right.actualIndex].key,
      ),
  );

  const matchedExpected = new Set<number>();
  const matchedActual = new Set<number>();
  const pairs: ColumnPair[] = [];
  for (const candidate of candidates) {
    if (
      matchedExpected.has(candidate.expectedIndex) ||
      matchedActual.has(candidate.actualIndex)
    ) {
      continue;
    }
    matchedExpected.add(candidate.expectedIndex);
    matchedActual.add(candidate.actualIndex);
    pairs.push({
      expected: expected[candidate.expectedIndex],
      actual: actual[candidate.actualIndex],
      weight: candidate.weight,
    });
  }

  // Deterministic report order for the diagnostic pairings.
  pairs.sort(
    (left, right) =>
      compareKeys(left.expected.key, right.expected.key) ||
      compareKeys(left.actual.key, right.actual.key),
  );

  return {
    pairs,
    unmatchedExpectedCount: expected.length - matchedExpected.size,
    unmatchedActualCount: actual.length - matchedActual.size,
  };
}

function toColumnSet(column: LatentColumn): ColumnSet {
  return {
    key: column.cells.join(" "),
    cells: column.cells,
    set: new Set(column.cells),
  };
}

function intersectionSize(left: Set<string>, right: Set<string>): number {
  let count = 0;
  for (const value of left) {
    if (right.has(value)) {
      count += 1;
    }
  }
  return count;
}

/**
 * Jaccard `|∩| / |∪|` from a shared count and both set sizes. An empty union
 * means both sides are empty and resolves to `1`, mirroring the
 * `precisionRecallF1` empty-set conventions in `csvDiff`.
 */
function jaccardScore(
  shared: number,
  expectedCount: number,
  actualCount: number,
): number {
  const union = expectedCount + actualCount - shared;
  return union === 0 ? 1 : shared / union;
}

function compareCellSets(left: string[], right: string[]): number {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const order = sortAddress(left[index], right[index]);
    if (order !== 0) {
      return order;
    }
  }
  return left.length - right.length;
}

function compareKeys(left: string, right: string): number {
  return compareCellSets(left.split(" "), right.split(" "));
}

function sortAddress(left: string, right: string): number {
  try {
    const a = parseCell(left);
    const b = parseCell(right);

    if (a.row !== b.row) {
      return a.row - b.row;
    }

    return a.col - b.col;
  } catch {
    return left.localeCompare(right);
  }
}
