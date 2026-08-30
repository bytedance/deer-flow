import { describe, expect, it } from "@rstest/core";

import {
  clearDuplicateDraft,
  draftFromScheduledTask,
  readDuplicateDraft,
  resolveCreateContextMode,
  writeDuplicateDraft,
} from "@/core/scheduled-tasks/duplicate-draft";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
  };
}

const TASK: ScheduledTask = {
  id: "task-1",
  thread_id: "thread-1",
  context_mode: "fresh_thread_per_run",
  title: "Daily summary",
  prompt: "Summarize thread",
  schedule_type: "cron",
  schedule_spec: { cron: "0 9 * * *" },
  timezone: "UTC",
  status: "enabled",
  next_run_at: null,
  last_run_at: null,
  last_run_id: null,
  last_thread_id: null,
  last_error: null,
  run_count: 0,
  created_at: "2026-07-01T00:00:00+00:00",
  updated_at: "2026-07-01T00:00:00+00:00",
};

describe("resolveCreateContextMode", () => {
  it("gives an explicit context_mode precedence over thread_id", () => {
    expect(
      resolveCreateContextMode({
        contextModeParam: "fresh_thread_per_run",
        threadIdParam: "thread-1",
      }),
    ).toBe("fresh_thread_per_run");
    expect(
      resolveCreateContextMode({
        contextModeParam: "reuse_thread",
        threadIdParam: null,
      }),
    ).toBe("reuse_thread");
  });

  it("infers reuse from thread_id only when context_mode is absent", () => {
    expect(
      resolveCreateContextMode({
        contextModeParam: null,
        threadIdParam: "thread-1",
      }),
    ).toBe("reuse_thread");
    expect(
      resolveCreateContextMode({
        contextModeParam: null,
        threadIdParam: null,
      }),
    ).toBe("fresh_thread_per_run");
  });
});

describe("duplicate draft storage", () => {
  it("round-trips a source task without putting the prompt in a URL", () => {
    const storage = memoryStorage();
    const draft = draftFromScheduledTask(TASK, " (Copy)");
    writeDuplicateDraft(storage, TASK.id, draft);
    expect(readDuplicateDraft(storage, TASK.id)).toEqual(draft);
    clearDuplicateDraft(storage, TASK.id);
    expect(readDuplicateDraft(storage, TASK.id)).toBeNull();
  });
});
