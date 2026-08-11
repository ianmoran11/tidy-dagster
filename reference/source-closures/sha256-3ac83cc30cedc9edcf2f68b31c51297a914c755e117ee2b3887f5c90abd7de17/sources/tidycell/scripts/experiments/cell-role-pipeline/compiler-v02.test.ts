// @vitest-environment node

import { parseRange } from "../../../src/lib/address";
import type { RecipeV01 } from "../../../src/lib/recipe/types";
import { describe, expect, it } from "vitest";
import {
  parseCellRoleSketchV02,
  type CellRoleSketchV02,
} from "./cell-role-sketch-v02";
import {
  compileCellRoleSketch,
  proveCellRoleSketchRecipeEquivalence,
} from "./compiler-v02";
import {
  buildSemanticGoldDraft,
  SEMANTIC_GOLD_ASSET_SPECS,
} from "./semantic-gold-drafts";

const directionSketch = `<CellRoleSketch version="0.2" sheet="Sheet 1">
  <Table id="table-1" name="Observations" evidence="fixture">
    <Values id="values-1" name="Value"><Cell id="value-range" range="R10C10:R309C309"/></Values>
    <Dimension id="d-n" name="North" evidence="fixture"><Cell id="n" range="R9C10:R9C309"/></Dimension>
    <Dimension id="d-w" name="West" evidence="fixture"><Cell id="w" address="R10C9"/><Cell id="w2" address="R11C9"/></Dimension>
    <Dimension id="d-nnw" name="North cascade" evidence="fixture"><Cell id="nnw" address="R8C10"/></Dimension>
    <Dimension id="d-wnw" name="West cascade" evidence="fixture"><Cell id="wnw" address="R9C9"/></Dimension>
    <Relationship id="r-n" dimensionId="d-n" kind="direct-column" evidence="fixture"/>
    <Relationship id="r-w" dimensionId="d-w" kind="direct-row" evidence="fixture"/>
    <Relationship id="r-nnw" dimensionId="d-nnw" kind="cascading-column" evidence="fixture"/>
    <Relationship id="r-wnw" dimensionId="d-wnw" kind="cascading-row" evidence="fixture"/>
  </Table>
  <Table id="table-2" name="Second" evidence="multi-table order fixture">
    <Values id="values-2" name="Measure"><Cell id="value-2" address="R2C2"/><Cell id="value-3" address="R3C2"/></Values>
    <Dimension id="second-label" name="Label" evidence="fixture"><Cell id="second-label-cell" address="R2C1"/><Cell id="second-label-cell-2" address="R3C1"/></Dimension>
    <Relationship id="second-relationship" dimensionId="second-label" kind="direct-row" evidence="fixture"/>
  </Table>
</CellRoleSketch>`;

function parsedDirectionSketch(): CellRoleSketchV02 {
  const parsed = parseCellRoleSketchV02(directionSketch, {
    rowCount: 1000,
    columnCount: 1000,
  });
  if (!parsed.ok) throw new Error(`${parsed.code}: ${parsed.message}`);
  return parsed.sketch;
}

function compile(sketch = parsedDirectionSketch()) {
  return compileCellRoleSketch(sketch);
}

describe("compileCellRoleSketch", () => {
  it("mechanically compiles every direction, selector form, and table order", () => {
    const result = compile();
    expect(result).toMatchObject({ ok: true });
    if (!result.ok) return;
    expect(result.recipe).toEqual({
      version: "0.1",
      sheet: "Sheet 1",
      tables: [
        {
          name: "Observations",
          values: {
            name: "Value",
            cells: { range: "R10C10:R309C309" },
          },
          headers: [
            {
              name: "North",
              direction: "N",
              cells: { range: "R9C10:R9C309" },
            },
            {
              name: "West",
              direction: "W",
              cells: { cells: ["R10C9", "R11C9"] },
            },
            {
              name: "North cascade",
              direction: "NNW",
              cells: { cells: ["R8C10"] },
            },
            {
              name: "West cascade",
              direction: "WNW",
              cells: { cells: ["R9C9"] },
            },
          ],
        },
        {
          name: "Second",
          values: {
            name: "Measure",
            cells: { cells: ["R2C2", "R3C2"] },
          },
          headers: [
            {
              name: "Label",
              direction: "W",
              cells: { cells: ["R2C1", "R3C1"] },
            },
          ],
        },
      ],
    });
    expect(result.canonicalJson).toBe(`${JSON.stringify(result.recipe)}\n`);
    expect(
      proveCellRoleSketchRecipeEquivalence(
        parsedDirectionSketch(),
        result.recipe,
      ),
    ).toEqual([]);
  });

  it("is deterministic byte-for-byte without expanding a very large compact range", () => {
    const sketch = parsedDirectionSketch();
    const outputs = Array.from({ length: 20 }, () =>
      compileCellRoleSketch(sketch),
    );
    expect(outputs.every((entry) => entry.ok)).toBe(true);
    const bytes = outputs.map((entry) => (entry.ok ? entry.canonicalJson : ""));
    expect(new Set(bytes)).toHaveLength(1);
    expect(bytes[0]).toContain('"range":"R10C10:R309C309"');
  }, 20_000);

  it.each([
    [
      "future sketch version",
      (sketch: CellRoleSketchV02) => {
        (sketch as unknown as { version: string }).version = "9.9";
      },
      "UNSUPPORTED_SKETCH_VERSION",
    ],
    [
      "historical sketch version",
      (sketch: CellRoleSketchV02) => {
        (sketch as unknown as { version: string }).version = "0.1";
      },
      "UNSUPPORTED_SKETCH_VERSION",
    ],
    [
      "missing sketch version",
      (sketch: CellRoleSketchV02) => {
        delete (sketch as unknown as { version?: string }).version;
      },
      "UNSUPPORTED_SKETCH_VERSION",
    ],
    [
      "table name",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[1].name = sketch.tables[0].name;
      },
      "DUPLICATE_TABLE_NAME",
    ],
    [
      "values/header name",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[0].dimensions[0].name = sketch.tables[0].values.name;
      },
      "DUPLICATE_OUTPUT_NAME",
    ],
    [
      "duplicate header name",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[0].dimensions[1].name =
          sketch.tables[0].dimensions[0].name;
      },
      "DUPLICATE_OUTPUT_NAME",
    ],
    [
      "reserved _source",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[0].values.name = "_source";
      },
      "RESERVED_OUTPUT_COLLISION",
    ],
    [
      "generated source column",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[0].values.name = "North_source";
      },
      "RESERVED_OUTPUT_COLLISION",
    ],
    [
      "empty name",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[0].name = " ";
      },
      "EMPTY_NAME",
    ],
    [
      "unsupported modifier",
      (sketch: CellRoleSketchV02) => {
        (sketch.tables[0] as unknown as Record<string, unknown>).options = {};
      },
      "UNSUPPORTED_CONSTRUCT",
    ],
    [
      "missing relationship",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[0].relationships.shift();
      },
      "RELATIONSHIP_CARDINALITY",
    ],
    [
      "headerless table",
      (sketch: CellRoleSketchV02) => {
        sketch.tables[1].dimensions = [];
        sketch.tables[1].relationships = [];
      },
      "HEADERLESS_TABLE_UNSUPPORTED",
    ],
  ])("returns a typed error for %s", (_label, mutate, code) => {
    const sketch = structuredClone(parsedDirectionSketch());
    mutate(sketch);
    expect(compileCellRoleSketch(sketch)).toMatchObject({
      ok: false,
      error: { code },
    });
  });

  it("rejects unattached relationship geometry before recipe emission", () => {
    const parsed = parseCellRoleSketchV02(
      `<CellRoleSketch version="0.2" sheet="Sheet 1"><Table id="table-main" name="T" evidence="fixture"><Values id="values" name="V"><Cell id="value" address="R3C2"/></Values><Dimension id="dimension" name="D" evidence="fixture"><Cell id="header" address="R4C2"/></Dimension><Relationship id="relationship" dimensionId="dimension" kind="direct-column" evidence="fixture"/></Table></CellRoleSketch>`,
      { rowCount: 4, columnCount: 2 },
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(compileCellRoleSketch(parsed.sketch)).toEqual({
      ok: false,
      error: expect.objectContaining({
        code: "GEOMETRY_VALIDATION_FAILED",
        message: expect.stringContaining("UNATTACHED_HEADER"),
      }),
    });
  });

  it("rejects the v1 range-inside-sparse failure before recipe emission", () => {
    const sketch = structuredClone(parsedDirectionSketch());
    sketch.tables[0].values.sources = [
      {
        id: "invalid-sparse-range",
        selector: { kind: "address", value: "R1C1:R2C2" },
      },
    ];
    expect(compileCellRoleSketch(sketch)).toMatchObject({
      ok: false,
      error: { code: "UNSUPPORTED_SELECTOR_REPRESENTATION" },
    });
  });

  it("rejects multiple ranges and mixed selectors with one stable representability error", () => {
    for (const sources of [
      [
        {
          id: "range-a",
          selector: { kind: "range" as const, value: "R1C1:R2C2" },
        },
        {
          id: "range-b",
          selector: { kind: "range" as const, value: "R3C3:R4C4" },
        },
      ],
      [
        {
          id: "range-a",
          selector: { kind: "range" as const, value: "R1C1:R2C2" },
        },
        { id: "cell-a", selector: { kind: "address" as const, value: "R3C3" } },
      ],
    ]) {
      const sketch = structuredClone(parsedDirectionSketch());
      sketch.tables[0].values.sources = sources;
      expect(compileCellRoleSketch(sketch)).toMatchObject({
        ok: false,
        error: { code: "UNSUPPORTED_SELECTOR_REPRESENTATION" },
      });
    }
  });

  it("the independent proof catches name, address, range, representation, direction, modifier, and order drift", () => {
    const sketch = parsedDirectionSketch();
    const result = compile(sketch);
    if (!result.ok) throw new Error(result.error.message);
    const mutations: Array<[string, (recipe: RecipeV01) => void]> = [
      [
        "TABLE_NAME_CHANGED",
        (recipe) => {
          recipe.tables[0].name = "changed";
        },
      ],
      [
        "VALUES_NAME_CHANGED",
        (recipe) => {
          recipe.tables[0].values.name = "changed";
        },
      ],
      [
        "SELECTOR_IDENTITY_CHANGED",
        (recipe) => {
          recipe.tables[0].values.cells = { range: "R10C10:R308C309" };
        },
      ],
      [
        "SELECTOR_REPRESENTATION_CHANGED",
        (recipe) => {
          recipe.tables[0].headers[1].cells = { range: "R10C9:R11C9" };
        },
      ],
      [
        "SELECTOR_REPRESENTATION_CHANGED",
        (recipe) => {
          recipe.tables[0].values.cells = {
            range: "R10C10:R309C309",
            where: { non_blank: true },
          };
        },
      ],
      [
        "SELECTOR_REPRESENTATION_CHANGED",
        (recipe) => {
          recipe.tables[0].headers[1].cells = {
            range: "R10C9:R11C9",
            cells: ["R10C9", "R11C9"],
          };
        },
      ],
      [
        "SELECTOR_IDENTITY_CHANGED",
        (recipe) => {
          recipe.tables[0].headers[1].cells = { cells: ["R11C9", "R10C9"] };
        },
      ],
      [
        "DIMENSION_NAME_CHANGED",
        (recipe) => {
          recipe.tables[0].headers[0].name = "changed";
        },
      ],
      [
        "DIRECTION_CHANGED",
        (recipe) => {
          recipe.tables[0].headers[0].direction = "W";
        },
      ],
      [
        "UNSUPPORTED_RECIPE_MODIFIER",
        (recipe) => {
          recipe.tables[0].headers[0].required = true;
        },
      ],
      [
        "TABLE_NAME_CHANGED",
        (recipe) => {
          recipe.tables.reverse();
        },
      ],
      [
        "DIMENSION_NAME_CHANGED",
        (recipe) => {
          recipe.tables[0].headers.reverse();
        },
      ],
    ];
    for (const [code, mutate] of mutations) {
      const recipe = structuredClone(result.recipe);
      mutate(recipe);
      expect(
        proveCellRoleSketchRecipeEquivalence(sketch, recipe).map(
          (entry) => entry.code,
        ),
      ).toContain(code);
    }
  });

  it("compiles or stably rejects all eight pending PRD 003 structural drafts without treating them as authorized gold", () => {
    const outcomes = SEMANTIC_GOLD_ASSET_SPECS.map((spec) => {
      const extent = parseRange(spec.physicalExtent);
      const draft = buildSemanticGoldDraft({
        spec,
        workbookSha256: "0".repeat(64),
        workbookBytes: 1,
        worksheetOrdinal: 0,
        rowCount: extent.end.row,
        columnCount: extent.end.col,
      });
      const table = draft.tables[0];
      const dimensions = table.dimensions.flatMap(
        (dimension) => dimension.levels,
      );
      const xml = `<CellRoleSketch version="0.2" sheet="${escapeXml(draft.worksheet.name)}"><Table id="table-main" name="${escapeXml(table.displayLabel)}" evidence="pending structural fixture"><Values id="values-main" name="Value">${table.valueAddresses.map((address, index) => `<Cell id="value-${index}" address="${address}"/>`).join("")}</Values>${dimensions.map((level) => `<Dimension id="${level.id}" name="${escapeXml(level.displayLabel)}" evidence="pending structural fixture">${level.headerSourceAddresses.map((address, index) => `<Cell id="${level.id}-cell-${index}" address="${address}"/>`).join("")}</Dimension><Relationship id="${level.id}-relationship" dimensionId="${level.id}" kind="${level.relationshipKind}" evidence="pending structural fixture"/>`).join("")}</Table></CellRoleSketch>`;
      const parsed = parseCellRoleSketchV02(xml, {
        rowCount: draft.worksheet.rowCount,
        columnCount: draft.worksheet.columnCount,
      });
      if (!parsed.ok) return `${spec.assetId}:parse:${parsed.code}`;
      const compiled = compileCellRoleSketch(parsed.sketch);
      return compiled.ok
        ? `${spec.assetId}:compiled`
        : `${spec.assetId}:compile:${compiled.error.code}`;
    });
    expect(outcomes).toHaveLength(8);
    expect(outcomes.every((outcome) => !outcome.includes(":parse:"))).toBe(
      true,
    );
    expect(
      outcomes.every(
        (outcome) =>
          outcome.endsWith(":compiled") ||
          outcome.endsWith(":compile:DUPLICATE_OUTPUT_NAME") ||
          outcome.endsWith(":compile:RESERVED_OUTPUT_COLLISION"),
      ),
    ).toBe(true);
  });
});

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;");
}
