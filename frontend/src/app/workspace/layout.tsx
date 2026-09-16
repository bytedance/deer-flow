import "katex/dist/katex.min.css";
import "streamdown/styles.css";

import { redirect } from "next/navigation";

import { GatewayOfflineFallback } from "@/components/workspace/gateway-offline-fallback";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

import { WorkspaceContent } from "./workspace-content";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await detectLocaleServer();
  const result = await getServerSideUser();

  let content: React.ReactNode;

  switch (result.tag) {
    case "authenticated":
      content = (
        <AuthProvider initialUser={result.user}>
          <WorkspaceContent>{children}</WorkspaceContent>
        </AuthProvider>
      );
      break;
    case "needs_setup":
      redirect("/setup");
    case "system_setup_required":
      redirect("/setup");
    case "unauthenticated":
      redirect("/login");
    case "gateway_unavailable":
      // GatewayOfflineFallback supplies the AuthProvider; WorkspaceContent
      // already mounts the banner inside its sidebar layout, so renderBanner
      // stays false here to avoid double-mounting.
      content = (
        <GatewayOfflineFallback>
          <WorkspaceContent gatewayUnavailable>{children}</WorkspaceContent>
        </GatewayOfflineFallback>
      );
      break;
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }

  return <I18nProvider initialLocale={locale}>{content}</I18nProvider>;
}
