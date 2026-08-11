import { existsSync } from "node:fs";
import path from "node:path";
import type { BenchmarkManifest } from "./types";
import { getRepoRoot, readJson } from "./utils/files";

const CONTROLLED_FEATURES = new Set([
  "multi_table",
  "hierarchical_headers",
  "time_series",
  "merged_cells",
  "stacked_blocks",
  "metadata_sheet",
  "sparse_data",
  "single_table",
]);

const CONTROLLED_DIFFICULTIES = new Set(["easy", "medium", "hard"]);

export async function loadManifest(
  manifestPath = "json-examples/benchmark-manifest.json",
  repoRoot = getRepoRoot(),
): Promise<BenchmarkManifest> {
  return readJson<BenchmarkManifest>(path.resolve(repoRoot, manifestPath));
}

export function validateManifest(
  manifest: BenchmarkManifest,
  repoRoot = getRepoRoot(),
): string[] {
  const errors: string[] = [];
  const names = new Set<string>();

  if (manifest.version !== "0.1") {
    errors.push("Manifest version must be 0.1.");
  }

  if (!Array.isArray(manifest.assets)) {
    return ["Manifest assets must be an array."];
  }

  for (const asset of manifest.assets) {
    if (!asset.name) {
      errors.push("Manifest asset is missing name.");
      continue;
    }

    if (names.has(asset.name)) {
      errors.push(`Duplicate manifest asset name: ${asset.name}.`);
    }
    names.add(asset.name);

    if (!asset.enabled && !asset.disabled_reason) {
      errors.push(`Disabled asset ${asset.name} requires disabled_reason.`);
    }

    if (!asset.enabled) {
      continue;
    }

    if (!asset.expected_csv && !asset.expected_csvs) {
      errors.push(`Asset ${asset.name} is missing expected_csv or expected_csvs.`);
    }

    if (!asset.difficulty || !CONTROLLED_DIFFICULTIES.has(asset.difficulty)) {
      errors.push(
        `Asset ${asset.name} difficulty must be one of easy, medium, hard.`,
      );
    }

    if (!asset.features || asset.features.length === 0) {
      errors.push(`Asset ${asset.name} requires at least one feature tag.`);
    } else {
      for (const feature of asset.features) {
        if (!CONTROLLED_FEATURES.has(feature)) {
          errors.push(`Asset ${asset.name} has unknown feature tag: ${feature}.`);
        }
      }
    }

    for (const [field, value] of Object.entries({
      xlsx: asset.xlsx,
      recipe: asset.recipe,
      expected_csv: asset.expected_csv,
      metadata: asset.metadata,
      expected_overlay: asset.expected_overlay,
    })) {
      if (
        field !== "metadata" &&
        field !== "expected_overlay" &&
        field !== "expected_csv" &&
        !value
      ) {
        errors.push(`Asset ${asset.name} is missing ${field}.`);
        continue;
      }

      if (value && !existsSync(path.resolve(repoRoot, value))) {
        errors.push(`Asset ${asset.name} ${field} does not exist: ${value}.`);
      }
    }
  }

  return errors;
}
