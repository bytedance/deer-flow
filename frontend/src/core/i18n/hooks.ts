"use client";

import { useEffect } from "react";

import { useI18nContext } from "./context";
import { getLocaleFromCookie, setLocaleInCookie } from "./cookies";
import { enUS } from "./locales/en-US";
import { zhCN } from "./locales/zh-CN";

import { detectLocale, type Locale, type Translations } from "./index";

const translations: Record<Locale, Translations> = {
  "en-US": enUS,
  "zh-CN": zhCN,
};

export function useI18n() {
  const { locale, setLocale } = useI18nContext();

  const t = translations[locale];

  const changeLocale = (newLocale: Locale) => {
    setLocale(newLocale);
    setLocaleInCookie(newLocale);
  };

  // Initialize locale on mount
  useEffect(() => {
    const saved = getLocaleFromCookie() as Locale | null;
    if (!saved) {
      const detected = detectLocale();
      setLocale(detected);
      setLocaleInCookie(detected);
    }
  }, [setLocale]);

  return {
    locale,
    t,
    changeLocale,
  };
}
