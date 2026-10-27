import { describe, expect, it } from "@rstest/core";

import { buildSchedule } from "@/core/enterprise/api";

describe("enterprise schedules", () => {
  it("keeps Beijing wall-clock time independent of the browser timezone", () => {
    expect(buildSchedule("once", "2026-12-01T09:00")).toEqual({
      schedule_type: "once",
      schedule_spec: { run_at: "2026-12-01T09:00" },
      timezone: "Asia/Shanghai",
    });
  });
  it("represents a weekday schedule with the existing five-field cron format", () => {
    expect(buildSchedule("weekdays", "")).toEqual({
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * 1-5" },
      timezone: "Asia/Shanghai",
    });
  });
});
