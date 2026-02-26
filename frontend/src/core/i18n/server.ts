import { cookies } from "next/headers";

import { normalizeLocale, type Locale } from "./locale";

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
