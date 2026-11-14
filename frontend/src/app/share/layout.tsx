import "katex/dist/katex.min.css";
import "streamdown/styles.css";

import type { Metadata } from "next";

import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

export const metadata: Metadata = {
  title: "Shared conversation · DeerFlow",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default async function ShareLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <I18nProvider initialLocale={await detectLocaleServer()}>
      {children}
    </I18nProvider>
  );
}
