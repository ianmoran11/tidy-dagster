import { createHash, randomUUID } from "node:crypto";
import {
  link,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  unlink,
} from "node:fs/promises";
import path from "node:path";
import { resolveContainedPath } from "../../harvest/path-safety";

export type ImmutableWriteResult = {
  path: string;
  sha256: string;
  bytes: number;
  created: boolean;
};

export function sha256Bytes(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

export function canonicalJson(value: unknown): string {
  if (Array.isArray(value))
    return `[${value.map((entry) => canonicalJson(entry ?? null)).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .filter(([, entry]) => entry !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function digestCanonicalJson(value: unknown): string {
  return sha256Bytes(Buffer.from(canonicalJson(value)));
}

export async function assertNoIncompleteArtifacts(
  directory: string,
): Promise<void> {
  let names: string[];
  try {
    names = await readdir(directory);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  const incomplete = names.filter((name) => name.startsWith(".tmp-cell-role-"));
  if (incomplete.length) {
    throw new Error(
      `INCOMPLETE_ARTIFACT: ${incomplete.sort().join(", ")}. Quarantine or remove after inspection.`,
    );
  }
}

/**
 * Durably publishes bytes without replacing an existing target.
 *
 * The temporary file is created in the target directory, fsynced, and linked
 * into place. link(2) supplies atomic create-if-absent semantics on the same
 * filesystem. An existing byte-identical target is accepted idempotently.
 */
export async function writeImmutableContainedFile(options: {
  repoRoot: string;
  target: string;
  bytes: Uint8Array;
  mode?: number;
  pathErrorCode?: string;
}): Promise<ImmutableWriteResult> {
  const code = options.pathErrorCode ?? "ARTIFACT_PATH_ESCAPE";
  const target = await resolveContainedPath({
    root: options.repoRoot,
    value: options.target,
    mustExist: false,
    code,
  });
  const directory = path.dirname(target);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await resolveContainedPath({
    root: options.repoRoot,
    value: directory,
    mustExist: true,
    code,
  });
  await assertNoIncompleteArtifacts(directory);

  const bytes = Buffer.from(options.bytes);
  const digest = sha256Bytes(bytes);
  const temporary = path.join(
    directory,
    `.tmp-cell-role-${process.pid}-${randomUUID()}`,
  );
  let temporaryExists = false;
  try {
    const handle = await open(temporary, "wx", options.mode ?? 0o600);
    temporaryExists = true;
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally {
      await handle.close();
    }

    // Revalidate immediately before publication to catch parent substitution.
    await resolveContainedPath({
      root: options.repoRoot,
      value: directory,
      mustExist: true,
      code,
    });
    try {
      await link(temporary, target);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      const existing = await readFile(target);
      if (
        existing.byteLength !== bytes.byteLength ||
        sha256Bytes(existing) !== digest ||
        !existing.equals(bytes)
      ) {
        throw new Error(`IMMUTABLE_ARTIFACT_CONFLICT: ${options.target}`);
      }
      await unlink(temporary);
      temporaryExists = false;
      return {
        path: target,
        sha256: digest,
        bytes: bytes.byteLength,
        created: false,
      };
    }

    await unlink(temporary);
    temporaryExists = false;
    await syncDirectory(directory);
    return {
      path: target,
      sha256: digest,
      bytes: bytes.byteLength,
      created: true,
    };
  } finally {
    if (temporaryExists) {
      await unlink(temporary).catch(() => undefined);
    }
  }
}

export async function readContainedArtifact(options: {
  repoRoot: string;
  target: string;
  pathErrorCode?: string;
}): Promise<Buffer> {
  const target = await resolveContainedPath({
    root: options.repoRoot,
    value: options.target,
    mustExist: true,
    code: options.pathErrorCode ?? "ARTIFACT_PATH_ESCAPE",
  });
  const stat = await lstat(target);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`ARTIFACT_NOT_REGULAR_FILE: ${options.target}`);
  }
  return readFile(target);
}

async function syncDirectory(directory: string): Promise<void> {
  let handle;
  try {
    handle = await open(directory, "r");
    await handle.sync();
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (
      !["EINVAL", "ENOTSUP", "EISDIR", "EBADF", "EPERM"].includes(code ?? "")
    ) {
      throw error;
    }
  } finally {
    await handle?.close().catch(() => undefined);
  }
}
