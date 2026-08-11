/**
 * Versioned, deliberately conservative text normalization for canonical-value
 * lookup. It never removes internal punctuation or expands abbreviations; those
 * transformations must be explicitly approved in a value-scheme dictionary.
 */
export const CANONICAL_VALUE_NORMALIZATION_VERSION = "1.0.0" as const;

export type ValueNormalizationOptions = {
  trim?: boolean;
  collapseWhitespace?: boolean;
  caseFold?: boolean;
  stripTerminalPeriods?: boolean;
};

export const CONSERVATIVE_VALUE_NORMALIZATION: Required<ValueNormalizationOptions> = {
  trim: true,
  collapseWhitespace: true,
  caseFold: true,
  // A terminal full stop is common in explicit abbreviations such as "Jan." or
  // "Aust.". No other punctuation is removed without a dictionary entry.
  stripTerminalPeriods: true,
};

export type NormalizedValue = {
  value: string;
  version: typeof CANONICAL_VALUE_NORMALIZATION_VERSION;
  appliedRules: string[];
};

export function normalizeCanonicalValue(
  rawValue: string,
  options: ValueNormalizationOptions = CONSERVATIVE_VALUE_NORMALIZATION,
): NormalizedValue {
  const effective = { ...CONSERVATIVE_VALUE_NORMALIZATION, ...options };
  let value = rawValue.normalize("NFKC");
  const appliedRules = ["unicode_nfkc"];

  if (effective.trim) {
    value = value.trim();
    appliedRules.push("trim");
  }
  if (effective.collapseWhitespace) {
    value = value.replace(/\s+/gu, " ");
    appliedRules.push("collapse_whitespace");
  }
  if (effective.stripTerminalPeriods && /\.+$/u.test(value)) {
    const withoutPeriods = value.replace(/\.+$/u, "");
    // Preserve punctuation-only cells verbatim so an abstention has a
    // reversible, schema-valid normalized representation.
    if (withoutPeriods) {
      value = withoutPeriods;
      appliedRules.push("strip_terminal_periods");
    }
  }
  if (effective.caseFold) {
    // ECMAScript lacks a full Unicode case-fold API. The language-neutral lower
    // form plus the two common fold-only forms keeps this deterministic while
    // remaining conservative: unsupported scripts simply abstain.
    value = value
      .toLocaleLowerCase("und")
      .replace(/\u00df/gu, "ss")
      .replace(/\u03c2/gu, "\u03c3");
    appliedRules.push("unicode_case_fold");
  }

  return { value, version: CANONICAL_VALUE_NORMALIZATION_VERSION, appliedRules };
}

export function exactCanonicalValueText(rawValue: string): string {
  return rawValue.normalize("NFKC").trim();
}
