export const OFFLINE_BANNER_RETRY_INTERVAL_MS = 10_000;

/**
 * Number of consecutive 401 responses before treating the session as
 * expired and delegating to AuthProvider.refreshUser() for /login redirect.
 *
 * Threshold > 1 absorbs transient 401s that may occur in the first few
 * milliseconds after a gateway becomes ready again, without indefinitely
 * masking a genuinely expired cookie.
 */
export const OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD = 3;

import type { User } from "@/core/auth/types";

export function shouldShowOfflineBanner(
  user: User | null,
  gatewayUnavailable: boolean,
): boolean {
  return gatewayUnavailable && user === null;
}

/** Categorised outcome of a single /auth/me probe. */
export type ProbeOutcome =
  | { kind: "ok" } // 2xx
  | { kind: "unauthorized" } // 401
  | { kind: "transient" }; // 5xx, network, abort, etc.

/** Next action the banner effect should take after a probe. */
export type ProbeAction =
  | { type: "delegate-refresh"; reason: "recovered" | "session-expired" }
  | { type: "noop"; nextFailureCount: number };

/**
 * Pure state machine for what to do after a probe lands.
 *
 * Inputs: how many consecutive 401s we've seen so far + the new outcome.
 * Outputs: either "delegate to refreshUser()" (which will sync user or
 * /login-redirect via AuthProvider) or "do nothing, update counter".
 */
export function decideProbeAction(
  consecutiveAuthFailures: number,
  outcome: ProbeOutcome,
  threshold: number = OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD,
): ProbeAction {
  if (outcome.kind === "ok") {
    return { type: "delegate-refresh", reason: "recovered" };
  }
  if (outcome.kind === "unauthorized") {
    const next = consecutiveAuthFailures + 1;
    if (next >= threshold) {
      return { type: "delegate-refresh", reason: "session-expired" };
    }
    return { type: "noop", nextFailureCount: next };
  }
  // transient (5xx, network, abort): reset auth-failure streak so we don't
  // count an unrelated outage toward "session expired".
  return { type: "noop", nextFailureCount: 0 };
}
