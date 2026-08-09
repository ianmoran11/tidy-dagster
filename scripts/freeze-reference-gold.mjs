import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cp,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";

const exec = promisify(execFile);
const commit = "1be6c995fa931e9860468e40490433161b0121cb";
const repository = "https://github.com/ianmoran11/tidycell.git";
const expectedNode = "24.7.0";
const expectedNpm = "11.5.1";
const sourceIndex = process.argv.indexOf("--source-repo");
const sourceRepository =
  sourceIndex >= 0 ? process.argv[sourceIndex + 1] : undefined;
if (!sourceRepository)
  throw new Error("A read-only Git mirror is required: --source-repo PATH");
const fixtures = ["simple-crosstab", "sparse-headers", "multi-table"];
const freeze = process.argv.includes("--confirm-reference-only");
const root = await mkdtemp(path.join(tmpdir(), "tidy-reference-freeze-"));
const checkout = path.join(root, "tidycell-reference");
const evidence = path.join(root, "evidence");

try {
  const actualNode = process.version.slice(1);
  const actualNpm = (await run("npm", ["--version"])).trim();
  if (actualNode !== expectedNode || actualNpm !== expectedNpm)
    throw new Error(
      `Reference freeze requires Node ${expectedNode} and npm ${expectedNpm}; got Node ${actualNode} and npm ${actualNpm}.`,
    );
  await run("git", ["clone", "--no-checkout", sourceRepository, checkout]);
  await run("git", ["-C", checkout, "sparse-checkout", "init", "--no-cone"]);
  await writeFile(
    path.join(checkout, ".git/info/sparse-checkout"),
    "/src/\n/fixtures/\n/package.json\n/package-lock.json\ntsconfig.json\n",
  );
  await run("git", ["-C", checkout, "checkout", "--detach", commit]);
  const resolved = (
    await run("git", ["-C", checkout, "rev-parse", "HEAD"])
  ).trim();
  if (resolved !== commit)
    throw new Error(`Reference checkout resolved to ${resolved}.`);
  await cp(
    "tools/reference/runner.ts",
    path.join(checkout, "reference-runner.ts"),
  );
  await run("npm", ["ci", "--ignore-scripts"], checkout);
  for (const fixture of fixtures) {
    await run(
      process.execPath,
      [
        "node_modules/tsx/dist/cli.mjs",
        "reference-runner.ts",
        fixture,
        path.join(evidence, fixture),
      ],
      checkout,
    );
  }

  const fixtureRecords = [];
  for (const fixture of fixtures) {
    const outputs = [];
    for (const relativePath of (await walk(path.join(evidence, fixture))).sort(
      outputOrder,
    )) {
      const bytes = await readFile(path.join(evidence, fixture, relativePath));
      outputs.push({
        name: relativePath,
        relativePath,
        contentDigest: sha256(bytes),
        byteLength: bytes.byteLength,
      });
    }
    fixtureRecords.push({ name: fixture, outputs });
  }
  const runnerBytes = await readFile("tools/reference/runner.ts");
  const lockBytes = await readFile(path.join(checkout, "package-lock.json"));
  const dependencyTree = JSON.parse(
    await run(
      "npm",
      ["ls", "--json", "--depth=0", "exceljs", "zod", "tsx", "typescript"],
      checkout,
    ),
  );
  const direct = Object.fromEntries(
    Object.entries(dependencyTree.dependencies).map(([name, value]) => [
      name,
      value.version,
    ]),
  );
  const manifest = {
    schemaVersion: "tidy.reference-gold/v1",
    classification: "independent-pinned-reference-bytes",
    scope: "M0–M2-scoped deterministic compatibility slice",
    sourceAuthoredExpectedScope:
      "fixtures/expected/*.json remains an additional rows/non-table-cell oracle",
    reference: {
      repository,
      sourceRemote: (
        await run("git", [
          "-C",
          sourceRepository,
          "remote",
          "get-url",
          "origin",
        ]).catch(() => "unconfigured")
      ).trim(),
      commit,
      tree: (
        await run("git", ["-C", checkout, "rev-parse", "HEAD^{tree}"])
      ).trim(),
      packageLockDigest: sha256(lockBytes),
      license: "MIT",
    },
    runner: {
      path: "tools/reference/runner.ts",
      contentDigest: sha256(runnerBytes),
      addsOnly:
        "evidence serialization (five JSON layers, geometry projection from reference relationship APIs, and reference rowsToCsv output); all transformation modules import from the clean pinned checkout",
    },
    toolchain: {
      node: expectedNode,
      npm: expectedNpm,
      dependencies: direct,
    },
    procedure: {
      command:
        "npm run gold:freeze:reference -- --source-repo PATH --confirm-reference-only",
      acquisition:
        "required read-only local Git mirror; resolved commit/tree verified before execution; no runtime dependency",
      checkout:
        "git clone --no-checkout from the required mirror, then sparse checkout and detached checkout of the pinned commit",
      install: "npm ci --ignore-scripts inside the clean sparse checkout",
      execution:
        "the pinned checkout's local tsx executes the digested reference serializer; candidate modules are never imported",
    },
    serialization:
      "JSON.stringify(value, null, 2) plus LF; TidyCell reference rowsToCsv with recipe valueColumn",
    summarySupported: false,
    fixtures: fixtureRecords,
  };

  if (freeze) {
    const destination = path.resolve("fixtures/gold");
    const publishRoot = await mkdtemp(
      path.join(path.dirname(destination), ".reference-gold-publish-"),
    );
    const staged = path.join(publishRoot, "replacement");
    const backup = path.join(publishRoot, "previous");
    await cp(evidence, staged, { recursive: true });
    await writeFile(
      path.join(staged, "manifest.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
    );
    let movedPrevious = false;
    try {
      await rename(destination, backup);
      movedPrevious = true;
      await rename(staged, destination);
      movedPrevious = false;
      await rm(backup, { recursive: true, force: true });
    } catch (error) {
      if (movedPrevious)
        await rename(backup, destination).catch(() => undefined);
      throw error;
    } finally {
      await rm(publishRoot, { recursive: true, force: true });
    }
    console.log(
      `reference-gold: froze ${fixtures.length} fixtures from ${commit}`,
    );
  } else {
    await verifyAgainstGold(evidence, fixtureRecords);
    console.log(
      `reference-gold: verified ${fixtures.length} fixtures from clean pinned checkout ${commit}`,
    );
  }
} finally {
  await rm(root, { recursive: true, force: true });
}

async function verifyAgainstGold(evidenceRoot, fixtureRecords) {
  const manifest = JSON.parse(
    await readFile("fixtures/gold/manifest.json", "utf8"),
  );
  for (const fixture of fixtureRecords) {
    const declared = manifest.fixtures.find(
      (entry) => entry.name === fixture.name,
    );
    if (JSON.stringify(declared?.outputs) !== JSON.stringify(fixture.outputs))
      throw new Error(`${fixture.name}: reference descriptor mismatch.`);
    for (const output of fixture.outputs) {
      const expected = await readFile(
        path.join("fixtures/gold", fixture.name, output.relativePath),
      );
      const actual = await readFile(
        path.join(evidenceRoot, fixture.name, output.relativePath),
      );
      if (!expected.equals(actual))
        throw new Error(`${fixture.name}: ${output.relativePath} mismatch.`);
    }
  }
}

async function run(command, args, cwd = process.cwd()) {
  const { stdout, stderr } = await exec(command, args, {
    cwd,
    maxBuffer: 20_000_000,
  });
  if (stderr && process.env.REFERENCE_VERBOSE === "1")
    process.stderr.write(stderr);
  return stdout;
}

async function walk(root, prefix = "") {
  const files = [];
  for (const entry of await readdir(path.join(root, prefix), {
    withFileTypes: true,
  })) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) files.push(...(await walk(root, relative)));
    else if (entry.isFile()) files.push(relative);
  }
  return files.sort();
}

function outputOrder(left, right) {
  const layers = [
    "parsed-workbook.json",
    "normalized-recipe.json",
    "selectors.json",
    "geometry.json",
    "execution.json",
  ];
  const leftIndex = layers.indexOf(left);
  const rightIndex = layers.indexOf(right);
  if (leftIndex >= 0 || rightIndex >= 0)
    return (
      (leftIndex < 0 ? layers.length : leftIndex) -
      (rightIndex < 0 ? layers.length : rightIndex)
    );
  return left.localeCompare(right);
}

function sha256(bytes) {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
