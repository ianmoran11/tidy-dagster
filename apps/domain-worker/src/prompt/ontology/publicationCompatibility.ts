/* Ported from TidyCell Phase A snapshot sha256:2628b98976791c1996c0baafb22b2f8c9ee87a03e60b6cf0f4fbc5ff45ce8f4d; MIT, Copyright (c) 2026 Ian Moran. */
import type { PublicationOntology } from "./publicationSchema.js";

/**
 * Returns hard compatibility conflicts for one durable occurrence and its
 * effective represented-variable binding. The function is shared by UI
 * previews and the persistence boundary so an API caller cannot bypass it.
 */
export function compatibilityWarningsForOccurrence(
  artifact: PublicationOntology,
  occurrence: PublicationOntology["occurrenceMappings"][number] | null,
): string[] {
  if (!occurrence || !("structuralEvidence" in occurrence)) return [];
  const binding = artifact.occurrenceVariableBindings.find(
    (item) => item.occurrenceId === occurrence.occurrenceId,
  );
  const candidateVariableId =
    occurrence.representedVariableId ?? binding?.representedVariableId;
  const variable = candidateVariableId
    ? artifact.representedVariables.find(
        (item) => item.id === candidateVariableId,
      )
    : undefined;
  if (!variable) return [];

  const warnings: string[] = [];
  if (
    occurrence.structuralEvidence.unitScale &&
    variable.unitScale &&
    occurrence.structuralEvidence.unitScale !== variable.unitScale
  ) {
    warnings.push(
      "Unit/scale conflicts with the occurrence structural evidence.",
    );
  }
  if (
    occurrence.structuralEvidence.universe &&
    variable.universe &&
    occurrence.structuralEvidence.universe !== variable.universe
  ) {
    warnings.push(
      "Universe/population conflicts with the occurrence structural evidence.",
    );
  }
  if (
    occurrence.structuralEvidence.classification &&
    variable.valueScheme &&
    (occurrence.structuralEvidence.classification.valueSchemeId !==
      variable.valueScheme.valueSchemeId ||
      occurrence.structuralEvidence.classification.valueSchemeVersion !==
        variable.valueScheme.valueSchemeVersion)
  ) {
    warnings.push(
      "Classification value-scheme version conflicts with the represented variable.",
    );
  }
  return warnings;
}
