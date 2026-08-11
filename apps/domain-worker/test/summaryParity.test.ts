import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildSheetSummary } from "../src/summary/buildSheetSummary.js";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";

const referencePath = path.join(
  process.cwd(),
  "fixtures/reference-summary/historical-v1.json",
);
const schemaVersion = "tidy.historical-source-summary-reference/v1";
const caseVersion = "tidy.historical-source-summary-reference-case/v1";

type ReferenceCase = {
  caseId: string;
  workbookRelativePath: string;
  workbookContentDigest: string;
  sheetCount: number;
  summaries: unknown[];
  caseDigest: string;
};

describe("historical source summary parity", () => {
  it("matches every frozen historical summary byte-for-byte by structure", async () => {
    const reference = JSON.parse(readFileSync(referencePath, "utf8"));
    const semantic = { ...reference };
    delete semantic.referenceDigest;
    expect(domainDigest(schemaVersion, semantic)).toBe(
      "sha256:0d0dca23d4f08204cbf02d6cc841fbd5ba15df32aeab92da77a0f91f5ff49c70",
    );
    expect(reference.referenceDigest).toBe(
      "sha256:0d0dca23d4f08204cbf02d6cc841fbd5ba15df32aeab92da77a0f91f5ff49c70",
    );
    expect(reference.candidateImplementationUsed).toBe(false);
    expect(reference.parityEstablished).toBe(false);
    const parity = JSON.parse(
      readFileSync(
        path.join(
          process.cwd(),
          "fixtures/reference-summary/candidate-parity-v1.json",
        ),
        "utf8",
      ),
    );
    const { parityDigest, ...paritySemantic } = parity;
    expect(domainDigest(parity.schemaVersion, paritySemantic)).toBe(
      "sha256:284ab8d7ac3a171f804e23d6fe84de72a96a82e2a26c05793b3cb905ecff4e9b",
    );
    expect(parityDigest).toBe(
      "sha256:284ab8d7ac3a171f804e23d6fe84de72a96a82e2a26c05793b3cb905ecff4e9b",
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
      domainDigest("tidy.candidate-summary-source-closure/v1", currentFiles),
    ).toBe(parity.candidateSourceDigest);
    expect(parity.referenceDigest).toBe(reference.referenceDigest);
    expect(parity.referenceCaseDigests).toEqual(
      reference.cases.map((entry: ReferenceCase) => entry.caseDigest),
    );
    expect(parity.scope).toMatchObject({
      scopeParityEstablished: true,
      fullPhaseCParityEstablished: false,
    });

    let matchedSheets = 0;
    for (const referenceCase of reference.cases as ReferenceCase[]) {
      const { caseDigest, ...caseSemantic } = referenceCase;
      expect(domainDigest(caseVersion, caseSemantic)).toBe(caseDigest);
      const workbookPath = path.join(
        process.cwd(),
        referenceCase.workbookRelativePath,
      );
      const workbookBytes = readFileSync(workbookPath);
      expect(sha256Bytes(workbookBytes)).toBe(
        referenceCase.workbookContentDigest,
      );
      const parsed = await parseWorkbook(workbookBytes);
      expect(parsed.ok).toBe(true);
      if (!parsed.ok) throw new Error("Candidate workbook parse failed");
      const summaries = parsed.workbook.sheets.map((sheet) =>
        buildSheetSummary(sheet, { checked: true }),
      );
      expect(summaries).toEqual(referenceCase.summaries);
      expect(summaries).toHaveLength(referenceCase.sheetCount);
      matchedSheets += summaries.length;
    }
    expect(matchedSheets).toBe(4);
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
