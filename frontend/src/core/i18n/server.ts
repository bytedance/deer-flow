import { cookies } from "next/headers";

export type Locale = "en-US" | "zh-CN";

export async function detectLocaleServer(): Promise<Locale> {
  const cookieStore = await cookies();
  const locale = cookieStore.get("locale")?.value ?? "en-US";
  return locale as Locale;
}
