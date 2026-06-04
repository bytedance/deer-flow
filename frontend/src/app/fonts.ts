/**
 * Self-hosted fonts.
 *
 * - `IBM Plex Sans` — Latin sans with industrial/engineering character, used
 *   for UI chrome and body text.
 * - `Noto Sans SC`  — Simplified-Chinese sans, paired with IBM Plex Sans for
 *   CJK glyphs.
 * - `JetBrains Mono` — Monospace, used for code blocks and engineering
 *   numerals.
 *
 * `next/font/google` downloads the woff2 files at build time and serves them
 * from the same origin as the app, so deployments behind locked-down
 * industrial networks no longer need outbound access to fonts.googleapis.com.
 *
 * The CSS variables are wired into Tailwind's `--font-sans` / `--font-mono`
 * tokens in `src/styles/globals.css`.
 */
import { IBM_Plex_Sans, JetBrains_Mono, Noto_Sans_SC } from "next/font/google";

export const fontSansLatin = IBM_Plex_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans-latin",
  weight: ["400", "500", "600", "700"],
});

export const fontSansCJK = Noto_Sans_SC({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans-cjk",
  weight: ["400", "500", "600", "700"],
});

export const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400", "500", "600", "700"],
});
