import { describe, expect, it } from "@rstest/core";

import { buildScheduledTaskDuplicateDraft } from "@/core/scheduled-tasks/duplicate";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

const BASE_TASK: ScheduledTask = {
  id: "task-1",
  thread_id: null,
  context_mode: "fresh_thread_per_run",
  title: "Daily summary",
  prompt: "Summarize the workspace",
  schedule_type: "cron",
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "Asia/Shanghai",
  status: "enabled",
  next_run_at: null,
  last_run_at: null,
  last_run_id: null,
  last_thread_id: null,
  last_error: null,
  run_count: 0,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("buildScheduledTaskDuplicateDraft", () => {
  it("copies a cron task into an independent create draft", () => {
    const draft = buildScheduledTaskDuplicateDraft(
      BASE_TASK,
      " (Copy)",
      new Date("2026-08-27T00:00:00Z"),
    );

    expect(draft).toEqual({
      title: "Daily summary (Copy)",
      prompt: "Summarize the workspace",
      contextMode: "fresh_thread_per_run",
      targetThreadId: "",
      schedule: {
        schedule_type: "cron",
        schedule_spec: { cron: "0 9 * * *" },
        timezone: "Asia/Shanghai",
      },
    });

    draft.schedule.schedule_spec.cron = "0 10 * * *";
    expect(BASE_TASK.schedule_spec).toEqual({ cron: "0 9 * * *" });
  });

  it("keeps a future one-time timestamp and reuse-thread identity", () => {
    const task: ScheduledTask = {
      ...BASE_TASK,
      thread_id: "thread-1",
      context_mode: "reuse_thread",
      schedule_type: "once",
      schedule_spec: { run_at: "2026-08-28T09:00:00Z" },
    };

    const draft = buildScheduledTaskDuplicateDraft(
      task,
      "（副本）",
      new Date("2026-08-27T00:00:00Z"),
    );

    expect(draft.title).toBe("Daily summary（副本）");
    expect(draft.targetThreadId).toBe("thread-1");
    expect(draft.schedule.schedule_spec).toEqual({
      run_at: "2026-08-28T09:00:00Z",
    });
  });

  it.each(["2026-08-26T09:00:00Z", "invalid", undefined])(
    "clears an unusable one-time timestamp: %s",
    (runAt) => {
      const task: ScheduledTask = {
        ...BASE_TASK,
        schedule_type: "once",
        schedule_spec: runAt ? { run_at: runAt } : {},
      };

      const draft = buildScheduledTaskDuplicateDraft(
        task,
        " (Copy)",
        new Date("2026-08-27T00:00:00Z"),
      );

      expect(draft.schedule.schedule_spec).toEqual({});
    },
  );
});
