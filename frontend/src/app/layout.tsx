import "@/styles/globals.css";
import "katex/dist/katex.min.css";

import { type Metadata } from "next";

import { CookieConsentBanner } from "@/components/cookie-consent-banner";
import { ThemeProvider } from "@/components/theme-provider";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

import { fontMono, fontSansCJK, fontSansLatin } from "./fonts";

export const metadata: Metadata = {
  metadataBase: new URL("https://inscphm.com"),
  title: "EHM AI 工作台",
  description: "面向石油石化行业的设备健康管理 AI 工作台。",
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
  },
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await detectLocaleServer();
  return (
    <html
      lang={locale}
      className={`${fontSansLatin.variable} ${fontSansCJK.variable} ${fontMono.variable}`}
      suppressContentEditableWarning
      suppressHydrationWarning
    >
      <body>
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
        >
          跳转到主要内容
        </a>
        <ThemeProvider
          attribute="class"
          defaultTheme="minimal-modern"
          themes={["industrial-dark", "industrial-light", "industrial-blue", "minimal-modern"]}
          disableTransitionOnChange
        >
          <I18nProvider initialLocale={locale}>
            {children}
          </I18nProvider>
          <CookieConsentBanner />
        </ThemeProvider>
      </body>
    </html>
  );
}
