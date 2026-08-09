import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const commit = "1be6c995fa931e9860468e40490433161b0121cb";
const tree = "96a76a1cbc6f2da3facd31d7cdae5b05926361d3";
const repository = "https://github.com/ianmoran11/tidycell.git";
const packageLockDigest =
  "sha256:cddcf7bf8b871a9a5f1a5c89229e8a714893c4caedfa5a1476d823b991fc4288";
const expectedToolchain = {
  node: "24.7.0",
  npm: "11.5.1",
  dependencies: {
    exceljs: "4.4.0",
    tsx: "4.21.0",
    typescript: "5.9.3",
    zod: "4.4.3",
  },
};
const manifest = JSON.parse(
  await readFile("fixtures/gold/manifest.json", "utf8"),
) as {
  schemaVersion: string;
  classification: string;
  scope: string;
  reference: {
    repository: string;
    sourceRemote: string;
    commit: string;
    tree: string;
    packageLockDigest: string;
  };
  runner: { path: string; contentDigest: string };
  toolchain: {
    node: string;
    npm: string;
    dependencies: Record<string, string>;
  };
  fixtures: Array<{
    name: string;
    outputs: Array<{
      relativePath: string;
      contentDigest: string;
      byteLength: number;
    }>;
  }>;
};
if (
  manifest.schemaVersion !== "tidy.reference-gold/v1" ||
  manifest.classification !== "independent-pinned-reference-bytes" ||
  manifest.reference.commit !== commit ||
  manifest.reference.tree !== tree ||
  manifest.reference.repository !== repository ||
  manifest.reference.sourceRemote !== repository ||
  manifest.reference.packageLockDigest !== packageLockDigest ||
  JSON.stringify(manifest.toolchain) !== JSON.stringify(expectedToolchain) ||
  manifest.scope !== "M0–M2-scoped deterministic compatibility slice"
)
  throw new Error("Reference-gold provenance metadata is invalid.");
const runner = await readFile(manifest.runner.path);
if (sha256(runner) !== manifest.runner.contentDigest)
  throw new Error(
    "Reference runner digest drifted; re-review before freezing gold.",
  );
for (const fixture of manifest.fixtures) {
  for (const output of fixture.outputs) {
    const bytes = await readFile(
      path.join("fixtures/gold", fixture.name, output.relativePath),
    );
    if (
      bytes.byteLength !== output.byteLength ||
      sha256(bytes) !== output.contentDigest
    )
      throw new Error(
        `${fixture.name}: independent reference bytes drifted for ${output.relativePath}.`,
      );
  }
}
console.log(
  `reference-gold-verification: ${manifest.fixtures.length} fixture sets match independent pinned reference bytes and runner digest`,
);

function sha256(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
