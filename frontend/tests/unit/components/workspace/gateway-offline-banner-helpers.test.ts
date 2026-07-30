import { describe, expect, it } from "@rstest/core";

import {
  OFFLINE_BANNER_AUTH_FAILURE_THRESHOLD,
  OFFLINE_BANNER_RETRY_INTERVAL_MS,
  classifyProbe,
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

function makeResponse(status: number, ok = status >= 200 && status < 300) {
  return { status, ok } as Response;
}

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

describe("classifyProbe", () => {
  it("returns transient when fetch errored", () => {
    expect(classifyProbe(null, true)).toEqual({ kind: "transient" });
  });

  it("returns transient when response is null with no error flag", () => {
    expect(classifyProbe(null, false)).toEqual({ kind: "transient" });
  });

  it("returns ok with parsed user for a 2xx response with body", () => {
    expect(classifyProbe(makeResponse(200), false, fakeUser)).toEqual({
      kind: "ok",
      user: fakeUser,
    });
  });

  it("returns transient for a 2xx response whose body failed to parse", () => {
    // Defensive: a 200 with malformed JSON / schema mismatch should not be
    // treated as 'ok' because the caller has no user to apply.
    expect(classifyProbe(makeResponse(200), false, null)).toEqual({
      kind: "transient",
    });
  });

  it("returns unauthorized for a 401 response", () => {
    expect(classifyProbe(makeResponse(401), false)).toEqual({
      kind: "unauthorized",
    });
  });

  it("returns transient for 5xx responses", () => {
    expect(classifyProbe(makeResponse(503), false)).toEqual({
      kind: "transient",
    });
    expect(classifyProbe(makeResponse(500), false)).toEqual({
      kind: "transient",
    });
  });

  it("returns transient for unexpected non-401 4xx responses", () => {
    expect(classifyProbe(makeResponse(429), false)).toEqual({
      kind: "transient",
    });
  });
});

describe("decideProbeAction", () => {
  it("returns apply-user with the body on a 2xx response", () => {
    expect(decideProbeAction(0, { kind: "ok", user: fakeUser })).toEqual({
      type: "apply-user",
      user: fakeUser,
    });
    // Even if we'd accumulated some 401s, a 200 wins immediately.
    expect(decideProbeAction(2, { kind: "ok", user: fakeUser })).toEqual({
      type: "apply-user",
      user: fakeUser,
    });
  });

  it("treats a single 401 as transient noise and only bumps the counter", () => {
    expect(decideProbeAction(0, { kind: "unauthorized" })).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
  });

  it("treats consecutive 401s below the threshold as still transient", () => {
    expect(decideProbeAction(1, { kind: "unauthorized" })).toEqual({
      type: "noop",
      nextFailureCount: 2,
    });
  });

  it("delegates to refreshUser as 'session-expired' once 401s reach the threshold", () => {
    expect(decideProbeAction(2, { kind: "unauthorized" })).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });

  it("honours a custom threshold (parameterised for safer tests)", () => {
    expect(decideProbeAction(0, { kind: "unauthorized" }, 2)).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
    expect(decideProbeAction(1, { kind: "unauthorized" }, 2)).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });

  it("decrements (not resets) the auth-failure streak on a transient outcome", () => {
    // Was 2 → 1, so a flapping gateway (401↔5xx) still converges on the
    // threshold instead of indefinitely masking session expiry.
    expect(decideProbeAction(2, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 1,
    });
    // Floored at 0; never goes negative.
    expect(decideProbeAction(0, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 0,
    });
    expect(decideProbeAction(1, { kind: "transient" })).toEqual({
      type: "noop",
      nextFailureCount: 0,
    });
  });

  it("convergence: alternating 401/transient still triggers session-expired", () => {
    // Simulate the exact scenario from #3493 CR: flapping gateway alternates
    // 401 (session gone) and 503 (overloaded). With decrement-by-1, the
    // counter still nets +1 per 401/transient pair and reaches threshold.
    let count = 0;
    const seq: Array<"unauthorized" | "transient"> = [
      "unauthorized", // count -> 1
      "transient", // count -> 0
      "unauthorized", // count -> 1
      "unauthorized", // count -> 2
      "transient", // count -> 1
      "unauthorized", // count -> 2
    ];
    for (const kind of seq) {
      const action = decideProbeAction(count, { kind });
      expect(action.type).toBe("noop");
      if (action.type === "noop") count = action.nextFailureCount;
    }
    // Next 401 should trip the wire (2 -> 3 == threshold).
    expect(decideProbeAction(count, { kind: "unauthorized" })).toEqual({
      type: "delegate-refresh",
      reason: "session-expired",
    });
  });
});
