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
import {
  TIDYCELL_DIGEST_RECORD_ALGORITHM,
  TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST,
  tidycellCanonicalJson,
  tidycellDigestRecord,
} from "../../domain-worker/src/migration/historicalDigestRecord.js";
import { validateRecipe } from "../../domain-worker/src/recipe/schema.js";

const PROTOCOL_VERSION = "tidy.migration-worker/v1" as const;
const MAX_REQUEST_ID_LENGTH = 128;
const MAX_NAME_LENGTH = 64;
const MAX_PATH_LENGTH = 4_096;
const MAX_MESSAGE_LENGTH = 1_024;
const MAX_INPUT_BYTES = 8 * 1024 * 1024;
const MAX_OUTPUT_BYTES = 8 * 1024 * 1024;
const MAX_JSON_DEPTH = 128;
const MAX_JSON_NODES = 1_000_000;
const MAX_RECORDS = 100_000;
export const MAX_MIGRATION_RESPONSE_ENVELOPE_BYTES = 1_000_000;

const digestSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const inputSchema = z
  .object({
    name: z
      .string()
      .min(1)
      .max(MAX_NAME_LENGTH)
      .regex(/^[A-Za-z0-9._-]+$/),
    relativePath: z.string().min(1).max(512),
    contentDigest: digestSchema,
    byteLength: z.number().int().nonnegative().max(MAX_INPUT_BYTES),
  })
  .strict();
const sourceBindingSchema = z
  .object({
    sourceSnapshotDigest: digestSchema,
    sourceItemDigest: digestSchema,
    importRecordId: digestSchema,
    relativePath: z.string().min(1).max(MAX_PATH_LENGTH),
  })
  .strict();
const parametersSchema = z
  .object({
    source: sourceBindingSchema.optional(),
    declaredRecipeDigest: digestSchema.optional(),
  })
  .strict();
const limitsSchema = z
  .object({
    maxInputBytes: z.number().int().positive().max(MAX_INPUT_BYTES),
    maxOutputBytes: z.number().int().positive().max(MAX_OUTPUT_BYTES),
    maxJsonDepth: z.number().int().positive().max(MAX_JSON_DEPTH),
    maxJsonNodes: z.number().int().positive().max(MAX_JSON_NODES),
    maxRecords: z.number().int().positive().max(MAX_RECORDS),
  })
  .strict();
const requestSchema = z
  .object({
    protocolVersion: z.literal(PROTOCOL_VERSION),
    requestId: z.string().min(1).max(MAX_REQUEST_ID_LENGTH),
    operation: z.enum([
      "health",
      "capabilities",
      "digest-legacy-approval-registry-v1",
      "parse-recipe-v01",
      "profile-generation-evidence-v1",
    ]),
    inputs: z.array(inputSchema).max(1),
    parameters: parametersSchema,
    limits: limitsSchema,
  })
  .strict();

const outputDescriptorSchema = z
  .object({
    name: z.string().min(1).max(MAX_NAME_LENGTH),
    relativePath: z.string().min(1).max(512),
    contentDigest: digestSchema,
    byteLength: z.number().int().nonnegative().max(MAX_OUTPUT_BYTES),
  })
  .strict();
const stageSchema = z.enum([
  "protocol",
  "input",
  "parse",
  "recipe",
  "limit",
  "output",
]);
const successSchema = z
  .object({
    protocolVersion: z.literal(PROTOCOL_VERSION),
    requestId: z.string().min(1).max(MAX_REQUEST_ID_LENGTH),
    ok: z.literal(true),
    outputs: z.array(outputDescriptorSchema).max(4),
    warnings: z.array(z.never()).max(0),
  })
  .strict();
const errorSchema = z
  .object({
    protocolVersion: z.literal(PROTOCOL_VERSION),
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
const resultSchema = z.union([successSchema, errorSchema]);

export type MigrationWorkerRequest = z.infer<typeof requestSchema>;
export type MigrationWorkerResult = z.infer<typeof resultSchema>;
type MigrationStage = z.infer<typeof stageSchema>;
type InputDescriptor = z.infer<typeof inputSchema>;
type RootIdentity = {
  requestedPath: string;
  canonicalPath: string;
  device: bigint;
  inode: bigint;
};
type RootContext = { input: RootIdentity; output: RootIdentity };
type ProducedFile = { name: string; relativePath: string; bytes: Buffer };

export async function runMigrationWorker(
  rawRequest: unknown,
  inputRoot: string,
  outputRoot: string,
): Promise<MigrationWorkerResult> {
  return normalizeMigrationWorkerResult(
    await runMigrationWorkerUnchecked(rawRequest, inputRoot, outputRoot),
  );
}

async function runMigrationWorkerUnchecked(
  rawRequest: unknown,
  inputRoot: string,
  outputRoot: string,
): Promise<MigrationWorkerResult> {
  const requestId = getRequestId(rawRequest);
  const parsed = requestSchema.safeParse(rawRequest);
  if (!parsed.success)
    return failure(
      requestId,
      "INVALID_REQUEST",
      "protocol",
      `Request does not match ${PROTOCOL_VERSION}.`,
      stableIssues(parsed.error),
    );
  const request = parsed.data;

  try {
    const roots = await assertIndependentRoots(inputRoot, outputRoot);
    await prepareOutputRoot(outputRoot);
    if (
      request.operation === "health" ||
      request.operation === "capabilities"
    ) {
      requireNoOperationInputs(request);
      const value =
        request.operation === "health"
          ? { status: "ok", protocolVersion: PROTOCOL_VERSION }
          : {
              protocolVersion: PROTOCOL_VERSION,
              operations: [
                "health",
                "capabilities",
                "digest-legacy-approval-registry-v1",
                "parse-recipe-v01",
                "profile-generation-evidence-v1",
              ],
              historicalDigest: {
                algorithm: TIDYCELL_DIGEST_RECORD_ALGORITHM,
                sourceDigest: TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST,
              },
              networkRequired: false,
              modelExecutionSupported: false,
            };
      return await publish(request, roots, [
        {
          name: request.operation,
          relativePath: `${request.operation}.json`,
          bytes: jsonBytes(value),
        },
      ]);
    }

    const source = request.parameters.source;
    if (!source)
      throw new MigrationProtocolError(
        "MISSING_SOURCE_BINDING",
        "protocol",
        "Migration interpretation requires an exact source binding.",
      );
    assertPortableRelativePath(source.relativePath, "input");
    const input = requireSingleInput(request);
    if (input.byteLength > request.limits.maxInputBytes)
      throw new MigrationProtocolError(
        "INPUT_LIMIT_EXCEEDED",
        "limit",
        `Input exceeds the declared ${request.limits.maxInputBytes}-byte limit.`,
      );
    const bytes = await readVerifiedInput(roots.input.requestedPath, input);
    const value = parseBoundedJson(bytes, request);

    if (request.operation === "digest-legacy-approval-registry-v1") {
      if (request.parameters.declaredRecipeDigest !== undefined)
        throw new MigrationProtocolError(
          "INVALID_OPERATION_PARAMETERS",
          "protocol",
          "Approval digesting does not accept declaredRecipeDigest.",
        );
      const rows = validateApprovalRegistry(value, request.limits.maxRecords);
      const artifact = {
        schemaVersion: "tidy.migration-approval-row-digests/v1",
        source: {
          ...source,
          sourceContentDigest: input.contentDigest,
          byteLength: input.byteLength,
        },
        algorithm: TIDYCELL_DIGEST_RECORD_ALGORITHM,
        algorithmSourceDigest: TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST,
        recordCount: rows.length,
        records: rows.map((row, index) => ({
          index,
          sourceRecordDigest: tidycellDigestRecord(row),
        })),
      };
      return await publish(request, roots, [
        {
          name: "approval-row-digests",
          relativePath: "approval-row-digests.json",
          bytes: jsonBytes(artifact),
        },
      ]);
    }

    if (request.operation === "profile-generation-evidence-v1") {
      if (request.parameters.declaredRecipeDigest !== undefined)
        throw new MigrationProtocolError(
          "INVALID_OPERATION_PARAMETERS",
          "protocol",
          "Generation evidence profiling does not accept declaredRecipeDigest.",
        );
      const profile = profileGenerationEvidence(
        value,
        request.limits.maxRecords,
      );
      const artifact = {
        schemaVersion: "tidy.migration-generation-evidence-profile/v1",
        source: {
          ...source,
          sourceContentDigest: input.contentDigest,
          byteLength: input.byteLength,
        },
        historicalDigestAlgorithm: TIDYCELL_DIGEST_RECORD_ALGORITHM,
        historicalDigestSourceDigest: TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST,
        structuralValueDigest: tidycellDigestRecord(value),
        ...profile,
        rawEvidenceRestricted: profile.restrictedElements.length > 0,
        providerDispatchAuthorized: false,
        retryAuthorized: false,
        approvalAuthorityCreated: false,
        activationAuthorized: false,
        trainingEligible: false,
      };
      return await publish(request, roots, [
        {
          name: "generation-evidence-profile",
          relativePath: "generation-evidence-profile.json",
          bytes: jsonBytes(artifact),
        },
      ]);
    }

    const recipe = validateRecipe(value);
    if (!recipe.success)
      throw new MigrationProtocolError(
        "INVALID_RECIPE",
        "recipe",
        "Source bytes do not contain one valid RecipeV01 document.",
        recipe.errors,
      );
    const recipeDigest = tidycellDigestRecord(recipe.data);
    const declared = request.parameters.declaredRecipeDigest ?? null;
    const artifact = {
      schemaVersion: "tidy.migration-recipe-revision/v1",
      source: {
        ...source,
        sourceContentDigest: input.contentDigest,
        byteLength: input.byteLength,
      },
      recipeSchemaVersion: "0.1",
      historicalDigestAlgorithm: TIDYCELL_DIGEST_RECORD_ALGORITHM,
      historicalDigestSourceDigest: TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST,
      historicalRecipeDigest: recipeDigest,
      declaredRecipeDigest: declared,
      digestMatches: declared === null ? null : declared === recipeDigest,
      sheetName: recipe.data.sheet,
      tableCount: recipe.data.tables.length,
      lifecycleState: "schema_valid",
      active: false,
      trainingEligible: false,
      normalizedRecipe: recipe.data,
    };
    return await publish(request, roots, [
      {
        name: "recipe-revision",
        relativePath: "recipe-revision.json",
        bytes: jsonBytes(artifact),
      },
    ]);
  } catch (error) {
    if (error instanceof MigrationProtocolError)
      return failure(
        request.requestId,
        error.code,
        error.stage,
        error.message,
        error.details,
      );
    return failure(
      request.requestId,
      "MIGRATION_WORKER_FAILURE",
      "output",
      messageOf(error),
    );
  }
}

function requireNoOperationInputs(request: MigrationWorkerRequest): void {
  if (
    request.inputs.length !== 0 ||
    request.parameters.source !== undefined ||
    request.parameters.declaredRecipeDigest !== undefined
  )
    throw new MigrationProtocolError(
      "INVALID_OPERATION_INPUTS",
      "protocol",
      `${request.operation} accepts no inputs or parameters.`,
    );
}

function requireSingleInput(request: MigrationWorkerRequest): InputDescriptor {
  if (request.inputs.length !== 1)
    throw new MigrationProtocolError(
      "INVALID_OPERATION_INPUTS",
      "protocol",
      `${request.operation} requires exactly one input.`,
    );
  const input = request.inputs[0];
  const expectedName =
    request.operation === "parse-recipe-v01"
      ? "recipe"
      : request.operation === "profile-generation-evidence-v1"
        ? "generation"
        : "registry";
  if (!input || input.name !== expectedName)
    throw new MigrationProtocolError(
      "INVALID_OPERATION_INPUTS",
      "protocol",
      `${request.operation} requires input name ${expectedName}.`,
    );
  return input;
}

function parseBoundedJson(
  bytes: Buffer,
  request: MigrationWorkerRequest,
): unknown {
  let value: unknown;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    value = JSON.parse(text);
  } catch {
    throw new MigrationProtocolError(
      "MALFORMED_JSON",
      "parse",
      "Input is not valid UTF-8 JSON.",
    );
  }
  enforceJsonLimits(
    value,
    request.limits.maxJsonDepth,
    request.limits.maxJsonNodes,
  );
  return value;
}

function enforceJsonLimits(
  root: unknown,
  maxDepth: number,
  maxNodes: number,
): void {
  const pending: Array<{ value: unknown; depth: number }> = [
    { value: root, depth: 1 },
  ];
  let nodes = 0;
  while (pending.length > 0) {
    const current = pending.pop();
    if (!current) break;
    nodes += 1;
    if (nodes > maxNodes)
      throw new MigrationProtocolError(
        "JSON_NODE_LIMIT_EXCEEDED",
        "limit",
        `JSON exceeds the declared ${maxNodes}-node limit.`,
      );
    if (current.depth > maxDepth)
      throw new MigrationProtocolError(
        "JSON_DEPTH_LIMIT_EXCEEDED",
        "limit",
        `JSON exceeds the declared depth limit ${maxDepth}.`,
      );
    if (Array.isArray(current.value)) {
      for (let index = current.value.length - 1; index >= 0; index -= 1)
        pending.push({ value: current.value[index], depth: current.depth + 1 });
    } else if (isRecord(current.value)) {
      const values = Object.values(current.value);
      for (let index = values.length - 1; index >= 0; index -= 1)
        pending.push({ value: values[index], depth: current.depth + 1 });
    }
  }
}

function validateApprovalRegistry(
  value: unknown,
  maxRecords: number,
): Array<Record<string, unknown>> {
  if (
    !isRecord(value) ||
    Object.keys(value).sort().join(",") !== "approvals,version" ||
    value.version !== 1 ||
    !Array.isArray(value.approvals)
  )
    throw new MigrationProtocolError(
      "INVALID_APPROVAL_REGISTRY",
      "parse",
      "Approval registry must be the exact version-1 {version, approvals} object.",
    );
  if (value.approvals.length > maxRecords)
    throw new MigrationProtocolError(
      "RECORD_LIMIT_EXCEEDED",
      "limit",
      `Approval registry exceeds the declared ${maxRecords}-record limit.`,
    );
  return value.approvals.map((entry, index) => {
    if (!isRecord(entry))
      throw new MigrationProtocolError(
        "INVALID_APPROVAL_ROW",
        "parse",
        `Approval row ${index} must be an object.`,
      );
    for (const field of ["assetId", "sheetName"] as const) {
      const fieldValue = entry[field];
      if (
        typeof fieldValue !== "string" ||
        fieldValue.length === 0 ||
        fieldValue.length > MAX_PATH_LENGTH
      )
        throw new MigrationProtocolError(
          "INVALID_APPROVAL_ROW",
          "parse",
          `Approval row ${index} has invalid ${field}.`,
        );
    }
    for (const field of ["approvedAt", "approvedBy"] as const) {
      if (field in entry && typeof entry[field] !== "string")
        throw new MigrationProtocolError(
          "INVALID_APPROVAL_ROW",
          "parse",
          `Approval row ${index} has non-string ${field}.`,
        );
    }
    if (typeof entry.approvedAt === "string" && entry.approvedAt.length > 128)
      throw new MigrationProtocolError(
        "INVALID_APPROVAL_ROW",
        "parse",
        `Approval row ${index} has oversized approvedAt.`,
      );
    if (typeof entry.approvedBy === "string" && entry.approvedBy.length > 256)
      throw new MigrationProtocolError(
        "INVALID_APPROVAL_ROW",
        "parse",
        `Approval row ${index} has oversized approvedBy.`,
      );
    for (const field of ["recipeDigest", "originalRecipeDigest"] as const) {
      if (field in entry && !digestSchema.safeParse(entry[field]).success)
        throw new MigrationProtocolError(
          "INVALID_APPROVAL_ROW",
          "parse",
          `Approval row ${index} has invalid ${field}.`,
        );
    }
    return entry;
  });
}

const PROMPT_EVIDENCE_KEYS = new Set([
  "input",
  "messages",
  "prompt",
  "rawinput",
  "rawprompt",
  "requestmessages",
  "systemprompt",
  "userprompt",
]);
const RESPONSE_EVIDENCE_KEYS = new Set([
  "completion",
  "content",
  "output",
  "outputtext",
  "providerresponse",
  "rawcompletion",
  "rawresponse",
  "response",
]);
const SAFE_GENERATION_METADATA_KEYS = new Set([
  "completedat",
  "completiontokens",
  "cost",
  "costusd",
  "durationms",
  "finishreason",
  "latencyms",
  "model",
  "prompttokens",
  "provider",
  "reasoningeffort",
  "startedat",
  "status",
  "totaltokens",
]);

function profileGenerationEvidence(
  value: unknown,
  maxRecords: number,
): {
  interpretationStatus: "parsed-recognized" | "parsed-unrecognized";
  restrictedElements: Array<Record<string, unknown>>;
  recipeCandidates: Array<Record<string, unknown>>;
  safeMetadata: Array<Record<string, unknown>>;
  totalVisitedNodes: number;
  unclassifiedLeafCount: number;
} {
  const restrictedElements: Array<Record<string, unknown>> = [];
  const recipeCandidates: Array<Record<string, unknown>> = [];
  const safeMetadata: Array<Record<string, unknown>> = [];
  let totalVisitedNodes = 0;
  let unclassifiedLeafCount = 0;
  const append = (
    target: Array<Record<string, unknown>>,
    entry: Record<string, unknown>,
  ) => {
    if (
      restrictedElements.length +
        recipeCandidates.length +
        safeMetadata.length >=
      maxRecords
    )
      throw new MigrationProtocolError(
        "RECORD_LIMIT_EXCEEDED",
        "limit",
        `Generation evidence profile exceeds the declared ${maxRecords}-record limit.`,
      );
    target.push(entry);
  };
  const visit = (
    current: unknown,
    pointer: string,
    key: string | null,
  ): void => {
    totalVisitedNodes += 1;
    if (pointer.length > MAX_PATH_LENGTH)
      throw new MigrationProtocolError(
        "JSON_POINTER_LIMIT_EXCEEDED",
        "limit",
        "Generation evidence contains an oversized JSON pointer.",
      );
    if (
      isRecord(current) &&
      typeof current.role === "string" &&
      "content" in current &&
      ["assistant", "developer", "system", "user"].includes(
        current.role.toLowerCase(),
      )
    ) {
      const content = current.content;
      const canonical = tidycellCanonicalJson(content);
      append(restrictedElements, {
        pointer: `${pointer}/content`,
        kind:
          current.role.toLowerCase() === "assistant"
            ? "restricted-provider-response"
            : "restricted-prompt",
        valueType: jsonValueType(content),
        valueDigest: tidycellDigestRecord(content),
        canonicalByteLength: Buffer.byteLength(canonical, "utf8"),
      });
      return;
    }
    const normalizedKey =
      key?.toLowerCase().replaceAll(/[^a-z0-9]/g, "") ?? null;
    if (
      normalizedKey &&
      (PROMPT_EVIDENCE_KEYS.has(normalizedKey) ||
        RESPONSE_EVIDENCE_KEYS.has(normalizedKey))
    ) {
      const canonical = tidycellCanonicalJson(current);
      append(restrictedElements, {
        pointer,
        kind: PROMPT_EVIDENCE_KEYS.has(normalizedKey)
          ? "restricted-prompt"
          : "restricted-provider-response",
        valueType: jsonValueType(current),
        valueDigest: tidycellDigestRecord(current),
        canonicalByteLength: Buffer.byteLength(canonical, "utf8"),
      });
      return;
    }
    if (
      isRecord(current) &&
      current.version === "0.1" &&
      typeof current.sheet === "string" &&
      Array.isArray(current.tables)
    ) {
      const parsedRecipe = validateRecipe(current);
      if (parsedRecipe.success) {
        append(recipeCandidates, {
          pointer,
          historicalRecipeDigest: tidycellDigestRecord(parsedRecipe.data),
          sheetName: parsedRecipe.data.sheet,
          tableCount: parsedRecipe.data.tables.length,
        });
        return;
      }
    }
    if (normalizedKey && SAFE_GENERATION_METADATA_KEYS.has(normalizedKey)) {
      if (
        current === null ||
        typeof current === "boolean" ||
        typeof current === "number" ||
        (typeof current === "string" && current.length <= 512)
      ) {
        append(safeMetadata, { pointer, key, value: current });
      } else {
        const canonical = tidycellCanonicalJson(current);
        append(restrictedElements, {
          pointer,
          kind: "restricted-oversized-metadata",
          valueType: jsonValueType(current),
          valueDigest: tidycellDigestRecord(current),
          canonicalByteLength: Buffer.byteLength(canonical, "utf8"),
        });
      }
      return;
    }
    if (Array.isArray(current)) {
      current.forEach((entry, index) =>
        visit(entry, `${pointer}/${index}`, String(index)),
      );
      return;
    }
    if (isRecord(current)) {
      for (const childKey of Object.keys(current).sort())
        visit(
          current[childKey],
          `${pointer}/${escapeJsonPointer(childKey)}`,
          childKey,
        );
      return;
    }
    unclassifiedLeafCount += 1;
  };
  visit(value, "", null);
  const recognized =
    restrictedElements.length + recipeCandidates.length + safeMetadata.length;
  return {
    interpretationStatus:
      recognized > 0 ? "parsed-recognized" : "parsed-unrecognized",
    restrictedElements,
    recipeCandidates,
    safeMetadata,
    totalVisitedNodes,
    unclassifiedLeafCount,
  };
}

function escapeJsonPointer(value: string): string {
  return value.replaceAll("~", "~0").replaceAll("/", "~1");
}

function jsonValueType(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

async function publish(
  request: MigrationWorkerRequest,
  roots: RootContext,
  files: ProducedFile[],
): Promise<MigrationWorkerResult> {
  let total = 0;
  const parent = path.dirname(roots.output.requestedPath);
  const stagingRoot = await mkdtemp(
    path.join(parent, ".tidy-migration-worker-stage-"),
  );
  let published = false;
  try {
    const outputs: Array<z.infer<typeof outputDescriptorSchema>> = [];
    for (const file of files) {
      assertPortableRelativePath(file.relativePath, "output");
      total += file.bytes.byteLength;
      if (total > request.limits.maxOutputBytes)
        throw new MigrationProtocolError(
          "OUTPUT_LIMIT_EXCEEDED",
          "limit",
          `Outputs exceed the declared ${request.limits.maxOutputBytes}-byte limit.`,
        );
      const destination = path.join(stagingRoot, file.relativePath);
      await mkdir(path.dirname(destination), { recursive: true, mode: 0o700 });
      await writeFile(destination, file.bytes, { flag: "wx", mode: 0o600 });
      outputs.push({
        name: file.name,
        relativePath: file.relativePath,
        contentDigest: sha256(file.bytes),
        byteLength: file.bytes.byteLength,
      });
    }
    const actual = await listFiles(stagingRoot);
    const declared = outputs.map((entry) => entry.relativePath).sort();
    if (JSON.stringify(actual) !== JSON.stringify(declared))
      throw new MigrationProtocolError(
        "UNDECLARED_OUTPUT",
        "output",
        "Private staging contains undeclared output files.",
      );
    const result: MigrationWorkerResult = {
      protocolVersion: PROTOCOL_VERSION,
      requestId: request.requestId,
      ok: true,
      outputs,
      warnings: [],
    };
    assertSerializableResult(result);
    await assertRootUnchanged(roots.input);
    await assertRootUnchanged(roots.output);
    await assertRootsDoNotOverlap(
      roots.input.canonicalPath,
      roots.output.canonicalPath,
    );
    if ((await readdir(roots.output.requestedPath)).length !== 0)
      throw new MigrationProtocolError(
        "OUTPUT_ROOT_CHANGED",
        "output",
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
    return result;
  } finally {
    if (!published) await rm(stagingRoot, { recursive: true, force: true });
  }
}

async function readVerifiedInput(
  root: string,
  input: InputDescriptor,
): Promise<Buffer> {
  assertPortableRelativePath(input.relativePath, "input");
  const target = path.join(root, input.relativePath);
  await assertNoSymlinks(root, input.relativePath);
  const before = await lstat(target, { bigint: true }).catch(() => undefined);
  if (!before?.isFile())
    throw new MigrationProtocolError(
      "INPUT_NOT_REGULAR_FILE",
      "input",
      `Input ${input.name} is not a regular file.`,
    );
  if (before.size !== BigInt(input.byteLength))
    throw new MigrationProtocolError(
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
    if (
      !opened.isFile() ||
      opened.dev !== before.dev ||
      opened.ino !== before.ino
    )
      throw new MigrationProtocolError(
        "INPUT_CHANGED",
        "input",
        `Input ${input.name} changed while opening.`,
      );
    bytes = await handle.readFile();
    const after = await handle.stat({ bigint: true });
    if (
      after.dev !== opened.dev ||
      after.ino !== opened.ino ||
      after.size !== opened.size ||
      after.mtimeNs !== opened.mtimeNs ||
      after.ctimeNs !== opened.ctimeNs
    )
      throw new MigrationProtocolError(
        "INPUT_CHANGED",
        "input",
        `Input ${input.name} changed while reading.`,
      );
  } finally {
    await handle.close();
  }
  if (bytes.byteLength !== input.byteLength)
    throw new MigrationProtocolError(
      "BYTE_LENGTH_MISMATCH",
      "input",
      `Byte length mismatch for input ${input.name}.`,
    );
  if (sha256(bytes) !== input.contentDigest)
    throw new MigrationProtocolError(
      "DIGEST_MISMATCH",
      "input",
      `Digest mismatch for input ${input.name}.`,
    );
  return bytes;
}

function assertPortableRelativePath(
  relativePath: string,
  stage: "input" | "output",
): void {
  if (
    relativePath.includes("\0") ||
    relativePath.includes("\\") ||
    path.posix.isAbsolute(relativePath)
  )
    throw new MigrationProtocolError(
      "UNSAFE_PATH",
      stage,
      "Paths must be portable relative paths.",
    );
  const parts = relativePath.split("/");
  if (
    parts.length === 0 ||
    parts.some((part) => part === "" || part === "." || part === "..") ||
    path.posix.normalize(relativePath) !== relativePath
  )
    throw new MigrationProtocolError(
      "UNSAFE_PATH",
      stage,
      "Path escapes or is not normalized.",
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
      throw new MigrationProtocolError(
        "SYMLINK_PATH",
        "input",
        "Input paths may not traverse symlinks.",
      );
  }
}

async function inspectRoot(root: string, label: "input" | "output") {
  if (root.length === 0 || root.length > MAX_PATH_LENGTH)
    throw new MigrationProtocolError(
      "UNSAFE_ROOT",
      label,
      `${label} root path is invalid.`,
    );
  const info = await lstat(root, { bigint: true }).catch(() => undefined);
  if (!info?.isDirectory() || info.isSymbolicLink())
    throw new MigrationProtocolError(
      "UNSAFE_ROOT",
      label,
      `${label} root must be an existing real directory.`,
    );
  return {
    requestedPath: path.resolve(root),
    canonicalPath: await realpath(root),
    device: info.dev,
    inode: info.ino,
  } satisfies RootIdentity;
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
  const nested = (relative: string) =>
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) && relative !== "..");
  if (
    nested(path.relative(input, output)) ||
    nested(path.relative(output, input))
  )
    throw new MigrationProtocolError(
      "OVERLAPPING_ROOTS",
      "input",
      "Input and output roots must not overlap.",
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
    throw new MigrationProtocolError(
      "ROOT_CHANGED",
      "output",
      "A launcher root changed during execution.",
    );
}

async function prepareOutputRoot(root: string): Promise<void> {
  if ((await readdir(root)).length !== 0)
    throw new MigrationProtocolError(
      "OUTPUT_ROOT_NOT_EMPTY",
      "output",
      "Output root must be empty.",
    );
  if (!(await stat(path.dirname(path.resolve(root)))).isDirectory())
    throw new MigrationProtocolError(
      "UNSAFE_ROOT",
      "output",
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
      throw new MigrationProtocolError(
        "UNDECLARED_OUTPUT",
        "output",
        "Output contains a symlink.",
      );
    if (entry.isDirectory()) files.push(...(await listFiles(root, relative)));
    else if (entry.isFile()) files.push(relative);
    else
      throw new MigrationProtocolError(
        "UNDECLARED_OUTPUT",
        "output",
        "Output contains a non-file entry.",
      );
  }
  return files.sort();
}

export function normalizeMigrationWorkerResult(
  raw: unknown,
): MigrationWorkerResult {
  const parsed = resultSchema.safeParse(raw);
  if (!parsed.success)
    return contractFailure(
      "INVALID_WORKER_RESULT",
      `Worker result did not match ${PROTOCOL_VERSION}.`,
    );
  try {
    if (
      Buffer.byteLength(`${JSON.stringify(parsed.data)}\n`, "utf8") >
      MAX_MIGRATION_RESPONSE_ENVELOPE_BYTES
    )
      return contractFailure(
        "RESPONSE_LIMIT_EXCEEDED",
        `Worker response exceeds ${MAX_MIGRATION_RESPONSE_ENVELOPE_BYTES} bytes.`,
      );
  } catch {
    return contractFailure(
      "INVALID_WORKER_RESULT",
      "Worker result could not be serialized.",
    );
  }
  return parsed.data;
}

export function serializeMigrationWorkerResult(raw: unknown): string {
  return `${JSON.stringify(normalizeMigrationWorkerResult(raw))}\n`;
}

function assertSerializableResult(result: MigrationWorkerResult): void {
  const normalized = normalizeMigrationWorkerResult(result);
  if (!normalized.ok)
    throw new MigrationProtocolError(
      normalized.error.code,
      normalized.error.stage,
      normalized.error.message,
      normalized.error.details,
    );
}

function failure(
  requestId: string,
  code: string,
  stage: MigrationStage,
  message: string,
  details?: unknown,
): MigrationWorkerResult {
  return {
    protocolVersion: PROTOCOL_VERSION,
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

function contractFailure(code: string, message: string): MigrationWorkerResult {
  return failure("invalid-request", code, "protocol", message);
}

function getRequestId(raw: unknown): string {
  return isRecord(raw) && typeof raw.requestId === "string"
    ? raw.requestId.slice(0, MAX_REQUEST_ID_LENGTH)
    : "invalid-request";
}

function stableIssues(error: z.ZodError): unknown {
  return error.issues.map((issue) => ({
    code: issue.code,
    path: issue.path.join("."),
    message: issue.message,
  }));
}

function jsonBytes(value: unknown): Buffer {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function sha256(bytes: Uint8Array): string {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Migration worker failed.";
}

class MigrationProtocolError extends Error {
  constructor(
    readonly code: string,
    readonly stage: MigrationStage,
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
  }
}
