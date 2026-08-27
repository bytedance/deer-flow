import type { ScheduledTask } from "./types";

export type ScheduledTaskDuplicateDraft = {
  title: string;
  prompt: string;
  contextMode: ScheduledTask["context_mode"];
  targetThreadId: string;
  schedule: {
    schedule_type: ScheduledTask["schedule_type"];
    schedule_spec: { cron?: string; run_at?: string };
    timezone: string;
  };
};

export function buildScheduledTaskDuplicateDraft(
  task: ScheduledTask,
  titleSuffix: string,
  now = new Date(),
): ScheduledTaskDuplicateDraft {
  const cron = task.schedule_spec.cron;
  const runAt = task.schedule_spec.run_at;
  const parsedRunAt = typeof runAt === "string" ? Date.parse(runAt) : NaN;
  const scheduleSpec =
    task.schedule_type === "cron"
      ? typeof cron === "string"
        ? { cron }
        : {}
      : Number.isFinite(parsedRunAt) && parsedRunAt > now.getTime()
        ? { run_at: runAt as string }
        : {};

  return {
    title: `${task.title}${titleSuffix}`,
    prompt: task.prompt,
    contextMode: task.context_mode,
    targetThreadId:
      task.context_mode === "reuse_thread" ? (task.thread_id ?? "") : "",
    schedule: {
      schedule_type: task.schedule_type,
      schedule_spec: scheduleSpec,
      timezone: task.timezone || "UTC",
    },
  };
}
