import { redirect } from "next/navigation";

import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";

import { WorkspaceContent } from "./workspace-content";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const result = await getServerSideUser();

  switch (result.tag) {
    case "authenticated":
      return (
        <AuthProvider initialUser={result.user}>
          <WorkspaceContent>{children}</WorkspaceContent>
        </AuthProvider>
      );
    case "needs_setup":
      redirect("/setup");
    case "system_setup_required":
      redirect("/setup");
    case "unauthenticated":
      redirect("/login");
    case "gateway_unavailable":
      return (
        <AuthProvider initialUser={null}>
          <WorkspaceContent gatewayUnavailable>{children}</WorkspaceContent>
        </AuthProvider>
      );
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }
}
