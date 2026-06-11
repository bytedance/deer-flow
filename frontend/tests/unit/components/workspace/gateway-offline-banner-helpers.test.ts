import { describe, expect, it } from "vitest";

import {
  OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD,
  OFFLINE_BANNER_RETRY_INTERVAL_MS,
  decideProbeAction,
  shouldShowOfflineBanner,
} from "@/components/workspace/gateway-offline-banner-helpers";
import type { User } from "@/core/auth/types";

const fakeUser: User = {
  id: "u1",
  email: "user@example.com",
  system_role: "user",
  needs_setup: false,
};

describe("shouldShowOfflineBanner", () => {
  it("hides when the gateway is reachable", () => {
    expect(shouldShowOfflineBanner(null, false)).toBe(false);
    expect(shouldShowOfflineBanner(fakeUser, false)).toBe(false);
  });

  it("shows when the gateway is unavailable and the client has no user yet", () => {
    expect(shouldShowOfflineBanner(null, true)).toBe(true);
  });

  it("hides as soon as the client recovers an authenticated user", () => {
    expect(shouldShowOfflineBanner(fakeUser, true)).toBe(false);
  });
});

describe("OFFLINE_BANNER_RETRY_INTERVAL_MS", () => {
  it("is a positive finite number", () => {
    expect(OFFLINE_BANNER_RETRY_INTERVAL_MS).toBeGreaterThan(0);
    expect(Number.isFinite(OFFLINE_BANNER_RETRY_INTERVAL_MS)).toBe(true);
  });
});

describe("OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD", () => {
  it("is an integer greater than 1 so a single transient 401 cannot expire the session", () => {
    expect(Number.isInteger(OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD)).toBe(true);
    expect(OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD).toBeGreaterThan(1);
  });
});

describe("decideProbeAction", () => {
  it("delegates to refreshUser as 'recovered' on a 2xx response", () => {
    expect(decideProbeAction(0, { kind: "ok" })).toEqual({
      type: "delegate-refresh",
      reason: "recovered",
    });
    // Even if we'd accumulated some 401s, a 200 wins immediately.
    expect(decideProbeAction(2, { kind: "ok" })).toEqual({
      type: "delegate-refresh",
      reason: "recovered",
    });
  });

  it("treats a single 401 as transient noise and only bumps the counter", () => {
    expect(decideProbeAction(0, { kind: "unauthorized" })).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
  });

  it("treats consecutive 401s below the threshold as still transient", () => {
    // With default threshold = 3, two consecutive 401s should not yet
    // be flagged as session-expired.
    expect(decideProbeAction(1, { kind: "unauthorized" })).toEqual({
      type: "noop",
      nextFailureCount: 2,
    });
  });

  it("delegates to refreshUser as 'session-expired' once 401s reach the threshold", () => {
    // Default threshold = 3 → third consecutive 401 trips the wire.
    expect(decideProbeAction(2, { kind: "unauthorized" })).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });

  it("honours a custom threshold (parameterised for safer tests)", () => {
    // threshold=2: first 401 is still noop, second 401 expires.
    expect(decideProbeAction(0, { kind: "unauthorized" }, 2)).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
    expect(decideProbeAction(1, { kind: "unauthorized" }, 2)).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });

  it("resets the auth-failure streak on a transient (5xx / network / abort) outcome", () => {
    // We had 2 consecutive 401s, but the next probe hits a 5xx or network
    // error — that is an *unrelated* gateway hiccup and must not be counted
    // toward "session expired". The streak resets to 0.
    expect(decideProbeAction(2, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 0,
    });
    expect(decideProbeAction(0, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 0,
    });
  });
});
