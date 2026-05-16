import Link from "next/link";
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
        <div className="flex h-screen flex-col items-center justify-center gap-4">
          <p className="text-muted-foreground">
            Service temporarily unavailable.
          </p>
          <p className="text-muted-foreground text-xs">
            The backend may be restarting. Please wait a moment and try again.
          </p>
          <div className="flex gap-3">
            <Link
              href="/workspace"
              className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-4 py-2 text-sm"
            >
              Retry
            </Link>
            <Link
              href="/api/v1/auth/logout"
              className="text-muted-foreground hover:bg-muted rounded-md border px-4 py-2 text-sm"
            >
              Logout &amp; Reset
            </Link>
          </div>
        </div>
      );
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }
}
