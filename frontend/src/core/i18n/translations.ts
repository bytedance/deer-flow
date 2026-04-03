import type { Locale } from "./locale";
import { enUS, zhCN, type Translations } from "./locales";

export const translations: Record<Locale, Translations> = {
  "en-US": enUS,
  "zh-CN": zhCN,
};
