import { beforeEach, describe, expect, it, rs } from "@rstest/core";

const localeMocks = rs.hoisted(() => ({
  detectLocale: rs.fn(),
  getLocaleFromCookie: rs.fn(),
}));

rs.mock("@/core/i18n", () => ({
  detectLocale: localeMocks.detectLocale,
}));

rs.mock("@/core/i18n/cookies", () => ({
  getLocaleFromCookie: localeMocks.getLocaleFromCookie,
}));

import { formatDate } from "@/core/utils/datetime";

const DATE = new Date(2026, 7, 25, 12, 0, 0);

describe("formatDate", () => {
  beforeEach(() => {
    localeMocks.detectLocale.mockReset();
    localeMocks.getLocaleFromCookie.mockReset();
    localeMocks.detectLocale.mockReturnValue("en-US");
    localeMocks.getLocaleFromCookie.mockReturnValue(null);
  });

  it("formats a valid date with the requested English locale", () => {
    expect(formatDate(DATE, "PP", "en-US")).toBe("Aug 25, 2026");
  });

  it("returns a neutral placeholder for an invalid timestamp", () => {
    expect(formatDate("not-a-date", "PP", "en-US")).toBe("-");
  });

  it("formats a valid date with the requested Chinese locale", () => {
    expect(formatDate(DATE, "PP", "zh-CN")).toBe("2026-08-25");
  });

  it("prefers the app locale cookie over browser detection", () => {
    localeMocks.getLocaleFromCookie.mockReturnValue("zh-CN");

    expect(formatDate(DATE)).toBe("2026-08-25");
    expect(localeMocks.detectLocale).not.toHaveBeenCalled();
  });

  it("uses locale detection when the app cookie is absent", () => {
    localeMocks.detectLocale.mockReturnValue("zh-CN");

    expect(formatDate(DATE)).toBe("2026-08-25");
    expect(localeMocks.detectLocale).toHaveBeenCalledTimes(1);
  });
});
