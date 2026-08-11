import { describe, expect, it } from "vitest";
import type { MlPrepassResult } from "../../src/lib/ml-prepass/types";
import { buildMlAssistedPrompt, buildMlStructureSuggestionSection } from "./ml-assisted-prompt";

const prepass: MlPrepassResult = {
  sheet: "Sheet1",
  modelFamily: "xgboost",
  modelVersion: "test-v1",
  predictions: [
    { sheet: "Sheet1", address: "R2C2", row: 2, col: 2, predictedRole: "value", confidence: 0.9 },
    { sheet: "Sheet1", address: "R3C2", row: 3, col: 2, predictedRole: "value", confidence: 0.8 },
    {
      sheet: "Sheet1",
      address: "R2C1",
      row: 2,
      col: 1,
      predictedRole: "header",
      predictedDirection: "W",
      confidence: 0.95,
    },
    { sheet: "Sheet1", address: "R9C4", row: 9, col: 4, predictedRole: "unused", confidence: 0.4 },
  ],
  headerGroups: [],
  tableRegions: [],
  confidence: {
    overall: 0.8,
    valueRole: 0.85,
    headerRole: 0.95,
    lowConfidenceCellCount: 1,
  },
  promptHints: [],
  lowConfidenceAddresses: ["R9C4"],
};

describe("ML-assisted LLM prompt", () => {
  it("renders compact, explicitly non-binding role and direction suggestions", () => {
    const section = buildMlStructureSuggestionSection(prepass);
    expect(section).toContain("fallible, non-binding");
    expect(section).toContain("Likely observation/value cells (2");
    expect(section).toContain("R2C2:R3C2");
    expect(section).toContain("Likely W header cells (1): R2C1");
    expect(section).toContain("Low-confidence cells (1): R9C4");
  });

  it("preserves the base prompt and appends one delimited suggestion section", () => {
    const prompt = buildMlAssistedPrompt("BASE_PROMPT", prepass);
    expect(prompt.startsWith("BASE_PROMPT\nBEGIN_ML_STRUCTURE_SUGGESTIONS")).toBe(true);
    expect(prompt.match(/BEGIN_ML_STRUCTURE_SUGGESTIONS/g)).toHaveLength(1);
  });
});
