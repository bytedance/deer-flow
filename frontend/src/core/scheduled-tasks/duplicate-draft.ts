import type { ScheduledTask } from "./types";

export const DUPLICATE_DRAFT_VERSION = 1;
export const DUPLICATE_DRAFT_PREFIX = "deerflow:scheduled-task-duplicate:v1";

export type DuplicateDraft = {
  title: string;
  prompt: string;
  context_mode: "fresh_thread_per_run" | "reuse_thread";
  thread_id: string | null;
  schedule_type: "once" | "cron";
  schedule_spec: Record<string, unknown>;
  timezone: string;
};

export type DuplicateDraftStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem"
>;

export function getSessionDuplicateDraftStorage(): DuplicateDraftStorage | null {
  try {
    if (typeof window === "undefined") {
      return null;
    }
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function buildDuplicateDraftKey(taskId: string) {
  return `${DUPLICATE_DRAFT_PREFIX}:${encodeURIComponent(taskId)}`;
}

export function resolveCreateContextMode({
  contextModeParam,
  threadIdParam,
}: {
  contextModeParam: string | null;
  threadIdParam: string | null;
}): "fresh_thread_per_run" | "reuse_thread" {
  if (
    contextModeParam === "reuse_thread" ||
    contextModeParam === "fresh_thread_per_run"
  ) {
    return contextModeParam;
  }
  return threadIdParam ? "reuse_thread" : "fresh_thread_per_run";
}

export function draftFromScheduledTask(
  task: ScheduledTask,
  titleSuffix: string,
): DuplicateDraft {
  return {
    title: `${task.title}${titleSuffix}`,
    prompt: task.prompt,
    context_mode: task.context_mode,
    thread_id: task.thread_id,
    schedule_type: task.schedule_type,
    schedule_spec: task.schedule_spec,
    timezone: task.timezone,
  };
}

export function readDuplicateDraft(
  storage: DuplicateDraftStorage | null | undefined,
  taskId: string,
): DuplicateDraft | null {
  try {
    if (!storage) {
      return null;
    }
    const raw = storage.getItem(buildDuplicateDraftKey(taskId));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as {
      version?: unknown;
      title?: unknown;
      prompt?: unknown;
      context_mode?: unknown;
      thread_id?: unknown;
      schedule_type?: unknown;
      schedule_spec?: unknown;
      timezone?: unknown;
    };
    if (
      parsed.version !== DUPLICATE_DRAFT_VERSION ||
      typeof parsed.title !== "string" ||
      typeof parsed.prompt !== "string" ||
      (parsed.context_mode !== "fresh_thread_per_run" &&
        parsed.context_mode !== "reuse_thread") ||
      !(parsed.thread_id === null || typeof parsed.thread_id === "string") ||
      (parsed.schedule_type !== "once" && parsed.schedule_type !== "cron") ||
      typeof parsed.schedule_spec !== "object" ||
      parsed.schedule_spec === null ||
      typeof parsed.timezone !== "string"
    ) {
      return null;
    }
    return {
      title: parsed.title,
      prompt: parsed.prompt,
      context_mode: parsed.context_mode,
      thread_id: parsed.thread_id,
      schedule_type: parsed.schedule_type,
      schedule_spec: parsed.schedule_spec as Record<string, unknown>,
      timezone: parsed.timezone,
    };
  } catch {
    return null;
  }
}

export function writeDuplicateDraft(
  storage: DuplicateDraftStorage | null | undefined,
  taskId: string,
  draft: DuplicateDraft,
) {
  try {
    if (!storage) {
      return;
    }
    storage.setItem(
      buildDuplicateDraftKey(taskId),
      JSON.stringify({ version: DUPLICATE_DRAFT_VERSION, ...draft }),
    );
  } catch {
    // Ignore quota / private-mode failures; the create page can still load
    // the source task from the scheduled-tasks list.
  }
}

export function clearDuplicateDraft(
  storage: DuplicateDraftStorage | null | undefined,
  taskId: string,
) {
  try {
    storage?.removeItem(buildDuplicateDraftKey(taskId));
  } catch {
    // Ignore storage failures.
  }
}
