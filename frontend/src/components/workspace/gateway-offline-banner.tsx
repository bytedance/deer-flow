"use client";

import { useEffect, useRef } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import {
  OFFLINE_BANNER_RETRY_INTERVAL_MS,
  shouldShowOfflineBanner,
} from "./gateway-offline-banner-helpers";

interface GatewayOfflineBannerProps {
  /**
   * True when the server-side auth probe at `/api/v1/auth/me` could not
   * reach the gateway. The banner stays mounted until a client-side probe
   * confirms the gateway is healthy and `user` becomes populated.
   */
  gatewayUnavailable: boolean;
}

export function GatewayOfflineBanner({
  gatewayUnavailable,
}: GatewayOfflineBannerProps) {
  const { t } = useI18n();
  const { user, refreshUser, logout } = useAuth();
  // Guard against piling up probe calls while the gateway is still slow:
  // each interval tick must wait for the previous probe to settle before
  // issuing a new one.
  const inFlightRef = useRef(false);

  useEffect(() => {
    if (!gatewayUnavailable) return;

    // We intentionally do NOT call `refreshUser()` directly here.
    // `AuthProvider.refreshUser()` treats any 401 from `/api/v1/auth/me`
    // as "session expired" and force-redirects to `/login`. During gateway
    // recovery, the first few requests may transiently return 401 before
    // the gateway is fully ready, which would incorrectly kick the user
    // out — defeating the purpose of this offline banner.
    //
    // Instead, we silently probe `/api/v1/auth/me` ourselves and only
    // delegate to `refreshUser()` once we confirm the gateway is healthy
    // (200 OK). Non-200 responses are swallowed; we just wait for the
    // next interval tick.
    const probe = async () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const res = await fetch("/api/v1/auth/me", {
          credentials: "include",
          cache: "no-store",
        });
        if (res.ok) {
          // Gateway is healthy again — hand off to AuthProvider so
          // `user` is populated and the banner unmounts itself.
          await refreshUser();
        }
        // 401 / 5xx / network: stay silent and retry on the next tick.
      } catch {
        // Network error during recovery is expected; stay silent.
      } finally {
        inFlightRef.current = false;
      }
    };

    // Kick off an immediate probe so the banner can disappear as soon
    // as the gateway is back, without waiting for the first interval.
    void probe();

    const handle = window.setInterval(() => {
      void probe();
    }, OFFLINE_BANNER_RETRY_INTERVAL_MS);

    return () => {
      window.clearInterval(handle);
    };
  }, [gatewayUnavailable, refreshUser]);

  if (!shouldShowOfflineBanner(user, gatewayUnavailable)) {
    return null;
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="bg-muted text-muted-foreground flex items-center justify-between gap-3 border-b px-4 py-2 text-sm"
    >
      <span>
        {t.workspace.gatewayUnavailable}{" "}
        {t.workspace.gatewayUnavailableRetrying}
      </span>
      <button
        type="button"
        onClick={() => {
          void logout();
        }}
        className="hover:bg-background rounded-md border px-3 py-1 text-xs"
      >
        {t.workspace.logout}
      </button>
    </div>
  );
}
