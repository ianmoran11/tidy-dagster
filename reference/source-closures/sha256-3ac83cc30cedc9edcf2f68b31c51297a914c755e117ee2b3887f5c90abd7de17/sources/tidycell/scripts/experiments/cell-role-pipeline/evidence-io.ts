import { TextDecoder } from "node:util";
import {
  writeImmutableContainedFile,
  type ImmutableWriteResult,
} from "./artifact-io";
import { assertSafeEvidence } from "./evidence";

export const EVIDENCE_PAYLOAD_MEDIA_TYPES = [
  "application/json",
  "text/csv",
  "text/html",
  "text/plain",
] as const;
export type EvidencePayloadMediaType =
  (typeof EVIDENCE_PAYLOAD_MEDIA_TYPES)[number];

export function validateEvidencePayload(options: {
  bytes: Uint8Array;
  mediaType: EvidencePayloadMediaType;
  role: string;
}): unknown {
  const text = decodeUtf8(options.bytes, options.role);
  if (options.mediaType === "application/json") {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      throw new Error(`MALFORMED_EVIDENCE_JSON: ${options.role}.`);
    }
    assertSafeEvidence(parsed, `$[${options.role}]`);
    return parsed;
  }
  assertSafeEvidence(text, `$[${options.role}]`);
  return text;
}

export async function writeImmutableEvidenceFile(options: {
  repoRoot: string;
  target: string;
  bytes: Uint8Array;
  mediaType: EvidencePayloadMediaType;
  role: string;
  mode?: number;
  pathErrorCode?: string;
}): Promise<ImmutableWriteResult> {
  validateEvidencePayload({
    bytes: options.bytes,
    mediaType: options.mediaType,
    role: options.role,
  });
  return writeImmutableContainedFile({
    repoRoot: options.repoRoot,
    target: options.target,
    bytes: options.bytes,
    mode: options.mode,
    pathErrorCode: options.pathErrorCode,
  });
}

export function evidenceMediaTypeForPath(
  target: string,
): EvidencePayloadMediaType {
  if (target.endsWith(".json")) return "application/json";
  if (target.endsWith(".csv")) return "text/csv";
  if (target.endsWith(".html")) return "text/html";
  if (target.endsWith(".txt") || target.endsWith(".sha256")) {
    return "text/plain";
  }
  throw new Error(`UNSUPPORTED_EVIDENCE_MEDIA_TYPE: ${target}.`);
}

function decodeUtf8(value: Uint8Array, role: string): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(value);
  } catch {
    throw new Error(`INVALID_EVIDENCE_UTF8: ${role}.`);
  }
}
