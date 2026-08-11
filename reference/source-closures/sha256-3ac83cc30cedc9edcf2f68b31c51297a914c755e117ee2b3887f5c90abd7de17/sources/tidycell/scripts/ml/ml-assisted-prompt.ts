import type { HeaderDirection } from "../../src/lib/recipe/types";
import type { MlPrepassResult } from "../../src/lib/ml-prepass/types";
import { summarizeAddressesAsRanges } from "../../src/lib/ml-prepass/promptHints";

const DIRECTIONS: HeaderDirection[] = ["N", "W", "NNW", "WNW"];

export function buildMlStructureSuggestionSection(prepass: MlPrepassResult): string {
  const values = prepass.predictions.filter((cell) => cell.predictedRole === "value");
  const headers = prepass.predictions.filter((cell) => cell.predictedRole === "header");
  const lines = [
    "BEGIN_ML_STRUCTURE_SUGGESTIONS",
    "These are fallible, non-binding machine-learning suggestions. Use them as additional structural evidence only. The semantic map and final recipe remain your responsibility; override suggestions that conflict with workbook context.",
    `Model: ${prepass.modelFamily}/${prepass.modelVersion}`,
    `Likely observation/value cells (${values.length}, mean confidence ${formatMean(values.map((cell) => cell.confidence))}): ${summarizeAddressesAsRanges(values.map((cell) => cell.address))}`,
    `Likely header cells (${headers.length}, mean confidence ${formatMean(headers.map((cell) => cell.confidence))}): ${summarizeAddressesAsRanges(headers.map((cell) => cell.address))}`,
  ];

  for (const direction of DIRECTIONS) {
    const cells = headers.filter((cell) => cell.predictedDirection === direction);
    if (!cells.length) continue;
    lines.push(
      `Likely ${direction} header cells (${cells.length}): ${summarizeAddressesAsRanges(cells.map((cell) => cell.address))}`,
    );
  }

  const uncertain = prepass.predictions.filter((cell) => (cell.confidence ?? 0) < 0.55);
  lines.push(
    `Low-confidence cells (${uncertain.length}): ${summarizeAddressesAsRanges(uncertain.map((cell) => cell.address))}`,
    "END_ML_STRUCTURE_SUGGESTIONS",
  );
  return lines.join("\n");
}

export function buildMlAssistedPrompt(basePrompt: string, prepass: MlPrepassResult): string {
  return `${basePrompt}\n${buildMlStructureSuggestionSection(prepass)}`;
}

function formatMean(values: Array<number | undefined>): string {
  const present = values.filter((value): value is number => typeof value === "number");
  if (!present.length) return "n/a";
  return (present.reduce((sum, value) => sum + value, 0) / present.length).toFixed(3);
}
