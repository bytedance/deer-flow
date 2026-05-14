"use client";

import {
  QueryClient,
  QueryClientProvider as TanStackQueryClientProvider,
} from "@tanstack/react-query";

export const queryClient = new QueryClient();

export function QueryClientProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <TanStackQueryClientProvider client={queryClient}>
      {children}
    </TanStackQueryClientProvider>
  );
}
