import "@/styles/globals.css";
import "katex/dist/katex.min.css";

import { type Metadata } from "next";

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
        <ThemeProvider
          attribute="class"
          defaultTheme="industrial-dark"
          themes={[
            "system",
            "light",
            "dark",
            "industrial-light",
            "industrial-dark",
          ]}
          value={{
            light: "light",
            dark: "dark",
            "industrial-light": "industrial-light",
            "industrial-dark": "industrial-dark",
          }}
          enableSystem
          disableTransitionOnChange
        >
          <I18nProvider initialLocale={locale}>{children}</I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
