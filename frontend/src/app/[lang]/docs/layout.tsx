import "katex/dist/katex.min.css";

import { Search } from "nextra/components";
import { getPageMap } from "nextra/page-map";
import { Layout } from "nextra-theme-docs";

import { DocsHtmlLang } from "@/components/docs/docs-html-lang";
import { DocsLanguageProvider } from "@/components/docs/docs-language-context";
import { buildLocalizedDocsPageMap } from "@/components/docs/docs-page-map";
import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { getLocaleByLang } from "@/core/i18n/locale";
import { getI18n } from "@/core/i18n/server";
import "nextra-theme-docs/style.css";

const i18n = [
  { locale: "en", name: "English" },
  { locale: "zh", name: "中文" },
];

export default async function DocLayout({ children, params }) {
  const { lang } = await params;
  const locale = getLocaleByLang(lang);
  const pages = await getPageMap(`/${lang}`);
  const pageMap = buildLocalizedDocsPageMap(`/${lang}/docs`, pages);
  const { t } = await getI18n(locale);
  // Pagefind keeps one index per language (see scripts/build-search-index.mjs);
  // the lang filter also scopes queries if <html lang> has not synced yet.
  const search = (
    <Search
      className="[&_input]:border-border [&_input]:bg-secondary/60 [&_input]:border"
      placeholder={t.home.searchDocs}
      aria-label={t.home.searchDocsLabel}
      emptyResult={t.home.searchNoResults}
      errorText={t.home.searchLoadFailed}
      loading={t.home.searchLoading}
      searchOptions={{ filters: { lang } }}
    />
  );

  return (
    <DocsLanguageProvider lang={lang}>
      <Layout
        navbar={
          <Header
            className="sticky max-w-full px-10"
            homeURL="/"
            locale={locale}
            search={search}
          />
        }
        pageMap={pageMap}
        // Search lives in the custom Header; Nextra's own mobile menu is never
        // shown, and a second instance would steal the Cmd/Ctrl+K shortcut.
        search={null}
        docsRepositoryBase="https://github.com/bytedance/deer-flow/tree/main/frontend"
        footer={<Footer className="mt-0" />}
        i18n={i18n}
        // ... Your additional layout options
      >
        <DocsHtmlLang lang={lang} />
        <span hidden data-pagefind-filter={`lang:${lang}`} />
        {children}
      </Layout>
    </DocsLanguageProvider>
  );
}
