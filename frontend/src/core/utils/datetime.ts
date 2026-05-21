import { formatDistanceToNow } from "date-fns";
import { enUS as dateFnsEnUS, zhCN as dateFnsZhCN } from "date-fns/locale";

import { detectLocale, type Locale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";

const TIMEZONE_PATTERN = /(Z|[+-]\d{2}:?\d{2})$/i;

export function normalizeApiDate(date: Date | string | number): Date | string | number {
  if (typeof date !== "string") {
    return date;
  }

  const trimmed = date.trim();
  if (!trimmed || TIMEZONE_PATTERN.test(trimmed)) {
    return date;
  }

  return new Date(`${trimmed}Z`);
}

function getDateFnsLocale(locale: Locale) {
  switch (locale) {
    case "zh-CN":
      return dateFnsZhCN;
    case "en-US":
    default:
      return dateFnsEnUS;
  }
}

export function formatTimeAgo(date: Date | string | number, locale?: Locale) {
  const effectiveLocale =
    locale ??
    (getLocaleFromCookie() as Locale | null) ??
    // Fallback when cookie is missing (or on first render)
    detectLocale();
  return formatDistanceToNow(normalizeApiDate(date), {
    addSuffix: true,
    locale: getDateFnsLocale(effectiveLocale),
  });
}
