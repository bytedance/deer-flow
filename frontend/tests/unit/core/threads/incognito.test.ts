import { describe, expect, test } from "@rstest/core";

import { incognitoLifetimeParts } from "@/core/threads/incognito";

describe("incognitoLifetimeParts", () => {
  test("renders the default day-sized idle window as whole days", () => {
    expect(incognitoLifetimeParts(24 * 60 * 60)).toEqual({
      count: 1,
      unit: "days",
    });
    expect(incognitoLifetimeParts(7 * 24 * 60 * 60)).toEqual({
      count: 7,
      unit: "days",
    });
  });

  test("uses hours when the window is shorter than a day", () => {
    expect(incognitoLifetimeParts(60 * 60)).toEqual({
      count: 1,
      unit: "hours",
    });
    // 90 minutes rounds to the nearest whole hour.
    expect(incognitoLifetimeParts(90 * 60)).toEqual({
      count: 2,
      unit: "hours",
    });
  });

  test("falls back to minutes and never reports zero", () => {
    expect(incognitoLifetimeParts(60)).toEqual({ count: 1, unit: "minutes" });
    expect(incognitoLifetimeParts(90)).toEqual({ count: 2, unit: "minutes" });
    // The config schema enforces at least 60s; a stray small value still
    // must not render "0 minutes".
    expect(incognitoLifetimeParts(1)).toEqual({ count: 1, unit: "minutes" });
  });
});
