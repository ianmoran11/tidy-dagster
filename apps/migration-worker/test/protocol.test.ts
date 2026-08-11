import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { afterEach, describe, expect, it } from "vitest";
import { tidycellDigestRecord } from "../../domain-worker/src/migration/historicalDigestRecord.js";
import {
  normalizeMigrationWorkerResult,
  runMigrationWorker,
  serializeMigrationWorkerResult,
} from "../src/protocol.js";

const roots: string[] = [];
afterEach(async () =>
  Promise.all(
    roots.splice(0).map((root) => rm(root, { recursive: true, force: true })),
  ),
);

const digest = (bytes: Uint8Array) =>
  `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
const fixedDigest = (character: string) => `sha256:${character.repeat(64)}`;
const recipe = {
  version: "0.1",
  sheet: "Data",
  tables: [
    {
      name: "counts",
      values: { name: "value", cells: ["R2C2"] },
      headers: [{ name: "category", direction: "W", cells: ["R2C1"] }],
    },
  ],
};

function baseRequest(operation: string) {
  return {
    protocolVersion: "tidy.migration-worker/v1",
    requestId: "migration-test",
    operation,
    inputs: [] as Array<{
      name: string;
      relativePath: string;
      contentDigest: string;
      byteLength: number;
    }>,
    parameters: {} as {
      source?: {
        sourceSnapshotDigest: string;
        sourceItemDigest: string;
        importRecordId: string;
        relativePath: string;
      };
      declaredRecipeDigest?: string;
    },
    limits: {
      maxInputBytes: 1_000_000,
      maxOutputBytes: 1_000_000,
      maxJsonDepth: 64,
      maxJsonNodes: 100_000,
      maxRecords: 10_000,
    },
  };
}

function source(relativePath = "recipes/example.json") {
  return {
    sourceSnapshotDigest: fixedDigest("a"),
    sourceItemDigest: fixedDigest("b"),
    importRecordId: fixedDigest("c"),
    relativePath,
  };
}

async function fixtureRoots() {
  const root = await mkdtemp(path.join(tmpdir(), "tidy-migration-worker-"));
  roots.push(root);
  const input = path.join(root, "input");
  const output = path.join(root, "output");
  await mkdir(input);
  await mkdir(output);
  return { root, input, output };
}

async function writeInput(
  root: string,
  relativePath: string,
  value: unknown,
  name: string,
) {
  const bytes = Buffer.from(JSON.stringify(value), "utf8");
  const target = path.join(root, relativePath);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, bytes);
  return {
    name,
    relativePath,
    contentDigest: digest(bytes),
    byteLength: bytes.byteLength,
  };
}

async function readOutput(root: string, relativePath: string) {
  return JSON.parse(
    await readFile(path.join(root, relativePath), "utf8"),
  ) as Record<string, unknown>;
}

async function expectCode(raw: unknown, code: string) {
  const root = await fixtureRoots();
  const result = await runMigrationWorker(raw, root.input, root.output);
  expect(result).toMatchObject({ ok: false, error: { code } });
}

describe("migration-only worker protocol", () => {
  it("reports bounded provider-free capabilities", async () => {
    const root = await fixtureRoots();
    const request = baseRequest("capabilities");
    const result = await runMigrationWorker(request, root.input, root.output);
    expect(result).toMatchObject({
      ok: true,
      outputs: [{ name: "capabilities" }],
    });
    const capabilities = await readOutput(root.output, "capabilities.json");
    expect(capabilities).toMatchObject({
      protocolVersion: "tidy.migration-worker/v1",
      networkRequired: false,
      modelExecutionSupported: false,
    });
  });

  it("normalizes one RecipeV01 document and remains inactive", async () => {
    const root = await fixtureRoots();
    const inputRecipe = { ...recipe, ".diagnostic": { ignored: true } };
    const input = await writeInput(
      root.input,
      "source.json",
      inputRecipe,
      "recipe",
    );
    const request = baseRequest("parse-recipe-v01");
    request.inputs = [input];
    request.parameters = {
      source: source(),
      declaredRecipeDigest: tidycellDigestRecord(recipe),
    };

    const result = await runMigrationWorker(request, root.input, root.output);
    expect(result).toMatchObject({
      ok: true,
      outputs: [{ name: "recipe-revision" }],
    });
    const revision = await readOutput(root.output, "recipe-revision.json");
    expect(revision).toMatchObject({
      schemaVersion: "tidy.migration-recipe-revision/v1",
      historicalRecipeDigest: tidycellDigestRecord(recipe),
      digestMatches: true,
      lifecycleState: "schema_valid",
      active: false,
      trainingEligible: false,
      normalizedRecipe: recipe,
    });
    expect(revision.normalizedRecipe).not.toHaveProperty(".diagnostic");
    expect(revision.source).toEqual({
      ...source(),
      sourceContentDigest: input.contentDigest,
      byteLength: input.byteLength,
    });
  });

  it("reports a declared recipe digest mismatch without granting authority", async () => {
    const root = await fixtureRoots();
    const input = await writeInput(root.input, "recipe.json", recipe, "recipe");
    const request = baseRequest("parse-recipe-v01");
    request.inputs = [input];
    request.parameters = {
      source: source(),
      declaredRecipeDigest: fixedDigest("d"),
    };
    const result = await runMigrationWorker(request, root.input, root.output);
    expect(result.ok).toBe(true);
    const revision = await readOutput(root.output, "recipe-revision.json");
    expect(revision).toMatchObject({
      declaredRecipeDigest: fixedDigest("d"),
      digestMatches: false,
      active: false,
      trainingEligible: false,
    });
  });

  it("emits exact historical approval row digests", async () => {
    const root = await fixtureRoots();
    const rows = [
      { assetId: "asset-one", sheetName: "Table 1", approvedAt: "" },
      {
        assetId: "asset-two",
        sheetName: "Table 2",
        approvedBy: "unverified label",
        futureEvidence: { preserved: true },
      },
    ];
    const input = await writeInput(
      root.input,
      "approvals.json",
      { version: 1, approvals: rows },
      "registry",
    );
    const request = baseRequest("digest-legacy-approval-registry-v1");
    request.inputs = [input];
    request.parameters = { source: source("approvals.json") };

    const result = await runMigrationWorker(request, root.input, root.output);
    expect(result.ok).toBe(true);
    const output = await readOutput(root.output, "approval-row-digests.json");
    expect(output).toMatchObject({
      schemaVersion: "tidy.migration-approval-row-digests/v1",
      recordCount: 2,
      records: [
        {
          index: 0,
          sourceRecordDigest:
            "sha256:d4745ceb965818e2dd15c924193b7592199a75a0b781d4427aabe3e72537c6dd",
        },
        { index: 1, sourceRecordDigest: tidycellDigestRecord(rows[1]) },
      ],
    });
  });

  it("rejects malformed recipes, registries, operation fields, and limits", async () => {
    const root = await fixtureRoots();
    const badRecipe = await writeInput(
      root.input,
      "bad-recipe.json",
      { ...recipe, surprise: true },
      "recipe",
    );
    const recipeRequest = baseRequest("parse-recipe-v01");
    recipeRequest.inputs = [badRecipe];
    recipeRequest.parameters = { source: source() };
    const recipeResult = await runMigrationWorker(
      recipeRequest,
      root.input,
      root.output,
    );
    expect(recipeResult).toMatchObject({
      ok: false,
      error: { code: "INVALID_RECIPE", stage: "recipe" },
    });

    await expectCode(
      { ...baseRequest("parse-recipe-v01"), unexpected: true },
      "INVALID_REQUEST",
    );
    await expectCode(
      { ...baseRequest("unknown-operation"), operation: "unknown-operation" },
      "INVALID_REQUEST",
    );

    const registryRoot = await fixtureRoots();
    const registry = await writeInput(
      registryRoot.input,
      "registry.json",
      {
        version: 1,
        approvals: [{ assetId: "asset", sheetName: "Sheet" }],
      },
      "registry",
    );
    const registryRequest = baseRequest("digest-legacy-approval-registry-v1");
    registryRequest.inputs = [registry];
    registryRequest.parameters = { source: source("approvals.json") };
    registryRequest.limits.maxRecords = 1;
    registryRequest.inputs[0] = { ...registry, name: "recipe" };
    const wrongName = await runMigrationWorker(
      registryRequest,
      registryRoot.input,
      registryRoot.output,
    );
    expect(wrongName).toMatchObject({
      ok: false,
      error: { code: "INVALID_OPERATION_INPUTS" },
    });

    const arrayRoot = await fixtureRoots();
    const arrayInput = await writeInput(
      arrayRoot.input,
      "registry.json",
      [{ assetId: "asset", sheetName: "Sheet" }],
      "registry",
    );
    const arrayRequest = baseRequest("digest-legacy-approval-registry-v1");
    arrayRequest.inputs = [arrayInput];
    arrayRequest.parameters = { source: source("approvals.json") };
    expect(
      await runMigrationWorker(arrayRequest, arrayRoot.input, arrayRoot.output),
    ).toMatchObject({
      ok: false,
      error: { code: "INVALID_APPROVAL_REGISTRY" },
    });
  });

  it("enforces byte, digest, JSON depth, record, root, and symlink bounds", async () => {
    const digestRoot = await fixtureRoots();
    const input = await writeInput(
      digestRoot.input,
      "recipe.json",
      recipe,
      "recipe",
    );
    const request = baseRequest("parse-recipe-v01");
    request.inputs = [{ ...input, contentDigest: fixedDigest("f") }];
    request.parameters = { source: source() };
    expect(
      await runMigrationWorker(request, digestRoot.input, digestRoot.output),
    ).toMatchObject({ ok: false, error: { code: "DIGEST_MISMATCH" } });

    const depthRoot = await fixtureRoots();
    const depthInput = await writeInput(
      depthRoot.input,
      "deep.json",
      { a: { b: { c: 1 } } },
      "recipe",
    );
    const depthRequest = baseRequest("parse-recipe-v01");
    depthRequest.inputs = [depthInput];
    depthRequest.parameters = { source: source() };
    depthRequest.limits.maxJsonDepth = 2;
    expect(
      await runMigrationWorker(depthRequest, depthRoot.input, depthRoot.output),
    ).toMatchObject({
      ok: false,
      error: { code: "JSON_DEPTH_LIMIT_EXCEEDED" },
    });

    const recordRoot = await fixtureRoots();
    const recordInput = await writeInput(
      recordRoot.input,
      "registry.json",
      {
        version: 1,
        approvals: [
          { assetId: "one", sheetName: "S" },
          { assetId: "two", sheetName: "S" },
        ],
      },
      "registry",
    );
    const recordRequest = baseRequest("digest-legacy-approval-registry-v1");
    recordRequest.inputs = [recordInput];
    recordRequest.parameters = { source: source("approvals.json") };
    recordRequest.limits.maxRecords = 1;
    expect(
      await runMigrationWorker(
        recordRequest,
        recordRoot.input,
        recordRoot.output,
      ),
    ).toMatchObject({ ok: false, error: { code: "RECORD_LIMIT_EXCEEDED" } });

    const symlinkRoot = await fixtureRoots();
    const outside = path.join(symlinkRoot.root, "outside.json");
    await writeFile(outside, JSON.stringify(recipe));
    await symlink(outside, path.join(symlinkRoot.input, "recipe.json"));
    const outsideBytes = await readFile(outside);
    const symlinkRequest = baseRequest("parse-recipe-v01");
    symlinkRequest.inputs = [
      {
        name: "recipe",
        relativePath: "recipe.json",
        contentDigest: digest(outsideBytes),
        byteLength: outsideBytes.byteLength,
      },
    ];
    symlinkRequest.parameters = { source: source() };
    expect(
      await runMigrationWorker(
        symlinkRequest,
        symlinkRoot.input,
        symlinkRoot.output,
      ),
    ).toMatchObject({ ok: false, error: { code: "SYMLINK_PATH" } });

    const overlap = await fixtureRoots();
    const health = baseRequest("health");
    expect(
      await runMigrationWorker(health, overlap.input, overlap.input),
    ).toMatchObject({ ok: false, error: { code: "OVERLAPPING_ROOTS" } });
  });

  it("normalizes result envelopes and runs through the actual executable", async () => {
    expect(
      normalizeMigrationWorkerResult({
        protocolVersion: "tidy.migration-worker/v1",
        requestId: "bad",
        ok: true,
        outputs: [],
        warnings: [],
        extra: true,
      }),
    ).toMatchObject({ ok: false, error: { code: "INVALID_WORKER_RESULT" } });
    expect(
      JSON.parse(
        serializeMigrationWorkerResult({
          protocolVersion: "tidy.migration-worker/v1",
          requestId: "ok",
          ok: true,
          outputs: [],
          warnings: [],
        }),
      ),
    ).toMatchObject({ ok: true, requestId: "ok" });

    const root = await fixtureRoots();
    const input = await writeInput(root.input, "recipe.json", recipe, "recipe");
    const request = baseRequest("parse-recipe-v01");
    request.inputs = [input];
    request.parameters = { source: source() };
    const requestPath = path.join(root.root, "request.json");
    await writeFile(requestPath, JSON.stringify(request));
    const executable = path.resolve("dist/tidy-migration-worker.cjs");
    const result = spawnSync(
      process.execPath,
      [
        executable,
        "--request",
        requestPath,
        "--input-root",
        root.input,
        "--output-root",
        root.output,
      ],
      { encoding: "utf8", env: { PATH: process.env.PATH ?? "" } },
    );
    expect(result.status, result.stderr).toBe(0);
    expect(JSON.parse(result.stdout)).toMatchObject({
      protocolVersion: "tidy.migration-worker/v1",
      requestId: "migration-test",
      ok: true,
    });
    expect(await readOutput(root.output, "recipe-revision.json")).toMatchObject(
      { historicalRecipeDigest: tidycellDigestRecord(recipe) },
    );
  });
});
