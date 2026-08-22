import "@/styles/globals.css";

import { type Metadata } from "next";

import { ThemeProvider } from "@/components/theme-provider";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";
import { SKIN_STORAGE_KEY } from "@/core/skins/types";

export const metadata: Metadata = {
  title: "DeerFlow",
  description: "A LangChain-based framework for building super agents.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang={DEFAULT_LOCALE}
      suppressContentEditableWarning
      suppressHydrationWarning
    >
      <body>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function () {
              try {
                var s = localStorage.getItem(${JSON.stringify(SKIN_STORAGE_KEY)});
                if (s === ${JSON.stringify("observatory")}) {
                  document.documentElement.setAttribute("data-skin", ${JSON.stringify("observatory")});
                }
              } catch (e) {}
            })();`,
          }}
        />
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
