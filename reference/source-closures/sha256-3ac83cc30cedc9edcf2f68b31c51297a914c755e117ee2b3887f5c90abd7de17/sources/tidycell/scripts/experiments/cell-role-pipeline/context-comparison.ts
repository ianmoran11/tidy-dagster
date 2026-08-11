import { readFile } from "node:fs/promises";
import path from "node:path";
import { findRecipeSheet } from "../../../src/lib/workbook/findRecipeSheet";
import { parseWorkbook } from "../../../src/lib/workbook/parseWorkbook";
import {
  buildCompactContextSnapshot,
  COMPACT_CONTEXT_SCHEMA_VERSION,
  countDuplicateCanonicalAddresses,
  estimateStaticTokens,
} from "./compact-context";
import { parseExperimentPlan } from "./plan";

export const CONTEXT_COMPARISON_VERSION =
  "cell-role-context-comparison-v1" as const;

type StaticMeasurement = ReturnType<typeof measure>;

export type ContextComparisonReport = {
  schemaVersion: typeof CONTEXT_COMPARISON_VERSION;
  providerFree: true;
  contextSchemaVersion: typeof COMPACT_CONTEXT_SCHEMA_VERSION;
  assets: Array<{
    asset: string;
    v1: StaticMeasurement;
    v2: StaticMeasurement;
    compact: StaticMeasurement;
    compactToV2CharacterRatio: number;
  }>;
  totals: {
    v1: StaticMeasurement;
    v2: StaticMeasurement;
    compact: StaticMeasurement;
    compactToV2CharacterRatio: number;
  };
};

export async function buildContextComparisonReport(
  repoRoot = process.cwd(),
  paths = {
    v1: "operations/cell-role-pipeline-luna-smoke-v1.plan.json",
    v2: "operations/cell-role-pipeline-luna-smoke-v2.plan.json",
  },
): Promise<ContextComparisonReport> {
  const [v1, v2] = await Promise.all([
    readHistoricalPlan(path.join(repoRoot, paths.v1)),
    readHistoricalPlan(path.join(repoRoot, paths.v2)),
  ]);
  const v1ByAsset = new Map(v1.units.map((unit) => [unit.asset, unit]));
  const assets = [];
  for (const v2Unit of v2.units) {
    const v1Unit = v1ByAsset.get(v2Unit.asset);
    if (!v1Unit || !("summary" in v1Unit) || !("summary" in v2Unit)) {
      throw new Error(`CONTEXT_COMPARISON_ASSET_MISMATCH: ${v2Unit.asset}`);
    }
    const workbookResult = await parseWorkbook(
      await readFile(path.join(repoRoot, v2Unit.assetSnapshot.xlsx)),
    );
    if (!workbookResult.ok) {
      throw new Error(`CONTEXT_COMPARISON_WORKBOOK_INVALID: ${v2Unit.asset}`);
    }
    const sheet = findRecipeSheet(workbookResult.workbook, v2Unit.sheet);
    if (!sheet) {
      throw new Error(`CONTEXT_COMPARISON_SHEET_MISSING: ${v2Unit.asset}`);
    }
    const compact = buildCompactContextSnapshot(sheet);
    const v1Text = JSON.stringify(v1Unit.summary);
    const v2Text = JSON.stringify(v2Unit.summary);
    assets.push({
      asset: v2Unit.asset,
      v1: measure(v1Text),
      v2: measure(v2Text),
      compact: measure(compact.serialized, 0),
      compactToV2CharacterRatio: ratio(compact.characters, v2Text.length),
    });
  }
  const totals = {
    v1: sumMeasurements(assets.map((asset) => asset.v1)),
    v2: sumMeasurements(assets.map((asset) => asset.v2)),
    compact: sumMeasurements(assets.map((asset) => asset.compact)),
  };
  return {
    schemaVersion: CONTEXT_COMPARISON_VERSION,
    providerFree: true,
    contextSchemaVersion: COMPACT_CONTEXT_SCHEMA_VERSION,
    assets,
    totals: {
      ...totals,
      compactToV2CharacterRatio: ratio(
        totals.compact.characters,
        totals.v2.characters,
      ),
    },
  };
}

function measure(text: string, duplicateAddressValueRepresentations?: number) {
  const addresses = countDuplicateCanonicalAddresses(text);
  return {
    characters: text.length,
    estimatedTokens: estimateStaticTokens(text.length),
    ...addresses,
    duplicateAddressValueRepresentations:
      duplicateAddressValueRepresentations ??
      addresses.duplicatedAddressOccurrences,
  };
}

function sumMeasurements(values: StaticMeasurement[]): StaticMeasurement {
  return values.reduce(
    (total, value) => ({
      characters: total.characters + value.characters,
      estimatedTokens: total.estimatedTokens + value.estimatedTokens,
      addressOccurrences: total.addressOccurrences + value.addressOccurrences,
      uniqueAddresses: total.uniqueAddresses + value.uniqueAddresses,
      duplicatedAddressOccurrences:
        total.duplicatedAddressOccurrences + value.duplicatedAddressOccurrences,
      duplicateAddressValueRepresentations:
        total.duplicateAddressValueRepresentations +
        value.duplicateAddressValueRepresentations,
    }),
    {
      characters: 0,
      estimatedTokens: 0,
      addressOccurrences: 0,
      uniqueAddresses: 0,
      duplicatedAddressOccurrences: 0,
      duplicateAddressValueRepresentations: 0,
    },
  );
}

async function readHistoricalPlan(planPath: string) {
  return parseExperimentPlan(JSON.parse(await readFile(planPath, "utf8")));
}

function ratio(numerator: number, denominator: number): number {
  return denominator === 0 ? 1 : numerator / denominator;
}
