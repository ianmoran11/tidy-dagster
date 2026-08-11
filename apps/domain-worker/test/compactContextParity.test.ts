import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildCompactContextSnapshot } from "../src/context/compactContext.js";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";

const schemaVersion = "tidy.historical-source-compact-context-reference/v1";
const caseVersion = "tidy.historical-source-compact-context-reference-case/v1";
const expectedReferenceDigest =
  "sha256:1bf6352d8379cec115896e74642dd4cefaa4bf50c21540827815055164cd8cb9";

type ReferenceCase = {
  caseId: string;
  workbookRelativePath: string;
  workbookContentDigest: string;
  contextCount: number;
  contexts: unknown[];
  caseDigest: string;
};

describe("historical compact-context parity", () => {
  it("matches all four frozen historical contexts exactly", async () => {
    const reference = JSON.parse(
      readFileSync(
        path.join(
          process.cwd(),
          "fixtures/reference-context/historical-v1.json",
        ),
        "utf8",
      ),
    );
    const { referenceDigest, ...semantic } = reference;
    expect(domainDigest(schemaVersion, semantic)).toBe(expectedReferenceDigest);
    expect(referenceDigest).toBe(expectedReferenceDigest);
    expect(reference.candidateImplementationUsed).toBe(false);
    expect(reference.parityEstablished).toBe(false);
    const parity = JSON.parse(
      readFileSync(
        path.join(
          process.cwd(),
          "fixtures/reference-context/candidate-parity-v1.json",
        ),
        "utf8",
      ),
    );
    const { parityDigest, ...paritySemantic } = parity;
    expect(domainDigest(parity.schemaVersion, paritySemantic)).toBe(
      "sha256:d7cc5a3905e6cb3d78d379e27e76b02b936775e0da4d3e7c5c8e3e34e834636a",
    );
    expect(parityDigest).toBe(
      "sha256:d7cc5a3905e6cb3d78d379e27e76b02b936775e0da4d3e7c5c8e3e34e834636a",
    );
    const currentFiles = parity.candidateFiles.map(
      (file: { relativePath: string; contentDigest: string }) => {
        const contentDigest = sha256Bytes(
          readFileSync(path.join(process.cwd(), file.relativePath)),
        );
        expect(contentDigest).toBe(file.contentDigest);
        return { relativePath: file.relativePath, contentDigest };
      },
    );
    expect(
      domainDigest(
        "tidy.candidate-compact-context-source-closure/v1",
        currentFiles,
      ),
    ).toBe(parity.candidateSourceDigest);
    expect(parity.referenceDigest).toBe(reference.referenceDigest);
    expect(parity.referenceCaseDigests).toEqual(
      reference.cases.map((entry: ReferenceCase) => entry.caseDigest),
    );
    expect(parity.scope).toMatchObject({
      scopeParityEstablished: true,
      fullPhaseCParityEstablished: false,
    });

    let matchedContexts = 0;
    for (const referenceCase of reference.cases as ReferenceCase[]) {
      const { caseDigest, ...caseSemantic } = referenceCase;
      expect(domainDigest(caseVersion, caseSemantic)).toBe(caseDigest);
      const workbook = readFileSync(
        path.join(process.cwd(), referenceCase.workbookRelativePath),
      );
      expect(sha256Bytes(workbook)).toBe(referenceCase.workbookContentDigest);
      const parsed = await parseWorkbook(workbook);
      expect(parsed.ok).toBe(true);
      if (!parsed.ok) throw new Error("Candidate workbook parse failed");
      const contexts = parsed.workbook.sheets.map(buildCompactContextSnapshot);
      expect(contexts).toEqual(referenceCase.contexts);
      expect(contexts).toHaveLength(referenceCase.contextCount);
      matchedContexts += contexts.length;
    }
    expect(matchedContexts).toBe(4);
  });
});

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string")
    return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Non-finite canonical number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
      .join(",")}}`;
  throw new Error("Unsupported canonical JSON value");
}

function domainDigest(domain: string, value: unknown): string {
  return sha256Bytes(
    Buffer.concat([
      Buffer.from(`${domain}\0`),
      Buffer.from(canonicalJson(value)),
    ]),
  );
}

function sha256Bytes(data: Buffer): string {
  return `sha256:${createHash("sha256").update(data).digest("hex")}`;
}
