import { createHash } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import {
  lstat,
  mkdir,
  mkdtemp,
  open,
  readdir,
  realpath,
  rename,
  rm,
  rmdir,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { z } from "zod";

const MAX_REQUEST_ID_LENGTH = 128;
const MAX_NAME_LENGTH = 200;
const MAX_PATH_LENGTH = 512;
const MAX_MESSAGE_LENGTH = 1_024;
export const MAX_RESPONSE_ENVELOPE_BYTES = 1_000_000;
const digestSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const inputSchema = z
  .object({
    name: z
      .string()
      .min(1)
      .max(MAX_NAME_LENGTH)
      .regex(/^[A-Za-z0-9._-]+$/),
    relativePath: z.string().min(1).max(MAX_PATH_LENGTH),
    contentDigest: digestSchema,
    byteLength: z.number().int().nonnegative().max(50_000_000),
  })
  .strict();
const outputDescriptorSchema = z
  .object({
    name: z.string().min(1).max(MAX_PATH_LENGTH),
    relativePath: z.string().min(1).max(MAX_PATH_LENGTH),
    contentDigest: digestSchema,
    byteLength: z.number().int().nonnegative().max(50_000_000),
  })
  .strict();
const warningDescriptorSchema = z
  .object({
    code: z.string().min(1).max(MAX_NAME_LENGTH),
    message: z.string().max(MAX_MESSAGE_LENGTH),
    path: z.string().max(MAX_PATH_LENGTH).optional(),
  })
  .strict();
const stageSchema = z.enum([
  "protocol",
  "input",
  "parse",
  "prompt",
  "semantic-map",
  "recipe",
  "execute",
  "export",
  "limit",
]);
const workerResultSchema = z.union([
  z
    .object({
      protocolVersion: z.literal("tidy.worker/v1"),
      requestId: z.string().min(1).max(MAX_REQUEST_ID_LENGTH),
      ok: z.literal(true),
      outputs: z.array(outputDescriptorSchema).max(10_000),
      warnings: z.array(warningDescriptorSchema).max(10_000),
    })
    .strict(),
  z
    .object({
      protocolVersion: z.literal("tidy.worker/v1"),
      requestId: z.string().min(1).max(MAX_REQUEST_ID_LENGTH),
      ok: z.literal(false),
      error: z
        .object({
          code: z.string().min(1).max(MAX_NAME_LENGTH),
          stage: stageSchema,
          message: z.string().max(MAX_MESSAGE_LENGTH),
          details: z.unknown().optional(),
        })
        .strict(),
    })
    .strict(),
]);

export type WorkerRequest = {
  protocolVersion: "tidy.worker/v1";
  requestId: string;
  operation: string;
  inputs: Array<z.infer<typeof inputSchema>>;
  parameters: Record<string, unknown>;
  limits: {
    maxOutputFiles: number;
    maxWarnings: number;
    maxOutputBytes: number;
    maxOutputRows: number;
    [key: string]: number;
  };
};
export type WorkerResult = z.infer<typeof workerResultSchema>;
export type WorkerPublicationRequest = WorkerRequest;
export type OutputDescriptor = z.infer<typeof outputDescriptorSchema>;
export type ProducedFile = {
  name: string;
  relativePath: string;
  render: () => Buffer;
};
export type RootIdentity = {
  requestedPath: string;
  canonicalPath: string;
  device: bigint;
  inode: bigint;
};
export type RootContext = { input: RootIdentity; output: RootIdentity };

export async function publish(
  request: WorkerPublicationRequest,
  roots: RootContext,
  files: ProducedFile[],
  warnings: Array<{ code: string; message: string }> = [],
): Promise<WorkerResult> {
  if (files.length > request.limits.maxOutputFiles)
    throw new ProtocolError(
      "OUTPUT_DESCRIPTOR_LIMIT_EXCEEDED",
      "limit",
      `Outputs exceed the ${request.limits.maxOutputFiles} descriptor limit.`,
    );
  if (warnings.length > request.limits.maxWarnings)
    throw new ProtocolError(
      "WARNING_LIMIT_EXCEEDED",
      "limit",
      `Warnings exceed the ${request.limits.maxWarnings} descriptor limit.`,
    );

  const parent = path.dirname(roots.output.requestedPath);
  const stagingRoot = await mkdtemp(path.join(parent, ".tidy-worker-stage-"));
  let published = false;
  try {
    const outputs: OutputDescriptor[] = [];
    let total = 0;
    for (const file of files) {
      assertSafeRelativePath(file.relativePath);
      if (
        file.name.length > MAX_PATH_LENGTH ||
        file.relativePath.length > MAX_PATH_LENGTH
      )
        throw new ProtocolError(
          "OUTPUT_PATH_LIMIT_EXCEEDED",
          "limit",
          "Output descriptor path exceeds the protocol limit.",
        );
      const bytes = file.render();
      total += bytes.byteLength;
      if (total > request.limits.maxOutputBytes)
        throw new ProtocolError(
          "OUTPUT_LIMIT_EXCEEDED",
          "limit",
          `Declared outputs exceed limit ${request.limits.maxOutputBytes}.`,
        );
      const destination = path.join(stagingRoot, file.relativePath);
      await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
      await writeFile(destination, bytes, { flag: "wx", mode: 0o600 });
      outputs.push({
        name: file.name,
        relativePath: file.relativePath,
        contentDigest: sha256(bytes),
        byteLength: bytes.byteLength,
      });
    }
    const actual = await listFiles(stagingRoot);
    const declared = outputs.map((output) => output.relativePath).sort();
    if (JSON.stringify(actual) !== JSON.stringify(declared))
      throw new ProtocolError(
        "UNDECLARED_OUTPUT",
        "export",
        "Private staging contains undeclared files.",
      );

    const success: WorkerResult = {
      protocolVersion: "tidy.worker/v1",
      requestId: request.requestId,
      ok: true,
      outputs,
      warnings,
    };
    assertSerializableWorkerResult(success);
    await assertRootUnchanged(roots.input);
    await assertRootUnchanged(roots.output);
    await assertRootsDoNotOverlap(
      roots.input.canonicalPath,
      roots.output.canonicalPath,
    );
    if ((await readdir(roots.output.requestedPath)).length !== 0)
      throw new ProtocolError(
        "OUTPUT_ROOT_CHANGED",
        "export",
        "Output root changed during execution.",
      );
    await rmdir(roots.output.requestedPath);
    try {
      await rename(stagingRoot, roots.output.requestedPath);
      published = true;
    } catch (error) {
      await mkdir(roots.output.requestedPath, { mode: 0o700 }).catch(
        () => undefined,
      );
      throw error;
    }
    return success;
  } finally {
    if (!published) await rm(stagingRoot, { recursive: true, force: true });
  }
}

export async function readVerifiedInput(
  root: string,
  input: z.infer<typeof inputSchema>,
): Promise<Buffer> {
  assertSafeRelativePath(input.relativePath);
  const target = path.join(root, input.relativePath);
  await assertNoSymlinks(root, input.relativePath);
  const info = await lstat(target, { bigint: true }).catch(() => undefined);
  if (!info?.isFile())
    throw new ProtocolError(
      "INPUT_NOT_REGULAR_FILE",
      "input",
      `Input ${input.name} is not a regular file.`,
    );
  if (info.size !== BigInt(input.byteLength))
    throw new ProtocolError(
      "BYTE_LENGTH_MISMATCH",
      "input",
      `Byte length mismatch for input ${input.name}.`,
    );
  const handle = await open(
    target,
    fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW,
  );
  let bytes: Buffer;
  try {
    const opened = await handle.stat({ bigint: true });
    if (!opened.isFile() || opened.dev !== info.dev || opened.ino !== info.ino)
      throw new ProtocolError(
        "INPUT_CHANGED",
        "input",
        `Input ${input.name} changed while opening.`,
      );
    bytes = await handle.readFile();
  } finally {
    await handle.close();
  }
  if (bytes.byteLength !== input.byteLength)
    throw new ProtocolError(
      "BYTE_LENGTH_MISMATCH",
      "input",
      `Byte length mismatch for input ${input.name}.`,
    );
  if (sha256(bytes) !== input.contentDigest)
    throw new ProtocolError(
      "DIGEST_MISMATCH",
      "input",
      `Digest mismatch for input ${input.name}.`,
    );
  return bytes;
}

export function assertSafeRelativePath(relativePath: string): void {
  if (
    relativePath.includes("\0") ||
    relativePath.includes("\\") ||
    path.posix.isAbsolute(relativePath)
  )
    throw new ProtocolError(
      "UNSAFE_PATH",
      "input",
      "Manifest paths must be portable relative paths.",
    );
  const parts = relativePath.split("/");
  if (
    parts.length === 0 ||
    parts.some((part) => part === "" || part === "." || part === "..") ||
    path.posix.normalize(relativePath) !== relativePath
  )
    throw new ProtocolError(
      "UNSAFE_PATH",
      "input",
      "Manifest path escapes or is not normalized.",
    );
}

async function assertNoSymlinks(
  root: string,
  relativePath: string,
): Promise<void> {
  let current = root;
  for (const part of relativePath.split("/")) {
    current = path.join(current, part);
    const info = await lstat(current).catch(() => undefined);
    if (info?.isSymbolicLink())
      throw new ProtocolError(
        "SYMLINK_PATH",
        "input",
        "Manifest paths may not traverse symlinks.",
      );
  }
}

async function inspectRoot(root: string, label: string): Promise<RootIdentity> {
  if (root.length === 0 || root.length > 4_096)
    throw new ProtocolError(
      "UNSAFE_ROOT",
      "input",
      `${label} root path is invalid.`,
    );
  const info = await lstat(root, { bigint: true }).catch(() => undefined);
  if (!info?.isDirectory() || info.isSymbolicLink())
    throw new ProtocolError(
      "UNSAFE_ROOT",
      label === "output" ? "export" : "input",
      `${label} root must be an existing real directory. The launcher must create private roots.`,
    );
  return {
    requestedPath: path.resolve(root),
    canonicalPath: await realpath(root),
    device: info.dev,
    inode: info.ino,
  };
}

export async function assertIndependentRoots(
  inputRoot: string,
  outputRoot: string,
): Promise<RootContext> {
  const input = await inspectRoot(inputRoot, "input");
  const output = await inspectRoot(outputRoot, "output");
  await assertRootsDoNotOverlap(input.canonicalPath, output.canonicalPath);
  return { input, output };
}

async function assertRootsDoNotOverlap(
  input: string,
  output: string,
): Promise<void> {
  const relativeInputToOutput = path.relative(input, output);
  const relativeOutputToInput = path.relative(output, input);
  const nested = (relative: string) =>
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) && relative !== "..");
  if (nested(relativeInputToOutput) || nested(relativeOutputToInput))
    throw new ProtocolError(
      "OVERLAPPING_ROOTS",
      "input",
      "Input and output roots must be distinct and must not contain one another, including after canonicalization.",
    );
}

async function assertRootUnchanged(identity: RootIdentity): Promise<void> {
  const current = await lstat(identity.requestedPath, { bigint: true }).catch(
    () => undefined,
  );
  if (
    !current?.isDirectory() ||
    current.isSymbolicLink() ||
    current.dev !== identity.device ||
    current.ino !== identity.inode ||
    (await realpath(identity.requestedPath)) !== identity.canonicalPath
  )
    throw new ProtocolError(
      "ROOT_CHANGED",
      "export",
      "A launcher root changed during worker execution.",
    );
}

export async function prepareOutputRoot(root: string): Promise<void> {
  if ((await readdir(root)).length !== 0)
    throw new ProtocolError(
      "OUTPUT_ROOT_NOT_EMPTY",
      "export",
      "Output root must be an empty launcher-created private directory.",
    );
  const parentInfo = await stat(path.dirname(path.resolve(root)));
  if (!parentInfo.isDirectory())
    throw new ProtocolError(
      "UNSAFE_ROOT",
      "export",
      "Output parent must be a directory.",
    );
}

async function listFiles(root: string, prefix = ""): Promise<string[]> {
  const entries = await readdir(path.join(root, prefix), {
    withFileTypes: true,
  });
  const files: string[] = [];
  for (const entry of entries) {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isSymbolicLink())
      throw new ProtocolError(
        "UNDECLARED_OUTPUT",
        "export",
        "Output contains a symlink.",
      );
    if (entry.isDirectory()) files.push(...(await listFiles(root, relative)));
    else if (entry.isFile()) files.push(relative);
    else
      throw new ProtocolError(
        "UNDECLARED_OUTPUT",
        "export",
        "Output contains a non-file entry.",
      );
  }
  return files.sort();
}

export function jsonBytes(value: unknown): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
}
function sha256(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}
function getRequestId(raw: unknown): string {
  return typeof raw === "object" &&
    raw !== null &&
    typeof (raw as { requestId?: unknown }).requestId === "string"
    ? (raw as { requestId: string }).requestId.slice(0, MAX_REQUEST_ID_LENGTH)
    : "invalid-request";
}
function stableIssues(error: z.ZodError): unknown {
  return error.issues.map((issue) => ({
    code: issue.code,
    path: issue.path.join("."),
    message: issue.message,
  }));
}
export function failure(
  requestId: string,
  code: string,
  stage: z.infer<typeof stageSchema>,
  message: string,
  details?: unknown,
): WorkerResult {
  return {
    protocolVersion: "tidy.worker/v1",
    requestId,
    ok: false,
    error: {
      code,
      stage,
      message: message.slice(0, MAX_MESSAGE_LENGTH),
      ...(details === undefined ? {} : { details }),
    },
  };
}

export function normalizeWorkerResult(raw: unknown): WorkerResult {
  const parsed = workerResultSchema.safeParse(raw);
  if (!parsed.success)
    return compactContractFailure(
      "INVALID_WORKER_RESULT",
      "Worker result did not match tidy.worker/v1.",
    );
  try {
    if (
      Buffer.byteLength(`${JSON.stringify(parsed.data)}\n`, "utf8") >
      MAX_RESPONSE_ENVELOPE_BYTES
    )
      return compactContractFailure(
        "RESPONSE_LIMIT_EXCEEDED",
        `Worker response exceeds ${MAX_RESPONSE_ENVELOPE_BYTES} bytes.`,
      );
  } catch {
    return compactContractFailure(
      "INVALID_WORKER_RESULT",
      "Worker result could not be serialized.",
    );
  }
  return parsed.data;
}

export function serializeWorkerResult(raw: unknown): string {
  return `${JSON.stringify(normalizeWorkerResult(raw))}\n`;
}

function assertSerializableWorkerResult(result: WorkerResult): void {
  const parsed = workerResultSchema.safeParse(result);
  if (!parsed.success)
    throw new ProtocolError(
      "INVALID_WORKER_RESULT",
      "export",
      "Generated result does not match tidy.worker/v1.",
    );
  if (
    Buffer.byteLength(`${JSON.stringify(parsed.data)}\n`, "utf8") >
    MAX_RESPONSE_ENVELOPE_BYTES
  )
    throw new ProtocolError(
      "RESPONSE_LIMIT_EXCEEDED",
      "limit",
      `Worker response exceeds ${MAX_RESPONSE_ENVELOPE_BYTES} bytes.`,
    );
}

function compactContractFailure(code: string, message: string): WorkerResult {
  return {
    protocolVersion: "tidy.worker/v1",
    requestId: "invalid-request",
    ok: false,
    error: { code, stage: "protocol", message },
  };
}

export class ProtocolError extends Error {
  constructor(
    readonly code: string,
    readonly stage:
      | "protocol"
      | "input"
      | "parse"
      | "prompt"
      | "semantic-map"
      | "recipe"
      | "execute"
      | "export"
      | "limit",
    message: string,
  ) {
    super(message);
  }
}
