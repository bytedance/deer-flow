/**
 * Pure helpers for the workspace gateway-offline banner.
 *
 * Kept in a separate module so they can be unit-tested without bringing
 * React / jsdom into the vitest config (see `frontend/vitest.config.ts`,
 * which only collects `tests/unit/**\/*.test.ts`).
 */

import type { User } from "@/core/auth/types";

/**
 * How often the banner re-checks the gateway by calling
 * `AuthProvider.refreshUser()` while it is mounted.
 *
 * 10s is a deliberate trade-off:
 * - fast enough for the UI to recover without user action once the
 *   gateway comes back, and
 * - slow enough not to add meaningful load while the gateway is
 *   already struggling.
 */
export const OFFLINE_BANNER_RETRY_INTERVAL_MS = 10_000;

/**
 * Decide whether the workspace gateway-offline banner should be visible.
 *
 * Visible iff:
 * - the workspace layout flagged the SSR auth probe as unavailable, AND
 * - the client has not yet recovered an authenticated user (e.g. via
 *   `AuthProvider.refreshUser()`).
 *
 * Once the gateway recovers and `refreshUser()` populates `user`, the
 * banner hides itself automatically.
 */
export function shouldShowOfflineBanner(
  user: User | null,
  gatewayUnavailable: boolean,
): boolean {
  return gatewayUnavailable && user === null;
}
