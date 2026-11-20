"use client";

import {
  QueryClient,
  QueryClientProvider as TanStackQueryClientProvider,
} from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";

import { AuthQueryScopeContext } from "@/core/auth/query-scope";

export function QueryClientProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const owner = useContext(AuthQueryScopeContext);
  // A confirmed logout must not start fresh reads with the old cookie while
  // the logout POST is still pending. Public/unknown-auth routes still render.
  if (owner === null) return null;

  // Remount consumers as well as the client, so no observer/local state can
  // retain an old account's data for the new account's first render.
  return (
    <ScopedQueryClientProvider key={owner}>
      {children}
    </ScopedQueryClientProvider>
  );
}

function ScopedQueryClientProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(() => new QueryClient());
  useEffect(() => () => queryClient.clear(), [queryClient]);

  return (
    <TanStackQueryClientProvider client={queryClient}>
      {children}
    </TanStackQueryClientProvider>
  );
}
