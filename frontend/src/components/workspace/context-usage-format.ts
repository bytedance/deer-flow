/**
 * Format a context-usage percentage for display.
 *
 * Returns `null` when the percentage is unknown so callers can choose to
 * hide the indicator entirely rather than render a placeholder.
 *
 * Whole-number percentages are rendered without a decimal point; otherwise
 * a single decimal place is shown to stay readable at high resolution
 * (e.g. ``35.4%``).
 */
export function formatContextUsagePercentage(
  percentage: number | null | undefined,
): string | null {
  if (typeof percentage !== "number" || !Number.isFinite(percentage)) {
    return null;
  }
  const clamped = Math.max(0, percentage);
  return Number.isInteger(clamped) ? `${clamped}` : clamped.toFixed(1);
}
