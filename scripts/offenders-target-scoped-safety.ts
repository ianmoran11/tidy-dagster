import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  realpathSync,
  renameSync,
  rmSync,
  rmdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { mkdir, readFile, readdir, rename, unlink } from "node:fs/promises";
import {
  basename,
  dirname,
  isAbsolute,
  normalize,
  relative,
  resolve,
  sep,
} from "node:path";

export type FilePin = { path: string; byteLength: number; sha256: string };

export const TARGET_SCOPED_RUNTIME_SOURCE_PATHS = [
  "apps/domain-worker/src/address.ts",
  "apps/domain-worker/src/catalog/cell-role-sketch-v02.ts",
  "apps/domain-worker/src/catalog/compiler-v02.ts",
  "apps/domain-worker/src/catalog/format-aware-region-catalog-v2.ts",
  "apps/domain-worker/src/catalog/geometry-v02.ts",
  "apps/domain-worker/src/catalog/role-aware-region-catalog-v5.ts",
  "apps/domain-worker/src/catalog/semantic-gold-schema.ts",
  "apps/domain-worker/src/catalog/semantic-map-v1.ts",
  "apps/domain-worker/src/catalog/semantic-map-v2.ts",
  "apps/domain-worker/src/catalog/target-scoped-recipe-v02.ts",
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
  "scripts/build-offenders-remaining-target-scoped.ts",
  "scripts/offenders-target-scoped-safety.ts",
  "scripts/verify-offenders-remaining-target-scoped.py",
] as const;

export function sha256(data: Buffer | string): string {
  return `sha256:${createHash("sha256").update(data).digest("hex")}`;
}
export function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.keys(value as Record<string, unknown>)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stable((value as any)[k])}`)
      .join(",")}}`;
  if (typeof value === "number" && Object.is(value, -0)) return '"-0"';
  return JSON.stringify(value);
}
export function jsonBytes(value: unknown): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
}
export function countJsonNodes(value: unknown, limit: number): number {
  let count = 0;
  const stack = [value];
  while (stack.length) {
    const item = stack.pop();
    if (++count > limit) throw Error(`JSON_NODE_LIMIT:${limit}`);
    if (Array.isArray(item)) stack.push(...item);
    else if (item && typeof item === "object")
      stack.push(...Object.values(item));
  }
  return count;
}
export function assertExactKeys(
  value: unknown,
  keys: readonly string[],
  label: string,
): void {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error(`INVALID_OBJECT:${label}`);
  if (stable(Object.keys(value as any).sort()) !== stable([...keys].sort()))
    throw Error(`UNKNOWN_OR_MISSING_FIELDS:${label}`);
}
export function assertSafeComponent(value: unknown, label: string): string {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/.test(value) ||
    value === "." ||
    value === ".."
  )
    throw Error(`UNSAFE_COMPONENT:${label}`);
  return value;
}
export function assertCanonicalRelativePath(
  path: string,
  label: string,
): string {
  if (
    !path ||
    isAbsolute(path) ||
    path.includes("\\") ||
    normalize(path) !== path ||
    path.split("/").some((part) => !part || part === "." || part === "..")
  )
    throw Error(`UNSAFE_CANONICAL_PATH:${label}:${path}`);
  return path;
}
export function assertContained(
  path: string,
  root: string,
  label: string,
): string {
  const target = resolve(path),
    boundary = resolve(root),
    rel = relative(boundary, target);
  if (
    rel === "" ||
    rel === ".." ||
    rel.startsWith(`..${sep}`) ||
    resolve(boundary, rel) !== target
  )
    throw Error(`UNSAFE_PATH:${label}:${path}`);
  return target;
}
function assertRealContained(path: string, root: string, label: string): void {
  const real = realpathSync(path),
    boundary = realpathSync(root),
    rel = relative(boundary, real);
  if (
    rel === ".." ||
    rel.startsWith(`..${sep}`) ||
    resolve(boundary, rel) !== real
  )
    throw Error(`REALPATH_ESCAPE:${label}:${path}`);
}
export function assertSafeAncestors(
  path: string,
  root = ".",
  label = "path",
): void {
  const target = resolve(path),
    boundary = resolve(root);
  const lexical = relative(boundary, target);
  if (lexical === ".." || lexical.startsWith(`..${sep}`))
    throw Error(`UNSAFE_PATH:${label}:${path}`);
  const chain: string[] = [];
  let current = target;
  while (current !== dirname(current)) {
    chain.push(current);
    if (current === boundary) break;
    current = dirname(current);
  }
  if (!chain.includes(boundary))
    throw Error(`UNSAFE_ANCESTOR_ROOT:${label}:${path}`);
  for (const entry of chain.reverse()) {
    if (!existsSync(entry)) continue;
    const info = lstatSync(entry);
    if (info.isSymbolicLink())
      throw Error(`SYMLINK_ANCESTOR:${label}:${entry}`);
    if (!info.isDirectory() && entry !== target)
      throw Error(`SPECIAL_ANCESTOR:${label}:${entry}`);
    assertRealContained(entry, boundary, label);
  }
}
export async function readRegularFile(
  path: string,
  root = ".",
  label = "input",
): Promise<Buffer> {
  assertCanonicalRelativePath(path, label);
  assertSafeAncestors(path, root, label);
  const info = lstatSync(path);
  if (info.isSymbolicLink()) throw Error(`SYMLINK_INPUT:${label}:${path}`);
  if (!info.isFile()) throw Error(`SPECIAL_INPUT:${label}:${path}`);
  assertRealContained(path, root, label);
  return readFile(path);
}
export async function verifyPinnedClosure(
  pins: readonly FilePin[],
  expected: readonly string[],
): Promise<void> {
  if (stable(pins.map((p) => p.path).sort()) !== stable([...expected].sort()))
    throw Error("RUNTIME_SOURCE_CLOSURE_PATH_MISMATCH");
  const seen = new Set<string>();
  for (const pin of pins) {
    assertExactKeys(pin, ["path", "byteLength", "sha256"], "runtime-pin");
    if (seen.has(pin.path)) throw Error(`DUPLICATE_PIN:${pin.path}`);
    seen.add(pin.path);
    const b = await readRegularFile(pin.path, ".", "runtime-pin");
    if (b.length !== pin.byteLength || sha256(b) !== pin.sha256)
      throw Error(`PIN_DRIFT:${pin.path}`);
  }
}
export async function readPinnedJson(
  path: string,
  pin: FilePin,
  maxBytes = 256_000_000,
  maxNodes = 15_000_000,
): Promise<any> {
  if (pin.path !== path) throw Error(`INPUT_PIN_PATH_MISMATCH:${path}`);
  const b = await readRegularFile(path, ".", "pinned-json");
  if (b.length !== pin.byteLength || sha256(b) !== pin.sha256)
    throw Error(`INPUT_PIN_MISMATCH:${path}`);
  if (b.length > maxBytes) throw Error(`INPUT_BYTE_LIMIT:${path}`);
  const v = JSON.parse(b.toString("utf8"));
  countJsonNodes(v, maxNodes);
  return v;
}
export async function listRegularFiles(root: string): Promise<string[]> {
  assertSafeAncestors(root, ".", "output-root");
  const info = lstatSync(root);
  if (!info.isDirectory() || info.isSymbolicLink())
    throw Error(`UNSAFE_OUTPUT_ROOT:${root}`);
  const out: string[] = [];
  async function walk(dir: string) {
    for (const e of await readdir(dir, { withFileTypes: true })) {
      const p = `${dir}/${e.name}`;
      const info = lstatSync(p);
      if (e.isSymbolicLink() || info.isSymbolicLink())
        throw Error(`SYMLINK_OUTPUT:${p}`);
      if (e.isDirectory() && info.isDirectory()) await walk(p);
      else if (e.isFile() && info.isFile()) {
        const rel = relative(root, p).split(sep).join("/");
        if (rel !== ".c2-transaction-owner.json") out.push(rel);
      } else throw Error(`SPECIAL_OUTPUT:${p}`);
    }
  }
  await walk(root);
  return out.sort();
}
export function digestFileRecords(
  records: Array<{ path: string; byteLength: number; sha256: string }>,
): string {
  return sha256(
    stable(
      records.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0)),
    ),
  );
}
export type NodeModulesEntry =
  | { path: string; kind: "file"; byteLength: number; sha256: string }
  | {
      path: string;
      kind: "symlink";
      target: string;
      targetPath: string;
      targetByteLength: number;
      targetSha256: string;
    };
export function computeNodeModulesClosure(root = "node_modules"): {
  entries: NodeModulesEntry[];
  regularFiles: number;
  symlinks: number;
  totalBytes: number;
  merkleRoot: string;
} {
  assertCanonicalRelativePath(root, "node-modules-root");
  assertSafeAncestors(root, ".", "node-modules-root");
  const boundary = realpathSync(root),
    entries: NodeModulesEntry[] = [];
  const walk = (directory: string) => {
    for (const item of readdirSync(directory, { withFileTypes: true }).sort(
      (a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0),
    )) {
      const path = `${directory}/${item.name}`,
        rel = relative(root, path).split(sep).join("/"),
        info = lstatSync(path);
      if (
        rel === ".DS_Store" ||
        rel === ".cache" ||
        rel.startsWith(".cache/") ||
        rel === ".vite" ||
        rel.startsWith(".vite/")
      )
        continue;
      if (info.isDirectory() && !info.isSymbolicLink()) walk(path);
      else if (info.isFile() && !info.isSymbolicLink()) {
        const bytes = readFileSync(path);
        entries.push({
          path: rel,
          kind: "file",
          byteLength: bytes.length,
          sha256: sha256(bytes),
        });
      } else if (info.isSymbolicLink()) {
        const target = readlinkSync(path),
          targetReal = realpathSync(path),
          targetRel = relative(boundary, targetReal).split(sep).join("/");
        if (targetRel === ".." || targetRel.startsWith("../"))
          throw Error(`NODE_MODULES_SYMLINK_ESCAPE:${rel}`);
        const targetInfo = lstatSync(targetReal);
        if (!targetInfo.isFile() || targetInfo.isSymbolicLink())
          throw Error(`NODE_MODULES_SYMLINK_TARGET:${rel}`);
        const bytes = readFileSync(targetReal);
        entries.push({
          path: rel,
          kind: "symlink",
          target,
          targetPath: targetRel,
          targetByteLength: bytes.length,
          targetSha256: sha256(bytes),
        });
      } else throw Error(`NODE_MODULES_SPECIAL:${rel}`);
    }
  };
  walk(root);
  entries.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  const regularFiles = entries.filter((entry) => entry.kind === "file").length,
    symlinks = entries.length - regularFiles,
    totalBytes = entries.reduce(
      (sum, entry) => sum + (entry.kind === "file" ? entry.byteLength : 0),
      0,
    );
  return {
    entries,
    regularFiles,
    symlinks,
    totalBytes,
    merkleRoot: sha256(stable(entries)),
  };
}
export function verifyNodeModulesClosure(root: string, manifest: any): void {
  assertExactKeys(
    manifest,
    [
      "schemaVersion",
      "policy",
      "root",
      "regularFiles",
      "symlinks",
      "totalBytes",
      "entryCount",
      "merkleRoot",
      "entries",
    ],
    "node-modules-closure",
  );
  if (
    manifest.schemaVersion !== "tidy.node-modules-closure/v1" ||
    manifest.root !== root ||
    stable(manifest.policy) !==
      stable({
        include: "all regular files and symlinks with regular in-root targets",
        excluded: [
          ".DS_Store (Finder metadata, never imported)",
          ".cache/** (Jiti/Pi compile cache outside project runtime imports)",
          ".vite/** (Vitest result cache, never imported by replay)",
        ],
      })
  )
    throw Error("NODE_MODULES_CLOSURE_SCHEMA");
  const actual = computeNodeModulesClosure(root);
  if (
    manifest.regularFiles !== actual.regularFiles ||
    manifest.symlinks !== actual.symlinks ||
    manifest.totalBytes !== actual.totalBytes ||
    manifest.entryCount !== actual.entries.length ||
    manifest.merkleRoot !== actual.merkleRoot ||
    stable(manifest.entries) !== stable(actual.entries)
  )
    throw Error("NODE_MODULES_CLOSURE_DRIFT");
}
export async function verifyToolchainClosure(
  toolchain: any,
  pins: Map<string, FilePin>,
): Promise<void> {
  assertExactKeys(
    toolchain,
    [
      "schemaVersion",
      "packageJson",
      "packageLock",
      "node",
      "python",
      "nodeModules",
      "tsxEntrypoint",
    ],
    "toolchain-closure",
  );
  if (toolchain.schemaVersion !== "tidy.offenders-target-scoped-toolchain/v1")
    throw Error("TOOLCHAIN_SCHEMA");
  for (const [field, path] of [
    ["packageJson", "package.json"],
    ["packageLock", "package-lock.json"],
  ] as const) {
    const proof = toolchain[field];
    assertExactKeys(proof, ["path", "byteLength", "sha256"], field);
    if (proof.path !== path || stable(proof) !== stable(pins.get(path)))
      throw Error(`TOOLCHAIN_PACKAGE_PIN:${path}`);
  }
  const verifyExecutable = (
    proof: any,
    label: string,
    expectedVersion: string,
  ) => {
    assertExactKeys(
      proof,
      [
        "version",
        "executablePath",
        "realPath",
        "linkTarget",
        "byteLength",
        "sha256",
      ],
      `${label}-executable`,
    );
    const info = lstatSync(proof.executablePath),
      real = realpathSync(proof.executablePath),
      bytes = readFileSync(real);
    const linkTarget = info.isSymbolicLink()
      ? readlinkSync(proof.executablePath)
      : null;
    if (!info.isFile() && !info.isSymbolicLink())
      throw Error(`TOOLCHAIN_EXECUTABLE_TYPE:${label}`);
    if (
      proof.version !== expectedVersion ||
      proof.realPath !== real ||
      proof.linkTarget !== linkTarget ||
      proof.byteLength !== bytes.length ||
      proof.sha256 !== sha256(bytes)
    )
      throw Error(`TOOLCHAIN_EXECUTABLE_DRIFT:${label}`);
  };
  verifyExecutable(toolchain.node, "node", process.version);
  if (
    realpathSync(toolchain.node.executablePath) !==
    realpathSync(process.execPath)
  )
    throw Error("TOOLCHAIN_NODE_PROCESS_MISMATCH");
  const pythonVersion = execFileSync(
    toolchain.python.executablePath,
    ["--version"],
    { encoding: "utf8" },
  ).trim();
  verifyExecutable(toolchain.python, "python", pythonVersion);
  const manifestPin = toolchain.nodeModules.manifest;
  assertExactKeys(
    toolchain.nodeModules,
    [
      "root",
      "manifest",
      "entryCount",
      "regularFiles",
      "symlinks",
      "totalBytes",
      "merkleRoot",
    ],
    "node-modules-toolchain",
  );
  if (
    toolchain.nodeModules.root !== "node_modules" ||
    stable(manifestPin) !== stable(pins.get(manifestPin.path))
  )
    throw Error("NODE_MODULES_MANIFEST_PIN");
  const manifest = await readPinnedJson(
    manifestPin.path,
    manifestPin,
    8_000_000,
    500_000,
  );
  verifyNodeModulesClosure("node_modules", manifest);
  for (const key of [
    "entryCount",
    "regularFiles",
    "symlinks",
    "totalBytes",
    "merkleRoot",
  ])
    if (toolchain.nodeModules[key] !== manifest[key])
      throw Error(`NODE_MODULES_SUMMARY:${key}`);
  const tsx = toolchain.tsxEntrypoint;
  assertExactKeys(tsx, ["path", "byteLength", "sha256"], "tsx-entrypoint");
  const tsxPin = pins.get(tsx.path),
    entry = manifest.entries.find(
      (item: any) =>
        item.path === relative("node_modules", tsx.path).split(sep).join("/"),
    );
  if (
    tsx.path !== "node_modules/tsx/dist/cli.mjs" ||
    stable(tsx) !== stable(tsxPin) ||
    !entry ||
    entry.kind !== "file" ||
    entry.byteLength !== tsx.byteLength ||
    entry.sha256 !== tsx.sha256
  )
    throw Error("TSX_ENTRYPOINT_DRIFT");
}
const OWNER_FILE = ".c2-transaction-owner.json";
type Owner = {
  version: "c2-transaction-owner/v1";
  token: string;
  finalPath: string;
  kind: "lock" | "temporary" | "backup";
};
function ownerBytes(owner: Owner): string {
  return `${JSON.stringify(owner)}\n`;
}
function readOwner(path: string, kind: Owner["kind"]): Owner {
  const file = kind === "lock" ? `${path}/owner.json` : `${path}/${OWNER_FILE}`;
  const info = lstatSync(file);
  if (info.isSymbolicLink() || !info.isFile())
    throw Error(`INVALID_OWNER_FILE:${path}`);
  const value = JSON.parse(readFileSync(file, "utf8")) as Owner;
  if (
    value.version !== "c2-transaction-owner/v1" ||
    value.kind !== kind ||
    typeof value.token !== "string" ||
    !/^[a-f0-9-]{36}$/.test(value.token) ||
    typeof value.finalPath !== "string"
  )
    throw Error(`INVALID_PATH_OWNER:${path}`);
  return value;
}
function assertLockOwned(
  lockPath: string,
  token: string,
  finalPath: string,
): void {
  const owner = readOwner(lockPath, "lock");
  if (owner.token !== token || owner.finalPath !== finalPath)
    throw Error("TRANSACTION_LOCK_NOT_OWNED");
}
function assertPathOwned(
  path: string,
  kind: "temporary" | "backup",
  token: string,
  finalPath: string,
): void {
  const owner = readOwner(path, kind);
  if (owner.token !== token || owner.finalPath !== finalPath)
    throw Error(`TRANSACTION_PATH_NOT_OWNED:${path}`);
}
function removeOwned(
  path: string,
  kind: "temporary" | "backup",
  token: string,
  finalPath: string,
  lockPath: string,
): void {
  assertLockOwned(lockPath, token, finalPath);
  assertSafeAncestors(path, ".", `${kind}-remove`);
  assertPathOwned(path, kind, token, finalPath);
  rmSync(path, { recursive: true, force: false });
}
function removeInstalledOwned(
  path: string,
  token: string,
  finalPath: string,
  lockPath: string,
): void {
  assertLockOwned(lockPath, token, finalPath);
  assertSafeAncestors(path, ".", "installed-remove");
  assertPathOwned(path, "temporary", token, finalPath);
  rmSync(path, { recursive: true, force: false });
}
function releaseLock(lockPath: string, token: string, finalPath: string): void {
  assertLockOwned(lockPath, token, finalPath);
  unlinkSync(`${lockPath}/owner.json`);
  rmdirSync(lockPath);
}
function removeStaleOwned(
  path: string,
  kind: "temporary" | "backup",
  currentToken: string,
  finalPath: string,
  lockPath: string,
): void {
  assertLockOwned(lockPath, currentToken, finalPath);
  assertSafeAncestors(path, ".", `stale-${kind}-remove`);
  const owner = readOwner(path, kind);
  if (owner.finalPath !== finalPath)
    throw Error(`STALE_PATH_FINAL_MISMATCH:${path}`);
  rmSync(path, { recursive: true, force: false });
}
function staleOwnedPaths(
  finalPath: string,
  kind: "temporary" | "backup",
): string[] {
  const parent = dirname(finalPath),
    prefix = `${basename(finalPath)}.${kind}-`;
  if (!existsSync(parent)) return [];
  const matches = readdirSync(parent, { withFileTypes: true }).filter((entry) =>
    entry.name.startsWith(prefix),
  );
  for (const entry of matches)
    if (entry.isSymbolicLink() || !entry.isDirectory())
      throw Error(`UNSAFE_STALE_TRANSACTION_PATH:${parent}/${entry.name}`);
  return matches.map((entry) => `${parent}/${entry.name}`).sort();
}
export async function beginTargetTransaction(
  requested: string,
  injected?: string,
) {
  const allowed =
    ".product-prototype/offenders-remaining-phase1/target-scoped-c2";
  const finalPath = assertContained(requested, allowed, "output");
  if (
    dirname(finalPath) !== resolve(allowed) ||
    !/^run-[A-Za-z0-9._-]+$/.test(basename(finalPath))
  )
    throw Error("UNSAFE_OUTPUT_NAME");
  assertSafeAncestors(allowed, ".", "allowed-root");
  await mkdir(allowed, { recursive: true });
  assertSafeAncestors(finalPath, ".", "final-root");
  if (existsSync(finalPath)) {
    const info = lstatSync(finalPath);
    if (info.isSymbolicLink() || !info.isDirectory())
      throw Error(`UNSAFE_FINAL_ROOT:${finalPath}`);
  }
  const token = randomUUID(),
    lockPath = `${finalPath}.lock`;
  try {
    mkdirSync(lockPath);
  } catch (error: any) {
    if (error?.code === "EEXIST")
      throw Error(`TRANSACTION_LOCKED:${finalPath}`);
    throw error;
  }
  writeFileSync(
    `${lockPath}/owner.json`,
    ownerBytes({
      version: "c2-transaction-owner/v1",
      token,
      finalPath,
      kind: "lock",
    }),
    { flag: "wx" },
  );
  assertLockOwned(lockPath, token, finalPath);
  const temporaryPath = `${finalPath}.temporary-${token}`,
    backupPath = `${finalPath}.backup-${token}`;
  try {
    for (const kind of ["temporary", "backup"] as const)
      for (const stale of staleOwnedPaths(finalPath, kind))
        removeStaleOwned(stale, kind, token, finalPath, lockPath);
    mkdirSync(temporaryPath);
    writeFileSync(
      `${temporaryPath}/${OWNER_FILE}`,
      ownerBytes({
        version: "c2-transaction-owner/v1",
        token,
        finalPath,
        kind: "temporary",
      }),
      { flag: "wx" },
    );
  } catch (error) {
    if (existsSync(temporaryPath)) {
      try {
        removeOwned(temporaryPath, "temporary", token, finalPath, lockPath);
      } catch {
        /* Never remove an unmarked path. */
      }
    }
    if (existsSync(lockPath)) releaseLock(lockPath, token, finalPath);
    throw error;
  }
  let committed = false,
    lockReleased = false;
  const rollbackSync = () => {
    if (committed || lockReleased || !existsSync(lockPath)) return;
    assertLockOwned(lockPath, token, finalPath);
    if (existsSync(finalPath)) {
      try {
        removeInstalledOwned(finalPath, token, finalPath, lockPath);
      } catch {
        try {
          assertPathOwned(finalPath, "backup", token, finalPath);
          unlinkSync(`${finalPath}/${OWNER_FILE}`);
        } catch {
          /* Foreign or unowned finals are never deleted or mutated. */
        }
      }
    }
    if (existsSync(backupPath)) {
      assertPathOwned(backupPath, "backup", token, finalPath);
      unlinkSync(`${backupPath}/${OWNER_FILE}`);
      if (!existsSync(finalPath)) renameSync(backupPath, finalPath);
    }
    if (existsSync(temporaryPath))
      removeOwned(temporaryPath, "temporary", token, finalPath, lockPath);
    if (existsSync(lockPath)) releaseLock(lockPath, token, finalPath);
    lockReleased = true;
  };
  process.once("exit", rollbackSync);
  return {
    token,
    lockPath,
    temporaryPath,
    backupPath,
    async abort() {
      rollbackSync();
    },
    async commit() {
      assertLockOwned(lockPath, token, finalPath);
      assertPathOwned(temporaryPath, "temporary", token, finalPath);
      if (injected === "before-swap") {
        rollbackSync();
        throw Error("INJECTED_FAILURE:before-swap");
      }
      const prior = existsSync(finalPath);
      try {
        if (prior) {
          const info = lstatSync(finalPath);
          if (info.isSymbolicLink() || !info.isDirectory())
            throw Error("UNSAFE_PRIOR_ROOT");
          writeFileSync(
            `${finalPath}/${OWNER_FILE}`,
            ownerBytes({
              version: "c2-transaction-owner/v1",
              token,
              finalPath,
              kind: "backup",
            }),
            { flag: "wx" },
          );
          await rename(finalPath, backupPath);
        }
        await rename(temporaryPath, finalPath);
        if (injected === "after-swap")
          throw Error("INJECTED_FAILURE:after-swap");
        assertPathOwned(finalPath, "temporary", token, finalPath);
        await unlink(`${finalPath}/${OWNER_FILE}`);
        // Commit point: no later cleanup failure may roll back this valid final.
        committed = true;
      } catch (error) {
        rollbackSync();
        throw error;
      }
      let cleanupError: unknown;
      try {
        if (injected === "cleanup-failure")
          throw Error("INJECTED_FAILURE:cleanup-failure");
        if (existsSync(backupPath))
          removeOwned(backupPath, "backup", token, finalPath, lockPath);
      } catch (error) {
        cleanupError = error;
      } finally {
        releaseLock(lockPath, token, finalPath);
        lockReleased = true;
      }
      if (cleanupError)
        throw Error(`POST_COMMIT_CLEANUP_FAILURE:${String(cleanupError)}`);
    },
  };
}
