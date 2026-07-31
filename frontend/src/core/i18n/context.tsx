"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { Locale } from "@/core/i18n";
import type { Translations } from "@/core/i18n/locales";

import { loadTranslations } from "./translations";

export interface I18nContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translations;
}

export const I18nContext = createContext<I18nContextType | null>(null);

export function I18nProvider({
  children,
  initialLocale,
  initialTranslations,
}: {
  children: ReactNode;
  initialLocale: Locale;
  initialTranslations: Translations;
}) {
  const [locale, setLocale] = useState<Locale>(initialLocale);
  const [t, setTranslations] = useState(initialTranslations);
  const requestIdRef = useRef(0);

  const handleSetLocale = useCallback((newLocale: Locale) => {
    const requestId = ++requestIdRef.current;
    void loadTranslations(newLocale).then((translations) => {
      if (requestId !== requestIdRef.current) return;
      setLocale(newLocale);
      setTranslations(translations);
    });
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  return (
    <I18nContext.Provider value={{ locale, setLocale: handleSetLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18nContext() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return context;
}
