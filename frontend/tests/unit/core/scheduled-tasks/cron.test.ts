import { describe, expect, test } from "@rstest/core";

import {
  buildOnceRunAtLocal,
  parseCron,
  serializeCron,
  utcToZonedLocalInput,
  zonedLocalToUtcIso,
  type CronParts,
} from "@/core/scheduled-tasks/cron";

describe("serializeCron", () => {
  test("hourly emits minute + star fields", () => {
    expect(serializeCron("hourly", { minute: 30 } as CronParts)).toBe(
      "30 * * * *",
    );
  });

  test("daily emits minute + hour", () => {
    expect(serializeCron("daily", { minute: 0, hour: 9 } as CronParts)).toBe(
      "0 9 * * *",
    );
  });

  test("weekly emits comma-joined weekday numbers in cron order (0=sun)", () => {
    expect(
      serializeCron("weekly", {
        minute: 0,
        hour: 9,
        weekdays: ["mon", "wed"],
      } as CronParts),
    ).toBe("0 9 * * 1,3");
  });

  test("weekly sorts + dedupes out-of-order / duplicate weekdays", () => {
    expect(
      serializeCron("weekly", {
        minute: 0,
        hour: 9,
        weekdays: ["wed", "mon", "wed"],
      } as CronParts),
    ).toBe("0 9 * * 1,3");
  });

  test("weekly maps sunday to 0", () => {
    expect(
      serializeCron("weekly", {
        minute: 0,
        hour: 9,
        weekdays: ["sun"],
      } as CronParts),
    ).toBe("0 9 * * 0");
  });

  test("monthly emits day-of-month", () => {
    expect(
      serializeCron("monthly", {
        minute: 0,
        hour: 9,
        dayOfMonth: 1,
      } as CronParts),
    ).toBe("0 9 1 * *");
  });

  test("custom returns raw expression", () => {
    expect(serializeCron("custom", { raw: "*/5 * * * *" } as CronParts)).toBe(
      "*/5 * * * *",
    );
  });

  test("clamps out-of-range minute / hour / day-of-month", () => {
    expect(serializeCron("daily", { minute: 99, hour: 24 } as CronParts)).toBe(
      "59 23 * * *",
    );
    expect(
      serializeCron("monthly", {
        minute: 0,
        hour: 9,
        dayOfMonth: 32,
      } as CronParts),
    ).toBe("0 9 31 * *");
    expect(
      serializeCron("monthly", {
        minute: 0,
        hour: 9,
        dayOfMonth: 0,
      } as CronParts),
    ).toBe("0 9 1 * *");
  });
});

describe("parseCron", () => {
  test("hourly: M * * * *", () => {
    expect(parseCron("30 * * * *").preset).toBe("hourly");
    expect(parseCron("30 * * * *").parts.minute).toBe(30);
  });

  test("daily: M H * * *", () => {
    const r = parseCron("0 9 * * *");
    expect(r.preset).toBe("daily");
    expect(r.parts).toMatchObject({ minute: 0, hour: 9 });
  });

  test("weekly: M H * * DOW", () => {
    const r = parseCron("0 9 * * 1,3");
    expect(r.preset).toBe("weekly");
    expect(r.parts.weekdays).toEqual(["mon", "wed"]);
  });

  test("weekly maps 0 and 7 to sunday", () => {
    expect(parseCron("0 9 * * 0").parts.weekdays).toEqual(["sun"]);
    expect(parseCron("0 9 * * 7").parts.weekdays).toEqual(["sun"]);
  });

  test("monthly: M H DOM * *", () => {
    const r = parseCron("0 9 1 * *");
    expect(r.preset).toBe("monthly");
    expect(r.parts.dayOfMonth).toBe(1);
  });

  test("non-canonical forms fall back to custom", () => {
    expect(parseCron("*/5 * * * *").preset).toBe("custom");
    expect(parseCron("0 9,10 * * *").preset).toBe("custom");
    expect(parseCron("0 9 * * 1-5").preset).toBe("custom");
    expect(parseCron("garbage").preset).toBe("custom");
    expect(parseCron("garbage").parts.raw).toBe("garbage");
  });
});

describe("buildOnceRunAtLocal", () => {
  test("valid date + time", () => {
    expect(buildOnceRunAtLocal("2026", "2", "28", "09:00")).toBe(
      "2026-02-28T09:00",
    );
  });

  test("leap year Feb 29 is valid", () => {
    expect(buildOnceRunAtLocal("2024", "2", "29", "09:00")).toBe(
      "2024-02-29T09:00",
    );
  });

  test("rejects Feb 30 via rollover", () => {
    expect(buildOnceRunAtLocal("2026", "2", "30", "09:00")).toBe("");
  });

  test("rejects Feb 29 in a non-leap year", () => {
    expect(buildOnceRunAtLocal("2026", "2", "29", "09:00")).toBe("");
  });

  test("rejects month 0 and month 13", () => {
    expect(buildOnceRunAtLocal("2026", "0", "15", "09:00")).toBe("");
    expect(buildOnceRunAtLocal("2026", "13", "15", "09:00")).toBe("");
  });

  test("rejects empty time", () => {
    expect(buildOnceRunAtLocal("2026", "2", "28", "")).toBe("");
  });

  test("rejects pre-1970 year", () => {
    expect(buildOnceRunAtLocal("1969", "1", "1", "09:00")).toBe("");
  });

  test("round-trips with zonedLocalToUtcIso", () => {
    const local = buildOnceRunAtLocal("2026", "7", "2", "09:00");
    expect(zonedLocalToUtcIso(local, "Asia/Shanghai")).toBe(
      "2026-07-02T01:00:00+00:00",
    );
  });
});

describe("zonedLocalToUtcIso", () => {
  test("Asia/Shanghai is UTC-8 (wall 09:00 -> 01:00Z)", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "Asia/Shanghai")).toBe(
      "2026-07-02T01:00:00+00:00",
    );
  });

  test("UTC passes through", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "UTC")).toBe(
      "2026-07-02T09:00:00+00:00",
    );
  });

  test("America/New_York July is EDT (-04:00)", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "America/New_York")).toBe(
      "2026-07-02T13:00:00+00:00",
    );
  });

  test("America/New_York January is EST (-05:00) — DST season flip", () => {
    expect(zonedLocalToUtcIso("2026-01-15T09:00", "America/New_York")).toBe(
      "2026-01-15T14:00:00+00:00",
    );
  });

  test("Asia/Kolkata half-hour offset UTC+5:30", () => {
    expect(zonedLocalToUtcIso("2026-07-02T09:00", "Asia/Kolkata")).toBe(
      "2026-07-02T03:30:00+00:00",
    );
  });
});

describe("utcToZonedLocalInput", () => {
  test("Shanghai +8: 01:00Z -> 09:00 wall", () => {
    expect(
      utcToZonedLocalInput("2026-07-02T01:00:00+00:00", "Asia/Shanghai"),
    ).toBe("2026-07-02T09:00");
  });

  test("New_York EDT: 13:00Z -> 09:00 wall", () => {
    expect(
      utcToZonedLocalInput("2026-07-02T13:00:00+00:00", "America/New_York"),
    ).toBe("2026-07-02T09:00");
  });

  test("invalid -> empty string", () => {
    expect(utcToZonedLocalInput("not-a-date", "UTC")).toBe("");
  });

  test("round-trips with zonedLocalToUtcIso", () => {
    const iso = zonedLocalToUtcIso("2026-07-02T09:00", "Asia/Shanghai");
    expect(utcToZonedLocalInput(iso, "Asia/Shanghai")).toBe("2026-07-02T09:00");
  });
});

describe("zonedLocalToUtcIso DST transitions", () => {
  // US spring-forward 2026: clocks jump 02:00 -> 03:00 EST->EDT on 2026-03-08.
  test("New_York wall time after spring-forward uses the post-transition offset", () => {
    // 03:30 EDT (-4) is 07:30Z; the stale pre-transition offset (-5) would say 08:30Z.
    expect(zonedLocalToUtcIso("2026-03-08T03:30", "America/New_York")).toBe(
      "2026-03-08T07:30:00+00:00",
    );
  });

  test("New_York wall time before spring-forward keeps the EST offset", () => {
    expect(zonedLocalToUtcIso("2026-03-08T01:30", "America/New_York")).toBe(
      "2026-03-08T06:30:00+00:00",
    );
  });

  // US fall-back 2026: clocks repeat 01:00-02:00 EDT->EST on 2026-11-01.
  test("New_York ambiguous fall-back wall time resolves deterministically", () => {
    expect(zonedLocalToUtcIso("2026-11-01T01:30", "America/New_York")).toBe(
      "2026-11-01T05:30:00+00:00",
    );
  });

  test("create -> edit round-trip survives spring-forward", () => {
    const iso = zonedLocalToUtcIso("2026-03-08T03:30", "America/New_York");
    expect(utcToZonedLocalInput(iso, "America/New_York")).toBe(
      "2026-03-08T03:30",
    );
  });

  test("no-DST timezone is unaffected", () => {
    expect(zonedLocalToUtcIso("2026-03-08T03:30", "Asia/Shanghai")).toBe(
      "2026-03-07T19:30:00+00:00",
    );
  });
});
