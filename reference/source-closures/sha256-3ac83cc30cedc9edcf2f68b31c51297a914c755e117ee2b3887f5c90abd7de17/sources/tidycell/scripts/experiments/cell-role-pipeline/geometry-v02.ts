import { formatRange, parseCell } from "../../../src/lib/address";
import {
  buildHeaderDirectionGroups,
  estimateRelationshipResolutionOperations,
  isBlankRelationshipValue,
  resolveRelationshipSelections,
} from "../../../src/lib/executor/relationshipResolution";
import type { HeaderDirection } from "../../../src/lib/recipe/types";
import type {
  SemanticGoldDraft,
  SemanticHierarchyLevel,
} from "./semantic-gold-schema";
import type {
  CellRoleSketchV02,
  SketchDimensionV02,
  SketchRelationshipV02,
  SketchTableV02,
} from "./cell-role-sketch-v02";
import type { RelationshipKind } from "./types";

export const MAX_CELL_ROLE_GEOMETRY_OPERATIONS = 2_000_000;
export const MAX_CELL_ROLE_GEOMETRY_ATTACHMENTS = 250_000;
export const MAX_CELL_ROLE_GEOMETRY_DIAGNOSTICS = 1_000;
export const SHARED_PHYSICAL_HEADER_POLICY =
  "A physical header may be duplicated into multiple semantic tables; each table resolves it independently. Value cells may belong to only one table, and value/header role overlap is forbidden." as const;

export const DIRECTION_BY_RELATIONSHIP: Readonly<
  Record<RelationshipKind, HeaderDirection>
> = {
  "direct-column": "N",
  "direct-row": "W",
  "cascading-column": "NNW",
  "cascading-row": "WNW",
};

export type GeometryDiagnosticCode =
  | "EMPTY_ACTIVE_VALUE_SELECTION"
  | "GEOMETRY_RESOURCE_LIMIT"
  | "GEOMETRY_DIAGNOSTIC_LIMIT"
  | "MISSING_DIMENSION_ATTACHMENT"
  | "OVERLAPPING_TABLE_VALUE"
  | "ROLE_OVERLAP"
  | "SELECTOR_BOUNDS_MISMATCH"
  | "SHARED_HEADER_DUPLICATED"
  | "UNATTACHED_HEADER";

export type GeometryDiagnostic = {
  code: GeometryDiagnosticCode;
  severity: "error" | "warning";
  message: string;
  path: string;
  tableId?: string;
  dimensionId?: string;
  relationshipId?: string;
  relationshipKind?: RelationshipKind;
  address?: string;
  valueAddress?: string;
  headerAddress?: string;
};

export type GeometryAssociation = {
  tableId: string;
  dimensionId: string;
  relationshipId: string;
  relationshipKind: RelationshipKind;
  valueAddress: string;
  headerAddress: string;
};

export type GeometryTableResult = {
  tableId: string;
  derivedSelectorBounds: string;
  selectedValueCount: number;
  activeValueCount: number;
  selectedHeaderCount: number;
  attachedHeaderCount: number;
};

export type CellRoleGeometryResult = {
  valid: boolean;
  diagnostics: GeometryDiagnostic[];
  associations: GeometryAssociation[];
  tables: GeometryTableResult[];
  stats: {
    estimatedOperations: number;
    attachmentCount: number;
    associationsCollected: boolean;
    diagnosticCount: number;
    diagnosticsTruncated: boolean;
  };
  sharedPhysicalHeaderPolicy: typeof SHARED_PHYSICAL_HEADER_POLICY;
};

export type CellRoleGeometryOptions = {
  sheet?: {
    cells: ReadonlyArray<{
      address: string;
      data_type?: string;
      value?: unknown;
    }>;
  };
  /** Dimensions are optional in v0.2 unless an external reviewed contract marks them required with evidence. */
  requiredDimensions?: ReadonlyMap<string, string>;
  /** Collect exact association pairs for gold metrics; validation itself streams them. */
  collectAssociations?: boolean;
};

export function validateCellRoleSketchGeometry(
  sketch: CellRoleSketchV02,
  options: CellRoleGeometryOptions = {},
): CellRoleGeometryResult {
  const diagnostics: GeometryDiagnostic[] = [];
  const associations: GeometryAssociation[] = [];
  const tables: GeometryTableResult[] = [];
  let diagnosticsTruncated = false;
  let estimatedOperations = 0;
  let attachmentCount = 0;
  const cellMap = options.sheet
    ? new Map(options.sheet.cells.map((cell) => [cell.address, cell]))
    : undefined;

  const addDiagnostic = (diagnostic: GeometryDiagnostic): void => {
    if (diagnostics.length < MAX_CELL_ROLE_GEOMETRY_DIAGNOSTICS) {
      diagnostics.push(diagnostic);
    } else {
      diagnosticsTruncated = true;
    }
  };

  validateCrossTableIsolation(sketch, addDiagnostic);

  for (const [tableIndex, table] of sketch.tables.entries()) {
    const tablePath = `tables[${tableIndex}]`;
    const activeValueAddresses = table.values.addresses.filter((address) => {
      if (!cellMap) return true;
      const cell = cellMap.get(address);
      return Boolean(cell && !isBlankRelationshipValue(cell));
    });
    if (!activeValueAddresses.length) {
      addDiagnostic({
        code: "EMPTY_ACTIVE_VALUE_SELECTION",
        severity: "error",
        path: `${tablePath}.values`,
        tableId: table.id,
        message: `Table ${table.id} has no nonblank selected value cells under executor semantics.`,
      });
    }

    let attachedHeaderCount = 0;
    let selectedHeaderCount = 0;
    for (const [dimensionIndex, dimension] of table.dimensions.entries()) {
      const dimensionPath = `${tablePath}.dimensions[${dimensionIndex}]`;
      const relationship = table.relationships.find(
        (candidate) => candidate.dimensionId === dimension.id,
      );
      if (!relationship) continue;
      const direction = DIRECTION_BY_RELATIONSHIP[relationship.kind];
      const estimated = estimateRelationshipResolutionOperations(
        direction,
        dimension.addresses.length,
        activeValueAddresses,
      );
      estimatedOperations += estimated;
      if (
        estimatedOperations > MAX_CELL_ROLE_GEOMETRY_OPERATIONS ||
        (options.collectAssociations === true &&
          associations.length + activeValueAddresses.length >
            MAX_CELL_ROLE_GEOMETRY_ATTACHMENTS)
      ) {
        addDiagnostic({
          code: "GEOMETRY_RESOURCE_LIMIT",
          severity: "error",
          path: dimensionPath,
          tableId: table.id,
          dimensionId: dimension.id,
          relationshipId: relationship.id,
          relationshipKind: relationship.kind,
          message: `Relationship geometry exceeds the bounded operation/attachment budget (${MAX_CELL_ROLE_GEOMETRY_OPERATIONS}/${MAX_CELL_ROLE_GEOMETRY_ATTACHMENTS}).`,
        });
        continue;
      }

      const groups = buildHeaderDirectionGroups({
        headerAddresses: dimension.addresses,
        valueAddresses: activeValueAddresses,
        direction,
      });
      const usedHeaders = new Set<string>();
      const requiredEvidence = options.requiredDimensions?.get(dimension.id);
      const required = Boolean(requiredEvidence);

      const selections = resolveRelationshipSelections(
        groups,
        activeValueAddresses,
      );
      for (const valueAddress of activeValueAddresses) {
        const attachment = selections.get(valueAddress)!;
        if (attachment.selectedAddress) {
          usedHeaders.add(attachment.selectedAddress);
          attachmentCount += 1;
          if (options.collectAssociations === true) {
            associations.push({
              tableId: table.id,
              dimensionId: dimension.id,
              relationshipId: relationship.id,
              relationshipKind: relationship.kind,
              valueAddress,
              headerAddress: attachment.selectedAddress,
            });
          }
        } else if (required) {
          addDiagnostic({
            code: "MISSING_DIMENSION_ATTACHMENT",
            severity: "error",
            path: `${dimensionPath}.addresses`,
            tableId: table.id,
            dimensionId: dimension.id,
            relationshipId: relationship.id,
            relationshipKind: relationship.kind,
            address: valueAddress,
            valueAddress,
            message: `Value cell ${valueAddress} does not resolve required dimension ${dimension.id} (${relationship.kind}). Required by: ${requiredEvidence}.`,
          });
        }
      }

      selectedHeaderCount += dimension.addresses.length;
      attachedHeaderCount += usedHeaders.size;
      for (const headerAddress of dimension.addresses) {
        if (!usedHeaders.has(headerAddress)) {
          addDiagnostic({
            code: "UNATTACHED_HEADER",
            severity: "error",
            path: `${dimensionPath}.addresses`,
            tableId: table.id,
            dimensionId: dimension.id,
            relationshipId: relationship.id,
            relationshipKind: relationship.kind,
            address: headerAddress,
            headerAddress,
            message: `Header cell ${headerAddress} does not attach to any active selected value for dimension ${dimension.id} (${relationship.kind}).`,
          });
        }
      }
    }

    const derivedSelectorBounds = deriveSelectorBounds(table);
    if (table.selectorBounds !== derivedSelectorBounds) {
      addDiagnostic({
        code: "SELECTOR_BOUNDS_MISMATCH",
        severity: "error",
        path: `${tablePath}.selectorBounds`,
        tableId: table.id,
        message: `Derived selector bounds ${derivedSelectorBounds} do not match ${table.selectorBounds}.`,
      });
    }
    tables.push({
      tableId: table.id,
      derivedSelectorBounds,
      selectedValueCount: table.values.addresses.length,
      activeValueCount: activeValueAddresses.length,
      selectedHeaderCount,
      attachedHeaderCount,
    });
  }

  if (diagnosticsTruncated) {
    diagnostics.push({
      code: "GEOMETRY_DIAGNOSTIC_LIMIT",
      severity: "error",
      path: "$",
      message: `Geometry diagnostics were truncated after ${MAX_CELL_ROLE_GEOMETRY_DIAGNOSTICS} exact-address diagnostics.`,
    });
  }

  return {
    valid: !diagnostics.some((diagnostic) => diagnostic.severity === "error"),
    diagnostics,
    associations,
    tables,
    stats: {
      estimatedOperations,
      attachmentCount,
      associationsCollected: options.collectAssociations === true,
      diagnosticCount: diagnostics.length,
      diagnosticsTruncated,
    },
    sharedPhysicalHeaderPolicy: SHARED_PHYSICAL_HEADER_POLICY,
  };
}

export type SemanticGeometryMetrics = {
  dimensionAddressPrecision: number;
  dimensionAddressRecall: number;
  relationshipKindAccuracy: number;
  headerAttachmentCoverage: number;
  valueDimensionCoverage: number;
};

/**
 * Address/topology-only gold scoring. Names and declaration order are excluded.
 * Dimensions are aligned by stable level ID first and by maximum header-address
 * overlap otherwise, so legacy output column names are never required.
 */
export function scoreGeometryAgainstSemanticGold(
  geometry: CellRoleGeometryResult,
  sketch: CellRoleSketchV02,
  gold: SemanticGoldDraft,
): SemanticGeometryMetrics {
  if (!geometry.stats.associationsCollected) {
    throw new Error("GEOMETRY_ASSOCIATIONS_NOT_COLLECTED");
  }
  const goldLevels = gold.tables.flatMap((table) =>
    table.dimensions.flatMap((dimension) => dimension.levels),
  );
  const predictedDimensions = sketch.tables.flatMap((table) =>
    table.dimensions.map((dimension) => ({
      dimension,
      relationship: table.relationships.find(
        (relationship) => relationship.dimensionId === dimension.id,
      ),
    })),
  );
  const predictedToGold = alignDimensions(predictedDimensions, goldLevels);
  const goldToPredicted = new Map(
    [...predictedToGold.entries()].map(([predictedId, goldId]) => [
      goldId,
      predictedId,
    ]),
  );
  const predictedHeaders = new Set(
    predictedDimensions.flatMap(({ dimension }) =>
      dimension.addresses.map(
        (address) =>
          `${predictedToGold.get(dimension.id) ?? `unmatched:${dimension.id}`}:${address}`,
      ),
    ),
  );
  const goldHeaders = new Set(
    goldLevels.flatMap((level) =>
      level.headerSourceAddresses.map((address) => `${level.id}:${address}`),
    ),
  );
  const headerIntersection = intersectionSize(predictedHeaders, goldHeaders);
  const correctKinds = goldLevels.filter((level) => {
    const predictedId = goldToPredicted.get(level.id);
    return (
      predictedDimensions.find(({ dimension }) => dimension.id === predictedId)
        ?.relationship?.kind === level.relationshipKind
    );
  }).length;
  const expectedPairs = new Set(
    goldLevels.flatMap((level) =>
      level.associations.map(
        (association) =>
          `${level.id}:${association.valueAddress}->${association.headerAddress}`,
      ),
    ),
  );
  const predictedPairs = new Set(
    geometry.associations.map(
      (association) =>
        `${predictedToGold.get(association.dimensionId) ?? `unmatched:${association.dimensionId}`}:${association.valueAddress}->${association.headerAddress}`,
    ),
  );
  const selectedHeaders = new Set(
    predictedDimensions.flatMap(({ dimension }) =>
      dimension.addresses.map((address) => `${dimension.id}:${address}`),
    ),
  );
  const attachedHeaders = new Set(
    geometry.associations.map(
      (association) =>
        `${association.dimensionId}:${association.headerAddress}`,
    ),
  );

  return {
    dimensionAddressPrecision: ratio(headerIntersection, predictedHeaders.size),
    dimensionAddressRecall: ratio(headerIntersection, goldHeaders.size),
    relationshipKindAccuracy: ratio(correctKinds, goldLevels.length),
    headerAttachmentCoverage: ratio(
      intersectionSize(attachedHeaders, selectedHeaders),
      selectedHeaders.size,
    ),
    valueDimensionCoverage: ratio(
      intersectionSize(predictedPairs, expectedPairs),
      expectedPairs.size,
    ),
  };
}

export type GeometryDiagnosticOverlay = {
  schemaVersion: "cell-role-geometry-diagnostic-overlay-v1";
  sheet: string;
  cells: Array<{
    address: string;
    codes: GeometryDiagnosticCode[];
    diagnostics: GeometryDiagnostic[];
  }>;
};

export function buildGeometryDiagnosticOverlay(
  sketch: CellRoleSketchV02,
  diagnostics: readonly GeometryDiagnostic[],
): GeometryDiagnosticOverlay {
  const byAddress = new Map<string, GeometryDiagnostic[]>();
  for (const diagnostic of diagnostics) {
    const address =
      diagnostic.address ?? diagnostic.valueAddress ?? diagnostic.headerAddress;
    if (!address) continue;
    const entries = byAddress.get(address) ?? [];
    entries.push(diagnostic);
    byAddress.set(address, entries);
  }
  return {
    schemaVersion: "cell-role-geometry-diagnostic-overlay-v1",
    sheet: sketch.sheet,
    cells: [...byAddress.entries()]
      .sort(([left], [right]) => compareAddresses(left, right))
      .map(([address, entries]) => ({
        address,
        codes: [...new Set(entries.map((entry) => entry.code))].sort(),
        diagnostics: entries,
      })),
  };
}

function validateCrossTableIsolation(
  sketch: CellRoleSketchV02,
  addDiagnostic: (diagnostic: GeometryDiagnostic) => void,
): void {
  const valueOwners = new Map<string, string[]>();
  const headerOwners = new Map<string, string[]>();
  for (const table of sketch.tables) {
    for (const address of table.values.addresses) {
      const owners = valueOwners.get(address) ?? [];
      owners.push(table.id);
      valueOwners.set(address, owners);
    }
    for (const address of table.dimensions.flatMap(
      (dimension) => dimension.addresses,
    )) {
      const owners = headerOwners.get(address) ?? [];
      if (!owners.includes(table.id)) owners.push(table.id);
      headerOwners.set(address, owners);
    }
  }

  for (const [address, owners] of valueOwners) {
    if (owners.length > 1) {
      addDiagnostic({
        code: "OVERLAPPING_TABLE_VALUE",
        severity: "error",
        path: "$",
        address,
        valueAddress: address,
        message: `Value cell ${address} belongs to multiple semantic tables: ${owners.join(", ")}.`,
      });
    }
    if (headerOwners.has(address)) {
      addDiagnostic({
        code: "ROLE_OVERLAP",
        severity: "error",
        path: "$",
        address,
        message: `Cell ${address} is selected as both a value and a header; CellRoleSketch v0.2 defines no reviewed exceptional overlap role.`,
      });
    }
  }
  for (const [address, owners] of headerOwners) {
    if (owners.length > 1) {
      addDiagnostic({
        code: "SHARED_HEADER_DUPLICATED",
        severity: "warning",
        path: "$",
        address,
        headerAddress: address,
        message: `Header cell ${address} is duplicated into semantic tables ${owners.join(", ")} and resolves independently in each table.`,
      });
    }
  }
}

function deriveSelectorBounds(table: SketchTableV02): string {
  const positions = [
    ...table.values.addresses,
    ...table.dimensions.flatMap((dimension) => dimension.addresses),
  ].map(parseCell);
  return formatRange({
    start: {
      row: Math.min(...positions.map((position) => position.row)),
      col: Math.min(...positions.map((position) => position.col)),
    },
    end: {
      row: Math.max(...positions.map((position) => position.row)),
      col: Math.max(...positions.map((position) => position.col)),
    },
  });
}

function alignDimensions(
  predicted: Array<{
    dimension: SketchDimensionV02;
    relationship: SketchRelationshipV02 | undefined;
  }>,
  goldLevels: SemanticHierarchyLevel[],
): Map<string, string> {
  const result = new Map<string, string>();
  const usedPredicted = new Set<string>();
  const usedGold = new Set<string>();
  for (const level of goldLevels) {
    const exact = predicted.find(
      ({ dimension }) =>
        dimension.id === level.id && !usedPredicted.has(dimension.id),
    );
    if (exact) {
      result.set(exact.dimension.id, level.id);
      usedPredicted.add(exact.dimension.id);
      usedGold.add(level.id);
    }
  }
  for (const level of goldLevels) {
    if (usedGold.has(level.id)) continue;
    const candidate = predicted
      .filter(({ dimension }) => !usedPredicted.has(dimension.id))
      .map((entry) => ({
        entry,
        overlap: intersectionSize(
          new Set(entry.dimension.addresses),
          new Set(level.headerSourceAddresses),
        ),
      }))
      .sort(
        (left, right) =>
          right.overlap - left.overlap ||
          left.entry.dimension.id.localeCompare(right.entry.dimension.id),
      )[0];
    if (candidate && candidate.overlap > 0) {
      result.set(candidate.entry.dimension.id, level.id);
      usedPredicted.add(candidate.entry.dimension.id);
      usedGold.add(level.id);
    }
  }
  return result;
}

function intersectionSize<T>(
  left: ReadonlySet<T>,
  right: ReadonlySet<T>,
): number {
  let count = 0;
  for (const value of left) if (right.has(value)) count += 1;
  return count;
}

function ratio(numerator: number, denominator: number): number {
  return denominator === 0 ? 1 : numerator / denominator;
}

function compareAddresses(left: string, right: string): number {
  const a = parseCell(left);
  const b = parseCell(right);
  return a.row - b.row || a.col - b.col;
}
