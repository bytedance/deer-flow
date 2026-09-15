import { describe, expect, test } from "@rstest/core";

import { validZonedLocalToUtcIso } from "@/core/scheduled-tasks/cron";

describe("one-time local time validation", () => {
  test.each([
    ["America/New_York", "2027-03-14T02:30"],
    ["Australia/Lord_Howe", "2027-10-03T02:15"],
    ["Pacific/Apia", "2011-12-30T12:00"],
    ["UTC", "2027-02-30T12:00"],
    ["Invalid/Timezone", "2027-06-01T12:00"],
    ["UTC", ""],
  ])("rejects %s %s without throwing", (timezone, local) => {
    expect(validZonedLocalToUtcIso(local, timezone)).toBeNull();
  });

  test.each([
    ["America/New_York", "2027-03-14T01:30", "2027-03-14T06:30:00+00:00"],
    ["America/New_York", "2027-03-14T03:30", "2027-03-14T07:30:00+00:00"],
    ["America/New_York", "2026-11-01T01:30", "2026-11-01T05:30:00+00:00"],
    ["Australia/Lord_Howe", "2027-10-03T01:45", "2027-10-02T15:15:00+00:00"],
    ["Australia/Lord_Howe", "2027-10-03T02:45", "2027-10-02T15:45:00+00:00"],
    ["Asia/Shanghai", "2027-03-14T02:30", "2027-03-13T18:30:00+00:00"],
    ["UTC", "2027-01-01T00:00", "2027-01-01T00:00:00+00:00"],
  ])("accepts %s %s", (timezone, local, expected) => {
    expect(validZonedLocalToUtcIso(local, timezone)).toBe(expected);
  });
});
