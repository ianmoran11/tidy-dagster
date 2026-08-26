import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { parseWorkbook } from "../apps/domain-worker/src/workbook/parseWorkbook.js";
import { buildCompactSemanticContext } from "../apps/domain-worker/src/context/compactContext.js";
import { buildSemanticCellFormattingFacts } from "../apps/domain-worker/src/catalog/format-aware-region-catalog-v2.js";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
} from "../apps/domain-worker/src/catalog/role-aware-region-catalog-v5.js";

const registered = new Set([
  "offenders-by-principal-offence-and-period",
  "offenders-by-sex-principal-offence-and-period",
  "offenders-by-principal-offence-age-and-period",
  "offender-rates-by-principal-offence-age-and-period",
  "offenders-by-sex-age-period-and-statistic",
]);
const bounded: Record<string, string> = {
  "workbooks/recorded-crime-offenders-2022-23-cube-4-source.xlsx": "workbooks/recorded-crime-offenders-2022-23-cube-4-remaining-bounded.xlsx",
  "workbooks/recorded-crime-offenders-2023-24-cube-2-source.xlsx": "workbooks/recorded-crime-offenders-2023-24-cube-2-remaining-bounded.xlsx",
  "workbooks/recorded-crime-offenders-2023-24-cube-3-source.xlsx": "workbooks/recorded-crime-offenders-2023-24-cube-3-remaining-bounded.xlsx",
  "workbooks/recorded-crime-offenders-2024-25-cube-3-source.xlsx": "workbooks/recorded-crime-offenders-2024-25-cube-3-remaining-bounded.xlsx",
  "workbooks/recorded-crime-offenders-2023-24-cube-7-source.xlsx": "workbooks/recorded-crime-offenders-2023-24-cube-7-remaining-bounded.xlsx",
  "workbooks/recorded-crime-offenders-2024-25-cube-7-source.xlsx": "workbooks/recorded-crime-offenders-2024-25-cube-7-remaining-bounded.xlsx",
};
const membership = JSON.parse(await readFile("fixtures/product-prototype/offenders-release-family-membership-v1.json", "utf8"));
const pending = membership.families
  .filter((family: any) => !registered.has(family.familyId))
  .flatMap((family: any) => family.members.map((member: any) => ({
    ...member,
    familyId: family.familyId,
    year: Number(member.releaseId.slice(0, 4)),
    sheet: member.physicalSheetName,
  })));
if (pending.length !== 170 || new Set(pending.map((member: any) => member.familyId)).size !== 47) throw new Error("pending Offenders closure mismatch");
const byPath = new Map<string, any[]>();
for (const member of pending) {
  const path = bounded[member.sourcePath] || member.sourcePath;
  const entries = byPath.get(path) || [];
  entries.push(member);
  byPath.set(path, entries);
}
const root = ".product-prototype/offenders-remaining-phase1/catalogs";
await mkdir(root, { recursive: true });
const summary = [];
for (const [path, members] of byPath) {
  const parsed = await parseWorkbook(await readFile("fixtures/product-prototype/" + path));
  if (!parsed.ok) throw new Error(path + JSON.stringify(parsed.errors));
  for (const member of members) {
    const sheet = parsed.workbook.sheets.find((item: any) => item.name === member.sheet);
    if (!sheet) throw new Error(`${path}:${JSON.stringify(member.sheet)}`);
    console.error(JSON.stringify({ path, sheet: member.sheet, rows: sheet.rowCount, columns: sheet.columnCount }));
    const context = buildCompactSemanticContext(sheet);
    const catalog = buildRoleAwareSemanticRegionCatalog(context, {
      formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
      cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
    });
    const key = `${member.releaseId}-${member.downloadOrdinal}-${member.sheet.replaceAll(" ", "_")}`;
    await writeFile(`${root}/${key}.json`, JSON.stringify({ member, executionPath: path, context, catalog }, null, 2));
    summary.push({
      key,
      member,
      executionPath: path,
      cells: sheet.cells.length,
      contextDigest: `sha256:${createHash("sha256").update(JSON.stringify(context)).digest("hex")}`,
      candidates: catalog.candidates.length,
      observationPanelCount: catalog.observationPanelCount,
      omitted: catalog.omittedCandidateCount,
    });
  }
}
await writeFile(".product-prototype/offenders-remaining-phase1/catalog-summary.json", JSON.stringify(summary, null, 2));
console.log(JSON.stringify({ families: new Set(pending.map((item: any) => item.familyId)).size, members: pending.length, workbooks: byPath.size }));
