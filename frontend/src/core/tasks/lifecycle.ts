import { normalizeTokenUsage } from "../messages/usage";

import { externalUsage, readTaskIdentity, subtaskKey } from "./identity";
import type { Subtask } from "./types";

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

  const identity = readTaskIdentity(event);
  const base = {
    id: subtaskKey(taskId, identity.dispatchId),
    ...(identity.dispatchId || identity.executionId
      ? { providerCallId: taskId }
      : {}),
    ...identity,
  };
  const modelName = normalizeModelName(event.model_name);
  const usage = normalizeTokenUsage(event.usage);
  const facts = {
    ...base,
    ...(modelName ? { modelName } : {}),
    ...(usage ? { usage } : {}),
    ...(externalUsage(event.external_usage)
      ? { externalUsage: externalUsage(event.external_usage) }
      : {}),
    ...(typeof event.stop_reason === "string"
      ? { stopReason: event.stop_reason }
      : {}),
  };
  if (event.type === "task_started" || event.type === "task_running")
    return facts;
  if (
    [
      "task_completed",
      "task_failed",
      "task_cancelled",
      "task_timed_out",
    ].includes(String(event.type))
  ) {
    return {
      ...facts,
      status: event.type === "task_completed" ? "completed" : "failed",
      ...(typeof event.result === "string" ? { result: event.result } : {}),
      ...(typeof event.error === "string" ? { error: event.error } : {}),
    };
  }

  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeModelName(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
