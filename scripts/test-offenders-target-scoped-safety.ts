import { mkdir, readFile, symlink, writeFile } from "node:fs/promises";
import { existsSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import {
  assertSafeAncestors,
  beginTargetTransaction,
  readRegularFile,
  sha256,
  stable,
} from "./offenders-target-scoped-safety.js";

const root = ".product-prototype/offenders-remaining-phase1/target-scoped-c2";
async function snapshot(path: string) {
  try {
    return sha256(await readFile(`${path}/prior.txt`));
  } catch {
    return "missing";
  }
}
for (const mode of ["before-swap", "after-swap"]) {
  const path = `${root}/run-transaction-${mode}`;
  rmSync(path, { recursive: true, force: true });
  await mkdir(path, { recursive: true });
  await writeFile(`${path}/prior.txt`, "prior\n");
  const before = await snapshot(path);
  const tx = await beginTargetTransaction(path, mode);
  await mkdir(tx.temporaryPath, { recursive: true });
  await writeFile(`${tx.temporaryPath}/new.txt`, "new\n");
  let failed = false;
  try {
    await tx.commit();
  } catch (error) {
    failed = String(error).includes(`INJECTED_FAILURE:${mode}`);
  }
  if (
    !failed ||
    (await snapshot(path)) !== before ||
    existsSync(tx.temporaryPath) ||
    existsSync(tx.backupPath)
  )
    throw Error(`ROLLBACK_FAILED:${mode}`);
  rmSync(path, { recursive: true, force: true });
}
const scratch =
  ".product-prototype/offenders-remaining-phase1/c2-safety-script-test";
rmSync(scratch, { recursive: true, force: true });
await mkdir(`${scratch}/real`, { recursive: true });
await writeFile(`${scratch}/real/input.json`, "{}\n");
await symlink("real", `${scratch}/linked`);
let ancestorRejected = false;
try {
  assertSafeAncestors(`${scratch}/linked/input.json`, ".", "ancestor-test");
} catch {
  ancestorRejected = true;
}
await symlink("real/input.json", `${scratch}/input-link.json`);
let inputLinkRejected = false;
try {
  await readRegularFile(`${scratch}/input-link.json`);
} catch {
  inputLinkRejected = true;
}
execFileSync("mkfifo", [`${scratch}/input-fifo`]);
let specialRejected = false;
try {
  await readRegularFile(`${scratch}/input-fifo`);
} catch {
  specialRejected = true;
}
rmSync(scratch, { recursive: true, force: true });
if (!ancestorRejected || !inputLinkRejected || !specialRejected)
  throw Error("FILESYSTEM_ADVERSARIAL_FAILURE");
let unsafe = false;
try {
  await beginTargetTransaction(`${root}/../escape`);
} catch {
  unsafe = true;
}
if (!unsafe) throw Error("UNSAFE_ROOT_ACCEPTED");
console.log(
  stable({
    rollback: ["before-swap", "after-swap"],
    noResidue: true,
    unsafeRootRejected: true,
    ancestorRejected,
    inputLinkRejected,
    specialRejected,
  }),
);
