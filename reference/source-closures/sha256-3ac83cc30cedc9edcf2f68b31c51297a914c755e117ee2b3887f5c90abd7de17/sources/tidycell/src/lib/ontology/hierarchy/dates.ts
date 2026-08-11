const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** Rejects impossible calendar dates while preserving the strict YYYY-MM-DD form. */
export function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE_PATTERN.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
