import { describe, expect, test } from "@rstest/core";

import type { ScheduledTask } from "@/core/scheduled-tasks/types";

describe("scheduled task types", () => {
  test("scheduled task shape supports status and next run", () => {
    const task: ScheduledTask = {
      id: "task-1",
      thread_id: "thread-1",
      context_mode: "reuse_thread",
      title: "Daily summary",
      prompt: "Summarize thread",
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * *" },
      timezone: "UTC",
      status: "enabled",
      next_run_at: "2026-07-02T01:00:00+00:00",
      last_run_at: null,
      last_run_id: null,
      last_thread_id: null,
      last_error: null,
      run_count: 0,
      created_at: "2026-07-01T00:00:00+00:00",
      updated_at: "2026-07-01T00:00:00+00:00",
    };

    expect(task.status).toBe("enabled");
  });
});
