import { Layout } from "nextra-theme-docs";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { getBlogIndexData } from "@/core/blog";
import "nextra-theme-docs/style.css";

export default async function BlogLayout({ children }) {
  const { pageMap } = await getBlogIndexData();

  return (
    <Layout
      navbar={<Header className="relative max-w-full px-10" homeURL="/" />}
      pageMap={pageMap}
      sidebar={{ defaultOpen: true }}
      docsRepositoryBase="https://github.com/bytedance/deerflow/tree/main/frontend/src/content"
      footer={<Footer />}
    >
      {children}
    </Layout>
  );
}
