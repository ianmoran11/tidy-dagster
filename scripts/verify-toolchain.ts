import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";

const exec = promisify(execFile);
const expectedNode = "24.7.0";
const expectedNpm = "11.5.1";
const packageJson = JSON.parse(await readFile("package.json", "utf8")) as {
  packageManager?: string;
  engines?: { node?: string; npm?: string };
};
const nodeVersion = process.version.slice(1);
const npmVersion = (await exec("npm", ["--version"])).stdout.trim();
const nodeVersionFile = (await readFile(".node-version", "utf8")).trim();
if (
  nodeVersion !== expectedNode ||
  npmVersion !== expectedNpm ||
  nodeVersionFile !== expectedNode ||
  packageJson.engines?.node !== expectedNode ||
  packageJson.engines?.npm !== expectedNpm ||
  packageJson.packageManager !== `npm@${expectedNpm}`
)
  throw new Error(
    `Toolchain drift: node=${nodeVersion}, npm=${npmVersion}, .node-version=${nodeVersionFile}, packageManager=${packageJson.packageManager}.`,
  );
console.log(
  `toolchain-verification: Node ${expectedNode} and npm ${expectedNpm} are exactly pinned`,
);
