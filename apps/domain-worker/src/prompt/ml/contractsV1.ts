import { createHash } from "node:crypto";
import { z } from "zod";
import type { CellFeatureVector } from "./types.js";

export const ML_FEATURE_SCHEMA = "tidy.ml-feature-batch/v1" as const;
export const ML_HINT_SCHEMA = "tidy.ml-hints/v1" as const;
export const ML_PACKAGE_ID =
  "tidycell-all-approved-gold-exclusion-xgboost-v1" as const;
export const MAX_ML_CELLS = 25_000;
export const ML_PACKAGE_MANIFEST_DIGEST =
  "sha256:75361df90d525c9c723f016f246ef141814ef693fe9579dbcf9f5ca7a253365a" as const;
export const ML_SOURCE_COHORT_DIGEST =
  "sha256:4afece250764eaf8c9acb57e491c894a0599d468b0005a760076153dccdd9d53" as const;
export const ML_ROLE_MODEL_DIGEST =
  "sha256:280973a12874d7d44457c96f8d6a4bec90297b6ae07f017494dab425950811bc" as const;
export const ML_DIRECTION_MODEL_DIGEST =
  "sha256:c95a62171ba86a757b2848e69374fc58facf52d5b4d6ee4b4c64bf4e5e6bd720" as const;
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const address = z.string().regex(/^R[1-9][0-9]{0,6}C[1-9][0-9]{0,6}$/);

export const NUMERIC_FEATURES = [
  "rowRatio",
  "colRatio",
  "textLength",
  "tokenCount",
  "digitRatio",
  "uppercaseRatio",
  "punctuationRatio",
  "rowNonEmptyCount",
  "columnNonEmptyCount",
  "rowDensity",
  "columnDensity",
  "nonEmptyAbove",
  "nonEmptyBelow",
  "nonEmptyLeft",
  "nonEmptyRight",
  "nearestBlankRowAbove",
  "nearestBlankRowBelow",
  "nearestBlankColumnLeft",
  "nearestBlankColumnRight",
  "fontSize",
  "fontIndent",
  "mergeRowSpan",
  "mergeColumnSpan",
] as const;
export const BOOLEAN_FEATURES = [
  "isBlank",
  "hasFormula",
  "hasComment",
  "hasFormattedValue",
  "isNumericLikeText",
  "isDateLikeText",
  "isTopEdge",
  "isLeftEdge",
  "isBottomEdge",
  "isRightEdge",
  "isBold",
  "isItalic",
  "isUnderlined",
  "hasFillColor",
  "hasFontColor",
  "hasBorderTop",
  "hasBorderRight",
  "hasBorderBottom",
  "hasBorderLeft",
  "hasAnyBorder",
] as const;
const CATEGORICAL_FEATURES = [
  "dataType",
  "horizontalAlign",
  "verticalAlign",
  "mergeRole",
] as const;
const ROLE_CATEGORIES: Record<string, readonly string[]> = {
  dataType: ["blank", "numeric", "string"],
  horizontalAlign: ["__missing__", "center", "left", "right"],
  verticalAlign: ["__missing__", "middle", "top"],
  mergeRole: ["child", "none", "parent"],
};
const DIRECTION_CATEGORIES: Record<string, readonly string[]> = {
  dataType: ["blank", "string"],
  horizontalAlign: ["__missing__", "center", "left", "right"],
  verticalAlign: ["__missing__", "middle"],
  mergeRole: ["child", "none", "parent"],
};

function numberValue(value: unknown): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === "boolean") return value ? 1 : 0;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
function categoryValue(value: unknown): string {
  return value === null || value === undefined ? "__missing__" : String(value);
}
function encode(
  feature: CellFeatureVector,
  categories: Record<string, readonly string[]>,
): number[] {
  const record = feature as unknown as Record<string, unknown>;
  const vector = [
    ...NUMERIC_FEATURES.map((name) => numberValue(record[name])),
    ...BOOLEAN_FEATURES.map((name) => (record[name] === true ? 1 : 0)),
  ];
  for (const name of CATEGORICAL_FEATURES) {
    const value = categoryValue(record[name]);
    vector.push(...categories[name].map((item) => (item === value ? 1 : 0)));
  }
  return vector;
}
export function encodeModelFeatures(feature: CellFeatureVector): {
  roleVector: number[];
  directionVector: number[];
} {
  const roleVector = encode(feature, ROLE_CATEGORIES);
  const directionVector = encode(feature, DIRECTION_CATEGORIES);
  if (roleVector.length !== 56 || directionVector.length !== 54)
    throw new Error("Pinned ML feature dimensions changed.");
  return { roleVector, directionVector };
}

const finiteFeature = z
  .number()
  .finite()
  .min(-1_000_000_000)
  .max(1_000_000_000);
export const mlFeatureBatchSchema = z
  .object({
    schemaVersion: z.literal(ML_FEATURE_SCHEMA),
    workbookDigest: digest,
    sheet: z.string().min(1).max(200),
    packageId: z.literal(ML_PACKAGE_ID),
    cells: z
      .array(
        z
          .object({
            address,
            roleVector: z.array(finiteFeature).length(56),
            directionVector: z.array(finiteFeature).length(54),
          })
          .strict(),
      )
      .max(MAX_ML_CELLS),
    featureBatchDigest: digest,
  })
  .strict();
export type MlFeatureBatchV1 = z.infer<typeof mlFeatureBatchSchema>;

const predictionSchema = z
  .object({
    address,
    role: z.enum(["blank", "header", "unused", "value"]),
    direction: z.enum(["N", "NNW", "W", "WNW"]),
    roleConfidence: z.number().finite().min(0).max(1),
    directionConfidence: z.number().finite().min(0).max(1),
  })
  .strict();
export const mlHintsSchema = z
  .object({
    schemaVersion: z.literal(ML_HINT_SCHEMA),
    workbookDigest: digest,
    sheet: z.string().min(1).max(200),
    featureBatchDigest: digest,
    packageId: z.literal(ML_PACKAGE_ID),
    packageManifestDigest: z.literal(ML_PACKAGE_MANIFEST_DIGEST),
    sourceCohortSha256: z.literal(ML_SOURCE_COHORT_DIGEST),
    models: z
      .object({
        cellRole: z.literal(ML_ROLE_MODEL_DIGEST),
        headerDirection: z.literal(ML_DIRECTION_MODEL_DIGEST),
      })
      .strict(),
    predictions: z.array(predictionSchema).max(MAX_ML_CELLS),
    hintDigest: digest,
  })
  .strict();
export type MlHintsV1 = z.infer<typeof mlHintsSchema>;

export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value))
      throw new Error("Canonical numbers must be finite binary64 values.");
    const normalized = Object.is(value, -0) ? 0 : value;
    const [mantissa, rawExponent] = normalized.toExponential(17).split("e");
    return `${mantissa}e${Number.parseInt(rawExponent, 10) >= 0 ? "+" : ""}${Number.parseInt(rawExponent, 10)}`;
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record).sort((left, right) =>
      Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8")),
    );
    return `{${keys
      .map((key) => `${canonicalJson(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  throw new Error(`Unsupported canonical value: ${typeof value}.`);
}
export function canonicalDigest(value: unknown): string {
  return `sha256:${createHash("sha256").update(canonicalJson(value)).digest("hex")}`;
}
export function validateMlFeatureBatch(
  raw: unknown,
  workbookDigest: string,
  sheet: string,
): MlFeatureBatchV1 {
  const parsed = mlFeatureBatchSchema.parse(raw);
  const semantic = { ...parsed } as Record<string, unknown>;
  delete semantic.featureBatchDigest;
  if (
    parsed.workbookDigest !== workbookDigest ||
    parsed.sheet !== sheet ||
    parsed.featureBatchDigest !== canonicalDigest(semantic) ||
    new Set(parsed.cells.map((item) => item.address)).size !==
      parsed.cells.length
  )
    throw new Error("ML feature batch integrity binding is invalid.");
  return parsed;
}

export function validateMlHints(
  raw: unknown,
  workbookDigest: string,
  sheet: string,
  featureBatchDigest: string,
  expectedAddresses: readonly string[],
): MlHintsV1 {
  const parsed = mlHintsSchema.parse(raw);
  const semantic = { ...parsed, hintDigest: undefined } as Record<
    string,
    unknown
  >;
  delete semantic.hintDigest;
  if (
    parsed.workbookDigest !== workbookDigest ||
    parsed.sheet !== sheet ||
    parsed.featureBatchDigest !== featureBatchDigest ||
    parsed.hintDigest !== canonicalDigest(semantic) ||
    parsed.predictions.length !== expectedAddresses.length ||
    parsed.predictions.some(
      (prediction, index) => prediction.address !== expectedAddresses[index],
    )
  )
    throw new Error("ML hint integrity binding is invalid.");
  return parsed;
}
