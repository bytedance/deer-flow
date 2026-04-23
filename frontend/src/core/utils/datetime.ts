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

/** Parse API / store timestamps into a valid Date, or null. */
function parseToDate(value: Date | string | number): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return null;
    }
    // Heuristic: values before year ~2001 in ms are almost certainly Unix seconds.
    const ms = value < 1e12 ? value * 1000 : value;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const s = value.trim();
  if (!s) {
    return null;
  }
  const fromIso = new Date(s);
  if (!Number.isNaN(fromIso.getTime())) {
    return fromIso;
  }
  // Backend often uses ``str(time.time())`` (seconds since epoch, not ISO-8601).
  if (/^\d+(\.\d+)?$/.test(s)) {
    const sec = parseFloat(s);
    if (!Number.isFinite(sec)) {
      return null;
    }
    const d = new Date(sec * 1000);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export function formatTimeAgo(date: Date | string | number, locale?: Locale) {
  const effectiveLocale =
    locale ??
    (getLocaleFromCookie() as Locale | null) ??
    // Fallback when cookie is missing (or on first render)
    detectLocale();
  const parsed = parseToDate(date);
  if (!parsed) {
    return "";
  }
  return formatDistanceToNow(parsed, {
    addSuffix: true,
    locale: getDateFnsLocale(effectiveLocale),
  });
}
