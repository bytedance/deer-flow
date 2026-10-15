import { normalizeTokenUsage } from "../messages/usage";

import type { Subtask } from "./types";

type TaskStartedEvent = {
  type: "task_started";
  task_id: string;
  model_name?: unknown;
};

type TaskRunningEvent = {
  type: "task_running";
  task_id: string;
  model_name?: unknown;
  usage?: unknown;
};

/** Convert an additive task lifecycle event into a task-state update. */
export function taskEventToSubtaskUpdate(
  event: unknown,
): (Partial<Subtask> & { id: string }) | null {
  if (!isRecord(event)) {
    return null;
  }

  const taskId = event.task_id;
  if (typeof taskId !== "string" || !taskId.trim()) {
    return null;
  }

  if (event.type === "task_started") {
    const started = event as TaskStartedEvent;
    const modelName =
      typeof started.model_name === "string" && started.model_name.trim()
        ? started.model_name.trim()
        : undefined;
    return {
      id: taskId,
      ...(modelName ? { modelName } : {}),
    };
  }

  if (event.type === "task_running") {
    const running = event as TaskRunningEvent;
    const usage = normalizeTokenUsage(running.usage);
    const modelName = normalizeModelName(running.model_name);
    return usage || modelName
      ? {
          id: taskId,
          ...(modelName ? { modelName } : {}),
          ...(usage ? { usage } : {}),
        }
      : null;
  }

  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeModelName(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
