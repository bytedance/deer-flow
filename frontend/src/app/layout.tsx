import "@/styles/globals.css";
import "katex/dist/katex.min.css";

import { type Metadata } from "next";
import Script from "next/script";

import { ThemeProvider } from "@/components/theme-provider";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

export const metadata: Metadata = {
  title: "DeerFlow",
  description: "A LangChain-based framework for building super agents.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await detectLocaleServer();
  const feishuDebugMode = process.env.NEXT_PUBLIC_FEISHU_DEBUG_MODE === "true";
  return (
    <html lang={locale} suppressContentEditableWarning suppressHydrationWarning>
      <head>
        {feishuDebugMode && (
          <Script
            src="https://lf-package-cn.feishucdn.com/obj/feishu-static/op/fe/devtools_frontend/remote-debug-0.0.1-alpha.6.js"
            strategy="afterInteractive"
          />
        )}
      </head>
      <body>
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          <I18nProvider initialLocale={locale}>{children}</I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
