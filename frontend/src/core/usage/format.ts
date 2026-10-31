import type { ModelUsage } from "./types";

export function modelUsageRows(models: Record<string, ModelUsage>) {
  return Object.entries(models)
    .map(([name, usage]) => ({ name, ...usage }))
    .sort((a, b) => b.tokens - a.tokens || a.name.localeCompare(b.name));
}

/** Day buckets are calendar dates, not UTC instants to shift a second time. */
export function formatUsageDate(date: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
}

export function formatRunDuration(
  seconds: number | null,
  locale: string,
  unknown: string,
): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0)
    return unknown;
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: seconds >= 60 ? "minute" : "second",
    unitDisplay: "short",
    maximumFractionDigits: 1,
  }).format(seconds >= 60 ? seconds / 60 : seconds);
}
