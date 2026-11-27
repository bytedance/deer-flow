import "@/styles/globals.css";

import { type Metadata } from "next";
import localFont from "next/font/local";

import { ThemeProvider } from "@/components/theme-provider";
import { ArtifactDraftsProvider } from "@/core/artifacts/draft-context";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

const newsreader = localFont({
  src: [
    {
      path: "./fonts/newsreader-latin.woff2",
      weight: "400 600",
      style: "normal",
    },
    {
      path: "./fonts/newsreader-italic-latin.woff2",
      weight: "400 600",
      style: "italic",
    },
  ],
  variable: "--font-landing-serif",
  display: "swap",
  preload: false,
});

const dmSans = localFont({
  src: "./fonts/dm-sans-latin.woff2",
  weight: "400 700",
  style: "normal",
  variable: "--font-landing-sans",
  display: "swap",
  preload: false,
});

const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono-latin.woff2",
  weight: "400 600",
  style: "normal",
  variable: "--font-mono",
  display: "swap",
  preload: false,
});

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
      className={`${newsreader.variable} ${dmSans.variable} ${jetbrainsMono.variable}`}
      suppressContentEditableWarning
      suppressHydrationWarning
    >
      <body>
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          <ArtifactDraftsProvider>{children}</ArtifactDraftsProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
