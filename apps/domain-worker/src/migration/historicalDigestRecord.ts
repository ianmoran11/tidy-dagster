import { createHash } from "node:crypto";

export const TIDYCELL_DIGEST_RECORD_ALGORITHM = "tidycell-digest-record-v1";
export const TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST =
  "sha256:ca0f38e741ba43886f809a2c96b782cec4db3a46787eb17f655fad019464114c";

/**
 * Exact port of canonicalJson/digestRecord from the Phase A-pinned
 * TidyCell scripts/harvest/candidate-contract.ts source item.
 *
 * This is historical compatibility behavior. It is not RFC 8785/JCS and must
 * not be silently reused as a generic canonical-JSON algorithm.
 */
export function tidycellCanonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) as string;
  }
  if (Array.isArray(value)) {
    return `[${value.map((entry) => tidycellCanonicalJson(entry)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort(compareText)
    .map(
      (key) => `${JSON.stringify(key)}:${tidycellCanonicalJson(record[key])}`,
    )
    .join(",")}}`;
}

export function tidycellDigestRecord(value: unknown): string {
  return `sha256:${createHash("sha256")
    .update(tidycellCanonicalJson(value))
    .digest("hex")}`;
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
