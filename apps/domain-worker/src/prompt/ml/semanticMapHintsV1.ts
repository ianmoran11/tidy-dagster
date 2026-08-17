import { compactAddressRanges } from "./promptHints.js";
import type { MlHintsV1 } from "./contractsV1.js";

export const SEMANTIC_MAP_ML_HINT_EXTENSION_VERSION =
  "cell-role-semantic-map-v13-ml-hints-v1" as const;
const MAX_RANGES_PER_ROLE = 160;

export function appendMlHintExtension(
  baseline: string,
  hints: MlHintsV1,
): string {
  const ranges = (role: MlHintsV1["predictions"][number]["role"]) =>
    compactAddressRanges(
      hints.predictions
        .filter((item) => item.role === role)
        .map((item) => item.address),
    ).slice(0, MAX_RANGES_PER_ROLE);
  const directions = (["N", "NNW", "W", "WNW"] as const).map((direction) => ({
    direction,
    ranges: compactAddressRanges(
      hints.predictions
        .filter(
          (item) => item.role === "header" && item.direction === direction,
        )
        .map((item) => item.address),
    ).slice(0, MAX_RANGES_PER_ROLE),
  }));
  const payload = {
    schemaVersion: SEMANTIC_MAP_ML_HINT_EXTENSION_VERSION,
    hintDigest: hints.hintDigest,
    likelyValueRanges: ranges("value"),
    likelyHeaderRanges: ranges("header"),
    likelyUnusedOrBlankRanges: [...ranges("unused"), ...ranges("blank")].slice(
      0,
      MAX_RANGES_PER_ROLE,
    ),
    likelyHeaderDirections: directions,
  };
  return [
    baseline,
    "BEGIN_LOCAL_ML_HINT_EXTENSION",
    `Hint extension contract: ${SEMANTIC_MAP_ML_HINT_EXTENSION_VERSION}.`,
    "These local ML hints may be wrong. They are non-authoritative suggestions only and have no semantic, compilation, validation, acceptance, execution, dashboard, Dagster, or decision authority. Make every semantic decision from the workbook context and catalog; ignore any hint that conflicts with them.",
    JSON.stringify(payload),
    "END_LOCAL_ML_HINT_EXTENSION",
  ].join("\n");
}
