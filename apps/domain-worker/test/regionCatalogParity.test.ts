import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildSemanticCellFormattingFacts } from "../src/catalog/format-aware-region-catalog-v2.js";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
} from "../src/catalog/role-aware-region-catalog-v5.js";
import { buildCompactSemanticContext } from "../src/context/compactContext.js";
import { parseWorkbook } from "../src/workbook/parseWorkbook.js";

const referenceSchema = "tidy.historical-source-region-catalog-reference/v1";
const caseSchema = "tidy.historical-source-region-catalog-reference-case/v1";
const paritySchema = "tidy.candidate-region-catalog-parity/v1";
const sourceDomain = "tidy.candidate-region-catalog-source-closure/v1";
const referenceDigest =
  "sha256:7632516d91c47855105d72b072df7368bf67b2167c0e74a4ab4833f6b5a954df";

type ReferenceCase = {
  caseId: string;
  workbookRelativePath: string;
  workbookContentDigest: string;
  catalogCount: number;
  catalogs: unknown[];
  caseDigest: string;
};

describe("historical source role-aware region catalogue parity", () => {
  it("matches every frozen historical catalogue exactly", async () => {
    const reference = JSON.parse(
      readFileSync(
        path.join(
          process.cwd(),
          "fixtures/reference-region/historical-v1.json",
        ),
        "utf8",
      ),
    );
    const { referenceDigest: storedReferenceDigest, ...referenceSemantic } =
      reference;
    expect(domainDigest(referenceSchema, referenceSemantic)).toBe(
      referenceDigest,
    );
    expect(storedReferenceDigest).toBe(referenceDigest);
    expect(reference.candidateImplementationUsed).toBe(false);
    expect(reference.parityEstablished).toBe(false);

    const parity = JSON.parse(
      readFileSync(
        path.join(
          process.cwd(),
          "fixtures/reference-region/candidate-parity-v1.json",
        ),
        "utf8",
      ),
    );
    const { parityDigest, ...paritySemantic } = parity;
    expect(domainDigest(paritySchema, paritySemantic)).toBe(parityDigest);
    const currentFiles = parity.candidateFiles.map(
      (file: { relativePath: string; contentDigest: string }) => {
        const contentDigest = sha256Bytes(
          readFileSync(path.join(process.cwd(), file.relativePath)),
        );
        expect(contentDigest).toBe(file.contentDigest);
        return { relativePath: file.relativePath, contentDigest };
      },
    );
    expect(domainDigest(sourceDomain, currentFiles)).toBe(
      parity.candidateSourceDigest,
    );
    expect(parity.referenceDigest).toBe(referenceDigest);
    expect(parity.referenceCaseDigests).toEqual(
      reference.cases.map((entry: ReferenceCase) => entry.caseDigest),
    );
    expect(parity.scope).toMatchObject({
      scopeParityEstablished: true,
      fullPhaseCParityEstablished: false,
    });

    let matchedCatalogs = 0;
    for (const referenceCase of reference.cases as ReferenceCase[]) {
      const { caseDigest, ...caseSemantic } = referenceCase;
      expect(domainDigest(caseSchema, caseSemantic)).toBe(caseDigest);
      const workbookBytes = readFileSync(
        path.join(process.cwd(), referenceCase.workbookRelativePath),
      );
      expect(sha256Bytes(workbookBytes)).toBe(
        referenceCase.workbookContentDigest,
      );
      const parsed = await parseWorkbook(workbookBytes);
      expect(parsed.ok).toBe(true);
      if (!parsed.ok) throw new Error("Candidate workbook parse failed");
      const catalogs = parsed.workbook.sheets.map((sheet) => {
        const context = buildCompactSemanticContext(sheet);
        return buildRoleAwareSemanticRegionCatalog(context, {
          formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
          cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
        });
      });
      expect(catalogs).toEqual(referenceCase.catalogs);
      expect(catalogs).toHaveLength(referenceCase.catalogCount);
      matchedCatalogs += catalogs.length;
    }
    expect(matchedCatalogs).toBe(4);
    expect(parity.matchedCatalogCount).toBe(matchedCatalogs);
    expect(parity.mismatchCount).toBe(0);
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
