import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  briefReason,
  browserTimeZone,
  displayTimeZone,
  formatTaskDateTime,
  formatTaskTime,
  formatWithViewerTime,
} from "@/core/scheduled-tasks/format";

// 2026-10-06 12:00 in Asia/Shanghai (a Tuesday).
const NOW = new Date("2026-10-06T04:00:00Z");
const en = { locale: "en-US", labels: enUS.scheduledTasks.time, now: NOW };
const zh = { locale: "zh-CN", labels: zhCN.scheduledTasks.time, now: NOW };

describe("formatTaskTime", () => {
  it("reads tomorrow morning in the task's zone", () => {
    expect(
      formatTaskTime("2026-10-07T01:00:00Z", {
        ...en,
        timeZone: "Asia/Shanghai",
      }),
    ).toBe("Tomorrow 09:00");
    expect(
      formatTaskTime("2026-10-07T01:00:00Z", {
        ...zh,
        timeZone: "Asia/Shanghai",
      }),
    ).toBe("明天 09:00");
  });

  it("uses today, yesterday, a weekday within the week, then a date", () => {
    const tz = { timeZone: "Asia/Shanghai" };
    expect(formatTaskTime("2026-10-06T07:30:00Z", { ...en, ...tz })).toBe(
      "Today 15:30",
    );
    expect(formatTaskTime("2026-10-05T01:00:00Z", { ...zh, ...tz })).toBe(
      "昨天 09:00",
    );
    expect(formatTaskTime("2026-10-09T01:00:00Z", { ...en, ...tz })).toBe(
      "Fri 09:00",
    );
    expect(formatTaskTime("2026-10-09T01:00:00Z", { ...zh, ...tz })).toBe(
      "周五 09:00",
    );
    expect(formatTaskTime("2026-10-20T01:00:00Z", { ...en, ...tz })).toBe(
      "Oct 20 09:00",
    );
    expect(formatTaskTime("2026-10-20T01:00:00Z", { ...zh, ...tz })).toBe(
      "10月20日 09:00",
    );
    expect(formatTaskTime("2027-01-02T01:00:00Z", { ...en, ...tz })).toBe(
      "Jan 2, 2027 09:00",
    );
    expect(formatTaskTime("2027-01-02T01:00:00Z", { ...zh, ...tz })).toBe(
      "2027年1月2日 09:00",
    );
  });

  it("decides the day in the given zone, not UTC", () => {
    // 23:30 UTC on the 6th is already the 7th in Shanghai.
    expect(
      formatTaskTime("2026-10-06T23:30:00Z", {
        ...en,
        timeZone: "Asia/Shanghai",
      }),
    ).toBe("Tomorrow 07:30");
    expect(
      formatTaskTime("2026-10-06T23:30:00Z", { ...en, timeZone: "UTC" }),
    ).toBe("Today 23:30");
  });

  it("returns an empty string for an invalid time or zone", () => {
    expect(formatTaskTime("not a time", { ...en, timeZone: "UTC" })).toBe("");
    expect(
      formatTaskTime("2026-10-07T01:00:00Z", { ...en, timeZone: "Mars/Base" }),
    ).toBe("");
  });

  it("never shows an ISO timestamp", () => {
    const text = formatTaskTime("2026-12-31T10:00:00+00:00", {
      ...en,
      timeZone: "Europe/Berlin",
    });
    expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
  });
});

describe("formatTaskDateTime", () => {
  it("always reads as a plain local date, never a relative day or ISO", () => {
    const tz = { timeZone: "Asia/Shanghai", now: NOW };
    expect(
      formatTaskDateTime("2026-10-07T01:00:00Z", { ...tz, locale: "en-US" }),
    ).toBe("Oct 7 09:00");
    expect(
      formatTaskDateTime("2026-10-06T07:30:00Z", { ...tz, locale: "zh-CN" }),
    ).toBe("10月6日 15:30");
    expect(
      formatTaskDateTime("2027-01-02T01:00:00Z", { ...tz, locale: "en-US" }),
    ).toBe("Jan 2, 2027 09:00");
    expect(formatTaskDateTime("bad", { ...tz, locale: "en-US" })).toBe("");
  });
});

describe("formatWithViewerTime", () => {
  it("adds the viewer's time only when the zones differ", () => {
    expect(
      formatWithViewerTime("2026-10-07T01:00:00Z", "Asia/Shanghai", {
        ...en,
        viewerTimeZone: "Asia/Shanghai",
      }),
    ).toBe("Tomorrow 09:00");
    expect(
      formatWithViewerTime("2026-10-07T01:00:00Z", "Asia/Shanghai", {
        ...en,
        viewerTimeZone: "Asia/Singapore",
      }),
    ).toBe("Tomorrow 09:00");
    expect(
      formatWithViewerTime("2026-10-07T07:00:00Z", "Asia/Shanghai", {
        ...en,
        viewerTimeZone: "Europe/Berlin",
      }),
    ).toBe("Tomorrow 15:00 · 09:00 your time");
    expect(
      formatWithViewerTime("2026-10-07T01:00:00Z", "Asia/Shanghai", {
        ...zh,
        viewerTimeZone: "Europe/Berlin",
      }),
    ).toBe("明天 09:00 · 你的时间 03:00");
  });

  it("repeats the day when the viewer's day differs", () => {
    expect(
      formatWithViewerTime("2026-10-06T17:00:00Z", "Asia/Shanghai", {
        ...en,
        viewerTimeZone: "Europe/Berlin",
      }),
    ).toBe("Tomorrow 01:00 · Today 19:00 your time");
  });
});

describe("display zone", () => {
  it("reads the browser zone, falling back to UTC", () => {
    expect(browserTimeZone()).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    );
  });

  afterEach(() => {
    rs.restoreAllMocks();
  });

  function mockViewerTimeZone(timeZone: string) {
    const RealDateTimeFormat = Intl.DateTimeFormat;
    rs.spyOn(Intl, "DateTimeFormat").mockImplementation(((
      ...args: ConstructorParameters<typeof Intl.DateTimeFormat>
    ) => {
      const real = new RealDateTimeFormat(...args);
      return {
        ...real,
        resolvedOptions: () => ({ ...real.resolvedOptions(), timeZone }),
      };
    }) as unknown as typeof Intl.DateTimeFormat);
  }

  it("shows interval tasks in the viewer's zone, never the stored UTC", () => {
    mockViewerTimeZone("Europe/Berlin");
    expect(
      displayTimeZone({ schedule_type: "interval", timezone: "UTC" }),
    ).toBe("Europe/Berlin");
    expect(
      displayTimeZone({ schedule_type: "cron", timezone: "Asia/Shanghai" }),
    ).toBe("Asia/Shanghai");
    expect(
      displayTimeZone({ schedule_type: "once", timezone: "Europe/Berlin" }),
    ).toBe("Europe/Berlin");
  });
});

describe("briefReason", () => {
  it("quotes one sentence without its closing punctuation", () => {
    expect(
      briefReason("清单里还有 3 项没勾（负责人：赵宁）。明天再检查一次。"),
    ).toBe("清单里还有 3 项没勾（负责人：赵宁）");
    expect(briefReason("Two items are still open. I will check again.")).toBe(
      "Two items are still open",
    );
    expect(briefReason("Version 1.2 is not released yet")).toBe(
      "Version 1.2 is not released yet",
    );
  });

  it("caps a long sentence with an ellipsis", () => {
    const reason = briefReason("a".repeat(300));
    expect(reason).toHaveLength(120);
    expect(reason.endsWith("…")).toBe(true);
  });
});
