"use client";

import { useEffect, useMemo } from "react";

import { useAppConfig } from "@/core/config";

import { useI18nContext } from "./context";
import { getLocaleFromCookie, setLocaleInCookie } from "./cookies";
import { enUS } from "./locales/en-US";
import { zhCN } from "./locales/zh-CN";

import { detectLocale, type Locale, type Translations } from "./index";

const translations: Record<Locale, Translations> = {
  "en-US": enUS,
  "zh-CN": zhCN,
};

export function formatMessage(
  template: string,
  vars: Record<string, string>,
): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, key: string) => {
    return vars[key] ?? "";
  });
}

function formatTranslationValue(value: unknown, vars: Record<string, string>): unknown {
  if (typeof value === "string") {
    return formatMessage(value, vars);
  }
  if (Array.isArray(value)) {
    return value.map((item) => formatTranslationValue(item, vars));
  }
  if (typeof value === "function") {
    return (...args: unknown[]) => {
      const result = value(...args);
      return typeof result === "string" ? formatMessage(result, vars) : result;
    };
  }
  if (value && typeof value === "object") {
    const output: Record<string, unknown> = {};
    for (const [key, nestedValue] of Object.entries(value)) {
      output[key] = formatTranslationValue(nestedValue, vars);
    }
    return output;
  }
  return value;
}

export function useI18n() {
  const { locale, setLocale } = useI18nContext();
  const { brand } = useAppConfig();

  const t = useMemo(() => {
    return formatTranslationValue(translations[locale], {
      brandName: brand.name,
    }) as Translations;
  }, [brand.name, locale]);

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
