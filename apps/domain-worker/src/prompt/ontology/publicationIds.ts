/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
export const PUBLICATION_ID_PREFIXES = [
  "publisher",
  "publication",
  "concept",
  "variable",
  "value_scheme",
  "value",
  "hierarchy",
  "occurrence",
] as const;

export type PublicationIdPrefix = (typeof PUBLICATION_ID_PREFIXES)[number];
export type PublicationEntityId = `${PublicationIdPrefix}_${string}`;

const ID_PATTERN =
  /^(publisher|publication|concept|variable|value_scheme|value|hierarchy|occurrence)_[a-z0-9]{8,32}$/;

/**
 * IDs deliberately contain no display labels, paths, sheet names, or ranges.
 * Callers must supply only durable registry, publisher, or edition identifiers.
 */
export function stablePublicationEntityId(
  prefix: PublicationIdPrefix,
  stableParts: readonly string[],
): PublicationEntityId {
  if (stableParts.length === 0 || stableParts.some((part) => !part.trim())) {
    throw new Error(
      "Stable publication entity IDs require at least one non-empty durable part.",
    );
  }

  return `${prefix}_${fnv1a32(stableParts.map(normalizeStablePart).join("\u001f"))}`;
}

export function publisherIdFor(
  authority: string,
  registryId: string,
): PublicationEntityId {
  return stablePublicationEntityId("publisher", [authority, registryId]);
}

export function publicationIdFor(
  publisherId: string,
  durablePublicationId: string,
): PublicationEntityId {
  return stablePublicationEntityId("publication", [
    publisherId,
    durablePublicationId,
  ]);
}

export function conceptIdFor(
  ownerId: string,
  durableConceptId: string,
): PublicationEntityId {
  return stablePublicationEntityId("concept", [ownerId, durableConceptId]);
}

/** Stable ID for a publisher-owned external concept scheme. */
export function externalConceptSchemeIdFor(
  authority: string,
  durableSchemeId: string,
): `concept_scheme_${string}` {
  const conceptId = stablePublicationEntityId("concept", [
    authority,
    durableSchemeId,
  ]);
  return `concept_scheme_${conceptId.slice("concept_".length)}`;
}

export function variableIdFor(
  ownerId: string,
  durableVariableId: string,
): PublicationEntityId {
  return stablePublicationEntityId("variable", [ownerId, durableVariableId]);
}

export function valueSchemeIdFor(
  ownerId: string,
  durableSchemeId: string,
): PublicationEntityId {
  return stablePublicationEntityId("value_scheme", [ownerId, durableSchemeId]);
}

/**
 * Builds a canonical-value identity from a stable scheme identity and durable
 * publisher/registry member identity. Do not pass a scheme version or mutable
 * display label; a code is suitable only when its owner guarantees stability.
 */
export function canonicalValueIdFor(
  valueSchemeId: string,
  durableMemberId: string,
): PublicationEntityId {
  return stablePublicationEntityId("value", [valueSchemeId, durableMemberId]);
}

export function hierarchyIdFor(
  ownerId: string,
  durableHierarchyId: string,
): PublicationEntityId {
  return stablePublicationEntityId("hierarchy", [ownerId, durableHierarchyId]);
}

export function occurrenceIdFor(
  publicationId: string,
  workbookEditionId: string,
  durableOccurrenceId: string,
): PublicationEntityId {
  return stablePublicationEntityId("occurrence", [
    publicationId,
    workbookEditionId,
    durableOccurrenceId,
  ]);
}

export function isPublicationEntityId(
  value: string,
  prefix?: PublicationIdPrefix,
): value is PublicationEntityId {
  if (!ID_PATTERN.test(value)) return false;
  return prefix ? value.startsWith(`${prefix}_`) : true;
}

export function assertPublicationEntityId(
  value: string,
  prefix?: PublicationIdPrefix,
): asserts value is PublicationEntityId {
  if (!isPublicationEntityId(value, prefix)) {
    throw new Error(
      `Invalid publication ontology ID${prefix ? ` for ${prefix}` : ""}: ${value}`,
    );
  }
}

function normalizeStablePart(value: string): string {
  return value.normalize("NFKC").trim().toLowerCase();
}

function fnv1a32(value: string): string {
  let hash = 0x811c9dc5;

  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }

  return hash.toString(36).padStart(8, "0");
}
