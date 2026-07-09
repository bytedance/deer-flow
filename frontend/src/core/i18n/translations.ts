import type { Locale } from "./locale";
import { enUS, zhCN, viVN, type Translations } from "./locales";

export const translations: Record<Locale, Translations> = {
  "en-US": enUS,
  "zh-CN": zhCN,
  "vi-VN": viVN,
};
