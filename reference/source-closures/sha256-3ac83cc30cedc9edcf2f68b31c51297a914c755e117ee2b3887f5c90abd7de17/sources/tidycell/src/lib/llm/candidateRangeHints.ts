import {
  CANDIDATE_BLOCK_DETECTOR_VERSION,
  type CandidateBlock,
} from "@/lib/recipe/detectCandidateBlocks";
import type { SheetSummary } from "@/lib/summary/types";

export const CANDIDATE_RANGE_HINT_PROJECTION_VERSION = "tidybank-v1" as const;
export const CANDIDATE_RANGE_HINT_LIMIT = 8;
export const DEFAULT_CANDIDATE_RANGE_HINT_MAX_CHARACTERS = 1_800;

export type CandidateRangeHintMode =
  | "off"
  | typeof CANDIDATE_RANGE_HINT_PROJECTION_VERSION;

export type ProjectedCandidateRangeHint = {
  sheet: string;
  range?: string;
  ranges?: readonly string[];
  signature: string;
  label: string;
};

export type CandidateRangeHintProvenance = {
  detector_version: typeof CANDIDATE_BLOCK_DETECTOR_VERSION;
  hint_projection_version: typeof CANDIDATE_RANGE_HINT_PROJECTION_VERSION;
  mode: CandidateRangeHintMode;
  available_count: number;
  included_count: number;
  omitted_count: number;
  character_count: number;
  maximum_candidates: typeof CANDIDATE_RANGE_HINT_LIMIT;
  maximum_characters: number;
  truncated: boolean;
};

export type CandidateRangeHintProjection = {
  hints: ProjectedCandidateRangeHint[];
  section: string;
  provenance: CandidateRangeHintProvenance;
};

type SheetCandidate = {
  sheet: string;
  candidate: CandidateBlock;
};

const GUIDANCE = [
  "Suggested range hypotheses (tidybank-v1; non-authoritative shadow evidence):",
  "These are fallible local hypotheses. Verify every range and role against the sheet evidence; they are not constraints, approvals, or recipe edits, and must not be copied into RecipeV01.",
].join("\n");

export function projectCandidateRangeHints(
  summaries: readonly Pick<SheetSummary, "sheet" | "candidateBlocks">[],
  mode: CandidateRangeHintMode,
  maximumCharacters = DEFAULT_CANDIDATE_RANGE_HINT_MAX_CHARACTERS,
): CandidateRangeHintProjection {
  const availableCount = summaries.reduce(
    (count, summary) => count + (summary.candidateBlocks?.length ?? 0),
    0,
  );

  if (mode === "off") {
    return {
      hints: [],
      section: "",
      provenance: provenance({
        mode,
        availableCount,
        includedCount: 0,
        characterCount: 0,
        maximumCharacters,
        truncated: false,
      }),
    };
  }

  const topCandidates: SheetCandidate[] = [];
  for (const summary of summaries) {
    for (const candidate of summary.candidateBlocks ?? []) {
      topCandidates.push({ sheet: summary.sheet, candidate });
      if (topCandidates.length === CANDIDATE_RANGE_HINT_LIMIT) break;
    }
    if (topCandidates.length === CANDIDATE_RANGE_HINT_LIMIT) break;
  }
  let hints = topCandidates.map(projectHint);
  let section = buildHintSection(hints, availableCount - hints.length);

  while (section.length > maximumCharacters && hints.length > 0) {
    hints = hints.slice(0, -1);
    section = buildHintSection(hints, availableCount - hints.length);
  }

  if (section.length > maximumCharacters) {
    section = "";
  }

  const omittedCount = availableCount - hints.length;
  return {
    hints,
    section,
    provenance: provenance({
      mode,
      availableCount,
      includedCount: hints.length,
      characterCount: section.length,
      maximumCharacters,
      truncated: omittedCount > 0 || section.length === 0,
    }),
  };
}

function projectHint({
  sheet,
  candidate,
}: SheetCandidate): ProjectedCandidateRangeHint {
  return {
    sheet,
    ...(candidate.ranges.length > 1
      ? { ranges: [...candidate.ranges] }
      : { range: candidate.range }),
    signature: candidate.signatureSummary,
    label: candidate.label,
  };
}

function buildHintSection(
  hints: ProjectedCandidateRangeHint[],
  omittedCount: number,
): string {
  return [
    GUIDANCE,
    JSON.stringify(
      {
        blocks: hints,
        ...(omittedCount === 0 ? {} : { omitted_block_count: omittedCount }),
      },
      null,
      2,
    ),
  ].join("\n");
}

function provenance(options: {
  mode: CandidateRangeHintMode;
  availableCount: number;
  includedCount: number;
  characterCount: number;
  maximumCharacters: number;
  truncated: boolean;
}): CandidateRangeHintProvenance {
  return {
    detector_version: CANDIDATE_BLOCK_DETECTOR_VERSION,
    hint_projection_version: CANDIDATE_RANGE_HINT_PROJECTION_VERSION,
    mode: options.mode,
    available_count: options.availableCount,
    included_count: options.includedCount,
    omitted_count: options.availableCount - options.includedCount,
    character_count: options.characterCount,
    maximum_candidates: CANDIDATE_RANGE_HINT_LIMIT,
    maximum_characters: options.maximumCharacters,
    truncated: options.truncated,
  };
}
