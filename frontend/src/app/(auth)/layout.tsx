import Link from "next/link";
import { type ReactNode } from "react";

import { AuthProvider } from "@/core/auth/AuthProvider";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever } from "@/core/auth/types";
import type { User } from "@/core/auth/types";

export const dynamic = "force-dynamic";

export default async function AuthLayout({
  children,
}: {
  children: ReactNode;
}) {
  const result = await getServerSideUser();

  // Let the login page handle authenticated redirects so EHM deep-link `next`
  // params can be preserved via a full client-side navigation.
  let initialUser: User | null = null;
  if (result.tag === "authenticated") {
    initialUser = result.user;
  }

  switch (result.tag) {
    case "authenticated":
    case "unauthenticated":
      return <AuthProvider initialUser={initialUser}>{children}</AuthProvider>;
    case "gateway_unavailable":
      return (
        <div className="flex min-h-dvh flex-col items-center justify-center gap-4">
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
