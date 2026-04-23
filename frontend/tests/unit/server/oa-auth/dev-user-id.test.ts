import { expect, test } from "vitest";

import { devUserIdFromEmail } from "@/server/oa-auth/dev-user-id";

test("devUserIdFromEmail is stable for the same email", () => {
  const a = devUserIdFromEmail("dev@example.com");
  const b = devUserIdFromEmail("dev@example.com");
  expect(a).toBe(b);
  expect(a).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-3[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  );
});

test("devUserIdFromEmail normalizes case", () => {
  expect(devUserIdFromEmail("Dev@Example.COM")).toBe(devUserIdFromEmail("dev@example.com"));
});

test("devUserIdFromEmail differs across emails", () => {
  expect(devUserIdFromEmail("a@b.co")).not.toBe(devUserIdFromEmail("c@d.co"));
});
