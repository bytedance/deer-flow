import { describe, expect, it } from "vitest";

import {
  OFFLINE_BANNER_RETRY_INTERVAL_MS,
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
