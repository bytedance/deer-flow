"use client";

import { useEffect } from "react";

import { useI18nContext } from "./context";
import { getLocaleFromCookie, setLocaleInCookie } from "./cookies";
import { enUS } from "./locales/en-US";
import { ruRU } from "./locales/ru-RU";
import { zhCN } from "./locales/zh-CN";

import {
  DEFAULT_LOCALE,
  detectLocale,
  normalizeLocale,
  type Locale,
  type Translations,
} from "./index";

const translations: Record<Locale, Translations> = {
  "en-US": enUS,
  "zh-CN": zhCN,
  "ru-RU": ruRU,
};

export function useI18n() {
  const { locale, setLocale } = useI18nContext();

  const t = translations[locale] ?? translations[DEFAULT_LOCALE];

  const changeLocale = (newLocale: Locale) => {
    setLocale(newLocale);
    setLocaleInCookie(newLocale);
  };

  // Initialize locale on mount
  useEffect(() => {
    const saved = getLocaleFromCookie();
    // Treat old "en-US" default cookie as no preference → migrate to DEFAULT_LOCALE
    if (saved && saved !== "en-US") {
      const normalizedSaved = normalizeLocale(saved);
      setLocale(normalizedSaved);
      if (saved !== normalizedSaved) {
        setLocaleInCookie(normalizedSaved);
      }
      return;
    }

    // No preference set — use DEFAULT_LOCALE (ru-RU)
    setLocale(DEFAULT_LOCALE);
    setLocaleInCookie(DEFAULT_LOCALE);
  }, [setLocale]);

  return {
    locale,
    t,
    changeLocale,
  };
}
