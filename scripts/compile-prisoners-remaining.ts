import { readFile, writeFile, mkdir } from "node:fs/promises";
import { parseWorkbook } from "../apps/domain-worker/src/workbook/parseWorkbook.js";
import { buildCompactSemanticContext } from "../apps/domain-worker/src/context/compactContext.js";
import { buildSemanticCellFormattingFacts } from "../apps/domain-worker/src/catalog/format-aware-region-catalog-v2.js";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
  compileRoleAwareSemanticTableMap,
} from "../apps/domain-worker/src/catalog/role-aware-region-catalog-v5.js";
import { executeRecipe } from "../apps/domain-worker/src/executor/executeRecipe.js";
import { resolveRecipeSelectors } from "../apps/domain-worker/src/recipe/resolveSelectors.js";
const plan = JSON.parse(
  await readFile(
    "fixtures/product-prototype/prisoners-remaining-semantic-map-plan-v1.json",
    "utf8",
  ),
);
let ok = 0,
  fail = 0;
const result = [];
for (const f of plan.families) {
  const cohort = JSON.parse(
    await readFile(
      `fixtures/product-prototype/prisoners-${f.familyId}.json`,
      "utf8",
    ),
  );
  for (const e of cohort.workbooks) {
    const parsed = await parseWorkbook(
      await readFile(`fixtures/product-prototype/${e.path}`),
    );
    if (!parsed.ok) throw Error("parse");
    const sheet = parsed.workbook.sheets.find((x: any) => x.name === e.sheet)!;
    const context = buildCompactSemanticContext(sheet),
      catalog = buildRoleAwareSemanticRegionCatalog(context, {
        formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
        cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
      });
    const map = JSON.parse(
      await readFile(
        `fixtures/product-prototype/${e.replayResponse.path}`,
        "utf8",
      ),
    );
    const compiled = compileRoleAwareSemanticTableMap({
      map,
      catalog,
      context,
    });
    const dir = `.product-prototype/prisoners-remaining-phase1/direct/${f.familyId}`;
    await mkdir(dir, { recursive: true });
    if (!compiled.ok) {
      fail++;
      result.push({
        family: f.familyId,
        year: e.year,
        ok: false,
        code: compiled.code,
        message: compiled.message,
        diagnostics: compiled.diagnostics,
      });
      continue;
    }
    const execution = executeRecipe(compiled.recipe, sheet);
    const selectors = resolveRecipeSelectors(compiled.recipe, sheet);
    await writeFile(
      `${dir}/${e.year}.json`,
      JSON.stringify(
        { recipe: compiled.recipe, execution, selectors },
        null,
        2,
      ),
    );
    ok++;
    result.push({
      family: f.familyId,
      year: e.year,
      ok: true,
      rows: execution.tables[0]?.rows.length,
      warnings: execution.warnings.length,
    });
  }
}
await writeFile(
  ".product-prototype/prisoners-remaining-phase1/direct-summary.json",
  JSON.stringify(result, null, 2),
);
console.log(
  JSON.stringify({
    ok,
    fail,
    failed: result
      .filter((x) => !x.ok)
      .map((x) => `${x.family}:${x.year}:${x.code}`),
  }),
);
