/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
export type OntologyKind =
  | "time.year"
  | "time.quarter"
  | "time.month"
  | "geo.state_au"
  | "demographic.sex"
  | "demographic.age_group"
  | "measure.percent"
  | "measure.count"
  | "measure.rate"
  | "total";

export type OntologyDetection = {
  id: string;
  name: string;
  kind: OntologyKind;
  sheet: string;
  range: string;
  addresses: string[];
  orientation: "row" | "column" | "block";
  confidence: number;
  evidence: string;
  joinKey: boolean;
  sampleValues: string[];
  source?: "deterministic" | "user";
};

export type OntologyAvoidAliasHint = {
  broadName: string;
  prefer: string[];
  ranges: string[];
  reason: string;
};

export type OntologyJoinCandidate = {
  kind: OntologyKind;
  name: string;
  sheet: string;
  range: string;
  confidence: number;
};

export type SheetOntology = {
  version: "0.1";
  sheet: string;
  detections: OntologyDetection[];
  avoidBroadAliases: OntologyAvoidAliasHint[];
  joinCandidates: OntologyJoinCandidate[];
  promptHints: string[];
};
