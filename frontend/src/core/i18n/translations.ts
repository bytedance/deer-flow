import type { Locale } from "./locale";
import type { Translations } from "./locales";

const translationLoaders: Record<Locale, () => Promise<Translations>> = {
  "en-US": async () => (await import("./locales/en-US")).enUS,
  "zh-CN": async () => (await import("./locales/zh-CN")).zhCN,
};

export async function loadTranslations(locale: Locale): Promise<Translations> {
  return await translationLoaders[locale]();
}
