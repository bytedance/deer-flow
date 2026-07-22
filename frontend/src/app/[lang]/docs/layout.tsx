import { getPageMap } from "nextra/page-map";
import { Layout } from "nextra-theme-docs";

import { buildLocalizedDocsPageMap } from "@/components/docs/docs-page-map";
import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { getLocaleByLang } from "@/core/i18n/locale";
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

  return (
    <Layout
      navbar={
        <Header
          className="sticky max-w-full px-10"
          homeURL="/"
          locale={locale}
        />
      }
      pageMap={pageMap}
      docsRepositoryBase="https://github.com/bytedance/deer-flow/tree/main/frontend"
      footer={<Footer className="mt-0" />}
      i18n={i18n}
      // ... Your additional layout options
    >
      {children}
    </Layout>
  );
}
