import "katex/dist/katex.min.css";
import "streamdown/styles.css";

import { redirect } from "next/navigation";

import { QueryClientProvider } from "@/components/query-client-provider";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

export const dynamic = "force-dynamic";

/**
 * Chrome-free layout for the standalone artifact window.
 *
 * Deliberately not nested under `/workspace`: this route opens in its own
 * browser window, so it wants the same auth gate and rich-content styles as
 * the chat page but none of its sidebar/thread shell.
 */
export default async function ArtifactViewerLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await detectLocaleServer();
  const result = await getServerSideUser();

  switch (result.tag) {
    case "authenticated":
      return (
        <I18nProvider initialLocale={locale}>
          <AuthProvider initialUser={result.user}>
            <QueryClientProvider>{children}</QueryClientProvider>
          </AuthProvider>
        </I18nProvider>
      );
    case "needs_setup":
    case "system_setup_required":
      redirect("/setup");
    case "unauthenticated":
      redirect("/login");
    case "gateway_unavailable":
      redirect("/workspace");
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }
}
