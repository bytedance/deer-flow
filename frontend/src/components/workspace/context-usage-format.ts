/**
 * Format a context-usage percentage for display.
 *
 * Returns `null` when the percentage is unknown so callers can choose to
 * hide the indicator entirely rather than render a placeholder.
 *
 * Whole-number percentages are rendered without a decimal point; otherwise
 * a single decimal place is shown to stay readable at high resolution
 * (e.g. ``35.4%``). A non-zero value below one tenth renders as ``<0.1`` so a
 * small but real share never looks like zero.
 */
export function formatContextUsagePercentage(
  percentage: number | null | undefined,
): string | null {
  if (typeof percentage !== "number" || !Number.isFinite(percentage)) {
    return null;
  }
  const clamped = Math.max(0, percentage);
  if (clamped > 0 && clamped < 0.1) {
    return "<0.1";
  }
  return Number.isInteger(clamped) ? `${clamped}` : clamped.toFixed(1);
}

/**
 * Format a token count shown in the context-usage ring and popover.
 *
 * Every count of a thousand tokens or more uses the K suffix so the breakdown
 * rows share one unit with the window figures; smaller counts stay exact, which
 * keeps values like a handful of injected tokens readable.
 */
export function formatContextUsageTokens(tokens: number): string {
  const clamped = Number.isFinite(tokens) ? Math.max(0, tokens) : 0;
  return clamped < 1000
    ? clamped.toLocaleString()
    : `${(clamped / 1000).toFixed(1)}K`;
}
