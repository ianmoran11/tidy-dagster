import type { PublicationOntology } from "./publicationSchema";

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
  const candidateVariableId = occurrence.representedVariableId ?? binding?.representedVariableId;
  const variable = candidateVariableId
    ? artifact.representedVariables.find((item) => item.id === candidateVariableId)
    : undefined;
  if (!variable) return [];

  const warnings: string[] = [];
  if (
    occurrence.structuralEvidence.unitScale
    && variable.unitScale
    && occurrence.structuralEvidence.unitScale !== variable.unitScale
  ) {
    warnings.push("Unit/scale conflicts with the occurrence structural evidence.");
  }
  if (
    occurrence.structuralEvidence.universe
    && variable.universe
    && occurrence.structuralEvidence.universe !== variable.universe
  ) {
    warnings.push("Universe/population conflicts with the occurrence structural evidence.");
  }
  if (
    occurrence.structuralEvidence.classification
    && variable.valueScheme
    && (
      occurrence.structuralEvidence.classification.valueSchemeId !== variable.valueScheme.valueSchemeId
      || occurrence.structuralEvidence.classification.valueSchemeVersion !== variable.valueScheme.valueSchemeVersion
    )
  ) {
    warnings.push("Classification value-scheme version conflicts with the represented variable.");
  }
  return warnings;
}
