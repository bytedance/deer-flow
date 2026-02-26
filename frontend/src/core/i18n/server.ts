import { cookies } from "next/headers";

import { normalizeLocale, type Locale } from "./index";

export async function detectLocaleServer(): Promise<Locale> {
  const cookieStore = await cookies();
  const locale = cookieStore.get("locale")?.value;
  return normalizeLocale(locale);
}
