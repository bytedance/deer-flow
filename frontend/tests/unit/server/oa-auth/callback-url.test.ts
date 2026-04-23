import { expect, test } from "vitest";

import {
  isLegacyApiAuthCallbackPathname,
  normalizeOAuthCallbackUrl,
} from "@/server/oa-auth/callback-url";

test("normalizeOAuthCallbackUrl trims and strips trailing slash and hash", () => {
  expect(
    normalizeOAuthCallbackUrl("  https://oauth.example.com/user/oa-auth/callback/  "),
  ).toBe("https://oauth.example.com/user/oa-auth/callback");
  expect(
    normalizeOAuthCallbackUrl("https://oauth.example.com/user/oa-auth/callback#frag"),
  ).toBe("https://oauth.example.com/user/oa-auth/callback");
});

test("isLegacyApiAuthCallbackPathname detects legacy backend callback", () => {
  expect(isLegacyApiAuthCallbackPathname("/api/auth/callback")).toBe(true);
  expect(isLegacyApiAuthCallbackPathname("/user/oa-auth/callback")).toBe(false);
});
