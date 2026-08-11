import { z } from "zod";
import { MAX_EXPANDED_RANGE_CELLS, parseCell, parseRange } from "@/lib/address";

export const dataTypeSchema = z.enum([
  "blank",
  "string",
  "numeric",
  "boolean",
  "date",
  "error",
]);

export const headerDirectionSchema = z.enum(["N", "W", "NNW", "WNW"]);
export const fillDirectionSchema = z.enum(["right", "down"]);

const r1c1AddressSchema = z.string().superRefine((value, ctx) => {
  try {
    parseCell(value);
  } catch (error) {
    ctx.addIssue({
      code: "custom",
      message: error instanceof Error ? error.message : "Invalid R1C1 address.",
    });
  }
});

const r1c1RangeSchema = z.string().superRefine((value, ctx) => {
  try {
    assertExpandableRange(value);
  } catch (error) {
    ctx.addIssue({
      code: "custom",
      message: error instanceof Error ? error.message : "Invalid R1C1 range.",
    });
  }
});

function assertExpandableRange(value: string): void {
  const range = parseRange(value);
  const cellCount =
    (range.end.row - range.start.row + 1) *
    (range.end.col - range.start.col + 1);

  if (cellCount > MAX_EXPANDED_RANGE_CELLS) {
    throw new Error(
      `Range ${value} selects ${cellCount} cells, which exceeds the supported maximum of ${MAX_EXPANDED_RANGE_CELLS}.`,
    );
  }
}

export const cellPredicateSchema = z
  .object({
    data_type: z.array(dataTypeSchema).min(1).optional(),
    non_blank: z.boolean().optional(),
    has_formula: z.boolean().optional(),
    has_comment: z.boolean().optional(),
    style_id: z.array(z.string().min(1)).min(1).optional(),
  })
  .strict();

export const cellSelectorObjectSchema = z
  .object({
    range: r1c1RangeSchema.optional(),
    cells: z.array(r1c1AddressSchema).optional(),
    where: cellPredicateSchema.optional(),
  })
  .strict()
  .superRefine((selector, ctx) => {
    if (!selector.range && !selector.cells) {
      ctx.addIssue({
        code: "custom",
        message: "Cell selector object must include range or cells.",
      });
    }
  });

const cellSelectorStringSchema = z.string().superRefine((value, ctx) => {
  try {
    if (value.includes(":")) {
      assertExpandableRange(value);
    } else {
      parseCell(value);
    }
  } catch (error) {
    ctx.addIssue({
      code: "custom",
      message:
        error instanceof Error
          ? error.message
          : "Invalid R1C1 address or range.",
    });
  }
});

const cellSelectorBaseSchema = z.union([
  cellSelectorStringSchema,
  z.array(r1c1AddressSchema),
  cellSelectorObjectSchema,
]);

export const cellSelectorSchema = z.preprocess((value) => {
  if (typeof value !== "string") {
    return value;
  }

  if (value.includes(":")) {
    return { range: value };
  }

  return [value];
}, cellSelectorBaseSchema);

export const recipeOptionsSchema = z
  .object({
    include_blank_values: z.boolean().optional(),
    preserve_source_address: z.boolean().optional(),
    preserve_header_source_address: z.boolean().optional(),
    preserve_formatted_value: z.boolean().optional(),
    preserve_non_table_cells: z.boolean().optional(),
    include_blank_non_table_cells: z.boolean().optional(),
  })
  .strict();

export const valuesSpecSchema = z
  .object({
    name: z.string().min(1),
    cells: cellSelectorSchema,
  })
  .strict();

export const headerSpecSchema = z
  .object({
    name: z.string().min(1),
    direction: headerDirectionSchema,
    direction_overrides: z
      .record(r1c1AddressSchema, headerDirectionSchema)
      .optional(),
    cells: cellSelectorSchema,
    fill: fillDirectionSchema.optional(),
    required: z.boolean().optional(),
  })
  .strict();

export const tableSpecSchema = z
  .object({
    name: z.string().min(1),
    values: valuesSpecSchema,
    headers: z.array(headerSpecSchema),
    options: recipeOptionsSchema.optional(),
  })
  .strict()
  .superRefine((table, ctx) => {
    addDuplicateNameIssues(
      table.headers.map((header) => header.name),
      ctx,
      "headers",
      "Duplicate header name within table declaration.",
    );
    addOutputKeyCollisionIssues(table, ctx);
  });

// The executor emits one column per header plus `<values.name>`, `_source`,
// and `<header.name>_source` columns. Reject names that would silently
// overwrite one another in the output rows.
function addOutputKeyCollisionIssues(
  table: {
    values: { name: string };
    headers: Array<{ name: string }>;
  },
  ctx: z.RefinementCtx,
): void {
  const headerNames = new Set(table.headers.map((header) => header.name));
  const valuesCollides =
    table.values.name === "_source" ||
    (table.values.name.endsWith("_source") &&
      headerNames.has(table.values.name.slice(0, -"_source".length)));

  if (valuesCollides) {
    ctx.addIssue({
      code: "custom",
      message: `Values name ${JSON.stringify(table.values.name)} collides with a reserved output column.`,
      path: ["values", "name"],
    });
  }

  table.headers.forEach((header, index) => {
    const sourcePrefix = header.name.endsWith("_source")
      ? header.name.slice(0, -"_source".length)
      : null;
    const collides =
      header.name === table.values.name ||
      header.name === "_source" ||
      (sourcePrefix !== null &&
        (headerNames.has(sourcePrefix) || sourcePrefix === table.values.name));

    if (collides) {
      ctx.addIssue({
        code: "custom",
        message: `Header name ${JSON.stringify(header.name)} collides with another output column (values name, _source, or a generated <name>_source column).`,
        path: ["headers", index, "name"],
      });
    }
  });
}

const recipeV01BaseSchema = z
  .object({
    version: z.literal("0.1"),
    sheet: z.string().min(1),
    tables: z.array(tableSpecSchema).min(1),
    options: recipeOptionsSchema.optional(),
  })
  .strict()
  .superRefine((recipe, ctx) => {
    addDuplicateNameIssues(
      recipe.tables.map((table) => table.name),
      ctx,
      "tables",
      "Duplicate table name within recipe.",
    );
  });

export const recipeV01Schema = z.preprocess(
  stripDiagnosticProperties,
  recipeV01BaseSchema,
);

export type RecipeValidationIssue = {
  path: string;
  code: string;
  message: string;
};

export type RecipeValidationResult<T> =
  | { success: true; data: T; errors?: never }
  | { success: false; data?: never; errors: RecipeValidationIssue[] };

export function validateRecipe(
  input: unknown,
): RecipeValidationResult<z.infer<typeof recipeV01Schema>> {
  const result = recipeV01Schema.safeParse(input);

  if (result.success) {
    return { success: true, data: result.data };
  }

  return {
    success: false,
    errors: result.error.issues.map((issue) => ({
      code: issue.code,
      message: issue.message,
      path: issue.path.length > 0 ? issue.path.join(".") : "$",
    })),
  };
}

export function parseRecipe(input: unknown): z.infer<typeof recipeV01Schema> {
  return recipeV01Schema.parse(input);
}

function addDuplicateNameIssues(
  names: string[],
  ctx: z.RefinementCtx,
  pathRoot: string,
  message: string,
): void {
  const seen = new Map<string, number>();

  names.forEach((name, index) => {
    const firstIndex = seen.get(name);

    if (firstIndex === undefined) {
      seen.set(name, index);
      return;
    }

    ctx.addIssue({
      code: "custom",
      message,
      path: [pathRoot, index, "name"],
    });
  });
}

function stripDiagnosticProperties(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stripDiagnosticProperties);
  }

  if (!value || typeof value !== "object") {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !key.startsWith("."))
      .map(([key, entry]) => [key, stripDiagnosticProperties(entry)]),
  );
}
