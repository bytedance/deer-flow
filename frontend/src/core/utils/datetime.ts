import { formatDistanceToNow } from "date-fns";
import { enUS as dateFnsEnUS, zhCN as dateFnsZhCN } from "date-fns/locale";

import { detectLocale, type Locale } from "@/core/i18n";
import { getLocaleFromCookie } from "@/core/i18n/cookies";

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
  // Guard against invalid/empty timestamps (e.g. a backend returning "" for
  // lastUpdated when there are no memories) -- date-fns would throw
  // "Invalid time value" on `new Date("")`. Return a neutral placeholder.
  const parsed = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(parsed.getTime())) {
    return "-";
  }
  return formatDistanceToNow(parsed, {
    addSuffix: true,
    locale: getDateFnsLocale(effectiveLocale),
  });
}
