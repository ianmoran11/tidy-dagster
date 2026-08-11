import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = requireEnvironment("TIDY_SOURCE_REFERENCE_ROOT");
const output = requireEnvironment("TIDY_SOURCE_REFERENCE_OUTPUT");
const parseModule = await import(
  pathToFileURL(path.join(root, "src/lib/workbook/parseWorkbook.ts")).href
);
const contextModule = await import(
  pathToFileURL(
    path.join(
      root,
      "scripts/experiments/cell-role-pipeline/compact-context.ts",
    ),
  ).href
);
const workbookNames = ["multi-table", "simple-crosstab", "sparse-headers"];
const cases = [];

for (const workbookName of workbookNames) {
  const relativePath = `fixtures/workbooks/${workbookName}.xlsx`;
  const parsed = await parseModule.parseWorkbook(
    readFileSync(path.join(root, relativePath)),
  );
  if (!parsed.ok)
    throw new Error(`Historical source failed to parse ${workbookName}`);
  cases.push({
    caseId: workbookName,
    workbookRelativePath: relativePath,
    contexts: parsed.workbook.sheets.map((sheet: unknown) =>
      contextModule.buildCompactContextSnapshot(sheet),
    ),
  });
}

const wire = JSON.parse(JSON.stringify({ cases }));
writeFileSync(output, `${canonicalJson(wire)}\n`, {
  encoding: "utf8",
  flag: "wx",
  mode: 0o600,
});

function requireEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing ${name}`);
  return value;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string")
    return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Non-finite canonical number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
      .join(",")}}`;
  throw new Error("Unsupported canonical JSON value");
}
