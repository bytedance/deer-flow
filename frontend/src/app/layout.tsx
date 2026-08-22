import "@/styles/globals.css";

import { type Metadata } from "next";

import { ThemeProvider } from "@/components/theme-provider";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";
import { SkinRouteGuard } from "@/core/skins/route-guard";
import { SKIN_SCOPED_PREFIXES, SKIN_STORAGE_KEY } from "@/core/skins/types";

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
                var scoped = ${JSON.stringify(SKIN_SCOPED_PREFIXES)}.some(function (prefix) {
                  return window.location.pathname === prefix ||
                    window.location.pathname.indexOf(prefix + "/") === 0;
                });
                if (!scoped) { return; }
                var s = localStorage.getItem(${JSON.stringify(SKIN_STORAGE_KEY)});
                if (s === ${JSON.stringify("observatory")}) {
                  document.documentElement.setAttribute("data-skin", ${JSON.stringify("observatory")});
                }
              } catch (e) {}
            })();`,
          }}
        />
        <SkinRouteGuard />
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
