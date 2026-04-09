import Link from "next/link";
import { redirect } from "next/navigation";
import { type ReactNode } from "react";

import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";

export const dynamic = "force-dynamic";

export default async function AuthLayout({
  children,
}: {
  children: ReactNode;
}) {
  const result = await getServerSideUser();

  switch (result.tag) {
    case "authenticated":
      redirect("/workspace");
    case "needs_setup":
      // Allow access to setup page
      return <AuthProvider initialUser={result.user}>{children}</AuthProvider>;
    case "system_setup_required":
    case "unauthenticated":
      return <AuthProvider initialUser={null}>{children}</AuthProvider>;
    case "gateway_unavailable":
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-4">
          <p className="text-muted-foreground">
            Service temporarily unavailable.
          </p>
          <Link
            href="/login"
            className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-md px-4 py-2 text-sm"
          >
            Retry
          </Link>
        </div>
      );
    case "config_error":
      throw new Error(result.message);
    default:
      assertNever(result);
  }
}
