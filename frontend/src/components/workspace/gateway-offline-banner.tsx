"use client";

import { useEffect, useRef } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import {
  OFFLINE_BANNER_RETRY_INTERVAL_MS,
  decideProbeAction,
  shouldShowOfflineBanner,
  type ProbeOutcome,
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
  // Guard against piling up probe calls while the gateway is still slow.
  const inFlightRef = useRef(false);
  // Count consecutive 401s so we can distinguish "transient warm-up 401"
  // from "session actually expired" and avoid lying with the banner.
  const authFailuresRef = useRef(0);

  useEffect(() => {
    if (!gatewayUnavailable) return;
    // Once AuthProvider has a user again the banner has served its
    // purpose; tear down the polling so we don't keep probing every 10s
    // for the entire lifetime of the page (gatewayUnavailable is a
    // server-rendered prop and stays true until a full reload).
    if (user !== null) return;

    const classify = (res: Response | null, errored: boolean): ProbeOutcome => {
      if (errored || res === null) return { kind: "transient" };
      if (res.ok) return { kind: "ok" };
      if (res.status === 401) return { kind: "unauthorized" };
      return { kind: "transient" };
    };

    const probe = async () => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      let res: Response | null = null;
      let errored = false;
      try {
        res = await fetch("/api/v1/auth/me", {
          credentials: "include",
          cache: "no-store",
        });
      } catch {
        errored = true;
      } finally {
        inFlightRef.current = false;
      }

      const action = decideProbeAction(
        authFailuresRef.current,
        classify(res, errored),
      );

      if (action.type === "delegate-refresh") {
        // Reset counter and hand off to AuthProvider. On "recovered" it
        // will populate `user` (banner unmounts on next render). On
        // "session-expired" it will /login-redirect from its 401 branch.
        authFailuresRef.current = 0;
        await refreshUser();
        return;
      }
      authFailuresRef.current = action.nextFailureCount;
    };

    void probe();
    const handle = window.setInterval(() => {
      void probe();
    }, OFFLINE_BANNER_RETRY_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [gatewayUnavailable, user, refreshUser]);

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
