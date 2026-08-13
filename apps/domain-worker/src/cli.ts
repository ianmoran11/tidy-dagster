#!/usr/bin/env node
import { constants as fsConstants } from "node:fs";
import { open } from "node:fs/promises";
import { serializeWorkerResult } from "./protocol/worker.js";
import type { WorkerResult } from "./protocol/prototypeRuntime.js";
import { runPrototypeAwareWorker } from "./protocol/prototypeSchema.js";

const MAX_REQUEST_ENVELOPE_BYTES = 65_536;
const MAX_ARGUMENT_LENGTH = 4_096;

async function main(): Promise<number> {
  let args: ReturnType<typeof parseArgs>;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    emit(cliFailure("INVALID_INVOCATION", messageOf(error)));
    return 2;
  }

  let raw: unknown;
  try {
    const handle = await open(
      args.request,
      fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW,
    );
    try {
      const info = await handle.stat();
      if (!info.isFile()) throw new Error("Request must be a regular file.");
      if (info.size > MAX_REQUEST_ENVELOPE_BYTES)
        throw new Error(
          `Request envelope exceeds ${MAX_REQUEST_ENVELOPE_BYTES} bytes.`,
        );
      raw = JSON.parse((await handle.readFile()).toString("utf8"));
    } finally {
      await handle.close();
    }
  } catch (error) {
    emit(cliFailure("MALFORMED_REQUEST", messageOf(error)));
    return 1;
  }

  try {
    const result = await runPrototypeAwareWorker(
      raw,
      args.inputRoot,
      args.outputRoot,
    );
    emit(result);
    return result.ok ? 0 : 1;
  } catch (error) {
    emit(cliFailure("CLI_FAILURE", messageOf(error)));
    return 2;
  }
}

function parseArgs(argv: string[]): {
  request: string;
  inputRoot: string;
  outputRoot: string;
} {
  if (argv.length !== 6) throw new Error(usage());
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith("--") || !value || value.length > MAX_ARGUMENT_LENGTH)
      throw new Error(usage());
    const key = flag.slice(2);
    if (values.has(key)) throw new Error(`Duplicate argument --${key}.`);
    values.set(key, value);
  }
  const request = values.get("request");
  const inputRoot = values.get("input-root");
  const outputRoot = values.get("output-root");
  if (!request || !inputRoot || !outputRoot || values.size !== 3)
    throw new Error(usage());
  return { request, inputRoot, outputRoot };
}

function usage(): string {
  return "Usage: tidy-domain-worker --request FILE --input-root DIR --output-root DIR";
}

function cliFailure(code: string, message: string): WorkerResult {
  return {
    protocolVersion: "tidy.worker/v1",
    requestId: "invalid-request",
    ok: false,
    error: {
      code,
      stage: "protocol",
      message: message.slice(0, 1_024),
    },
  };
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Worker CLI failed.";
}

function emit(result: WorkerResult): void {
  process.stdout.write(serializeWorkerResult(result));
}

void main()
  .then((exitCode) => {
    process.exitCode = exitCode;
  })
  .catch((error: unknown) => {
    emit(cliFailure("CLI_FAILURE", messageOf(error)));
    process.exitCode = 2;
  });
