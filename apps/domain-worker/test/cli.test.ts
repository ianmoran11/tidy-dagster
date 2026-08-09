import { spawn } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { runFixtureTwice } from "../../../scripts/parity-harness.js";

const roots: string[] = [];
afterEach(async () =>
  Promise.all(
    roots.splice(0).map((root) => rm(root, { recursive: true, force: true })),
  ),
);

async function cliRoot() {
  const root = await mkdtemp(path.join(tmpdir(), "tidy-cli-"));
  roots.push(root);
  const input = path.join(root, "input");
  const output = path.join(root, "output");
  await mkdir(input);
  await mkdir(output);
  return { root, input, output };
}

async function spawnCli(args: string[]) {
  return await new Promise<{
    code: number | null;
    stdout: string;
    stderr: string;
  }>((resolve, reject) => {
    const child = spawn(
      process.execPath,
      ["dist/apps/domain-worker/src/cli.js", ...args],
      {
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

function expectSingleEnvelope(result: { stdout: string; stderr: string }) {
  expect(result.stderr).toBe("");
  expect(result.stdout.endsWith("\n")).toBe(true);
  expect(result.stdout.trim().split("\n")).toHaveLength(1);
  return JSON.parse(result.stdout);
}

describe("built worker CLI", () => {
  it("uses a stable machine-readable invocation error and exit code 2", async () => {
    const result = await spawnCli([]);
    expect(result.code).toBe(2);
    expect(expectSingleEnvelope(result)).toMatchObject({
      ok: false,
      error: { code: "INVALID_INVOCATION", stage: "protocol" },
    });
  });

  it("uses exit code 1 for malformed and invalid protocol envelopes", async () => {
    const roots = await cliRoot();
    const malformed = path.join(roots.root, "malformed.json");
    await writeFile(malformed, "{");
    const malformedResult = await spawnCli([
      "--request",
      malformed,
      "--input-root",
      roots.input,
      "--output-root",
      roots.output,
    ]);
    expect(malformedResult.code).toBe(1);
    expect(expectSingleEnvelope(malformedResult)).toMatchObject({
      ok: false,
      error: { code: "MALFORMED_REQUEST" },
    });

    const invalid = path.join(roots.root, "invalid.json");
    await writeFile(
      invalid,
      JSON.stringify({ protocolVersion: "tidy.worker/v2" }),
    );
    const invalidResult = await spawnCli([
      "--request",
      invalid,
      "--input-root",
      roots.input,
      "--output-root",
      roots.output,
    ]);
    expect(invalidResult.code).toBe(1);
    expect(expectSingleEnvelope(invalidResult)).toMatchObject({
      ok: false,
      error: { code: "INVALID_REQUEST" },
    });
  });

  it("executes a full fixture twice through the built CLI in relocated roots", async () => {
    const run = await runFixtureTwice("simple-crosstab");
    expect(run.files.has("execution.json")).toBe(true);
    expect(run.files.has("tables/population_counts.csv")).toBe(true);
  });
});
