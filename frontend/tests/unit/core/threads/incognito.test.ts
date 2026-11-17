import { describe, expect, test } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import {
  incognitoLifetimeLabel,
  incognitoLifetimeParts,
} from "@/core/threads/incognito";

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe("incognitoLifetimeParts", () => {
  test("keeps windows up to 72 hours in hours", () => {
    expect(incognitoLifetimeParts(HOUR)).toEqual({
      count: 1,
      unit: "hours",
      remainderHours: 0,
      approximate: false,
    });
    expect(incognitoLifetimeParts(2 * DAY)).toEqual({
      count: 48,
      unit: "hours",
      remainderHours: 0,
      approximate: false,
    });
    expect(incognitoLifetimeParts(72 * HOUR)).toEqual({
      count: 72,
      unit: "hours",
      remainderHours: 0,
      approximate: false,
    });
  });

  test("switches to days past 72 hours", () => {
    expect(incognitoLifetimeParts(73 * HOUR)).toEqual({
      count: 3,
      unit: "days",
      remainderHours: 1,
      approximate: false,
    });
    expect(incognitoLifetimeParts(7 * DAY)).toEqual({
      count: 7,
      unit: "days",
      remainderHours: 0,
      approximate: false,
    });
    expect(incognitoLifetimeParts(4 * DAY + 4 * HOUR)).toEqual({
      count: 4,
      unit: "days",
      remainderHours: 4,
      approximate: false,
    });
  });

  test("marks a window the units cannot spell exactly", () => {
    expect(incognitoLifetimeParts(90)).toEqual({
      count: 2,
      unit: "minutes",
      remainderHours: 0,
      approximate: true,
    });
    expect(incognitoLifetimeParts(90 * MINUTE)).toEqual({
      count: 2,
      unit: "hours",
      remainderHours: 0,
      approximate: true,
    });
    expect(incognitoLifetimeParts(73 * HOUR + 30 * MINUTE)).toEqual({
      count: 3,
      unit: "days",
      remainderHours: 2,
      approximate: true,
    });
    expect(incognitoLifetimeParts(4 * DAY + MINUTE)).toEqual({
      count: 4,
      unit: "days",
      remainderHours: 0,
      approximate: true,
    });
  });

  test("picks the unit from the rounded value", () => {
    // 71.5 hours rounds to 72, the last hour-counted window.
    expect(incognitoLifetimeParts(71.5 * HOUR)).toEqual({
      count: 72,
      unit: "hours",
      remainderHours: 0,
      approximate: true,
    });
    // 72.5 hours rounds to 73, which reads as three days and one hour.
    expect(incognitoLifetimeParts(72.5 * HOUR)).toEqual({
      count: 3,
      unit: "days",
      remainderHours: 1,
      approximate: true,
    });
    // 59.5 minutes rounds up to an hour instead of showing 60 minutes.
    expect(incognitoLifetimeParts(59.5 * MINUTE)).toEqual({
      count: 1,
      unit: "hours",
      remainderHours: 0,
      approximate: true,
    });
  });

  test("falls back to minutes and never reports zero", () => {
    expect(incognitoLifetimeParts(MINUTE)).toEqual({
      count: 1,
      unit: "minutes",
      remainderHours: 0,
      approximate: false,
    });
    // The config schema enforces at least 60s; a stray small value still
    // must not render "0 minutes".
    expect(incognitoLifetimeParts(1)).toEqual({
      count: 1,
      unit: "minutes",
      remainderHours: 0,
      approximate: true,
    });
    expect(incognitoLifetimeParts(-5)).toEqual({
      count: 1,
      unit: "minutes",
      remainderHours: 0,
      approximate: false,
    });
  });
});

describe("incognitoLifetimeLabel", () => {
  test("spells exact windows without the approximate marker", () => {
    expect(
      incognitoLifetimeLabel(incognitoLifetimeParts(DAY), enUS.incognito),
    ).toBe("24 hours");
    expect(
      incognitoLifetimeLabel(incognitoLifetimeParts(73 * HOUR), enUS.incognito),
    ).toBe("3 days and 1 hour");
    expect(
      incognitoLifetimeLabel(incognitoLifetimeParts(7 * DAY), enUS.incognito),
    ).toBe("7 days");
  });

  test("marks what the display rounds", () => {
    expect(
      incognitoLifetimeLabel(
        incognitoLifetimeParts(73 * HOUR + 30 * MINUTE),
        enUS.incognito,
      ),
    ).toBe("about 3 days and 2 hours");
    expect(
      incognitoLifetimeLabel(incognitoLifetimeParts(90), enUS.incognito),
    ).toBe("about 2 minutes");
  });
});
