"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getLocaleFromCookie, setLocaleInCookie } from "./cookies";
import { DEFAULT_LOCALE, normalizeLocale } from "./locale";

export type LandingLocale = "en-US" | "zh-CN";
export type LandingDocsLang = "en" | "zh";

export type LandingLocaleContextValue = {
  locale: LandingLocale;
  setLocale: (next: LandingLocale) => void;
  docsLang: LandingDocsLang;
};

export type OptionalLandingLocaleValue = {
  locale: LandingLocale;
  setLocale: ((next: LandingLocale) => void) | null;
  docsLang: LandingDocsLang;
};

export function getLandingDocsLang(locale: LandingLocale): LandingDocsLang {
  return locale === "zh-CN" ? "zh" : "en";
}

const LandingLocaleContext = createContext<LandingLocaleContextValue | null>(
  null,
);

/**
 * Lightweight client locale context for the landing page.
 * Intentionally avoids importing the workspace's 245 KB translation dictionaries
 * so `/` remains statically prerenderable and well inside its JS bundle budget.
 */
export function LandingLocaleProvider({
  initialLocale = DEFAULT_LOCALE,
  children,
}: {
  initialLocale?: LandingLocale;
  children: ReactNode;
}) {
  const [locale, setLocaleState] = useState<LandingLocale>(initialLocale);

  useEffect(() => {
    const cookieLocale = getLocaleFromCookie();
    if (!cookieLocale) return;
    const normalized = normalizeLocale(cookieLocale);
    if (normalized !== initialLocale) {
      setLocaleState(normalized);
    }
  }, [initialLocale]);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
  }, [locale]);

  const setLocale = useCallback((next: LandingLocale) => {
    const normalized = normalizeLocale(next);
    setLocaleState(normalized);
    setLocaleInCookie(normalized);
    if (typeof document !== "undefined") {
      document.documentElement.lang = normalized;
    }
  }, []);

  const value = useMemo<LandingLocaleContextValue>(
    () => ({
      locale,
      setLocale,
      docsLang: getLandingDocsLang(locale),
    }),
    [locale, setLocale],
  );

  return createElement(LandingLocaleContext.Provider, { value }, children);
}

/**
 * Read the active landing locale when mounted inside `LandingLocaleProvider`.
 * Safely falls back to `fallback` (default `"en-US"`) with `setLocale: null`
 * when called outside the provider (e.g. on `/[lang]/docs/*` or `/blog/*`).
 */
export function useOptionalLandingLocale(
  fallback: LandingLocale = DEFAULT_LOCALE,
): OptionalLandingLocaleValue {
  const context = useContext(LandingLocaleContext);
  if (context) {
    return context;
  }
  const normalizedFallback = normalizeLocale(fallback);
  return {
    locale: normalizedFallback,
    setLocale: null,
    docsLang: getLandingDocsLang(normalizedFallback),
  };
}
