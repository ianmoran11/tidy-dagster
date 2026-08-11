/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
export const RELATIONSHIP_KINDS = [
  "direct-column",
  "direct-row",
  "cascading-column",
  "cascading-row",
] as const;
export type RelationshipKind = (typeof RELATIONSHIP_KINDS)[number];
