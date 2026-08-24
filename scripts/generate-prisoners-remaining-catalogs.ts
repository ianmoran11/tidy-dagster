import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { parseWorkbook } from "../apps/domain-worker/src/workbook/parseWorkbook.js";
import { buildCompactSemanticContext } from "../apps/domain-worker/src/context/compactContext.js";
import { buildSemanticCellFormattingFacts } from "../apps/domain-worker/src/catalog/format-aware-region-catalog-v2.js";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
} from "../apps/domain-worker/src/catalog/role-aware-region-catalog-v5.js";

const members = JSON.parse(
  await readFile(
    "fixtures/product-prototype/prisoners-release-family-membership-v1.json",
    "utf8",
  ),
).families.flatMap((f: any) =>
  f.members.map((m: any) => ({ ...m, familyId: f.familyId })),
);
const pendingFamilies = new Set([
  "national-selected-characteristics-time-series",
  "national-offence-charge-time-series",
  "national-indigenous-offence-charge-by-legal-status-prior-imprisonment",
  "national-offence-charge-by-legal-status-sex",
  "national-sentenced-indigenous-offence-by-aggregate-sentence",
  "national-sentenced-indigenous-offence-by-expected-time",
  "national-sentenced-sex-by-offence-time-series",
  "national-unsentenced-indigenous-charge-by-time-on-remand",
  "national-indigenous-status-by-sex-time-series",
  "federal-prisoners-parolees-selected-characteristics",
  "federal-prisoners-selected-characteristics-time-series",
  "federal-parolees-selected-characteristics-time-series",
  "federal-prisoners-country-of-birth",
  "state-indigenous-sex-prisoner-count-time-series",
  "state-indigenous-sex-crude-rate-time-series",
  "state-indigenous-sex-age-standardised-rate-time-series",
  "preliminary-anzsoc-2023-table-1",
  "preliminary-anzsoc-2023-table-2",
  "preliminary-anzsoc-2023-table-3",
  "preliminary-anzsoc-2023-table-4",
  "preliminary-anzsoc-2023-table-5",
]);
const pending = members.filter((m: any) => pendingFamilies.has(m.familyId));
const byPath = new Map<string, any[]>();
for (const m of pending) {
  const arr = byPath.get(m.sourcePath) || [];
  arr.push(m);
  byPath.set(m.sourcePath, arr);
}
await mkdir(".product-prototype/prisoners-remaining-phase1/catalogs", {
  recursive: true,
});
const summary = [];
for (const [path, ms] of byPath) {
  const actualPath =
    path === "workbooks/prisoners-australia-2025-national-source.xlsx"
      ? "workbooks/prisoners-australia-2025-national-remaining-bounded.xlsx"
      : path === "workbooks/prisoners-australia-2024-federal-source.xlsx"
        ? "workbooks/prisoners-australia-2024-federal-remaining-bounded.xlsx"
        : path === "workbooks/prisoners-australia-2025-federal-source.xlsx"
          ? "workbooks/prisoners-australia-2025-federal-remaining-bounded.xlsx"
          : path;
  const parsed = await parseWorkbook(
    await readFile("fixtures/product-prototype/" + actualPath),
  );
  if (!parsed.ok) throw new Error(path + JSON.stringify(parsed.errors));
  for (const m of ms) {
    const sheet = parsed.workbook.sheets.find((s: any) => s.name === m.sheet);
    if (!sheet) throw new Error(m.sheet);
    const context = buildCompactSemanticContext(sheet);
    const fmt = buildSemanticCellFormattingFacts(sheet.cells);
    const facts = buildSemanticCellDataFacts(sheet.cells);
    const catalog = buildRoleAwareSemanticRegionCatalog(context, {
      formattingFacts: fmt,
      cellDataFacts: facts,
    });
    const key = `${m.year}-${m.downloadOrdinal}-${m.sheet.replaceAll(" ", "_")}`;
    await writeFile(
      `.product-prototype/prisoners-remaining-phase1/catalogs/${key}.json`,
      JSON.stringify({ member: m, context, catalog }, null, 2),
    );
    const contextDigest = `sha256:${createHash("sha256").update(JSON.stringify(context)).digest("hex")}`;
    summary.push({
      key,
      member: m,
      cells: sheet.cells.length,
      contextDigest,
      candidates: catalog.candidates.length,
      observationPanelCount: catalog.observationPanelCount,
      omitted: catalog.omittedCandidateCount,
    });
  }
}
await writeFile(
  ".product-prototype/prisoners-remaining-phase1/catalog-summary.json",
  JSON.stringify(summary, null, 2),
);
console.log(
  JSON.stringify({
    members: pending.length,
    files: summary.length,
    workbooks: byPath.size,
  }),
);
