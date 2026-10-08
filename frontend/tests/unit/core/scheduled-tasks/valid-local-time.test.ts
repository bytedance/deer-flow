import { describe, expect, test } from "@rstest/core";

import {
  editedZonedLocalToUtcIso,
  validZonedLocalToUtcIso,
} from "@/core/scheduled-tasks/cron";

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

describe("edited local time keeps the stored instant while it is unchanged", () => {
  test.each([
    // The second 01:30 of the New York fall-back (EST), which the wall value
    // alone would read as the first (EDT, 05:30Z).
    ["America/New_York", "2026-11-01T01:30", "2026-11-01T06:30:00Z"],
    // Seconds the minute-precision input cannot show.
    ["UTC", "2099-12-31T10:00", "2099-12-31T10:00:30Z"],
  ])("keeps %s %s as %s", (timezone, local, stored) => {
    expect(editedZonedLocalToUtcIso(local, timezone, stored)).toBe(stored);
  });

  test.each([
    // The wall value changed.
    [
      "America/New_York",
      "2026-11-01T02:30",
      "2026-11-01T06:30:00Z",
      "2026-11-01T07:30:00+00:00",
    ],
    // The zone changed, so the same wall value is another instant.
    [
      "UTC",
      "2026-11-01T01:30",
      "2026-11-01T06:30:00Z",
      "2026-11-01T01:30:00+00:00",
    ],
    // Nothing stored (a new task).
    ["America/New_York", "2026-11-01T01:30", null, "2026-11-01T05:30:00+00:00"],
  ])("reads %s %s (stored %s) as %s", (timezone, local, stored, expected) => {
    expect(editedZonedLocalToUtcIso(local, timezone, stored)).toBe(expected);
  });

  test("a skipped wall time is still rejected", () => {
    expect(
      editedZonedLocalToUtcIso(
        "2027-03-14T02:30",
        "America/New_York",
        "2027-03-14T07:30:00Z",
      ),
    ).toBeNull();
  });
});
