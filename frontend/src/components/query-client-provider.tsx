"use client";

import {
  QueryClient,
  QueryClientProvider as TanStackQueryClientProvider,
} from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useOptionalAuthUserId } from "@/core/auth/AuthProvider";

function QueryClientLifetime({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());
  const cleanupGeneration = useRef({ generation: 0 });

  useEffect(() => {
    const lifetime = cleanupGeneration.current;
    const generation = ++lifetime.generation;
    return () => {
      // StrictMode immediately replays setup after a simulated cleanup. Only
      // clear after a genuine unmount; a newly keyed tree already has its own
      // empty client before it can render any data from the previous lifetime.
      queueMicrotask(() => {
        if (lifetime.generation === generation) client.clear();
      });
    };
  }, [client]);

  return (
    <TanStackQueryClientProvider client={client}>
      {children}
    </TanStackQueryClientProvider>
  );
}

export function QueryClientProvider({
  children,
  cacheKey,
}: Readonly<{
  children: React.ReactNode;
  /** A workspace lifetime key; changing it remounts all query consumers. */
  cacheKey?: string;
}>) {
  // Public showcase/artifact layouts need independent caches without requiring
  // an AuthProvider. Authenticated trees additionally reset on account/logout.
  const actorUserId = useOptionalAuthUserId();
  const identityKey = JSON.stringify([actorUserId, cacheKey ?? null]);
  return (
    <QueryClientLifetime key={identityKey}>{children}</QueryClientLifetime>
  );
}
