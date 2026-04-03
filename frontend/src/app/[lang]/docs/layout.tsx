import type { PageMapItem } from "nextra";
import { getPageMap } from "nextra/page-map";
import { Footer, Layout } from "nextra-theme-docs";

import { Header } from "@/components/landing/header";
import { getLocaleByLang } from "@/core/i18n/locale";
import "nextra-theme-docs/style.css";

const footer = <Footer>MIT {new Date().getFullYear()} © Nextra.</Footer>;

const i18n = [
  { locale: "en", name: "English" },
  { locale: "zh", name: "中文" },
];

function formatPageRoute(base: string, items: PageMapItem[]): PageMapItem[] {
  return items.map((item) => {
    if ("route" in item) {
      item.route = `${base}${item.route}`;
    }
    if ("children" in item && item.children) {
      item.children = formatPageRoute(base, item.children);
    }
    return item;
  });
}

export default async function DocLayout({ children, params }) {
  const { lang } = await params;
  const locale = getLocaleByLang(lang);
  const pages = await getPageMap(`/${lang}`);

  return (
    <Layout
      navbar={
        <Header
          className="relative max-w-full px-10"
          homeURL="/"
          locale={locale}
        />
      }
      pageMap={formatPageRoute(`/${lang}/docs`, pages)}
      docsRepositoryBase="https://github.com/bytedance/deerflow/tree/main/frontend/src/app/content"
      footer={footer}
      i18n={i18n}
      // ... Your additional layout options
    >
      {children}
    </Layout>
  );
}
