import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, rmSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import {
  assertContained,
  assertDistinctPaths,
  beginDirectoryTransaction,
  readBoundedJson,
  sha256,
} from "./offenders-phased-safety.js";

const ROOT = ".product-prototype/offenders-remaining-phase1/multi-panel-b2a";
const AUTH =
  "fixtures/product-prototype/offenders-remaining-semantic-generation-authorization-v1.json";
const CAP =
  "fixtures/product-prototype/offenders-remaining-capability-routing-pin-v1.json";
const AUTH_DIGEST =
  "sha256:13624947ec0620b0b48b64ef1cd9126a62fada7adad458f64be2598b8d7f4d6a";
const CAP_DIGEST =
  "sha256:62fb94b842714e7d8243950b9d92e6ed880e0228f6548d8955e4f18a5da939a4";
const ROUTING_DIGEST =
  "sha256:c4945bb612f323d4b13ba784d863649e01fa7cd89cb0c2fe44bf0460e33dd243";
const ROUTING = `${ROOT}/run-e-phased/routing-manifest.json`;
const MAPS = `${ROOT}/run-e-phased/maps`;
const MEMBERS = `${ROOT}/run-e-phased/members`;

function expectThrow(fn: () => unknown, pattern: RegExp): void {
  assert.throws(fn, pattern);
}
function run(args: string[]): { status: number | null; output: string } {
  const result = spawnSync("npx", ["tsx", ...args], {
    cwd: process.cwd(),
    encoding: "utf8",
    env: { ...process.env, npm_config_loglevel: "silent" },
    timeout: 600_000,
  });
  return { status: result.status, output: `${result.stdout}${result.stderr}` };
}
function compilerArgs(options: {
  routing?: string;
  routingDigest?: string;
  capability?: string;
  capabilityDigest?: string;
  out: string;
  inject?: string;
}): string[] {
  const args = [
    "scripts/compile-offenders-remaining.ts",
    "--routing-manifest",
    options.routing ?? ROUTING,
    "--routing-digest",
    options.routingDigest ?? ROUTING_DIGEST,
    "--capability-pin",
    options.capability ?? CAP,
    "--capability-pin-digest",
    options.capabilityDigest ?? CAP_DIGEST,
    "--authorization",
    AUTH,
    "--authorization-digest",
    AUTH_DIGEST,
    "--maps-root",
    MAPS,
    "--members-root",
    MEMBERS,
    "--out",
    options.out,
  ];
  if (options.inject) args.push("--inject-failure", options.inject);
  return args;
}

expectThrow(() => assertContained(ROOT, ROOT, "root"), /UNSAFE_PATH/);
expectThrow(() => assertContained("/tmp/out", ROOT, "outside"), /UNSAFE_PATH/);
expectThrow(
  () =>
    assertDistinctPaths([
      ["a", `${ROOT}/run-a`],
      ["b", `${ROOT}/run-a/maps`],
    ]),
  /OVERLAPPING_PATHS/,
);

const scratch = `${ROOT}/safety-adversarial`;
const fixtureScratch =
  "fixtures/product-prototype/offenders-phased-safety-adversarial";
rmSync(scratch, { recursive: true, force: true });
rmSync(fixtureScratch, { recursive: true, force: true });
await mkdir(scratch, { recursive: true });
await mkdir(fixtureScratch, { recursive: true });
const jsonPath = `${scratch}/bounded.json`;
await writeFile(jsonPath, '{"a":[1,2]}\n');
const data = await readFile(jsonPath);
await readBoundedJson(jsonPath, {
  maxBytes: 100,
  maxNodes: 10,
  pin: { path: jsonPath, byteLength: data.length, sha256: sha256(data) },
});
await assert.rejects(
  readBoundedJson(jsonPath, {
    maxBytes: 100,
    maxNodes: 10,
    pin: {
      path: jsonPath,
      byteLength: data.length,
      sha256: `sha256:${"0".repeat(64)}`,
    },
  }),
  /EXTERNAL_INPUT_PIN_MISMATCH/,
);
await assert.rejects(
  readBoundedJson(jsonPath, { maxBytes: 2, maxNodes: 10 }),
  /JSON_BYTE_LIMIT/,
);
await assert.rejects(
  readBoundedJson(jsonPath, { maxBytes: 100, maxNodes: 2 }),
  /JSON_NODE_LIMIT/,
);

for (const point of ["before-swap", "after-swap"]) {
  const finalPath = `${scratch}/run-${point}`;
  await mkdir(finalPath, { recursive: true });
  await writeFile(`${finalPath}/marker`, "prior");
  const tx = await beginDirectoryTransaction(finalPath, scratch, point);
  await mkdir(tx.temporaryPath, { recursive: true });
  await writeFile(`${tx.temporaryPath}/marker`, "new");
  await assert.rejects(tx.commit(), new RegExp(`INJECTED_FAILURE:${point}`));
  assert.equal(await readFile(`${finalPath}/marker`, "utf8"), "prior");
  rmSync(tx.temporaryPath, { recursive: true, force: true });
}

const wrongBuilder = run([
  "scripts/build-offenders-remaining-multi-panel.ts",
  "--out",
  `${ROOT}/run-safety-wrong-pin`,
  "--authorization-digest",
  `sha256:${"0".repeat(64)}`,
  "--capability-pin-digest",
  CAP_DIGEST,
]);
assert.notEqual(wrongBuilder.status, 0);
assert.match(wrongBuilder.output, /CAMPAIGN_EXTERNAL_PIN_MISMATCH/);
assert.equal(existsSync(`${ROOT}/run-safety-wrong-pin`), false);

const wrongCompiler = run(
  compilerArgs({
    routingDigest: `sha256:${"1".repeat(64)}`,
    out: `${ROOT}/routed-safety-wrong-pin`,
  }),
);
assert.notEqual(wrongCompiler.status, 0);
assert.match(wrongCompiler.output, /EXTERNAL_ROUTING_PIN_MISMATCH/);
assert.equal(existsSync(`${ROOT}/routed-safety-wrong-pin`), false);

const outside = run(compilerArgs({ out: "/tmp/offenders-unsafe-output" }));
assert.notEqual(outside.status, 0);
assert.match(outside.output, /UNSAFE_PATH/);

async function scenario(
  name: string,
  mutate: (routing: any, capability: any) => void,
  expected: RegExp,
): Promise<void> {
  const routing = JSON.parse(await readFile(ROUTING, "utf8"));
  const capability = JSON.parse(await readFile(CAP, "utf8"));
  mutate(routing, capability);
  const routePath = `${scratch}/routing-${name}.json`;
  const routeBytes = Buffer.from(`${JSON.stringify(routing, null, 2)}\n`);
  await writeFile(routePath, routeBytes);
  capability.routingManifest = {
    byteLength: routeBytes.length,
    sha256: sha256(routeBytes),
  };
  const capPath = `${fixtureScratch}/capability-${name}.json`;
  const capBytes = Buffer.from(`${JSON.stringify(capability, null, 2)}\n`);
  await writeFile(capPath, capBytes);
  const out = `${ROOT}/routed-safety-${name}`;
  const result = run(
    compilerArgs({
      routing: routePath,
      routingDigest: sha256(routeBytes),
      capability: capPath,
      capabilityDigest: sha256(capBytes),
      out,
    }),
  );
  assert.notEqual(result.status, 0, `${name} unexpectedly passed`);
  assert.match(result.output, expected, `${name}: ${result.output}`);
  assert.equal(existsSync(out), false);
}

await scenario(
  "duplicate-route",
  (routing) => {
    routing.members[routing.members.length - 1] = structuredClone(
      routing.members[0],
    );
  },
  /DUPLICATE_ROUTING_IDENTITY/,
);
await scenario(
  "unknown-route",
  (routing, capability) => {
    routing.members[0].status = "unknown-route";
    capability.members.find(
      (x: any) =>
        x.familyId === routing.members[0].familyId &&
        x.year === routing.members[0].year,
    ).status = "unknown-route";
  },
  /UNKNOWN_ROUTE/,
);
await scenario(
  "split-drift",
  (routing, capability) => {
    const route = routing.members.find(
      (x: any) => x.status === "multi-table-v1-capable",
    );
    const expected = capability.members.find(
      (x: any) => x.familyId === route.familyId && x.year === route.year,
    );
    route.status = expected.status = "target-scoped-required";
    route.failure = expected.failure = structuredClone(
      capability.members.find((x: any) => x.status === "target-scoped-required")
        .failure,
    );
  },
  /ROUTING_SPLIT_DRIFT/,
);
await scenario(
  "failure-drift",
  (routing) => {
    const route = routing.members.find(
      (x: any) => x.status === "target-scoped-required",
    );
    route.failure.message += " drift";
  },
  /ROUTE_FAILURE_DRIFT/,
);

const coherent = await scenario(
  "coherent-rehash",
  (_routing, capability) => {
    capability.members[0].rows += 1;
  },
  /ROUTE_FIELD_DRIFT/,
);
void coherent;

for (const inject of ["v1-direction", "v1-warning"]) {
  const out = `${ROOT}/routed-safety-${inject}`;
  const result = run(compilerArgs({ out, inject }));
  assert.notEqual(result.status, 0);
  assert.match(result.output, /RECIPE_OR_WARNING_DRIFT/);
  assert.equal(existsSync(out), false);
}

const afterWrites = `${ROOT}/routed-safety-after-writes`;
rmSync(afterWrites, { recursive: true, force: true });
await mkdir(afterWrites, { recursive: true });
await writeFile(`${afterWrites}/marker`, "prior");
const injected = run(
  compilerArgs({ out: afterWrites, inject: "after-writes" }),
);
assert.notEqual(injected.status, 0);
assert.match(injected.output, /INJECTED_FAILURE:after-writes/);
assert.equal(await readFile(`${afterWrites}/marker`, "utf8"), "prior");
assert.equal(existsSync(`${afterWrites}/summary.json`), false);

rmSync(scratch, { recursive: true, force: true });
rmSync(fixtureScratch, { recursive: true, force: true });
rmSync(afterWrites, { recursive: true, force: true });
console.log(
  JSON.stringify({
    ok: true,
    pathSafety: true,
    boundedJson: true,
    rollbackPoints: ["before-swap", "after-swap", "after-writes"],
    duplicateRouteRejected: true,
    unknownRouteRejected: true,
    splitDriftRejected: true,
    failureDriftRejected: true,
    v1DirectionRejected: true,
    v1WarningRejected: true,
    externalPinMismatch: true,
    coherentRehashRejected: true,
  }),
);
