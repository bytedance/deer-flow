import { expect, test } from "vitest";

import { sanitizePostLoginPath } from "@/server/oa-auth/redirect-path";

test("sanitizePostLoginPath keeps safe relative paths", () => {
  expect(sanitizePostLoginPath("/workspace/chats/1")).toBe("/workspace/chats/1");
});

test("sanitizePostLoginPath rejects open redirects", () => {
  expect(sanitizePostLoginPath("//evil.com")).toBe("/workspace");
  expect(sanitizePostLoginPath("https://evil.com")).toBe("/workspace");
  expect(sanitizePostLoginPath("")).toBe("/workspace");
});
