import { cookies } from "next/headers";

import { DEFAULT_LOCALE, normalizeLocale, type Locale } from "./locale";
import { translations } from "./translations";

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

  return normalizeLocale(locale);
}

export async function setLocale(locale: string | Locale): Promise<Locale> {
  const normalizedLocale = normalizeLocale(locale);
  const cookieStore = await cookies();
  cookieStore.set("locale", encodeURIComponent(normalizedLocale), {
    maxAge: 365 * 24 * 60 * 60,
    path: "/",
    sameSite: "lax",
  });

  return normalizedLocale;
}

export async function getI18n(localeOverride?: string | Locale) {
  const locale = localeOverride
    ? normalizeLocale(localeOverride)
    : await detectLocaleServer();
  const t = translations[locale] ?? translations[DEFAULT_LOCALE];
  return {
    locale,
    t,
  };
}
