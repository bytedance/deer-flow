"use client";

import { AuthProvider } from "@/core/auth/AuthProvider";

import { GatewayOfflineBanner } from "./gateway-offline-banner";

interface GatewayOfflineFallbackProps {
  /**
   * When true, this component renders its own banner. The workspace layout
   * sets this to false because WorkspaceContent already mounts the banner
   * inside its sidebar layout. The (auth) layout sets it to true because
   * its plain children have no banner of their own.
   */
  renderBanner?: boolean;
  children?: React.ReactNode;
}

/**
 * Shared fallback shown by both the workspace and (auth) layouts when the
 * server-side auth probe could not reach the gateway. Wraps the children
 * with an AuthProvider so the banner's probe / logout / refresh hooks work
 * — fixing the `(auth)/layout.tsx` lockup where the bare static HTML had
 * no AuthProvider / QueryClientProvider and the user could not recover
 * without a manual reload.
 */
export function GatewayOfflineFallback({
  renderBanner = false,
  children,
}: GatewayOfflineFallbackProps) {
  return (
    <AuthProvider initialUser={null}>
      {renderBanner && <GatewayOfflineBanner gatewayUnavailable />}
      {children}
    </AuthProvider>
  );
}
