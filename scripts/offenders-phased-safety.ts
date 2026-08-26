import { createHash, randomUUID } from "node:crypto";
import { existsSync, renameSync, rmSync } from "node:fs";
import {
  lstat,
  mkdir,
  open,
  readFile,
  realpath,
  rename,
  rm,
} from "node:fs/promises";
import { basename, dirname, relative, resolve, sep } from "node:path";

export type FilePin = { path: string; byteLength: number; sha256: string };

// Exact transitive local-source closure of scripts/compile-offenders-remaining.ts.
// Keep this explicit: adding or removing a runtime import requires a reviewed pin update.
export const OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS = [
  "apps/domain-worker/src/address.ts",
  "apps/domain-worker/src/catalog/cell-role-sketch-v02.ts",
  "apps/domain-worker/src/catalog/compiler-v02.ts",
  "apps/domain-worker/src/catalog/format-aware-region-catalog-v2.ts",
  "apps/domain-worker/src/catalog/geometry-v02.ts",
  "apps/domain-worker/src/catalog/role-aware-region-catalog-v5.ts",
  "apps/domain-worker/src/catalog/semantic-gold-schema.ts",
  "apps/domain-worker/src/catalog/semantic-map-v1.ts",
  "apps/domain-worker/src/catalog/semantic-map-v2.ts",
  "apps/domain-worker/src/catalog/types.ts",
  "apps/domain-worker/src/context/compactContext.ts",
  "apps/domain-worker/src/executor/directions.ts",
  "apps/domain-worker/src/executor/executeRecipe.ts",
  "apps/domain-worker/src/executor/relationshipResolution.ts",
  "apps/domain-worker/src/executor/types.ts",
  "apps/domain-worker/src/recipe/resolveSelectors.ts",
  "apps/domain-worker/src/recipe/schema.ts",
  "apps/domain-worker/src/recipe/styleFingerprint.ts",
  "apps/domain-worker/src/recipe/types.ts",
  "apps/domain-worker/src/workbook/parseWorkbook.ts",
  "apps/domain-worker/src/workbook/types.ts",
  "scripts/compile-offenders-remaining.ts",
  "scripts/offenders-phased-safety.ts",
] as const;

export function sha256(data: Buffer | string): string {
  return `sha256:${createHash("sha256").update(data).digest("hex")}`;
}

export function countJsonNodes(value: unknown, limit: number): number {
  let count = 0;
  const stack: unknown[] = [value];
  while (stack.length) {
    const item = stack.pop();
    if (++count > limit) throw new Error(`JSON_NODE_LIMIT:${limit}`);
    if (Array.isArray(item)) stack.push(...item);
    else if (item && typeof item === "object")
      stack.push(...Object.values(item as Record<string, unknown>));
  }
  return count;
}

export async function verifyPinnedFileClosure(
  pins: readonly FilePin[],
  expectedPaths: readonly string[],
): Promise<void> {
  const expected = [...expectedPaths].sort();
  const actual = pins.map((pin) => pin.path).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw new Error("RUNTIME_SOURCE_CLOSURE_PATH_MISMATCH");
  const seen = new Set<string>();
  for (const pin of pins) {
    if (seen.has(pin.path))
      throw new Error(`DUPLICATE_RUNTIME_SOURCE_PIN:${pin.path}`);
    seen.add(pin.path);
    const bytes = await readFile(pin.path);
    if (bytes.length !== pin.byteLength || sha256(bytes) !== pin.sha256)
      throw new Error(`RUNTIME_SOURCE_PIN_DRIFT:${pin.path}`);
  }
}

export async function readBoundedJson(
  path: string,
  options: { maxBytes: number; maxNodes: number; pin?: FilePin },
): Promise<{ value: any; bytes: Buffer }> {
  const bytes = await readFile(path);
  if (bytes.length > options.maxBytes)
    throw new Error(`JSON_BYTE_LIMIT:${path}:${bytes.length}`);
  if (options.pin) {
    if (
      options.pin.path !== path ||
      options.pin.byteLength !== bytes.length ||
      options.pin.sha256 !== sha256(bytes)
    )
      throw new Error(`EXTERNAL_INPUT_PIN_MISMATCH:${path}`);
  }
  const value = JSON.parse(bytes.toString("utf8"));
  countJsonNodes(value, options.maxNodes);
  return { value, bytes };
}

export function assertAllowedKeys(
  value: unknown,
  allowed: readonly string[],
  label: string,
): void {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error(`INVALID_OBJECT:${label}`);
  const permitted = new Set(allowed);
  const unknown = Object.keys(value as Record<string, unknown>).filter(
    (key) => !permitted.has(key),
  );
  if (unknown.length)
    throw new Error(
      `UNKNOWN_FIELDS:${label}:${JSON.stringify(unknown.sort())}`,
    );
}

export function assertExactKeys(
  value: unknown,
  allowed: readonly string[],
  label: string,
): void {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error(`INVALID_OBJECT:${label}`);
  const actual = Object.keys(value as Record<string, unknown>).sort();
  const expected = [...allowed].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw new Error(
      `UNKNOWN_OR_MISSING_FIELDS:${label}:${JSON.stringify(actual)}`,
    );
}

export function assertSafeComponent(value: unknown, label: string): string {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/.test(value) ||
    value === "." ||
    value === ".."
  )
    throw new Error(`UNSAFE_PATH_COMPONENT:${label}:${String(value)}`);
  return value;
}

export function assertSafeYear(value: unknown): number {
  if (!Number.isInteger(value) || Number(value) < 2000 || Number(value) > 2100)
    throw new Error(`UNSAFE_YEAR:${String(value)}`);
  return Number(value);
}

export function assertContained(
  path: string,
  root: string,
  label: string,
): string {
  const target = resolve(path);
  const boundary = resolve(root);
  const rel = relative(boundary, target);
  if (
    rel === "" ||
    rel === ".." ||
    rel.startsWith(`..${sep}`) ||
    resolve(boundary, rel) !== target
  )
    throw new Error(`UNSAFE_PATH:${label}:${path}`);
  return target;
}

export function assertDistinctPaths(paths: Array<[string, string]>): void {
  const resolved = paths.map(
    ([label, path]) => [label, resolve(path)] as const,
  );
  for (let i = 0; i < resolved.length; i++)
    for (let j = i + 1; j < resolved.length; j++) {
      const [aLabel, a] = resolved[i];
      const [bLabel, b] = resolved[j];
      if (a === b || a.startsWith(`${b}${sep}`) || b.startsWith(`${a}${sep}`))
        throw new Error(`OVERLAPPING_PATHS:${aLabel}:${bLabel}`);
    }
}

export type DirectoryTransaction = {
  finalPath: string;
  temporaryPath: string;
  commit: () => Promise<void>;
};

async function assertNoSymlinkAncestors(
  requested: string,
  allowedRoot: string,
): Promise<void> {
  const boundary = resolve(allowedRoot);
  const finalPath = assertContained(requested, allowedRoot, "output");
  const boundaryInfo = await lstat(boundary);
  if (boundaryInfo.isSymbolicLink() || !boundaryInfo.isDirectory())
    throw new Error(`UNSAFE_OUTPUT_ANCESTOR:${boundary}`);
  if ((await realpath(boundary)) !== boundary)
    throw new Error(`OUTPUT_ANCESTOR_REALPATH_DRIFT:${boundary}`);
  const parent = dirname(finalPath);
  if (parent !== boundary) throw new Error("OUTPUT_MUST_BE_DIRECT_CHILD");
  if (existsSync(finalPath)) {
    const info = await lstat(finalPath);
    if (info.isSymbolicLink() || (await realpath(finalPath)) !== finalPath)
      throw new Error("UNSAFE_EXISTING_OUTPUT");
  }
}

export async function beginDirectoryTransaction(
  requested: string,
  allowedRoot: string,
  injectedFailure: string | undefined,
): Promise<DirectoryTransaction> {
  const finalPath = assertContained(requested, allowedRoot, "output");
  if (
    !/^run-[A-Za-z0-9._-]+$/.test(basename(finalPath)) &&
    !/^routed-[A-Za-z0-9._-]+$/.test(basename(finalPath))
  )
    throw new Error(`UNSAFE_OUTPUT_NAME:${basename(finalPath)}`);
  await assertNoSymlinkAncestors(finalPath, allowedRoot);
  const token = randomUUID();
  const leasePath = `${finalPath}.lease`;
  const lease = await open(leasePath, "wx", 0o600);
  await lease.writeFile(
    `${JSON.stringify({ token, pid: process.pid, finalPath })}\n`,
  );
  await lease.sync();
  await lease.close();
  const temporaryPath = `${finalPath}.tmp-${token}`;
  const backupPath = `${finalPath}.backup-${token}`;
  let committed = false;
  const cleanup = () => {
    if (!committed) rmSync(temporaryPath, { recursive: true, force: true });
    rmSync(leasePath, { force: true });
  };
  process.once("exit", cleanup);
  process.once("SIGINT", () => process.exit(130));
  process.once("SIGTERM", () => process.exit(143));
  return {
    finalPath,
    temporaryPath,
    commit: async () => {
      if (injectedFailure === "before-swap") {
        cleanup();
        throw new Error("INJECTED_FAILURE:before-swap");
      }
      const hadPrior = existsSync(finalPath);
      if (hadPrior) await rename(finalPath, backupPath);
      try {
        await rename(temporaryPath, finalPath);
        if (injectedFailure === "after-swap")
          throw new Error("INJECTED_FAILURE:after-swap");
        await rm(backupPath, { recursive: true, force: true });
        committed = true;
        await rm(leasePath, { force: false });
      } catch (error) {
        rmSync(finalPath, { recursive: true, force: true });
        if (hadPrior && existsSync(backupPath))
          renameSync(backupPath, finalPath);
        cleanup();
        throw error;
      }
    },
  };
}
