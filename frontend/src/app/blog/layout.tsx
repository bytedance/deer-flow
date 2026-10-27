import "katex/dist/katex.min.css";

import { Layout } from "nextra-theme-docs";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { getBlogIndexData } from "@/core/blog";
import { detectLocaleServer } from "@/core/i18n/server";
import "nextra-theme-docs/style.css";

export default async function BlogLayout({ children }) {
  const [locale, { pageMap }] = await Promise.all([
    detectLocaleServer(),
    getBlogIndexData(),
  ]);

  return (
    <Layout
      navbar={
        <Header
          className="relative max-w-full px-10"
          homeURL="/"
          locale={locale}
        />
      }
      pageMap={pageMap}
      sidebar={{ defaultOpen: true }}
      docsRepositoryBase="https://github.com/bytedance/deer-flow/tree/main/frontend"
      footer={<Footer />}
    >
      {children}
    </Layout>
  );
}
