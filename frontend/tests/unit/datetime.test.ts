import { describe, expect, test, vi } from "vitest";

vi.mock("@/core/i18n", () => ({
  detectLocale: () => "en-US",
}));

vi.mock("@/core/i18n/cookies", () => ({
  getLocaleFromCookie: () => null,
}));

import { normalizeApiDate } from "@/core/utils/datetime";

describe("normalizeApiDate", () => {
  test("treats timezone-less API timestamps as UTC", () => {
    const normalized = normalizeApiDate("2026-05-20T06:12:31.333753");

    expect(normalized).toBeInstanceOf(Date);
    expect((normalized as Date).toISOString()).toBe("2026-05-20T06:12:31.333Z");
  });

  test("preserves timezone-aware strings", () => {
    const timestamp = "2026-05-20T06:12:31.333753Z";

    expect(normalizeApiDate(timestamp)).toBe(timestamp);
  });

  test("preserves non-string date inputs", () => {
    const date = new Date("2026-05-20T06:12:31.333Z");

    expect(normalizeApiDate(date)).toBe(date);
    expect(normalizeApiDate(1779257551333)).toBe(1779257551333);
  });
});
