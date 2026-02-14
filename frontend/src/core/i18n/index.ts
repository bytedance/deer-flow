export { enUS } from "./locales/en-US";
export { zhCN } from "./locales/zh-CN";
export type { Translations } from "./locales/types";

export type Locale = "en-US" | "zh-CN";

// Helper function to detect browser locale
export function detectLocale(): Locale {
  if (typeof window === "undefined") {
    return "en-US";
  }

  const browserLang =
    navigator.language ||
    (navigator as unknown as { userLanguage: string }).userLanguage;

  // Check if browser language is Chinese (zh, zh-CN, zh-TW, etc.)
  if (browserLang.toLowerCase().startsWith("zh")) {
    return "zh-CN";
  }

  return "en-US";
}
