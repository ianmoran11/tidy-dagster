import type { ExecutionResult, OutputScalar, TidyOutputRow } from "@/lib/executor/types";
import {
  safeParsePublicationOntology,
  type PublicationOntology,
} from "@/lib/ontology/publicationSchema";
import {
  CANONICAL_VALUE_MAPPER_ID,
  CANONICAL_VALUE_MAPPER_VERSION,
  mapCanonicalValue,
  reportCanonicalValueMappings,
  type CanonicalValueMappingContext,
  type CanonicalValueMappingEvaluationCase,
  type CanonicalValueMappingEvidence,
  type CanonicalValueMappingReport,
  type CanonicalValueMappingRequest,
  type RawValueMapping as AutomaticRawValueMapping,
} from "@/lib/ontology/canonicalValueMapping";

/** Explicit opt-in modes; `raw` deliberately preserves the existing export contract. */
export type OntologyExportMode =
  | "raw"
  | "raw_and_canonical"
  | "canonical_with_raw_audit";

/**
 * Pins an enrichment to the exact schema and semantic snapshot it was authored
 * against. A mismatch is a soft failure: consumers receive unchanged raw rows.
 */
export type PublicationOntologyVersionPin = {
  publicationId: string;
  artifactVersion: "0.2";
  ontologyVersion: string;
};

const issuedAutomaticMappingPolicies = new WeakSet<object>();

/** Created only by `createAutomaticMappingPolicy`, which recomputes PRD-006 evidence and outcomes. */
export type AutomaticMappingPolicy = {
  readonly version: string;
  readonly promotionReport: CanonicalValueMappingReport;
  readonly qualifiedMappings: readonly AutomaticRawValueMapping[];
};

export function createAutomaticMappingPolicy({
  version,
  mappingContext,
  evaluationCases,
  evidence,
  requests,
}: {
  version: string;
  mappingContext: CanonicalValueMappingContext;
  evaluationCases: CanonicalValueMappingEvaluationCase[];
  evidence: CanonicalValueMappingEvidence;
  requests: CanonicalValueMappingRequest[];
}): AutomaticMappingPolicy {
  const promotionReport = reportCanonicalValueMappings(mappingContext, evaluationCases, evidence);
  const qualifiedMappings = isPromotionReportEligible(promotionReport)
    ? requests
        .map((request) => mapCanonicalValue(mappingContext, request).mapping)
        .filter((mapping) => mapping.reviewStatus === "automatic" && ["exact", "alias"].includes(mapping.relation))
    : [];
  const policy: AutomaticMappingPolicy = deepFreeze({
    version,
    promotionReport,
    qualifiedMappings,
  });
  issuedAutomaticMappingPolicies.add(policy);
  return policy;
}

export type OntologyEnrichmentContext = {
  assetId: string;
  workbookEditionId: string;
  /** Locale and temporal context are explicit; mappings never cross them implicitly. */
  language?: string;
  effectiveAt?: string;
  /** Explicit recipe value field by table, when an occurrence is value-cell scoped. */
  valueFieldByTable?: Record<string, string>;
  pin: PublicationOntologyVersionPin;
  automaticMappingPolicy?: AutomaticMappingPolicy;
};

export type OntologyEnrichmentWarning = {
  code:
    | "INVALID_ONTOLOGY_PROFILE"
    | "STALE_ONTOLOGY_PROFILE"
    | "AMBIGUOUS_OCCURRENCE"
    | "MISSING_APPROVED_OCCURRENCE"
    | "MISSING_APPROVED_VALUE_MAPPING"
    | "MISSING_CANONICAL_VALUE";
  message: string;
  table?: string;
  field?: string;
  address?: string;
};

export type EnrichedFieldBinding = {
  occurrenceId: string;
  representedVariableId: string;
  representedVariableVersion: string;
  valueSchemeId?: string;
  valueSchemeVersion?: string;
  canonicalValueId?: string;
  canonicalValueVersion?: string;
  canonicalValueCode?: string;
  canonicalValueLabel?: string;
  mappingId?: string;
  mappingReviewStatus?: string;
  mappingMethod?: string;
  mappingMethodVersion?: string;
  mappingEvidence?: string[];
  mappingProvenanceSourceId?: string;
  mappingProvenanceSourceType?: string;
  mappingProvenanceRecordedAt?: string;
  sourceAddress: string;
};

export type EnrichedOutputRow = {
  raw: TidyOutputRow;
  fields: Record<string, EnrichedFieldBinding>;
};

export type CanonicalColumnSet = {
  representedVariableId: string;
  representedVariableVersion: string;
  valueSchemeId: string;
  valueSchemeVersion: string;
  canonicalValueId: string;
  canonicalValueVersion: string;
  canonicalValueCode: string;
  canonicalValueLabel: string;
  mappingId: string;
  mappingReviewStatus: string;
  mappingMethod: string;
  mappingMethodVersion: string;
  mappingEvidence: string;
  mappingProvenanceSourceId: string;
  mappingProvenanceSourceType: string;
  mappingProvenanceRecordedAt: string;
  sourceAddress: string;
  profileId: string;
  profileOntologyVersion: string;
  artifactVersion: string;
  automaticMappingPolicyVersion: string;
  automaticMapperId: string;
  automaticMapperVersion: string;
  automaticPromotionLowerBound: string;
  exportMode: string;
};

export type EnrichedOutputTable = {
  table: string;
  sheet: string;
  rows: EnrichedOutputRow[];
  canonicalColumns: Record<string, CanonicalColumnSet>;
};

export type OntologyEnrichmentMetadata = {
  mode: OntologyExportMode;
  profile: PublicationOntologyVersionPin;
  automaticMappingPolicyVersion?: string;
  automaticMappingPromotion?: {
    mapperId: string;
    mapperVersion: string;
    status: "eligible_for_promotion";
    threshold: number;
    oneSided95LowerBound: number;
  };
  /** Field bindings are sidecar data, independent of CSV shape. */
  semanticBindings: Array<{
    table: string;
    field: string;
    occurrenceId: string;
    representedVariableId: string;
    valueSchemeId?: string;
    valueSchemeVersion?: string;
    canonicalValueId?: string;
    mappingId?: string;
    mappingProvenanceSourceId?: string;
    mappingProvenanceSourceType?: string;
    mappingProvenanceRecordedAt?: string;
  }>;
  canonicalColumns: Record<string, CanonicalColumnSet>;
};

export type OntologyEnrichmentResult = {
  /** The untouched executor result remains the raw/default export source. */
  raw: ExecutionResult;
  tables: EnrichedOutputTable[];
  warnings: OntologyEnrichmentWarning[];
  metadata: OntologyEnrichmentMetadata | null;
};

export type ExportFlatRow = Record<string, OutputScalar>;

/**
 * Pure post-extraction sidecar enrichment. It never mutates recipe output,
 * guesses from labels, or lets proposed/rejected ontology records transform a
 * row. Source-address and edition matching are intentionally exact.
 */
export function enrichRecipeOutputWithOntology({
  output,
  ontology,
  context,
  mode = "raw",
}: {
  output: ExecutionResult;
  ontology: unknown;
  context: OntologyEnrichmentContext;
  mode?: OntologyExportMode;
}): OntologyEnrichmentResult {
  const parsed = safeParsePublicationOntology(ontology);
  if (!parsed.success) {
    return rawFallback(output, mode, {
      code: "INVALID_ONTOLOGY_PROFILE",
      message: "Ignoring invalid publication ontology profile; exporting raw output.",
    });
  }
  const artifact = parsed.data;
  if (!matchesPin(artifact, context.pin)) {
    return rawFallback(output, mode, {
      code: "STALE_ONTOLOGY_PROFILE",
      message: "Pinned publication ontology version does not match the supplied profile; exporting raw output.",
    });
  }

  const warnings: OntologyEnrichmentWarning[] = [];
  const warningKeys = new Set<string>();
  const warn = (warning: OntologyEnrichmentWarning) => {
    const key = [warning.code, warning.table ?? "", warning.field ?? "", warning.address ?? ""].join("\u001f");
    if (!warningKeys.has(key)) {
      warningKeys.add(key);
      warnings.push(warning);
    }
  };

  const occurrencesByAddress = indexApprovedOccurrences(artifact, context);
  const canonicalValues = new Map<string, PublicationOntology["canonicalValues"][number]>(
    artifact.canonicalValues.map((value) => [value.id, value]),
  );
  const mappingsByVariableAndValue = indexApprovedMappings(artifact, context, canonicalValues);

  const tables: EnrichedOutputTable[] = output.tables.map((table) => {
    const fields = rawFields(table.rows);
    const canonicalColumns = allocateCanonicalColumns(fields, new Set(fields));
    const rows = table.rows.map((raw) => {
      const bindings: Record<string, EnrichedFieldBinding> = {};
      for (const field of fields) {
        const sourceAddress = sourceAddressFor(raw, field, table.table, context);
        if (!sourceAddress) continue;
        const occurrenceMatches = occurrencesByAddress.get(`${table.sheet}\u001f${sourceAddress}`) ?? [];
        if (occurrenceMatches.length === 0) {
          warn({
            code: "MISSING_APPROVED_OCCURRENCE",
            message: "No approved durable occurrence binding matches this source address.",
            table: table.table,
            field,
            address: sourceAddress,
          });
          continue;
        }
        if (occurrenceMatches.length !== 1) {
          warn({
            code: "AMBIGUOUS_OCCURRENCE",
            message: "Multiple approved durable occurrences match this source address; leaving it raw.",
            table: table.table,
            field,
            address: sourceAddress,
          });
          continue;
        }
        const occurrence = occurrenceMatches[0];
        const variable = artifact.representedVariables.find((item) => item.id === occurrence.representedVariableId);
        if (!variable) continue;

        const binding: EnrichedFieldBinding = {
          occurrenceId: occurrence.occurrenceId,
          representedVariableId: variable.id,
          representedVariableVersion: variable.version,
          valueSchemeId: variable.valueScheme?.valueSchemeId,
          valueSchemeVersion: variable.valueScheme?.valueSchemeVersion,
          sourceAddress,
        };
        const rawValue = raw[field];
        if (typeof rawValue !== "object" && rawValue !== null && rawValue !== undefined && variable.valueScheme) {
          const mappingKey = mappingLookupKey(variable.id, String(rawValue));
          const mappings = mappingsByVariableAndValue.get(mappingKey) ?? [];
          if (mappings.length !== 1) {
            warn({
              code: "MISSING_APPROVED_VALUE_MAPPING",
              message: mappings.length > 1
                ? "Multiple usable canonical mappings match this raw value; leaving it raw."
                : "No approved or policy-qualified automatic canonical mapping matches this raw value.",
              table: table.table,
              field,
              address: sourceAddress,
            });
          } else {
            const mapping = mappings[0];
            const canonical = mapping.canonicalValueId ? canonicalValues.get(mapping.canonicalValueId) : undefined;
            if (!canonical || !isCanonicalValidAt(canonical, context.effectiveAt)) {
              warn({
                code: "MISSING_CANONICAL_VALUE",
                message: "The selected canonical mapping has no canonical value valid for this export context; leaving it raw.",
                table: table.table,
                field,
                address: sourceAddress,
              });
            } else {
              Object.assign(binding, {
                canonicalValueId: canonical.id,
                canonicalValueVersion: canonical.version,
                canonicalValueCode: canonical.code,
                canonicalValueLabel: preferredLabel(canonical.preferredLabels),
                mappingId: mapping.id,
                mappingReviewStatus: mapping.reviewStatus,
                mappingMethod: mapping.normalizationMethod,
                mappingMethodVersion: mapping.normalizationMethodVersion,
                mappingEvidence: [...mapping.evidence].sort(),
                mappingProvenanceSourceId: mapping.provenance.sourceId,
                mappingProvenanceSourceType: mapping.provenance.sourceType,
                mappingProvenanceRecordedAt: mapping.provenance.recordedAt,
              });
            }
          }
        }
        bindings[field] = binding;
      }
      return { raw, fields: bindings };
    });
    return { table: table.table, sheet: table.sheet, rows, canonicalColumns };
  });

  const metadata: OntologyEnrichmentMetadata = {
    mode,
    profile: context.pin,
    ...(context.automaticMappingPolicy ? { automaticMappingPolicyVersion: context.automaticMappingPolicy.version } : {}),
    ...(context.automaticMappingPolicy && isAutomaticPolicyEligible(context.automaticMappingPolicy)
      ? {
          automaticMappingPromotion: {
            mapperId: context.automaticMappingPolicy.promotionReport.mapper.id,
            mapperVersion: context.automaticMappingPolicy.promotionReport.mapper.version,
            status: "eligible_for_promotion" as const,
            threshold: context.automaticMappingPolicy.promotionReport.promotion.threshold,
            oneSided95LowerBound: context.automaticMappingPolicy.promotionReport.promotion.oneSided95LowerBound!,
          },
        }
      : {}),
    semanticBindings: tables
      .flatMap((table) => table.rows.flatMap((row) => Object.entries(row.fields).map(([field, binding]) => ({
        table: table.table,
        field,
        occurrenceId: binding.occurrenceId,
        representedVariableId: binding.representedVariableId,
        valueSchemeId: binding.valueSchemeId,
        valueSchemeVersion: binding.valueSchemeVersion,
        canonicalValueId: binding.canonicalValueId,
        mappingId: binding.mappingId,
        mappingProvenanceSourceId: binding.mappingProvenanceSourceId,
        mappingProvenanceSourceType: binding.mappingProvenanceSourceType,
        mappingProvenanceRecordedAt: binding.mappingProvenanceRecordedAt,
      }))))
      .sort((a, b) => [a.table, a.field, a.occurrenceId].join("\u001f").localeCompare([b.table, b.field, b.occurrenceId].join("\u001f"))),
    canonicalColumns: Object.fromEntries(
      tables.flatMap((table) => Object.entries(table.canonicalColumns).map(
        ([field, columns]) => [`${table.table}\u001f${field}`, columns] as const,
      ))
        .sort(([a], [b]) => a.localeCompare(b)),
    ),
  };
  return { raw: output, tables, warnings: warnings.sort(compareWarnings), metadata };
}

/** Produces flat, collision-safe rows for the requested explicit export mode. */
export function enrichedRowsForExport(
  table: EnrichedOutputTable,
  mode: OntologyExportMode,
  metadata: OntologyEnrichmentMetadata | null,
): ExportFlatRow[] {
  if (mode === "raw") return table.rows.map((row) => flattenRawRow(row.raw));
  return table.rows.map((row) => {
    const raw = flattenRawRow(row.raw);
    const canonical: ExportFlatRow = {};
    for (const [field, columns] of Object.entries(table.canonicalColumns).sort(([a], [b]) => a.localeCompare(b))) {
      const binding = row.fields[field];
      canonical[columns.representedVariableId] = binding?.representedVariableId ?? null;
      canonical[columns.representedVariableVersion] = binding?.representedVariableVersion ?? null;
      canonical[columns.valueSchemeId] = binding?.valueSchemeId ?? null;
      canonical[columns.valueSchemeVersion] = binding?.valueSchemeVersion ?? null;
      canonical[columns.canonicalValueId] = binding?.canonicalValueId ?? null;
      canonical[columns.canonicalValueVersion] = binding?.canonicalValueVersion ?? null;
      canonical[columns.canonicalValueCode] = binding?.canonicalValueCode ?? null;
      canonical[columns.canonicalValueLabel] = binding?.canonicalValueLabel ?? null;
      canonical[columns.mappingId] = binding?.mappingId ?? null;
      canonical[columns.mappingReviewStatus] = binding?.mappingReviewStatus ?? null;
      canonical[columns.mappingMethod] = binding?.mappingMethod ?? null;
      canonical[columns.mappingMethodVersion] = binding?.mappingMethodVersion ?? null;
      canonical[columns.mappingEvidence] = binding?.mappingEvidence?.join(" | ") ?? null;
      canonical[columns.mappingProvenanceSourceId] = binding?.mappingProvenanceSourceId ?? null;
      canonical[columns.mappingProvenanceSourceType] = binding?.mappingProvenanceSourceType ?? null;
      canonical[columns.mappingProvenanceRecordedAt] = binding?.mappingProvenanceRecordedAt ?? null;
      canonical[columns.sourceAddress] = binding?.sourceAddress ?? sourceAddressFor(row.raw, field) ?? null;
      canonical[columns.profileId] = metadata?.profile.publicationId ?? null;
      canonical[columns.profileOntologyVersion] = metadata?.profile.ontologyVersion ?? null;
      canonical[columns.artifactVersion] = metadata?.profile.artifactVersion ?? null;
      canonical[columns.automaticMappingPolicyVersion] = metadata?.automaticMappingPolicyVersion ?? null;
      canonical[columns.automaticMapperId] = metadata?.automaticMappingPromotion?.mapperId ?? null;
      canonical[columns.automaticMapperVersion] = metadata?.automaticMappingPromotion?.mapperVersion ?? null;
      canonical[columns.automaticPromotionLowerBound] = metadata?.automaticMappingPromotion?.oneSided95LowerBound ?? null;
      canonical[columns.exportMode] = mode;
    }
    return mode === "raw_and_canonical" ? { ...raw, ...canonical } : { ...canonical, ...raw };
  });
}

function rawFallback(
  output: ExecutionResult,
  mode: OntologyExportMode,
  warning: OntologyEnrichmentWarning,
): OntologyEnrichmentResult {
  return {
    raw: output,
    tables: output.tables.map((table) => ({
      table: table.table,
      sheet: table.sheet,
      rows: table.rows.map((raw) => ({ raw, fields: {} })),
      canonicalColumns: {},
    })),
    warnings: [warning],
    metadata: null,
  };
}

function matchesPin(artifact: PublicationOntology, pin: PublicationOntologyVersionPin): boolean {
  return artifact.profile.id === pin.publicationId
    && artifact.artifactVersion === pin.artifactVersion
    && artifact.profile.ontologyVersion === pin.ontologyVersion;
}

function indexApprovedOccurrences(artifact: PublicationOntology, context: OntologyEnrichmentContext) {
  const index = new Map<string, Array<{ occurrenceId: string; representedVariableId: string }>>();
  for (const occurrence of artifact.occurrenceMappings) {
    if (!("structuralSignatureVersion" in occurrence) || !("rawDetectionIds" in occurrence)) continue;
    if (occurrence.reviewStatus !== "approved"
      || !occurrence.representedVariableId
      || occurrence.publicationId !== context.pin.publicationId
      || occurrence.workbookEditionId !== context.workbookEditionId
      || occurrence.sourceLocation.assetId !== context.assetId) continue;
    const representedVariableId = occurrence.representedVariableId;
    for (const address of occurrence.sourceLocation.addresses) {
      const key = `${occurrence.sourceLocation.sheetName}\u001f${address}`;
      const matches = index.get(key) ?? [];
      matches.push({ occurrenceId: occurrence.occurrenceId, representedVariableId });
      index.set(key, matches);
    }
  }
  return index;
}

function indexApprovedMappings(
  artifact: PublicationOntology,
  context: OntologyEnrichmentContext,
  canonicalValues: Map<string, PublicationOntology["canonicalValues"][number]>,
) {
  const index = new Map<string, UsableMapping[]>();
  const representedVariables = new Map<string, PublicationOntology["representedVariables"][number]>(
    artifact.representedVariables.map((variable) => [variable.id, variable]),
  );
  const add = (mapping: UsableMapping) => {
    const canonical = mapping.canonicalValueId ? canonicalValues.get(mapping.canonicalValueId) : undefined;
    const variable = representedVariables.get(mapping.representedVariableId);
    if (mapping.publicationId !== context.pin.publicationId
      || !mapping.canonicalValueId
      || !variable?.valueScheme
      || variable.valueScheme.valueSchemeId !== mapping.valueScheme.valueSchemeId
      || variable.valueScheme.valueSchemeVersion !== mapping.valueScheme.valueSchemeVersion
      || canonical?.valueScheme.valueSchemeId !== mapping.valueScheme.valueSchemeId
      || canonical?.valueScheme.valueSchemeVersion !== mapping.valueScheme.valueSchemeVersion
      || mapping.relation === "unmapped"
      || (mapping.rawLanguage !== undefined && mapping.rawLanguage !== context.language)
      || (mapping.effectiveAt !== undefined && mapping.effectiveAt !== context.effectiveAt)
      || !canonical
      || !isCanonicalValidAt(canonical, context.effectiveAt)) return;
    const key = mappingLookupKey(mapping.representedVariableId, mapping.rawValue);
    const matches = index.get(key) ?? [];
    matches.push(mapping);
    index.set(key, matches);
  };
  for (const mapping of artifact.rawValueMappings) {
    if (mapping.reviewStatus === "approved") add(mapping);
  }
  const policy = context.automaticMappingPolicy;
  if (policy && isAutomaticPolicyEligible(policy)) {
    for (const mapping of policy.qualifiedMappings) add(mapping);
  }
  return index;
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    for (const nested of Object.values(value)) deepFreeze(nested);
    Object.freeze(value);
  }
  return value;
}

function isAutomaticPolicyEligible(policy: AutomaticMappingPolicy): boolean {
  return issuedAutomaticMappingPolicies.has(policy)
    && isPromotionReportEligible(policy.promotionReport);
}

function isPromotionReportEligible(report: CanonicalValueMappingReport): boolean {
  return report.mapper.id === CANONICAL_VALUE_MAPPER_ID
    && report.mapper.version === CANONICAL_VALUE_MAPPER_VERSION
    && report.evidence.sufficient
    && report.promotion.status === "eligible_for_promotion"
    && report.promotion.threshold >= 0.995
    && report.promotion.oneSided95LowerBound !== null
    && report.promotion.oneSided95LowerBound >= report.promotion.threshold;
}

function isCanonicalValidAt(
  value: PublicationOntology["canonicalValues"][number],
  effectiveAt: string | undefined,
): boolean {
  if (value.status === "deprecated" && (!effectiveAt || (!value.validFrom && !value.validTo))) return false;
  if ((value.validFrom || value.validTo) && !effectiveAt) return false;
  return (!value.validFrom || value.validFrom <= effectiveAt!)
    && (!value.validTo || value.validTo >= effectiveAt!);
}

type UsableMapping = {
  id: string;
  publicationId: string;
  representedVariableId: string;
  valueScheme: { valueSchemeId: string; valueSchemeVersion: string };
  rawValue: string;
  rawLanguage?: string;
  effectiveAt?: string;
  canonicalValueId?: string;
  relation: "exact" | "alias" | "close" | "broader" | "narrower" | "unmapped";
  normalizationMethod: string;
  normalizationMethodVersion: string;
  evidence: string[];
  reviewStatus: string;
  provenance: AutomaticRawValueMapping["provenance"];
};

function mappingLookupKey(representedVariableId: string, rawValue: string): string {
  return `${representedVariableId}\u001f${rawValue.normalize("NFKC")}`;
}

function rawFields(rows: TidyOutputRow[]): string[] {
  return [...new Set(rows.flatMap((row) => Object.keys(row).filter((key) => key !== "_source" && !key.endsWith("_source"))))]
    .sort((a, b) => a.localeCompare(b));
}

function sourceAddressFor(
  row: TidyOutputRow,
  field: string,
  table?: string,
  context?: OntologyEnrichmentContext,
): string | undefined {
  const headerSource = row[`${field}_source`];
  if (typeof headerSource === "string") return headerSource;
  // A value-cell address is only meaningful for a caller-designated value field;
  // never apply one value cell's occurrence to unrelated output columns.
  if (table && context?.valueFieldByTable?.[table] === field) return row._source?.address;
  return undefined;
}

function flattenRawRow(row: TidyOutputRow): ExportFlatRow {
  const result: ExportFlatRow = {};
  for (const [key, value] of Object.entries(row)) {
    if (key === "_source") continue;
    if (typeof value !== "object" && value !== undefined) result[key] = value;
  }
  if (row._source) {
    result["_source.sheet"] = row._source.sheet;
    result["_source.address"] = row._source.address;
    result["_source.row"] = row._source.row;
    result["_source.col"] = row._source.col;
  }
  return result;
}

function allocateCanonicalColumns(fields: string[], existingColumns: Set<string>): Record<string, CanonicalColumnSet> {
  const result: Record<string, CanonicalColumnSet> = {};
  for (const field of [...fields].sort((a, b) => a.localeCompare(b))) {
    const prefix = `__tidycell_ontology_${fieldToken(field)}`;
    const allocate = (suffix: string) => uniqueColumn(`${prefix}_${suffix}`, existingColumns);
    result[field] = {
      representedVariableId: allocate("represented_variable_id"),
      representedVariableVersion: allocate("represented_variable_version"),
      valueSchemeId: allocate("value_scheme_id"),
      valueSchemeVersion: allocate("value_scheme_version"),
      canonicalValueId: allocate("canonical_value_id"),
      canonicalValueVersion: allocate("canonical_value_version"),
      canonicalValueCode: allocate("canonical_value_code"),
      canonicalValueLabel: allocate("canonical_value_label"),
      mappingId: allocate("mapping_id"),
      mappingReviewStatus: allocate("mapping_review_status"),
      mappingMethod: allocate("mapping_method"),
      mappingMethodVersion: allocate("mapping_method_version"),
      mappingEvidence: allocate("mapping_evidence"),
      mappingProvenanceSourceId: allocate("mapping_provenance_source_id"),
      mappingProvenanceSourceType: allocate("mapping_provenance_source_type"),
      mappingProvenanceRecordedAt: allocate("mapping_provenance_recorded_at"),
      sourceAddress: allocate("source_address"),
      profileId: allocate("profile_id"),
      profileOntologyVersion: allocate("profile_ontology_version"),
      artifactVersion: allocate("artifact_version"),
      automaticMappingPolicyVersion: allocate("automatic_mapping_policy_version"),
      automaticMapperId: allocate("automatic_mapper_id"),
      automaticMapperVersion: allocate("automatic_mapper_version"),
      automaticPromotionLowerBound: allocate("automatic_promotion_lower_bound"),
      exportMode: allocate("export_mode"),
    };
  }
  return result;
}

function uniqueColumn(base: string, existing: Set<string>): string {
  let candidate = base;
  let index = 2;
  while (existing.has(candidate)) candidate = `${base}_${index++}`;
  existing.add(candidate);
  return candidate;
}

function fieldToken(field: string): string {
  const readable = field.normalize("NFKC").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 24) || "field";
  let hash = 2166136261;
  for (const char of field) hash = Math.imul(hash ^ char.codePointAt(0)!, 16777619);
  return `${readable}_${(hash >>> 0).toString(36)}`;
}

function preferredLabel(labels: Array<{ language: string; value: string }>): string {
  return [...labels].sort((a, b) => a.language.localeCompare(b.language) || a.value.localeCompare(b.value))[0]?.value ?? "";
}

function compareWarnings(a: OntologyEnrichmentWarning, b: OntologyEnrichmentWarning): number {
  return [a.code, a.table ?? "", a.field ?? "", a.address ?? ""].join("\u001f")
    .localeCompare([b.code, b.table ?? "", b.field ?? "", b.address ?? ""].join("\u001f"));
}
