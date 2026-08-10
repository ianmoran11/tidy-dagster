/* Exact compatibility port from the Phase A-pinned TidyCell candidate-contract source. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  TIDYCELL_DIGEST_RECORD_ALGORITHM,
  TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST,
  tidycellCanonicalJson,
  tidycellDigestRecord,
} from "../src/migration/historicalDigestRecord.js";

type Vector = {
  id: string;
  input: unknown;
  canonical: string;
  digest: string;
};

type VectorManifest = {
  schemaVersion: string;
  algorithm: string;
  source: {
    snapshotDigest: string;
    gitHead: string;
    gitTree: string;
    relativePath: string;
    contentDigest: string;
  };
  vectors: Vector[];
};

const manifest = JSON.parse(
  readFileSync(
    join(process.cwd(), "fixtures/migration/digest-record-v1.json"),
    "utf8",
  ),
) as VectorManifest;

describe("historical TidyCell digestRecord", () => {
  it("binds the exact frozen source and named algorithm", () => {
    expect(manifest.schemaVersion).toBe("tidycell-digest-record-vectors/v1");
    expect(manifest.algorithm).toBe(TIDYCELL_DIGEST_RECORD_ALGORITHM);
    expect(manifest.source.contentDigest).toBe(
      TIDYCELL_DIGEST_RECORD_SOURCE_DIGEST,
    );
    expect(manifest.source.snapshotDigest).toBe(
      "sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d",
    );
    expect(manifest.source.gitHead).toBe(
      "1be6c995fa931e9860468e40490433161b0121cb",
    );
    expect(manifest.source.gitTree).toBe(
      "96a76a1cbc6f2da3facd31d7cdae5b05926361d3",
    );
    expect(manifest.source.relativePath).toBe(
      "scripts/harvest/candidate-contract.ts",
    );
  });

  it.each(manifest.vectors)("matches independent vector $id", (vector) => {
    expect(tidycellCanonicalJson(vector.input)).toBe(vector.canonical);
    expect(tidycellDigestRecord(vector.input)).toBe(vector.digest);
  });

  it("preserves historical non-JSON edge behavior without calling it JCS", () => {
    expect(tidycellCanonicalJson(Number.NaN)).toBe("null");
    expect(tidycellDigestRecord(Number.NaN)).toBe(
      "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
    );
    expect(tidycellCanonicalJson({ x: undefined })).toBe('{"x":undefined}');
    expect(tidycellDigestRecord({ x: undefined })).toBe(
      "sha256:3f0c22c2414f574f3627393c85d85446d22df2364ed2cd9020d2c2e15a0eb598",
    );
    expect(tidycellCanonicalJson([undefined])).toBe("[]");
    expect(tidycellCanonicalJson(-0)).toBe("0");
    expect(() => tidycellDigestRecord(undefined)).toThrow(TypeError);
    expect(() => tidycellCanonicalJson(1n)).toThrow(TypeError);
  });
});
