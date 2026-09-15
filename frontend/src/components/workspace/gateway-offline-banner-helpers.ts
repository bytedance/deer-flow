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
  | { kind: "ok"; user: User } // 2xx with parsed body
  | { kind: "unauthorized" } // 401
  | { kind: "transient" }; // 5xx, network, abort, malformed body, etc.

/** Next action the banner effect should take after a probe. */
export type ProbeAction =
  | { type: "apply-user"; user: User }
  | { type: "delegate-refresh"; reason: "session-expired" }
  | { type: "noop"; nextFailureCount: number };

/**
 * Pure: classify an HTTP probe outcome into ProbeOutcome.
 *
 * Extracted from the banner effect so it can be unit-tested independently.
 * `parsedUser` is the JSON body of a 2xx response (or null if absent/malformed);
 * surfacing it through ProbeOutcome lets the caller apply it directly instead
 * of paying for a second /auth/me round-trip via refreshUser().
 */
export function classifyProbe(
  res: Response | null,
  errored: boolean,
  parsedUser: User | null = null,
): ProbeOutcome {
  if (errored || res === null) return { kind: "transient" };
  if (res.ok && parsedUser !== null) return { kind: "ok", user: parsedUser };
  if (res.ok) return { kind: "transient" }; // 2xx but body unusable
  if (res.status === 401) return { kind: "unauthorized" };
  return { kind: "transient" };
}

/**
 * Pure state machine for what to do after a probe lands.
 *
 * Inputs: how many consecutive 401s we've seen so far + the new outcome.
 * Outputs: either "apply the user body we just fetched", "delegate to
 * refreshUser() for /login redirect", or "do nothing, update counter".
 *
 * Transient outcomes (5xx / network / abort) decrement the auth-failure
 * streak by 1 (floored at 0) rather than resetting it. This prevents a
 * flapping gateway that alternates 401 ↔ 5xx from indefinitely masking a
 * genuinely expired session: the streak still converges on the threshold.
 */
export function decideProbeAction(
  consecutiveAuthFailures: number,
  outcome: ProbeOutcome,
  threshold: number = OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD,
): ProbeAction {
  if (outcome.kind === "ok") {
    return { type: "apply-user", user: outcome.user };
  }
  if (outcome.kind === "unauthorized") {
    const next = consecutiveAuthFailures + 1;
    if (next >= threshold) {
      return { type: "delegate-refresh", reason: "session-expired" };
    }
    return { type: "noop", nextFailureCount: next };
  }
  // transient: decrement rather than reset so a flapping gateway
  // (alternating 401 ↔ 5xx) still converges on session-expired.
  return {
    type: "noop",
    nextFailureCount: Math.max(0, consecutiveAuthFailures - 1),
  };
}
