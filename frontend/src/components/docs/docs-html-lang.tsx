"use client";

import { useEffect } from "react";

import { getLocaleByLang } from "@/core/i18n/locale";

type PagefindWindow = Window & {
  pagefind?: { destroy?: () => Promise<void> };
};

// Pagefind picks its per-language index from <html lang> when it first
// initializes, and Nextra keeps the module on `window`. Dropping it makes the
// next search re-import and re-initialize for the current language.
function resetPagefind() {
  const win = window as PagefindWindow;
  const pagefind = win.pagefind;
  delete win.pagefind;
  void pagefind?.destroy?.();
}

/**
 * The root layout renders a fixed `<html lang>`. Docs pages sync it to their
 * locale so screen readers and Pagefind's language-specific index (built by
 * `scripts/build-search-index.mjs`) see the right language.
 */
export function DocsHtmlLang({ lang }: { lang: string }) {
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.lang;
    const locale = getLocaleByLang(lang);
    if (previous === locale) return;
    root.lang = locale;
    resetPagefind();
    return () => {
      root.lang = previous;
      resetPagefind();
    };
  }, [lang]);
  return null;
}
