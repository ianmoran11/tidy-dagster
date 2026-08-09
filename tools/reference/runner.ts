/*
 * Reference evidence serializer. This file is copied into a clean checkout of
 * the pinned TidyCell commit. It imports only that checkout's public source
 * modules and adds JSON/CSV evidence serialization; it contains no candidate
 * tidy-dagster imports or transformation semantics.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { executeRecipe } from "@/lib/executor/executeRecipe";
import {
  buildHeaderDirectionGroups,
  resolveRelationshipAttachmentAtAddress,
} from "@/lib/executor/relationshipResolution";
import { rowsToCsv } from "@/lib/export/formatters";
import { resolveRecipeSelectors } from "@/lib/recipe/resolveSelectors";
import { parseRecipe } from "@/lib/recipe/schema";
import { findRecipeSheet } from "@/lib/workbook/findRecipeSheet";
import { parseWorkbook } from "@/lib/workbook/parseWorkbook";

async function main() {
  const [fixture, outputRoot] = process.argv.slice(2);
  if (!fixture || !outputRoot)
    throw new Error("Usage: runner FIXTURE OUTPUT_ROOT");

  const recipe = parseRecipe(
    JSON.parse(await readFile(`fixtures/recipes/${fixture}.json`, "utf8")),
  );
  const parsed = await parseWorkbook(
    await readFile(`fixtures/workbooks/${fixture}.xlsx`),
  );
  if (!parsed.ok) throw new Error(JSON.stringify(parsed.errors));
  const sheet = findRecipeSheet(parsed.workbook, recipe.sheet);
  if (!sheet) throw new Error(`Reference sheet ${recipe.sheet} not found.`);
  const selectors = resolveRecipeSelectors(recipe, sheet);
  const execution = executeRecipe(recipe, sheet);
  const geometry = {
    sheet: selectors.sheet,
    tables: recipe.tables.map((table, tableIndex) => {
      const selected = selectors.tables[tableIndex];
      return {
        table: table.name,
        headers: table.headers.map((header, headerIndex) => {
          const groups = buildHeaderDirectionGroups({
            headerAddresses: selected.headers[headerIndex].result.addresses,
            valueAddresses: selected.values.addresses,
            direction: header.direction,
            fill: header.fill,
            directionOverrides: header.direction_overrides,
          });
          return {
            name: header.name,
            defaultDirection: header.direction,
            anchors: groups.flatMap((group) =>
              group.candidates.map((candidate) => ({
                address: candidate.address,
                effectiveDirection: group.direction,
                spanEndRow: candidate.spanEndRow,
                spanEndCol: candidate.spanEndCol,
              })),
            ),
            values: selected.values.addresses.map((address) => ({
              address,
              ...resolveRelationshipAttachmentAtAddress(groups, address),
            })),
          };
        }),
      };
    }),
  };

  const json = async (relativePath: string, value: unknown) => {
    const destination = path.join(outputRoot, relativePath);
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(destination, `${JSON.stringify(value, null, 2)}\n`);
  };
  await json("parsed-workbook.json", parsed.workbook);
  await json("normalized-recipe.json", recipe);
  await json("selectors.json", selectors);
  await json("geometry.json", geometry);
  await json("execution.json", execution);
  for (const [index, table] of execution.tables.entries()) {
    const relativePath = `tables/${encodeURIComponent(table.table)}.csv`;
    const destination = path.join(outputRoot, relativePath);
    await mkdir(path.dirname(destination), { recursive: true });
    await writeFile(
      destination,
      rowsToCsv(table.rows, { valueColumn: recipe.tables[index].values.name }),
    );
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
