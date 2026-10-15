const SUPPORTED_DOC_LANGUAGES = new Set(["en", "zh"]);
const UNLOCALIZED_DOCS_PATH = /^\/docs(?=\/|[?#]|$)/;

export function localizeDocsHref(
  href: string,
  lang: string | undefined,
): string {
  if (!lang || !SUPPORTED_DOC_LANGUAGES.has(lang)) {
    return href;
  }
  if (!UNLOCALIZED_DOCS_PATH.test(href)) {
    return href;
  }
  return `/${lang}${href}`;
}
