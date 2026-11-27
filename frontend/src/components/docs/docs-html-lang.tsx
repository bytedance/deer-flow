"use client";

import { useEffect } from "react";

import { getLocaleByLang } from "@/core/i18n/locale";

type PagefindWindow = Window & {
  pagefind?: { destroy?: () => Promise<void> };
};

const PAGEFIND_LANG_ATTR = "data-pagefind-lang";

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
    const previousHtmlLang = root.lang;
    const locale = getLocaleByLang(lang);
    const activePagefindLang = root.getAttribute(PAGEFIND_LANG_ATTR);

    if (root.lang !== locale) {
      root.lang = locale;
    }

    // Track Pagefind's initialized locale separately from `<html lang>` so
    // switching language on `/` before navigating to `/[lang]/docs` still
    // discards any Pagefind instance loaded under the previous docs language.
    if (activePagefindLang !== locale) {
      resetPagefind();
      root.setAttribute(PAGEFIND_LANG_ATTR, locale);
    }

    return () => {
      if (root.lang === locale && previousHtmlLang !== locale) {
        root.lang = previousHtmlLang;
      }
      resetPagefind();
      root.removeAttribute(PAGEFIND_LANG_ATTR);
    };
  }, [lang]);
  return null;
}
