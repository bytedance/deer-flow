import { describe, expect, test } from "@rstest/core";

import { isValidEmail } from "@/core/auth/email";

// The backend identity schema deliberately accepts addresses stricter
// validators reject (`emailSchema` in @/core/auth/types is a bare
// `z.string().min(1)`). The auth forms used to hand the decision to the
// browser's `type="email"` constraint instead, which rejects any non-ASCII
// local part before the submit handler runs — an account like
// `用户@example.com` (creatable via the API, an admin, or OIDC) could never
// sign in through the password form (#7488).
describe("auth email validation", () => {
  test("accepts addresses the backend accepts, including non-ASCII local parts", () => {
    expect(isValidEmail("用户@example.com")).toBe(true);
    expect(isValidEmail("wíérd@name.example")).toBe(true);
    expect(isValidEmail("someone@example.com")).toBe(true);
    expect(isValidEmail("a@b")).toBe(true);
  });

  test("accepts surrounding whitespace (trimmed before the check)", () => {
    expect(isValidEmail("  user@example.com  ")).toBe(true);
  });

  test("rejects values without a usable local@domain shape", () => {
    expect(isValidEmail("not-an-email")).toBe(false);
    expect(isValidEmail("@example.com")).toBe(false);
    expect(isValidEmail("user@")).toBe(false);
    expect(isValidEmail("a@b@c.example")).toBe(false);
    expect(isValidEmail("a b@example.com")).toBe(false);
  });

  test("rejects empty and blank input", () => {
    expect(isValidEmail("")).toBe(false);
    expect(isValidEmail("   ")).toBe(false);
  });
});
