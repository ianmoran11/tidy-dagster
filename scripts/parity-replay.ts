import { readFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import {
  fixtureNames,
  runFixtureTwice,
  type FixtureName,
  type FixtureRun,
} from "./parity-harness.js";

type GoldFixture = {
  name: string;
  outputs: Array<{
    name: string;
    relativePath: string;
    contentDigest: string;
    byteLength: number;
  }>;
};
type GoldManifest = { fixtures: GoldFixture[] };
const gold = JSON.parse(
  await readFile("fixtures/gold/manifest.json", "utf8"),
) as GoldManifest;
let wrongOutputRejected = false;
for (const name of fixtureNames) {
  const declared = gold.fixtures.find((fixture) => fixture.name === name);
  if (!declared) throw new Error(`${name}: missing reference declaration`);
  const run = await runFixtureTwice(name);
  if (!wrongOutputRejected) {
    const wrong: FixtureRun = { ...run, files: new Map(run.files) };
    const firstPath = declared.outputs[0].relativePath;
    wrong.files.set(
      firstPath,
      Buffer.from("deliberately-wrong-candidate-output\n"),
    );
    try {
      await assertReferenceParity(name, wrong, declared);
    } catch {
      wrongOutputRejected = true;
    }
  }
  await assertReferenceParity(name, run, declared);
  console.log(
    `${name}: ${declared.outputs.map((output) => `${output.relativePath}=${output.contentDigest}`).join(" ")}`,
  );
}
if (!wrongOutputRejected)
  throw new Error(
    "Parity negative control failed to reject wrong candidate output.",
  );
console.log(
  "parity-replay: three relocated CLI fixture runs match independent pinned reference bytes; wrong-output negative rejected",
);

async function assertReferenceParity(
  name: FixtureName,
  run: FixtureRun,
  declared: GoldFixture,
): Promise<void> {
  if (!isDeepStrictEqual(run.result.outputs, declared.outputs))
    throw new Error(
      `${name}: output manifest differs from independent reference gold`,
    );
  for (const output of declared.outputs) {
    const expected = await readFile(
      `fixtures/gold/${name}/${output.relativePath}`,
    );
    const actual = run.files.get(output.relativePath);
    if (!actual?.equals(expected))
      throw new Error(
        `${name}: bytes differ from independent reference gold for ${output.relativePath}`,
      );
  }
}
