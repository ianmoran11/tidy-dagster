import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import {
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { isDeepStrictEqual, promisify } from "node:util";
import type { WorkerResult } from "../apps/domain-worker/src/protocol/worker.js";

const execFileAsync = promisify(execFile);

export const fixtureNames = [
  "simple-crosstab",
  "sparse-headers",
  "multi-table",
] as const;
export type FixtureName = (typeof fixtureNames)[number];
export type FixtureRun = {
  result: Extract<WorkerResult, { ok: true }>;
  files: Map<string, Buffer>;
};

export async function runFixtureTwice(name: FixtureName): Promise<FixtureRun> {
  const first = await runFixture(name, "tidy-parity-a-");
  const second = await runFixture(name, "tidy-parity-relocated-b-");
  if (!isDeepStrictEqual(first.result, second.result))
    throw new Error(`${name}: relocated result manifests differ`);
  if (first.files.size !== second.files.size)
    throw new Error(`${name}: relocated file sets differ`);
  for (const [relativePath, bytes] of first.files) {
    const other = second.files.get(relativePath);
    if (!other?.equals(bytes))
      throw new Error(`${name}: relocated bytes differ for ${relativePath}`);
  }
  await assertPartialSourceGold(name, first);
  return first;
}

async function runFixture(
  name: FixtureName,
  prefix: string,
): Promise<FixtureRun> {
  const root = await mkdtemp(path.join(tmpdir(), prefix));
  try {
    const inputRoot = path.join(root, "staged-inputs");
    const outputRoot = path.join(root, "worker-outputs");
    await mkdir(path.join(inputRoot, "inputs"), { recursive: true });
    await mkdir(outputRoot);
    const workbookPath = `fixtures/workbooks/${name}.xlsx`;
    const recipePath = `fixtures/recipes/${name}.json`;
    await copyFile(workbookPath, path.join(inputRoot, "inputs/workbook.xlsx"));
    await copyFile(recipePath, path.join(inputRoot, "inputs/recipe.json"));
    const request = {
      protocolVersion: "tidy.worker/v1",
      requestId: `parity-${name}`,
      operation: "execute-recipe-v01",
      inputs: [
        {
          name: "workbook",
          relativePath: "inputs/workbook.xlsx",
          contentDigest: await digestFile(workbookPath),
          byteLength: (await readFile(workbookPath)).byteLength,
        },
        {
          name: "recipe",
          relativePath: "inputs/recipe.json",
          contentDigest: await digestFile(recipePath),
          byteLength: (await readFile(recipePath)).byteLength,
        },
      ],
      parameters: {
        evidenceProfile:
          name === "simple-crosstab"
            ? "m1-simple-v1"
            : "m2-deterministic-parity-v1",
        csvMode: "recipe-aware",
      },
      limits: {
        timeoutMs: 30_000,
        maxInputBytes: 20_000_000,
        maxOutputBytes: 10_000_000,
        maxOutputFiles: 100,
        maxWarnings: 1_000,
        maxWorkbookCompressedBytes: 10_000_000,
        maxZipEntries: 1_000,
        maxZipEntryUncompressedBytes: 10_000_000,
        maxZipTotalUncompressedBytes: 20_000_000,
        maxSheets: 100,
        maxCells: 100_000,
        maxMerges: 10_000,
        maxMergeExpansionCells: 100_000,
        maxSelectorCells: 100_000,
        maxOutputRows: 100_000,
      },
    };
    const requestPath = path.join(root, "request.json");
    await writeFile(requestPath, JSON.stringify(request));
    const { stdout, stderr } = await execFileAsync(
      process.execPath,
      [
        "dist/apps/domain-worker/src/cli.js",
        "--request",
        requestPath,
        "--input-root",
        inputRoot,
        "--output-root",
        outputRoot,
      ],
      { maxBuffer: 1_000_000 },
    );
    if (stderr !== "") throw new Error(`${name}: CLI wrote unexpected stderr`);
    if (!stdout.endsWith("\n") || stdout.trim().split("\n").length !== 1)
      throw new Error(`${name}: CLI did not emit exactly one JSON line`);
    const result = JSON.parse(stdout) as WorkerResult;
    if (!result.ok)
      throw new Error(`${name}: ${result.error.code}: ${result.error.message}`);
    const files = new Map<string, Buffer>();
    for (const output of result.outputs) {
      const bytes = await readFile(path.join(outputRoot, output.relativePath));
      if (
        sha256(bytes) !== output.contentDigest ||
        bytes.byteLength !== output.byteLength
      )
        throw new Error(
          `${name}: output descriptor drift for ${output.relativePath}`,
        );
      files.set(output.relativePath, bytes);
    }
    return { result, files };
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function assertPartialSourceGold(
  name: FixtureName,
  run: FixtureRun,
): Promise<void> {
  const expected = JSON.parse(
    await readFile(`fixtures/expected/${name}.json`, "utf8"),
  ) as {
    sheet: string;
    tables: Array<{ name: string; rows: unknown[] }>;
    non_table_cells: unknown[];
  };
  const execution = JSON.parse(
    run.files.get("execution.json")!.toString("utf8"),
  ) as {
    sheet: string;
    tables: Array<{ table: string; rows: unknown[] }>;
    non_table_cells: unknown[];
  };
  const comparable = {
    sheet: execution.sheet,
    tables: execution.tables.map((table) => ({
      name: table.table,
      rows: table.rows,
    })),
    non_table_cells: execution.non_table_cells,
  };
  if (!isDeepStrictEqual(comparable, expected))
    throw new Error(
      `${name}: rows/non-table cells differ from source-authored partial gold`,
    );
}

export function sha256(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
async function digestFile(file: string): Promise<string> {
  return sha256(await readFile(file));
}
