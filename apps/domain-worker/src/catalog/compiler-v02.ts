/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import { validateRecipe } from "../recipe/schema.js";
import type {
  CellSelector,
  HeaderDirection,
  RecipeV01,
} from "../recipe/types.js";
import {
  CELL_ROLE_SKETCH_V02,
  validateCellRoleSketchV02ForCompilation,
  type CellRoleSketchV02,
  type SketchRoleSelectorV02,
} from "./cell-role-sketch-v02.js";
import {
  DIRECTION_BY_RELATIONSHIP,
  validateCellRoleSketchGeometry,
  type CellRoleGeometryOptions,
} from "./geometry-v02.js";
import type { RelationshipKind } from "./types.js";

export const CELL_ROLE_COMPILER_VERSION =
  "cell-role-sketch-v02-recipe-v01-compiler-v2" as const;

const CANONICAL_ADDRESS = /^R[1-9]\d*C[1-9]\d*$/;
const CANONICAL_RANGE = /^R[1-9]\d*C[1-9]\d*:R[1-9]\d*C[1-9]\d*$/;

export type CellRoleCompileErrorCode =
  | "BLOCKING_UNCERTAINTY"
  | "EMPTY_NAME"
  | "DUPLICATE_TABLE_NAME"
  | "DUPLICATE_OUTPUT_NAME"
  | "RESERVED_OUTPUT_COLLISION"
  | "UNSUPPORTED_CONSTRUCT"
  | "UNSUPPORTED_SKETCH_VERSION"
  | "GEOMETRY_VALIDATION_FAILED"
  | "HEADERLESS_TABLE_UNSUPPORTED"
  | "UNSUPPORTED_SELECTOR_REPRESENTATION"
  | "RELATIONSHIP_CARDINALITY"
  | "RELATIONSHIP_TARGET_INVALID"
  | "COMPILED_RECIPE_INVALID"
  | "EQUIVALENCE_PROOF_FAILED";

export type CellRoleCompileError = {
  code: CellRoleCompileErrorCode;
  path: string;
  message: string;
};

export type CellRoleCompileResult =
  | {
      ok: true;
      recipe: RecipeV01;
      canonicalJson: string;
      compilerVersion: typeof CELL_ROLE_COMPILER_VERSION;
    }
  | { ok: false; error: CellRoleCompileError };

export type CellRoleEquivalenceDifference = {
  code:
    | "VERSION_CHANGED"
    | "SHEET_CHANGED"
    | "TABLE_COUNT_CHANGED"
    | "TABLE_NAME_CHANGED"
    | "VALUES_NAME_CHANGED"
    | "DIMENSION_COUNT_CHANGED"
    | "DIMENSION_NAME_CHANGED"
    | "DIRECTION_CHANGED"
    | "SELECTOR_REPRESENTATION_CHANGED"
    | "SELECTOR_IDENTITY_CHANGED"
    | "UNSUPPORTED_RECIPE_MODIFIER";
  path: string;
  expected: unknown;
  actual: unknown;
};

/**
 * Pure deterministic compiler for the canonical CellRoleSketch v0.2 subset.
 * The caller must supply the validated object returned by parseCellRoleSketchV02.
 */
export function compileCellRoleSketch(
  sketch: CellRoleSketchV02,
  geometryOptions: CellRoleGeometryOptions = {},
): CellRoleCompileResult {
  const preflight = preflightSketch(sketch, geometryOptions);
  if (preflight) return { ok: false, error: preflight };

  const recipe: RecipeV01 = {
    version: "0.1",
    sheet: sketch.sheet,
    tables: sketch.tables.map((table) => ({
      name: table.name,
      values: {
        name: table.values.name,
        cells: compileSelector(table.values),
      },
      headers: table.dimensions.map((dimension) => {
        const relationship = table.relationships.find(
          (entry) => entry.dimensionId === dimension.id,
        )!;
        return {
          name: dimension.name,
          direction: DIRECTION_BY_RELATIONSHIP[relationship.kind],
          cells: compileSelector(dimension),
        };
      }),
    })),
  };

  const validation = validateRecipe(recipe);
  if (!validation.success) {
    return {
      ok: false,
      error: {
        code: "COMPILED_RECIPE_INVALID",
        path: "$",
        message: validation.errors
          .map((issue) => `${issue.path}: ${issue.message}`)
          .join("; "),
      },
    };
  }

  const differences = proveCellRoleSketchRecipeEquivalence(
    sketch,
    validation.data,
  );
  if (differences.length) {
    return {
      ok: false,
      error: {
        code: "EQUIVALENCE_PROOF_FAILED",
        path: differences[0].path,
        message: differences
          .map((entry) => `${entry.code}:${entry.path}`)
          .join("; "),
      },
    };
  }

  return {
    ok: true,
    recipe: validation.data,
    canonicalJson: `${JSON.stringify(validation.data)}\n`,
    compilerVersion: CELL_ROLE_COMPILER_VERSION,
  };
}

/** Compact structural proof. It never expands a range. */
export function proveCellRoleSketchRecipeEquivalence(
  sketch: CellRoleSketchV02,
  recipe: RecipeV01,
): CellRoleEquivalenceDifference[] {
  const differences: CellRoleEquivalenceDifference[] = [];
  addDifference(
    differences,
    recipe.version === "0.1",
    "VERSION_CHANGED",
    "version",
    "0.1",
    recipe.version,
  );
  addDifference(
    differences,
    recipe.sheet === sketch.sheet,
    "SHEET_CHANGED",
    "sheet",
    sketch.sheet,
    recipe.sheet,
  );
  addDifference(
    differences,
    recipe.tables.length === sketch.tables.length,
    "TABLE_COUNT_CHANGED",
    "tables",
    sketch.tables.length,
    recipe.tables.length,
  );
  if (recipe.options !== undefined) {
    differences.push({
      code: "UNSUPPORTED_RECIPE_MODIFIER",
      path: "options",
      expected: undefined,
      actual: recipe.options,
    });
  }

  sketch.tables.forEach((table, tableIndex) => {
    const output = recipe.tables[tableIndex];
    if (!output) return;
    const tablePath = `tables.${tableIndex}`;
    addDifference(
      differences,
      output.name === table.name,
      "TABLE_NAME_CHANGED",
      `${tablePath}.name`,
      table.name,
      output.name,
    );
    addDifference(
      differences,
      output.values.name === table.values.name,
      "VALUES_NAME_CHANGED",
      `${tablePath}.values.name`,
      table.values.name,
      output.values.name,
    );
    compareCompactSelector(
      table.values,
      output.values.cells,
      `${tablePath}.values.cells`,
      differences,
    );
    addDifference(
      differences,
      output.headers.length === table.dimensions.length,
      "DIMENSION_COUNT_CHANGED",
      `${tablePath}.headers`,
      table.dimensions.length,
      output.headers.length,
    );
    if (output.options !== undefined) {
      differences.push({
        code: "UNSUPPORTED_RECIPE_MODIFIER",
        path: `${tablePath}.options`,
        expected: undefined,
        actual: output.options,
      });
    }
    table.dimensions.forEach((dimension, dimensionIndex) => {
      const header = output.headers[dimensionIndex];
      if (!header) return;
      const headerPath = `${tablePath}.headers.${dimensionIndex}`;
      addDifference(
        differences,
        header.name === dimension.name,
        "DIMENSION_NAME_CHANGED",
        `${headerPath}.name`,
        dimension.name,
        header.name,
      );
      const relationship = table.relationships.find(
        (entry) => entry.dimensionId === dimension.id,
      );
      const expectedDirection = relationship
        ? proofDirection(relationship.kind)
        : undefined;
      addDifference(
        differences,
        header.direction === expectedDirection,
        "DIRECTION_CHANGED",
        `${headerPath}.direction`,
        expectedDirection,
        header.direction,
      );
      compareCompactSelector(
        dimension,
        header.cells,
        `${headerPath}.cells`,
        differences,
      );
      for (const modifier of [
        "direction_overrides",
        "fill",
        "required",
      ] as const) {
        if (header[modifier] !== undefined) {
          differences.push({
            code: "UNSUPPORTED_RECIPE_MODIFIER",
            path: `${headerPath}.${modifier}`,
            expected: undefined,
            actual: header[modifier],
          });
        }
      }
    });
  });
  return differences;
}

function proofDirection(kind: RelationshipKind): HeaderDirection {
  switch (kind) {
    case "direct-column":
      return "N";
    case "direct-row":
      return "W";
    case "cascading-column":
      return "NNW";
    case "cascading-row":
      return "WNW";
  }
}

function preflightSketch(
  sketch: CellRoleSketchV02,
  geometryOptions: CellRoleGeometryOptions,
): CellRoleCompileError | null {
  if (sketch.version !== CELL_ROLE_SKETCH_V02) {
    return {
      code: "UNSUPPORTED_SKETCH_VERSION",
      path: "version",
      message: `CellRoleSketch version must be ${CELL_ROLE_SKETCH_V02}; received ${JSON.stringify(sketch.version)}.`,
    };
  }
  const unsupported = findUnsupportedConstruct(sketch);
  if (unsupported) return unsupported;
  const compilable = validateCellRoleSketchV02ForCompilation(sketch);
  if (!compilable.ok) {
    return {
      code: compilable.code,
      path: "uncertainties",
      message: compilable.message,
    };
  }
  if (!sketch.sheet.trim()) return emptyName("sheet");
  if (!sketch.tables.length) {
    return {
      code: "UNSUPPORTED_CONSTRUCT",
      path: "tables",
      message: "At least one table is required.",
    };
  }
  const tableNames = new Set<string>();
  for (const [tableIndex, table] of sketch.tables.entries()) {
    const tablePath = `tables.${tableIndex}`;
    if (!table.name.trim()) return emptyName(`${tablePath}.name`);
    if (tableNames.has(table.name)) {
      return {
        code: "DUPLICATE_TABLE_NAME",
        path: `${tablePath}.name`,
        message: `Duplicate table name ${JSON.stringify(table.name)}.`,
      };
    }
    tableNames.add(table.name);
    if (!table.values.name.trim()) return emptyName(`${tablePath}.values.name`);
    if (!table.dimensions.length) {
      return {
        code: "HEADERLESS_TABLE_UNSUPPORTED",
        path: `${tablePath}.dimensions`,
        message:
          "Headerless tables are outside the supported CellRoleSketch v0.2 compiler subset.",
      };
    }
    const selectorError = validateSelector(table.values, `${tablePath}.values`);
    if (selectorError) return selectorError;

    const outputNames = new Set<string>();
    const generatedNames = new Set(["_source"]);
    outputNames.add(table.values.name);
    if (table.values.name === "_source") {
      return reservedCollision(`${tablePath}.values.name`, table.values.name);
    }
    for (const [dimensionIndex, dimension] of table.dimensions.entries()) {
      const dimensionPath = `${tablePath}.dimensions.${dimensionIndex}`;
      if (!dimension.name.trim()) return emptyName(`${dimensionPath}.name`);
      if (outputNames.has(dimension.name)) {
        return {
          code: "DUPLICATE_OUTPUT_NAME",
          path: `${dimensionPath}.name`,
          message: `Output name ${JSON.stringify(dimension.name)} is duplicated.`,
        };
      }
      outputNames.add(dimension.name);
      const dimensionSelectorError = validateSelector(dimension, dimensionPath);
      if (dimensionSelectorError) return dimensionSelectorError;
    }
    for (const name of outputNames) {
      if (generatedNames.has(name)) {
        return reservedCollision(`${tablePath}.name`, name);
      }
      generatedNames.add(`${name}_source`);
    }
    for (const name of outputNames) {
      if (generatedNames.has(name)) {
        return reservedCollision(`${tablePath}.name`, name);
      }
    }

    const dimensionIds = new Set(
      table.dimensions.map((dimension) => dimension.id),
    );
    for (const relationship of table.relationships) {
      if (!dimensionIds.has(relationship.dimensionId)) {
        return {
          code: "RELATIONSHIP_TARGET_INVALID",
          path: `${tablePath}.relationships`,
          message: `Relationship ${relationship.id} targets unknown dimension ${relationship.dimensionId}.`,
        };
      }
    }
    for (const [dimensionIndex, dimension] of table.dimensions.entries()) {
      const matches = table.relationships.filter(
        (relationship) => relationship.dimensionId === dimension.id,
      );
      if (matches.length !== 1) {
        return {
          code: "RELATIONSHIP_CARDINALITY",
          path: `${tablePath}.dimensions.${dimensionIndex}`,
          message: `Dimension ${dimension.id} requires exactly one relationship; found ${matches.length}.`,
        };
      }
    }
  }
  const geometry = validateCellRoleSketchGeometry(sketch, geometryOptions);
  if (!geometry.valid) {
    const diagnostic = geometry.diagnostics.find(
      (entry) => entry.severity === "error",
    )!;
    return {
      code: "GEOMETRY_VALIDATION_FAILED",
      path: diagnostic.path,
      message: `${diagnostic.code}: ${diagnostic.message}`,
    };
  }
  return null;
}

function validateSelector(
  selector: SketchRoleSelectorV02,
  path: string,
): CellRoleCompileError | null {
  if (!selector.sources.length) {
    return {
      code: "UNSUPPORTED_SELECTOR_REPRESENTATION",
      path: `${path}.sources`,
      message: "Selector must contain at least one source.",
    };
  }
  if (
    selector.sources.some((source) =>
      source.selector.kind === "range"
        ? !CANONICAL_RANGE.test(source.selector.value)
        : !CANONICAL_ADDRESS.test(source.selector.value),
    )
  ) {
    return {
      code: "UNSUPPORTED_SELECTOR_REPRESENTATION",
      path: `${path}.sources`,
      message:
        "Range syntax must use a range selector; sparse address selectors must contain canonical individual R1C1 addresses only.",
    };
  }
  const ranges = selector.sources.filter(
    (source) => source.selector.kind === "range",
  );
  const addresses = selector.sources.filter(
    (source) => source.selector.kind === "address",
  );
  if (
    ranges.length > 1 ||
    (ranges.length > 0 && addresses.length > 0) ||
    (ranges.length === 0 && addresses.length !== selector.sources.length)
  ) {
    return {
      code: "UNSUPPORTED_SELECTOR_REPRESENTATION",
      path: `${path}.sources`,
      message:
        "Selector must use exactly one compact range or one or more sparse addresses.",
    };
  }
  return null;
}

function compileSelector(selector: SketchRoleSelectorV02): CellSelector {
  const source = selector.sources[0];
  return source.selector.kind === "range"
    ? { range: source.selector.value }
    : { cells: selector.sources.map((entry) => entry.selector.value) };
}

function compareCompactSelector(
  expected: SketchRoleSelectorV02,
  actual: CellSelector,
  path: string,
  differences: CellRoleEquivalenceDifference[],
): void {
  const expectedRange =
    expected.sources.length === 1 &&
    expected.sources[0].selector.kind === "range"
      ? expected.sources[0].selector.value
      : undefined;
  if (expectedRange !== undefined) {
    const actualRange =
      isRecord(actual) &&
      !Array.isArray(actual) &&
      hasExactKeys(actual, ["range"])
        ? actual.range
        : undefined;
    addDifference(
      differences,
      typeof actualRange === "string",
      "SELECTOR_REPRESENTATION_CHANGED",
      path,
      { range: expectedRange },
      actual,
    );
    if (typeof actualRange === "string") {
      addDifference(
        differences,
        actualRange === expectedRange,
        "SELECTOR_IDENTITY_CHANGED",
        path,
        expectedRange,
        actualRange,
      );
    }
    return;
  }

  const expectedCells = expected.sources.map((source) => source.selector.value);
  const actualCells =
    isRecord(actual) &&
    !Array.isArray(actual) &&
    hasExactKeys(actual, ["cells"]) &&
    Array.isArray(actual.cells)
      ? actual.cells
      : undefined;
  addDifference(
    differences,
    actualCells !== undefined,
    "SELECTOR_REPRESENTATION_CHANGED",
    path,
    { cells: expectedCells },
    actual,
  );
  if (actualCells) {
    addDifference(
      differences,
      JSON.stringify(actualCells) === JSON.stringify(expectedCells),
      "SELECTOR_IDENTITY_CHANGED",
      path,
      expectedCells,
      actualCells,
    );
  }
}

function findUnsupportedConstruct(
  sketch: CellRoleSketchV02,
): CellRoleCompileError | null {
  const checks: Array<[Record<string, unknown>, readonly string[], string]> = [
    [
      sketch as unknown as Record<string, unknown>,
      ["version", "sheet", "tables", "uncertainties"],
      "$",
    ],
  ];
  sketch.tables.forEach((table, tableIndex) => {
    const tablePath = `tables.${tableIndex}`;
    checks.push([
      table as unknown as Record<string, unknown>,
      [
        "id",
        "name",
        "evidence",
        "selectorBounds",
        "physicalExtent",
        "values",
        "dimensions",
        "relationships",
      ],
      tablePath,
    ]);
    checks.push([
      table.values as unknown as Record<string, unknown>,
      ["id", "name", "evidence", "sources", "addresses"],
      `${tablePath}.values`,
    ]);
    table.dimensions.forEach((dimension, dimensionIndex) =>
      checks.push([
        dimension as unknown as Record<string, unknown>,
        ["id", "name", "evidence", "sources", "addresses"],
        `${tablePath}.dimensions.${dimensionIndex}`,
      ]),
    );
    const roleSelectors = [table.values, ...table.dimensions];
    roleSelectors.forEach((role, roleIndex) => {
      const rolePath =
        roleIndex === 0
          ? `${tablePath}.values`
          : `${tablePath}.dimensions.${roleIndex - 1}`;
      role.sources.forEach((source, sourceIndex) => {
        checks.push([
          source as unknown as Record<string, unknown>,
          ["id", "selector", "evidence"],
          `${rolePath}.sources.${sourceIndex}`,
        ]);
        checks.push([
          source.selector as unknown as Record<string, unknown>,
          ["kind", "value"],
          `${rolePath}.sources.${sourceIndex}.selector`,
        ]);
      });
    });
    table.relationships.forEach((relationship, relationshipIndex) =>
      checks.push([
        relationship as unknown as Record<string, unknown>,
        ["id", "dimensionId", "kind", "evidence"],
        `${tablePath}.relationships.${relationshipIndex}`,
      ]),
    );
  });
  sketch.uncertainties.forEach((uncertainty, uncertaintyIndex) =>
    checks.push([
      uncertainty as unknown as Record<string, unknown>,
      ["id", "target", "field", "alternatives", "evidence", "blocking"],
      `uncertainties.${uncertaintyIndex}`,
    ]),
  );
  for (const [value, keys, path] of checks) {
    const allowed = new Set(keys);
    const unsupported = Object.keys(value).find((key) => !allowed.has(key));
    if (unsupported) {
      return {
        code: "UNSUPPORTED_CONSTRUCT",
        path: `${path}.${unsupported}`,
        message: `Unsupported sketch construct ${path}.${unsupported}.`,
      };
    }
  }
  return null;
}

function emptyName(path: string): CellRoleCompileError {
  return { code: "EMPTY_NAME", path, message: `${path} must not be empty.` };
}

function reservedCollision(path: string, name: string): CellRoleCompileError {
  return {
    code: "RESERVED_OUTPUT_COLLISION",
    path,
    message: `Output name ${JSON.stringify(name)} collides with a reserved or generated source column.`,
  };
}

function addDifference(
  target: CellRoleEquivalenceDifference[],
  condition: boolean,
  code: CellRoleEquivalenceDifference["code"],
  path: string,
  expected: unknown,
  actual: unknown,
): void {
  if (!condition) target.push({ code, path, expected, actual });
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  return (
    JSON.stringify(Object.keys(value).sort()) ===
    JSON.stringify([...expected].sort())
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
