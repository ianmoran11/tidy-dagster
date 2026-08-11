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
