import { cookies } from "next/headers";

import { DEFAULT_LOCALE, normalizeLocale, type Locale } from "./locale";

export async function detectLocaleServer(): Promise<Locale> {
  const cookieStore = await cookies();
  let locale = cookieStore.get("locale")?.value;
  if (locale !== undefined) {
    try {
      locale = decodeURIComponent(locale);
    } catch {
      // Keep raw cookie value when decoding fails.
    }
  }

  // Treat old "en-US" default cookie as no preference set → use new DEFAULT_LOCALE
  if (!locale || locale === "en-US") {
    return DEFAULT_LOCALE;
  }

  return normalizeLocale(locale);
}
