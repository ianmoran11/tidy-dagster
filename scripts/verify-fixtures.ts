import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

type SourceManifest = {
  admissionOrder: string[];
  files: Array<{
    fixture: string;
    copiedPath: string;
    byteLength: number;
    sha256: string;
    admissionMilestone: string;
  }>;
};

const manifest = JSON.parse(
  await readFile("fixtures/parity/source-manifest.json", "utf8"),
) as SourceManifest;
const expectedOrder = ["simple-crosstab", "sparse-headers", "multi-table"];
if (JSON.stringify(manifest.admissionOrder) !== JSON.stringify(expectedOrder))
  throw new Error("Fixture admission order drifted.");
if (manifest.files.length !== 9)
  throw new Error("Source manifest must declare exactly nine fixture files.");
for (const [index, fixture] of expectedOrder.entries()) {
  const entries = manifest.files.filter((entry) => entry.fixture === fixture);
  if (entries.length !== 3)
    throw new Error(`${fixture} must have exactly three files.`);
  const firstIndex = manifest.files.findIndex(
    (entry) => entry.fixture === fixture,
  );
  if (firstIndex !== index * 3)
    throw new Error(`${fixture} is out of admission order.`);
}
for (const entry of manifest.files) {
  const bytes = await readFile(entry.copiedPath);
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (bytes.byteLength !== entry.byteLength || digest !== entry.sha256)
    throw new Error(`Fixture drift: ${entry.copiedPath}`);
}
console.log(
  "fixture-verification: 9/9 pinned files match byte lengths and SHA-256; admission order M0 -> M2-sparse -> M2-multi-table",
);
