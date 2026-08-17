import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  canonicalDigest,
  canonicalJson,
  encodeModelFeatures,
  ML_PACKAGE_MANIFEST_DIGEST,
  validateMlHints,
} from "../src/prompt/ml/contractsV1.js";
import { extractCellFeatures } from "../src/prompt/ml/featuresV1.js";
import {
  appendMlHintExtension,
  SEMANTIC_MAP_ML_HINT_EXTENSION_VERSION,
} from "../src/prompt/ml/semanticMapHintsV1.js";
import type { MlHintsV1 } from "../src/prompt/ml/contractsV1.js";
import type { ParsedSheet } from "../src/workbook/types.js";

const workbookDigest = `sha256:${"1".repeat(64)}`;

function hints(): MlHintsV1 {
  const semantic = {
    schemaVersion: "tidy.ml-hints/v1" as const,
    workbookDigest,
    sheet: "Data",
    featureBatchDigest: `sha256:${"2".repeat(64)}`,
    packageId: "tidycell-all-approved-gold-exclusion-xgboost-v1" as const,
    packageManifestDigest: ML_PACKAGE_MANIFEST_DIGEST,
    sourceCohortSha256:
      "sha256:4afece250764eaf8c9acb57e491c894a0599d468b0005a760076153dccdd9d53" as const,
    models: {
      cellRole:
        "sha256:280973a12874d7d44457c96f8d6a4bec90297b6ae07f017494dab425950811bc" as const,
      headerDirection:
        "sha256:c95a62171ba86a757b2848e69374fc58facf52d5b4d6ee4b4c64bf4e5e6bd720" as const,
    },
    predictions: [
      {
        address: "R1C1",
        role: "header" as const,
        direction: "N" as const,
        roleConfidence: 0.9,
        directionConfidence: 0.8,
      },
      {
        address: "R2C1",
        role: "value" as const,
        direction: "W" as const,
        roleConfidence: 0.95,
        directionConfidence: 0.7,
      },
    ],
  };
  return { ...semantic, hintDigest: canonicalDigest(semantic) };
}

describe("local ML v1 contracts", () => {
  it("ports the upstream extractor and exact task-specific encoders", () => {
    const sheet: ParsedSheet = {
      name: "Data",
      usedRange: "R1C1:R2C2",
      rowCount: 2,
      columnCount: 2,
      nonEmptyCellCount: 2,
      merges: [],
      cells: [
        {
          sheet: "Data",
          address: "R1C1",
          row: 1,
          col: 1,
          value: "ABC 12",
          formatted: "ABC 12",
          data_type: "string",
          style: { bold: true, horizontalAlign: "center" },
        },
        {
          sheet: "Data",
          address: "R2C2",
          row: 2,
          col: 2,
          value: 7,
          formatted: "7",
          data_type: "numeric",
        },
      ],
    };
    const features = extractCellFeatures(sheet);
    expect(features[0]).toMatchObject({
      rowRatio: 0.5,
      colRatio: 0.5,
      textLength: 6,
      tokenCount: 2,
      digitRatio: 2 / 6,
      uppercaseRatio: 1,
      rowNonEmptyCount: 1,
      columnNonEmptyCount: 1,
      nonEmptyBelow: 0,
      nonEmptyRight: 0,
      isTopEdge: true,
      isLeftEdge: true,
      isBold: true,
      horizontalAlign: "center",
      mergeRole: "none",
    });
    const encoded = encodeModelFeatures(features[0]);
    expect(encoded.roleVector).toHaveLength(56);
    expect(encoded.directionVector).toHaveLength(54);
    expect(encoded.roleVector.slice(0, 7)).toEqual([
      0.5,
      0.5,
      6,
      2,
      2 / 6,
      1,
      0,
    ]);
    // Frozen upstream category ordering: blank,numeric,string then alignment.
    expect(encoded.roleVector.slice(43, 50)).toEqual([0, 0, 1, 0, 1, 0, 0]);
  });

  it("strictly binds hint digest, request, package, and address order", () => {
    const expectedAddresses = ["R1C1", "R2C1"];
    expect(
      validateMlHints(
        hints(),
        workbookDigest,
        "Data",
        `sha256:${"2".repeat(64)}`,
        expectedAddresses,
      ),
    ).toEqual(hints());
    expect(() =>
      validateMlHints(
        hints(),
        `sha256:${"9".repeat(64)}`,
        "Data",
        `sha256:${"2".repeat(64)}`,
        expectedAddresses,
      ),
    ).toThrow(/binding/);
    expect(() =>
      validateMlHints(
        hints(),
        workbookDigest,
        "Data",
        `sha256:${"2".repeat(64)}`,
        [...expectedAddresses].reverse(),
      ),
    ).toThrow(/binding/);
  });

  it("matches shared Unicode and exponent canonical digest vectors", () => {
    const vectors = JSON.parse(
      readFileSync("contracts/ml/v1/canonical-vectors.json", "utf8"),
    ) as {
      positive: Array<{
        value: unknown;
        canonicalUtf8: string;
        digest: string;
      }>;
      negative: Array<{ value: unknown; digest: string }>;
    };
    for (const vector of vectors.positive) {
      expect(canonicalJson(vector.value)).toBe(vector.canonicalUtf8);
      expect(canonicalDigest(vector.value)).toBe(vector.digest);
    }
    for (const vector of vectors.negative)
      expect(canonicalDigest(vector.value)).not.toBe(vector.digest);
  });

  it("appends a separately versioned, explicitly non-authoritative snapshot", () => {
    expect(appendMlHintExtension("BASELINE", hints())).toMatchInlineSnapshot(`
      "BASELINE
      BEGIN_LOCAL_ML_HINT_EXTENSION
      Hint extension contract: cell-role-semantic-map-v13-ml-hints-v1.
      These local ML hints may be wrong. They are non-authoritative suggestions only and have no semantic, compilation, validation, acceptance, execution, dashboard, Dagster, or decision authority. Make every semantic decision from the workbook context and catalog; ignore any hint that conflicts with them.
      {"schemaVersion":"cell-role-semantic-map-v13-ml-hints-v1","hintDigest":"sha256:9307ca0ebd6c66200cb18f1b6e77ea654cf5b6a829d38340963ef25a081c3a09","likelyValueRanges":["R2C1"],"likelyHeaderRanges":["R1C1"],"likelyUnusedOrBlankRanges":[],"likelyHeaderDirections":[{"direction":"N","ranges":["R1C1"]},{"direction":"NNW","ranges":[]},{"direction":"W","ranges":[]},{"direction":"WNW","ranges":[]}]}
      END_LOCAL_ML_HINT_EXTENSION"
    `);
    expect(SEMANTIC_MAP_ML_HINT_EXTENSION_VERSION).not.toContain(
      "adjacent-year-aware",
    );
  });
});
