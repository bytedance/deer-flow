import "@/styles/globals.css";
import "katex/dist/katex.min.css";

import { type Metadata, type Viewport } from "next";

import { ThemeProvider } from "@/components/theme-provider";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

export const metadata: Metadata = {
  title: "DeerFlow",
  description: "A LangChain-based framework for building super agents.",
};

// Viewport configuration. ``viewport-fit=cover`` is required to make
// ``env(safe-area-inset-*)`` return non-zero values on iPhone notch /
// Dynamic Island devices. ``interactive-widget=resizes-content`` asks
// Chromium to shrink the layout viewport when the virtual keyboard opens
// so ``dvh`` / ``100dvh`` measurements reflect the available area
// (iOS Safari ignores this directive — we cover that case in JS via the
// visualViewport API, see src/hooks/use-visual-viewport.ts).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await detectLocaleServer();
  return (
    <html lang={locale} suppressContentEditableWarning suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          <I18nProvider initialLocale={locale}>{children}</I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
