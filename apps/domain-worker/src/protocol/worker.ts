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
import { executeRecipe } from "../executor/executeRecipe.js";
import { buildGeometryEvidence } from "../executor/geometryEvidence.js";
import { rowsToCsv } from "../export/formatters.js";
import {
  resolveRecipeSelectors,
  type ResolvedRecipeSelectors,
} from "../recipe/resolveSelectors.js";
import { validateRecipe } from "../recipe/schema.js";
import type { RecipeV01 } from "../recipe/types.js";
import { buildSheetSummary } from "../summary/buildSheetSummary.js";
import { findRecipeSheet } from "../workbook/findRecipeSheet.js";
import { parseWorkbook } from "../workbook/parseWorkbook.js";
import {
  enforceRecipeSelectorLimit,
  enforceWorkbookLimits,
  LimitViolation,
  preflightXlsxZip,
} from "./resourceLimits.js";

const MAX_REQUEST_ID_LENGTH = 128;
const MAX_NAME_LENGTH = 64;
const MAX_PATH_LENGTH = 512;
const MAX_MESSAGE_LENGTH = 1_024;
export const MAX_RESPONSE_ENVELOPE_BYTES = 1_000_000;
export const MAX_OUTPUT_DESCRIPTORS = 10_000;
export const MAX_WARNING_DESCRIPTORS = 10_000;
const digestSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const boundedPositiveInteger = (maximum: number) =>
  z.number().int().positive().max(maximum);
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
const parametersSchema = z
  .object({
    evidenceProfile: z
      .enum(["m1-simple-v1", "m2-deterministic-parity-v1"])
      .optional(),
    includeSummary: z.boolean().optional(),
    csvMode: z.literal("recipe-aware").optional(),
  })
  .strict();
const requestSchema = z
  .object({
    protocolVersion: z.literal("tidy.worker/v1"),
    requestId: z.string().min(1).max(MAX_REQUEST_ID_LENGTH),
    operation: z.enum(["health", "capabilities", "execute-recipe-v01"]),
    inputs: z.array(inputSchema).max(8),
    parameters: parametersSchema,
    limits: z
      .object({
        timeoutMs: boundedPositiveInteger(300_000),
        maxInputBytes: boundedPositiveInteger(50_000_000),
        maxOutputBytes: boundedPositiveInteger(50_000_000),
        maxOutputFiles: boundedPositiveInteger(MAX_OUTPUT_DESCRIPTORS),
        maxWarnings: boundedPositiveInteger(MAX_WARNING_DESCRIPTORS),
        maxWorkbookCompressedBytes: boundedPositiveInteger(25_000_000),
        maxZipEntries: boundedPositiveInteger(10_000),
        maxZipEntryUncompressedBytes: boundedPositiveInteger(50_000_000),
        maxZipTotalUncompressedBytes: boundedPositiveInteger(200_000_000),
        maxSheets: boundedPositiveInteger(256),
        maxCells: boundedPositiveInteger(1_000_000),
        maxMerges: boundedPositiveInteger(100_000),
        maxMergeExpansionCells: boundedPositiveInteger(1_000_000),
        maxSelectorCells: boundedPositiveInteger(1_000_000),
        maxOutputRows: boundedPositiveInteger(1_000_000),
      })
      .strict(),
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
  "recipe",
  "execute",
  "export",
  "limit",
]);
const successSchema = z
  .object({
    protocolVersion: z.literal("tidy.worker/v1"),
    requestId: z.string().min(1).max(MAX_REQUEST_ID_LENGTH),
    ok: z.literal(true),
    outputs: z.array(outputDescriptorSchema).max(MAX_OUTPUT_DESCRIPTORS),
    warnings: z.array(warningDescriptorSchema).max(MAX_WARNING_DESCRIPTORS),
  })
  .strict();
const errorSchema = z
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
  .strict();
const workerResultSchema = z.union([successSchema, errorSchema]);

export type WorkerRequest = z.infer<typeof requestSchema>;
export type OutputDescriptor = z.infer<typeof outputDescriptorSchema>;
export type WorkerResult = z.infer<typeof workerResultSchema>;

type ProducedFile = {
  name: string;
  relativePath: string;
  render: () => Buffer;
};
type RootIdentity = {
  requestedPath: string;
  canonicalPath: string;
  device: bigint;
  inode: bigint;
};
type RootContext = { input: RootIdentity; output: RootIdentity };

export async function runWorker(
  rawRequest: unknown,
  inputRoot: string,
  outputRoot: string,
): Promise<WorkerResult> {
  return normalizeWorkerResult(
    await runWorkerUnchecked(rawRequest, inputRoot, outputRoot),
  );
}

async function runWorkerUnchecked(
  rawRequest: unknown,
  inputRoot: string,
  outputRoot: string,
): Promise<WorkerResult> {
  const requestId = getRequestId(rawRequest);
  const parsedRequest = requestSchema.safeParse(rawRequest);
  if (!parsedRequest.success)
    return failure(
      requestId,
      "INVALID_REQUEST",
      "protocol",
      "Request does not match tidy.worker/v1.",
      stableIssues(parsedRequest.error),
    );
  const request = parsedRequest.data;

  try {
    const roots = await assertIndependentRoots(inputRoot, outputRoot);
    await prepareOutputRoot(outputRoot);
    if (
      request.operation === "health" ||
      request.operation === "capabilities"
    ) {
      if (
        request.inputs.length !== 0 ||
        Object.keys(request.parameters).length !== 0
      )
        return failure(
          request.requestId,
          "INVALID_OPERATION_INPUTS",
          "protocol",
          `${request.operation} accepts no inputs or parameters.`,
        );
      const value =
        request.operation === "health"
          ? { status: "ok", protocolVersion: "tidy.worker/v1" }
          : {
              operations: ["health", "capabilities", "execute-recipe-v01"],
              evidenceProfiles: ["m1-simple-v1", "m2-deterministic-parity-v1"],
              summary: {
                supported: true,
                contract: "tidy-sheet-summary-v1",
                options: {
                  checked: true,
                  allOtherOptions: "historical-defaults",
                },
                historicalReferenceDigest:
                  "sha256:0d0dca23d4f08204cbf02d6cc841fbd5ba15df32aeab92da77a0f91f5ff49c70",
              },
              networkRequired: false,
            };
      return await publish(request, roots, [
        {
          name: `${request.operation}.json`,
          relativePath: `${request.operation}.json`,
          render: () => jsonBytes(value),
        },
      ]);
    }

    if (!request.parameters.evidenceProfile)
      return failure(
        request.requestId,
        "INVALID_PARAMETERS",
        "protocol",
        "execute-recipe-v01 requires evidenceProfile.",
      );
    const inputByName = new Map(
      request.inputs.map((input) => [input.name, input]),
    );
    if (
      request.inputs.length !== 2 ||
      inputByName.size !== 2 ||
      !inputByName.has("workbook") ||
      !inputByName.has("recipe")
    )
      return failure(
        request.requestId,
        "INVALID_INPUT_MANIFEST",
        "input",
        "execute-recipe-v01 requires exactly workbook and recipe inputs.",
      );

    const declaredInputBytes = request.inputs.reduce(
      (total, input) => total + input.byteLength,
      0,
    );
    if (declaredInputBytes > request.limits.maxInputBytes)
      throw new ProtocolError(
        "INPUT_LIMIT_EXCEEDED",
        "limit",
        `Declared inputs require ${declaredInputBytes} bytes, exceeding limit ${request.limits.maxInputBytes}.`,
      );
    const workbookInput = inputByName.get("workbook")!;
    if (workbookInput.byteLength > request.limits.maxWorkbookCompressedBytes)
      throw new ProtocolError(
        "WORKBOOK_COMPRESSED_LIMIT_EXCEEDED",
        "limit",
        `Declared workbook size exceeds limit ${request.limits.maxWorkbookCompressedBytes}.`,
      );
    const workbookBytes = await readVerifiedInput(inputRoot, workbookInput);
    await preflightXlsxZip(workbookBytes, request.limits);
    const recipeBytes = await readVerifiedInput(
      inputRoot,
      inputByName.get("recipe")!,
    );
    let recipeJson: unknown;
    try {
      recipeJson = JSON.parse(recipeBytes.toString("utf8"));
    } catch {
      return failure(
        request.requestId,
        "MALFORMED_RECIPE_JSON",
        "recipe",
        "Recipe input is not valid JSON.",
      );
    }
    const validated = validateRecipe(recipeJson);
    if (!validated.success)
      return failure(
        request.requestId,
        "INVALID_RECIPE",
        "recipe",
        "RecipeV01 validation failed.",
        validated.errors,
      );

    enforceRecipeNames(validated.data);
    enforceOutputDescriptorLimit(
      validated.data,
      request.limits.maxOutputFiles,
      request.parameters.includeSummary === true,
    );
    enforceRecipeSelectorLimit(validated.data, request.limits.maxSelectorCells);
    const parsedWorkbook = await parseWorkbook(workbookBytes);
    if (!parsedWorkbook.ok)
      return failure(
        request.requestId,
        "INVALID_WORKBOOK",
        "parse",
        "Workbook parsing failed.",
        parsedWorkbook.errors,
      );
    enforceWorkbookLimits(parsedWorkbook.workbook, request.limits);
    const sheet = findRecipeSheet(
      parsedWorkbook.workbook,
      validated.data.sheet,
    );
    if (!sheet)
      return failure(
        request.requestId,
        "SHEET_NOT_FOUND",
        "execute",
        `Recipe sheet ${JSON.stringify(validated.data.sheet)} was not found.`,
      );

    const selectors = resolveRecipeSelectors(validated.data, sheet);
    enforcePredictedExecutionLimits(validated.data, selectors, request);
    const geometry = buildGeometryEvidence(validated.data, selectors);
    const execution = executeRecipe(validated.data, sheet);
    const files: ProducedFile[] = [
      {
        name: "parsed-workbook.json",
        relativePath: "parsed-workbook.json",
        render: () => jsonBytes(parsedWorkbook.workbook),
      },
      {
        name: "normalized-recipe.json",
        relativePath: "normalized-recipe.json",
        render: () => jsonBytes(validated.data),
      },
      {
        name: "selectors.json",
        relativePath: "selectors.json",
        render: () => jsonBytes(selectors),
      },
      {
        name: "geometry.json",
        relativePath: "geometry.json",
        render: () => jsonBytes(geometry),
      },
      {
        name: "execution.json",
        relativePath: "execution.json",
        render: () => jsonBytes(execution),
      },
      ...(request.parameters.includeSummary === true
        ? [
            {
              name: "sheet-summary.json",
              relativePath: "sheet-summary.json",
              render: () =>
                jsonBytes(buildSheetSummary(sheet, { checked: true })),
            },
          ]
        : []),
    ];
    execution.tables.forEach((table, index) => {
      const relativePath = csvOutputPath(table.table);
      files.push({
        name: relativePath,
        relativePath,
        render: () =>
          Buffer.from(
            rowsToCsv(table.rows, {
              valueColumn: validated.data.tables[index].values.name,
            }),
            "utf8",
          ),
      });
    });
    return await publish(
      request,
      roots,
      files,
      execution.warnings.map(({ code, message }) => ({ code, message })),
    );
  } catch (error) {
    const protocolError =
      error instanceof ProtocolError
        ? error
        : error instanceof LimitViolation
          ? new ProtocolError(error.code, "limit", error.message)
          : new ProtocolError(
              "WORKER_FAILURE",
              "execute",
              error instanceof Error ? error.message : "Worker failed.",
            );
    return failure(
      request.requestId,
      protocolError.code,
      protocolError.stage,
      protocolError.message,
    );
  }
}

function enforceRecipeNames(recipe: RecipeV01): void {
  const names = recipe.tables.flatMap((table) => [
    table.name,
    table.values.name,
    ...table.headers.map((header) => header.name),
  ]);
  if (names.some((name) => name.length > MAX_NAME_LENGTH))
    throw new ProtocolError(
      "NAME_LIMIT_EXCEEDED",
      "limit",
      `Recipe names may not exceed ${MAX_NAME_LENGTH} characters.`,
    );
  if (names.some((name) => !isWellFormedUnicode(name)))
    throw new ProtocolError(
      "INVALID_NAME_ENCODING",
      "recipe",
      "Recipe names must contain well-formed Unicode scalar values.",
    );
  for (const table of recipe.tables) csvOutputPath(table.name);
}

function enforceOutputDescriptorLimit(
  recipe: RecipeV01,
  maxOutputFiles: number,
  includeSummary: boolean,
): void {
  if (recipe.tables.length + 5 + (includeSummary ? 1 : 0) > maxOutputFiles)
    throw new ProtocolError(
      "OUTPUT_DESCRIPTOR_LIMIT_EXCEEDED",
      "limit",
      `Execution would declare more than ${maxOutputFiles} outputs.`,
    );
}

function enforcePredictedExecutionLimits(
  recipe: RecipeV01,
  selectors: ResolvedRecipeSelectors,
  request: WorkerRequest,
): void {
  let predictedRows = 0;
  let warningUpperBound = selectors.warnings.length;
  for (const table of selectors.tables) {
    const values = table.values.addresses.length;
    predictedRows += values;
    // Conservative bound: empty selection, overlap, two attachment warnings
    // per value/header, and one unused warning per selected header cell.
    warningUpperBound += (values === 0 ? 1 : 0) + values;
    for (const header of table.headers) {
      warningUpperBound +=
        (header.result.addresses.length === 0 ? 1 : 0) +
        2 * values +
        header.result.addresses.length;
    }
  }
  if (predictedRows > request.limits.maxOutputRows)
    throw new ProtocolError(
      "OUTPUT_ROW_LIMIT_EXCEEDED",
      "limit",
      `Resolved selectors could produce ${predictedRows} rows, exceeding limit ${request.limits.maxOutputRows}.`,
    );
  if (warningUpperBound > request.limits.maxWarnings)
    throw new ProtocolError(
      "WARNING_LIMIT_EXCEEDED",
      "limit",
      `Execution could produce more than ${request.limits.maxWarnings} warnings.`,
    );
}

function csvOutputPath(tableName: string): string {
  if (!isWellFormedUnicode(tableName))
    throw new ProtocolError(
      "INVALID_NAME_ENCODING",
      "recipe",
      "Table names must contain well-formed Unicode scalar values.",
    );
  const fileName = `${encodeURIComponent(tableName)}.csv`;
  const relativePath = `tables/${fileName}`;
  if (
    Buffer.byteLength(fileName, "utf8") > 255 ||
    Buffer.byteLength(relativePath, "utf8") > MAX_PATH_LENGTH
  )
    throw new ProtocolError(
      "OUTPUT_PATH_LIMIT_EXCEEDED",
      "limit",
      "Encoded table output path exceeds the portable filesystem limit.",
    );
  return relativePath;
}

function isWellFormedUnicode(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) return false;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}

async function publish(
  request: WorkerRequest,
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

async function readVerifiedInput(
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

async function assertIndependentRoots(
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

async function prepareOutputRoot(root: string): Promise<void> {
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

function jsonBytes(value: unknown): Buffer {
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
function failure(
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

class ProtocolError extends Error {
  constructor(
    readonly code: string,
    readonly stage:
      | "protocol"
      | "input"
      | "parse"
      | "recipe"
      | "execute"
      | "export"
      | "limit",
    message: string,
  ) {
    super(message);
  }
}
