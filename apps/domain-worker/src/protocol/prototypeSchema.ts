import { z } from "zod";
import {
  MAX_RESPONSE_ENVELOPE_BYTES,
  assertIndependentRoots,
  normalizeWorkerResult,
  prepareOutputRoot,
  type WorkerResult,
} from "./prototypeRuntime.js";
import { runWorker } from "./worker.js";

const MAX_OUTPUT_DESCRIPTORS = 10_000;
const MAX_WARNING_DESCRIPTORS = 10_000;
import { interpretSemanticMapV13, prepareSemanticMapV13 } from "./prototype.js";

const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const bounded = (maximum: number) => z.number().int().positive().max(maximum);
const requestSchema = z
  .object({
    protocolVersion: z.literal("tidy.worker/v1"),
    requestId: z.string().min(1).max(128),
    operation: z.enum([
      "health",
      "capabilities",
      "execute-recipe-v01",
      "prepare-semantic-map-v13",
      "interpret-semantic-map-v13",
    ]),
    inputs: z
      .array(
        z
          .object({
            name: z
              .string()
              .min(1)
              .max(200)
              .regex(/^[A-Za-z0-9._-]+$/),
            relativePath: z.string().min(1).max(512),
            contentDigest: digest,
            byteLength: z.number().int().nonnegative().max(50_000_000),
          })
          .strict(),
      )
      .max(8),
    parameters: z
      .object({
        evidenceProfile: z
          .enum(["m1-simple-v1", "m2-deterministic-parity-v1"])
          .optional(),
        includeSummary: z.boolean().optional(),
        includeCompactContext: z.boolean().optional(),
        includeRegionCatalog: z.boolean().optional(),
        csvMode: z.literal("recipe-aware").optional(),
        sheet: z.string().min(1).max(200).optional(),
        correction: z.boolean().optional(),
      })
      .strict(),
    limits: z
      .object({
        timeoutMs: bounded(300_000),
        maxInputBytes: bounded(50_000_000),
        maxOutputBytes: bounded(50_000_000),
        maxOutputFiles: bounded(MAX_OUTPUT_DESCRIPTORS),
        maxWarnings: bounded(MAX_WARNING_DESCRIPTORS),
        maxWorkbookCompressedBytes: bounded(25_000_000),
        maxZipEntries: bounded(10_000),
        maxZipEntryUncompressedBytes: bounded(50_000_000),
        maxZipTotalUncompressedBytes: bounded(200_000_000),
        maxSheets: bounded(256),
        maxCells: bounded(1_000_000),
        maxMerges: bounded(100_000),
        maxMergeExpansionCells: bounded(1_000_000),
        maxSelectorCells: bounded(1_000_000),
        maxOutputRows: bounded(1_000_000),
      })
      .strict(),
  })
  .strict();

type PrototypeWorkerRequest = z.infer<typeof requestSchema>;

export async function runPrototypeAwareWorker(
  rawRequest: unknown,
  inputRoot: string,
  outputRoot: string,
): Promise<WorkerResult> {
  const parsed = requestSchema.safeParse(rawRequest);
  if (!parsed.success || !isPrototypeOperation(parsed.data.operation))
    return await runWorker(rawRequest, inputRoot, outputRoot);

  // Reuse the canonical worker's fail-closed independent-root checks while the
  // prototype adapter owns only its distinct request schema and domain work.
  const roots = await assertIndependentRoots(inputRoot, outputRoot);
  await prepareOutputRoot(outputRoot);
  const result =
    parsed.data.operation === "prepare-semantic-map-v13"
      ? await prepareSemanticMapV13(
          parsed.data as Parameters<typeof prepareSemanticMapV13>[0],
          roots,
          inputRoot,
        )
      : await interpretSemanticMapV13(
          parsed.data as Parameters<typeof interpretSemanticMapV13>[0],
          roots,
          inputRoot,
        );
  return normalizeWorkerResult(result);
}

function isPrototypeOperation(value: string): boolean {
  return (
    value === "prepare-semantic-map-v13" ||
    value === "interpret-semantic-map-v13"
  );
}

export { MAX_RESPONSE_ENVELOPE_BYTES };
