import type {
  OntologyAvoidAliasHint,
  OntologyDetection,
  OntologyJoinCandidate,
  OntologyKind,
  SheetOntology,
} from "./types";

export const ONTOLOGY_ARTIFACT_VERSION = "0.1" as const;

export type OntologyDetectionOverride = {
  detectionId: string;
  canonicalName?: string;
  kind?: OntologyKind;
  joinKey?: boolean;
  rejected?: boolean;
  updatedAt?: string;
};

export type UserOntologyDetectionInput = {
  id?: string;
  name: string;
  kind: OntologyKind;
  sheet: string;
  range: string;
  addresses: string[];
  orientation: OntologyDetection["orientation"];
  confidence?: number;
  evidence?: string;
  joinKey?: boolean;
  sampleValues?: string[];
};

export type OntologyOverrides = {
  detections?: OntologyDetectionOverride[];
  additions?: UserOntologyDetectionInput[];
};

export type ResolvedSheetOntology = SheetOntology & {
  version: typeof ONTOLOGY_ARTIFACT_VERSION;
  deterministicDetections: OntologyDetection[];
  detections: OntologyDetection[];
  rejectedDetections: OntologyDetection[];
  overrides: OntologyOverrides;
};

export type OntologyArtifact = {
  version: typeof ONTOLOGY_ARTIFACT_VERSION;
  artifactVersion: typeof ONTOLOGY_ARTIFACT_VERSION;
  assetId: string;
  sheet: string;
  generatedAt: string;
  deterministicDetections: OntologyDetection[];
  overrides: OntologyOverrides;
  resolvedDetections: OntologyDetection[];
  rejectedDetections: OntologyDetection[];
  avoidBroadAliases: OntologyAvoidAliasHint[];
  joinCandidates: OntologyJoinCandidate[];
  promptHints: string[];
};

export function detectionIdFor(input: {
  sheet: string;
  range: string;
  kind: OntologyKind;
  name: string;
}): string {
  const key = [input.sheet, input.range, input.kind, input.name]
    .map((part) => normalizeIdPart(part))
    .join("|");
  return `det_${fnv1a32(key)}`;
}

export function withDetectionIds(
  detections: OntologyDetection[],
): OntologyDetection[] {
  return detections.map((detection) => ({
    ...detection,
    id: detection.id.trim() ? detection.id : detectionIdFor(detection),
    source: detection.source ?? "deterministic",
  }));
}

export function resolveSheetOntology(
  ontology: SheetOntology,
  overrides: OntologyOverrides = {},
): ResolvedSheetOntology {
  const deterministicDetections = withDetectionIds(ontology.detections);
  const overrideById = new Map(
    (overrides.detections ?? []).map((override) => [override.detectionId, override]),
  );
  const rejectedDetections: OntologyDetection[] = [];
  const resolvedDetections: OntologyDetection[] = [];

  for (const detection of deterministicDetections) {
    const override = overrideById.get(detection.id);

    if (override?.rejected) {
      rejectedDetections.push(detection);
      continue;
    }

    resolvedDetections.push({
      ...detection,
      name: override?.canonicalName ?? detection.name,
      kind: override?.kind ?? detection.kind,
      joinKey: override?.joinKey ?? detection.joinKey,
    });
  }

  for (const addition of overrides.additions ?? []) {
    const detection: OntologyDetection = {
      id: addition.id ?? `usr_${fnv1a32(
        [addition.sheet, addition.range, addition.kind, addition.name]
          .map((part) => normalizeIdPart(part))
          .join("|"),
      )}`,
      name: addition.name,
      kind: addition.kind,
      sheet: addition.sheet,
      range: addition.range,
      addresses: addition.addresses,
      orientation: addition.orientation,
      confidence: addition.confidence ?? 1,
      evidence: addition.evidence ?? "user-defined ontology detection",
      joinKey: addition.joinKey ?? isJoinKeyKind(addition.kind),
      sampleValues: addition.sampleValues ?? [],
      source: "user",
    };
    resolvedDetections.push(detection);
  }

  const joinCandidates = buildJoinCandidates(resolvedDetections);
  const avoidBroadAliases = buildAvoidBroadAliases(resolvedDetections);

  return {
    version: ONTOLOGY_ARTIFACT_VERSION,
    sheet: ontology.sheet,
    deterministicDetections,
    detections: resolvedDetections,
    rejectedDetections,
    overrides,
    avoidBroadAliases,
    joinCandidates,
    promptHints: buildPromptHints(resolvedDetections, avoidBroadAliases),
  };
}

export function createOntologyArtifact({
  assetId,
  ontology,
  overrides = {},
  generatedAt = new Date().toISOString(),
}: {
  assetId: string;
  ontology: SheetOntology;
  overrides?: OntologyOverrides;
  generatedAt?: string;
}): OntologyArtifact {
  const deterministicDetections = withDetectionIds(ontology.detections);
  const resolved = resolveSheetOntology(
    { ...ontology, detections: deterministicDetections },
    overrides,
  );

  return {
    version: ONTOLOGY_ARTIFACT_VERSION,
    artifactVersion: ONTOLOGY_ARTIFACT_VERSION,
    assetId,
    sheet: ontology.sheet,
    generatedAt,
    deterministicDetections,
    overrides,
    resolvedDetections: resolved.detections,
    rejectedDetections: resolved.rejectedDetections,
    avoidBroadAliases: resolved.avoidBroadAliases,
    joinCandidates: resolved.joinCandidates,
    promptHints: resolved.promptHints,
  };
}

export function ontologyFromArtifact(
  artifact: OntologyArtifact,
): SheetOntology {
  return {
    version: ONTOLOGY_ARTIFACT_VERSION,
    sheet: artifact.sheet,
    detections: artifact.resolvedDetections,
    avoidBroadAliases: artifact.avoidBroadAliases,
    joinCandidates: artifact.joinCandidates,
    promptHints: artifact.promptHints,
  };
}

function buildJoinCandidates(
  detections: OntologyDetection[],
): OntologyJoinCandidate[] {
  return detections
    .filter((detection) => detection.joinKey)
    .map((detection) => ({
      kind: detection.kind,
      name: detection.name,
      sheet: detection.sheet,
      range: detection.range,
      confidence: detection.confidence,
    }));
}

function buildAvoidBroadAliases(
  detections: OntologyDetection[],
): OntologyAvoidAliasHint[] {
  const temporal = detections.filter((detection) =>
    ["time.year", "time.quarter", "time.month"].includes(detection.kind),
  );
  const hasSpecificTemporal = new Set(temporal.map((detection) => detection.name));

  if (hasSpecificTemporal.size < 2) {
    return [];
  }

  return [
    {
      broadName: "period",
      prefer: [...hasSpecificTemporal].sort(),
      ranges: temporal.map((detection) => detection.range),
      reason:
        "Resolved ontology has separate specific temporal dimensions; avoid assigning these cells to an overlapping broad period header.",
    },
  ];
}

function buildPromptHints(
  detections: OntologyDetection[],
  avoidBroadAliases: OntologyAvoidAliasHint[],
): string[] {
  const hints = detections.slice(0, 12).map((detection) =>
    `${detection.range}: likely ${detection.name} (${detection.kind}, ${Math.round(
      detection.confidence * 100,
    )}% confidence; ${detection.evidence}).`,
  );

  for (const alias of avoidBroadAliases) {
    hints.push(
      `Prefer ${alias.prefer.join(" + ")} over broad '${alias.broadName}' for ${alias.ranges.join(", ")}; keep these header variables mutually exclusive.`,
    );
  }

  if (detections.some((detection) => detection.joinKey)) {
    hints.push(
      "Ontology join candidates are reusable dimensions for cross-spreadsheet joins; preserve their specific names rather than collapsing them into generic labels.",
    );
  }

  return hints;
}

function isJoinKeyKind(kind: OntologyKind): boolean {
  return [
    "time.year",
    "time.quarter",
    "time.month",
    "geo.state_au",
    "demographic.sex",
    "demographic.age_group",
  ].includes(kind);
}

function normalizeIdPart(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function fnv1a32(value: string): string {
  let hash = 0x811c9dc5;

  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }

  return hash.toString(36).padStart(7, "0");
}
