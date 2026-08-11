// @vitest-environment node

import { describe, expect, it } from "vitest";
import type { CompactContextSnapshot } from "./compact-context";
import {
  buildSemanticMapV13CorrectionPrompt,
  buildSemanticMapV13Prompt,
  SEMANTIC_MAP_V13_CORRECTION_PROMPT_VERSION,
  SEMANTIC_MAP_V13_PROMPT_VERSION,
} from "./prompts-v13-role-aware-semantic-map";
import type { RoleAwareSemanticRegionCatalog } from "./role-aware-region-catalog-v5";
import type { SemanticTableMapV1 } from "./semantic-map-v1";

const context: CompactContextSnapshot = {
  schemaVersion: "cell-role-compact-context-v1",
  digest: "digest",
  bytes: 20,
  characters: 20,
  estimatedTokens: 5,
  addressValueEntries: 4,
  duplicateAddressValueRepresentations: 0,
  serialized:
    '{"schemaVersion":"cell-role-compact-context-v1","sheet":"Sheet 1","grid":"large-context-marker"}',
};
const catalog: RoleAwareSemanticRegionCatalog = {
  version: "semantic-region-catalog-v5-adjacent-year-aware",
  sheet: "Sheet 1",
  omittedCandidateCount: 0,
  observationPanelCount: 1,
  formatFactCount: 2,
  cellDataFactCount: 4,
  candidates: [
    {
      id: "region-001",
      segments: ["R2C2:R3C3"],
      kinds: ["observation-panel"],
      roleHints: ["observations"],
      formatSignatures: [],
      formatting: [],
      selectedCellCount: 4,
      nonblankCount: 4,
      valueLikeCount: 4,
      sample: ["R2C2=1"],
    },
    {
      id: "region-002",
      segments: ["R2C1:R3C1"],
      kinds: ["direct-row-projection-group"],
      roleHints: ["direct-row-candidate"],
      formatSignatures: ["i|in1"],
      formatting: ["italic,indent=1"],
      selectedCellCount: 2,
      nonblankCount: 2,
      valueLikeCount: 0,
      sample: ['R2C1="A"'],
    },
  ],
};
const map: SemanticTableMapV1 = {
  version: "semantic-table-map-v1",
  table: {
    name: "Example",
    values: { name: "Value", regions: ["region-001"] },
    dimensions: [
      {
        name: "Category",
        memberRegions: ["region-002"],
        direction: "W",
      },
    ],
  },
};

describe("role- and format-aware semantic-map V13 prompts", () => {
  it("keeps formatting and geometric uses as evidence while preserving model ownership", () => {
    const prompt = buildSemanticMapV13Prompt(context, catalog);

    expect(prompt).toContain(SEMANTIC_MAP_V13_PROMPT_VERSION);
    expect(prompt).toContain("geometric suggestions, not semantic decisions");
    expect(prompt).toContain(
      "Formatting is structural evidence, not semantic truth",
    );
    expect(prompt).toContain("italic,indent=1");
    expect(prompt).toContain("N (directly above/by column)");
    expect(prompt).toContain("tidy-row coordinate test");
    expect(prompt).toContain("plausible cascading-row and cascading-column");
    expect(prompt).toContain(
      "Numeric-looking coordinates can resemble observations",
    );
    expect(prompt).toContain("1900 through 2099");
    expect(prompt).toContain("local adjacent horizontal or vertical run");
    expect(prompt).toContain("do not infer a year from an isolated");
    expect(prompt).not.toContain("<CellRoleSketch");
  });

  it("uses a compact one-shot correction without repeating the full context", () => {
    const full = buildSemanticMapV13Prompt(context, catalog);
    const correction = buildSemanticMapV13CorrectionPrompt({
      context,
      previousMap: map,
      diagnostics:
        "UNASSIGNED_CASCADING_HEADER_GROUP: region-002 is not assigned",
      correctionCatalog: catalog,
    });

    expect(correction).toContain(SEMANTIC_MAP_V13_CORRECTION_PROMPT_VERSION);
    expect(correction).toContain("exactly one correction opportunity");
    expect(correction).toContain("UNASSIGNED_CASCADING_HEADER_GROUP");
    expect(correction).toContain("region-002");
    expect(correction).not.toContain("large-context-marker");
    expect(correction.length).toBeLessThan(full.length);
  });
});
