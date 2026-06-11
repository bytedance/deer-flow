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
   * reach the gateway. The banner stays mounted until the client-side
   * `refreshUser()` succeeds and populates `user`.
   */
  gatewayUnavailable: boolean;
}

export function GatewayOfflineBanner({
  gatewayUnavailable,
}: GatewayOfflineBannerProps) {
  const { t } = useI18n();
  const { user, refreshUser, logout } = useAuth();
  // Guard against piling up `refreshUser()` calls while the gateway is
  // still slow: each interval tick must wait for the previous probe to
  // settle before issuing a new one.
  const inFlightRef = useRef(false);

  useEffect(() => {
    if (!gatewayUnavailable) return;

    const probe = async () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        await refreshUser();
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
